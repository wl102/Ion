from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from Ion.db import get_default_db
from Ion.db.models import SessionRecord
from Ion.web.schemas import RunRequest, HookRequest
from Ion.web.agent_runner import WebAgentRunner

router = APIRouter()


def get_db_session(db=Depends(get_default_db)):
    return next(db.get_session())


@router.post("/run")
async def run_agent(sid: str, req: RunRequest, db: Session = Depends(get_db_session)):
    session = db.query(SessionRecord).filter_by(id=sid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status == "running":
        raise HTTPException(status_code=409, detail="Session is already running")

    session.status = "running"
    db.commit()

    runner = WebAgentRunner.get_or_create(
        sid,
        db=get_default_db(),
        mode=session.mode,
        log_dir=session.log_dir,
    )
    await runner.start(req.query)
    return {"status": "started", "session_id": sid}


@router.post("/hook")
async def submit_hook(sid: str, req: HookRequest, db: Session = Depends(get_db_session)):
    session = db.query(SessionRecord).filter_by(id=sid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    runner = WebAgentRunner.get(sid)
    if not runner:
        raise HTTPException(status_code=409, detail="Agent not running")
    await runner.submit_hook(req.content)
    return {"status": "hook_submitted", "session_id": sid}


@router.post("/interrupt")
async def interrupt_agent(sid: str, db: Session = Depends(get_db_session)):
    session = db.query(SessionRecord).filter_by(id=sid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    runner = WebAgentRunner.get(sid)
    if not runner:
        raise HTTPException(status_code=409, detail="Agent not running")
    runner.interrupt()
    session.status = "paused"
    db.commit()
    return {"status": "interrupted", "session_id": sid}


@router.post("/resume")
async def resume_agent(sid: str, req: RunRequest, db: Session = Depends(get_db_session)):
    session = db.query(SessionRecord).filter_by(id=sid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    runner = WebAgentRunner.get(sid)
    if not runner:
        raise HTTPException(status_code=409, detail="Agent not running")
    await runner.submit_hook(req.query)
    runner.resume()
    session.status = "running"
    db.commit()
    return {"status": "resumed", "session_id": sid}


@router.get("/stream")
async def stream_events(sid: str, db: Session = Depends(get_db_session)):
    session = db.query(SessionRecord).filter_by(id=sid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    runner = WebAgentRunner.get(sid)
    if not runner:
        raise HTTPException(status_code=409, detail="Agent not running")

    async def event_generator():
        async for line in runner.iter_sse():
            yield line
        # Mark session as no longer running when stream ends
        if runner._done:
            session.status = "completed"
            db.commit()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
