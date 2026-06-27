# interview-eval-pipeline

Automated candidate evaluation system for recorded job interviews. Processes MP4 video files through a transcription and LLM-scoring pipeline, producing structured JSON evaluations and a batch CSV summary.

## Quick Start (Windows — for HR / non-technical users)

If you're on a Windows machine and just want to grade interviews, you only need two double-clicks:

1. **Install Python** — if you don't already have it, get it from the [Microsoft Store](https://apps.microsoft.com/search?query=python+3) or [python.org](https://www.python.org/downloads/). Make sure "Add Python to PATH" is checked during install.
2. **Double-click `1_Setup_For_HR.bat`** — this creates a local environment, installs all dependencies (including FFmpeg), and sets up Desktop folders. It will open a Notepad window where you paste your API key.
3. **Place `.mp4` interview videos** in the `Interviews_To_Grade` folder on your Desktop. Files must be named like `firstname-lastname-SME.mp4` or `firstname-lastname-QA.mp4`.
4. **Double-click `2_Run_Evaluations.bat`** — results appear in the `Results` folder on your Desktop.

> **First run note:** The first evaluation downloads the `small` faster-whisper transcription model (~460 MB). The window may appear frozen while downloading and during transcription of large video files — this is normal.

---

## Requirements

- Python 3.10+
- FFmpeg installed and on PATH (the batch scripts handle this automatically on Windows)
- Anthropic API key

## Install

### Windows (automated)

Double-click `1_Setup_For_HR.bat`. It handles the virtual environment, dependencies, FFmpeg, and API key configuration.

### Manual / macOS / Linux

```bash
# Install FFmpeg (pick your platform)
winget install Gyan.FFmpeg     # Windows
brew install ffmpeg             # macOS
sudo apt install ffmpeg         # Ubuntu/Debian

# Verify
ffmpeg -version

# Install the pipeline
git clone https://github.com/NitzanZacharia/interview-eval-pipeline.git
cd interview-eval-pipeline
pip install -e ".[dev]"
```

## Configure

Copy the example env file and add your Anthropic API key:

```bash
cp .env.example .env
# Edit .env and replace "your-api-key-here" with your real key
```

Or set it directly as an environment variable:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

On Windows (PowerShell):
```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

## Usage

### Windows (automated)

Double-click `2_Run_Evaluations.bat`. It reads videos from `Desktop\Interviews_To_Grade` and writes results to `Desktop\Results`.

### Command line

```bash
interview-eval --input-dir ./interviews --output-dir ./results
```

| Argument | Required | Default | Description |
|:---|:---|:---|:---|
| `--input-dir` | Yes | -- | Directory containing `.mp4` interview files |
| `--output-dir` | No | `./output` | Directory for JSON and CSV output |
| `--rubric` | No | `./scoring_rubric.md` | Path to scoring rubric file |

## Input

Place `.mp4` files in the input directory using the naming convention:

```
firstname-lastname-JOBTYPE.mp4
```

- Names: lowercase alphabetic (e.g., `john`, `doe`)
- Job type: `SME` or `QA` (uppercase)
- Examples: `john-doe-SME.mp4`, `jane-smith-QA.mp4`

Files with invalid names are moved to a sibling `bad_name_conv/` directory.

## Output

Per-candidate JSON files and a `batch_summary.csv` are written to the output directory. See [SPEC.md](SPEC.md) for the full output schema.

## Pipeline

1. **Ingest** -- scans for `.mp4` files, validates filenames, checks duration
2. **Transcribe** -- extracts audio via FFmpeg, transcribes with faster-whisper (`small` model)
3. **Analyze** -- scores transcript against rubric via Claude Sonnet 4.6 (`temperature=0`, calibrated decisiveness prompt)
4. **Classify** -- applies decision rules (Advance / Hold / Decline)
5. **Output** -- writes JSON + CSV, moves processed files

## Airtable Integration (read-only)

The pipeline can ingest candidate videos directly from an Airtable base instead of a local directory. By default it is **read-only** — it fetches records and downloads attachments without writing anything back. Pass `--write-back` to also PATCH scores into Airtable after each evaluation.

### How it works

1. Polls the Candidate Submissions table for unscored "Video Submission" records (files attached, no score yet).
2. Downloads the video attachment to a local temp directory.
3. Fetches the linked scoring rubric from Airtable (or falls back to a local `scoring_rubric.md`).
4. Runs the full pipeline: transcription, LLM scoring, classification.
5. Writes results locally (JSON, HTML report, CSV) — nothing is written to Airtable.

### Setup

Set an Airtable Personal Access Token with at minimum `data.records:read` and `schema.bases:read` scopes. Add `data.records:write` if you plan to use `--write-back`.

```bash
export AIRTABLE_TOKEN=patXXXXXX...
export ANTHROPIC_API_KEY=sk-ant-...
```

On Windows (PowerShell):
```powershell
$env:AIRTABLE_TOKEN = "patXXXXXX..."
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

### Running the pipeline

```bash
python scripts/simulate_airtable_pipeline.py
```

Scores are written back to Airtable by default. Pass `--dry-run` to skip the write-back (useful for testing; a read-only token is then sufficient).

| Flag | Default | Description |
|:---|:---|:---|
| `--record-id <ID>` | -- | Process a specific Airtable record instead of auto-fetching |
| `--limit <N>` | `1` | Maximum number of records to process |
| `--output-dir <DIR>` | `./sim_output` | Directory for JSON/HTML/CSV outputs |
| `--fallback-rubric <PATH>` | `./scoring_rubric.md` | Local rubric used when no rubric is linked in Airtable |
| `--dry-run` | off | Skip writing scores back to Airtable (read-only mode) |
| `--save-transcripts` | off | Save raw transcript text to `tests/fixtures/transcripts/` after transcription |

