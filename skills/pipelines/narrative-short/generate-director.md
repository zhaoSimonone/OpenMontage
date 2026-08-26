# Generate Director - Narrative Short Pipeline

## Goal

Submit only approved H3 requests and update the matching GenerationAttempt.

## Required Tool

Use `narrative_short_video_generate` with `paid_generation_approved=true`.

## Preconditions

- The exact request artifact was shown to the user.
- The user approved the third-party `metaso.cn` Provider, `MiniMax-H3`, cost,
  resolution, duration, and test/batch intent.
- A provider change has not been made.

## Process

1. Announce tool, Provider, model, reason, and whether this is a test or batch.
2. Generate the first segment and write an in-progress checkpoint.
3. Record the task id, output path, actual/estimated cost, latency, and status.
4. Generate the second segment using its own approved attempt.
5. If one segment fails, report the error and retry only that segment after the
   declared retry policy. Do not switch provider.

## Rule

Do not silently use Wan, ComfyUI, Seedance, a still-image alternative, or an
unapproved provider fallback.
