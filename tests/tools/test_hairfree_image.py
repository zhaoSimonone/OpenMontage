"""Regression tests for the Hairfree GPT Image 2 gateway."""

from __future__ import annotations

import base64
import json
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.content = payload if isinstance(payload, (bytes, bytearray)) else b""
        self.headers = {"content-type": "application/json; charset=utf-8"}
        self.status_code = 200
        self.text = json.dumps(payload) if not isinstance(payload, (bytes, bytearray)) else ""
        self.ok = True

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeRequests:
    def __init__(self, mode: str = "b64"):
        self.mode = mode
        self.downloads: list[str] = []
        self.calls: list[dict[str, object]] = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "headers": headers or {},
                "json": json,
                "timeout": timeout,
            }
        )
        n = json["n"]
        if self.mode == "url":
            payload = {
                "data": [
                    {"url": f"https://cdn.example.test/image_{i}.png"}
                    for i in range(n)
                ]
            }
        else:
            payload = {
                "data": [
                    {"b64_json": base64.b64encode(f"IMAGE_{i}".encode()).decode()}
                    for i in range(n)
                ]
            }
        return _FakeResponse(payload)

    def get(self, url, timeout=None):
        self.downloads.append(url)
        return _FakeResponse(b"")


class _EditRequests:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def post(self, url, headers=None, data=None, files=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "headers": headers or {},
                "json": None,
                "data": data,
                "files": files or [],
                "timeout": timeout,
            }
        )
        payload = {
            "data": [
                {"b64_json": base64.b64encode(b"EDIT_IMAGE").decode()}
            ]
        }
        return _FakeResponse(payload)

    def get(self, url, timeout=None):
        return _FakeResponse(b"")


@pytest.fixture
def hairfree_tool(monkeypatch):
    fake_requests = _FakeRequests()
    fake = types.ModuleType("requests")
    fake.post = fake_requests.post
    fake.get = lambda url, timeout=None: _FakeResponse(b"")
    monkeypatch.setitem(sys.modules, "requests", fake)
    monkeypatch.setenv("HAIRFREE_API_KEY", "test-key")
    from tools.graphics.hairfree_image import HairfreeImage

    return HairfreeImage()


def test_all_requested_images_are_written(hairfree_tool, tmp_path):
    out = tmp_path / "gen.png"
    result = hairfree_tool.execute({"prompt": "p", "n": 4, "output_path": str(out)})

    assert result.success
    assert result.data["images_generated"] == 4
    assert len(result.artifacts) == 4

    files = sorted(tmp_path.glob("*.png"))
    assert len(files) == 4
    contents = {f.read_bytes() for f in files}
    assert contents == {b"IMAGE_0", b"IMAGE_1", b"IMAGE_2", b"IMAGE_3"}


def test_single_image_keeps_exact_output_path(hairfree_tool, tmp_path):
    out = tmp_path / "single.png"
    result = hairfree_tool.execute({"prompt": "p", "n": 1, "output_path": str(out)})

    assert result.success
    assert result.artifacts == [str(out)]
    assert out.read_bytes() == b"IMAGE_0"


def test_url_outputs_are_downloaded(monkeypatch, tmp_path):
    fake_requests = _FakeRequests(mode="url")
    fake = types.ModuleType("requests")
    fake.post = fake_requests.post

    def _download(url, timeout=None):
        fake_requests.downloads.append(url)
        return _FakeResponse(b"DOWNLOAD")

    fake.get = _download
    monkeypatch.setitem(sys.modules, "requests", fake)
    monkeypatch.setenv("HAIRFREE_API_KEY", "test-key")
    from tools.graphics.hairfree_image import HairfreeImage

    tool = HairfreeImage()
    out = tmp_path / "url.png"
    result = tool.execute({"prompt": "p", "n": 2, "output_path": str(out), "output_format": "png"})

    assert result.success
    assert result.data["images_generated"] == 2
    assert fake_requests.downloads == [
        "https://cdn.example.test/image_0.png",
        "https://cdn.example.test/image_1.png",
    ]
    assert (tmp_path / "url_1.png").read_bytes() == b"DOWNLOAD"
    assert (tmp_path / "url_2.png").read_bytes() == b"DOWNLOAD"


def test_edit_mode_uses_multipart_when_image_path_present(monkeypatch, tmp_path):
    fake_requests = _EditRequests()
    fake = types.ModuleType("requests")
    fake.post = fake_requests.post
    fake.get = fake_requests.get
    monkeypatch.setitem(sys.modules, "requests", fake)
    monkeypatch.setenv("HAIRFREE_API_KEY", "test-key")
    from tools.graphics.hairfree_image import HairfreeImage

    source = tmp_path / "source.png"
    source.write_bytes(b"PNGDATA")
    out = tmp_path / "edit.png"

    tool = HairfreeImage()
    result = tool.execute(
        {
            "prompt": "make a refined reference image",
            "generation_mode": "edit",
            "image_path": str(source),
            "output_path": str(out),
            "quality": "low",
        }
    )

    assert result.success
    assert fake_requests.calls[0]["url"].endswith("/images/edits")
    assert fake_requests.calls[0]["json"] is None
    assert len(fake_requests.calls[0]["files"]) == 1
    assert fake_requests.calls[0]["files"][0][0] == "image"
    assert out.read_bytes() == b"EDIT_IMAGE"


def test_edit_mode_accepts_multiple_reference_images(monkeypatch, tmp_path):
    fake_requests = _EditRequests()
    fake = types.ModuleType("requests")
    fake.post = fake_requests.post
    fake.get = fake_requests.get
    monkeypatch.setitem(sys.modules, "requests", fake)
    monkeypatch.setenv("HAIRFREE_API_KEY", "test-key")
    from tools.graphics.hairfree_image import HairfreeImage

    src1 = tmp_path / "ref1.png"
    src2 = tmp_path / "ref2.png"
    src1.write_bytes(b"ONE")
    src2.write_bytes(b"TWO")
    out = tmp_path / "multi.png"

    tool = HairfreeImage()
    result = tool.execute(
        {
            "prompt": "multi reference test",
            "reference_images": [str(src1), str(src2)],
            "output_path": str(out),
            "quality": "low",
        }
    )

    assert result.success
    assert fake_requests.calls[0]["url"].endswith("/images/edits")
    assert len(fake_requests.calls[0]["files"]) == 2
    assert out.read_bytes() == b"EDIT_IMAGE"


def test_status_is_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("HAIRFREE_API_KEY", raising=False)
    from tools.graphics.hairfree_image import HairfreeImage

    assert HairfreeImage().get_status().name == "UNAVAILABLE"
