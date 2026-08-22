"""Governed generator for the reference-dance pipeline.

MiniMax-H3 remains the default path.  A reference-dance QA report can request
the Wan 2.2 ComfyUI path after repeated motion failures, but that provider
change is deliberately blocked until the caller supplies human approval.
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
    ToolStatus,
    ToolTier,
)
from tools.video.comfyui_video import ComfyUIVideo
from tools.video.minimax_h3_video import MiniMaxH3Video


_H3_PROVIDER = "minimax_h3"
_COMFY_PROVIDER = "comfyui_video"
_COMFY_MODEL_HINT = "wan2.2"
_FALLBACK_TRIGGER = "consider_fallback_provider"


class ReferenceDanceGenerator(BaseTool):
    """Route a dance generation attempt while preserving the QA gate."""

    name = "reference_dance_video_generate"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "reference_dance_generation"
    provider = "openmontage"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.HYBRID

    dependencies: list[str] = []
    install_instructions = (
        "MiniMax-H3 requires MINIMAX_H3_API_KEY. The Wan 2.2 path requires a "
        "running ComfyUI server and the bundled Wan 2.2 models."
    )
    agent_skills = ["ai-video-gen", "comfyui"]

    capabilities = [
        "reference_dance_generation",
        "qa_gated_provider_routing",
        "generation_attempt_logging",
    ]
    supports = {
        "minimax_h3_primary": True,
        "wan22_fallback": True,
        "human_approval_gate": True,
        "reference_image": True,
        "reference_video": True,
        "camera_lock": True,
        "motion_priority": True,
    }
    best_for = [
        "governed MiniMax-H3 generation for the Rem/Ram dance project",
        "routing repeated motion failures to an approved Wan 2.2 attempt",
        "keeping provider changes and QA evidence in GenerationAttempt logs",
    ]
    not_good_for = [
        "silent provider switching",
        "using a standard Wan I2V workflow as a pose-control guarantee",
    ]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "provider": {
                "type": "string",
                "enum": [_H3_PROVIDER, _COMFY_PROVIDER, "auto"],
                "default": _H3_PROVIDER,
                "description": "Provider to use after the QA gate is evaluated.",
            },
            "operation": {
                "type": "string",
                "enum": ["text_to_video", "image_to_video", "reference_to_video"],
                "default": "reference_to_video",
            },
            "project_id": {"type": "string"},
            "shot_id": {"type": "string", "default": "shot_001"},
            "attempt_id": {"type": "string", "default": "attempt_001"},
            "duration": {"type": "integer", "minimum": 4, "maximum": 15, "default": 15},
            "ratio": {"type": "string", "enum": ["9:16", "16:9", "1:1"], "default": "9:16"},
            "resolution": {"type": "string", "enum": ["768P", "2K"], "default": "768P"},
            "reference_image_path": {"type": "string"},
            "reference_image_url": {"type": "string"},
            "reference_image_urls": {"type": "array", "items": {"type": "string"}},
            "reference_video_url": {"type": "string"},
            "reference_video_urls": {"type": "array", "items": {"type": "string"}},
            "reference_audio_url": {"type": "string"},
            "reference_audio_urls": {"type": "array", "items": {"type": "string"}},
            "content": {"type": "array"},
            "aigc_watermark": {"type": "boolean", "default": False},
            "output_path": {"type": "string"},
            "workflow_json": {"type": "string"},
            "workflow_path": {"type": "string"},
            "output_node": {"type": "string"},
            "workflow_name": {"type": "string"},
            "workflow_model": {"type": "string"},
            "workflow_model_stack": {"type": "array", "items": {"type": "object"}},
            "qa_report": {"type": "object"},
            "qa_report_path": {"type": "string"},
            "fallback_approved": {
                "type": "boolean",
                "default": False,
                "description": "Required before routing a failed H3 motion pass to Wan 2.2.",
            },
            "approve_fallback": {"type": "boolean", "default": False},
            "write_attempt": {"type": "boolean", "default": True},
            "output_attempt_path": {"type": "string"},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "selected_provider": {"type": "string"},
            "selected_tool": {"type": "string"},
            "fallback": {"type": "object"},
            "generation_attempt": {"type": "object"},
            "attempt_json_path": {"type": "string"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=16000, vram_mb=8000, disk_mb=2000)
    retry_policy = RetryPolicy(max_retries=0)
    idempotency_key_fields = [
        "project_id",
        "shot_id",
        "attempt_id",
        "prompt",
        "provider",
        "operation",
        "duration",
        "ratio",
        "reference_image_path",
        "reference_image_url",
        "reference_image_urls",
        "reference_video_url",
        "qa_report_path",
    ]
    side_effects = [
        "delegates to MiniMax-H3 or ComfyUI after the QA/approval gate",
        "writes a GenerationAttempt JSON artifact when write_attempt=true",
    ]
    user_visible_verification = [
        "Confirm the selected provider and fallback approval in the attempt artifact",
        "Run reference_dance_qa after the generated clip is available",
    ]

    def __init__(self) -> None:
        self._providers = {
            _H3_PROVIDER: MiniMaxH3Video(),
            _COMFY_PROVIDER: ComfyUIVideo(),
        }

    def get_status(self) -> ToolStatus:
        if any(tool.get_status() != ToolStatus.UNAVAILABLE for tool in self._providers.values()):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        provider = self._requested_provider(inputs)
        if provider == _COMFY_PROVIDER:
            return 0.0
        return self._providers[_H3_PROVIDER].estimate_cost(inputs)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        provider = self._requested_provider(inputs)
        if provider == _COMFY_PROVIDER:
            return self._providers[_COMFY_PROVIDER].estimate_runtime(self._comfy_inputs(inputs))
        return self._providers[_H3_PROVIDER].estimate_runtime(inputs)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        try:
            qa = self._load_qa(inputs)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return ToolResult(success=False, error=f"Unable to load reference-dance QA report: {exc}")
        fallback = self._fallback_state(inputs, qa)
        requested_provider = self._requested_provider(inputs)

        if fallback["required"] and requested_provider == _H3_PROVIDER:
            requested_provider = _COMFY_PROVIDER

        if requested_provider == _COMFY_PROVIDER and fallback["required"] and not fallback["approved"]:
            attempt = self._attempt_record(
                inputs=inputs,
                provider=_COMFY_PROVIDER,
                model=_COMFY_MODEL_HINT,
                status="approval_required",
                fallback=fallback,
                provider_result=None,
            )
            artifacts = self._write_attempt(inputs, attempt)
            data = {
                "selected_provider": None,
                "selected_tool": None,
                "fallback": fallback,
                "approval_required": True,
                "generation_attempt": attempt,
            }
            if artifacts:
                data["attempt_json_path"] = str(artifacts[0])
            return ToolResult(
                success=False,
                data=data,
                artifacts=[str(path) for path in artifacts],
                error=(
                    "Reference-dance QA requires a provider change to Wan 2.2, "
                    "but fallback_approved=true was not supplied. Review the QA "
                    "report and approve the provider switch before generation."
                ),
            )

        if requested_provider not in self._providers:
            return ToolResult(success=False, error=f"Unknown reference-dance provider: {requested_provider}")

        provider_tool = self._providers[requested_provider]
        provider_inputs = self._comfy_inputs(inputs) if requested_provider == _COMFY_PROVIDER else self._h3_inputs(inputs)
        provider_result = provider_tool.execute(provider_inputs)
        model = provider_result.model or provider_result.data.get("model") or (
            _COMFY_MODEL_HINT if requested_provider == _COMFY_PROVIDER else "MiniMax-H3"
        )
        attempt = self._attempt_record(
            inputs=inputs,
            provider=requested_provider,
            model=model,
            status="succeeded" if provider_result.success else "failed",
            fallback=fallback,
            provider_result=provider_result,
        )
        artifacts = [str(path) for path in self._write_attempt(inputs, attempt)]

        data = dict(provider_result.data)
        data.update(
            {
                "selected_provider": requested_provider,
                "selected_tool": provider_tool.name,
                "fallback": fallback,
                "generation_attempt": attempt,
            }
        )
        if artifacts:
            data["attempt_json_path"] = artifacts[0]
        return ToolResult(
            success=provider_result.success,
            data=data,
            artifacts=[*provider_result.artifacts, *artifacts],
            error=provider_result.error,
            cost_usd=provider_result.cost_usd,
            duration_seconds=provider_result.duration_seconds,
            seed=provider_result.seed,
            model=model,
        )

    def _requested_provider(self, inputs: dict[str, Any]) -> str:
        value = str(inputs.get("provider") or _H3_PROVIDER)
        return _H3_PROVIDER if value == "auto" else value

    @staticmethod
    def _load_qa(inputs: dict[str, Any]) -> dict[str, Any]:
        inline = inputs.get("qa_report")
        if isinstance(inline, dict):
            return inline
        path = inputs.get("qa_report_path")
        if not path:
            return {}
        qa_path = Path(str(path))
        if not qa_path.exists():
            raise FileNotFoundError(f"QA report not found: {qa_path}")
        return json.loads(qa_path.read_text(encoding="utf-8"))

    @staticmethod
    def _fallback_state(inputs: dict[str, Any], qa: dict[str, Any]) -> dict[str, Any]:
        next_action = qa.get("next_action") if isinstance(qa, dict) else {}
        next_action = next_action if isinstance(next_action, dict) else {}
        required = (
            next_action.get("kind") == _FALLBACK_TRIGGER
            and next_action.get("provider") == _COMFY_PROVIDER
        )
        approved = bool(inputs.get("fallback_approved") or inputs.get("approve_fallback"))
        return {
            "required": required,
            "approved": approved,
            "provider": _COMFY_PROVIDER if required else None,
            "model_hint": next_action.get("model_hint") if required else None,
            "reason": next_action.get("reason") if required else None,
            "qa_decision": qa.get("decision") if isinstance(qa, dict) else None,
            "qa_report_path": inputs.get("qa_report_path"),
        }

    @staticmethod
    def _h3_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "prompt", "operation", "model", "resolution", "duration", "ratio", "aspect_ratio",
            "content", "reference_image_url", "first_frame_image_url", "last_frame_image_url",
            "reference_tail_image_url", "reference_image_urls", "reference_video_url",
            "reference_video_urls", "reference_audio_url", "reference_audio_urls", "aigc_watermark",
            "output_path", "poll_interval_seconds", "timeout_seconds", "submit_timeout_seconds",
            "query_timeout_seconds",
        }
        adapted = {key: value for key, value in inputs.items() if key in allowed}
        adapted.setdefault("output_path", ReferenceDanceGenerator._default_output_path(inputs))
        return adapted

    @staticmethod
    def _comfy_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
        ratio = str(inputs.get("ratio") or inputs.get("aspect_ratio") or "9:16")
        dimensions = {
            "9:16": (576, 1024),
            "16:9": (1024, 576),
            "1:1": (768, 768),
        }.get(ratio, (576, 1024))
        duration = int(inputs.get("duration") or 15)
        reference_image_url = inputs.get("reference_image_url")
        if not reference_image_url:
            image_urls = inputs.get("reference_image_urls") or []
            reference_image_url = image_urls[0] if image_urls else None
        operation = "image_to_video" if (inputs.get("reference_image_path") or reference_image_url) else "text_to_video"
        comfy = {
            "prompt": inputs["prompt"],
            "operation": operation,
            "width": int(inputs.get("width") or dimensions[0]),
            "height": int(inputs.get("height") or dimensions[1]),
            "num_frames": int(inputs.get("num_frames") or duration * 16),
            "output_path": inputs.get("output_path") or ReferenceDanceGenerator._default_output_path(inputs),
            "reference_image_path": inputs.get("reference_image_path"),
            "reference_image_url": reference_image_url,
            "workflow_json": inputs.get("workflow_json"),
            "workflow_path": inputs.get("workflow_path"),
            "output_node": inputs.get("output_node"),
            "workflow_name": inputs.get("workflow_name") or "reference-dance-wan22-fallback",
            "workflow_model": inputs.get("workflow_model") or "wan2.2-14b-fp8-4step",
            "workflow_model_stack": inputs.get("workflow_model_stack"),
        }
        return {key: value for key, value in comfy.items() if value is not None}

    @staticmethod
    def _default_output_path(inputs: dict[str, Any]) -> str:
        project_id = str(inputs.get("project_id") or "unknown-project")
        shot_id = str(inputs.get("shot_id") or "shot_001")
        attempt_id = str(inputs.get("attempt_id") or "attempt_001")
        return str(
            Path("projects")
            / project_id
            / "assets"
            / "video"
            / f"{shot_id}_{attempt_id}_reference_dance.mp4"
        )

    @staticmethod
    def _attempt_record(
        *,
        inputs: dict[str, Any],
        provider: str,
        model: str,
        status: str,
        fallback: dict[str, Any],
        provider_result: ToolResult | None,
    ) -> dict[str, Any]:
        data = provider_result.data if provider_result else {}
        output_path = data.get("output") or data.get("output_path") or ReferenceDanceGenerator._default_output_path(inputs)
        return {
            "version": "1.0",
            "project_id": inputs.get("project_id"),
            "pipeline": "reference-dance",
            "shot_id": str(inputs.get("shot_id") or "shot_001"),
            "attempt_id": str(inputs.get("attempt_id") or "attempt_001"),
            "status": status,
            "provider": provider,
            "tool": "comfyui_video" if provider == _COMFY_PROVIDER else "minimax_h3_video",
            "model": model,
            "operation": inputs.get("operation", "reference_to_video"),
            "prompt": inputs.get("prompt"),
            "output_path": output_path,
            "task_id": data.get("task_id"),
            "cost_estimate_usd": 0.0 if provider == _COMFY_PROVIDER else MiniMaxH3Video().estimate_cost(inputs),
            "actual_cost_usd": provider_result.cost_usd if provider_result else 0.0,
            "latency_seconds": provider_result.duration_seconds if provider_result else None,
            "error": provider_result.error if provider_result else None,
            "provider_response": data if provider_result else None,
            "fallback": fallback,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _write_attempt(inputs: dict[str, Any], attempt: dict[str, Any]) -> list[Path]:
        if not bool(inputs.get("write_attempt", True)):
            return []
        path = Path(
            inputs.get("output_attempt_path")
            or Path("projects")
            / str(inputs.get("project_id") or "unknown-project")
            / "artifacts"
            / f"{attempt['shot_id']}_{attempt['attempt_id']}_{attempt['provider']}_generation_attempt.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(attempt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return [path]
