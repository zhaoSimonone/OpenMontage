"""Tests for the reference-performance QA gate."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tools.analysis.reference_performance_qa import ReferencePerformanceQA
from tools.base_tool import ToolResult


def _base_result(path: Path) -> ToolResult:
    return ToolResult(
        success=True,
        data={
            "version": "1.0",
            "project_id": "reference-performance-test",
            "decision": "PASS",
            "output_path": str(path),
            "scores": {"motion": 0.9, "continuity": 1.0},
            "sample_frame_dirs": [],
        },
    )


def _analysis(count: int = 1) -> dict:
    return {
        "reference_video": {"path": "reference.mp4"},
        "beats": [{"beat_id": f"beat_{index:02d}"} for index in range(1, count + 1)],
    }


def test_missing_expression_review_cannot_pass(tmp_path):
    output = tmp_path / "qa.json"
    with patch("tools.analysis.reference_performance_qa.ReferenceDanceQA.execute", return_value=_base_result(output)):
        result = ReferencePerformanceQA().execute(
            {
                "project_id": "reference-performance-test",
                "reference_video_path": str(tmp_path / "reference.mp4"),
                "candidate_video_path": str(tmp_path / "candidate.mp4"),
                "performance_analysis": _analysis(),
                "output_path": str(output),
            }
        )

    assert result.success
    assert result.data["decision"] == "REVIEW_REQUIRED"
    assert result.data["scores"]["expression"] is None
    assert result.data["next_action"]["kind"] == "manual_performance_review"


def test_beat_review_can_clear_expression_gate(tmp_path):
    output = tmp_path / "qa.json"
    manual = {
        "beats": [
            {
                "beat_id": "beat_01",
                "action_score": 0.9,
                "gesture_score": 0.9,
                "expression_score": 0.9,
                "gaze_score": 0.9,
                "head_angle_score": 0.9,
            }
        ]
    }
    with patch("tools.analysis.reference_performance_qa.ReferenceDanceQA.execute", return_value=_base_result(output)):
        result = ReferencePerformanceQA().execute(
            {
                "project_id": "reference-performance-test",
                "reference_video_path": str(tmp_path / "reference.mp4"),
                "candidate_video_path": str(tmp_path / "candidate.mp4"),
                "performance_analysis": _analysis(),
                "manual_review": manual,
                "output_path": str(output),
            }
        )

    assert result.success
    assert result.data["decision"] == "PASS"
    assert result.data["scores"]["action_order"] == 0.9
    assert result.data["scores"]["expression"] == 0.9


def test_partial_beat_review_cannot_clear_expression_gate(tmp_path):
    output = tmp_path / "qa.json"
    manual = {
        "beats": [
            {
                "beat_id": "beat_01",
                "action_score": 0.9,
                "gesture_score": 0.9,
                "expression_score": 0.9,
                "gaze_score": 0.9,
                "head_angle_score": 0.9,
            }
        ]
    }
    with patch("tools.analysis.reference_performance_qa.ReferenceDanceQA.execute", return_value=_base_result(output)):
        result = ReferencePerformanceQA().execute(
            {
                "project_id": "reference-performance-test",
                "reference_video_path": str(tmp_path / "reference.mp4"),
                "candidate_video_path": str(tmp_path / "candidate.mp4"),
                "performance_analysis": _analysis(count=2),
                "manual_review": manual,
                "output_path": str(output),
            }
        )

    assert result.success
    assert result.data["decision"] == "REVIEW_REQUIRED"
    assert result.data["performance_analysis"]["missing_beat_ids"] == ["beat_02"]
