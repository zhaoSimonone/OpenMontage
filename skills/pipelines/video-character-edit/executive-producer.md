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

