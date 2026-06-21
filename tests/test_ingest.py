from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from interview_eval import config
from interview_eval import ingest


def _make_input_dir(tmp_path: Path) -> Path:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    return input_dir


def _touch(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_bytes(b"fake video data")
    return path


def _ffprobe_returning(duration: float):
    """Return a fake subprocess.run that emits a valid ffprobe duration."""

    def fake_run(cmd, capture_output=True, text=True):
        return mock.Mock(returncode=0, stdout=f"{duration}\n", stderr="")

    return fake_run


# --- scan_input_dir: valid filenames ---


def test_valid_filenames_accepted(tmp_path):
    input_dir = _make_input_dir(tmp_path)
    _touch(input_dir, "john-doe-SME.mp4")
    _touch(input_dir, "jane-smith-QA.mp4")

    with mock.patch("subprocess.run", side_effect=_ffprobe_returning(300.0)):
        result = ingest.scan_input_dir(input_dir)

    by_id = {c.candidate_id: c for c in result}
    assert set(by_id) == {"john-doe-SME", "jane-smith-QA"}

    john = by_id["john-doe-SME"]
    assert john.first_name == "john"
    assert john.last_name == "doe"
    assert john.job_type == "SME"
    assert john.duration_seconds == 300.0
    assert john.warnings == []

    jane = by_id["jane-smith-QA"]
    assert jane.first_name == "jane"
    assert jane.last_name == "smith"
    assert jane.job_type == "QA"


# --- scan_input_dir: invalid filenames ---


@pytest.mark.parametrize(
    "bad_name",
    [
        "JohnDoe_SME.mp4",
        "john.mp4",
        "john-doe-INVALID.mp4",
        "john-doe-sme.mp4",
    ],
)
def test_invalid_filenames_rejected_and_moved(tmp_path, bad_name):
    input_dir = _make_input_dir(tmp_path)
    _touch(input_dir, bad_name)

    with mock.patch("subprocess.run", side_effect=_ffprobe_returning(300.0)):
        result = ingest.scan_input_dir(input_dir)

    assert result == []
    assert not (input_dir / bad_name).exists()
    bad_dir = input_dir.parent / "bad_name_conv"
    assert (bad_dir / bad_name).exists()


def test_invalid_does_not_block_valid(tmp_path):
    input_dir = _make_input_dir(tmp_path)
    _touch(input_dir, "john-doe-SME.mp4")
    _touch(input_dir, "JohnDoe_SME.mp4")

    with mock.patch("subprocess.run", side_effect=_ffprobe_returning(300.0)):
        result = ingest.scan_input_dir(input_dir)

    assert [c.candidate_id for c in result] == ["john-doe-SME"]
    assert (input_dir.parent / "bad_name_conv" / "JohnDoe_SME.mp4").exists()


# --- scan_input_dir: already processed ---


def test_already_processed_skipped(tmp_path):
    input_dir = _make_input_dir(tmp_path)
    _touch(input_dir, "john-doe-SME.mp4")

    processed_dir = input_dir.parent / "processed"
    processed_dir.mkdir()
    _touch(processed_dir, "john-doe-SME.mp4")

    with mock.patch("subprocess.run", side_effect=_ffprobe_returning(300.0)):
        result = ingest.scan_input_dir(input_dir)

    assert result == []
    # The unprocessed copy is left in place (skipped, not moved).
    assert (input_dir / "john-doe-SME.mp4").exists()


# --- scan_input_dir: duration warnings ---


def test_duration_below_minimum_warns_but_included(tmp_path):
    input_dir = _make_input_dir(tmp_path)
    _touch(input_dir, "john-doe-SME.mp4")

    short = config.MIN_DURATION_SECONDS - 1
    with mock.patch("subprocess.run", side_effect=_ffprobe_returning(short)):
        result = ingest.scan_input_dir(input_dir)

    assert len(result) == 1
    cand = result[0]
    assert cand.duration_seconds == short
    assert len(cand.warnings) == 1
    assert "duration" in cand.warnings[0].lower()


def test_duration_above_maximum_warns_but_included(tmp_path):
    input_dir = _make_input_dir(tmp_path)
    _touch(input_dir, "john-doe-SME.mp4")

    long = config.MAX_DURATION_SECONDS + 1
    with mock.patch("subprocess.run", side_effect=_ffprobe_returning(long)):
        result = ingest.scan_input_dir(input_dir)

    assert len(result) == 1
    assert len(result[0].warnings) == 1
    assert "duration" in result[0].warnings[0].lower()


def test_duration_in_range_no_warning(tmp_path):
    input_dir = _make_input_dir(tmp_path)
    _touch(input_dir, "john-doe-SME.mp4")

    with mock.patch("subprocess.run", side_effect=_ffprobe_returning(300.0)):
        result = ingest.scan_input_dir(input_dir)

    assert result[0].warnings == []


def test_duration_failure_warns_but_included(tmp_path):
    input_dir = _make_input_dir(tmp_path)
    _touch(input_dir, "john-doe-SME.mp4")

    failing = mock.Mock(returncode=1, stdout="", stderr="boom")
    with mock.patch("subprocess.run", return_value=failing):
        result = ingest.scan_input_dir(input_dir)

    assert len(result) == 1
    assert result[0].duration_seconds is None
    assert len(result[0].warnings) == 1


# --- sibling directory creation ---


def test_sibling_dirs_created(tmp_path):
    input_dir = _make_input_dir(tmp_path)

    with mock.patch("subprocess.run", side_effect=_ffprobe_returning(300.0)):
        ingest.scan_input_dir(input_dir)

    assert (input_dir.parent / "bad_name_conv").is_dir()
    assert (input_dir.parent / "processed").is_dir()


# --- get_video_duration ---


def test_get_video_duration_success(tmp_path):
    path = _touch(tmp_path, "john-doe-SME.mp4")
    ok = mock.Mock(returncode=0, stdout="123.45\n", stderr="")
    with mock.patch("subprocess.run", return_value=ok):
        assert ingest.get_video_duration(path) == 123.45


def test_get_video_duration_nonzero_return(tmp_path):
    path = _touch(tmp_path, "john-doe-SME.mp4")
    bad = mock.Mock(returncode=1, stdout="", stderr="err")
    with mock.patch("subprocess.run", return_value=bad):
        assert ingest.get_video_duration(path) is None


def test_get_video_duration_unparseable_output(tmp_path):
    path = _touch(tmp_path, "john-doe-SME.mp4")
    junk = mock.Mock(returncode=0, stdout="not-a-number\n", stderr="")
    with mock.patch("subprocess.run", return_value=junk):
        assert ingest.get_video_duration(path) is None


def test_get_video_duration_ffprobe_missing(tmp_path):
    path = _touch(tmp_path, "john-doe-SME.mp4")
    with mock.patch("subprocess.run", side_effect=FileNotFoundError):
        assert ingest.get_video_duration(path) is None


# --- move_to_processed ---


def test_move_to_processed_moves_file(tmp_path):
    input_dir = _make_input_dir(tmp_path)
    path = _touch(input_dir, "john-doe-SME.mp4")

    ingest.move_to_processed(path, input_dir)

    processed = input_dir.parent / "processed" / "john-doe-SME.mp4"
    assert processed.exists()
    assert not path.exists()
    assert processed.read_bytes() == b"fake video data"


def test_move_to_processed_creates_dir(tmp_path):
    input_dir = _make_input_dir(tmp_path)
    path = _touch(input_dir, "john-doe-SME.mp4")
    assert not (input_dir.parent / "processed").exists()

    ingest.move_to_processed(path, input_dir)

    assert (input_dir.parent / "processed").is_dir()
