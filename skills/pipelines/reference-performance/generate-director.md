# Generate Director - Reference Performance Pipeline

## Preconditions

- The exact H3 request is approved.
- Provider and model are still `minimax_h3` / `MiniMax-H3`.
- Output path is under the project directory.

## Process

Call `reference_dance_video_generate` with the approved request and
`pipeline_name: reference-performance`. Record the task id, provider response,
actual cost, latency, probe data, and output path in the `GenerationAttempt`.

Do not add TTS, subtitles, music, or a provider fallback unless the current
brief explicitly includes them and the user approves the change.
