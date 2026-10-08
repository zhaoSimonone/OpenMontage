# Scene Director — WeChat Channels Pipeline

## When to Use

Approved copy exists. Map every VO beat to clip in/out points and choose the cover hero.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/scene_plan.schema.json` | Validation |
| Tools | `frame_sampler`, `scene_detect` | Optional inspection |
| Cover | `cover-style.md` | Hero + crop |

## Process

### Step 1: Beat sheet

For each script section: `source_path`, `in_seconds`, `out_seconds`, `vo_text`, `why this shot`. Prefer action peaks (油热、下酱、裹粉) over hands rummaging.

### Step 2: Time to VO, not the other way

Plan to **fit picture to TTS** after assets lock duration. Here, only mark usable ranges and optional speed-up (1.1–1.3×) on setup, 1.0× on payoff.

### Step 3: Insert cards

If a wait (蒸 20 分钟) needs a card:

- Do **not** use an ugly full-screen numeric countdown that flashes too fast to read
- Prefer a short designed hold: steam frame + one line of type, 2–3s, or cut to the next real action
- Any card must be readable on 9:16 and not steal the hook

### Step 4: Cover hero

Pick one:

1. Generated food-hero photo (no glyphs) if `image_selector` will be available
2. Best still from footage if generation is off or the user wants the real plate

Record the choice. Layout happens in assets.

### Step 5: Self-evaluate

| Criterion | Question |
|-----------|----------|
| Coverage | Every VO beat has a shot? |
| 成片 | Did we avoid planning a dish the user never filmed? |
| Wait | If there is a wait, is it designed? |

### Step 6: Submit

Checkpoint `awaiting_human`. **END THE TURN.**

---

## Gate Reminder (Binding)

`human_approval_default: true`.
