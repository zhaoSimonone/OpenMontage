# Generate Director - Reference Dance Pipeline

## Goal

Submit an approved reference-dance request and record the provider response.
MiniMax-H3 remains the primary path. The `reference_dance_video_generate`
router may use the Wan 2.2 ComfyUI path only after review QA requests it and
the user explicitly approves the provider change.

## Preconditions

- The user has approved the exact request artifact.
- The normal provider/model path is `minimax_h3_video` / `MiniMax-H3`.
- A fallback request must carry `qa_report_path` (or inline `qa_report`) and
  `fallback_approved=true`; otherwise no provider switch is allowed.
- Estimated cost was shown before submission.

## Process

1. Announce the exact provider, model, tool, and whether this is a sample or batch.
2. Call `reference_dance_video_generate` with the approved request fields.
   The router delegates to `minimax_h3_video` by default. If the QA report's
   `next_action.kind` is `consider_fallback_provider`, show the user the
   Wan 2.2 / ComfyUI choice and wait for explicit approval before retrying.
3. Save output video under `projects/<project-id>/assets/video/`.
4. Update GenerationAttempt with:
   - status
   - task id
   - output path
   - provider response
   - actual or estimated cost
   - latency

## Blockers

If auth, quota, network, or provider access fails, surface the blocker. Do not
switch provider without user approval. A standard Wan 2.2 I2V workflow can
preserve the character reference, but it is not a pose-control guarantee for
the dance reference video; record that limitation in the attempt.
