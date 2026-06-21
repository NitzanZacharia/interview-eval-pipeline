"""Audio extraction and transcription for interview videos (SPEC §8, §10).

Extracts mono 16kHz WAV audio from an MP4 via ffmpeg, then transcribes it
with faster-whisper. All failures are captured in the returned TranscriptResult
rather than raised, so the pipeline can continue past a bad video.

Manual smoke test (no automated tests — requires real audio + ffmpeg):
    1. Ensure ffmpeg is on PATH and faster-whisper is installed.
    2. >>> from pathlib import Path
       >>> from interview_eval.transcribe import transcribe_video
       >>> r = transcribe_video(Path("some-interview.mp4"))
       >>> print(r.failed, r.word_count, r.duration_seconds)
       >>> print(r.text[:200])
    3. For the failure path, pass a non-existent or non-video file and
       confirm r.failed is True and r.error_message is populated.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from . import config
from .models import TranscriptResult


def transcribe_video(video_path: Path) -> TranscriptResult:
    wav_path: str | None = None
    try:
        from faster_whisper import WhisperModel

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "wav",
                wav_path,
            ],
            check=True,
            capture_output=True,
        )

        model = WhisperModel(
            config.WHISPER_MODEL_SIZE,
            device="cpu",
            compute_type="int8",
        )
        segments, info = model.transcribe(wav_path)

        transcript = " ".join(segment.text.strip() for segment in segments).strip()

        return TranscriptResult(
            text=transcript,
            word_count=len(transcript.split()),
            duration_seconds=info.duration,
            failed=False,
        )
    except Exception as e:  # noqa: BLE001 — pipeline must never crash on one bad video
        return TranscriptResult(failed=True, error_message=str(e))
    finally:
        if wav_path is not None and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass
