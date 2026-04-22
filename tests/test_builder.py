"""Unit tests for PromptBuilder."""

import pytest

from Ion.prompts.builder import PromptBuilder


class TestPromptBuilderBuildSystemPrompt:
    """Tests for PromptBuilder.build_system_prompt()."""

    def test_default_config_includes_all_sections(self):
        """Default config should include all major sections."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt()

        assert "## Persona" in prompt
        assert "## Primary Directive" in prompt
        assert "## Core Responsibilities" in prompt
        assert "## Domain Knowledge Base" in prompt
        assert "## Execution Principles" in prompt
        assert "## Attack Path Graph Planning" in prompt
        assert "## Tool Usage Guidelines" in prompt
        assert "## Output Format" in prompt

    def test_sections_are_joined_with_double_newline(self):
        """Sections should be separated by double newlines."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt()

        assert "\n\n\n" not in prompt
        assert "## Primary Directive" in prompt
        assert "## Core Responsibilities" in prompt
        assert "## Output Format" in prompt

    def test_agent_mode_default_no_mode_hint(self):
        """Default mode should not include mode hint section."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt()

        assert "## Current Mode" not in prompt

    def test_agent_mode_ctf_includes_ctf_knowledge(self):
        """CTF mode should include CTF-specific domain knowledge."""
        builder = PromptBuilder({"agent_mode": "ctf"})
        prompt = builder.build_system_prompt()

        assert "## Current Mode\nctf" in prompt
        assert "CTF-Specific Optimizations" in prompt

    def test_agent_mode_pentest_includes_pentest_knowledge(self):
        """Pentest mode should include pentest-specific domain knowledge."""
        builder = PromptBuilder({"agent_mode": "pentest"})
        prompt = builder.build_system_prompt()

        assert "## Current Mode\npentest" in prompt
        assert "Penetration Testing Methodology" in prompt

    def test_agent_mode_aggressive_includes_aggressive_principles(self):
        """Aggressive mode should include aggressive execution principles."""
        builder = PromptBuilder({"agent_mode": "aggressive"})
        prompt = builder.build_system_prompt()

        assert "## Current Mode\naggressive" in prompt
        assert "### Aggressive Mode" in prompt

    def test_agent_mode_stealthy_includes_stealthy_principles(self):
        """Stealthy mode should include stealthy execution principles."""
        builder = PromptBuilder({"agent_mode": "stealthy"})
        prompt = builder.build_system_prompt()

        assert "## Current Mode\nstealthy" in prompt
        assert "### Stealthy Mode" in prompt

    def test_exclude_domain_knowledge(self):
        """Can disable domain knowledge section."""
        builder = PromptBuilder({"include_domain_knowledge": False})
        prompt = builder.build_system_prompt()

        assert "## Domain Knowledge Base" not in prompt
        assert "## Core Responsibilities" in prompt

    def test_exclude_execution_principles(self):
        """Can disable execution principles section."""
        builder = PromptBuilder({"include_execution_principles": False})
        prompt = builder.build_system_prompt()

        assert "## Execution Principles" not in prompt
        assert "## Persona" in prompt

    def test_exclude_attack_path_planning(self):
        """Can disable attack path planning section."""
        builder = PromptBuilder({"include_attack_path_planning": False})
        prompt = builder.build_system_prompt()

        assert "## Attack Path Graph Planning" not in prompt
        assert "## Tool Usage Guidelines" in prompt

    def test_exclude_tool_guidelines(self):
        """Can disable tool guidelines section."""
        builder = PromptBuilder({"include_tool_guidelines": False})
        prompt = builder.build_system_prompt()

        assert "## Tool Usage Guidelines" not in prompt

    def test_runtime_context_user_goal(self):
        """Runtime context with user_goal should add Mission Context."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt({"user_goal": "Find SQL injection"})

        assert "### User Objective" in prompt
        assert "Find SQL injection" in prompt
        assert "## Mission Context" in prompt

    def test_runtime_context_subagent_catalog(self):
        """Subagent catalog adds sub-agent delegation sections."""
        builder = PromptBuilder()
        catalog = "## ReconAgent\nSpecializes in recon"
        prompt = builder.build_system_prompt({"subagent_catalog": catalog})

        assert "## Sub-Agent Delegation Rules" in prompt
        assert "AGENT.MD" in prompt
        assert "ReconAgent" in prompt


