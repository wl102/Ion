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
        self._sse_queues: set[asyncio.Queue[dict[str, Any]]] = set()
        self._sse_queues_lock = threading.Lock()
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._queue_ready = asyncio.Event()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"agent-{session_id}")
        self._run_future: Any = None
        self._done = False
        self._start_lock = asyncio.Lock()
        self._pause_event = threading.Event()
        self._pause_event.set()  # default: not paused

        # Per-message_id assistant streaming buffers (held only during a turn)
        self._assistant_buffers: dict[str, _AssistantBuffer] = {}
        # Persistence is serialized to a single thread to avoid SQLite contention
        self._persist_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"persist-{session_id}"
        )

        _model_id = model_id or os.getenv("MODEL_ID", "")
        _base_url = base_url or os.getenv("API_BASE")
        _api_key = api_key or os.getenv("API_KEY")

        def _persist_observability(category: str, entry: dict) -> None:
            # Tool calls are already persisted by on_tool_result callback.
            if category == "tool":
                return

            def _do_insert() -> None:
                try:
                    with next(self.db.get_session()) as sess:
                        record = MessageRecord(
                            session_id=self.session_id,
                            role="event" if category != "usage" else "usage",
                            meta=json.dumps(entry, ensure_ascii=False),
                        )
                        sess.add(record)
                        sess.commit()
                except Exception as exc:
                    print(f"[obs-persist] failed to insert {category!r}: {exc}")

            self._persist_executor.submit(_do_insert)

        logger = ObservabilityLogger(
            run_id=session_id, agent_name="root", persist_fn=_persist_observability
        )
        task_manager = PersistentTaskManager(session_id, db)
        task_manager.load_from_db()

        self.agent = IonAgent(
            model_id=_model_id,
            base_url=_base_url,
            api_key=_api_key,
            mode=mode,
            task_manager=task_manager,
            logger=logger,
            verbose=False,
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
                cls._runners[session_id] = cls(session_id, db, mode=mode)
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
    #  Broadcast helpers                                                 #
    # ------------------------------------------------------------------ #

    def _broadcast_event(self, event: dict[str, Any], sync: bool = False) -> None:
        """Send an event to all connected SSE consumers.

        Called from the agent background thread; uses run_coroutine_threadsafe
        so that Queue.put runs on the event-loop thread.

        When *sync* is True, the method blocks until every queue has actually
        received the event (or a short timeout expires). This prevents a race
        where ``self._done`` becomes True while the final ``done``/``error``
        event is still in-flight and has not yet landed in the consumer queues.
        """
        loop = self._main_loop
        if loop is None:
            return
        with self._sse_queues_lock:
            queues = list(self._sse_queues)
        if not queues:
            return
        futures = []
        for q in queues:
            try:
                fut = asyncio.run_coroutine_threadsafe(q.put(event), loop)
                futures.append(fut)
            except Exception:
                pass
        if sync and futures:
            for fut in futures:
                try:
                    fut.result(timeout=2.0)
                except Exception:
                    pass

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
        arguments: dict | None = None,
        meta: dict | None = None,
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
                        arguments=json.dumps(arguments, ensure_ascii=False) if arguments else None,
                        meta=json.dumps(meta, ensure_ascii=False) if meta else None,
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
            self._broadcast_event(event)

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

        def on_assistant_end(message_id: str, agent_name: str = "root", tool_calls: list[dict] | None = None, **_):
            buf = self._assistant_buffers.pop(message_id or "", None)
            if buf is not None:
                content = "".join(buf.content) or None
                reasoning = "".join(buf.reasoning) or None
                if content or reasoning or tool_calls:
                    self._persist_message(
                        role="assistant",
                        content=content,
                        reasoning_content=reasoning,
                        message_id=message_id or "",
                        tool_calls=tool_calls,
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
            arguments: dict | None = None,
            tool_call_id: str = "",
            **_,
        ):
            # Persist full tool output (no truncation in DB).
            self._persist_message(
                role="tool",
                content=output,
                tool_name=name,
                tool_call_id=tool_call_id,
                duration_ms=round(duration_ms, 2),
                arguments=arguments,
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
            # Only push the full tool log summary when the agent actually stops
            # (not after every intermediate tool-calls turn). This prevents the
            # chat stream from being flooded with repetitive tool history.
            if finish_reason != "tool_calls":
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
        """Read the most recent tool log entries from the database."""
        try:
            from Ion.db.models import MessageRecord

            with next(self.db.get_session()) as sess:
                records = (
                    sess.query(MessageRecord)
                    .filter_by(session_id=self.session_id, role="tool")
                    .order_by(MessageRecord.id.desc())
                    .limit(5)
                    .all()
                )
                entries = []
                for r in reversed(records):
                    entry: dict[str, Any] = {
                        "timestamp": r.created_at.isoformat() if r.created_at else None,
                        "tool_name": r.tool_name,
                        "output": r.content,
                        "duration_ms": r.duration_ms,
                    }
                    if r.arguments:
                        try:
                            entry["arguments"] = json.loads(r.arguments)
                        except json.JSONDecodeError:
                            pass
                    entries.append(entry)
                return entries
        except Exception:
            return []

    def interrupt(self):
        """Pause the agent loop after the current turn completes."""
        self._pause_event.clear()

    def resume(self):
        """Resume a paused agent loop."""
        self._pause_event.set()

    def _rebuild_messages(self, max_tools: int = 15) -> list[dict]:
        """Rebuild message history from the database for session recovery.

        Keeps all system / user / assistant messages, but strips early tool
        results and orphaned tool_calls to avoid bloating the context window.
        """
        try:
            from Ion.db.models import MessageRecord

            with next(self.db.get_session()) as sess:
                records = (
                    sess.query(MessageRecord)
                    .filter_by(session_id=self.session_id)
                    .filter(MessageRecord.role.in_(["system", "user", "assistant", "tool"]))
                    .order_by(MessageRecord.id.asc())
                    .all()
                )
        except Exception:
            return []

        # Identify which tool records to keep (the most recent `max_tools`)
        # Only keep well-formed tool records that have a tool_call_id.
        tool_records = [r for r in records if r.role == "tool" and r.tool_call_id]
        kept_tool_ids = {r.id for r in tool_records[-max_tools:]} if tool_records else set()
        kept_tool_call_ids = {
            r.tool_call_id for r in tool_records[-max_tools:] if r.tool_call_id
        }

        messages: list[dict] = []
        for r in records:
            # Skip malformed tool messages (missing tool_call_id) entirely
            if r.role == "tool" and (r.id not in kept_tool_ids or not r.tool_call_id):
                continue

            msg = r.to_openai_message()

            # If assistant message references tool_calls whose results were
            # evicted, strip the tool_calls field to avoid confusing the model.
            if r.role == "assistant" and msg.get("tool_calls"):
                tc_ids = {tc["id"] for tc in msg["tool_calls"]}
                if not tc_ids.issubset(kept_tool_call_ids):
                    del msg["tool_calls"]
                    # Ensure the message remains valid (has content or tool_calls)
                    if not msg.get("content"):
                        msg["content"] = "[Earlier tool calls omitted]"

            messages.append(msg)

        # Refresh the system prompt with current runtime context
        if messages and messages[0].get("role") == "system":
            user_goal = ""
            for m in messages:
                if m.get("role") == "user":
                    user_goal = m.get("content", "")
                    break
            new_prompt = self.agent._build_system_prompt(user_goal=user_goal)
            messages[0]["content"] = new_prompt

        return messages

    def _agent_run_wrapper(self, messages: list[dict]):
        """Runs in a background thread."""
        try:
            self._broadcast_event({"type": "system", "payload": "Agent started"})
            callbacks = self._make_callbacks()

            def pause_check():
                self._pause_event.wait()

            result = self.agent.run(
                "",
                callbacks=callbacks,
                pause_check=pause_check,
                initial_messages=messages,
            )
            self._broadcast_event({"type": "done", "payload": result}, sync=True)
        except Exception as exc:
            import traceback
            err = f"{exc}\n{traceback.format_exc()}"
            print(f"[AGENT ERROR] {err}")
            self._broadcast_event({"type": "error", "payload": err}, sync=True)
        finally:
            self._done = True

    async def _do_start(self, messages: list[dict]) -> None:
        """Core start logic shared by start() and restore_and_resume()."""
        if self._run_future is not None and not self._run_future.done():
            raise RuntimeError("Agent is already running")
        self._done = False
        self._main_loop = asyncio.get_running_loop()
        # Use a fresh Event so that stale SSE connections from a previous run
        # don't race with the new one.
        self._queue_ready = asyncio.Event()
        self._queue_ready.set()
        self._assistant_buffers.clear()
        loop = self._main_loop
        self._run_future = loop.run_in_executor(
            self._executor, self._agent_run_wrapper, messages
        )

    async def start(self, query: str):
        """Start the agent in a background thread.

        Rebuilds message history from the database so that every new task
        within a session retains full conversation context.

        The caller (e.g. api/agent.py) is responsible for holding
        _start_lock around both the status check and this call so that
        the whole check-and-start sequence is atomic.
        """
        messages = self._rebuild_messages(max_tools=15)
        if not messages or messages[0].get("role") != "system":
            system_prompt = self.agent._build_system_prompt(user_goal=query)
            messages.insert(0, {"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": query})
        self._persist_message(role="user", content=query)
        await self._do_start(messages)

    async def restore_and_resume(self, query: str = ""):
        """Restore a session after server restart and resume the agent loop."""
        async with self._start_lock:
            messages = self._rebuild_messages(max_tools=15)
            if not messages or messages[0].get("role") != "system":
                system_prompt = self.agent._build_system_prompt(user_goal=query)
                messages.insert(0, {"role": "system", "content": system_prompt})
            if query:
                messages.append({"role": "user", "content": query})
                self._persist_message(role="user", content=query)
            await self._do_start(messages)

    async def submit_hook(self, content: str):
        self.agent.submit_hook(content)
        # Hooks become user messages in the agent loop — persist them too.
        self._persist_message(role="user", content=content)
        self._broadcast_event({"type": "hook_received", "payload": content})

    async def iter_sse(self):
        """Async generator yielding SSE formatted lines.

        Each caller gets an independent event queue so that multiple clients
        can observe the same session without competing for events.
        """
        await self._queue_ready.wait()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        with self._sse_queues_lock:
            self._sse_queues.add(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.5)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("type") in ("done", "error"):
                        break
                except asyncio.TimeoutError:
                    if self._done and queue.empty():
                        break
                    yield ":heartbeat\n\n"
        finally:
            with self._sse_queues_lock:
                self._sse_queues.discard(queue)
