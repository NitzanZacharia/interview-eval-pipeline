import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import config
from .pipeline import run_pipeline


def main() -> None:
    load_dotenv()
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
        default=None,
        help=(
            "Path to a scoring rubric file. If omitted, scoring_rubric_QA.md or "
            "scoring_rubric_SME.md is selected automatically per candidate, falling "
            "back to scoring_rubric.md."
        ),
    )

    args = parser.parse_args()

    if not args.input_dir.is_dir():
        print(f"Error: input directory does not exist: {args.input_dir}", file=sys.stderr)
        sys.exit(1)

    explicit_rubric = args.rubric is not None
    rubric_path = args.rubric if explicit_rubric else Path("./scoring_rubric.md")

    if explicit_rubric and not rubric_path.is_file():
        print(f"Error: rubric file does not exist: {rubric_path}", file=sys.stderr)
        sys.exit(1)

    config.get_api_key()

    run_pipeline(args.input_dir, args.output_dir, rubric_path, explicit_rubric=explicit_rubric)
