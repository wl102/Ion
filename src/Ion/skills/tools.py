from Ion.skills.registry import SkillRegistry
from Ion.tools.registry import tool


def register_skill_tools(skill_registry: SkillRegistry):
    """Register skill-related tools bound to a SkillRegistry instance."""

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
