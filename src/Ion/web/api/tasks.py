from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from Ion.db import get_default_db
from Ion.db.models import SessionRecord, TaskRecord
from Ion.web.schemas import TaskOut, AttackGraphOut
from Ion.web.agent_runner import WebAgentRunner

router = APIRouter()


def get_db_session(db=Depends(get_default_db)):
    return next(db.get_session())


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
