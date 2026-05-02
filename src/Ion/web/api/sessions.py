from __future__ import annotations

import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAI
from sqlalchemy.orm import Session

from Ion.db import Database, get_default_db
from Ion.db.models import SessionRecord
from Ion.web.schemas import SessionCreate, SessionOut

# Load env at import. Title generation runs before any agent is constructed,
# so we cannot rely on Ion.agent's load_dotenv firing first.
load_dotenv()

router = APIRouter()


def get_db_session(db: Database = Depends(get_default_db)) -> Session:
    yield from db.get_session()


_TITLE_SYSTEM_PROMPT = (
    "You output a short title only. 2-6 words. "
    "No quotes, no surrounding punctuation, no explanation, no leading "
    "label. The title summarizes the user task."
)


def _fallback_title(query: str) -> str:
    line = (query or "").strip().splitlines()[0] if query else ""
    return (line[:50] or "Untitled").strip()


def _clean_title(text: str) -> str:
    # Some reasoning models prepend the answer with markers like "Title:"
    # or wrap it in quotes — strip those before truncating.
    text = (text or "").strip()
    if not text:
        return ""
    for line in text.splitlines():
        line = line.strip().strip("\"'`*")
        if not line:
            continue
        lowered = line.lower()
        for prefix in ("title:", "session title:", "name:"):
            if lowered.startswith(prefix):
                line = line[len(prefix):].strip().strip("\"'`*")
                break
        line = line.rstrip(".!?")
        if line:
            return line[:80]
    return ""


def _generate_title(query: str, mode: str) -> str:
    """Ask the configured LLM for a short session title.

    Falls back to a truncated query on any error (missing config, network,
    timeout). Never raises — title generation must not block session creation.
    """
    query = (query or "").strip()
    if not query:
        return "Untitled"

    model_id = os.getenv("MODEL_ID", "")
    base_url = os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("OPENAI_API_KEY")
    if not (model_id and base_url and api_key):
        return _fallback_title(query)

    try:
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=30.0)
        # max_tokens is generous so reasoning-style models (which spend the
        # bulk of their budget on internal chain-of-thought) can still emit
        # the final title in the output channel.
        resp = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": _TITLE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Task: {query[:1000]}\nMode: {mode}\nTitle:",
                },
            ],
            max_tokens=2048,
            temperature=0.2,
        )
        title = _clean_title(resp.choices[0].message.content or "")
        return title or _fallback_title(query)
    except Exception:
        return _fallback_title(query)


@router.post("", response_model=SessionOut)
def create_session(req: SessionCreate, db: Session = Depends(get_db_session)):
    sid = str(uuid.uuid4())[:8]
    log_dir = str(Path.home() / ".ion" / "logs" / sid)
    title = req.title.strip() if req.title else ""
    if not title:
        title = _generate_title(req.query, req.mode)
    record = SessionRecord(
        id=sid,
        title=title,
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
