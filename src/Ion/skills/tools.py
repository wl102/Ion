"""Skill tool registration helpers.

This module ensures skill-related tools are registered in the global
tool registry when the PentestAgent is initialized.
"""


def register_skill_tools(skill_registry):
    """Import skill tool modules to trigger their side-effect registrations."""
    # The actual tool registrations live in Ion.tools.skill_tool and are
    # executed at import time via registry.register() calls.
    import Ion.tools.skill_tool  # noqa: F401
