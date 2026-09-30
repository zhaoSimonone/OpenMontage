from __future__ import annotations

import sys
from pathlib import Path

from tools.base_tool import ToolStatus
from tools.video.seedance_openrouter import OpenRouterSeedance


class FakeResponse:
    def __init__(self, payload=None, *, status_code=200, content=b"", headers=None):
        self._payload = payload
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeRequests:
    def __init__(self, post_responses=None, get_responses=None):
        self.post_responses = list(post_responses or [])
        self.get_responses = list(get_responses or [])
        self.post_calls = []
        self.get_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.post_responses.pop(0)

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.get_responses.pop(0)


def _install_requests(monkeypatch, fake):
    monkeypatch.setitem(sys.modules, "requests", fake)


def _base_inputs(tmp_path):
    return {
        "prompt": "Change only the clothing; preserve the original action and camera.",
        "input_video_url": "https://cdn.example/source.mp4",
        "reference_image_urls": [
            "https://cdn.example/face.png",
            "https://cdn.example/outfit.png",
            "https://cdn.example/hair.png",
        ],
        "duration": "5",
        "resolution": "720p",
        "aspect_ratio": "9:16",
        "generate_audio": False,
        "poll_interval_seconds": 0,
        "timeout_seconds": 5,
        "output_path": str(tmp_path / "edited.mp4"),
    }


def test_openrouter_seedance_status_and_contract(monkeypatch):
    tool = OpenRouterSeedance()
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert tool.get_status() == ToolStatus.UNAVAILABLE
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    assert tool.get_status() == ToolStatus.AVAILABLE
    assert tool.supports["strict_source_edit"] is True
    assert "edit_video" in tool.capabilities


def test_openrouter_seedance_maps_source_and_references(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    fake = FakeRequests(
        post_responses=[FakeResponse({"id": "job-1", "status": "queued"})],
        get_responses=[
            FakeResponse({"id": "job-1", "status": "completed", "unsigned_urls": ["https://cdn.example/result.mp4"]}),
            FakeResponse(content=b"edited video"),
        ],
    )
    _install_requests(monkeypatch, fake)

    result = OpenRouterSeedance().execute(_base_inputs(tmp_path))

    assert result.success, result.error
    payload = fake.post_calls[0][1]["json"]
    assert fake.post_calls[0][0] == "https://openrouter.ai/api/v1/videos"
    assert fake.post_calls[0][1]["headers"]["Authorization"] == "Bearer or-test-key"
    assert payload["model"] == "bytedance/seedance-2.0-mini"
    assert payload["omni_reference_task_type"] == "edit"
    assert payload["input_references"][0] == {
        "type": "video_url",
        "video_url": {"url": "https://cdn.example/source.mp4"},
    }
    assert [item["type"] for item in payload["input_references"][1:]] == [
        "image_url", "image_url", "image_url"
    ]
    assert Path(result.data["output_path"]).read_bytes() == b"edited video"
    assert result.data["usage"] == {}
    assert fake.get_calls[1][1]["headers"]["Authorization"] == "Bearer or-test-key"


def test_openrouter_seedance_content_endpoint_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    fake = FakeRequests(
        post_responses=[FakeResponse({"id": "job-2"})],
        get_responses=[
            FakeResponse({"id": "job-2", "status": "completed"}),
            FakeResponse(content=b"content endpoint video", headers={"Content-Type": "video/mp4"}),
        ],
    )
    _install_requests(monkeypatch, fake)

    result = OpenRouterSeedance().execute(_base_inputs(tmp_path))

    assert result.success, result.error
    assert fake.get_calls[1][0] == "https://openrouter.ai/api/v1/videos/job-2/content?index=0"
    assert fake.get_calls[1][1]["headers"]["Authorization"] == "Bearer or-test-key"
    assert Path(result.data["output_path"]).read_bytes() == b"content endpoint video"


def test_openrouter_seedance_uploads_local_media(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    source = tmp_path / "source.mp4"
    outfit = tmp_path / "outfit.png"
    source.write_bytes(b"video")
    outfit.write_bytes(b"image")

    fake = FakeRequests(
        post_responses=[FakeResponse({"id": "job-3", "status": "completed", "unsigned_urls": ["https://cdn.example/out.mp4"]})],
        get_responses=[FakeResponse(content=b"edited")],
    )
    _install_requests(monkeypatch, fake)
    uploaded = []

    def fake_upload(_self, path_value, inputs):
        uploaded.append(path_value)
        return f"https://upload.example/{Path(path_value).name}"

    monkeypatch.setattr(OpenRouterSeedance, "_upload_local_media", fake_upload)
    inputs = _base_inputs(tmp_path)
    inputs.pop("input_video_url")
    inputs["input_video_path"] = str(source)
    inputs.pop("reference_image_urls")
    inputs["reference_image_paths"] = [str(outfit)]

    result = OpenRouterSeedance().execute(inputs)

    assert result.success, result.error
    assert uploaded == [str(source), str(outfit)]
    refs = fake.post_calls[0][1]["json"]["input_references"]
    assert refs[0]["video_url"]["url"].endswith("source.mp4")
    assert refs[1]["image_url"]["url"].endswith("outfit.png")


def test_openrouter_seedance_errors_redact_api_key(monkeypatch, tmp_path):
    token = "or-secret-key"
    monkeypatch.setenv("OPENROUTER_API_KEY", token)
    fake = FakeRequests(post_responses=[FakeResponse({"error": f"invalid token {token}"}, status_code=401)])
    _install_requests(monkeypatch, fake)

    result = OpenRouterSeedance().execute(_base_inputs(tmp_path))

    assert not result.success
    assert token not in (result.error or "")
    assert "[REDACTED]" in (result.error or "")