class TestPromptBuilderRuntimeBlock:
    """Tests for PromptBuilder._build_runtime_block()."""

    def test_empty_context_returns_empty_string(self):
        """Empty context should return empty string."""
        result = PromptBuilder._build_runtime_block({})
        assert result == ""

    def test_user_goal(self):
        """user_goal should create User Objective section."""
        result = PromptBuilder._build_runtime_block({"user_goal": "Test SQL injection"})
        assert "### User Objective" in result
        assert "Test SQL injection" in result

    def test_task_graph_summary(self):
        """task_graph_summary should create Task Graph State section."""
        result = PromptBuilder._build_runtime_block(
            {"task_graph_summary": "3 tasks pending"}
        )
        assert "### Task Graph State" in result
        assert "3 tasks pending" in result

    def test_ready_tasks(self):
        """ready_tasks should create Ready Tasks section."""
        result = PromptBuilder._build_runtime_block({"ready_tasks": "Task-1, Task-2"})
        assert "### Ready Tasks" in result
        assert "Task-1, Task-2" in result

    def test_failed_tasks(self):
        """failed_tasks should create Failed Tasks section."""
        result = PromptBuilder._build_runtime_block({"failed_tasks": "Recon failed"})
        assert "### Failed Tasks" in result
        assert "Recon failed" in result

    def test_active_skills(self):
        """active_skills should create Active Skills section."""
        result = PromptBuilder._build_runtime_block({"active_skills": "SQLMap skill"})
        assert "### Active Skills" in result
        assert "SQLMap skill" in result

    def test_available_skills(self):
        """available_skills should create Available Skills section."""
        result = PromptBuilder._build_runtime_block(
            {"available_skills": "Recon, Exploit"}
        )
        assert "### Available Skills" in result
        assert "Recon, Exploit" in result

    def test_tools_section(self):
        """tools_section should create Available Tools section."""
        result = PromptBuilder._build_runtime_block({"tools_section": "nmap, sqlmap"})
        assert "### Available Tools" in result
        assert "nmap, sqlmap" in result

    def test_execution_history(self):
        """execution_history should create Recent Execution History section."""
        result = PromptBuilder._build_runtime_block(
            {"execution_history": "Ran nmap scan"}
        )
        assert "### Recent Execution History" in result
        assert "Ran nmap scan" in result

    def test_failure_patterns(self):
        """failure_patterns should create Failure Patterns section."""
        result = PromptBuilder._build_runtime_block({"failure_patterns": "WAF blocked"})
        assert "### Failure Patterns" in result
        assert "WAF blocked" in result

    def test_key_facts(self):
        """key_facts should create Key Facts section."""
        result = PromptBuilder._build_runtime_block(
            {"key_facts": "Apache 2.4.41 detected"}
        )
        assert "### Key Facts" in result
        assert "Apache 2.4.41 detected" in result

    def test_custom_context(self):
        """custom_context should create Additional Context section."""
        result = PromptBuilder._build_runtime_block({"custom_context": "Custom info"})
        assert "### Additional Context" in result
        assert "Custom info" in result

    def test_multiple_sections_joined_with_double_newline(self):
        """Multiple sections should be joined with double newlines."""
        result = PromptBuilder._build_runtime_block(
            {
                "user_goal": "Test SQLi",
                "task_graph_summary": "Graph info",
            }
        )
        assert "### User Objective" in result
        assert "### Task Graph State" in result
        assert "\n\n" in result


