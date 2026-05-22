import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from Ion.agent import IonAgent


class TestIonAgentPrompt(unittest.TestCase):
    def test_system_prompt_stays_static_without_mission_context(self):
        agent = IonAgent(model_id="test-model", verbose=False)

        static_prompt = agent.get_system_prompt()
        compat_prompt = agent._build_system_prompt(user_goal="Find SQL injection")

        self.assertEqual(compat_prompt, static_prompt)
        self.assertNotIn("## Mission Context", static_prompt)
        self.assertNotIn("Find SQL injection", static_prompt)


if __name__ == "__main__":
    unittest.main()
