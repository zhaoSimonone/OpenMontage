"""Hairfree.work GPT Image 2 gateway."""

from __future__ import annotations

import base64
import mimetypes
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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


class HairfreeImage(BaseTool):
    name = "hairfree_image"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "image_generation"
    provider = "hairfree"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["env:HAIRFREE_API_KEY"]
    install_instructions = (
        "Set HAIRFREE_API_KEY to your hairfree.work bearer token.\n"
        "  Optional HAIRFREE_API_BASE_URL overrides the API origin (for example, an internal gateway).\n"
        "  Generation endpoint: <base>/v1/images/generations\n"
        "  Edit endpoint: <base>/v1/images/edits"
    )
    agent_skills = ["flux-best-practices"]

    capabilities = [
        "generate_image",
        "edit_image",
        "image_to_image",
        "style_transfer",
        "generate_illustration",
        "text_to_image",
    ]
    supports = {
        "complex_instructions": True,
        "text_in_image": True,
        "multiple_outputs": True,
        "image_edit": True,
        "reference_image": True,
        "multiple_reference_images": True,
    }
    best_for = [
        "OpenAI-compatible GPT Image 2 access via hairfree.work",
        "reference-guided image edits and style transfer",
        "complex multi-element compositions",
        "images with text and labels",
    ]
    not_good_for = ["offline generation", "budget-constrained projects at high quality"]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "generation_mode": {
                "type": "string",
                "enum": ["generate", "edit"],
                "default": "generate",
                "description": "Use 'edit' when providing one or more source images.",
            },
            "model": {
                "type": "string",
                "enum": ["gpt-image-2"],
                "default": "gpt-image-2",
            },
            "size": {
                "type": "string",
                "enum": ["1024x1024", "1536x1024", "1024x1536", "auto"],
                "default": "1024x1024",
            },
            "quality": {
                "type": "string",
                "enum": ["low", "medium", "high", "auto"],
                "default": "high",
            },
            "output_format": {
                "type": "string",
                "enum": ["png", "jpeg", "webp"],
                "default": "png",
            },
            "n": {"type": "integer", "default": 1, "minimum": 1, "maximum": 4},
            "image": {
                "type": "string",
                "description": "Single source image URL, data URI, or local path for edit mode.",
            },
            "image_url": {
                "type": "string",
                "description": "Single source image URL for edit mode.",
            },
            "image_path": {
                "type": "string",
                "description": "Single local source image path for edit mode.",
            },
            "image_urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Multiple source image URLs for edit mode.",
            },
            "image_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Multiple local source image paths for edit mode.",
            },
            "reference_images": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Reference image URLs, data URIs, or local paths for edit or generation mode.",
            },
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=100, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = [
        "prompt",
        "generation_mode",
        "size",
        "quality",
        "model",
        "image",
        "image_url",
        "image_path",
        "image_urls",
        "image_paths",
        "reference_images",
    ]
    side_effects = ["writes image file to output_path", "calls the configured Hairfree-compatible API"]
    user_visible_verification = ["Inspect generated image for relevance and quality"]

    DEFAULT_API_BASE_URL = "https://hairfree.work"

    @classmethod
    def _api_base_url(cls) -> str | None:
        configured = os.environ.get("HAIRFREE_API_BASE_URL")
        return configured.rstrip("/") if configured else None

    @classmethod
    def _endpoint_generate(cls) -> str:
        base_url = cls._api_base_url()
        return (
            f"{base_url}/v1/images/generations"
            if base_url
            else f"{cls.DEFAULT_API_BASE_URL}/images/generations"
        )

    @classmethod
    def _endpoint_edit(cls) -> str:
        base_url = cls._api_base_url()
        return (
            f"{base_url}/v1/images/edits"
            if base_url
            else f"{cls.DEFAULT_API_BASE_URL}/images/edits"
        )

    @staticmethod
    def _output_paths(output_path: str | None, count: int, extension: str) -> list[Path]:
        ext = extension if extension.startswith(".") else f".{extension}"
        if not output_path:
            return [Path(f"generated_image_{idx + 1}{ext}") for idx in range(count)]

        path = Path(output_path)
        suffix = path.suffix or ext
        if count == 1:
            return [path if path.suffix else path.with_suffix(suffix)]

        base = path.with_suffix("") if path.suffix else path
        return [base.parent / f"{base.name}_{idx + 1}{suffix}" for idx in range(count)]

    @staticmethod
    def _infer_extension(output_format: str, item: Any) -> str:
        if isinstance(item, dict):
            url = item.get("url") or item.get("image_url")
            if isinstance(url, str):
                suffix = Path(urlparse(url).path).suffix.lower()
                if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                    return suffix
        return f".{output_format}"

    @staticmethod
    def _extract_outputs(payload: dict[str, Any]) -> list[Any]:
        for key in ("data", "images", "output"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return []

    @staticmethod
    def _is_data_uri(value: str) -> bool:
        return value.startswith("data:") and "," in value

    @staticmethod
    def _decode_data_uri(value: str) -> tuple[bytes, str, str]:
        header, data = value.split(",", 1)
        mime_type = "application/octet-stream"
        if header.startswith("data:"):
            mime_type = header[5:].split(";", 1)[0] or mime_type
        extension = mimetypes.guess_extension(mime_type) or ".png"
        filename = f"reference{extension}"
        return base64.b64decode(data), filename, mime_type

    @staticmethod
    def _load_local_image(path_value: str) -> tuple[bytes, str, str]:
        path = Path(path_value)
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")
        mime_type, _ = mimetypes.guess_type(path.name)
        return path.read_bytes(), path.name, mime_type or "application/octet-stream"

    @staticmethod
    def _load_remote_image(url_value: str) -> tuple[bytes, str, str]:
        import requests

        response = requests.get(url_value, timeout=120)
        response.raise_for_status()
        filename = Path(urlparse(url_value).path).name or "reference.png"
        mime_type = response.headers.get("content-type") or mimetypes.guess_type(filename)[0]
        return response.content, filename, mime_type or "application/octet-stream"

    @classmethod
    def _normalize_image_source(cls, source: Any) -> tuple[bytes, str, str]:
        if isinstance(source, dict):
            for key in ("image_path", "path", "file_path"):
                if source.get(key):
                    return cls._load_local_image(str(source[key]))
            for key in ("image_url", "url"):
                if source.get(key):
                    return cls._load_remote_image(str(source[key]))
            for key in ("image", "data_uri", "data"):
                if source.get(key):
                    value = str(source[key])
                    if cls._is_data_uri(value):
                        return cls._decode_data_uri(value)
                    if value.startswith("http://") or value.startswith("https://"):
                        return cls._load_remote_image(value)
                    return cls._load_local_image(value)
        if isinstance(source, str):
            if cls._is_data_uri(source):
                return cls._decode_data_uri(source)
            if source.startswith("http://") or source.startswith("https://"):
                return cls._load_remote_image(source)
            return cls._load_local_image(source)
        raise TypeError(f"Unsupported image source type: {type(source)!r}")

    @classmethod
    def _collect_reference_sources(cls, inputs: dict[str, Any]) -> list[Any]:
        sources: list[Any] = []
        for key in ("image", "image_url", "image_path"):
            value = inputs.get(key)
            if value:
                sources.append(value)
        for key in ("image_urls", "image_paths", "reference_images"):
            values = inputs.get(key) or []
            sources.extend(values)
        return sources

    @classmethod
    def _has_reference_inputs(cls, inputs: dict[str, Any]) -> bool:
        return bool(cls._collect_reference_sources(inputs))

    @staticmethod
    def _encode_data_uri(data: bytes, mime_type: str) -> str:
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    @classmethod
    def _build_edit_files(
        cls, inputs: dict[str, Any]
    ) -> list[tuple[str, tuple[str, bytes, str]]]:
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        for source in cls._collect_reference_sources(inputs):
            data, filename, mime_type = cls._normalize_image_source(source)
            files.append(("image", (filename, data, mime_type)))
        return files

    @staticmethod
    def _build_generation_payload(inputs: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": inputs.get("model", "gpt-image-2"),
            "prompt": inputs["prompt"],
            "size": inputs.get("size", "1024x1024"),
            "quality": inputs.get("quality", "high"),
            "n": int(inputs.get("n", 1)),
        }
        output_format = inputs.get("output_format", "png")
        if output_format:
            payload["output_format"] = output_format

        # The corporate gateway accepts reference images on the JSON
        # generations endpoint. Normalize local paths and remote URLs to data
        # URIs so the request remains self-contained and provider-readable.
        reference_sources = HairfreeImage._collect_reference_sources(inputs)
        if reference_sources:
            payload["reference_images"] = [
                HairfreeImage._encode_data_uri(
                    *HairfreeImage._normalize_image_source(source)[::2]
                )
                for source in reference_sources
            ]
        return payload

    @classmethod
    def _build_edit_payload_and_files(
        cls, inputs: dict[str, Any]
    ) -> tuple[dict[str, Any], list[tuple[str, tuple[str, bytes, str]]]]:
        files = cls._build_edit_files(inputs)
        if not files:
            raise ValueError("Edit mode requires at least one reference image")
        payload: dict[str, Any] = {
            "model": inputs.get("model", "gpt-image-2"),
            "prompt": inputs["prompt"],
            "size": inputs.get("size", "1024x1024"),
            "quality": inputs.get("quality", "high"),
            "n": str(int(inputs.get("n", 1))),
        }
        output_format = inputs.get("output_format", "png")
        if output_format:
            payload["output_format"] = output_format
        return payload, files

    def get_status(self) -> ToolStatus:
        if os.environ.get("HAIRFREE_API_KEY"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        quality = inputs.get("quality", "high")
        n = inputs.get("n", 1)
        cost_map = {"low": 0.006, "medium": 0.053, "high": 0.211, "auto": 0.053}
        return cost_map.get(quality, 0.053) * n

    def _choose_mode(self, inputs: dict[str, Any]) -> str:
        requested = str(inputs.get("generation_mode", "")).strip().lower()
        if requested in {"generate", "edit"}:
            return requested
        if self._has_reference_inputs(inputs):
            return "edit"
        return "generate"

    def _finalize_image_response(
        self,
        inputs: dict[str, Any],
        data: dict[str, Any],
        requests_module: Any,
        start: float,
    ) -> ToolResult:
        items = self._extract_outputs(data)
        if not items:
            return ToolResult(success=False, error="Hairfree returned no image outputs")

        extension = self._infer_extension(inputs.get("output_format", "png"), items[0])
        output_paths = self._output_paths(inputs.get("output_path"), len(items), extension)
        outputs: list[str] = []
        for item, out_path in zip(items, output_paths):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(item, dict):
                b64_value = (
                    item.get("b64_json")
                    or item.get("base64")
                    or item.get("image_base64")
                )
                image_url = item.get("url") or item.get("image_url")
                if b64_value:
                    out_path.write_bytes(base64.b64decode(b64_value))
                elif image_url:
                    download = requests_module.get(image_url, timeout=120)
                    download.raise_for_status()
                    out_path.write_bytes(download.content)
                else:
                    return ToolResult(success=False, error="Hairfree image output missing data")
            elif isinstance(item, str):
                if item.startswith("http://") or item.startswith("https://"):
                    download = requests_module.get(item, timeout=120)
                    download.raise_for_status()
                    out_path.write_bytes(download.content)
                else:
                    b64_value = item.split(",", 1)[1] if item.startswith("data:") and "," in item else item
                    out_path.write_bytes(base64.b64decode(b64_value))
            else:
                return ToolResult(success=False, error="Unsupported Hairfree image output format")
            outputs.append(str(out_path))

        return ToolResult(
            success=True,
            data={
                "provider": "hairfree",
                "model": inputs.get("model", "gpt-image-2"),
                "prompt": inputs["prompt"],
                "mode": self._choose_mode(inputs),
                "output": outputs[0],
                "outputs": outputs,
                "images_generated": len(outputs),
            },
            artifacts=outputs,
            cost_usd=self.estimate_cost(inputs),
            duration_seconds=round(time.time() - start, 2),
            model=inputs.get("model", "gpt-image-2"),
        )

    def _execute_generation(self, inputs: dict[str, Any], requests_module: Any) -> ToolResult:
        start = time.time()
        payload = self._build_generation_payload(inputs)
        try:
            response = requests_module.post(
                self._endpoint_generate(),
                headers={
                    "Authorization": f"Bearer {os.environ['HAIRFREE_API_KEY']}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=180,
            )
            response.raise_for_status()
            return self._finalize_image_response(inputs, response.json(), requests_module, start)
        except Exception as e:
            return ToolResult(success=False, error=f"Hairfree image generation failed: {e}")

    def _execute_edit(self, inputs: dict[str, Any], requests_module: Any) -> ToolResult:
        start = time.time()
        try:
            payload, files = self._build_edit_payload_and_files(inputs)
            response = requests_module.post(
                self._endpoint_edit(),
                headers={"Authorization": f"Bearer {os.environ['HAIRFREE_API_KEY']}"},
                data=payload,
                files=files,
                timeout=180,
            )
            response.raise_for_status()
            return self._finalize_image_response(inputs, response.json(), requests_module, start)
        except Exception as e:
            return ToolResult(success=False, error=f"Hairfree image edit failed: {e}")

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        api_key = os.environ.get("HAIRFREE_API_KEY")
        if not api_key:
            return ToolResult(
                success=False,
                error="HAIRFREE_API_KEY not set. " + self.install_instructions,
            )

        import requests

        mode = self._choose_mode(inputs)
        if mode == "edit":
            return self._execute_edit(inputs, requests)
        return self._execute_generation(inputs, requests)
