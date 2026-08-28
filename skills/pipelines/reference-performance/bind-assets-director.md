# Bind Assets Director - Reference Performance Pipeline

## Role separation

When `appearance_adaptation.decision = "NOT_NEEDED"`, the original identity
image is authoritative for the target character's face, hair, body
proportions, age, wardrobe, and accessories.

When `appearance_adaptation.decision = "APPROVED"`, the original identity
image remains authoritative for immutable identity: face shape, facial
proportions, eye color, age, body proportions, and character identity. The
approved adapted image is authoritative only for the approved styling
attributes: wardrobe, hair arrangement, makeup, palette, lighting, and setting.

Do not pass `CANDIDATES_READY` or `REJECTED` as a usable target appearance.

The reference video is authoritative for action order, body rhythm, hand
gestures, head angles, gaze, blinks, expressions, pauses, timing, and the
style contract extracted by the appearance-adaptation stage. It is never
authoritative for the source performer's identity.

Never bind the source performer as a second character. For single-character
work, the source performer is an invisible motion source.

## Provider readiness

If MiniMax-H3 requires HTTPS URLs, upload local media through the approved
media uploader and verify anonymous `HEAD` access, content type, and size
before planning.
