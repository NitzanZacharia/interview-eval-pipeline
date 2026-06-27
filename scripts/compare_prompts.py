#!/usr/bin/env python3
"""
scripts/compare_prompts.py

Prompt calibration harness: runs the current prompt stack against saved transcript
fixtures and compares against both the pre-revision AI baseline and HR ground truth.

Usage:
  python scripts/compare_prompts.py

Prerequisites:
  1. Transcript fixtures must exist in tests/fixtures/transcripts/.
     Generate them by running the simulation with --save-transcripts:
       python scripts/simulate_airtable_pipeline.py --limit 3 --save-transcripts
  2. ANTHROPIC_API_KEY must be set (reads from .env automatically).

Output:
  - Console table comparing baseline AI, new AI, and HR scores per candidate.
  - compare_output.csv written to the project root.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from interview_eval.analyze import score_transcript
from interview_eval.classify import classify_candidate


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------

# HR-assigned scores (source: manual HR evaluation of SANDBOX candidates).
# Format: (role_fit, domain, process, comms, instr_following)
HR_GROUND_TRUTH: dict[str, dict] = {
    "leslie-doucet-QA": {
        "label": "Leslie Doucet",
        "job_type": "QA",
        "hr_scores": (4, 4, 3, 4, 3),
        "hr_total": 18,
        "hr_recommendation": "Strong hire",
    },
    "maria-ferrara-QA": {
        "label": "Maria Ferrara",
        "job_type": "QA",
        "hr_scores": (3, 3, 4, 4, 4),
        "hr_total": 18,
        "hr_recommendation": "Strong hire",
    },
    "emily-kobelenzdirienzo-QA": {
        "label": "Emily Kobelenz-DiRienzo",
        "job_type": "QA",
        "hr_scores": (1, 2, 2, 2, 3),
        "hr_total": 10,
        "hr_recommendation": "Strong no",
    },
    "natalie-emery-SME": {
        "label": "Natalie Emery",
        "job_type": "SME",
        "hr_scores": (3, 3, 4, 4, 4),
        "hr_total": 18,
        "hr_recommendation": "Strong hire",
    },
    "cynthia-taylor-SME": {
        "label": "Cynthia Taylor",
        "job_type": "SME",
        "hr_scores": (3, 3, 3, 4, 4),
        "hr_total": 17,
        "hr_recommendation": "Hire",
    },
}

# AI scores produced by the old prompt (pre-revision baseline).
# QA source: simulation run on easy-setup branch before the ranking branch changes.
# SME source: simulation run on ranking branch with QA-only rubric (before SME anchors added).
BASELINE_AI_SCORES: dict[str, dict] = {
    "leslie-doucet-QA":            {"scores": (2, 2, 2, 2, 3), "total": 11, "recommendation": "Hold"},
    "maria-ferrara-QA":            {"scores": (2, 2, 2, 3, 3), "total": 12, "recommendation": "Hold"},
    "emily-kobelenzdirienzo-QA":   {"scores": (2, 2, 2, 3, 4), "total": 13, "recommendation": "Hold"},
    "natalie-emery-SME":           {"scores": (2, 2, 3, 3, 4), "total": 14, "recommendation": "Hold"},
    "cynthia-taylor-SME":          {"scores": (4, 3, 3, 3, 4), "total": 17, "recommendation": "Advance"},
}

RUBRIC_PATH = _ROOT / "scoring_rubric.md"
FIXTURES_DIR = _ROOT / "tests" / "fixtures" / "transcripts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mae(ai: tuple[int, ...], hr: tuple[int, ...]) -> float:
    return sum(abs(a - h) for a, h in zip(ai, hr)) / len(ai)


def _direction_correct(recommendation: str, hr_recommendation: str) -> bool:
    hire = {"Strong Advance", "Advance", "Strong hire", "Hire"}
    no_hire = {"Decline", "Strong no"}
    if hr_recommendation in hire:
        return recommendation in {"Strong Advance", "Advance"}
    if hr_recommendation in no_hire:
        return recommendation == "Decline"
    return False


def _print_row(label: str, scores: tuple, total: int, rec: str) -> None:
    s = "  ".join(str(x) for x in scores)
    print(f"    Scores: {s}   Total: {total:2d}/20   Rec: {rec}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    rubric_text = RUBRIC_PATH.read_text(encoding="utf-8")

    csv_rows: list[dict] = []
    summary_mae_baseline: list[float] = []
    summary_mae_new: list[float] = []
    direction_baseline = 0
    direction_new = 0
    total_candidates = len(HR_GROUND_TRUTH)

    print("=" * 70)
    print("  Prompt Calibration Report")
    print(f"  Rubric: {RUBRIC_PATH.name}")
    print("=" * 70)

    for key, gt in HR_GROUND_TRUTH.items():
        fixture = FIXTURES_DIR / f"{key}.txt"
        if not fixture.is_file():
            print(f"\n  SKIP {gt['label']} — fixture not found: {fixture}")
            print(f"       Run: python scripts/simulate_airtable_pipeline.py --limit 3 --save-transcripts")
            total_candidates -= 1
            continue

        transcript_text = fixture.read_text(encoding="utf-8")
        job_type = gt["job_type"]

        print(f"\n{'─' * 70}")
        print(f"  Candidate : {gt['label']}  ({job_type})")
        print(f"{'─' * 70}")

        # Baseline (old prompt, pre-recorded)
        bl = BASELINE_AI_SCORES[key]
        print(f"  BASELINE (old prompt):")
        _print_row(gt["label"], bl["scores"], bl["total"], bl["recommendation"])
        bl_mae = _mae(bl["scores"], gt["hr_scores"])
        bl_dir = _direction_correct(bl["recommendation"], gt["hr_recommendation"])
        summary_mae_baseline.append(bl_mae)
        if bl_dir:
            direction_baseline += 1

        # New prompt (current analyze.py)
        print(f"  NEW (ranking branch prompt):")
        analysis = score_transcript(transcript_text, rubric_text, job_type)
        if analysis is None:
            print("    ERROR: scoring failed — check ANTHROPIC_API_KEY and API status.")
            continue

        classification = classify_candidate(analysis)
        new_scores = (
            analysis.role_fit_and_relevant_experience.score,
            analysis.domain_judgment.score,
            analysis.process_and_methodology.score,
            analysis.communication.score,
            analysis.instruction_following_and_professionalism.score,
        )
        new_total = sum(new_scores)
        new_rec = classification.recommendation
        _print_row(gt["label"], new_scores, new_total, new_rec)
        new_mae = _mae(new_scores, gt["hr_scores"])
        new_dir = _direction_correct(new_rec, gt["hr_recommendation"])
        summary_mae_new.append(new_mae)
        if new_dir:
            direction_new += 1

        # HR ground truth
        print(f"  HR GROUND TRUTH:")
        _print_row(gt["label"], gt["hr_scores"], gt["hr_total"], gt["hr_recommendation"])

        # Per-candidate delta
        mae_delta = bl_mae - new_mae
        delta_str = f"-{mae_delta:.2f} (improved)" if mae_delta > 0 else f"+{abs(mae_delta):.2f} (regressed)" if mae_delta < 0 else "0.00 (no change)"
        print(f"\n  MAE vs HR:  baseline={bl_mae:.2f}  new={new_mae:.2f}  delta={delta_str}")
        print(f"  Direction:  baseline={'correct' if bl_dir else 'WRONG'}  new={'correct' if new_dir else 'WRONG'}")

        csv_rows.append({
            "candidate": gt["label"],
            "job_type": job_type,
            "baseline_scores": ",".join(str(s) for s in bl["scores"]),
            "baseline_total": bl["total"],
            "baseline_rec": bl["recommendation"],
            "new_scores": ",".join(str(s) for s in new_scores),
            "new_total": new_total,
            "new_rec": new_rec,
            "hr_scores": ",".join(str(s) for s in gt["hr_scores"]),
            "hr_total": gt["hr_total"],
            "hr_rec": gt["hr_recommendation"],
            "baseline_mae": round(bl_mae, 3),
            "new_mae": round(new_mae, 3),
            "mae_delta": round(mae_delta, 3),
            "baseline_direction_correct": bl_dir,
            "new_direction_correct": new_dir,
        })

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------
    if not csv_rows:
        print("\nNo candidates processed. Nothing to summarise.")
        return

    n = len(csv_rows)
    avg_bl_mae = sum(summary_mae_baseline) / n if summary_mae_baseline else 0
    avg_new_mae = sum(summary_mae_new) / n if summary_mae_new else 0

    print(f"\n{'=' * 70}")
    print("  SUMMARY")
    print(f"{'─' * 70}")
    print(f"  Candidates scored      : {n}/{total_candidates}")
    print(f"  Avg MAE (baseline)     : {avg_bl_mae:.3f}")
    print(f"  Avg MAE (new)          : {avg_new_mae:.3f}")
    print(f"  MAE improvement        : {avg_bl_mae - avg_new_mae:+.3f}")
    print(f"  Direction accuracy     : baseline={direction_baseline}/{n}  new={direction_new}/{n}")

    passing = avg_new_mae < 1.0 and direction_new == n
    status = "PASS" if passing else "NEEDS WORK"
    print(f"\n  Target: MAE < 1.0 AND direction accuracy = {n}/{n}")
    print(f"  Result: {status}")
    print("=" * 70)

    # Write CSV
    out_csv = _ROOT / "compare_output.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"\n  Full results → {out_csv}")


if __name__ == "__main__":
    main()
