"""
segment.py — Sentence Extraction + Segmentation step

Phase 1 — Sentence Extraction:
  Parse Whisper transcript into complete sentences.
  A sentence ends with .!？AND the next word starts ≥2s later.
  Discard sentences shorter than 2s of speech.

Phase 2 — Segment:
  Group consecutive sentences into candidate segments.
  Gap ≥ 5s between sentences → new segment boundary.
  Segment > 30s → force split.
  Single sentence > 30s with no gaps → split at word level at nearest ≥2s pause.

Phase 3 — Score (normalized):
  All component scores are expressed PER SECOND so longer segments don't
  automatically dominate.
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Constants ────────────────────────────────────────────────────────────────

SENTENCE_END_PUNCT = re.compile(r"[.!?\-\u2014\u2013]$")
MIN_SENTENCE_DURATION = 2.0
GAP_BOUNDARY = 5.0          # ≥5s gap → segment boundary
MAX_SEGMENT_DURATION = 30.0  # force split if segment exceeds this
FORCED_SPLIT_GAP = 5.0      # split at gaps ≥ this within long sentences
SENTENCE_START_GAP = 2.0    # gap needed to confirm sentence break


# ─── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class Word:
    word: str
    start: float
    end: float


@dataclass
class Sentence:
    start: float
    end: float
    text: str
    word_count: int

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Segment:
    start: float
    end: float
    sentences: list[Sentence]
    word_count: int
    words_per_second: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "duration": self.duration,
            "word_count": self.word_count,
            "words_per_second": self.words_per_second,
            "sentences": [s.text for s in self.sentences]
        }


# ─── Phase 1: Sentence Extraction ───────────────────────────────────────────

def load_words(transcript_path: str) -> list[Word]:
    with open(transcript_path) as f:
        data = json.load(f)
    words = []
    for seg in data.get("segments", []):
        for w in seg.get("words", []):
            words.append(Word(
                word=w["word"].strip(),
                start=float(w["start"]),
                end=float(w["end"])
            ))
    return words


def extract_sentences(words: list[Word]) -> list[Sentence]:
    """
    Group Whisper words into complete sentences.

    A word ends a sentence if:
      1. The word ends with .!？
      2. The next word starts ≥ SENTENCE_START_GAP (2s) after this word ends

    Sentences < MIN_SENTENCE_DURATION (2s) of speech are discarded.
    """
    if not words:
        return []

    sentences: list[Sentence] = []
    current_words: list[Word] = []

    for i, word in enumerate(words):
        is_end = bool(SENTENCE_END_PUNCT.search(word.word))
        gap = words[i + 1].start - word.end if i + 1 < len(words) else SENTENCE_START_GAP + 1

        if is_end and gap >= SENTENCE_START_GAP:
            if current_words:
                dur = word.end - current_words[0].start
                if dur >= MIN_SENTENCE_DURATION:
                    sentences.append(Sentence(
                        start=current_words[0].start,
                        end=word.end,
                        text=" ".join(w.word for w in current_words),
                        word_count=len(current_words)
                    ))
                current_words = []
        else:
            current_words.append(word)

    return sentences


# ─── Phase 2: Segmentation ──────────────────────────────────────────────────

def make_segment(sents: list[Sentence]) -> Optional[Segment]:
    if not sents:
        return None
    total_words = sum(s.word_count for s in sents)
    dur = sents[-1].end - sents[0].start
    return Segment(
        start=sents[0].start,
        end=sents[-1].end,
        sentences=sents,
        word_count=total_words,
        words_per_second=total_words / dur if dur > 0 else 0
    )


def split_long_sentence(words: list[Word]) -> list[list[Sentence]]:
    """
    Split a single OVERSIZED sentence (no internal gaps) at the word level.
    Split at the nearest ≥2s pause within the last 5 seconds of the sentence.
    Returns a list of sentence-groups (each group becomes a sub-segment).
    """
    if not words:
        return []

    dur = words[-1].end - words[0].start
    if dur <= MAX_SEGMENT_DURATION:
        return [words]

    # Find all ≥2s pauses
    target_start = words[-1].end - 5.0
    pause_positions = []
    for i in range(1, len(words)):
        gap = words[i].start - words[i - 1].end
        if gap >= FORCED_SPLIT_GAP and words[i].start >= target_start:
            pause_positions.append(i)

    if not pause_positions:
        # No good pause — split roughly in half by time
        mid_time = words[0].start + dur / 2
        mid_idx = 0
        for i, w in enumerate(words):
            if w.start >= mid_time:
                mid_idx = max(1, i)
                break
        left_group = words[:mid_idx]
        right_group = words[mid_idx:]
        # Recurse to keep splitting until all sub-groups are ≤ MAX
        return split_long_sentence(left_group) + split_long_sentence(right_group)

    # Split at first good pause
    split_idx = pause_positions[0]
    left = split_long_sentence(words[:split_idx])
    right = split_long_sentence(words[split_idx:])
    return left + right


def words_to_sentence_group(word_group: list[Word]) -> Sentence:
    """Convert a word group into a Sentence object"""
    return Sentence(
        start=word_group[0].start,
        end=word_group[-1].end,
        text=" ".join(w.word for w in word_group),
        word_count=len(word_group)
    )


def build_segments(sentences: list[Sentence], words: list[Word]) -> list[Segment]:
    """
    Group sentences into candidate segments.

    Rules:
      - Gap ≥ 5s between sentence end and next sentence start → new segment
      - If segment > 30s without hitting a 5s gap → force split
      - Single sentence > 30s with no internal gaps → split at word level (≥2s pause)
    """
    if not sentences:
        return []

    # Build a word-index for sentence → word lookup
    # sentence_words[sentence_index] = list of words in that sentence
    # We reconstruct by re-parsing: find words between sentence.start and sentence.end
    def get_sentence_words(sent: Sentence) -> list[Word]:
        return [w for w in words if sent.start <= w.start < sent.end + 0.01]

    sentence_words: list[list[Word]] = []
    for sent in sentences:
        sw = get_sentence_words(sent)
        sentence_words.append(sw if sw else [Word("", sent.start, sent.start)])

    def split_segment(sents: list[Sentence], sents_words: list[list[Word]]) -> list[Segment]:
        """Recursively split sents into valid ≤30s segments"""
        if not sents:
            return []
        if len(sents) == 1:
            # Single sentence: check if it needs word-level split
            seg = make_segment(sents)
            if seg is None or seg.duration <= MAX_SEGMENT_DURATION:
                return [seg] if seg else []

            # Split this sentence at word level
            sub_word_groups = split_long_sentence(sents_words[0])
            result = []
            for wg in sub_word_groups:
                sub_sent = words_to_sentence_group(wg)
                sub_seg = make_segment([sub_sent])
                if sub_seg:
                    result.append(sub_seg)
            return result

        seg = make_segment(sents)
        if seg is None:
            return []
        if seg.duration <= MAX_SEGMENT_DURATION:
            return [seg]

        # Find first ≥5s gap to split on
        for i in range(1, len(sents)):
            gap = sents[i].start - sents[i - 1].end
            if gap >= FORCED_SPLIT_GAP:
                left = split_segment(sents[:i], sents_words[:i])
                right = split_segment(sents[i:], sents_words[i:])
                return left + right

        # No gap — split in half
        mid = len(sents) // 2
        return split_segment(sents[:mid], sents_words[:mid]) + split_segment(sents[mid:], sents_words[mid:])

    results: list[Segment] = []
    current: list[Sentence] = [sentences[0]]
    current_words: list[list[Word]] = [sentence_words[0]]

    for i in range(1, len(sentences)):
        curr = sentences[i]
        curr_words = sentence_words[i]
        gap = curr.start - sentences[i - 1].end
        seg_dur = curr.end - current[0].start

        # Force split if segment has grown > 30s
        if seg_dur > MAX_SEGMENT_DURATION and len(current) >= 1:
            seg = make_segment(current)
            if seg:
                results.extend(split_segment(current, current_words))
            current = [curr]
            current_words = [curr_words]
            continue

        # Gap ≥ 5s → new segment boundary
        if gap >= GAP_BOUNDARY:
            seg = make_segment(current)
            if seg:
                results.extend(split_segment(current, current_words))
            current = [curr]
            current_words = [curr_words]
        else:
            current.append(curr)
            current_words.append(curr_words)

    if current:
        results.extend(split_segment(current, current_words))

    return results


def process_transcript(transcript_path: str) -> tuple[list[Sentence], list[Segment]]:
    words = load_words(transcript_path)
    sentences = extract_sentences(words)
    segments = build_segments(sentences, words)
    return sentences, segments


def run(config, job_state: dict) -> dict:
    transcribe_results = job_state.get("transcribe", [])
    all_sentences = {}
    all_segments = {}

    for result in transcribe_results:
        if not result["success"]:
            continue
        stem = Path(result["video_path"]).stem
        try:
            sentences, segments = process_transcript(result["transcript_path"])
            all_sentences[stem] = [s.__dict__ for s in sentences]
            all_segments[stem] = [s.to_dict() for s in segments]
            logger.info(f"{stem}: {len(sentences)} sentences → {len(segments)} segments")
        except Exception as e:
            logger.error(f"Segmentation failed for {stem}: {e}")
            all_sentences[stem] = []
            all_segments[stem] = []

    job_state["sentences"] = all_sentences
    job_state["segment"] = all_segments

    return {
        "status": "ok",
        "total_sentences": sum(len(v) for v in all_sentences.values()),
        "total_segments": sum(len(v) for v in all_segments.values()),
        "videos_processed": len(all_segments)
    }
