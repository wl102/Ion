from __future__ import annotations

import os
import shutil
import yaml
from pathlib import Path
from typing import Optional

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
    platforms: list[str] = Field(default_factory=list)
    required_environment_variables: list[dict] = Field(default_factory=list)
    body: str = ""
    raw_frontmatter: str = ""

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
                    resources[subdir] = sorted(files)
        return resources

    def get_resource_content(self, relative_path: str) -> Optional[str]:
        """Read the content of a specific resource file."""
        p = self.get_resource_path(relative_path)
        if not p.exists() or not p.is_file():
            return None
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return None

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

    def to_summary(self) -> dict:
        """Return a compact summary for Level 0 disclosure."""
        hermes_meta = self.metadata.get("hermes", {})
        tags = hermes_meta.get("tags", [])
        category = hermes_meta.get("category", "")
        if not category and self.metadata.get("category"):
            category = self.metadata.get("category")
        return {
            "name": self.name,
            "description": self.description,
            "category": category,
            "tags": tags,
            "platforms": self.platforms,
            "compatibility": self.compatibility,
        }

    def to_full_view(self) -> dict:
        """Return full skill view for Level 1 disclosure."""
        return {
            "name": self.name,
            "description": self.description,
            "metadata": self.metadata,
            "platforms": self.platforms,
            "compatibility": self.compatibility,
            "license": self.license,
            "allowed_tools": self.allowed_tools,
            "required_environment_variables": self.required_environment_variables,
            "resources": self.list_resources(),
            "body": self.body,
        }


