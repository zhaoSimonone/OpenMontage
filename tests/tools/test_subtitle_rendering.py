"""Regression tests for subtitle filter escaping and CJK cue pagination."""

from __future__ import annotations

from pathlib import Path

from tools.base_tool import ToolResult
from tools.video.remotion_caption_burn import RemotionCaptionBurn
from tools.video.video_compose import VideoCompose


def test_video_compose_escapes_ass_option_commas() -> None:
    style = VideoCompose._build_subtitle_style(
        {"font": "Hiragino Sans GB", "font_size": 20}
    )

    assert r"\," in style


def test_remotion_defaults_cjk_srt_to_one_cue_per_page(tmp_path, monkeypatch) -> None:
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"fixture")
    srt_path = tmp_path / "captions.srt"
    srt_path.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n今天回来。\n\n"
        "2\n00:00:01,100 --> 00:00:02,000\n外面冷不冷？\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "output.mp4"
    captured: dict[str, int] = {}

    def fake_render(
        self,
        input_path: str,
        output_path: str,
        captions: list[dict],
        words_per_page: int,
        font_size: int,
        highlight_color: str,
        overlays: list[dict] | None = None,
    ) -> ToolResult:
        captured["words_per_page"] = words_per_page
        return ToolResult(success=True, data={}, artifacts=[output_path])

    monkeypatch.setattr(RemotionCaptionBurn, "_remotion_available", lambda self: True)
    monkeypatch.setattr(RemotionCaptionBurn, "_render_remotion", fake_render)

    result = RemotionCaptionBurn().execute(
        {
            "input_path": str(input_path),
            "srt_path": str(srt_path),
            "output_path": str(output_path),
            "font_size": 20,
        }
    )

    assert result.success
    assert captured["words_per_page"] == 1
