# Intake Director - Video Character Edit

Run `source_media_review` on the source video and all supplied references.
Record technical metadata, representative frames, source audio presence, and
the intended target person.

Bind assets by role:

- `source_video`: motion, timing, camera, background, body, and audio authority
- `face_reference`: identity authority for the face-lock stage
- `hair_reference` or description: hairstyle target only
- `outfit_reference` or description: wardrobe target only

Do not use the source video's face or clothing as an implicit reference image.
Mark unsupported or ambiguous inputs for review before proposal.

