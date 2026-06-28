import os
import re
import sys


CLAUDE_MODEL = "claude-sonnet-4-6"
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "base")

MIN_DURATION_SECONDS = 120  # 2 minutes
MAX_DURATION_SECONDS = 600  # 10 minutes

VALID_JOB_TYPES = {"SME", "QA"}
FILENAME_PATTERN = re.compile(r"^[a-z]+-[a-z]+-(?:SME|QA)\.mp4$")

PIPELINE_VERSION = "0.1.0"

SME_QUESTIONS = [
    (
        "Tell us about a time you built or coordinated a CTE program or course "
        "beyond teaching it. What was your role at the program level, and how did "
        "you make sure it met its qualifying criteria, such as funding, articulation, "
        "or certification?"
    ),
    (
        "This is a generalist role across many CTE pathways. Describe one pathway "
        "you know deeply, and walk us through how you would come up to speed quickly "
        "to review a course in a pathway outside your expertise."
    ),
    (
        "Imagine we hand you a drafted CTE course to review against its standards "
        "and its funding or certification requirements. What would you check, and "
        "how would you turn the gaps you find into clear, actionable revision "
        "direction for the writing team?"
    ),
]

QA_QUESTIONS = [
    (
        "This role reviews every activity in a lesson for errors before it reaches "
        "a classroom. Walk us through how you would systematically review a single "
        "K-12 lesson. What kinds of errors would you look for, and how would you "
        "keep your process consistent across many lessons?"
    ),
    (
        "Tell us about your experience catching content or quality errors in "
        "educational or digital materials. Give a specific example of an error you "
        "caught and how you handled it."
    ),
    (
        "When you find an issue, some you can fix yourself and some need to go to "
        "developers as a bug ticket. How do you decide which is which, and how do "
        "you write up an issue so that someone else can act on it without asking "
        "you questions?"
    ),
]

INTERVIEW_QUESTIONS = {
    "SME": SME_QUESTIONS,
    "QA": QA_QUESTIONS,
}


def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print(
            "Error: ANTHROPIC_API_KEY environment variable is not set.\n"
            "Get an API key from https://console.anthropic.com/ and set it:\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...",
            file=sys.stderr,
        )
        sys.exit(1)
    return key
