"""Contracts for the WeChat Channels footage-led pipeline."""

from __future__ import annotations

from pathlib import Path

from lib.pipeline_loader import get_stage_order, get_required_tools, list_pipelines, load_pipeline
from styles.playbook_loader import load_playbook

REPO = Path(__file__).resolve().parents[2]


def test_wechat_channels_is_listed_and_loads() -> None:
    assert "wechat-channels" in list_pipelines()
    manifest = load_pipeline("wechat-channels")
    assert manifest["name"] == "wechat-channels"
    assert manifest["category"] == "custom"
    assert manifest["stability"] == "beta"


def test_stage_order_and_gates() -> None:
    manifest = load_pipeline("wechat-channels")
    assert get_stage_order(manifest) == [
        "idea",
        "script",
        "scene_plan",
        "assets",
        "edit",
        "compose",
        "publish",
    ]
    gates = {stage["name"]: stage.get("human_approval_default") for stage in manifest["stages"]}
    assert gates["idea"] is True
    assert gates["script"] is True
    assert gates["scene_plan"] is True
    assert gates["assets"] is True
    assert gates["edit"] is False
    assert gates["compose"] is False
    assert gates["publish"] is True


def test_required_tools_and_skills() -> None:
    manifest = load_pipeline("wechat-channels")
    tools = get_required_tools(manifest)
    assert "tts_selector" in tools
    assert "subtitle_gen" in tools
    assert "video_compose" in tools
    skills = manifest["required_skills"]
    assert "pipelines/wechat-channels/cover-style" in skills
    assert "pipelines/wechat-channels/xiaohe-tts" in skills
    assert "creative/wechat-channels" in skills
    assert any("checkpoint-protocol" in s for s in skills)


def test_director_skills_exist() -> None:
    root = REPO / "skills" / "pipelines" / "wechat-channels"
    for name in (
        "executive-producer.md",
        "idea-director.md",
        "script-director.md",
        "scene-director.md",
        "asset-director.md",
        "edit-director.md",
        "compose-director.md",
        "publish-director.md",
        "cover-style.md",
        "xiaohe-tts.md",
    ):
        path = root / name
        assert path.exists(), path
        assert len(path.read_text(encoding="utf-8")) > 100, name
    creative = REPO / "skills" / "creative" / "wechat-channels.md"
    assert creative.exists()
    assert "3:4" in creative.read_text(encoding="utf-8")


def test_cover_kit_and_playbook() -> None:
    kit = REPO / "styles" / "wechat-channels-cover"
    for rel in (
        "README.md",
        "layout_cover.py",
        "fonts/ZCOOLKuaiLe-Regular.ttf",
        "examples/golden_cover_9x16.jpg",
        "examples/golden_cover_4x5.jpg",
        "examples/golden_food_hero.png",
        "examples/wechat_crop_overlay.jpg",
        "examples/wechat_thumb_sim.jpg",
    ):
        assert (kit / rel).exists(), rel
    playbook = load_playbook("wechat-channels-food")
    assert playbook["identity"]["name"] == "WeChat Channels Food"
    layout = (kit / "layout_cover.py").read_text(encoding="utf-8")
    assert "title_y = 390" in layout
    assert "1528" in layout


def test_xiaohe_is_the_default_voice() -> None:
    voice = "zh_female_xiaohe_uranus_bigtts"
    for rel in (
        "skills/pipelines/wechat-channels/xiaohe-tts.md",
        "skills/pipelines/wechat-channels/asset-director.md",
        "skills/pipelines/wechat-channels/executive-producer.md",
        "styles/wechat-channels-food.yaml",
        "pipeline_defs/wechat-channels.yaml",
    ):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert voice in text, rel
