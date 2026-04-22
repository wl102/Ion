from __future__ import annotations

import shutil
import yaml
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class Agent(BaseModel):
    """A parsed Sub-Agent following the AGENT.md specification."""

    name: str
    description: str
    agent_dir: Path
    metadata: dict = Field(default_factory=dict)
    body: str = ""

    def activate(self) -> str:
        """Return the agent body for model consumption."""
        return self.body


class AgentRegistry:
    """Discovers, parses, and manages Sub-Agents."""

    # Built-in agents live alongside the package (src/Ion/agents/ directory)
    BUILTIN_AGENTS_DIR = Path(__file__).parent
    USER_AGENTS_DIR = Path.home() / ".ion" / "agents"
    PROJECT_AGENTS_DIR = Path.cwd() / ".ion" / "agents"

    def __init__(self, extra_dirs: Optional[list[str | Path]] = None):
        self._agents: dict[str, Agent] = {}
        self._search_dirs: list[Path] = []

        # Ensure user-level directory exists and populate with built-ins
        self._ensure_user_agents_dir()

        # Register search paths in priority order (later = lower priority)
        # 1. Extra dirs (highest)
        if extra_dirs:
            self._search_dirs.extend(Path(d) for d in extra_dirs)
        # 2. ~/.ion/agents/ (client-native)
        self._search_dirs.append(self.USER_AGENTS_DIR)
        # 3. ./.ion/agents/ (project-level)
        self._search_dirs.append(self.PROJECT_AGENTS_DIR)

        self.discover()

    def _ensure_user_agents_dir(self):
        """Create ~/.ion/agents/ and copy built-in agents if empty."""
        if not self.USER_AGENTS_DIR.exists():
            self.USER_AGENTS_DIR.mkdir(parents=True, exist_ok=True)

        if self.BUILTIN_AGENTS_DIR.exists():
            for src_dir in self.BUILTIN_AGENTS_DIR.iterdir():
                if not src_dir.is_dir():
                    continue
                agent_md = src_dir / "AGENT.md"
                if not agent_md.exists():
                    continue
                dest_dir = self.USER_AGENTS_DIR / src_dir.name
                if not dest_dir.exists():
                    shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True)

    def discover(self):
        """Scan search directories for AGENT.md files."""
        self._agents = {}
        seen: set[str] = set()

        for search_dir in self._search_dirs:
            if not search_dir.exists():
                continue
            for entry in search_dir.iterdir():
                if not entry.is_dir():
                    continue
                agent_md = entry / "AGENT.md"
                if not agent_md.exists():
                    continue

                agent = self._parse_agent(agent_md)
                if agent is None:
                    continue

                # Project/user-level precedence: later dirs override earlier
                if agent.name in seen:
                    continue
                seen.add(agent.name)
                self._agents[agent.name] = agent

    def _parse_agent(self, agent_md: Path) -> Optional[Agent]:
        """Parse an AGENT.md file into an Agent object."""
        try:
            text = agent_md.read_text(encoding="utf-8")
        except Exception:
            return None

        if not text.startswith("---"):
            return None

        # Split frontmatter and body
        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        frontmatter_text = parts[1].strip()
        body = parts[2].strip()

        # Parse YAML frontmatter
        try:
            frontmatter = yaml.safe_load(frontmatter_text) or {}
        except yaml.YAMLError:
            return None

        name = frontmatter.get("name", "").strip()
        description = frontmatter.get("description", "").strip()

        if not name or not description:
            return None

        return Agent(
            name=name,
            description=description,
            agent_dir=agent_md.parent,
            metadata=frontmatter.get("metadata", {}),
            body=body,
        )

    def get(self, name: str) -> Optional[Agent]:
        return self._agents.get(name)

    def list_agents(self) -> list[str]:
        return sorted(self._agents.keys())

    def get_catalog(self) -> list[dict]:
        """Return agent catalog for model disclosure (tier 1)."""
        return [
            {
                "name": a.name,
                "description": a.description,
                "location": str(a.agent_dir / "AGENT.md"),
            }
            for a in self._agents.values()
        ]

    def get_catalog_xml(self) -> str:
        """Build the agent catalog in XML format for system prompt injection."""
        if not self._agents:
            return ""
        lines = ["<available_subagents>"]
        for agent in self._agents.values():
            lines.append("  <subagent>")
            lines.append(f"    <name>{agent.name}</name>")
            lines.append(f"    <description>{agent.description}</description>")
            lines.append(f"    <location>{agent.agent_dir / 'AGENT.md'}</location>")
            lines.append("  </subagent>")
        lines.append("</available_subagents>")
        return "\n".join(lines)

    def activate(self, name: str) -> dict:
        """Activate an agent and return its content."""
        agent = self._agents.get(name)
        if agent is None:
            return {"success": False, "error": f"Agent '{name}' not found"}
        return {"success": True, "content": agent.activate()}


agent_registry = AgentRegistry()
