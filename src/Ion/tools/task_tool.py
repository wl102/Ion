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

    def attack_graph_view(self) -> str:
        if not self._tasks:
            return "No tasks yet."

        task_map = {t.id: t for t in self._tasks.values()}

        children_map: dict[str, list[str]] = {}
        for tid, t in task_map.items():
            for dep in t.depend_on:
                children_map.setdefault(dep, []).append(tid)

        root_ids = [tid for tid, t in task_map.items() if not t.depend_on]

        lines = []

        def print_tree(task_id: str, prefix: str = "", is_last: bool = True):
            task = task_map.get(task_id)
            if not task:
                return
            conn = "└── " if is_last else "├── "
            lines.append(f"{prefix}{conn}[{task.status.value}] {task.name} ({task.id})")
            children = children_map.get(task_id, [])
            for i, child_id in enumerate(children):
                new_prefix = prefix + ("    " if is_last else "│   ")
                print_tree(child_id, new_prefix, i == len(children) - 1)

        for i, root_id in enumerate(root_ids):
            print_tree(root_id, is_last=i == len(root_ids) - 1)

        all_deps = set()
        for t in task_map.values():
            all_deps.update(t.depend_on)
        orphans = [
            tid for tid in task_map if tid not in all_deps and task_map[tid].depend_on
        ]

        for tid in orphans:
            task = task_map[tid]
            lines.append(f"[{task.status.value}] {task.name} ({task.id}) - (orphan)")

        return "\n".join(lines) if lines else "No tasks yet."

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


def _attack_graph_view(task_manager):
    result = task_manager.attack_graph_view()
    return tool_result(success=True, output=result)


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

ATTACK_GRAPH_VIEW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "attack_graph_view",
        "description": "View the attack graph as a tree structure.",
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
    name="attack_graph_view",
    toolset="task",
    schema=ATTACK_GRAPH_VIEW_SCHEMA,
    handler=lambda **kw: _attack_graph_view(task_manager),
    description="View the attack graph as a tree structure.",
    emoji="🌳",
)
