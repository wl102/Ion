"""Subagent spawning tool with controlled delegation protocol.

Implements:
- Structured request/result contract (SubagentRequest / SubagentResult)
- Pre-delegation validation (agent match, criteria check, similarity guard)
- Budget-enforced subagent loop (run_subagent_loop)
- Structured JSON output parsing
"""

from __future__ import annotations

import os
from typing import Optional

from openai import OpenAI

from Ion.subagent_models import (
    Budget,
    DelegationCheck,
    StopConditions,
    SubagentRequest,
    SubagentResult,
    SubagentStatus,
)
from Ion.tools.registry import registry, tool_error, tool_result
from Ion.agents.registry import agent_registry
from Ion.observability import ObservabilityLogger, get_current_logger
from Ion.prompts import PromptBuilder

# --------------------------------------------------------------------------- #
#  Similarity guard (simple in-memory)                                        #
# --------------------------------------------------------------------------- #

_recent_delegations: list[dict] = []
_MAX_RECENT = 20


def _record_delegation(agent_name: str, goal: str, context: str):
    _recent_delegations.append(
        {"agent_name": agent_name, "goal": goal, "context": context}
    )
    if len(_recent_delegations) > _MAX_RECENT:
        _recent_delegations.pop(0)


def _check_similarity(agent_name: str, goal: str, context: str) -> DelegationCheck:
    """Simple similarity check to prevent repetitive delegation."""
    for recent in _recent_delegations:
        if recent["agent_name"] != agent_name:
            continue
        # Very naive heuristic: same goal or highly overlapping context
        if recent["goal"] == goal:
            return DelegationCheck(
                allowed=False,
                reason="Identical goal was recently delegated to the same agent. "
                "You must provide new evidence, a new hypothesis, or a new success criterion.",
                similarity_score=1.0,
            )
        if len(goal) > 20 and recent["goal"] in goal or goal in recent["goal"]:
            return DelegationCheck(
                allowed=False,
                reason="Highly similar goal was recently delegated to the same agent. "
                "Rephrase with a concrete new angle or new tool permission.",
                similarity_score=0.9,
            )
    return DelegationCheck(allowed=True, reason="", similarity_score=0.0)


# --------------------------------------------------------------------------- #
#  Pre-delegation validation                                                  #
# --------------------------------------------------------------------------- #


def _validate_delegation(req: SubagentRequest, filtered_tools: list[dict]) -> DelegationCheck:
    # 1. Agent must exist
    agent = agent_registry.get(req.agent_name)
    if agent is None:
        available = ", ".join(agent_registry.list_agents()) or "none"
        return DelegationCheck(
            allowed=False,
            reason=f"Sub-agent '{req.agent_name}' not found. Available: {available}",
        )

    # 2. success_criteria must not be empty
    if not req.success_criteria:
        return DelegationCheck(
            allowed=False,
            reason="Delegation rejected: success_criteria is empty. "
            "Define at least one concrete success criterion before delegating.",
        )

    # 3. Tools must be non-empty after filtering
    if not filtered_tools:
        return DelegationCheck(
            allowed=False,
            reason="No tools available for the sub-agent after filtering.",
        )

    # 4. Similarity guard
    sim_check = _check_similarity(req.agent_name, req.goal, req.context)
    if not sim_check.allowed:
        return sim_check

    return DelegationCheck(allowed=True, reason="")


# --------------------------------------------------------------------------- #
#  Core subagent runner                                                       #
# --------------------------------------------------------------------------- #


