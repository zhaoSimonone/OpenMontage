#!/usr/bin/env python3
"""Compose the transform-splice-cover result in the YUV domain.

Why a second compositor?  The RGB compositor (``compose_splice.py``) decodes
to full-range RGB, composites there and encodes back to limited-range
yuv420p.  That round trip re-subsamples the chroma and rounds the luma, so
even the frames that are copied verbatim from the reel come out measurably
different from the source: measured on a 1080x1920 bt709/tv reel, the
untouched POST segment lost ~2.6 luma levels (PSNR 39.2 dB in Y) even though
a plain transcode of the same reel keeps 49.7 dB.

The skill allows this alternative explicitly (section 6.3: "若使用 YUV 直接
混合，色度 Alpha 要按 2x2 降采样").  Here the whole film is handled as
planar yuv420p:

  * video1 is decoded to yuv420p planes and scaled in the YUV domain;
  * the reel's POST frames are used as *verbatim* Y/U/V planes -- no colour
    conversion happens at all, so those frames survive at transcode quality;
  * the burned-in overlays are composited in YUV: luma is mixed at full
    resolution, chroma is mixed at full resolution too and then box-downsampled
    2x2 (skill 6.3), with every plate's box expanded to the chroma grid first
    so the sampling grid of the source and the result agree;
  * the encoder receives rawvideo yuv420p, so there is no RGB/YUV conversion
    step and the video is encoded exactly once.

The overlay plates are still authored in RGB (extraction works in HSV), so
they are converted once to bt709 limited-range YUV before being mixed.

usage: compose_splice_yuv.py <v1> <reel> <rootdir> [crf] [luma_offset]
"""
import json
import os
import subprocess
import sys

import cv2
import numpy as np

V1, REEL, ROOT = sys.argv[1], sys.argv[2], sys.argv[3]
CRF = sys.argv[4] if len(sys.argv) > 4 else "16"
# Optional luma offset applied to the INSERTED clip only.  Two takes of the
# same room differ in exposure; without a match the PRE segment sits ~28
# levels below the reference, which makes every translucent overlay (the
# title's soft shadow, the illustration's hair) read muddy against it.
# 0 disables it.
LUMA_OFFSET = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0
LAY, QA, OUT = f"{ROOT}/layers", f"{ROOT}/qa", f"{ROOT}/out"
os.makedirs(OUT, exist_ok=True)
os.makedirs(QA, exist_ok=True)
FFMPEG = "/opt/homebrew/bin/ffmpeg"

geom = json.load(open(f"{LAY}/overlay_geom.json"))
dm = json.load(open(f"{LAY}/digit_meta.json"))
C = geom["C"]
W, H, FPS = geom["W"], geom["H"], geom["FPS"]

PLATES = geom.get("PLATES")
if PLATES is None:
    PLATES = [{"name": "cluster", "file": "cluster.png",
               "bbox": geom["CLUSTER_BBOX"], "from": 0, "to": 10 ** 9},
              {"name": "title_stroke", "file": "title_stroke.png",
               "bbox": geom["TITLE_STROKE_BBOX"], "from": 0, "to": 10 ** 9},
              {"name": "title_fill", "file": "title_fill.png",
               "bbox": geom["TITLE_FILL_BBOX"], "from": 0, "to": 10 ** 9}]

