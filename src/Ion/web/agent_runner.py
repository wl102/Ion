from __future__ import annotations

import asyncio
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from Ion.agent import IonAgent
from Ion.db import Database
from Ion.db.models import MessageRecord
from Ion.observability import ObservabilityLogger
from Ion.tools.task_tool import PersistentTaskManager


class _AssistantBuffer:
    """Accumulates streamed chunks for one assistant message."""

    __slots__ = ("content", "reasoning")

    def __init__(self) -> None:
        self.content: list[str] = []
        self.reasoning: list[str] = []


class WebAgentRunner:
    """Manages a single IonAgent session with SSE streaming and hook support."""

    _runners: dict[str, "WebAgentRunner"] = {}
    _lock = threading.Lock()

    def __init__(
        self,
        session_id: str,
        db: Database,
        model_id: str = "",
        base_url: str | None = None,
        api_key: str | None = None,
        mode: str = "general",
        log_dir: str | None = None,
    ):
        self.session_id = session_id
        self.db = db
        self.sse_queue: asyncio.Queue[dict[str, Any]] | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._queue_ready = asyncio.Event()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"agent-{session_id}")
        self._run_future: Any = None
        self._done = False
        self._pause_event = threading.Event()
        self._pause_event.set()  # default: not paused

        # Per-message_id assistant streaming buffers (held only during a turn)
        self._assistant_buffers: dict[str, _AssistantBuffer] = {}
        # Persistence is serialized to a single thread to avoid SQLite contention
        self._persist_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"persist-{session_id}"
        )

        _model_id = model_id or os.getenv("MODEL_ID", "")
        _base_url = base_url or os.getenv("OPENAI_BASE_URL")
        _api_key = api_key or os.getenv("OPENAI_API_KEY")

        logger = ObservabilityLogger(log_dir=log_dir, run_id=session_id, agent_name="root")
        task_manager = PersistentTaskManager(session_id, db)
        task_manager.load_from_db()

        self.agent = IonAgent(
            model_id=_model_id,
            base_url=_base_url,
            api_key=_api_key,
            mode=mode,
            task_manager=task_manager,
            logger=logger,
        )
        self.logger = logger

    @classmethod
    def get_or_create(
        cls,
        session_id: str,
        db: Database,
        mode: str = "general",
        log_dir: str | None = None,
    ) -> "WebAgentRunner":
        with cls._lock:
            if session_id not in cls._runners:
                cls._runners[session_id] = cls(session_id, db, mode=mode, log_dir=log_dir)
            return cls._runners[session_id]

    @classmethod
    def get(cls, session_id: str) -> "WebAgentRunner" | None:
        with cls._lock:
            return cls._runners.get(session_id)

    @classmethod
    def remove(cls, session_id: str):
        with cls._lock:
            runner = cls._runners.pop(session_id, None)
            if runner:
                runner._executor.shutdown(wait=False)
                runner._persist_executor.shutdown(wait=False)

    # ------------------------------------------------------------------ #
    #  Persistence helpers                                               #
    # ------------------------------------------------------------------ #

    def _persist_message(
        self,
        role: str,
        content: str | None = None,
        reasoning_content: str | None = None,
        tool_calls: list[dict] | None = None,
        tool_call_id: str = "",
        tool_name: str = "",
        duration_ms: float = 0.0,
        message_id: str = "",
    ) -> None:
        """Schedule an INSERT into messages table on the persistence thread."""

        def _do_insert() -> None:
            try:
                with next(self.db.get_session()) as sess:
                    record = MessageRecord(
                        session_id=self.session_id,
                        message_id=message_id,
                        role=role,
                        content=content,
                        reasoning_content=reasoning_content,
                        tool_calls=json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        duration_ms=duration_ms,
                    )
                    sess.add(record)
                    sess.commit()
            except Exception as exc:  # pragma: no cover — keep agent running
                print(f"[message-persist] failed to insert {role!r}: {exc}")

        self._persist_executor.submit(_do_insert)

    def _make_callbacks(self) -> dict[str, Any]:
        """Build callback dict for IonAgent.run() to capture streaming events.

        Must be called from within the thread that runs agent.run().
        """
        loop = self._main_loop
        if loop is None:
            raise RuntimeError("Main event loop not set; call start() first.")

        def put_event(event: dict[str, Any]):
            if self.sse_queue is not None:
                asyncio.run_coroutine_threadsafe(self.sse_queue.put(event), loop)

        def on_assistant_start(message_id: str, agent_name: str = "root", **_):
            self._assistant_buffers[message_id or ""] = _AssistantBuffer()
            put_event({
                "type": "assistant_start",
                "message_id": message_id,
                "agent_name": agent_name,
            })

        def on_assistant_chunk(
            text: str,
            reasoning: bool = False,
            message_id: str = "",
            agent_name: str = "root",
            **_,
        ):
            buf = self._assistant_buffers.get(message_id or "")
            if buf is None:
                buf = _AssistantBuffer()
                self._assistant_buffers[message_id or ""] = buf
            (buf.reasoning if reasoning else buf.content).append(text)
            put_event({
                "type": "assistant",
                "payload": text,
                "reasoning": reasoning,
                "message_id": message_id,
                "agent_name": agent_name,
            })

        def on_assistant_end(message_id: str, agent_name: str = "root", **_):
            buf = self._assistant_buffers.pop(message_id or "", None)
            if buf is not None:
                content = "".join(buf.content) or None
                reasoning = "".join(buf.reasoning) or None
                if content or reasoning:
                    self._persist_message(
                        role="assistant",
                        content=content,
                        reasoning_content=reasoning,
                        message_id=message_id or "",
                    )
            put_event({
                "type": "assistant_end",
                "message_id": message_id,
                "agent_name": agent_name,
            })

        def on_tool_start(names: list[str], agent_name: str = "root", **_):
            put_event({
                "type": "tool_start",
                "payload": names,
                "agent_name": agent_name,
            })

        def on_tool_result(
            name: str,
            output: str,
            duration_ms: float,
            agent_name: str = "root",
            **_,
        ):
            # Persist full tool output (no truncation in DB).
            self._persist_message(
                role="tool",
                content=output,
                tool_name=name,
                duration_ms=round(duration_ms, 2),
            )
            # Truncate large outputs for SSE
            payload = output if len(output) < 5000 else output[:5000] + "\n...[truncated]"
            put_event(
                {
                    "type": "tool_result",
                    "payload": payload,
                    "tool_name": name,
                    "duration_ms": round(duration_ms, 2),
                    "agent_name": agent_name,
                }
            )

        def on_subagent_start(agent_name: str, goal: str = "", **_):
            put_event({
                "type": "subagent_start",
                "agent_name": agent_name,
                "payload": goal,
            })

        def on_subagent_end(
            agent_name: str,
            summary: str = "",
            status: str = "",
            **_,
        ):
            put_event({
                "type": "subagent_end",
                "agent_name": agent_name,
                "payload": {"summary": summary, "status": status},
            })

        def on_turn_complete(turn_count: int, finish_reason: str | None):
            tasks = self.agent.task_manager.list_tasks()
            if tasks:
                put_event(
                    {
                        "type": "task_update",
                        "payload": [t.model_dump() for t in tasks],
                    }
                )
            # Push recent tool log entries so frontend sees full execution details
            log_entries = self._read_recent_tool_logs()
            if log_entries:
                put_event({"type": "tool_log", "payload": log_entries})

        return {
            "on_assistant_start": on_assistant_start,
            "on_assistant_chunk": on_assistant_chunk,
            "on_assistant_end": on_assistant_end,
            "on_tool_start": on_tool_start,
            "on_tool_result": on_tool_result,
            "on_subagent_start": on_subagent_start,
            "on_subagent_end": on_subagent_end,
            "on_turn_complete": on_turn_complete,
        }

    def _read_recent_tool_logs(self) -> list[dict[str, Any]]:
        """Read the most recent lines from the current session's tool log file."""
        log_dir = Path(self.logger.log_dir)
        date_str = self.logger.date_str
        tool_log = log_dir / f"tools_{date_str}.jsonl"
        if not tool_log.exists():
            return []
        try:
            lines = tool_log.read_text(encoding="utf-8").splitlines()
            entries = []
            for line in lines[-5:]:
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            return entries
        except Exception:
            return []

    def interrupt(self):
        """Pause the agent loop after the current turn completes."""
        self._pause_event.clear()

    def resume(self):
        """Resume a paused agent loop."""
        self._pause_event.set()

    def _agent_run_wrapper(self, query: str):
        """Runs in a background thread."""
        try:
            if self.sse_queue is not None and self._main_loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self.sse_queue.put({"type": "system", "payload": "Agent started"}),
                    self._main_loop,
                )
            callbacks = self._make_callbacks()

            def pause_check():
                self._pause_event.wait()

            result = self.agent.run(query, callbacks=callbacks, pause_check=pause_check)
            if self.sse_queue is not None and self._main_loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self.sse_queue.put({"type": "done", "payload": result}),
                    self._main_loop,
                )
        except Exception as exc:
            if self.sse_queue is not None and self._main_loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self.sse_queue.put({"type": "error", "payload": str(exc)}),
                    self._main_loop,
                )
        finally:
            self._done = True

    async def start(self, query: str):
        """Start the agent in a background thread."""
        if self._run_future is not None and not self._run_future.done():
            raise RuntimeError("Agent is already running")
        self._done = False
        self._main_loop = asyncio.get_running_loop()
        self.sse_queue = asyncio.Queue()
        self._queue_ready.set()
        # Persist the user's query as a user message before the agent starts.
        self._persist_message(role="user", content=query)
        loop = self._main_loop
        self._run_future = loop.run_in_executor(self._executor, self._agent_run_wrapper, query)

    async def submit_hook(self, content: str):
        self.agent.submit_hook(content)
        # Hooks become user messages in the agent loop — persist them too.
        self._persist_message(role="user", content=content)
        if self.sse_queue is not None:
            await self.sse_queue.put({"type": "hook_received", "payload": content})

    async def iter_sse(self):
        """Async generator yielding SSE formatted lines.

        Waits until the queue is ready (start() has been called) so that
        consumers can connect before the agent begins running without
        missing events.
        """
        await self._queue_ready.wait()
        if self.sse_queue is None:
            return
        while True:
            try:
                event = await asyncio.wait_for(self.sse_queue.get(), timeout=0.5)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") in ("done", "error"):
                    break
            except asyncio.TimeoutError:
                if self._done and self.sse_queue.empty():
                    break
                yield ":heartbeat\n\n"
