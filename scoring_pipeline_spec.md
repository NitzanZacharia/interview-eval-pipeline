# NovoDia Scoring Pipeline — Technical Specification

## Overview

End-to-end automated pipeline that ingests candidate video submissions, transcribes them, scores them with Claude AI against a rubric, and writes the results back to Airtable — with no manual HR intervention required for the standard case.

---

## System Components

### 1. Gmail Watcher (`scripts/gmail_watcher.gs`)

A Google Apps Script that runs on a **5-minute time trigger** in the HR Gmail inbox (`nitzanzacharia@gmail.com`). It monitors for candidate replies to the video-request email and routes them to the Railway evaluation server.

#### Email Identification

Gmail search query:
```
subject:"Re: Next step in your NovoDia application: short video submission" is:unread newer_than:7d
```

Only the latest message in each matching thread is processed per run.

#### Sender Classification

Emails are classified into three categories:

| Sender | Classification | Action |
|:---|:---|:---|
| Non-@novodia.co address | Direct candidate reply | Process normally |
| @novodia.co with valid forwarded candidate payload | Valid forward | Extract candidate email from body; process |
| @novodia.co with no valid candidate payload (or forward From: is also @novodia.co) | Internal chatter | Mark read, skip |

#### Forward Detection Logic

When a teammate (`@novodia.co`) is the sender, the script parses the plain-text body to extract the original candidate's email using three ordered patterns:

**Pattern 1 — Gmail forward:**
```
---------- Forwarded message ---------
From: Candidate Name <candidate@email.com>
...
```
Regex: `/------+\s*Forwarded message\s*------+[\s\S]*?From:\s*([^\n]+)/i`

**Pattern 2 — Apple Mail / Outlook forward:**
```
Begin forwarded message:
From: Candidate Name <candidate@email.com>
...
```
Regex: `/Begin forwarded message:[\s\S]*?From:\s*([^\n]+)/i`

**Pattern 3 — Bare inline quote:**
```
On Jun 28, 2026, Candidate Name <candidate@email.com> wrote:
```
Regex: `/On\s+[^\n]+?,\s+([^\n]+?)\s+wrote:/i`

From each matched `From:` line, the email address is extracted (angle-bracket format preferred; bare `@` pattern as fallback). If the extracted email ends in `@novodia.co`, the message is treated as internal chatter and skipped.

#### Path A — Video Submission (MP4 or YouTube)

1. **MP4 attachment**: Upload to Google Drive folder `1GzhsnpTYcGZsiKoDx9ID0UwOkF4ZSrES`, set public link, POST to `/ingest` with `source_type: "gdrive"`.
2. **YouTube link** (detected via regex in body): POST to `/ingest` with `source_type: "youtube"`.

`msg.getAttachments()` returns forwarded attachments at the message level — no special handling needed for forwards.

#### Path B — Text-Only Reply (No Video)

1. PATCH the Candidate Submission record: `Review Needed = true`
2. Send notification email to `lily.nir@novodia.co` with sender email + reply text snippet (first 1000 chars)
3. Mark email as read

Auto-resume: the script processes any later reply with a video from the same sender regardless of the `Review Needed` flag state.

#### Airtable Record Lookup (Two-Step)

1. **Find Application**: GET Applications table (`tblEsA1ZVdJdRLbs1`) filtered by `{Email}="<candidateEmail>"` → returns Application record ID.
2. **Find Submission**: GET Submissions table (`tblAjBCyfful0jay0`) filtered by `{Score 1}=""`, with `returnFieldsByFieldId=true`; iterate records client-side to find one where `fields["fldYAiyp0ILBXGuiQ"]` (Application link field) contains the Application record ID.

Client-side ID matching is used because Airtable's `filterByFormula` engine evaluates linked-record fields as primary-field display text, not record IDs.

#### Configuration

Stored in GAS Script Properties (never hardcoded):
- `AIRTABLE_TOKEN` — Airtable Personal Access Token
- `WEBHOOK_SECRET` — shared secret for Railway `/ingest` `X-Webhook-Secret` header

Constants in script:
- `AIRTABLE_BASE_ID = "app2HZvbePXlH9xLX"`
- `APPLICATIONS_TABLE_ID = "tblEsA1ZVdJdRLbs1"`
- `SUBMISSIONS_TABLE_ID = "tblAjBCyfful0jay0"`
- `TEAM_DOMAIN = "@novodia.co"`
- `DRIVE_FOLDER_ID = "1GzhsnpTYcGZsiKoDx9ID0UwOkF4ZSrES"`
- `HR_NOTIFICATION_EMAIL = "lily.nir@novodia.co"`
- `RAILWAY_INGEST_URL = "https://airtableintegration-production.up.railway.app/ingest"`
- `REPLY_SUBJECT = "Re: Next step in your NovoDia application: short video submission"`

---

### 2. Railway FastAPI Server (`src/interview_eval/server.py`)

Hosted at `https://airtableintegration-production.up.railway.app`. Two evaluation entry points:

#### `POST /evaluate`

Triggered by Airtable Automation when a video file is attached directly to a Candidate Submission record (all scores empty + Recommendation empty). Downloads video from Airtable's Files field attachment.

