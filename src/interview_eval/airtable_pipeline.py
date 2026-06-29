"""
interview_eval.airtable_pipeline

Per-record pipeline orchestration for Airtable-driven evaluation runs.
Used by both the CLI script (simulate_airtable_pipeline.py) and the
FastAPI server (server.py).
"""
from __future__ import annotations

from pathlib import Path

from .airtable_ingest import (
    F_APPLICATION,
    F_RUBRIC_LINK,
    _REVIEW_RECOMMENDATIONS,
    _STAGE_MAP,
    advance_application_stage,
    airtable_record_to_candidate_file,
    build_candidate_file_from_path,
    fetch_rubric_text,
    send_hr_review_notification,
    write_scores_to_airtable,
)
from .analyze import score_transcript
from .classify import classify_candidate
from .models import CandidateResult, ClassificationResult, TranscriptResult
from .output import write_batch_csv, write_candidate_json, write_candidate_report
from .transcribe import transcribe_video

# Repo root — used only when save_transcripts=True (local calibration runs).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def process_record(
    record: dict,
    airtable_key: str,
    download_dir: Path,
    fallback_rubric_path: Path,
    output_dir: Path,
    write_back: bool = True,
    save_transcripts: bool = False,
    video_path: Path | None = None,
) -> dict | None:
    """
    Run the full pipeline for one Airtable Candidate Submission record.

    Returns the result dict (suitable for JSON serialisation), or None if the
    record could not be processed (e.g. no video attachment, no rubric).
    When write_back is True, PATCHes scores and advances the Application stage.
    """
    record_id = record["id"]
    label     = record.get("fields", {}).get("fldDn1kGnhYp9QTfa", record_id)
    print(f"\n{'─' * 60}")
    print(f"  Record : {record_id}")
    print(f"  Label  : {label}")

    # ── Step 1: Download video + build CandidateFile ──────────────────────
    if video_path is not None:
        # Email ingest path: video was already downloaded externally (from Drive or YouTube).
        print(f"  [1/5] Using pre-downloaded video: {video_path.name}")
        candidate = build_candidate_file_from_path(record, video_path)
        if candidate is None:
            print("        SKIPPED — could not parse candidate metadata from record.")
            return None
        at_record_id = record["id"]
    else:
        # Standard Airtable path: download from the record's Files attachment.
        print("  [1/5] Downloading video from Airtable...")
        outcome = airtable_record_to_candidate_file(record, download_dir)
        if outcome is None:
            print("        SKIPPED — could not build CandidateFile (check attachment field).")
            return None
        candidate, at_record_id = outcome

    print(f"        Video     : {candidate.path.name}")
    if candidate.duration_seconds is not None:
        print(f"        Duration  : {candidate.duration_seconds:.1f}s")
    for w in candidate.warnings:
        print(f"        WARNING   : {w}")

    # ── Step 2: Fetch rubric ───────────────────────────────────────────────
    # Priority: role-specific file (scoring_rubric_QA.md / scoring_rubric_SME.md)
    # → combined base file (scoring_rubric.md) → Airtable record (last resort).
    # Role-specific files are derived from the base path so callers don't need
    # to change — server.py and simulate_airtable_pipeline.py pass the same path.
    print("  [2/5] Fetching rubric...")
    role_rubric = (
        fallback_rubric_path.parent
        / f"{fallback_rubric_path.stem}_{candidate.job_type}.md"
    )
    if role_rubric.is_file():
        rubric_text = role_rubric.read_text(encoding="utf-8")
        print(f"        Rubric loaded from local file: {role_rubric.name}")
    elif fallback_rubric_path.is_file():
        rubric_text = fallback_rubric_path.read_text(encoding="utf-8")
        print(f"        Rubric loaded from local file: {fallback_rubric_path.name}")
    else:
        rubric_ids: list[str] = record.get("fields", {}).get(F_RUBRIC_LINK, [])
        if rubric_ids:
            rubric_text = fetch_rubric_text(rubric_ids, airtable_key)
            print(f"        Local rubric not found — fetched from Airtable (record {rubric_ids[0]}).")
        else:
            print(
                f"        ERROR: No rubric available at {fallback_rubric_path} and no "
                "Airtable rubric linked.\n"
                "        Set RUBRIC_PATH env var or place scoring_rubric.md in the repo root."
            )
            return None

    # ── Step 3: Transcribe ─────────────────────────────────────────────────
    print("  [3/5] Transcribing video (this may take a while on first run)...")
    transcript: TranscriptResult = transcribe_video(candidate.path)
    if transcript.failed:
        print(f"        Transcription FAILED: {transcript.error_message}")
        classification = ClassificationResult(
            recommendation="Needs Human Review",
            reason=f"Transcription failed: {transcript.error_message}",
        )
        result_obj = CandidateResult.from_pipeline(candidate, transcript, None, classification)
        _print_result(result_obj, at_record_id)
        _write_local_outputs(result_obj, output_dir)
        return result_obj.model_dump()

    print(f"        Transcript : {transcript.word_count} words")
    if save_transcripts and transcript.text:
        fixtures_dir = _REPO_ROOT / "tests" / "fixtures" / "transcripts"
        fixtures_dir.mkdir(parents=True, exist_ok=True)
        txt_path = fixtures_dir / f"{candidate.candidate_id}.txt"
        txt_path.write_text(transcript.text, encoding="utf-8")
        print(f"        Transcript saved → {txt_path}")

    # ── Step 4: Score ──────────────────────────────────────────────────────
    print(f"  [4/5] Scoring transcript via Claude ({candidate.job_type})...")
    analysis = score_transcript(transcript.text, rubric_text, candidate.job_type)
    if analysis is None:
        print("        Scoring FAILED.")
        classification = ClassificationResult(
            recommendation="Needs Human Review",
            reason="LLM scoring failed. Manual review required.",
        )
        result_obj = CandidateResult.from_pipeline(candidate, transcript, None, classification)
        _print_result(result_obj, at_record_id)
        _write_local_outputs(result_obj, output_dir)
        return result_obj.model_dump()

    # ── Step 5: Classify ───────────────────────────────────────────────────
    print("  [5/5] Classifying...")
    classification = classify_candidate(analysis)
    result_obj = CandidateResult.from_pipeline(candidate, transcript, analysis, classification)

    _print_result(result_obj, at_record_id)
    _write_local_outputs(result_obj, output_dir)

    if write_back:
        try:
            write_scores_to_airtable(result_obj, at_record_id, airtable_key)
            print(f"  Scores written to Airtable record {at_record_id}.")
            app_ids: list[str] = record.get("fields", {}).get(F_APPLICATION, [])
            if app_ids:
                advance_application_stage(app_ids, result_obj.recommendation, airtable_key)
                new_stage = _STAGE_MAP.get(result_obj.recommendation)
                if new_stage:
                    print(f"  Stage updated    → {new_stage}")
        except Exception as exc:
            print(
                f"  WARNING: Airtable write failed for {at_record_id}: {exc}\n"
                "  Scores saved locally — retry the record to write back."
            )

        if result_obj.recommendation in _REVIEW_RECOMMENDATIONS:
            candidate_name = f"{result_obj.first_name.title()} {result_obj.last_name.title()}"
            send_hr_review_notification(candidate_name, result_obj.recommendation, at_record_id)

    return result_obj.model_dump()


