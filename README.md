# interview-eval-pipeline

Automated candidate evaluation system for recorded job interviews. Processes MP4 video files through a transcription and LLM-scoring pipeline, producing structured JSON evaluations and a batch CSV summary.

## Quick Start (Windows — for HR / non-technical users)

If you're on a Windows machine and just want to grade interviews, you only need two double-clicks:

1. **Install Python** — if you don't already have it, get it from the [Microsoft Store](https://apps.microsoft.com/search?query=python+3) or [python.org](https://www.python.org/downloads/). Make sure "Add Python to PATH" is checked during install.
2. **Double-click `1_Setup_For_HR.bat`** — this creates a local environment, installs all dependencies (including FFmpeg), and sets up Desktop folders. It will open a Notepad window where you paste your API key.
3. **Place `.mp4` interview videos** in the `Interviews_To_Grade` folder on your Desktop. Files must be named like `firstname-lastname-SME.mp4` or `firstname-lastname-QA.mp4`.
4. **Double-click `2_Run_Evaluations.bat`** — results appear in the `Results` folder on your Desktop.

> **First run note:** The first evaluation will download a transcription model, which may take a few minutes. The window may appear frozen — this is normal.

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
2. **Transcribe** -- extracts audio via FFmpeg, transcribes with faster-whisper
3. **Analyze** -- scores transcript against rubric via Claude Sonnet
4. **Classify** -- applies decision rules (Advance / Hold / Decline)
5. **Output** -- writes JSON + CSV, moves processed files

## Modules

| Module | Responsibility |
|:---|:---|
| `ingest.py` | File scanning, filename validation, directory management |
| `transcribe.py` | FFmpeg audio extraction + faster-whisper transcription |
| `analyze.py` | Claude API rubric scoring with structured output |
| `classify.py` | Pure decision logic (advance/hold/decline/hard-fail) |
| `output.py` | Per-candidate JSON + batch CSV generation |
| `pipeline.py` | Orchestrates the full flow with per-candidate error isolation |
| `cli.py` | CLI entry point (argparse) |
| `models.py` | All Pydantic data models |
| `config.py` | Configuration constants and environment loading |

## Tests

```bash
pytest
```

## License

MIT
