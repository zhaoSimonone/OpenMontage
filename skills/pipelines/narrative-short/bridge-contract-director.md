# Bridge Contract Director - Narrative Short Pipeline

## Goal

Make a two-clip story feel causally continuous without relying on impossible
frame-perfect H3 pose continuation.

## Required Artifact

Write a schema-valid `segment_bridge_contract` with exactly two segments and
one join.

## Required Join Fields

- one bridge prop or one simple cause-effect action;
- terminal/initial character state that keeps wardrobe, eye line, emotion, and
  camera family coherent;
- `visual_lock` containing character identity, wardrobe, colour/lighting, and
  camera language;
- a transition type and duration;
- narration, music, and room-tone cross-segment policies.

## Preferred Transitions

Use a `fade` or `crossfade` around 0.3 seconds when the location changes. Use
`cut` only when the first segment ends on a deliberate visual pause and both
locations match closely.
