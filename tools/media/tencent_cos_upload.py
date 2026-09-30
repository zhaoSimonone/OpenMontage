"""Upload local media to Tencent COS and verify its public read URL."""

from __future__ import annotations

import csv
import hashlib
import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

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


class TencentCosUpload(BaseTool):
    """Publish a local asset as an anonymous-readable COS object.

    COS remains private-write/public-read: the SDK signs the PUT request and
    the tool separately verifies the resulting URL without credentials. The
    latter is important because MiniMax-H3 reads the URL from its own servers.
    """

    name = "tencent_cos_upload"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "media_upload"
    provider = "tencent_cos"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.API

    dependencies = [
        "python:qcloud_cos",
        "env:TENCENT_COS_BUCKET",
    ]
    install_instructions = (
        "Install the Tencent COS SDK with `pip install cos-python-sdk-v5`, then set "
        "TENCENT_COS_BUCKET and either TENCENT_COS_SECRET_ID/TENCENT_COS_SECRET_KEY "
        "or TENCENT_COS_CREDENTIALS_FILE pointing to Tencent's credential CSV. "
        "Optionally set TENCENT_COS_REGION/TENCENT_COS_PREFIX in .env."
    )
    capabilities = [
        "upload_image",
        "upload_video",
        "upload_audio",
        "verify_public_read",
        "provider_ready_url",
    ]
    supports = {
        "private_write_public_read_bucket": True,
        "anonymous_provider_read_verification": True,
        "overwrite_protection": True,
        "multipart_upload": False,
    }
    best_for = [
        "preparing local reference images for URL-only video providers",
        "uploading project media to a Tencent COS public-read bucket",
        "verifying that a provider can fetch an asset without login cookies",
    ]
    not_good_for = [
        "public anonymous uploads",
        "large multipart video uploads in the current V1 adapter",
        "storing provider credentials in project artifacts",
    ]
    input_schema = {
        "type": "object",
        "required": ["local_path"],
        "properties": {
            "local_path": {"type": "string", "description": "Local file to upload."},
            "object_key": {
                "type": "string",
                "description": "Explicit COS object key. Defaults to prefix/project_id/basename.",
            },
            "project_id": {"type": "string"},
            "prefix": {"type": "string", "description": "Overrides TENCENT_COS_PREFIX."},
            "content_type": {"type": "string"},
            "verify_public_read": {"type": "boolean", "default": True},
            "overwrite": {"type": "boolean", "default": False},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "bucket": {"type": "string"},
            "region": {"type": "string"},
            "object_key": {"type": "string"},
            "content_type": {"type": "string"},
            "size_bytes": {"type": "integer"},
            "sha256": {"type": "string"},
            "public_read_verified": {"type": "boolean"},
        },
    }
    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=0, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["timeout", "connection"])
    idempotency_key_fields = ["local_path", "object_key", "project_id", "prefix"]
    side_effects = ["uploads a local file to Tencent COS"]
    user_visible_verification = [
        "Anonymous HEAD request returns HTTP 200 with the expected content type and size.",
    ]

    @staticmethod
    def _env(name: str, *aliases: str, default: str = "") -> str:
        for key in (name, *aliases):
            value = os.environ.get(key, "").strip()
            if value:
                return value
        return default

    @classmethod
    def _config_values(cls, inputs: dict[str, Any]) -> dict[str, str]:
        return {
            "secret_id": cls._env("TENCENT_COS_SECRET_ID", "TENCENT_SECRET_ID"),
            "secret_key": cls._env("TENCENT_COS_SECRET_KEY", "TENCENT_SECRET_KEY"),
            "bucket": cls._env("TENCENT_COS_BUCKET"),
            "region": cls._env("TENCENT_COS_REGION", default="ap-guangzhou"),
            "prefix": str(inputs.get("prefix") or cls._env("TENCENT_COS_PREFIX", default="openmontage/")).strip(),
            "public_base_url": cls._env("TENCENT_COS_PUBLIC_BASE_URL"),
        }

    @classmethod
    def _csv_credentials(cls) -> tuple[dict[str, str], str]:
        """Read Tencent's exported sub-user CSV without exposing its secrets."""
        raw_path = cls._env("TENCENT_COS_CREDENTIALS_FILE")
        if not raw_path:
            return {}, ""
        path = Path(raw_path).expanduser()
        if not path.is_file():
            return {}, f"credentials file not found: {path}"
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                row = next(csv.DictReader(stream), None)
        except Exception as exc:
            return {}, f"credentials file could not be read: {type(exc).__name__}"
        if not row:
            return {}, "credentials file has no data row"
        values = {
            "secret_id": str(row.get("SecretId") or row.get("SecretID") or "").strip(),
            "secret_key": str(row.get("SecretKey") or "").strip(),
        }
        missing = []
        if not values["secret_id"]:
            missing.append("SecretId")
        if not values["secret_key"]:
            missing.append("SecretKey")
        if missing:
            return {}, f"credentials file is missing {', '.join(missing)}"
        return values, ""

    @classmethod
    def _resolved_config_values(cls, inputs: dict[str, Any]) -> dict[str, str]:
        config = cls._config_values(inputs)
        file_values, file_error = cls._csv_credentials()
        if not config["secret_id"]:
            config["secret_id"] = file_values.get("secret_id", "")
        if not config["secret_key"]:
            config["secret_key"] = file_values.get("secret_key", "")
        if config["secret_id"] and config["secret_key"]:
            # Explicit env credentials take precedence over a stale optional
            # CSV path, as documented in .env.example.
            file_error = ""
        config["credentials_file_error"] = file_error
        return config

    def get_status(self) -> ToolStatus:
        try:
            self.check_dependencies()
        except Exception:
            return ToolStatus.UNAVAILABLE
        config = self._resolved_config_values({})
        if config.get("credentials_file_error"):
            return ToolStatus.UNAVAILABLE
        if not config.get("secret_id") or not config.get("secret_key"):
            return ToolStatus.UNAVAILABLE
        return ToolStatus.AVAILABLE

    @staticmethod
    def _normalize_prefix(prefix: str) -> str:
        prefix = prefix.strip().strip("/")
        return f"{prefix}/" if prefix else ""

    @classmethod
    def _object_key(cls, inputs: dict[str, Any], *, local_path: Path) -> str:
        explicit = str(inputs.get("object_key") or "").strip().lstrip("/")
        if explicit:
            return explicit
        config = cls._config_values(inputs)
        prefix = cls._normalize_prefix(config["prefix"])
        project_id = str(inputs.get("project_id") or "").strip().strip("/")
        scope = f"{project_id}/" if project_id else ""
        return f"{prefix}{scope}{local_path.name}"

    @staticmethod
    def _public_url(config: dict[str, str], object_key: str) -> str:
        base = config["public_base_url"].rstrip("/") if config["public_base_url"] else (
            f"https://{config['bucket']}.cos.{config['region']}.myqcloud.com"
        )
        encoded_key = "/".join(quote(part, safe="") for part in object_key.split("/"))
        return f"{base}/{encoded_key}"

    @staticmethod
    def _content_type(inputs: dict[str, Any], local_path: Path) -> str:
        explicit = str(inputs.get("content_type") or "").strip()
        if explicit:
            return explicit
        return mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @classmethod
    def _verify_public_read(cls, url: str, *, expected_size: int, expected_type: str) -> None:
        try:
            with urlopen(Request(url, method="HEAD"), timeout=30) as response:
                if response.status != 200:
                    raise RuntimeError(f"provider URL returned HTTP {response.status}")
                content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
                content_length = response.headers.get("Content-Length")
                if expected_type and content_type != expected_type.lower():
                    raise RuntimeError(
                        f"provider URL content type mismatch: expected {expected_type}, got {content_type or 'missing'}"
                    )
                if content_length is not None and int(content_length) != expected_size:
                    raise RuntimeError(
                        f"provider URL size mismatch: expected {expected_size}, got {content_length}"
                    )
        except HTTPError as exc:
            raise RuntimeError(f"provider URL returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"provider URL could not be reached: {exc.reason}") from exc

    @staticmethod
    def _cos_error_detail(exc: Exception, config: dict[str, str]) -> str:
        """Return actionable COS diagnostics while redacting credentials."""
        code = ""
        status = ""
        message = ""
        getter = getattr(exc, "get_error_code", None)
        if callable(getter):
            try:
                code = str(getter() or "")
            except Exception:
                pass
        getter = getattr(exc, "get_status_code", None)
        if callable(getter):
            try:
                status = str(getter() or "")
            except Exception:
                pass
        getter = getattr(exc, "get_error_msg", None)
        if callable(getter):
            try:
                message = str(getter() or "")
            except Exception:
                pass
        if not message:
            message = str(exc)
        for secret in (config.get("secret_id", ""), config.get("secret_key", "")):
            if secret:
                message = message.replace(secret, "[REDACTED]")
        parts = [type(exc).__name__]
        if status:
            parts.append(f"HTTP {status}")
        if code:
            parts.append(f"code={code}")
        if message:
            parts.append(f"message={message[:300]}")
        return ", ".join(parts)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        local_path = Path(str(inputs.get("local_path") or "")).expanduser()
        if not local_path.is_file():
            return ToolResult(success=False, error=f"local_path not found: {local_path}")
        if local_path.stat().st_size == 0:
            return ToolResult(success=False, error=f"local_path is empty: {local_path}")

        config = self._resolved_config_values(inputs)
        if config.get("credentials_file_error"):
            return ToolResult(
                success=False,
                error=f"Tencent COS {config['credentials_file_error']}. {self.install_instructions}",
            )
        missing = [name for name in ("secret_id", "secret_key", "bucket") if not config[name]]
        if missing:
            return ToolResult(
                success=False,
                error=f"Tencent COS configuration missing: {', '.join(missing)}. {self.install_instructions}",
            )

        object_key = self._object_key(inputs, local_path=local_path)
        content_type = self._content_type(inputs, local_path)
        public_url = self._public_url(config, object_key)

        try:
            from qcloud_cos import CosConfig, CosS3Client
            from qcloud_cos.cos_exception import CosClientError, CosServiceError
        except ImportError as exc:
            return ToolResult(
                success=False,
                error=f"Tencent COS SDK is not installed: {exc}. {self.install_instructions}",
            )

        try:
            client = CosS3Client(CosConfig(
                Region=config["region"],
                SecretId=config["secret_id"],
                SecretKey=config["secret_key"],
                Scheme="https",
            ))
            if not bool(inputs.get("overwrite", False)):
                try:
                    client.head_object(Bucket=config["bucket"], Key=object_key)
                    return ToolResult(success=False, error=f"COS object already exists: {object_key}; set overwrite=true to replace it")
                except (CosServiceError, CosClientError) as exc:
                    code = str(getattr(exc, "get_error_code", lambda: "")() or "")
                    if code not in {"NoSuchResource", "NoSuchKey", "NotFound"}:
                        return ToolResult(success=False, error=f"COS preflight failed: {code or type(exc).__name__}")
            with local_path.open("rb") as stream:
                client.put_object(
                    Bucket=config["bucket"],
                    Body=stream,
                    Key=object_key,
                    ContentType=content_type,
                )
            public_verified = bool(inputs.get("verify_public_read", True))
            if public_verified:
                self._verify_public_read(
                    public_url,
                    expected_size=local_path.stat().st_size,
                    expected_type=content_type,
                )
        except (CosServiceError, CosClientError) as exc:
            detail = self._cos_error_detail(exc, config)
            return ToolResult(success=False, error=f"Tencent COS upload failed: {detail}")
        except Exception as exc:
            return ToolResult(success=False, error=f"Tencent COS upload failed: {exc}")

        return ToolResult(
            success=True,
            data={
                "provider": "tencent_cos",
                "bucket": config["bucket"],
                "region": config["region"],
                "object_key": object_key,
                "url": public_url,
                "content_type": content_type,
                "size_bytes": local_path.stat().st_size,
                "sha256": self._sha256(local_path),
                "public_read_verified": public_verified,
            },
            cost_usd=0.0,
        )
