"""Seedance 2.0 Mini source-video editing through OpenRouter.

OpenRouter's video endpoint is a URL-based API.  This adapter keeps the
source-video editing contract explicit: the supplied video is always the
first ``input_references`` item and the request declares
``omni_reference_task_type=edit``.  Local media is uploaded through the
existing Tencent COS provider so provider workers can fetch it anonymously.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

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


_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "bytedance/seedance-2.0-mini"
_DEFAULT_DURATION = 5
_DEFAULT_POLL_INTERVAL = 5.0
_DEFAULT_TIMEOUT = 900
# OpenRouter pricing can vary by account and model revision.  This is a
# planning estimate only; the response usage is retained for reconciliation.
_ESTIMATED_COST_PER_SECOND = 0.30
_FINAL_STATUSES = {"completed", "succeeded", "success", "done", "finished"}
_FAILED_STATUSES = {"failed", "failure", "error", "cancelled", "canceled"}
_RATIOS = {"21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}


class OpenRouterSeedance(BaseTool):
    name = "openrouter_seedance"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "openrouter"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["env:OPENROUTER_API_KEY"]
    install_instructions = (
        "Set OPENROUTER_API_KEY to an OpenRouter API key with video access.\n"
        "  Seedance 2.0 Mini uses model bytedance/seedance-2.0-mini.\n"
        "  Local source/reference media also requires a public-read Tencent COS bucket."
    )
    agent_skills = ["seedance-2-0", "ai-video-gen"]

    # This provider intentionally advertises edit_video only.  It must not be
    # selected by the ordinary text/image/reference-to-video selector.
    capabilities = ["edit_video"]
    supports = {
        "edit_video": True,
        "strict_source_edit": True,
        "existing_video_input": True,
        "reference_image": True,
        "reference_video": True,
        "reference_audio": True,
        "multiple_reference_images": True,
        "preserve_source_timing": True,
        "preserve_source_audio": True,
        "native_audio": True,
        "camera_direction": True,
        "aspect_ratio": True,
        "resolution": True,
    }
    best_for = [
        "editing an existing clip while preserving its action, camera, and setting",
        "sequential outfit, hairstyle, and identity edits with image references",
        "Seedance 2.0 Mini through the OpenRouter video API",
    ]
    not_good_for = [
        "offline generation",
        "local media without a publicly readable HTTPS upload URL",
        "assuming provider-side identity locking replaces the final face-lock stage",
    ]
    fallback_tools: list[str] = []
    quality_score = 0.95

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "operation": {"type": "string", "enum": ["edit_video"], "default": "edit_video"},
            "model": {"type": "string", "default": _DEFAULT_MODEL},
            "input_video_path": {"type": "string"},
            "input_video_url": {"type": "string"},
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
            "duration": {"type": "string", "default": str(_DEFAULT_DURATION)},
            "resolution": {"type": "string", "enum": ["480p", "720p"], "default": "720p"},
            "aspect_ratio": {"type": "string", "enum": sorted(_RATIOS), "default": "16:9"},
            "generate_audio": {"type": "boolean", "default": False},
            "poll_interval_seconds": {"type": "number", "default": _DEFAULT_POLL_INTERVAL},
            "timeout_seconds": {"type": "integer", "default": _DEFAULT_TIMEOUT},
            "project_id": {"type": "string"},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=1500, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = [
        "prompt", "model", "input_video_path", "input_video_url", "reference_image_paths",
        "reference_image_urls", "duration", "resolution", "aspect_ratio",
    ]
    side_effects = [
        "uploads local media to Tencent COS when needed",
        "calls the OpenRouter video generation API",
        "writes the completed video to output_path",
    ]
    user_visible_verification = [
        "Confirm the original action, camera, background, timing, and audio remain intact",
        "Review clothing/hair/face changes at matched source timestamps",
        "Reconcile actual provider usage against the planning estimate",
    ]

    @staticmethod
    def _api_key() -> str | None:
        value = os.environ.get("OPENROUTER_API_KEY", "").strip()
        return value or None

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._api_key() else ToolStatus.UNAVAILABLE

    @staticmethod
    def _duration(inputs: dict[str, Any]) -> int:
        raw = str(inputs.get("duration") or _DEFAULT_DURATION).strip().lower()
        raw = raw[:-1] if raw.endswith("s") else raw
        try:
            value = int(float(raw))
        except ValueError:
            value = _DEFAULT_DURATION
        return max(4, min(15, value))

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return round(_ESTIMATED_COST_PER_SECOND * self._duration(inputs), 2)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 180.0 + self._duration(inputs) * 12.0

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://openmontage.local",
            "X-Title": "OpenMontage video character edit",
        }

    @staticmethod
    def _safe_error(error: Any, api_key: str | None = None) -> str:
        text = str(error)
        if api_key:
            text = text.replace(api_key, "[REDACTED]")
        # Be defensive if a requests exception or proxy error includes a
        # bearer token in a URL/header dump.
        import re
        text = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[REDACTED]", text)
        return text[:500]

    @staticmethod
    def _as_list(inputs: dict[str, Any], singular: str, plural: str) -> list[str]:
        values: list[str] = []
        if inputs.get(singular):
            values.append(str(inputs[singular]))
        values.extend(str(value) for value in (inputs.get(plural) or []) if value)
        return values

    def _upload_local_media(self, path_value: str, inputs: dict[str, Any]) -> str:
        from tools.tool_registry import registry

        registry.ensure_discovered()
        uploader = registry.get("tencent_cos_upload")
        if uploader is None:
            raise RuntimeError("tencent_cos_upload is not registered")
        result = uploader.execute({
            "local_path": path_value,
            "project_id": inputs.get("project_id"),
            "verify_public_read": True,
        })
        if not result.success:
            raise RuntimeError(result.error or "Tencent COS upload failed")
        url = result.data.get("url")
        if not url:
            raise RuntimeError("Tencent COS upload returned no public URL")
        return str(url)

    def _resolve_media(self, value: str, inputs: dict[str, Any]) -> str:
        value = str(value).strip()
        if value.startswith("https://") or value.startswith("http://"):
            return value
        path = Path(value).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"media file not found: {path}")
        return self._upload_local_media(str(path), inputs)

    def _build_references(self, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        source_value = inputs.get("input_video_url") or inputs.get("input_video_path")
        if not source_value:
            raise ValueError("edit_video requires input_video_path or input_video_url")

        source_url = self._resolve_media(str(source_value), inputs)
        references: list[dict[str, Any]] = [
            {"type": "video_url", "video_url": {"url": source_url}}
        ]

        image_values = self._as_list(inputs, "reference_image_url", "reference_image_urls")
        image_values += self._as_list(inputs, "reference_image_path", "reference_image_paths")
        video_values = self._as_list(inputs, "reference_video_url", "reference_video_urls")
        video_values += self._as_list(inputs, "reference_video_path", "reference_video_paths")
        audio_values = self._as_list(inputs, "reference_audio_url", "reference_audio_urls")
        audio_values += self._as_list(inputs, "reference_audio_path", "reference_audio_paths")

        if len(image_values) > 9:
            raise ValueError("Seedance allows at most 9 reference images")
        if len(video_values) > 2:
            raise ValueError("Seedance allows at most 3 video references including the source video")
        if len(audio_values) > 3:
            raise ValueError("Seedance allows at most 3 reference audio clips")

        for value in image_values:
            references.append({"type": "image_url", "image_url": {"url": self._resolve_media(value, inputs)}})
        for value in video_values:
            references.append({"type": "video_url", "video_url": {"url": self._resolve_media(value, inputs)}})
        for value in audio_values:
            references.append({"type": "audio_url", "audio_url": {"url": self._resolve_media(value, inputs)}})
        return references

    @staticmethod
    def _json_body(response: Any) -> dict[str, Any]:
        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"OpenRouter returned non-JSON response: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError("OpenRouter returned an unexpected response shape")
        return data

    @classmethod
    def _request_json(cls, requests_mod: Any, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = getattr(requests_mod, method)(url, **kwargs)
        status = int(getattr(response, "status_code", 200))
        data = cls._json_body(response)
        if status < 200 or status >= 300:
            detail = data.get("error") or data.get("message") or data.get("detail") or f"HTTP {status}"
            raise RuntimeError(f"OpenRouter API error ({status}): {detail}")
        return data

    @staticmethod
    def _poll_url(submission: dict[str, Any]) -> str | None:
        value = submission.get("polling_url") or submission.get("poll_url")
        if value:
            return str(value)
        job_id = submission.get("id") or submission.get("job_id") or submission.get("request_id")
        return f"{_BASE_URL}/videos/{job_id}" if job_id else None

    @staticmethod
    def _job_id(payload: dict[str, Any]) -> str | None:
        value = payload.get("id") or payload.get("job_id") or payload.get("request_id")
        return str(value) if value else None

    @staticmethod
    def _output_urls(payload: dict[str, Any]) -> list[str]:
        values = payload.get("unsigned_urls") or payload.get("video_urls") or payload.get("output_urls")
        if isinstance(values, str):
            return [values]
        if isinstance(values, list):
            return [str(value) for value in values if value]
        for key in ("video_url", "output_url"):
            if isinstance(payload.get(key), str):
                return [str(payload[key])]
        return []

    @staticmethod
    def _download(requests_mod: Any, url: str, *, headers: dict[str, str] | None = None) -> bytes:
        response = requests_mod.get(url, headers=headers or {}, timeout=300)
        status = int(getattr(response, "status_code", 200))
        if status < 200 or status >= 300:
            raise RuntimeError(f"video download failed (HTTP {status})")
        content = getattr(response, "content", b"")
        if not content:
            raise RuntimeError("video download returned an empty body")
        return bytes(content)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        api_key = self._api_key()
        if not api_key:
            return ToolResult(success=False, error="OPENROUTER_API_KEY not set. " + self.install_instructions)
        if str(inputs.get("operation", "edit_video")) != "edit_video":
            return ToolResult(success=False, error="openrouter_seedance only supports operation=edit_video")
        prompt = str(inputs.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(success=False, error="prompt is required")

        try:
            references = self._build_references(inputs)
            ratio = str(inputs.get("aspect_ratio") or "16:9")
            if ratio not in _RATIOS:
                raise ValueError(f"aspect_ratio must be one of {sorted(_RATIOS)}")
            resolution = str(inputs.get("resolution") or "720p")
            if resolution not in {"480p", "720p"}:
                raise ValueError("resolution must be 480p or 720p")
            payload = {
                "model": str(inputs.get("model") or _DEFAULT_MODEL),
                "prompt": prompt,
                "duration": self._duration(inputs),
                "resolution": resolution,
                "aspect_ratio": ratio,
                "generate_audio": bool(inputs.get("generate_audio", False)),
                "omni_reference_task_type": "edit",
                "input_references": references,
            }
        except Exception as exc:
            return ToolResult(success=False, error=f"OpenRouter Seedance input preparation failed: {self._safe_error(exc, api_key)}")

        import requests

        start = time.time()
        headers = self._headers(api_key)
        try:
            submission = self._request_json(
                requests, "post", f"{_BASE_URL}/videos", headers=headers, json=payload, timeout=90
            )
            poll_url = self._poll_url(submission)
            job_id = self._job_id(submission)
            if not poll_url:
                raise RuntimeError("OpenRouter response did not include a polling URL or job id")

            interval = max(0.0, float(inputs.get("poll_interval_seconds", _DEFAULT_POLL_INTERVAL)))
            timeout = max(1.0, int(inputs.get("timeout_seconds", _DEFAULT_TIMEOUT)))
            deadline = time.time() + timeout
            state = submission
            while True:
                status = str(state.get("status") or "").strip().lower()
                if status in _FINAL_STATUSES:
                    break
                if status in _FAILED_STATUSES:
                    detail = state.get("error") or state.get("message") or status
                    raise RuntimeError(f"Seedance job {job_id or 'unknown'} failed: {detail}")
                if time.time() >= deadline:
                    raise TimeoutError(f"Seedance job {job_id or 'unknown'} polling timed out")
                if interval:
                    time.sleep(min(interval, max(0.0, deadline - time.time())))
                state = self._request_json(requests, "get", poll_url, headers=headers, timeout=60)

            output_urls = self._output_urls(state)
            output_path = Path(inputs.get("output_path") or "openrouter_seedance_output.mp4")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if output_urls:
                # Some OpenRouter gateways return a signed-looking URL that
                # still requires the API bearer token. Passing the headers is
                # harmless for public URLs and avoids an opaque HTTP 401.
                video_bytes = self._download(requests, output_urls[0], headers=headers)
            else:
                if not job_id:
                    raise RuntimeError("Completed response did not include a video URL or job id")
                content_url = urljoin(f"{_BASE_URL}/videos/{job_id}/", "content?index=0")
                content_response = requests.get(content_url, headers=headers, timeout=300)
                content_status = int(getattr(content_response, "status_code", 200))
                if content_status < 200 or content_status >= 300:
                    raise RuntimeError(f"OpenRouter content download failed (HTTP {content_status})")
                content_type = str(getattr(content_response, "headers", {}).get("Content-Type", ""))
                if "json" in content_type.lower():
                    content_payload = self._json_body(content_response)
                    fallback_urls = self._output_urls(content_payload)
                    if not fallback_urls:
                        raise RuntimeError("OpenRouter content response contained no video URL")
                    video_bytes = self._download(requests, fallback_urls[0], headers=headers)
                else:
                    video_bytes = bytes(getattr(content_response, "content", b""))
                    if not video_bytes:
                        raise RuntimeError("OpenRouter content response was empty")
            output_path.write_bytes(video_bytes)
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"OpenRouter Seedance 2.0 Mini edit failed: {self._safe_error(exc, api_key)}",
                duration_seconds=round(time.time() - start, 2),
            )

        from tools.video._shared import probe_output

        probed = probe_output(output_path)
        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "gateway": "openrouter",
                "model": payload["model"],
                "operation": "edit_video",
                "prompt": prompt,
                "job_id": job_id,
                "polling_url": poll_url,
                "input_references": references,
                "resolution": resolution,
                "aspect_ratio": ratio,
                "duration": payload["duration"],
                "generate_audio": payload["generate_audio"],
                "usage": state.get("usage", {}),
                "output": str(output_path),
                "output_path": str(output_path),
                "format": "mp4",
                **probed,
            },
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
            duration_seconds=round(time.time() - start, 2),
            model=payload["model"],
        )
