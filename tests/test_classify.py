from __future__ import annotations

import pytest

from interview_eval.classify import classify_candidate
from interview_eval.models import (
    DimensionScore,
    HardFailFlags,
    RubricAnalysis,
)


def _make_analysis(
    role_fit: int,
    domain: int,
    process: int,
    communication: int,
    instruction: int,
    hard_fail_flags: HardFailFlags | None = None,
) -> RubricAnalysis:
    def dim(score: int) -> DimensionScore:
        return DimensionScore(score=score, quotes=[], rationale="")

    return RubricAnalysis(
        role_fit_and_relevant_experience=dim(role_fit),
        domain_judgment=dim(domain),
        process_and_methodology=dim(process),
        communication=dim(communication),
        instruction_following_and_professionalism=dim(instruction),
        hard_fail_flags=hard_fail_flags or HardFailFlags(),
        confidence_score=0.5,
        overall_summary="",
    )


def test_advance_total_14_criterion_3():
    # total = 3+3+3+3+2 = 14, role_fit = 3
    analysis = _make_analysis(3, 3, 3, 3, 2)
    result = classify_candidate(analysis)
    assert result.recommendation == "Advance"


def test_advance_high_scores():
    # total = 4+4+4+4+4 = 20, role_fit = 4
    analysis = _make_analysis(4, 4, 4, 4, 4)
    result = classify_candidate(analysis)
    assert result.recommendation == "Advance"


def test_advance_boundary_total_14_criterion_exactly_3():
    # total = 3+4+4+2+1 = 14, role_fit = 3 exactly
    analysis = _make_analysis(3, 4, 4, 2, 1)
    result = classify_candidate(analysis)
    assert result.recommendation == "Advance"


def test_hold_borderline_total_12():
    # total = 3+3+2+2+2 = 12, role_fit = 3
    analysis = _make_analysis(3, 3, 2, 2, 2)
    result = classify_candidate(analysis)
    assert result.recommendation == "Hold"


def test_hold_high_total_low_gating():
    # total = 2+4+4+3+3 = 16, role_fit = 2 (gating fail)
    analysis = _make_analysis(2, 4, 4, 3, 3)
    result = classify_candidate(analysis)
    assert result.recommendation == "Hold"
    assert "gating" in result.reason.lower()


def test_hold_boundary_total_11():
    # total = 3+2+2+2+2 = 11
    analysis = _make_analysis(3, 2, 2, 2, 2)
    result = classify_candidate(analysis)
    assert result.recommendation == "Hold"


def test_hold_boundary_total_13():
    # total = 3+3+3+2+2 = 13
    analysis = _make_analysis(3, 3, 3, 2, 2)
    result = classify_candidate(analysis)
    assert result.recommendation == "Hold"


def test_decline_low_total_10():
    # total = 2+2+2+2+2 = 10
    analysis = _make_analysis(2, 2, 2, 2, 2)
    result = classify_candidate(analysis)
    assert result.recommendation == "Decline"


def test_decline_very_low_total_5():
    # total = 1+1+1+1+1 = 5
    analysis = _make_analysis(1, 1, 1, 1, 1)
    result = classify_candidate(analysis)
    assert result.recommendation == "Decline"


def test_hard_fail_did_not_answer_all_questions():
    # total = 4+4+4+3+3 = 18 but hard fail
    flags = HardFailFlags(did_not_answer_all_questions=True)
    analysis = _make_analysis(4, 4, 4, 3, 3, hard_fail_flags=flags)
    result = classify_candidate(analysis)
    assert result.recommendation == "Decline"
    assert "answer" in result.reason.lower()


def test_hard_fail_lacks_core_experience():
    # total = 4+4+3+2+2 = 15 but hard fail
    flags = HardFailFlags(lacks_core_experience=True)
    analysis = _make_analysis(4, 4, 3, 2, 2, hard_fail_flags=flags)
    result = classify_candidate(analysis)
    assert result.recommendation == "Decline"
    assert "experience" in result.reason.lower()


def test_hard_fail_cannot_communicate():
    # total = 3+3+3+3+2 = 14 but hard fail
    flags = HardFailFlags(cannot_communicate_clearly=True)
    analysis = _make_analysis(3, 3, 3, 3, 2, hard_fail_flags=flags)
    result = classify_candidate(analysis)
    assert result.recommendation == "Decline"
    assert "communicate" in result.reason.lower()


def test_hard_fail_overrides_advance():
    # total = 4+4+4+2+2 = 16, role_fit = 4 (would Advance) but hard fail
    flags = HardFailFlags(did_not_answer_all_questions=True)
    analysis = _make_analysis(4, 4, 4, 2, 2, hard_fail_flags=flags)
    result = classify_candidate(analysis)
    assert result.recommendation == "Decline"
