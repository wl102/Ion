from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from Ion.db import Database, get_default_db
from Ion.db.models import MessageRecord, ReportRecord, SessionRecord, TaskRecord
from Ion.web.schemas import TaskOut, AttackGraphOut
from Ion.web.agent_runner import WebAgentRunner
from Ion.web.report_generator import ReportData, generate_pdf, render_report_html

router = APIRouter()

REPORT_CACHE_DIR = Path("data/reports")


def get_db_session(db: Database = Depends(get_default_db)):
    yield from db.get_session()


@router.get("", response_model=list[TaskOut])
def list_tasks(sid: str, db: Session = Depends(get_db_session)):
    session = db.query(SessionRecord).filter_by(id=sid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    records = db.query(TaskRecord).filter_by(session_id=sid).order_by(TaskRecord.created_at).all()
    return [r.to_dict() for r in records]


@router.get("/attack_graph", response_model=AttackGraphOut)
def get_attack_graph(sid: str, db: Session = Depends(get_db_session)):
    session = db.query(SessionRecord).filter_by(id=sid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    runner = WebAgentRunner.get(sid)
    if runner:
        text = runner.agent.task_manager.attack_graph_view()
    else:
        # No active runner: load from DB into a temp task manager
        from Ion.tools.task_tool import PersistentTaskManager
        tm = PersistentTaskManager(sid, db=get_default_db())
        tm.load_from_db()
        text = tm.attack_graph_view()
    return AttackGraphOut(text=text)


def _cache_path(sid: str) -> Path:
    return REPORT_CACHE_DIR / f"{sid}.pdf"


def _is_cache_valid(cache_path: Path, session_record: SessionRecord) -> bool:
    """Return True if the cached PDF exists and is newer than the session."""
    if not cache_path.exists():
        return False
    cache_mtime = cache_path.stat().st_mtime
    if session_record.updated_at is not None:
        return cache_mtime >= session_record.updated_at.timestamp()
    return True


@router.get("/report")
async def download_report(sid: str, request: Request, db: Session = Depends(get_db_session)):
    """Assemble a penetration-test report for the session.

    Query params:
        format: "pdf" (default), "html", or "markdown"
    """
    session = db.query(SessionRecord).filter_by(id=sid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    records = (
        db.query(TaskRecord)
        .filter_by(session_id=sid)
        .order_by(TaskRecord.created_at)
        .all()
    )

    # Reuse the ASCII attack graph if a runner is active, else load from DB.
    runner = WebAgentRunner.get(sid)
    if runner:
        graph_text = runner.agent.task_manager.attack_graph_view()
    else:
        from Ion.tools.task_tool import PersistentTaskManager
        tm = PersistentTaskManager(sid, db=get_default_db())
        tm.load_from_db()
        graph_text = tm.attack_graph_view()

    # Load messages for system info / endpoint extraction
    msg_records = (
        db.query(MessageRecord)
        .filter_by(session_id=sid)
        .order_by(MessageRecord.id.asc())
        .all()
    )
    messages = [r.to_dict() for r in msg_records]

    # Load model-submitted report (from submit_report tool call)
    report_record = (
        db.query(ReportRecord)
        .filter_by(session_id=sid)
        .order_by(ReportRecord.id.desc())
        .first()
    )
    report_data_dict = report_record.to_dict() if report_record else None

    fmt = (request.query_params.get("format") or "pdf").lower()

    if fmt == "markdown":
        return _build_markdown_response(session, records, graph_text, report_data_dict)

    report_data = ReportData(
        session=session.to_dict(),
        tasks=[r.to_dict() for r in records],
        messages=messages,
        graph_text=graph_text,
        report_record=report_data_dict,
    )

    if fmt == "html":
        html = render_report_html(report_data)
        return Response(content=html, media_type="text/html; charset=utf-8")

    # Default: PDF
    REPORT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(sid)

    if _is_cache_valid(cache_path, session):
        return FileResponse(
            path=cache_path,
            media_type="application/pdf",
            filename=f"pentest-report-{sid}.pdf",
        )

    try:
        await generate_pdf(report_data, cache_path)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"PDF generation failed: {exc}",
        )

    return FileResponse(
        path=cache_path,
        media_type="application/pdf",
        filename=f"pentest-report-{sid}.pdf",
    )


def _build_markdown_response(session, records, graph_text, report_data=None):
    completed = [r for r in records if r.status == "completed"]
    failed = [r for r in records if r.status == "failed"]

    lines: list[str] = []
    lines.append(f"# Exploit Chain Atlas Report")
    lines.append("")
    lines.append(f"- **Session ID**: `{session.id}`")
    lines.append(f"- **Title**: {session.title or 'Untitled'}")
    lines.append(f"- **Mode**: {session.mode}")
    lines.append(f"- **Status**: {session.status}")
    if session.created_at:
        lines.append(f"- **Created**: {session.created_at.isoformat()}")
    if session.updated_at:
        lines.append(f"- **Updated**: {session.updated_at.isoformat()}")
    lines.append("")
    lines.append(f"## Summary")
    lines.append("")
    lines.append(f"- Total tasks: **{len(records)}**")
    lines.append(f"- Completed: **{len(completed)}**")
    lines.append(f"- Failed: **{len(failed)}**")
    lines.append("")
    lines.append("## Attack Graph")
    lines.append("")
    lines.append("```")
    lines.append(graph_text or "No tasks yet.")
    lines.append("```")
    lines.append("")
    lines.append("## Task Chain")
    lines.append("")

    if not records:
        lines.append("_No tasks recorded for this session._")
    else:
        for idx, r in enumerate(records, start=1):
            data = r.to_dict()
            depend_on = data.get("depend_on") or []
            lines.append(f"### {idx}. {r.name}")
            lines.append("")
            lines.append(f"- **ID**: `{r.id}`")
            lines.append(f"- **Status**: `{r.status}`")
            lines.append(f"- **Attempts**: {r.attempt_count}/{r.max_attempts}")
            lines.append(f"- **On failure**: {r.on_failure}")
            if depend_on:
                deps_md = ", ".join(f"`{d}`" for d in depend_on)
                lines.append(f"- **Depends on**: {deps_md}")
            else:
                lines.append("- **Depends on**: _none (root task)_")
            if r.intelligence_source:
                lines.append(f"- **Intelligence source**: {r.intelligence_source}")
            lines.append("")
            lines.append("**Description**")
            lines.append("")
            lines.append(r.description or "_(no description)_")
            lines.append("")
            if r.result:
                lines.append("**Result**")
                lines.append("")
                lines.append("```")
                lines.append(r.result)
                lines.append("```")
                lines.append("")

    # ---- Model-Submitted Report ----
    if report_data:
        summary = report_data.get("summary_fields") or {}
        md_content = report_data.get("content_markdown") or ""
        if summary or md_content:
            lines.append("## AI-Generated Report")
            lines.append("")
            lines.append("### Structured Summary")
            lines.append("")
            lines.append(f"- **Target**: {summary.get('target', 'N/A')}")
            lines.append(f"- **Vulnerabilities**: {summary.get('vuln_count', 0)}")
            lines.append(f"- **Max Severity**: {summary.get('max_severity', 'N/A')}")
            services = summary.get("services_discovered") or []
            if services:
                lines.append("- **Services Discovered**:")
                for s in services:
                    lines.append(f"  - `{s}`")
            vulns = summary.get("vulnerabilities") or []
            if vulns:
                lines.append("")
                lines.append("### Vulnerabilities")
                lines.append("")
                for idx, v in enumerate(vulns, 1):
                    lines.append(f"#### {idx}. {v.get('name', 'Unknown')}")
                    lines.append("")
                    lines.append(f"- **Service**: `{v.get('service', 'N/A')}`")
                    if v.get("url"):
                        lines.append(f"- **URL**: `{v['url']}`")
                    lines.append(f"- **Severity**: **{v.get('severity', 'Info')}**")
                    if v.get("type"):
                        lines.append(f"- **Type**: {v['type']}")
                    if v.get("payload"):
                        lines.append("- **Payload**:")
                        lines.append("  ```")
                        lines.append(f"  {v['payload']}")
                        lines.append("  ```")
                    if v.get("remediation"):
                        lines.append(f"- **Remediation**: {v['remediation']}")
                    lines.append("")
            if md_content:
                lines.append("---")
                lines.append("")
                lines.append(md_content)
                lines.append("")

    body = "\n".join(lines).encode("utf-8")
    filename = f"exploit-chain-atlas-{session.id}.md"
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
