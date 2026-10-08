# Publish Director — WeChat Channels Pipeline

## When to Use

A playable 9:16 cut exists. Package it for 视频号 upload. Do not post automatically.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/publish_log.schema.json` | Validation |
| Files | Video, 9:16 cover, 4:5 cover | Deliverables |

## Process

### Step 1: Export folder

```
export/
  <title>_9x16.mp4
  <title>_封面_9比16.jpg
  <title>_封面_4比5.jpg
  视频号文案.txt
```

`视频号文案.txt` contains title, body, hashtags from the approved script.

### Step 2: Links

Give `file://` URLs for video and both covers so the user can open them in Finder.

### Step 3: Disk hygiene

If the user already asked to keep only the last version, delete superseded cuts/covers in this project. Never delete the golden kit in `styles/wechat-channels-cover/`.

### Step 4: Publish log

Platform `wechat_channels`, status `draft`, paths recorded.

### Step 5: Self-evaluate

| Criterion | Question |
|-----------|----------|
| Complete | Video + 2 covers + caption? |
| Openable | file:// links are absolute? |

### Step 6: Submit

Checkpoint `awaiting_human`. **END THE TURN.**

---

## Gate Reminder (Binding)

`human_approval_default: true`.
