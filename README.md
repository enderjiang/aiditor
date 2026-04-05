# Aiditor — Base Video Editor Pipeline

> AI-powered video highlight generation for educational/content video editing

**First Release:** Class Record Video Editor Agent (executed by OpenClaw)

## Project Vision

## Project Vision

### The Pain Point

Creating highlight reels from raw video footage is **labor-intensive**:
- Manual transcription and timestamp marking
- Subjective clip selection by watching entire footage
- Tedious cutting and concatenation in video editors
- Inconsistent quality across different editors

**Typical workflow:** 1 hour of raw footage → 30-60 minutes of manual editing → 3-5 minute highlight

### Our Solution

An automated pipeline that:
1. **Transcribes** speech with Whisper (word-level timestamps)
2. **Segments** content by complete sentences (5s silence = boundary)
3. **Scores** clips by content quality (keyword density, engagement signals)
4. **Selects** top segments to match target duration (±10s tolerance)
5. **Exports** ready-to-use highlight clips

### Time Savings

| Task | Manual | Our Pipeline |
|------|--------|--------------|
| Transcription | 0.5-1x video duration | 0.1-0.2x video duration |
| Clip Selection | 10-30 min | Automatic (seconds) |
| Export | 5-15 min | Automatic (seconds) |
| **Total** | **30-60 min per highlight** | **~5-20 min** (mostly Whisper) |

**Time saved: 50-80%** (mostly in transcription and selection)

### Token Consumption

Based on pipeline runs with `classrecap` template:

| Video Duration | Whisper Tokens (approx) | Pipeline Tokens | Total Estimate |
|----------------|----------------------|-----------------|----------------|
| 10 min | ~50K | ~10K | ~60K |
| 30 min | ~150K | ~15K | ~165K |
| 60 min | ~300K | ~20K | ~320K |

*Note: Most token consumption is in Whisper transcription. The scoring/selection steps are lightweight.*

### Current Status

- ✅ **Production-ready:** Successfully processed multiple projects
- ✅ **Sentence-aware segmentation:** Respects natural speech breaks
- ✅ **Normalized scoring:** Longer clips don't automatically win
- ✅ **Queue system:** Multi-folder batch processing with notifications
- ✅ **Heartbeat monitoring:** Progress tracking per SOP

### Roadmap

- [ ] Multi-language support (non-English transcription)
- [ ] Scene detection fallback (for non-speech videos)
- [ ] Custom scoring templates per content type
- [ ] Web UI for configuration and monitoring

---

## Quick Start (Run with OpenClaw Agent)

```bash
# Clone the repo
git clone https://github.com/enderjiang/aiditor.git
cd aiditor

# Install dependencies
pip install openai-whisper
brew install ffmpeg  # macOS

# Create a job config
cp jobs/00_TEMPLATE.json jobs/my_project.json
# Edit my_project.json with your folder path and target duration

# Run pipeline (via OpenClaw agent)
python pipeline.py --config job_config.json

# Or use the queue system for multi-folder processing
python queue.py --add  # Interactive job creation
python queue.py        # Run all jobs sequentially
```

## Powered by OpenClaw

This pipeline is designed to run as an **OpenClaw agent task**. The pipeline:
- Follows SOP (Standard Operating Procedure) defined in `SOP.txt`
- Uses heartbeat for progress tracking
- Supports queue system for batch processing
- Can be triggered via OpenClaw's task system

## System Architecture

See [architecture diagram](docs/options/option_a_baoyu_infographic.png) for visual overview.

```
Input: Raw Videos (.mp4)
  │
  ▼
[1] Whisper Transcription → Word-level timestamps
  │
  ▼
[2] Sentence Extraction + Segmentation (5s silence = boundary)
  │
  ▼
[3] Content Scoring (normalized per-second)
  │
  ▼
[4] Duration-Driven Selection (target ±10s)
  │
  ▼
[5] ffmpeg Export (cut + concat)
  │
  ▼
Output: Highlight Clips (.mp4)
```

## Configuration

| Field | Description |
|-------|-------------|
| `source_dir` | Folder containing input videos |
| `output_dir` | Where to save processed files |
| `target_duration` | Target clip length in seconds |
| `mode` | `individual` (one per video) or `single` (combine all) |
| `template` | Scoring template (default: `classrecap`) |

See [SOP.txt](SOP.txt) for detailed documentation.
