"""
transcribe.py — Whisper transcription step

Uses OpenAI Whisper to produce word-level timestamps for each video.
"""

import json
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def get_audio_path(video_path: str) -> str:
    """Extract audio to a temp wav file and return its path"""
    stem = Path(video_path).stem
    audio_dir = Path(video_path).parent
    audio_path = audio_dir / f"{stem}_audio.wav"
    if audio_path.exists():
        return str(audio_path)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(audio_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: {result.stderr}")
    return str(audio_path)


def transcribe_video(video_path: str, output_dir: str) -> dict:
    """
    Transcribe a single video using Whisper with word timestamps.

    Returns:
        dict with keys: video_path, transcript_path, success, error, word_count
    """
    import whisper

    stem = Path(video_path).stem
    transcript_path = os.path.join(output_dir, f"{stem}_transcript.json")

    # Skip Whisper if transcript already exists
    if os.path.exists(transcript_path):
        word_count = 0
        try:
            with open(transcript_path) as f:
                data = json.load(f)
                word_count = sum(len(s.get("words", [])) for s in data.get("segments", []))
        except Exception:
            pass
        return {
            "video_path": video_path,
            "transcript_path": transcript_path,
            "success": True,
            "error": None,
            "word_count": word_count,
            "duration": 0
        }

    audio_path = get_audio_path(video_path)
    model = whisper.load_model("base")
    result = model.transcribe(audio_path, word_timestamps=True)

    # Write transcript
    with open(transcript_path, "w") as f:
        json.dump(result, f, indent=2)

    word_count = sum(len(seg.get("words", [])) for seg in result.get("segments", []))

    return {
        "video_path": video_path,
        "transcript_path": transcript_path,
        "success": True,
        "error": None,
        "word_count": word_count,
        "duration": result.get("duration", 0)
    }


def run(config, job_state: dict) -> dict:
    """
    Transcribe all videos in source_dir.
    Updates job_state["transcribe"] with per-video results.
    """
    os.makedirs(config.output_dir, exist_ok=True)

    videos = config.get_video_files()
    if not videos:
        return {"status": "error", "message": "No video files found"}

    results = []
    for video_path in videos:
        try:
            logger.info(f"Transcribing: {video_path}")
            result = transcribe_video(video_path, config.output_dir)
            if result["word_count"] == 0:
                logger.warning(f"No words transcribed from {video_path} — skipping")
                result["success"] = False
                result["error"] = "Transcription produced no output"
            results.append(result)
        except Exception as e:
            logger.error(f"Transcription failed for {video_path}: {e}")
            results.append({
                "video_path": video_path,
                "transcript_path": None,
                "success": False,
                "error": str(e),
                "word_count": 0
            })

    job_state["transcribe"] = results

    skipped = [r for r in results if not r["success"]]
    processed = [r for r in results if r["success"]]

    return {
        "status": "ok",
        "total": len(videos),
        "processed": len(processed),
        "skipped": len(skipped),
        "skipped_videos": [r["video_path"] for r in skipped]
    }
