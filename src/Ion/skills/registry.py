from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class Skill(BaseModel):
    """A parsed Agent Skill following the agentskills specification."""

    name: str
    description: str
    skill_dir: Path
    license: str = ""
    compatibility: str = ""
    metadata: dict = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    body: str = ""

    def get_resource_path(self, relative_path: str) -> Path:
        return self.skill_dir / relative_path

    def list_resources(self) -> dict:
        """List bundled resources in scripts/, references/, assets/."""
        resources = {}
        for subdir in ("scripts", "references", "assets"):
            p = self.skill_dir / subdir
            if p.exists():
                files = [
                    str(f.relative_to(self.skill_dir))
                    for f in p.rglob("*")
                    if f.is_file()
                ]
                if files:
                    resources[subdir] = files
        return resources

    def activate(self) -> str:
        """Return structured skill content for model consumption."""
        resources = self.list_resources()
        resource_lines = []
        for category, files in resources.items():
            resource_lines.append(f"  <{category}>")
            for f in files:
                resource_lines.append(f"    <file>{f}</file>")
            resource_lines.append(f"  </{category}>")

        resource_block = "\n".join(resource_lines) if resource_lines else "  (none)"

        return (
            f'<skill_content name="{self.name}">\n'
            f"{self.body}\n\n"
            f"Skill directory: {self.skill_dir}\n"
            f"Relative paths in this skill are relative to the skill directory.\n\n"
            f"<skill_resources>\n"
            f"{resource_block}\n"
            f"</skill_resources>\n"
            f"</skill_content>"
        )


class SkillRegistry:
    """Discovers, parses, and manages Agent Skills."""

    # Built-in skills live alongside the package (src/Ion/skills/ directory)
    BUILTIN_SKILLS_DIR = Path(__file__).parent
    USER_SKILLS_DIR = Path.home() / ".ion" / "skills"
    AGENTS_SKILLS_DIR = Path.home() / ".agents" / "skills"

    def __init__(self, extra_dirs: Optional[list[str | Path]] = None):
        self._skills: dict[str, Skill] = {}
        self._search_dirs: list[Path] = []

        # Ensure user-level directory exists and populate with built-ins
        self._ensure_user_skills_dir()

        # Register search paths in priority order (later = lower priority)
        # 1. Extra dirs (highest)
        if extra_dirs:
            self._search_dirs.extend(Path(d) for d in extra_dirs)
        # 2. ~/.ion/skills/ (client-native)
        self._search_dirs.append(self.USER_SKILLS_DIR)
        # 3. ~/.agents/skills/ (cross-client interoperability)
        self._search_dirs.append(self.AGENTS_SKILLS_DIR)

        self.discover()

    def _ensure_user_skills_dir(self):
        """Create ~/.ion/skills/ and copy built-in skills if empty."""
        if not self.USER_SKILLS_DIR.exists():
            self.USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

        if self.BUILTIN_SKILLS_DIR.exists():
            for src_dir in self.BUILTIN_SKILLS_DIR.iterdir():
                if not src_dir.is_dir():
                    continue
                skill_md = src_dir / "SKILL.md"
                if not skill_md.exists():
                    continue
                dest_dir = self.USER_SKILLS_DIR / src_dir.name
                if not dest_dir.exists():
                    shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True)

    def discover(self):
        """Scan search directories for SKILL.md files."""
        self._skills = {}
        seen: set[str] = set()

        for search_dir in self._search_dirs:
            if not search_dir.exists():
                continue
            for entry in search_dir.iterdir():
                if not entry.is_dir():
                    continue
                skill_md = entry / "SKILL.md"
                if not skill_md.exists():
                    continue

                skill = self._parse_skill(skill_md)
                if skill is None:
                    continue

                # Project/user-level precedence: later dirs override earlier
                if skill.name in seen:
                    continue
                seen.add(skill.name)
                self._skills[skill.name] = skill

    def _parse_skill(self, skill_md: Path) -> Optional[Skill]:
        """Parse a SKILL.md file into a Skill object."""
        try:
            text = skill_md.read_text(encoding="utf-8")
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

        # Parse YAML frontmatter with fallback for malformed YAML
        try:
            frontmatter = yaml.safe_load(frontmatter_text) or {}
        except yaml.YAMLError:
            # Retry with quoting heuristic for colons in values
            fixed = self._fix_yaml(frontmatter_text)
            try:
                frontmatter = yaml.safe_load(fixed) or {}
            except yaml.YAMLError:
                return None

        name = frontmatter.get("name", "").strip()
        description = frontmatter.get("description", "").strip()

        if not name or not description:
            return None

        allowed_tools_raw = frontmatter.get("allowed-tools", "")
        allowed_tools = (
            allowed_tools_raw.split() if isinstance(allowed_tools_raw, str) else []
        )

        return Skill(
            name=name,
            description=description,
            skill_dir=skill_md.parent,
            license=str(frontmatter.get("license", "")),
            compatibility=str(frontmatter.get("compatibility", "")),
            metadata=frontmatter.get("metadata", {}),
            allowed_tools=allowed_tools,
            body=body,
        )

    @staticmethod
    def _fix_yaml(text: str) -> str:
        """Heuristic fix for common YAML issues (unquoted colons)."""
        lines = []
        for line in text.split("\n"):
            stripped = line.strip()
            if ":" in stripped and not stripped.startswith("#"):
                key, sep, value = stripped.partition(":")
                if value.strip() and not (
                    value.strip().startswith('"') or value.strip().startswith("'")
                ):
                    # Check if value contains a colon not inside quotes
                    if ":" in value and not any(
                        c in value for c in ('"', "'", "[", "{", "|", ">")
                    ):
                        line = f'{key}: "{value.strip()}"'
            lines.append(line)
        return "\n".join(lines)

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def list_skills(self) -> list[str]:
        return sorted(self._skills.keys())

    def get_catalog(self) -> list[dict]:
        """Return skill catalog for model disclosure (tier 1)."""
        return [
            {
                "name": s.name,
                "description": s.description,
                "location": str(s.skill_dir / "SKILL.md"),
            }
            for s in self._skills.values()
        ]

    def activate(self, skill_names: list[str]) -> dict:
        """Activate skills and return structured content for each (tier 2)."""
        results = {}
        for name in skill_names:
            skill = self._skills.get(name)
            if skill is None:
                results[name] = {"success": False, "error": f"Skill '{name}' not found"}
                continue
            results[name] = {"success": True, "content": skill.activate()}
        return results

    def get_catalog_xml(self) -> str:
        """Build the skill catalog in XML format for system prompt injection."""
        if not self._skills:
            return ""
        lines = ["<available_skills>"]
        for skill in self._skills.values():
            lines.append("  <skill>")
            lines.append(f"    <name>{skill.name}</name>")
            lines.append(f"    <description>{skill.description}</description>")
            lines.append(f"    <location>{skill.skill_dir / 'SKILL.md'}</location>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)
