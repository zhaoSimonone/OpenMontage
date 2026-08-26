"""Tests for narrative-short MiniMax-H3 planning and approval gating."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.video.narrative_short_h3_plan import NarrativeShortH3Plan
from tools.video.narrative_short_generator import NarrativeShortGenerator


def _bridge() -> dict:
    return {
        "version": "1.0",
        "project_id": "waiting-home-test",
        "target_duration_seconds": 30,
        "segments": [
            {"id": "shot_001", "start_seconds": 0, "end_seconds": 15, "purpose": "door", "state": {"character": "door", "key_prop": "paper bag", "emotion": "expectant", "camera": "POV"}},
            {"id": "shot_002", "start_seconds": 15, "end_seconds": 30, "purpose": "table", "state": {"character": "table", "key_prop": "paper bag", "emotion": "warm", "camera": "POV"}},
        ],
        "joins": [{"from": "shot_001", "to": "shot_002", "semantic_bridge": {"kind": "prop_cause_effect", "bridge_prop": "paper bag", "from_action": "carry it inside", "to_action": "place it on the table"}, "visual_lock": ["identity", "wardrobe"], "transition": {"type": "fade", "duration_seconds": 0.3}, "audio_policy": {"narration_continues": True, "music_crossfades": True, "room_tone_continues": True}}],
    }


def _inputs(tmp_path: Path) -> dict:
    return {
        "project_id": "waiting-home-test",
        "reference_image_urls": ["https://cdn.example.test/character.png"],
        "canonical_character_description": "adult woman with a warm, familiar, gentle look from the reference image",
        "scene_lock": "A warm apartment at night, consistent wardrobe and natural 50mm eye-level POV.",
        "bridge_contract": _bridge(),
        "shots": [
            {"shot_id": "shot_001", "story_beat": "She opens the door holding a paper bag.", "bridge_state": "She turns inward with the bag.", "dialogue": "回来啦，外面冷不冷？"},
            {"shot_id": "shot_002", "story_beat": "She lays out supper on the table.", "bridge_state": "The bag rests on the table.", "dialogue": "你回来就好。"},
        ],
        "output_dir": str(tmp_path / "attempts"),
    }


def test_planner_writes_two_reviewable_h3_requests(tmp_path):
    result = NarrativeShortH3Plan().execute(_inputs(tmp_path))

    assert result.success
    assert len(result.data["plans"]) == 2
    assert result.data["estimated_cost_usd"] == 2.4
    first = result.data["plans"][0]
    request = json.loads(Path(first["request_json_path"]).read_text())
    attempt = json.loads(Path(first["attempt_json_path"]).read_text())
    assert request["model"] == "MiniMax-H3"
    assert request["ratio"] == "9:16"
    assert request["duration"] == 15
    assert request["content"][1]["role"] == "reference_image"
    assert "[identity_lock]" in request["content"][0]["text"]
    assert "Never show his face, body, arms, hands" in request["content"][0]["text"]
    assert attempt["status"] == "planned"
    assert attempt["metadata"]["paid_generation_submitted"] is False


def test_planner_rejects_mismatched_bridge_segments(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["bridge_contract"] = _bridge()
    inputs["bridge_contract"]["segments"][1]["id"] = "wrong"

    result = NarrativeShortH3Plan().execute(inputs)

    assert not result.success
    assert "must match shots" in result.error


def test_generator_blocks_unapproved_paid_submission(tmp_path):
    plan = NarrativeShortH3Plan().execute(_inputs(tmp_path)).data["plans"][0]
    result = NarrativeShortGenerator().execute(
        {
            "generation_attempt": plan["generation_attempt"],
            "attempt_path": plan["attempt_json_path"],
            "paid_generation_approved": False,
        }
    )

    assert not result.success
    assert "requires paid_generation_approved=true" in result.error
