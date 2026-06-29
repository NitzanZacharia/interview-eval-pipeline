"""
tests/test_airtable_pipeline.py

Unit tests for process_record() in airtable_pipeline.py.
Focus: rubric source-of-truth priority (local file > Airtable).
All heavy steps (transcription, scoring, write-back) are mocked.
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from interview_eval.airtable_ingest import F_CANDIDATE_NAME, F_FILES, F_RUBRIC_LINK
from interview_eval.airtable_pipeline import process_record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(rubric_ids: list | None = None) -> dict:
    fields: dict = {
        F_CANDIDATE_NAME: ["Jane Smith - QA Specialist"],
        F_FILES: [],
    }
    if rubric_ids:
        fields[F_RUBRIC_LINK] = rubric_ids
    return {"id": "recTEST123", "fields": fields}


def _stub_pipeline(monkeypatch) -> mock.Mock:
    """
    Stub everything downstream of the rubric step so tests run instantly.
    Returns the mock for fetch_rubric_text so callers can assert on it.
    """
    fake_candidate = mock.Mock()
    fake_candidate.path = Path("/tmp/fake.mp4")
    fake_candidate.duration_seconds = 120.0
    fake_candidate.warnings = []

    monkeypatch.setattr(
        "interview_eval.airtable_pipeline.build_candidate_file_from_path",
        lambda *a, **kw: fake_candidate,
    )

    fetch_rubric_mock = mock.Mock(return_value="airtable rubric text")
    monkeypatch.setattr(
        "interview_eval.airtable_pipeline.fetch_rubric_text",
        fetch_rubric_mock,
    )

    fake_transcript = mock.Mock()
    fake_transcript.failed = False
    fake_transcript.word_count = 50
    fake_transcript.text = "transcript text"
    monkeypatch.setattr(
        "interview_eval.airtable_pipeline.transcribe_video",
        lambda *a: fake_transcript,
    )

    fake_analysis = mock.Mock()
    monkeypatch.setattr(
        "interview_eval.airtable_pipeline.score_transcript",
        lambda *a: fake_analysis,
    )

    fake_classification = mock.Mock()
    fake_classification.recommendation = "Hold"
    monkeypatch.setattr(
        "interview_eval.airtable_pipeline.classify_candidate",
        lambda *a: fake_classification,
    )

    monkeypatch.setattr(
        "interview_eval.airtable_pipeline.write_scores_to_airtable",
        mock.Mock(),
    )
    monkeypatch.setattr(
        "interview_eval.airtable_pipeline._write_local_outputs",
        mock.Mock(),
    )
    monkeypatch.setattr(
        "interview_eval.airtable_pipeline._print_result",
        mock.Mock(),
    )
    monkeypatch.setattr(
        "interview_eval.airtable_pipeline.CandidateResult",
        mock.Mock(from_pipeline=mock.Mock(return_value=mock.Mock(
            recommendation="Hold",
            scores=mock.Mock(),
            model_dump=mock.Mock(return_value={}),
        ))),
    )

    return fetch_rubric_mock


# ---------------------------------------------------------------------------
# Rubric priority tests
# ---------------------------------------------------------------------------

class TestRubricPriority:
    def test_local_file_used_even_when_airtable_link_present(self, tmp_path, monkeypatch):
        """Local scoring_rubric.md must win over a linked Airtable rubric record."""
        fetch_rubric_mock = _stub_pipeline(monkeypatch)

        local_rubric = tmp_path / "scoring_rubric.md"
        local_rubric.write_text("# Local calibrated rubric", encoding="utf-8")

        record = _make_record(rubric_ids=["recRUBRIC1"])
        video = tmp_path / "fake.mp4"
        video.write_bytes(b"fake")

        process_record(
            record=record,
            airtable_key="fake_key",
            download_dir=tmp_path,
            fallback_rubric_path=local_rubric,
            output_dir=tmp_path,
            write_back=False,
            video_path=video,
        )

        fetch_rubric_mock.assert_not_called()

    def test_local_content_is_passed_to_scorer(self, tmp_path, monkeypatch):
        """The exact text from the local file must reach score_transcript."""
        _stub_pipeline(monkeypatch)

        local_rubric = tmp_path / "scoring_rubric.md"
        local_rubric.write_text("# My calibrated rubric content", encoding="utf-8")

        captured = {}

        def capture_score(transcript_text, rubric_text, job_type):
            captured["rubric"] = rubric_text
            return mock.Mock()

        monkeypatch.setattr(
            "interview_eval.airtable_pipeline.score_transcript",
            capture_score,
        )

        record = _make_record()
        video = tmp_path / "fake.mp4"
        video.write_bytes(b"fake")

        process_record(
            record=record,
            airtable_key="fake_key",
            download_dir=tmp_path,
            fallback_rubric_path=local_rubric,
            output_dir=tmp_path,
            write_back=False,
            video_path=video,
        )

        assert captured["rubric"] == "# My calibrated rubric content"

    def test_falls_back_to_airtable_when_local_missing(self, tmp_path, monkeypatch):
        """When local file is absent, Airtable rubric must be fetched."""
        fetch_rubric_mock = _stub_pipeline(monkeypatch)

        missing_path = tmp_path / "nonexistent_rubric.md"  # does not exist
        record = _make_record(rubric_ids=["recRUBRIC1"])
        video = tmp_path / "fake.mp4"
        video.write_bytes(b"fake")

        process_record(
            record=record,
            airtable_key="fake_key",
            download_dir=tmp_path,
            fallback_rubric_path=missing_path,
            output_dir=tmp_path,
            write_back=False,
            video_path=video,
        )

        fetch_rubric_mock.assert_called_once_with(["recRUBRIC1"], "fake_key")

    def test_returns_none_when_no_rubric_available(self, tmp_path, monkeypatch):
        """No local file and no Airtable link → process_record returns None."""
        _stub_pipeline(monkeypatch)

        missing_path = tmp_path / "nonexistent_rubric.md"
        record = _make_record(rubric_ids=None)  # no Airtable link either
        video = tmp_path / "fake.mp4"
        video.write_bytes(b"fake")

        result = process_record(
            record=record,
            airtable_key="fake_key",
            download_dir=tmp_path,
            fallback_rubric_path=missing_path,
            output_dir=tmp_path,
            write_back=False,
            video_path=video,
        )

        assert result is None
