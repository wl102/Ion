"""Tests for the synthesis helpers in ion.py that auto-populate
SubagentResult fields from message history when the model leaves them empty.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from Ion.ion import (
    LoopState,
    _action_tag,
    _classify_tool_result,
    _extract_paths_from_command,
    _extract_result,
    _first_error_line,
    _latest_assistant_content,
    _looks_like_result_json,
    _short,
    _synthesize_from_messages,
)
from Ion.subagent_models import (
    SubagentLoopTracker,
    SubagentStatus,
    WhyStopped,
)


class TestShort(unittest.TestCase):
    def test_short_keeps_short_strings(self):
        self.assertEqual(_short("hello", 100), "hello")

    def test_short_truncates_long_strings(self):
        self.assertTrue(_short("a" * 1000, 50).endswith("…"))
        self.assertEqual(len(_short("a" * 1000, 50)), 50)

    def test_short_handles_newlines(self):
        self.assertEqual(_short("a\nb\nc", 100), "a b c")

    def test_short_empty(self):
        self.assertEqual(_short("", 10), "")


class TestClassifyToolResult(unittest.TestCase):
    def test_empty_is_no_signal(self):
        self.assertEqual(_classify_tool_result(""), "no_signal")
        self.assertEqual(_classify_tool_result("   "), "no_signal")

    def test_error_envelope(self):
        self.assertEqual(
            _classify_tool_result('{"error": "command not found"}'),
            "failed",
        )

    def test_traceback(self):
        self.assertEqual(
            _classify_tool_result("Traceback (most recent call last):\n  File ..."),
            "failed",
        )

    def test_success_default(self):
        self.assertEqual(
            _classify_tool_result("PORT     STATE SERVICE\n22/tcp open ssh"),
            "success",
        )

    def test_failed_text_word_alone_not_classified_when_zero_failed(self):
        # "0 failed" / "no failed" is benign
        self.assertEqual(
            _classify_tool_result("Tests run: 100, 0 failed."),
            "success",
        )


class TestFirstErrorLine(unittest.TestCase):
    def test_picks_error_line(self):
        text = "Some preamble\nERROR: connection refused\nMore"
        self.assertIn("connection refused", _first_error_line(text))

    def test_falls_back_to_first_line(self):
        text = "Just some output\nMore data\n"
        self.assertEqual(_first_error_line(text), "Just some output")

    def test_empty(self):
        self.assertEqual(_first_error_line(""), "")


class TestLooksLikeResultJson(unittest.TestCase):
    def test_bare_json(self):
        self.assertTrue(_looks_like_result_json('{"status": "completed", "summary": "x"}'))

    def test_fenced_json(self):
        text = '```json\n{"status": "partial", "summary": "x"}\n```'
        self.assertTrue(_looks_like_result_json(text))

    def test_narrative_text_not_json(self):
        self.assertFalse(
            _looks_like_result_json(
                "Excellent! Port scan complete. Found 18 open ports."
            )
        )

    def test_empty(self):
        self.assertFalse(_looks_like_result_json(""))

    def test_json_without_status(self):
        self.assertFalse(_looks_like_result_json('{"foo": "bar"}'))

    def test_invalid_json(self):
        self.assertFalse(_looks_like_result_json('{"status": "completed"'))


class TestLatestAssistantContent(unittest.TestCase):
    def test_returns_latest(self):
        state = LoopState(messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "first"},
            {"role": "tool", "tool_call_id": "t1", "content": "tool result"},
            {"role": "assistant", "content": "second"},
        ])
        self.assertEqual(_latest_assistant_content(state), "second")

    def test_handles_list_content(self):
        state = LoopState(messages=[
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "hello "},
                    {"type": "text", "text": "world"},
                ],
            },
        ])
        self.assertIn("hello", _latest_assistant_content(state))
        self.assertIn("world", _latest_assistant_content(state))

    def test_skips_empty_assistant(self):
        state = LoopState(messages=[
            {"role": "assistant", "content": "useful"},
            {"role": "assistant", "content": None},
        ])
        self.assertEqual(_latest_assistant_content(state), "useful")


class TestSynthesizeFromMessages(unittest.TestCase):
    def _build_messages(self):
        # Simulate a recon subagent that ran nmap then nuclei
        return [
            {"role": "system", "content": "you are ReconAgent"},
            {"role": "user", "content": "scan target"},
            {
                "role": "assistant",
                "content": "Running nmap first.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "nmap_scan",
                            "arguments": json.dumps(
                                {"target": "10.0.0.1", "ports": "1-65535"}
                            ),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "PORT     STATE SERVICE\n22/tcp open ssh\n80/tcp open http\n443/tcp open https",
            },
            {
                "role": "assistant",
                "content": "Now running nuclei against discovered services.",
                "tool_calls": [
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "nuclei_run",
                            "arguments": json.dumps(
                                {
                                    "target": "http://10.0.0.1",
                                    "output_path": "/tmp/nuclei.txt",
                                }
                            ),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_2",
                "content": "[high] CVE-2024-1234 detected on /admin\n[medium] CVE-2023-9999 found",
            },
            {
                "role": "assistant",
                "content": "Excellent! Port scan complete. Now let me check CVEs.",
            },
        ]

    def test_attempted_actions_collected(self):
        result = _synthesize_from_messages(self._build_messages())
        names = [a.action.split("(")[0] for a in result["attempted_actions"]]
        self.assertIn("nmap_scan", names)
        self.assertIn("nuclei_run", names)

    def test_evidence_is_not_auto_filled(self):
        # Evidence is the model's job — re-injecting raw tool output would
        # defeat the whole point of context compression in delegation.
        result = _synthesize_from_messages(self._build_messages())
        self.assertEqual(result["evidence"], [])

    def test_artifacts_extracted_from_path_args(self):
        result = _synthesize_from_messages(self._build_messages())
        paths = [a.path for a in result["artifacts"]]
        self.assertIn("/tmp/nuclei.txt", paths)

    def test_key_findings_are_header_notes_not_content(self):
        # Key findings should be compact "what tool, what classification,
        # how much output" lines — NOT the actual content.
        result = _synthesize_from_messages(self._build_messages())
        joined = " ".join(result["key_findings"])
        # tool name appears
        self.assertIn("nmap_scan", joined)
        self.assertIn("nuclei_run", joined)
        # classification appears
        self.assertIn("success", joined)
        # but raw output content does NOT (this was the regression we are fixing)
        self.assertNotIn("22/tcp", joined)
        self.assertNotIn("CVE-2024-1234", joined)
        # And each finding is short
        for f in result["key_findings"]:
            self.assertLess(len(f), 100)

    def test_empty_messages(self):
        result = _synthesize_from_messages([])
        self.assertEqual(result["attempted_actions"], [])
        self.assertEqual(result["evidence"], [])

    def test_failed_tool_classified(self):
        msgs = [
            {
                "role": "assistant",
                "content": "trying",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "exec_cmd",
                            "arguments": json.dumps({"cmd": "foo"}),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "c1",
                "content": '{"error": "command not found"}',
            },
        ]
        result = _synthesize_from_messages(msgs)
        self.assertEqual(result["attempted_actions"][0].result, "failed")


class TestExtractResultEnrichment(unittest.TestCase):
    """End-to-end: the regression case from the user's bug report."""

    def test_narrative_text_is_enriched_with_tool_history(self):
        # Reproduce the exact scenario: model produced narrative instead of JSON,
        # but several tool calls happened earlier.
        state = LoopState(messages=[
            {"role": "system", "content": "you are ReconAgent"},
            {"role": "user", "content": "scan 10.0.0.1"},
            {
                "role": "assistant",
                "content": "Running nmap.",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "nmap",
                            "arguments": json.dumps({"target": "10.0.0.1"}),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "c1",
                "content": "22/tcp open ssh\n80/tcp open http\n443/tcp open https",
            },
            {
                "role": "assistant",
                # The exact bug-report style text
                "content": (
                    "Excellent! Port scan complete. Found 18 open ports with "
                    "multiple services. Now let me run vulnerability-specific "
                    "scans and check for CVEs on the key services."
                ),
            },
        ])
        tracker = SubagentLoopTracker()

        result = _extract_result(state, tracker, WhyStopped.SUCCESS)

        # Even though model didn't emit JSON, attempted_actions and key_findings
        # (header notes) must be filled from tool history so the parent does
        # NOT redo the same work.
        self.assertEqual(result.status, SubagentStatus.PARTIAL)
        self.assertGreater(len(result.attempted_actions), 0,
                           "attempted_actions should be auto-populated from tool calls")
        self.assertGreater(len(result.key_findings), 0,
                           "key_findings should at least carry per-tool header notes")
        # Evidence is intentionally NOT auto-filled (preserves context compression).
        self.assertEqual(result.evidence, [],
                         "evidence is the model's job; auto-filling defeats delegation")
        self.assertEqual(result.attempted_actions[0].action.split("(")[0], "nmap")
        self.assertEqual(result.attempted_actions[0].result, "success")
        # Original summary preserved
        self.assertIn("Port scan complete", result.summary)

    def test_model_provided_fields_are_not_overwritten(self):
        # If the model DID provide structured fields, keep them as-is.
        json_output = json.dumps({
            "status": "completed",
            "summary": "found stuff",
            "confidence": "high",
            "key_findings": ["custom finding"],
            "evidence": [
                {"type": "observation", "value": "custom evidence", "source": "manual"}
            ],
            "attempted_actions": [
                {"action": "manual_check", "result": "success", "why": "explicit"}
            ],
            "artifacts": [],
            "why_stopped": "success",
            "recommended_owner": "parent",
        })
        state = LoopState(messages=[
            {
                "role": "assistant",
                "content": "tool noise",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "auto_tool",
                            "arguments": "{}",
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "tool output"},
            {"role": "assistant", "content": json_output},
        ])
        tracker = SubagentLoopTracker()
        result = _extract_result(state, tracker, WhyStopped.SUCCESS)

        self.assertEqual(result.status, SubagentStatus.COMPLETED)
        self.assertEqual(result.key_findings, ["custom finding"])
        self.assertEqual(len(result.evidence), 1)
        self.assertEqual(result.evidence[0].source, "manual")
        self.assertEqual(result.attempted_actions[0].action, "manual_check")


