from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.responses import Response

from Ion.db import Database, get_default_db
from Ion.db.models import SessionRecord, TaskRecord
from Ion.web.schemas import TaskOut, AttackGraphOut
from Ion.web.agent_runner import WebAgentRunner

router = APIRouter()


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


@router.get("/report")
def download_report(sid: str, db: Session = Depends(get_db_session)):
    """Assemble a Markdown exploit-chain report for the session."""
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

    body = "\n".join(lines).encode("utf-8")
    filename = f"exploit-chain-atlas-{session.id}.md"
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
