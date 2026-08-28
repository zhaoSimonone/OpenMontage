# Performance Analysis Director - Reference Performance Pipeline

## Goal

Turn the reference video into a timed performance contract that a generator
and reviewer can use without guessing.

## Beat contract

For every meaningful action or pause, record:

- start and end time
- body action and hand trajectory
- head angle and gaze target
- facial expression, eyelid state, blink timing, and mouth shape
- body-weight transfer and intensity
- pause after the gesture
- representative frame paths

Do not write only "cute", "confident", or "natural". Those are style labels,
not observable performance instructions.

## Review gate

The agent must inspect sampled frames and verify the beat order visually. A
technical motion curve can supplement the analysis but cannot replace facial
performance observation.
