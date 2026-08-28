"""Tests for QA-gated reference-dance provider routing."""

from __future__ import annotations

import json
from pathlib import Path

from tools.base_tool import ToolResult
from tools.video.reference_dance_generator import ReferenceDanceGenerator


class _FakeProvider:
    def __init__(self, name: str, model: str, *, success: bool = True) -> None:
        self.name = name
        self.model = model
        self.success = success
        self.calls: list[dict] = []

    def get_status(self):
        from tools.base_tool import ToolStatus

        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs):
        return 1.2 if self.name == "minimax_h3_video" else 0.0

    def estimate_runtime(self, inputs):
        return 10.0

    def execute(self, inputs):
        self.calls.append(inputs)
        return ToolResult(
            success=self.success,
            data={
                "model": self.model,
                "task_id": "fake-task" if self.success else None,
                "output": inputs.get("output_path"),
            },
            artifacts=[],
            cost_usd=1.2 if self.name == "minimax_h3_video" else 0.0,
            duration_seconds=0.2,
            model=self.model,
            error=None if self.success else "fake failure",
        )


def _router():
    router = ReferenceDanceGenerator()
    h3 = _FakeProvider("minimax_h3_video", "MiniMax-H3")
    comfy = _FakeProvider("comfyui_video", "wan2.2-14b-fp8-4step")
    router._providers = {"minimax_h3": h3, "comfyui_video": comfy}
    return router, h3, comfy


def _inputs(tmp_path: Path) -> dict:
    return {
        "project_id": "rem-ram-dance-ep01",
        "shot_id": "shot_001",
        "attempt_id": "attempt_002",
        "prompt": "Two women perform the locked reference dance in a full-body 9:16 shot.",
        "duration": 15,
        "ratio": "9:16",
        "output_path": str(tmp_path / "candidate.mp4"),
        "output_attempt_path": str(tmp_path / "attempt.json"),
    }


def _fallback_qa() -> dict:
    return {
        "decision": "REGENERATE",
        "next_action": {
            "kind": "consider_fallback_provider",
            "provider": "comfyui_video",
            "model_hint": "wan2.2",
            "reason": "H3 motion did not clear the pass line after repeated attempts.",
        },
    }


def test_h3_is_the_default_route_and_is_logged(tmp_path):
    router, h3, comfy = _router()
    result = router.execute(_inputs(tmp_path))

    assert result.success
    assert result.data["selected_provider"] == "minimax_h3"
    assert len(h3.calls) == 1
    assert comfy.calls == []
    attempt = json.loads((tmp_path / "attempt.json").read_text())
    assert attempt["provider"] == "minimax_h3"
    assert attempt["status"] == "succeeded"


def test_pipeline_name_is_preserved_in_generation_attempt(tmp_path):
    router, h3, _ = _router()
    inputs = _inputs(tmp_path)
    inputs["pipeline_name"] = "reference-performance"

    result = router.execute(inputs)

    assert result.success
    attempt = json.loads((tmp_path / "attempt.json").read_text())
    assert attempt["pipeline"] == "reference-performance"


def test_missing_output_path_uses_project_video_directory(tmp_path):
    router, h3, _ = _router()
    inputs = _inputs(tmp_path)
    inputs.pop("output_path")

    result = router.execute(inputs)

    assert result.success
    assert h3.calls[0]["output_path"] == (
        "projects/rem-ram-dance-ep01/assets/video/"
        "shot_001_attempt_002_reference_dance.mp4"
    )
    attempt = json.loads((tmp_path / "attempt.json").read_text())
    assert attempt["output_path"].startswith("projects/rem-ram-dance-ep01/assets/video/")


def test_fallback_requires_explicit_approval_and_does_not_call_provider(tmp_path):
    router, h3, comfy = _router()
    inputs = _inputs(tmp_path)
    inputs["qa_report"] = _fallback_qa()

    result = router.execute(inputs)

    assert not result.success
    assert result.data["approval_required"] is True
    assert result.data["fallback"]["required"] is True
    assert h3.calls == []
    assert comfy.calls == []
    attempt = json.loads((tmp_path / "attempt.json").read_text())
    assert attempt["status"] == "approval_required"
    assert attempt["fallback"]["provider"] == "comfyui_video"


def test_approved_fallback_routes_to_wan22_comfyui_with_vertical_i2v(tmp_path):
    router, h3, comfy = _router()
    inputs = _inputs(tmp_path)
    inputs.update(
        {
            "provider": "auto",
            "qa_report": _fallback_qa(),
            "fallback_approved": True,
            "reference_image_url": "https://cdn.example.test/rem-ram.png",
        }
    )

    result = router.execute(inputs)

    assert result.success
    assert result.data["selected_provider"] == "comfyui_video"
    assert h3.calls == []
    assert len(comfy.calls) == 1
    assert comfy.calls[0]["operation"] == "image_to_video"
    assert (comfy.calls[0]["width"], comfy.calls[0]["height"]) == (576, 1024)
    assert comfy.calls[0]["num_frames"] == 240
    attempt = json.loads((tmp_path / "attempt.json").read_text())
    assert attempt["provider"] == "comfyui_video"
    assert attempt["model"] == "wan2.2-14b-fp8-4step"
    assert attempt["fallback"]["approved"] is True


def test_invalid_qa_report_is_a_tool_failure(tmp_path):
    router, _, _ = _router()
    inputs = _inputs(tmp_path)
    inputs["qa_report_path"] = str(tmp_path / "missing.json")

    result = router.execute(inputs)

    assert not result.success
    assert "QA report" in (result.error or "")
