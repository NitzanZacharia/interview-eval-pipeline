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

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel

from .airtable_ingest import fetch_single_record
from .airtable_pipeline import process_record

load_dotenv()

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
