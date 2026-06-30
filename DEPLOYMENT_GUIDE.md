# Production Deployment Guide

Step-by-step checklist for migrating the interview evaluation pipeline from the Airtable Sandbox environment to production, including switching Google accounts and Railway environment variables.

---

## Architecture Overview

```
Candidate email reply
        │
        ▼
 Gmail (HR inbox)
        │
  [GAS: gmail_watcher.gs]  ◄── runs every 5 min
        │  (uploads MP4 to Drive or passes YouTube URL)
        ▼
Railway server  ◄── POST /ingest
        │
        │   ──────────────────────────────────────────────
        │   Parallel path: HR attaches video directly in Airtable
        │                     │
        │              [Airtable Automation]
        │                     │
        │          ◄── POST /evaluate ──────────────
        │
        ▼
  Whisper transcription
        │
        ▼
  Claude scoring (scoring_rubric_QA.md / scoring_rubric_SME.md)
        │
        ▼
  Airtable write-back (Scores, Recommendation, Stage, Candidates table)
```

Three shared secrets must be consistent across all components:
- **`AIRTABLE_TOKEN`** — same PAT used by Railway server, GAS script, and CLI
- **`WEBHOOK_SECRET`** — same value in Railway env vars and GAS Script Properties
- **Airtable Base ID + Table/Field IDs** — hardcoded in `airtable_ingest.py` and `gmail_watcher.gs`; both must point to the same base

---

## Prerequisites

Before starting, have the following ready:

- [ ] Access to the production Airtable base (you need to be a base owner or admin)
- [ ] A production Airtable Personal Access Token (PAT) with scopes: `data.records:read`, `data.records:write`, `schema.bases:read`
- [ ] A production Anthropic API key
- [ ] A Railway account with the `Airtable_integration` service already created (or create a new one)
- [ ] The production Google Workspace account (HR inbox) that will run the GAS script
- [ ] A Google Drive folder in that account to store uploaded candidate videos
- [ ] Railway CLI installed: `npm install -g @railway/cli` and `railway login`

---

## Phase 1 — Airtable Production Base

### 1.1 Identify or create the production base

- [ ] Log in to Airtable and open the production base.
- [ ] Note the **Base ID** from the URL: `https://airtable.com/appXXXXXXXXXXXXXX/...` — the `appXXXXXXXXXXXXXX` segment is the Base ID.

### 1.2 Verify required tables exist

The pipeline writes to three tables. Confirm each exists in the production base:

| Purpose | Expected table name | Notes |
|:---|:---|:---|
| Candidate Submissions | `Candidate Submissions` | Primary scoring target — where videos and scores live |
| Applications | `Applications` | Linked from Submissions; pipeline updates the Stage field |
| Candidates | `Candidates` | Linked from Applications; pipeline sets Recommendations on Decline |

### 1.3 Verify required fields exist in Candidate Submissions

The pipeline reads and writes these fields by field ID. After pointing the code at the production base, verify each field is present and the right type:

| Field name | Type | Direction |
|:---|:---|:---|
| Files | multipleAttachments | Read (video source) |
| Round type | singleSelect | Read (filter: "Video Submission") |
| Score 1 – Score 5 | number | Write |
| Recommendation | singleSelect | Write |
| Notes | multilineText | Write (AI summary) |
| Application | multipleRecordLinks → Applications | Read (for stage update) |
| Review Needed | checkbox | Write |
| **Model output** | **multipleAttachments** | **Write (HTML evaluation report)** |

### 1.4 Verify required singleSelect option names

Airtable write-back uses **display name strings**, not choice IDs. The following names must exist exactly as shown (case-sensitive):

**Candidate Submissions → Recommendation field:**
- `Strong hire`
- `Hire`
- `Lean no`
- `Strong no`

**Applications → Stage field:**
- `First Interview`
- `TBD`
- `Discontinued`

