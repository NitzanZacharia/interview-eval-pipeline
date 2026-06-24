# src/interview_eval/airtable_ingest.py
"""
Read-only Airtable ingestion layer.
Replaces scan_input_dir() for the Airtable-driven pipeline.
Requires: AIRTABLE_API_KEY (read-only token is sufficient for this entire module).
"""
from __future__ import annotations

import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

import requests

from .models import CandidateFile
from .ingest import get_video_duration  # reuse existing ffprobe wrapper

# ── Constants (from prior schema exploration) ──────────────────────────────
AIRTABLE_BASE_ID   = "appaDY3ar7TcmEkI6"
SUBMISSIONS_TABLE  = "tblAjBCyfful0jay0"
RUBRIC_TABLE       = "tblt1hU6iW6dKsLkO"
AIRTABLE_API_BASE  = "https://api.airtable.com/v0"

# Field IDs — Candidate Submissions table
F_SUBMISSION_NAME  = "fldDn1kGnhYp9QTfa"
F_ROUND_TYPE       = "fldMowMIcpaxlxsor"
F_FILES            = "fldqc8EyRmXqogYTm"   # multipleAttachments — video lives here
F_CANDIDATE_NAME   = "fldIULihwWP4KmQKm"   # multipleLookupValues
F_APPLICATION      = "fldYAiyp0ILBXGuiQ"
F_RUBRIC_LINK      = "fldQ6e4ARmWjasS7z"
F_SCORE_1          = "fldPHxOA56TRIsEXq"   # used to detect "blank rubric" records

# Round type option IDs
ROUND_VIDEO_SUBMISSION = "sel11RPB63d9K0hFG"

# Field IDs — Rubric table
F_RUBRIC_NAME      = "fldHiXGCAYNLjw9Z8"
F_CRITERION_1      = "fldVvpbMNMthzLoUG"
F_CRITERION_2      = "fldAwcAmWCP2Kyb9V"
F_CRITERION_3      = "fldFmG2yJJqDl5AOx"
F_CRITERION_4      = "fldv2ila1djNoMtvx"
F_CRITERION_5      = "fldcbFBcOkZ7p8Xzj"
F_WEIGHT_1         = "fldB5zVKKwBz3CX4B"
F_WEIGHT_2         = "fldLHsiodYNfb1MRj"
F_WEIGHT_3         = "fldr2ATD0qU40A4IO"
F_WEIGHT_4         = "fldmvQiVSZQwBIHUr"
F_WEIGHT_5         = "fldFpLBJTyWxE36HZ"
F_PASSING_THRESHOLD= "fldfKyXGXJLTdEJlB"
F_HARD_FAIL_RULES  = "fld9dtMu2Rj5vN41o"


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _airtable_get(url: str, params: dict, api_key: str) -> dict:
    """Single GET with basic retry on 429 (rate limit)."""
    for attempt in range(3):
        resp = requests.get(url, headers=_headers(api_key), params=params, timeout=30)
        if resp.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()


def fetch_unscored_video_submissions(api_key: str) -> list[dict]:
    """
    Poll Candidate Submissions for records that:
      1. Have Round type == "Video Submission"
      2. Have at least one file attachment (the video)
      3. Have Score 1 empty (blank rubric — not yet processed)

    Returns raw Airtable record dicts.
    """
    url = f"{AIRTABLE_API_BASE}/{AIRTABLE_BASE_ID}/{SUBMISSIONS_TABLE}"

    # filterByFormula targets blank-rubric Video Submission records
    # AND({Round type} = "Video Submission", {Files} != "", {Score 1} = "")
    formula = (
        "AND("
        '{Round type}="Video Submission",'
        '{Files}!="",'
        "{Score 1}="
        ")"
    )

    records = []
    offset = None

    while True:
        params = {
            "filterByFormula": formula,
            "fields[]": [
                F_SUBMISSION_NAME, F_ROUND_TYPE, F_FILES,
                F_CANDIDATE_NAME, F_APPLICATION, F_RUBRIC_LINK, F_SCORE_1,
            ],
        }
        if offset:
            params["offset"] = offset

        data = _airtable_get(url, params, api_key)
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break

    return records


