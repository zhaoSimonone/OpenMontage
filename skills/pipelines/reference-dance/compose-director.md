# Compose Director - Reference Dance Pipeline

## Goal

Create the final platform-ready render only after generation review passes.

## Process

1. Use the approved generated clip when one-shot passed.
2. Use `video_stitch` only when multiple clips passed continuity review.
3. Keep 9:16 vertical output.
4. Save final render under `projects/<project-id>/renders/final.mp4`.
5. Write `render_report` with duration, resolution, codec, source clips, and warnings.

## Review Focus

- Compose must not change the approved motion language.
- Stitching must not mask failed continuity.
- Output should remain suitable for short-form vertical platforms.

