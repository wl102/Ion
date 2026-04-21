import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


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
    on_failure: str = Field(default="replan", pattern="^(retry|replan|skip)$")
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
