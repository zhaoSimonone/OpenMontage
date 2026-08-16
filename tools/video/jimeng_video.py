"""Volcengine Jimeng (即梦 AI) video generation via the official API.

Calls the Volcengine visual API directly (visual.volcengineapi.com) using
HMAC-SHA256 V4 request signing with AK/SK credentials. Supports text-to-video
and image-to-video via Jimeng 3.0 models.

API flow: POST submit action -> poll get-result action -> download video_url.

Authentication uses Volcengine IAM V4 signing (not Bearer token), which
requires an Access Key ID (AK) and Secret Access Key (SK) pair from
console.volcengine.com/iam/keymanage.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.parse
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


_HOST = "visual.volcengineapi.com"
_REGION = "cn-north-1"
_SERVICE = "cv"
_ALGORITHM = "HMAC-SHA256"
_GENERIC_API_VERSION = "2022-08-31"
_TI2V_PRO_API_VERSION = "2024-06-06"
_REQ_KEY_TEXT_TO_VIDEO = "jimeng_t2v_v30"
_REQ_KEY_IMAGE_TO_VIDEO = "jimeng_i2v_first_v30"
_MODEL_ACTIONS = {
    "jimeng_t2v_v30": {
        "submit": "JimengT2VV30SubmitTask",
        "get": "JimengT2VV30GetResult",
        "version": _TI2V_PRO_API_VERSION,
        "region": "cn-beijing",
        "signed_headers": ("host", "x-content-sha256", "x-date"),
        "poll_req_json": False,
    },
    "jimeng_i2v_first_v30": {
        "submit": "JimengI2VFirstV30SubmitTask",
        "get": "JimengI2VFirstV30GetResult",
        "version": _TI2V_PRO_API_VERSION,
        "region": "cn-beijing",
        "signed_headers": ("host", "x-content-sha256", "x-date"),
        "poll_req_json": False,
        "omit_aspect_ratio": True,
    },
    "jimeng_i2v_first_tail_v30": {
        "submit": "JimengI2VFirstTailV30SubmitTask",
        "get": "JimengI2VFirstTailV30GetResult",
        "version": _TI2V_PRO_API_VERSION,
        "region": "cn-beijing",
        "signed_headers": ("host", "x-content-sha256", "x-date"),
        "poll_req_json": False,
        "omit_aspect_ratio": True,
    },
    "jimeng_i2v_recamera_v30": {
        "submit": "JimengI2VRecameraV30SubmitTask",
        "get": "JimengI2VRecameraV30GetResult",
        "version": _TI2V_PRO_API_VERSION,
        "region": "cn-beijing",
        "signed_headers": ("host", "x-content-sha256", "x-date"),
        "poll_req_json": False,
        "omit_aspect_ratio": True,
    },
    "jimeng_ti2v_v30_pro": {
        "submit": "JimengTI2VV30PROSubmitTask",
        "get": "JimengTI2VV30PROGetResult",
        "version": _TI2V_PRO_API_VERSION,
        "region": "cn-beijing",
        "signed_headers": ("host", "x-content-sha256", "x-date"),
        "poll_req_json": False,
    },
}


class JimengVideo(BaseTool):
    name = "jimeng_video"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "volcengine"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.ASYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["env:VOLC_ACCESSKEY", "env:VOLC_SECRETKEY"]
    install_instructions = (
        "Set VOLC_ACCESSKEY and VOLC_SECRETKEY to your Volcengine IAM credentials.\n"
        "  Get them at https://console.volcengine.com/iam/keymanage\n"
        "  Ensure your account has access to Jimeng AI (即梦) video generation."
    )
    agent_skills = ["ai-video-gen"]

    capabilities = ["text_to_video", "image_to_video"]
    supports = {
        "text_to_video": True,
        "image_to_video": True,
        "native_audio": False,
        "seed": True,
    }
    best_for = [
        "Jimeng 3.0 text-to-video and image-to-video via Volcengine",
        "direct ByteDance API quota usage (not through a gateway)",
        "Chinese-language prompt understanding",
    ]
    not_good_for = ["offline generation", "users without Volcengine AK/SK"]
    fallback_tools = ["minimax_video", "kling_video", "veo_video"]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {
                "type": "string",
                "maxLength": 800,
                "description": "Video description. Max 800 chars. Supports Chinese.",
            },
            "operation": {
                "type": "string",
                "enum": ["text_to_video", "image_to_video"],
                "default": "text_to_video",
            },
            "image_url": {
                "type": "string",
                "description": (
                    "First frame image URL for image-to-video. "
                    "Must be publicly accessible."
                ),
            },
            "frames": {
                "type": "integer",
                "enum": [121, 241],
                "default": 121,
                "description": "Total frames. 121=5s, 241=10s at 24fps.",
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"],
                "default": "16:9",
            },
            "seed": {
                "type": "integer",
                "minimum": -1,
                "default": -1,
                "description": "Random seed. -1 for random.",
            },
            "output_path": {"type": "string"},
            "poll_interval_seconds": {
                "type": "number",
                "minimum": 2,
                "default": 5.0,
            },
            "timeout_seconds": {
                "type": "integer",
                "minimum": 60,
                "default": 600,
            },
            "req_key": {
                "type": "string",
                "description": (
                    "Optional Volcengine model service identifier. Defaults to "
                    "jimeng_t2v_v30 for text_to_video and jimeng_i2v_first_v30 for image_to_video."
                ),
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=500, network_required=True
    )
    retry_policy = RetryPolicy(
        max_retries=2,
        backoff_seconds=2.0,
        retryable_errors=["rate_limit", "timeout"],
    )
    idempotency_key_fields = [
        "prompt",
        "operation",
        "image_url",
        "frames",
        "aspect_ratio",
        "seed",
        "req_key",
    ]
    side_effects = [
        "writes video file to output_path",
        "calls Volcengine Jimeng API (V4-signed submit + poll + download)",
    ]
    user_visible_verification = [
        "Watch generated clip for motion coherence and prompt adherence",
    ]

    def _ak(self) -> str | None:
        val = os.environ.get("VOLC_ACCESSKEY", "")
        if val and not val.strip().startswith("#"):
            return val.strip()
        return None

    def _sk(self) -> str | None:
        val = os.environ.get("VOLC_SECRETKEY", "")
        if val and not val.strip().startswith("#"):
            return val.strip()
        return None

    def get_status(self) -> ToolStatus:
        if self._ak() and self._sk():
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        frames = int(inputs.get("frames", 121))
        seconds = frames / 24.0
        return round(0.05 * seconds, 2)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 120.0 + int(inputs.get("frames", 121)) * 1.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        ak = self._ak()
        sk = self._sk()
        if not ak or not sk:
            return ToolResult(
                success=False,
                error="VOLC_ACCESSKEY or VOLC_SECRETKEY not set. " + self.install_instructions,
            )

        operation = inputs.get("operation", "text_to_video")
        if operation == "image_to_video" and not inputs.get("image_url"):
            return ToolResult(
                success=False,
                error="image_to_video requires image_url (public URL).",
            )

        start = time.time()
        try:
            result = self._generate(inputs, ak=ak, sk=sk)
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Jimeng video generation failed: {self._safe_error(exc)}",
            )

        result.duration_seconds = round(time.time() - start, 2)
        return result

    def _generate(self, inputs: dict[str, Any], *, ak: str, sk: str) -> ToolResult:
        import requests

        from tools.video._shared import probe_output

        payload = self._build_payload(inputs)
        task_id = self._submit_task(payload, ak=ak, sk=sk)
        video_url = self._poll_task(
            task_id, ak=ak, sk=sk,
            poll_interval=float(inputs.get("poll_interval_seconds", 5.0)),
            timeout_seconds=int(inputs.get("timeout_seconds", 600)),
            req_key=payload["req_key"],
        )

        download = requests.get(video_url, timeout=120)
        download.raise_for_status()

        output_path = Path(inputs.get("output_path", "jimeng_video.mp4"))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(download.content)

        probed = probe_output(output_path)
        return ToolResult(
            success=True,
            data={
                "provider": "volcengine",
                "route": "jimeng_direct",
                "model": payload["req_key"],
                "prompt": inputs["prompt"],
                "operation": inputs.get("operation", "text_to_video"),
                "frames": payload.get("frames", 121),
                "aspect_ratio": payload.get("aspect_ratio", "16:9"),
                "seed": payload.get("seed", -1),
                "task_id": task_id,
                "video_url": video_url,
                "output": str(output_path),
                "format": "mp4",
                **probed,
            },
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
            model=payload["req_key"],
        )

    @staticmethod
    def _duration_to_frames(duration: int) -> int:
        if duration >= 10:
            return 241
        return 121

    @staticmethod
    def _default_req_key(operation: str) -> str:
        if operation == "image_to_video":
            return _REQ_KEY_IMAGE_TO_VIDEO
        return _REQ_KEY_TEXT_TO_VIDEO

    @staticmethod
    def _build_payload(inputs: dict[str, Any]) -> dict[str, Any]:
        operation = inputs.get("operation", "text_to_video")
        frames = inputs.get("frames")
        if frames is None:
            frames = JimengVideo._duration_to_frames(int(inputs.get("duration", 5)))
        payload: dict[str, Any] = {
            "req_key": inputs.get("req_key") or JimengVideo._default_req_key(operation),
            "prompt": inputs["prompt"],
            "frames": int(frames),
            "seed": int(inputs.get("seed", -1)),
        }
        if not JimengVideo._omits_aspect_ratio(payload["req_key"]):
            payload["aspect_ratio"] = inputs.get("aspect_ratio", "16:9")
        if operation == "image_to_video" and inputs.get("image_url"):
            payload["image_urls"] = [inputs["image_url"]]
        return payload

    def _submit_task(self, payload: dict[str, Any], *, ak: str, sk: str) -> str:
        import requests

        query = self._task_query(payload["req_key"], operation="submit")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = self._sign(
            "POST", "/", query, {}, body, ak, sk,
            region=self._signing_region(payload["req_key"]),
            signed_headers=self._signed_headers(payload["req_key"]),
        )
        url = f"https://{_HOST}/?{urllib.parse.urlencode(sorted(query.items()))}"
        resp = requests.post(url, data=body, headers=headers, timeout=30)
        data = self._json_or_raise(resp)
        self._check_code(resp.status_code, data)
        task_id = self._result_data(data).get("task_id")
        if not task_id:
            raise RuntimeError(f"Jimeng submit returned no task_id: {data}")
        return task_id

    def _poll_task(
        self, task_id: str, *, ak: str, sk: str,
        poll_interval: float, timeout_seconds: int, req_key: str,
    ) -> str:
        import requests

        query = self._task_query(req_key, operation="get")
        poll_body = {
            "req_key": req_key,
            "task_id": task_id,
        }
        if self._poll_accepts_req_json(req_key):
            poll_body["req_json"] = json.dumps({"return_url": True})
        body = json.dumps(poll_body, ensure_ascii=False).encode("utf-8")

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            time.sleep(poll_interval)
            headers = self._sign(
                "POST", "/", query, {}, body, ak, sk,
                region=self._signing_region(req_key),
                signed_headers=self._signed_headers(req_key),
            )
            url = f"https://{_HOST}/?{urllib.parse.urlencode(sorted(query.items()))}"
            resp = requests.post(url, data=body, headers=headers, timeout=30)
            data = self._json_or_raise(resp)
            self._check_code(resp.status_code, data)
            result_data = self._result_data(data)
            status = result_data.get("status", "")
            if status == "done":
                video_url = result_data.get("video_url")
                if not video_url:
                    raise RuntimeError(f"Jimeng task done but no video_url: {data}")
                return video_url
            if status in ("not_found", "expired"):
                raise RuntimeError(f"Jimeng task invalid: status={status}")
        raise TimeoutError(f"Jimeng task {task_id} did not finish within {timeout_seconds}s")

    @staticmethod
    def _result_data(payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data")
        if isinstance(data, dict):
            return data
        result = payload.get("Result")
        if isinstance(result, dict):
            nested = result.get("data")
            if isinstance(nested, dict):
                return nested
        return {}

    @staticmethod
    def _task_query(req_key: str, *, operation: str) -> dict[str, str]:
        model_actions = _MODEL_ACTIONS.get(req_key)
        if model_actions:
            return {
                "Action": str(model_actions[operation]),
                "Version": str(model_actions["version"]),
            }
        action = "CVSync2AsyncSubmitTask" if operation == "submit" else "CVSync2AsyncGetResult"
        return {"Action": action, "Version": _GENERIC_API_VERSION}

    @staticmethod
    def _poll_accepts_req_json(req_key: str) -> bool:
        model_actions = _MODEL_ACTIONS.get(req_key)
        if model_actions is None:
            return True
        return bool(model_actions.get("poll_req_json", False))

    @staticmethod
    def _signing_region(req_key: str) -> str:
        model_actions = _MODEL_ACTIONS.get(req_key)
        if model_actions is None:
            return _REGION
        return str(model_actions.get("region", _REGION))

    @staticmethod
    def _signed_headers(req_key: str) -> tuple[str, ...] | None:
        model_actions = _MODEL_ACTIONS.get(req_key)
        if model_actions is None:
            return None
        configured = model_actions.get("signed_headers")
        return tuple(configured) if configured else None

    @staticmethod
    def _omits_aspect_ratio(req_key: str) -> bool:
        model_actions = _MODEL_ACTIONS.get(req_key)
        if model_actions is None:
            return False
        return bool(model_actions.get("omit_aspect_ratio", False))

    @staticmethod
    def _sign(
        method: str, path: str, query_params: dict,
        headers: dict, body: bytes, ak: str, sk: str, *,
        region: str = _REGION,
        signed_headers: tuple[str, ...] | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc)
        x_date = now.strftime("%Y%m%dT%H%M%SZ")
        short_date = x_date[:8]

        body_hash = hashlib.sha256(body).hexdigest()
        headers = dict(headers)
        headers["Host"] = _HOST
        headers["X-Date"] = x_date
        headers["X-Content-Sha256"] = body_hash
        headers["Content-Type"] = "application/json"

        lower_headers = {k.lower(): v.strip() for k, v in headers.items()}
        if signed_headers is None:
            signed_names = sorted(lower_headers)
        else:
            signed_names = sorted(signed_headers)
        canonical_headers = "".join(
            f"{k}:{lower_headers[k]}\n"
            for k in signed_names
        )
        signed_str = ";".join(signed_names)

        canonical_query = "&".join(
            f"{urllib.parse.quote(str(k), safe='')}={urllib.parse.quote(str(v), safe='')}"
            for k, v in sorted(query_params.items())
        )

        canonical_request = "\n".join([
            method.upper(), path, canonical_query,
            canonical_headers, signed_str, body_hash,
        ])

        credential_scope = f"{short_date}/{region}/{_SERVICE}/request"
        string_to_sign = "\n".join([
            _ALGORITHM, x_date, credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ])

        k_date = hmac.new(sk.encode("utf-8"), short_date.encode("utf-8"), hashlib.sha256).digest()
        k_region = hmac.new(k_date, region.encode("utf-8"), hashlib.sha256).digest()
        k_service = hmac.new(k_region, _SERVICE.encode("utf-8"), hashlib.sha256).digest()
        k_signing = hmac.new(k_service, b"request", hashlib.sha256).digest()

        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        headers["Authorization"] = (
            f"{_ALGORITHM} Credential={ak}/{credential_scope}, "
            f"SignedHeaders={signed_str}, Signature={signature}"
        )
        return headers

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        msg = str(exc)
        for var in ("VOLC_SECRETKEY", "VOLC_ACCESSKEY"):
            val = os.environ.get(var, "")
            if val:
                msg = msg.replace(val, "[redacted]")
        return msg

    @staticmethod
    def _json_or_raise(response: Any) -> dict[str, Any]:
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Non-JSON response from Jimeng API: HTTP {response.status_code}"
            ) from exc

    @staticmethod
    def _check_code(http_status: int, payload: dict[str, Any]) -> None:
        if http_status < 400:
            result = payload.get("Result") if isinstance(payload.get("Result"), dict) else {}
            code = payload.get("code", result.get("code", 10000))
            if code == 10000:
                return
            msg = payload.get("message", result.get("message", "unknown error"))
            raise RuntimeError(f"Jimeng API error: code={code}, msg={msg}")
        code = payload.get("code")
        msg = payload.get("message")
        response_meta = payload.get("ResponseMetadata") or {}
        meta_error = response_meta.get("Error") or {}
        code = code or meta_error.get("Code") or meta_error.get("CodeN") or "unknown"
        msg = msg or meta_error.get("Message") or payload.get("Message") or "unknown error"
        raise RuntimeError(f"Jimeng API error: HTTP {http_status}, code={code}, msg={msg}")
