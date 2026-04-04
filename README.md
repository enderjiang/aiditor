# Base Video Editor Pipeline

Automated video editing pipeline that transcribes, segments, scores, and exports highlight clips.

## Quick Start

### 1. Create `job_config.json` in the pipeline folder

```bash
# Or use a pre-saved config:
cp config_<folder>.json job_config.json
```

### 2. Run

```json
{
  "source_dir": "/Volumes/django/base_video_editor/your-project-folder",
  "output_dir": "/Volumes/django/base_video_editor/your-project-folder/processed",
  "template": "classrecap",
  "mode": "individual",
  "target_duration": 120,
  "resolution": "720p",
  "bitrate": "1M",
  "templates_dir": "/Volumes/django/base_video_editor/pipeline/templates"
}
```

**Required field:**
- `target_duration` — target clip length in seconds (clips are selected automatically by score until duration is met ±10s)

### 2. Run

```bash
cd /Volumes/django/base_video_editor/pipeline
python pipeline.py --config job_config.json
```

## Pipeline Steps

| Step | Module | What it does |
|---|---|---|
| Transcribe | `src/transcribe.py` | Whisper word-level transcription |
| Segment | `src/segment.py` | Split on silence (≥5s gap = boundary) |
| Score | `src/score.py` | Rate segments by content quality |
| Select | `src/select.py` | Pick top N segments matching target duration |
| Export | `src/export.py` | Cut & concatenate with ffmpeg |

## Project Structure

```
pipeline/
├── pipeline.py              ← Main entry point
├── job_config.json         ← Active job config
├── README.md               ← This file
├── config_*.json           ← Saved per-folder configs
├── templates/
│   ├── __init__.py
│   └── classrecap.json     ← Default scoring template
└── src/
    ├── __init__.py
    ├── config.py           ← JobConfig dataclass + validation
    ├── transcribe.py       ← Whisper transcription
    ├── segment.py           ← Sentence extraction + segmentation
    ├── score.py             ← Normalized segment scoring
    ├── selector.py          ← Duration-driven selection
    └── export.py            ← ffmpeg cut & concat
```

## Queue System (Multiple Folders)

Use `queue.py` to run multiple folders **sequentially** (not in parallel):

```bash
# Run all saved configs
python queue.py --all

# Run specific configs
python queue.py config_maker01.json config_maker02.json config_nrpc.json
```

`queue.py` streams live output, waits for each job to finish, and stops on first failure.

## Modes

- **`individual`** — one highlight clip per source video
- **`single`** — combine all videos into one compilation clip

## Segmentation Rules

| Rule | Value |
|---|---|
| Silence boundary | ≥ 5 seconds gap |
| Long silence kill | ≥ 10 seconds gap inside segment → **discarded** |
| Forced break | > 30s building → cut at ≥2s pause |
| Min segment | < 2 seconds → discarded |
| Max segment | > 15 seconds → split |

## Scoring (classrecap)

1. **Word density** — faster speech = higher score
2. **Action keywords** — hits × 3.0 multiplier
3. **Complete sentence** — ends with `.!？` → +3 bonus
4. **Questions** — contains question word → +1 bonus
5. **Excitement** — contains excitement word → +1.5 bonus

## Requirements

```bash
pip install openai-whisper
# ffmpeg must be installed (brew install ffmpeg)
```