class TestExtractPathsFromCommand(unittest.TestCase):
    def test_nmap_oA_oN(self):
        cmd = "nmap -p- -sV -oA /tmp/nmap_scan -oN /tmp/scan.txt 10.0.0.1"
        paths = _extract_paths_from_command(cmd)
        self.assertIn("/tmp/nmap_scan", paths)
        self.assertIn("/tmp/scan.txt", paths)

    def test_curl_output(self):
        self.assertEqual(
            _extract_paths_from_command("curl --output /tmp/page.html http://x"),
            ["/tmp/page.html"],
        )

    def test_long_form_output_eq(self):
        self.assertEqual(
            _extract_paths_from_command("tool --output=/tmp/out.json args"),
            ["/tmp/out.json"],
        )

    def test_redirect(self):
        self.assertEqual(
            _extract_paths_from_command("echo hi > /tmp/log.txt"),
            ["/tmp/log.txt"],
        )

    def test_append_redirect(self):
        self.assertEqual(
            _extract_paths_from_command("nuclei >> /tmp/nuclei.log"),
            ["/tmp/nuclei.log"],
        )

    def test_tee(self):
        self.assertEqual(
            _extract_paths_from_command("find / | tee -a /tmp/findings.txt"),
            ["/tmp/findings.txt"],
        )

    def test_oG_eq(self):
        self.assertEqual(
            _extract_paths_from_command("nmap -oG=/tmp/grep.txt 10.0.0.1"),
            ["/tmp/grep.txt"],
        )

    def test_skips_non_paths(self):
        # `cd /tmp && ls -la` should NOT pull "la" or unrelated tokens
        self.assertEqual(_extract_paths_from_command("cd /tmp && ls -la"), [])

    def test_empty(self):
        self.assertEqual(_extract_paths_from_command(""), [])

    def test_dedup(self):
        cmd = "nmap -oN /tmp/a.txt > /tmp/a.txt"
        self.assertEqual(_extract_paths_from_command(cmd), ["/tmp/a.txt"])


