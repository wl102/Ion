import json
from datetime import datetime
from typing import Any, Optional, List

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    mode: Mapped[str] = mapped_column(String(32), default="general")
    status: Mapped[str] = mapped_column(String(32), default="idle")
    log_dir: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    tasks: Mapped[List["TaskRecord"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    hooks: Mapped[List["HookRecord"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    messages: Mapped[List["MessageRecord"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "mode": self.mode,
            "status": self.status,
            "log_dir": self.log_dir,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TaskRecord(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    depend_on: Mapped[str] = mapped_column(Text, default="[]")
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    on_failure: Mapped[str] = mapped_column(String(32), default="replan")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    information_score: Mapped[int] = mapped_column(Integer, default=0)
    intelligence_source: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    session: Mapped["SessionRecord"] = relationship(back_populates="tasks")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "depend_on": json.loads(self.depend_on) if self.depend_on else [],
            "result": self.result,
            "on_failure": self.on_failure,
            "attempt_count": self.attempt_count,
            "max_attempts": self.max_attempts,
            "information_score": self.information_score,
            "intelligence_source": self.intelligence_source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class HookRecord(Base):
    __tablename__ = "hooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    session: Mapped["SessionRecord"] = relationship(back_populates="hooks")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "content": self.content,
            "consumed": self.consumed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class MessageRecord(Base):
    """Persisted conversation message for a session.

    Stores assistant/user/tool/system messages so a session's chat history
    survives process restarts and can be displayed when the user re-opens
    a session.
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    # Stable identifier for grouping streamed chunks; empty for non-assistant.
    message_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    role: Mapped[str] = mapped_column(String(16))  # system/user/assistant/tool
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reasoning_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Assistant tool_calls list (JSON-encoded) when role == "assistant".
    tool_calls: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # For role == "tool"
    tool_call_id: Mapped[str] = mapped_column(String(128), default="")
    tool_name: Mapped[str] = mapped_column(String(128), default="")
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    session: Mapped["SessionRecord"] = relationship(back_populates="messages")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "role": self.role,
            "content": self.content,
            "reasoning_content": self.reasoning_content,
            "tool_calls": json.loads(self.tool_calls) if self.tool_calls else None,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def to_openai_message(self) -> dict[str, Any]:
        """Reconstruct the message dict shape used by the OpenAI/IonAgent loop."""
        msg: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            msg["content"] = self.content
        if self.reasoning_content:
            msg["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            try:
                msg["tool_calls"] = json.loads(self.tool_calls)
            except json.JSONDecodeError:
                pass
        if self.role == "tool" and self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        return msg
