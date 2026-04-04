"""
export.py — Export step

Cuts segments from source videos using ffmpeg and concatenates them
into the final output file.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def cut_segment(
    video_path: str,
    start: float,
    end: float,
    output_path: str,
    resolution: str = "720p",
    bitrate: str = "1M"
) -> bool:
    """
    Extract a segment from video using ffmpeg with frame-accurate cutting.
    Uses -ss before -i for fast seek, -to for duration.
    """
    scale_filter = "scale=-2:720" if resolution == "720p" else "scale=-2:1080"

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", video_path,
        "-to", str(end - start),
        "-vf", scale_filter,
        "-c:v", "libx264",
        "-preset", "fast",
        "-b:v", bitrate,
        "-c:a", "aac",
        "-b:a", "128k",
        "-avoid_negative_ts", "make_zero",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"ffmpeg cut failed: {result.stderr}")
        return False
    return True


def concatenate_segments(
    segment_files: list[str],
    output_path: str
) -> bool:
    """
    Concatenate multiple video files into one using ffmpeg concat demuxer.
    """
    if not segment_files:
        return False
    if len(segment_files) == 1:
        # Just rename/copy
        os.rename(segment_files[0], output_path)
        return True

    # Write concat list
    list_path = output_path + ".concat.txt"
    with open(list_path, "w") as f:
        for seg in segment_files:
            f.write(f"file '{seg}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        os.remove(list_path)
    except:
        pass

    if result.returncode != 0:
        logger.error(f"ffmpeg concat failed: {result.stderr}")
        return False
    return True


def cleanup_temp_files(files: list[str]):
    """Remove temporary segment files"""
    for f in files:
        try:
            if os.path.exists(f):
                os.remove(f)
        except Exception as e:
            logger.warning(f"Could not remove temp file {f}: {e}")


def export_video(
    video_path: str,
    segments: list,
    output_dir: str,
    resolution: str = "720p",
    bitrate: str = "1M"
) -> dict:
    """
    Export a single video's selected segments as a highlight clip.
    Returns dict with success status and output path.
    """
    if not segments:
        return {"success": False, "output_path": None, "error": "No segments to export"}

    stem = Path(video_path).stem
    os.makedirs(output_dir, exist_ok=True)

    segment_files = []
    temp_dir = os.path.join(output_dir, f"{stem}_segments")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        for i, seg in enumerate(segments):
            seg_path = os.path.join(temp_dir, f"seg_{i:03d}.mp4")
            success = cut_segment(
                video_path,
                seg["start"],
                seg["end"],
                seg_path,
                resolution=resolution,
                bitrate=bitrate
            )
            if not success:
                return {"success": False, "output_path": None, "error": f"Failed to cut segment {i}"}
            segment_files.append(seg_path)

        # Output filename
        total_duration = sum(s["end"] - s["start"] for s in segments)
        output_filename = f"{stem}_highlight_{int(total_duration)}s_{len(segments)}clips.mp4"
        output_path = os.path.join(output_dir, output_filename)

        # Concatenate
        if not concatenate_segments(segment_files, output_path):
            return {"success": False, "output_path": None, "error": "Concatenation failed"}

        return {
            "success": True,
            "output_path": output_path,
            "segments": len(segments),
            "duration": total_duration,
            "segment_times": [(s["start"], s["end"]) for s in segments]
        }
    finally:
        cleanup_temp_files(segment_files)
        try:
            os.rmdir(temp_dir)
        except:
            pass


def export_compilation(
    selections: dict,
    video_map: dict,
    output_dir: str,
    resolution: str = "720p",
    bitrate: str = "1M"
) -> dict:
    """
    Export a single compilation from multiple videos (single mode).
    selections: {"__all__": [segments]}
    video_map: {stem: video_path}
    """
    all_segments = selections.get("__all__", [])
    if not all_segments:
        return {"success": False, "output_path": None, "error": "No segments"}

    os.makedirs(output_dir, exist_ok=True)

    # Group segments by source video to preserve order
    # Sort segments chronologically, track source
    all_segments.sort(key=lambda x: x["start"])

    temp_dir = os.path.join(output_dir, "compilation_segments")
    os.makedirs(temp_dir, exist_ok=True)

    segment_files = []

    try:
        for i, seg in enumerate(all_segments):
            source_stem = seg.get("_source_stem", "")
            video_path = video_map.get(source_stem)
            if not video_path:
                continue

            seg_path = os.path.join(temp_dir, f"seg_{i:03d}.mp4")
            success = cut_segment(
                video_path,
                seg["start"],
                seg["end"],
                seg_path,
                resolution=resolution,
                bitrate=bitrate
            )
            if success:
                segment_files.append(seg_path)

        total_duration = sum(s["end"] - s["start"] for s in all_segments)
        output_filename = f"compilation_classrecap_{int(total_duration)}s_{len(all_segments)}clips.mp4"
        output_path = os.path.join(output_dir, output_filename)

        if not concatenate_segments(segment_files, output_path):
            return {"success": False, "output_path": None, "error": "Concatenation failed"}

        return {
            "success": True,
            "output_path": output_path,
            "segments": len(segment_files),
            "duration": total_duration
        }
    finally:
        cleanup_temp_files(segment_files)
        try:
            os.rmdir(temp_dir)
        except:
            pass


def run(config, job_state: dict) -> dict:
    """
    Export final clips for all videos.
    Updates job_state["export"] with per-video output info.
    """
    select_data = job_state.get("select", {})
    stats_data = job_state.get("stats", {})
    transcribe_data = job_state.get("transcribe", [])

    # Build video stem → path map
    video_map = {}
    for r in transcribe_data:
        if r["success"]:
            stem = Path(r["video_path"]).stem
            video_map[stem] = r["video_path"]

    exports = {}

    if config.mode == "single":
        result = export_compilation(
            select_data,
            video_map,
            config.output_dir,
            resolution=config.resolution,
            bitrate=config.bitrate
        )
        exports["__all__"] = result
    else:
        for stem, segments in select_data.items():
            video_path = video_map.get(stem)
            if not video_path:
                exports[stem] = {"success": False, "error": "Video path not found"}
                continue

            result = export_video(
                video_path,
                segments,
                config.output_dir,
                resolution=config.resolution,
                bitrate=config.bitrate
            )
            exports[stem] = result

    job_state["export"] = exports

    successful = [v for v in exports.values() if v.get("success")]
    return {
        "status": "ok",
        "exported": len(successful),
        "failed": len(exports) - len(successful)
    }
