---
name: seedance-identity-edit
description: |
  One-shot Seedance video+image identity edit: replace face and hairstyle from
  a reference image while keeping the source video's motion, clothing, camera,
  scene, and timeline. Use when: (1) user asks to swap the person/face/hair in
  an existing clip to a reference still, (2) clothing and body action must stay,
  (3) the approved path is Seedance / ToAPIs seedance-2-fast, not CapCut or the
  staged video-character-edit outfit->hair->face pipeline.
---

# Seedance Identity Edit (face + hair, keep motion/clothes)

Precipitated from `projects/bluehair-ponytail-identity-edit` on 2026-11-05.
One ToAPIs `seedance-2-fast` call replaced the source face and hair with
`03-轻薄刘海高马尾.png` while the white off-shoulder sweatshirt, held dress,
pose, camera, and bathroom set stayed in place.

This is **not** pixel-exact CapCut editing. It is a Seedance omni-reference
edit (or ToAPIs reference-to-video with edit-intent prompt) that happened to
hold identity + clothing + motion well enough to reuse.

## When to use

- One source clip + one identity still
- Change **face identity and hairstyle only**
- Keep original motion, clothing, body, camera, lighting, scene, timeline
- Source duration fits the provider window (ToAPIs Fast: 4-15s; official Ark edit: 4-30s)
- User explicitly wants Seedance / toapis, not the staged character-edit pipeline

## When not to use

- Pixel-exact 1080p / 30fps / frame-count preservation (Fast returns 720p / 24fps)
- Outfit change, scene change, or new action
- Multi-person clips without naming the target
- Source shorter than 4s or longer than the provider max
- User wants CapCut-level frame lock or the outfit -> hair -> face-lock pipeline

## Binding rules

1. **Actually bind both assets in the same call.** Chat history, filenames, and
   text descriptions of the still do not count. Pass the muted source as
   `reference_video` and the still as `reference_image`.
2. **Official edit prompt shape.** Start with an edit keyword
   (`视频编辑` / `替换` / `修改`). Address assets as `@视频1` and `@图片1`.
   Split material roles. Do not over-describe a clear reference still.
3. **Edit parameters.** `duration=-1`, `aspect_ratio=adaptive`,
   `generate_audio=false`. ToAPIs Fast ceiling is `720p`.
4. **Never auto-resubmit.** If `output.task.json` or the output file exists,
   resume or stop. Do not spend another credit.
5. **Mute the working copy; restore source audio after.** Seedance audio is not
   the authority unless the user asked to replace sound.
6. **QA before calling it done.** Identity must change (not dye-only). Clothing,
   body, and motion must hold. No flashback to the original face. Report actual
   resolution, fps, frame count, duration, and audio state.
7. **Do not invent a new pipeline.** If the user asked for staged
   `video-character-edit`, stay there. This skill is the one-shot Seedance path.

## Canonical prompt (official 2.5 / 2.0 series)

Use this unless the user supplies a tighter brief. Keep it short. The still
already carries identity; the video already carries motion.

```text
视频编辑：把 @视频1 中人物的整张脸和发型替换为 @图片1 中的同一位成年女性身份和蓝色高马尾。
仅修改脸与发型，其余构图、机位、光线、服装、动作、口型和时间轴保持与 @视频1 一致。
@图片1 只提供人脸身份、妆容和发型，忽略衣服、身体、背景和静态表情。
```

Official docs: https://docs.volcengine.com/docs/ark/seedance-2-5?lang=zh
Prompt guide: https://docs.volcengine.com/docs/ark/seedance-2-5-prompt-guide?lang=zh

Required pieces from that guide:

- Task keywords: `视频编辑` / `替换` / `修改` / `改成`
- Asset tags: `@视频1`, `@图片1` (or `@video1`, `@image1`)
- Material duties: say what each asset provides **and** what to ignore
- Do not restyle a clear still in prose (no extra makeup/eye/mole inventory
  unless the still is ambiguous)
- Ark edit: `omni_reference_task_type=edit`, `ratio=adaptive`, `duration=-1`

## What this production run actually sent

