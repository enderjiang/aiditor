"""
select.py — Select and Export step

Selection is driven purely by target_duration.
Algorithm:
1. Sort scored candidates by score descending
2. Greedily take segments until total duration hits target (±10s tolerance)
   - Too short → take next highest-ranked candidate
   - Too long → drop lowest-ranked selected segment
3. Re-sort final selection by original start time (chronological)
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DURATION_TOLERANCE = 10  # seconds


def select_segments(scored_segments: list, target_duration: int) -> list:
    """
    Select the best segments to reach target_duration.

    Args:
        scored_segments: list of scored segment dicts (sorted desc by score)
        target_duration: target total duration in seconds

    Returns:
        list of selected segment dicts, sorted chronologically
    """
    if not scored_segments:
        return []

    sorted_segs = sorted(scored_segments, key=lambda x: x["score"], reverse=True)
    selected = []
    total_duration = 0.0
    min_duration = target_duration - DURATION_TOLERANCE
    max_duration = target_duration + DURATION_TOLERANCE

    for seg in sorted_segs:
        seg_dur = seg["end"] - seg["start"]
        # If adding this segment doesn't overshoot max, include it
        if total_duration + seg_dur <= max_duration + DURATION_TOLERANCE:
            selected.append(seg)
            total_duration += seg_dur

        # Stop if we're within acceptable range and have at least 1 segment
        if min_duration <= total_duration <= max_duration:
            break

    # If still too short, keep adding regardless of overshoot (up to tolerance)
    if total_duration < min_duration:
        for seg in sorted_segs[len(selected):]:
            if seg in selected:
                continue
            seg_dur = seg["end"] - seg["start"]
            if total_duration + seg_dur <= target_duration + DURATION_TOLERANCE:
                selected.append(seg)
                total_duration += seg_dur
            if total_duration >= min_duration:
                break

    # If too long → drop lowest-ranked selected segments
    while total_duration > max_duration and len(selected) > 1:
        lowest = selected.pop()  # remove lowest-scoring one
        total_duration -= lowest["end"] - lowest["start"]

    # Sort chronologically by start time
    selected.sort(key=lambda x: x["start"])

    final_duration = sum(s["end"] - s["start"] for s in selected)
    logger.info(f"Selected {len(selected)} segments, total duration: {final_duration:.1f}s (target: {target_duration}s ±{DURATION_TOLERANCE})")

    return selected


def run(config, job_state: dict) -> dict:
    """
    Select segments for each video (individual) or overall (single).
    Driven by target_duration only — no target_clips parameter.
    """
    scored_data = job_state.get("score", {})
    target_duration = config.target_duration

    selections = {}
    stats = {}

    if config.mode == "single":
        # Flatten all segments across all videos
        all_scored = []
        for stem, segments in scored_data.items():
            for seg in segments:
                seg["_source_stem"] = stem
            all_scored.extend(segments)

        selected = select_segments(all_scored, target_duration)
        selections["__all__"] = selected
        stats["__all__"] = {
            "count": len(selected),
            "duration": sum(s["end"] - s["start"] for s in selected)
        }
    else:
        for stem, segments in scored_data.items():
            if not segments:
                selections[stem] = []
                stats[stem] = {"count": 0, "duration": 0}
                continue
            selected = select_segments(segments, target_duration)
            selections[stem] = selected
            stats[stem] = {
                "count": len(selected),
                "duration": sum(s["end"] - s["start"] for s in selected)
            }

    job_state["select"] = selections
    job_state["stats"] = stats

    total_selected = sum(s["count"] for s in stats.values())

    return {
        "status": "ok",
        "total_selected": total_selected,
        "videos_processed": len(selections)
    }
