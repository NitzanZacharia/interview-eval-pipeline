#!/usr/bin/env python3
"""
scripts/simulate_airtable_pipeline.py

Airtable-driven interview evaluation pipeline.

What it does:
  1. Fetches unscored "Video Submission" records from the live Airtable base.
  2. Downloads the first video to a local temp directory.
  3. Fetches the linked rubric (or falls back to scoring_rubric.md).
  4. Runs transcription → scoring → classification exactly as the real pipeline does.
  5. Prints a full result summary and writes simulation_output.json to the CWD.
  6. Writes scores back to Airtable after each successful evaluation.

Default behaviour:
  - PATCHes scores, recommendation, and notes to the Airtable record.
  - Requires data.records:write scope on the token.
  - Pass --dry-run to skip the write-back (read-only token is then sufficient).

Usage:
  AIRTABLE_TOKEN=patXXXXXX... \\
  ANTHROPIC_API_KEY=sk-ant-... \\
  python scripts/simulate_airtable_pipeline.py

Optional flags:
  --record-id <id>   Process a specific Airtable record instead of the first unscored one.
  --limit <n>        Process up to n records (default: all eligible records).
  --output-dir <dir> Write JSON/HTML/CSV outputs here too (default: ./sim_output).
  --fallback-rubric <path>  Local rubric .md to use when no rubric is linked (default: ./scoring_rubric.md).
  --dry-run          Skip writing scores back to Airtable (read-only mode).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Make the src/ layout importable when run directly from the project root
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from interview_eval.airtable_ingest import (
    F_RUBRIC_LINK,
    airtable_record_to_candidate_file,
    fetch_rubric_text,
    fetch_single_record,
    fetch_unscored_video_submissions,
    write_scores_to_airtable,
)
from interview_eval.analyze import score_transcript
from interview_eval.classify import classify_candidate
from interview_eval.models import (
    CandidateResult,
    ClassificationResult,
    TranscriptResult,
)
from interview_eval.output import (
    write_batch_csv,
    write_candidate_json,
    write_candidate_report,
)
from interview_eval.transcribe import transcribe_video


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Airtable-driven interview evaluation pipeline."
    )
    parser.set_defaults(write_back=True)
    parser.add_argument(
        "--record-id",
        metavar="ID",
        default=None,
        help="Process a specific Airtable record ID instead of auto-fetching.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Maximum number of records to process (default: all eligible records).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./sim_output"),
        metavar="DIR",
        help="Directory for local JSON/HTML/CSV outputs (default: ./sim_output).",
    )
    parser.add_argument(
        "--fallback-rubric",
        type=Path,
        default=Path("./scoring_rubric.md"),
        metavar="PATH",
        help="Local rubric .md file used when no rubric is linked in Airtable.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_false",
        dest="write_back",
        help="Skip writing scores back to Airtable (read-only mode).",
    )
    parser.add_argument(
        "--save-transcripts",
        action="store_true",
        default=False,
        help="Save raw transcript text to tests/fixtures/transcripts/<candidate_id>.txt after transcription.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Per-record processing — pure read path, no Airtable writes
# ---------------------------------------------------------------------------

def _process_record(
    record: dict,
    airtable_key: str,
    download_dir: Path,
    fallback_rubric_path: Path,
    output_dir: Path,
    write_back: bool = False,
    save_transcripts: bool = False,
) -> dict | None:
    """
    Run the full pipeline for one Airtable record.
    Returns the result dict (suitable for JSON serialisation) or None on failure.
    When write_back is True, PATCHes scores to Airtable after a successful evaluation.
    """
    record_id = record["id"]
    label     = record.get("fields", {}).get("fldDn1kGnhYp9QTfa", record_id)
    print(f"\n{'─' * 60}")
    print(f"  Record : {record_id}")
    print(f"  Label  : {label}")

    # ── Step 1: Download video + build CandidateFile ─────────────────────
    print("  [1/5] Downloading video from Airtable...")
    outcome = airtable_record_to_candidate_file(record, download_dir)
    if outcome is None:
        print("        SKIPPED — could not build CandidateFile (check attachment field).")
        return None
    candidate, at_record_id = outcome
    print(f"        Downloaded → {candidate.path.name}")
    if candidate.duration_seconds is not None:
        print(f"        Duration  : {candidate.duration_seconds:.1f}s")
    if candidate.warnings:
        for w in candidate.warnings:
            print(f"        WARNING   : {w}")

    # ── Step 2: Fetch rubric ──────────────────────────────────────────────
    print("  [2/5] Fetching rubric...")
    rubric_ids: list[str] = record.get("fields", {}).get(F_RUBRIC_LINK, [])
    if rubric_ids:
        rubric_text = fetch_rubric_text(rubric_ids, airtable_key)
        print(f"        Rubric fetched from Airtable (record {rubric_ids[0]}).")
    elif fallback_rubric_path.is_file():
        rubric_text = fallback_rubric_path.read_text(encoding="utf-8")
        print(f"        No rubric linked — using local fallback: {fallback_rubric_path}")
    else:
        print(
            f"        ERROR: No rubric linked and fallback not found at {fallback_rubric_path}.\n"
            "        Pass --fallback-rubric <path> or link a Rubric record in Airtable."
        )
        return None

    # ── Step 3: Transcribe ────────────────────────────────────────────────
    print("  [3/5] Transcribing video (this may take a while on first run)...")
    transcript: TranscriptResult = transcribe_video(candidate.path)
    if transcript.failed:
        print(f"        Transcription FAILED: {transcript.error_message}")
        classification = ClassificationResult(
            recommendation="Needs Human Review",
            reason=f"Transcription failed: {transcript.error_message}",
        )
        result_obj = CandidateResult.from_pipeline(
            candidate, transcript, None, classification
        )
        _print_result(result_obj, at_record_id)
        _write_local_outputs(result_obj, output_dir)
        return result_obj.model_dump()

    print(f"        Transcript : {transcript.word_count} words")
    if save_transcripts and transcript.text:
        fixtures_dir = _ROOT / "tests" / "fixtures" / "transcripts"
        fixtures_dir.mkdir(parents=True, exist_ok=True)
        txt_path = fixtures_dir / f"{candidate.candidate_id}.txt"
        txt_path.write_text(transcript.text, encoding="utf-8")
        print(f"        Transcript saved → {txt_path}")

    # ── Step 4: Score ─────────────────────────────────────────────────────
    print(f"  [4/5] Scoring transcript via Claude ({candidate.job_type})...")
    analysis = score_transcript(transcript.text, rubric_text, candidate.job_type)
    if analysis is None:
        print("        Scoring FAILED.")
        classification = ClassificationResult(
            recommendation="Needs Human Review",
            reason="LLM scoring failed. Manual review required.",
        )
        result_obj = CandidateResult.from_pipeline(
            candidate, transcript, None, classification
        )
        _print_result(result_obj, at_record_id)
        _write_local_outputs(result_obj, output_dir)
        return result_obj.model_dump()

    # ── Step 5: Classify ──────────────────────────────────────────────────
    print("  [5/5] Classifying...")
    classification = classify_candidate(analysis)
    result_obj = CandidateResult.from_pipeline(
        candidate, transcript, analysis, classification
    )

    _print_result(result_obj, at_record_id)
    _write_local_outputs(result_obj, output_dir)

    if write_back:
        try:
            write_scores_to_airtable(result_obj, at_record_id, airtable_key)
            print(f"  Scores written to Airtable record {at_record_id}.")
        except Exception as exc:
            print(
                f"  WARNING: Airtable write failed for {at_record_id}: {exc}\n"
                f"  Scores saved locally — re-run without --dry-run to retry."
            )

    return result_obj.model_dump()


def _print_result(result: CandidateResult, at_record_id: str) -> None:
    """Pretty-print the pipeline result. No Airtable writes."""
    s = result.scores
    hf = result.hard_fail_flags
    any_hf = any([
        hf.did_not_answer_all_questions,
        hf.lacks_core_experience,
        hf.cannot_communicate_clearly,
    ])

    print()
    print("  ┌─ RESULT (simulation — nothing written to Airtable) ──────────")
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
    """Write the standard local outputs — JSON, HTML, CSV — to output_dir."""
    json_path   = write_candidate_json(result, output_dir)
    report_path = write_candidate_report(result, output_dir)
    write_batch_csv([result], output_dir)
    print(f"  Local JSON   → {json_path}")
    print(f"  Local report → {report_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()
    args = _parse_args()

    # ── Validate environment ──────────────────────────────────────────────
    airtable_key = os.environ.get("AIRTABLE_TOKEN", "").strip()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if not airtable_key:
        print(
            "ERROR: AIRTABLE_TOKEN is not set.\n"
            "Export a read-only Personal Access Token:\n"
            "  export AIRTABLE_TOKEN=patXXXXXX...",
            file=sys.stderr,
        )
        sys.exit(1)

    if not anthropic_key:
        print(
            "ERROR: ANTHROPIC_API_KEY is not set.\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...",
            file=sys.stderr,
        )
        sys.exit(1)

    # The pipeline reads ANTHROPIC_API_KEY via config.get_api_key()
    os.environ["ANTHROPIC_API_KEY"] = anthropic_key

    args.output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  Airtable Pipeline — Read-Only Simulation")
    print("=" * 60)

    # ── Fetch records ─────────────────────────────────────────────────────
    if args.record_id:
        print(f"\nFetching specific record: {args.record_id}")
        records = [fetch_single_record(args.record_id, airtable_key)]
    else:
        print("\nFetching unscored Video Submission records from Airtable...")
        records = fetch_unscored_video_submissions(airtable_key)
        if not records:
            print(
                "\nNo unscored Video Submission records found.\n"
                "To test:\n"
                "  1. Create a Candidate Submission record in Airtable.\n"
                "  2. Set Round type = 'Video Submission'.\n"
                "  3. Upload a .mp4 to the Files field.\n"
                "  4. Leave Score 1 blank.\n"
                "Or pass --record-id <id> to target a specific record directly."
            )
            sys.exit(0)

        if args.limit is not None:
            print(f"Found {len(records)} unscored record(s). Processing up to {args.limit}.")
            records = records[: args.limit]
        else:
            print(f"Found {len(records)} unscored record(s). Processing all.")

    # ── Process each record inside a shared temp directory ────────────────
    all_results: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="airtable_sim_") as tmp_str:
        tmp_dir = Path(tmp_str)
        print(f"Temp download directory: {tmp_dir}")

        for record in records:
            result_dict = _process_record(
                record=record,
                airtable_key=airtable_key,
                download_dir=tmp_dir,
                fallback_rubric_path=args.fallback_rubric,
                output_dir=args.output_dir,
                write_back=args.write_back,
                save_transcripts=args.save_transcripts,
            )
            if result_dict:
                all_results.append(result_dict)

        # Temp directory (and all downloaded videos) deleted here automatically

    # ── Write combined simulation output JSON ─────────────────────────────
    sim_output_path = Path("simulation_output.json")
    with sim_output_path.open("w", encoding="utf-8") as fh:
        json.dump(all_results, fh, indent=2)

    print(f"\n{'=' * 60}")
    print(f"  Simulation complete. Processed {len(all_results)} record(s).")
    print(f"  Combined output  → {sim_output_path.resolve()}")
    print(f"  Per-candidate    → {args.output_dir.resolve()}/")
    print("=" * 60)


if __name__ == "__main__":
    main()