"""Tests for the controlled subagent delegation system."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from Ion.subagent_models import (
    Budget,
    SubagentLoopTracker,
    SubagentRequest,
    SubagentResult,
    SubagentStatus,
    WhyStopped,
    RecommendedOwner,
    ToolCallSignature,
)


class TestBudget(unittest.TestCase):
    def test_default_budget(self):
        b = Budget()
        self.assertEqual(b.max_turns, 20)
        self.assertEqual(b.max_tool_calls, 15)
        self.assertEqual(b.max_same_tool_retries, 2)
        self.assertEqual(b.max_no_progress_turns, 3)

    def test_custom_budget(self):
        b = Budget(max_turns=5, max_tool_calls=3)
        self.assertEqual(b.max_turns, 5)
        self.assertEqual(b.max_tool_calls, 3)


class TestSubagentLoopTracker(unittest.TestCase):
    def test_record_tool_call(self):
        t = SubagentLoopTracker()
        t.record_tool_call("nmap", {"target": "127.0.0.1"})
        self.assertEqual(t.tool_call_count, 1)
        self.assertEqual(len(t.tool_call_history), 1)

    def test_duplicate_detection(self):
        t = SubagentLoopTracker()
        t.record_tool_call("nmap", {"target": "127.0.0.1"})
        t.record_tool_call("nmap", {"target": "127.0.0.1"})
        dups = t.count_duplicate_calls("nmap", {"target": "127.0.0.1"}, window=10)
        self.assertEqual(dups, 2)

    def test_progress_tracking(self):
        t = SubagentLoopTracker()
        t.mark_progress(True)
        self.assertEqual(t.no_progress_turn_count, 0)
        t.mark_progress(False)
        self.assertEqual(t.no_progress_turn_count, 1)
        t.mark_progress(False)
        self.assertEqual(t.no_progress_turn_count, 2)

    def test_budget_check_tool_limit(self):
        t = SubagentLoopTracker()
        b = Budget(max_tool_calls=3)
        t.record_tool_call("a", {})
        t.record_tool_call("b", {})
        self.assertIsNone(t.check_budget(b))
        t.record_tool_call("c", {})
        self.assertEqual(t.check_budget(b), "tool_limit")

    def test_budget_check_no_progress(self):
        t = SubagentLoopTracker()
        b = Budget(max_no_progress_turns=3)
        t.mark_progress(False)
        t.mark_progress(False)
        self.assertIsNone(t.check_budget(b))
        t.mark_progress(False)
        self.assertEqual(t.check_budget(b), "no_progress")


class TestSubagentResultParsing(unittest.TestCase):
    def test_from_raw_output_json_block(self):
        raw = '```json\n{"status": "completed", "summary": "done", "confidence": "high"}\n```'
        result = SubagentResult.from_raw_output(raw)
        self.assertEqual(result.status, SubagentStatus.COMPLETED)
        self.assertEqual(result.summary, "done")
        self.assertEqual(result.confidence, "high")

    def test_from_raw_output_bare_json(self):
        raw = '{"status": "blocked", "summary": "stuck", "confidence": "low"}'
        result = SubagentResult.from_raw_output(raw)
        self.assertEqual(result.status, SubagentStatus.BLOCKED)

    def test_from_raw_output_fallback(self):
        raw = "This is just plain text with no JSON."
        result = SubagentResult.from_raw_output(raw)
        self.assertEqual(result.status, SubagentStatus.PARTIAL)
        self.assertEqual(result.summary, raw)


class TestSubagentRequest(unittest.TestCase):
    def test_request_defaults(self):
        req = SubagentRequest(agent_name="XSSAgent", goal="find xss", context="")
        self.assertEqual(req.agent_name, "XSSAgent")
        self.assertEqual(req.budget.max_turns, 20)
        self.assertEqual(req.on_failure, "replan")


class TestToolCallSignature(unittest.TestCase):
    def test_from_call(self):
        sig = ToolCallSignature.from_call("scan", {"host": "a", "port": 80})
        self.assertEqual(sig.name, "scan")
        self.assertIn("host", sig.arguments_hash)


if __name__ == "__main__":
    unittest.main()
