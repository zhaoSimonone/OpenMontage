#!/usr/bin/env python3
"""Extract burned-in overlay layers (sticker / text / dynamic digits) from a
reel's PRE segment.

Pure edit: no generation, no repainting. Implements the transform-splice-cover
skill sections 4.2 / 4.5 / 4.7.

  * colour comes from the TEMPORAL MEDIAN, never the mean (the mean averages
    away the 1 px sub-pixel wobble of a burned-in graphic and makes it blurry);
  * stability gate = "fraction of frames within median +/- t  >= 0.80", with t
    calibrated from the measured retention of the headline's own pixels;
  * edge alpha is a TRUE sub-pixel matte  a = (M-B).(P-B)/|P-B|^2  with
    B = nearest true background pixel, P = nearest ALPHA-CORE pixel colour;
  * edge colour is taken from the core pixel P (never M/a, which amplifies
    h264 noise into visible stipple);
  * dark strokes are selected on VALUE only: in OpenCV HSV a near-black pixel
    has saturation ~255, so any saturation condition drops the whole outline;
  * the headline is selected by its saturated colour signature and its burned-in
    components are removed from the artwork layer so they cannot bleed into it.

usage:
  extract_overlay_layers.py <reel> <outdir> <C> <title_roi> <digit_roi>
  roi = x0,y0,x1,y1   (title_roi covers the headline band, digit_roi the counter)
"""
import os
import sys
import json
import cv2
import numpy as np

REEL, ROOT = sys.argv[1], sys.argv[2]
C = int(sys.argv[3])
TX = [int(v) for v in sys.argv[4].split(",")]
DX = [int(v) for v in sys.argv[5].split(",")]
LAY, QA = f"{ROOT}/layers", f"{ROOT}/qa"
os.makedirs(f"{LAY}/digit", exist_ok=True)
os.makedirs(QA, exist_ok=True)

# ---------------------------------------------------------------- decode
cap = cv2.VideoCapture(REEL)
frames = []
i = 0
while i < C:
    ok, f = cap.read()
    if not ok:
        break
    frames.append(f)
    i += 1
cap.release()
N = len(frames)
H, W = frames[0].shape[:2]
print(f"PRE {N} frames {W}x{H}")

# ------------------------------------------------- median + stability gate
STRIP = 96
TOLS = [4, 6, 8, 10, 14, 20, 28, 40]
median = np.zeros((H, W, 3), np.uint8)
within = {t: np.zeros((H, W), np.int32) for t in TOLS}
for y0 in range(0, H, STRIP):
    y1 = min(H, y0 + STRIP)
    block = np.stack([f[y0:y1] for f in frames])
    dev = None
    for ch in range(3):
        med = np.median(block[:, :, :, ch], axis=0).astype(np.uint8)
        median[y0:y1, :, ch] = med
        d = np.abs(block[:, :, :, ch].astype(np.int16) - med[None].astype(np.int16))
        dev = d if dev is None else np.maximum(dev, d)
    for t in TOLS:
        within[t][y0:y1] += (dev <= t).sum(axis=0)
    del block, dev
STAB = {t: (within[t] >= 0.80 * N).astype(np.uint8) for t in TOLS}
del within
cv2.imwrite(f"{QA}/pre_median.png", median)

hsv = cv2.cvtColor(median, cv2.COLOR_BGR2HSV)
Hh = hsv[:, :, 0].astype(np.int32)
Ss = hsv[:, :, 1].astype(np.int32)
Vv = hsv[:, :, 2].astype(np.int32)
wall_like = ((Hh >= 4) & (Hh <= 33) & (Ss >= 28) & (Ss <= 105)
             & (Vv >= 45) & (Vv <= 248)).astype(np.uint8)
wall_like = cv2.erode(wall_like, np.ones((5, 5), np.uint8))
M = median.astype(np.float32)


