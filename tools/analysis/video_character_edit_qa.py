"""Contact-sheet QA for source-video character edits.

The tool deliberately does not invent identity, motion, or background scores.
It creates a matched-timestamp visual review artifact and marks the result
``REVIEW_REQUIRED`` until a human or a calibrated reviewer supplies scores.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps

from tools.analysis.frame_sampler import FrameSampler
from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


class VideoCharacterEditQA(BaseTool):
    name = "video_character_edit_qa"
    version = "0.1.0"
    tier = ToolTier.ANALYZE
    capability = "analysis"
    provider = "openmontage"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["cmd:ffmpeg", "cmd:ffprobe"]
    install_instructions = "Install FFmpeg and ffprobe. Pillow is included in requirements.txt."
    agent_skills = ["ffmpeg"]
    capabilities = ["matched_timestamp_contact_sheet", "source_edit_visual_review", "technical_probe"]
    supports = {
        "contact_sheet": True,
        "manual_review_gate": True,
        "identity_score": False,
        "motion_score": False,
        "background_score": False,
    }
    best_for = [
        "side-by-side source and edited video review",
        "manual QA before accepting outfit, hair, or face-lock outputs",
    ]
    not_good_for = ["uncalibrated automatic identity or pose judgment"]
    input_schema = {
        "type": "object",
        "required": ["source_path", "edited_path", "output_path"],
        "properties": {
            "source_path": {"type": "string"},
            "edited_path": {"type": "string"},
            "output_path": {"type": "string"},
            "stage": {"type": "string", "enum": ["outfit_edit", "hair_edit", "face_lock", "final"], "default": "final"},
            "sample_count": {"type": "integer", "minimum": 2, "maximum": 24, "default": 8},
        },
    }
    output_schema = {
        "type": "object",
        "required": ["qa_report", "contact_sheet_path"],
        "properties": {"qa_report": {"type": "object"}, "contact_sheet_path": {"type": "string"}},
    }
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=1024, disk_mb=500, network_required=False)
    idempotency_key_fields = ["source_path", "edited_path", "stage", "sample_count"]
    side_effects = ["writes sampled frames, contact sheet, and QA JSON under output_path"]
    user_visible_verification = [
        "Inspect the contact sheet at matched timestamps",
        "Supply a manual decision before marking the QA artifact PASS",
    ]

    def get_status(self) -> ToolStatus:
        try:
            self.check_dependencies()
        except Exception:
            return ToolStatus.UNAVAILABLE
        return ToolStatus.AVAILABLE

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        source = Path(inputs["source_path"])
        edited = Path(inputs["edited_path"])
        output = Path(inputs["output_path"])
        if not source.exists():
            return ToolResult(success=False, error=f"Source video not found: {source}")
        if not edited.exists():
            return ToolResult(success=False, error=f"Edited video not found: {edited}")
        output.parent.mkdir(parents=True, exist_ok=True)
        sample_count = int(inputs.get("sample_count", 8))
        stage = str(inputs.get("stage", "final"))
        frame_root = output.parent / f"{output.stem}_frames"
        sample_inputs = {
            "strategy": "count",
            "count": sample_count,
            "format": "jpg",
        }
        source_result = FrameSampler().execute({**sample_inputs, "input_path": str(source), "output_dir": str(frame_root / "source")})
        if not source_result.success:
            return ToolResult(success=False, error=source_result.error or "Source-frame sampling failed")
        source_frames = source_result.data.get("frames", [])
        timestamps = [float(frame.get("timestamp_seconds", 0.0)) for frame in source_frames]
        edited_result = FrameSampler().execute({
            "input_path": str(edited),
            "strategy": "timestamps",
            "timestamps": timestamps,
            "output_dir": str(frame_root / "edited"),
            "format": "jpg",
        })
        if not edited_result.success:
            return ToolResult(success=False, error=edited_result.error or "Edited-frame sampling failed")
        edited_frames = edited_result.data.get("frames", [])
        pair_count = min(len(source_frames), len(edited_frames))
        if pair_count < 2:
            return ToolResult(success=False, error="At least two matched frame pairs are required")
        self._write_contact_sheet(output, source_frames[:pair_count], edited_frames[:pair_count], stage=stage)

        report_path = output.with_suffix(".json")
        report = {
            "version": "1.0",
            "stage": stage,
            "source_path": str(source),
            "edited_path": str(edited),
            "contact_sheet_path": str(output),
            "sampled_frames": pair_count,
            "status": "REVIEW_REQUIRED",
            "manual_review_required": True,
            "checks": {
                "identity_score": None,
                "motion_score": None,
                "background_score": None,
                "appearance_score": None,
                "continuity_score": None,
            },
            "issues": [],
            "metadata": {
                "source_sample_dir": str(frame_root / "source"),
                "edited_sample_dir": str(frame_root / "edited"),
                "score_policy": "Scores are intentionally uncomputed until calibrated against human review.",
            },
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return ToolResult(
            success=True,
            data={"qa_report": report, "contact_sheet_path": str(output), "report_path": str(report_path)},
            artifacts=[str(output), str(report_path), str(frame_root)],
            duration_seconds=round(time.time() - start, 2),
        )

    @staticmethod
    def _write_contact_sheet(output: Path, source_frames: list[dict[str, Any]], edited_frames: list[dict[str, Any]], *, stage: str) -> None:
        tile_width, tile_height, label_height = 320, 220, 28
        row_height = tile_height + label_height
        sheet = Image.new("RGB", (tile_width * 2, row_height * len(source_frames)), "#202124")
        draw = ImageDraw.Draw(sheet)
        for index, (source_frame, edited_frame) in enumerate(zip(source_frames, edited_frames)):
            y = index * row_height
            timestamp = float(source_frame.get("timestamp_seconds", 0.0))
            draw.text((8, y + 6), f"{stage} | t={timestamp:.2f}s | source", fill="white")
            draw.text((tile_width + 8, y + 6), f"{stage} | t={timestamp:.2f}s | edited", fill="white")
            for x, frame in ((0, source_frame), (tile_width, edited_frame)):
                path = frame.get("path")
                if not path:
                    continue
                with Image.open(path) as image:
                    thumb = ImageOps.contain(image.convert("RGB"), (tile_width, tile_height))
                tile = Image.new("RGB", (tile_width, tile_height), "#111111")
                tile.paste(thumb, ((tile_width - thumb.width) // 2, (tile_height - thumb.height) // 2))
                sheet.paste(tile, (x, y + label_height))
        sheet.save(output, quality=92)
