"""
config.py — Job configuration management

Loads and validates job_config.json, resolves paths.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


DEFAULT_TEMPLATE = "classrecap"
DEFAULT_MODE = "individual"
DEFAULT_RESOLUTION = "720p"
DEFAULT_BITRATE = "1M"


@dataclass
class JobConfig:
    source_dir: str
    output_dir: str
    target_duration: int
    template: str = DEFAULT_TEMPLATE
    mode: str = DEFAULT_MODE
    resolution: str = DEFAULT_RESOLUTION
    bitrate: str = DEFAULT_BITRATE
    templates_dir: str = ""

    @classmethod
    def from_file(cls, path: str) -> "JobConfig":
        """Load config from job_config.json"""
        with open(path, "r") as f:
            data = json.load(f)
        return cls(**data)

    def validate(self) -> list[str]:
        """Return list of error messages; empty list means valid"""
        errors = []
        if not self.source_dir:
            errors.append("source_dir is required")
        elif not os.path.isdir(self.source_dir):
            errors.append(f"source_dir not found: {self.source_dir}")

        if not self.output_dir:
            errors.append("output_dir is required")

        if self.target_duration is None or self.target_duration <= 0:
            errors.append("target_duration must be a positive integer")

        if self.mode not in ("individual", "single"):
            errors.append("mode must be 'individual' or 'single'")

        if self.resolution not in ("720p", "1080p"):
            errors.append("resolution must be '720p' or '1080p'")

        return errors

    def template_path(self) -> str:
        """Return full path to the template JSON"""
        if not self.templates_dir:
            # default: templates/ folder next to pipeline.py
            base = Path(__file__).parent.parent
            self.templates_dir = str(base / "templates")
        return os.path.join(self.templates_dir, f"{self.template}.json")

    def load_template(self) -> dict:
        """Load the template JSON"""
        path = self.template_path()
        if not os.path.exists(path):
            raise FileNotFoundError(f"Template not found: {path}")
        with open(path, "r") as f:
            return json.load(f)

    def get_video_files(self) -> list[str]:
        """Return list of video file paths in source_dir (recursive, excludes processed)"""
        video_exts = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v")
        videos = []
        for root, dirs, files in os.walk(self.source_dir):
            # Skip processed and other non-source directories
            dirs[:] = [d for d in dirs if d not in ("processed", "pipeline", "briefing", "0328Explorer")]
            for fname in files:
                if fname.lower().endswith(video_exts):
                    videos.append(os.path.join(root, fname))
        return sorted(videos)
