# Plan Generation Director - Reference Dance Pipeline

## Goal

Compile a MiniMax-H3 request artifact and planned GenerationAttempt without calling the paid API.

## Required Tool

Use `reference_dance_h3_plan`.

## Process

1. Read `asset_manifest` and `subject_mapping`.
2. Prefer a 15-second one-shot request when MiniMax-H3 supports the target duration.
3. Compile the H3 prompt with:
   - identity lock
   - subject mapping
   - wardrobe lock
   - reference-video use/ignore rules
   - camera lock
   - choreography beats
   - negative constraints
4. Write request JSON under the project `artifacts/` directory.
5. Write a planned GenerationAttempt with `status: planned`.
6. Present request path, cost estimate, and review notes to the user.
7. Stop for approval.

## Hard Rule

Do not call `minimax_h3_video` in this stage.

## Review Focus

- Request uses `MiniMax-H3`.
- Duration and ratio are explicit.
- Subject mapping and camera lock are visible in prompt text.
- `paid_generation_submitted` is false.

