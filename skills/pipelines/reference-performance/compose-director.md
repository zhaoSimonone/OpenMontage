# Compose Director - Reference Performance Pipeline

## Goal

Package the approved performance candidate without changing the performance
character.

## Runtime routing

Read `edit_decisions.render_runtime` and the approved
`proposal_packet.production_plan.render_runtime` before composing. They must
match unless a new `render_runtime_selection` decision explicitly records the
change.

- **`render_runtime="ffmpeg"`**: use `video_compose` for trim, concat,
  normalization, or a clean no-overlay export. This is the recommended route
  when the H3 candidate already contains the approved performance.
- **`render_runtime="remotion"`**: use the Remotion composition path when the
  approved brief needs captions, audio layers, or React-authored support
  scenes. Pass `proposal_packet` so runtime-swap validation remains active.
- **`render_runtime="hyperframes"`**: use the HyperFrames composition path only
  for an approved HTML/CSS/GSAP support layer, after its lint and validation
  checks pass. Pass `proposal_packet` and preserve the same candidate media.

Do not silently replace one runtime with another. Do not use HyperFrames or
Remotion merely to hide a failed action or expression review. If the selected
runtime is unavailable, stop and escalate the blocker for an approved change.

## Rules

- Preserve the approved source clip whenever it already meets the QA gate.
- Use FFmpeg only for required format normalization, trimming, or safe-zone
  operations.
- Do not crop away hands, feet, or facial evidence to inflate the review.
- Verify duration, ratio, codec, audio policy, and final visual frames.
