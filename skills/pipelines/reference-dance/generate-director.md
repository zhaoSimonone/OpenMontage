# Generate Director - Reference Dance Pipeline

## Goal

Submit an approved MiniMax-H3 request and record the provider response.

## Preconditions

- The user has approved the exact request artifact.
- The provider/model path remains `minimax_h3_video` / `MiniMax-H3`.
- Estimated cost was shown before submission.

## Process

1. Announce the exact provider, model, tool, and whether this is a sample or batch.
2. Call `minimax_h3_video` with the approved request fields.
3. Save output video under `projects/<project-id>/assets/video/`.
4. Update GenerationAttempt with:
   - status
   - task id
   - output path
   - provider response
   - actual or estimated cost
   - latency

## Blockers

If auth, quota, network, or provider access fails, surface the blocker. Do not switch provider without user approval.

