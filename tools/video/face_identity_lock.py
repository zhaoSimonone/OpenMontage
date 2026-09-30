"""Fail-closed selector contract for temporal face identity locking.

OpenMontage currently has face detection/enhancement tools but no bundled
FaceSwap/FaceFusion video provider. Keeping this selector in the registry makes
the missing capability explicit and gives future providers one stable contract.
"""

from __future__ import annotations

from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


class FaceIdentityLock(BaseTool):
    name = "face_identity_lock"
    version = "0.1.0"
    tier = ToolTier.ENHANCE
    capability = "face_identity_lock"
    provider = "selector"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.HYBRID

    dependencies: list[str] = []
    agent_skills = ["faceswap", "video-edit"]
    capabilities = ["face_identity_lock", "video_face_swap", "provider_selection"]
    supports = {
        "temporal_video": True,
        "reference_face_image": True,
        "preserve_expression": True,
        "preserve_hair_and_clothing": True,
    }
    best_for = [
        "routing to a temporal face identity provider",
        "keeping face locking separate from outfit and hairstyle generation",
    ]
    not_good_for = ["face restoration or generic face enhancement"]
    input_schema = {
        "type": "object",
        "required": ["video_path", "face_reference_path", "output_path"],
        "properties": {
            "video_path": {"type": "string"},
            "face_reference_path": {"type": "string"},
            "output_path": {"type": "string"},
            "preferred_provider": {"type": "string", "default": "auto"},
        },
    }
    output_schema = {"type": "object", "properties": {"output_path": {"type": "string"}}}
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=2048, vram_mb=0, disk_mb=2000, network_required=False)
    idempotency_key_fields = ["video_path", "face_reference_path", "preferred_provider"]
    side_effects = ["would write a face-locked video to output_path when a provider is configured"]
    user_visible_verification = [
        "Verify temporal identity, expression, gaze, occlusion, and hairline stability",
    ]

    def get_status(self) -> ToolStatus:
        return ToolStatus.UNAVAILABLE

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        return ToolResult(
            success=False,
            error=(
                "No temporal face identity provider is configured. "
                "FaceFusion/FaceSwap integration is required; no generic face "
                "enhancer or video-generation fallback was executed."
            ),
        )

