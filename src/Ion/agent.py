import os
import queue
from typing import Any, Optional

from dotenv import load_dotenv
from openai import OpenAI

from Ion.ion import LoopState, run_agent_loop
from Ion.observability import ObservabilityLogger
from Ion.prompts import PromptBuilder
from Ion.agents.registry import AgentRegistry
from Ion.skills.registry import SkillRegistry
from Ion.skills.tools import register_skill_tools
from Ion.tools.registry import registry
from Ion.tools.task_tool import (
    TaskManager,
    register_task_tools,
    set_current_task_manager,
    reset_current_task_manager,
)

# Import remaining built-in tools so their side-effect registrations fire.
import Ion.tools.shell  # noqa: F401
import Ion.tools.programing  # noqa: F401
import Ion.tools.network_tool  # noqa: F401
import Ion.tools.web_search  # noqa: F401
import Ion.tools.spawn_tool  # noqa: F401

load_dotenv()

# Fallback system prompt used when the user opts out of layered prompts.
DEFAULT_SYSTEM_PROMPT = (
    "You are Ion, an intelligent autonomous agent. "
    "You can plan and execute tasks using a dynamic task graph, run specialized tools via skills, "
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


_RUNTIME_CONTEXT_MARKER = "[ION_RUNTIME_CONTEXT]"


def _inject_or_replace_runtime_context(messages: list[dict], context: str):
    """
    Inject or replace a dynamic runtime context message at the end of the list.
    This keeps messages[0] (the static system prompt) untouched so prefix
    caching can reuse its KV cache across turns.
    """
    marked_content = f"{_RUNTIME_CONTEXT_MARKER}\n\n{context}"

    # Search backwards for an existing runtime context message
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") == "system" and _RUNTIME_CONTEXT_MARKER in (
            msg.get("content") or ""
        ):
            msg["content"] = marked_content
            return

    # Not found: append as a new trailing system message
    messages.append({"role": "system", "content": marked_content})


