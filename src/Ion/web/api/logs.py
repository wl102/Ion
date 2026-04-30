from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from Ion.db import Database, get_default_db
from Ion.db.models import SessionRecord
from Ion.web.schemas import LogsOut

router = APIRouter()


def get_db_session(db: Database = Depends(get_default_db)):
    yield from db.get_session()


@router.get("", response_model=LogsOut)
def get_logs(sid: str, db: Session = Depends(get_db_session)):
    session = db.query(SessionRecord).filter_by(id=sid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    log_dir = Path(session.log_dir) if session.log_dir else Path.home() / ".ion" / "logs" / sid
    if not log_dir.exists():
        return LogsOut(files=[], content={})

    files = [f.name for f in log_dir.iterdir() if f.is_file()]
    content: dict[str, list] = {}
    for fname in files:
        fpath = log_dir / fname
        if fname.endswith(".jsonl"):
            lines = []
            for line in fpath.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        lines.append({"raw": line})
            content[fname] = lines
        else:
            content[fname] = fpath.read_text(encoding="utf-8")

    return LogsOut(files=files, content=content)
