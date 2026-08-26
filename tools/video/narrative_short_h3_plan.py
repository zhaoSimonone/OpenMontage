"""Deterministic MiniMax-H3 request compiler for narrative-short projects."""

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


class NarrativeShortH3Plan(BaseTool):
    """Compile approved story artifacts into reviewable H3 requests.

    The tool deliberately does not create story beats or call a paid endpoint.
    Those are responsibilities of the pipeline director and generation stage.
    """

    name = "narrative_short_h3_plan"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "openmontage"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies: list[str] = []
    install_instructions = "No external setup required. This planner never calls paid APIs."
    agent_skills = ["ai-video-gen"]
    capabilities = [
        "narrative_short_prompt_compile",
        "minimax_h3_request_artifact",
        "generation_attempt_log",
        "segment_bridge_contract",
    ]
    supports = {
        "paid_api_call": False,
        "reference_image": True,
        "two_segment_story": True,
        "identity_lock": True,
        "first_person_pov": True,
        "generation_attempt_log": True,
    }
    best_for = [
        "compiling a two-clip vertical narrative short for MiniMax-H3",
        "recording reviewable request and bridge artifacts before paid generation",
    ]
    not_good_for = [
        "writing story beats autonomously",
        "submitting paid jobs",
        "guaranteeing native dialogue audio from MiniMax-H3",
    ]

    input_schema = {
        "type": "object",
        "required": [
            "project_id",
            "reference_image_urls",
            "canonical_character_description",
            "scene_lock",
            "bridge_contract",
            "shots",
        ],
        "properties": {
            "project_id": {"type": "string"},
            "reference_image_urls": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "canonical_character_description": {"type": "string", "minLength": 1},
            "scene_lock": {"type": "string", "minLength": 1},
            "bridge_contract": {"type": ["object", "string"]},
            "shots": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "required": ["shot_id", "story_beat", "bridge_state"],
                    "properties": {
                        "shot_id": {"type": "string"},
                        "attempt_id": {"type": "string"},
                        "story_beat": {"type": "string"},
                        "bridge_state": {"type": "string"},
                        "camera": {"type": "string"},
                        "performance": {"type": "string"},
                        "dialogue": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            "negative_constraints": {"type": "array", "items": {"type": "string"}},
            "duration": {"type": "integer", "minimum": 4, "maximum": 15, "default": 15},
            "ratio": {"type": "string", "enum": ["9:16"], "default": "9:16"},
            "resolution": {"type": "string", "enum": ["768P", "2K"], "default": "768P"},
            "aigc_watermark": {"type": "boolean", "default": False},
            "output_dir": {"type": "string"},
            "write_files": {"type": "boolean", "default": True},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "plans": {"type": "array"},
            "estimated_cost_usd": {"type": "number"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=20)
    retry_policy = RetryPolicy(max_retries=0)
    idempotency_key_fields = [
        "project_id",
        "reference_image_urls",
        "canonical_character_description",
        "scene_lock",
        "bridge_contract",
        "shots",
        "negative_constraints",
        "duration",
        "ratio",
        "resolution",
    ]
    side_effects = [
        "writes H3 request JSON when write_files=true",
        "writes planned GenerationAttempt JSON when write_files=true",
    ]
    user_visible_verification = [
        "Review both request JSON files, their bridge state, and total cost before approving paid generation.",
    ]

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        clip_cost = MiniMaxH3Video().estimate_cost(
            {
                "prompt": "narrative short plan",
                "duration": inputs.get("duration", 15),
                "resolution": inputs.get("resolution", "768P"),
            }
        )
        return round(clip_cost * len(inputs.get("shots", [])), 2)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        try:
            bridge_contract = self._load_contract(inputs["bridge_contract"])
            plans = self._plans(inputs, bridge_contract)
        except Exception as exc:
            return ToolResult(success=False, error=f"Narrative short H3 plan failed: {exc}")

        artifacts: list[str] = []
        if bool(inputs.get("write_files", True)):
            for plan in plans:
                request_path = Path(plan["request_json_path"])
                attempt_path = Path(plan["attempt_json_path"])
                request_path.parent.mkdir(parents=True, exist_ok=True)
                attempt_path.parent.mkdir(parents=True, exist_ok=True)
                request_path.write_text(
                    json.dumps(plan["request_json"], ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                attempt_path.write_text(
                    json.dumps(plan["generation_attempt"], ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                artifacts.extend([str(request_path), str(attempt_path)])

        return ToolResult(
            success=True,
            data={
                "provider": _PROVIDER,
                "model": _MODEL,
                "operation": _OPERATION,
                "plans": plans,
                "estimated_cost_usd": self.estimate_cost(inputs),
            },
            artifacts=artifacts,
            cost_usd=0.0,
            model=_MODEL,
        )

    @staticmethod
    def _load_contract(contract: object) -> dict[str, Any]:
        if isinstance(contract, dict):
            return contract
        path = Path(str(contract))
        if not path.is_file():
            raise ValueError(f"Bridge contract does not exist: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Bridge contract must be a JSON object")
        return data

    def _plans(self, inputs: dict[str, Any], bridge_contract: dict[str, Any]) -> list[dict[str, Any]]:
        shots = list(inputs.get("shots") or [])
        if len(shots) != 2:
            raise ValueError("Narrative short V1 requires exactly two shots")
        segment_ids = [segment.get("id") for segment in bridge_contract.get("segments", [])]
        shot_ids = [str(shot["shot_id"]) for shot in shots]
        if segment_ids and segment_ids != shot_ids:
            raise ValueError(
                f"Bridge contract segments {segment_ids!r} must match shots {shot_ids!r}"
            )
        joins = bridge_contract.get("joins") or []
        if len(joins) != 1 or joins[0].get("from") != shot_ids[0] or joins[0].get("to") != shot_ids[1]:
            raise ValueError("Bridge contract must define one join from shot 1 to shot 2")

        output_dir = Path(
            inputs.get("output_dir")
            or Path("projects") / str(inputs["project_id"]) / "artifacts" / "generation_attempts"
        )
        plans: list[dict[str, Any]] = []
        for index, shot in enumerate(shots, start=1):
            shot_id = str(shot["shot_id"])
            attempt_id = str(shot.get("attempt_id") or "attempt_001")
            prompt = self._compile_prompt(inputs, shot, bridge_contract, index)
            content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for url in inputs["reference_image_urls"]:
                content.append({"type": "image_url", "image_url": str(url), "role": "reference_image"})
            request_json = MiniMaxH3Video._build_payload(
                {
                    "prompt": prompt,
                    "operation": _OPERATION,
                    "content": content,
                    "duration": int(inputs.get("duration", 15)),
                    "ratio": str(inputs.get("ratio", "9:16")),
                    "resolution": str(inputs.get("resolution", "768P")),
                    "aigc_watermark": bool(inputs.get("aigc_watermark", False)),
                }
            )
            request_json["aigc_watermark"] = bool(inputs.get("aigc_watermark", False))
            request_path = output_dir / f"{shot_id}_{attempt_id}_minimax_h3_request.json"
            attempt_path = output_dir / f"{shot_id}_{attempt_id}_generation_attempt.json"
            target_output = (
                Path("projects")
                / str(inputs["project_id"])
                / "assets"
                / "video"
                / f"{shot_id}_{attempt_id}_minimax_h3.mp4"
            )
            attempt = self._generation_attempt(
                project_id=str(inputs["project_id"]),
                shot_id=shot_id,
                attempt_id=attempt_id,
                request_json=request_json,
                request_path=request_path,
                output_path=target_output,
                bridge_contract=bridge_contract,
                index=index,
                cost=MiniMaxH3Video().estimate_cost(
                    {
                        "prompt": prompt,
                        "duration": inputs.get("duration", 15),
                        "resolution": inputs.get("resolution", "768P"),
                    }
                ),
            )
            plans.append(
                {
                    "shot_id": shot_id,
                    "attempt_id": attempt_id,
                    "request_json": request_json,
                    "request_json_path": str(request_path),
                    "attempt_json_path": str(attempt_path),
                    "generation_attempt": attempt,
                }
            )
        return plans

    @classmethod
    def _compile_prompt(
        cls,
        inputs: dict[str, Any],
        shot: dict[str, Any],
        bridge_contract: dict[str, Any],
        index: int,
    ) -> str:
        negative_constraints = inputs.get("negative_constraints") or cls._default_negatives()
        join = bridge_contract["joins"][0]
        bridge = join["semantic_bridge"]
        dialogue = str(shot.get("dialogue") or "").strip()
        dialogue_block = (
            "She forms natural Mandarin lip movements for this exact short line: "
            f"\"{dialogue}\". Keep the delivery gentle and realistic. Do not burn subtitles."
            if dialogue
            else "No spoken line is required in this visual segment. Do not burn subtitles."
        )
        camera = shot.get("camera") or (
            "Adult male protagonist first-person eye-level camera, lightly tired natural handheld motion only; "
            "do not reveal the protagonist in any way."
        )
        performance = shot.get("performance") or (
            "Natural restrained acting with one readable emotional change at a time. "
            "Hands move naturally with five correct fingers and relaxed joints."
        )
        orientation = "opening segment" if index == 1 else "continuation segment"
        sections = [
            (
                "format",
                f"A single continuous {int(inputs.get('duration', 15))}-second {inputs.get('ratio', '9:16')} "
                "vertical near-photoreal cinematic live-action scene. Natural 50mm perspective, shallow but believable "
                "depth of field, authentic skin texture and hair strands. No cutaways, no montage, no on-screen text.",
            ),
            (
                "identity_lock",
                "The supplied reference image is the canonical appearance of the only visible adult female character. "
                f"{inputs['canonical_character_description']} Keep her unmistakably the same person: face, hair, hairstyle, "
                "hair accessories, clothing silhouette, age presentation, body scale, and gentle temperament remain consistent. "
                "Do not introduce another person.",
            ),
            (
                "pov_rule",
                "The camera is an adult male protagonist's first-person point of view. Never show his face, body, arms, hands, "
                "shadow, reflection, silhouette, or a second person. Only the adult female character may be visible.",
            ),
            ("scene_lock", str(inputs["scene_lock"])),
            ("story_beat", f"This is the {orientation}. {shot['story_beat']}"),
            (
                "bridge_state",
                f"Bridge object: {bridge['bridge_prop']}. Previous-to-next cause and effect: {bridge['from_action']} then "
                f"{bridge['to_action']}. This shot must end or begin in this state: {shot['bridge_state']}.",
            ),
            ("performance", str(performance)),
            ("dialogue_staging", dialogue_block),
            ("camera", str(camera)),
            (
                "negative_constraints",
                "No " + ", no ".join(str(item) for item in negative_constraints) + ".",
            ),
        ]
        return "\n\n".join(f"[{name}]\n{body}" for name, body in sections)

    @staticmethod
    def _generation_attempt(
        *,
        project_id: str,
        shot_id: str,
        attempt_id: str,
        request_json: dict[str, Any],
        request_path: Path,
        output_path: Path,
        bridge_contract: dict[str, Any],
        index: int,
        cost: float,
    ) -> dict[str, Any]:
        return {
            "version": "1.0",
            "project_id": project_id,
            "pipeline": "narrative-short",
            "shot_id": shot_id,
            "attempt_id": attempt_id,
            "status": "planned",
            "provider": _PROVIDER,
            "model": _MODEL,
            "operation": _OPERATION,
            "prompt": request_json["content"][0]["text"],
            "request_json": request_json,
            "request_json_path": str(request_path),
            "output_path": str(output_path),
            "cost_estimate_usd": cost,
            "cost_actual_usd": None,
            "latency_seconds": None,
            "task_id": None,
            "failure_reason": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "segment_index": index,
                "ratio": request_json["ratio"],
                "resolution": request_json["resolution"],
                "reference_image_count": len(
                    [item for item in request_json["content"] if item.get("role") == "reference_image"]
                ),
                "paid_generation_submitted": False,
                "native_audio_expected": False,
                "bridge_contract_version": bridge_contract.get("version"),
                "requires_visual_review": True,
            },
        }

    @staticmethod
    def _default_negatives() -> list[str]:
        return [
            "anime illustration",
            "plastic CGI skin",
            "cheap cosplay studio look",
            "sexualized pose",
            "cleavage",
            "identity drift",
            "face drift",
            "wardrobe change",
            "extra people",
            "male body",
            "male hands",
            "male shadow",
            "mirror reflection",
            "deformed hands",
            "extra fingers",
            "missing fingers",
            "readable text",
            "logo",
            "watermark",
        ]
