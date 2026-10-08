# Cover Style — WeChat Channels

## When to Use

Any time this pipeline (or a sequel 视频号 video) needs a cover. Golden reference: `styles/wechat-channels-cover/examples/golden_cover_9x16.jpg`.

## Hard rules

1. **Image model draws food only.** Prompt must forbid text, letters, captions, watermarks, Japanese, 「AI菜品示意图」.
2. **Type is local.** Overlay with `styles/wechat-channels-cover/fonts/ZCOOLKuaiLe-Regular.ttf` via `layout_cover.py`.
3. **Bouncing puffy title**, cream/lemon/peach washi labels, **left-aligned**, max 3.
4. **No extra stickers** (hearts, 家常菜 bubble, 好吃 star) unless the user asks.
5. Deliver **9:16 and 4:5**. 视频号主页 thumb is ~3:4 center crop of 9:16.

## Geometry (1080×1920)

| Item | Value |
|------|-------|
| Crop | `y=240–1680` (3:4 centered) |
| Title | `title_y=390`, fitted to `width-56` |
| Labels | `labels_y=1528`, `x=36`, keep ≥70px above crop bottom |
| Badge | Top-left 「刚刚」 can hide a full-bleed 粉 — keep side inset |

If the user says the title is too high on the published thumb, move **down inside the crop**, not up into the badge. If they say the 9:16 looks empty in the red box, move **up toward `title_y=390`**, not back to y=0.

## Approval pack

Always attach:

- 9:16 cover
- 4:5 cover
- `wechat_thumb_sim.jpg` (刚刚 overlay)
- `wechat_crop_overlay.jpg` (red box)

Compare against `examples/golden_cover_9x16.jpg`. If the new title sits on the ribs or the labels fall outside the red box, fix before locking.

## Command

```bash
python styles/wechat-channels-cover/layout_cover.py \
  --photo <hero.png> \
  --title <四字中文> \
  --labels <标签1>,<标签2>,<标签3> \
  --out-dir projects/<id>/assets/cover
```
