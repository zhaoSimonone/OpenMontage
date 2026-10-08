# Idea Director — WeChat Channels Pipeline

## When to Use

Raw clips exist. Build a brief for a 微信视频号 9:16 video: what was filmed, what the cover/title should say, and what we will **not** fake.

## Runtime selection

Prefer **ffmpeg** for source-footage concat. If Remotion or HyperFrames are available, present them, then record `render_runtime_selection` with ffmpeg as the cut path. Do not silently pick.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/brief.schema.json` | Validation |
| Cover kit | `styles/wechat-channels-cover/` | Golden cover |
| Skill | `skills/creative/wechat-channels.md` | Platform rules |

## Process

### Step 1: Inventory footage

ffprobe every input. Sample frames if `frame_sampler` is later available. Record:

- What each clip shows (洗切 / 炒酱 / 腌制 / 上锅 / …)
- Audio: silent kitchen, noisy room, or existing VO
- **Missing shots** the user might expect (especially 成片/装盘)

### Step 2: Platform brief

Lock:

- Platform: 微信视频号
- Aspect: 9:16 1080x1920
- Cover: 9:16 + 4:5, golden cute style
- Language: Mandarin VO + Chinese burned captions
- Voice: Doubao 小何 `zh_female_xiaohe_uranus_bigtts` (see `xiaohe-tts.md`)

### Step 3: Music plan (mandatory)

Check in order and present choices:

1. User library — `registry.get_by_capability("music_library")` and `music_library/`
2. Royalty-free search — `registry.get_by_capability("music_search")`
3. Generation — `registry.get_by_capability("music_generation")`
4. Bring your own (drop a track in `music_library/`)

Do not silently pick BGM.

### Step 4: Write the brief

Include title, hook, key cooking beats that **exist in footage**, tone (家常、可爱、不装), cover labels (≤3), and missing-shot list.

### Step 5: Self-evaluate

| Criterion | Question |
|-----------|----------|
| Honesty | Did we list missing 成片 instead of planning to fake it? |
| Platform | Is 视频号 9:16 + crop-aware cover explicit? |
| Music | Did the user see real BGM options? |

### Step 6: Submit

Validate, checkpoint `awaiting_human`, **END THE TURN**.

---

## Gate Reminder (Binding)

`human_approval_default: true`. After review: `awaiting_human`, show the brief, **END YOUR TURN**.
