# Bind Assets Director - Reference Dance Pipeline

## Goal

Bind character, wardrobe, and motion assets into separate roles so the video model does not confuse identity, clothing, and choreography.

## Subject Mapping

Create `subject_mapping`:

```yaml
character_1:
  target: blue-haired character
  reference_performer: left performer
  screen_position: left / slightly forward
character_2:
  target: pink-haired character
  reference_performer: right performer
  screen_position: right / half step behind
```

## Asset Roles

Record assets in `asset_manifest` by role:

- `character_identity`
- `wardrobe_reference`
- `motion_reference_video`
- optional `reference_audio`

## Review Focus

- Character identity references and motion references are not treated as interchangeable.
- Provider-required CDN URLs exist before generation planning.
- The prompt compiler has enough data to keep full-body two-person framing.