#### `POST /ingest`

Triggered by the GAS email watcher. Accepts a pre-located video source:

```json
{
  "record_id": "recXXXXXX",
  "source_type": "gdrive" | "youtube",
  "source_url": "https://...",
  "filename": "candidate.mp4"   // optional
}
```

Authentication: `X-Webhook-Secret` header matched against `WEBHOOK_SECRET` env var.

Both endpoints return **202 Accepted immediately** and run the pipeline as a background task.

#### Duplicate Guard

`_run_ingest` checks `fields["fldPHxOA56TRIsEXq"]` (Score 1) before processing. If already scored, the run is skipped.

#### Video Download

- `source_type = "youtube"`: downloaded with `yt-dlp`, best available MP4 format.
- `source_type = "gdrive"`: streamed via `requests.get` with 300-second timeout.

Known limitation: Google Drive's `uc?export=download` URL shows a virus-scan confirmation page for files over ~25 MB. If this becomes an issue, candidates should be instructed to keep submissions under 5 minutes.

#### `GET /health`

Uptime check, returns `{"status": "ok"}`.

---

### 3. Evaluation Pipeline (`src/interview_eval/airtable_pipeline.py`)

`process_record()` orchestrates five steps:

1. **Video source** — if `video_path` param is provided (email ingest path), uses it directly via `build_candidate_file_from_path()`. Otherwise downloads from Airtable Files attachment.
2. **Rubric** — fetches from linked Airtable Rubric record; falls back to local `scoring_rubric.md`.
3. **Transcription** — faster-whisper (`base` model, 74 MB); configurable via `WHISPER_MODEL_SIZE` env var.
4. **Scoring** — Claude (`claude-sonnet-4-6`) with structured output (`RubricAnalysis`), temperature 0.
5. **Write-back** — PATCHes Score 1–5, Recommendation, Notes; advances Application Stage.

---

## Airtable Schema Reference

### Base: Process Management (`app2HZvbePXlH9xLX`)

| Table | ID |
|:---|:---|
| Candidate Submissions | `tblAjBCyfful0jay0` |
| Applications | `tblEsA1ZVdJdRLbs1` |
| Rubric | `tblt1hU6iW6dKsLkO` |

### Candidate Submissions — Key Fields

| Field | ID | Notes |
|:---|:---|:---|
| Files | `fldqc8EyRmXqogYTm` | MP4 attachment |
| Application (link) | `fldYAiyp0ILBXGuiQ` | Links to Applications table |
| Score 1–5 | `fldPHxOA56TRIsEXq` … | Populated by pipeline |
| Recommendation | `fldKC0LCVpzpv1Z1P` | singleSelect |
| Notes | `fldYtJUdvm7R2e6KN` | Overall summary text |
| Review Needed | *(checkbox, add manually)* | Set by GAS on Path B |

### Applications — Key Fields

| Field | Display Name | Notes |
|:---|:---|:---|
| Email | `Email` | Used for candidate lookup by GAS |
| Stage | `fldLdOo2ZFgu8iaV5` | Advanced by pipeline write-back |

### Recommendation Mapping

| Pipeline Label | Airtable Value | Application Stage |
|:---|:---|:---|
| Strong Advance | Strong hire | First Interview |
| Advance | Hire | First Interview |
| Hold | Lean no | Hold |
| Decline | Strong no | Discontinued |
| Needs Human Review | *(skipped)* | *(unchanged)* |

---

## Airtable Automation (Existing)

Trigger: record updated in Candidate Submissions where:
- `Files` not empty
- `Recommendation` empty
- `Score 1` through `Score 5` all empty

Action: JavaScript script POSTs to `/evaluate` with the record ID and `X-Webhook-Secret` header.

---

## Environment Variables (Railway)

| Variable | Required | Description |
|:---|:---|:---|
| `AIRTABLE_TOKEN` | Yes | PAT with `data.records:read/write`, `schema.bases:read` |
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `WEBHOOK_SECRET` | Yes | Shared secret (also in GAS Script Properties) |
| `WHISPER_MODEL_SIZE` | No | `base` (default, 74 MB) or `small` (483 MB) |
| `RUBRIC_PATH` | No | Path to `scoring_rubric.md` (default: repo root) |
| `OUTPUT_DIR` | No | Local output dir (default: `/tmp/eval_output`) |

---

## Known Limitations

1. **Google Drive large-file download**: The `uc?export=download` URL shows a confirmation page for files >25 MB; Railway will receive HTML instead of the video. Mitigate by instructing candidates to keep submissions short.
2. **Nested forwards**: `msg.getAttachments()` only returns attachments from the outermost email. A forward of a forward will not surface the original attachment; the record will be flagged for human review (safe default).
3. **Pattern 3 false positive**: The bare "On ... wrote:" pattern could match a candidate quoting the original NovoDia email. The `@novodia.co` rejection and Airtable lookup failure together ensure this is handled safely.
4. **Whisper disk space**: `base` model = 74 MB; Railway volume must have at least 100 MB free. Partial failed downloads from previous `small` model attempts may consume space — clean via `railway ssh → rm -rf ~/.cache/huggingface/hub/models--Systran--faster-whisper-small`.
