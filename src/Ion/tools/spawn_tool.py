"""
工具：派生新的子Agent，包括子agent的类型，context，工具（剔除派生子agent，不允许再次委托）
"""

import os
from typing import Optional

from openai import OpenAI

from .registry import registry, tool_error, tool_result
from Ion.agents.registry import agent_registry
from Ion.observability import ObservabilityLogger
from Ion.prompts import PromptBuilder


async def _async_run_subagent(
    agent_name: str, task_goal: str, context: str, tools: Optional[list] = None
):
    """Spawn a sub-agent with the specified agent type to handle a sub-task.

    Loads the AGENT.md content for the named agent and injects it into the
    sub-agent's system prompt.  The sub-agent is not allowed to spawn further
    sub-agents.
    """
    agent = agent_registry.get(agent_name)
    if agent is None:
        available = ", ".join(agent_registry.list_agents()) or "none"
        return tool_error(f"Sub-agent '{agent_name}' not found. Available: {available}")

    # ------------------------------------------------------------------
    # Filter tools: remove delegation tools to prevent recursive spawning
    # ------------------------------------------------------------------

    all_tools = registry.get_tools_schema()
    forbidden = {"spawn_subagent", "list_subagents"}
    filtered_tools = []
    allowed = set(tools) if tools else None

    for t in all_tools:
        func = t.get("function", {})
        tname = func.get("name", "")
        if tname in forbidden:
            continue
        if allowed is not None and tname not in allowed:
            continue
        filtered_tools.append(t)

    if not filtered_tools:
        return tool_error("No tools available for the sub-agent after filtering.")

    # Build a human-readable tools description for the sub-agent
    tools_desc_lines = []
    for t in filtered_tools:
        func = t.get("function", {})
        tname = func.get("name", "unknown")
        tdesc = func.get("description", "")
        tools_desc_lines.append(f"- `{tname}`: {tdesc}")
    tools_description = "\n".join(tools_desc_lines) if tools_desc_lines else None

    agent_body = agent.activate()
    system_prompt = PromptBuilder.build_subagent_prompt(
        agent_name=agent.name,
        agent_body=agent_body,
        task_goal=task_goal,
        parent_context=context,
        tools_description=tools_description,
    )

    # ------------------------------------------------------------------
    # Build a lightweight agent loop directly (avoid re-initialising a full
    # PentestAgent which would re-register global tools / side-effects).
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
        {"role": "user", "content": task_goal},
    ]

    from Ion.ion import LoopState, run_agent_loop

    state = LoopState(
        messages=messages,
        max_turns=15,
        context_max_tokens=8000,
    )

    # Create a child logger so the sub-agent's tool calls are also recorded.
    sub_logger = ObservabilityLogger(agent_name=agent_name)
    sub_logger.log_subagent_spawn(agent_name, task_goal, context)

    run_agent_loop(client, model_id, state, filtered_tools, logger=sub_logger)

    last_msg = state.messages[-1] if state.messages else {}
    result = last_msg.get("content", "") or ""

    sub_logger.log_subagent_finish(
        agent_name=agent_name,
        result=result,
        turns_used=state.turn_count,
        finish_reason=state.finish_reason,
    )

    return tool_result(
        success=True,
        output=result,
        turns_used=state.turn_count,
        finish_reason=state.finish_reason,
    )


# ---------------------------------------------------------------------------
# list_subagents
# ---------------------------------------------------------------------------


def _list_subagents():
    catalog = agent_registry.get_catalog()
    if not catalog:
        return tool_result(success=True, output="No sub-agents available.")
    lines = [f"{a['name']}: {a['description']}" for a in catalog]
    return tool_result(success=True, output="\n".join(lines))


# ---------------------------------------------------------------------------
# Inline schemas
# ---------------------------------------------------------------------------

RUN_SUBAGENT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "spawn_subagent",
        "description": "Spawn a sub-agent to handle a specific sub-task.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Name of the sub-agent to spawn (e.g., 'ReconAgent', 'XSSAgent')",
                },
                "task_goal": {
                    "type": "string",
                    "description": "What the sub-agent should do",
                },
                "context": {
                    "type": "string",
                    "description": "Relevant context from the parent agent to ground the sub-agent's work.",
                },
                "tools": {
                    "type": "array",
                    "description": "Optional list of tool names to restrict the sub-agent to",
                },
            },
            "required": ["agent_name", "task_goal", "context"],
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


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

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
    handler=lambda agent_name, task_goal, context, tools=None, **kw: (
        _async_run_subagent(agent_name, task_goal, context, tools)
    ),
    description="Spawn a sub-agent to handle a specific sub-task.",
    emoji="🚀",
    is_async=True,
)
