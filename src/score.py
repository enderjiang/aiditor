"""
score.py — Scoring step (normalized per-second)

All component scores are expressed PER SECOND so that segment length
does not automatically favor longer segments.

For classrecap template:
1. Word density score = words_per_second * multiplier  [already per-second]
2. Keyword score = (keyword_hits / word_count) * multiplier * 10  [per-word normalized]
3. Sentence completeness bonus = bonus if last sentence ends with punct  [flat bonus]
4. Question bonus = bonus per question sentence  [flat bonus]
5. Excitement bonus = bonus per excitement sentence  [flat bonus]

Total score is sum of per-second-normalized components.
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


SENTENCE_END_PUNCT = re.compile(r"[.!?\-\u2014\u2013]$")


def is_complete_sentence(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    return bool(t) and bool(SENTENCE_END_PUNCT.search(t[-1])) if t else False


def score_segment(segment: dict, template: dict) -> dict:
    """
    Score a single segment — all components normalized per second
    so that raw duration does not give longer segments an advantage.
    """
    weights = template.get("scoring_weights", {})
    rules = template.get("selection_rules", {})

    density_mult = weights.get("word_density_multiplier", 2.0)
    action_mult = weights.get("action_score_multiplier", 3.0)
    complete_bonus = weights.get("complete_sentence_bonus", 3.0)
    incomplete_penalty = weights.get("incomplete_sentence_penalty", 0.1)
    excitement_bonus = weights.get("excitement_bonus", 1.5)
    question_bonus = weights.get("question_bonus", 1.0)

    action_keywords = template.get("action_keywords", [])
    excitement_keywords = rules.get("excitement_keywords", [])
    question_keywords = rules.get("question_keywords", [])

    sentences = segment.get("sentences", [])
    word_count = segment.get("word_count", 1)
    wps = segment.get("words_per_second", 0.0)
    dur = segment.get("duration", 1.0)
    dur = max(dur, 0.1)  # avoid division by zero

    # 1. Word density score (already per-second: wps * mult)
    density_score = wps * density_mult

    # 2. Keyword score — normalized per word, scaled × 10
    all_words_text = " ".join(sentences).lower()
    all_words_list = all_words_text.split()
    keyword_set = {k.lower() for k in action_keywords}
    action_hits = sum(1 for w in all_words_list if w in keyword_set)
    # Normalize: hits per word * 10, then * multiplier
    keyword_score = (action_hits / max(word_count, 1)) * 10 * action_mult

    # 3. Sentence completeness (flat bonus, not scaled by duration)
    last_sentence = sentences[-1] if sentences else ""
    sentence_complete = is_complete_sentence(last_sentence)
    sentence_score = complete_bonus if sentence_complete else -incomplete_penalty

    # 4. Question bonus — flat bonus per question sentence found
    question_hits = 0
    for kw in question_keywords:
        for s in sentences:
            if kw.lower() in s.lower():
                question_hits += 1
                break
    question_score = question_hits * question_bonus

    # 5. Excitement bonus — flat bonus per excitement sentence
    excitement_hits = 0
    for kw in excitement_keywords:
        for s in sentences:
            if kw.lower() in s.lower():
                excitement_hits += 1
                break
    excitement_score = excitement_hits * excitement_bonus

    total = density_score + keyword_score + sentence_score + question_score + excitement_score

    scored = dict(segment)
    scored["score"] = round(total, 4)
    scored["score_breakdown"] = {
        "density_score": round(density_score, 4),
        "keyword_score": round(keyword_score, 4),
        "sentence_score": round(sentence_score, 4),
        "question_score": round(question_score, 4),
        "excitement_score": round(excitement_score, 4),
        "action_hits": action_hits,
        "word_count": word_count,
        "question_hits": question_hits,
        "excitement_hits": excitement_hits,
        "ends_with_complete_sentence": sentence_complete
    }

    return scored


def run(config, job_state: dict) -> dict:
    template = config.load_template()
    segment_data = job_state.get("segment", {})

    scored_segments = {}

    for stem, segments in segment_data.items():
        scored = [score_segment(seg, template) for seg in segments]
        scored.sort(key=lambda x: x["score"], reverse=True)
        scored_segments[stem] = scored

    job_state["score"] = scored_segments

    return {
        "status": "ok",
        "total_scored": sum(len(v) for v in scored_segments.values()),
        "videos_scored": len(scored_segments)
    }
