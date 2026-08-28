# Intake Director - Reference Performance Pipeline

## Goal

Lock the supplied identity image, reference performance video, target format,
provider preference, and source-usage boundaries.

## Required output

Create an asset manifest with separate roles:

- `character_identity_reference`
- `performance_reference_video`
- optional `wardrobe_reference`, `audio_reference`, or clean setting reference

Record local paths, technical metadata, and provider-ready URLs when the
provider requires public HTTPS media.

## Exclusions

Mark the source person's face, body, hair, clothing, background, text, logo,
watermark, and transformation effects as excluded unless the user explicitly
requests one of them.