class TestActionTag(unittest.TestCase):
    def test_non_shell_returns_tool_name(self):
        self.assertEqual(_action_tag("nmap", {"target": "x"}), "nmap")

    def test_bash_picks_first_program(self):
        self.assertEqual(
            _action_tag("bash", {"command": "nmap -p- 10.0.0.1"}),
            "bash:nmap",
        )

    def test_bash_skips_sudo(self):
        self.assertEqual(
            _action_tag("bash", {"command": "sudo curl http://x"}),
            "bash:curl",
        )

    def test_bash_skips_env_assignment(self):
        self.assertEqual(
            _action_tag("bash", {"command": "FOO=bar python script.py"}),
            "bash:python",
        )

    def test_bash_skips_time_and_path(self):
        self.assertEqual(
            _action_tag("bash", {"command": "sudo time /usr/bin/nuclei -u http://x"}),
            "bash:nuclei",
        )

    def test_shell_alias(self):
        self.assertEqual(
            _action_tag("shell", {"cmd": "ls -la /tmp"}),
            "shell:ls",
        )

    def test_empty_command_falls_back(self):
        self.assertEqual(_action_tag("bash", {"command": "   "}), "bash")

    def test_no_args_object(self):
        self.assertEqual(_action_tag("bash", None), "bash")


