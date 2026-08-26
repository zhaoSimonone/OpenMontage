"""Contracts for the narrative-short pipeline."""

from __future__ import annotations

from lib.pipeline_loader import get_required_tools, get_stage_order, load_pipeline


def test_narrative_short_pipeline_loads():
    manifest = load_pipeline("narrative-short")

    assert manifest["name"] == "narrative-short"
    assert manifest["category"] == "custom"
    assert manifest["stability"] == "beta"
    assert manifest["reference_input"]["supported"] is True


def test_narrative_short_stage_order_and_generation_gates():
    manifest = load_pipeline("narrative-short")

    assert get_stage_order(manifest) == [
        "intake",
        "story_plan",
        "bridge_contract",
        "plan_generation",
        "generate",
        "audio_post",
        "review",
        "compose",
    ]
    gates = {stage["name"]: stage.get("human_approval_default") for stage in manifest["stages"]}
    assert gates["plan_generation"] is True
    assert gates["generate"] is True
    assert gates["audio_post"] is True
    assert gates["review"] is True


def test_narrative_short_required_tools_are_explicit():
    required = get_required_tools(load_pipeline("narrative-short"))

    assert "narrative_short_h3_plan" in required
    assert "narrative_short_video_generate" in required
    assert "narrative_short_qa" in required
    assert "video_stitch" in required
