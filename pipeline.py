#!/usr/bin/env python3
"""
pipeline.py — Video Editing Pipeline

Main entry point for the base_video_editor pipeline.
Runs: Transcribe → Segment → Score → Select & Export

Usage:
    # Set up job_config.json first (see SOP), then:
    python pipeline.py [--config job_config.json]

Heartbeat:
    Writes progress to ~/HEARTBEAT.md during execution.
    Each step logs its completion and results.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.config import JobConfig
from src import transcribe, segment, score, selector, export

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("pipeline")


# ─── Heartbeat ────────────────────────────────────────────────────────────────

HEARTBEAT_PATH = os.path.expanduser("~/HEARTBEAT.md")


def write_heartbeat(status: str, progress: str, eta: str = ""):
    """Write progress to heartbeat file for agent monitoring"""
    content = f"""# HEARTBEAT

task: base_video_editor pipeline
agent: engineer
started: {datetime.now().isoformat()}
status: {status}
progress: {progress}
eta: {eta}
"""
    with open(HEARTBEAT_PATH, "w") as f:
        f.write(content)


def clear_heartbeat():
    """Remove heartbeat file on completion"""
    try:
        if os.path.exists(HEARTBEAT_PATH):
            os.remove(HEARTBEAT_PATH)
    except Exception:
        pass


# ─── Pipeline ─────────────────────────────────────────────────────────────────

STEPS = [
    ("transcribe", transcribe),
    ("segment", segment),
    ("score", score),
    ("select", selector),
    ("export", export),
]


def run_pipeline(config: JobConfig) -> dict:
    """
    Run all pipeline steps in order.
    Returns a summary dict of all step results.
    """
    job_state = {"config": config}

    step_results = {}

    for step_name, step_module in STEPS:
        logger.info(f"═══ Step: {step_name.upper()} ═══")
        write_heartbeat("in-progress", f"Running {step_name}...")

        try:
            result = step_module.run(config, job_state)
        except Exception as e:
            logger.exception(f"Step {step_name} crashed: {e}")
            result = {"status": "error", "message": str(e)}

        step_results[step_name] = result
        job_state[f"_{step_name}_result"] = result

        if result.get("status") == "error":
            logger.error(f"Step {step_name} error: {result.get('message')}")
            return {
                "status": "error",
                "failed_step": step_name,
                "message": result.get("message"),
                "step_results": step_results
            }

        logger.info(f"Step {step_name} complete: {result}")

    return {
        "status": "ok",
        "step_results": step_results,
        "job_state": job_state
    }


def format_report(config: JobConfig, job_state: dict, result: dict) -> str:
    """Format a human-readable summary report"""
    if result.get("status") == "error":
        return f"""❌ Pipeline failed at step: {result.get("failed_step")}
Error: {result.get("message")}"""

    export_data = job_state.get("export", {})
    transcribe_data = job_state.get("transcribe", [])
    stats_data = job_state.get("stats", {})

    total_videos = len(transcribe_data)
    processed = [r for r in transcribe_data if r.get("success")]
    skipped = [r for r in transcribe_data if not r.get("success")]
    exported = [v for v in export_data.values() if v.get("success")]

    lines = [
        "✅ Pipeline complete!",
        "",
        f"📁 Source: {config.source_dir}",
        f"📁 Output: {config.output_dir}",
        f"🎯 Mode: {config.mode} | Target: {config.target_duration}s highlight",
        "",
        f"📊 Videos: {len(processed)}/{total_videos} transcribed, {len(skipped)} skipped",
    ]

    if skipped:
        lines.append(f"⚠️  Skipped: {[Path(r['video_path']).name for r in skipped]}")

    lines.append("")
    lines.append("📄 Outputs:")

    for stem, exp in export_data.items():
        if exp.get("success"):
            path = exp["output_path"]
            name = Path(path).name
            dur = exp.get("duration", 0)
            clips = exp.get("segments", 0)
            lines.append(f"  • {name} — {dur:.0f}s, {clips} clips")
        else:
            lines.append(f"  • {stem}: ❌ {exp.get('error', 'unknown error')}")

    lines.append("")
    lines.append("🎬 Segment timestamps per video:")
    select_data = job_state.get("select", {})
    for stem, segs in select_data.items():
        if not segs:
            continue
        times = ", ".join(f"{s['start']:.1f}s–{s['end']:.1f}s" for s in segs)
        lines.append(f"  • {stem}: {times}")

    return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Video Editing Pipeline")
    parser.add_argument("--config", default="job_config.json", help="Path to job_config.json")
    args = parser.parse_args()

    config_path = args.config

    # If config path is relative, resolve relative to pipeline dir
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.path.dirname(__file__), config_path)

    if not os.path.exists(config_path):
        print(f"ERROR: Config file not found: {config_path}")
        print("Create job_config.json first. See SOP for fields.")
        sys.exit(1)

    # Load and validate config
    try:
        config = JobConfig.from_file(config_path)
    except Exception as e:
        print(f"ERROR: Failed to load config: {e}")
        sys.exit(1)

    errors = config.validate()
    if errors:
        print("ERROR: Config validation failed:")
        for err in errors:
            print(f"  • {err}")
        sys.exit(1)

    print(f"Loaded config: {config.source_dir} → {config.output_dir}")
    print(f"Template: {config.template} | Mode: {config.mode} | Target: {config.target_duration}s highlight")
    print()

    write_heartbeat("in-progress", f"Starting pipeline: {config.source_dir}")
    result = run_pipeline(config)

    report = format_report(config, result.get("job_state", {}), result)
    print()
    print(report)

    if result.get("status") == "ok":
        clear_heartbeat()
    else:
        write_heartbeat("error", f"Failed at {result.get('failed_step')}: {result.get('message')}")

    # Write result JSON for programmatic use
    result_path = os.path.join(config.output_dir, "pipeline_result.json")
    os.makedirs(config.output_dir, exist_ok=True)
    with open(result_path, "w") as f:
        # Strip non-serializable objects
        clean = {k: v for k, v in result.items() if k != "job_state"}
        # Include readable export summary
        clean["report"] = report
        json.dump(clean, f, indent=2, default=str)
    print(f"\n📄 Result saved to: {result_path}")


if __name__ == "__main__":
    main()
