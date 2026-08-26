"""Tests for narrative-short technical and seam-readiness QA."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.analysis.narrative_short_qa import NarrativeShortQA


def _ffmpeg_available() -> bool:
    from shutil import which

    return which("ffmpeg") is not None


def _make_video(path: Path, color: str) -> Path:
    if not _ffmpeg_available():
        pytest.skip("ffmpeg is required for narrative-short QA tests")
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:size=72x128:rate=8",
            "-t", "12", "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return path


def _bridge() -> dict:
    return {
        "version": "1.0",
        "project_id": "qa-test",
        "target_duration_seconds": 24,
        "segments": [
            {"id": "shot_001", "start_seconds": 0, "end_seconds": 12, "purpose": "door", "state": {"character": "door", "key_prop": "bag", "emotion": "expecting", "camera": "POV"}},
            {"id": "shot_002", "start_seconds": 12, "end_seconds": 24, "purpose": "table", "state": {"character": "table", "key_prop": "bag", "emotion": "warm", "camera": "POV"}},
        ],
        "joins": [{"from": "shot_001", "to": "shot_002", "semantic_bridge": {"kind": "prop_cause_effect", "bridge_prop": "bag", "from_action": "carry", "to_action": "place"}, "visual_lock": ["identity"], "transition": {"type": "fade", "duration_seconds": 0.3}, "audio_policy": {"narration_continues": True, "music_crossfades": True, "room_tone_continues": True}}],
    }


def test_qa_writes_frames_and_reports_technical_readiness(tmp_path):
    first = _make_video(tmp_path / "first.mp4", "yellow")
    second = _make_video(tmp_path / "second.mp4", "yellow")
    output = tmp_path / "qa.json"

    result = NarrativeShortQA().execute(
        {
            "project_id": "qa-test",
            "clip_paths": [str(first), str(second)],
            "bridge_contract": _bridge(),
            "output_path": str(output),
            "expected_total_duration_seconds": 24,
            "duration_tolerance_seconds": 1.0,
        }
    )

    assert result.success
    assert result.data["decision"] == "READY_FOR_HUMAN_REVIEW"
    assert len(result.data["review_frames"]) == 6
    assert result.data["seam_readiness"]["technical_readiness_score"] > 0.9
    assert output.exists()


def test_qa_flags_wrong_aspect_ratio(tmp_path):
    first = _make_video(tmp_path / "first.mp4", "yellow")
    bad = tmp_path / "bad.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:size=128x72:rate=8", "-t", "12", "-c:v", "libx264", str(bad)],
        check=True,
        capture_output=True,
        text=True,
    )

    result = NarrativeShortQA().execute(
        {
            "project_id": "qa-test",
            "clip_paths": [str(first), str(bad)],
            "bridge_contract": _bridge(),
            "output_path": str(tmp_path / "qa.json"),
            "expected_total_duration_seconds": 24,
        }
    )

    assert result.success
    assert result.data["decision"] == "REGENERATE_AFFECTED_CLIP"
    assert any("expected 9:16" in issue for issue in result.data["automatic_issues"])
