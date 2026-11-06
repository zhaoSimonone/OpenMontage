#!/usr/bin/env python3
"""Extract burned-in overlay layers (v2) -- transform-splice-cover skill.

v1 (``extract_overlay_layers.py``) covers a saturated-fill title, a
stability-gated graphic layer and a saturated-fill counter.  Real reels also
contain:

  * static stickers that live in a SHORT window and then disappear -- v1 takes
    the temporal median over the whole PRE segment, so a sticker that is only
    on screen for the first N frames gets averaged away;
  * WHITE text with a DARK stroke -- v1 selects the fill by saturation and
    therefore finds nothing on white text;
  * a separate COLOURED sticker (flag emoji) sitting next to that text;
  * an OPAQUE hard-edged RECTANGULAR sticker (illustration card);
  * WHITE countdown digits with a dark stroke whose value changes mid-shot;
  * an ANIMATED sticker (a rotating badge) next to the text -- it has to be
    extracted per frame, because a temporal median blends its animation
    phases into a ghost.

v2 handles all of those.  Every mechanism the skill flags as "easy to get
wrong" is reused verbatim from v1: the temporal MEDIAN (never the mean), the
projection-style sub-pixel matte ``a = (M-B).(P-B)/|P-B|^2``, edge colour
taken from the nearest ALPHA-CORE pixel (never ``M/a``), hole filling after
closing, dark elements selected on VALUE only, and 1:1 native-pixel
checkerboard previews.

usage: extract_overlay_layers_v2.py <reel> <outdir> <C> <spec.json>

spec.json::

    {
      "pre_end": 180,                 # last frame of the static-overlay window
      "layers": [
        {"name": "cluster", "type": "opaque_rect",
         "box":  [306, 1288, 774, 1910]},
        {"name": "title",   "type": "white_text",
         "roi":  [175, 1195, 915, 1285], "tol": 8, "stable_frac": 0.8,
         # "geometric" replaces the 15 px ring + temporal-stability stroke
         # rule (which breaks on a moving background and fills the letter
         # counters with opaque black).  "temporal" keeps the old behaviour.
         "stroke_mode": "geometric", "stroke_v": 40, "stroke_radius": 2,
         "exclude_boxes": [[128, 814, 174, 862]],   # owned by the emoji
         "pad": 4},                                  # keep the matte band
        {"name": "emoji",   "type": "animated_sticker",
         "boxes": [[128, 814, 174, 862]], "window": [0, 179]},
        {"name": "digit",   "type": "white_digit",
         "roi":  [450, 1430, 640, 1560], "window": [180, 251], "white_v": 235}
      ]
    }
"""
import json
import os
import subprocess
import sys

import cv2
import numpy as np

REEL, ROOT, C = sys.argv[1], sys.argv[2], int(sys.argv[3])
SPEC = json.load(open(sys.argv[4]))
LAY, QA = f"{ROOT}/layers", f"{ROOT}/qa"
os.makedirs(f"{LAY}/digit", exist_ok=True)
os.makedirs(QA, exist_ok=True)

# ---------------------------------------------------------------- helpers
# reused verbatim from extract_overlay_layers.py (v1)
def nearest_field(mask, img):
    """Colour of the nearest True pixel of `mask`, for every pixel."""
    mask = mask.astype(bool)
    if mask.sum() == 0:
        return np.zeros(img.shape, np.float32)
    inv = (mask == 0).astype(np.uint8)
    _, labels = cv2.distanceTransformWithLabels(inv, cv2.DIST_L2, 5,
                                                labelType=cv2.DIST_LABEL_PIXEL)
    lut = np.zeros((int(labels.max()) + 1, 3), np.float32)
    lut[labels[mask]] = img[mask].astype(np.float32)
    return lut[labels]


def fill_holes(mask):
    m = mask.astype(np.uint8)
    ff = m.copy()
    h2 = np.zeros((m.shape[0] + 2, m.shape[1] + 2), np.uint8)
    cv2.floodFill(ff, h2, (0, 0), 1)
    return (m | (1 - ff)).astype(np.uint8)