# ---- helpers ------------------------------------------------------------
def probe_fps(path):
    out = subprocess.run(
        ["/opt/homebrew/bin/ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip()
    num, den = out.split("/")
    return float(num) / float(den)


def probe_size(path):
    """Real decoded raster of `path` -- never assume the reel's size."""
    out = subprocess.run(
        ["/opt/homebrew/bin/ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def read_yuv420(path, w, h):
    """Decode a whole file to planar yuv420p; returns (Y, U, V) uint8 arrays.

    `-fps_mode passthrough` is mandatory: the rawvideo muxer otherwise
    re-times frames onto the output timebase and *duplicates* frames whose
    pts does not land on it.  A 231-frame 30 fps reel whose video stream
    starts at pts 0.1 s came out as 234 frames without it -- every index
    after the first gap then pointed at the wrong picture, so C, the POST
    splice and the whole verification would silently be off by three.
    """
    fs = w * h * 3 // 2
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", path, "-fps_mode", "passthrough",
         "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"],
        capture_output=True).stdout
    n = len(raw) // fs
    a = np.frombuffer(raw[:n * fs], np.uint8).reshape(n, fs)
    return (a[:, :w * h].reshape(n, h, w),
            a[:, w * h:w * h + w * h // 4].reshape(n, h // 2, w // 2),
            a[:, w * h + w * h // 4:].reshape(n, h // 2, w // 2))


def rgb_to_yuv709_limited(bgr):
    """BT.709 limited-range YUV from full-range BGR uint8.

    Y  = 16  + (65.481 R + 128.553 G + 24.966 B) / 255
    Cb = 128 + (-37.797 R - 74.203 G + 112.000 B) / 255
    Cr = 128 + (112.000 R - 93.786 G - 18.214 B) / 255
    """
    b = bgr[:, :, 0].astype(np.float32)
    g = bgr[:, :, 1].astype(np.float32)
    r = bgr[:, :, 2].astype(np.float32)
    y = 16.0 + (65.481 * r + 128.553 * g + 24.966 * b) / 255.0
    cb = 128.0 + (-37.797 * r - 74.203 * g + 112.000 * b) / 255.0
    cr = 128.0 + (112.000 * r - 93.786 * g - 18.214 * b) / 255.0
    return (np.clip(y, 0, 255), np.clip(cb, 0, 255), np.clip(cr, 0, 255))


def downsample2(a):
    """Box-downsample a full-resolution plane by 2x2 (for chroma)."""
    h, w = a.shape
    return a.reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))


def even_box(box):
    """Expand a box to even bounds so it sits on the 4:2:0 chroma grid."""
    x0, y0, x1, y1 = box
    return (x0 - (x0 % 2), y0 - (y0 % 2),
            x1 + (x1 % 2), y1 + (y1 % 2))


def make_op(png_path, box, name):
    """Turn one RGBA plate into a YUV mixer description.

    The plate is placed on a full-frame canvas (neutral 16 / 128 / 128
    outside its own box) so that the luma, the chroma and the alpha all share
    one coordinate system.  The box is then expanded to the 4:2:0 chroma grid.
    """
    lay = cv2.imread(png_path, cv2.IMREAD_UNCHANGED)
    assert lay is not None and lay.shape[2] == 4, f"bad plate {png_path}"
    x0, y0, x1, y1 = box
    al = lay[:, :, 3].astype(np.float32) / 255.0
    py, pcb, pcr = rgb_to_yuv709_limited(lay[:, :, :3])
    ex0, ey0, ex1, ey1 = even_box(box)
    ex0, ey0 = max(0, ex0), max(0, ey0)
    ex1, ey1 = min(W, ex1), min(H, ey1)
    # Build the mixer canvas INSIDE the expanded box only.  Slicing a
    # full-frame array keeps the whole base alive through the view, so a
    # per-frame digit (430 of them on a 1080x1920 reel) would retain ~27 MB
    # each -- 11 GB of dead weight.  Local canvases keep each op at ~0.4 MB.
    H_, W_ = ey1 - ey0, ex1 - ex0
    px0, py0 = x0 - ex0, y0 - ey0
    px1, py1 = x1 - ex0, y1 - ey0
    py_f = np.full((H_, W_), 16.0, np.float32);  py_f[py0:py1, px0:px1] = py
    pcb_f = np.full((H_, W_), 128.0, np.float32); pcb_f[py0:py1, px0:px1] = pcb
    pcr_f = np.full((H_, W_), 128.0, np.float32); pcr_f[py0:py1, px0:px1] = pcr
    a_f = np.zeros((H_, W_), np.float32);           a_f[py0:py1, px0:px1] = al
    return {"name": name, "box": (ex0, ey0, ex1, ey1),
            # luma at full resolution
            "py": py_f, "a": a_f,
            # chroma on the half-resolution grid, alpha box-downsampled 2x2
            "pcb": downsample2(pcb_f), "pcr": downsample2(pcr_f),
            "ac": downsample2(a_f)}


plates = []
for i, p in enumerate(PLATES):
    op = make_op(f"{LAY}/{p['file']}", p["bbox"], p["name"])
    op["from"], op["to"] = p.get("from", 0), p.get("to", 10 ** 9)
    op["z"] = p.get("z", i)
    plates.append(op)
print(f"plates: {[(p['name'], p['from'], p['to'], p['z']) for p in plates]}")

V1W, V1H = probe_size(V1)
v1Y, v1U, v1V = read_yuv420(V1, V1W, V1H)
rY, rU, rV = read_yuv420(REEL, W, H)
N1, N = len(v1Y), len(rY)
print(f"video1 {N1} frames {v1Y.shape[2]}x{v1Y.shape[1]}, reel {N} frames {W}x{H}, C={C}")

# ---- scale video1 into the reel's raster, in the YUV domain ---------------
if v1Y.shape[1] != H or v1Y.shape[2] != W:
    w1, h1 = v1Y.shape[2], v1Y.shape[1]
    # Aspect-preserving COVER + centre crop.  A plain resize to (W, H) would
    # apply two different scale factors and shear the person by the aspect
    # mismatch (skill 1.3: video1 may be scaled/cropped, never stretched).
    s = max(W / w1, H / h1)
    sw = int(np.ceil(w1 * s)); sw += sw % 2
    sh = int(np.ceil(h1 * s)); sh += sh % 2
    # even crop offsets keep the luma and the chroma on the same sampling grid
    ox = ((sw - W) // 2) & ~1
    oy = ((sh - H) // 2) & ~1
    print(f"scaling video1 {w1}x{h1} -> cover {sw}x{sh} -> crop {W}x{H} "
          f"(aspect {w1/h1:.6f} vs reel {W/H:.6f}; uniform scale x{s:.6f}, "
          f"cropped {sw-W}x{sh-H} px)")
    # INTER_AREA for a >2x downscale: INTER_CUBIC does NOT band-limit, it
    # aliases (and over-sharpens) the luma of a 1792x3184 source scaled to
    # 720x1280, which shows up as shimmer on moving hair.
    yi = cv2.INTER_AREA if sw < w1 else cv2.INTER_CUBIC
    ci = cv2.INTER_AREA if sw // 2 < w1 // 2 else cv2.INTER_LINEAR
    v1Y = np.stack([cv2.resize(f, (sw, sh), interpolation=yi) for f in v1Y])
    v1U = np.stack([cv2.resize(f, (sw // 2, sh // 2), interpolation=ci)
                     for f in v1U])
    v1V = np.stack([cv2.resize(f, (sw // 2, sh // 2), interpolation=ci)
                     for f in v1V])
    v1Y = v1Y[:, oy:oy + H, ox:ox + W]
    v1U = v1U[:, oy // 2:(oy + H) // 2, ox // 2:(ox + W) // 2]
    v1V = v1V[:, oy // 2:(oy + H) // 2, ox // 2:(ox + W) // 2]

# ---- exposure match of the INSERTED clip to the reference ------------------
# The inserted clip and the reference are two takes of the same room.  Fitted
# on the wall (the one region present in both), the inserted clip reads ~28
# luma levels below the reference.  A pure luma offset is applied to video1
# ONLY -- the reference's own frames, and therefore the POST segment, are
# never touched.
if abs(LUMA_OFFSET) > 0.01:
    before = float(v1Y.mean())
    v1Y = np.clip(v1Y + LUMA_OFFSET, 0.0, 255.0)
    print(f"luma offset applied to the inserted clip: {LUMA_OFFSET:+.1f} "
          f"(mean {before:.2f} -> {float(v1Y.mean()):.2f})")

# ---- frame-copy resample: keep video1 at its native 1x speed -------------
SRC_FPS = probe_fps(V1)
OUT_FPS = probe_fps(REEL)
# Native 1x speed: output k reads source frame floor(k * src_fps / out_fps).
# If that runs past the end of video1, video1 is simply NOT long enough to
# fill 0..C-1 at 1x.  Clamping the tail (the obvious fix) freezes the last
# 4-5 frames into a visible stutter that lands exactly on the cut; a uniform
# stretch is forbidden (it shifts the action phase).  So the shortfall is
# absorbed as extra single-frame holds placed on the calmest motion
# boundaries of video1, where a repeated frame cannot be seen.
base = [int(np.floor(k * SRC_FPS / OUT_FPS)) for k in range(C)]
# Optional last *usable* source frame of video1 (env V1_MAX_SRC).  An inserted
# clip can end in a cross-dissolve to another costume; those frames belong to
# neither segment and must never reach the cut.  Capping behaves exactly like a
# short clip: the surplus frames become extra one-frame holds placed on the
# calmest motion boundaries (same machinery as the shortfall branch below).
MAX_SRC = os.environ.get("V1_MAX_SRC")
LAST = int(MAX_SRC) if MAX_SRC else (N1 - 1)
LAST = min(LAST, N1 - 1)
deficit = base[-1] - LAST
mapping = list(base)
if deficit > 0:
    # motion between consecutive source frames, measured on the scaled luma
    motion = np.zeros(N1 + 1, np.float32)
    for i in range(1, N1):
        motion[i] = float(np.abs(v1Y[i].astype(np.float32) -
                                 v1Y[i - 1].astype(np.float32)).mean())
    motion[N1] = 1e9
    # A removal turns the step at output k into a hold, so the source frame
    # that gets repeated is whatever mapping[k-1] currently is.  Its
    # visibility is governed by the motion AROUND it, i.e. in and out:
    # cost(s) = max(motion[s], motion[s+1]).  Removals are applied one at a
    # time and the mapping re-evaluated, because every removal shifts all
    # later indices down by one (ranking on the untouched base is off by the
    # number of holds already placed -- that's how a "calm" pick can end up
    # on a frame whose neighbours move at the clip average).
    def cost(s):
        return max(motion[s], motion[s + 1]) if s + 1 < N1 else 1e9
    picked = []
    for _ in range(deficit):
        best, best_c = None, None
        for k in range(1, C):
            if mapping[k] == mapping[k - 1]:
                continue                      # already a hold
            if any(abs(k - q) < max(8, C // 6) for q in picked):
                continue                      # don't stack two holds
            c = cost(mapping[k - 1])
            if best_c is None or c < best_c:
                best, best_c = k, c
        if best is None:                      # spacing too strict: relax it
            for k in range(1, C):
                if mapping[k] == mapping[k - 1] or k in picked:
                    continue
                c = cost(mapping[k - 1])
                if best_c is None or c < best_c:
                    best, best_c = k, c
        if best is None:
            break
        picked.append(best)
        for j in range(best, C):
            mapping[j] -= 1
    picked.sort()
    held = [mapping[k] for k in picked]
    print(f"video1 usable head ends at source frame {LAST} (cap={MAX_SRC}); "
          f"{deficit} frame(s) of surplus: added {deficit} one-frame hold(s) at output "
          f"{picked}, repeating source frames {held} "
          f"(local motion {[round(cost(s), 2) for s in held]}, clip mean "
          f"{float(motion[1:LAST].mean()):.2f}) instead of freezing the tail")
mapping = [min(m, LAST) for m in mapping]
print(f"fps: video1={SRC_FPS} reel={OUT_FPS} -> {len(set(mapping))} distinct source "
      f"frames ({C - len(set(mapping))} duplicated, "
      f"{N1 - 1 - mapping[-1]} tail frames truncated)")

# ---- the per-frame countdown digits --------------------------------------
digits = {}
for t in range(C):
    p = f"{LAY}/digit/d{t:04d}.png"
    if not os.path.exists(p):
        continue
    im = cv2.imread(p, cv2.IMREAD_UNCHANGED)
    box = dm["boxes"][t]
    if box is None:
        continue
    op = make_op(p, box, f"digit{t}")
    digits[t] = op

# ---- per-frame ANIMATED stickers (a rotating badge, a pulsing heart) -----
# A burned-in sticker that animates cannot live in a static plate: the
# temporal median would blend its animation phases into a ghost.  It is
# extracted per frame by the v2 extractor and composited here, one fixed
# box per sticker -- never tracked, translated or rescaled.
anim = []
if os.path.exists(f"{LAY}/anim_meta.json"):
    am = json.load(open(f"{LAY}/anim_meta.json"))
    for L in am.get("layers", []):
        ops = {}
        for t in range(max(0, L["from"]), min(L["to"], C - 1) + 1):
            boxes = L["boxes"][t] if t < len(L["boxes"]) else []
            for bi, box in enumerate(boxes):
                if box is None:
                    continue
                p = f"{LAY}/{L['dir']}/{L['name']}_{t:04d}_{bi}.png"
                if not os.path.exists(p):
                    continue
                ops.setdefault(t, []).append(make_op(p, box, f"{L['name']}{t}_{bi}"))
        anim.append({"name": L["name"], "z": L.get("z", 0), "ops": ops})
        print(f"animated layer {L['name']}: {len(ops)} frames, z={L.get('z', 0)}")


def mix(y, u, v, op):
    """Composite one plate into the YUV planes.

    Luma is mixed at full resolution with the full-resolution alpha; chroma
    is mixed on the half-resolution grid with the 2x2 box-downsampled alpha
    (skill 6.3).
    """
    ex0, ey0, ex1, ey1 = op["box"]
    al, ac = op["a"], op["ac"]
    y[ey0:ey1, ex0:ex1] = y[ey0:ey1, ex0:ex1] * (1 - al) + op["py"] * al
    cy0, cy1 = ey0 // 2, ey1 // 2
    cx0, cx1 = ex0 // 2, ex1 // 2
    u[cy0:cy1, cx0:cx1] = u[cy0:cy1, cx0:cx1] * (1 - ac) + op["pcb"] * ac
    v[cy0:cy1, cx0:cx1] = v[cy0:cy1, cx0:cx1] * (1 - ac) + op["pcr"] * ac


def frame_ops(k):
    """Every overlay op that applies to frame k, in z order (low z first).

    The z order matters where two overlays touch: the animated emoji is
    mixed BEFORE the text plate, so the last pixel column of a letter always
    wins over the faint outer matte of the badge next to it.
    """
    ops = [(op["z"], op) for op in plates if op["from"] <= k <= op["to"]]
    for L in anim:
        for op in L["ops"].get(k, []):
            ops.append((L["z"], op))
    d = digits.get(k)
    if d is not None:
        ops.append((1000, d))          # the countdown always sits on top
    ops.sort(key=lambda t: t[0])
    return [op for _, op in ops]


def compose(k, with_overlay=True):
    """Return a (Y, U, V) triple for output frame k.

    POST frames are the reel's own planes, verbatim -- no conversion at all --
    but a plate whose [from, to] window is scoped INTO the POST range (a
    sticker the user asked to burn in after the costume change) still has to
    be mixed, otherwise the layer silently disappears on every frame past C.
    The values stay integer-valued floats, so frames without an op round-trip
    bit-exactly.
    """
    if k >= C:
        y = rY[k].astype(np.float32)
        u = rU[k].astype(np.float32)
        v = rV[k].astype(np.float32)
        if not with_overlay:
            return y, u, v
        for op in frame_ops(k):
            mix(y, u, v, op)
        return y, u, v
    y = v1Y[mapping[k]].astype(np.float32)
    u = v1U[mapping[k]].astype(np.float32)
    v = v1V[mapping[k]].astype(np.float32)
    if not with_overlay:
        return y, u, v
    for op in frame_ops(k):
        mix(y, u, v, op)
    return y, u, v


# ---- QA stills (RGB, rendered from the same YUV path) --------------------
def to_bgr(y, u, v):
    # 4:2:0 chroma -> full resolution (co-sited: each sample covers a 2x2 block)
    uu = np.repeat(np.repeat(u, 2, axis=0), 2, axis=1)[:H, :W]
    vv = np.repeat(np.repeat(v, 2, axis=0), 2, axis=1)[:H, :W]
    yf = y.astype(np.float32)
    cb = (uu.astype(np.float32) - 128.0) * 255.0 / 224.0
    cr = (vv.astype(np.float32) - 128.0) * 255.0 / 224.0
    r = 1.164 * (yf - 16.0) + 1.793 * cr
    g = 1.164 * (yf - 16.0) - 0.213 * cb - 0.533 * cr
    b = 1.164 * (yf - 16.0) + 2.112 * cb
    return np.clip(np.dstack([b, g, r]), 0, 255).astype(np.uint8)


qa_ks = sorted(set([0, 1, 30, 60, 90, 120, 150, 180, 210] +
                   list(range(max(0, C - 12), C + 2)) +
                   [270, 300, N - 2, N - 1]))
for k in qa_ks:
    if not (0 <= k < N):
        continue
    cv2.imwrite(f"{QA}/out_k{k:03d}.png", to_bgr(*compose(k, True)))
    cv2.imwrite(f"{QA}/plain_k{k:03d}.png", to_bgr(*compose(k, False)))
bnd = [to_bgr(*compose(k, True)) for k in range(max(0, C - 3), min(N, C + 3))]
rows = []
for r in range(0, len(bnd), 3):
    ch = bnd[r:r + 3]
    while len(ch) < 3:
        ch.append(np.zeros_like(bnd[0]))
    rows.append(np.hstack(ch))
cv2.imwrite(f"{QA}/boundary_C{C}.jpg", np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 92])

# ---- protection zone, measured BEFORE encoding (exact, lossless) --------
ov = np.zeros((H, W), np.uint8)
worst = 0
changed = []
for k in range(C):
    # the mask is exactly the set of pixels this frame's overlays can touch
    m = np.zeros((H, W), np.uint8)
    for op in frame_ops(k):
        ex0, ey0, ex1, ey1 = op["box"]
        m[ey0:ey1, ex0:ex1] |= (op["a"] > 0).astype(np.uint8)
    ov |= m
    y, u, v = compose(k, True)
    y0, u0, v0 = compose(k, False)
    dy = np.abs(y - y0)
    outside = dy[m == 0]
    worst = max(worst, int(outside.max()) if outside.size else 0)
    changed.append(int((dy > 0).sum()))
print(f"protection zone (pre-encode): max|diff| outside every overlay = {worst}; "
      f"changed px {min(changed)}..{max(changed)}")
json.dump({"rule": "pre-encode: the composed YUV frame must be identical to the source "
                   "video1 YUV frame outside the union of all overlay alpha masks",
           "max_abs_diff_outside_overlay": worst, "frames_checked": C,
           "changed_px_per_frame_min": min(changed), "changed_px_per_frame_max": max(changed),
           "overlay_alpha_px": int((ov > 0).sum())},
          open(f"{QA}/protection_zone.json", "w"), indent=2)


def encode(path, with_overlay):
    # The rawvideo demuxer carries no colour metadata.  Without the input
    # flags below ffmpeg treats the limited-range source as full range and
    # rescales the luma, which cost ~2.6 grey levels on the untouched POST
    # segment (39.2 dB instead of 52.8 dB).  Declaring the input makes the
    # pipe a true passthrough.
    cmd = [FFMPEG, "-y",
           "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{W}x{H}", "-r", str(FPS),
           "-color_range", "tv", "-colorspace", "bt709",
           "-color_primaries", "bt709", "-color_trc", "bt709",
           "-i", "-",
           "-i", REEL,
           "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "libx264", "-preset", "medium", "-crf", CRF,
           "-pix_fmt", "yuv420p",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-color_range", "tv", "-vf", "setsar=1",
           "-c:a", "copy", "-movflags", "+faststart", "-video_track_timescale", "15360", path]
    print(f"encoding {os.path.basename(path)} (overlay={with_overlay})")
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for k in range(N):
        y, u, v = compose(k, with_overlay)
        buf = np.concatenate([y.ravel(), u.ravel(), v.ravel()]).astype(np.uint8)
        assert buf.size == W * H * 3 // 2, buf.size
        p.stdin.write(np.ascontiguousarray(buf).tobytes())
    p.stdin.close()
    err = p.stderr.read().decode("utf-8", "replace")
    rc = p.wait()
    open(f"{QA}/ffmpeg_{os.path.basename(path)}.log", "w").write(err)
    if rc != 0:
        print(err[-3000:])
        raise SystemExit(f"ffmpeg failed rc={rc}")
    print("  ok", path)


encode(f"{OUT}/成片_最终含贴图.mp4", True)
encode(f"{OUT}/中间版_无贴图替换版.mp4", False)
json.dump({"mapping": mapping, "C": C, "N": N, "N1": N1,
           "src_fps": SRC_FPS, "out_fps": OUT_FPS,
           "mapping_rule": "output k <- floor(k * src_fps / out_fps)  "
                           "(frame-copy resample, video1 keeps native 1x speed)",
           "distinct_src": len(set(mapping)),
           "compositor": "yuv420p domain (no RGB round trip)",
           "plates": [{"name": p["name"], "bbox": list(p["box"]),
                       "from": p["from"], "to": p["to"], "z": p["z"]} for p in plates],
           "animated": [{"name": L["name"], "frames": len(L["ops"]), "z": L["z"]}
                        for L in anim],
           "digit_windows": geom.get("DIGIT_WINDOWS", [])},
          open(f"{QA}/build_meta.json", "w"), indent=2)
print("done")
