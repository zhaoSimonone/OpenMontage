#!/usr/bin/env python3
"""Compose the transform-splice-cover result.

Pure edit, single final encode.

  output frame k <  C  -> video1 frame  floor(k * N1 / C)  (monotonic time map,
                          frame-copy resample; never a speed change, never AI
                          inpainting or motion reconstruction)
                          + the reel's burned-in overlays re-composited at
                            their original coordinates
  output frame k >= C  -> the reel's original POST frame, untouched

Stacking order of the source reel: artwork -> stroke -> coloured fill -> digit.

usage: compose_splice.py <v1> <reel> <rootdir> [crf]
"""
import os
import sys
import json
import subprocess
import cv2
import numpy as np

V1, REEL, ROOT = sys.argv[1], sys.argv[2], sys.argv[3]
CRF = sys.argv[4] if len(sys.argv) > 4 else "16"
LAY, QA, OUT = f"{ROOT}/layers", f"{ROOT}/qa", f"{ROOT}/out"
os.makedirs(OUT, exist_ok=True)
os.makedirs(QA, exist_ok=True)
FFMPEG = "/opt/homebrew/bin/ffmpeg"

geom = json.load(open(f"{LAY}/overlay_geom.json"))
dm = json.load(open(f"{LAY}/digit_meta.json"))
C = geom["C"]
W, H, FPS = geom["W"], geom["H"], geom["FPS"]
CB = geom["CLUSTER_BBOX"]
FB = geom["TITLE_FILL_BBOX"]
SB = geom["TITLE_STROKE_BBOX"]

cluster = cv2.imread(f"{LAY}/cluster.png", cv2.IMREAD_UNCHANGED)
tfill = cv2.imread(f"{LAY}/title_fill.png", cv2.IMREAD_UNCHANGED)
tstroke = cv2.imread(f"{LAY}/title_stroke.png", cv2.IMREAD_UNCHANGED)
for lay, nm in ((cluster, "cluster"), (tfill, "title_fill"), (tstroke, "title_stroke")):
    assert lay is not None and lay.shape[2] == 4, f"bad layer {nm}"


def overlay(base, layer, x0, y0):
    """Alpha-composite an RGBA layer onto a BGR base at (x0,y0)."""
    lh, lw = layer.shape[:2]
    bx0, by0 = max(0, x0), max(0, y0)
    bx1, by1 = min(base.shape[1], x0 + lw), min(base.shape[0], y0 + lh)
    if bx1 <= bx0 or by1 <= by0:
        return base
    l = layer[by0 - y0:by1 - y0, bx0 - x0:bx1 - x0]
    a = l[:, :, 3:4].astype(np.float32) / 255.0
    roi = base[by0:by1, bx0:bx1].astype(np.float32)
    base[by0:by1, bx0:bx1] = (l[:, :, :3].astype(np.float32) * a + roi * (1.0 - a)).astype(np.uint8)
    return base


def read_all(path):
    cap = cv2.VideoCapture(path)
    fr = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        fr.append(f)
    cap.release()
    return fr


v1 = read_all(V1)
reel = read_all(REEL)
N1, N = len(v1), len(reel)
print(f"v1 {N1} frames, reel {N} frames, C={C}")

# monotonic time mapping: output k <- floor(k * N1 / C)
mapping = [min(int(np.floor(k * N1 / C)), N1 - 1) for k in range(C)]
print(f"mapping: {C} out frames <- {N1} src, {len(set(mapping))} distinct "
      f"({C - len(set(mapping))} duplicated)")

digits = {}
for t in range(C):
    p = f"{LAY}/digit/d{t:04d}.png"
    if os.path.exists(p):
        digits[t] = cv2.imread(p, cv2.IMREAD_UNCHANGED)


def compose(k, with_overlay=True):
    if k < C:
        img = v1[mapping[k]].copy()
        if with_overlay:
            img = overlay(img, cluster, CB[0], CB[1])
            img = overlay(img, tstroke, SB[0], SB[1])
            img = overlay(img, tfill, FB[0], FB[1])
            d = digits.get(k)
            if d is not None:
                b = dm["boxes"][k]
                img = overlay(img, d, b[0], b[1])
        return img
    return reel[k].copy()


# ---- QA stills ----
qa_ks = sorted(set([0, 1, 30, 60, 90, 120, 150, 180, 210, 233, 238, 239, 240, 241,
                    242, 243, 244, C - 1, C, C + 1, 270, 300, N - 2, N - 1]))
qa_ks = [k for k in qa_ks if 0 <= k < N]
for k in qa_ks:
    cv2.imwrite(f"{QA}/out_k{k:03d}.png", compose(k, True))
    cv2.imwrite(f"{QA}/plain_k{k:03d}.png", compose(k, False))
bnd = [compose(k, True) for k in range(max(0, C - 3), min(N, C + 3))]
rows = []
for r in range(0, len(bnd), 3):
    ch = bnd[r:r + 3]
    while len(ch) < 3:
        ch.append(np.zeros_like(bnd[0]))
    rows.append(np.hstack(ch))
cv2.imwrite(f"{QA}/boundary_C{C}.jpg", np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 92])

# ---- protection zone, measured BEFORE encoding (exact, lossless) ----
ov = np.zeros((H, W), np.uint8)
ov[CB[1]:CB[3], CB[0]:CB[2]] = (cluster[:, :, 3] > 0).astype(np.uint8)
ov[SB[1]:SB[3], SB[0]:SB[2]] |= (tstroke[:, :, 3] > 0).astype(np.uint8)
ov[FB[1]:FB[3], FB[0]:FB[2]] |= (tfill[:, :, 3] > 0).astype(np.uint8)
worst = 0
changed = []
for k in range(C):
    m = ov.copy()
    d = dm["boxes"][k]
    if d and k in digits:
        m[d[1]:d[3], d[0]:d[2]] |= (digits[k][:, :, 3] > 0).astype(np.uint8)
    src = v1[mapping[k]].astype(np.int16)
    out = compose(k, True).astype(np.int16)
    diff = np.abs(src - out).max(axis=2)
    outside = diff[m == 0]
    worst = max(worst, int(outside.max()) if outside.size else 0)
    changed.append(int((diff > 0).sum()))
print(f"protection zone (pre-encode): max|diff| outside every overlay = {worst}; "
      f"changed px {min(changed)}..{max(changed)}")
json.dump({"rule": "pre-encode: composed frame vs source video1 frame must be identical "
                   "outside the union of all overlay alpha masks",
           "max_abs_diff_outside_overlay": worst, "frames_checked": C,
           "changed_px_per_frame_min": min(changed), "changed_px_per_frame_max": max(changed),
           "overlay_alpha_px": int((ov > 0).sum())},
          open(f"{QA}/protection_zone.json", "w"), indent=2)


def encode(path, with_overlay):
    cmd = [FFMPEG, "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
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
        img = compose(k, with_overlay)
        assert img.shape == (H, W, 3), img.shape
        p.stdin.write(np.ascontiguousarray(img).tobytes())
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
           "distinct_src": len(set(mapping)),
           "title_bbox": FB, "title_stroke_bbox": SB, "cluster_bbox": CB,
           "digit_windows": geom["DIGIT_WINDOWS"]},
          open(f"{QA}/build_meta.json", "w"), indent=2)
print("done")
