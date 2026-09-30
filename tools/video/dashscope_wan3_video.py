"""Alibaba Cloud Model Studio Wan 3 video generation via workspace endpoint.

This adapter implements the native asynchronous video-synthesis API shown in
the Wan 3.0 documentation. Media URLs are passed as reference_image,
reference_video, or reference_audio objects in the order supplied by the
caller; the provider keeps task state for 24 hours, so completed output is
downloaded immediately into the project workspace.
"""

from __future__ import annotations

import os
import time
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
from tools.dashscope_utils import dashscope_url


class DashscopeWan3Video(BaseTool):
    name = "dashscope_wan3_video"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "dashscope"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["env:DASHSCOPE_API_KEY"]
    install_instructions = (
        "Set DASHSCOPE_API_KEY and DASHSCOPE_API_BASE to the Alibaba Cloud "
        "Model Studio workspace credentials. The native base should end in /api/v1."
    )
    agent_skills = ["dashscope"]
    capabilities = ["text_to_video", "reference_to_video", "edit_video"]
    supports = {
        "reference_to_video": True,
        "edit_video": True,
        "existing_video_input": True,
        "reference_image": True,
        "reference_video": True,
        "reference_audio": True,
        "preserve_source_background": True,
        "native_audio": True,
    }
    best_for = [
        "Wan 3.0 multimodal reference-video generation through a workspace endpoint",
        "instruction-based character and appearance changes with image/video references",
        "5-30 second vertical clips with asynchronous task polling",
    ]
    not_good_for = ["offline generation", "strict pixel-preserving edits without provider validation"]
    fallback_tools: list[str] = []

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "model": {"type": "string", "default": "wan3.0-video"},
            "operation": {"type": "string", "enum": ["text_to_video", "reference_to_video", "edit_video"], "default": "reference_to_video"},
            "official_minimal": {"type": "boolean", "default": False},
            "media": {"type": "array", "items": {"type": "object"}},
            "resolution": {"type": "string", "default": "480P"},
            "ratio": {"type": "string", "default": "adaptive"},
            "duration": {"type": "integer", "minimum": 2, "maximum": 30, "default": 5},
            "prompt_extend": {"type": "boolean", "default": True},
            "watermark": {"type": "boolean", "default": False},
            "negative_prompt": {"type": "string"},
            "seed": {"type": "integer"},
            "poll_interval_seconds": {"type": "number", "minimum": 5, "default": 15},
            "timeout_seconds": {"type": "integer", "minimum": 60, "default": 900},
            "output_path": {"type": "string"},
            "project_id": {"type": "string"},
        },
    }
    output_schema = {"type": "object", "properties": {"output_path": {"type": "string"}}}
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=1500, network_required=True)
    retry_policy = RetryPolicy(max_retries=1, backoff_seconds=2.0, retryable_errors=["rate_limit", "timeout", "server_error"])
    idempotency_key_fields = ["prompt", "model", "media", "resolution", "ratio", "duration", "prompt_extend", "negative_prompt", "seed"]
    side_effects = ["calls Alibaba Cloud Model Studio Wan video-synthesis API", "writes the completed video to output_path"]
    user_visible_verification = ["Review reference-video motion transfer, face/hair consistency, clothing/background drift, audio, and watermark removal"]
    quality_score = 0.84
    latency_p50_seconds = 240.0

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if os.environ.get("DASHSCOPE_API_KEY", "").strip() else ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        # Wan 3 pricing is workspace/model/resolution dependent; keep planning
        # cost conservative and reconcile from the provider console/task usage.
        return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 180.0 + int(inputs.get("duration", 5)) * 15.0

    @staticmethod
    def _safe_error(error: Any) -> str:
        text = str(error)
        key = os.environ.get("DASHSCOPE_API_KEY", "")
        if key:
            text = text.replace(key, "[REDACTED]")
        return text[:700]

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "Authorization": f"Bearer {os.environ.get('DASHSCOPE_API_KEY', '').strip()}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }

    @staticmethod
    def _json(response: Any) -> dict[str, Any]:
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("DashScope returned an unexpected response shape")
        status = int(getattr(response, "status_code", 200))
        if status < 200 or status >= 300:
            detail = data.get("message") or data.get("error") or data
            raise RuntimeError(f"DashScope API error ({status}): {detail}")
        return data

    @staticmethod
    def _task_id(data: dict[str, Any]) -> str:
        output = data.get("output") if isinstance(data.get("output"), dict) else data
        task_id = output.get("task_id") if isinstance(output, dict) else None
        if not task_id:
            raise RuntimeError(f"DashScope response did not include output.task_id: {data}")
        return str(task_id)

    @staticmethod
    def _status(data: dict[str, Any]) -> str:
        output = data.get("output") if isinstance(data.get("output"), dict) else data
        return str(output.get("task_status", "")).upper() if isinstance(output, dict) else ""

    @staticmethod
    def _video_url(data: dict[str, Any]) -> str | None:
        output = data.get("output") if isinstance(data.get("output"), dict) else data
        value = output.get("video_url") if isinstance(output, dict) else None
        return str(value) if value else None

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if not os.environ.get("DASHSCOPE_API_KEY", "").strip():
            return ToolResult(success=False, error="DASHSCOPE_API_KEY not set. " + self.install_instructions)
        prompt = str(inputs.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(success=False, error="prompt is required")
        operation = str(inputs.get("operation") or "reference_to_video")
        media = inputs.get("media")
        if operation != "text_to_video" and (not isinstance(media, list) or not media):
            return ToolResult(success=False, error="media must be a non-empty array of reference assets")
        if operation == "text_to_video":
            media = []

        import requests

        model = str(inputs.get("model") or "wan3.0-video")
        parameters: dict[str, Any] = {
            "resolution": str(inputs.get("resolution") or ("720P" if model == "wan2.7-videoedit" else "480P")),
        }
        if not bool(inputs.get("official_minimal", False)):
            parameters.update({
                "prompt_extend": bool(inputs.get("prompt_extend", True)),
                "watermark": bool(inputs.get("watermark", False)),
            })
        # VideoEdit infers duration/aspect from the source clip; Wan 3 reference
        # generation requires these explicit controls.
        if model != "wan2.7-videoedit":
            parameters.update({
                "ratio": str(inputs.get("ratio") or "adaptive"),
                "duration": int(inputs.get("duration", 5)),
            })
        input_payload: dict[str, Any] = {"prompt": prompt}
        if media:
            input_payload["media"] = media
        payload: dict[str, Any] = {
            "model": model,
            "input": input_payload,
            "parameters": parameters,
        }
        if inputs.get("negative_prompt"):
            payload["input"]["negative_prompt"] = str(inputs["negative_prompt"])
        if inputs.get("seed") is not None:
            payload["parameters"]["seed"] = int(inputs["seed"])

        start = time.time()
        try:
            submit = self._json(requests.post(dashscope_url("services/aigc/video-generation/video-synthesis"), headers=self._headers(), json=payload, timeout=90))
            task_id = self._task_id(submit)
            deadline = time.time() + max(60, int(inputs.get("timeout_seconds", 900)))
            state = submit
            while time.time() < deadline:
                status = self._status(state)
                if status == "SUCCEEDED":
                    break
                if status in {"FAILED", "UNKNOWN"}:
                    output = state.get("output") if isinstance(state.get("output"), dict) else state
                    raise RuntimeError(f"Wan task {task_id} ended with {status}: {output}")
                time.sleep(max(5.0, float(inputs.get("poll_interval_seconds", 15))))
                state = self._json(requests.get(dashscope_url(f"tasks/{task_id}"), headers=self._headers(), timeout=60))
            else:
                raise TimeoutError(f"Wan task {task_id} did not finish before timeout")

            video_url = self._video_url(state)
            if not video_url:
                raise RuntimeError(f"Wan task {task_id} succeeded but returned no video_url")
            download = requests.get(video_url, timeout=300)
            if int(getattr(download, "status_code", 200)) >= 300:
                raise RuntimeError(f"Wan video download failed (HTTP {download.status_code})")
            output_path = Path(inputs.get("output_path") or "dashscope_wan3_output.mp4")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(download.content)
        except Exception as exc:
            return ToolResult(success=False, error=f"DashScope Wan 3 video generation failed: {self._safe_error(exc)}", duration_seconds=round(time.time() - start, 2))

        from tools.video._shared import probe_output

        probed = probe_output(output_path)
        output = state.get("output") if isinstance(state.get("output"), dict) else state
        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "model": payload["model"],
                "operation": operation,
                "task_id": task_id,
                "task_status": self._status(state),
                "video_url": video_url,
                "output": str(output_path),
                "usage": output.get("usage", {}) if isinstance(output, dict) else {},
                "request_id": state.get("request_id"),
                **probed,
            },
            artifacts=[str(output_path)],
            cost_usd=0.0,
            duration_seconds=round(time.time() - start, 2),
            model=payload["model"],
        )
