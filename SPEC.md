# Interview Evaluation Pipeline — System Specification

## 1. Overview

A lightweight, CLI-driven pipeline that evaluates recorded candidate interviews. It ingests MP4 video files, transcribes them locally, scores each transcript against a structured rubric using an LLM, classifies candidates, and produces per-candidate JSON evaluations plus a batch CSV summary.

**Constraints:** Maximum 10 videos per day, each 2–10 minutes long. Triggered manually via CLI.

---

## 2. System Architecture

### 2.1 Project Structure

```
interview-eval-pipeline/
├── scoring_rubric.md              # Evaluation rubric (existing)
├── pyproject.toml                 # Package config and dependencies
├── .env.example                   # Environment variable template
├── README.md                      # Setup and usage instructions
├── SPEC.md                        # This file
├── src/
│   └── interview_eval/
│       ├── __init__.py
│       ├── cli.py                 # CLI entry point (argparse)
│       ├── config.py              # Configuration and constants
│       ├── pipeline.py            # Main orchestrator
│       ├── ingest.py              # File scanning, validation, directory management
│       ├── transcribe.py          # Audio extraction + transcription
│       ├── analyze.py             # LLM rubric analysis
│       ├── classify.py            # Decision logic
│       ├── output.py              # JSON and CSV output generation
│       └── models.py              # Pydantic data models
└── tests/
    ├── __init__.py
    ├── test_ingest.py
    ├── test_classify.py
    └── test_models.py
```

### 2.2 Module Responsibilities

| Module | Responsibility |
|:---|:---|
| `models.py` | All Pydantic data models. Single source of truth for data shapes across the pipeline. The `RubricAnalysis` model doubles as the structured output schema for the Claude API call. |
| `config.py` | Loads `ANTHROPIC_API_KEY` from environment. Defines constants: model IDs, Whisper model size, duration bounds, filename regex, job types. |
| `cli.py` | Parses CLI arguments (`--input-dir`, `--output-dir`, `--rubric`). Validates paths. Hands control to `pipeline.py`. |
| `ingest.py` | Scans input directory for `.mp4` files. Validates filenames. Moves invalid files to `bad_name_conv/`. Checks `processed/` to skip already-processed files. Checks video duration via `ffprobe`. |
| `transcribe.py` | Extracts audio from MP4 via `ffmpeg` subprocess (to temp WAV). Transcribes using `faster-whisper` with the `base` model. Returns transcript text and metadata. |
| `analyze.py` | Builds the LLM prompt from transcript, rubric, job type, and interview questions. Calls `client.messages.parse()` with the `RubricAnalysis` Pydantic model for validated structured output. |
| `classify.py` | Pure logic, no I/O. Sums scores, checks gating criterion, checks hard-fail flags, applies decision thresholds. Returns recommendation and reason. |
| `output.py` | Writes per-candidate JSON files to the output directory. Writes batch CSV summary. |
| `pipeline.py` | Orchestrates the full flow: ingest → transcribe → analyze → classify → output. Processes candidates sequentially. Handles per-candidate errors so one failure never stops the batch. |

---

## 3. Data Flow

```
CLI parses args
│
▼
ingest.scan_input_dir(input_dir)
│── for each .mp4 file:
│   ├── validate filename regex ──► bad? move to bad_name_conv/
│   ├── already in processed/? ───► skip
│   ├── check duration via ffprobe ► warn if outside 2–10 min
│   └── yield CandidateFile(path, first_name, last_name, job_type, duration, warnings)
│
▼
for each CandidateFile:
│
├── transcribe.transcribe_video(path)
│   ├── ffmpeg: extract audio → temp .wav
│   ├── faster-whisper: transcribe .wav → text
│   └── return TranscriptResult(text, word_count, duration)
│       or TranscriptResult(failed=True) on error
│
├── if transcription failed:
│   └── mark "Needs Human Review", write output, continue
│
├── analyze.score_transcript(transcript, rubric, job_type)
│   ├── build prompt with job-type-specific interview questions
│   ├── call client.messages.parse(model, output_format=RubricAnalysis)
│   └── return RubricAnalysis (validated by Pydantic)
│
├── classify.classify_candidate(analysis)
│   ├── sum scores, check hard fails, check gating
│   └── return ClassificationResult(recommendation, reason)
│
├── output.write_candidate_json(candidate, transcript, analysis, classification)
│   └── write to output_dir/firstname-lastname-JOBTYPE.json
│
└── ingest.move_to_processed(path)
    └── move .mp4 to processed/
│
▼
output.write_batch_csv(all_results, output_dir)
└── write output_dir/batch_summary.csv
```

