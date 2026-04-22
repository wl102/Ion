"""Ion built-in tools.

Importing this package (or any individual tool module) triggers
side-effect registrations in the global ToolRegistry.
"""

# Ensure all built-in tools are registered when this package is imported.
from Ion.tools import shell  # noqa: F401
from Ion.tools import programing  # noqa: F401
from Ion.tools import network_tool  # noqa: F401
from Ion.tools import web_search  # noqa: F401
from Ion.tools import spawn_tool  # noqa: F401
from Ion.tools import skill_tool  # noqa: F401
from Ion.tools import task_tool  # noqa: F401
