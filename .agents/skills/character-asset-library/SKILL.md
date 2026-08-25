---
name: character-asset-library
description: Consolidate reusable character design images across OpenMontage projects, with exact deduplication and legacy-path compatibility. Use when character references are scattered between projects and need a shared library.
---

# Character Asset Library

Use this project-specific skill when a user asks to centralize, organize, or
deduplicate reusable character setting images across `projects/`.

Before changing any file, read
[`skills/meta/character-asset-library.md`](../../../skills/meta/character-asset-library.md).
It is the authoritative OpenMontage workflow for this operation: category
semantics, exclusion rules, SHA-256 deduplication, relative symlink migration,
and acceptance checks.

## Operating Constraints

- Treat the request as a filesystem migration. Inventory the candidates and
  explain the proposed library layout before moving or removing files.
- Include only reusable character references by default. Do not pull in render
  frames, video extracts, waveforms, or diagnostic images merely because a
  character appears in them.
- Deduplicate only when SHA-256 hashes match exactly. Never use a filename,
  visual resemblance, or dimensions as proof that files can be merged.
- Preserve old project paths with relative symlinks after confirming their
  consumers support them. Do not silently rewrite historical project artifacts
  as a fallback.
- Verify every intended legacy link and sample each category before reporting
  completion.

This skill governs asset-library organization only. Follow the normal pipeline
and its stage skills when the user instead asks to generate character assets or
produce a video.
