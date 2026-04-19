import os

from openai import OpenAI

from Ion.ion import LoopState, run_agent_loop
from Ion.tools.tools import get_tools_schema, tool


@tool("run_subagent")
def run_subagent(task_description: str, tools: list = None) -> dict:
    """Spawn a sub-agent to handle a specific sub-task.
    task_description: What the sub-agent should do.
    tools: Optional list of tool names to restrict the sub-agent to.
    """
    model_id = os.getenv("MODEL_ID")
    base_url = os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("OPENAI_API_KEY")

    if not all([model_id, base_url, api_key]):
        return {"success": False, "output": "Error: Missing API configuration for subagent"}

    client = OpenAI(base_url=base_url, api_key=api_key)
    all_schemas = get_tools_schema()

    if tools:
        allowed = set(tools)
        filtered = [s for s in all_schemas if s["function"]["name"] in allowed]
    else:
        filtered = all_schemas

    messages = [
        {"role": "system", "content": "You are a sub-agent focused on a single task."},
        {"role": "user", "content": task_description},
    ]
    state = LoopState(messages=messages)

    try:
        run_agent_loop(client, model_id, state, filtered)
        content = state.messages[-1].get("content", "") if state.messages else "(no output)"
        return {"success": True, "output": content}
    except Exception as e:
        return {"success": False, "output": f"Subagent error: {e}"}
