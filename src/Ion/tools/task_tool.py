"""
任务持久化：包括创建、更新、删除、总览工具，智能体随时查看当前进度
"""

import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .registry import registry, tool_error, tool_result


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
    KILLED = "killed"
    COMPLETED = "completed"


class Task(BaseModel):
    id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    name: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    depend_on: list[str] = Field(default_factory=list)
    result: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    on_failure: str = Field(default="replan", pattern="^(retry|skip)$")
    attempt_count: int = 0
    max_attempts: int = 1

    def model_post_init(self, __context):
        self.updated_at = datetime.now().isoformat()

    def is_retryable(self) -> bool:
        return (
            self.status == TaskStatus.FAILED
            and self.on_failure == "retry"
            and self.attempt_count < self.max_attempts
        )


class TaskManager:
    def __init__(self):
        self._tasks: dict[str, Task] = {}

    def add_task(self, task: Task) -> Task:
        self._tasks[task.id] = task
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[Task]:
        return list(self._tasks.values())

    def get_ready_tasks(self) -> list[Task]:
        ready = []
        for task in self._tasks.values():
            if task.status == TaskStatus.COMPLETED:
                continue
            if task.status == TaskStatus.RUNNING:
                continue
            if task.status == TaskStatus.KILLED:
                continue
            if task.status == TaskStatus.FAILED and not task.is_retryable():
                continue
            deps_satisfied = all(
                self._tasks.get(dep_id) is not None
                and self._tasks[dep_id].status == TaskStatus.COMPLETED
                for dep_id in task.depend_on
            )
            if deps_satisfied:
                ready.append(task)
        return ready

    def get_failed_tasks(self) -> list[Task]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.FAILED]

    def update_status(
        self, task_id: str, status: TaskStatus, result: Optional[str] = None
    ) -> Optional[Task]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task.status = status
        task.updated_at = datetime.now().isoformat()
        if result is not None:
            task.result = result
        if status == TaskStatus.RUNNING:
            task.attempt_count += 1
        return task

    def delete_task(self, task_id: str) -> bool:
        if task_id in self._tasks:
            del self._tasks[task_id]
            return True
        return False

    def kill_task(self, task_id: str) -> Optional[Task]:
        return self.update_status(task_id, TaskStatus.KILLED)

    def get_attack_graph(self) -> dict:
        nodes = []
        edges = []
        for task in self._tasks.values():
            nodes.append(
                {
                    "id": task.id,
                    "name": task.name,
                    "status": task.status.value,
                    "description": task.description,
                }
            )
            for dep_id in task.depend_on:
                edges.append({"from": dep_id, "to": task.id})
        return {"nodes": nodes, "edges": edges}

    def save_to_file(self, path: str | Path):
        data = [task.model_dump() for task in self._tasks.values()]
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def load_from_file(self, path: str | Path):
        data = json.loads(Path(path).read_text())
        self._tasks = {}
        for item in data:
            task = Task(**item)
            self._tasks[task.id] = task


task_manager = TaskManager()


# ---------------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------------


def _create_task(task_manager, name, description, depend_on, on_failure):
    if depend_on is None:
        depend_on = []
    elif isinstance(depend_on, str):
        depend_on = [depend_on]
    elif not isinstance(depend_on, list):
        return tool_error(f"Invalid depend_on type: {type(depend_on).__name__}")
    task = Task(
        name=name,
        description=description,
        depend_on=depend_on,
        on_failure=on_failure,
    )
    task_manager.add_task(task)
    return tool_result(success=True, output=f"Task created: {task.id} - {task.name}")


def _update_task(task_manager, task_id, status, result):
    try:
        st = TaskStatus(status.lower())
    except ValueError:
        return tool_error(f"Invalid status: {status}")
    updated = task_manager.update_status(task_id, st, result)
    if updated is None:
        return tool_error(f"Task {task_id} not found")
    return tool_result(success=True, output=f"Task {task_id} updated to {status}")


def _delete_task(task_manager, task_id):
    ok = task_manager.delete_task(task_id)
    return tool_result(
        success=ok,
        output=f"Task {task_id} deleted" if ok else f"Task {task_id} not found",
    )


def _list_tasks(task_manager):
    tasks = task_manager.list_tasks()
    if not tasks:
        return tool_result(success=True, output="No tasks yet.")
    lines = []
    for t in tasks:
        deps = ", ".join(t.depend_on) if t.depend_on else "none"
        lines.append(f"{t.id}: [{t.status.value}] {t.name} (deps: {deps})")
    return tool_result(success=True, output="\n".join(lines))


def _get_attack_graph(task_manager):
    graph = task_manager.get_attack_graph()
    return tool_result(
        success=True, output=json.dumps(graph, indent=2, ensure_ascii=False)
    )


# ---------------------------------------------------------------------------
# Inline schemas
# ---------------------------------------------------------------------------

CREATE_TASK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_task",
        "description": "Create a new task in the attack graph.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Task name"},
                "description": {"type": "string", "description": "What this task does"},
                "depend_on": {
                    "type": "array",
                    "description": "List of task IDs this task depends on",
                },
            },
            "required": ["name", "description"],
        },
    },
}

UPDATE_TASK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "update_task",
        "description": "Update a task's status and optionally its result.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID"},
                "status": {
                    "type": "string",
                    "description": "New status (pending, running, failed, killed, completed)",
                },
                "result": {"type": "string", "description": "Optional result text"},
            },
            "required": ["task_id", "status"],
        },
    },
}

DELETE_TASK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "delete_task",
        "description": "Delete a task from the attack graph.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID to delete"}
            },
            "required": ["task_id"],
        },
    },
}


LIST_TASKS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_tasks",
        "description": "List all tasks in the attack graph.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

GET_ATTACK_GRAPH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_attack_graph",
        "description": "Get the current attack graph as nodes and edges.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="create_task",
    toolset="task",
    schema=CREATE_TASK_SCHEMA,
    handler=lambda name, description, depend_on=None, on_failure="replan", **kw: (
        _create_task(task_manager, name, description, depend_on, on_failure)
    ),
    description="Create a new task in the attack graph.",
    emoji="📋",
)

registry.register(
    name="update_task",
    toolset="task",
    schema=UPDATE_TASK_SCHEMA,
    handler=lambda task_id, status, result=None, **kw: _update_task(
        task_manager, task_id, status, result
    ),
    description="Update a task's status and optionally its result.",
    emoji="📝",
)

registry.register(
    name="delete_task",
    toolset="task",
    schema=DELETE_TASK_SCHEMA,
    handler=lambda task_id, **kw: _delete_task(task_manager, task_id),
    description="Delete a task from the attack graph.",
    emoji="🗑️",
)

registry.register(
    name="list_tasks",
    toolset="task",
    schema=LIST_TASKS_SCHEMA,
    handler=lambda **kw: _list_tasks(task_manager),
    description="List all tasks in the attack graph.",
    emoji="📜",
)

registry.register(
    name="get_attack_graph",
    toolset="task",
    schema=GET_ATTACK_GRAPH_SCHEMA,
    handler=lambda **kw: _get_attack_graph(task_manager),
    description="Get the current attack graph as nodes and edges.",
    emoji="🕸️",
)
