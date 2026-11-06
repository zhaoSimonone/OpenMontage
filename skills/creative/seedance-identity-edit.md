# Seedance Identity Edit

> Layer 3 authority: `.agents/skills/seedance-identity-edit/SKILL.md`
> Prompting: `skills/creative/prompting/seedance-prompting.md`
> Tool: `toapis_seedance` (model `seedance-2-fast`) or official Ark Seedance edit

## When to use

The user has an existing clip and one identity still, and wants the **face and
hairstyle** replaced while motion, clothing, camera, and timeline stay with the
source. Typical phrasing: 「把视频里的人脸和发型换成参考图，动作服装不要变」.

This is a **one-shot Seedance path**. It is valid when the user asks for
Seedance / ToAPIs. It is not a silent substitute for the staged
`video-character-edit` pipeline (outfit -> hair -> face-lock).

## Preservation promise

| Authority | Asset |
|---|---|
| Face identity, makeup, hair | the reference still |
| Motion, expression timing, mouth, body, clothes, camera, scene, timeline | the source video |
| Audio | original source track, restored after a muted working copy |

## Call shape

- Prompt starts with `视频编辑` / `替换` / `修改`
- Assets tagged `@视频1` and `@图片1`
- Same call binds `reference_video` + `reference_image`
- `duration=-1`, `aspect_ratio=adaptive`, `generate_audio=false`
- ToAPIs Fast max `720p`
- Existing `.task.json` means resume, never resubmit

Canonical prompt lives in the Layer 3 skill. Do not paste CapCut-length
checklists into Seedance; the still already shows the face.

## QA bar

Sample 0 / 25 / 50 / 75 / 100% stills, then play the clip:

- New face matches the still, not a recolor of the source face
- Blue / specified hair holds; no original-face flashback
- Clothes, print, held object, pose, and camera hold
- Report actual width, height, fps, frames, duration, audio

If identity did not change, say `人脸替换未成功` and stop.

## Honest limits (2026-11-05 run)

Source `1080x1920 30fps 125f 4.17s` became `720x1280 24fps 97f 4.04s`.
Hair ran a bit more saturated than the still. Clothing and motion held.
