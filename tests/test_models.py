"""Tests for Pydantic models against SPEC §9.1 and §9.2 JSON shapes."""

from __future__ import annotations

import pytest

from interview_eval.models import (
    CandidateFile,
    CandidateResult,
    ClassificationResult,
    DimensionScore,
    HardFailFlags,
    RubricAnalysis,
    Scores,
    SystemNotes,
    TranscriptMetadata,
    TranscriptResult,
)


# --- DimensionScore ---


def test_dimension_score_valid():
    ds = DimensionScore(score=3, quotes=["verbatim"], rationale="Good.")
    assert ds.score == 3
    assert ds.quotes == ["verbatim"]


def test_dimension_score_zero_allowed():
    ds = DimensionScore(score=0, quotes=[], rationale="")
    assert ds.score == 0


def test_dimension_score_four_allowed():
    ds = DimensionScore(score=4, quotes=[], rationale="")
    assert ds.score == 4


def test_dimension_score_five_rejected():
    with pytest.raises(Exception):
        DimensionScore(score=5, quotes=[], rationale="")


def test_dimension_score_negative_rejected():
    with pytest.raises(Exception):
        DimensionScore(score=-1, quotes=[], rationale="")


# --- HardFailFlags ---


def test_hard_fail_defaults_all_false():
    hf = HardFailFlags()
    assert not hf.did_not_answer_all_questions
    assert not hf.lacks_core_experience
    assert not hf.cannot_communicate_clearly


# --- RubricAnalysis ---


def _make_rubric_analysis(**overrides) -> RubricAnalysis:
    dim = DimensionScore(score=3, quotes=[], rationale="ok")
    defaults = dict(
        role_fit_and_relevant_experience=dim,
        domain_judgment=dim,
        process_and_methodology=dim,
        communication=dim,
        instruction_following_and_professionalism=dim,
        hard_fail_flags=HardFailFlags(),
        confidence_score=0.82,
        overall_summary="Good candidate.",
    )
    defaults.update(overrides)
    return RubricAnalysis(**defaults)


def test_rubric_analysis_valid():
    ra = _make_rubric_analysis()
    assert ra.confidence_score == 0.82


def test_rubric_analysis_confidence_bounds():
    _make_rubric_analysis(confidence_score=0.0)
    _make_rubric_analysis(confidence_score=1.0)
    with pytest.raises(Exception):
        _make_rubric_analysis(confidence_score=1.1)
    with pytest.raises(Exception):
        _make_rubric_analysis(confidence_score=-0.1)


# --- CandidateFile ---


def test_candidate_file_properties(tmp_path):
    cf = CandidateFile(
        path=tmp_path / "john-doe-SME.mp4",
        first_name="john",
        last_name="doe",
        job_type="SME",
    )
    assert cf.candidate_id == "john-doe-SME"
    assert cf.video_filename == "john-doe-SME.mp4"


# --- TranscriptResult ---


def test_transcript_result_defaults():
    tr = TranscriptResult()
    assert tr.text == ""
    assert tr.word_count == 0
    assert not tr.failed


def test_transcript_result_failed():
    tr = TranscriptResult(failed=True, error_message="bad audio")
    assert tr.failed
    assert tr.error_message == "bad audio"


# --- CandidateResult.from_pipeline ---


