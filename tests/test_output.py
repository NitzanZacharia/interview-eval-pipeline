from __future__ import annotations

import csv
from pathlib import Path

from interview_eval.models import (
    CandidateFile,
    CandidateResult,
    ClassificationResult,
    DimensionScore,
    HardFailFlags,
    RubricAnalysis,
    TranscriptResult,
)
from interview_eval.output import write_batch_csv, write_candidate_report


def _make_result(candidate_id: str, recommendation: str = "Advance") -> CandidateResult:
    dim = DimensionScore(score=3, quotes=[], rationale="ok")
    analysis = RubricAnalysis(
        role_fit_and_relevant_experience=dim,
        domain_judgment=dim,
        process_and_methodology=dim,
        communication=dim,
        instruction_following_and_professionalism=dim,
        hard_fail_flags=HardFailFlags(),
        confidence_score=0.8,
        overall_summary="Good.",
    )
    parts = candidate_id.rsplit("-", 1)
    first, last = parts[0].split("-", 1)
    job_type = parts[1]
    candidate = CandidateFile(
        path=Path(f"{candidate_id}.mp4"),
        first_name=first,
        last_name=last,
        job_type=job_type,
        duration_seconds=300.0,
    )
    transcript = TranscriptResult(text="test", word_count=1, duration_seconds=300.0)
    classification = ClassificationResult(recommendation=recommendation, reason="ok")
    return CandidateResult.from_pipeline(candidate, transcript, analysis, classification)


def _read_csv_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# --- write_batch_csv: cumulative append ---


def test_batch_csv_creates_new_file(tmp_path):
    results = [_make_result("john-doe-SME")]
    path = write_batch_csv(results, tmp_path)
    rows = _read_csv_rows(path)
    assert len(rows) == 1
    assert rows[0]["candidate_id"] == "john-doe-SME"


def test_batch_csv_appends_to_existing(tmp_path):
    write_batch_csv([_make_result("john-doe-SME")], tmp_path)
    write_batch_csv([_make_result("jane-smith-QA")], tmp_path)

    rows = _read_csv_rows(tmp_path / "batch_summary.csv")
    assert len(rows) == 2
    assert rows[0]["candidate_id"] == "john-doe-SME"
    assert rows[1]["candidate_id"] == "jane-smith-QA"


def test_batch_csv_header_written_once(tmp_path):
    write_batch_csv([_make_result("john-doe-SME")], tmp_path)
    write_batch_csv([_make_result("jane-smith-QA")], tmp_path)
    write_batch_csv([_make_result("bob-jones-SME")], tmp_path)

    text = (tmp_path / "batch_summary.csv").read_text(encoding="utf-8")
    header_count = text.count("candidate_id,first_name,last_name")
    assert header_count == 1


def test_batch_csv_multiple_results_per_batch(tmp_path):
    batch1 = [_make_result("john-doe-SME"), _make_result("jane-smith-QA")]
    batch2 = [_make_result("bob-jones-SME")]
    write_batch_csv(batch1, tmp_path)
    write_batch_csv(batch2, tmp_path)

    rows = _read_csv_rows(tmp_path / "batch_summary.csv")
    assert len(rows) == 3


def test_batch_csv_empty_batch_no_extra_rows(tmp_path):
    write_batch_csv([_make_result("john-doe-SME")], tmp_path)
    write_batch_csv([], tmp_path)

    rows = _read_csv_rows(tmp_path / "batch_summary.csv")
    assert len(rows) == 1


def test_batch_csv_empty_first_run(tmp_path):
    write_batch_csv([], tmp_path)
    rows = _read_csv_rows(tmp_path / "batch_summary.csv")
    assert len(rows) == 0

    write_batch_csv([_make_result("john-doe-SME")], tmp_path)
    rows = _read_csv_rows(tmp_path / "batch_summary.csv")
    assert len(rows) == 1


# --- write_candidate_report ---


def test_report_creates_html_file(tmp_path):
    result = _make_result("john-doe-SME")
    path = write_candidate_report(result, tmp_path)
    assert path.suffix == ".html"
    assert path.exists()
    assert path.stat().st_size > 0


def test_report_contains_candidate_name(tmp_path):
    result = _make_result("john-doe-SME")
    path = write_candidate_report(result, tmp_path)
    html = path.read_text(encoding="utf-8")
    assert "John" in html
    assert "Doe" in html


def test_report_contains_recommendation(tmp_path):
    result = _make_result("john-doe-SME", recommendation="Advance")
    html = write_candidate_report(result, tmp_path).read_text(encoding="utf-8")
    assert "Advance to Interview" in html


def test_report_contains_hold_recommendation(tmp_path):
    result = _make_result("jane-smith-QA", recommendation="Hold")
    html = write_candidate_report(result, tmp_path).read_text(encoding="utf-8")
    assert "Hold for Discussion" in html


def test_report_contains_decline_recommendation(tmp_path):
    result = _make_result("jane-smith-QA", recommendation="Decline")
    html = write_candidate_report(result, tmp_path).read_text(encoding="utf-8")
    assert "Decline" in html


def test_report_contains_score_breakdown(tmp_path):
    result = _make_result("john-doe-SME")
    html = write_candidate_report(result, tmp_path).read_text(encoding="utf-8")
    assert "Role Fit" in html
    assert "Domain Judgment" in html
    assert "Communication" in html
    assert "Process" in html
    assert "Instruction-Following" in html


def test_report_contains_total_score(tmp_path):
    result = _make_result("john-doe-SME")
    html = write_candidate_report(result, tmp_path).read_text(encoding="utf-8")
    assert f"{result.total_score}" in html
    assert "/20" in html


def test_report_contains_summary(tmp_path):
    result = _make_result("john-doe-SME")
    html = write_candidate_report(result, tmp_path).read_text(encoding="utf-8")
    assert "Overall Assessment" in html


def test_report_shows_hard_fail(tmp_path):
    dim = DimensionScore(score=3, quotes=[], rationale="ok")
    analysis = RubricAnalysis(
        role_fit_and_relevant_experience=dim, domain_judgment=dim,
        process_and_methodology=dim, communication=dim,
        instruction_following_and_professionalism=dim,
        hard_fail_flags=HardFailFlags(did_not_answer_all_questions=True),
        confidence_score=0.5, overall_summary="Incomplete.",
    )
    candidate = CandidateFile(
        path=Path("bob-jones-QA.mp4"), first_name="bob",
        last_name="jones", job_type="QA", duration_seconds=300.0,
    )
    transcript = TranscriptResult(text="test", word_count=1, duration_seconds=300.0)
    classification = ClassificationResult(recommendation="Decline", reason="hard fail")
    result = CandidateResult.from_pipeline(candidate, transcript, analysis, classification)

    html = write_candidate_report(result, tmp_path).read_text(encoding="utf-8")
    assert "Automatic Disqualification" in html
    assert "Did not answer all interview questions" in html


def test_report_handles_zero_scores(tmp_path):
    candidate = CandidateFile(
        path=Path("fail-case-QA.mp4"), first_name="fail",
        last_name="case", job_type="QA", duration_seconds=300.0,
    )
    transcript = TranscriptResult(failed=True, error_message="bad audio")
    classification = ClassificationResult(
        recommendation="Needs Human Review",
        reason="Transcription failed. Manual review required.",
    )
    result = CandidateResult.from_pipeline(candidate, transcript, analysis=None, classification=classification)

    html = write_candidate_report(result, tmp_path).read_text(encoding="utf-8")
    assert "Needs Human Review" in html
    assert "N/A" in html
