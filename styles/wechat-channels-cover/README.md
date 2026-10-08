# WeChat Channels Cover Style Kit

Golden style distilled from the approved 粉蒸排骨 cover (2026-10-08).

Use this kit whenever the `wechat-channels` pipeline builds a 视频号封面.
Read `skills/pipelines/wechat-channels/cover-style.md` before generating.

## Golden examples

| File | What it is |
|------|------------|
| `examples/golden_cover_9x16.jpg` | Approved 9:16 cover. **Keep this look.** |
| `examples/golden_cover_4x5.jpg` | Approved 4:5 sibling |
| `examples/golden_food_hero.png` | Food photo only — no title baked in |
| `examples/wechat_crop_overlay.jpg` | Red box = 视频号主页 3:4 可见范围 |
| `examples/wechat_thumb_sim.jpg` | Profile thumb + 「刚刚」 badge |

## Layout rules (do not regress)

On `1080x1920`:

- WeChat profile thumb is a **3:4 center crop**: `y=240–1680`
- Title sits in the **upper crop**, below the top-left 「刚刚」 badge: `title_y=390`
- Washi labels sit **inside the crop**, left-aligned, near the bowl foot: `labels_y=1528` (~70px above crop bottom)
- Title glyphs are **local 站酷快乐体**, bouncing puffy stickers — never image-model text
- No Japanese. No 「AI菜品示意图」. No speech-bubble clutter

## Compositor

```bash
python styles/wechat-channels-cover/layout_cover.py \
  --photo <hero.png> \
  --title 粉蒸排骨 \
  --labels 炒酱,腌透,裹粉 \
  --out-dir <project>/assets/cover
```

Always show the user: 9:16 cover, 4:5 cover, thumb sim, and crop overlay before locking.
