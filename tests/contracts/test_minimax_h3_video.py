"""Contract tests for the MiniMax-H3 metaso video provider."""

from __future__ import annotations

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)
from tools.video.minimax_h3_video import MiniMaxH3Video


def test_inherits_base_tool():
    assert issubclass(MiniMaxH3Video, BaseTool)


def test_has_required_identity():
    tool = MiniMaxH3Video()
    assert tool.name == "minimax_h3_video"
    assert tool.version
    assert tool.provider == "minimax_h3"
    assert tool.capability == "video_generation"
    assert tool.tier == ToolTier.GENERATE
    assert tool.stability == ToolStability.EXPERIMENTAL
    assert tool.execution_mode == ExecutionMode.SYNC
    assert tool.determinism == Determinism.STOCHASTIC
    assert tool.runtime == ToolRuntime.API


def test_has_input_schema():
    schema = MiniMaxH3Video().input_schema
    assert schema.get("type") == "object"
    assert schema.get("required") == ["prompt"]
    props = schema.get("properties", {})
    assert props["resolution"]["enum"] == ["768P", "2K"]
    assert "9:16" in props["ratio"]["enum"]
    assert "content" in props


def test_status_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("MINIMAX_H3_API_KEY", raising=False)
    monkeypatch.delenv("METASO_MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    assert MiniMaxH3Video().get_status() == ToolStatus.UNAVAILABLE


def test_status_available_with_key(monkeypatch):
    monkeypatch.setenv("MINIMAX_H3_API_KEY", "fake-key")
    assert MiniMaxH3Video().get_status() == ToolStatus.AVAILABLE


def test_has_contract_metadata():
    tool = MiniMaxH3Video()
    assert "ai-video-gen" in tool.agent_skills
    assert "text_to_video" in tool.capabilities
    assert "image_to_video" in tool.capabilities
    assert "reference_to_video" in tool.capabilities
    assert tool.supports["first_last_frame"] is True
    assert tool.resource_profile.network_required is True
    assert tool.retry_policy.max_retries >= 0
    assert "MINIMAX_H3_API_KEY" in tool.install_instructions


def test_estimate_cost_scales_by_duration_and_resolution():
    tool = MiniMaxH3Video()
    low = tool.estimate_cost({"prompt": "x", "duration": 5, "resolution": "768P"})
    high = tool.estimate_cost({"prompt": "x", "duration": 5, "resolution": "2K"})
    longer = tool.estimate_cost({"prompt": "x", "duration": 10, "resolution": "768P"})
    assert high > low
    assert longer > low


def test_build_payload_text_to_video_vertical():
    payload = MiniMaxH3Video._build_payload({
        "prompt": "two dancers smile at camera",
        "duration": 5,
        "aspect_ratio": "9:16",
    })
    assert payload == {
        "model": "MiniMax-H3",
        "content": [{"type": "text", "text": "two dancers smile at camera"}],
        "resolution": "768P",
        "duration": 5,
        "ratio": "9:16",
        "aigc_watermark": False,
    }


def test_text_to_video_rejects_adaptive_ratio():
    try:
        MiniMaxH3Video._build_payload({"prompt": "x", "operation": "text_to_video", "ratio": "adaptive"})
    except ValueError as exc:
        assert "concrete ratio" in str(exc)
    else:
        raise AssertionError("text_to_video must reject adaptive ratio")


def test_build_payload_image_to_video_uses_adaptive_and_frame_roles():
    payload = MiniMaxH3Video._build_payload({
        "prompt": "gentle camera push",
        "operation": "image_to_video",
        "reference_image_url": "https://example.com/start.png",
        "last_frame_image_url": "https://example.com/end.png",
        "ratio": "9:16",
    })
    assert payload["ratio"] == "adaptive"
    assert payload["content"] == [
        {"type": "text", "text": "gentle camera push"},
        {"type": "image_url", "image_url": "https://example.com/start.png", "role": "first_frame"},
        {"type": "image_url", "image_url": "https://example.com/end.png", "role": "last_frame"},
    ]


def test_image_to_video_requires_an_image():
    try:
        MiniMaxH3Video._build_payload({"prompt": "x", "operation": "image_to_video"})
    except ValueError as exc:
        assert "image_to_video requires" in str(exc)
    else:
        raise AssertionError("image_to_video must require first or last frame")


def test_build_payload_reference_to_video():
    payload = MiniMaxH3Video._build_payload({
        "prompt": "match the reference dance rhythm",
        "operation": "reference_to_video",
        "reference_image_urls": ["https://example.com/a.png", "https://example.com/b.png"],
        "reference_video_url": "https://example.com/motion.mp4",
        "reference_audio_url": "https://example.com/beat.mp3",
        "aspect_ratio": "9:16",
        "resolution": "2K",
        "duration": 6,
        "aigc_watermark": True,
    })
    assert payload["resolution"] == "2K"
    assert payload["duration"] == 6
    assert payload["ratio"] == "9:16"
    assert payload["aigc_watermark"] is True
    assert payload["content"][1:] == [
        {"type": "image_url", "image_url": "https://example.com/a.png", "role": "reference_image"},
        {"type": "image_url", "image_url": "https://example.com/b.png", "role": "reference_image"},
        {"type": "video_url", "video_url": "https://example.com/motion.mp4", "role": "reference_video"},
        {"type": "audio_url", "audio_url": "https://example.com/beat.mp3", "role": "reference_audio"},
    ]


def test_content_override_must_include_text():
    try:
        MiniMaxH3Video._build_payload({
            "prompt": "ignored",
            "content": [{"type": "image_url", "url": "https://example.com/a.png"}],
        })
    except ValueError as exc:
        assert "text item" in str(exc)
    else:
        raise AssertionError("content override must include text")


def test_rejects_mixing_frame_and_reference_roles():
    try:
        MiniMaxH3Video._build_payload({
            "prompt": "bad mix",
            "operation": "reference_to_video",
            "content": [
                {"type": "text", "text": "bad mix"},
                {"type": "image_url", "image_url": "https://example.com/a.png", "role": "first_frame"},
                {"type": "image_url", "image_url": "https://example.com/b.png", "role": "reference_image"},
            ],
        })
    except ValueError as exc:
        assert "cannot mix" in str(exc)
    else:
        raise AssertionError("frame roles and reference roles must not be mixed")


def test_extract_task_id_and_status_and_video_url():
    create_payload = {"task_id": "424010985738629"}
    query_payload = {
        "task": {
            "id": "424010985738629",
            "status": "succeeded",
            "content": {"url": "https://cdn.example.com/out.mp4"},
        }
    }
    assert MiniMaxH3Video._extract_task_id(create_payload) == "424010985738629"
    assert MiniMaxH3Video._extract_status(query_payload) == "succeeded"
    assert MiniMaxH3Video._extract_video_url(query_payload) == "https://cdn.example.com/out.mp4"


def test_no_key_returns_error(monkeypatch):
    monkeypatch.delenv("MINIMAX_H3_API_KEY", raising=False)
    monkeypatch.delenv("METASO_MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    result = MiniMaxH3Video().execute({"prompt": "test"})
    assert result.success is False
    assert "MINIMAX_H3_API_KEY" in result.error


def test_registry_discovers_minimax_h3_video(monkeypatch, isolated_tool_registry):
    monkeypatch.delenv("MINIMAX_H3_API_KEY", raising=False)
    isolated_tool_registry.discover("tools")
    tool = isolated_tool_registry.get("minimax_h3_video")
    assert tool is not None
    assert tool.capability == "video_generation"
    assert tool.provider == "minimax_h3"


def test_provider_menu_exposes_env_offer(monkeypatch, isolated_tool_registry):
    monkeypatch.delenv("MINIMAX_H3_API_KEY", raising=False)
    isolated_tool_registry.discover("tools")
    summary = isolated_tool_registry.provider_menu_summary()
    offers = [
        offer for offer in summary["setup_offers"]
        if offer.get("tool") == "minimax_h3_video"
    ]
    assert offers
    assert offers[0]["env_vars"] == ["MINIMAX_H3_API_KEY"]
