import io
import json
import os
import subprocess
import sys
from typing import Optional
from pathlib import Path

import requests


tool_map = {}


def tool(name):
    def decorator(func):
        tool_map[name] = func
        return func

    return decorator


def dispatch(tool_name, **kw):
    func = tool_map[tool_name]
    return func(**kw)


def get_tools_schema():
    builtin_tools_schema_path = Path(__file__).parent / "schema.json"
    with open(builtin_tools_schema_path, "r", encoding="utf-8") as f:
        json_str = f.read()
        return json.loads(json_str)


@tool("bash")
def bash_exec(command: str) -> dict:
    """Run a shell command in the current workspace with safety checks."""
    no_permission = ["rm -rf /", "shutdown", "reboot", "> /dev/", "mkfs", "dd if="]
    if any(item in command for item in no_permission):
        return {"success": False, "output": "Error: Dangerous command blocked"}
    timeout_str = os.getenv("BASH_COMMAND_TIMEOUT_SECONDS")
    timeout = float(timeout_str) if timeout_str else 120
    try:
        output = subprocess.run(
            command,
            shell=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "output": f"Error: Timeout: {timeout}s"}
    except Exception as e:
        return {"success": False, "output": f"Error: {e}"}
    result = output.stdout + output.stderr
    return {
        "success": output.returncode == 0,
        "output": result[:10000] if result else "(no output)",
    }


@tool("python_exec")
def python_exec(code: str) -> dict:
    """Execute Python code in a restricted environment and return stdout."""
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    redirected_output = io.StringIO()
    redirected_error = io.StringIO()
    try:
        sys.stdout = redirected_output
        sys.stderr = redirected_error
        exec(code, {"__builtins__": __builtins__}, {})
    except Exception as e:
        return {"success": False, "output": f"Error: {e}"}
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    output = redirected_output.getvalue() + redirected_error.getvalue()
    return {"success": True, "output": output[:10000] if output else "(no output)"}


@tool("http_request")
def http_request(url: str, method: str = "GET", body: str = "") -> dict:
    """Make an HTTP request.
    url: Target URL.
    method: HTTP method (GET or POST).
    body: Request body for POST.
    """
    try:
        if method.upper() == "POST":
            resp = requests.post(url, data=body, timeout=30)
        else:
            resp = requests.get(url, timeout=30)
        content = resp.text[:10000]
        return {
            "success": 200 <= resp.status_code < 300,
            "output": f"Status: {resp.status_code}\n\n{content}",
        }
    except Exception as e:
        return {"success": False, "output": f"Error: {e}"}


@tool("web_search")
def web_search(query: str) -> dict:
    """Search the web using DuckDuckGo."""
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return {"success": True, "output": "No results found."}
        output = []
        for r in results:
            output.append(
                f"Title: {r.get('title', '')}\n"
                f"URL: {r.get('href', '')}\n"
                f"Snippet: {r.get('body', '')}\n"
            )
        return {"success": True, "output": "\n".join(output)}
    except ImportError:
        return {
            "success": False,
            "output": "Error: duckduckgo-search not installed. Install with: pip install Ion[pentest]",
        }
    except Exception as e:
        return {"success": False, "output": f"Error: {e}"}


# --- Task 工具（由 PentestAgent 初始化时注册）---


def register_task_tools(task_manager):
    @tool("create_task")
    def create_task(
        name: str, description: str, depend_on: Optional[list] = None
    ) -> dict:
        """Create a new task in the attack graph.
        name: Task name.
        description: What this task does.
        depend_on: List of task IDs this task depends on.
        """
        from Ion.tasks import Task

        if depend_on is None:
            depend_on = []
        elif isinstance(depend_on, str):
            depend_on = [depend_on]
        elif not isinstance(depend_on, list):
            return {
                "success": False,
                "output": f"Invalid depend_on type: {type(depend_on).__name__}",
            }
        task = Task(name=name, description=description, depend_on=depend_on)
        task_manager.add_task(task)
        return {"success": True, "output": f"Task created: {task.id} - {task.name}"}

    @tool("update_task")
    def update_task(task_id: str, status: str, result: Optional[str] = None) -> dict:
        """Update a task's status and optionally its result.
        task_id: The task ID.
        status: New status (pending, running, failed, killed, completed).
        result: Optional result text.
        """
        from Ion.tasks import TaskStatus

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
        """List ready tasks in the attack graph"""
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


# --- Skills 工具（由 PentestAgent 初始化时注册）---


def register_skill_tools(skill_registry):
    @tool("activate_skills")
    def activate_skills(skill_names: list) -> dict:
        """Activate one or more skills by loading their full instructions into context.
        skill_names: List of skill names to activate (e.g., ["nmap", "nuclei"]).
        """
        results = skill_registry.activate(skill_names)
        outputs = []
        for name, res in results.items():
            if res["success"]:
                outputs.append(res["content"])
            else:
                outputs.append(
                    f"Error activating '{name}': {res.get('error', 'unknown')}"
                )
        return {
            "success": all(r["success"] for r in results.values()),
            "output": "\n\n".join(outputs),
        }

    @tool("list_skills")
    def list_skills() -> dict:
        """List all available skills with name and description."""
        catalog = skill_registry.get_catalog()
        if not catalog:
            return {"success": True, "output": "No skills available."}
        lines = [f"{s['name']}: {s['description']}" for s in catalog]
        return {"success": True, "output": "\n".join(lines)}
