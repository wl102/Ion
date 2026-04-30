from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from Ion.db import Database, get_default_db
from Ion.db.models import SessionRecord
from Ion.web.schemas import SessionCreate, SessionOut

router = APIRouter()


def get_db_session(db: Database = Depends(get_default_db)) -> Session:
    yield from db.get_session()


@router.post("", response_model=SessionOut)
def create_session(req: SessionCreate, db: Session = Depends(get_db_session)):
    sid = str(uuid.uuid4())[:8]
    log_dir = str(Path.home() / ".ion" / "logs" / sid)
    record = SessionRecord(
        id=sid,
        title=req.title or req.query[:50],
        mode=req.mode,
        status="idle",
        log_dir=log_dir,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("", response_model=list[SessionOut])
def list_sessions(skip: int = 0, limit: int = 50, db: Session = Depends(get_db_session)):
    records = (
        db.query(SessionRecord)
        .order_by(SessionRecord.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return records


@router.get("/{sid}", response_model=SessionOut)
def get_session(sid: str, db: Session = Depends(get_db_session)):
    record = db.query(SessionRecord).filter_by(id=sid).first()
    if not record:
        raise HTTPException(status_code=404, detail="Session not found")
    return record


@router.delete("/{sid}")
def delete_session(sid: str, db: Session = Depends(get_db_session)):
    record = db.query(SessionRecord).filter_by(id=sid).first()
    if not record:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(record)
    db.commit()
    from Ion.web.agent_runner import WebAgentRunner
    WebAgentRunner.remove(sid)
    return {"deleted": True}
