from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from Ion.db import Database, get_default_db
from Ion.db.models import SessionRecord
from Ion.web.schemas import RunRequest
from Ion.web.agent_runner import WebAgentRunner

router = APIRouter()


def get_db_session(db: Database = Depends(get_default_db)):
    yield from db.get_session()


@router.post("/run")
async def run_agent(sid: str, req: RunRequest, db: Session = Depends(get_db_session)):
    session = db.query(SessionRecord).filter_by(id=sid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    runner = WebAgentRunner.get_or_create(
        sid,
        db=get_default_db(),
        mode=session.mode,
    )

    # Use the runner's start_lock so that status check + start() are atomic
    # and multiple concurrent /run requests cannot race.
    async with runner._start_lock:
        if runner._run_future is not None and not runner._run_future.done():
            raise HTTPException(status_code=409, detail="Session is already running")
        session.status = "running"
        db.commit()
        await runner.start(req.query)

    return {"status": "started", "session_id": sid}


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
async def resume_agent(
    sid: str, req: RunRequest, db: Session = Depends(get_db_session)
):
    session = db.query(SessionRecord).filter_by(id=sid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    runner = WebAgentRunner.get(sid)
    if runner is None:
        # Server restart scenario: runner was lost but session may be paused.
        # Reconstruct the runner and resume from the database snapshot.
        if session.status != "paused":
            raise HTTPException(status_code=409, detail="Agent not running")
        runner = WebAgentRunner.get_or_create(
            sid,
            db=get_default_db(),
            mode=session.mode,
        )
        await runner.restore_and_resume(req.query)
        session.status = "running"
        db.commit()
        return {"status": "resumed_from_snapshot", "session_id": sid}

    async with runner._start_lock:
        if runner._run_future is None or runner._run_future.done():
            session.status = "running"
            db.commit()
            await runner.start(req.query)
            return {"status": "restarted", "session_id": sid}

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
        try:
            async for line in runner.iter_sse():
                yield line
        finally:
            # Mark session as no longer running when stream ends
            if runner._done and runner._final_status:
                session.status = runner._final_status
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


@router.get("/usage")
async def get_usage(sid: str, db: Session = Depends(get_db_session)):
    """Return token usage summary for a session."""
    session = db.query(SessionRecord).filter_by(id=sid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    runner = WebAgentRunner.get(sid)
    if not runner:
        raise HTTPException(status_code=409, detail="Agent not running")

    return runner.logger.get_usage_summary()
