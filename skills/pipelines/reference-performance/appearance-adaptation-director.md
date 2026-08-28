# Appearance Adaptation Director - Reference Performance Pipeline

## Goal

Decide whether the target character image fits the reference video's visual
language. When it does not, use `hairfree_image` to create several target-
character appearance candidates, then stop for human selection before video
planning or generation.

This stage adapts the target character to the reference video's **style**, not
its performer. The reference performer's face, body, identity, exact clothing,
background, text, logo, watermark, and transformation effects must not be
copied.

## Style assessment

Inspect the reference video's sampled frames and the target identity image.
Compare these observable dimensions:

- wardrobe silhouette, coverage, materials, colors, and accessories
- hair arrangement and finish
- makeup intensity and color direction
- lighting, palette, contrast, and environment
- camera distance, framing, and overall tone

Write a style mismatch assessment with severity `none`, `minor`, or `major`.
Do not infer mismatch from attractiveness or personal taste. Explain which
dimensions conflict and what can be adapted without changing identity.

## Decision branches

### No mismatch

Write `appearance_adaptation.decision = "NOT_NEEDED"`. Keep the original
identity image as the downstream H3 image. The stage still requires its
checkpoint so the decision is explicit and auditable.

### Mismatch detected

1. Build a positive style contract from the video analysis. Describe the
   target wardrobe, hair treatment, makeup, palette, lighting, and setting in
   concrete terms.
2. Keep immutable identity attributes explicit: face shape, facial proportions,
   eye color, age, body proportions, character identity, and any accessories
   that define the character.
3. Call `hairfree_image` in edit mode with the target identity image as the
   primary source. Generate 2-3 alternatives at the approved image quality.
4. The prompt must say that the output is the same target character and that
   only the approved style attributes may change. Prefer the analyzed style
   contract in text; use extracted video frames as style-only references only
   when the provider can preserve role separation.
5. Save every output under `projects/<project-id>/assets/images/`, record the
   exact prompt, model, source image, and cost in the asset manifest, and write
   all candidates to `appearance_adaptation.json`.

The stage is not complete merely because Hairfree returned images. Mark the
artifact `CANDIDATES_READY` and checkpoint `awaiting_human`.

## Human approval gate

Present a contact sheet or candidate list with candidate IDs. The user must
choose one candidate, reject the set, or request another adaptation pass.

- On approval, mark exactly one candidate `approved`, set
  `selected_candidate_id`, and set `decision = "APPROVED"`.
- On rejection, mark the stage `REJECTED` and stop. Do not silently use the
  original image as a substitute for the requested adaptation.
- A later revision must append a decision-log entry with the same category and
  subject as the prior appearance decision.

The approved candidate becomes authoritative for wardrobe, hair styling,
makeup, palette, and lighting. The original identity image remains the
authority for immutable identity. The approved candidate must have a verified
provider-readable URL before it enters `reference_performance_h3_plan`.

## Gate and cost

This stage may incur Hairfree Image cost only after the proposal has identified
an adaptation need and the generation call is announced with the exact tool,
model, number of candidates, and estimate. It must never trigger MiniMax-H3.
After candidates are generated, checkpoint with `status="awaiting_human"` and
stop. Downstream performance analysis and video planning wait for the user's
appearance choice.
