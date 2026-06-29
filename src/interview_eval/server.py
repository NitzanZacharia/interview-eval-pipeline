"""
interview_eval.server

FastAPI webhook endpoint for HR-triggered video evaluation.

HR clicks "Score Video" in Airtable → Airtable Automation fires a POST to
/evaluate → this server returns 202 immediately and processes the record in
the background → scores and stage update appear in Airtable within minutes.

Required environment variables:
  AIRTABLE_TOKEN      — Airtable Personal Access Token (data.records:write scope)
  ANTHROPIC_API_KEY   — Anthropic API key
  WEBHOOK_SECRET      — Shared secret matched against X-Webhook-Secret header

Optional environment variables:
  RUBRIC_PATH         — Path to scoring_rubric.md (default: repo root)
  OUTPUT_DIR          — Directory for local JSON/HTML/CSV outputs (default: /tmp/eval_output)

Running locally:
  uvicorn interview_eval.server:app --reload

Deploying to Railway:
  railway variables set AIRTABLE_TOKEN=pat...
  railway variables set ANTHROPIC_API_KEY=sk-ant-...
  railway variables set WEBHOOK_SECRET=<random-32-char-string>
  railway up
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import static_ffmpeg
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel

from .airtable_ingest import fetch_single_record
from .airtable_pipeline import process_record

load_dotenv()
static_ffmpeg.add_paths()  # adds static ffmpeg binary to PATH before any transcription runs

app = FastAPI(title="Interview Eval Pipeline")

# Default rubric: scoring_rubric.md in the project root (two levels above src/interview_eval/)
_DEFAULT_RUBRIC = Path(__file__).resolve().parent.parent.parent / "scoring_rubric.md"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class EvaluateRequest(BaseModel):
    record_id: str


class EvaluateResponse(BaseModel):
    status: str
    record_id: str


class IngestRequest(BaseModel):
    record_id: str
    source_type: str           # "gdrive" | "youtube"
    source_url: str            # public Google Drive URL or YouTube video URL
    filename: str | None = None


class IngestResponse(BaseModel):
    status: str
    record_id: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/evaluate", status_code=202, response_model=EvaluateResponse)
async def evaluate(
    req: EvaluateRequest,
    background_tasks: BackgroundTasks,
    x_webhook_secret: str = Header(default=None),
) -> EvaluateResponse:
    """
    Accept a record ID from an Airtable Automation and queue the evaluation.

    Returns 202 immediately; the pipeline runs in the background so Airtable's
    30-second webhook timeout is never reached.
    """
    expected = os.environ.get("WEBHOOK_SECRET", "")
    if not expected or x_webhook_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Webhook-Secret header.")

    background_tasks.add_task(_run_pipeline, req.record_id)
    return EvaluateResponse(status="accepted", record_id=req.record_id)


@app.post("/ingest", status_code=202, response_model=IngestResponse)
async def ingest(
    req: IngestRequest,
    background_tasks: BackgroundTasks,
    x_webhook_secret: str = Header(default=None),
) -> IngestResponse:
    """
    Accept a video source (Google Drive URL or YouTube link) from the GAS email
    watcher and queue the download + evaluation pipeline.

    Called by gmail_watcher.gs when a candidate replies to the video-request
    email with an MP4 attachment (uploaded to Drive) or a YouTube link.
    Returns 202 immediately; the pipeline runs in the background.
    """
    expected = os.environ.get("WEBHOOK_SECRET", "")
    if not expected or x_webhook_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Webhook-Secret header.")

    background_tasks.add_task(_run_ingest, req.record_id, req.source_type, req.source_url, req.filename)
    return IngestResponse(status="accepted", record_id=req.record_id)


@app.get("/health")
def health() -> dict:
    """Uptime check used by Railway and load balancers."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _run_pipeline(record_id: str) -> None:
    airtable_key = os.environ.get("AIRTABLE_TOKEN", "")
    rubric_path  = Path(os.environ.get("RUBRIC_PATH", str(_DEFAULT_RUBRIC)))
    output_dir   = Path(os.environ.get("OUTPUT_DIR", "/tmp/eval_output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[server] Starting evaluation for record {record_id}")
    try:
        record = fetch_single_record(record_id, airtable_key)
        with tempfile.TemporaryDirectory(prefix="eval_") as tmp:
            process_record(
                record=record,
                airtable_key=airtable_key,
                download_dir=Path(tmp),
                fallback_rubric_path=rubric_path,
                output_dir=output_dir,
                write_back=True,
                save_transcripts=False,
            )
        print(f"[server] Evaluation complete for record {record_id}")
    except Exception as exc:
        print(f"[server] ERROR evaluating record {record_id}: {exc}")


def _run_ingest(record_id: str, source_type: str, source_url: str, filename: str | None) -> None:
    """Download video from Drive or YouTube and run the evaluation pipeline."""
    import yt_dlp

    airtable_key = os.environ.get("AIRTABLE_TOKEN", "")
    rubric_path  = Path(os.environ.get("RUBRIC_PATH", str(_DEFAULT_RUBRIC)))
    output_dir   = Path(os.environ.get("OUTPUT_DIR", "/tmp/eval_output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[server] Ingest from email: record={record_id} source={source_type}")
    try:
        record = fetch_single_record(record_id, airtable_key)

        # Guard: skip if this record was already scored (prevents duplicate runs).
        if record.get("fields", {}).get("fldPHxOA56TRIsEXq"):
            print(f"[server] Record {record_id} already scored — skipping ingest.")
            return

        with tempfile.TemporaryDirectory(prefix="ingest_") as tmp:
            tmp_path = Path(tmp)
            fname = filename or "video.mp4"

            if source_type == "youtube":
                out_file = tmp_path / fname
                ydl_opts = {
                    "outtmpl": str(out_file.with_suffix("")),
                    "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
                    "merge_output_format": "mp4",
                    "quiet": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([source_url])
                # yt-dlp may add extension; find the actual output file
                mp4_files = list(tmp_path.glob("*.mp4"))
                if not mp4_files:
                    raise FileNotFoundError("yt-dlp produced no mp4 file.")
                video_path = mp4_files[0]
            else:
                # Google Drive direct download or other public URL
                import requests as req_lib
                video_path = tmp_path / fname
                resp = req_lib.get(source_url, stream=True, timeout=300)
                resp.raise_for_status()
                with video_path.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        f.write(chunk)

            process_record(
                record=record,
                airtable_key=airtable_key,
                download_dir=tmp_path,
                fallback_rubric_path=rubric_path,
                output_dir=output_dir,
                write_back=True,
                save_transcripts=False,
                video_path=video_path,
            )

        print(f"[server] Ingest complete for record {record_id}")
    except Exception as exc:
        print(f"[server] ERROR during ingest for record {record_id}: {exc}")
