"""Tests for the reference-dance motion / continuity QA tool."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.analysis.reference_dance_qa import ReferenceDanceQA


def _ffmpeg_available() -> bool:
    from shutil import which

    return which("ffmpeg") is not None


def _make_video(path: Path, kind: str) -> Path:
    if not _ffmpeg_available():
        pytest.skip("ffmpeg is required for reference-dance QA tests")

    if kind == "motion":
        source = "testsrc2=size=128x72:rate=8"
    elif kind == "static":
        source = "color=c=red:size=128x72:rate=8"
    else:
        raise ValueError(f"Unknown test video kind: {kind}")

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        source,
        "-t",
        "2",
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    assert path.exists()
    return path


def test_motion_qa_flags_conservative_candidate_and_fallback(tmp_path):
    reference = _make_video(tmp_path / "reference.mp4", "motion")
    candidate = _make_video(tmp_path / "candidate.mp4", "static")
    output_path = tmp_path / "continuity_report.json"

    result = ReferenceDanceQA().execute(
        {
            "project_id": "rem-ram-dance-ep01",
            "reference_video_path": str(reference),
            "candidate_video_path": str(candidate),
            "output_path": str(output_path),
            "failed_motion_attempts": 2,
            "sample_fps": 2.0,
            "max_samples_per_clip": 8,
        }
    )

    assert result.success
    report = result.data
    assert report["decision"] == "REGENERATE"
    assert report["motion_analysis"]["motion_score"] < 0.70
    assert report["continuity_analysis"]["continuity_score"] == 1.0
    assert report["next_action"]["kind"] == "consider_fallback_provider"
    assert report["next_action"]["provider"] == "comfyui_video"
    assert Path(report["output_path"]).exists()


def test_motion_qa_scores_seam_boundaries(tmp_path):
    reference = _make_video(tmp_path / "reference.mp4", "motion")
    clip_a = _make_video(tmp_path / "clip_a.mp4", "motion")
    clip_b = _make_video(tmp_path / "clip_b.mp4", "static")
    output_path = tmp_path / "continuity_report.json"

    result = ReferenceDanceQA().execute(
        {
            "project_id": "rem-ram-dance-ep01",
            "reference_video_path": str(reference),
            "clip_paths": [str(clip_a), str(clip_b)],
            "output_path": str(output_path),
            "sample_fps": 2.0,
            "max_samples_per_clip": 8,
            "seam_window_seconds": 0.2,
        }
    )

    assert result.success
    report = result.data
    assert report["seams_present"] is True
    assert report["seam_review_required"] is True
    assert len(report["continuity_analysis"]["seams"]) == 1
    assert report["continuity_analysis"]["continuity_score"] < 1.0
    assert Path(report["output_path"]).exists()