def _run_subagent(
    agent_name: str,
    goal: str,
    context: str = "",
    task_type: str = "",
    success_criteria: Optional[list] = None,
    budget: Optional[dict] = None,
    stop_conditions: Optional[dict] = None,
    tools: Optional[list] = None,
    parent_expectation: str = "",
    on_failure: str = "replan",
    # Legacy compat
    task_goal: Optional[str] = None,
) -> str:
    """Spawn a sub-agent with the controlled delegation protocol.

    Accepts the new structured protocol (goal, success_criteria, budget, …)
    and falls back to legacy ``task_goal`` for backward compatibility.
    """
    # Legacy compat: map task_goal -> goal
    if task_goal is not None and not goal:
        goal = task_goal

    req = SubagentRequest(
        agent_name=agent_name,
        goal=goal,
        task_type=task_type or "general",
        context=context,
        success_criteria=success_criteria or [],
        budget=Budget.model_validate(budget or {}),
        stop_conditions=StopConditions.model_validate(stop_conditions or {}),
        tools=tools,
        parent_expectation=parent_expectation,
        on_failure=on_failure,
    )

    # ------------------------------------------------------------------
    # Filter tools: remove delegation tools to prevent recursive spawning
    # ------------------------------------------------------------------
    all_tools = registry.get_tools_schema()
    forbidden = {"spawn_subagent", "list_subagents"}
    filtered_tools = []
    allowed = set(req.tools) if req.tools else None

    for t in all_tools:
        func = t.get("function", {})
        tname = func.get("name", "")
        if tname in forbidden:
            continue
        if allowed is not None and tname not in allowed:
            continue
        filtered_tools.append(t)

    # ------------------------------------------------------------------
    # Pre-delegation validation
    # ------------------------------------------------------------------
    check = _validate_delegation(req, filtered_tools)
    if not check.allowed:
        return tool_error(check.reason)

    # Build a human-readable tools description for the sub-agent
    tools_desc_lines = []
    for t in filtered_tools:
        func = t.get("function", {})
        tname = func.get("name", "unknown")
        tdesc = func.get("description", "")
        tools_desc_lines.append(f"- `{tname}`: {tdesc}")
    tools_description = "\n".join(tools_desc_lines) if tools_desc_lines else None

    agent = agent_registry.get(req.agent_name)
    agent_body = agent.activate()
    system_prompt = PromptBuilder.build_subagent_prompt(
        agent_name=agent.name,
        agent_body=agent_body,
        task_goal=req.goal,
        parent_context=req.context,
        tools_description=tools_description,
        success_criteria=req.success_criteria,
        budget=req.budget,
        stop_conditions=req.stop_conditions,
    )

    # ------------------------------------------------------------------
    # Build lightweight agent loop
    # ------------------------------------------------------------------
    model_id = os.getenv("MODEL_ID", "")
    base_url = os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("OPENAI_API_KEY")

    if not model_id:
        return tool_error("Missing MODEL_ID environment variable.")
    if not base_url:
        return tool_error("Missing OPENAI_BASE_URL environment variable.")
    if not api_key:
        return tool_error("Missing OPENAI_API_KEY environment variable.")

    client = OpenAI(base_url=base_url, api_key=api_key)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": req.goal},
    ]

    from Ion.ion import LoopState, run_subagent_loop

    state = LoopState(
        messages=messages,
        max_turns=req.budget.max_turns,
        context_max_tokens=8000,
    )

    parent_logger = get_current_logger()
    if parent_logger is not None:
        sub_logger = parent_logger.child_logger(agent_name)
    else:
        sub_logger = ObservabilityLogger(agent_name=agent_name)
    sub_logger.log_subagent_spawn(
        agent_name=agent_name,
        task_goal=req.goal,
        context=req.context,
        budget=req.budget.model_dump(),
        task_type=req.task_type,
    )

    # Record delegation for similarity guard
    _record_delegation(req.agent_name, req.goal, req.context)

    print(f"\n[SubAgent: {agent_name}] Starting task: {req.goal}\n")

    try:
        result: SubagentResult = run_subagent_loop(
            client,
            model_id,
            state,
            filtered_tools,
            budget=req.budget,
            logger=sub_logger,
            agent_name=agent_name,
            stop_conditions=req.stop_conditions,
        )
    except Exception as exc:
        sub_logger.log_subagent_finish(
            agent_name=agent_name,
            result=str(exc),
            turns_used=state.turn_count,
            finish_reason="error",
        )
        result = SubagentResult(
            status=SubagentStatus.FAILED,
            summary=f"Subagent crashed: {exc}",
        )

    # Merge loop state into result for observability
    sub_logger.log_subagent_finish(
        agent_name=agent_name,
        result=result.summary,
        turns_used=state.turn_count,
        finish_reason=result.why_stopped.value,
        status=result.status.value,
        confidence=result.confidence.value,
    )

    # Return structured result as JSON
    return tool_result(
        success=result.status
        in (SubagentStatus.COMPLETED, SubagentStatus.PARTIAL),
        output=result.model_dump(),
        status=result.status.value,
        turns_used=state.turn_count,
        finish_reason=result.why_stopped.value,
    )


