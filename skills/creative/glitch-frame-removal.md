# Glitch Frame Removal Skill (AI Transformation-Clip Repair)

## When to Use

Apply this skill when an AI-generated cosplay / transformation clip contains a short
run of "leak frames" — the character's hair/face has already changed to another
identity while the outfit still belongs to the previous scene (or vice versa) —
and the user asks to evaluate and remove them.

Typical user phrasing: 「视频里有几帧【白色头发+黑色上衣】的人物，评估下去除是否会有较大影响，没有太大影响就帮我去除」,
often with a screenshot of one paused glitch frame. The clip is usually a countdown
transformation video ("3.. 2.. 1.. → outfit reveal").

**Do NOT use** for: removing whole scenes, trimming duration, or censoring — those
are ordinary edit decisions, not glitch repair.

## Core Principles (binding)

1. **Frame-exact removal.** Every deleted frame must be a glitch frame; every kept
   frame must be clean. One frame of slack in either direction is a defect.
2. **Intended styling vs leak frames.** The final look's hair color (e.g., silver
   hair in a school-uniform scene, pink hair in a Zero Two outfit), burned-in
   countdown captions, and anime inset images are **creative intent — never touch
   them**, even when they share the "wrong-looking" hair color the user described.
   Only remove frames whose identity/outfit combination matches no intended scene
   (leak frames).
3. **Standard treatment**: remove the leak run + apply a 0.2s white-flash transition
   at the cut, with audio trimmed in sync and crossfaded. This is the default; do
   not ask.
4. **Never overwrite the source.** Output `<original_name>_cut.mp4` in the same
   directory.
5. **Proceed autonomously.** Evaluate, state the conclusion, and execute in one
   turn. Pause to ask the user ONLY if: the leak run exceeds ~2s, it is a
   standalone shot rather than a transition leak, or removal would cut voice/SFX.

## Workflow

### Step 1 — Metadata

```bash
ffprobe -v error -select_streams v -count_frames \
  -show_entries stream=width,height,r_frame_rate,nb_read_frames,duration -of csv INPUT.mp4
ffprobe -v error -select_streams a -show_entries stream=codec_name,channels,duration -of csv INPUT.mp4
```

Record: fps, total frames, duration, audio presence.

### Step 2 — Structure scan

Extract 3fps thumbnails and tile into a timestamped contact sheet with PIL
(`drawtext` is unavailable in this ffmpeg build). Read the sheet and classify:

- Intended scenes/looks (in order of appearance)
- The leak run(s) — approximate time range
- Burned-in captions/insets and which scenes they belong to

### Step 3 — Boundary lock by SOURCE FRAME INDEX (critical)

Extract frames around the leak **by frame number** with `select`, labeled with
frame indices:

```bash
mkdir -p /tmp/glitch_fine
ffmpeg -y -v error -i INPUT.mp4 \
  -vf "select='between(n,A-15,D+15)',setpts=PTS-STARTPTS,scale=180:320" \
  -fps_mode passthrough /tmp/glitch_fine/f_%03d.jpg
# tile with PIL; label each cell  frame#=index, ts=index/fps
```

**Never locate boundaries via `-ss` + `fps` filter.** The seek/fps grid can be
offset by 1 frame from true source frame indices — this caused a real defect
(one extra uniform frame deleted) during the technique's first uses. `select`
by `n` is the single source of truth.

Identify exactly:

| Symbol | Meaning |
|--------|---------|
| `#A` | last clean frame before the leak |
| `#B` | first leak frame (= A+1) |
| `#C` | last leak frame |
| `#D` | first clean frame after (= C+1) |

### Step 4 — Audio check

Extract mono WAV, compute 0.1s-window RMS/peak around the removal span:

```bash
ffmpeg -y -v error -i INPUT.mp4 -vn -ac 1 /tmp/glitch_audio.wav
# python wave: 0.1s RMS windows; flag voice/SFX/beat transients inside [B/fps, D/fps)
```

If the span contains voice or an isolated SFX, stop and surface options. If it is
continuous music only, proceed — a sub-second skip softened by the crossfade is
acceptable and gets masked by the scene reveal.

### Step 5 — Impact evaluation (state, then act)

Report in one short block: leak frame count and time range; whether the cut lands
adjacent to an existing scene change (minimal impact) or inside a continuous shot
(small jump, masked by the flash); audio verdict. Then execute — no approval gate
for the standard case.

### Step 6 — Removal + 0.2s white flash + synced audio

