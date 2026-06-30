"""
src/interview_eval/airtable_ingest.py

Read-only Airtable ingestion layer.
Replaces scan_input_dir() for the Airtable-driven pipeline.

Requires an Airtable Personal Access Token with:
  - data.records:read
  - data.records:write
  - schema.bases:read

Environment variable: AIRTABLE_TOKEN
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Optional

import requests

from .ingest import get_video_duration
from .models import CandidateFile, CandidateResult
from . import config

# ---------------------------------------------------------------------------
# Base / table constants (confirmed from live schema exploration)
# ---------------------------------------------------------------------------
AIRTABLE_BASE_ID  = "app2HZvbePXlH9xLX"
SUBMISSIONS_TABLE = "tblAjBCyfful0jay0"
RUBRIC_TABLE      = "tblt1hU6iW6dKsLkO"
AIRTABLE_API_BASE = "https://api.airtable.com/v0"

# ---------------------------------------------------------------------------
# Candidate Submissions field IDs
# ---------------------------------------------------------------------------
F_SUBMISSION_NAME = "fldDn1kGnhYp9QTfa"   # formula (primary key label)
F_ROUND_TYPE      = "fldMowMIcpaxlxsor"   # singleSelect
F_FILES           = "fldqc8EyRmXqogYTm"   # multipleAttachments — video lives here
F_CANDIDATE_NAME  = "fldIULihwWP4KmQKm"   # multipleLookupValues
F_APPLICATION     = "fldYAiyp0ILBXGuiQ"   # multipleRecordLinks
F_RUBRIC_LINK     = "fldQ6e4ARmWjasS7z"   # multipleRecordLinks → Rubric table
F_SCORE_1         = "fldPHxOA56TRIsEXq"   # number — used to detect unscored records
F_SCORE_2         = "fldr4ptlsQrynyMVT"   # number
F_SCORE_3         = "flda1iZ43luzWo58q"   # number
F_SCORE_4         = "flddiNitZN15QQlkS"   # number
F_SCORE_5         = "fldR7xFsNNmyJp45d"   # number
F_RECOMMENDATION  = "fldKC0LCVpzpv1Z1P"   # singleSelect
F_NOTES           = "fldYtJUdvm7R2e6KN"   # multilineText
F_MODEL_OUTPUT    = "fldd9rSej4iiNFlwe"   # multipleAttachments — HTML evaluation report
# F_WEIGHTED_SCORE = "fldWy8zzT16FIt2Pz"  — formula field, auto-calculated; do not write

# Airtable singleSelect names differ from pipeline labels — map at write time.
# "Needs Human Review" has no Airtable equivalent; skip the field in that case.
_RECOMMENDATION_MAP: dict[str, str | None] = {
    "Strong Advance":      "Strong hire",
    "Advance":             "Hire",
    "Hold":                "Lean no",
    "Decline":             "Strong no",
    "Needs Human Review":  None,
}

# ---------------------------------------------------------------------------
# Applications table — stage advancement
# ---------------------------------------------------------------------------
APPLICATIONS_TABLE = "tblEsA1ZVdJdRLbs1"
F_STAGE            = "fldLdOo2ZFgu8iaV5"   # singleSelect in Applications

# Maps pipeline recommendation labels to Applications Stage choice names.
# None = no stage movement (leave the current stage unchanged).
_STAGE_MAP: dict[str, str | None] = {
    "Strong Advance":     "First Interview",
    "Advance":            "First Interview",
    "Hold":               "TBD",
    "Decline":            "Discontinued",
    "Needs Human Review": None,
}

# ---------------------------------------------------------------------------
# Candidates table — recommendation update on decline
# ---------------------------------------------------------------------------
CANDIDATES_TABLE           = "tblGmwHWlWoEPnTfA"
F_CANDIDATES_LINK          = "fldQMED2ek5EJCTFD"   # On Applications: links → Candidates table
F_CANDIDATE_RECOMMENDATION = "fld7kwtOwLCby2vtp"   # On Candidates: Recommendations singleSelect

# Round type singleSelect option IDs (confirmed from live data)
ROUND_VIDEO_SUBMISSION  = "sel11RPB63d9K0hFG"
ROUND_PRACTICAL_TASK    = "selleUvcssoa4WCXs"
ROUND_MICRO_DEMO        = "sel6zR8MPOWY3rM7v"
ROUND_QA_NEUTRAL        = "sel5SyqoMqZhxtXGr"

# ---------------------------------------------------------------------------
# Rubric table field IDs
# ---------------------------------------------------------------------------
F_RUBRIC_NAME       = "fldHiXGCAYNLjw9Z8"
F_CRITERION_1       = "fldVvpbMNMthzLoUG"
F_CRITERION_2       = "fldAwcAmWCP2Kyb9V"
F_CRITERION_3       = "fldFmG2yJJqDl5AOx"
F_CRITERION_4       = "fldv2ila1djNoMtvx"
F_CRITERION_5       = "fldcbFBcOkZ7p8Xzj"
F_WEIGHT_1          = "fldB5zVKKwBz3CX4B"
F_WEIGHT_2          = "fldLHsiodYNfb1MRj"
F_WEIGHT_3          = "fldr2ATD0qU40A4IO"
F_WEIGHT_4          = "fldmvQiVSZQwBIHUr"
F_WEIGHT_5          = "fldFpLBJTyWxE36HZ"
F_PASSING_THRESHOLD = "fldfKyXGXJLTdEJlB"
F_HARD_FAIL_RULES   = "fld9dtMu2Rj5vN41o"   # multipleSelects


# ---------------------------------------------------------------------------
# Internal HTTP helpers
# ---------------------------------------------------------------------------

def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _get(url: str, params: dict, api_key: str, retries: int = 3) -> dict:
    """GET with exponential back-off on 429 (rate limit)."""
    params = {**params, "returnFieldsByFieldId": "true"}
    for attempt in range(retries):
        resp = requests.get(url, headers=_headers(api_key), params=params, timeout=30)
        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"  [airtable_ingest] Rate limited — waiting {wait}s before retry...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()  # re-raise on the final attempt
    return {}  # unreachable; keeps type-checker happy


def _patch(url: str, payload: dict, api_key: str, retries: int = 3) -> dict:
    """PATCH with exponential back-off on 429 (rate limit)."""
    for attempt in range(retries):
        resp = requests.patch(url, headers=_headers(api_key), json=payload, timeout=30)
        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"  [airtable_ingest] Rate limited — waiting {wait}s before retry...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()
    return {}  # unreachable; keeps type-checker happy


# ---------------------------------------------------------------------------
# Public: fetch unscored Video Submission records
# ---------------------------------------------------------------------------

def fetch_unscored_video_submissions(api_key: str) -> list[dict]:
    """
    Return all Candidate Submission records where:
      - Round type  == "Video Submission"
      - Files field is not empty (there is an attachment)
      - Score 1 is blank (not yet processed by the pipeline)

    Uses Airtable's filterByFormula with full pagination (offset loop).
    Only fetches the fields the caller actually needs.
    """
    url = f"{AIRTABLE_API_BASE}/{AIRTABLE_BASE_ID}/{SUBMISSIONS_TABLE}"

    # Airtable formula syntax — quotes inside single-quoted formula string
    formula = (
        "AND("
        "{Round type}=\"Video Submission\","
        "{Files}!=\"\","
        "{Score 1}=\"\""
        ")"
    )

    fields_to_fetch = [
        F_SUBMISSION_NAME,
        F_ROUND_TYPE,
        F_FILES,
        F_CANDIDATE_NAME,
        F_APPLICATION,
        F_RUBRIC_LINK,
        F_SCORE_1,
    ]

    records: list[dict] = []
    offset: Optional[str] = None

    while True:
        params: dict = {
            "filterByFormula": formula,
            "fields[]": fields_to_fetch,
            "pageSize": 100,
        }
        if offset:
            params["offset"] = offset

        data = _get(url, params, api_key)
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break

    return records


def fetch_single_record(record_id: str, api_key: str) -> dict:
    """
    Fetch a single Candidate Submission record by its Airtable record ID.
    Used by the webhook path (Phase 2) but safe to call read-only.
    """
    url = f"{AIRTABLE_API_BASE}/{AIRTABLE_BASE_ID}/{SUBMISSIONS_TABLE}/{record_id}"
    return _get(url, {}, api_key)


# ---------------------------------------------------------------------------
# Public: download video to local disk
# ---------------------------------------------------------------------------

def download_video(attachment: dict, dest_dir: Path) -> Path:
    """
    Download one Airtable attachment to dest_dir.

    The signed URL in attachment["url"] is time-limited (a few hours).
    Call this immediately after fetching the record — do not cache the URL.

    Returns the local Path of the downloaded file.
    Raises requests.HTTPError on download failure.
    """
    signed_url = attachment["url"]
    filename   = attachment.get("filename", "video.mp4")
    dest_path  = dest_dir / filename

    with requests.get(signed_url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with dest_path.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=65_536):
                fh.write(chunk)

    return dest_path


# ---------------------------------------------------------------------------
# Internal: parse identity fields from Airtable lookups
# ---------------------------------------------------------------------------

def _parse_name(candidate_name_values: list) -> tuple[str, str]:
    """
    candidate_name_values is a multipleLookupValues list, e.g.:
      ["Emily Kobelenz-DiRienzo - QA Specialist"]

    Parses first_name and last_name from the first entry.
    Strips everything after the first " - " separator (that is the role title).
    Then lowercases and removes any character that is not a-z so the result
    satisfies the filename regex ^[a-z]+-[a-z]+-(?:SME|QA).mp4$.

    Hyphenated surnames like "Kobelenz-DiRienzo" are treated as a single last
    name token; non-alpha characters are stripped to produce "kobelenzdirienzo".
    """
    if not candidate_name_values:
        return "unknown", "unknown"

    raw: str = str(candidate_name_values[0])
    # Everything before the first " - " is the human name
    name_part = raw.split(" - ")[0].strip()   # e.g. "Emily Kobelenz-DiRienzo"
    # Split on whitespace only — keeps hyphenated surnames intact as one token
    parts = name_part.split()

    if not parts:
        return "unknown", "unknown"

    first = re.sub(r"[^a-z]", "", parts[0].lower())
    # Last is the final whitespace-delimited token (handles "First Last" and
    # single-word names like "Madonna" by falling back to parts[0])
    last_raw = parts[-1] if len(parts) > 1 else parts[0]
    last = re.sub(r"[^a-z]", "", last_raw.lower())

    # Guard against empty strings after stripping (e.g. all-numeric input)
    first = first or "unknown"
    last  = last  or "unknown"
    return first, last


def _derive_job_type(candidate_name_values: list) -> str:
    """
    Derive job_type from the role text embedded in the Candidate Name lookup.
    Rules:
      - Contains "QA" or "Quality" → "QA"
      - Everything else            → "SME"
    """
    combined = " ".join(str(v) for v in candidate_name_values)
    if "QA" in combined or "Quality" in combined:
        return "QA"
    return "SME"


# ---------------------------------------------------------------------------
# Public: convert a raw Airtable record into a CandidateFile
# ---------------------------------------------------------------------------

def airtable_record_to_candidate_file(
    record: dict,
    download_dir: Path,
) -> Optional[tuple[CandidateFile, str]]:
    """
    Given a raw Airtable record dict and a writable local directory:
      1. Selects the first video attachment from the Files field.
      2. Downloads it to download_dir.
      3. Runs ffprobe on the downloaded file (reusing get_video_duration).
      4. Builds and returns a CandidateFile plus the Airtable record ID.

    Returns None if the record cannot be processed (no attachment, download
    failure, etc.), so callers can skip gracefully without crashing the batch.
    """
    fields    = record.get("fields", {})
    record_id = record["id"]

    # ── 1. Find a video attachment ──────────────────────────────────────────
    attachments: list[dict] = fields.get(F_FILES, [])
    if not attachments:
        print(f"  [airtable_ingest] Record {record_id} has no attachments — skipping.")
        return None

    # Prefer an attachment whose MIME type is video/*; fall back to first file
    video_attachment = next(
        (a for a in attachments if a.get("type", "").startswith("video/")),
        attachments[0],
    )

    # ── 2. Parse identity fields ────────────────────────────────────────────
    candidate_names: list = fields.get(F_CANDIDATE_NAME, [])
    if not candidate_names:
        # F_CANDIDATE_NAME is a lookup that may be empty when the Application
        # link isn't populated. Fall back to the submission name formula field,
        # which has the format "Firstname Lastname - Role - Round Type".
        submission_label = fields.get(F_SUBMISSION_NAME, "")
        if submission_label:
            candidate_names = [submission_label]
    first_name, last_name = _parse_name(candidate_names)
    job_type = _derive_job_type(candidate_names)

    warnings: list[str] = []

    # ── 3. Download video ───────────────────────────────────────────────────
    try:
        video_path = download_video(video_attachment, download_dir)
    except Exception as exc:
        print(f"  [airtable_ingest] Download failed for {record_id}: {exc}")
        return None

    # ── 4. Duration check (reuses existing ffprobe wrapper) ─────────────────
    duration = get_video_duration(video_path)
    if duration is None:
        warnings.append(f"Could not determine duration for {video_path.name}.")
    elif duration < config.MIN_DURATION_SECONDS:
        warnings.append(
            f"Video duration {duration:.1f}s is below the minimum of "
            f"{config.MIN_DURATION_SECONDS}s."
        )
    elif duration > config.MAX_DURATION_SECONDS:
        warnings.append(
            f"Video duration {duration:.1f}s is above the maximum of "
            f"{config.MAX_DURATION_SECONDS}s."
        )

    candidate = CandidateFile(
        path=video_path,
        first_name=first_name,
        last_name=last_name,
        job_type=job_type,
        duration_seconds=duration,
        warnings=warnings,
    )

    return candidate, record_id


# ---------------------------------------------------------------------------
# Public: fetch and assemble rubric text from Airtable
# ---------------------------------------------------------------------------

def fetch_rubric_text(rubric_record_ids: list[str], api_key: str) -> str:
    """
    Fetch the first linked Rubric record and assemble it into the markdown
    string that analyze.score_transcript() expects.

    Returns an empty string if rubric_record_ids is empty; the caller is
    responsible for falling back to the local scoring_rubric.md in that case.
    """
    if not rubric_record_ids:
        return ""

    record_id = rubric_record_ids[0]
    url  = f"{AIRTABLE_API_BASE}/{AIRTABLE_BASE_ID}/{RUBRIC_TABLE}/{record_id}"
    data = _get(url, {}, api_key)
    f    = data.get("fields", {})

    # Helper closures to pull criterion text and weight by index
    _criteria = [F_CRITERION_1, F_CRITERION_2, F_CRITERION_3, F_CRITERION_4, F_CRITERION_5]
    _weights  = [F_WEIGHT_1,    F_WEIGHT_2,    F_WEIGHT_3,    F_WEIGHT_4,    F_WEIGHT_5]

    def criterion(n: int) -> str:          # n is 1-based
        return f.get(_criteria[n - 1], f"Criterion {n}")

    def weight(n: int) -> str:
        return str(f.get(_weights[n - 1], 1))

    # Hard-fail rules may be stored as strings or dicts with a "name" key
    hard_fail_raw: list = f.get(F_HARD_FAIL_RULES, [])
    hard_fail_lines = [
        f"* {item['name']}" if isinstance(item, dict) else f"* {item}"
        for item in hard_fail_raw
    ]
    hard_fail_text = "\n".join(hard_fail_lines) if hard_fail_lines else "None defined."

    passing = f.get(F_PASSING_THRESHOLD, 14)
    rubric_name = f.get(F_RUBRIC_NAME, "Untitled Rubric")

    rubric_md = f"""# Scoring Rubric: {rubric_name}

