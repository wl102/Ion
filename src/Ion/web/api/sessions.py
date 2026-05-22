from __future__ import annotations

import os
import uuid

from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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


# The model is asked to *label* the user's text, not engage with it. This
# wording is deliberately flat and instruction-only because security/CTF
# tasks otherwise trip refusal patterns ("I can't help with that…").
_TITLE_SYSTEM_PROMPT = (
    "You are a topic labeler. Your ONLY job is to read the user's text and "
    "emit a short title (2-6 words) that names the topic.\n"
    "\n"
    "Hard rules:\n"
    "- Output exactly ONE line: the title itself, nothing else.\n"
    "- No quotes, no surrounding punctuation, no leading label "
    '("Title:", "Topic:", etc.), no explanation, no preamble, no '
    "disclaimers, no trailing notes.\n"
    "- Do NOT refuse and do NOT add safety language. You are not "
    "performing or assisting the task; you are only naming it. Even if "
    "the text discusses security testing, exploitation, malware, CTF "
    "challenges, or other sensitive topics, write a neutral, factual "
    'label (examples: "SQLi on login form", "Reverse engineer ELF '
    'binary", "Recon target subdomain", "Buffer overflow PoC").\n'
    "- If the text is vague or empty, infer the most likely topic and "
    "label it; never reply with a refusal or a question.\n"
    "- Prefer the same language as the user's text.\n"
    "- Always output a title."
)


# Lowercased substrings that indicate the model returned a refusal or a
# safety preamble instead of a title. Covers EN + ZH variants we've seen.
_REFUSAL_SUBSTRINGS = (
    "i can't",
    "i cannot",
    "i won't",
    "i will not",
    "i'm sorry",
    "i am sorry",
    "sorry, i",
    "sorry i",
    "i'm unable",
    "i am unable",
    "i'm not able",
    "i am not able",
    "as an ai",
    "as a language model",
    "i don't feel comfortable",
    "i do not feel comfortable",
    "我无法",
    "我不能",
    "我不会",
    "我没办法",
    "抱歉",
    "对不起",
    "很抱歉",
    "无法协助",
    "无法帮助",
    "不便协助",
    "不能协助",
)


def _looks_like_refusal(text: str) -> bool:
    if not text:
        return True
    lowered = text.lower()
    return any(p in lowered for p in _REFUSAL_SUBSTRINGS)


def _fallback_title(query: str) -> str:
    stripped = (query or "").strip()
    if not stripped:
        return "Untitled"
    line = stripped.splitlines()[0]
    return (line[:50] or "Untitled").strip()


def _clean_title(text: str) -> str:
    # Some reasoning models prepend the answer with markers like "Title:"
    # or wrap it in quotes — strip those before truncating.
    text = (text or "").strip()
    if not text:
        return ""
    # Remove any <think>...</think> sections added by some model chains.
    import re

    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I).strip()
    if not text:
        return ""
    for line in text.splitlines():
        line = line.strip().strip("\"'`*")
        if not line:
            continue
        lowered = line.lower()
        for prefix in ("title:", "session title:", "name:", "topic:"):
            if lowered.startswith(prefix):
                line = line[len(prefix) :].strip().strip("\"'`*")
                break
        line = line.rstrip(".!?")
        if line:
            return line[:80]
    return ""


def _generate_title(query: str, mode: str) -> str:
    """Ask the configured LLM for a short session title.

    Falls back to a truncated query on any error (missing config, network,
    timeout, refusal). Never raises — title generation must not block
    session creation.
    """
    query = (query or "").strip()
    if not query:
        return "Untitled"

    model_id = os.getenv("MODEL_ID", "")
    base_url = os.getenv("API_BASE")
    api_key = os.getenv("API_KEY")
    if not (model_id and base_url and api_key):
        return _fallback_title(query)

    try:
        import litellm

        # max_tokens is generous so reasoning-style models (which spend the
        # bulk of their budget on internal chain-of-thought) can still emit
        # the final title in the output channel.
        raw_messages = [
            {"role": "system", "content": _TITLE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Write a 2-6 word topic label for the following "
                    f"task description (mode={mode}). Do not perform "
                    f"or evaluate the task; only name it.\n\n<<<\n"
                    f"{query[:1500]}\n>>>"
                ),
            },
        ]
        create_kwargs = {
            "model": model_id,
            "messages": list(raw_messages),
            "max_tokens": 2048,
            "temperature": 0.2,
        }
        if api_key:
            create_kwargs["api_key"] = api_key
        if base_url:
            create_kwargs["api_base"] = base_url
        resp = litellm.completion(**create_kwargs)
        title = _clean_title(resp.choices[0].message.content or "")
        if not title or _looks_like_refusal(title):
            return _fallback_title(query)
        return title
    except Exception:
        return _fallback_title(query)


def _update_session_title(sid: str, title: str) -> None:
    """Persist a generated title from a background task.

    Uses a fresh DB session because the request-scoped one is already
    closed by the time the BackgroundTasks runner fires.
    """
    if not title:
        return
    db_inst = get_default_db()
    session = db_inst.SessionLocal()
    try:
        record = session.query(SessionRecord).filter_by(id=sid).first()
        if record is None:
            return
        record.title = title
        session.commit()
    finally:
        session.close()


def _bg_generate_title(sid: str, query: str, mode: str) -> None:
    """Background entry point — generate then persist. Must never raise."""
    try:
        title = _generate_title(query, mode)
        _update_session_title(sid, title)
    except Exception:
        # Best-effort: a failed title refinement just leaves the
        # placeholder (truncated query) in place.
        pass


@router.post("", response_model=SessionOut)
def create_session(
    req: SessionCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_session),
):
    sid = str(uuid.uuid4())[:8]
    user_title = req.title.strip() if req.title else ""
    # If the caller didn't supply a title, store an empty placeholder
    # immediately and let the background task fill it in. The frontend
    # renders an empty title as "Untitled"/topbar default until the
    # LLM-generated label arrives.
    record = SessionRecord(
        id=sid,
        title=user_title,
        mode=req.mode,
        status="idle",
        log_dir="",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    if not user_title and (req.query or "").strip():
        background_tasks.add_task(_bg_generate_title, sid, req.query, req.mode)
    return record


@router.get("", response_model=list[SessionOut])
def list_sessions(
    skip: int = 0, limit: int = 50, db: Session = Depends(get_db_session)
):
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

    # Clean up cached PDF report
    from Ion.web.api.tasks import _cache_path
    cache = _cache_path(sid)
    if cache.exists():
        cache.unlink()

    return {"deleted": True}