**Candidates → Recommendations field:**
- `Discontinue`

**Candidate Submissions → Round type field:**
- `Video Submission`

### 1.5 Create the "Model output" field in the production Candidate Submissions table

The pipeline uploads the HTML evaluation report as an attachment after every scoring run. This field does **not** exist by default — you must create it manually in the production base.

- [ ] Open the **Candidate Submissions** table in the production base
- [ ] Add a new field: **Name** → `Model output` | **Type** → `Attachments`
- [ ] After creating the field, retrieve its field ID:
  - Option A: Use the Airtable REST API — `GET https://api.airtable.com/v0/meta/bases/{baseId}/tables` and find the `id` of the `Model output` field in the `Candidate Submissions` table
  - Option B: Open the field's context menu → **Copy field ID**
- [ ] In `src/interview_eval/airtable_ingest.py`, update the constant:

```python
F_MODEL_OUTPUT = "fld_PRODUCTION_FIELD_ID_HERE"   # multipleAttachments — HTML evaluation report
```

The upload itself uses this endpoint (no other change needed):
```
POST https://content.airtable.com/v0/{AIRTABLE_BASE_ID}/{recordId}/{F_MODEL_OUTPUT}/uploadAttachment
```
`AIRTABLE_BASE_ID` is already updated in step 1.5 below, so only `F_MODEL_OUTPUT` needs to change here.

> **Note:** The sandbox field ID (`fldd9rSej4iiNFlwe`) will not exist in the production base. Using the sandbox ID in production will cause 404 errors on every upload. This is the **only** field ID that differs between sandbox and production (all others are identical because the sandbox was duplicated from production before this field was added).

### 1.5 Update `AIRTABLE_BASE_ID` in the code

The sandbox was duplicated from production, so **all table IDs (`tbl...`) and field IDs (`fld...`) are identical between both bases**. The only value that differs is the Base ID itself.

Make this single change in `src/interview_eval/airtable_ingest.py`:

```python
# Change this line from the sandbox Base ID to the production Base ID:
AIRTABLE_BASE_ID = "app_PRODUCTION_BASE_ID_HERE"
```

The production Base ID is in the URL when you open the production base:
`https://airtable.com/appXXXXXXXXXXXXXX/...` — the `appXXX...` segment is the Base ID.

No other constants in `airtable_ingest.py` need to change.

### 1.6 Set up the Airtable Automation (Trigger 1)

In the production base, create a new Automation:

- **Trigger:** When a record is updated
  - Condition: Files is not empty AND filenames contains `mp4`
  - Condition: Recommendation is empty
  - Condition: Score 1 is empty, Score 2 is empty, Score 3 is empty, Score 4 is empty, Score 5 is empty
- **Action:** Run a script

Paste the script from the `### Trigger 1` section of README.md, updating the Railway URL to your production server URL.

Add input variables:
- `record_id` → Triggering record's Record ID
- `webhook_secret` → store as a **secret** (not a plain input) — use the production `WEBHOOK_SECRET` value

### 1.7 Generate a new Airtable Personal Access Token

- [ ] In Airtable: account icon → **Developer Hub** → **Personal access tokens** → **Create token**
- [ ] Name it (e.g., `interview-eval-prod`)
- [ ] Scopes: `data.records:read`, `data.records:write`, `schema.bases:read`
- [ ] Scope to: production base only
- [ ] Copy and store the token — it is shown only once

---

## Phase 2 — Google Apps Script (GAS) Email Watcher

### 2.1 Create a new GAS project on the production Google account