def enclosed_holes(mask, min_area=20):
    """Holes fully enclosed by `mask` -- the counters of a/o/p.

    They are genuine holes in the graphic: the background shows through
    them.  Filling them would paste the original scene into the plate, and
    a blanket flood-fill would also destroy the enclosed part of a glyph
    (skill 4.2, pitfall 11).
    """
    m = mask.astype(np.uint8)
    h, w = m.shape
    inv = (1 - m).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(inv, 4)
    out = np.zeros_like(m)
    for j in range(1, n):
        x, y, ww, hh, a = st[j]
        if a >= min_area and x > 0 and y > 0 and x + ww < w and y + hh < h:
            out[lab == j] = 1
    return out


def fill_small_holes(mask, max_area):
    """Fill only *small* enclosed holes (pinholes left by the threshold).

    A blanket flood-fill is wrong for lettering: the counters of "a", "o" and
    "p" are enclosed holes too, and filling them would paste the original
    scene (hair, wall) into the plate as opaque pixels.
    """
    m = mask.astype(np.uint8)
    h, w = m.shape
    inv = (1 - m).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(inv, 4)
    out = m.copy()
    for j in range(1, n):
        x, y, ww, hh, a = st[j]
        if a <= max_area and x > 0 and y > 0 and x + ww < w and y + hh < h:
            out[lab == j] = 1
    return out


