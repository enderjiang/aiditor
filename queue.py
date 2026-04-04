#!/usr/bin/env python3
"""
queue.py — Sequential pipeline runner with Discord notifications

Processes all jobs in the jobs/ folder in order.
Each job gets its own heartbeat update and a Discord DM to the user when done.

Usage:
    python queue.py                  # run all jobs in jobs/ folder
    python queue.py --dry-run        # show what would run, don't execute
    python queue.py jobs/001_foo.json  # run specific job(s)
    python queue.py --add            # interactive: create a new job from prompts
"""

import os
import sys
import json
import subprocess
import argparse
import glob
import re
from datetime import datetime

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = "/tmp"
HEARTBEAT_PATH = os.path.expanduser("~/HEARTBEAT.md")
DISCORD_CHANNEL_ID = "1487830336636195009"  # #base-video-editor channel


# ── Discord notification ─────────────────────────────────────────────────────

def notify(message: str):
    """Send a Discord message via openclaw CLI."""
    cmd = ["openclaw", "message", "send",
           "--channel", "discord",
           "--target", DISCORD_CHANNEL_ID,
           "--message", message]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            print(f"[notify] failed: {result.stderr[:200]}")
    except Exception as e:
        print(f"[notify] error: {e}")


# ── Heartbeat ────────────────────────────────────────────────────────────────

def write_heartbeat(status: str, progress: str, eta: str = ""):
    content = f"""# HEARTBEAT

task: base_video_editor queue
agent: engineer
started: {datetime.now().isoformat()}
status: {status}
progress: {progress}
eta: {eta}
"""
    try:
        with open(HEARTBEAT_PATH, "w") as f:
            f.write(content)
    except Exception as e:
        print(f"[heartbeat] write failed: {e}")


def clear_heartbeat():
    try:
        if os.path.exists(HEARTBEAT_PATH):
            os.remove(HEARTBEAT_PATH)
    except Exception:
        pass


# ── Job helpers ──────────────────────────────────────────────────────────────