## Instructions
Score the candidate's submission using the rubric below.
Each criterion is scored 1 to 4. Record the total and per-criterion scores.

## Scoring Rubric

| Criterion | Weight |
|:----------|:-------|
| **1. {criterion(1)}** | {weight(1)} |
| **2. {criterion(2)}** | {weight(2)} |
| **3. {criterion(3)}** | {weight(3)} |
| **4. {criterion(4)}** | {weight(4)} |
| **5. {criterion(5)}** | {weight(5)} |

## Scoring Rules
**Passing threshold:** Weighted score >= {passing} to Advance.

## Hard Fail Rules (automatic decline regardless of total score)
{hard_fail_text}
"""
    return rubric_md


# ---------------------------------------------------------------------------
# Public: write pipeline scores back to an Airtable Submission record
# ---------------------------------------------------------------------------

def write_scores_to_airtable(
    result: CandidateResult,
    record_id: str,
    api_key: str,
) -> None:
    """
    PATCH the Candidate Submission record with scores from a completed pipeline run.

    Writes all five dimension scores, the Recommendation singleSelect, and the
    overall summary as Notes. The Weighted Score is a formula field and is never
    written — Airtable recalculates it automatically once the score fields land.

    Raises requests.HTTPError on non-retryable HTTP errors.
    """
    url = f"{AIRTABLE_API_BASE}/{AIRTABLE_BASE_ID}/{SUBMISSIONS_TABLE}/{record_id}"

    fields: dict = {
        F_SCORE_1: result.scores.role_fit_and_relevant_experience.score,
        F_SCORE_2: result.scores.domain_judgment.score,
        F_SCORE_3: result.scores.process_and_methodology.score,
        F_SCORE_4: result.scores.communication.score,
        F_SCORE_5: result.scores.instruction_following_and_professionalism.score,
        F_NOTES:   result.overall_summary,
    }

    airtable_recommendation = _RECOMMENDATION_MAP.get(result.recommendation)
    if airtable_recommendation is not None:
        fields[F_RECOMMENDATION] = airtable_recommendation
    else:
        print(
            f"  [airtable_ingest] Recommendation '{result.recommendation}' has no "
            "Airtable mapping — field skipped."
        )

    _patch(url, {"fields": fields}, api_key)


def advance_application_stage(
    application_record_ids: list[str],
    recommendation: str,
    api_key: str,
) -> None:
    """PATCH the Stage field on each linked Application record.

    Moves the candidate to the next pipeline stage based on the AI recommendation.
    No-ops if the recommendation has no stage mapping (Hold or Needs Human Review).
    """
    stage = _STAGE_MAP.get(recommendation)
    if stage is None:
        return
    for app_id in application_record_ids:
        url = f"{AIRTABLE_API_BASE}/{AIRTABLE_BASE_ID}/{APPLICATIONS_TABLE}/{app_id}"
        _patch(url, {"fields": {F_STAGE: stage}}, api_key)


def discontinue_candidate_record(
    application_record_ids: list[str],
    api_key: str,
) -> None:
    """Set Recommendations = 'Discontinue' on the Candidates record for a declined applicant.

    Traversal: Application (via F_APPLICATION on Submission) → Candidates link → PATCH.
    """
    for app_id in application_record_ids:
        url = f"{AIRTABLE_API_BASE}/{AIRTABLE_BASE_ID}/{APPLICATIONS_TABLE}/{app_id}"
        app_record = _get(url, {}, api_key)
        candidate_ids: list[str] = app_record.get("fields", {}).get(F_CANDIDATES_LINK, [])
        for cand_id in candidate_ids:
            url = f"{AIRTABLE_API_BASE}/{AIRTABLE_BASE_ID}/{CANDIDATES_TABLE}/{cand_id}"
            _patch(url, {"fields": {F_CANDIDATE_RECOMMENDATION: "Discontinue"}}, api_key)


# Recommendations that require a human to review before a final hiring decision.
_REVIEW_RECOMMENDATIONS = {"Hold", "Needs Human Review"}


def flag_review_needed(record_id: str, api_key: str) -> None:
    """Set Review Needed = true on a Submission record so the GAS watcher picks it up."""
    url = f"{AIRTABLE_API_BASE}/{AIRTABLE_BASE_ID}/{SUBMISSIONS_TABLE}/{record_id}"
    _patch(url, {"fields": {"Review Needed": True}}, api_key)


def write_video_url_to_airtable(record_id: str, url: str, filename: str, api_key: str) -> None:
    """
    PATCH the Files (multipleAttachments) field with a video URL so the
    submission video appears in Airtable.  Called AFTER scores are written so
    the Airtable automation (Files not empty + scores empty → /evaluate) never
    re-fires.  Only call when the field is currently empty.
    """
    endpoint = f"{AIRTABLE_API_BASE}/{AIRTABLE_BASE_ID}/{SUBMISSIONS_TABLE}/{record_id}"
    _patch(endpoint, {"fields": {F_FILES: [{"url": url, "filename": filename}]}}, api_key)


AIRTABLE_CONTENT_BASE = "https://content.airtable.com/v0"


def upload_html_report_to_airtable(record_id: str, html_path: Path, api_key: str) -> None:
    """
    Upload the HTML evaluation report binary to the Model output field.

    Uses content.airtable.com binary upload endpoint (multipart/form-data).
    Cannot use the URL-based PATCH pattern — HTML is a local file with no public URL.
    """
    url = (
        f"{AIRTABLE_CONTENT_BASE}/{AIRTABLE_BASE_ID}"
        f"/{record_id}/{F_MODEL_OUTPUT}/uploadAttachment"
    )
    with html_path.open("rb") as fh:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (html_path.name, fh, "text/html")},
            timeout=60,
        )
    if not resp.ok:
        print(f"  [upload_html] HTTP {resp.status_code} response body: {resp.text}")
    resp.raise_for_status()


def build_candidate_file_from_path(record: dict, video_path: Path) -> Optional[CandidateFile]:
    """
    Build a CandidateFile from a pre-downloaded video path and the Airtable
    record metadata, skipping the Airtable attachment download step.

    Used by the email ingest path (/ingest endpoint) where the video has already
    been downloaded from Google Drive or YouTube before this function is called.
    """
    fields = record.get("fields", {})

    candidate_names: list = fields.get(F_CANDIDATE_NAME, [])
    if not candidate_names:
        submission_label = fields.get(F_SUBMISSION_NAME, "")
        if submission_label:
            candidate_names = [submission_label]

    first_name, last_name = _parse_name(candidate_names)
    job_type = _derive_job_type(candidate_names)

    warnings: list[str] = []
    duration = get_video_duration(video_path)
    if duration is None:
        warnings.append(f"Could not determine duration for {video_path.name}.")
    elif duration < config.MIN_DURATION_SECONDS:
        warnings.append(
            f"Video duration {duration:.1f}s is below the minimum of "
            f"{config.MIN_DURATION_SECONDS}s."
        )
    elif duration > config.MAX_DURATION_SECONDS:
        warnings.append(
            f"Video duration {duration:.1f}s is above the maximum of "
            f"{config.MAX_DURATION_SECONDS}s."
        )

    return CandidateFile(
        path=video_path,
        first_name=first_name,
        last_name=last_name,
        job_type=job_type,
        duration_seconds=duration,
        warnings=warnings,
    )