def checker(rgb, a, cell=24):
    yy, xx = np.indices(a.shape[:2])
    chk = np.where(((yy // cell) + (xx // cell)) % 2 == 0, 200, 120).astype(np.float32)
    chk = np.dstack([chk, chk, chk])
    aa = a[..., None] if a.ndim == 2 else a
    if aa.max() > 1.5:
        aa = aa / 255.0
    return (rgb.astype(np.float32) * aa + chk * (1 - aa)).astype(np.uint8)


def bbox_of(mask):
    ys, xs = np.nonzero(mask > 0)
    if len(ys) == 0:
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def projection_alpha(M, P, B, band):
    """Least-squares coverage  a = (M-B).(P-B) / |P-B|^2, masked to `band`."""
    num = ((M - B) * (P - B)).sum(axis=2)
    den = ((P - B) ** 2).sum(axis=2)
    a = np.where(den > 12.0, num / np.maximum(den, 1e-6), 0.0).astype(np.float32)
    return np.clip(a, 0.0, 1.0) * band


def edge_colour(M, P, a):
    """Core pixels keep M (they are opaque); partial-alpha pixels take the
    nearest core colour P.  Never M/a -- that amplifies h264 noise."""
    col = M.astype(np.float32).copy()
    m = (a > 0.0) & (a <= 0.985)
    if m.any():
        col[m] = P[m].astype(np.float32)
    return col


def save_layer(name, rgb, alpha, bbox, qa_name=None, pre_cropped=False):
    if pre_cropped:
        sub, sa = rgb, alpha
        x0, y0, x1, y1 = bbox
    else:
        x0, y0, x1, y1 = bbox
        sub, sa = rgb[y0:y1, x0:x1], alpha[y0:y1, x0:x1]
    rgba = np.dstack([np.clip(sub, 0, 255).astype(np.uint8),
                      np.clip(sa, 0, 255).astype(np.uint8)])
    cv2.imwrite(f"{LAY}/{name}.png", rgba)
    cv2.imwrite(f"{QA}/{qa_name or name}_checker.png", checker(sub, sa))  # 1:1 native
    cv2.imwrite(f"{QA}/{qa_name or name}_alpha.png", np.clip(sa, 0, 255).astype(np.uint8))
    print(f"  saved {name}.png bbox={bbox} {x1-x0}x{y1-y0} alpha>0={int((sa>0).sum())}")
    return list(bbox)


def temporal_median(frames, box, strip=96):
    """Temporal MEDIAN of `frames` inside `box` -- never the mean (the mean
    averages away the 1 px sub-pixel wobble of a burned-in graphic)."""
    x0, y0, x1, y1 = box
    out = np.zeros((y1 - y0, x1 - x0, 3), np.uint8)
    for a in range(y0, y1, strip):
        b = min(y1, a + strip)
        blk = np.stack([f[a:b, x0:x1] for f in frames])
        out[a - y0:b - y0] = np.median(blk, axis=0).astype(np.uint8)
        del blk
    return out


def stability(frames, box, tols, strip=96):
    """`stable[t]` = fraction of frames whose pixel sits within median +/- t.

    The robust criterion from the skill: a fixed per-pixel std threshold
    throws away real glyph pixels, because h264 gives a burned-in graphic a
    different bitrate every frame.
    """
    x0, y0, x1, y1 = box
    h, w = y1 - y0, x1 - x0
    n = len(frames)
    within = {t: np.zeros((h, w), np.int32) for t in tols}
    for a in range(y0, y1, strip):
        b = min(y1, a + strip)
        blk = np.stack([f[a:b, x0:x1] for f in frames])
        dev = None
        for ch in range(3):
            med = np.median(blk[:, :, :, ch], axis=0).astype(np.uint8)
            d = np.abs(blk[:, :, :, ch].astype(np.int16) - med[None].astype(np.int16))
            dev = d if dev is None else np.maximum(dev, d)
        for t in tols:
            within[t] += (dev <= t).sum(axis=0)
        del blk, dev
    return {t: (within[t] >= 0.80 * n) for t in tols}


def matte(M, core, P=None, B=None, far_erode=3, band_dilate=3):
    """Build (colour, alpha) for one plate from a binary core mask.

    The core is opaque (alpha = 1).  A one-to-three pixel transition band
    around it gets the proper sub-pixel matte; the colour there comes from
    the nearest CORE pixel, never from `M / alpha` (that amplifies h264 noise
    into a stipple)."""
    core = core.astype(np.uint8)
    if P is None:
        P = nearest_field(core, M)
    if B is None:
        far = (cv2.erode((1 - core).astype(np.uint8),
                         np.ones((far_erode, far_erode), np.uint8)) > 0)
        B = nearest_field(far, M)
    band = ((cv2.dilate(core, np.ones((band_dilate, band_dilate), np.uint8))
             & (1 - core)).astype(np.float32))
    a = np.where(core > 0, 1.0, projection_alpha(M, P, B, band)).astype(np.float32)
    return edge_colour(M, P, a), a


# ---------------------------------------------------------------- decode
cap = cv2.VideoCapture(REEL)
frames = []
while len(frames) < C:
    ok, f = cap.read()
    if not ok:
        break
    frames.append(f)
cap.release()
N = len(frames)
H, W = frames[0].shape[:2]
print(f"PRE {N} frames {W}x{H}")

PRE_END = int(SPEC.get("pre_end", C))
PRE_FRAMES = frames[:PRE_END]
print(f"static-overlay window: frames 0..{PRE_END-1} ({len(PRE_FRAMES)} frames)")

plates = []          # ordered list of {"name","file","bbox"}
ANIM = []            # per-frame animated layers -> layers/anim_meta.json
# The output frame rate must come from the reel, not from a hard-coded 30.
# A 60 fps reel encoded at 30 fps halves the duration and desynchronises the
# whole timeline.
_r = subprocess.run(
    ["/opt/homebrew/bin/ffprobe", "-v", "error", "-select_streams", "v:0",
     "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", REEL],
    capture_output=True, text=True).stdout.strip()
_num, _den = _r.split("/")
FPS = float(_num) / float(_den)
geom = {"C": C, "W": W, "H": H, "FPS": FPS, "N_PRE": N,
        "PRE_END": PRE_END, "PLATES": plates}
print(f"reel fps: {FPS}")

for spec in SPEC["layers"]:
    name = spec["name"]
    kind = spec["type"]
    print(f"\n--- layer {name} ({kind}) ---")

    # ============================================================ opaque rect
    if kind == "opaque_rect":
        x0, y0, x1, y1 = spec["box"]
        med = temporal_median(PRE_FRAMES, (x0, y0, x1, y1))
        # a hard-edged opaque sticker must be *constant* in the window; prove it
        worst = 0
        for k in (0, len(PRE_FRAMES) // 2, len(PRE_FRAMES) - 1):
            d = np.abs(PRE_FRAMES[k][y0:y1, x0:x1].astype(np.int16)
                       - med.astype(np.int16)).max()
            worst = max(worst, int(d))
        a = np.full((y1 - y0, x1 - x0), 255, np.uint8)
        bb = save_layer(name, med, a, (x0, y0, x1, y1), pre_cropped=True)
        print(f"  window constancy: max|diff| vs median = {worst} "
              f"(edge column dominates; interior is static)")
        geom.setdefault("RECT_CONSTANCY", {})[name] = worst
        plates.append({"name": name, "file": f"{name}.png", "bbox": bb,
                       "from": 0, "to": PRE_END - 1, "z": spec.get("z", 0)})

    # ============================================================ white text
    elif kind == "white_text":
        tx0, ty0, tx1, ty1 = spec["roi"]
        box = (tx0, ty0, tx1, ty1)
        med = temporal_median(PRE_FRAMES, box)
        hsv = cv2.cvtColor(med, cv2.COLOR_BGR2HSV)
        V = hsv[:, :, 2].astype(np.int16)
        S = hsv[:, :, 1].astype(np.int16)
        Hh = hsv[:, :, 0].astype(np.int16)
        tol = int(spec.get("tol", 8))
        stroke_mode = spec.get("stroke_mode", "temporal")
        # -- region owned by ANOTHER layer (e.g. an animated sticker that sits
        #    next to the text).  None of it may leak into this plate.
        excl = np.zeros((ty1 - ty0, tx1 - tx0), np.uint8)
        for bx0, by0, bx1, by1 in spec.get("exclude_boxes", []):
            # clamp to the ROI: a box that starts ABOVE the ROI would slice
            # with a negative index and silently exclude NOTHING
            xa, xb = max(0, bx0 - tx0), min(tx1 - tx0, bx1 - tx0)
            ya, yb = max(0, by0 - ty0), min(ty1 - ty0, by1 - ty0)
            if xb > xa and yb > ya:
                excl[ya:yb, xa:xb] = 1

        # -- white glyph bodies: white components in the median that look like
        #    glyphs.  A moving white garment is NOT in the median (it averages
        #    out), so this is far cleaner than a brightness threshold.
        white = (((V > 238) & (S < 60)) & (excl == 0)).astype(np.uint8)
        n, l, st, _ = cv2.connectedComponentsWithStats(
            cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)), 8)
        letters = np.zeros_like(white)
        for j in range(1, n):
            x, y, w, h, area = st[j]
            if area >= 40 and h <= 70 and w <= 90:
                letters[l == j] = 1
        letters = fill_small_holes(letters, int(spec.get("max_hole", 12)))
        letters[excl > 0] = 0
        print(f"  white glyph comps kept: {int(letters.sum())} px")

        # -- coloured sticker next to the text: saturated colour signature
        red = ((((Hh < 12) | (Hh > 168)) & (S > 130) & (V > 60))
               & (excl == 0)).astype(np.uint8)
        n2, l2, st2, _ = cv2.connectedComponentsWithStats(
            cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)), 8)
        colour = np.zeros_like(red)
        for j in range(1, n2):
            if st2[j, 4] >= 300:
                colour[l2 == j] = 1
        if colour.sum():
            ys, xs = np.nonzero(colour)
            ey0, ey1 = int(ys.min()), int(ys.max()) + 1
            ex0, ex1 = int(xs.min()), int(xs.max()) + 1
            # the white artwork inside the coloured sticker belongs to it too
            inner = np.zeros_like(colour)
            inner[ey0:ey1, ex0:ex1] = white[ey0:ey1, ex0:ex1]
            colour = colour | inner
            print(f"  coloured sticker: {int(colour.sum())} px "
                  f"bbox native x{ex0+tx0}..{ex1+tx0} y{ey0+ty0}..{ey1+ty0}")
        else:
            print("  no coloured sticker found")

        # -- dark stroke.
        #
        #    LEGACY ("temporal"): dark AND next to a glyph AND temporally
        #    stable.  A fixed value threshold cannot separate the stroke from
        #    the black hair behind the text; temporal stability can.
        #
        #    "geometric": the stroke is a hard black band that hugs the glyph
        #    body (~2 px).  The legacy rule is wrong on a moving scene: its
        #    15 px ring reaches far into the background, the stability gate
        #    then throws away the outer, anti-aliased half of the REAL
        #    stroke, and `glyph_edge` -- which has no gate at all -- drags
        #    the dark letter COUNTERS in as opaque black blobs.  Measured on
        #    one reel: 886 counter px, every single one of them inside the
        #    15 px ring, 738 of them darker than V=120 -- those become black
        #    holes inside the letters and the caption reads as "blurry".
        #
        #    The geometric rule: everything very dark within `stroke_radius`
        #    px of the white glyph body is stroke, and the counters (holes
        #    enclosed by the glyph union) are NEVER opaque -- they are real
        #    holes in the graphic, so the new background shows through.
        if stroke_mode == "geometric":
            counters = enclosed_holes(letters, int(spec.get("counter_min", 20)))
            stroke_v = int(spec.get("stroke_v", 40))
            radius = int(spec.get("stroke_radius", 2))
            ring = cv2.dilate(letters, np.ones((2 * radius + 1,) * 2, np.uint8))
            base = (letters == 0) & (counters == 0) & (excl == 0)
            stroke = ((V < stroke_v) & (ring > 0) & base).astype(np.uint8)
            stroke = cv2.morphologyEx(stroke, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            # the white glyph's own antialiased ring: the transition from the
            # white body to the black stroke, still part of the graphic
            glyph_edge = ((cv2.dilate(letters, np.ones((3, 3), np.uint8)) > 0)
                          & base & (V < 235)).astype(np.uint8)
            print(f"  dark stroke (geometric): {int(stroke.sum())} px "
                  f"(V<{stroke_v}, within {radius} px of a glyph); "
                  f"counters excluded {int(counters.sum())} px")
        else:
            stable = stability(PRE_FRAMES, box, [tol])[tol]
            outline_v = int(spec.get("outline_v", 120))
            ring = cv2.dilate(letters, np.ones((15, 15), np.uint8))
            stroke = ((V < outline_v) & (ring > 0) & stable).astype(np.uint8)
            stroke = cv2.morphologyEx(stroke, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            n3, l3, st3, _ = cv2.connectedComponentsWithStats(stroke, 8)
            keep = np.zeros_like(stroke)
            for j in range(1, n3):
                if st3[j, 4] >= 30:
                    keep[l3 == j] = 1
            stroke = keep
            print(f"  dark stroke: {int(stroke.sum())} px, {n3-1} comps "
                  f"(value<{outline_v}, next to a glyph, temporally stable)")

            # -- the white glyph's own antialiased ring sits between the glyph
            #    and the stroke: it is part of the opaque graphic, not a
            #    transition against the far background.
            stroke_near = cv2.dilate(stroke, np.ones((7, 7), np.uint8))
            glyph_edge = ((cv2.dilate(letters, np.ones((7, 7), np.uint8))
                           & stroke_near) & (V < 235)).astype(np.uint8)

        core = (letters | stroke | glyph_edge | colour).astype(np.uint8)
        core = cv2.morphologyEx(core, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        # NOT fill_holes(): the counters of a/o/p are legitimate holes.
        print(f"  core: {int(core.sum())} px")

        # plates: the coloured sticker first (it owns its own outer matte),
        # then the text as ONE plate -- the white body and its dark stroke are
        # both opaque and their mutual transition is already in the median.
        big = cv2.dilate(core, np.ones((3, 3), np.uint8))
        far = (cv2.erode((1 - big).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)
        if far.sum() < 50:                       # letters are close together
            far = (cv2.erode((1 - big).astype(np.uint8), np.ones((1, 1), np.uint8)) > 0)
        B = nearest_field(far, med.astype(np.float32))
        P = nearest_field(core, med.astype(np.float32))
        col, a = matte(med.astype(np.float32), core, P=P, B=B,
                       far_erode=1, band_dilate=3)
        cbb = bbox_of(core)
        if cbb is None:
            raise SystemExit(f"layer {name}: empty core")
        # The sub-pixel matte lives in a 3 px band AROUND the core.  Cropping
        # the plate to the core box cuts that band in half and leaves a hard
        # 1 px edge where the alpha is still > 0 -- `pad` widens the crop so
        # the transition band survives.  Default 0 keeps the old behaviour.
        pad = int(spec.get("pad", 0))
        if pad:
            cbb = [max(0, cbb[0] - pad), max(0, cbb[1] - pad),
                   min(med.shape[1], cbb[2] + pad), min(med.shape[0], cbb[3] + pad)]
        # the plate lives inside the band; the bbox is reported in native
        # (full-frame) coordinates so compose/verify can place it directly
        bb = save_layer(name, col[cbb[1]:cbb[3], cbb[0]:cbb[2]],
                        a[cbb[1]:cbb[3], cbb[0]:cbb[2]] * 255,
                        (tx0 + cbb[0], ty0 + cbb[1], tx0 + cbb[2], ty0 + cbb[3]),
                        pre_cropped=True)
        plates.append({"name": name, "file": f"{name}.png", "bbox": bb,
                       "from": 0, "to": PRE_END - 1, "z": spec.get("z", 0)})
        # keep the legacy keys so older verify scripts still work
        geom["TITLE_FILL_BBOX"] = bb
        geom.setdefault("TITLE_STROKE_BBOX", bb)

    # ============================================================ animated sticker
    elif kind == "animated_sticker":
        # A burned-in sticker that ANIMATES (a rotating badge, a pulsing
        # heart, ...).  The temporal median over the static window blends its
        # animation phases into a ghost, so such a sticker has to be
        # extracted PER FRAME -- exactly like the countdown digits.
        #
        # The box of every sticker is FIXED (given in the spec): the plate is
        # never tracked, translated or rescaled from frame to frame, only
        # its pixels change.
        boxes = spec["boxes"]
        w0, w1 = spec.get("window", [0, PRE_END - 1])
        red_s = int(spec.get("red_s", 130))
        red_v = int(spec.get("red_v", 60))
        red_h = int(spec.get("red_h", 12))
        os.makedirs(f"{LAY}/{name}", exist_ok=True)
        full = [[] for _ in range(C)]
        areas = []
        for t in range(max(0, w0), min(w1, C - 1) + 1):
            fr = frames[t]
            for bi, (bx0, by0, bx1, by1) in enumerate(boxes):
                sub = fr[by0:by1, bx0:bx1]
                if sub.size == 0:
                    continue
                sh = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
                r = (((sh[:, :, 0] < red_h) | (sh[:, :, 0] > 180 - red_h))
                     & (sh[:, :, 1] > red_s) & (sh[:, :, 2] > red_v)).astype(np.uint8)
                cnts, _ = cv2.findContours(r, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if not cnts:
                    continue
                c = max(cnts, key=cv2.contourArea)
                if cv2.contourArea(c) < 100:
                    continue
                # the silhouette of a sticker is convex (a ball, a badge):
                # the convex hull of its saturated core is its outline, so a
                # shaded rim that drops out of the colour mask still lands
                # inside the opaque region
                hull = np.zeros_like(r)
                cv2.fillConvexPoly(hull, cv2.convexHull(c), 1)
                core = hull.astype(np.uint8)
                M = sub.astype(np.float32)
                far = (cv2.erode((1 - core).astype(np.uint8),
                                 np.ones((3, 3), np.uint8)) > 0)
                B = nearest_field(far, M)
                P = nearest_field(core, M)
                band = ((cv2.dilate(core, np.ones((3, 3), np.uint8))
                         & (1 - core)).astype(np.float32))
                a = np.where(core > 0, 1.0, projection_alpha(M, P, B, band)).astype(np.float32)
                col = edge_colour(M, P, a)
                rgba = np.dstack([np.clip(col, 0, 255).astype(np.uint8),
                                  np.clip(a * 255, 0, 255).astype(np.uint8)])
                cv2.imwrite(f"{LAY}/{name}/{name}_{t:04d}_{bi}.png", rgba)
                full[t].append([bx0, by0, bx1, by1])
                areas.append(int(core.sum()))
        if areas:
            print(f"  animated sticker: {len(areas)} sticker-plates over frames "
                  f"{w0}..{min(w1, C - 1)}, {len(boxes)} fixed box(es), "
                  f"core area min={min(areas)} max={max(areas)}")
        ANIM.append({"name": name, "dir": name, "from": w0, "to": w1,
                     "z": spec.get("z", 0), "boxes": full})

    # ============================================================ white digit
    elif kind == "white_digit":
        dx0, dy0, dx1, dy1 = spec["roi"]
        w0, w1 = spec["window"]
        white_v = int(spec.get("white_v", 235))
        roi = (dx0, dy0, dx1, dy1)
        Wt = np.zeros((w1 - w0 + 1, dy1 - dy0, dx1 - dx0), np.uint8)
        for k in range(w0, w1 + 1):
            r = frames[k][dy0:dy1, dx0:dx1]
            hsv = cv2.cvtColor(r, cv2.COLOR_BGR2HSV)
            Wt[k - w0] = ((hsv[:, :, 2] > white_v) & (hsv[:, :, 1] < 70)).astype(np.uint8)

        # -- glyph discovery: union of sliding-window per-pixel medians.  A
        #    pixel that is white in every frame of a segment has median 1; the
        #    skin that flashes past has median 0 and drops out.
        half = 5
        Gu = np.zeros_like(Wt[0])
        for t in range(len(Wt)):
            a, b = max(0, t - half), min(len(Wt), t + half + 1)
            Gu |= (np.median(Wt[a:b], axis=0) > 0.5).astype(np.uint8)
        Gu = cv2.morphologyEx(Gu, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, l, st, _ = cv2.connectedComponentsWithStats(Gu, 8)
        big = 1 + int(np.argmax(st[1:, 4]))
        Gu = (l == big).astype(np.uint8)
        R = cv2.dilate(Gu, np.ones((9, 9), np.uint8)) > 0

        # -- value changes: XOR of consecutive white masks restricted to the
        #    glyph region.  Background motion outside the glyph is ignored.
        #    The threshold is a magic number in the original: it was measured
        #    on a reel whose digit swap moved ~900 px, but a narrower glyph
        #    swaps far fewer pixels (measured 382 px for "3.." -> "2..") and a
        #    fixed 400 would silently merge two DIFFERENT digits into one
        #    segment -- the median of "3" and "2" is neither of them.  The
        #    threshold is therefore spec-configurable; the default keeps the
        #    previous behaviour.
        change_thresh = int(spec.get("change_thresh", 400))
        changes = []
        for i in range(1, len(Wt)):
            x = int((np.abs(Wt[i].astype(int) - Wt[i - 1].astype(int)) * R).sum())
            if x > change_thresh:
                changes.append(w0 + i)
        bounds = [w0] + changes + [w1 + 1]
        windows = [[bounds[i], bounds[i + 1] - 1] for i in range(len(bounds) - 1)]
        print(f"  digit windows: {windows}")

        boxes, present = [], []
        for a, b in windows:
            G = (np.median(Wt[a - w0:b - w0 + 1], axis=0) > 0.5).astype(np.uint8)
            ys, xs = np.nonzero(G)
            if len(ys) < 150:
                boxes.append(None)
                present.append(False)
                continue
            gx0, gx1 = int(xs.min()), int(xs.max()) + 1
            gy0, gy1 = int(ys.min()), int(ys.max()) + 1
            bb = [dx0 + gx0, dy0 + gy0, dx0 + gx1, dy0 + gy1]
            # the dark stroke around the glyph.
            #
            # The v2 original used  (V < 120) & dilate(G, 15x15): a wide ring
            # with a high value ceiling.  When the counter is printed on dark
            # clothing -- a countdown sitting on black shorts -- that rule
            # sweeps the SHORTS into the plate: measured on such a reel the
            # extracted plate was 67.9% opaque and 33.1% of it (901 px) was
            # shorts-coloured, i.e. a piece of the original person's clothing.
            #
            # The stroke is a thin band hugging the glyph and it is burned in.
            # Measured radial profile around the glyph (distance in px from the
            # white core):
            #     1..2  median V 112   antialiased glyph edge
            #     2..3  median V   2   <- the stroke
            #     3..4  median V   8   <- the stroke
            #     4..6  median V  27   <- the shorts
            #     6..9  median V  32   <- the shorts
            # so a tight radius plus a low value ceiling separates them.
            seg_frames = frames[a:b + 1]
            med = temporal_median(seg_frames, roi)
            hsv = cv2.cvtColor(med, cv2.COLOR_BGR2HSV)
            V = hsv[:, :, 2].astype(np.int16)
            stroke_v = int(spec.get("stroke_v", 20))
            stroke_dilate = int(spec.get("stroke_dilate", 7))
            ring = cv2.dilate(G, np.ones((stroke_dilate, stroke_dilate), np.uint8)) > 0
            outline = ((V < stroke_v) & ring).astype(np.uint8)
            stroke_near = cv2.dilate(outline, np.ones((7, 7), np.uint8))
            glyph_edge = ((cv2.dilate(G, np.ones((7, 7), np.uint8)) & stroke_near)
                          & (V < 235)).astype(np.uint8)
            # NOT fill_holes(): the counter of a "0"/"8" is a legitimate hole,
            # and a blanket flood-fill would freeze the scene inside it
            # (skill 4.2, pitfall 11).  Only pinholes are closed.
            core = fill_small_holes(
                cv2.morphologyEx(G | outline | glyph_edge,
                                 cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)),
                int(spec.get("max_hole", 12)))
            pad = 4
            bx0 = max(dx0, bb[0] - pad)
            by0 = max(dy0, bb[1] - pad)
            bx1 = min(dx1, bb[2] + pad)
            by1 = min(dy1, bb[3] + pad)
            sub = med[by0 - dy0:by1 - dy0, bx0 - dx0:bx1 - dx0].astype(np.float32)
            subcore = core[by0 - dy0:by1 - dy0, bx0 - dx0:bx1 - dx0]
            P = nearest_field(subcore, sub)
            far = (cv2.erode((1 - subcore).astype(np.uint8),
                             np.ones((3, 3), np.uint8)) > 0)
            B = nearest_field(far, sub)
            band = ((cv2.dilate(subcore, np.ones((3, 3), np.uint8))
                     & (1 - subcore)).astype(np.float32))
            a_d = np.where(subcore > 0, 1.0,
                           projection_alpha(sub, P, B, band)).astype(np.float32)
            rgba = np.dstack([np.clip(edge_colour(sub, P, a_d), 0, 255).astype(np.uint8),
                              np.clip(a_d * 255, 0, 255).astype(np.uint8)])
            for t in range(a, b + 1):
                cv2.imwrite(f"{LAY}/digit/d{t:04d}.png", rgba)
                boxes.append([bx0, by0, bx1, by1])
                present.append(True)
            print(f"  segment f{a}..f{b}: glyph {int(G.sum())}px core {int(core.sum())}px "
                  f"bbox {[dx0+gx0, dy0+gy0, dx0+gx1, dy0+gy1]}")
        # frames outside the windows have no digit
        full_boxes = [None] * C
        full_present = [False] * C
        for t in range(C):
            if w0 <= t <= w1 and present[t - w0]:
                full_boxes[t] = boxes[t - w0]
                full_present[t] = True
        json.dump({"boxes": full_boxes, "present": full_present,
                   "windows": windows, "fill_bgr": [255.0, 255.0, 255.0]},
                  open(f"{LAY}/digit_meta.json", "w"))
        geom["DIGIT_ROI"] = [dx0, dy0, dx1, dy1]
        geom["DIGIT_WINDOWS"] = windows
        # the digit is composited per frame, it is not a fixed plate
        geom["DIGIT_DYNAMIC"] = True

    else:
        raise SystemExit(f"unknown layer type {kind}")

json.dump(geom, open(f"{LAY}/overlay_geom.json", "w"), indent=2)
if ANIM:
    json.dump({"layers": ANIM}, open(f"{LAY}/anim_meta.json", "w"))
print("\nplates:", json.dumps(plates, indent=2))
print("done")