def test_from_pipeline_with_analysis(tmp_path):
    candidate = CandidateFile(
        path=tmp_path / "john-doe-SME.mp4",
        first_name="john",
        last_name="doe",
        job_type="SME",
        duration_seconds=420.0,
        warnings=[],
    )
    transcript = TranscriptResult(
        text="I spent four years managing CTE programs...",
        word_count=1850,
        duration_seconds=420.0,
    )
    analysis = RubricAnalysis(
        role_fit_and_relevant_experience=DimensionScore(
            score=3, quotes=["I spent four years managing CTE programs..."], rationale="Clear experience."
        ),
        domain_judgment=DimensionScore(score=3, quotes=[], rationale="Solid."),
        process_and_methodology=DimensionScore(score=2, quotes=[], rationale="Gaps."),
        communication=DimensionScore(score=3, quotes=[], rationale="Clear."),
        instruction_following_and_professionalism=DimensionScore(score=3, quotes=[], rationale="All answered."),
        hard_fail_flags=HardFailFlags(),
        confidence_score=0.82,
        overall_summary="Good candidate overall.",
    )
    classification = ClassificationResult(
        recommendation="Advance",
        reason="Total score 14 meets threshold and Role Fit >= 3.",
    )

    result = CandidateResult.from_pipeline(candidate, transcript, analysis, classification)

    assert result.candidate_id == "john-doe-SME"
    assert result.first_name == "john"
    assert result.job_type == "SME"
    assert result.total_score == 14
    assert result.recommendation == "Advance"
    assert result.confidence_score == 0.82
    assert result.scores.role_fit_and_relevant_experience.score == 3
    assert result.transcript_metadata.video_filename == "john-doe-SME.mp4"
    assert result.transcript_metadata.video_duration_seconds == 420.0
    assert result.transcript_metadata.transcript_word_count == 1850
    assert result.transcript_metadata.duration_warning is None


def test_from_pipeline_failed_transcription(tmp_path):
    candidate = CandidateFile(
        path=tmp_path / "jane-smith-QA.mp4",
        first_name="jane",
        last_name="smith",
        job_type="QA",
        duration_seconds=300.0,
    )
    transcript = TranscriptResult(failed=True, error_message="bad audio")
    classification = ClassificationResult(
        recommendation="Needs Human Review",
        reason="Transcription failed. Manual review required.",
    )

    result = CandidateResult.from_pipeline(candidate, transcript, analysis=None, classification=classification)

    assert result.candidate_id == "jane-smith-QA"
    assert result.total_score == 0
    assert result.recommendation == "Needs Human Review"
    assert result.confidence_score == 0.0
    assert result.scores.role_fit_and_relevant_experience.score == 0
    assert result.transcript_metadata.transcript_word_count == 0
    assert "Transcription failed" in result.system_notes.limitations[0]


def test_from_pipeline_duration_warning(tmp_path):
    candidate = CandidateFile(
        path=tmp_path / "john-doe-SME.mp4",
        first_name="john",
        last_name="doe",
        job_type="SME",
        duration_seconds=60.0,
        warnings=["Video duration 60.0s is below the minimum of 120s."],
    )
    transcript = TranscriptResult(text="short", word_count=1, duration_seconds=60.0)
    analysis = _make_rubric_analysis()
    classification = ClassificationResult(recommendation="Advance", reason="ok")

    result = CandidateResult.from_pipeline(candidate, transcript, analysis, classification)

    assert result.transcript_metadata.duration_warning is not None
    assert "duration" in result.transcript_metadata.duration_warning.lower()


def test_candidate_result_json_roundtrip(tmp_path):
    """Verify model_dump produces a dict matching SPEC §9.1 top-level keys."""
    candidate = CandidateFile(
        path=tmp_path / "john-doe-SME.mp4",
        first_name="john",
        last_name="doe",
        job_type="SME",
        duration_seconds=420.0,
    )
    transcript = TranscriptResult(text="test", word_count=1, duration_seconds=420.0)
    analysis = _make_rubric_analysis()
    classification = ClassificationResult(recommendation="Advance", reason="ok")
    result = CandidateResult.from_pipeline(candidate, transcript, analysis, classification)

    data = result.model_dump()

    expected_keys = {
        "candidate_id", "first_name", "last_name", "job_type",
        "evaluation_timestamp", "transcript_metadata", "scores",
        "total_score", "recommendation", "recommendation_reason",
        "hard_fail_flags", "confidence_score", "overall_summary",
        "system_notes",
    }
    assert set(data.keys()) == expected_keys
    assert data["system_notes"]["pipeline_version"] == "0.1.0"
