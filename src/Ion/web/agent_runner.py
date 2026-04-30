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
from Ion.observability import ObservabilityLogger
from Ion.tools.task_tool import PersistentTaskManager


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

        def on_assistant_start(message_id: str):
            put_event({"type": "assistant_start", "message_id": message_id})

        def on_assistant_chunk(text: str, reasoning: bool = False, message_id: str = ""):
            put_event({"type": "assistant", "payload": text, "reasoning": reasoning, "message_id": message_id})

        def on_assistant_end(message_id: str):
            put_event({"type": "assistant_end", "message_id": message_id})

        def on_tool_start(names: list[str]):
            put_event({"type": "tool_start", "payload": names})

        def on_tool_result(name: str, output: str, duration_ms: float):
            # Truncate large outputs for SSE
            payload = output if len(output) < 5000 else output[:5000] + "\n...[truncated]"
            put_event(
                {
                    "type": "tool_result",
                    "payload": payload,
                    "tool_name": name,
                    "duration_ms": round(duration_ms, 2),
                }
            )

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

    def _agent_run_wrapper(self, query: str):
        """Runs in a background thread."""
        try:
            if self.sse_queue is not None and self._main_loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self.sse_queue.put({"type": "system", "payload": "Agent started"}),
                    self._main_loop,
                )
            callbacks = self._make_callbacks()
            result = self.agent.run(query, callbacks=callbacks)
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
        loop = self._main_loop
        self._run_future = loop.run_in_executor(self._executor, self._agent_run_wrapper, query)

    async def submit_hook(self, content: str):
        self.agent.submit_hook(content)
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