class TestSynthesizeBashRegression(unittest.TestCase):
    """Regression for the user's second bug report: bash wrappers were losing
    the actual command in attempted_actions and missing -oA artifacts."""

    def test_bash_command_not_truncated(self):
        long_cmd = "nmap -p 22,80,443,445,3306,5432,8080,8443,3389,21,25,110,143 -sV 10.0.0.1"
        msgs = [
            {
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {
                        "name": "bash",
                        "arguments": json.dumps({"command": long_cmd}),
                    },
                }],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "open ports..."},
        ]
        result = _synthesize_from_messages(msgs)
        action = result["attempted_actions"][0].action
        # Full port list should appear (not truncated to 60 chars)
        self.assertIn("22,80,443,445,3306,5432,8080,8443,3389,21,25,110,143", action)

    def test_bash_oA_paths_become_artifacts(self):
        cmd = "nmap -p- -oA /tmp/nmap_scan -oN /tmp/scan.txt 10.0.0.1"
        msgs = [
            {
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {
                        "name": "bash",
                        "arguments": json.dumps({"command": cmd}),
                    },
                }],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "scan output"},
        ]
        result = _synthesize_from_messages(msgs)
        paths = [a.path for a in result["artifacts"]]
        self.assertIn("/tmp/nmap_scan", paths)
        self.assertIn("/tmp/scan.txt", paths)

    def test_bash_findings_distinguish_programs(self):
        msgs = [
            {
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {
                        "name": "bash",
                        "arguments": json.dumps({"command": "nmap -p- 10.0.0.1"}),
                    },
                }],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "ports"},
            {
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": "c2", "type": "function",
                    "function": {
                        "name": "bash",
                        "arguments": json.dumps({"command": "curl http://target"}),
                    },
                }],
            },
            {"role": "tool", "tool_call_id": "c2", "content": "page"},
        ]
        result = _synthesize_from_messages(msgs)
        joined = " | ".join(result["key_findings"])
        # Both programs appear distinctly
        self.assertIn("bash:nmap", joined)
        self.assertIn("bash:curl", joined)


if __name__ == "__main__":
    unittest.main()
