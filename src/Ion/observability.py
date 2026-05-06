import contextvars
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional


# Context variable to track the active logger across sync/async boundaries.
_observability_logger_ctx: contextvars.ContextVar[Optional["ObservabilityLogger"]] = contextvars.ContextVar(
    "observability_logger", default=None
)


def get_current_logger() -> Optional["ObservabilityLogger"]:
    """Return the ObservabilityLogger active in the current execution context."""
    return _observability_logger_ctx.get()


class ObservabilityLogger:
    def __init__(
        self,
        log_dir: Optional[str | Path] = None,
        run_id: Optional[str] = None,
        parent_run_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        persist_fn: Optional[Callable[[str, dict], None]] = None,
    ):
        self.persist_fn = persist_fn
        self.date_str = datetime.now().strftime("%Y-%m-%d")
        self.usage_stats = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self.run_id = run_id or str(uuid.uuid4())[:8]
        self.parent_run_id = parent_run_id
        self.agent_name = agent_name or "root"

        if persist_fn is None:
            if log_dir is None:
                log_dir = os.getenv("ION_LOG_DIR")
            if log_dir is None:
                log_dir = Path.home() / ".ion" / "logs"
            self.log_dir = Path(log_dir)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self._tool_log_file = self.log_dir / f"tools_{self.date_str}.jsonl"
            self._conversation_file = self.log_dir / f"conversation_{self.date_str}.jsonl"
            self._subagent_file = self.log_dir / f"subagents_{self.date_str}.jsonl"
        else:
            self.log_dir = Path.home() / ".ion" / "logs"

    def _base_entry(self) -> dict:
        return {
            "timestamp": datetime.now().isoformat(),
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "agent_name": self.agent_name,
        }

    def _write(self, category: str, entry: dict):
        if self.persist_fn:
            self.persist_fn(category, entry)
            return
        file_map = {
            "tool": self._tool_log_file,
            "conversation": self._conversation_file,
            "subagent": self._subagent_file,
        }
        fpath = file_map.get(category, self._tool_log_file)
        with open(fpath, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_tool_call(
        self, tool_name: str, arguments: dict, output: Any, duration_ms: float
    ):
        entry = self._base_entry()
        entry.update({
            "tool_name": tool_name,
            "arguments": arguments,
            "output": str(output)[:2000],
            "duration_ms": round(duration_ms, 2),
        })
        self._write("tool", entry)

    def log_conversation(self, messages: list[dict]):
        entry = self._base_entry()
        entry.update({
            "event": "conversation",
            "messages": messages,
        })
        self._write("conversation", entry)

    def record_token_usage(self, usage: dict):
        self.usage_stats["prompt_tokens"] += usage.get("prompt_tokens", 0)
        self.usage_stats["completion_tokens"] += usage.get("completion_tokens", 0)
        self.usage_stats["total_tokens"] += usage.get("total_tokens", 0)

    def log_compression(self, summary: str, original_turns: int):
        entry = self._base_entry()
        entry.update({
            "event": "context_compression",
            "original_turns": original_turns,
            "summary": summary[:2000],
        })
        self._write("tool", entry)

    def log_subagent_spawn(
        self,
        agent_name: str,
        task_goal: str,
        context: str,
        budget: Optional[dict] = None,
        task_type: Optional[str] = None,
    ):
        entry = self._base_entry()
        entry.update({
            "event": "subagent_spawn",
            "agent_name": agent_name,
            "task_type": task_type,
            "task_goal": task_goal[:1000],
            "context": context[:1000],
            "budget": budget,
        })
        self._write("subagent", entry)

    def log_subagent_finish(
        self,
        agent_name: str,
        result: str,
        turns_used: int,
        finish_reason: Optional[str],
        tool_calls: int = 0,
        duplicate_calls: int = 0,
        no_progress_turns: int = 0,
        status: Optional[str] = None,
        confidence: Optional[str] = None,
    ):
        entry = self._base_entry()
        entry.update({
            "event": "subagent_finish",
            "agent_name": agent_name,
            "result": result[:2000],
            "turns_used": turns_used,
            "finish_reason": finish_reason,
            "tool_calls": tool_calls,
            "duplicate_calls": duplicate_calls,
            "no_progress_turns": no_progress_turns,
            "status": status,
            "confidence": confidence,
        })
        self._write("subagent", entry)

    def log_redelegation(
        self,
        agent_name: str,
        prior_status: str,
        new_goal: str,
        has_new_delta: bool,
    ):
        entry = self._base_entry()
        entry.update({
            "event": "redelegation",
            "agent_name": agent_name,
            "prior_status": prior_status,
            "new_goal": new_goal[:500],
            "has_new_delta": has_new_delta,
        })
        self._write("subagent", entry)

    def child_logger(self, agent_name: str, run_id: Optional[str] = None) -> "ObservabilityLogger":
        """Create a child logger for a sub-agent.

        The child logger shares the same log directory so that tool calls
        from both parent and child agents are co-located, while using a
        distinct run_id / parent_run_id pair for traceability.
        """
        return ObservabilityLogger(
            log_dir=self.log_dir,
            run_id=run_id or str(uuid.uuid4())[:8],
            parent_run_id=self.run_id,
            agent_name=agent_name,
        )

    def get_usage_summary(self) -> dict:
        return dict(self.usage_stats)

    def save(self, path: Optional[str | Path] = None):
        if self.persist_fn:
            self.persist_fn(
                "usage",
                {
                    **self._base_entry(),
                    "stats": dict(self.usage_stats),
                },
            )
            return
        if path is None:
            path = self.log_dir / f"usage_{self.date_str}.json"
        Path(path).write_text(
            json.dumps(self.usage_stats, indent=2, ensure_ascii=False)
        )
