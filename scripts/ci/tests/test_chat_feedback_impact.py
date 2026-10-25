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

    def test_native_feedback_changes_select_only_its_platform_consumers(self):
        for path, lane, contract, state in [
            (
                "android/core/chat/src/main/kotlin/com/gmaicoson/socraticmind/chat/ChatAnswerFeedback.kt",
                "android",
                "com.gmaicoson.socraticmind.chat.ChatFeedbackContractTest",
                "com.gmaicoson.socraticmind.chat.ChatFeedbackStateTest",
            ),
            (
                "ios/Packages/MindCore/Sources/MindCore/Chat/ChatAnswerFeedback.swift",
                "ios",
                "ChatFeedbackContractTests",
                "ChatFeedbackStateTests",
            ),
        ]:
            with self.subTest(path=path):
                result = load_plan(scope(path))
                self.assertIn(contract, result["checks"][lane])
                self.assertIn(state, result["checks"][lane])
                self.assertFalse(result["checks"]["ios" if lane == "android" else "android"])
                self.assertFalse(result["checks"]["python"])
                self.assertFalse(result["checks"]["mysql"])

    def test_shared_fixture_selects_both_feedback_consumers(self):
        result = load_plan(scope("contracts/fixtures/chat-feedback.json"))
        self.assertIn(
            "com.gmaicoson.socraticmind.chat.ChatFeedbackContractTest", result["checks"]["android"]
        )
        self.assertIn("ChatFeedbackContractTests", result["checks"]["ios"])

    def test_number_type_reader_and_raw_http_fixture_keep_related_consumers(self):
        result = load_plan(
            scope("ios/Packages/MindCore/Sources/MindCore/Chat/ChatFeedbackJSON.swift")
        )
        for name in [
            "ChatHistoryAPIContractTests",
            "ChatTurnAPIContractTests",
            "ChatFeedbackContractTests",
        ]:
            self.assertIn(name, result["checks"]["ios"])
        self.assertFalse(result["checks"]["android"])
        self.assertFalse(result["checks"]["python"])
        wire = load_plan(scope("contracts/fixtures/chat-feedback-wire.json"))
        self.assertIn(
            "com.gmaicoson.socraticmind.chat.ChatFeedbackContractTest", wire["checks"]["android"]
        )
        self.assertIn("ChatFeedbackContractTests", wire["checks"]["ios"])
        self.assertFalse(wire["checks"]["mysql"])
        self.assertFalse(wire["checks"]["python"])


if __name__ == "__main__":
    unittest.main()