- [ ] Sign in to the **production HR Google account** (the inbox that receives candidate replies)
- [ ] Go to [script.google.com](https://script.google.com) → **New project**
- [ ] Name it `interview-eval-email-watcher` (or similar)
- [ ] Paste the full contents of `scripts/gmail_watcher.gs`

### 2.2 Update the configuration block

At the top of `gmail_watcher.gs`, update these variables:

```javascript
// ── Airtable identifiers ─────────────────────────────────────
var AIRTABLE_BASE_ID        = "app_PRODUCTION_BASE_ID_HERE";
var APPLICATIONS_TABLE_ID   = "tbl_APPLICATIONS_TABLE_ID";
var SUBMISSIONS_TABLE_ID    = "tbl_SUBMISSIONS_TABLE_ID";

// Field IDs on Submissions table (must match airtable_ingest.py)
var SUBMISSION_APPLICATION_FIELD_ID = "fld...";   // Application link field
var SUBMISSION_SCORE1_FIELD_ID      = "fld...";   // Score 1 field

// ── Railway server ────────────────────────────────────────────
var RAILWAY_INGEST_URL = "https://YOUR-PRODUCTION-URL.up.railway.app/ingest";

// ── Drive folder ──────────────────────────────────────────────
// Create a new folder in the production Google Drive account.
// Share it: anyone with the link can view. Copy the folder ID from the URL.
var DRIVE_FOLDER_ID = "YOUR_PRODUCTION_DRIVE_FOLDER_ID";

// ── HR notifications ──────────────────────────────────────────
var HR_NOTIFICATION_EMAIL = "hr@yourcompany.com";   // production HR email

// ── Email domain ──────────────────────────────────────────────
var TEAM_DOMAIN = "@yourcompany.com";   // used to distinguish forwarded replies from internal chatter

// ── Candidate reply email subject ────────────────────────────
// Must match the subject line of the video-request email you send to candidates.
var REPLY_SUBJECT = "Next step in your NovoDia application: short video submission";
```

### 2.3 Add Script Properties (secrets)

**File > Project Settings > Script Properties** → add:

| Property | Value |
|:---|:---|
| `AIRTABLE_TOKEN` | Production Airtable PAT from Phase 1.7 |
| `WEBHOOK_SECRET` | Production webhook secret (must match Railway env var) |

> These are stored securely inside the Apps Script project and never visible in the code.

### 2.4 Authorize OAuth permissions

- [ ] Click **Run** → `checkVideoReplies` (or any function) — this triggers the OAuth consent screen
- [ ] Grant permissions for **Gmail** (read/send) and **Google Drive** (create files)
- [ ] If the consent screen says "This app isn't verified", click **Advanced** → **Go to (project name)**

### 2.5 Create the time-driven trigger

- [ ] In the Apps Script editor, run `createTimeTrigger()` **once manually**
- [ ] Verify in **Triggers** (clock icon in the left panel) that `checkVideoReplies` appears with a 5-minute interval
- [ ] Do NOT run `createTimeTrigger()` again — it creates a duplicate trigger each time

### 2.6 Verify the watcher is working

- [ ] Send a test email to the HR inbox with subject matching `REPLY_SUBJECT` and an MP4 attachment
- [ ] Wait up to 5 minutes for the trigger to fire
- [ ] Check **Executions** (in Apps Script) for a successful run and console output
- [ ] Confirm the Submission record in Airtable received scores

---

## Phase 3 — Railway Server

### 3.1 Set production environment variables

```bash
railway variables set AIRTABLE_TOKEN="pat_PRODUCTION_TOKEN"
railway variables set ANTHROPIC_API_KEY="sk-ant-PRODUCTION_KEY"
railway variables set WEBHOOK_SECRET="GENERATE_A_RANDOM_32_CHAR_STRING"
```

Optional (leave unset to use defaults):
```bash
railway variables set WHISPER_MODEL_SIZE="base"   # or "small" for better accuracy
railway variables set OUTPUT_DIR="/tmp/eval_output"
```

> **Generating a webhook secret:** `python -c "import secrets; print(secrets.token_hex(32))"`

### 3.2 Deploy

```bash
railway up --service Airtable_integration
```

Or push to the linked Git branch — Railway auto-deploys on push if configured.

### 3.3 Verify the server is healthy

```bash
curl https://YOUR-PRODUCTION-URL.up.railway.app/health
# Expected: {"status":"ok"}
```

### 3.4 Test the `/evaluate` endpoint

```bash
curl -X POST https://YOUR-PRODUCTION-URL.up.railway.app/evaluate \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: YOUR_WEBHOOK_SECRET" \
  -d '{"record_id": "recXXXXXXXXXXXXXX"}'
# Expected: 202 {"status":"accepted","record_id":"..."}
```

---

## Phase 4 — End-to-End Verification

Run through this checklist after completing Phases 1–3:

- [ ] **Airtable Automation path:** Manually attach a test MP4 to a Candidate Submission record in production. Within 3–5 minutes, Score 1–5, Recommendation, and Stage should be populated.
- [ ] **GAS email path:** Send a test reply email with an MP4 to the HR inbox. Within 5 minutes, the video should appear in the Drive folder and scores should populate in Airtable.
- [ ] **Decline path:** For a Decline result, verify the linked Candidates record has `Recommendations = Discontinue`.
- [ ] **Needs Human Review path:** For a record flagged for human review, verify `Review Needed` is checked in Airtable and HR receives a notification email.
- [ ] **Health check:** Confirm `GET /health` returns `{"status":"ok"}`.

---

## Environment Variables Reference

Complete list of all credentials that differ between Sandbox and Production:

### Railway server

| Variable | Sandbox value | Production action |
|:---|:---|:---|
| `AIRTABLE_TOKEN` | Sandbox PAT | Replace with production PAT (Phase 1.7) |
| `ANTHROPIC_API_KEY` | Shared or test key | Use production key |
| `WEBHOOK_SECRET` | Sandbox secret | Generate a new random string |
| `WHISPER_MODEL_SIZE` | `base` | Keep or change to `small` for accuracy |

### GAS Script Properties

| Property | Production value |
|:---|:---|
| `AIRTABLE_TOKEN` | Same production PAT as Railway |
| `WEBHOOK_SECRET` | Same production `WEBHOOK_SECRET` as Railway |

### Code constants that need updating (requires redeploy)

Most table IDs and field IDs are identical between sandbox and production (sandbox was duplicated from production). The exceptions are the Base ID and the `Model output` field ID, which was added to the sandbox after the duplication:

| File | Variable | Change |
|:---|:---|:---|
| `src/interview_eval/airtable_ingest.py` | `AIRTABLE_BASE_ID` | Production Base ID |
| `src/interview_eval/airtable_ingest.py` | `F_MODEL_OUTPUT` | Field ID of the `Model output` column in the production base (created in step 1.5) |
| `scripts/gmail_watcher.gs` | `AIRTABLE_BASE_ID` | Same production Base ID |
| `scripts/gmail_watcher.gs` | `DRIVE_FOLDER_ID` | Production Google Drive folder ID |
| `scripts/gmail_watcher.gs` | `HR_NOTIFICATION_EMAIL` | Production HR email address |
| `scripts/gmail_watcher.gs` | `TEAM_DOMAIN` | Production company email domain |
| `scripts/gmail_watcher.gs` | `RAILWAY_INGEST_URL` | Production Railway server URL |

---

## Rollback Plan

If production issues arise:

1. **Server rollback:** In Railway dashboard, select the previous successful deployment and click **Redeploy**.
2. **GAS rollback:** In Apps Script editor → **Project history** → restore the previous version.
3. **Airtable rollback:** Disable the Automation in the production base — this stops the `/evaluate` trigger. The GAS email watcher can be paused by deleting its trigger in **Triggers**.
4. **Code rollback:** `git revert` the offending commit and `railway up`.

To test a rollback scenario without affecting production: use `--dry-run` with the CLI script, or temporarily point `AIRTABLE_BASE_ID` in a local `.env` back to the sandbox base ID.
