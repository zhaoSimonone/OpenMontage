# Review Director - Reference Dance Pipeline

## Goal

Evaluate dance usefulness, not just technical playability.

## Checks

- Exactly two adult fictional women are visible.
- Character 1 stays left / slightly forward.
- Character 2 stays right / half step behind.
- Both bodies and both feet stay visible.
- Camera remains locked and full-body.
- Hands are natural.
- Lower body has weight transfer.
- Shoulders and hips carry the rhythm.
- Motion is not hand-only or mannequin-still.
- The generated clip follows the broad reference rhythm.
- Use `reference_dance_qa` for motion_score, continuity_score, and seam review.
- Treat `motion_score < 0.55` as a regenerate signal.
- Treat `continuity_score < 0.65` as a seam repair signal.
- If H3 motion fails twice, emit a fallback recommendation for
  `reference_dance_video_generate` with `comfyui_video` / Wan 2.2. The next
  generation attempt must wait for explicit user approval; do not auto-switch.

## Output

Produce `final_review` and, when multiple clips exist, `continuity_report`.

## Decision

Use:

- `PASS` when motion and continuity scores both clear the gate and the dance still reads alive.
- `REPAIR` for seam issues, small framing drift, or other fixable continuity problems.
- `REGENERATE` for stiff motion, hand-only motion, mannequin stillness, identity drift, side swaps, framing jumps, or wrong choreography.

Do not hide bad dance motion with crossfades.
