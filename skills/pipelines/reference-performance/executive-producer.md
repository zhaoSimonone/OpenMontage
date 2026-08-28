# Executive Producer - Reference Performance Pipeline

## Purpose

Use this pipeline when a target character image must perform the actions and
facial performance of a reference video. The target image owns identity and
wardrobe; the reference video owns timed performance information.

## Quality priority

```text
action order > expression timing > identity > continuity > beauty
```

"Looks like the character" is not sufficient if the hands, body rhythm, gaze,
or expression reset to a generic pose.

## Rules

1. Run `performance_analysis` before compiling an H3 request.
2. Every performance beat records body action and facial action separately.
3. Use `reference_performance_h3_plan` before any paid generation.
4. Use `reference_performance_qa` after generation; missing expression review is
   not a pass.
5. Keep provider/model changes behind an explicit approval gate.

## Fallback

Do not silently switch away from MiniMax-H3. A failed performance review may
recommend a different control path, but the user must approve that change.
