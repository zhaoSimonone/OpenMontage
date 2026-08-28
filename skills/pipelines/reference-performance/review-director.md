# Review Director - Reference Performance Pipeline

## Required review

Run `reference_performance_qa` and inspect sampled frames side by side with
the reference. Review these independently:

- action order and timing
- hand and arm trajectory
- body-weight transfer and rhythm
- facial expression timing
- gaze, blink, eyelid, mouth, and head-angle changes
- target identity and wardrobe consistency
- camera, framing, hands, and unwanted source content
- segment seams, when segments exist

## Decision rules

- Missing beat-level expression review: `REVIEW_REQUIRED`
- Action order or expression below 0.70: `REGENERATE`
- Motion/continuity issue with otherwise good performance: `REPAIR`
- All required scores and visual checks clear: `PASS`

Do not use a crossfade or color grade to conceal a performance failure.
