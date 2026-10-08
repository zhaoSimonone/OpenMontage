# 小何配音 — WeChat Channels

## When to Use

Every `wechat-channels` narration. Default voice is Doubao **小何**:

```text
zh_female_xiaohe_uranus_bigtts
```

Read `.agents/skills/doubao-tts/SKILL.md` before calling the tool.

## Lock

| Field | Value |
|-------|-------|
| Provider | `doubao` via `tts_selector` |
| `voice_id` | `zh_female_xiaohe_uranus_bigtts` |
| `resource_id` | `seed-tts-2.0` |
| `sample_rate` | `48000` |
| `speech_rate` | `0` |
| `enable_timestamp` | `true` |
| Format | `mp3` |

Do not switch voices unless the user names a different 音色. If Doubao is unavailable, say so and ask — do not silently pick another female voice.

## Call

```python
from tools.audio.tts_selector import TTSSelector

result = TTSSelector().execute({
    "preferred_provider": "doubao",
    "text": "<approved Mandarin VO>",
    "voice_id": "zh_female_xiaohe_uranus_bigtts",
    "resource_id": "seed-tts-2.0",
    "format": "mp3",
    "sample_rate": 48000,
    "speech_rate": 0,
    "enable_timestamp": True,
    "sample_mode": True,  # first 10-15s only
    "output_path": "projects/<id>/assets/audio/xiaohe_sample.mp3",
})
```

After the user approves the sample, generate the full take with `sample_mode=False` and keep `<output>.json` word timestamps. Build SRT from `sentences[].words[]`, not from estimated duration.

## Workflow

1. 10–15s 小何 sample → user hears it
2. Full VO only after approval
3. Timeline follows 小何 duration
4. Subtitles follow Doubao timestamps
5. Mix BGM under VO; do not replace 小何 with kitchen-only audio unless asked

Proven on 粉蒸排骨 (`projects/steamed-pork-ribs-video-20261007/DOUBAO_TTS_API.md`).
