"""
tests/test_airtable_ingest.py

Unit tests for airtable_ingest.py.
All network calls are mocked — no real Airtable credentials needed.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest
import requests

# Make the src layout importable when pytest is run from the project root
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from interview_eval.airtable_ingest import (
    F_CANDIDATE_NAME,
    F_FILES,
    F_RUBRIC_LINK,
    F_SCORE_1,
    _derive_job_type,
    _get,
    _parse_name,
    airtable_record_to_candidate_file,
    download_video,
    fetch_rubric_text,
    fetch_single_record,
    fetch_unscored_video_submissions,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_record(
    record_id: str = "recABC123",
    candidate_names: list | None = None,
    attachments: list | None = None,
    rubric_ids: list | None = None,
    score_1=None,
) -> dict:
    """Build a minimal Airtable record dict."""
    if candidate_names is None:
        candidate_names = ["John Doe - QA Specialist"]
    if attachments is None:
        attachments = [
            {
                "id": "attXXX",
                "url": "https://example.com/video.mp4",
                "filename": "john-doe-QA.mp4",
                "type": "video/mp4",
                "size": 1024,
            }
        ]
    fields: dict = {
        F_CANDIDATE_NAME: candidate_names,
        F_FILES: attachments,
    }
    if rubric_ids is not None:
        fields[F_RUBRIC_LINK] = [{"id": rid} for rid in rubric_ids]
    if score_1 is not None:
        fields[F_SCORE_1] = score_1
    return {"id": record_id, "fields": fields}


def _make_rubric_fields() -> dict:
    return {
        "fldHiXGCAYNLjw9Z8": "Test Rubric",
        "fldVvpbMNMthzLoUG": "Role Fit and Relevant Experience",
        "fldAwcAmWCP2Kyb9V": "Domain Judgment",
        "fldFmG2yJJqDl5AOx": "Process and Methodology",
        "fldv2ila1djNoMtvx": "Communication",
        "fldcbFBcOkZ7p8Xzj": "Instruction Following",
        "fldB5zVKKwBz3CX4B": 1,
        "fldLHsiodYNfb1MRj": 1,
        "fldr2ATD0qU40A4IO": 1,
        "fldmvQiVSZQwBIHUr": 1,
        "fldFpLBJTyWxE36HZ": 1,
        "fldfKyXGXJLTdEJlB": 14,
        "fld9dtMu2Rj5vN41o": [
            {"name": "Did not answer all questions"},
            {"name": "Lacks core experience"},
        ],
    }


# ---------------------------------------------------------------------------
# _parse_name
# ---------------------------------------------------------------------------

class TestParseName:
    def test_standard_full_name(self):
        first, last = _parse_name(["Emily Kobelenz - QA Specialist"])
        assert first == "emily"
        assert last == "kobelenz"

    def test_hyphenated_name_stripped(self):
        # "Kobelenz-DiRienzo" is one whitespace token; hyphens are stripped
        # so the last name becomes "kobelenzdirienzo"
        first, last = _parse_name(["Emily Kobelenz-DiRienzo - QA Specialist"])
        assert first == "emily"
        assert last == "kobelenzdirienzo"

    def test_single_word_name(self):
        # Only one token → first and last are the same word
        first, last = _parse_name(["Madonna - SME"])
        assert first == "madonna"
        assert last == "madonna"

    def test_empty_list_returns_unknown(self):
        first, last = _parse_name([])
        assert first == "unknown"
        assert last == "unknown"

    def test_none_characters_stripped(self):
        first, last = _parse_name(["John123 Doe456 - SME"])
        assert first == "john"
        assert last == "doe"

    def test_no_role_separator(self):
        # No " - " separator — whole string is treated as name
        first, last = _parse_name(["John Doe"])
        assert first == "john"
        assert last == "doe"


# ---------------------------------------------------------------------------
# _derive_job_type
# ---------------------------------------------------------------------------

class TestDeriveJobType:
    def test_qa_keyword(self):
        assert _derive_job_type(["Sam Carver - QA Specialist"]) == "QA"

    def test_quality_keyword(self):
        assert _derive_job_type(["Sam Carver - Quality Analyst"]) == "QA"

    def test_sme_default(self):
        assert _derive_job_type(["Jane Smith - Math Curriculum Writer"]) == "SME"

    def test_empty_list_defaults_sme(self):
        assert _derive_job_type([]) == "SME"

    def test_case_sensitivity_qa_uppercase(self):
        # "QA" must be uppercase in the lookup value to match
        assert _derive_job_type(["qa specialist"]) == "SME"   # lowercase → SME


# ---------------------------------------------------------------------------
# _get (internal HTTP helper)
# ---------------------------------------------------------------------------

class TestInternalGet:
    def test_returns_json_on_200(self):
        fake_resp = mock.Mock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"records": []}
        fake_resp.raise_for_status = mock.Mock()

        with mock.patch("interview_eval.airtable_ingest.requests.get", return_value=fake_resp):
            result = _get("https://example.com", {}, "fake_key")
        assert result == {"records": []}

    def test_retries_on_429_then_succeeds(self):
        rate_limited = mock.Mock()
        rate_limited.status_code = 429
        rate_limited.raise_for_status = mock.Mock()

        success = mock.Mock()
        success.status_code = 200
        success.json.return_value = {"records": ["x"]}
        success.raise_for_status = mock.Mock()

        with mock.patch(
            "interview_eval.airtable_ingest.requests.get",
            side_effect=[rate_limited, success],
        ), mock.patch("interview_eval.airtable_ingest.time.sleep"):
            result = _get("https://example.com", {}, "fake_key")
        assert result == {"records": ["x"]}

    def test_raises_on_401(self):
        fake_resp = mock.Mock()
        fake_resp.status_code = 401
        fake_resp.raise_for_status.side_effect = requests.HTTPError("401")

        with mock.patch("interview_eval.airtable_ingest.requests.get", return_value=fake_resp):
            with pytest.raises(requests.HTTPError):
                _get("https://example.com", {}, "bad_key")


# ---------------------------------------------------------------------------
# fetch_unscored_video_submissions
# ---------------------------------------------------------------------------

class TestFetchUnscoredVideoSubmissions:
    def _mock_get(self, records: list, offset: str | None = None):
        payload = {"records": records}
        if offset:
            payload["offset"] = offset

        fake_resp = mock.Mock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = payload
        fake_resp.raise_for_status = mock.Mock()
        return fake_resp

    def test_returns_records(self):
        record = _make_record()
        with mock.patch(
            "interview_eval.airtable_ingest.requests.get",
            return_value=self._mock_get([record]),
        ):
            results = fetch_unscored_video_submissions("fake_key")
        assert len(results) == 1
        assert results[0]["id"] == "recABC123"

    def test_paginates_via_offset(self):
        page1_resp = mock.Mock()
        page1_resp.status_code = 200
        page1_resp.json.return_value = {
            "records": [_make_record("rec001")],
            "offset": "cursor_xyz",
        }
        page1_resp.raise_for_status = mock.Mock()

        page2_resp = mock.Mock()
        page2_resp.status_code = 200
        page2_resp.json.return_value = {"records": [_make_record("rec002")]}
        page2_resp.raise_for_status = mock.Mock()

        with mock.patch(
            "interview_eval.airtable_ingest.requests.get",
            side_effect=[page1_resp, page2_resp],
        ):
            results = fetch_unscored_video_submissions("fake_key")

        assert len(results) == 2
        assert {r["id"] for r in results} == {"rec001", "rec002"}

    def test_returns_empty_list_when_no_records(self):
        with mock.patch(
            "interview_eval.airtable_ingest.requests.get",
            return_value=self._mock_get([]),
        ):
            results = fetch_unscored_video_submissions("fake_key")
        assert results == []


# ---------------------------------------------------------------------------
# fetch_single_record
# ---------------------------------------------------------------------------

class TestFetchSingleRecord:
    def test_fetches_by_record_id(self):
        record = _make_record("recSPECIFIC")
        fake_resp = mock.Mock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = record
        fake_resp.raise_for_status = mock.Mock()

        with mock.patch(
            "interview_eval.airtable_ingest.requests.get", return_value=fake_resp
        ) as mock_get:
            result = fetch_single_record("recSPECIFIC", "fake_key")

        assert result["id"] == "recSPECIFIC"
        # Confirm the URL contains the record ID
        call_url = mock_get.call_args[0][0]
        assert "recSPECIFIC" in call_url


# ---------------------------------------------------------------------------
# download_video
# ---------------------------------------------------------------------------

class TestDownloadVideo:
    def test_writes_file_to_dest(self, tmp_path):
        fake_content = b"fake video bytes"
        attachment = {
            "url": "https://example.com/video.mp4",
            "filename": "test-video.mp4",
        }

        mock_resp = mock.MagicMock()
        mock_resp.__enter__ = mock.Mock(return_value=mock_resp)
        mock_resp.__exit__ = mock.Mock(return_value=False)
        mock_resp.raise_for_status = mock.Mock()
        mock_resp.iter_content = mock.Mock(return_value=[fake_content])

        with mock.patch("interview_eval.airtable_ingest.requests.get", return_value=mock_resp):
            result = download_video(attachment, tmp_path)

        assert result == tmp_path / "test-video.mp4"
        assert result.exists()
        assert result.read_bytes() == fake_content

    def test_raises_on_http_error(self, tmp_path):
        attachment = {"url": "https://example.com/gone.mp4", "filename": "gone.mp4"}

        mock_resp = mock.MagicMock()
        mock_resp.__enter__ = mock.Mock(return_value=mock_resp)
        mock_resp.__exit__ = mock.Mock(return_value=False)
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404")

        with mock.patch("interview_eval.airtable_ingest.requests.get", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                download_video(attachment, tmp_path)

    def test_uses_fallback_filename(self, tmp_path):
        attachment = {"url": "https://example.com/video.mp4"}   # no "filename" key

        mock_resp = mock.MagicMock()
        mock_resp.__enter__ = mock.Mock(return_value=mock_resp)
        mock_resp.__exit__ = mock.Mock(return_value=False)
        mock_resp.raise_for_status = mock.Mock()
        mock_resp.iter_content = mock.Mock(return_value=[b"data"])

        with mock.patch("interview_eval.airtable_ingest.requests.get", return_value=mock_resp):
            result = download_video(attachment, tmp_path)

        assert result.name == "video.mp4"


# ---------------------------------------------------------------------------
# airtable_record_to_candidate_file
# ---------------------------------------------------------------------------

class TestAirtableRecordToCandidateFile:
    def _fake_download(self, attachment, dest_dir):
        """Write a tiny fake file without hitting the network."""
        dest = dest_dir / attachment.get("filename", "video.mp4")
        dest.write_bytes(b"fake")
        return dest

    def test_happy_path(self, tmp_path):
        record = _make_record(
            candidate_names=["Jane Smith - QA Specialist"],
            attachments=[{
                "id": "attXXX",
                "url": "https://example.com/video.mp4",
                "filename": "jane-smith-QA.mp4",
                "type": "video/mp4",
                "size": 512,
            }],
        )

        with mock.patch(
            "interview_eval.airtable_ingest.download_video",
            side_effect=self._fake_download,
        ), mock.patch(
            "interview_eval.airtable_ingest.get_video_duration",
            return_value=300.0,
        ):
            result = airtable_record_to_candidate_file(record, tmp_path)

        assert result is not None
        candidate, record_id = result
        assert candidate.first_name == "jane"
        assert candidate.last_name  == "smith"
        assert candidate.job_type   == "QA"
        assert candidate.duration_seconds == 300.0
        assert candidate.warnings == []
        assert record_id == "recABC123"

    def test_returns_none_when_no_attachments(self, tmp_path):
        record = _make_record(attachments=[])
        result = airtable_record_to_candidate_file(record, tmp_path)
        assert result is None

    def test_returns_none_when_download_fails(self, tmp_path):
        record = _make_record()

        with mock.patch(
            "interview_eval.airtable_ingest.download_video",
            side_effect=Exception("network error"),
        ):
            result = airtable_record_to_candidate_file(record, tmp_path)

        assert result is None

    def test_duration_warning_below_minimum(self, tmp_path):
        record = _make_record()

        with mock.patch(
            "interview_eval.airtable_ingest.download_video",
            side_effect=self._fake_download,
        ), mock.patch(
            "interview_eval.airtable_ingest.get_video_duration",
            return_value=30.0,  # well below 120s minimum
        ):
            result = airtable_record_to_candidate_file(record, tmp_path)

        assert result is not None
        candidate, _ = result
        assert len(candidate.warnings) == 1
        assert "below" in candidate.warnings[0].lower()

    def test_duration_warning_above_maximum(self, tmp_path):
        record = _make_record()

        with mock.patch(
            "interview_eval.airtable_ingest.download_video",
            side_effect=self._fake_download,
        ), mock.patch(
            "interview_eval.airtable_ingest.get_video_duration",
            return_value=700.0,  # above 600s maximum
        ):
            result = airtable_record_to_candidate_file(record, tmp_path)

        assert result is not None
        candidate, _ = result
        assert len(candidate.warnings) == 1
        assert "above" in candidate.warnings[0].lower()

    def test_duration_none_produces_warning(self, tmp_path):
        record = _make_record()

        with mock.patch(
            "interview_eval.airtable_ingest.download_video",
            side_effect=self._fake_download,
        ), mock.patch(
            "interview_eval.airtable_ingest.get_video_duration",
            return_value=None,
        ):
            result = airtable_record_to_candidate_file(record, tmp_path)

        assert result is not None
        candidate, _ = result
        assert len(candidate.warnings) == 1
        assert "duration" in candidate.warnings[0].lower()

    def test_prefers_video_mime_type_attachment(self, tmp_path):
        """When multiple attachments exist, the video/* one must be chosen."""
        attachments = [
            {
                "id": "att1",
                "url": "https://example.com/rubric.pdf",
                "filename": "rubric.pdf",
                "type": "application/pdf",
                "size": 100,
            },
            {
                "id": "att2",
                "url": "https://example.com/video.mp4",
                "filename": "interview.mp4",
                "type": "video/mp4",
                "size": 200,
            },
        ]
        record = _make_record(attachments=attachments)

        chosen_attachment: dict = {}

        def capture_download(attachment, dest_dir):
            chosen_attachment.update(attachment)
            dest = dest_dir / attachment.get("filename", "video.mp4")
            dest.write_bytes(b"fake")
            return dest

        with mock.patch(
            "interview_eval.airtable_ingest.download_video",
            side_effect=capture_download,
        ), mock.patch(
            "interview_eval.airtable_ingest.get_video_duration",
            return_value=300.0,
        ):
            airtable_record_to_candidate_file(record, tmp_path)

        assert chosen_attachment.get("type") == "video/mp4"
        assert chosen_attachment.get("filename") == "interview.mp4"


# ---------------------------------------------------------------------------
# fetch_rubric_text
# ---------------------------------------------------------------------------

class TestFetchRubricText:
    def _mock_rubric_response(self, fields: dict | None = None):
        fake_resp = mock.Mock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"fields": fields or _make_rubric_fields()}
        fake_resp.raise_for_status = mock.Mock()
        return fake_resp

    def test_returns_empty_string_for_empty_ids(self):
        result = fetch_rubric_text([], "fake_key")
        assert result == ""

    def test_assembles_markdown_with_criteria(self):
        with mock.patch(
            "interview_eval.airtable_ingest.requests.get",
            return_value=self._mock_rubric_response(),
        ):
            rubric_md = fetch_rubric_text(["recRUBRIC1"], "fake_key")

        assert "Role Fit and Relevant Experience" in rubric_md
        assert "Domain Judgment" in rubric_md
        assert "Process and Methodology" in rubric_md
        assert "Communication" in rubric_md
        assert "Instruction Following" in rubric_md

    def test_includes_passing_threshold(self):
        with mock.patch(
            "interview_eval.airtable_ingest.requests.get",
            return_value=self._mock_rubric_response(),
        ):
            rubric_md = fetch_rubric_text(["recRUBRIC1"], "fake_key")

        assert "14" in rubric_md   # the passing threshold value

    def test_includes_hard_fail_rules(self):
        with mock.patch(
            "interview_eval.airtable_ingest.requests.get",
            return_value=self._mock_rubric_response(),
        ):
            rubric_md = fetch_rubric_text(["recRUBRIC1"], "fake_key")

        assert "Did not answer all questions" in rubric_md
        assert "Lacks core experience" in rubric_md

    def test_uses_first_rubric_id_only(self):
        """Confirm only one API call is made even when multiple IDs are passed."""
        with mock.patch(
            "interview_eval.airtable_ingest.requests.get",
            return_value=self._mock_rubric_response(),
        ) as mock_get:
            fetch_rubric_text(["recRUBRIC1", "recRUBRIC2"], "fake_key")

        assert mock_get.call_count == 1
        call_url = mock_get.call_args[0][0]
        assert "recRUBRIC1" in call_url
        assert "recRUBRIC2" not in call_url

    def test_handles_missing_hard_fail_rules(self):
        fields = _make_rubric_fields()
        fields["fld9dtMu2Rj5vN41o"] = []   # no hard fail rules defined

        with mock.patch(
            "interview_eval.airtable_ingest.requests.get",
            return_value=self._mock_rubric_response(fields),
        ):
            rubric_md = fetch_rubric_text(["recRUBRIC1"], "fake_key")

        assert "None defined." in rubric_md

    def test_rubric_name_included(self):
        with mock.patch(
            "interview_eval.airtable_ingest.requests.get",
            return_value=self._mock_rubric_response(),
        ):
            rubric_md = fetch_rubric_text(["recRUBRIC1"], "fake_key")

        assert "Test Rubric" in rubric_md