# ---------------------------------------------------------------- helpers
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
    nearest core colour P. Never M/a -- that amplifies h264 noise."""
    col = M.astype(np.float32).copy()
    m = (a > 0.0) & (a <= 0.985)
    if m.any():
        col[m] = P[m].astype(np.float32)
    return col


def save_layer(name, rgb, alpha, bbox):
    x0, y0, x1, y1 = bbox
    sub, sa = rgb[y0:y1, x0:x1], alpha[y0:y1, x0:x1]
    rgba = np.dstack([np.clip(sub, 0, 255).astype(np.uint8), np.clip(sa, 0, 255).astype(np.uint8)])
    cv2.imwrite(f"{LAY}/{name}.png", rgba)
    cv2.imwrite(f"{QA}/{name}_checker.png", checker(sub, sa))     # 1:1 native pixels
    cv2.imwrite(f"{QA}/{name}_alpha.png", np.clip(sa, 0, 255).astype(np.uint8))
    print(f"  saved {name}.png bbox={bbox} {x1-x0}x{y1-y0} alpha>0={int((sa>0).sum())}")


# ================================================================= TITLE
tx0, ty0, tx1, ty1 = TX
roi = (slice(ty0, ty1), slice(tx0, tx1))
roi_s, roi_v = Ss[roi], Vv[roi]

# fill = the saturated coloured glyph body. Keep EVERY component above the
# area floor -- the glyphs are separate components, taking only the largest
# one would keep half a letter.
fill = ((roi_s >= 120) & (roi_v >= 60)).astype(np.uint8)
fill = cv2.morphologyEx(fill, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
n, lab, st, _ = cv2.connectedComponentsWithStats(fill, 8)
keep = np.zeros_like(fill)
for j in range(1, n):
    if st[j, 4] >= 150:
        keep[lab == j] = 1
fill = fill_holes(keep)
fill_full = np.zeros((H, W), np.uint8)
fill_full[roi] = fill

# stroke = the outline hugging the fill. Polarity is decided from the ring.
ring = (cv2.dilate(fill, np.ones((21, 21), np.uint8)) & (1 - fill)).astype(np.uint8)
ring_mean_v = float(Vv[roi][ring > 0].mean()) if ring.sum() else 0.0
bright = ring_mean_v >= 140
if bright:
    stroke = ((roi_v >= 205) & (roi_s <= 55)).astype(np.uint8)
else:
    # A near-black pixel has HSV saturation ~255 (max-min over a tiny max), so
    # the dark stroke must be selected on VALUE only, never with a saturation
    # condition -- that would drop the whole outline.
    stroke = (roi_v <= 95).astype(np.uint8)
stroke = (stroke & ring).astype(np.uint8)
stroke = cv2.morphologyEx(stroke, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
n, lab, st, _ = cv2.connectedComponentsWithStats(stroke, 8)
keep = np.zeros_like(stroke)
for j in range(1, n):
    if st[j, 4] >= 100:
        keep[lab == j] = 1
stroke_full = np.zeros((H, W), np.uint8)
stroke_full[roi] = keep
text_full = ((fill_full | stroke_full) > 0).astype(np.uint8)
print(f"title: ring V={ring_mean_v:.1f} stroke={'BRIGHT' if bright else 'DARK'} "
      f"fill={int(fill_full.sum())}px stroke={int(stroke_full.sum())}px")

# ---- threshold-loss table (§4.2.1) on the headline's OWN pixels ----
calib = []
for t in TOLS:
    s_t = STAB[t]
    tf, ts = int(fill_full.sum()), int(stroke_full.sum())
    kf = int((fill_full & (s_t > 0)).sum())
    ks = int((stroke_full & (s_t > 0)).sum())
    calib.append({"tol": t, "fill_kept": kf, "fill_total": tf,
                  "fill_ratio": round(kf / max(tf, 1), 4),
                  "stroke_kept": ks, "stroke_total": ts,
                  "stroke_ratio": round(ks / max(ts, 1), 4)})
    print(f"  tol +-{t:2d}: fill {kf}/{tf} = {kf/max(tf,1):.4f} | stroke {ks}/{ts} = {ks/max(ts,1):.4f}")

# artwork gate tolerance: pick the tolerance whose graphic area has plateaued
areas = []
for t in TOLS:
    g = (STAB[t] & (1 - wall_like)).astype(np.uint8)
    g = cv2.morphologyEx(g, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    g = cv2.morphologyEx(g, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    areas.append(int(g.sum()))
print("graphic area vs tolerance:", dict(zip(TOLS, areas)))
TOL = 6
stable = STAB[TOL]
print(f"artwork gate tolerance = +-{TOL}")
cv2.imwrite(f"{QA}/stable_map.png", stable * 255)

# ================================================================= ARTWORK
graphic = (stable & (1 - wall_like)).astype(np.uint8)
graphic = cv2.morphologyEx(graphic, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
graphic = cv2.morphologyEx(graphic, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
n, lab, st, _ = cv2.connectedComponentsWithStats(graphic, 8)
keep = np.zeros_like(graphic)
comps = []
for j in range(1, n):
    x, y, w, h, a = st[j]
    if a < 400:
        continue
    keep[lab == j] = 1
    comps.append({"box": [int(x), int(y), int(x + w), int(y + h)], "area": int(a)})
graphic = keep
print(f"graphic components: {len(comps)}")
for c in sorted(comps, key=lambda c: -c["area"])[:8]:
    print(f"   {c['box']} area={c['area']}")
cv2.imwrite(f"{QA}/graphic_mask.png", graphic * 255)

b_minus_r = median[:, :, 0].astype(np.int16) - median[:, :, 2].astype(np.int16)
warm = int((graphic & (b_minus_r > 18)).sum())
print(f"cold-bias (b-r) in graphic: median {np.median(b_minus_r[graphic>0]):.1f}, warm(>18) {warm}px")

# the headline's burned-in components belong to the text layers, not the artwork
title_graphic = np.zeros((H, W), np.uint8)
for j in range(1, n):
    x, y, w, h, a = st[j]
    if a >= 400 and y + h <= ty1 + 20:
        title_graphic[y:y + h, x:x + w] = graphic[y:y + h, x:x + w]

cluster_core = (graphic & (1 - text_full) & (1 - title_graphic)).astype(np.uint8)
cluster_core = fill_holes(cluster_core)
n, lab, st, _ = cv2.connectedComponentsWithStats(cluster_core, 8)
keep = np.zeros_like(cluster_core)
ccomps = []
for j in range(1, n):
    x, y, w, h, a = st[j]
    if a < 1500:
        continue
    keep[lab == j] = 1
    ccomps.append({"box": [int(x), int(y), int(x + w), int(y + h)], "area": int(a)})
cluster_core = keep
cb = bbox_of(cluster_core)
print(f"artwork bbox {cb} comps={len(ccomps)}")
far_c = (cv2.erode((1 - cluster_core).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0)
B_c = nearest_field(far_c, M)
P_c = nearest_field(cluster_core, M)
band_c = ((cv2.dilate(cluster_core, np.ones((7, 7), np.uint8)) & (1 - cluster_core))).astype(np.float32)
a_cl = np.where(cluster_core > 0, 1.0, projection_alpha(M, P_c, B_c, band_c)).astype(np.float32)
save_layer("cluster", edge_colour(M, P_c, a_cl), a_cl * 255, cb)

# ================================================================= TITLE PLATES
P_fill = nearest_field(fill_full, M)
C_stroke = nearest_field(stroke_full, M) if stroke_full.sum() else M.copy()
inner = ((cv2.dilate(fill_full, np.ones((5, 5), np.uint8)) & (1 - fill_full))).astype(np.float32)
a_fill = np.where(fill_full > 0, 1.0, projection_alpha(M, P_fill, C_stroke, inner)).astype(np.float32)

far = (cv2.erode((1 - text_full).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0)
B_far = nearest_field(far, M)
P_stroke = nearest_field(stroke_full, M)
outer = ((cv2.dilate(text_full, np.ones((7, 7), np.uint8)) & (1 - text_full))).astype(np.float32)
a_stroke = np.where(stroke_full > 0, 1.0, projection_alpha(M, P_stroke, B_far, outer)).astype(np.float32)

fill_bb, stroke_bb, title_bb = bbox_of(fill_full), bbox_of(stroke_full), bbox_of(text_full)
save_layer("title_fill", edge_colour(M, P_fill, a_fill), a_fill * 255, fill_bb)
save_layer("title_stroke", edge_colour(M, P_stroke, a_stroke), a_stroke * 255, stroke_bb)
print(f"title fill {fill_bb} stroke {stroke_bb} union {title_bb}")

# ================================================================= DIGIT (dynamic)
dx0, dy0, dx1, dy1 = DX
samples = []
for f in frames:
    c = f[dy0:dy1, dx0:dx1]
    h2 = cv2.cvtColor(c, cv2.COLOR_BGR2HSV)
    m = h2[:, :, 1] > 140
    if m.sum() < 200:
        continue
    samples.append(c[m].astype(np.float32))
DIGIT_FILL = (np.median(np.concatenate(samples, 0), 0) if samples
               else np.array([235.0, 150.0, 20.0]))
print(f"digit fill BGR={DIGIT_FILL}")

digit_boxes, content_boxes, present = [], [], []
for t in range(N):
    fr = frames[t]
    c = fr[dy0:dy1, dx0:dx1].astype(np.float32)
    fm = (np.abs(c - DIGIT_FILL).sum(axis=2) < 150).astype(np.uint8)
    fm = cv2.morphologyEx(fm, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n2, l2, s2, _ = cv2.connectedComponentsWithStats(fm, 8)
    if n2 <= 1 or s2[1 + int(np.argmax(s2[1:, 4])), 4] < 250:
        digit_boxes.append(None); content_boxes.append(None); present.append(False)
        continue
    big = 1 + int(np.argmax(s2[1:, 4]))
    fm = (l2 == big).astype(np.uint8)
    ringm = cv2.dilate(fm, np.ones((13, 13), np.uint8))
    hv = cv2.cvtColor(fr[dy0:dy1, dx0:dx1], cv2.COLOR_BGR2HSV)
    dark = (hv[:, :, 2] < 90).astype(np.uint8)
    core = (fm | (ringm & dark)).astype(np.uint8)
    core = fill_holes(cv2.morphologyEx(core, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)))
    ys, xs = np.nonzero(core)
    if len(ys) < 200:
        digit_boxes.append(None); content_boxes.append(None); present.append(False)
        continue
    bb = [dx0 + int(xs.min()), dy0 + int(ys.min()), dx0 + int(xs.max()) + 1, dy0 + int(ys.max()) + 1]
    content_boxes.append(bb); present.append(True)
    pad = 5
    bx0 = max(dx0, bb[0] - pad); by0 = max(dy0, bb[1] - pad)
    bx1 = min(dx1, bb[2] + pad); by1 = min(dy1, bb[3] + pad)
    sub = fr[by0:by1, bx0:bx1].astype(np.float32)
    subcore = core[by0 - dy0:by1 - dy0, bx0 - dx0:bx1 - dx0]
    P_d = nearest_field(subcore, sub)
    far_d = (cv2.erode((1 - subcore).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0)
    B_d = nearest_field(far_d, sub)
    band_d = ((cv2.dilate(subcore, np.ones((7, 7), np.uint8)) & (1 - subcore))).astype(np.float32)
    a_d = np.where(subcore > 0, 1.0, projection_alpha(sub, P_d, B_d, band_d)).astype(np.float32)
    rgba = np.dstack([np.clip(edge_colour(sub, P_d, a_d), 0, 255).astype(np.uint8),
                      np.clip(a_d * 255, 0, 255).astype(np.uint8)])
    cv2.imwrite(f"{LAY}/digit/d{t:04d}.png", rgba)
    digit_boxes.append([bx0, by0, bx1, by1])

wins = []
s = None
for t, p in enumerate(present + [False]):
    if p and s is None:
        s = t
    elif not p and s is not None:
        wins.append([s, t - 1]); s = None
print(f"digit visible {sum(present)}/{N} frames, windows {wins}")
json.dump({"fill_bgr": [float(x) for x in DIGIT_FILL], "boxes": digit_boxes,
           "content_boxes": content_boxes, "present": present, "windows": wins},
          open(f"{LAY}/digit_meta.json", "w"))

json.dump({"C": C, "W": W, "H": H, "FPS": 30, "N_PRE": N,
           "TITLE_FILL_BBOX": fill_bb, "TITLE_STROKE_BBOX": stroke_bb, "TITLE_BBOX": title_bb,
           "CLUSTER_BBOX": cb, "DIGIT_ROI": DX,
           "DIGIT_FILL_BGR": [float(x) for x in DIGIT_FILL], "DIGIT_WINDOWS": wins,
           "CLUSTER_COMPS": ccomps, "ARTWORK_TOL": TOL,
           "THRESHOLD_LOSS_TABLE": calib, "GRAPHIC_AREA_VS_TOL": dict(zip(TOLS, areas)),
           "STROKE_POLARITY": "bright" if bright else "dark",
           "COLD_BIAS_MEDIAN_IN_GRAPHIC": float(np.median(b_minus_r[graphic > 0])),
           "WARM_PX_IN_GRAPHIC": warm},
          open(f"{LAY}/overlay_geom.json", "w"), indent=2)
print("done")