---

## 4. CLI Interface

```
interview-eval --input-dir <PATH> [--output-dir <PATH>] [--rubric <PATH>]
```

| Argument | Required | Default | Description |
|:---|:---|:---|:---|
| `--input-dir` | Yes | — | Directory containing `.mp4` interview files |
| `--output-dir` | No | `./output` | Directory for JSON and CSV output |
| `--rubric` | No | `./scoring_rubric.md` | Path to scoring rubric file |

The `pyproject.toml` defines a console script entry point so that after `pip install -e .`, the command `interview-eval` is available on PATH.

---

## 5. Input Specification

### 5.1 Video Files

- **Format:** MP4 only
- **Duration:** 2–10 minutes expected. Videos outside this range produce a warning in the output but are still processed.
- **Volume:** Maximum 10 per day

### 5.2 Filename Convention

**Pattern:** `firstname-lastname-JOBTYPE.mp4`

- `firstname`: lowercase alphabetic, e.g., `john`
- `lastname`: lowercase alphabetic, e.g., `doe`
- `JOBTYPE`: exactly `SME` or `QA` (uppercase)
- Separator: hyphen (`-`)

**Examples:**
- `john-doe-SME.mp4` ✓
- `jane-smith-QA.mp4` ✓
- `JohnDoe_SME.mp4` ✗ (wrong format → moved to `bad_name_conv/`)

**Validation regex:** `^[a-z]+-[a-z]+-(?:SME|QA)\.mp4$`

### 5.3 Directory Management

Given an input directory at `/path/to/interviews/`, the system manages two sibling directories:

```
/path/to/
├── interviews/        # input dir (user-specified)
├── processed/         # successfully processed .mp4 files moved here
└── bad_name_conv/     # files with invalid naming convention moved here
```

Both sibling directories are created automatically if they do not exist.

### 5.4 Interview Questions by Job Type

The system includes job-type-specific interview questions in the LLM prompt so it can evaluate instruction-following (Criterion 5) and contextualize scoring.

**SME (Subject Matter Expert) Questions:**

1. Tell us about a time you built or coordinated a CTE program or course beyond teaching it. What was your role at the program level, and how did you make sure it met its qualifying criteria, such as funding, articulation, or certification?
2. This is a generalist role across many CTE pathways. Describe one pathway you know deeply, and walk us through how you would come up to speed quickly to review a course in a pathway outside your expertise.
3. Imagine we hand you a drafted CTE course to review against its standards and its funding or certification requirements. What would you check, and how would you turn the gaps you find into clear, actionable revision direction for the writing team?

**QA (Curriculum QA Specialist) Questions:**

1. This role reviews every activity in a lesson for errors before it reaches a classroom. Walk us through how you would systematically review a single K-12 lesson. What kinds of errors would you look for, and how would you keep your process consistent across many lessons?
2. Tell us about your experience catching content or quality errors in educational or digital materials. Give a specific example of an error you caught and how you handled it.
3. When you find an issue, some you can fix yourself and some need to go to developers as a bug ticket. How do you decide which is which, and how do you write up an issue so that someone else can act on it without asking you questions?

---

## 6. Scoring Rubric

The system uses the rubric defined in `scoring_rubric.md`. Five criteria, each scored 1–4:

