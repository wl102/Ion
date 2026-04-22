import json
import logging
import threading
from typing import Callable, Dict, Optional
from .tools import _run_async


class ToolEntry:
    """Metadata for a single registered tool."""

    __slots__ = (
        "name",
        "toolset",
        "schema",
        "handler",
        "check_fn",
        "requires_env",
        "is_async",
        "description",
        "emoji",
        "max_result_size_chars",
        "_check_ok",
    )

    def __init__(
        self,
        name,
        toolset,
        schema,
        handler,
        check_fn,
        requires_env,
        is_async,
        description,
        emoji,
        max_result_size_chars=None,
    ):
        self.name = name
        self.toolset = toolset
        self.schema = schema
        self.handler = handler
        self.check_fn = check_fn
        self.requires_env = requires_env
        self.is_async = is_async
        self.description = description
        self.emoji = emoji
        self.max_result_size_chars = max_result_size_chars
        self._check_ok = None  # cached check result

    def run_check(self) -> bool:
        """Run the tool's availability check, caching the result."""
        if self._check_ok is not None:
            return self._check_ok
        if self.check_fn is None:
            self._check_ok = True
            return True
        try:
            self._check_ok = self.check_fn()
        except Exception as e:
            logging.warning(f"Tool check failed for {self.name}: {e}")
            self._check_ok = False
        return self._check_ok


class ToolRegistry:
    """Singleton registry that collects tool schemas + handlers from tool files."""

    def __init__(self):
        self._tools: Dict[str, ToolEntry] = {}
        self._toolset_checks: Dict[str, Callable] = {}
        self._toolset_aliases: Dict[str, str] = {}
        # MCP dynamic refresh can mutate the registry while other threads are
        # reading tool metadata, so keep mutations serialized and readers on
        # stable snapshots.
        self._lock = threading.RLock()

    def register(
        self,
        name,
        toolset="default",
        schema=None,
        handler=None,
        check_fn=None,
        requires_env=None,
        is_async=False,
        description="",
        emoji="",
        max_result_size_chars=None,
    ):
        """Register a tool with full metadata."""
        with self._lock:
            entry = ToolEntry(
                name=name,
                toolset=toolset,
                schema=schema,
                handler=handler,
                check_fn=check_fn,
                requires_env=requires_env,
                is_async=is_async,
                description=description,
                emoji=emoji,
                max_result_size_chars=max_result_size_chars,
            )
            # Run availability check at registration time and cache the result.
            entry.run_check()
            self._tools[name] = entry

    def dispatch(self, tool_name, **kw) -> str:
        """Dispatch a tool call by name to the registered handler.

        Returns a JSON string.  If the handler is not found, its check fails,
        or an unexpected exception is raised, a JSON error string is returned.
        """
        with self._lock:
            entry = self._tools.get(tool_name)
        if entry is None:
            return tool_error(f"Tool not found: {tool_name}")
        if not entry.run_check():
            return tool_error(f"Tool {tool_name} is not available")

        try:
            if entry.is_async:
                result = _run_async(entry.handler(**kw))
            else:
                result = entry.handler(**kw)
        except Exception as e:
            logging.warning(
                f"Unexpected error executing tool {tool_name}: {e}", exc_info=True
            )
            return tool_error(f"Unexpected error: {e}")

        if isinstance(result, str):
            return result

        result = self._maybe_truncate(result, entry)
        return json.dumps(result, ensure_ascii=False)

    def _maybe_truncate(self, result, entry: ToolEntry):
        """Truncate the 'output' field if it exceeds the configured limit."""
        if not entry.max_result_size_chars:
            return result
        if isinstance(result, dict) and "output" in result:
            output = result["output"]
            if isinstance(output, str) and len(output) > entry.max_result_size_chars:
                result = dict(result)
                result["output"] = (
                    output[: entry.max_result_size_chars] + "\n...[truncated]"
                )
        return result

    def get_tools_schema(self) -> list[dict]:
        """Return all registered tool schemas for LLM tool-calling APIs."""
        with self._lock:
            schemas = []
            for entry in self._tools.values():
                if entry.schema:
                    schemas.append(entry.schema)
            return schemas

    def get_tool(self, name) -> Optional[ToolEntry]:
        """Retrieve a single ToolEntry by name."""
        with self._lock:
            return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        with self._lock:
            return list(self._tools.keys())


# ---------------------------------------------------------------------------
# Singleton instance
# ---------------------------------------------------------------------------
registry = ToolRegistry()


# ---------------------------------------------------------------------------
# Helpers for tool response serialization
# ---------------------------------------------------------------------------
# Every tool handler must return a JSON string.  These helpers eliminate the
# boilerplate ``json.dumps({"error": msg}, ensure_ascii=False)`` that appears
# hundreds of times across tool files.
#
# Usage:
#   from Ion.tools.registry import registry, tool_error, tool_result
#
#   return tool_error("something went wrong")
#   return tool_error("not found", code=404)
#   return tool_result(success=True, data=payload)
#   return tool_result(items)            # pass a dict directly


def tool_error(message, **extra) -> str:
    """Return a JSON error string for tool handlers.

    >>> tool_error("file not found")
    '{"error": "file not found"}'
    >>> tool_error("bad input", success=False)
    '{"error": "bad input", "success": false}'
    """
    result = {"error": str(message)}
    if extra:
        result.update(extra)
    return json.dumps(result, ensure_ascii=False)


def tool_result(data=None, **kwargs) -> str:
    """Return a JSON result string for tool handlers.

    Accepts a dict positional arg *or* keyword arguments (not both):

    >>> tool_result(success=True, count=42)
    '{"success": true, "count": 42}'
    >>> tool_result({"key": "value"})
    '{"key": "value"}'
    """
    if data is not None:
        return json.dumps(data, ensure_ascii=False)
    return json.dumps(kwargs, ensure_ascii=False)
