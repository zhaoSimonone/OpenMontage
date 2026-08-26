# Compose Director - Narrative Short Pipeline

## Goal

Assemble approved clips, an approved sound mix, and canonical subtitles into a
vertical final render without altering the approved visual story.

## Runtime Decision

Before using `video_compose`, query its `render_engines`. If Remotion and
HyperFrames are both available, present both to the user and wait for explicit
runtime approval as required by `AGENT_GUIDE.md`.

For a two-clip narrative short, recommend FFmpeg-oriented composition via
`video_stitch` plus `audio_mixer`/`video_compose`: it preserves generated video
frames and handles the 0.3-second seam, external mix, and SRT reliably. It is
not a replacement for the mandatory runtime discussion when `video_compose` is
used.

## Process

1. Stitch the approved clips using the bridge contract transition.
2. Use `audio_mixer` to create one approved mixed audio track with narration,
   dialogue, ambience, effects, and ducked music.
3. Burn the canonical SRT and mux the approved audio with `video_compose`.
4. Run final review against vertical resolution, approximately 30-second
  duration, audio stream, subtitle legibility, and delivery-promise checks.

## Output

Write `edit_decisions`, `render_report`, `final_review`, and the final MP4
under the canonical project directory.