| # | Criterion | What It Measures |
|:--|:---|:---|
| 1 | **Role Fit and Relevant Experience** (gating) | Core bar for the role. CTE: program-level CTE work + compliance. QA: content/materials accuracy review. |
| 2 | **Domain Judgment** | CTE: standards, funding, articulation, certification. QA: instinct for spotting accuracy errors. |
| 3 | **Process and Methodology** | Structured, systematic approach |
| 4 | **Communication** | Clear, concise, organized delivery |
| 5 | **Instruction-Following and Professionalism** | Answered all three questions, on time, professional |

**Maximum score:** 20 points

### 6.1 Decision Rules

| Condition | Recommendation |
|:---|:---|
| Total ≥ 14 AND Criterion 1 ≥ 3 | **Advance** |
| Total 11–13 | **Hold** (Needs Human Review) |
| Total ≤ 10 | **Decline** |
| Any hard-fail flag triggered | **Decline** (regardless of total) |

### 6.2 Hard-Fail Conditions

Automatic decline regardless of total score if the candidate:

- Did not answer all three questions
- Has no experience meeting the role's core bar
- Cannot communicate clearly enough to follow

---

## 7. LLM Integration

### 7.1 Model

**Claude Sonnet 4.6** (`claude-sonnet-4-6`) via the Anthropic Python SDK.

### 7.2 API Usage

Uses `client.messages.parse()` with the `RubricAnalysis` Pydantic model as the `output_format` parameter. This:

- Auto-generates the JSON schema from the Pydantic model
- Validates the response against the schema automatically
- Eliminates manual JSON parsing and schema definition

### 7.3 Prompt Design

The prompt includes:

1. **System prompt:** Instructs Claude to act as a hiring evaluator, score strictly against the provided rubric, extract verbatim quotes as evidence, and flag any uncertainties.
2. **User message:** Contains the full transcript text, the complete rubric markdown, and the three interview questions for the candidate's job type.

### 7.4 Cost Estimate

A 5-minute interview transcript is ~2,000–3,500 tokens. With rubric (~600 tokens) and system prompt (~200 tokens), each call costs approximately $0.01–0.02 input + $0.05–0.10 output. At 10 videos/day: **under $1/day**.

---

## 8. Transcription

### 8.1 Engine

**faster-whisper** with the `base` model size, running on CPU.

- Free, local, no API dependency
- The `base` model provides good accuracy for clear interview audio
- At this volume (max 10 videos, 2–10 min each), CPU processing is practical (~1–2 min per video)

### 8.2 Audio Extraction

`ffmpeg` extracts audio from MP4 via subprocess:

```
ffmpeg -i input.mp4 -vn -ar 16000 -ac 1 -f wav output.wav
```

Video duration is checked with `ffprobe`:

```
ffprobe -v error -show_entries format=duration -of csv=p=0 input.mp4
```

### 8.3 System Requirement

FFmpeg must be installed and available on PATH.

---

## 9. Output Specification

### 9.1 Per-Candidate JSON

One JSON file per candidate, written to the output directory. Filename: `firstname-lastname-JOBTYPE.json`.

