from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from interview_eval.models import CandidateResult


CSV_COLUMNS = [
    "candidate_id",
    "first_name",
    "last_name",
    "job_type",
    "total_score",
    "role_fit",
    "domain_judgment",
    "process",
    "communication",
    "instruction_following",
    "recommendation",
    "confidence",
    "hard_fail",
    "evaluation_timestamp",
]


def write_candidate_json(result: CandidateResult, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.candidate_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(result.model_dump(), f, indent=2)
    return path


def write_candidate_report(result: CandidateResult, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.candidate_id}.html"
    html = _render_report(result)
    with path.open("w", encoding="utf-8") as f:
        f.write(html)
    return path


_RECOMMENDATION_STYLE = {
    "Advance": ("background:#d4edda;color:#155724;", "Advance to Interview"),
    "Hold": ("background:#fff3cd;color:#856404;", "Hold for Discussion"),
    "Decline": ("background:#f8d7da;color:#721c24;", "Decline"),
    "Needs Human Review": ("background:#cce5ff;color:#004085;", "Needs Human Review"),
}

_SCORE_LABELS = {
    0: "N/A", 1: "Weak", 2: "Developing", 3: "Strong", 4: "Excellent",
}

_DIMENSION_DISPLAY = [
    ("role_fit_and_relevant_experience", "Role Fit & Relevant Experience"),
    ("domain_judgment", "Domain Judgment"),
    ("process_and_methodology", "Process & Methodology"),
    ("communication", "Communication"),
    ("instruction_following_and_professionalism", "Instruction-Following & Professionalism"),
]


def _score_bar(score: int) -> str:
    if score == 0:
        return '<span style="color:#999;">N/A</span>'
    colors = {1: "#dc3545", 2: "#fd7e14", 3: "#28a745", 4: "#007bff"}
    color = colors.get(score, "#999")
    filled = "&#9632; " * score
    empty = "&#9633; " * (4 - score)
    return f'<span style="color:{color};font-size:16px;">{filled}</span><span style="color:#ddd;font-size:16px;">{empty}</span>'


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _render_report(r: CandidateResult) -> str:
    name = f"{r.first_name.title()} {r.last_name.title()}"
    job_label = "Subject Matter Expert (SME)" if r.job_type == "SME" else "Curriculum QA Specialist"
    rec_style, rec_label = _RECOMMENDATION_STYLE.get(
        r.recommendation, ("background:#e2e3e5;color:#383d41;", r.recommendation)
    )

    timestamp = r.evaluation_timestamp.replace("T", " ").replace("Z", " UTC") if r.evaluation_timestamp else ""

    duration_str = ""
    if r.transcript_metadata.video_duration_seconds:
        mins = int(r.transcript_metadata.video_duration_seconds // 60)
        secs = int(r.transcript_metadata.video_duration_seconds % 60)
        duration_str = f"{mins}m {secs}s"

    warnings_html = ""
    if r.transcript_metadata.duration_warning:
        warnings_html = f"""
        <div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;padding:10px 14px;margin-bottom:20px;">
            <strong>Note:</strong> {_escape(r.transcript_metadata.duration_warning)}
        </div>"""

    hard_fail_items = []
    if r.hard_fail_flags.did_not_answer_all_questions:
        hard_fail_items.append("Did not answer all interview questions")
    if r.hard_fail_flags.lacks_core_experience:
        hard_fail_items.append("Lacks core experience required for the role")
    if r.hard_fail_flags.cannot_communicate_clearly:
        hard_fail_items.append("Unable to communicate clearly")
    hard_fail_html = ""
    if hard_fail_items:
        items = "".join(f"<li>{_escape(i)}</li>" for i in hard_fail_items)
        hard_fail_html = f"""
        <div style="background:#f8d7da;border:1px solid #f5c6cb;border-radius:6px;padding:10px 14px;margin-top:16px;">
            <strong>Automatic Disqualification:</strong>
            <ul style="margin:6px 0 0 0;padding-left:20px;">{items}</ul>
        </div>"""

    score_rows = ""
    for field, label in _DIMENSION_DISPLAY:
        dim = getattr(r.scores, field)
        score_label = _SCORE_LABELS.get(dim.score, str(dim.score))
        bar = _score_bar(dim.score)

        quotes_html = ""
        if dim.quotes:
            quote_items = "".join(
                f'<li style="margin-bottom:4px;"><em>"{_escape(q)}"</em></li>'
                for q in dim.quotes
            )
            quotes_html = f'<ul style="margin:4px 0 0 0;padding-left:18px;font-size:13px;color:#555;">{quote_items}</ul>'

        rationale_html = ""
        if dim.rationale:
            rationale_html = f'<div style="font-size:13px;color:#555;margin-top:4px;">{_escape(dim.rationale)}</div>'

        score_rows += f"""
            <tr>
                <td style="padding:10px 12px;border-bottom:1px solid #eee;font-weight:500;">{label}</td>
                <td style="padding:10px 12px;border-bottom:1px solid #eee;text-align:center;">{bar}<br><span style="font-size:12px;color:#666;">{dim.score}/4 &mdash; {score_label}</span></td>
                <td style="padding:10px 12px;border-bottom:1px solid #eee;">{rationale_html}{quotes_html}</td>
            </tr>"""

    confidence_pct = int(r.confidence_score * 100) if r.confidence_score else 0
    confidence_color = "#28a745" if confidence_pct >= 70 else "#fd7e14" if confidence_pct >= 40 else "#dc3545"

    summary_html = ""
    if r.overall_summary:
        summary_html = f"""
    <div style="margin-top:24px;">
        <h2 style="font-size:18px;color:#333;margin-bottom:10px;">Overall Assessment</h2>
        <p style="line-height:1.6;color:#444;">{_escape(r.overall_summary)}</p>
    </div>"""

    reason_html = ""
    if r.recommendation_reason:
        reason_html = f'<p style="font-size:13px;color:#666;margin-top:6px;"><strong>Basis:</strong> {_escape(r.recommendation_reason)}</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Candidate Report — {_escape(name)}</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; max-width: 800px; margin: 30px auto; padding: 0 20px; color: #333; }}
  @media print {{ body {{ margin: 0; }} }}
</style>
</head>
<body>

<div style="border-bottom:3px solid #333;padding-bottom:16px;margin-bottom:24px;">
    <h1 style="margin:0 0 4px 0;font-size:26px;">{_escape(name)}</h1>
    <div style="font-size:15px;color:#666;">
        {job_label} &nbsp;|&nbsp; Evaluated {timestamp}
        {"&nbsp;|&nbsp; Video length: " + duration_str if duration_str else ""}
    </div>
</div>
{warnings_html}
<div style="display:flex;align-items:center;gap:20px;margin-bottom:24px;">
    <div style="{rec_style}padding:12px 24px;border-radius:8px;font-size:20px;font-weight:600;">
        {rec_label}
    </div>
    <div style="text-align:center;">
        <div style="font-size:28px;font-weight:700;color:#333;">{r.total_score}<span style="font-size:16px;color:#999;">/20</span></div>
        <div style="font-size:12px;color:#666;">Total Score</div>
    </div>
    <div style="text-align:center;">
        <div style="font-size:28px;font-weight:700;color:{confidence_color};">{confidence_pct}%</div>
        <div style="font-size:12px;color:#666;">Confidence</div>
    </div>
</div>
{reason_html}
{hard_fail_html}

<h2 style="font-size:18px;color:#333;margin-top:30px;margin-bottom:12px;">Scoring Breakdown</h2>
<table style="width:100%;border-collapse:collapse;border:1px solid #ddd;border-radius:6px;">
    <thead>
        <tr style="background:#f8f9fa;">
            <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #ddd;width:30%;">Criterion</th>
            <th style="padding:10px 12px;text-align:center;border-bottom:2px solid #ddd;width:22%;">Score</th>
            <th style="padding:10px 12px;text-align:left;border-bottom:2px solid #ddd;">Evidence &amp; Rationale</th>
        </tr>
    </thead>
    <tbody>
        {score_rows}
    </tbody>
</table>
{summary_html}

<div style="margin-top:30px;padding-top:12px;border-top:1px solid #eee;font-size:11px;color:#999;">
    Generated by Interview Evaluation Pipeline v{r.system_notes.pipeline_version} &nbsp;|&nbsp; Model: {r.system_notes.model_used}
</div>

</body>
</html>"""


def _open_with_retry(path: Path, mode: str, retries: int = 3, delay: float = 2.0):
    """Try to open a file, retrying on PermissionError (file locked by another process)."""
    for attempt in range(retries):
        try:
            return path.open(mode, encoding="utf-8", newline="")
        except PermissionError:
            if attempt < retries - 1:
                print(f"  Warning: {path.name} is locked, retrying in {delay}s... "
                      f"(close any program that has it open)")
                time.sleep(delay)
            else:
                raise PermissionError(
                    f"Cannot write to {path} — it is locked by another process "
                    f"(Excel, OneDrive sync, etc.). Close the file and re-run."
                )


def _open_for_write(path: Path, retries: int = 3, delay: float = 2.0):
    return _open_with_retry(path, "w", retries, delay)


def _open_for_append(path: Path, retries: int = 3, delay: float = 2.0):
    return _open_with_retry(path, "a", retries, delay)


def _result_to_row(result: CandidateResult) -> dict:
    hard_fail = any(
        [
            result.hard_fail_flags.did_not_answer_all_questions,
            result.hard_fail_flags.lacks_core_experience,
            result.hard_fail_flags.cannot_communicate_clearly,
        ]
    )
    return {
        "candidate_id": result.candidate_id,
        "first_name": result.first_name,
        "last_name": result.last_name,
        "job_type": result.job_type,
        "total_score": result.total_score,
        "role_fit": result.scores.role_fit_and_relevant_experience.score,
        "domain_judgment": result.scores.domain_judgment.score,
        "process": result.scores.process_and_methodology.score,
        "communication": result.scores.communication.score,
        "instruction_following": result.scores.instruction_following_and_professionalism.score,
        "recommendation": result.recommendation,
        "confidence": result.confidence_score,
        "hard_fail": "true" if hard_fail else "false",
        "evaluation_timestamp": result.evaluation_timestamp,
    }


def write_batch_csv(results: list[CandidateResult], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "batch_summary.csv"
    file_exists = path.is_file() and path.stat().st_size > 0
    with _open_for_append(path) as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        for result in results:
            writer.writerow(_result_to_row(result))
    return path
