from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from Ion.web.api import sessions, tasks, agent, logs

app = FastAPI(title="Ion Agent Web API", version="0.1.0")

# CORS — allow all origins for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(tasks.router, prefix="/api/sessions/{sid}/tasks", tags=["tasks"])
app.include_router(agent.router, prefix="/api/sessions/{sid}", tags=["agent"])
app.include_router(logs.router, prefix="/api/sessions/{sid}/logs", tags=["logs"])

@app.get("/health")
def health():
    return {"status": "ok"}


# Static files (frontend assets) — mounted last so API routes take precedence
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
