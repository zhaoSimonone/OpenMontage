# Review Director - Narrative Short Pipeline

## Goal

Determine whether each H3 clip and their planned join can proceed to final
composition.

## Required Tool

Use `narrative_short_qa` for deterministic technical checks and review frames,
then use `visual_qa` frames for semantic inspection.

## Required Human Review

Check `0s, 3s, 8s, 14.7s, 15.2s, 20s, 26s, 29s` or nearest generated frames:

- one consistent adult female character and wardrobe;
- no male face/body/hands/shadow/reflection/silhouette;
- correct number of visible people;
- bridge prop persists in a causally readable way;
- no malformed fingers, face drift, text, logo, or watermark;
- natural expression changes and credible lip movement;
- music, narration, and subtitle timing align with the script.

## Repair Policy

If a segment fails identity, POV, prop, or hand checks, regenerate that segment
only. If both clips are sound but the boundary is rough, try the approved 0.3
second transition and audio bridge before regenerating segment 2.
