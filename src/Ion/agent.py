import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from openai import OpenAI

from Ion.ion import LoopState, run_agent_loop
from Ion.observability import ObservabilityLogger
from Ion.prompts import PromptBuilder
from Ion.agents.registry import AgentRegistry
from Ion.skills.registry import SkillRegistry
from Ion.skills.tools import register_skill_tools
from Ion.tasks.manager import TaskManager
from Ion.tasks.tools import register_task_tools
from Ion.tools.registry import get_tools_schema

load_dotenv()

# Fallback system prompt used when the user opts out of layered prompts.
DEFAULT_SYSTEM_PROMPT = (
    "You are Ion, a cybersecurity penetration testing agent. "
    "You can plan attack paths using tasks, run pentest tools via skills, "
    "execute shell commands, write Python scripts, make HTTP requests, and search the web. "
    "Always think step by step and use tools when needed."
)

SKILL_INSTRUCTIONS = (
    "The following skills provide specialized instructions for specific tasks. "
    "When a task matches a skill's description, call the activate_skills tool "
    "with the skill's name to load its full instructions. "
    "When a skill references relative paths, resolve them against the skill's "
    "directory and use absolute paths in tool calls."
)


class PentestAgent:
    def __init__(
        self,
        model_id: str = "",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
        task_manager: Optional[TaskManager] = None,
        skill_registry: Optional[SkillRegistry] = None,
        agent_registry: Optional[AgentRegistry] = None,
        logger: Optional[ObservabilityLogger] = None,
        # ---- Layered prompt configuration ----
        use_layered_prompts: bool = True,
        agent_mode: str = "default",
        template_dir: Optional[str | Path] = None,
        dynamic_config: Optional[dict[str, Any]] = None,
        # ---- Loop / context configuration ----
        max_turns: int = 0,
        context_max_tokens: int = 0,
    ):
        self.model_id = model_id or os.getenv("MODEL_ID", "")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.max_turns = max_turns or int(os.getenv("AGENT_MAX_LOOP", "0"))
        self.context_max_tokens = context_max_tokens or int(
            os.getenv("CONTEXT_MAX_TOKENS", "0")
        )

        if not self.model_id:
            raise ValueError("Missing MODEL_ID. Set env var or pass to constructor.")
        if not self.base_url:
            raise ValueError(
                "Missing OPENAI_BASE_URL. Set env var or pass to constructor."
            )
        if not self.api_key:
            raise ValueError(
                "Missing OPENAI_API_KEY. Set env var or pass to constructor."
            )

        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        self.task_manager = task_manager or TaskManager()
        self.skill_registry = skill_registry or SkillRegistry()
        self.agent_registry = agent_registry or AgentRegistry()
        self.logger = logger or ObservabilityLogger()

        # 注册依赖上下文的工具（task / skill）
        register_task_tools(self.task_manager)
        register_skill_tools(self.skill_registry)

        self.tools = get_tools_schema()
        self.use_layered_prompts = use_layered_prompts
        self.agent_mode = agent_mode

        # ---- Build prompt builder (Layer 1 + Layer 2) ----
        if self.use_layered_prompts:
            dyn_cfg = {"agent_mode": self.agent_mode, **(dynamic_config or {})}
            self._prompt_builder = PromptBuilder(
                template_dir=template_dir, dynamic_config=dyn_cfg
            )
            self._fallback_prompt = None
        else:
            # Legacy mode: hard-coded system prompt
            base_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
            catalog = self.skill_registry.get_catalog_xml()
            if catalog:
                self._fallback_prompt = (
                    f"{base_prompt}\n\n{SKILL_INSTRUCTIONS}\n\n{catalog}"
                )
            else:
                self._fallback_prompt = base_prompt
            self._prompt_builder = None

    # ------------------------------------------------------------------ #
    #  Prompt assembly helpers                                           #
    # ------------------------------------------------------------------ #

    def _build_runtime_context(
        self, user_goal: str, messages: Optional[list[dict]] = None
    ) -> dict[str, Any]:
        """Assemble Layer 3 (runtime) context from current agent state."""
        ctx = PromptBuilder.build_full_runtime_context(
            user_goal=user_goal,
            task_manager=self.task_manager,
            skill_registry=self.skill_registry,
            tools_schema=self.tools,
            messages=messages,
        )
        # Inject active skills content if any were activated during the session.
        # SkillRegistry currently does not track active state; we surface catalog instead.
        return ctx

    def _build_system_prompt(
        self, user_goal: str, messages: Optional[list[dict]] = None
    ) -> str:
        """Build the complete system prompt from all three layers."""
        if not self.use_layered_prompts or self._prompt_builder is None:
            prompt = self._fallback_prompt or DEFAULT_SYSTEM_PROMPT
            # Inject sub-agent catalog so the parent agent knows what it can delegate
            subagent_catalog = self.agent_registry.get_catalog_xml()
            if subagent_catalog:
                prompt += (
                    f"\n\nYou may delegate specialized tasks to sub-agents. "
                    f"Use list_subagents to see available agents and spawn_subagent to delegate.\n\n"
                    f"{subagent_catalog}"
                )
            return prompt

        runtime_ctx = self._build_runtime_context(user_goal, messages)
        # Inject sub-agent catalog into runtime context for layered prompts
        subagent_catalog = self.agent_registry.get_catalog_xml()
        if subagent_catalog:
            runtime_ctx["subagent_catalog"] = subagent_catalog
        return self._prompt_builder.build_system_prompt(runtime_ctx)

    # ------------------------------------------------------------------ #
    #  Main execution                                                    #
    # ------------------------------------------------------------------ #

    def run(self, query: str) -> str:
        # Initial system prompt with runtime context (Layer 3 injected at start)
        system_prompt = self._build_system_prompt(user_goal=query)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]
        state = LoopState(
            messages=messages,
            max_turns=self.max_turns,
            context_max_tokens=self.context_max_tokens,
        )

        # Callback to refresh the system prompt before each turn.
        # This allows Layer 3 runtime context (task graph, execution history)
        # to stay up-to-date as the agent loop progresses.
        def _on_before_turn(st: LoopState):
            if not self.use_layered_prompts:
                return
            new_prompt = self._build_system_prompt(
                user_goal=query, messages=st.messages
            )
            if st.messages and st.messages[0].get("role") == "system":
                st.messages[0]["content"] = new_prompt

        run_agent_loop(
            self.client,
            self.model_id,
            state,
            self.tools,
            self.logger,
            on_before_turn=_on_before_turn,
        )

        if self.logger:
            self.logger.log_conversation(state.messages)

        last_msg = state.messages[-1] if state.messages else {}
        return last_msg.get("content", "") or ""

    def get_usage_summary(self) -> dict:
        return self.logger.get_usage_summary()

    def save_tasks(self, path: str):
        self.task_manager.save_to_file(path)

    def load_tasks(self, path: str):
        self.task_manager.load_from_file(path)
