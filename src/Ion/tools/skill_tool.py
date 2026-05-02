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
    catalog = skill_registry.list_skills()
    if not catalog:
        return tool_result(success=True, output="No skills available.")
    lines = []
    for s in catalog:
        tags = f"  [tags: {', '.join(s['tags'])}]" if s.get("tags") else ""
        category = f"  [category: {s['category']}]" if s.get("category") else ""
        lines.append(f"- {s['name']}: {s['description']}{category}{tags}")
    return tool_result(success=True, output="\n".join(lines))


def _skill_view(skill_registry, name, path=None):
    result = skill_registry.skill_view(name, path)
    if not result["success"]:
        return tool_result(success=False, error=result["error"])

    if path is None:
        # Level 1: full view
        content = result["content"]
        lines = [
            f"# Skill: {content['name']}",
            f"**Description:** {content['description']}",
        ]
        if content.get("compatibility"):
            lines.append(f"**Compatibility:** {content['compatibility']}")
        if content.get("platforms"):
            lines.append(f"**Platforms:** {', '.join(content['platforms'])}")
        if content.get("allowed_tools"):
            lines.append(f"**Allowed Tools:** {', '.join(content['allowed_tools'])}")

        resources = content.get("resources", {})
        if resources:
            lines.append("\n**Resources:**")
            for category, files in resources.items():
                lines.append(f"  {category}/")
                for f in files:
                    lines.append(f"    - {f}")

        lines.append("\n**Body:**")
        lines.append(content["body"])
        return tool_result(success=True, output="\n".join(lines))

    # Level 2: specific file
    return tool_result(
        success=True,
        output=f"--- {result['skill']}/{result['path']} ---\n{result['content']}",
    )


def _skill_manage(skill_registry, action, name, **kwargs):
    if action == "create":
        content = kwargs.get("content", "")
        if not content:
            return tool_result(success=False, error="'content' is required for create")
        category = kwargs.get("category")
        result = skill_registry.create_skill(name, content, category=category)

    elif action == "patch":
        old_string = kwargs.get("old_string", "")
        new_string = kwargs.get("new_string", "")
        if old_string == "":
            return tool_result(
                success=False, error="'old_string' and 'new_string' are required for patch"
            )
        result = skill_registry.patch_skill(name, old_string, new_string)

    elif action == "edit":
        content = kwargs.get("content", "")
        if not content:
            return tool_result(success=False, error="'content' is required for edit")
        result = skill_registry.edit_skill(name, content)

    elif action == "delete":
        result = skill_registry.delete_skill(name)

    elif action == "write_file":
        file_path = kwargs.get("file_path", "")
        file_content = kwargs.get("file_content", "")
        if not file_path:
            return tool_result(
                success=False, error="'file_path' is required for write_file"
            )
        result = skill_registry.write_skill_file(name, file_path, file_content)

    elif action == "remove_file":
        file_path = kwargs.get("file_path", "")
        if not file_path:
            return tool_result(
                success=False, error="'file_path' is required for remove_file"
            )
        result = skill_registry.remove_skill_file(name, file_path)

    else:
        return tool_result(success=False, error=f"Unknown action: '{action}'")

    if result["success"]:
        return tool_result(success=True, output=str(result))
    return tool_result(success=False, error=result["error"])


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
        "description": "List all available skills with name, description, category, and tags (Level 0 progressive disclosure).",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

SKILL_VIEW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "skill_view",
        "description": (
            "View a skill's full content (Level 1) or a specific resource file (Level 2). "
            "Use without 'path' to see the full SKILL.md content and metadata. "
            "Use with 'path' to read a specific file from scripts/, references/, or assets/."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the skill to view",
                },
                "path": {
                    "type": "string",
                    "description": "Optional relative path to a resource file within the skill directory (e.g., 'references/common-payloads.md')",
                },
            },
            "required": ["name"],
        },
    },
}

SKILL_MANAGE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "skill_manage",
        "description": (
            "YOUR PROCEDURAL MEMORY — use this to save experience from completed tasks so future you "
            "does not have to rediscover the same knowledge. This is how you self-improve over time. "
            "When a task reveals a reusable workflow, technique, failure pattern, or tool combination, "
            "capture it as a skill immediately while the details are fresh. "
            "Actions: create (new skill from scratch), patch (add a section/example to existing skill), "
            "edit (full replace), delete (remove), write_file (add supporting script/reference), remove_file. "
            "For 'create', write a complete SKILL.md with frontmatter (name, description, metadata) and actionable body."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "patch", "edit", "delete", "write_file", "remove_file"],
                    "description": (
                        "create = new skill from a full SKILL.md; "
                        "patch = targeted edit (add a pitfall, example, or section to existing skill); "
                        "edit = full replace of SKILL.md; "
                        "delete = remove skill entirely; "
                        "write_file = add a supporting script/reference file; "
                        "remove_file = delete a supporting file"
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Skill name (kebab-case, e.g., 'jwt-auth-bypass', 'sqlmap-tamper-guide')",
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Full SKILL.md content for create/edit. Must include YAML frontmatter with 'name' and 'description', "
                        "followed by a body with: When to use, Step-by-step workflow, Concrete examples, Pitfalls & lessons learned."
                    ),
                },
                "category": {
                    "type": "string",
                    "description": "Optional category directory for the skill (e.g., 'exploitation', 'reconnaissance')",
                },
                "old_string": {
                    "type": "string",
                    "description": "Exact text to locate and replace (for patch action). Must be unique within the SKILL.md.",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text that will be inserted in place of old_string (for patch action)",
                },
                "file_path": {
                    "type": "string",
                    "description": "Relative path within the skill directory (for write_file / remove_file, e.g., 'scripts/scan.py')",
                },
                "file_content": {
                    "type": "string",
                    "description": "Content to write for write_file action",
                },
            },
            "required": ["action", "name"],
        },
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
    description="List all available skills with name, description, category, and tags (Level 0 progressive disclosure).",
    emoji="📚",
)

registry.register(
    name="skill_view",
    toolset="skill",
    schema=SKILL_VIEW_SCHEMA,
    handler=lambda name, path=None, **kw: _skill_view(skill_registry, name, path),
    description="View a skill's full content (Level 1) or a specific resource file (Level 2).",
    emoji="👁️",
)

registry.register(
    name="skill_manage",
    toolset="skill",
    schema=SKILL_MANAGE_SCHEMA,
    handler=lambda action, name, **kw: _skill_manage(skill_registry, action, name, **kw),
    description="Create, update, patch, or delete agent-managed skills (procedural memory).",
    emoji="✏️",
)
