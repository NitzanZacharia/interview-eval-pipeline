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


def run_pipeline(input_dir: Path, output_dir: Path, rubric_path: Path) -> None:
    rubric_text = rubric_path.read_text(encoding="utf-8")
    candidates = scan_input_dir(input_dir)

    if not candidates:
        print("No new videos to process.")
        return

    print(f"Processing {len(candidates)} candidate(s)...")

    results: list[CandidateResult] = []

    for candidate in candidates:
        print(f"  [{candidate.candidate_id}] Transcribing...")
        try:
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
