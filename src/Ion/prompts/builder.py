"""
PromptBuilder - Layered prompt assembly for Ion Agent.

Design inspired by luaniao's prompt template architecture:
  - Static Layer:    Fixed persona, directive, responsibilities, output format
  - Dynamic Layer:   Configurable domain knowledge, principles, tool guidelines
  - Runtime Layer:   Injected state (task graph, skills, execution history, etc.)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape


class PromptBuilder:
    """Builds system prompts from layered templates with runtime context injection."""

    DEFAULT_TEMPLATE_DIR = Path(__file__).parent / "templates" / "en"

    # ------------------------------------------------------------------ #
    #  Layer 2: dynamic prompt toggles (configurable at init time)       #
    # ------------------------------------------------------------------ #
    DEFAULT_DYNAMIC_CONFIG = {
        "include_domain_knowledge": True,
        "include_execution_principles": True,
        "include_tool_guidelines": True,
        "agent_mode": "default",  # "default" | "ctf" | "pentest" | "aggressive" | "stealthy"
    }

    def __init__(
        self,
        template_dir: Optional[Path | str] = None,
        dynamic_config: Optional[dict[str, Any]] = None,
    ):
        """
        Args:
            template_dir: Directory containing Jinja2 templates. Defaults to built-in templates.
            dynamic_config: Overrides for Layer 2 dynamic prompt toggles and agent_mode.
        """
        self.template_dir = Path(template_dir or self.DEFAULT_TEMPLATE_DIR)
        if not self.template_dir.exists():
            raise FileNotFoundError(
                f"Template directory not found: {self.template_dir}"
            )

        self.dynamic_config = {**self.DEFAULT_DYNAMIC_CONFIG, **(dynamic_config or {})}

        self._env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    # ------------------------------------------------------------------ #
    #  Core build method                                                 #
    # ------------------------------------------------------------------ #

    def build_system_prompt(
        self, runtime_context: Optional[dict[str, Any]] = None
    ) -> str:
        """
        Assemble the full system prompt from all three layers.

        Args:
            runtime_context: Layer 3 variables injected at runtime (task graph,
                             skills, execution history, user goal, etc.)

        Returns:
            Rendered system prompt string.
        """
        template = self._env.get_template("system_prompt.jinja2")

        # Merge Layer 2 (dynamic config) + Layer 3 (runtime context)
        context = {
            **self.dynamic_config,
            **(runtime_context or {}),
        }

        return template.render(**context)

    # ------------------------------------------------------------------ #
    #  Convenience helpers for building runtime context from Ion objects   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def build_task_graph_context(task_manager) -> dict[str, Any]:
        """Build runtime context variables from a TaskManager instance."""
        tasks = task_manager.list_tasks()
        if not tasks:
            return {
                "task_graph_summary": "No tasks have been created yet.",
                "ready_tasks": None,
            }

        # Summary of all tasks
        lines = []
        for t in tasks:
            deps = ", ".join(t.depend_on) if t.depend_on else "none"
            lines.append(f"- {t.id}: [{t.status.value}] {t.name} (deps: {deps})")
        graph_summary = "\n".join(lines)

        # Ready tasks
        ready = task_manager.get_ready_tasks()
        ready_text = None
        if ready:
            ready_lines = [f"- {t.id}: {t.name} — {t.description}" for t in ready]
            ready_text = "\n".join(ready_lines)

        return {
            "task_graph_summary": graph_summary,
            "ready_tasks": ready_text,
        }

    @staticmethod
    def build_skills_context(skill_registry) -> dict[str, Any]:
        """Build runtime context variables from a SkillRegistry instance."""
        catalog = skill_registry.get_catalog()
        if not catalog:
            return {
                "available_skills": None,
                "active_skills": None,
            }

        skill_lines = [f"- {s['name']}: {s['description']}" for s in catalog]
        return {
            "available_skills": "\n".join(skill_lines),
            "active_skills": None,  # populated externally if skills are activated
        }

    @staticmethod
    def build_tools_context(tools_schema: list[dict]) -> dict[str, Any]:
        """Build runtime context variables from tool schemas."""
        if not tools_schema:
            return {"tools_section": None}

        lines = []
        for schema in tools_schema:
            func = schema.get("function", {})
            name = func.get("name", "unknown")
            desc = func.get("description", "")
            params = func.get("parameters", {})
            props = params.get("properties", {})
            required = params.get("required", [])

            param_strs = []
            for pname, pdef in props.items():
                ptype = pdef.get("type", "any")
                req_mark = " (required)" if pname in required else ""
                param_strs.append(f"    - {pname}: {ptype}{req_mark}")

            lines.append(f"- `{name}`: {desc}")
            if param_strs:
                lines.extend(param_strs)

        return {"tools_section": "\n".join(lines)}

    @staticmethod
    def build_execution_history(
        messages: list[dict],
        max_turns: int = 5,
    ) -> dict[str, Any]:
        """
        Extract recent execution history from conversation messages for runtime injection.

        Args:
            messages: Full conversation message list.
            max_turns: Maximum recent tool call / assistant turn pairs to include.

        Returns:
            Dict with `execution_history` key, or None if no relevant history.
        """
        # Find the last user message index; only consider messages after it
        last_user_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                last_user_idx = i
                break

        relevant = messages[last_user_idx + 1 :] if last_user_idx >= 0 else messages

        history_entries = []
        turn_count = 0
        for msg in relevant:
            role = msg.get("role")
            if role == "assistant":
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls", [])
                if content or tool_calls:
                    entry = "[Assistant]"
                    if content:
                        entry += f"\n{content}"
                    if tool_calls:
                        for tc in tool_calls:
                            fn = tc.get("function", {})
                            entry += (
                                f"\n  → Tool call: `{fn.get('name', '?')}` "
                                f"args={fn.get('arguments', '{}')}"
                            )
                    history_entries.append(entry)
                    turn_count += 1
            elif role == "tool":
                tool_id = msg.get("tool_call_id", "?")
                content = msg.get("content", "")
                history_entries.append(f"[Tool result {tool_id}]\n{content[:500]}")

            if turn_count >= max_turns:
                break

        if not history_entries:
            return {"execution_history": None}

        return {"execution_history": "\n\n".join(history_entries)}

    @classmethod
    def build_full_runtime_context(
        cls,
        user_goal: str,
        task_manager=None,
        skill_registry=None,
        tools_schema: Optional[list[dict]] = None,
        messages: Optional[list[dict]] = None,
        key_facts: Optional[str] = None,
        failure_patterns: Optional[str] = None,
        custom_context: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Convenience method to build the complete Layer 3 runtime context
        from all available Ion components.
        """
        ctx: dict[str, Any] = {
            "user_goal": user_goal,
            "key_facts": key_facts,
            "failure_patterns": failure_patterns,
            "custom_context": custom_context,
        }

        if task_manager is not None:
            ctx.update(cls.build_task_graph_context(task_manager))

        if skill_registry is not None:
            ctx.update(cls.build_skills_context(skill_registry))

        if tools_schema is not None:
            ctx.update(cls.build_tools_context(tools_schema))

        if messages is not None:
            ctx.update(cls.build_execution_history(messages))

        # Remove None values so `{% if var %}` conditions in templates work cleanly
        return {k: v for k, v in ctx.items() if v is not None}
