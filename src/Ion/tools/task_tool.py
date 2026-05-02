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
    on_failure: str = Field(default="replan", pattern="^(retry|skip|replan)$")
    attempt_count: int = 0
    max_attempts: int = 1
    # information_score: higher = task was created based on richer intelligence
    # Used for DFS prioritization in CTF mode (0-10, default 0)
    information_score: int = Field(default=0, ge=0, le=10)
    # intelligence_source: brief note on what finding triggered this task
    intelligence_source: str = ""
    # execution_notes: running log of key observations, failures, and pivot decisions
    # Populated by add_task_note during task execution for later reflection
    execution_notes: list[str] = Field(default_factory=list)
    # key_findings: high-signal outputs or discoveries from this task
    key_findings: list[str] = Field(default_factory=list)

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

    def get_ready_tasks(self) -> list[Task]:
        """Return tasks that are pending and have all dependencies completed.

        Sorted by information_score descending so high-intelligence tasks
        (source-code exploitation, credential-based attacks) run first.
        """
        completed_ids = {
            t.id for t in self._tasks.values() if t.status == TaskStatus.COMPLETED
        }
        ready = [
            t
            for t in self._tasks.values()
            if t.status == TaskStatus.PENDING
            and all(dep in completed_ids for dep in t.depend_on)
        ]
        return sorted(ready, key=lambda t: t.information_score, reverse=True)

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

    def add_task_note(
        self,
        task_id: str,
        note: str = "",
        finding: str = "",
    ) -> Optional[Task]:
        """Append an execution note or key finding to a task."""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if note:
            task.execution_notes.append(note)
        if finding:
            task.key_findings.append(finding)
        task.updated_at = datetime.now().isoformat()
        return task

    def get_task_reflection_data(self, task_id: str) -> Optional[dict]:
        """Return structured reflection material for a completed task."""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        return {
            "id": task.id,
            "name": task.name,
            "description": task.description,
            "status": task.status.value,
            "result": task.result,
            "attempts": task.attempt_count,
            "execution_notes": task.execution_notes,
            "key_findings": task.key_findings,
            "intelligence_source": task.intelligence_source,
        }

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


def _create_task(
    task_manager, name, description, depend_on, on_failure, information_score, intelligence_source
):
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
        information_score=information_score or 0,
        intelligence_source=intelligence_source or "",
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

    output = f"Task {task_id} updated to {status}"

    # Trigger self-improvement reflection when a task reaches a terminal state
    if st in (TaskStatus.COMPLETED, TaskStatus.FAILED):
        output += (
            f"\n\n🧠 SELF-IMPROVEMENT TRIGGER — Task '{updated.name}' is now {status.upper()}.\n"
            f"Before proceeding, ask yourself:\n"
            f"1. Was this a non-trivial workflow worth preserving as a skill?\n"
            f"2. Were there reusable patterns, techniques, or failure lessons?\n"
            f"3. Did you discover a novel tool combination or approach?\n"
            f"4. Would a skill have helped you solve this faster?\n\n"
        )
        if st == TaskStatus.COMPLETED:
            output += (
                "If YES to any → Use `skill_manage` (create/patch) to save this knowledge NOW.\n"
                "If unsure → Use `reflect_on_task` with this task_id to structure your reflection."
            )
        else:
            output += (
                "Failure is intelligence. If the failure reveals a reusable pitfall or anti-pattern,\n"
                "save it as a skill (e.g., name it `xxx-anti-pattern`) so future tasks avoid the same trap.\n"
                "Use `reflect_on_task` with this task_id to review what went wrong."
            )

    return tool_result(success=True, output=output)


def _reflect_on_task(task_manager, task_id):
    """Structured reflection on a completed or failed task to distill experience."""
    data = task_manager.get_task_reflection_data(task_id)
    if data is None:
        return tool_error(f"Task {task_id} not found")

    lines = [
        f"## Task Reflection: {data['name']}",
        f"",
        f"**ID:** {data['id']}",
        f"**Description:** {data['description']}",
        f"**Status:** {data['status']}",
        f"**Result:** {data['result'] or '(no result recorded)'}",
        f"**Attempts:** {data['attempts']}",
    ]

    if data['intelligence_source']:
        lines.append(f"**Intelligence Source:** {data['intelligence_source']}")

    notes = data.get('execution_notes', [])
    if notes:
        lines.append(f"\n### Execution Notes ({len(notes)})")
        for i, note in enumerate(notes, 1):
            lines.append(f"{i}. {note}")

    findings = data.get('key_findings', [])
    if findings:
        lines.append(f"\n### Key Findings ({len(findings)})")
        for i, finding in enumerate(findings, 1):
            lines.append(f"{i}. {finding}")

    lines.extend([
        "",
        "### Reflection Prompts (answer these to decide if a skill is warranted)",
        "1. What was the core challenge? Was it domain-specific or generalizable?",
        "2. What approach ultimately worked? Can it be abstracted into a reusable workflow?",
        "3. What failed approaches taught you something important?",
        "4. Were there specific tool parameters, combinations, or sequences that mattered?",
        "5. If you faced this exact scenario again, would a skill help?",
        "",
        "### Next Step",
        "If this task contains reusable knowledge, use `skill_manage` (action=create) to save it. "
        "If a similar skill already exists, use `skill_manage` (action=patch) to enrich it.",
    ])

    return tool_result(success=True, output="\n".join(lines))


