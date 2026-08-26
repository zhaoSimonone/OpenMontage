"""Deterministic technical and seam-readiness QA for narrative shorts."""

from __future__ import annotations

import json
import math
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)
from tools.video._shared import probe_output


class NarrativeShortQA(BaseTool):
    """Check clip spec compliance and produce review frames for human QA.

    It intentionally does not claim to identify a character or judge acting.
    Those remain human reviewer tasks supported by the output contact frames.
    """

    name = "narrative_short_qa"
    version = "0.1.0"
    tier = ToolTier.ANALYZE
    capability = "narrative_short_qa"
    provider = "ffmpeg"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["cmd:ffmpeg", "cmd:ffprobe"]
    install_instructions = "Install FFmpeg: brew install ffmpeg"
    agent_skills = ["ffmpeg", "video-understand"]
    capabilities = ["narrative_clip_validation", "seam_readiness", "review_frame_extraction"]
    supports = {"two_clip_qa": True, "semantic_identity_score": False, "manual_review_frames": True}
    best_for = ["checking 9:16 narrative short clips before final composition"]
    not_good_for = ["automatic face identity or acting-quality judgment"]

    input_schema = {
        "type": "object",
        "required": ["project_id", "clip_paths", "bridge_contract", "output_path"],
        "properties": {
            "project_id": {"type": "string"},
            "clip_paths": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2},
            "bridge_contract": {"type": ["object", "string"]},
            "output_path": {"type": "string"},
            "frame_output_dir": {"type": "string"},
            "expected_ratio": {"type": "string", "enum": ["9:16"], "default": "9:16"},
            "expected_total_duration_seconds": {"type": "number", "default": 30},
            "duration_tolerance_seconds": {"type": "number", "default": 1.5},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=250)
    retry_policy = RetryPolicy(max_retries=0)
    idempotency_key_fields = ["clip_paths", "bridge_contract", "expected_ratio"]
    side_effects = ["writes review frames and narrative_short_qa JSON"]
    user_visible_verification = [
        "Inspect the extracted frames for character identity, POV violations, hand quality, prop continuity, and acting.",
    ]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        paths = [Path(path) for path in inputs["clip_paths"]]
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            return ToolResult(success=False, error=f"Narrative-short QA clip(s) missing: {missing}")

        try:
            bridge = self._load_bridge(inputs["bridge_contract"])
            self._validate_bridge(bridge, paths)
            report = self._build_report(inputs, paths, bridge)
        except Exception as exc:
            return ToolResult(success=False, error=f"Narrative-short QA failed: {exc}")

        output_path = Path(inputs["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return ToolResult(
            success=True,
            data=report,
            artifacts=[str(output_path), *report["review_frames"]],
        )

    @staticmethod
    def _load_bridge(value: object) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        path = Path(str(value))
        if not path.is_file():
            raise ValueError(f"Bridge contract does not exist: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Bridge contract must be a JSON object")
        return data

    @staticmethod
    def _validate_bridge(bridge: dict[str, Any], paths: list[Path]) -> None:
        segments = bridge.get("segments") or []
        joins = bridge.get("joins") or []
        if len(segments) != len(paths) or len(joins) != 1:
            raise ValueError("Bridge contract must contain two segments and one join")
        if joins[0].get("from") != segments[0].get("id") or joins[0].get("to") != segments[1].get("id"):
            raise ValueError("Bridge join does not match segment ordering")

    def _build_report(self, inputs: dict[str, Any], paths: list[Path], bridge: dict[str, Any]) -> dict[str, Any]:
        frame_dir = Path(
            inputs.get("frame_output_dir")
            or Path(inputs["output_path"]).parent / "narrative_short_review_frames"
        )
        frame_dir.mkdir(parents=True, exist_ok=True)
        clips = [self._clip_report(path, frame_dir, index) for index, path in enumerate(paths, start=1)]
        seam = self._seam_report(clips, bridge)
        total_duration = sum(float(clip["probe"].get("duration_seconds") or 0.0) for clip in clips)
        expected = float(inputs.get("expected_total_duration_seconds", 30))
        tolerance = float(inputs.get("duration_tolerance_seconds", 1.5))
        duration_ok = abs(total_duration - expected) <= tolerance
        spec_issues = [issue for clip in clips for issue in clip["issues"]]
        if not duration_ok:
            spec_issues.append(
                f"Source clips total {total_duration:.2f}s, expected {expected:.2f}s +/- {tolerance:.2f}s before transition."
            )
        decision = "READY_FOR_HUMAN_REVIEW" if not spec_issues else "REGENERATE_AFFECTED_CLIP"
        return {
            "version": "1.0",
            "project_id": inputs["project_id"],
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "clip_count": len(clips),
            "clips": clips,
            "total_source_duration_seconds": round(total_duration, 3),
            "expected_total_duration_seconds": expected,
            "duration_within_tolerance": duration_ok,
            "seam_readiness": seam,
            "review_frames": [frame for clip in clips for frame in clip["review_frames"]],
            "automatic_issues": spec_issues,
            "manual_review_required": [
                "same adult female character and wardrobe in both clips",
                "no male face, body, arms, hands, shadow, reflection, or silhouette",
                "no extra people, malformed hands, face drift, text, logo, or watermark",
                "bridge prop and emotional cause-effect remain readable",
                "dialogue lip movement and acting look natural enough for final audio treatment",
            ],
            "decision": decision,
            "next_action": (
                {"kind": "human_visual_review", "reason": "Technical checks passed; semantic and acting review is required."}
                if decision == "READY_FOR_HUMAN_REVIEW"
                else {"kind": "regenerate_affected_clip", "reason": "At least one technical clip requirement failed."}
            ),
        }

    def _clip_report(self, path: Path, frame_dir: Path, index: int) -> dict[str, Any]:
        probe = probe_output(path)
        width = int(probe.get("video_width") or 0)
        height = int(probe.get("video_height") or 0)
        duration = float(probe.get("duration_seconds") or 0.0)
        issues: list[str] = []
        if width <= 0 or height <= 0:
            issues.append(f"{path.name}: missing a readable video stream")
        elif not math.isclose(width / height, 9 / 16, abs_tol=0.03):
            issues.append(f"{path.name}: expected 9:16, got {width}x{height}")
        if duration < 12.0 or duration > 16.0:
            issues.append(f"{path.name}: expected a roughly 15-second clip, got {duration:.2f}s")
        review_frames = self._extract_review_frames(path, frame_dir, index, duration)
        luma = [self._mean_luma(Path(frame)) for frame in review_frames]
        if luma and max(luma) < 5.0:
            issues.append(f"{path.name}: sampled frames are near-black")
        return {
            "clip_id": f"shot_{index:03d}",
            "path": str(path),
            "probe": probe,
            "issues": issues,
            "review_frames": review_frames,
            "luma_samples": [round(value, 3) for value in luma],
        }

    def _extract_review_frames(self, path: Path, frame_dir: Path, index: int, duration: float) -> list[str]:
        sample_times = [0.2, max(duration * 0.5, 0.2), max(duration - 0.2, 0.2)]
        frames: list[str] = []
        for sample_index, timestamp in enumerate(sample_times, start=1):
            target = frame_dir / f"shot_{index:03d}_{sample_index:02d}_{timestamp:.2f}s.jpg"
            self.run_command(
                [
                    "ffmpeg", "-y", "-ss", f"{timestamp:.3f}", "-i", str(path),
                    "-frames:v", "1", "-q:v", "2", str(target),
                ]
            )
            if target.exists():
                frames.append(str(target))
        return frames

    @staticmethod
    def _mean_luma(frame_path: Path) -> float:
        try:
            from PIL import Image, ImageStat

            image = Image.open(frame_path).convert("L")
            return float(ImageStat.Stat(image).mean[0])
        except Exception:
            return 0.0

    @staticmethod
    def _seam_report(clips: list[dict[str, Any]], bridge: dict[str, Any]) -> dict[str, Any]:
        first_luma = clips[0]["luma_samples"][-1] if clips[0]["luma_samples"] else 0.0
        second_luma = clips[1]["luma_samples"][0] if clips[1]["luma_samples"] else 0.0
        luma_delta = abs(float(first_luma) - float(second_luma))
        transition = bridge["joins"][0]["transition"]
        readiness_score = max(0.0, min(1.0, 1.0 - (luma_delta / 170.0)))
        return {
            "from_clip": clips[0]["clip_id"],
            "to_clip": clips[1]["clip_id"],
            "transition": transition,
            "bridge_prop": bridge["joins"][0]["semantic_bridge"]["bridge_prop"],
            "boundary_luma_delta": round(luma_delta, 3),
            "technical_readiness_score": round(readiness_score, 3),
            "requires_manual_prop_identity_review": True,
        }
