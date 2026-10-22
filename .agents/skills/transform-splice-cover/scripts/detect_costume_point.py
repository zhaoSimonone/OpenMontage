#!/usr/bin/env python3
"""Frame-level costume-change detection for the original reel (video2).

Pure analysis, no generation. Identifies PRE / TRANSITION / POST frames and
proposes candidate cut points; the caller must confirm the final C by eye on
the generated contact sheets (skill section 2: scene-cut scores only produce
candidates, they never decide the cut).

IMPORTANT: the analysis window must extend PAST the suspected cut point
(C + 16 frames at least). The costume change is a hard cut, so the largest
adjacent-frame jump sits exactly at C -- truncating the analysis at C hides
the very jump that identifies it.

usage: detect_costume_point.py <reel> <outdir> [frames_to_analyse]
"""
import os
import sys
import cv2
import numpy as np

REEL, OUT = sys.argv[1], sys.argv[2]
CUT = int(sys.argv[3]) if len(sys.argv) > 3 else 10**9   # frames to analyse; keep it > C
os.makedirs(OUT, exist_ok=True)


def read_all(path, limit):
    cap = cv2.VideoCapture(path)
    frames = []
    while len(frames) < limit:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    return frames


def roi_feats(f, rois):
    out = {}
    hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
    for name, (x0, y0, x1, y1) in rois.items():
        h = hsv[y0:y1, x0:x1]
        v = h[:, :, 2].astype(np.float32)
        s = h[:, :, 1].astype(np.float32)
        out[f"{name}_V"] = float(v.mean())
        out[f"{name}_S"] = float(s.mean())
        out[f"{name}_dark"] = float((v < 60).mean())
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
    out["flash"] = float((g > 235).mean())
    return out


frames = read_all(REEL, CUT)
N = len(frames)
H, W = frames[0].shape[:2]
print(f"{N} frames {W}x{H}")

rois = {
    "torso": (int(0.28 * W), int(0.36 * H), int(0.72 * W), int(0.58 * H)),
    "head": (int(0.30 * W), int(0.06 * H), int(0.70 * W), int(0.30 * H)),
}
rows = [roi_feats(f, rois) for f in frames]

# adjacent-frame difference, full frame and torso ROI
d_full = np.zeros(N)
d_torso = np.zeros(N)
for i in range(1, N):
    a = frames[i - 1].astype(np.float32)
    b = frames[i].astype(np.float32)
    d_full[i] = float(np.abs(a - b).mean())
    ta = a[rois["torso"][1]:rois["torso"][3], rois["torso"][0]:rois["torso"][2]]
    tb = b[rois["torso"][1]:rois["torso"][3], rois["torso"][0]:rois["torso"][2]]
    d_torso[i] = float(np.abs(ta - tb).mean())

print("\ntop-20 adjacent torso diffs (candidates only):")
for i in sorted(np.argsort(-d_torso)[:20]):
    print(f"   f{i:3d}  dtorso={d_torso[i]:6.2f}  dfull={d_full[i]:6.2f}  flash={rows[i]['flash']:.3f}")

print("\nwhite-flash / exposure events (flash > 0.25):")
for i in range(N):
    if rows[i]["flash"] > 0.25:
        print(f"   f{i:3d}  flash={rows[i]['flash']:.3f}")

# contact sheets around the strongest candidates so a human can confirm C
def sheet(sel, path):
    tiles = []
    for n in sel:
        f = frames[n]
        s = cv2.resize(f, (270, 480), interpolation=cv2.INTER_AREA)
        band = np.zeros((32, 270, 3), np.uint8)
        cv2.putText(band, f"f{n}", (8, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 255, 255), 2, cv2.LINE_AA)
        tiles.append(np.vstack([band, s]))
    cols = 5
    rowsl = []
    for r in range(0, len(tiles), cols):
        ch = tiles[r:r + cols]
        while len(ch) < cols:
            ch.append(np.zeros_like(tiles[0]))
        rowsl.append(np.hstack(ch))
    cv2.imwrite(path, np.vstack(rowsl), [cv2.IMWRITE_JPEG_QUALITY, 92])


if N:
    order = [int(i) for i in np.argsort(-d_torso) if d_torso[i] > 0]
    seen = []
    for top in order:
        if any(abs(top - o) < 12 for o in seen):
            continue
        seen.append(top)
        if len(seen) >= 3:
            break
    for rank, top in enumerate(seen):
        lo = max(0, top - 8)
        hi = min(N - 1, top + 8)
        sel = list(range(lo, hi + 1))
        sheet(sel, f"{OUT}/costume_candidate{rank+1}_f{top}.jpg")
        print(f"\ncandidate {rank+1}: frame {top}  dtorso={d_torso[top]:.2f}  "
              f"-> {OUT}/costume_candidate{rank+1}_f{top}.jpg  (frames {lo}..{hi})")
    print("Rule: C = first frame already showing the POST outfit AND followed by >=4")
    print("      consecutive POST frames. A flash/blur/motion-blur frame is TRANSITION.")
