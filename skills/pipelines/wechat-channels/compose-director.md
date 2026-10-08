# Compose Director — WeChat Channels Pipeline

## When to Use

Edit decisions exist. Render the 9:16 video and copy approved covers beside it.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/render_report.schema.json` | Validation |
| Tools | `video_compose`, `audio_mixer` | Required |
| Tools | `color_grade`, `video_stitch`, `video_trimmer` | Optional |

## Process

### Step 1: Assemble

ffmpeg/video_compose concat per edit_decisions. Output `1080x1920`, H.264, AAC, 9:16.

### Step 2: Mix

VO + ducked BGM. Target about −14 LUFS, VO peaks below −1 dBTP. BGM stays in the background.

### Step 3: Grade (gentle)

Food should look **a bit fresher**, not blown-out. If a strong grade looks harsh/刺眼, pull it back. Do not apply a second grade on top of an approved one.

### Step 4: Burn subtitles

Burn the locked SRT/ASS. Spot-check three timestamps against VO. If drift > 150ms, stop and send back to edit/assets — do not “fix” by changing video speed.

### Step 5: Package covers

Copy the approved 9:16 + 4:5 covers into the same output folder as the video. Do not re-layout unless the user asked.

### Step 6: Probe + review

ffprobe: 9:16, has audio, duration ≈ TTS. Write render_report + final_review.

### Step 7: Self-evaluate

| Criterion | Question |
|-----------|----------|
| Sync | Subs land on the spoken words? |
| Grade | Appetizing, not neon? |
| Files | Video + two covers on disk? |

`human_approval_default: false` — still show the user the file:// video after render.