def _add_task_note(task_manager, task_id, note, finding):
    """Append an execution note or key finding to a running task."""
    if not note and not finding:
        return tool_error("Either 'note' or 'finding' must be provided")
    updated = task_manager.add_task_note(task_id, note=note or "", finding=finding or "")
    if updated is None:
        return tool_error(f"Task {task_id} not found")
    parts = []
    if note:
        parts.append("note added")
    if finding:
        parts.append("finding recorded")
    return tool_result(
        success=True,
        output=f"Task {task_id}: {' and '.join(parts)}. Total notes: {len(updated.execution_notes)}, findings: {len(updated.key_findings)}.",
    )


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
        score_info = f" [info_score: {t.information_score}]" if t.information_score > 0 else ""
        intel_info = f" ← {t.intelligence_source[:60]}" if t.intelligence_source else ""
        lines.append(
            f"{t.id}: [{t.status.value}] {t.name}{score_info} (deps: {deps}){intel_info}"
        )
    return tool_result(success=True, output="\n".join(lines))


def _attack_graph_view(task_manager):
    result = task_manager.attack_graph_view()
    return tool_result(success=True, output=result)


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------


def register_task_tools(task_manager):
    """Register task tools with a custom task manager instance."""
    registry.register(
        name="create_task",
        toolset="task",
        schema=CREATE_TASK_SCHEMA,
        handler=lambda name, description, depend_on=None, on_failure="replan",
        information_score=None, intelligence_source=None, **kw: (
            _create_task(
                task_manager, name, description, depend_on, on_failure,
                information_score, intelligence_source
            )
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

    registry.register(
        name="reflect_on_task",
        toolset="task",
        schema=REFLECT_ON_TASK_SCHEMA,
        handler=lambda task_id, **kw: _reflect_on_task(task_manager, task_id),
        description="Reflect on a completed/failed task to decide if experience should be saved as a skill.",
        emoji="🧠",
    )

    registry.register(
        name="add_task_note",
        toolset="task",
        schema=ADD_TASK_NOTE_SCHEMA,
        handler=lambda task_id, note="", finding="", **kw: _add_task_note(
            task_manager, task_id, note, finding
        ),
        description="Record execution notes and key findings while a task is running.",
        emoji="📝",
    )


# ---------------------------------------------------------------------------
# Inline schemas
# ---------------------------------------------------------------------------

CREATE_TASK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_task",
        "description": (
            "Create a new task in the attack graph. "
            "Use information_score to prioritize high-value exploitation paths (CTF mode). "
            "Set information_score=8-10 for tasks based on source code/credentials discovered by a parent task. "
            "Set information_score=0-3 for pure reconnaissance tasks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Task name"},
                "description": {"type": "string", "description": "What this task does"},
                "depend_on": {
                    "type": "array",
                    "description": "List of task IDs this task depends on. Use this to build causal prerequisite chains in the attack path graph.",
                },
                "information_score": {
                    "type": "integer",
                    "description": "Priority score 0-10. Higher = spawned from richer intelligence (source code, credentials, DB schema). Ready tasks are executed highest-score first.",
                    "minimum": 0,
                    "maximum": 10,
                },
                "intelligence_source": {
                    "type": "string",
                    "description": "Brief note on what parent finding triggered this task (e.g., 'source code of index.php revealed SQL query').",
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

REFLECT_ON_TASK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "reflect_on_task",
        "description": (
            "Structured reflection on a completed or failed task to distill experience. "
            "Use this AFTER marking a task completed/failed to decide whether the knowledge "
            "is worth saving as a skill. The tool returns execution notes, key findings, and "
            "reflection prompts that guide you toward creating a high-quality skill."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task ID to reflect on",
                },
            },
            "required": ["task_id"],
        },
    },
}

