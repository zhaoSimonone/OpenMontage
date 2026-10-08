# Edit Director — WeChat Channels Pipeline

## When to Use

Assets are approved. TTS duration is the **timeline authority**. Build `edit_decisions` that fit picture to that duration.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/edit_decisions.schema.json` | Validation |
| Assets | VO duration, subtitle file | Lock |
| Tool | `video_trimmer` | Optional trims |

## Process

### Step 1: Lock duration

`timeline_seconds = tts_duration + 0.4–0.8s tail`. Do not expand later.

### Step 2: Allocate shots

Scale each planned clip so the sum matches the lock. Speed 1.0–1.3× on prep, 1.0× on the money shot. Never cut mid-pour unless the next shot continues the same action.

### Step 3: Audio stack

- VO at full level
- BGM ducked under VO
- Keep real sizzle if it does not fight the VO

### Step 4: Subtitles

Reference the **already timed** subtitle file. If a cut would drift subs, change picture, not the SRT.

### Step 5: Self-evaluate

| Criterion | Question |
|-----------|----------|
| Authority | Does timeline == TTS (+tail)? |
| Sync | Would burning SRT now stay on the voice? |
| Honesty | No black slug standing in for 成片? |

### Step 6: Submit

`human_approval_default: false` — persist and continue unless a check failed.

---

If you must recut after compose because 声音和字幕不同步, **rebuild subtitles from the TTS take**, do not stretch the video under old cues.
