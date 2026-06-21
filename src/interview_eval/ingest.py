from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from . import config
from .models import CandidateFile


def get_video_duration(path: Path) -> Optional[float]:
    """Return the duration of a video in seconds, or None on failure."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    raw = result.stdout.strip()
    if not raw:
        return None

    try:
        return float(raw)
    except ValueError:
        return None


def move_to_processed(path: Path, input_dir: Path) -> None:
    """Move a .mp4 from the input dir to the sibling ``processed/`` directory."""
    processed_dir = input_dir.parent / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(processed_dir / path.name))


def _parse_filename(stem: str) -> tuple[str, str, str]:
    """Split a validated filename stem into (first_name, last_name, job_type).

    The filename matches ``^[a-z]+-[a-z]+-(?:SME|QA)$`` so it is exactly three
    hyphen-separated segments.
    """
    left, job_type = stem.rsplit("-", 1)
    first_name, last_name = left.rsplit("-", 1)
    return first_name, last_name, job_type


def scan_input_dir(input_dir: Path) -> list[CandidateFile]:
    """Scan ``input_dir`` for .mp4 files and return valid CandidateFile objects.

    Invalid filenames are moved to the sibling ``bad_name_conv/`` directory.
    Files already present in the sibling ``processed/`` directory are skipped.
    Durations outside the configured range produce a warning but the file is
    still included.
    """
    bad_name_dir = input_dir.parent / "bad_name_conv"
    processed_dir = input_dir.parent / "processed"
    bad_name_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[CandidateFile] = []

    for path in sorted(input_dir.glob("*.mp4")):
        if not path.is_file():
            continue

        if not config.FILENAME_PATTERN.match(path.name):
            shutil.move(str(path), str(bad_name_dir / path.name))
            continue

        if (processed_dir / path.name).exists():
            continue

        first_name, last_name, job_type = _parse_filename(path.stem)

        warnings: list[str] = []
        duration = get_video_duration(path)
        if duration is None:
            warnings.append(
                f"Could not determine duration for {path.name}."
            )
        elif duration < config.MIN_DURATION_SECONDS:
            warnings.append(
                f"Video duration {duration:.1f}s is below the minimum of "
                f"{config.MIN_DURATION_SECONDS}s."
            )
        elif duration > config.MAX_DURATION_SECONDS:
            warnings.append(
                f"Video duration {duration:.1f}s is above the maximum of "
                f"{config.MAX_DURATION_SECONDS}s."
            )

        candidates.append(
            CandidateFile(
                path=path,
                first_name=first_name,
                last_name=last_name,
                job_type=job_type,
                duration_seconds=duration,
                warnings=warnings,
            )
        )

    return candidates