```json
{
  "candidate_id": "john-doe-SME",
  "first_name": "john",
  "last_name": "doe",
  "job_type": "SME",
  "evaluation_timestamp": "2026-06-21T14:30:00Z",

  "transcript_metadata": {
    "video_filename": "john-doe-SME.mp4",
    "video_duration_seconds": 420,
    "transcript_word_count": 1850,
    "duration_warning": null
  },

  "scores": {
    "role_fit_and_relevant_experience": {
      "score": 3,
      "quotes": ["I spent four years managing CTE programs..."],
      "rationale": "Clear, relevant experience that maps to the role."
    },
    "domain_judgment": {
      "score": 3,
      "quotes": ["We aligned our programs with state standards..."],
      "rationale": "Solid, specific understanding of CTE standards."
    },
    "process_and_methodology": {
      "score": 2,
      "quotes": ["I would start by reviewing the existing curriculum..."],
      "rationale": "Some structure shown but gaps remain in edge cases."
    },
    "communication": {
      "score": 3,
      "quotes": [],
      "rationale": "Clear and well organized throughout."
    },
    "instruction_following_and_professionalism": {
      "score": 3,
      "quotes": [],
      "rationale": "All three questions answered professionally."
    }
  },

  "total_score": 14,
  "recommendation": "Advance",
  "recommendation_reason": "Total score 14 meets threshold and Role Fit >= 3.",

  "hard_fail_flags": {
    "did_not_answer_all_questions": false,
    "lacks_core_experience": false,
    "cannot_communicate_clearly": false
  },

  "confidence_score": 0.82,
  "overall_summary": "Candidate demonstrates relevant CTE experience with solid domain knowledge. Process methodology shows room for growth. Communication is clear and professional.",

  "system_notes": {
    "model_used": "claude-sonnet-4-6",
    "rubric_version": "scoring_rubric.md",
    "pipeline_version": "0.1.0",
    "limitations": [
      "Transcription quality may affect scoring accuracy.",
      "Scores reflect rubric criteria only, not holistic assessment."
    ]
  }
}
```

### 9.2 Failed Transcription JSON

When transcription fails, the system still produces a JSON file with zero scores and a "Needs Human Review" recommendation:

```json
{
  "candidate_id": "jane-smith-QA",
  "first_name": "jane",
  "last_name": "smith",
  "job_type": "QA",
  "evaluation_timestamp": "2026-06-21T14:35:00Z",

  "transcript_metadata": {
    "video_filename": "jane-smith-QA.mp4",
    "video_duration_seconds": 300,
    "transcript_word_count": 0,
    "duration_warning": null
  },

  "scores": {
    "role_fit_and_relevant_experience": { "score": 0, "quotes": [], "rationale": "" },
    "domain_judgment": { "score": 0, "quotes": [], "rationale": "" },
    "process_and_methodology": { "score": 0, "quotes": [], "rationale": "" },
    "communication": { "score": 0, "quotes": [], "rationale": "" },
    "instruction_following_and_professionalism": { "score": 0, "quotes": [], "rationale": "" }
  },

  "total_score": 0,
  "recommendation": "Needs Human Review",
  "recommendation_reason": "Transcription failed. Manual review required.",

  "hard_fail_flags": {
    "did_not_answer_all_questions": false,
    "lacks_core_experience": false,
    "cannot_communicate_clearly": false
  },

  "confidence_score": 0.0,
  "overall_summary": "Transcription failed for this candidate. Manual review required.",

  "system_notes": {
    "model_used": "claude-sonnet-4-6",
    "rubric_version": "scoring_rubric.md",
    "pipeline_version": "0.1.0",
    "limitations": [
      "Transcription failed — no evaluation was performed."
    ]
  }
}
```

### 9.3 Batch CSV Summary

`batch_summary.csv` in the output directory. One row per candidate processed in the batch run.

| Column | Description |
|:---|:---|
| `candidate_id` | e.g., `john-doe-SME` |
| `first_name` | e.g., `john` |
| `last_name` | e.g., `doe` |
| `job_type` | `SME` or `QA` |
| `total_score` | Sum of 5 criteria (0–20) |
| `role_fit` | Criterion 1 score (0–4) |
| `domain_judgment` | Criterion 2 score (0–4) |
| `process` | Criterion 3 score (0–4) |
| `communication` | Criterion 4 score (0–4) |
| `instruction_following` | Criterion 5 score (0–4) |
| `recommendation` | `Advance`, `Hold`, `Decline`, or `Needs Human Review` |
| `confidence` | 0.0–1.0 |
| `hard_fail` | `true` if any hard-fail flag is set |
| `evaluation_timestamp` | ISO 8601 timestamp |

---

## 10. Error Handling

