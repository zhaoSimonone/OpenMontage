"""Reference-dance motion / continuity QA.

Scores a generated dance clip against the locked reference dance and writes a
continuity report that the reference-dance pipeline can consume directly.
The implementation stays local and avoids OpenCV so it works in the current
workspace with FFmpeg + numpy + Pillow only.
"""

from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.analysis.frame_sampler import FrameSampler
from tools.analysis.motion_metrics import (
    compare_motion_series,
    motion_series_from_frames,
)
from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)
from tools.video._shared import probe_output


MOTION_PASS_THRESHOLD = 0.70
MOTION_REGENERATE_THRESHOLD = 0.55
CONTINUITY_PASS_THRESHOLD = 0.70
CONTINUITY_REPAIR_THRESHOLD = 0.65
FALLBACK_AFTER_FAILED_MOTION_ATTEMPTS = 2
DEFAULT_SAMPLE_FPS = 2.0
DEFAULT_MAX_SAMPLES = 18
DEFAULT_SEAM_WINDOW_SECONDS = 0.25
DEFAULT_FRAME_WIDTH = 160


class ReferenceDanceQA(BaseTool):
    name = "reference_dance_qa"
    version = "0.1.0"
    tier = ToolTier.ANALYZE
    capability = "analysis"
    provider = "ffmpeg"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["cmd:ffmpeg", "cmd:ffprobe"]
    install_instructions = (
        "Install FFmpeg:\n"
        "  Windows: winget install ffmpeg\n"
        "  macOS: brew install ffmpeg\n"
        "  Linux: sudo apt install ffmpeg"
    )
    agent_skills = ["ffmpeg"]

    capabilities = [
        "score_motion_energy",
        "score_clip_continuity",
        "review_reference_dance",
    ]
    best_for = [
        "comparing a generated dance clip against the locked reference",
        "scoring motion energy, seam continuity, and stiff-motion risk",
        "deciding PASS / REPAIR / REGENERATE for the reference-dance pipeline",
    ]
    not_good_for = [
        "face-identity recognition",
        "semantic pose estimation",
        "automatic provider switching without agent approval",
    ]

    input_schema = {
        "type": "object",
        "required": ["project_id", "reference_video_path"],
        "properties": {
            "project_id": {"type": "string"},
            "reference_video_path": {"type": "string"},
            "candidate_video_path": {"type": "string"},
            "clip_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional clip list for multi-clip seam analysis.",
            },
            "seam_timestamps": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Optional seam timestamps inside a stitched candidate.",
            },
            "failed_motion_attempts": {
                "type": "integer",
                "minimum": 0,
                "default": 0,
                "description": "How many prior H3 attempts already failed the motion gate.",
            },
            "sample_fps": {
                "type": "number",
                "minimum": 0.5,
                "maximum": 6.0,
                "default": DEFAULT_SAMPLE_FPS,
            },
            "max_samples_per_clip": {
                "type": "integer",
                "minimum": 4,
                "maximum": 48,
                "default": DEFAULT_MAX_SAMPLES,
            },
            "seam_window_seconds": {
                "type": "number",
                "minimum": 0.05,
                "maximum": 1.0,
                "default": DEFAULT_SEAM_WINDOW_SECONDS,
            },
            "frame_width": {
                "type": "integer",
                "minimum": 64,
                "maximum": 640,
                "default": DEFAULT_FRAME_WIDTH,
            },
            "output_path": {
                "type": "string",
                "description": "Path for the continuity report JSON.",
            },
            "label": {
                "type": "string",
                "description": "Optional human label for the report.",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1,
        ram_mb=512,
        vram_mb=0,
        disk_mb=600,
        network_required=False,
    )
    retry_policy = RetryPolicy(max_retries=0)
    idempotency_key_fields = [
        "project_id",
        "reference_video_path",
        "candidate_video_path",
        "clip_paths",
        "seam_timestamps",
        "sample_fps",
        "max_samples_per_clip",
        "seam_window_seconds",
        "frame_width",
    ]
    side_effects = [
        "writes continuity_report JSON to output_path",
        "writes sampled QA frames alongside the report",
    ]
    user_visible_verification = [
        "Inspect the sampled frames and seam frames in the report folder",
    ]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()

        try:
            report = self._build_report(inputs)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

        output_path = Path(report["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        artifacts = [str(output_path)]
        for path in report.get("sample_frame_dirs", []):
            artifacts.append(str(path))

        return ToolResult(
            success=True,
            data=report,
            artifacts=artifacts,
            duration_seconds=round(time.time() - start, 2),
        )

    def _build_report(self, inputs: dict[str, Any]) -> dict[str, Any]:
        project_id = str(inputs["project_id"])
        reference_path = Path(inputs["reference_video_path"])
        candidate_path = Path(inputs["candidate_video_path"]) if inputs.get("candidate_video_path") else None
        clip_paths = [Path(p) for p in inputs.get("clip_paths") or []]
        seam_timestamps = [float(ts) for ts in inputs.get("seam_timestamps") or []]
        failed_motion_attempts = int(inputs.get("failed_motion_attempts", 0) or 0)
        sample_fps = float(inputs.get("sample_fps", DEFAULT_SAMPLE_FPS))
        max_samples_per_clip = int(inputs.get("max_samples_per_clip", DEFAULT_MAX_SAMPLES))
        seam_window_seconds = float(inputs.get("seam_window_seconds", DEFAULT_SEAM_WINDOW_SECONDS))
        frame_width = int(inputs.get("frame_width", DEFAULT_FRAME_WIDTH))
        label = str(inputs.get("label") or "")

        if not reference_path.exists():
            raise FileNotFoundError(f"Reference video not found: {reference_path}")
        if candidate_path is None and not clip_paths:
            raise ValueError("Provide candidate_video_path or clip_paths")
        if candidate_path is not None and not candidate_path.exists():
            raise FileNotFoundError(f"Candidate video not found: {candidate_path}")
        for clip in clip_paths:
            if not clip.exists():
                raise FileNotFoundError(f"Clip not found: {clip}")

        output_path = Path(
            inputs.get("output_path")
            or Path("projects") / project_id / "artifacts" / "continuity_report.json"
        )
        sample_root = output_path.parent / f"{output_path.stem}_frames"
        sample_root.mkdir(parents=True, exist_ok=True)

        frame_sampler = FrameSampler()

        reference_run = self._sample_video(
            frame_sampler=frame_sampler,
            video_path=reference_path,
            output_dir=sample_root / "reference",
            sample_fps=sample_fps,
            max_samples=max_samples_per_clip,
            frame_width=frame_width,
            label="reference",
        )

        candidate_runs: list[dict[str, Any]] = []
        if clip_paths:
            for index, clip_path in enumerate(clip_paths, start=1):
                candidate_runs.append(
                    self._sample_video(
                        frame_sampler=frame_sampler,
                        video_path=clip_path,
                        output_dir=sample_root / f"candidate_clip_{index:02d}",
                        sample_fps=sample_fps,
                        max_samples=max_samples_per_clip,
                        frame_width=frame_width,
                        label=clip_path.stem,
                    )
                )
        elif candidate_path is not None:
            candidate_runs.append(
                self._sample_video(
                    frame_sampler=frame_sampler,
                    video_path=candidate_path,
                    output_dir=sample_root / "candidate",
                    sample_fps=sample_fps,
                    max_samples=max_samples_per_clip,
                    frame_width=frame_width,
                    label=candidate_path.stem,
                )
            )

        candidate_series = self._flatten_series(candidate_runs)
        candidate_lower_shares = self._flatten_lower_shares(candidate_runs)
        candidate_summary = self._summarize_series(candidate_series, candidate_lower_shares)
        candidate_profile = compare_motion_series(
            reference_run["motion"]["series"],
            candidate_series,
            target_length=24,
        )

        motion_score = self._score_motion(
            comparison=candidate_profile,
            reference_summary=reference_run["motion"]["summary"],
            candidate_summary=candidate_summary,
        )

        seam_reports = self._score_seams(
            candidate_runs=candidate_runs,
            seam_timestamps=seam_timestamps,
            candidate_video_path=candidate_path,
            frame_width=frame_width,
            seam_window_seconds=seam_window_seconds,
            frame_sampler=frame_sampler,
            sample_root=sample_root,
        )
        continuity_score = self._score_continuity(seam_reports)
        total_score = round((motion_score * 0.7) + (continuity_score * 0.3), 6)

        decision = self._decide(motion_score, continuity_score, total_score)
        next_action = self._next_action(
            decision=decision,
            motion_score=motion_score,
            continuity_score=continuity_score,
            failed_motion_attempts=failed_motion_attempts,
        )

        clip_ids = [run["clip_id"] for run in candidate_runs] or [candidate_path.stem if candidate_path else "candidate"]
        mode = "multi_clip_sequence" if len(candidate_runs) > 1 else "single_oneshot_clip"
        seams_present = len(seam_reports) > 0
        seam_review_required = seams_present

        report = {
            "version": "1.0",
            "project_id": project_id,
            "label": label,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "clip_ids": clip_ids,
            "seams_present": seams_present,
            "seam_review_required": seam_review_required,
            "quality_gate": {
                "motion_score_threshold": MOTION_PASS_THRESHOLD,
                "motion_regenerate_threshold": MOTION_REGENERATE_THRESHOLD,
                "continuity_score_threshold": CONTINUITY_PASS_THRESHOLD,
                "continuity_repair_threshold": CONTINUITY_REPAIR_THRESHOLD,
                "failed_motion_attempts_before_fallback": FALLBACK_AFTER_FAILED_MOTION_ATTEMPTS,
            },
            "reference_video": {
                "path": str(reference_path),
                "probe": reference_run["probe"],
                "frame_dir": reference_run["frame_dir"],
                "sample_count": reference_run["sample_count"],
                "sample_timestamps": reference_run["sample_timestamps"],
                "frame_paths": reference_run["frame_paths"],
                "motion": reference_run["motion"],
            },
            "candidate_video": {
                "path": str(candidate_path) if candidate_path else None,
                "clip_paths": [str(path) for path in clip_paths],
                "probe": candidate_runs[0]["probe"] if len(candidate_runs) == 1 else None,
                "frame_dirs": [run["frame_dir"] for run in candidate_runs],
                "sample_count": sum(run["sample_count"] for run in candidate_runs),
                "sample_timestamps": [ts for run in candidate_runs for ts in run["sample_timestamps"]],
                "frame_paths": [path for run in candidate_runs for path in run["frame_paths"]],
                "motion": {
                    "series": candidate_series,
                    "summary": candidate_summary,
                },
                "clips": candidate_runs,
            },
            "motion_analysis": {
                "comparison": candidate_profile,
                "motion_score": motion_score,
                "issues": self._motion_issues(
                    motion_score=motion_score,
                    reference_summary=reference_run["motion"]["summary"],
                    candidate_summary=candidate_summary,
                    comparison=candidate_profile,
                ),
            },
            "continuity_analysis": {
                "seams": seam_reports,
                "continuity_score": continuity_score,
                "worst_seam_score": min((seam["score"] for seam in seam_reports), default=1.0),
                "average_seam_score": round(
                    statistics.fmean([seam["score"] for seam in seam_reports]) if seam_reports else 1.0,
                    6,
                ),
                "issues": self._continuity_issues(seam_reports),
            },
            "scores": {
                "motion": motion_score,
                "continuity": continuity_score,
                "identity": None,
                "camera": None,
                "total": total_score,
            },
            "decision": decision,
            "next_action": next_action,
            "summary": self._summary_text(
                decision=decision,
                motion_score=motion_score,
                continuity_score=continuity_score,
                candidate_summary=candidate_summary,
                reference_summary=reference_run["motion"]["summary"],
                seam_reports=seam_reports,
            ),
            "output_path": str(output_path),
            "sample_frame_dirs": [
                reference_run["frame_dir"],
                *[run["frame_dir"] for run in candidate_runs],
            ],
            "metadata": {
                "reference_video": str(reference_path),
                "candidate_video": str(candidate_path) if candidate_path else None,
                "clip_count": len(candidate_runs),
                "sample_fps": sample_fps,
                "max_samples_per_clip": max_samples_per_clip,
                "seam_window_seconds": seam_window_seconds,
                "frame_width": frame_width,
                "failed_motion_attempts": failed_motion_attempts,
                "fallback_after_failed_motion_attempts": FALLBACK_AFTER_FAILED_MOTION_ATTEMPTS,
            },
        }
        return report

    def _sample_video(
        self,
        *,
        frame_sampler: FrameSampler,
        video_path: Path,
        output_dir: Path,
        sample_fps: float,
        max_samples: int,
        frame_width: int,
        label: str,
    ) -> dict[str, Any]:
        probe = probe_output(video_path)
        duration = float(probe.get("duration_seconds") or probe.get("duration") or 0.0)
        sample_count = self._sample_count(duration, sample_fps, max_samples)
        timestamps = self._sample_timestamps(duration, sample_count, sample_fps)

        output_dir.mkdir(parents=True, exist_ok=True)
        frame_result = frame_sampler.execute(
            {
                "input_path": str(video_path),
                "strategy": "timestamps",
                "timestamps": timestamps,
                "output_dir": str(output_dir),
                "format": "jpg",
                "quality": 2,
            }
        )
        if not frame_result.success:
            raise RuntimeError(frame_result.error or f"Failed to sample frames for {video_path}")

        frames = frame_result.data.get("frames", [])
        frame_paths = [str(frame["path"]) for frame in frames if frame.get("path")]
        if len(frame_paths) < 2:
            raise RuntimeError(f"Not enough frames extracted from {video_path}")

        motion = motion_series_from_frames(frame_paths, max_width=frame_width)
        return {
            "clip_id": label,
            "path": str(video_path),
            "probe": probe,
            "frame_dir": str(output_dir),
            "sample_count": len(frame_paths),
            "sample_timestamps": [float(frame.get("timestamp_seconds", 0.0)) for frame in frames if frame.get("path")],
            "frame_paths": frame_paths,
            "motion": motion,
        }

    def _sample_count(self, duration: float, sample_fps: float, max_samples: int) -> int:
        if duration <= 0:
            return max(2, min(max_samples, 6))
        count = int(round(duration * sample_fps))
        count = max(6, count)
        return max(2, min(max_samples, count))

    def _sample_timestamps(self, duration: float, sample_count: int, sample_fps: float) -> list[float]:
        if sample_count <= 1:
            return [0.0]
        tail_buffer = max(0.25, 1.0 / max(sample_fps, 0.1))
        upper = max(duration - tail_buffer, 0.0)
        if upper <= 0:
            return [0.0] * sample_count
        if sample_count == 2:
            return [0.0, upper]
        step = upper / (sample_count - 1)
        return [round(min(step * i, upper), 3) for i in range(sample_count)]

    def _flatten_series(self, runs: list[dict[str, Any]]) -> list[float]:
        values: list[float] = []
        for run in runs:
            values.extend(run["motion"]["series"])
        return values

    def _flatten_lower_shares(self, runs: list[dict[str, Any]]) -> list[float]:
        values: list[float] = []
        for run in runs:
            values.extend(metric["lower_share"] for metric in run["motion"]["pair_metrics"])
        return values

    def _summarize_series(self, series: list[float], lower_shares: list[float]) -> dict[str, Any]:
        if not series:
            return {
                "pair_count": 0,
                "mean_total": 0.0,
                "median_total": 0.0,
                "std_total": 0.0,
                "peak_total": 0.0,
                "active_ratio": 0.0,
                "mean_lower_share": 0.0,
            }
        total_array = [float(value) for value in series]
        active_threshold = max(0.015, statistics.fmean(total_array) * 0.5)
        return {
            "pair_count": len(total_array),
            "mean_total": round(statistics.fmean(total_array), 6),
            "median_total": round(statistics.median(total_array), 6),
            "std_total": round(statistics.pstdev(total_array) if len(total_array) > 1 else 0.0, 6),
            "peak_total": round(max(total_array), 6),
            "active_ratio": round(
                sum(1 for value in total_array if value > active_threshold) / len(total_array),
                6,
            ),
            "mean_lower_share": round(statistics.fmean(lower_shares) if lower_shares else 0.0, 6),
        }

    def _score_motion(
        self,
        *,
        comparison: dict[str, Any],
        reference_summary: dict[str, Any],
        candidate_summary: dict[str, Any],
    ) -> float:
        corr_score = float(comparison.get("normalized_correlation", 0.0))
        mean_ratio = float(comparison.get("mean_ratio", 0.0))
        if mean_ratio >= 1.0:
            energy_score = 1.0
        else:
            energy_score = max(0.0, min(1.0, mean_ratio / 0.8))

        ref_lower = float(reference_summary.get("mean_lower_share", 0.0))
        cand_lower = float(candidate_summary.get("mean_lower_share", 0.0))
        lower_alignment = 1.0 - min(abs(cand_lower - ref_lower) / 0.20, 1.0)

        ref_active = float(reference_summary.get("active_ratio", 0.0))
        cand_active = float(candidate_summary.get("active_ratio", 0.0))
        activity_score = 1.0 if ref_active <= 1e-6 else max(0.0, min(1.0, cand_active / ref_active))

        motion_score = (
            (corr_score * 0.35)
            + (energy_score * 0.30)
            + (lower_alignment * 0.20)
            + (activity_score * 0.15)
        )
        return round(max(0.0, min(1.0, motion_score)), 6)

    def _score_seams(
        self,
        *,
        candidate_runs: list[dict[str, Any]],
        seam_timestamps: list[float],
        candidate_video_path: Path | None,
        frame_width: int,
        seam_window_seconds: float,
        frame_sampler: FrameSampler,
        sample_root: Path,
    ) -> list[dict[str, Any]]:
        if len(candidate_runs) > 1:
            seam_reports: list[dict[str, Any]] = []
            for index in range(len(candidate_runs) - 1):
                seam_reports.append(
                    self._score_clip_seam(
                        left_run=candidate_runs[index],
                        right_run=candidate_runs[index + 1],
                        index=index,
                        frame_width=frame_width,
                        seam_window_seconds=seam_window_seconds,
                        sample_root=sample_root,
                    )
                )
            return seam_reports

        if candidate_video_path is None:
            return []

        seam_reports = []
        for index, seam_time in enumerate(seam_timestamps):
            seam_reports.append(
                self._score_timestamp_seam(
                    video_path=candidate_video_path,
                    seam_time=seam_time,
                    index=index,
                    frame_width=frame_width,
                    seam_window_seconds=seam_window_seconds,
                    frame_sampler=frame_sampler,
                    sample_root=sample_root,
                )
            )
        return seam_reports

    def _score_clip_seam(
        self,
        *,
        left_run: dict[str, Any],
        right_run: dict[str, Any],
        index: int,
        frame_width: int,
        seam_window_seconds: float,
        sample_root: Path,
    ) -> dict[str, Any]:
        left_frames = left_run["frame_paths"]
        right_frames = right_run["frame_paths"]
        tail_pair = left_run["motion"]["pair_metrics"][-1] if left_run["motion"]["pair_metrics"] else {"total": 0.0, "lower_share": 0.0}
        head_pair = right_run["motion"]["pair_metrics"][0] if right_run["motion"]["pair_metrics"] else {"total": 0.0, "lower_share": 0.0}
        visual_jump = self._frame_difference(left_frames[-1], right_frames[0], frame_width=frame_width)
        motion_jump = abs(float(tail_pair["total"]) - float(head_pair["total"]))
        lower_jump = abs(float(tail_pair["lower_share"]) - float(head_pair["lower_share"]))
        score = self._seam_score(visual_jump, motion_jump, lower_jump)
        seam_dir = sample_root / f"seam_{index + 1:02d}"
        seam_dir.mkdir(parents=True, exist_ok=True)
        return {
            "index": index,
            "between": [left_run["clip_id"], right_run["clip_id"]],
            "mode": "clip_boundary",
            "tail_frame": left_frames[-1],
            "head_frame": right_frames[0],
            "visual_jump": round(visual_jump, 6),
            "motion_jump": round(motion_jump, 6),
            "lower_share_delta": round(lower_jump, 6),
            "score": round(score, 6),
            "frame_dir": str(seam_dir),
            "seam_window_seconds": seam_window_seconds,
            "issues": self._seam_issues(score, visual_jump, motion_jump, lower_jump),
        }

    def _score_timestamp_seam(
        self,
        *,
        video_path: Path,
        seam_time: float,
        index: int,
        frame_width: int,
        seam_window_seconds: float,
        frame_sampler: FrameSampler,
        sample_root: Path,
    ) -> dict[str, Any]:
        offsets = [
            max(seam_time - (seam_window_seconds * 2), 0.0),
            max(seam_time - seam_window_seconds, 0.0),
            min(seam_time + seam_window_seconds, seam_time + seam_window_seconds * 2),
            min(seam_time + (seam_window_seconds * 2), seam_time + (seam_window_seconds * 3)),
        ]
        seam_dir = sample_root / f"seam_{index + 1:02d}"
        seam_dir.mkdir(parents=True, exist_ok=True)
        frame_result = frame_sampler.execute(
            {
                "input_path": str(video_path),
                "strategy": "timestamps",
                "timestamps": offsets,
                "output_dir": str(seam_dir),
                "format": "jpg",
                "quality": 2,
            }
        )
        if not frame_result.success:
            raise RuntimeError(frame_result.error or f"Failed seam sampling at {seam_time}s")
        frames = [frame["path"] for frame in frame_result.data.get("frames", []) if frame.get("path")]
        if len(frames) < 4:
            raise RuntimeError(f"Seam sampling at {seam_time}s returned too few frames")

        tail_pair = motion_series_from_frames(frames[:2], max_width=frame_width)["pair_metrics"][-1]
        head_pair = motion_series_from_frames(frames[2:], max_width=frame_width)["pair_metrics"][0]
        visual_jump = self._frame_difference(frames[1], frames[2], frame_width=frame_width)
        motion_jump = abs(float(tail_pair["total"]) - float(head_pair["total"]))
        lower_jump = abs(float(tail_pair["lower_share"]) - float(head_pair["lower_share"]))
        score = self._seam_score(visual_jump, motion_jump, lower_jump)
        return {
            "index": index,
            "between": [round(seam_time - seam_window_seconds, 3), round(seam_time + seam_window_seconds, 3)],
            "mode": "timestamp_boundary",
            "timestamp_seconds": round(seam_time, 3),
            "tail_frame": frames[1],
            "head_frame": frames[2],
            "visual_jump": round(visual_jump, 6),
            "motion_jump": round(motion_jump, 6),
            "lower_share_delta": round(lower_jump, 6),
            "score": round(score, 6),
            "frame_dir": str(seam_dir),
            "seam_window_seconds": seam_window_seconds,
            "issues": self._seam_issues(score, visual_jump, motion_jump, lower_jump),
        }

    def _frame_difference(self, frame_a: str, frame_b: str, *, frame_width: int) -> float:
        from PIL import Image
        import numpy as np

        with Image.open(frame_a) as img_a, Image.open(frame_b) as img_b:
            gray_a = img_a.convert("L")
            gray_b = img_b.convert("L")
            if gray_a.width > frame_width:
                new_height = max(1, int(round(gray_a.height * (frame_width / gray_a.width))))
                gray_a = gray_a.resize((frame_width, new_height))
            if gray_b.width > frame_width:
                new_height = max(1, int(round(gray_b.height * (frame_width / gray_b.width))))
                gray_b = gray_b.resize((frame_width, new_height))
            if gray_a.size != gray_b.size:
                gray_b = gray_b.resize(gray_a.size)
            arr_a = np.asarray(gray_a, dtype=np.float32)
            arr_b = np.asarray(gray_b, dtype=np.float32)
            diff = np.abs(arr_b - arr_a) / 255.0
            return float(diff.mean())

    def _seam_score(self, visual_jump: float, motion_jump: float, lower_jump: float) -> float:
        visual_norm = min(visual_jump / 0.18, 1.0)
        motion_norm = min(motion_jump / 0.08, 1.0)
        lower_norm = min(lower_jump / 0.20, 1.0)
        score = 1.0 - ((visual_norm * 0.55) + (motion_norm * 0.30) + (lower_norm * 0.15))
        return max(0.0, min(1.0, score))

    def _seam_issues(
        self,
        score: float,
        visual_jump: float,
        motion_jump: float,
        lower_jump: float,
    ) -> list[str]:
        issues: list[str] = []
        if score < CONTINUITY_PASS_THRESHOLD:
            issues.append(
                "Seam continuity is weak: the clip boundary still reads as a restart instead of a bridge."
            )
        if visual_jump > 0.18:
            issues.append("Boundary frames differ too much visually.")
        if motion_jump > 0.08:
            issues.append("Motion energy drops too hard across the seam.")
        if lower_jump > 0.20:
            issues.append("Lower-body rhythm changes too sharply across the seam.")
        return issues

    def _score_continuity(self, seam_reports: list[dict[str, Any]]) -> float:
        if not seam_reports:
            return 1.0
        return round(min(report["score"] for report in seam_reports), 6)

    def _decide(self, motion_score: float, continuity_score: float, total_score: float) -> str:
        if motion_score < MOTION_REGENERATE_THRESHOLD:
            return "REGENERATE"
        if continuity_score < CONTINUITY_REPAIR_THRESHOLD:
            return "REPAIR"
        if motion_score >= MOTION_PASS_THRESHOLD and continuity_score >= CONTINUITY_PASS_THRESHOLD and total_score >= 0.72:
            return "PASS"
        if total_score >= 0.60:
            return "REPAIR"
        return "REGENERATE"

    def _next_action(
        self,
        *,
        decision: str,
        motion_score: float,
        continuity_score: float,
        failed_motion_attempts: int,
    ) -> dict[str, Any]:
        if decision == "PASS":
            return {
                "kind": "present_to_user",
                "provider": None,
                "reason": "Motion and continuity both meet the gate.",
            }

        if failed_motion_attempts >= FALLBACK_AFTER_FAILED_MOTION_ATTEMPTS and motion_score < MOTION_PASS_THRESHOLD:
            return {
                "kind": "consider_fallback_provider",
                "provider": "comfyui_video",
                "model_hint": "wan2.2",
                "reason": "H3 motion has not cleared the pass line after repeated attempts.",
            }

        if motion_score < MOTION_REGENERATE_THRESHOLD:
            return {
                "kind": "regenerate_h3",
                "provider": "minimax_h3",
                "reason": "Motion energy is still too conservative for the reference dance.",
                "focus": [
                    "increase knee, hip, and shoulder travel",
                    "keep lower-body weight transfer visible",
                    "keep the bridge pose alive instead of resetting to neutral",
                ],
            }

        if continuity_score < CONTINUITY_REPAIR_THRESHOLD:
            return {
                "kind": "repair_seam",
                "provider": "minimax_h3",
                "reason": "Motion is acceptable, but the seam still reads as a restart.",
                "focus": [
                    "tighten the bridge pose",
                    "keep the same side/blocking and hand height at the boundary",
                    "avoid a new gesture at the seam",
                ],
            }

        return {
            "kind": "regenerate_h3",
            "provider": "minimax_h3",
            "reason": "The clip clears the technical bar but still needs stronger dance energy.",
        }

    def _motion_issues(
        self,
        *,
        motion_score: float,
        reference_summary: dict[str, Any],
        candidate_summary: dict[str, Any],
        comparison: dict[str, Any],
    ) -> list[str]:
        issues: list[str] = []
        if motion_score < MOTION_PASS_THRESHOLD:
            issues.append("Motion energy is still below the reference-dance target.")
        if float(comparison.get("mean_ratio", 0.0)) < 0.8:
            issues.append("Candidate motion is noticeably quieter than the reference.")
        if float(candidate_summary.get("mean_lower_share", 0.0)) + 0.08 < float(reference_summary.get("mean_lower_share", 0.0)):
            issues.append("Lower-body contribution is weaker than the reference.")
        if float(candidate_summary.get("active_ratio", 0.0)) + 0.05 < float(reference_summary.get("active_ratio", 0.0)):
            issues.append("The motion curve stays too flat across the clip.")
        return issues

    def _continuity_issues(self, seam_reports: list[dict[str, Any]]) -> list[str]:
        issues: list[str] = []
        for seam in seam_reports:
            issues.extend(seam.get("issues", []))
        return list(dict.fromkeys(issues))

    def _summary_text(
        self,
        *,
        decision: str,
        motion_score: float,
        continuity_score: float,
        candidate_summary: dict[str, Any],
        reference_summary: dict[str, Any],
        seam_reports: list[dict[str, Any]],
    ) -> str:
        seam_text = ""
        if seam_reports:
            seam_text = f" Worst seam score: {min(report['score'] for report in seam_reports):.2f}."
        return (
            f"Decision {decision}. Motion score {motion_score:.2f} vs reference lower-share {reference_summary.get('mean_lower_share', 0.0):.2f} "
            f"and candidate lower-share {candidate_summary.get('mean_lower_share', 0.0):.2f}. "
            f"Continuity score {continuity_score:.2f}.{seam_text}"
        )
