# Ingest Director - Reference Dance Pipeline

## Goal

Lock the project, reference video, target format, and provider path before any creative or paid generation work.

## Required Inputs

- Project id
- Local or CDN dance reference video
- Target duration
- Target aspect ratio
- Preferred provider/model
- Any explicit exclusions from the user

## Required Output

Produce `reference_dance_ingest` with:

- `project_id`
- `reference_video`
- `target_duration_seconds`
- `aspect_ratio`
- `provider_preference`
- `do_not_use`

## Review Focus

- The correct reference video is identified.
- The target is 9:16 unless the user says otherwise.
- The active provider remains MiniMax-H3 unless the user explicitly changes it.
- Unrelated hospital, POV, TTS, or dialogue-story tasks are excluded.

