from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Session schemas
# ---------------------------------------------------------------------------

SessionMode = Literal["general", "security", "ctf"]


class SessionCreate(BaseModel):
    title: str = ""
    mode: SessionMode = "general"
    query: str = ""


class SessionOut(BaseModel):
    id: str
    title: str
    mode: SessionMode
    status: str
    log_dir: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Agent run / hook schemas
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    query: str


class HookRequest(BaseModel):
    content: str


class SSEEvent(BaseModel):
    type: str  # system | assistant | tool_start | tool_result | task_update | hook_received | subagent_start | subagent_end | done | error
    payload: Any
    reasoning: bool = False
    tool_name: str = ""
    duration_ms: float = 0.0
    agent_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Task schemas
# ---------------------------------------------------------------------------


class TaskOut(BaseModel):
    id: str
    session_id: str
    name: str
    description: str
    status: str
    depend_on: list[str] = Field(default_factory=list)
    result: Optional[str] = None
    on_failure: str = "replan"
    attempt_count: int = 0
    max_attempts: int = 1
    information_score: int = 0
    intelligence_source: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AttackGraphOut(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# Log schemas
# ---------------------------------------------------------------------------


class LogsOut(BaseModel):
    files: list[str]
    content: dict[str, Any]


# ---------------------------------------------------------------------------
# Message (chat history) schemas
# ---------------------------------------------------------------------------


class MessageOut(BaseModel):
    id: int
    session_id: str
    message_id: str = ""
    role: str
    content: Optional[str] = None
    reasoning_content: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = None
    tool_call_id: str = ""
    tool_name: str = ""
    duration_ms: float = 0.0
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