def _print_result(result: CandidateResult, at_record_id: str) -> None:
    s  = result.scores
    hf = result.hard_fail_flags
    any_hf = any([
        hf.did_not_answer_all_questions,
        hf.lacks_core_experience,
        hf.cannot_communicate_clearly,
    ])
    print()
    print("  ┌─ RESULT ─────────────────────────────────────────────────────")
    print(f"  │  Airtable record ID : {at_record_id}")
    print(f"  │  Candidate          : {result.first_name.title()} {result.last_name.title()}")
    print(f"  │  Job type           : {result.job_type}")
    print(f"  │  Recommendation     : {result.recommendation}")
    print(f"  │  Total score        : {result.total_score}/20")
    print(f"  │  Confidence         : {result.confidence_score:.0%}")
    print(f"  │  Hard fail          : {'YES' if any_hf else 'no'}")
    print(f"  │  Score 1 (Role Fit) : {s.role_fit_and_relevant_experience.score}/4")
    print(f"  │  Score 2 (Domain)   : {s.domain_judgment.score}/4")
    print(f"  │  Score 3 (Process)  : {s.process_and_methodology.score}/4")
    print(f"  │  Score 4 (Comms)    : {s.communication.score}/4")
    print(f"  │  Score 5 (Instr)    : {s.instruction_following_and_professionalism.score}/4")
    print("  └──────────────────────────────────────────────────────────────")


def _write_local_outputs(result: CandidateResult, output_dir: Path) -> None:
    json_path   = write_candidate_json(result, output_dir)
    report_path = write_candidate_report(result, output_dir)
    write_batch_csv([result], output_dir)
    print(f"  Local JSON   → {json_path}")
    print(f"  Local report → {report_path}")
