# Executive Producer - Reference Dance Pipeline

## Purpose

Use this pipeline for a reference-driven dance short with one or two visible characters where choreography fidelity, full-body framing, character identity, and provider cost control all matter.

## Core Rules

1. Stay bound to the active project and reference video.
2. Do not drift into unrelated storylines, dialogue shorts, POV scenes, or TTS tasks.
3. Treat `MiniMax-H3` through `minimax_h3_video` as the active provider unless the user explicitly changes it.
4. Use `reference_dance_h3_plan` before paid generation.
5. Do not submit paid generation until the user approves the request artifact.

## Quality Priority

For dance:

```text
motion fidelity > continuity > identity > beauty
```

The model should not win by producing a pretty but stiff clip.

## Gates

- `bind_assets`, `plan_generation`, `generate`, and `review` require human approval.
- The `plan_generation` gate is the paid-spend guard: it must produce a reviewable request JSON and planned attempt log, then stop.
- The `generate` stage may call `minimax_h3_video` only after explicit user approval.
