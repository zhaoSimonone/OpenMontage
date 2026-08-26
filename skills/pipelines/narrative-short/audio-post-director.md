# Audio Post Director - Narrative Short Pipeline

## Goal

Create a controllable soundtrack and canonical subtitle timeline independent of
unverified H3 native audio.

## Voice Procedure

1. Generate a 6-10 second performance-sensitive sample before a full TTS run.
2. For delivery control, use `dashscope_tts` with
   `qwen3-tts-instruct-flash` instructions. For timestamp-led subtitle timing,
   use `doubao_tts` when an authorized voice is available.
3. Record voice/provider/instructions in `decision_log` before full synthesis.
4. Generate full narration and any post-produced dialogue only after sample
   approval.

## Timeline Rules

- Build `audio_timeline` from approved script and TTS timestamps; ASR is only a
  validation fallback.
- Keep music and room tone continuous over the visual seam.
- Use `audio_mixer` ducking while speech is active and normalize for vertical
  social delivery.
- Add only causal effects such as door, bag, and room ambience; avoid clutter.
