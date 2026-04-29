"""Data models for the controlled subagent delegation system.

Defines the structured request/result protocol and budget/stop-condition
checks used by the spawn_tool and subagent loop.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class SubagentStatus(str, Enum):
    """Terminal status reported by a subagent."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"
    WRONG_AGENT = "wrong_agent"
    NEEDS_PARENT = "needs_parent"
    BUDGET_EXHAUSTED = "budget_exhausted"


class WhyStopped(str, Enum):
    """Reason the subagent stopped execution."""

    SUCCESS = "success"
    BLOCKED = "blocked"
    NO_PROGRESS = "no_progress"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TOOL_LIMIT = "tool_limit"
    WRONG_CAPABILITY = "wrong_capability"
    MAX_TURNS = "max_turns"
    SAME_ERROR_LIMIT = "same_error_limit"
    LOW_SUCCESS_RATE = "low_success_rate"
    STOP_CONDITION = "stop_condition"


class RecommendedOwner(str, Enum):
    """Who should own the next step."""

    PARENT = "parent"
    SAME_AGENT = "same_agent"
    OTHER_AGENT = "other_agent"


class Confidence(str, Enum):
    """Confidence level for findings."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Budget(BaseModel):
    """Execution budget for a subagent."""

    max_turns: int = Field(default=20, description="Maximum LLM turns")
    max_tool_calls: int = Field(
        default=15, description="Maximum total tool calls"
    )
    max_same_tool_retries: int = Field(
        default=2, description="Max repeats of same tool with similar args"
    )
    max_no_progress_turns: int = Field(
        default=3, description="Max consecutive turns without new information"
    )
    max_same_error_count: int = Field(
        default=2, description="Max consecutive identical errors before stopping"
    )
    min_success_rate: float = Field(
        default=0.15, description="Stop if success rate falls below this threshold after min_sample_size attempts"
    )
    min_sample_size: int = Field(
        default=5, description="Minimum attempts before checking success rate"
    )


class StopConditions(BaseModel):
    """Explicit stop conditions for a subagent."""

    success_criteria: list[str] = Field(
        default_factory=list,
        description="List of criteria that, if met, mean the task is complete",
    )
    max_same_error_count: int = Field(
        default=2,
        description="Stop if the same error occurs this many times in a row",
    )
    blocked_keywords: list[str] = Field(
        default_factory=list,
        description="Keywords in output that indicate blocking",
    )


class EvidenceItem(BaseModel):
    """A single piece of evidence."""

    type: str = Field(
        default="observation",
        description="tool_output|http_response|file|observation",
    )
    value: str = ""
    source: str = ""


class AttemptedAction(BaseModel):
    """Record of an action attempted by the subagent."""

    action: str = ""
    result: str = Field(
        default="no_signal", description="success|failed|no_signal"
    )
    why: str = ""


class Artifact(BaseModel):
    """Artifact produced by the subagent."""

    path: str = ""
    description: str = ""


class SubagentResult(BaseModel):
    """Structured result that a subagent must produce."""

    status: SubagentStatus = SubagentStatus.FAILED
    summary: str = ""
    confidence: Confidence = Confidence.LOW
    success_criteria_met: bool = False
    key_findings: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    attempted_actions: list[AttemptedAction] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    why_stopped: WhyStopped = WhyStopped.BUDGET_EXHAUSTED
    recommended_next_action: str = ""
    recommended_owner: RecommendedOwner = RecommendedOwner.PARENT
    next_agent: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, ensure_ascii=False)

    @classmethod
    def from_raw_output(cls, raw: str) -> "SubagentResult":
        """Best-effort parse of subagent free-text output into structured result.

        Tries to find a JSON block first, then falls back to heuristics.
        """
        # 1. Try explicit JSON block
        if "```json" in raw:
            json_part = raw.split("```json")[-1].split("```")[0].strip()
            try:
                data = json.loads(json_part)
                return cls.model_validate(data)
            except Exception:
                pass

        # 2. Try bare JSON object
        raw_stripped = raw.strip()
        if raw_stripped.startswith("{") and raw_stripped.endswith("}"):
            try:
                data = json.loads(raw_stripped)
                return cls.model_validate(data)
            except Exception:
                pass

        # 3. Fallback: treat the whole thing as a plain-text summary
        return cls(
            status=SubagentStatus.PARTIAL,
            summary=raw[:2000],
            confidence=Confidence.LOW,
            why_stopped=WhyStopped.NO_PROGRESS,
            recommended_owner=RecommendedOwner.PARENT,
        )


class SubagentRequest(BaseModel):
    """Full delegation request sent to spawn_subagent."""

    agent_name: str
    goal: str
    task_type: str = ""
    context: str = ""
    success_criteria: list[str] = Field(default_factory=list)
    budget: Budget = Field(default_factory=Budget)
    stop_conditions: StopConditions = Field(default_factory=StopConditions)
    tools: Optional[list[str]] = None
    parent_expectation: str = Field(
        default="",
        description="What the parent expects to receive",
    )
    on_failure: str = Field(
        default="replan",
        description="retry|replan|parent_takeover|cancel",
    )


class DelegationCheck(BaseModel):
    """Result of pre-delegation validation."""

    allowed: bool = False
    reason: str = ""
    similarity_score: float = 0.0


class ToolCallSignature(BaseModel):
    """Fingerprint of a tool call for duplicate detection."""

    name: str = ""
    arguments_hash: str = ""

    @classmethod
    def from_call(cls, name: str, arguments: dict) -> "ToolCallSignature":
        # Simple deterministic hash: sorted JSON of arguments
        args_json = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
        return cls(name=name, arguments_hash=args_json)


class SubagentLoopTracker(BaseModel):
    """Mutable tracker used inside the subagent loop."""

    tool_call_count: int = 0
    tool_call_history: list[ToolCallSignature] = Field(default_factory=list)
    no_progress_turn_count: int = 0
    consecutive_same_error_count: int = 0
    last_error_signature: str = ""
    status_transitions: list[str] = Field(default_factory=list)
    has_new_information_last_turn: bool = False
    attempt_results: list[str] = Field(default_factory=list)

    def record_tool_call(self, name: str, arguments: dict):
        self.tool_call_count += 1
        sig = ToolCallSignature.from_call(name, arguments)
        self.tool_call_history.append(sig)

    def count_duplicate_calls(self, name: str, arguments: dict, window: int = 10) -> int:
        sig = ToolCallSignature.from_call(name, arguments)
        recent = self.tool_call_history[-window:]
        return sum(1 for s in recent if s.name == sig.name and s.arguments_hash == sig.arguments_hash)

    def record_error(self, error_text: str):
        sig = error_text[:200]
        if sig == self.last_error_signature:
            self.consecutive_same_error_count += 1
        else:
            self.consecutive_same_error_count = 1
            self.last_error_signature = sig

    def mark_progress(self, has_progress: bool):
        if has_progress:
            self.no_progress_turn_count = 0
            self.has_new_information_last_turn = True
        else:
            self.no_progress_turn_count += 1
            self.has_new_information_last_turn = False

    def record_attempt_result(self, result: str):
        """Record an attempt result: 'success', 'failed', or 'no_signal'."""
        self.attempt_results.append(result)

    def get_success_rate(self, window: int = 10) -> float:
        """Calculate success rate over the last N attempts."""
        recent = self.attempt_results[-window:] if self.attempt_results else []
        if not recent:
            return 0.0
        successes = sum(1 for r in recent if r == "success")
        return successes / len(recent)

    def is_low_success_rate(self, budget: Budget) -> bool:
        """Check if success rate is below threshold after minimum sample size."""
        if budget.min_success_rate <= 0:
            return False
        if len(self.attempt_results) < budget.min_sample_size:
            return False
        return self.get_success_rate(window=budget.min_sample_size) < budget.min_success_rate

    def check_blocked_keywords(self, content: str, blocked_keywords: list[str]) -> Optional[str]:
        """Check if content contains any blocked keywords."""
        if not blocked_keywords or not content:
            return None
        content_lower = content.lower()
        for keyword in blocked_keywords:
            if keyword.lower() in content_lower:
                return f"blocked_keyword:{keyword}"
        return None

    def check_budget(self, budget: Budget, latest_content: str = "", stop_conditions: Optional[Any] = None) -> Optional[str]:
        """Return stop reason if budget exceeded or stop conditions met, else None."""
        if budget.max_tool_calls > 0 and self.tool_call_count >= budget.max_tool_calls:
            return "tool_limit"
        if budget.max_same_tool_retries > 0:
            # Check last call for duplicates
            if self.tool_call_history:
                last = self.tool_call_history[-1]
                dup_count = self.count_duplicate_calls(last.name, json.loads(last.arguments_hash))
                if dup_count > budget.max_same_tool_retries:
                    return "duplicate_tool_call"
        if budget.max_no_progress_turns > 0 and self.no_progress_turn_count >= budget.max_no_progress_turns:
            return "no_progress"
        if budget.max_same_error_count > 0 and self.consecutive_same_error_count >= budget.max_same_error_count:
            return "same_error_limit"
        if self.is_low_success_rate(budget):
            rate = self.get_success_rate(window=budget.min_sample_size)
            return f"low_success_rate:{rate:.0%}"

        # Check stop_conditions if provided
        if stop_conditions is not None:
            blocked_keywords = getattr(stop_conditions, "blocked_keywords", None)
            blocked = self.check_blocked_keywords(latest_content, blocked_keywords or [])
            if blocked:
                return blocked
            max_same_error = getattr(stop_conditions, "max_same_error_count", 0)
            if max_same_error > 0 and self.consecutive_same_error_count >= max_same_error:
                return "stop_condition_same_error"

        return None