class TestPromptBuilderBuildSubagentPrompt:
    """Tests for PromptBuilder.build_subagent_prompt()."""

    def test_basic_subagent_prompt_structure(self):
        """Should include identity, rules, task, and context sections."""
        prompt = PromptBuilder.build_subagent_prompt(
            agent_name="ReconAgent",
            agent_body="Recon agent body content",
            task_goal="Scan port 80",
            parent_context="Context from parent",
        )

        assert "# ReconAgent" in prompt
        assert "## Identity" in prompt
        assert "## Rules" in prompt
        assert "## Task" in prompt
        assert "## Context from Parent Agent" in prompt
        assert "ReconAgent" in prompt
        assert "Recon agent body content" in prompt
        assert "Scan port 80" in prompt
        assert "Context from parent" in prompt

    def test_subagent_prompt_with_tools_description(self):
        """Should include tools section when tools_description is provided."""
        prompt = PromptBuilder.build_subagent_prompt(
            agent_name="ExploitAgent",
            agent_body="Exploit agent",
            task_goal="Exploit SQLi",
            parent_context="Found SQLi on /login",
            tools_description="- nmap: network scanner\n- sqlmap: SQL injection tool",
        )

        assert "## Available Tools" in prompt
        assert "nmap" in prompt
        assert "sqlmap" in prompt

    def test_subagent_prompt_without_tools_description(self):
        """Should not include tools section when tools_description is None."""
        prompt = PromptBuilder.build_subagent_prompt(
            agent_name="TestAgent",
            agent_body="Test body",
            task_goal="Test task",
            parent_context="Test context",
        )

        assert "## Available Tools" not in prompt

    def test_subagent_no_spawn_warning(self):
        """Should include warning about not spawning sub-agents."""
        prompt = PromptBuilder.build_subagent_prompt(
            agent_name="TestAgent",
            agent_body="Body",
            task_goal="Task",
            parent_context="Context",
        )

        assert "Do NOT spawn additional sub-agents" in prompt


class TestPromptBuilderContextHelpers:
    """Tests for context builder helper methods."""

    def test_build_tools_context_with_schema(self):
        """Should format tool schema into readable text."""
        schema = [
            {
                "function": {
                    "name": "nmap",
                    "description": "Port scanner",
                    "parameters": {
                        "properties": {
                            "target": {"type": "string"},
                            "ports": {"type": "string"},
                        },
                        "required": ["target"],
                    },
                }
            }
        ]
        result = PromptBuilder.build_tools_context(schema)

        assert result["tools_section"] is not None
        assert "`nmap`" in result["tools_section"]
        assert "Port scanner" in result["tools_section"]
        assert "target: string (required)" in result["tools_section"]
        assert "ports: string" in result["tools_section"]

    def test_build_tools_context_empty_schema(self):
        """Should return None tools_section for empty schema."""
        result = PromptBuilder.build_tools_context([])
        assert result["tools_section"] is None

    def test_build_tools_context_none_schema(self):
        """Should return None tools_section for None schema."""
        result = PromptBuilder.build_tools_context(None)
        assert result["tools_section"] is None

    def test_build_execution_history_with_messages(self):
        """Should extract assistant and tool messages."""
        messages = [
            {"role": "user", "content": "Scan example.com"},
            {"role": "assistant", "content": "Running scan", "tool_calls": []},
            {"role": "tool", "tool_call_id": "1", "content": "Port 80 open"},
        ]
        result = PromptBuilder.build_execution_history(messages)

        assert result["execution_history"] is not None
        assert "Port 80 open" in result["execution_history"]

    def test_build_execution_history_empty_messages(self):
        """Should return None for empty message list."""
        result = PromptBuilder.build_execution_history([])
        assert result["execution_history"] is None

    def test_build_execution_history_max_turns(self):
        """Should limit to max_turns."""
        messages = [
            {"role": "assistant", "content": f"Turn {i}", "tool_calls": []}
            for i in range(10)
        ]
        result = PromptBuilder.build_execution_history(messages, max_turns=3)

        assert result["execution_history"] is not None
        assert "Turn 0" in result["execution_history"]
        assert "Turn 3" not in result["execution_history"]


class TestPromptBuilderDefaultConfig:
    """Tests for PromptBuilder default configuration."""

    def test_default_config_values(self):
        """Should have correct default config values."""
        builder = PromptBuilder()

        assert builder.prompt_config["include_domain_knowledge"] is True
        assert builder.prompt_config["include_execution_principles"] is True
        assert builder.prompt_config["include_attack_path_planning"] is True
        assert builder.prompt_config["include_tool_guidelines"] is True
        assert builder.prompt_config["agent_mode"] == "default"

    def test_config_override(self):
        """Should override defaults with dynamic_config."""
        builder = PromptBuilder(
            {
                "agent_mode": "ctf",
                "include_domain_knowledge": False,
            }
        )

        assert builder.prompt_config["agent_mode"] == "ctf"
        assert builder.prompt_config["include_domain_knowledge"] is False
        assert builder.prompt_config["include_execution_principles"] is True
