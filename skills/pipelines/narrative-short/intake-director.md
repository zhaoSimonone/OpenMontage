# Intake Director - Narrative Short Pipeline

## Goal

Freeze the user-facing delivery promise and the reference image before story
planning or paid generation.

## Required Artifacts

Write `narrative_short_brief` and `asset_manifest` under the project workspace.

The brief must record:

- the original user prompt verbatim;
- target duration, 9:16 output, adult male first-person POV, and visible-person count;
- canonical character reference URL/path;
- a source-of-truth note for any text/image conflict;
- all explicit negatives.

## Conflict Policy

When prompt prose contradicts the supplied image's immutable visual attributes
(hair color, hair length, outfit, face), use the supplied image as the visual
source of truth and record the change. Do not silently mix incompatible traits
in an H3 prompt.

## Review

Do not advance if the supplied character is not explicitly an adult or the
required reference URL/path has not been resolved for the selected provider.
