# Asset Director — WeChat Channels Pipeline

## When to Use

Scene plan approved. Produce TTS, BGM, subtitles timed to TTS, and the **cover pair**.

**Read first:** `skills/pipelines/wechat-channels/cover-style.md`, `skills/pipelines/wechat-channels/xiaohe-tts.md`, and `styles/wechat-channels-cover/README.md`.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/asset_manifest.schema.json` | Validation |
| Tools | `tts_selector`, `subtitle_gen` | Required |
| Tools | `image_selector`, `audio_mixer` | Optional hero + mix |
| Script | `styles/wechat-channels-cover/layout_cover.py` | Local type overlay |

## Process

### Step 0: Hero cover sample (mandatory)

Before batching anything expensive:

1. Get a **glyph-free** food hero (`image_selector` or a still).
2. Run `layout_cover.py` with approved title + ≤3 labels.
3. Show **9:16, 4:5, WeChat thumb sim (with 刚刚), and 3:4 red-box overlay**.
4. Wait for cover approval.

Do not generate 10 cover variants in the image model with letters in the prompt.

### Step 1: TTS (小何)

Read `xiaohe-tts.md` and `.agents/skills/doubao-tts/SKILL.md`.

1. Generate a 10–15s sample with `tts_selector`, `preferred_provider="doubao"`, `voice_id="zh_female_xiaohe_uranus_bigtts"`, `sample_rate=48000`, `enable_timestamp=True`, `sample_mode=True`.
2. Let the user hear it before the full take.
3. Full VO with the same voice. Probe duration — this is now the timeline authority.
4. Keep the Doubao query JSON; subtitles come from `sentences[].words[]`.

If Doubao is down, stop and ask. Do not silently switch to Google/ElevenLabs.

### Step 2: Subtitles from TTS

Build SRT/ASS from the TTS take (or aligned text), not from an unfinished video. `subtitle_gen` with short lines (≤12–14 汉字). Burn later; **do not retiming after this file is locked.**

### Step 3: BGM

Use the music choice from idea. Duck under VO (`music_volume` ≈ 0.12 in the playbook). If the user supplied 菊次郎的夏天 or similar, keep it; do not replace without asking.

### Step 4: Manifest

Record paths for: VO, BGM, subs, food hero, 9:16 cover, 4:5 cover, thumb sim, crop overlay, font.

### Step 5: Self-evaluate

| Criterion | Question |
|-----------|----------|
| Glyphs | Any letters in the generated photo? If yes, discard and overlay locally. |
| Crop | Title + labels inside y=240–1680 on 9:16? |
| Sync source | Subs timed to TTS duration? |

### Step 6: Submit

Checkpoint `awaiting_human` with the cover images inline. **END THE TURN.**

---

## Gate Reminder (Binding)

`human_approval_default: true`. Cover + VO sample must be seen before compose.
