import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from openai import OpenAI

from Ion.ion import LoopState, run_agent_loop
from Ion.tools.tools import get_tools_schema, tool


def _create_client() -> tuple[OpenAI | None, str]:
    """Create an OpenAI client from environment variables."""
    model_id = os.getenv("MODEL_ID", "")
    base_url = os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("OPENAI_API_KEY")

    if not all([model_id, base_url, api_key]):
        return None, ""

    return OpenAI(base_url=base_url, api_key=api_key), model_id


def _summarize_subagent_output(client: OpenAI, model_id: str, content: str) -> str:
    """Summarize lengthy sub-agent output via a quick LLM call."""
    if len(content) <= 2000:
        return content
    try:
        resp = client.chat.completions.create(
            model=model_id,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Summarize the following sub-agent execution output into a "
                        "structured report with these sections:\n"
                        "1. Key Findings (bullet points)\n"
                        "2. Conclusion (1-2 sentences)\n"
                        "3. State (completed / blocked / failed)\n"
                        "4. Recommended Next Steps\n"
                        "Be concise."
                    ),
                },
                {"role": "user", "content": content[:15000]},
            ],
            max_tokens=800,
            stream=False,
        )
        return resp.choices[0].message.content or content[:500]
    except Exception:
        return content[:1500] + "\n...[truncated]"


def _run_subagent_sync(task_description: str, tools: Optional[list] = None) -> dict:
    """Synchronous core of sub-agent execution."""
    client, model_id = _create_client()
    if client is None:
        return {
            "success": False,
            "output": "Error: Missing API configuration for subagent",
        }

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
        content = (
            state.messages[-1].get("content", "") if state.messages else "(no output)"
        )
        summary = _summarize_subagent_output(client, model_id, content)
        return {"success": True, "output": summary, "full_output": content}
    except Exception as e:
        return {"success": False, "output": f"Subagent error: {e}"}


@tool("run_subagent")
def run_subagent(task_description: str, tools: Optional[list] = None) -> dict:
    """Spawn a sub-agent to handle a specific sub-task.
    task_description: What the sub-agent should do.
    tools: Optional list of tool names to restrict the sub-agent to.
    """
    return _run_subagent_sync(task_description, tools)


@tool("run_subagents")
def run_subagents(tasks: list) -> dict:
    """Spawn multiple sub-agents concurrently.
    tasks: List of dicts, each with keys:
      - task_id (str): Identifier for this task
      - description (str): What the sub-agent should do
      - tools (list[str], optional): Tool names to restrict the sub-agent to
    Returns a structured summary of all sub-agent results.
    """
    if not tasks:
        return {"success": True, "output": "No tasks provided.", "results": []}

    async def _batch() -> list[dict]:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=min(len(tasks), 5)) as pool:
            futures = [
                loop.run_in_executor(
                    pool, _run_subagent_sync, t["description"], t.get("tools")
                )
                for t in tasks
            ]
            raw_results = await asyncio.gather(*futures, return_exceptions=True)

        results = []
        for task_def, raw in zip(tasks, raw_results):
            if isinstance(raw, BaseException):
                results.append(
                    {
                        "task_id": task_def.get("task_id", "unknown"),
                        "success": False,
                        "output": f"Execution exception: {raw}",
                    }
                )
            else:
                results.append(
                    {
                        "task_id": task_def.get("task_id", "unknown"),
                        "success": raw.get("success", False),
                        "output": raw.get("output", ""),
                        "full_output": raw.get("full_output", ""),
                    }
                )
        return results

    try:
        results = asyncio.run(_batch())
        successes = sum(1 for r in results if r["success"])
        summary = (
            f"Batch complete: {successes}/{len(results)} succeeded.\n"
            + "\n".join(
                f"  [{'OK' if r['success'] else 'FAIL'}] {r['task_id']}: {r['output'][:200]}"
                for r in results
            )
        )
        return {"success": True, "output": summary, "results": results}
    except Exception as e:
        return {"success": False, "output": f"Batch execution error: {e}"}
