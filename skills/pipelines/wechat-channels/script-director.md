# Script Director — WeChat Channels Pipeline

## When to Use

You have a brief and source clips. Write **spoken Mandarin copy** that the TTS will read, plus on-screen caption lines and a 视频号 post caption.

Do **not** transcribe kitchen noise into a recipe. If a clip has usable speech, `transcriber` may help; most cooking inputs are silent and need a new VO.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/script.schema.json` | Validation |
| Prior | brief | Title, missing shots |
| Optional tool | `transcriber` | Only if the source already talks |

## Process

### Step 1: Shot-true outline

Walk the clips in filming order. Each VO sentence must map to a visible action. If the user did not shoot 成片, do not write “出锅装盘看成品”.

### Step 2: Hook + body

- Sentence 1 is the hook (“粉蒸排骨这样做，简单又好吃”).
- Short clauses, 3–4 chars/sec, easy for TTS.
- Name the method the camera actually shows (炒酱 / 腌透 / 裹粉 / 上锅).
- End on the last real shot, not an imagined plated beauty.

Spoken length targets (from `skills/creative/short-form.md`): ~70–80 words / 30s, ~125–150 / 60s. Mandarin: count characters; keep a 15–45s VO unless footage is longer.

### Step 3: Caption + hashtags

Draft the 视频号 caption separately from VO:

- Title line
- 1–2 sentence body
- 3–5 hashes (`#粉蒸排骨` `#蒸菜` …)

### Step 4: Cover words

Propose:

- Title (usually 4 characters, bouncing sticker)
- Up to 3 washi labels from real steps

### Step 5: Self-evaluate

| Criterion | Question |
|-----------|----------|
| Shot-true | Every sentence has a clip? |
| TTS | Any tongue-twisters or 10+ char clauses? |
| Honesty | No 成片 / 秘制 unless filmed or user-provided? |

### Step 6: Submit

Checkpoint `awaiting_human`. Show VO text, duration estimate, caption, cover words. **END THE TURN.**

---

## Gate Reminder (Binding)

`human_approval_default: true`. Do not synthesize TTS until the copy is approved.
