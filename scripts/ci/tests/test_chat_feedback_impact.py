"""Usage/error changes select provider persistence and both existing native consumers."""

import unittest

from scripts.ci.impact import load_plan
from scripts.ci.tests.test_impact import scope


class ChatFeedbackImpactTests(unittest.TestCase):
    def test_feedback_helpers_and_fixture_expand_persistence_and_native_consumers(self):
        for path in [
            "backend/services/chat_feedback.py",
            "backend/services/chat_message_metadata.py",
            "backend/tests/feedback_cases.py",
            "contracts/fixtures/chat-feedback.json",
        ]:
            with self.subTest(path=path):
                result = load_plan(scope(path))
                self.assertIn("feedback-provider", result["groups"])
                self.assertIn(
                    "pytest:tests/contracts/test_chat_feedback_contract.py",
                    result["checks"]["python"],
                )
                self.assertIn(
                    "pytest:tests/p0/test_chat_feedback_lifecycle.py", result["checks"]["python"]
                )
                self.assertIn(
                    "pytest:tests/integration/test_mysql_chat_feedback.py::test_mysql_usage_checkpoint_and_new_turn_fence",
                    result["checks"]["mysql"],
                )
                for test in ["ChatTurnApiContractTest", "ChatHistoryApiContractTest"]:
                    self.assertIn(
                        "com.gmaicoson.socraticmind.chat." + test, result["checks"]["android"]
                    )
                self.assertIn("SSEContractTests", result["checks"]["ios"])
                self.assertIn("ChatTurnAPIContractTests", result["checks"]["ios"])
                self.assertTrue(result["manual"])

    def test_lifecycle_and_timeout_runner_keep_feedback_checks(self):
        for path in [
            "backend/services/chat_lifecycle.py",
            "backend/services/chat_stream_runner.py",
        ]:
            with self.subTest(path=path):
                result = load_plan(scope(path))
                self.assertIn(
                    "pytest:tests/p0/test_chat_stream_runner.py", result["checks"]["python"]
                )
                self.assertIn("pytest:tests/p0/test_chat_feedback.py", result["checks"]["python"])


if __name__ == "__main__":
    unittest.main()
