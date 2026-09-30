"""MiniMax-H3 video generation through the metaso.cn MiniMax proxy.

MiniMax-H3 uses the V2 video API: submit a task with a multimodal
``content`` array, poll by task id, then download ``task.content.url``.
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


_DEFAULT_API_BASE = "https://metaso.cn/api/minimax"
_MODEL = "MiniMax-H3"
_RATIOS = {"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
_CONCRETE_RATIOS = _RATIOS - {"adaptive"}
_FINAL_STATUSES = {"succeed", "succeeded", "success", "completed", "done", "finish", "finished"}
_FAILED_STATUSES = {"fail", "failed", "cancelled", "canceled", "error"}


class MiniMaxTaskError(RuntimeError):
    """Failure with enough provenance to distinguish API and local phases."""

    def __init__(self, message: str, *, task_id: str | None = None, phase: str = "unknown"):
        super().__init__(message)
        self.task_id = task_id
        self.phase = phase


class MiniMaxH3Video(BaseTool):
    name = "minimax_h3_video"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "minimax_h3"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["env:MINIMAX_H3_API_KEY"]
    install_instructions = (
        "Set MINIMAX_H3_API_KEY to your metaso.cn MiniMax-H3 bearer token.\n"
        "  Optional: set MINIMAX_H3_API_BASE to override the default "
        "https://metaso.cn/api/minimax endpoint."
    )
    agent_skills = ["ai-video-gen"]

    capabilities = ["text_to_video", "image_to_video", "reference_to_video"]
    supports = {
        "text_to_video": True,
        "image_to_video": True,
        "reference_to_video": True,
        "reference_image": True,
        "reference_video": True,
        "reference_audio": True,
        "first_last_frame": True,
        "native_audio": False,
        "camera_direction": True,
        "aspect_ratio": True,
        "watermark": True,
    }
    best_for = [
        "MiniMax-H3 768P/2K video via the metaso.cn proxy",
        "multimodal reference-guided short clips with image, video, and audio URLs",
        "vertical social clips where 9:16 must be explicit",
    ]
    not_good_for = [
        "offline generation",
        "local-only reference video paths; upload media to CDN first",
    ]
    fallback_tools = [
        "seedance_video",
        "jimeng_video",
        "kling_official_video",
        "minimax_video",
    ]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Required text prompt. MiniMax-H3 content must include one non-empty text item.",
            },
            "operation": {
                "type": "string",
                "enum": ["text_to_video", "image_to_video", "reference_to_video"],
                "default": "text_to_video",
            },
            "model": {
                "type": "string",
                "enum": [_MODEL],
                "default": _MODEL,
            },
            "resolution": {
                "type": "string",
                "enum": ["768P", "2K"],
                "default": "768P",
            },
            "duration": {
                "type": "integer",
                "minimum": 4,
                "maximum": 15,
                "default": 5,
            },
            "ratio": {
                "type": "string",
                "enum": sorted(_RATIOS),
                "default": "16:9",
                "description": "Use 9:16 for vertical clips. Text-to-video cannot use adaptive.",
            },
            "aspect_ratio": {
                "type": "string",
                "enum": sorted(_CONCRETE_RATIOS),
                "description": "Alias for ratio used by other OpenMontage tools.",
            },
            "content": {
                "type": "array",
                "description": "Provider-native content override. Must include a non-empty text item.",
            },
            "reference_image_url": {
                "type": "string",
                "description": "First frame image URL for image_to_video, or a reference image for reference_to_video.",
            },
            "first_frame_image_url": {
                "type": "string",
                "description": "First frame image URL for image_to_video.",
            },
            "last_frame_image_url": {
                "type": "string",
                "description": "Last frame image URL for first-and-last-frame video.",
            },
            "reference_tail_image_url": {
                "type": "string",
                "description": "Alias for last_frame_image_url.",
            },
            "reference_image_urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Reference images for multimodal reference-to-video.",
            },
            "reference_video_url": {
                "type": "string",
                "description": "Reference video URL for multimodal reference-to-video.",
            },
            "reference_video_urls": {
                "type": "array",
                "items": {"type": "string"},
            },
            "reference_audio_url": {
                "type": "string",
                "description": "Reference audio URL for multimodal reference-to-video.",
            },
            "reference_audio_urls": {
                "type": "array",
                "items": {"type": "string"},
            },
            "callback_url": {"type": "string"},
            "aigc_watermark": {
                "type": "boolean",
                "default": False,
            },
            "output_path": {"type": "string"},
            "poll_interval_seconds": {
                "type": "number",
                "minimum": 2,
                "default": 10.0,
            },
            "timeout_seconds": {
                "type": "integer",
                "minimum": 60,
                "default": 900,
            },
            "submit_timeout_seconds": {
                "type": "integer",
                "minimum": 60,
                "default": 180,
                "description": "HTTP read timeout for the initial task submission.",
            },
            "query_timeout_seconds": {
                "type": "integer",
                "minimum": 30,
                "default": 60,
                "description": "HTTP read timeout for each task status query.",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=1000, network_required=True
    )
    retry_policy = RetryPolicy(
        max_retries=2,
        backoff_seconds=2.0,
        retryable_errors=["rate_limit", "timeout", "server_error"],
    )
    idempotency_key_fields = [
        "prompt",
        "operation",
        "content",
        "resolution",
        "duration",
        "ratio",
        "aspect_ratio",
        "image_url",
        "reference_image_url",
        "first_frame_image_url",
        "last_frame_image_url",
        "reference_tail_image_url",
        "reference_image_urls",
        "reference_video_url",
        "reference_video_urls",
        "reference_audio_url",
        "reference_audio_urls",
        "aigc_watermark",
    ]
    side_effects = [
        "writes video file to output_path",
        "calls metaso.cn MiniMax-H3 API (submit + poll + download)",
    ]
    user_visible_verification = [
        "Watch generated clip for character consistency, motion quality, and prompt adherence",
    ]
    quality_score = 0.84
    latency_p50_seconds = 180.0

    def _api_key(self) -> str | None:
        return (
            os.environ.get("MINIMAX_H3_API_KEY")
            or os.environ.get("METASO_MINIMAX_API_KEY")
            or os.environ.get("MINIMAX_API_KEY")
        )

    def _api_base(self) -> str:
        return (os.environ.get("MINIMAX_H3_API_BASE") or _DEFAULT_API_BASE).rstrip("/")

    def _submit_url(self) -> str:
        return f"{self._api_base()}/v2/video_generation"

    def _query_url(self, task_id: str) -> str:
        return f"{self._api_base()}/v2/query/video_generation/{task_id}"

    def get_status(self) -> ToolStatus:
        if self._api_key():
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        duration = self._duration(inputs)
        resolution = str(inputs.get("resolution", "768P")).upper()
        rate = 0.13 if resolution == "2K" else 0.08
        return round(duration * rate, 2)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 90.0 + self._duration(inputs) * 18.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        api_key = self._api_key()
        if not api_key:
            return ToolResult(
                success=False,
                error="MINIMAX_H3_API_KEY not set. " + self.install_instructions,
            )

        start = time.time()
        try:
            result = self._generate(inputs, api_key=api_key)
        except MiniMaxTaskError as exc:
            details: dict[str, Any] = {"phase": exc.phase}
            if exc.task_id:
                details["task_id"] = exc.task_id
            provenance = f" (phase={exc.phase}"
            if exc.task_id:
                provenance += f", task_id={exc.task_id}"
            provenance += ")"
            return ToolResult(
                success=False,
                data=details,
                error=f"MiniMax-H3 video generation failed{provenance}: {self._safe_error(exc)}",
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"MiniMax-H3 video generation failed: {self._safe_error(exc)}",
            )

        result.duration_seconds = round(time.time() - start, 2)
        return result

    def _generate(self, inputs: dict[str, Any], *, api_key: str) -> ToolResult:
        import requests

        from tools.video._shared import probe_output

        task_id: str | None = None
        phase = "build_payload"
        try:
            payload = self._build_payload(inputs)
            phase = "submit"
            task_id = self._submit_task(
                payload,
                api_key=api_key,
                timeout_seconds=int(inputs.get("submit_timeout_seconds", 180)),
            )
            phase = "poll"
            task = self._poll_task(
                task_id,
                api_key=api_key,
                poll_interval=float(inputs.get("poll_interval_seconds", 10.0)),
                timeout_seconds=int(inputs.get("timeout_seconds", 900)),
                request_timeout_seconds=int(inputs.get("query_timeout_seconds", 60)),
            )
            phase = "download"
            video_url = self._extract_video_url(task)
            if not video_url:
                raise RuntimeError(f"MiniMax-H3 task succeeded but returned no video URL: {task}")

            download = requests.get(video_url, timeout=180)
            download.raise_for_status()

            output_path = Path(inputs.get("output_path") or f"minimax_h3_{task_id}.mp4")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            # Keep each task's temporary download distinct and publish atomically.
            part_path = output_path.with_name(f"{output_path.name}.{task_id}.part")
            try:
                part_path.write_bytes(download.content)
                probed = probe_output(part_path)
                part_path.replace(output_path)
            finally:
                if part_path.exists():
                    part_path.unlink()
        except MiniMaxTaskError:
            raise
        except Exception as exc:
            raise MiniMaxTaskError(
                self._safe_error(exc), task_id=task_id, phase=phase
            ) from exc

        task_obj = task.get("task", task) if isinstance(task, dict) else {}
        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "route": "metaso_minimax_h3",
                "model": payload["model"],
                "prompt": inputs["prompt"],
                "operation": inputs.get("operation", "text_to_video"),
                "resolution": payload["resolution"],
                "duration": payload["duration"],
                "ratio": payload["ratio"],
                "aigc_watermark": payload.get("aigc_watermark", False),
                "task_id": task_id,
                "task_status": task_obj.get("status"),
                "usage": task_obj.get("usage", {}),
                "video_url": video_url,
                "output": str(output_path),
                "format": "mp4",
                **probed,
            },
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
            model=payload["model"],
        )

    def _submit_task(
        self,
        payload: dict[str, Any],
        *,
        api_key: str,
        timeout_seconds: int = 180,
    ) -> str:
        import requests

        resp = requests.post(
            self._submit_url(),
            headers=self._headers(api_key),
            json=payload,
            timeout=timeout_seconds,
        )
        data = self._json_or_raise(resp)
        self._raise_for_api_error(resp.status_code, data)
        return self._extract_task_id(data)

    def _poll_task(
        self,
        task_id: str,
        *,
        api_key: str,
        poll_interval: float,
        timeout_seconds: int,
        request_timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        import requests

        deadline = time.time() + timeout_seconds
        last_payload: dict[str, Any] = {}
        while time.time() < deadline:
            time.sleep(min(poll_interval, max(0.0, deadline - time.time())))
            resp = requests.get(
                self._query_url(task_id),
                headers=self._headers(api_key),
                timeout=request_timeout_seconds,
            )
            data = self._json_or_raise(resp)
            self._raise_for_api_error(resp.status_code, data)
            last_payload = data
            status = self._extract_status(data)
            if self._extract_video_url(data):
                return data
            if status in _FINAL_STATUSES:
                return data
            if status in _FAILED_STATUSES:
                raise RuntimeError(f"MiniMax-H3 task {task_id} failed: {data}")

        raise TimeoutError(
            f"MiniMax-H3 task {task_id} did not finish within {timeout_seconds}s; "
            f"last response: {last_payload}"
        )

    @classmethod
    def _build_payload(cls, inputs: dict[str, Any]) -> dict[str, Any]:
        content = cls._content(inputs)
        operation = str(inputs.get("operation", "text_to_video"))
        ratio = cls._ratio(inputs, operation=operation, content=content)
        payload: dict[str, Any] = {
            "model": inputs.get("model") or _MODEL,
            "content": content,
            "resolution": cls._resolution(inputs),
            "duration": cls._duration(inputs),
            "ratio": ratio,
        }
        if "callback_url" in inputs and inputs.get("callback_url"):
            payload["callback_url"] = inputs["callback_url"]
        payload["aigc_watermark"] = bool(inputs.get("aigc_watermark", False))
        cls._validate_payload(payload, operation=operation)
        return payload

    @classmethod
    def _content(cls, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        override = inputs.get("content")
        if override is not None:
            if not isinstance(override, list):
                raise ValueError("content override must be a list")
            content = [dict(item) for item in override if isinstance(item, dict)]
            if not cls._has_text(content):
                raise ValueError("content override must include a non-empty text item")
            return content

        prompt = str(inputs.get("prompt", "")).strip()
        if not prompt:
            raise ValueError("prompt is required")

        operation = str(inputs.get("operation", "text_to_video"))
        content = [{"type": "text", "text": prompt}]
        if operation == "text_to_video":
            return content
        if operation == "image_to_video":
            first = (
                inputs.get("first_frame_image_url")
                or inputs.get("reference_image_url")
                or inputs.get("image_url")
            )
            last = inputs.get("last_frame_image_url") or inputs.get("reference_tail_image_url")
            if not first and not last:
                raise ValueError("image_to_video requires first_frame_image_url, reference_image_url, image_url, or last_frame_image_url")
            if first:
                content.append({"type": "image_url", "image_url": str(first), "role": "first_frame"})
            if last:
                content.append({"type": "image_url", "image_url": str(last), "role": "last_frame"})
            return content
        if operation == "reference_to_video":
            for url in cls._urls(inputs, "reference_image_urls", "reference_image_url"):
                content.append({"type": "image_url", "image_url": url, "role": "reference_image"})
            for url in cls._urls(inputs, "reference_video_urls", "reference_video_url"):
                content.append({"type": "video_url", "video_url": url, "role": "reference_video"})
            for url in cls._urls(inputs, "reference_audio_urls", "reference_audio_url"):
                content.append({"type": "audio_url", "audio_url": url, "role": "reference_audio"})
            if len(content) == 1:
                raise ValueError("reference_to_video requires at least one reference image, video, or audio URL")
            return content
        raise ValueError(f"Unsupported MiniMax-H3 operation: {operation}")

    @staticmethod
    def _urls(inputs: dict[str, Any], list_key: str, single_key: str) -> list[str]:
        urls: list[str] = []
        value = inputs.get(list_key)
        if isinstance(value, list):
            urls.extend(str(item) for item in value if item)
        if inputs.get(single_key):
            urls.append(str(inputs[single_key]))
        return urls

    @staticmethod
    def _duration(inputs: dict[str, Any]) -> int:
        raw = inputs.get("duration", 5)
        if isinstance(raw, str):
            raw = raw.strip().rstrip("sS")
        duration = int(raw)
        if duration < 4 or duration > 15:
            raise ValueError("MiniMax-H3 duration must be an integer from 4 to 15 seconds")
        return duration

    @staticmethod
    def _resolution(inputs: dict[str, Any]) -> str:
        resolution = str(inputs.get("resolution", "768P")).upper()
        if resolution in {"768P", "2K"}:
            return resolution
        raise ValueError("MiniMax-H3 resolution must be 768P or 2K")

    @classmethod
    def _ratio(
        cls,
        inputs: dict[str, Any],
        *,
        operation: str,
        content: list[dict[str, Any]],
    ) -> str:
        ratio = str(inputs.get("ratio") or inputs.get("aspect_ratio") or "16:9")
        roles = {str(item.get("role", "")) for item in content}
        has_reference_role = bool(roles & {"reference_image", "reference_video", "reference_audio"})
        has_frame_role = bool(roles & {"first_frame", "last_frame"})
        if operation == "image_to_video" or (has_frame_role and not has_reference_role):
            return "adaptive"
        if ratio not in _RATIOS:
            raise ValueError(f"MiniMax-H3 ratio must be one of {', '.join(sorted(_RATIOS))}")
        if operation == "text_to_video" and ratio == "adaptive":
            raise ValueError("MiniMax-H3 text_to_video requires a concrete ratio, not adaptive")
        return ratio

    @classmethod
    def _validate_payload(cls, payload: dict[str, Any], *, operation: str) -> None:
        if payload.get("model") != _MODEL:
            raise ValueError("MiniMax-H3 provider only supports model=MiniMax-H3")
        content = payload.get("content") or []
        if not cls._has_text(content):
            raise ValueError("MiniMax-H3 content must include one non-empty text item")
        roles = {str(item.get("role", "")) for item in content if isinstance(item, dict)}
        if roles & {"reference_image", "reference_video", "reference_audio"} and roles & {"first_frame", "last_frame"}:
            raise ValueError("MiniMax-H3 cannot mix reference_* roles with first_frame/last_frame roles")
        if operation == "text_to_video" and payload.get("ratio") == "adaptive":
            raise ValueError("MiniMax-H3 text_to_video requires a concrete ratio")

    @staticmethod
    def _has_text(content: list[dict[str, Any]]) -> bool:
        return any(
            item.get("type") == "text" and str(item.get("text", "")).strip()
            for item in content
            if isinstance(item, dict)
        )

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _extract_task_id(payload: dict[str, Any]) -> str:
        task_id = payload.get("task_id") or payload.get("id")
        if not task_id and isinstance(payload.get("data"), dict):
            task_id = payload["data"].get("task_id") or payload["data"].get("id")
        if not task_id and isinstance(payload.get("task"), dict):
            task_id = payload["task"].get("id")
        if not task_id:
            raise RuntimeError(f"MiniMax-H3 create response missing task_id: {payload}")
        return str(task_id)

    @staticmethod
    def _extract_status(payload: dict[str, Any]) -> str:
        task = payload.get("task") if isinstance(payload.get("task"), dict) else payload
        status = task.get("status") if isinstance(task, dict) else None
        if not status and isinstance(payload.get("data"), dict):
            status = payload["data"].get("status")
        return str(status or "").lower()

    @classmethod
    def _extract_video_url(cls, payload: dict[str, Any]) -> str | None:
        task = payload.get("task") if isinstance(payload.get("task"), dict) else payload
        candidates = [
            task.get("video_url") if isinstance(task, dict) else None,
            task.get("url") if isinstance(task, dict) else None,
            task.get("download_url") if isinstance(task, dict) else None,
        ]
        if isinstance(task, dict) and isinstance(task.get("content"), dict):
            candidates.append(task["content"].get("url"))
            candidates.append(task["content"].get("video_url"))
        if isinstance(payload.get("data"), dict):
            candidates.append(cls._extract_video_url(payload["data"]))
        for value in candidates:
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _json_or_raise(response: Any) -> dict[str, Any]:
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Non-JSON response from MiniMax-H3 API: HTTP {response.status_code}"
            ) from exc

    @staticmethod
    def _raise_for_api_error(http_status: int, payload: dict[str, Any]) -> None:
        base_resp = payload.get("base_resp") if isinstance(payload.get("base_resp"), dict) else {}
        base_code = base_resp.get("status_code")
        if http_status < 400 and base_code not in (None, 0, "0") and not payload.get("error"):
            message = base_resp.get("status_msg") or base_resp.get("message") or "unknown error"
            raise RuntimeError(f"MiniMax-H3 API error: HTTP {http_status}, code={base_code}, message={message}")
        if http_status < 400 and not payload.get("error"):
            return
        err = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        err_type = err.get("type") or payload.get("type") or "api_error"
        message = err.get("message") or payload.get("message") or payload.get("msg") or "unknown error"
        request_id = payload.get("request_id")
        suffix = f", request_id={request_id}" if request_id else ""
        raise RuntimeError(f"MiniMax-H3 API error: HTTP {http_status}, type={err_type}, message={message}{suffix}")

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        msg = str(exc)
        for var in ("MINIMAX_H3_API_KEY", "METASO_MINIMAX_API_KEY", "MINIMAX_API_KEY"):
            val = os.environ.get(var, "")
            if val:
                msg = msg.replace(val, "[redacted]")
        return msg
