"""MiniMax-H3 planner for identity + performance-reference video generation.

The dance planner is intentionally narrow. This planner keeps the same H3
request contract but makes facial performance and timed action beats first
class inputs, so a reference-performance run cannot silently collapse into a
generic motion prompt.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.video.reference_dance_h3_plan import ReferenceDanceH3Plan


class ReferencePerformanceH3Plan(ReferenceDanceH3Plan):
    name = "reference_performance_h3_plan"
    version = "0.1.0"
    capabilities = [
        "reference_performance_prompt_compile",
        "minimax_h3_request_artifact",
        "generation_attempt_log",
        "timed_action_expression_lock",
    ]
    supports = {
        "paid_api_call": False,
        "reference_image": True,
        "reference_video": True,
        "reference_audio": True,
        "subject_mapping": True,
        "camera_lock": True,
        "timed_action_beats": True,
        "facial_expression_beats": True,
        "one_shot_15s": True,
        "generation_attempt_log": True,
    }
    best_for = [
        "compiling H3 requests from a target identity image and a performance reference video",
        "preserving action order, hand gestures, head angles, gaze, blinks, expressions, and pauses",
        "creating a reviewable request before paid reference-performance generation",
    ]
    not_good_for = [
        "guaranteeing frame-perfect facial landmark transfer through prompting alone",
        "submitting paid video jobs",
        "replacing a pose or facial-control model when exact tracking is required",
    ]

    input_schema = {
        **ReferenceDanceH3Plan.input_schema,
        "required": ["project_id", "reference_image_urls", "reference_video_url", "performance_analysis"],
        "properties": {
            **ReferenceDanceH3Plan.input_schema["properties"],
            "performance_analysis": {
                "type": ["object", "string"],
                "description": "Timed action/expression analysis artifact or its JSON path.",
            },
            "identity_lock": {"type": "string"},
            "reference_usage_policy": {"type": "object"},
        },
    }

    def execute(self, inputs: dict[str, Any]):
        """Delegate persistence to the proven planner with a corrected pipeline label."""
        result = super().execute(inputs)
        if result.success:
            attempt = result.data.get("generation_attempt", {})
            attempt["pipeline"] = "reference-performance"
            result.data["generation_attempt"] = attempt
            attempt_path = result.data.get("attempt_json_path")
            if attempt_path:
                Path(attempt_path).write_text(
                    json.dumps(attempt, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        return result

    @classmethod
    def _compile_prompt(cls, inputs: dict[str, Any]) -> str:
        analysis = cls._load_analysis(inputs.get("performance_analysis"))
        mode = str(inputs.get("performance_mode") or "single_character")
        if mode not in {"single_character", "two_character"}:
            raise ValueError("performance_mode must be single_character or two_character")

        identity = str(
            inputs.get("identity_lock")
            or "[reference_image] is the sole authority for the target face, facial proportions, hair, wardrobe, body proportions, age, and identity. Preserve it consistently from first frame to last frame."
        )
        scene = str(
            inputs.get("scene")
            or "Use a simple scene selected independently from the reference video; preserve the reference camera grammar only when the analysis says it is part of the intended performance."
        )
        beats = analysis.get("beats")
        cls._validate_performance_beats(beats)
        performer_count = "exactly one" if mode == "single_character" else "exactly two"
        subject = (
            f"There are {performer_count} visible fictional adult performer(s). "
            "The target identity image has priority over the reference video's performer. "
            "The reference video supplies performance data only: action order, gesture trajectory, body rhythm, "
            "head angle, gaze direction, blink timing, facial expression, breathing rhythm, pauses, and reaction timing. "
            "Never copy the reference performer's face, hair, body, clothing, background, text, watermark, or identity."
        )
        camera = str(
            inputs.get("camera_lock")
            or "Preserve a stable camera, subject count, framing, lens feel, and spatial blocking. Do not add a cut, zoom, reframing, or new character unless explicitly present in the approved plan."
        )
        wardrobe = str(
            inputs.get("wardrobe")
            or "Keep the target character's wardrobe from the supplied identity/reference images unchanged throughout. Ignore every outfit transformation in the motion reference."
        )
        beat_text = "\n".join(cls._format_beat(index, beat) for index, beat in enumerate(beats, start=1))
        negatives = inputs.get("negative_constraints") or [
            "identity drift",
            "expression reset to a blank face",
            "missing blink or gaze change",
            "wrong action order",
            "generic hand waving",
            "stiff mannequin motion",
            "copied source performer",
            "copied source wardrobe",
            "outfit transformation",
            "extra people",
            "duplicate performer",
            "face merge",
            "hair color change",
            "camera reframing",
            "scene change",
            "text",
            "logo",
            "watermark",
            "deformed hands",
            "extra fingers",
            "plastic CGI skin",
            "anime illustration",
        ]

        sections = [
            (
                "core_intent",
                "Create one continuous reference-performance video. The priority is faithful performance transfer: the target character must perform the same timed action and facial-performance sequence as the source, while retaining the target identity and wardrobe.",
            ),
            ("subject_mapping", subject),
            ("identity_lock", identity),
            ("wardrobe_lock", wardrobe),
            ("camera_lock", camera),
            ("scene", scene),
            (
                "performance_transfer",
                "Do not summarize the performance as a mood. Execute each beat in order. Body motion must lead from weight shift through torso and shoulders to elbows, wrists, hands, and fingers. Facial performance must be synchronized with the action: preserve gaze target, eyelid openness, blink timing, brow tension, mouth shape, head angle, and the pause after each gesture.",
            ),
            ("timed_performance_beats", beat_text),
            (
                "continuity_lock",
                "Keep the target face, hair, accessories, wardrobe, body scale, subject count, left/right placement, lighting, and camera distance stable from first frame to last frame. If a segment boundary is necessary, begin from the exact terminal pose and expression of the previous segment; never reset to a neutral pose.",
            ),
            (
                "audio",
                "Do not invent dialogue or singing unless explicitly requested. Preserve only approved source rhythm/ambience references. Do not add subtitles, lyrics, or readable text.",
            ),
            ("negative_constraints", "No " + ", no ".join(str(item) for item in negatives) + "."),
        ]
        header = (
            f"Single continuous shot, {inputs.get('ratio', '9:16')} vertical photoreal cinematic "
            f"reference-performance video, duration {inputs.get('duration', 15)} seconds, no cuts."
        )
        return header + "\n\n" + "\n\n".join(
            f"[{name}]\n{body}" for name, body in sections
        )

    @staticmethod
    def _load_analysis(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value:
            path = Path(str(value))
            if not path.is_file():
                raise ValueError(f"performance_analysis does not exist: {path}")
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("performance_analysis must be a JSON object")
            return data
        return {}

    @staticmethod
    def _validate_performance_beats(beats: Any) -> None:
        """Reject vague or partial analyses before they reach a paid request."""
        if not isinstance(beats, list) or not beats:
            raise ValueError("performance_analysis.beats must contain at least one analyzed beat")

        required = (
            "beat_id",
            "start_seconds",
            "end_seconds",
            "action",
            "hand_gesture",
            "head_angle",
            "gaze",
            "expression",
            "blink",
            "body_weight",
            "pause_after_seconds",
            "intensity",
        )
        for index, beat in enumerate(beats, start=1):
            if not isinstance(beat, dict):
                raise ValueError(f"performance_analysis.beats[{index}] must be an object")
            missing = [field for field in required if beat.get(field) in (None, "")]
            if missing:
                beat_id = beat.get("beat_id", f"#{index}")
                raise ValueError(f"beat {beat_id} is missing: {', '.join(missing)}")
            try:
                start = float(beat["start_seconds"])
                end = float(beat["end_seconds"])
                pause = float(beat["pause_after_seconds"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"beat {beat['beat_id']} has invalid timing values") from exc
            if start < 0 or end <= start or pause < 0:
                raise ValueError(f"beat {beat['beat_id']} must have start < end and non-negative pause")

    @staticmethod
    def _format_beat(index: int, beat: dict[str, Any]) -> str:
        start = beat.get("start_seconds", beat.get("start", 0))
        end = beat.get("end_seconds", beat.get("end", start))
        fields = [
            f"beat {index} ({float(start):.2f}-{float(end):.2f}s)",
            f"action={beat.get('action', 'preserve the analyzed action order')}",
            f"hands={beat.get('hand_gesture', 'preserve the analyzed hand trajectory')}",
            f"head={beat.get('head_angle', 'preserve the analyzed head angle')}",
            f"gaze={beat.get('gaze', 'preserve the analyzed gaze target')}",
            f"expression={beat.get('expression', 'preserve the analyzed facial expression')}",
            f"blink={beat.get('blink', 'preserve the analyzed blink timing')}",
            f"weight={beat.get('body_weight', 'preserve the analyzed body-weight transfer')}",
            f"pause_after={beat.get('pause_after_seconds', 0)}s",
        ]
        return " | ".join(str(item) for item in fields)

    @staticmethod
    def _fallback_beats(duration: int) -> list[dict[str, Any]]:
        step = duration / 5
        return [
            {
                "start_seconds": round(index * step, 2),
                "end_seconds": round((index + 1) * step, 2),
                "action": "execute the source action sequence in this interval",
                "hand_gesture": "preserve the source hand trajectory",
                "head_angle": "preserve the source head angle",
                "gaze": "preserve the source gaze target",
                "expression": "preserve the source facial expression",
                "blink": "preserve the source blink timing",
                "body_weight": "preserve the source weight transfer",
                "pause_after_seconds": 0,
            }
            for index in range(5)
        ]

    @staticmethod
    def _generation_attempt(*, inputs, request_json, request_path, target_output_path, cost):
        attempt = ReferenceDanceH3Plan._generation_attempt(
            inputs=inputs,
            request_json=request_json,
            request_path=request_path,
            target_output_path=target_output_path,
            cost=cost,
        )
        attempt["pipeline"] = "reference-performance"
        attempt["metadata"].update(
            {
                "timed_performance_beats": len(
                    ReferencePerformanceH3Plan._load_analysis(inputs.get("performance_analysis")).get("beats", [])
                ),
                "expression_review_required": True,
                "identity_source_authority": "reference_image",
                "motion_source_authority": "reference_video",
            }
        )
        attempt["metadata"]["quality_gate"]["priority_order"] = [
            "action_order",
            "expression",
            "identity",
            "continuity",
            "beauty",
        ]
        return attempt
