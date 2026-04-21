import io
import os
import subprocess
import sys

import requests

from Ion.tools.registry import tool


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
