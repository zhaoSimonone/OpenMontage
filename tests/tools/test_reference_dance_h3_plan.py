"""Tests for reference-dance MiniMax-H3 planning."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.base_tool import ToolStatus
from tools.video.reference_dance_h3_plan import ReferenceDanceH3Plan


def _inputs(tmp_path: Path) -> dict:
    return {
        "project_id": "rem-ram-dance-ep01",
        "shot_id": "shot_001",
        "attempt_id": "attempt_001",
        "duration": 15,
        "ratio": "9:16",
        "resolution": "768P",
        "reference_image_urls": [
            "https://cdn.example.test/pair.png",
            "https://cdn.example.test/wardrobe.png",
        ],
        "reference_video_url": "https://cdn.example.test/dance.mp4",
        "output_request_path": str(tmp_path / "request.json"),
        "output_attempt_path": str(tmp_path / "attempt.json"),
    }


def test_planner_is_available_without_api_key(monkeypatch):
    monkeypatch.delenv("MINIMAX_H3_API_KEY", raising=False)
    assert ReferenceDanceH3Plan().get_status() == ToolStatus.AVAILABLE


def test_writes_h3_request_and_generation_attempt(tmp_path):
    tool = ReferenceDanceH3Plan()
    result = tool.execute(_inputs(tmp_path))

    assert result.success
    assert result.cost_usd == 0.0
    assert result.data["estimated_cost_usd"] == 1.2
    assert result.artifacts == [
        str(tmp_path / "request.json"),
        str(tmp_path / "attempt.json"),
    ]

    request = json.loads((tmp_path / "request.json").read_text())
    attempt = json.loads((tmp_path / "attempt.json").read_text())

    assert request["model"] == "MiniMax-H3"
    assert request["duration"] == 15
    assert request["ratio"] == "9:16"
    assert request["resolution"] == "768P"
    assert [item.get("role", "text") for item in request["content"]] == [
        "text",
        "reference_image",
        "reference_image",
        "reference_video",
    ]
    assert attempt["status"] == "planned"
    assert attempt["provider"] == "minimax_h3"
    assert attempt["operation"] == "reference_to_video"
    assert attempt["metadata"]["paid_generation_submitted"] is False
    assert attempt["metadata"]["one_shot"] is True


def test_prompt_contains_p0_controls(tmp_path):
    result = ReferenceDanceH3Plan().execute(_inputs(tmp_path))
    prompt = result.data["request_json"]["content"][0]["text"]

    assert "[subject_mapping]" in prompt
    assert "Character 1 always maps to the left performer" in prompt
    assert "Character 2 always maps to the right performer" in prompt
    assert "[camera_lock]" in prompt
    assert "Full-body two-shot" in prompt
    assert "Both feet remain visible" in prompt
    assert "Motion is the priority" in prompt
    assert "no hospital room" in prompt
    assert "no first-person POV" in prompt


def test_reference_audio_role_is_optional(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["reference_audio_url"] = "https://cdn.example.test/audio.wav"

    result = ReferenceDanceH3Plan().execute(inputs)

    assert result.success
    roles = [item.get("role", "text") for item in result.data["request_json"]["content"]]
    assert roles[-1] == "reference_audio"
    assert result.data["generation_attempt"]["metadata"]["has_reference_audio"] is True


def test_write_files_can_be_disabled(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["write_files"] = False

    result = ReferenceDanceH3Plan().execute(inputs)

    assert result.success
    assert result.artifacts == []
    assert not (tmp_path / "request.json").exists()
    assert not (tmp_path / "attempt.json").exists()
