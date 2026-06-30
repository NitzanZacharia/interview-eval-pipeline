# interview-eval-pipeline

Automated candidate evaluation system for recorded job interviews. Processes MP4 video files through a transcription and LLM-scoring pipeline, producing structured JSON evaluations and a batch CSV summary.

## Quick Start (Windows — for HR / non-technical users)

If you're on a Windows machine and just want to grade interviews, you only need two double-clicks:

1. **Install Python** — if you don't already have it, get it from the [Microsoft Store](https://apps.microsoft.com/search?query=python+3) or [python.org](https://www.python.org/downloads/). Make sure "Add Python to PATH" is checked during install.
2. **Double-click `1_Setup_For_HR.bat`** — this creates a local environment, installs all dependencies (including FFmpeg), and sets up Desktop folders. It will open a Notepad window where you paste your API key.
3. **Place `.mp4` interview videos** in the `Interviews_To_Grade` folder on your Desktop. Files must be named like `firstname-lastname-SME.mp4` or `firstname-lastname-QA.mp4`.
4. **Double-click `2_Run_Evaluations.bat`** — results appear in the `Results` folder on your Desktop.

> **First run note:** The first evaluation downloads the faster-whisper transcription model. The window may appear frozen while downloading and during transcription of large video files — this is normal.

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
| `--rubric` | No | _(auto)_ | Explicit rubric file override. If omitted, auto-selects `scoring_rubric_QA.md` for QA candidates and `scoring_rubric_SME.md` for SME candidates based on the filename job-type suffix. |

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

1. **Ingest** — scans for `.mp4` files, validates filenames, checks duration
2. **Transcribe** — extracts audio via FFmpeg, transcribes with faster-whisper (`base` model by default; override with `WHISPER_MODEL_SIZE` env var)
3. **Analyze** — scores transcript against rubric via Claude Sonnet 4.6 (`temperature=0`, calibrated decisiveness prompt)
4. **Classify** — applies decision rules (Strong Advance / Advance / Hold / Decline)
5. **Output** — writes JSON + CSV, moves processed files

## Scoring Rubrics

Two role-specific rubrics live in the repo root:

| File | Used for |
|:---|:---|
| `scoring_rubric_QA.md` | QA Specialist candidates (`*-QA.mp4`) |
| `scoring_rubric_SME.md` | CTE SME candidates (`*-SME.mp4`) |

Both the CLI and the Airtable automation path follow the same auto-selection waterfall: role-specific file → `scoring_rubric.md` (base fallback) → rubric linked in the Airtable record.

---

## Airtable Integration

The pipeline integrates with Airtable in three trigger modes:

| Trigger | Endpoint | When it fires |
|:---|:---|:---|
| Airtable Automation | `POST /evaluate` | Video is attached to a Submission record in Airtable and all score fields are empty |
| GAS email watcher | `POST /ingest` | Candidate replies to the video-request email with an MP4 attachment or YouTube link |
| CLI bulk run | _(no server)_ | Developer or HR runs `simulate_airtable_pipeline.py` manually |

All three paths share the same scoring logic and write results back to the same Airtable fields.

---

### Trigger 1 — Airtable Automation → `/evaluate`

When a video is attached to a Candidate Submissions record and all score fields are empty, an Airtable Automation fires a `POST /evaluate` to the Railway server. The server returns 202 immediately and evaluates in the background. Scores appear in Airtable within a few minutes.

#### Airtable automation setup

Create a new Automation on the **Candidate Submissions** table:

- **Trigger:** When a record is updated — matches **all** of the following:
  - Files is not empty + filenames contains `mp4`
  - Recommendation is empty
  - Score 1, Score 2, Score 3, Score 4, and Score 5 are all empty
- **Action:** Run a script

Paste this script and configure the two input variables:

```javascript
const { record_id } = input.config();
const webhook_sec = input.secret('webhook_secret');

const response = await fetch(
    "https://airtableintegration-production.up.railway.app/evaluate",
    {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-Webhook-Secret": webhook_sec,
        },
        body: JSON.stringify({ record_id }),
    }
);

if (response.status === 202) {
    console.log(`Evaluation queued for ${record_id} — scores will appear in ~3 minutes.`);
} else {
    const body = await response.text();
    throw new Error(`Server returned ${response.status}: ${body}`);
}
```

