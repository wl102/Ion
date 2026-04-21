import json
from pathlib import Path


tool_map = {}


def tool(name):
    """Decorator that registers a function as a tool under the given name."""

    def decorator(func):
        tool_map[name] = func
        return func

    return decorator


def dispatch(tool_name, **kw):
    """Dispatch a tool call by name to the registered function."""
    func = tool_map[tool_name]
    return func(**kw)


def get_tools_schema():
    """Load tool schemas from the bundled schema.json file."""
    builtin_tools_schema_path = Path(__file__).parent / "schema.json"
    with open(builtin_tools_schema_path, "r", encoding="utf-8") as f:
        json_str = f.read()
        return json.loads(json_str)