class IonAgent:
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
        # Mode selection (unified domain + operational style):
        #   "general"  — General-purpose task solving (default)
        #   "security" — Security assessment / penetration testing
        #   "ctf"      — CTF capture-the-flag mode (flag-driven, aggressive)
        use_layered_prompts: bool = True,
        mode: str = "general",
        dynamic_config: Optional[dict[str, Any]] = None,
        # ---- Loop / context configuration ----
        max_turns: int = 0,
        context_max_tokens: int = 0,
        verbose: bool = True,
    ):
        self.model_id = model_id or os.getenv("MODEL_ID", "")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.max_turns = max_turns or int(os.getenv("AGENT_MAX_LOOP", "0"))
        self.context_max_tokens = context_max_tokens or int(
            os.getenv("CONTEXT_MAX_TOKENS", "0")
        )
        self.verbose = verbose

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
        self.hook_queue: queue.Queue = queue.Queue()

        # 注册依赖上下文的工具（task / skill）
        register_task_tools(self.task_manager)
        register_skill_tools(self.skill_registry)

        self.tools = registry.get_tools_schema()
        self.use_layered_prompts = use_layered_prompts
        self.mode = mode

        # ---- Build prompt builder (Layer 1 + Layer 2) ----
        if self.use_layered_prompts:
            dyn_cfg = {
                "mode": self.mode,
                **(dynamic_config or {}),
            }
            self._prompt_builder = PromptBuilder(dynamic_config=dyn_cfg)
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

        # ---- Pre-build static system prompt for prefix caching ----
        self._static_system_prompt = self._build_static_system_prompt()

    # ------------------------------------------------------------------ #
    #  Prompt assembly helpers                                           #
    # ------------------------------------------------------------------ #

    def _build_runtime_context(
        self, user_goal: str, messages: Optional[list[dict]] = None
    ) -> dict[str, Any]:
        """Assemble Layer 3 (runtime) context from current agent state."""
        # NOTE: messages parameter is kept for backward compatibility but no
        # longer used. execution_history has been removed to preserve prefix
        # cache stability (the conversation history is already in messages).
        ctx = PromptBuilder.build_full_runtime_context(
            user_goal=user_goal,
            task_manager=self.task_manager,
            skill_registry=self.skill_registry,
            tools_schema=self.tools,
        )
        # Inject sub-agent catalog so the parent agent knows what it can delegate
        subagent_catalog = self.agent_registry.get_catalog_xml()
        if subagent_catalog:
            ctx["subagent_catalog"] = subagent_catalog
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
        return self._prompt_builder.build_system_prompt(runtime_ctx)

    def _build_static_system_prompt(self) -> str:
        """Build the static system prompt (Layers 1-4 + 6) once per session."""
        if not self.use_layered_prompts or self._prompt_builder is None:
            prompt = self._fallback_prompt or DEFAULT_SYSTEM_PROMPT
            subagent_catalog = self.agent_registry.get_catalog_xml()
            if subagent_catalog:
                prompt += (
                    f"\n\nYou may delegate specialized tasks to sub-agents. "
                    f"Use list_subagents to see available agents and spawn_subagent to delegate.\n\n"
                    f"{subagent_catalog}"
                )
            return prompt

        subagent_catalog = self.agent_registry.get_catalog_xml()
        return self._prompt_builder.build_static_system_prompt(
            subagent_catalog=subagent_catalog
        )

    def _build_dynamic_context(self, user_goal: str) -> str:
        """Build only the dynamic Mission Context (Layer 5)."""
        if not self.use_layered_prompts or self._prompt_builder is None:
            return ""

        runtime_ctx = PromptBuilder.build_full_runtime_context(
            user_goal=user_goal,
            task_manager=self.task_manager,
            skill_registry=self.skill_registry,
            tools_schema=self.tools,
        )
        return self._prompt_builder.build_dynamic_context(runtime_ctx)

    # ------------------------------------------------------------------ #
    #  Main execution                                                    #
    # ------------------------------------------------------------------ #

    def submit_hook(self, content: str):
        """Inject a user message into the running agent loop."""
        self.hook_queue.put(content)

    def run(
        self,
        query: str = "",
        callbacks: Optional[dict[str, Any]] = None,
        pause_check: Optional[callable] = None,
        initial_messages: Optional[list[dict]] = None,
    ) -> str:
        """Run the agent loop.

        Args:
            query: The initial user query. Ignored when `initial_messages` is provided.
            callbacks: Optional streaming/event callbacks.
            pause_check: Optional callable that blocks between turns (for interrupt/resume).
            initial_messages: Optional pre-built message list. When provided, the loop
                resumes from this context instead of starting fresh with [system, user].
        """
        if initial_messages is not None:
            messages = list(initial_messages)
            # Derive user_goal from the first user message for system-prompt refresh
            user_goal = query
            for msg in messages:
                if msg.get("role") == "user":
                    user_goal = msg.get("content", "") or query
                    break
        else:
            user_goal = query
            messages = [
                {"role": "system", "content": self._static_system_prompt},
                {"role": "user", "content": query},
            ]

        state = LoopState(
            messages=messages,
            max_turns=self.max_turns,
            context_max_tokens=self.context_max_tokens,
            hook_queue=self.hook_queue,
        )

        # Callback to refresh the system prompt before each turn.
        # This allows Layer 3 runtime context (task graph, execution history)
        # to stay up-to-date as the agent loop progresses.
        def _on_before_turn(st: LoopState):
            if not self.use_layered_prompts:
                return
            dynamic_ctx = self._build_dynamic_context(user_goal=user_goal)
            if dynamic_ctx:
                _inject_or_replace_runtime_context(st.messages, dynamic_ctx)

        # Inject verbose flag into callbacks so sub-agents can inherit it
        if callbacks is None:
            callbacks = {}
        callbacks.setdefault("verbose", self.verbose)

        # Bind this agent's task_manager to the current execution context so
        # that the globally-registered task tools (create_task, update_task,
        # attack_graph_view, ...) dispatch to *this* session's DAG. Without
        # this, sessions sharing the same process would silently overwrite
        # each other's task handlers via the global tool registry.
        tm_token = set_current_task_manager(self.task_manager)
        try:
            run_agent_loop(
                self.client,
                self.model_id,
                state,
                self.tools,
                self.logger,
                on_before_turn=_on_before_turn,
                callbacks=callbacks,
                pause_check=pause_check,
                verbose=self.verbose,
            )
        finally:
            reset_current_task_manager(tm_token)

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


# Backward compatibility alias
class PentestAgent(IonAgent):
    """Backward-compatible alias. Equivalent to IonAgent(mode='security')."""

    def __init__(self, *args, **kwargs):
        if "mode" not in kwargs:
            kwargs["mode"] = "security"
        super().__init__(*args, **kwargs)