Input variables in the Airtable automation editor:
- `record_id` → **Triggering record's Record ID**
- `webhook_secret` → your `WEBHOOK_SECRET` value (stored as a secret inside the automation)

---

### Trigger 2 — GAS email watcher → `/ingest`

`scripts/gmail_watcher.gs` is a Google Apps Script that runs every 5 minutes and watches the HR inbox for candidate replies to the video-request email. It handles three cases:

- **MP4 attachment** — uploads the file to Google Drive and calls `POST /ingest` with the Drive URL
- **YouTube link** — calls `POST /ingest` with the YouTube URL (server downloads via yt-dlp)
- **No video** — sets `Review Needed = true` on the Submission record and emails HR

#### GAS setup

1. Go to [script.google.com](https://script.google.com) → **New project**
2. Paste the contents of `scripts/gmail_watcher.gs`
3. Update the configuration block at the top of the file (Base IDs, Drive folder ID, HR email address — see [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md))
4. **File > Project Settings > Script Properties** → add two properties:
   - `AIRTABLE_TOKEN` — Airtable Personal Access Token
   - `WEBHOOK_SECRET` — must match the Railway server's `WEBHOOK_SECRET`
5. Run `createTimeTrigger()` once manually from the Apps Script editor to register the 5-minute time trigger
6. Grant the OAuth consent screen permissions for Gmail and Drive when prompted

---

### Trigger 3 — CLI bulk run

Fetches unscored records from Airtable and processes them in bulk. Writes scores back by default; pass `--dry-run` to skip write-back.

#### Setup

```bash
export AIRTABLE_TOKEN=patXXXXXX...
export ANTHROPIC_API_KEY=sk-ant-...
```

On Windows (PowerShell):
```powershell
$env:AIRTABLE_TOKEN = "patXXXXXX..."
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

#### Running

```bash
python scripts/simulate_airtable_pipeline.py
```

| Flag | Default | Description |
|:---|:---|:---|
| `--record-id <ID>` | -- | Process a specific Airtable record instead of auto-fetching |
| `--limit <N>` | all | Maximum number of records to process |
| `--output-dir <DIR>` | `./sim_output` | Directory for JSON/HTML/CSV outputs |
| `--fallback-rubric <PATH>` | `./scoring_rubric.md` | Local rubric used when no rubric is linked in Airtable |
| `--dry-run` | off | Skip writing scores back to Airtable (read-only mode) |
| `--save-transcripts` | off | Save raw transcript text to `tests/fixtures/transcripts/` |

---

### Write-back behaviour

After each successful evaluation the pipeline PATCHes results into the Candidate Submissions record and updates linked tables:

| AI recommendation | Airtable Recommendation field | Application Stage | Candidates table |
|:---|:---|:---|:---|
| `Strong Advance` | `Strong hire` | First Interview | _(unchanged)_ |
| `Advance` | `Hire` | First Interview | _(unchanged)_ |
| `Hold` | `Lean no` | TBD | _(unchanged)_ |
| `Decline` | `Strong no` | Discontinued | Recommendations → `Discontinue` |
| `Needs Human Review` | _(skipped)_ | _(unchanged)_ | _(unchanged)_ |

In addition, after every successful evaluation the pipeline uploads the HTML evaluation report as a binary attachment to the **Model output** field (`multipleAttachments`) on the Candidate Submissions record. This uses the Airtable `uploadAttachment` endpoint (`POST https://content.airtable.com/v0/{baseId}/{recordId}/{fieldId}/uploadAttachment`) with a JSON body containing the base64-encoded HTML file. The upload runs after scores are written, so it never re-triggers the Airtable Automation.

> **Note:** Transcription and scoring failures are never written back. Those records keep `Score 1` blank so they are retried on the next run. A `Needs Human Review` result also sets the `Review Needed` checkbox on the Submission record; the GAS email watcher picks this up and emails HR on its next poll.

---

### Server deployment (Railway)

The FastAPI server lives in `src/interview_eval/server.py` and is deployed to Railway. It exposes:

- `POST /evaluate` — accepts `{"record_id": "<id>"}` with `X-Webhook-Secret` header; called by Airtable Automation
- `POST /ingest` — accepts `{"record_id", "source_type", "source_url", "filename"}` with `X-Webhook-Secret` header; called by GAS email watcher
- `GET /health` — uptime check

**Environment variables required on Railway:**

| Variable | Description |
|:---|:---|
| `AIRTABLE_TOKEN` | Airtable Personal Access Token (`data.records:write` scope) |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `WEBHOOK_SECRET` | Shared secret matched against `X-Webhook-Secret` header on both endpoints |
| `WHISPER_MODEL_SIZE` | _(optional)_ `base` (default, 74 MB) or `small` (483 MB) |
| `RUBRIC_PATH` | _(optional)_ Path to `scoring_rubric.md` on the server (default: repo root) |
| `OUTPUT_DIR` | _(optional)_ Directory for local JSON/HTML/CSV outputs (default: `/tmp/eval_output`) |

**Deploy:**
```bash
railway up --service Airtable_integration
```

---

## Modules

| Module | Responsibility |
|:---|:---|
| `ingest.py` | File scanning, filename validation, directory management |
| `airtable_ingest.py` | Airtable API polling, video download, rubric fetching, score write-back, HTML report upload, stage advancement, candidate discontinuation |
| `airtable_pipeline.py` | Per-record pipeline orchestration shared by CLI script and FastAPI server |
| `server.py` | FastAPI server — `/evaluate` for Airtable Automation, `/ingest` for GAS email watcher |
| `transcribe.py` | FFmpeg audio extraction + faster-whisper transcription |
| `analyze.py` | Claude API rubric scoring with structured output |
| `classify.py` | Pure decision logic (Strong Advance / Advance / Hold / Decline / hard-fail) |
| `output.py` | Per-candidate JSON + batch CSV generation |
| `pipeline.py` | Orchestrates the full local file flow with per-candidate error isolation |
| `cli.py` | CLI entry point (argparse) |
| `models.py` | All Pydantic data models |
| `config.py` | Configuration constants and environment loading |

**Scripts** (`scripts/`):

| Script | Responsibility |
|:---|:---|
| `simulate_airtable_pipeline.py` | CLI runner for bulk Airtable evaluation (writes back by default; `--dry-run` to skip) |
| `gmail_watcher.gs` | Google Apps Script email watcher — monitors HR inbox for candidate video replies and triggers `/ingest` |
| `compare_prompts.py` | Prompt calibration harness — scores saved transcript fixtures, reports accuracy vs. HR ground truth |

## Tests

```bash
pytest
```

## Limitations and Assumptions

* **File Format:** The pipeline strictly requires video files to be in `.mp4` format.
* **Naming Convention:** A rigid naming convention is enforced. Interview files must be named `firstname-lastname-JOBTYPE.mp4` (e.g., `john-doe-SME.mp4` or `jane-smith-QA.mp4`). Any files that fail to match this pattern are automatically moved to a sibling `bad_name_conv/` directory.
* **File Locking (CSV):** The `batch_summary.csv` file must be closed before running the pipeline. If left open in Excel, the script will error with a `PermissionError`.
* **Audio Only:** The evaluation is entirely based on the extracted audio track. Visual cues, presentation materials, and body language are ignored.
* **Audio Quality Dependency:** Poor audio recordings may result in inaccurate transcripts, which directly affects scoring accuracy.
* **Language Support:** The transcription model and scoring rubric are designed exclusively for English-language interviews.
* **Single Speaker Assumption:** The transcription engine processes audio as a single continuous stream. Interviewer prompts or interruptions are included in the transcript and may occasionally be interpreted as candidate speech.
* **Throughput and Duration Constraints:** The system is built and tested for a maximum of ~10 videos per day, with individual video length between 2 and 10 minutes. Videos outside this range trigger processing warnings.

## License

MIT
