import os

from openai import OpenAI
from dotenv import load_dotenv
from typing import Optional

from Ion.ion import LoopState, run_agent_loop
from Ion.observability import ObservabilityLogger
from Ion.skills import SkillRegistry
from Ion.tasks import TaskManager
from Ion.tools.tools import get_tools_schema, register_skill_tools, register_task_tools


load_dotenv()


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
        logger: Optional[ObservabilityLogger] = None,
    ):
        self.model_id = model_id or os.getenv("MODEL_ID", "")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")

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
        self.logger = logger or ObservabilityLogger()

        # 注册依赖上下文的工具（task / skill）
        register_task_tools(self.task_manager)
        register_skill_tools(self.skill_registry)

        self.tools = get_tools_schema()

        # 构建系统提示（包含 skill catalog）
        base_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        catalog = self.skill_registry.get_catalog_xml()
        if catalog:
            self.system_prompt = f"{base_prompt}\n\n{SKILL_INSTRUCTIONS}\n\n{catalog}"
        else:
            self.system_prompt = base_prompt

    def run(self, query: str) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": query},
        ]
        state = LoopState(messages=messages)
        run_agent_loop(self.client, self.model_id, state, self.tools, self.logger)

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
