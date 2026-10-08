# WeChat Channels — Creative Skill

## When to Use

User wants a **微信视频号** piece from their own clips: 文案、配音、封面、9:16 成片. Route to `pipeline_defs/wechat-channels.yaml`. Do not improvise a one-off ffmpeg script.

Also use when they say 视频号封面、刚刚挡住字、主页小图裁切.

## Platform facts

- Playback is 9:16. **Profile thumb is ~3:4 center-crop** of that cover (`y≈240–1680` at 1080×1920).
- A 「刚刚」 pill sits on the **top-left of the thumb**, not of the full 9:16.
- Bottom washi labels that sit on the table below the crop **will not show** on the profile grid.
- Caption + hashtags live in the post, not on the cover.

## Lessons from 粉蒸排骨 (keep)

1. Write VO from **filmed steps**. Skip 成片 if they did not shoot it.
2. 配音默认豆包**小何** `zh_female_xiaohe_uranus_bigtts`。TTS first, picture second, subtitles last. Changing duration after burn desyncs 声音和字幕.
3. BGM under VO; if they pick a track, do not swap it quietly.
4. Freshness grade: a little brighter, then back off if 刺眼.
5. Cover: generate/choose a food hero **without letters**, then overlay 站酷快乐体 bouncing title + 3 left washi labels.
6. Show 9:16, 4:5, thumb-with-刚刚, and red-box crop before locking the cover.
7. Keep the approved files; delete old renders when asked.

Golden cover: `styles/wechat-channels-cover/examples/golden_cover_9x16.jpg`.

## Do not

- Bake 粉蒸排骨 into the image model
- Use Japanese or “AI菜品示意图”
- Put the title at y=0 (刚刚 will eat 粉)
- Drop labels under y=1680 on 9:16 and expect the grid to show them
