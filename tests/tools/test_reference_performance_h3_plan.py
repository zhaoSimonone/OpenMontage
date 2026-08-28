"""Tests for the reference-performance H3 prompt compiler."""

from __future__ import annotations

import json
from pathlib import Path

from schemas.artifacts import validate_artifact
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


def test_plan_rejects_unapproved_appearance_candidates(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["appearance_adaptation"] = {"decision": "CANDIDATES_READY"}

    result = ReferencePerformanceH3Plan().execute(inputs)

    assert result.success is False
    assert "NOT_NEEDED or APPROVED" in result.error


def test_approved_appearance_candidate_replaces_target_reference_url(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["appearance_adaptation"] = {
        "decision": "APPROVED",
        "selected_candidate_id": "appearance_02",
        "style_contract": {
            "target_appearance_prompt": "black tailored jacket, soft cinematic key light"
        },
        "candidates": [
            {
                "candidate_id": "appearance_02",
                "status": "approved",
                "image_path": "projects/reference-performance-test/assets/images/appearance-02.png",
                "image_url": "https://cdn.example.test/approved-appearance.png",
            }
        ],
    }

    result = ReferencePerformanceH3Plan().execute(inputs)

    assert result.success
    assert result.data["request_json"]["content"][1]["image_url"] == (
        "https://cdn.example.test/approved-appearance.png"
    )
    assert "approved appearance adaptation" in result.data["request_json"]["content"][0]["text"]
    assert result.data["generation_attempt"]["metadata"]["appearance_adaptation_selected_candidate_id"] == "appearance_02"
    assert result.data["generation_attempt"]["metadata"]["original_identity_reference_urls"] == [
        "https://cdn.example.test/identity.png"
    ]


def test_explicit_approved_url_cannot_bypass_candidate_approval(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["appearance_adaptation"] = {
        "decision": "APPROVED",
        "selected_candidate_id": "missing",
        "candidates": [],
    }
    inputs["approved_appearance_image_url"] = "https://cdn.example.test/untracked.png"

    result = ReferencePerformanceH3Plan().execute(inputs)

    assert result.success is False
    assert "selected_candidate_id" in result.error


def test_multiple_approved_candidates_are_rejected(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["appearance_adaptation"] = {
        "decision": "APPROVED",
        "selected_candidate_id": "appearance_01",
        "candidates": [
            {
                "candidate_id": "appearance_01",
                "status": "approved",
                "image_url": "https://cdn.example.test/approved-01.png",
            },
            {
                "candidate_id": "appearance_02",
                "status": "approved",
                "image_url": "https://cdn.example.test/approved-02.png",
            },
        ],
    }

    result = ReferencePerformanceH3Plan().execute(inputs)

    assert result.success is False
    assert "exactly one approved candidate" in result.error


def test_approved_candidate_style_contract_is_not_overridden_by_input_wardrobe(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["wardrobe"] = "unrelated wardrobe override"
    inputs["appearance_adaptation"] = {
        "decision": "APPROVED",
        "selected_candidate_id": "appearance_01",
        "style_contract": {"target_appearance_prompt": "approved black tailored jacket"},
        "candidates": [
            {
                "candidate_id": "appearance_01",
                "status": "approved",
                "image_path": "projects/reference-performance-test/assets/images/appearance-01.png",
                "image_url": "https://cdn.example.test/approved-appearance.png",
            }
        ],
    }

    result = ReferencePerformanceH3Plan().execute(inputs)

    assert result.success
    prompt = result.data["request_json"]["content"][0]["text"]
    assert "approved black tailored jacket" in prompt
    assert "unrelated wardrobe override" not in prompt


def test_appearance_adaptation_schema_accepts_candidate_gate_artifact():
    validate_artifact(
        "appearance_adaptation",
        {
            "version": "1.0",
            "project_id": "reference-performance-test",
            "decision": "CANDIDATES_READY",
            "style_mismatch": {
                "detected": True,
                "severity": "major",
                "summary": "The supplied wardrobe does not match the reference performance style.",
                "dimensions": ["wardrobe", "lighting"],
            },
            "style_contract": {
                "adapt": True,
                "preserve_identity": ["face shape", "age", "body proportions"],
                "adapt_attributes": ["wardrobe", "lighting"],
                "exclude_attributes": ["source performer identity", "source watermark"],
                "target_appearance_prompt": "black tailored jacket, soft key light",
            },
            "target_identity": {
                "source_path_or_url": "https://cdn.example.test/identity.png",
                "identity_attributes": ["face shape", "age", "body proportions"],
            },
            "candidates": [
                {
                    "candidate_id": "appearance_01",
                    "status": "candidate",
                    "image_path": "projects/reference-performance-test/assets/images/appearance-01.png",
                    "source_tool": "hairfree_image",
                    "prompt": "Edit only the wardrobe and lighting.",
                    "adapted_attributes": ["wardrobe", "lighting"],
                }
            ],
            "approval": {"human_approved": False, "notes": "Awaiting selection."},
        },
    )
