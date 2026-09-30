"""Selector for providers that can edit an existing video clip.

This is intentionally separate from ``video_selector``. A provider that can
generate a video from a reference video is not automatically a provider that
can edit the supplied source clip while preserving unmentioned content.
"""

from __future__ import annotations

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


class VideoEditSelector(BaseTool):
    name = "video_edit_selector"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_edit"
    provider = "selector"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.HYBRID

    dependencies: list[str] = []
    agent_skills = ["gemini-omni", "seedance-2-0", "ai-video-gen"]
    capabilities = ["edit_video", "outfit_edit", "hair_edit", "provider_selection"]
    supports = {
        "existing_video_input": True,
        "strict_source_edit": True,
        "provider_discovery": True,
        "user_preference_routing": True,
    }
    best_for = [
        "routing only to providers that advertise existing-video editing",
        "outfit and hairstyle edit stages with explicit source-preservation prompts",
    ]
    not_good_for = [
        "reference-to-video generation when no source edit capability exists",
        "face identity locking; use face_identity_lock instead",
    ]
    fallback_tools: list[str] = []
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, disk_mb=500, network_required=True)
    idempotency_key_fields = [
        "prompt", "operation", "input_video_path", "previous_interaction_id",
        "reference_image_paths", "preferred_provider",
    ]
    side_effects = [
        "delegates an existing-video edit to a selected provider",
        "writes provider output to output_path",
    ]
    user_visible_verification = [
        "Confirm the selected provider supports edit_video before paid execution",
        "Review matched timestamps against the source video after the edit",
    ]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "operation": {"type": "string", "enum": ["edit_video", "rank"], "default": "edit_video"},
            "input_video_path": {"type": "string"},
            "input_video_url": {"type": "string"},
            "previous_interaction_id": {"type": "string"},
            "reference_image_path": {"type": "string"},
            "reference_image_paths": {"type": "array", "items": {"type": "string"}},
            "reference_image_url": {"type": "string"},
            "reference_image_urls": {"type": "array", "items": {"type": "string"}},
            "reference_video_path": {"type": "string"},
            "reference_video_paths": {"type": "array", "items": {"type": "string"}},
            "reference_video_url": {"type": "string"},
            "reference_video_urls": {"type": "array", "items": {"type": "string"}},
            "reference_audio_path": {"type": "string"},
            "reference_audio_paths": {"type": "array", "items": {"type": "string"}},
            "reference_audio_url": {"type": "string"},
            "reference_audio_urls": {"type": "array", "items": {"type": "string"}},
            "preferred_provider": {"type": "string", "default": "auto"},
            "allowed_providers": {"type": "array", "items": {"type": "string"}},
            "aspect_ratio": {"type": "string"},
            "duration": {"type": "string"},
            "store": {"type": "boolean", "default": True},
            "output_path": {"type": "string"},
        },
    }

    def _providers(self) -> list[BaseTool]:
        from tools.tool_registry import registry

        registry.ensure_discovered()
        providers: list[BaseTool] = []
        for tool in registry.get_by_capability("video_generation"):
            if tool.name == self.name:
                continue
            supports = getattr(tool, "supports", {})
            capabilities = getattr(tool, "capabilities", [])
            if supports.get("edit_video") or "edit_video" in capabilities:
                providers.append(tool)
        return providers

    @staticmethod
    def _provider_label(tool: BaseTool) -> str:
        return f"{tool.provider}/{tool.name}"

    def _rank(self, providers: list[BaseTool], inputs: dict[str, Any]) -> list[dict[str, Any]]:
        ranked: list[dict[str, Any]] = []
        for tool in providers:
            try:
                cost = float(tool.estimate_cost(inputs))
            except Exception:
                cost = 0.0
            ranked.append({
                "tool": tool.name,
                "provider": tool.provider,
                "status": tool.get_status().value,
                "quality_score": tool.quality_score,
                "estimated_cost_usd": round(cost, 4),
                "supports": dict(getattr(tool, "supports", {})),
                "best_for": list(getattr(tool, "best_for", [])),
            })
        ranked.sort(
            key=lambda item: (
                item["status"] == ToolStatus.AVAILABLE.value,
                item["quality_score"] if item["quality_score"] is not None else 0.0,
                -item["estimated_cost_usd"],
            ),
            reverse=True,
        )
        return ranked

    def get_status(self) -> ToolStatus:
        if any(tool.get_status() == ToolStatus.AVAILABLE for tool in self._providers()):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        ranked = self._rank(self._providers(), inputs)
        return float(ranked[0]["estimated_cost_usd"]) if ranked else 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        providers = self._providers()
        if not providers:
            return 0.0
        available = [tool for tool in providers if tool.get_status() == ToolStatus.AVAILABLE]
        return float((available or providers)[0].estimate_runtime(inputs))

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        providers = self._providers()
        if inputs.get("operation", "edit_video") == "rank":
            return ToolResult(success=True, data={
                "operation": "rank",
                "rankings": self._rank(providers, inputs),
                "edit_providers_discovered": len(providers),
            })

        if not inputs.get("previous_interaction_id"):
            input_path = inputs.get("input_video_path")
            input_url = str(inputs.get("input_video_url") or "").strip()
            if not input_path and not input_url:
                return ToolResult(success=False, error="edit_video requires input_video_path or input_video_url")
            if input_path and not Path(str(input_path)).exists():
                return ToolResult(success=False, error=f"Input video not found: {input_path}")

        allowed = set(str(value) for value in inputs.get("allowed_providers") or [])
        if allowed:
            providers = [tool for tool in providers if tool.provider in allowed or tool.name in allowed]

        preferred = str(inputs.get("preferred_provider") or "auto")
        if preferred != "auto":
            selected = next((tool for tool in providers if tool.provider == preferred or tool.name == preferred), None)
            if selected is None:
                return ToolResult(success=False, error=(
                    f"Requested edit provider {preferred!r} is unavailable or does not advertise edit_video. "
                    "No fallback was executed."
                ))
        else:
            ranked = self._rank(providers, inputs)
            selected_name = ranked[0]["tool"] if ranked else None
            selected = next((tool for tool in providers if tool.name == selected_name), None)

        if selected is None:
            return ToolResult(success=False, error=(
                "No provider currently advertises existing-video editing. "
                "Reference-to-video generation is not an automatic substitute."
            ))
        if selected.get_status() != ToolStatus.AVAILABLE:
            return ToolResult(success=False, error=(
                f"Selected edit provider {self._provider_label(selected)} is {selected.get_status().value}; "
                "configure its dependency before execution."
            ))

        adapted = dict(inputs)
        adapted["operation"] = "edit_video"
        result = selected.execute(adapted)
        if result.success:
            result.data.setdefault("selected_tool", selected.name)
            result.data.setdefault("selected_provider", selected.provider)
            result.data.setdefault("edit_capability", "existing_video_edit")
            result.data.setdefault("fallback_tools", [])
        return result
