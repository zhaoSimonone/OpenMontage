# Proposal Director - Reference Performance Pipeline

## Goal

Turn the locked identity image and motion-reference intake into an approved
production contract before any paid MiniMax-H3 request is sent. This stage
chooses how faithfully to transfer the performance, how to handle continuity,
and how the final candidate will be packaged. It does not generate media.

## Concept options

Present at least three genuinely different, motion-preserving options:

1. **One-shot performance transfer**: one continuous H3 request for a simple
   performance that can hold identity, action order, and expression timing in
   one pass.
2. **Beat-segmented transfer**: short H3 segments with explicit terminal pose,
   hand position, gaze, expression, and weight bridge contracts when the source
   contains difficult action changes.
3. **Performance-first candidate**: the same identity and source-usage rules,
   with a restrained camera and minimal post composition so action and facial
   evidence remain easy to review.

Do not offer a prompt-only still-image substitute as an equivalent option.
Every option must state its expected action fidelity, expression fidelity,
continuity risk, cost, and the reason it fits the reference.

## Runtime selection (mandatory)

`render_runtime` is the technical composition engine and is separate from the
MiniMax-H3 generation provider. Read the hard rule in `AGENT_GUIDE.md` before
locking it.

When Remotion and HyperFrames (`hyperframes`) are available, present both to
the user:

- **Remotion** is best when the generated candidate needs deterministic MP4
  packaging, captions, audio, or React-based composition. The tradeoff is a
  heavier render path for a clip that may only need normalization.
- **HyperFrames** is best when the final support layer is HTML/CSS/GSAP-native
  and needs browser-rendered overlays. The tradeoff is that a plain generated
  clip gains no performance benefit from an HTML composition layer.
- **FFmpeg** is applicable when the approved candidate only needs trim,
  concat, normalization, or validation. The tradeoff is that it cannot author
  rich overlays or composition scenes.

Recommend `ffmpeg` for a clean approved H3 candidate with no overlays;
recommend Remotion or HyperFrames only when the brief actually needs that
composition layer. Wait for explicit user approval before writing the locked
choice into `proposal_packet.production_plan.render_runtime`.

Record all applicable alternatives in `decision_log` under
`category: "render_runtime_selection"`, including the selected option and
why the other options were rejected. A single-option decision when multiple
runtimes are available is invalid.

## Composition authoring mode

Present `templated` and `atelier` separately from runtime. Use `templated` for
simple packaging and stable caption/audio layers. Use `atelier` for a bespoke
hero treatment that needs hand-authored scenes, and route through the bespoke
composition guidance before authoring. Record this choice under
`category: "composition_mode"` with the same subject on revisions.

## Required proposal fields

The approved `proposal_packet` must include:

- `delivery_promise.promise_type: "motion_led"`
- `delivery_promise.motion_required: true`
- `delivery_promise.source_required: false`
- `delivery_promise.approved_fallback: null`
- target duration, ratio, and resolution
- `renderer_family`, `render_runtime`, and `composition_mode`
- MiniMax-H3 as the video provider/model and its estimated cost
- the reference image/video role separation and the expected QA gates

The packet must state that the identity image owns face, hair, wardrobe, body
proportions, and character identity; the reference video owns timed action,
gesture, gaze, head angle, blink, expression, pauses, and rhythm. It must also
state that the source performer's identity, wardrobe, background, text, logo,
watermark, and transformation effects are excluded.

## Gate

This stage requires human approval. After writing the proposal and decision log,
checkpoint with `status="awaiting_human"` and stop. Do not start performance
analysis, planning, or paid generation in the same response.
