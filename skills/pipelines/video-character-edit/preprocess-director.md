# Preprocess Director - Video Character Edit

Probe the source and preserve its aspect ratio, frame rate, duration, and audio
as the default. Apply provider-specific normalization only when required, and
record the conversion in `video_analysis_brief`.

For clips longer than the selected provider limit, create short segments with a
small overlap. Keep source timecodes and an explicit trim window so overlap
frames are removed only after the edited segment passes review.

All files must live under `projects/<project-id>/assets/video/` or its artifact
directories. Never overwrite the source.

