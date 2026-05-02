from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from Ion.db import Database, get_default_db
from Ion.db.models import MessageRecord, SessionRecord
from Ion.web.schemas import MessageOut

router = APIRouter()


def get_db_session(db: Database = Depends(get_default_db)):
    yield from db.get_session()


@router.get("", response_model=list[MessageOut])
def list_messages(
    sid: str,
    skip: int = 0,
    limit: int = 1000,
    db: Session = Depends(get_db_session),
):
    """Return the persisted conversation history for a session.

    Messages are returned in chronological order (id ASC) so the frontend
    can render them top-to-bottom without further sorting.
    """
    session = db.query(SessionRecord).filter_by(id=sid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    records = (
        db.query(MessageRecord)
        .filter_by(session_id=sid)
        .order_by(MessageRecord.id.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [r.to_dict() for r in records]


@router.delete("")
def clear_messages(sid: str, db: Session = Depends(get_db_session)):
    """Delete all persisted messages for a session (chat history reset)."""
    session = db.query(SessionRecord).filter_by(id=sid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    deleted = (
        db.query(MessageRecord).filter_by(session_id=sid).delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": deleted}
