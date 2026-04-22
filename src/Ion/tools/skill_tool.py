from Ion.skills.registry import skill_registry
from .registry import registry, tool_result

# ---------------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------------


def _activate_skills(skill_registry, skill_names):
    results = skill_registry.activate(skill_names)
    outputs = []
    for name, res in results.items():
        if res["success"]:
            outputs.append(res["content"])
        else:
            outputs.append(f"Error activating '{name}': {res.get('error', 'unknown')}")
    return tool_result(
        success=all(r["success"] for r in results.values()),
        output="\n\n".join(outputs),
    )


def _list_skills(skill_registry):
    catalog = skill_registry.get_catalog()
    if not catalog:
        return tool_result(success=True, output="No skills available.")
    lines = [f"{s['name']}: {s['description']}" for s in catalog]
    return tool_result(success=True, output="\n".join(lines))


# ---------------------------------------------------------------------------
# Inline schemas
# ---------------------------------------------------------------------------

ACTIVATE_SKILLS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "activate_skills",
        "description": "Activate one or more skills by loading their full instructions into context.",
        "parameters": {
            "type": "object",
            "properties": {
                "skill_names": {
                    "type": "array",
                    "description": 'List of skill names to activate (e.g., ["nmap", "nuclei"])',
                }
            },
            "required": ["skill_names"],
        },
    },
}

LIST_SKILLS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_skills",
        "description": "List all available skills with name and description.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


registry.register(
    name="activate_skills",
    toolset="skill",
    schema=ACTIVATE_SKILLS_SCHEMA,
    handler=lambda skill_names, **kw: _activate_skills(skill_registry, skill_names),
    description="Activate one or more skills by loading their full instructions into context.",
    emoji="🔧",
)

registry.register(
    name="list_skills",
    toolset="skill",
    schema=LIST_SKILLS_SCHEMA,
    handler=lambda **kw: _list_skills(skill_registry),
    description="List all available skills with name and description.",
    emoji="📚",
)
