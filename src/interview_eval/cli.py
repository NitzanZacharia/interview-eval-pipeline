import argparse
import sys
from pathlib import Path

from . import config
from .pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="interview-eval",
        description="Evaluate recorded candidate interviews against a scoring rubric.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Directory containing .mp4 interview files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./output"),
        help="Directory for JSON and CSV output (default: ./output)",
    )
    parser.add_argument(
        "--rubric",
        type=Path,
        default=Path("./scoring_rubric.md"),
        help="Path to scoring rubric file (default: ./scoring_rubric.md)",
    )

    args = parser.parse_args()

    if not args.input_dir.is_dir():
        print(f"Error: input directory does not exist: {args.input_dir}", file=sys.stderr)
        sys.exit(1)

    if not args.rubric.is_file():
        print(f"Error: rubric file does not exist: {args.rubric}", file=sys.stderr)
        sys.exit(1)

    config.get_api_key()

    run_pipeline(args.input_dir, args.output_dir, args.rubric)