```bash
ffmpeg -y -v error -i INPUT.mp4 -filter_complex \
"[0:v]select='lt(n,B)',setpts=PTS-STARTPTS,fps=30[v0];\
 [0:v]select='gte(n,D)',setpts=PTS-STARTPTS,fps=30[v1];\
 [v0][v1]xfade=transition=fadewhite:duration=0.2:offset=((B/30)-0.2)[vout];\
 [0:a]atrim=0:B/30,asetpts=PTS-STARTPTS[a0];\
 [0:a]atrim=start=D/30,asetpts=PTS-STARTPTS[a1];\
 [a0][a1]acrossfade=d=0.2[aout]" \
-map "[vout]" -map "[aout]" \
-c:v libx264 -crf 16 -preset medium -pix_fmt yuv420p \
-colorspace bt709 -color_primaries bt709 -color_trc bt709 \
-r 30 -c:a aac -b:a 192k -movflags +faststart OUTPUT_cut.mp4
```

Rules:
- Video removal: keep `[0,B)` and `[D,end)`, concat. Audio removal span in seconds:
  `[B/fps, D/fps)` — identical span so A/V stay in sync.
- Transition: `xfade=transition=fadewhite:duration=0.2:offset=(part1_duration-0.2)`.
  Audio counterpart is `acrossfade=d=0.2`, **not** fade-out + fade-in (the lumpy
  60ms in/out fades are the pre-flash fallback only, when the user explicitly
  declines the flash).
- `fps=30` must be applied to both video branches before `xfade`.
- Encode: libx264 crf 16 preset medium, yuv420p, bt709 color tags, `-r 30`,
  aac 192k, `+faststart`.

### Step 7 — Verification (all four, no exceptions)

1. **Frame-count math**: output frames = original − (C−B+1) − 6 (0.2s flash
   overlap at 30fps); output duration ≈ original − (D/fps − B/fps) − 0.2; A/V
   durations match within ~30ms.
2. **Junction sheet**: extract output frames `B-12 .. B+6`, tile and Read — the
   flash must fully cover the identity swap; no leak frame visible at peak white.
3. **Full 3fps rescan** of the output: zero leak frames anywhere; captions,
   insets, and countdown intact.
4. **Report**: leak range (frames + seconds), frames/seconds removed,
   before/after duration and frame counts, output path as a clickable link.

### Pitfalls (each one bit us already)

- **1-frame offset** from `-ss`+fps seeking → always `select` by `n` for boundaries;
  when in doubt, re-verify the boundary sheet with `select='between(n,..)'` before
  cutting.
- **Analysis frames are inspection-only**: the Step-3 JPG boundary frames exist
  only for visual boundary confirmation. Output MUST come from the Step-6
  single-pass filter_complex reading INPUT.mp4 directly — never assemble output
  from analysis JPGs (a lossy JPEG generation measurably softened a whole
  deliverable: PSNR vs direct decode dropped to ~31dB, sharpness −14%).
- **Contact-sheet labeling bug**: when tiling with PIL, parse the file with
  `os.path.basename()` before splitting on `_` — absolute paths containing
  underscores break naive `path.split('_')[1]` parsing.
- **Intended-look trap**: in a 4-clip real session the "white hair" the user
  reported was a leak in clip 1, but clip 2's final look legitimately had white
  hair throughout. Removing by color match alone would have destroyed the video.
- **Beat alignment**: check where the music transient/beat lands. If the original
  edit cut on a beat, keep the reveal on that beat after removal (the flash
  transition is short enough that beat sync survives).
- **Multiple glitch runs**: if the scan reveals more than one leak run, repeat
  Steps 3–7 per run (chain segments in one filter graph rather than re-encoding
  repeatedly).

## User Prompt Template (paste-ready, Chinese)

```text
处理视频【路径/附件】:视频里有几帧【毛刺描述,格式如"XX色头发+XX色上衣的人物",例:白色头发+黑色上衣 / 黑色头发+紫灰色上衣 / 白色头发+白色上衣】。描述不准的话,附一张暂停在毛刺帧上的截图即可。
1. 按源帧号逐帧定位边界(别用 -ss 抽帧定位,会有 1 帧偏移),评估剪除影响;影响小就直接删,不用问我。
2. 注意:最终造型的发色、贴片、倒计时字幕是设定,一帧不能动;只删"头发/脸变了但衣服还停在上一场景"的漏帧。
3. 剪除后在剪点加 0.2s 白闪转场(fadewhite + acrossfade),音轨同步剪。
4. 输出 <原名>_cut.mp4,不覆盖原片。
5. 交付前逐帧复查剪点和全片,确认毛刺零残留,汇报剪掉的帧数和秒数。
```

This template is only a convenience entry point — when the user pastes it, this
skill file is the authority on HOW.
