"""Tests for Tencent COS provider-ready media uploads."""

from __future__ import annotations

from pathlib import Path
import sys
import types
from unittest.mock import MagicMock, patch

from tools.base_tool import ToolStatus
from tools.media.tencent_cos_upload import TencentCosUpload


def _env(monkeypatch) -> None:
    monkeypatch.setenv("TENCENT_COS_SECRET_ID", "test-secret-id")
    monkeypatch.setenv("TENCENT_COS_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("TENCENT_COS_BUCKET", "public-cos-1257258774")
    monkeypatch.setenv("TENCENT_COS_REGION", "ap-guangzhou")
    monkeypatch.setenv("TENCENT_COS_PREFIX", "openmontage/")


def test_status_requires_cos_configuration(monkeypatch):
    tool = TencentCosUpload()
    monkeypatch.delenv("TENCENT_COS_SECRET_ID", raising=False)
    monkeypatch.delenv("TENCENT_COS_SECRET_KEY", raising=False)
    monkeypatch.delenv("TENCENT_COS_BUCKET", raising=False)
    assert tool.get_status() == ToolStatus.UNAVAILABLE


def test_object_key_and_public_url_are_deterministic(monkeypatch, tmp_path: Path):
    _env(monkeypatch)
    path = tmp_path / "character reference.png"

    key = TencentCosUpload._object_key(
        {"project_id": "waiting-home-ep01"}, local_path=path
    )
    url = TencentCosUpload._public_url(
        {
            "bucket": "public-cos-1257258774",
            "region": "ap-guangzhou",
            "public_base_url": "",
        },
        key,
    )

    assert key == "openmontage/waiting-home-ep01/character reference.png"
    assert url.endswith("openmontage/waiting-home-ep01/character%20reference.png")


def test_upload_puts_file_and_verifies_anonymous_read(monkeypatch, tmp_path: Path):
    _env(monkeypatch)
    source = tmp_path / "character.png"
    source.write_bytes(b"png-test")

    fake_response = MagicMock(status=200)
    fake_response.headers = {
        "Content-Type": "image/png",
        "Content-Length": str(source.stat().st_size),
    }
    fake_client = MagicMock()
    fake_qcloud = types.ModuleType("qcloud_cos")
    fake_qcloud.CosConfig = MagicMock()
    fake_qcloud.CosS3Client = MagicMock(return_value=fake_client)
    fake_exceptions = types.ModuleType("qcloud_cos.cos_exception")
    fake_exceptions.CosClientError = RuntimeError
    fake_exceptions.CosServiceError = RuntimeError
    with patch.dict(
        sys.modules,
        {"qcloud_cos": fake_qcloud, "qcloud_cos.cos_exception": fake_exceptions},
    ), patch("tools.media.tencent_cos_upload.urlopen", return_value=fake_response):
        fake_response.__enter__.return_value = fake_response
        result = TencentCosUpload().execute(
            {
                "local_path": str(source),
                "project_id": "waiting-home-ep01",
                "overwrite": True,
            }
        )

    assert result.success
    assert result.data["public_read_verified"] is True
    assert result.data["object_key"] == "openmontage/waiting-home-ep01/character.png"
    assert result.data["url"].endswith("openmontage/waiting-home-ep01/character.png")
    fake_client.put_object.assert_called_once()
    assert fake_client.put_object.call_args.kwargs["ContentType"] == "image/png"


def test_upload_fails_before_network_for_missing_file(monkeypatch, tmp_path: Path):
    _env(monkeypatch)
    result = TencentCosUpload().execute({"local_path": str(tmp_path / "missing.png")})
    assert not result.success
    assert "not found" in result.error


def test_csv_credentials_file_supplies_secret_pair(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("TENCENT_COS_SECRET_ID", raising=False)
    monkeypatch.delenv("TENCENT_COS_SECRET_KEY", raising=False)
    monkeypatch.setenv("TENCENT_COS_BUCKET", "public-cos-1257258774")
    credentials = tmp_path / "sub-user.csv"
    credentials.write_text(
        "\ufeffUsername,Password,SecretId,SecretKey,LoginURL\n"
        "u,p,csv-secret-id,csv-secret-key,https://cloud.tencent.com/\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TENCENT_COS_CREDENTIALS_FILE", str(credentials))

    config = TencentCosUpload._resolved_config_values({})

    assert config["secret_id"] == "csv-secret-id"
    assert config["secret_key"] == "csv-secret-key"
    assert config["credentials_file_error"] == ""
    assert TencentCosUpload().get_status() == ToolStatus.AVAILABLE