def download_video(attachment: dict, dest_dir: Path) -> Path:
    """
    Download the video from an Airtable signed URL to a local temp file.
    The signed URL is time-limited (~hours); call this immediately after fetch.

    Returns the local Path of the downloaded .mp4.
    """
    signed_url = attachment["url"]
    filename   = attachment.get("filename", "video.mp4")
    dest_path  = dest_dir / filename

    with requests.get(signed_url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with dest_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

    return dest_path


def _parse_name_from_candidate_lookup(candidate_name_values: list) -> tuple[str, str]:
    """
    candidate_name_values is a multipleLookupValues array of strings like:
      ["Emily Kobelenz-DiRienzo - QA Specialist"]
    Parse first_name and last_name from the first entry.
    """
    if not candidate_name_values:
        return "unknown", "unknown"
    raw = candidate_name_values[0]            # "Emily Kobelenz-DiRienzo - QA Specialist"
    name_part = raw.split(" - ")[0].strip()   # "Emily Kobelenz-DiRienzo"
    parts = name_part.lower().split()
    first = parts[0] if parts else "unknown"
    last  = parts[-1] if len(parts) > 1 else "unknown"
    # Strip hyphens to satisfy filename regex ^[a-z]+-[a-z]+-(?:SME|QA)\.mp4$
    first = re.sub(r"[^a-z]", "", first)
    last  = re.sub(r"[^a-z]", "", last)
    return first, last


def _derive_job_type(candidate_name_values: list) -> str:
    """
    Derive job_type from the Role Title embedded in the Candidate Name lookup string.
    Current roles map: anything containing "QA" → "QA", else → "SME".
    """
    raw = " ".join(candidate_name_values)
    if "QA" in raw or "Quality" in raw:
        return "QA"
    return "SME"


def airtable_record_to_candidate_file(
    record: dict,
    download_dir: Path,
) -> Optional[tuple[CandidateFile, str]]:
    """
    Convert a raw Airtable record into a CandidateFile + the Airtable record ID.
    Downloads the video to download_dir.
    Returns None if the record is not processable.
    """
    fields = record.get("fields", {})
    record_id = record["id"]

    attachments = fields.get(F_FILES, [])
    if not attachments:
        return None

    # Find the first .mp4 attachment
    video_attachment = next(
        (a for a in attachments if a.get("type", "").startswith("video")),
        attachments[0],   # fallback to first file
    )

    candidate_names = fields.get(F_CANDIDATE_NAME, [])
    first_name, last_name = _parse_name_from_candidate_lookup(candidate_names)
    job_type = _derive_job_type(candidate_names)

    warnings: list[str] = []

    # Download video to local temp path
    try:
        video_path = download_video(video_attachment, download_dir)
    except Exception as e:
        warnings.append(f"Download failed: {e}")
        return None

    # Run ffprobe on the downloaded file (reuses existing ingest function)
    duration = get_video_duration(video_path)
    if duration is None:
        warnings.append(f"Could not determine duration for {video_path.name}.")

    candidate = CandidateFile(
        path=video_path,
        first_name=first_name,
        last_name=last_name,
        job_type=job_type,
        duration_seconds=duration,
        warnings=warnings,
    )

    return candidate, record_id


def fetch_rubric_text(rubric_record_ids: list[str], api_key: str) -> str:
    """
    Fetch the Rubric record(s) linked to a submission and assemble
    them into the markdown string that analyze.score_transcript() expects.
    """
    if not rubric_record_ids:
        # Fall back to the local scoring_rubric.md if no rubric is linked
        return ""

    record_id = rubric_record_ids[0]
    url = f"{AIRTABLE_API_BASE}/{AIRTABLE_BASE_ID}/{RUBRIC_TABLE}/{record_id}"
    data = _airtable_get(url, {}, api_key)
    f = data.get("fields", {})

    def w(n: int) -> str:
        weights = [F_WEIGHT_1, F_WEIGHT_2, F_WEIGHT_3, F_WEIGHT_4, F_WEIGHT_5]
        return str(f.get(weights[n - 1], 1))

    def c(n: int) -> str:
        criteria = [F_CRITERION_1, F_CRITERION_2, F_CRITERION_3, F_CRITERION_4, F_CRITERION_5]
        return f.get(criteria[n - 1], f"Criterion {n}")

    hard_fails = f.get(F_HARD_FAIL_RULES, [])
    hard_fail_text = "\n".join(
        f"* {hf['name']}" if isinstance(hf, dict) else f"* {hf}"
        for hf in hard_fails
    )

    rubric_text = f"""# Scoring Rubric: {f.get(F_RUBRIC_NAME, "Untitled")}

## Criteria (each scored 1–4)

| # | Criterion | Weight |
|:--|:----------|:-------|
| 1 | {c(1)} | {w(1)} |
| 2 | {c(2)} | {w(2)} |
| 3 | {c(3)} | {w(3)} |
| 4 | {c(4)} | {w(4)} |
| 5 | {c(5)} | {w(5)} |

## Passing Threshold
Total weighted score >= {f.get(F_PASSING_THRESHOLD, 14)} to Advance.

## Hard Fail Rules
{hard_fail_text if hard_fail_text else "None defined."}
"""
    return rubric_text