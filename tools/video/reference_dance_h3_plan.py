"""Reference-dance planning tool for MiniMax-H3.

This tool compiles a structured dance prompt, writes the H3 request JSON, and
records a planned GenerationAttempt. It does not call the paid H3 API.
"""

from __future__ import annotations

import json
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
from tools.video.minimax_h3_video import MiniMaxH3Video


_MODEL = "MiniMax-H3"
_PROVIDER = "minimax_h3"
_OPERATION = "reference_to_video"


class ReferenceDanceH3Plan(BaseTool):
    name = "reference_dance_h3_plan"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "openmontage"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies: list[str] = []
    install_instructions = "No external setup required. This planner does not call paid APIs."
    agent_skills = ["ai-video-gen"]

    capabilities = [
        "reference_dance_prompt_compile",
        "minimax_h3_request_artifact",
        "generation_attempt_log",
    ]
    supports = {
        "paid_api_call": False,
        "reference_image": True,
        "reference_video": True,
        "reference_audio": True,
        "subject_mapping": True,
        "camera_lock": True,
        "one_shot_15s": True,
        "generation_attempt_log": True,
    }
    best_for = [
        "compiling two-character reference-dance prompts for MiniMax-H3",
        "creating reviewable H3 request JSON before paid generation",
        "logging planned GenerationAttempt metadata for continuity",
    ]
    not_good_for = [
        "submitting paid video generation jobs",
        "automatic pose-fidelity scoring; use later motion QA tools",
    ]

    input_schema = {
        "type": "object",
        "required": ["project_id", "reference_image_urls", "reference_video_url"],
        "properties": {
            "project_id": {"type": "string"},
            "shot_id": {"type": "string", "default": "shot_001"},
            "attempt_id": {"type": "string", "default": "attempt_001"},
            "duration": {"type": "integer", "minimum": 4, "maximum": 15, "default": 15},
            "ratio": {"type": "string", "enum": ["9:16", "16:9", "1:1"], "default": "9:16"},
            "resolution": {"type": "string", "enum": ["768P", "2K"], "default": "768P"},
            "aigc_watermark": {"type": "boolean", "default": False},
            "reference_image_urls": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "reference_video_url": {"type": "string"},
            "reference_audio_url": {"type": "string"},
            "character_1": {"type": "object"},
            "character_2": {"type": "object"},
            "wardrobe": {"type": "string"},
            "scene": {"type": "string"},
            "choreography_beats": {"type": "array", "items": {"type": "string"}},
            "negative_constraints": {"type": "array", "items": {"type": "string"}},
            "output_request_path": {"type": "string"},
            "output_attempt_path": {"type": "string"},
            "target_output_path": {"type": "string"},
            "write_files": {"type": "boolean", "default": True},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "request_json_path": {"type": "string"},
            "attempt_json_path": {"type": "string"},
            "request_json": {"type": "object"},
            "generation_attempt": {"type": "object"},
            "estimated_cost_usd": {"type": "number"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=20)
    retry_policy = RetryPolicy(max_retries=0)
    idempotency_key_fields = [
        "project_id",
        "shot_id",
        "attempt_id",
        "duration",
        "ratio",
        "resolution",
        "reference_image_urls",
        "reference_video_url",
        "reference_audio_url",
        "character_1",
        "character_2",
        "wardrobe",
        "scene",
        "choreography_beats",
        "negative_constraints",
    ]
    side_effects = [
        "writes H3 request JSON when write_files=true",
        "writes planned GenerationAttempt JSON when write_files=true",
    ]
    user_visible_verification = [
        "Review generated request JSON before approving paid H3 generation",
    ]

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return MiniMaxH3Video().estimate_cost(
            {
                "prompt": "reference dance plan",
                "duration": inputs.get("duration", 15),
                "resolution": inputs.get("resolution", "768P"),
            }
        )

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        try:
            payload = self._build_request(inputs)
            request_json = MiniMaxH3Video._build_payload(
                {
                    "prompt": payload["content"][0]["text"],
                    "operation": _OPERATION,
                    "content": payload["content"],
                    "resolution": payload["resolution"],
                    "duration": payload["duration"],
                    "ratio": payload["ratio"],
                    "aigc_watermark": payload.get("aigc_watermark", False),
                }
            )
            request_json["aigc_watermark"] = payload.get("aigc_watermark", False)
        except Exception as exc:
            return ToolResult(success=False, error=f"Reference dance H3 plan failed: {exc}")

        project_id = inputs["project_id"]
        shot_id = str(inputs.get("shot_id") or "shot_001")
        attempt_id = str(inputs.get("attempt_id") or "attempt_001")
        request_path = Path(
            inputs.get("output_request_path")
            or self._default_artifact_path(project_id, f"{shot_id}_{attempt_id}_minimax_h3_request.json")
        )
        attempt_path = Path(
            inputs.get("output_attempt_path")
            or self._default_artifact_path(project_id, f"{shot_id}_{attempt_id}_generation_attempt.json")
        )
        target_output_path = str(
            inputs.get("target_output_path")
            or Path("projects") / project_id / "assets" / "video" / f"{shot_id}_{attempt_id}_minimax_h3.mp4"
        )
        cost = self.estimate_cost(inputs)
        attempt = self._generation_attempt(
            inputs=inputs,
            request_json=request_json,
            request_path=request_path,
            target_output_path=target_output_path,
            cost=cost,
        )

        artifacts: list[str] = []
        if bool(inputs.get("write_files", True)):
            request_path.parent.mkdir(parents=True, exist_ok=True)
            attempt_path.parent.mkdir(parents=True, exist_ok=True)
            request_path.write_text(
                json.dumps(request_json, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            attempt_path.write_text(
                json.dumps(attempt, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            artifacts.extend([str(request_path), str(attempt_path)])

        return ToolResult(
            success=True,
            data={
                "provider": _PROVIDER,
                "model": _MODEL,
                "operation": _OPERATION,
                "request_json": request_json,
                "generation_attempt": attempt,
                "request_json_path": str(request_path),
                "attempt_json_path": str(attempt_path),
                "target_output_path": target_output_path,
                "estimated_cost_usd": cost,
            },
            artifacts=artifacts,
            cost_usd=0.0,
            model=_MODEL,
        )

    @staticmethod
    def _default_artifact_path(project_id: str, filename: str) -> Path:
        return Path("projects") / project_id / "artifacts" / filename

    @classmethod
    def _build_request(cls, inputs: dict[str, Any]) -> dict[str, Any]:
        prompt = cls._compile_prompt(inputs)
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for url in inputs.get("reference_image_urls") or []:
            content.append({"type": "image_url", "image_url": str(url), "role": "reference_image"})
        if inputs.get("reference_video_url"):
            content.append(
                {
                    "type": "video_url",
                    "video_url": str(inputs["reference_video_url"]),
                    "role": "reference_video",
                }
            )
        if inputs.get("reference_audio_url"):
            content.append(
                {
                    "type": "audio_url",
                    "audio_url": str(inputs["reference_audio_url"]),
                    "role": "reference_audio",
                }
            )
        return {
            "model": _MODEL,
            "content": content,
            "resolution": str(inputs.get("resolution") or "768P"),
            "duration": int(inputs.get("duration") or 15),
            "ratio": str(inputs.get("ratio") or "9:16"),
            "aigc_watermark": bool(inputs.get("aigc_watermark", False)),
        }

    @classmethod
    def _compile_prompt(cls, inputs: dict[str, Any]) -> str:
        c1 = {
            **cls._default_character_1(),
            **(inputs.get("character_1") or {}),
        }
        c2 = {
            **cls._default_character_2(),
            **(inputs.get("character_2") or {}),
        }
        scene = inputs.get("scene") or (
            "warm clean indoor hallway or simple dance-practice room, natural daylight, "
            "soft cinematic color, realistic skin texture and matte hair strands"
        )
        wardrobe = inputs.get("wardrobe") or (
            "fashion-forward dance-friendly outfits: cropped or short soft blazer, clean white blouse, "
            "slim black tie, high-waisted wide-leg trousers, and clean white sneakers; "
            "pastel light-blue accents for Character 1 and pastel light-pink accents for Character 2"
        )
        choreography_beats = inputs.get("choreography_beats") or cls._default_choreography_beats()
        negative_constraints = inputs.get("negative_constraints") or cls._default_negative_constraints()

        sections = [
            (
                "core_intent",
                (
                    "Single unbroken reference-dance video for a vertical social short. "
                    "Motion is the priority: fluid body-led dance motion over static beauty posing. "
                    "Keep the energy cute, stylish, modest, and live-action realistic."
                ),
            ),
            (
                "subject_mapping",
                (
                    f"Character 1 = {c1['name']} = {c1['summary']}. Character 1 always maps to the "
                    "left performer in the reference video and stays left / slightly forward in frame. "
                    f"Character 2 = {c2['name']} = {c2['summary']}. Character 2 always maps to the "
                    "right performer in the reference video and stays right / half a step behind in frame. "
                    "Use the reference video only for choreography, timing, body motion, footwork, "
                    "body-weight transfer, shoulder rhythm, hip rhythm, arm trajectories, relative spacing, "
                    "and final beat structure. Do not copy the reference performers' faces, bodies, clothes, "
                    "masks, background, captions, platform UI, watermark, or exact identity."
                ),
            ),
            (
                "identity_lock",
                (
                    "Exactly two fictional adult young women around 20, no other people. "
                    f"Character 1 appearance: {c1['appearance']}. "
                    f"Character 2 appearance: {c2['appearance']}. "
                    "Keep hair colors, face shapes, side placement, body scale, and personality clearly "
                    "distinct for the entire clip."
                ),
            ),
            ("wardrobe_lock", str(wardrobe)),
            (
                "camera_lock",
                (
                    "Static locked camera. Vertical 9:16 frame. Full-body two-shot. Both dancers visible "
                    "together for the whole clip. Both feet remain visible. Keep the same scene, warm daylight, "
                    "camera height, crop, distance, and lens feel. No zoom, no push-in, no dolly, no reframing, "
                    "no handheld wobble that changes framing, no sudden angle change, no medium shot, no close-up, "
                    "and no approach-to-camera ending."
                ),
            ),
            (
                "scene",
                str(scene),
            ),
            (
                "choreography",
                (
                    "Follow the supplied reference dance video's broad rhythm and blocking: side-by-side spacing, "
                    "playful setup, alternating gestures, tie/collar rhythm, chest-level hand crosses, shoulder hits, "
                    "wide-stance footwork, small half-beat call-and-response, and synchronized ending beats. "
                    "Make the body lead every gesture: knees soften before hands move, hips and shoulders pulse under "
                    "the arms, wrists lag slightly after elbows, and feet keep making grounded adjustments."
                ),
            ),
            ("timing", "\n".join(choreography_beats)),
            (
                "audio",
                (
                    "No dialogue and no singing. If native sound appears, keep only soft room tone, light footsteps, "
                    "subtle fabric movement, tiny breath, and a light upbeat rhythm feel. Do not add captions or lyrics."
                ),
            ),
            ("negative_constraints", "No " + ", no ".join(negative_constraints) + "."),
        ]
        header = (
            f"Single continuous shot, {inputs.get('ratio', '9:16')} vertical photoreal cinematic "
            f"two-person dance video, duration {inputs.get('duration', 15)} seconds, no cuts."
        )
        return header + "\n\n" + "\n\n".join(
            f"[{name}]\n{body}" for name, body in sections
        )

    @staticmethod
    def _default_character_1() -> dict[str, str]:
        return {
            "name": "blue-haired fictional adult young woman",
            "summary": "pastel sky-blue short-haired adult woman with gentle shy energy",
            "appearance": (
                "pastel sky-blue short bob hair with long bangs covering most of one eye, clear light-blue eyes, "
                "soft round face, natural full cheeks, short midface, small rounded chin, gentle shy smile, petite "
                "cute adult proportions, realistic matte hair strands, natural skin texture"
            ),
        }

    @staticmethod
    def _default_character_2() -> dict[str, str]:
        return {
            "name": "pink-haired fictional adult young woman",
            "summary": "pastel rose-pink short-haired adult woman with reserved tender energy",
            "appearance": (
                "pastel rose-pink short bob hair with long bangs covering most of one eye, warm red-pink eyes, "
                "soft round face, natural full cheeks, short midface, small rounded chin, slightly reserved tender "
                "smile, petite compact cute adult proportions, realistic matte hair strands, natural skin texture"
            ),
        }

    @staticmethod
    def _default_choreography_beats() -> list[str]:
        return [
            "0-3s: Both start full-body in frame, already alive with tiny knee bends and side-to-side weight shift. Hands hover near tie/collar; shoulders softly pulse; feet stay grounded and visible.",
            "3-6s: Character 1 leads a small side-step and modest wrist flick; Character 2 answers half a beat later. Keep shoulder bounce, hip recovery, soft knees, and small foot travel.",
            "6-10s: Both lightly tug or adjust the slim tie, then cross hands near chest level in rhythm. The stance opens wider with clear lower-body weight transfer.",
            "10-13s: They perform mirrored torso-crossing arm sweeps and wider footwork. Character 1 leads slightly, Character 2 follows with a soft half-beat delay, then they synchronize again.",
            "13-15s: They land in a cute synchronized final pose with both feet visible, relaxed hands near chest or tie height, gentle smiles, same full-body framing, and a short natural hold.",
        ]

    @staticmethod
    def _default_negative_constraints() -> list[str]:
        return [
            "extra people",
            "duplicated characters",
            "male body",
            "viewer hands",
            "camera operator reflection",
            "mirror reflection",
            "phone prop",
            "readable text",
            "captions",
            "logo",
            "watermark",
            "app UI",
            "anime illustration",
            "plastic CGI skin",
            "cheap cosplay studio look",
            "sharp chin",
            "long narrow face",
            "harsh cheekbones",
            "heavy eyeliner",
            "dark lipstick",
            "exaggerated breasts",
            "cleavage",
            "bare midriff",
            "seductive pose",
            "underage look",
            "school uniform",
            "maid outfit",
            "idol stage costume",
            "deformed hands",
            "extra fingers",
            "fused fingers",
            "missing fingers",
            "face merge",
            "face drift",
            "hair color swap",
            "outfit swap",
            "sudden cut",
            "camera zoom",
            "closer framing",
            "approach-to-camera",
            "hospital room",
            "bedside scene",
            "first-person POV",
            "male lead",
            "dialogue drama",
        ]

    @staticmethod
    def _generation_attempt(
        *,
        inputs: dict[str, Any],
        request_json: dict[str, Any],
        request_path: Path,
        target_output_path: str,
        cost: float,
    ) -> dict[str, Any]:
        shot_id = str(inputs.get("shot_id") or "shot_001")
        attempt_id = str(inputs.get("attempt_id") or "attempt_001")
        return {
            "version": "1.0",
            "project_id": inputs["project_id"],
            "pipeline": "reference-dance",
            "shot_id": shot_id,
            "attempt_id": attempt_id,
            "status": "planned",
            "provider": _PROVIDER,
            "model": _MODEL,
            "operation": _OPERATION,
            "prompt": request_json["content"][0]["text"],
            "request_json": request_json,
            "request_json_path": str(request_path),
            "output_path": target_output_path,
            "cost_estimate_usd": cost,
            "latency_seconds": None,
            "scores": {
                "motion": None,
                "continuity": None,
                "identity": None,
                "camera": None,
                "total": None,
            },
            "failure_reason": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "one_shot": int(inputs.get("duration") or 15) == 15,
                "ratio": inputs.get("ratio", "9:16"),
                "resolution": inputs.get("resolution", "768P"),
                "reference_image_count": len(inputs.get("reference_image_urls") or []),
                "has_reference_video": bool(inputs.get("reference_video_url")),
                "has_reference_audio": bool(inputs.get("reference_audio_url")),
                "paid_generation_submitted": False,
                "quality_gate": {
                    "motion_score_threshold": 0.70,
                    "motion_regenerate_threshold": 0.55,
                    "continuity_score_threshold": 0.70,
                    "continuity_repair_threshold": 0.65,
                    "failed_motion_attempts_before_fallback": 2,
                    "priority_order": ["motion", "continuity", "identity", "beauty"],
                },
            },
        }
