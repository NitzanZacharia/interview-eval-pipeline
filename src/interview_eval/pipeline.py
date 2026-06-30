from __future__ import annotations

from pathlib import Path

from .analyze import score_transcript
from .classify import classify_candidate
from .ingest import move_to_processed, scan_input_dir
from .models import (
    CandidateResult,
    ClassificationResult,
    TranscriptResult,
)
from .output import write_batch_csv, write_candidate_json, write_candidate_report
from .transcribe import transcribe_video


def _resolve_rubric_text(base_path: Path, job_type: str, explicit: bool) -> str | None:
    """Return rubric text for this candidate.

    When --rubric was explicitly passed, use that file for every candidate.
    Otherwise mirror the airtable_pipeline.py waterfall:
      1. scoring_rubric_{job_type}.md  (role-specific)
      2. base_path (scoring_rubric.md)
    Returns None if no rubric file can be found.
    """
    if explicit:
        return base_path.read_text(encoding="utf-8")
    role_specific = base_path.parent / f"{base_path.stem}_{job_type}.md"
    if role_specific.is_file():
        print(f"  Rubric: {role_specific.name}")
        return role_specific.read_text(encoding="utf-8")
    if base_path.is_file():
        print(f"  Rubric: {base_path.name}")
        return base_path.read_text(encoding="utf-8")
    return None


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    rubric_path: Path,
    explicit_rubric: bool = False,
) -> None:
    candidates = scan_input_dir(input_dir)

    if not candidates:
        print("No new videos to process.")
        return

    print(f"Processing {len(candidates)} candidate(s)...")

    results: list[CandidateResult] = []

    for candidate in candidates:
        print(f"  [{candidate.candidate_id}] Transcribing...")
        try:
            rubric_text = _resolve_rubric_text(rubric_path, candidate.job_type, explicit_rubric)
            if rubric_text is None:
                print(
                    f"  [{candidate.candidate_id}] ERROR: No rubric file found for "
                    f"job_type={candidate.job_type} at {rubric_path}. Skipping."
                )
                continue

            transcript = transcribe_video(candidate.path)

            if transcript.failed:
                print(f"  [{candidate.candidate_id}] Transcription failed: {transcript.error_message}")
                classification = ClassificationResult(
                    recommendation="Needs Human Review",
                    reason=f"Transcription failed. Manual review required.",
                )
                result = CandidateResult.from_pipeline(
                    candidate, transcript, analysis=None, classification=classification
                )
                results.append(result)
                write_candidate_json(result, output_dir)
                write_candidate_report(result, output_dir)
                move_to_processed(candidate.path, input_dir)
                continue

            print(f"  [{candidate.candidate_id}] Scoring against rubric...")
            analysis = score_transcript(transcript.text, rubric_text, candidate.job_type)

            if analysis is None:
                print(f"  [{candidate.candidate_id}] Scoring failed, flagging for human review.")
                classification = ClassificationResult(
                    recommendation="Needs Human Review",
                    reason="LLM scoring failed. Manual review required.",
                )
                result = CandidateResult.from_pipeline(
                    candidate, transcript, analysis=None, classification=classification
                )
                results.append(result)
                write_candidate_json(result, output_dir)
                write_candidate_report(result, output_dir)
                move_to_processed(candidate.path, input_dir)
                continue

            classification = classify_candidate(analysis)
            print(f"  [{candidate.candidate_id}] → {classification.recommendation}")

            result = CandidateResult.from_pipeline(
                candidate, transcript, analysis, classification
            )
            results.append(result)
            write_candidate_json(result, output_dir)
            write_candidate_report(result, output_dir)
            move_to_processed(candidate.path, input_dir)

        except Exception as e:
            print(f"  [{candidate.candidate_id}] Unexpected error: {e}")
            transcript = TranscriptResult(failed=True, error_message=str(e))
            classification = ClassificationResult(
                recommendation="Needs Human Review",
                reason=f"Unexpected pipeline error: {e}",
            )
            result = CandidateResult.from_pipeline(
                candidate, transcript, analysis=None, classification=classification
            )
            results.append(result)
            write_candidate_json(result, output_dir)
            write_candidate_report(result, output_dir)

    csv_path = write_batch_csv(results, output_dir)
    print(f"\nBatch summary written to {csv_path}")
    print(f"Processed {len(results)} candidate(s).")
