from __future__ import annotations

import csv
import json
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


def write_batch_csv(results: list[CandidateResult], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "batch_summary.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
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
