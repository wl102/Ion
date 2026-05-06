from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from Ion.db import Database, get_default_db
from Ion.db.models import MessageRecord, SessionRecord
from Ion.web.schemas import LogsOut

router = APIRouter()


def get_db_session(db: Database = Depends(get_default_db)):
    yield from db.get_session()


@router.get("", response_model=LogsOut)
def get_logs(sid: str, db: Session = Depends(get_db_session)):
    session = db.query(SessionRecord).filter_by(id=sid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    records = (
        db.query(MessageRecord)
        .filter(MessageRecord.session_id == sid)
        .filter(MessageRecord.role.in_(["tool", "event"]))
        .all()
    )
    content: dict[str, list] = {}
    for r in records:
        if r.role == "tool":
            cat = "tool"
            payload: dict[str, Any] = {
                "timestamp": r.created_at.isoformat() if r.created_at else None,
                "tool_name": r.tool_name,
                "output": r.content,
                "duration_ms": r.duration_ms,
            }
            if r.arguments:
                try:
                    payload["arguments"] = json.loads(r.arguments)
                except json.JSONDecodeError:
                    pass
        else:
            try:
                payload = json.loads(r.meta) if r.meta else {}
            except json.JSONDecodeError:
                payload = {"raw": r.meta}
            cat = payload.get("event", "event")

        if cat not in content:
            content[cat] = []
        content[cat].append(payload)

    files = list(content.keys())
    return LogsOut(files=files, content=content)
