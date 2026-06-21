from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


# --- Ingestion models ---


class CandidateFile(BaseModel):
    path: Path
    first_name: str
    last_name: str
    job_type: str  # "SME" or "QA"
    duration_seconds: Optional[float] = None
    warnings: list[str] = Field(default_factory=list)

    @property
    def candidate_id(self) -> str:
        return f"{self.first_name}-{self.last_name}-{self.job_type}"

    @property
    def video_filename(self) -> str:
        return f"{self.candidate_id}.mp4"


# --- Transcription models ---


class TranscriptResult(BaseModel):
    text: str = ""
    word_count: int = 0
    duration_seconds: float = 0.0
    failed: bool = False
    error_message: str = ""


# --- LLM analysis models (used as output_format for client.messages.parse) ---


class DimensionScore(BaseModel):
    score: int = Field(ge=0, le=4)
    quotes: list[str] = Field(default_factory=list)
    rationale: str = ""


class HardFailFlags(BaseModel):
    did_not_answer_all_questions: bool = False
    lacks_core_experience: bool = False
    cannot_communicate_clearly: bool = False


class RubricAnalysis(BaseModel):
    """Structured output from Claude for rubric scoring.

    Used as the output_format parameter in client.messages.parse().
    """

    role_fit_and_relevant_experience: DimensionScore
    domain_judgment: DimensionScore
    process_and_methodology: DimensionScore
    communication: DimensionScore
    instruction_following_and_professionalism: DimensionScore
    hard_fail_flags: HardFailFlags
    confidence_score: float = Field(ge=0.0, le=1.0)
    overall_summary: str = ""


# --- Classification models ---


class ClassificationResult(BaseModel):
    recommendation: str  # "Advance", "Hold", "Decline", "Needs Human Review"
    reason: str = ""


# --- Output models (final JSON payload per SPEC §9.1) ---


class TranscriptMetadata(BaseModel):
    video_filename: str
    video_duration_seconds: float = 0.0
    transcript_word_count: int = 0
    duration_warning: Optional[str] = None


class Scores(BaseModel):
    role_fit_and_relevant_experience: DimensionScore
    domain_judgment: DimensionScore
    process_and_methodology: DimensionScore
    communication: DimensionScore
    instruction_following_and_professionalism: DimensionScore


class SystemNotes(BaseModel):
    model_used: str = "claude-sonnet-4-6"
    rubric_version: str = "scoring_rubric.md"
    pipeline_version: str = "0.1.0"
    limitations: list[str] = Field(default_factory=list)


class CandidateResult(BaseModel):
    candidate_id: str
    first_name: str
    last_name: str
    job_type: str
    evaluation_timestamp: str

    transcript_metadata: TranscriptMetadata

    scores: Scores

    total_score: int = 0
    recommendation: str = ""
    recommendation_reason: str = ""

    hard_fail_flags: HardFailFlags = Field(default_factory=HardFailFlags)

    confidence_score: float = 0.0
    overall_summary: str = ""

    system_notes: SystemNotes = Field(default_factory=SystemNotes)

    @staticmethod
    def from_pipeline(
        candidate: CandidateFile,
        transcript: TranscriptResult,
        analysis: Optional[RubricAnalysis],
        classification: ClassificationResult,
    ) -> CandidateResult:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        duration_warning = None
        for w in candidate.warnings:
            if "duration" in w.lower():
                duration_warning = w
                break

        if analysis is not None:
            scores = Scores(
                role_fit_and_relevant_experience=analysis.role_fit_and_relevant_experience,
                domain_judgment=analysis.domain_judgment,
                process_and_methodology=analysis.process_and_methodology,
                communication=analysis.communication,
                instruction_following_and_professionalism=analysis.instruction_following_and_professionalism,
            )
            hard_fail = analysis.hard_fail_flags
            confidence = analysis.confidence_score
            summary = analysis.overall_summary
            total = (
                analysis.role_fit_and_relevant_experience.score
                + analysis.domain_judgment.score
                + analysis.process_and_methodology.score
                + analysis.communication.score
                + analysis.instruction_following_and_professionalism.score
            )
            limitations = [
                "Transcription quality may affect scoring accuracy.",
                "Scores reflect rubric criteria only, not holistic assessment.",
            ]
        else:
            zero = DimensionScore(score=0, quotes=[], rationale="")
            scores = Scores(
                role_fit_and_relevant_experience=zero,
                domain_judgment=zero,
                process_and_methodology=zero,
                communication=zero,
                instruction_following_and_professionalism=zero,
            )
            hard_fail = HardFailFlags()
            confidence = 0.0
            summary = classification.reason
            total = 0
            limitations = ["Transcription failed — no evaluation was performed."]

        return CandidateResult(
            candidate_id=candidate.candidate_id,
            first_name=candidate.first_name,
            last_name=candidate.last_name,
            job_type=candidate.job_type,
            evaluation_timestamp=now,
            transcript_metadata=TranscriptMetadata(
                video_filename=candidate.video_filename,
                video_duration_seconds=candidate.duration_seconds or 0.0,
                transcript_word_count=transcript.word_count,
                duration_warning=duration_warning,
            ),
            scores=scores,
            total_score=total,
            recommendation=classification.recommendation,
            recommendation_reason=classification.reason,
            hard_fail_flags=hard_fail,
            confidence_score=confidence,
            overall_summary=summary,
            system_notes=SystemNotes(limitations=limitations),
        )
