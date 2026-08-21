"""Shared motion-metrics helpers for dance QA.

The helpers intentionally avoid OpenCV so they work in the current workspace
where numpy + Pillow are available but cv2 is not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


_RESAMPLE_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)


def load_grayscale_array(frame_path: str | Path, max_width: int = 160) -> np.ndarray:
    """Load a frame as a resized grayscale float32 array."""
    with Image.open(frame_path) as img:
        gray = img.convert("L")
        if max_width > 0 and gray.width > max_width:
            new_height = max(1, int(round(gray.height * (max_width / gray.width))))
            gray = gray.resize((max_width, new_height), _RESAMPLE_LANCZOS)
        return np.asarray(gray, dtype=np.float32)


def frame_motion_metrics(
    prev_frame_path: str | Path,
    curr_frame_path: str | Path,
    *,
    max_width: int = 160,
) -> dict[str, float]:
    """Compute per-pair motion metrics from two sampled frames."""
    prev = load_grayscale_array(prev_frame_path, max_width=max_width)
    curr = load_grayscale_array(curr_frame_path, max_width=max_width)

    if prev.shape != curr.shape:
        with Image.open(curr_frame_path) as img:
            resized = img.convert("L").resize(
                (prev.shape[1], prev.shape[0]),
                _RESAMPLE_LANCZOS,
            )
            curr = np.asarray(resized, dtype=np.float32)

    diff = np.abs(curr - prev) / 255.0
    total = float(diff.mean())
    height = max(diff.shape[0], 1)
    split = max(1, height // 2)
    upper = float(diff[:split, :].mean())
    lower = float(diff[split:, :].mean()) if split < height else upper
    lower_share = lower / (upper + lower + 1e-6)

    return {
        "total": round(total, 6),
        "upper": round(upper, 6),
        "lower": round(lower, 6),
        "lower_share": round(lower_share, 6),
    }


def motion_series_from_frames(
    frame_paths: list[str],
    *,
    max_width: int = 160,
) -> dict[str, Any]:
    """Compute a motion profile from an ordered frame list."""
    pair_metrics: list[dict[str, float]] = []
    for prev_path, curr_path in zip(frame_paths[:-1], frame_paths[1:]):
        pair_metrics.append(
            frame_motion_metrics(prev_path, curr_path, max_width=max_width)
        )

    totals = [metric["total"] for metric in pair_metrics]
    lower_shares = [metric["lower_share"] for metric in pair_metrics]
    upper_values = [metric["upper"] for metric in pair_metrics]
    lower_values = [metric["lower"] for metric in pair_metrics]

    if totals:
        total_array = np.asarray(totals, dtype=np.float32)
        lower_share_array = np.asarray(lower_shares, dtype=np.float32)
        active_threshold = max(0.015, float(np.mean(total_array)) * 0.5)
        summary = {
            "pair_count": len(pair_metrics),
            "mean_total": round(float(np.mean(total_array)), 6),
            "median_total": round(float(np.median(total_array)), 6),
            "std_total": round(float(np.std(total_array)), 6),
            "peak_total": round(float(np.max(total_array)), 6),
            "active_ratio": round(float(np.mean(total_array > active_threshold)), 6),
            "mean_lower_share": round(float(np.mean(lower_share_array)), 6),
            "mean_upper": round(float(np.mean(np.asarray(upper_values, dtype=np.float32))), 6),
            "mean_lower": round(float(np.mean(np.asarray(lower_values, dtype=np.float32))), 6),
        }
    else:
        summary = {
            "pair_count": 0,
            "mean_total": 0.0,
            "median_total": 0.0,
            "std_total": 0.0,
            "peak_total": 0.0,
            "active_ratio": 0.0,
            "mean_lower_share": 0.0,
            "mean_upper": 0.0,
            "mean_lower": 0.0,
        }

    return {
        "pair_metrics": pair_metrics,
        "series": [round(value, 6) for value in totals],
        "summary": summary,
    }


def resample_series(values: list[float], target_length: int = 24) -> list[float]:
    """Linearly resample a 1D series to a fixed length."""
    if target_length <= 0:
        return []
    if not values:
        return [0.0] * target_length
    if len(values) == 1:
        return [float(values[0])] * target_length

    x_src = np.linspace(0.0, 1.0, num=len(values), endpoint=True)
    x_dst = np.linspace(0.0, 1.0, num=target_length, endpoint=True)
    y_dst = np.interp(x_dst, x_src, np.asarray(values, dtype=np.float32))
    return [round(float(value), 6) for value in y_dst]


def compare_motion_series(
    reference_values: list[float],
    candidate_values: list[float],
    *,
    target_length: int = 24,
) -> dict[str, float | list[float]]:
    """Compare two motion profiles on a shared normalized axis."""
    ref = np.asarray(resample_series(reference_values, target_length), dtype=np.float32)
    cand = np.asarray(resample_series(candidate_values, target_length), dtype=np.float32)

    if ref.size < 2 or cand.size < 2:
        correlation = 0.0
    elif float(np.std(ref)) < 1e-6 or float(np.std(cand)) < 1e-6:
        correlation = 0.0
    else:
        correlation = float(np.corrcoef(ref, cand)[0, 1])
        if np.isnan(correlation):
            correlation = 0.0

    correlation = max(-1.0, min(1.0, correlation))
    normalized_correlation = max(0.0, (correlation + 1.0) / 2.0)

    ref_mean = float(np.mean(ref)) if ref.size else 0.0
    cand_mean = float(np.mean(cand)) if cand.size else 0.0
    mean_ratio = cand_mean / ref_mean if ref_mean > 1e-6 else 0.0

    ref_active = float(np.mean(ref > max(0.015, ref_mean * 0.5))) if ref.size else 0.0
    cand_active = float(np.mean(cand > max(0.015, cand_mean * 0.5))) if cand.size else 0.0
    activity_ratio = cand_active / ref_active if ref_active > 1e-6 else 0.0

    return {
        "correlation": round(correlation, 6),
        "normalized_correlation": round(normalized_correlation, 6),
        "reference_mean": round(ref_mean, 6),
        "candidate_mean": round(cand_mean, 6),
        "mean_ratio": round(mean_ratio, 6),
        "reference_active_ratio": round(ref_active, 6),
        "candidate_active_ratio": round(cand_active, 6),
        "activity_ratio": round(activity_ratio, 6),
        "reference_series": [round(float(v), 6) for v in ref.tolist()],
        "candidate_series": [round(float(v), 6) for v in cand.tolist()],
    }

