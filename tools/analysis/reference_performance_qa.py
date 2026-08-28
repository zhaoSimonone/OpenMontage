"""QA for reference-performance outputs.

The local motion metrics remain useful for movement energy and continuity, but
they cannot infer a blink, gaze target, mouth shape, or facial emotion from
pixels reliably. This adapter therefore combines automated motion/continuity
metrics with an explicit human/vision-model beat review and refuses to mark
expression quality as passed when that review is missing.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from tools.analysis.reference_dance_qa import ReferenceDanceQA
from tools.base_tool import (
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)


PASS_THRESHOLD = 0.70


class ReferencePerformanceQA(ReferenceDanceQA):
    name = "reference_performance_qa"
    version = "0.1.0"
    capability = "analysis"
    provider = "ffmpeg"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL
    tier = ToolTier.ANALYZE
    capabilities = [
        "score_action_order",
        "score_expression_fidelity",
        "score_gaze_and_head_timing",
        "score_motion_energy",
        "score_clip_continuity",
        "review_reference_performance",
    ]
    best_for = [
        "reviewing target-character performance against a motion reference",
        "separating action, gesture, expression, gaze, identity, and continuity findings",
        "blocking false PASS results when expression review was not completed",
    ]
    not_good_for = [
        "automatic face recognition or emotion recognition without a vision review",
        "proving frame-perfect pose transfer",
        "silent provider switching",
    ]
    input_schema = {
        **ReferenceDanceQA.input_schema,
        "properties": {
            **ReferenceDanceQA.input_schema["properties"],
            "performance_analysis": {
                "type": ["object", "string"],
                "description": "Timed reference-performance beat analysis or JSON path.",
            },
            "manual_review": {
                "type": "object",
                "description": "Vision/manual comparison keyed by beat_id.",
            },
            "identity_score": {"type": "number", "minimum": 0, "maximum": 1},
            "camera_score": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }
    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=700, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=0)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        base = ReferenceDanceQA().execute(inputs)
        if not base.success:
            return base

        report = dict(base.data)
        analysis = self._load_object(inputs.get("performance_analysis"))
        manual = inputs.get("manual_review") or {}
        if not isinstance(manual, dict):
            return ToolResult(success=False, error="manual_review must be an object")

        expected_beats = analysis.get("beats") or []
        beat_reviews = manual.get("beats") or manual.get("beat_reviews") or []
        if not isinstance(beat_reviews, list):
            return ToolResult(success=False, error="manual_review.beats must be an array")

        missing_beat_ids = self._missing_beat_ids(expected_beats, beat_reviews)
        incomplete_beat_ids = self._incomplete_beat_ids(expected_beats, beat_reviews)

        action_scores = self._scores(beat_reviews, "action_score")
        gesture_scores = self._scores(beat_reviews, "gesture_score")
        expression_scores = self._scores(beat_reviews, "expression_score")
        gaze_scores = self._scores(beat_reviews, "gaze_score")
        head_scores = self._scores(beat_reviews, "head_angle_score")
        order_score = self._number_or_none(manual.get("action_order_score"))
        expression_score = self._number_or_none(manual.get("expression_score"))
        if expression_score is None:
            expression_score = self._average(expression_scores)
        if order_score is None:
            order_score = self._average(action_scores)

        expression_reviewed = bool(expected_beats) and not missing_beat_ids and not incomplete_beat_ids
        report["performance_analysis"] = {
            "reference_path": analysis.get("reference_video", {}).get("path"),
            "expected_beat_count": len(expected_beats),
            "reviewed_beat_count": len(expected_beats) - len(missing_beat_ids) - len(incomplete_beat_ids),
            "beats": beat_reviews,
            "missing_beat_ids": missing_beat_ids,
            "incomplete_beat_ids": incomplete_beat_ids,
            "action_order_score": order_score,
            "gesture_score": self._average(gesture_scores),
            "expression_score": expression_score,
            "gaze_score": self._average(gaze_scores),
            "head_angle_score": self._average(head_scores),
            "expression_reviewed": expression_reviewed,
            "issues": self._performance_issues(
                order_score=order_score,
                expression_score=expression_score,
                reviewed=expression_reviewed,
                missing=[*missing_beat_ids, *incomplete_beat_ids],
            ),
        }
        report["scores"]["action_order"] = order_score
        report["scores"]["gesture"] = self._average(gesture_scores)
        report["scores"]["expression"] = expression_score
        report["scores"]["gaze"] = self._average(gaze_scores)
        report["scores"]["head_angle"] = self._average(head_scores)
        report["scores"]["identity"] = self._number_or_none(inputs.get("identity_score"))
        report["scores"]["camera"] = self._number_or_none(inputs.get("camera_score"))

        base_decision = report.get("decision")
        performance_scores = [
            order_score,
            self._average(gesture_scores),
            expression_score,
            self._average(gaze_scores),
            self._average(head_scores),
        ]
        if not expression_reviewed:
            report["decision"] = "REVIEW_REQUIRED"
            report["next_action"] = {
                "kind": "manual_performance_review",
                "provider": None,
                "reason": "Action and expression fidelity need beat-level vision review before this candidate can pass.",
                "required_fields": [
                    "action_order_score",
                    "gesture_score",
                    "expression_score",
                    "gaze_score",
                    "head_angle_score",
                    "identity_score",
                ],
            }
        elif any((score or 0.0) < PASS_THRESHOLD for score in performance_scores):
            report["decision"] = "REGENERATE"
            report["next_action"] = {
                "kind": "regenerate_h3",
                "provider": "minimax_h3",
                "reason": "The candidate does not reproduce the analyzed action order or facial performance strongly enough.",
                "focus": report["performance_analysis"]["issues"],
            }
        else:
            report["decision"] = base_decision if base_decision != "REVIEW_REQUIRED" else "PASS"

        report["summary"] = (
            f"Reference-performance review: action order {self._format_score(order_score)}, "
            f"expression {self._format_score(expression_score)}, "
            f"motion {self._format_score(report.get('scores', {}).get('motion'))}, "
            f"continuity {self._format_score(report.get('scores', {}).get('continuity'))}. "
            f"Decision {report['decision']}."
        )
        report.setdefault("metadata", {})["expression_review_required"] = True
        report["metadata"]["manual_review_supplied"] = expression_reviewed

        output_path = Path(report["output_path"])
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return ToolResult(
            success=True,
            data=report,
            artifacts=[str(output_path), *report.get("sample_frame_dirs", [])],
            duration_seconds=round(time.time() - started, 2),
        )

    @staticmethod
    def _load_object(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value:
            path = Path(str(value))
            if not path.is_file():
                raise FileNotFoundError(f"performance_analysis does not exist: {path}")
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("performance_analysis must be an object")
            return data
        return {}

    @staticmethod
    def _number_or_none(value: Any) -> float | None:
        if value is None or value == "":
            return None
        number = float(value)
        if not 0.0 <= number <= 1.0:
            raise ValueError("performance scores must be between 0 and 1")
        return round(number, 6)

    @classmethod
    def _scores(cls, reviews: list[dict[str, Any]], field: str) -> list[float]:
        values: list[float] = []
        for review in reviews:
            if not isinstance(review, dict) or review.get(field) is None:
                continue
            value = cls._number_or_none(review[field])
            if value is not None:
                values.append(value)
        return values

    @staticmethod
    def _average(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 6) if values else None

    @staticmethod
    def _missing_beat_ids(expected: list[dict[str, Any]], reviewed: list[dict[str, Any]]) -> list[str]:
        expected_ids = [str(beat.get("beat_id")) for beat in expected if beat.get("beat_id")]
        reviewed_ids = {str(beat.get("beat_id")) for beat in reviewed if beat.get("beat_id")}
        return [beat_id for beat_id in expected_ids if beat_id not in reviewed_ids]

    @classmethod
    def _incomplete_beat_ids(cls, expected: list[dict[str, Any]], reviewed: list[dict[str, Any]]) -> list[str]:
        required = ("action_score", "gesture_score", "expression_score", "gaze_score", "head_angle_score")
        reviews = {
            str(beat.get("beat_id")): beat
            for beat in reviewed
            if isinstance(beat, dict) and beat.get("beat_id")
        }
        incomplete: list[str] = []
        for beat in expected:
            beat_id = str(beat.get("beat_id")) if beat.get("beat_id") else ""
            if not beat_id or beat_id not in reviews:
                continue
            if any(reviews[beat_id].get(field) is None for field in required):
                incomplete.append(beat_id)
        return incomplete

    @staticmethod
    def _performance_issues(*, order_score, expression_score, reviewed, missing) -> list[str]:
        issues: list[str] = []
        if not reviewed:
            issues.append("Beat-level action and expression review is missing.")
        if missing:
            issues.append("Missing reviewed beats: " + ", ".join(missing) + ".")
        if order_score is not None and order_score < PASS_THRESHOLD:
            issues.append("Action order or gesture timing is below the pass line.")
        if expression_score is not None and expression_score < PASS_THRESHOLD:
            issues.append("Expression, gaze, blink, or head-angle timing is below the pass line.")
        return issues

    @staticmethod
    def _format_score(value: Any) -> str:
        return "unreviewed" if value is None else f"{float(value):.2f}"