# --------------------------------------------------------------------------- #
#  list_subagents                                                             #
# --------------------------------------------------------------------------- #


def _list_subagents():
    catalog = agent_registry.get_catalog()
    if not catalog:
        return tool_result(success=True, output="No sub-agents available.")
    lines = [f"{a['name']}: {a['description']}" for a in catalog]
    return tool_result(success=True, output="\n".join(lines))


# --------------------------------------------------------------------------- #
#  Schemas                                                                    #
# --------------------------------------------------------------------------- #

RUN_SUBAGENT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "spawn_subagent",
        "description": (
            "Spawn a specialized sub-agent to handle a specific sub-task. "
            "Delegation is a strategic decision, not the default. "
            "Only delegate when the task is specialized, sliceable, and has a clear deliverable."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Name of the sub-agent to spawn (e.g., 'ReconAgent', 'XSSAgent')",
                },
                "goal": {
                    "type": "string",
                    "description": "What the sub-agent should accomplish. Be specific and measurable.",
                },
                "task_type": {
                    "type": "string",
                    "description": "Category of the task (e.g., recon, exploit, verify)",
                },
                "context": {
                    "type": "string",
                    "description": "Relevant context extracted from the parent agent. Do not dump the full conversation.",
                },
                "success_criteria": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Concrete criteria that define when the task is complete. "
                        "Required. The sub-agent stops as soon as these are met."
                    ),
                },
                "budget": {
                    "type": "object",
                    "description": "Execution budget. Defaults are applied if omitted.",
                    "properties": {
                        "max_turns": {"type": "integer"},
                        "max_tool_calls": {"type": "integer"},
                        "max_same_tool_retries": {"type": "integer"},
                        "max_no_progress_turns": {"type": "integer"},
                        "max_same_error_count": {"type": "integer"},
                        "min_success_rate": {"type": "number"},
                        "min_sample_size": {"type": "integer"},
                    },
                },
                "stop_conditions": {
                    "type": "object",
                    "description": "Additional stop conditions.",
                    "properties": {
                        "success_criteria": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "max_same_error_count": {"type": "integer"},
                        "blocked_keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
                "tools": {
                    "type": "array",
                    "description": "Optional whitelist of tool names for the sub-agent",
                },
                "parent_expectation": {
                    "type": "string",
                    "description": "What the parent expects to receive back (e.g., a confirmed vulnerability, a list of open ports)",
                },
                "on_failure": {
                    "type": "string",
                    "description": "What the parent should do if the sub-agent fails: retry|replan|parent_takeover|cancel",
                },
                # Legacy compat
                "task_goal": {
                    "type": "string",
                    "description": "Legacy alias for 'goal'. Use 'goal' instead.",
                },
            },
            "required": ["agent_name", "goal", "context", "success_criteria"],
        },
    },
}

LIST_SUBAGENTS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_subagents",
        "description": "List all available sub-agents with name and description.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


# --------------------------------------------------------------------------- #
#  Registration                                                               #
# --------------------------------------------------------------------------- #

registry.register(
    name="list_subagents",
    toolset="subagent",
    schema=LIST_SUBAGENTS_SCHEMA,
    handler=lambda **kw: _list_subagents(),
    description="List all available sub-agents with name and description.",
    emoji="🤖",
)

registry.register(
    name="spawn_subagent",
    toolset="subagent",
    schema=RUN_SUBAGENT_SCHEMA,
    handler=lambda **kw: _run_subagent(**kw),
    description="Spawn a sub-agent with controlled delegation protocol.",
    emoji="🚀",
    is_async=False,
)
