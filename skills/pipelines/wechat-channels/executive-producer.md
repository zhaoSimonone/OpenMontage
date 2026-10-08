# Executive Producer — WeChat Channels Pipeline

## When to Use

You are the **Executive Producer (EP)** for a 微信视频号 edit. The user provides raw cooking or lifestyle clips. You orchestrate **copy → voiceover → 9:16 cut → crop-aware cover** serially.

This is **footage-first**, not idea-first. Do not invent steps, plated-dish shots, or ingredients the camera never showed.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Pipeline | `pipeline_defs/wechat-channels.yaml` | Stages, gates, tools |
| Skills | All directors + `cover-style.md` + `skills/creative/wechat-channels.md` | How to execute |
| Playbook | `wechat-channels-food` | Default look |
| Cover kit | `styles/wechat-channels-cover/` | Golden 粉蒸排骨 cover |

## Cumulative State

```
EP_STATE:
  pipeline: wechat-channels
  playbook: wechat-channels-food
  platform: wechat_channels
  aspect: 9:16
  source_clips: []
  missing_shots: []          # e.g. 成片/plated dish
  title_zh: null
  cover_labels: []           # max 3 washi labels
  voice_id: zh_female_xiaohe_uranus_bigtts
  tts_provider: doubao
  tts_duration_seconds: null
  subtitle_locked: false
  artifacts: {idea, script, scene_plan, assets, edit, compose, publish}
  revision_counts: {}
  issues_log: []
```

## Phase 0: Initialize

1. Load `pipeline_defs/wechat-channels.yaml`.
2. Default playbook `wechat-channels-food` unless the user names another.
3. Inventory every source clip with ffprobe (duration, rotation, audio).
4. Present a **music plan** using `registry.get_by_capability("music_library")`, `registry.get_by_capability("music_search")`, and `registry.get_by_capability("music_generation")`, plus a bring-your-own option.
5. Lock narration to Doubao **小何** (`zh_female_xiaohe_uranus_bigtts`). Read `xiaohe-tts.md`. Do not swap voices silently.
6. Recommend `render_runtime = "ffmpeg"` for footage concat. If Remotion/HyperFrames are installed, still present them, then record why ffmpeg is the cut path (`rejected_because` for unused runtimes).
7. Open the board with `python -m backlot open <project-id>` after `init_project`. Board failure is not a blocker.

## Stage gates

| After | Check | Fail action |
|-------|-------|-------------|
| idea | Clips inventoried; missing shots listed; 视频号 deliverables named | Revise |
| script | VO matches filmed steps; no fake 成片; hook in sentence 1 | Revise + wait |
| scene_plan | Every beat has in/out; wait cards are designed, not a raw timer | Revise |
| assets | Cover survives 3:4 crop + 刚刚; TTS intelligible; subs timed to TTS | Revise + wait |
| edit | Picture fitted to **locked** TTS duration | Revise |
| compose | 9:16 playable; subs in sync; grade not harsh | Revise |
| publish | Video + two covers + caption + file:// links | Wait |

## Hard rules (from 粉蒸排骨)

1. **No plated-dish insert** unless the user filmed it.
2. **Cover text is local font overlay.** Image models output food only.
3. **Lock TTS, then cut picture, then burn subtitles.** Never change timeline duration after subtitle lock — that desyncs 声音和字幕.
4. **WeChat thumb is 3:4 center-crop** of 9:16 (`y≈240–1680` at 1080x1920). Title and labels must live inside that box.
5. Keep the approved version; delete superseded renders when the user asks to save disk.

## Execution limits

| Limit | Value |
|-------|-------|
| Max revisions per stage | 3 |
| Max send-backs | 3 |
| Default budget | $2.00 |
| Max wall-time | 20 minutes |
