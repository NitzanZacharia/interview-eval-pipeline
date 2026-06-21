"""Rubric scoring of interview transcripts via Claude (SPEC §7, §5.4, §10).

Sends a transcript, the scoring rubric, and the candidate's interview
questions to Claude and parses the structured RubricAnalysis back. Any
failure (API error, validation error, etc.) is caught and surfaced as None
so the pipeline can isolate it per candidate and fall back to
"Needs Human Review" rather than crashing the whole run.

Manual smoke test (no automated tests — requires a live API key):
    1. Set ANTHROPIC_API_KEY in the environment.
    2. >>> from pathlib import Path
       >>> from interview_eval.analyze import score_transcript
       >>> rubric = Path("scoring_rubric.md").read_text(encoding="utf-8")
       >>> analysis = score_transcript("...transcript text...", rubric, "SME")
       >>> print(analysis.confidence_score, analysis.overall_summary)
    3. For the failure path, unset the API key or pass an invalid job_type
       and confirm score_transcript returns None with a warning on stdout.
"""

from __future__ import annotations

from typing import Optional

from . import config
from .models import RubricAnalysis


SYSTEM_PROMPT = (
    "You are a professional hiring evaluator. Score the candidate's interview "
    "transcript strictly against the scoring rubric provided. For each of the 5 "
    "criteria, assign a score from 0 to 4, extract verbatim quotes from the "
    "transcript as evidence, and write a concise rationale grounded in those "
    "quotes. Determine whether any hard-fail conditions apply. Provide a "
    "confidence score from 0.0 to 1.0 reflecting how certain you are in your "
    "evaluation given the quality and completeness of the transcript. Flag any "
    "uncertainties or limitations in the overall_summary. Do not reward claims "
    "the transcript does not support, and do not penalize the candidate for "
    "transcription artifacts."
)


def score_transcript(
    transcript_text: str, rubric_text: str, job_type: str
) -> Optional[RubricAnalysis]:
    try:
        import anthropic

        questions = config.INTERVIEW_QUESTIONS[job_type]
        questions_block = "\n".join(
            f"{i}. {q}" for i, q in enumerate(questions, start=1)
        )

        user_message = (
            f"# Job Type\n{job_type}\n\n"
            f"# Interview Questions\n{questions_block}\n\n"
            f"# Scoring Rubric\n{rubric_text}\n\n"
            f"# Interview Transcript\n{transcript_text}"
        )

        client = anthropic.Anthropic(api_key=config.get_api_key())
        response = client.messages.parse(
            model=config.CLAUDE_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            output_format=RubricAnalysis,
        )
        return response.parsed_output
    except Exception as e:  # noqa: BLE001 — isolate per-candidate scoring failures
        print(f"Warning: scoring failed for a {job_type} candidate: {e}")
        return None
