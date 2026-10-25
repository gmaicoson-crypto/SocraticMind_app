"""Model directory and selection changes keep provider and sending consumers explicit."""

import unittest

from scripts.ci.impact import load_plan
from scripts.ci.tests.test_impact import scope


class ModelSelectionImpactTests(unittest.TestCase):
    def test_model_contract_changes_select_provider_turns_suggestions_and_schema(self):
        for path in [
            "backend/routers/llm.py",
            "backend/core/ai_client.py",
            "backend/core/user_llm.py",
            "backend/tests/contracts/test_model_selection_contract.py",
            "contracts/fixtures/model-selection.json",
        ]:
            with self.subTest(path=path):
                result = load_plan(scope(path))
                self.assertIn("model-provider", result["groups"])
                self.assertIn("turn-provider", result["groups"])
                self.assertIn("suggestions-provider", result["groups"])
                self.assertIn(
                    "pytest:tests/contracts/test_model_selection_contract.py",
                    result["checks"]["python"],
                )
                self.assertIn(
                    "com.gmaicoson.socraticmind.chat.ChatTurnApiContractTest",
                    result["checks"]["android"],
                )
                self.assertIn("ChatSuggestionsAPIContractTests", result["checks"]["ios"])
                self.assertTrue(result["schema"])
                self.assertFalse(result["checks"]["mysql"])

    def test_extracted_request_schema_keeps_stream_and_regeneration_consumers(self):
        result = load_plan(scope("backend/schemas/chat_request.py"))
        self.assertIn("chat-provider", result["groups"])
        self.assertIn("model-provider", result["groups"])
        self.assertIn("ChatRegenerationContextTests", result["checks"]["ios"])
        self.assertIn(
            "com.gmaicoson.socraticmind.chat.ChatRegenerationContextTest",
            result["checks"]["android"],
        )
        self.assertTrue(result["manual"])

    def test_unknown_model_source_does_not_silently_skip(self):
        with self.assertRaises(ValueError):
            load_plan(scope("backend/services/unknown_model_selection.py"))


if __name__ == "__main__":
    unittest.main()
