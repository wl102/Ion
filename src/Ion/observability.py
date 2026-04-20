import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


class ObservabilityLogger:
    def __init__(self, log_dir: Optional[str | Path] = None):
        if log_dir is None:
            log_dir = Path.home() / ".ion" / "logs"
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.date_str = datetime.now().strftime("%Y-%m-%d")
        self._tool_log_file = self.log_dir / f"tools_{self.date_str}.jsonl"
        self._conversation_file = self.log_dir / f"conversation_{self.date_str}.jsonl"
        self.usage_stats = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def log_tool_call(
        self, tool_name: str, arguments: dict, output: Any, duration_ms: float
    ):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "tool_name": tool_name,
            "arguments": arguments,
            "output": str(output)[:2000],
            "duration_ms": round(duration_ms, 2),
        }
        with open(self._tool_log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_conversation(self, messages: list[dict]):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "messages": messages,
        }
        with open(self._conversation_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def record_token_usage(self, usage: dict):
        self.usage_stats["prompt_tokens"] += usage.get("prompt_tokens", 0)
        self.usage_stats["completion_tokens"] += usage.get("completion_tokens", 0)
        self.usage_stats["total_tokens"] += usage.get("total_tokens", 0)

    def log_compression(self, summary: str, original_turns: int):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event": "context_compression",
            "original_turns": original_turns,
            "summary": summary[:2000],
        }
        with open(self._tool_log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_usage_summary(self) -> dict:
        return dict(self.usage_stats)

    def save(self, path: Optional[str | Path] = None):
        if path is None:
            path = self.log_dir / f"usage_{self.date_str}.json"
        Path(path).write_text(
            json.dumps(self.usage_stats, indent=2, ensure_ascii=False)
        )
