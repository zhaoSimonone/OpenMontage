# Executive Producer - Video Character Edit

This pipeline edits a supplied source video. The source video's timing, camera,
setting, body motion, and original audio are the default authorities. Reference
images provide only the requested appearance changes.

The producer must keep these decisions explicit:

- target person and whether multiple people are in scope
- outfit and hairstyle edit providers
- face identity-lock provider
- segment length, overlap, source cadence, and audio policy
- preservation promise and known provider limitations

Do not describe a reference-to-video generation call as a source-video edit.
When a provider cannot accept the source clip for editing, stop and report the
capability gap. Do not silently switch to a generated replacement.

One-shot Seedance identity+hair (keep clothes and motion) is a **valid
explicit path**, not a silent fallback. If the user asks for Seedance / ToAPIs
and only wants face+hair replaced, follow
`.agents/skills/seedance-identity-edit/SKILL.md` instead of inventing a new
pipeline. Do not use that path when the approved plan is staged outfit -> hair
-> face-lock, and do not claim pixel-exact 1080p/30fps preservation.