### Writing scores back to Airtable

After each successful evaluation the pipeline PATCHes results into the Candidate Submissions record. This requires `data.records:write` scope on the token. Use `--dry-run` to process records without writing anything back.

```bash
python scripts/simulate_airtable_pipeline.py --limit 3
python scripts/simulate_airtable_pipeline.py --limit 3 --dry-run  # read-only
```

On success the record receives all five dimension scores, a Weighted Score (recalculated automatically by Airtable's formula field), and a Recommendation. Once Score 1 is written, that record no longer matches the "unscored" filter, so it will not be re-fetched on future runs.

#### Recommendation mapping

The pipeline produces four internal labels. These are translated to Airtable's singleSelect options before writing:

| Pipeline label | Airtable value | Notes |
|:---|:---|:---|
| `Strong Advance` | `Strong hire` | Total ≥ 17 AND Role Fit ≥ 3 |
| `Advance` | `Hire` | Total 14–16 AND Role Fit ≥ 3 |
| `Hold` | `Lean no` | |
| `Decline` | `Strong no` | |
| `Needs Human Review` | _(skipped)_ | No equivalent option exists; the Recommendation field is left blank |

The mapping is defined in `_RECOMMENDATION_MAP` in `airtable_ingest.py`. The `Strong Advance` / `Advance` split threshold (17) is set in `classify.py`.

> **Note:** Transcription and scoring failures are never written back. Those records keep `Score 1` blank so they are retried on the next run.

## Scoring Calibration

The LLM scoring prompt and rubric were calibrated against a set of real QA Specialist video submissions with known HR ground-truth scores to reduce central tendency bias (the tendency to score everything 2 or 3 regardless of actual quality).

### What was changed

**System prompt (`analyze.py`)** — rewritten with three explicit directives:
- *Decisiveness mandate*: scores 1 and 4 are expected when evidence clearly supports them; 2 and 3 require justification just as much as the extremes do.
- *Symmetric evidence clause*: withholding a high score when clear evidence of excellence exists is treated as an error, not as caution.
- *Substance-over-form*: conversational or rambling delivery is not penalised — the substance of what the candidate describes is what matters.

**Scoring rubric (`scoring_rubric.md`)** — each criterion's 1–4 anchor cells were expanded from a single generic sentence to 2–3 behavioral signals per level, with separate QA Behavioral Signals and SME Behavioral Signals columns. The Process and Instruction-Following criteria include worked examples. Role Fit anchors distinguish classroom-teacher-only backgrounds from candidates who have navigated CTE funding or compliance processes. The Communication anchor includes guidance on narrative Q1 storytelling vs. repetitive thin answers.

**Transcription model (`config.py`)** — upgraded from `base` to `small` for better fidelity on conversational speech.

**Temperature** — set to `0` in all API calls for deterministic, reproducible scoring.

### Calibration results (5 candidates: 3 QA + 2 SME)

| | Old prompt | New prompt | HR ground truth |
|:---|:---:|:---:|:---:|
| Average MAE vs. HR | 0.88 | **0.80** | — |
| Direction accuracy | 1 / 5 | **3 / 5** | — |

Candidates correctly classified by the new prompt: Maria Ferrara (QA → Advance ✓), Natalie Emery (SME → Advance ✓), Cynthia Taylor (SME → Advance ✓). Remaining gaps: Leslie Doucet (expertise visible on video but not in transcript text) and Emily Kobelenz-DiRienzo (one point above the Decline threshold).

### Running the calibration harness

To re-run calibration after changing the prompt or rubric:

```bash
# Step 1: generate transcript fixtures (downloads + transcribes from Airtable)
python scripts/simulate_airtable_pipeline.py --limit 3 --save-transcripts

# Step 2: score the fixtures and compare against HR ground truth
python scripts/compare_prompts.py
```

`compare_prompts.py` prints a per-candidate breakdown and writes `compare_output.csv`. The target is MAE < 1.0 and correct Advance/Decline direction on all calibration candidates. Transcript fixtures are stored in `tests/fixtures/transcripts/` and do not need to be regenerated unless the candidate pool changes.

## Modules

| Module | Responsibility |
|:---|:---|
| `ingest.py` | File scanning, filename validation, directory management |
| `airtable_ingest.py` | Airtable API polling, video download, rubric fetching, score write-back |
| `transcribe.py` | FFmpeg audio extraction + faster-whisper transcription |
| `analyze.py` | Claude API rubric scoring with structured output |
| `classify.py` | Pure decision logic (advance/hold/decline/hard-fail) |
| `output.py` | Per-candidate JSON + batch CSV generation |
| `pipeline.py` | Orchestrates the full flow with per-candidate error isolation |
| `cli.py` | CLI entry point (argparse) |
| `models.py` | All Pydantic data models |
| `config.py` | Configuration constants and environment loading |

**Scripts** (`scripts/`):

| Script | Responsibility |
|:---|:---|
| `simulate_airtable_pipeline.py` | End-to-end Airtable pipeline runner (read-only by default, `--write-back` to PATCH scores) |
| `compare_prompts.py` | Prompt calibration harness — scores saved transcript fixtures, reports MAE and direction accuracy vs. HR ground truth |

## Tests

```bash
pytest
```

## License

MIT