ADD_TASK_NOTE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "add_task_note",
        "description": (
            "Record an execution note or key finding while a task is running. "
            "Use this during task execution to capture observations, failures, pivot decisions, "
            "and discoveries. These notes become the raw material for later reflection when the task completes. "
            "Call this after every significant tool call or discovery."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task ID to annotate",
                },
                "note": {
                    "type": "string",
                    "description": "An execution note (e.g., 'Tried SQLi on login form, filtered by WAF. Pivoting to blind SQLi.')",
                },
                "finding": {
                    "type": "string",
                    "description": "A high-signal finding (e.g., 'Found hardcoded API key in /js/app.js: sk-abc123')",
                },
            },
            "required": ["task_id"],
        },
    },
}


# ---------------------------------------------------------------------------
# Persistent TaskManager backed by SQLAlchemy
# ---------------------------------------------------------------------------

class PersistentTaskManager(TaskManager):
    """TaskManager that syncs every mutation to a database."""

    def __init__(self, session_id: str, db=None):
        super().__init__()
        self.session_id = session_id
        self._db = db
        self._loaded = False

    def _get_db(self):
        if self._db is None:
            from Ion.db import get_default_db
            self._db = get_default_db()
        return self._db

    def _sync_task(self, task: Task):
        from Ion.db.models import TaskRecord
        db = self._get_db()
        with next(db.get_session()) as sess:
            existing = sess.query(TaskRecord).filter_by(id=task.id).first()
            if existing is None:
                record = TaskRecord(
                    id=task.id,
                    session_id=self.session_id,
                    name=task.name,
                    description=task.description,
                    status=task.status.value,
                    depend_on=json.dumps(task.depend_on),
                    result=task.result,
                    on_failure=task.on_failure,
                    attempt_count=task.attempt_count,
                    max_attempts=task.max_attempts,
                    information_score=task.information_score,
                    intelligence_source=task.intelligence_source,
                    execution_notes=json.dumps(task.execution_notes),
                    key_findings=json.dumps(task.key_findings),
                )
                sess.add(record)
            else:
                existing.name = task.name
                existing.description = task.description
                existing.status = task.status.value
                existing.depend_on = json.dumps(task.depend_on)
                existing.result = task.result
                existing.on_failure = task.on_failure
                existing.attempt_count = task.attempt_count
                existing.max_attempts = task.max_attempts
                existing.information_score = task.information_score
                existing.intelligence_source = task.intelligence_source
                existing.execution_notes = json.dumps(task.execution_notes)
                existing.key_findings = json.dumps(task.key_findings)
            sess.commit()

    def _delete_from_db(self, task_id: str):
        from Ion.db.models import TaskRecord
        db = self._get_db()
        with next(db.get_session()) as sess:
            record = sess.query(TaskRecord).filter_by(id=task_id).first()
            if record:
                sess.delete(record)
                sess.commit()

    def add_task(self, task: Task) -> Task:
        result = super().add_task(task)
        self._sync_task(result)
        return result

    def add_task_note(
        self,
        task_id: str,
        note: str = "",
        finding: str = "",
    ) -> Optional[Task]:
        updated = super().add_task_note(task_id, note, finding)
        if updated is not None:
            self._sync_task(updated)
        return updated

    def update_status(
        self, task_id: str, status: TaskStatus, result: Optional[str] = None
    ) -> Optional[Task]:
        updated = super().update_status(task_id, status, result)
        if updated is not None:
            self._sync_task(updated)
        return updated

    def delete_task(self, task_id: str) -> bool:
        ok = super().delete_task(task_id)
        if ok:
            self._delete_from_db(task_id)
        return ok

    def load_from_db(self):
        """Load tasks from database into memory."""
        from Ion.db.models import TaskRecord
        db = self._get_db()
        with next(db.get_session()) as sess:
            records = sess.query(TaskRecord).filter_by(session_id=self.session_id).all()
            self._tasks = {}
            for r in records:
                task = Task(
                    id=r.id,
                    name=r.name,
                    description=r.description,
                    status=TaskStatus(r.status),
                    depend_on=json.loads(r.depend_on) if r.depend_on else [],
                    result=r.result,
                    on_failure=r.on_failure,
                    attempt_count=r.attempt_count,
                    max_attempts=r.max_attempts,
                    information_score=r.information_score,
                    intelligence_source=r.intelligence_source,
                    execution_notes=json.loads(r.execution_notes) if r.execution_notes else [],
                    key_findings=json.loads(r.key_findings) if r.key_findings else [],
                )
                self._tasks[task.id] = task
        self._loaded = True