def load_job(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def load_result(output_dir: str) -> dict | None:
    rp = os.path.join(output_dir, "pipeline_result.json")
    if os.path.exists(rp):
        with open(rp) as f:
            return json.load(f)
    return None


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    return f"{seconds//60:.0f}m {seconds%60:.0f}s"


# ── Pipeline runner ──────────────────────────────────────────────────────────

def run_job(job: dict, job_path: str, log_path: str) -> dict:
    """Run pipeline.py for one job, stream output to log."""
    job_name = job.get("name", os.path.basename(job_path))
    print(f"\n{'='*60}")
    print(f"  STARTING: {job_name}")
    print(f"  Source:   {job['source_dir']}")
    print(f"  Mode:     {job['mode']} | Target: {job['target_duration']}s")
    print(f"{'='*60}")

    write_heartbeat(
        "in-progress",
        f"Running {job_name}... Transcription step starting.",
        "See Discord for updates on completion."
    )

    # Write job as active job_config.json for pipeline.py
    config_path = os.path.join(PIPELINE_DIR, "job_config.json")
    with open(config_path, "w") as f:
        json.dump(job, f, indent=2)

    proc = subprocess.Popen(
        [sys.executable, "pipeline.py", "--config", config_path],
        cwd=PIPELINE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    last_step = "transcribe"
    step_times = {}

    with open(log_path, "w") as logf:
        logf.write(f"Job: {job_name}\nConfig: {job_path}\n\n")
        for line in proc.stdout:
            decoded = line.decode("utf-8", errors="replace")
            logf.write(decoded)

            # Detect step transitions
            for step in ("TRANSCRIBE", "SEGMENT", "SCORE", "SELECT", "EXPORT"):
                if f"Step: {step}" in decoded:
                    last_step = step
                    step_times[step] = datetime.now()
                    write_heartbeat(
                        "in-progress",
                        f"[{job_name}] {step} step running...",
                        ""
                    )

            print(decoded, end="")

    proc.wait()

    result = load_result(job.get("output_dir", ""))
    return {
        "job_name": job_name,
        "job_path": job_path,
        "returncode": proc.returncode,
        "result": result,
        "log_path": log_path,
    }


# ── Queue summary ─────────────────────────────────────────────────────────────

def build_summary(results: list[dict]) -> str:
    lines = ["**Pipeline Queue Complete**\n"]
    all_ok = True
    for r in results:
        status = "✅" if r["returncode"] == 0 else "❌"
        name = r["job_name"]
        if r["returncode"] == 0:
            res = r["result"]
            if res and res.get("step_results", {}).get("export", {}).get("exported"):
                exp = res["step_results"]["export"]
                out_files = []
                export_data = res.get("job_state", {}).get("export", {}) if "job_state" in res else {}
                # Re-read from result JSON for cleaner output
                rp_path = None
                for k, v in (res.get("job_state", {}) or {}).items():
                    if isinstance(v, dict) and v.get("success") and v.get("output_path"):
                        out_files.append(os.path.basename(v["output_path"]))
                lines.append(f"{status} **{name}**")
                lines.append(f"   → {len(out_files)} clip(s) exported")
            else:
                lines.append(f"{status} **{name}**")
                all_ok = False
        else:
            lines.append(f"{status} **{name}** — FAILED (see log)")
            all_ok = False
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Pipeline queue runner")
    parser.add_argument("--dry-run", action="store_true", help="Show jobs without running")
    parser.add_argument("--add", action="store_true", help="Interactively add a new job")
    parser.add_argument("jobs", nargs="*", help="Specific job files to run")
    args = parser.parse_args()

    # Collect jobs
    if args.jobs:
        jobs = args.jobs
    else:
        jobs = sorted(glob.glob(os.path.join(PIPELINE_DIR, "jobs", "*.json")))

    if not jobs:
        print("No jobs found in jobs/ folder.")
        print("Use --add to create a new job, or add JSON files to jobs/")
        sys.exit(1)

    # Load and validate
    loaded = []
    for jp in jobs:
        try:
            j = load_job(jp)
            if "source_dir" not in j:
                print(f"SKIP {jp}: missing source_dir")
                continue
            j["_path"] = jp
            loaded.append(j)
        except Exception as e:
            print(f"ERROR loading {jp}: {e}")

    if not loaded:
        print("No valid jobs to run.")
        sys.exit(1)

    # Dry run
    if args.dry_run:
        print(f"Queue has {len(loaded)} job(s):")
        for j in loaded:
            print(f"  [{j['name']}] mode={j['mode']} target={j['target_duration']}s  {j['source_dir']}")
        print("\nRemove --dry-run to execute.")
        sys.exit(0)

    # Add job
    if args.add:
        print("Add new job interactively...")
        name = input("Job name (e.g. my_folder): ").strip()
        source = input("Source dir: ").strip()
        output = input("Output dir [/path/source/processed]: ").strip()
        duration = int(input("Target duration (seconds): ").strip() or "120")
        mode = input("Mode [single]: ").strip() or "single"

        if not output:
            output = os.path.join(os.path.dirname(source.rstrip("/")), name, "processed")

        job = {
            "name": name,
            "source_dir": source,
            "output_dir": output,
            "template": "classrecap",
            "mode": mode,
            "target_duration": duration,
            "resolution": "720p",
            "bitrate": "1M",
            "templates_dir": os.path.join(PIPELINE_DIR, "templates"),
        }

        # Assign next number
        existing = glob.glob(os.path.join(PIPELINE_DIR, "jobs", "*.json"))
        next_num = len(existing) + 1
        path = os.path.join(PIPELINE_DIR, "jobs", f"{next_num:03d}_{name}.json")
        with open(path, "w") as f:
            json.dump(job, f, indent=2)
        print(f"Saved: {path}")
        sys.exit(0)

    # Execute
    total = len(loaded)
    print(f"\n{'#'*60}")
    print(f"  QUEUE: {total} job(s)")
    for i, j in enumerate(loaded, 1):
        print(f"  {i}. {j['name']}  [{j['mode']}] {j['target_duration']}s — {j['source_dir']}")
    print(f"{'#'*60}\n")

    results = []
    start_time = datetime.now()

    for i, job in enumerate(loaded, 1):
        job_name = job.get("name", f"job_{i}")
        log_path = os.path.join(LOG_DIR, f"queue_{i}_{job_name}.log")

        write_heartbeat(
            "in-progress",
            f"Queue running: {job_name} ({i}/{total}). Whisper is the slow step.",
            f"~15-25 min per video. See log: {log_path}"
        )

        r = run_job(job, job["_path"], log_path)
        results.append(r)

        if r["returncode"] != 0:
            print(f"\n❌ JOB FAILED: {job_name}")
            print(f"   Log: {r['log_path']}")
            notify(
                f"⚠️ **Queue stopped**\n"
                f"Job `{job_name}` failed (exit {r['returncode']}).\n"
                f"Log: {r['log_path']}"
            )
            write_heartbeat("error", f"Job {job_name} failed. Queue stopped.", "")
            break

        elapsed = (datetime.now() - start_time).total_seconds()
        remaining = total - i
        print(f"\n✅ Completed {i}/{total}: {job_name} ({elapsed/60:.0f}m elapsed)")

    # Queue complete
    clear_heartbeat()
    summary = build_summary(results)
    print(f"\n{summary}")
    notify(summary)

    print(f"\nAll logs: /tmp/queue_*.log")


if __name__ == "__main__":
    main()
