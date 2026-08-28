"""Contracts for the generalized reference-performance pipeline."""

from __future__ import annotations

from lib.pipeline_loader import get_required_tools, get_stage_order, load_pipeline


def test_reference_performance_pipeline_loads():
    manifest = load_pipeline("reference-performance")

    assert manifest["name"] == "reference-performance"
    assert manifest["category"] == "custom"
    assert manifest["stability"] == "beta"
    assert manifest["reference_input"]["supported"] is True


def test_reference_performance_has_analysis_and_review_gates():
    manifest = load_pipeline("reference-performance")

    assert get_stage_order(manifest) == [
        "intake",
        "proposal",
        "performance_analysis",
        "bind_assets",
        "plan_generation",
        "generate",
        "review",
        "compose",
    ]
    gates = {stage["name"]: stage.get("human_approval_default") for stage in manifest["stages"]}
    assert gates["performance_analysis"] is True
    assert gates["plan_generation"] is True
    assert gates["generate"] is True
    assert gates["review"] is True


def test_reference_performance_proposal_locks_runtime_before_paid_generation():
    manifest = load_pipeline("reference-performance")

    proposal = next(stage for stage in manifest["stages"] if stage["name"] == "proposal")
    plan = next(stage for stage in manifest["stages"] if stage["name"] == "plan_generation")
    compose = next(stage for stage in manifest["stages"] if stage["name"] == "compose")

    assert proposal["produces"] == ["proposal_packet", "decision_log"]
    assert "proposal_packet" in plan["required_artifacts_in"]
    assert "proposal_packet" in compose["required_artifacts_in"]


def test_reference_performance_tools_are_explicit():
    required = get_required_tools(load_pipeline("reference-performance"))

    assert "reference_performance_h3_plan" in required
    assert "reference_performance_qa" in required
    assert "reference_dance_video_generate" in required
    assert "frame_sampler" in required
