# video-character-edit Pipeline

`video-character-edit` is the source-video workflow for a supplied video plus
face, hair, and outfit references. It is deliberately separate from
`reference-performance`: that pipeline generates a new performance from a
target identity image and a motion reference, while this pipeline treats the
supplied source clip as the visual anchor.

## Current provider boundary

- `video_edit_selector` routes only to tools that advertise `edit_video`.
- The registry exposes Gemini Omni and OpenRouter Seedance 2.0 Mini as explicit
  `edit_video` providers. OpenRouter's adapter uses
  `bytedance/seedance-2.0-mini` with `omni_reference_task_type=edit` and can
  consume local files through Tencent COS or existing HTTPS media URLs.
- MiniMax-H3 and fal.ai/Replicate Seedance remain reference-to-video providers
  in this workflow; they are not silently treated as source-video editors.
- `face_identity_lock` is a fail-closed selector. A temporal FaceSwap/FaceFusion
  provider must be added before the `face_lock` stage can run.

## Artifact and review policy

Every run uses the standard `projects/<project-id>/` layout, checkpoints, cost
tracking, and canonical artifacts. `video_character_edit_qa` writes matched
source/edited contact sheets and intentionally leaves identity, motion,
background, appearance, and continuity scores uncomputed until they have been
calibrated against human review.

The first real validation should be a five-second clip. Preserve source audio,
aspect ratio, frame rate, and timing by default; provider-specific conversion
must be recorded in the artifacts. Segment overlap is removed only after seam
review.