The successful ToAPIs Fast call used edit keywords, `duration=-1`,
`aspect_ratio=adaptive`, and real `reference_video` + `reference_image` roles.
It did **not** use `@视频1` / `@图片1`, and it over-described the still
(eyes, makeup, mole, bangs). That is a partial match to the official guide.
Future runs should use the canonical prompt above.

Tool: `toapis_seedance`
Model: `seedance-2-fast`
Cost this run: about $0.41
Wall time: about 171s

## Execution

### 1. Probe source

```bash
ffprobe -v error -show_entries format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames -of json SOURCE.mp4
```

Record width, height, fps, frame count, duration, audio. Source should be
4s+ and 9:16 for this look.

### 2. Make a silent working copy

Keep the original with audio. Strip audio on the copy sent to Seedance.

```bash
ffmpeg -y -i SOURCE.mp4 -c:v copy -an source-silent.mp4
```

### 3. One paid call

```python
tool = registry.get("toapis_seedance")
tool.execute({
    "operation": "reference_to_video",
    "model": "seedance-2-fast",
    "prompt": CANONICAL_PROMPT,
    "reference_video_path": "projects/<proj>/assets/video/source-silent.mp4",
    "reference_image_path": "projects/<proj>/assets/images/identity.png",
    "duration": -1,
    "resolution": "720p",
    "aspect_ratio": "adaptive",
    "generate_audio": False,
    "output_path": "projects/<proj>/assets/video/seedance2fast-face-hair-v1.mp4",
    "project_id": "<proj>",
})
```

On official Ark, also set `omni_reference_task_type=edit`. ToAPIs Fast does
not expose that field; the prompt keywords are what steer it toward edit.

If the `.task.json` already exists: `operation=resume_generation` only.
Never POST again.

### 4. Restore source audio

```bash
ffmpeg -y -i seedance2fast-face-hair-v1.mp4 -i SOURCE.mp4 \
  -map 0:v -map 1:a -c:v copy -c:a aac -b:a 160k -shortest \
  seedance2fast-face-hair-v1-with-audio.mp4
```

### 5. Side-by-side comparison (no drawtext)

This ffmpeg build has no `drawtext`. Scale both to the result size, `hstack`,
overlay pre-rendered PNG labels if needed.

```bash
ffmpeg -y -i SOURCE.mp4 -i RESULT.mp4 \
  -filter_complex "[0:v]scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,setpts=PTS-STARTPTS[left];[1:v]scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,setpts=PTS-STARTPTS[right];[left][right]hstack=inputs=2[v]" \
  -map "[v]" -map 0:a -c:v libx264 -pix_fmt yuv420p -crf 18 -c:a aac -b:a 160k -shortest \
  compare.mp4
```

### 6. Visual QA (sampled stills, then full play)

Grab stills at 0%, 25%, 50%, 75%, 100% of the **result** duration. Compare:

- Face contour, eyes, nose, mouth vs the reference still (must be that person)
- Hair: color, ponytail, bangs, movement (not glued, not reverted to black)
- Clothing, print, held object, body scale, camera, background
- No original-face flashback on blink, side face, or occlusion

If the result is still the original face, report `人脸替换未成功` and stop.
Do not spend another credit unless the user asks.

## Known deltas from the 2026-11-05 run

| Item | Source | Seedance Fast result |
|---|---|---|
| Size | 1080x1920 | 720x1280 |
| fps | 30 | 24 |
| Frames | 125 | 97 |
| Duration | 4.17s | 4.04s |
| Audio | original AAC | restored after mute |

Other residuals: hair more saturated / wig-like than the still; held dress a
bit more motion-blurred near the tail. Clothing, pose, and identity held
across the sampled frames.

## Failure modes

- **Dye-only / original face remains:** identity bind failed. Report and stop.
- **Reference outfit leaks in:** prompt ignored the "ignore clothes" clause.
- **Motion rewritten:** task was classified as reference-to-video, not edit.
  Check keywords, `@视频1`, `duration=-1`, `aspect_ratio=adaptive`.
- **Wrong duration / ratio:** forgot adaptive / -1 on an edit task.
- **Duplicate billed call:** ignored existing `.task.json`.
