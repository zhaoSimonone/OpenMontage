"""Contracts for the reference-dance pipeline."""

from __future__ import annotations

from lib.pipeline_loader import get_required_tools, get_stage_order, load_pipeline


def test_reference_dance_pipeline_loads():
    manifest = load_pipeline("reference-dance")

    assert manifest["name"] == "reference-dance"
    assert manifest["category"] == "custom"
    assert manifest["stability"] == "beta"
    assert manifest["reference_input"]["supported"] is True


def test_reference_dance_stage_order_and_gates():
    manifest = load_pipeline("reference-dance")

    assert get_stage_order(manifest) == [
        "ingest",
        "bind_assets",
        "plan_generation",
        "generate",
        "review",
        "compose",
    ]
    gates = {stage["name"]: stage.get("human_approval_default") for stage in manifest["stages"]}
    assert gates["plan_generation"] is True
    assert gates["generate"] is True
    assert gates["review"] is True
    assert gates["compose"] is False


def test_reference_dance_required_tools_include_p0_planner():
    manifest = load_pipeline("reference-dance")
    required = get_required_tools(manifest)

    assert "reference_dance_h3_plan" in required
    assert "minimax_h3_video" in required
    assert "video_stitch" in required
