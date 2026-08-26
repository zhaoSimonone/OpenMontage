"""Controlled paid MiniMax-H3 submission for narrative-short projects."""

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


class NarrativeShortGenerator(BaseTool):
    """Submit an explicitly approved planned narrative-short attempt."""

    name = "narrative_short_video_generate"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "narrative_short_generation"
    provider = "openmontage"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies: list[str] = []
    install_instructions = "MiniMax-H3 requires MINIMAX_H3_API_KEY."
    agent_skills = ["ai-video-gen"]
    capabilities = ["narrative_short_generation", "generation_attempt_logging", "approval_gated_generation"]
    supports = {"minimax_h3_primary": True, "human_approval_gate": True, "provider_fallback": False}
    best_for = ["approved MiniMax-H3 narrative-short segments with per-shot audit records"]
    not_good_for = ["silent provider switching", "unapproved paid generation"]

    input_schema = {
        "type": "object",
        "required": ["generation_attempt", "paid_generation_approved"],
        "properties": {
            "generation_attempt": {"type": "object"},
            "attempt_path": {"type": "string"},
            "paid_generation_approved": {"type": "boolean"},
            "output_path": {"type": "string"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=1000, network_required=True)
    retry_policy = RetryPolicy(max_retries=0)
    idempotency_key_fields = ["generation_attempt"]
    side_effects = ["calls metaso.cn MiniMax-H3 API", "writes video output and GenerationAttempt JSON"]
    user_visible_verification = ["Review the completed segment before submitting the next retry."]

    def get_status(self):  # type: ignore[override]
        return MiniMaxH3Video().get_status()

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        attempt = inputs.get("generation_attempt") or {}
        request = attempt.get("request_json") or {}
        return MiniMaxH3Video().estimate_cost(
            {
                "prompt": attempt.get("prompt", "narrative short"),
                "duration": request.get("duration", 15),
                "resolution": request.get("resolution", "768P"),
            }
        )

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        attempt = dict(inputs["generation_attempt"])
        if not bool(inputs.get("paid_generation_approved")):
            return ToolResult(
                success=False,
                error="Paid narrative-short generation requires paid_generation_approved=true.",
            )
        if attempt.get("provider") != "minimax_h3" or attempt.get("model") != "MiniMax-H3":
            return ToolResult(success=False, error="Narrative-short V1 only permits the approved MiniMax-H3 provider.")
        request = attempt.get("request_json")
        if not isinstance(request, dict) or not request.get("content"):
            return ToolResult(success=False, error="GenerationAttempt is missing request_json.content.")

        attempt["status"] = "submitted"
        attempt["metadata"] = {**(attempt.get("metadata") or {}), "paid_generation_submitted": True}
        attempt["submitted_at"] = datetime.now(timezone.utc).isoformat()
        attempt_path = Path(inputs.get("attempt_path") or attempt.get("request_json_path", "")).with_name(
            Path(inputs.get("attempt_path") or attempt.get("request_json_path", "attempt.json")).stem
            .replace("_minimax_h3_request", "_generation_attempt")
            + ".json"
        )
        if inputs.get("attempt_path"):
            attempt_path = Path(str(inputs["attempt_path"]))
        self._write_attempt(attempt_path, attempt)

        result = MiniMaxH3Video().execute(
            {
                "prompt": str(attempt["prompt"]),
                "operation": str(attempt.get("operation") or "reference_to_video"),
                "content": request["content"],
                "duration": request.get("duration", 15),
                "ratio": request.get("ratio", "9:16"),
                "resolution": request.get("resolution", "768P"),
                "aigc_watermark": bool(request.get("aigc_watermark", False)),
                "output_path": str(inputs.get("output_path") or attempt["output_path"]),
            }
        )

        attempt["completed_at"] = datetime.now(timezone.utc).isoformat()
        attempt["latency_seconds"] = result.duration_seconds
        attempt["cost_actual_usd"] = result.cost_usd
        if result.success:
            attempt["status"] = "succeeded"
            attempt["task_id"] = result.data.get("task_id")
            attempt["output_path"] = result.data.get("output", attempt["output_path"])
            attempt["provider_response"] = result.data
            self._write_attempt(attempt_path, attempt)
            return ToolResult(
                success=True,
                data={**result.data, "generation_attempt": attempt, "attempt_path": str(attempt_path)},
                artifacts=[*result.artifacts, str(attempt_path)],
                cost_usd=result.cost_usd,
                duration_seconds=result.duration_seconds,
                model=result.model,
            )

        attempt["status"] = "failed"
        attempt["failure_reason"] = result.error
        self._write_attempt(attempt_path, attempt)
        return ToolResult(
            success=False,
            error=result.error,
            data={"generation_attempt": attempt, "attempt_path": str(attempt_path)},
            artifacts=[str(attempt_path)],
            cost_usd=result.cost_usd,
            duration_seconds=result.duration_seconds,
            model=result.model,
        )

    @staticmethod
    def _write_attempt(path: Path, attempt: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(attempt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
