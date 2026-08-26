# Executive Producer - Narrative Short Pipeline

## Goal

Turn one prompt and one supplied character reference into an approximately
30-second, two-segment vertical narrative short without silently changing the
video provider, character source of truth, or POV rules.

## Non-Negotiable Rules

- Use `narrative-short`, never `reference-dance`, for relationship-led short drama.
- Treat the supplied image as canonical when its physical traits conflict with prose.
- Keep one visible adult female character only when the brief requires male first-person POV.
- A two-clip story needs an explicit `segment_bridge_contract`; no hard continuation of a complex gesture.
- MiniMax-H3 is visual only in V1. TTS, music, ambience, and subtitles are separate controlled assets.
- Do not replace MiniMax-H3 with another provider without explicit human approval.

## Run Order

`intake -> story_plan -> bridge_contract -> plan_generation -> generate -> audio_post -> review -> compose`

Write an `in_progress` checkpoint at stage entry. Read the stage director,
complete its artifacts, self-review, then obey the manifest approval gate.
