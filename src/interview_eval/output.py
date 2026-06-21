from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from interview_eval.models import CandidateResult


CSV_COLUMNS = [
    "candidate_id",
    "first_name",
    "last_name",
    "job_type",
    "total_score",
    "role_fit",
    "domain_judgment",
    "process",
    "communication",
    "instruction_following",
    "recommendation",
    "confidence",
    "hard_fail",
    "evaluation_timestamp",
]


def write_candidate_json(result: CandidateResult, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.candidate_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(result.model_dump(), f, indent=2)
    return path


def write_candidate_csv(result: CandidateResult, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.candidate_id}.csv"
    hard_fail = any(
        [
            result.hard_fail_flags.did_not_answer_all_questions,
            result.hard_fail_flags.lacks_core_experience,
            result.hard_fail_flags.cannot_communicate_clearly,
        ]
    )
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerow(
            {
                "candidate_id": result.candidate_id,
                "first_name": result.first_name,
                "last_name": result.last_name,
                "job_type": result.job_type,
                "total_score": result.total_score,
                "role_fit": result.scores.role_fit_and_relevant_experience.score,
                "domain_judgment": result.scores.domain_judgment.score,
                "process": result.scores.process_and_methodology.score,
                "communication": result.scores.communication.score,
                "instruction_following": result.scores.instruction_following_and_professionalism.score,
                "recommendation": result.recommendation,
                "confidence": result.confidence_score,
                "hard_fail": "true" if hard_fail else "false",
                "evaluation_timestamp": result.evaluation_timestamp,
            }
        )
    return path


def _open_for_write(path: Path, retries: int = 3, delay: float = 2.0):
    """Try to open a file for writing, retrying on PermissionError (file locked by another process)."""
    for attempt in range(retries):
        try:
            return path.open("w", encoding="utf-8", newline="")
        except PermissionError:
            if attempt < retries - 1:
                print(f"  Warning: {path.name} is locked, retrying in {delay}s... "
                      f"(close any program that has it open)")
                time.sleep(delay)
            else:
                raise PermissionError(
                    f"Cannot write to {path} — it is locked by another process "
                    f"(Excel, OneDrive sync, etc.). Close the file and re-run."
                )


def write_batch_csv(results: list[CandidateResult], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "batch_summary.csv"
    with _open_for_write(path) as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for result in results:
            hard_fail = any(
                [
                    result.hard_fail_flags.did_not_answer_all_questions,
                    result.hard_fail_flags.lacks_core_experience,
                    result.hard_fail_flags.cannot_communicate_clearly,
                ]
            )
            writer.writerow(
                {
                    "candidate_id": result.candidate_id,
                    "first_name": result.first_name,
                    "last_name": result.last_name,
                    "job_type": result.job_type,
                    "total_score": result.total_score,
                    "role_fit": result.scores.role_fit_and_relevant_experience.score,
                    "domain_judgment": result.scores.domain_judgment.score,
                    "process": result.scores.process_and_methodology.score,
                    "communication": result.scores.communication.score,
                    "instruction_following": result.scores.instruction_following_and_professionalism.score,
                    "recommendation": result.recommendation,
                    "confidence": result.confidence_score,
                    "hard_fail": "true" if hard_fail else "false",
                    "evaluation_timestamp": result.evaluation_timestamp,
                }
            )
    return path