| Scenario | Action | Output |
|:---|:---|:---|
| Invalid filename | Move file to sibling `bad_name_conv/` directory | Print warning to stdout |
| Already processed | File exists in sibling `processed/` directory | Skip silently |
| Duration outside 2–10 min | Proceed with processing | Warning stored in JSON `transcript_metadata.duration_warning` |
| FFmpeg / audio extraction failure | Skip scoring for this candidate | JSON with zero scores, recommendation "Needs Human Review" |
| faster-whisper failure | Skip scoring for this candidate | JSON with zero scores, recommendation "Needs Human Review" |
| Claude API error (auth, rate limit, server) | SDK auto-retries (2x). If still fails, skip scoring | JSON with zero scores, recommendation "Needs Human Review" |
| Claude returns invalid structured output | Pydantic validation catches it | JSON with zero scores, recommendation "Needs Human Review" |
| Missing `ANTHROPIC_API_KEY` | Exit immediately at startup | Clear error message to stderr |
| Output directory doesn't exist | Create it automatically | — |

**Design principle:** A single-candidate failure never stops the batch. Each candidate is processed in its own try/except block. The batch CSV is always written, even if every candidate failed.

---

## 11. Tech Stack

| Component | Technology | Reason |
|:---|:---|:---|
| Language | Python 3.10+ | Ecosystem support for ML/AI tooling |
| Transcription | `faster-whisper` (base model) | Free, local, CPU-friendly, no API dependency |
| Audio extraction | `ffmpeg` (subprocess) | Industry standard, two simple commands |
| LLM | Claude Sonnet 4.6 via `anthropic` SDK | Structured output support, strong evaluation capability, cost-effective |
| Data models | `pydantic` | Validation, JSON schema generation, SDK integration |
| CLI | `argparse` (stdlib) | Simple, no extra dependency |
| CSV | `csv` (stdlib) | Simple, no extra dependency |

### 11.1 Python Dependencies

```
anthropic>=0.92.0
faster-whisper>=1.1.0
pydantic>=2.0
```

### 11.2 System Requirements

- Python 3.10+
- FFmpeg installed and on PATH

---

## 12. Setup Instructions

### 12.1 Install FFmpeg

**Windows (winget):**
```
winget install Gyan.FFmpeg
```

**Windows (chocolatey):**
```
choco install ffmpeg
```

**macOS:**
```
brew install ffmpeg
```

**Linux (Ubuntu/Debian):**
```
sudo apt install ffmpeg
```

Verify: `ffmpeg -version`

### 12.2 Install the Pipeline

```bash
git clone https://github.com/NitzanZacharia/interview-eval-pipeline.git
cd interview-eval-pipeline
pip install -e .
```

### 12.3 Set Your API Key

Get an API key from [console.anthropic.com](https://console.anthropic.com/).

**Option A — Environment variable:**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

**Option B — Shell profile (persistent):**
Add to `~/.bashrc`, `~/.zshrc`, or Windows environment variables:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 12.4 Run

```bash
interview-eval --input-dir ./interviews --output-dir ./results
```

---

## 13. Idempotency

The system is idempotent by design:

1. Before processing, each `.mp4` filename is checked against the sibling `processed/` directory.
2. If a file with the same name exists in `processed/`, the file is skipped.
3. After successful processing, the `.mp4` is moved from the input directory to `processed/`.
4. Re-running the CLI on the same input directory produces no duplicate output.

---

## 14. Limitations and Assumptions

- **Audio quality:** Transcription accuracy depends on recording quality. Poor audio may produce inaccurate transcripts and unreliable scores.
- **Language:** English only. The rubric and transcription are designed for English-language interviews.
- **Single speaker assumed:** The system transcribes the full audio as a single stream. Interviewer prompts in the recording may appear in the transcript.
- **No video analysis:** Only audio is extracted and evaluated. Visual cues (body language, presentation materials) are not assessed.
- **LLM scoring variability:** Scores may vary slightly between runs for the same transcript. The confidence score reflects the model's self-assessed certainty.
- **Rubric-only evaluation:** Scores reflect the rubric criteria only, not a holistic assessment of the candidate.
