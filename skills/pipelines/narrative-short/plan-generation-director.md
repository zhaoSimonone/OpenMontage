# Plan Generation Director - Narrative Short Pipeline

## Goal

Compile two reviewable MiniMax-H3 requests without submitting a paid task.

## Required Tools

Use `tencent_cos_upload` when a reference asset is still a local file, then use
`narrative_short_h3_plan`. The COS tool must complete its anonymous-read check
before its URL is passed to H3. `narrative_short_h3_plan` is a deterministic
formatter and record writer, not a creative planner.

## Process

1. Read the brief, script, scene plan, and bridge contract.
2. If the asset manifest has a local canonical reference but no provider-ready URL,
   call `tencent_cos_upload` with the explicit project object key. Record the
   returned URL in the project asset metadata; never put credentials in an
   artifact or prompt.
3. Repeat the same verified canonical reference URL and identity lock in both requests.
4. Keep the two prompts focused on their own 15-second action and bridge state.
5. Include the adult male POV exclusion in both requests.
6. Write both request JSON files and planned `GenerationAttempt` records.
7. Present tool, provider, model, output spec, prompt paths, verified reference URL,
   and total estimate.
8. Stop at the approval gate. Do not call H3 in this stage.

## Prompt Rule

Native dialogue cannot be promised through the current metaso H3 contract. A
line can be used as lip-movement staging, but the approved audio timeline owns
the delivered speech.
