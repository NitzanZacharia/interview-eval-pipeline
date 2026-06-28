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
sys.path.insert(0, str(_ROOT / "src"))  # make src/ importable when run directly

from interview_eval.airtable_ingest import (
    fetch_single_record,
    fetch_unscored_video_submissions,
)
from interview_eval.airtable_pipeline import process_record


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
    print("  Airtable Pipeline")
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
            result_dict = process_record(
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