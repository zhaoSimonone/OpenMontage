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

## Output

Produce `final_review` and, when multiple clips exist, `continuity_report`.

## Decision

Use:

- `PASS` when motion, identity, camera, and continuity are good enough.
- `REPAIR` for small technical fixes.
- `REGENERATE` for stiff motion, identity drift, side swaps, framing jumps, or wrong choreography.

Do not hide bad dance motion with crossfades.