class SkillRegistry:
    """Discovers, parses, and manages Agent Skills.

    Progressive disclosure levels:
      Level 0: list_skills()     -> [{name, description, category, tags}, ...]
      Level 1: skill_view(name)  -> Full content + metadata
      Level 2: skill_view(name, path) -> Specific reference file content
    """

    # Built-in skills live alongside the package (src/Ion/skills/ directory)
    BUILTIN_SKILLS_DIR = Path(__file__).parent
    USER_SKILLS_DIR = Path.home() / ".ion" / "skills"

    def __init__(self, extra_dirs: Optional[list[str | Path]] = None):
        self._skills: dict[str, Skill] = {}
        self._active_skills: set[str] = set()
        self._search_dirs: list[Path] = []

        # Ensure user-level directory exists and populate with built-ins
        self._ensure_user_skills_dir()

        # Register search paths in priority order (earlier = higher priority)
        # 1. Extra dirs (highest)
        if extra_dirs:
            self._search_dirs.extend(Path(d) for d in extra_dirs)
        # 2. ~/.ion/skills/ (client-native, read-write)
        self._search_dirs.append(self.USER_SKILLS_DIR)
        # 3. Project-level skills
        self._search_dirs.append(Path.cwd() / ".ion" / "skills")

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

    # ------------------------------------------------------------------ #
    #  Discovery                                                         #
    # ------------------------------------------------------------------ #

    def discover(self):
        """Scan search directories for SKILL.md files (recursively)."""
        self._skills = {}
        seen: set[str] = set()

        for search_dir in self._search_dirs:
            if not search_dir.exists():
                continue
            for skill_md in search_dir.rglob("SKILL.md"):
                if not skill_md.is_file():
                    continue

                skill = self._parse_skill(skill_md)
                if skill is None:
                    continue

                # Earlier dirs have higher priority; skip duplicates from later dirs
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

        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        frontmatter_text = parts[1].strip()
        body = parts[2].strip()

        try:
            frontmatter = yaml.safe_load(frontmatter_text) or {}
        except yaml.YAMLError:
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

        platforms = frontmatter.get("platforms", [])
        if isinstance(platforms, str):
            platforms = [p.strip() for p in platforms.split(",") if p.strip()]

        return Skill(
            name=name,
            description=description,
            skill_dir=skill_md.parent,
            license=str(frontmatter.get("license", "")),
            compatibility=str(frontmatter.get("compatibility", "")),
            metadata=frontmatter.get("metadata", {}),
            allowed_tools=allowed_tools,
            platforms=platforms,
            required_environment_variables=frontmatter.get(
                "required_environment_variables", []
            ),
            body=body,
            raw_frontmatter=frontmatter_text,
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
                    if ":" in value and not any(
                        c in value for c in ('"', "'", "[", "{", "|", ">")
                    ):
                        line = f'{key}: "{value.strip()}"'
            lines.append(line)
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    #  Progressive Disclosure (Level 0 / 1 / 2)                          #
    # ------------------------------------------------------------------ #

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def list_skills(self) -> list[dict]:
        """Level 0: Return compact summaries of all available skills."""
        current_platform = _detect_platform()
        results = []
        for skill in self._skills.values():
            if skill.platforms and current_platform not in skill.platforms:
                continue
            if not self._skill_is_available(skill):
                continue
            results.append(skill.to_summary())
        return sorted(results, key=lambda s: s["name"])

    def skill_view(self, name: str, path: Optional[str] = None) -> dict:
        """Level 1 (path=None) or Level 2 (path given) disclosure."""
        skill = self._skills.get(name)
        if skill is None:
            return {"success": False, "error": f"Skill '{name}' not found"}

        if path is None:
            # Level 1: full skill view
            return {"success": True, "content": skill.to_full_view()}

        # Level 2: specific resource file
        content = skill.get_resource_content(path)
        if content is None:
            return {
                "success": False,
                "error": f"Resource '{path}' not found in skill '{name}'",
            }
        return {"success": True, "skill": name, "path": path, "content": content}

    # ------------------------------------------------------------------ #
    #  Activation & Active State                                         #
    # ------------------------------------------------------------------ #

    def activate(self, skill_names: list[str]) -> dict:
        """Activate skills and return structured content for each."""
        results = {}
        for name in skill_names:
            skill = self._skills.get(name)
            if skill is None:
                results[name] = {"success": False, "error": f"Skill '{name}' not found"}
                continue
            self._active_skills.add(name)
            results[name] = {"success": True, "content": skill.activate()}
        return results

    def get_active_skills(self) -> list[str]:
        return sorted(self._active_skills)

    def deactivate(self, skill_names: Optional[list[str]] = None) -> dict:
        """Deactivate skills. If None, deactivate all."""
        if skill_names is None:
            cleared = list(self._active_skills)
            self._active_skills.clear()
            return {"success": True, "deactivated": cleared}
        deactivated = []
        for name in skill_names:
            if name in self._active_skills:
                self._active_skills.discard(name)
                deactivated.append(name)
        return {"success": True, "deactivated": deactivated}

    def is_active(self, name: str) -> bool:
        return name in self._active_skills

    # ------------------------------------------------------------------ #
    #  Conditional Activation Helpers                                    #
    # ------------------------------------------------------------------ #

    def _skill_is_available(self, skill: Skill) -> bool:
        """Check conditional activation rules (fallback_for/requires)."""
        hermes_meta = skill.metadata.get("hermes", {})

        # Check requires_toolsets
        requires_toolsets = hermes_meta.get("requires_toolsets", [])
        if requires_toolsets:
            for ts in requires_toolsets:
                if not _toolset_available(ts):
                    return False

        # Check requires_tools
        requires_tools = hermes_meta.get("requires_tools", [])
        if requires_tools:
            for t in requires_tools:
                if not _tool_available(t):
                    return False

        # Check fallback_for_toolsets: hide when listed toolsets ARE available
        fallback_for_toolsets = hermes_meta.get("fallback_for_toolsets", [])
        if fallback_for_toolsets:
            if any(_toolset_available(ts) for ts in fallback_for_toolsets):
                return False

        # Check fallback_for_tools: hide when listed tools ARE available
        fallback_for_tools = hermes_meta.get("fallback_for_tools", [])
        if fallback_for_tools:
            if any(_tool_available(t) for t in fallback_for_tools):
                return False

        return True

    # ------------------------------------------------------------------ #
    #  Agent-Managed Skill CRUD                                          #
    # ------------------------------------------------------------------ #

    def create_skill(
        self,
        name: str,
        content: str,
        category: Optional[str] = None,
    ) -> dict:
        """Create a new skill from a full SKILL.md content string."""
        if not name or not _is_valid_skill_name(name):
            return {"success": False, "error": f"Invalid skill name: '{name}'"}

        dest_dir = self.USER_SKILLS_DIR / name
        if dest_dir.exists():
            return {
                "success": False,
                "error": f"Skill '{name}' already exists at {dest_dir}",
            }

        if category:
            dest_dir = self.USER_SKILLS_DIR / category / name
            dest_dir.mkdir(parents=True, exist_ok=True)
        else:
            dest_dir.mkdir(parents=True, exist_ok=True)

        skill_md = dest_dir / "SKILL.md"
        try:
            skill_md.write_text(content, encoding="utf-8")
        except Exception as e:
            return {"success": False, "error": f"Failed to write SKILL.md: {e}"}

        # Re-discover to pick up the new skill
        self.discover()
        return {"success": True, "skill": name, "path": str(dest_dir)}

    def patch_skill(self, name: str, old_string: str, new_string: str) -> dict:
        """Apply a targeted patch to a skill's SKILL.md (token-efficient)."""
        skill = self._skills.get(name)
        if skill is None:
            return {"success": False, "error": f"Skill '{name}' not found"}

        skill_md = skill.skill_dir / "SKILL.md"
        try:
            text = skill_md.read_text(encoding="utf-8")
        except Exception as e:
            return {"success": False, "error": f"Failed to read SKILL.md: {e}"}

        if old_string not in text:
            return {
                "success": False,
                "error": "old_string not found in SKILL.md",
            }

        text = text.replace(old_string, new_string, 1)
        try:
            skill_md.write_text(text, encoding="utf-8")
        except Exception as e:
            return {"success": False, "error": f"Failed to write SKILL.md: {e}"}

        self.discover()
        return {"success": True, "skill": name}

    def edit_skill(self, name: str, content: str) -> dict:
        """Replace a skill's SKILL.md with new full content."""
        skill = self._skills.get(name)
        if skill is None:
            return {"success": False, "error": f"Skill '{name}' not found"}

        skill_md = skill.skill_dir / "SKILL.md"
        try:
            skill_md.write_text(content, encoding="utf-8")
        except Exception as e:
            return {"success": False, "error": f"Failed to write SKILL.md: {e}"}

        self.discover()
        return {"success": True, "skill": name}

    def delete_skill(self, name: str) -> dict:
        """Remove a skill entirely."""
        skill = self._skills.get(name)
        if skill is None:
            return {"success": False, "error": f"Skill '{name}' not found"}

        try:
            shutil.rmtree(skill.skill_dir)
        except Exception as e:
            return {"success": False, "error": f"Failed to remove skill dir: {e}"}

        self._active_skills.discard(name)
        self.discover()
        return {"success": True, "skill": name}

    def write_skill_file(self, name: str, file_path: str, file_content: str) -> dict:
        """Add or update a supporting file in a skill directory."""
        skill = self._skills.get(name)
        if skill is None:
            return {"success": False, "error": f"Skill '{name}' not found"}

        target = skill.skill_dir / file_path
        # Prevent escaping skill directory
        try:
            target.relative_to(skill.skill_dir.resolve())
        except ValueError:
            return {"success": False, "error": "file_path escapes skill directory"}

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(file_content, encoding="utf-8")
        except Exception as e:
            return {"success": False, "error": f"Failed to write file: {e}"}

        return {"success": True, "skill": name, "file": file_path}

    def remove_skill_file(self, name: str, file_path: str) -> dict:
        """Remove a supporting file from a skill directory."""
        skill = self._skills.get(name)
        if skill is None:
            return {"success": False, "error": f"Skill '{name}' not found"}

        target = skill.skill_dir / file_path
        try:
            target.relative_to(skill.skill_dir.resolve())
        except ValueError:
            return {"success": False, "error": "file_path escapes skill directory"}

        if not target.exists():
            return {"success": False, "error": f"File '{file_path}' not found"}

        try:
            target.unlink()
        except Exception as e:
            return {"success": False, "error": f"Failed to remove file: {e}"}

        return {"success": True, "skill": name, "file": file_path}

    # ------------------------------------------------------------------ #
    #  Legacy / Prompt helpers                                           #
    # ------------------------------------------------------------------ #

    def get_catalog(self) -> list[dict]:
        """Return skill catalog for model disclosure (Level 0)."""
        return self.list_skills()

    def get_catalog_xml(self) -> str:
        """Build the skill catalog in XML format for system prompt injection."""
        skills = self.list_skills()
        if not skills:
            return ""
        lines = ["<available_skills>"]
        for skill in skills:
            lines.append("  <skill>")
            lines.append(f"    <name>{skill['name']}</name>")
            lines.append(f"    <description>{skill['description']}</description>")
            if skill.get("category"):
                lines.append(f"    <category>{skill['category']}</category>")
            if skill.get("tags"):
                lines.append(f"    <tags>{', '.join(skill['tags'])}</tags>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)

    def get_active_skills_xml(self) -> str:
        """Build active skills content in XML format for system prompt injection."""
        if not self._active_skills:
            return ""
        lines = ["<active_skills>"]
        for name in sorted(self._active_skills):
            skill = self._skills.get(name)
            if skill is None:
                continue
            lines.append(skill.activate())
        lines.append("</active_skills>")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  Helpers                                                                    #
# --------------------------------------------------------------------------- #


def _detect_platform() -> str:
    import platform

    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    if system == "windows" or system.startswith("win"):
        return "windows"
    return "linux"


def _is_valid_skill_name(name: str) -> bool:
    import re

    return bool(re.match(r"^[a-z][a-z0-9_-]*$", name))


def _toolset_available(toolset: str) -> bool:
    """Best-effort check whether a toolset is available in the current session.

    This is a heuristic: we check if any registered tool belongs to the toolset.
    If the tool registry hasn't been fully imported yet, we default to True
    (optimistically assume available).
    """
    try:
        from Ion.tools.registry import registry

        for entry in registry._tools.values():
            if entry.toolset == toolset:
                return True
        return False
    except Exception:
        return True


def _tool_available(tool_name: str) -> bool:
    """Best-effort check whether a specific tool is available."""
    try:
        from Ion.tools.registry import registry

        return tool_name in registry._tools
    except Exception:
        return True


skill_registry = SkillRegistry()
