"""Tests for the reference-performance H3 prompt compiler."""

from __future__ import annotations

import json
from pathlib import Path

from tools.video.reference_performance_h3_plan import ReferencePerformanceH3Plan


def _inputs(tmp_path: Path) -> dict:
    return {
        "project_id": "reference-performance-test",
        "shot_id": "shot_001",
        "attempt_id": "attempt_001",
        "performance_mode": "single_character",
        "duration": 15,
        "ratio": "9:16",
        "resolution": "768P",
        "reference_image_urls": ["https://cdn.example.test/identity.png"],
        "reference_video_url": "https://cdn.example.test/performance.mp4",
        "performance_analysis": {
            "beats": [
                {
                    "beat_id": "beat_01",
                    "start_seconds": 0.0,
                    "end_seconds": 2.5,
                    "action": "right hand rises from chest to cheek",
                    "hand_gesture": "relaxed fingers follow the wrist",
                    "head_angle": "slight left tilt",
                    "gaze": "holds on camera",
                    "expression": "quiet controlled smile",
                    "blink": "one slow blink at the end",
                    "body_weight": "left foot to right foot",
                    "pause_after_seconds": 0.2,
                    "intensity": "moderate",
                }
            ]
        },
        "output_request_path": str(tmp_path / "request.json"),
        "output_attempt_path": str(tmp_path / "attempt.json"),
    }


def test_prompt_contains_action_and_expression_contract(tmp_path):
    result = ReferencePerformanceH3Plan().execute(_inputs(tmp_path))

    assert result.success
    prompt = result.data["request_json"]["content"][0]["text"]
    assert "[performance_transfer]" in prompt
    assert "[timed_performance_beats]" in prompt
    assert "action=right hand rises from chest to cheek" in prompt
    assert "expression=quiet controlled smile" in prompt
    assert "gaze=holds on camera" in prompt
    assert "blink=one slow blink at the end" in prompt
    assert "reference_image" in prompt
    assert result.data["generation_attempt"]["pipeline"] == "reference-performance"
    assert result.data["generation_attempt"]["metadata"]["expression_review_required"] is True


def test_plan_persists_correct_pipeline_attempt(tmp_path):
    result = ReferencePerformanceH3Plan().execute(_inputs(tmp_path))

    attempt = json.loads((tmp_path / "attempt.json").read_text())
    assert attempt["pipeline"] == "reference-performance"
    assert attempt["metadata"]["motion_source_authority"] == "reference_video"
    assert attempt["metadata"]["identity_source_authority"] == "reference_image"


def test_plan_rejects_missing_timed_performance_analysis(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["performance_analysis"] = {}

    result = ReferencePerformanceH3Plan().execute(inputs)

    assert result.success is False
    assert "beats must contain at least one analyzed beat" in result.error
