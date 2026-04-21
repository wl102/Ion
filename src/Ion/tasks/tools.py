import asyncio
import json
import os
from typing import Optional

from openai import OpenAI

from Ion.executor.executor import TaskGraphExecutor
from Ion.tasks.manager import Task, TaskManager, TaskStatus
from Ion.tools.registry import tool


def _create_client() -> tuple[OpenAI | None, str]:
    """Create an OpenAI client from environment variables."""
    model_id = os.getenv("MODEL_ID", "")
    base_url = os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("OPENAI_API_KEY")

    if not all([model_id, base_url, api_key]):
        return None, ""

    return OpenAI(base_url=base_url, api_key=api_key), model_id


def register_task_tools(task_manager: TaskManager):
    """Register task-graph related tools bound to a TaskManager instance."""
    # Ensure sub-agent tools are loaded into tool_map
    import Ion.executor.subagent  # noqa: F401

    @tool("create_task")
    def create_task(
        name: str,
        description: str,
        depend_on: Optional[list] = None,
        on_failure: str = "replan",
    ) -> dict:
        """Create a new task in the attack graph.
        name: Task name.
        description: What this task does.
        depend_on: List of task IDs this task depends on.
        on_failure: Failure strategy — 'retry', 'replan', or 'skip'.
        """
        if depend_on is None:
            depend_on = []
        elif isinstance(depend_on, str):
            depend_on = [depend_on]
        elif not isinstance(depend_on, list):
            return {
                "success": False,
                "output": f"Invalid depend_on type: {type(depend_on).__name__}",
            }
        task = Task(
            name=name,
            description=description,
            depend_on=depend_on,
            on_failure=on_failure,
        )
        task_manager.add_task(task)
        return {"success": True, "output": f"Task created: {task.id} - {task.name}"}

    @tool("update_task")
    def update_task(task_id: str, status: str, result: Optional[str] = None) -> dict:
        """Update a task's status and optionally its result."""
        try:
            st = TaskStatus(status.lower())
        except ValueError:
            return {"success": False, "output": f"Invalid status: {status}"}
        updated = task_manager.update_status(task_id, st, result)
        if updated is None:
            return {"success": False, "output": f"Task {task_id} not found"}
        return {"success": True, "output": f"Task {task_id} updated to {status}"}

    @tool("delete_task")
    def delete_task(task_id: str) -> dict:
        """Delete a task from the attack graph."""
        ok = task_manager.delete_task(task_id)
        return {
            "success": ok,
            "output": f"Task {task_id} deleted" if ok else f"Task {task_id} not found",
        }

    @tool("get_ready_tasks")
    def get_ready_tasks() -> dict:
        """List ready tasks in the attack graph."""
        tasks = task_manager.get_ready_tasks()
        if not tasks:
            return {"success": True, "output": "No tasks ready yet."}
        lines = []
        for t in tasks:
            deps = ", ".join(t.depend_on) if t.depend_on else "none"
            lines.append(
                f"{t.id}: [{t.status.value}] {t.name} {t.description} (deps: {deps})"
            )
        return {"success": True, "output": "\n".join(lines)}

    @tool("list_tasks")
    def list_tasks() -> dict:
        """List all tasks in the attack graph."""
        tasks = task_manager.list_tasks()
        if not tasks:
            return {"success": True, "output": "No tasks yet."}
        lines = []
        for t in tasks:
            deps = ", ".join(t.depend_on) if t.depend_on else "none"
            lines.append(f"{t.id}: [{t.status.value}] {t.name} (deps: {deps})")
        return {"success": True, "output": "\n".join(lines)}

    @tool("get_attack_graph")
    def get_attack_graph() -> dict:
        """Get the current attack graph as nodes and edges."""
        graph = task_manager.get_attack_graph()
        return {
            "success": True,
            "output": json.dumps(graph, indent=2, ensure_ascii=False),
        }

    @tool("execute_ready_tasks")
    def execute_ready_tasks(max_concurrency: int = 3, summarize: bool = True) -> dict:
        """Execute all ready tasks concurrently via sub-agents."""
        client, model_id = _create_client()
        if client is None:
            return {
                "success": False,
                "output": "Error: Missing API configuration for subagent execution",
            }

        executor = TaskGraphExecutor(
            client=client,
            model_id=model_id,
            max_concurrency=max_concurrency,
            summarize=summarize,
        )

        try:
            report = asyncio.run(executor.execute_layer(task_manager))
            return {
                "success": True,
                "output": report.to_dict()["layer_summary"],
                "report": report.to_dict(),
            }
        except Exception as e:
            return {"success": False, "output": f"Execution error: {e}"}

    @tool("replan_task")
    def replan_task(
        failed_task_id: str, reason: str, alternative_approaches: list
    ) -> dict:
        """Replace a failed task with alternative approaches."""
        failed = task_manager.get_task(failed_task_id)
        if failed is None:
            return {
                "success": False,
                "output": f"Task {failed_task_id} not found",
            }

        task_manager.update_status(failed_task_id, TaskStatus.FAILED, result=reason)

        created = []
        for approach in alternative_approaches:
            alt = Task(
                name=f"{failed.name} (alt)",
                description=f"[Alternative to {failed_task_id}] {approach}\n\nReason original failed: {reason}",
                depend_on=list(failed.depend_on),
                on_failure="replan",
            )
            task_manager.add_task(alt)
            created.append(alt.id)

        return {
            "success": True,
            "output": (
                f"Replanned task {failed_task_id}. "
                f"Created {len(created)} alternative task(s): {', '.join(created)}"
            ),
            "alternative_task_ids": created,
        }
