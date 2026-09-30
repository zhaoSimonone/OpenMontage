"""Contracts for the source-video character-edit pipeline."""

from __future__ import annotations

from lib.pipeline_loader import get_required_tools, get_stage_order, load_pipeline
from schemas.artifacts import validate_artifact
from tools.analysis.video_character_edit_qa import VideoCharacterEditQA
from tools.video.face_identity_lock import FaceIdentityLock
from tools.video.video_edit_selector import VideoEditSelector


def test_video_character_edit_pipeline_loads_with_sequential_edit_gates():
    manifest = load_pipeline("video-character-edit")
    assert manifest["name"] == "video-character-edit"
    assert manifest["category"] == "custom"
    assert get_stage_order(manifest) == [
        "intake", "proposal", "preprocess", "outfit_edit", "hair_edit",
        "face_lock", "review", "compose", "publish",
    ]
    gates = {stage["name"]: stage.get("human_approval_default") for stage in manifest["stages"]}
    assert gates["proposal"] is True
    assert gates["outfit_edit"] is True
    assert gates["hair_edit"] is True
    assert gates["face_lock"] is True
    assert gates["review"] is True


def test_pipeline_uses_edit_capability_and_no_generation_fallback():
    required = get_required_tools(load_pipeline("video-character-edit"))
    assert "video_edit_selector" in required
    assert "face_identity_lock" in required
    assert "video_character_edit_qa" in required
    assert "video_selector" not in required


def test_video_edit_selector_excludes_reference_only_providers():
    providers = VideoEditSelector()._providers()
    names = {provider.name for provider in providers}
    assert "minimax_h3_video" not in names
    assert "seedance_video" not in names
    assert "openrouter_seedance" in names
    assert all(provider.supports.get("edit_video") or "edit_video" in provider.capabilities for provider in providers)


def test_face_identity_lock_fails_closed_without_a_provider():
    result = FaceIdentityLock().execute({
        "video_path": "hair.mp4",
        "face_reference_path": "face.png",
        "output_path": "face.mp4",
    })
    assert not result.success
    assert "No temporal face identity provider" in result.error


def test_video_character_edit_qa_artifact_schema_accepts_unscored_review():
    validate_artifact("video_character_edit_qa", {
        "version": "1.0",
        "stage": "outfit_edit",
        "source_path": "assets/video/source.mp4",
        "edited_path": "assets/video/outfit.mp4",
        "contact_sheet_path": "artifacts/outfit-contact-sheet.jpg",
        "sampled_frames": 8,
        "status": "REVIEW_REQUIRED",
        "manual_review_required": True,
        "checks": {
            "identity_score": None,
            "motion_score": None,
            "background_score": None,
            "appearance_score": None,
            "continuity_score": None,
        },
        "issues": [],
    })
