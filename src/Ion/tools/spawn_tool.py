"""
工具：派生新的子Agent，包括子agent的类型，context，工具（剔除派生子agent，不允许再次委托）
"""

from .registry import registry
from typing import Optional


class BaseAgent:
    name: str
    description: str
    tools: list[str]

    async def run(self, task_goal: str, context: str):
        pass


async def _async_run_subagent(
    task_goal: str, context: str, tools: Optional[list] = None
):
    """Synchronous core of sub-agent execution.

    Returns a dict (not a JSON string) so that run_subagents can consume it
    directly before dispatch serialises it.
    """
    pass


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
                "task_goal": {
                    "type": "string",
                    "description": "What the sub-agent should do",
                },
                "context": {
                    "type": "string",
                    "description": "the sub-agent own context window from parent.",
                },
                "tools": {
                    "type": "array",
                    "description": "Optional list of tool names to restrict the sub-agent to",
                },
            },
            "required": ["task_goal", "context"],
        },
    },
}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="run_subagent",
    toolset="subagent",
    schema=RUN_SUBAGENT_SCHEMA,
    handler=lambda task_goal, context, tools=None, **kw: _async_run_subagent(
        task_goal, context, tools
    ),
    description="Spawn a sub-agent to handle a specific sub-task.",
    emoji="🤖",
)
