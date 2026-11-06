#!/usr/bin/env python3
"""Compose the transform-splice-cover result.

Pure edit, single final encode.

  output frame k <  C  -> video1 frame  floor(k * src_fps / out_fps)  (frame-copy
                          resample that PRESERVES video1's native action speed;
                          never a speed change, never AI inpainting or motion
                          reconstruction)
                          + the reel's burned-in overlays re-composited at
                            their original coordinates
  output frame k >= C  -> the reel's original POST frame, untouched

NOTE on the mapping: the older ``floor(k * N1 / C)`` stretched or squeezed
video1 to fill C frames exactly.  When the two clips have different frame
rates that is a real speed change, and it is what shifts the raise / fist /
hands-together phase near the cut.  The skill mandates the frame-copy
resample above: video1 keeps 1x speed, the fps difference is absorbed by
duplicating frames, and the surplus tail frames are simply truncated.

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
CB = geom.get("CLUSTER_BBOX")
FB = geom.get("TITLE_FILL_BBOX")
SB = geom.get("TITLE_STROKE_BBOX")

# v2 writes an ordered plate manifest; v1 used three fixed slots.
PLATES = geom.get("PLATES")
if PLATES is None:
    PLATES = [{"name": "cluster", "file": "cluster.png", "bbox": CB},
              {"name": "title_stroke", "file": "title_stroke.png", "bbox": SB},
              {"name": "title_fill", "file": "title_fill.png", "bbox": FB}]
plates = []
for p in PLATES:
    img = cv2.imread(f"{LAY}/{p['file']}", cv2.IMREAD_UNCHANGED)
    assert img is not None and img.shape[2] == 4, f"bad plate {p['file']}"
    # a static sticker only exists inside its own time window; the reel's
    # timeline can switch overlays mid-shot, so the window is mandatory
    plates.append((img, p["bbox"], p["name"],
                   p.get("from", 0), p.get("to", 10 ** 9)))
print(f"plates: {[(p[2], p[3], p[4]) for p in plates]}")


def probe_fps(path):
    out = subprocess.run(
        ["/opt/homebrew/bin/ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip()
    num, den = out.split("/")
    return float(num) / float(den)


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

# ---- scale video1 to the reel's raster (uniform; never a person stretch) --
if v1[0].shape[0] != H or v1[0].shape[1] != W:
    sx, sy = W / v1[0].shape[1], H / v1[0].shape[0]
    print(f"scaling video1 {v1[0].shape[1]}x{v1[0].shape[0]} -> {W}x{H} "
          f"(x{sx:.4f} / y{sy:.4f}, uniform={abs(sx-sy) < 1e-6})")
    v1 = [cv2.resize(f, (W, H), interpolation=cv2.INTER_CUBIC) for f in v1]

# ---- frame-copy resample: keep video1 at its native 1x speed -------------
SRC_FPS = probe_fps(V1)
OUT_FPS = probe_fps(REEL)
mapping = [min(int(np.floor(k * SRC_FPS / OUT_FPS)), N1 - 1) for k in range(C)]
print(f"fps: video1={SRC_FPS} reel={OUT_FPS} -> output k <- floor(k*{SRC_FPS}/{OUT_FPS}); "
      f"{len(set(mapping))} distinct source frames "
      f"({C - len(set(mapping))} duplicated, {N1 - 1 - mapping[-1]} tail frames truncated)")

digits = {}
for t in range(C):
    p = f"{LAY}/digit/d{t:04d}.png"
    if os.path.exists(p):
        digits[t] = cv2.imread(p, cv2.IMREAD_UNCHANGED)


def compose(k, with_overlay=True):
    if k < C:
        img = v1[mapping[k]].copy()
        if with_overlay:
            for lay, bb, _nm, pf, pt in plates:
                if pf <= k <= pt:
                    img = overlay(img, lay, bb[0], bb[1])
            d = digits.get(k)
            if d is not None:
                b = dm["boxes"][k]
                img = overlay(img, d, b[0], b[1])
        return img
    return reel[k].copy()


# ---- QA stills ----
qa_ks = sorted(set([0, 1, 30, 60, 90, 120, 150, 180, 210] +
                   list(range(max(0, C - 12), C + 2)) +          # 12 frames before the cut
                   [C - 1, C, C + 1, 270, 300, N - 2, N - 1]))
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
for lay, bb, _nm, pf, pt in plates:
    ov[bb[1]:bb[3], bb[0]:bb[2]] |= (lay[:, :, 3] > 0).astype(np.uint8)
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
           "src_fps": SRC_FPS, "out_fps": OUT_FPS,
           "mapping_rule": "output k <- floor(k * src_fps / out_fps)  "
                           "(frame-copy resample, video1 keeps native 1x speed)",
           "distinct_src": len(set(mapping)),
           "title_bbox": FB, "title_stroke_bbox": SB, "cluster_bbox": CB,
           "plates": [{"name": p[2], "bbox": p[1], "from": p[3], "to": p[4]}
                      for p in plates],
           "digit_windows": geom.get("DIGIT_WINDOWS", [])},
          open(f"{QA}/build_meta.json", "w"), indent=2)
print("done")
