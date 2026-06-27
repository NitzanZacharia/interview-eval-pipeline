from __future__ import annotations

from interview_eval.models import ClassificationResult, RubricAnalysis


def classify_candidate(analysis: RubricAnalysis) -> ClassificationResult:
    flags = analysis.hard_fail_flags
    if flags.did_not_answer_all_questions:
        return ClassificationResult(
            recommendation="Decline",
            reason="Hard fail: candidate did not answer all questions.",
        )
    if flags.lacks_core_experience:
        return ClassificationResult(
            recommendation="Decline",
            reason="Hard fail: candidate lacks core experience for the role.",
        )
    if flags.cannot_communicate_clearly:
        return ClassificationResult(
            recommendation="Decline",
            reason="Hard fail: candidate cannot communicate clearly enough to follow.",
        )

    role_fit = analysis.role_fit_and_relevant_experience.score
    total_score = (
        role_fit
        + analysis.domain_judgment.score
        + analysis.process_and_methodology.score
        + analysis.communication.score
        + analysis.instruction_following_and_professionalism.score
    )

    if total_score >= 14:
        if role_fit >= 3:
            if total_score >= 17:
                return ClassificationResult(
                    recommendation="Strong Advance",
                    reason=(
                        f"Total score {total_score} meets the strong threshold (>=17) "
                        f"and Role Fit {role_fit} meets the gating criterion (>=3)."
                    ),
                )
            return ClassificationResult(
                recommendation="Advance",
                reason=(
                    f"Total score {total_score} meets the threshold (>=14) "
                    f"and Role Fit {role_fit} meets the gating criterion (>=3)."
                ),
            )
        return ClassificationResult(
            recommendation="Hold",
            reason=(
                f"Total score {total_score} meets the threshold (>=14) but "
                f"Role Fit {role_fit} does not meet the gating criterion (>=3)."
            ),
        )

    if total_score >= 11:
        return ClassificationResult(
            recommendation="Hold",
            reason=f"Total score {total_score} is borderline (11-13).",
        )

    return ClassificationResult(
        recommendation="Decline",
        reason=f"Total score {total_score} is below the threshold (<=10).",
    )
