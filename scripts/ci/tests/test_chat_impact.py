"""Chat feature impact contracts: history, turns, suggestions, actions and rendering."""

import unittest

from scripts.ci.impact import load_plan
from scripts.ci.tests.test_impact import scope


class ChatImpactTests(unittest.TestCase):
    def test_regeneration_context_inputs_select_existing_wire_consumers(self):
        for path in [
            "backend/services/chat_regeneration.py",
            "backend/tests/contracts/test_chat_regeneration_context.py",
            "contracts/fixtures/chat-regeneration-contexts.json",
        ]:
            result = load_plan(scope(path))
            self.assertIn("ChatTurnAPIContractTests", result["checks"]["ios"])
            self.assertIn("ChatRegenerationContextTests", result["checks"]["ios"])
            self.assertIn(
                "com.gmaicoson.socraticmind.chat.ChatRegenerationContextTest",
                result["checks"]["android"],
            )
            self.assertIn(
                "com.gmaicoson.socraticmind.chat.ChatTurnApiContractTest",
                result["checks"]["android"],
            )
            self.assertIn(
                "pytest:tests/contracts/test_chat_regeneration_context.py",
                result["checks"]["python"],
            )
            self.assertFalse(result["checks"]["mysql"])

    def test_native_context_selects_its_state_and_keeps_other_platform_out(self):
        for platform, path, selector in [
            (
                "android",
                "android/core/chat/src/main/kotlin/com/gmaicoson/socraticmind/chat/ChatRequestContext.kt",
                "com.gmaicoson.socraticmind.chat.ChatRegenerationContextTest",
            ),
            (
                "ios",
                "ios/Packages/MindCore/Sources/MindCore/Chat/ChatRequestContext.swift",
                "ChatRegenerationContextTests",
            ),
        ]:
            result = load_plan(scope(path))
            self.assertIn(selector, result["checks"][platform])
            self.assertFalse(result["checks"]["ios" if platform == "android" else "android"])

    def test_suggestion_contract_and_state_keep_exact_consumers(self):
        result = load_plan(scope("contracts/fixtures/chat-suggestions.json"))
        self.assertEqual(
            [
                "ChatModelSendTests",
                "ChatSuggestionsAPIContractTests",
                "ChatSuggestionsModelTests",
            ],
            result["checks"]["ios"],
        )
        self.assertEqual(
            [
                "com.gmaicoson.socraticmind.chat.ChatModelSendTest",
                "com.gmaicoson.socraticmind.chat.ChatSuggestionsApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatSuggestionsControllerTest",
            ],
            result["checks"]["android"],
        )
        self.assertIn("pytest:tests/p0/test_chat_suggestions.py", result["checks"]["python"])
        self.assertTrue(result["schema"])
        self.assertFalse(result["checks"]["mysql"])
        result = load_plan(
            scope("ios/Packages/MindCore/Sources/MindCore/Chat/ChatSuggestionsModel.swift")
        )
        self.assertEqual(
            [
                "ChatModelSendTests",
                "ChatSuggestionsModelTests",
            ],
            result["checks"]["ios"],
        )
        self.assertFalse(result["checks"]["android"])
        self.assertFalse(result["checks"]["python"])
        self.assertTrue(result["manual"])

    def test_title_reads_keep_visibility_checks_and_platform_scope(self):
        result = load_plan(
            scope("ios/Packages/MindCore/Sources/MindCore/Chat/ChatTitleRefresh.swift")
        )
        self.assertIn("ChatTitleRefreshTests", result["checks"]["ios"])
        self.assertIn("ChatActionsModelTests", result["checks"]["ios"])
        self.assertFalse(result["checks"]["android"])
        self.assertFalse(result["checks"]["mysql"])
        self.assertFalse(result["checks"]["python"])
        self.assertTrue(any("100" in item and "8" in item for item in result["manual"]))

    def test_actions_state_is_platform_scoped_and_extracted_views_keep_consumers(self):
        result = load_plan(
            scope(
                "android/core/chat/src/main/kotlin/com/gmaicoson/socraticmind/chat/ChatActionsState.kt"
            )
        )
        self.assertEqual(
            [
                "com.gmaicoson.socraticmind.auth.SessionStoreTest",
                "com.gmaicoson.socraticmind.chat.AvatarImageLoaderTest",
                "com.gmaicoson.socraticmind.chat.AvatarImagePolicyTest",
                "com.gmaicoson.socraticmind.chat.ChatActionsControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatAvatarControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatLibraryControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatModelControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatModelSendTest",
                "com.gmaicoson.socraticmind.chat.ChatRegenerationContextTest",
                "com.gmaicoson.socraticmind.chat.ChatRegenerationTest",
                "com.gmaicoson.socraticmind.chat.ChatSuggestionsControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatTitleRefreshTest",
                "com.gmaicoson.socraticmind.chat.ChatTurnControllerTest",
                "com.gmaicoson.socraticmind.chat.FileChatTurnJournalTest",
            ],
            result["checks"]["android"],
        )
        self.assertFalse(result["checks"]["ios"])
        self.assertFalse(result["checks"]["python"])
        result = load_plan(scope("ios/SocraticMind/Chat/MessageHistoryView.swift"))
        self.assertIn("ChatActionsModelTests", result["checks"]["ios"])
        self.assertIn("ChatLibraryModelTests", result["checks"]["ios"])
        self.assertIn("MarkdownRendererTests", result["checks"]["ios"])
        self.assertFalse(result["checks"]["android"])

    def test_actions_contract_selects_provider_both_consumers_and_schema(self):
        result = load_plan(scope("contracts/fixtures/chat-actions.json"))
        self.assertEqual(
            [
                "com.gmaicoson.socraticmind.auth.SessionStoreTest",
                "com.gmaicoson.socraticmind.chat.AvatarImageLoaderTest",
                "com.gmaicoson.socraticmind.chat.AvatarImagePolicyTest",
                "com.gmaicoson.socraticmind.chat.ChatActionsApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatActionsControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatAvatarControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatLibraryControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatModelControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatModelSendTest",
                "com.gmaicoson.socraticmind.chat.ChatRegenerationContextTest",
                "com.gmaicoson.socraticmind.chat.ChatRegenerationTest",
                "com.gmaicoson.socraticmind.chat.ChatSuggestionsControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatTitleRefreshTest",
                "com.gmaicoson.socraticmind.chat.ChatTurnControllerTest",
                "com.gmaicoson.socraticmind.chat.FileChatTurnJournalTest",
            ],
            result["checks"]["android"],
        )
        self.assertEqual(
            [
                "AvatarImageCodecTests",
                "AvatarImageLoaderTests",
                "ChatActionsAPIContractTests",
                "ChatActionsModelTests",
                "ChatAvatarModelTests",
                "ChatLibraryModelTests",
                "ChatModelSelectionModelTests",
                "ChatModelSendTests",
                "ChatRegenerationContextTests",
                "ChatRegenerationTests",
                "ChatSuggestionsModelTests",
                "ChatTitleRefreshTests",
                "ChatTurnModelTests",
                "FileChatTurnJournalTests",
                "SessionStoreTests",
            ],
            result["checks"]["ios"],
        )
        self.assertIn(
            "pytest:tests/contracts/test_chat_actions_contract.py", result["checks"]["python"]
        )
        self.assertIn("pytest:tests/contracts/test_openapi_contract.py", result["checks"]["python"])
        self.assertFalse(result["checks"]["mysql"])

    def test_turn_fixture_selects_provider_and_exact_native_consumers(self):
        result = load_plan(scope("contracts/fixtures/chat-turns.json"))
        self.assertIn(
            "pytest:tests/contracts/test_chat_turn_contract.py", result["checks"]["python"]
        )
        self.assertEqual(
            [
                "com.gmaicoson.socraticmind.chat.AvatarImageLoaderTest",
                "com.gmaicoson.socraticmind.chat.AvatarImagePolicyTest",
                "com.gmaicoson.socraticmind.chat.ChatActionsControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatAvatarControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatLibraryControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatModelControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatModelSendTest",
                "com.gmaicoson.socraticmind.chat.ChatRegenerationContextTest",
                "com.gmaicoson.socraticmind.chat.ChatRegenerationTest",
                "com.gmaicoson.socraticmind.chat.ChatSuggestionsApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatSuggestionsControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatTurnApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatTurnControllerTest",
                "com.gmaicoson.socraticmind.chat.FileChatTurnJournalTest",
            ],
            result["checks"]["android"],
        )
        self.assertEqual(
            [
                "AvatarImageCodecTests",
                "AvatarImageLoaderTests",
                "ChatActionsModelTests",
                "ChatAvatarModelTests",
                "ChatLibraryModelTests",
                "ChatModelSelectionModelTests",
                "ChatModelSendTests",
                "ChatRegenerationContextTests",
                "ChatRegenerationTests",
                "ChatSuggestionsAPIContractTests",
                "ChatSuggestionsModelTests",
                "ChatTurnAPIContractTests",
                "ChatTurnModelTests",
                "FileChatTurnJournalTests",
            ],
            result["checks"]["ios"],
        )
        self.assertFalse(result["checks"]["mysql"])

    def test_turn_controller_is_platform_scoped_and_unknown_files_fail(self):
        path = "android/core/chat/src/main/kotlin/com/gmaicoson/socraticmind/chat/ChatTurnController.kt"
        result = load_plan(scope(path))
        self.assertEqual(
            [
                "com.gmaicoson.socraticmind.chat.AvatarImageLoaderTest",
                "com.gmaicoson.socraticmind.chat.AvatarImagePolicyTest",
                "com.gmaicoson.socraticmind.chat.ChatActionsControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatAvatarControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatLibraryControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatModelControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatModelSendTest",
                "com.gmaicoson.socraticmind.chat.ChatRegenerationContextTest",
                "com.gmaicoson.socraticmind.chat.ChatRegenerationTest",
                "com.gmaicoson.socraticmind.chat.ChatSuggestionsControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatTurnControllerTest",
                "com.gmaicoson.socraticmind.chat.FileChatTurnJournalTest",
            ],
            result["checks"]["android"],
        )
        self.assertFalse(result["checks"]["ios"])
        self.assertFalse(result["checks"]["python"])
        self.assertTrue(any("进程终止" in text for text in result["manual"]))
        with self.assertRaises(ValueError):
            load_plan(scope(path.replace("ChatTurnController", "UnknownTurnLogic")))

    def test_journal_and_composer_keep_device_work_out_of_automatic_lanes(self):
        for path in [
            "ios/Packages/MindCore/Sources/MindCore/Chat/FileChatTurnJournal.swift",
            "ios/SocraticMind/Chat/ChatComposerView.swift",
        ]:
            result = load_plan(scope(path))
            self.assertEqual(
                [
                    "AvatarImageCodecTests",
                    "AvatarImageLoaderTests",
                    "ChatActionsModelTests",
                    "ChatAvatarModelTests",
                    "ChatLibraryModelTests",
                    "ChatModelSelectionModelTests",
                    "ChatModelSendTests",
                    "ChatRegenerationContextTests",
                    "ChatRegenerationTests",
                    "ChatSuggestionsModelTests",
                    "ChatTurnModelTests",
                    "FileChatTurnJournalTests",
                ],
                result["checks"]["ios"],
            )
            self.assertFalse(result["checks"]["android"])
            self.assertTrue(any("文件保护" in text for text in result["manual"]))

    def test_history_provider_selects_both_consumers_and_mysql_projection(self):
        result = load_plan(scope("backend/services/chat_history.py"))
        self.assertIn(
            "pytest:tests/contracts/test_chat_history_contract.py", result["checks"]["python"]
        )
        self.assertEqual(
            [
                "com.gmaicoson.socraticmind.auth.AuthApiContractTest",
                "com.gmaicoson.socraticmind.auth.AuthFormControllerTest",
                "com.gmaicoson.socraticmind.auth.EncryptedTokenVaultTest",
                "com.gmaicoson.socraticmind.auth.SessionStoreTest",
                "com.gmaicoson.socraticmind.chat.AvatarImageLoaderTest",
                "com.gmaicoson.socraticmind.chat.AvatarImagePolicyTest",
                "com.gmaicoson.socraticmind.chat.ChatActionsApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatActionsControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatAvatarApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatAvatarControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatHistoryApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatLibraryControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatModelApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatModelControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatModelSendTest",
                "com.gmaicoson.socraticmind.chat.ChatRegenerationContextTest",
                "com.gmaicoson.socraticmind.chat.ChatRegenerationTest",
                "com.gmaicoson.socraticmind.chat.ChatSuggestionsApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatSuggestionsControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatTitleRefreshTest",
                "com.gmaicoson.socraticmind.chat.ChatTurnApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatTurnControllerTest",
                "com.gmaicoson.socraticmind.chat.FileChatAvatarStoreTest",
                "com.gmaicoson.socraticmind.chat.FileChatTurnJournalTest",
                "com.gmaicoson.socraticmind.network.HttpTransportTest",
                "com.gmaicoson.socraticmind.network.SseContractTest",
            ],
            result["checks"]["android"],
        )
        self.assertEqual(
            [
                "AuthAPIContractTests",
                "AuthFormModelTests",
                "AvatarImageCodecTests",
                "AvatarImageLoaderTests",
                "ChatActionsAPIContractTests",
                "ChatActionsModelTests",
                "ChatAvatarAPIContractTests",
                "ChatAvatarModelTests",
                "ChatHistoryAPIContractTests",
                "ChatLibraryModelTests",
                "ChatModelAPIContractTests",
                "ChatModelSelectionModelTests",
                "ChatModelSendTests",
                "ChatRegenerationContextTests",
                "ChatRegenerationTests",
                "ChatSuggestionsAPIContractTests",
                "ChatSuggestionsModelTests",
                "ChatTitleRefreshTests",
                "ChatTurnAPIContractTests",
                "ChatTurnModelTests",
                "FileChatAvatarStoreTests",
                "FileChatTurnJournalTests",
                "HTTPTransportTests",
                "KeychainTokenVaultTests",
                "SSEContractTests",
                "SessionStoreTests",
            ],
            result["checks"]["ios"],
        )
        self.assertEqual(
            [
                "pytest:tests/integration/test_mysql_chat_feedback.py::test_mysql_usage_checkpoint_and_new_turn_fence",
                "pytest:tests/integration/test_mysql_chat_history.py::test_mysql_history_window_and_unicode_projection",
            ],
            result["checks"]["mysql"],
        )
        self.assertTrue(result["schema"])

    def test_history_adapter_selects_only_its_platform_and_unknown_features_fail(self):
        value = (
            "android/core/chat/src/main/kotlin/com/gmaicoson/socraticmind/chat/ChatHistoryApi.kt"
        )
        result = load_plan(scope(value))
        self.assertEqual(
            [
                "com.gmaicoson.socraticmind.auth.SessionStoreTest",
                "com.gmaicoson.socraticmind.chat.AvatarImageLoaderTest",
                "com.gmaicoson.socraticmind.chat.AvatarImagePolicyTest",
                "com.gmaicoson.socraticmind.chat.ChatActionsApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatActionsControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatAvatarApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatAvatarControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatHistoryApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatLibraryControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatModelControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatModelSendTest",
                "com.gmaicoson.socraticmind.chat.ChatRegenerationContextTest",
                "com.gmaicoson.socraticmind.chat.ChatRegenerationTest",
                "com.gmaicoson.socraticmind.chat.ChatSuggestionsApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatSuggestionsControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatTitleRefreshTest",
                "com.gmaicoson.socraticmind.chat.ChatTurnApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatTurnControllerTest",
                "com.gmaicoson.socraticmind.chat.FileChatAvatarStoreTest",
                "com.gmaicoson.socraticmind.chat.FileChatTurnJournalTest",
            ],
            result["checks"]["android"],
        )
        self.assertFalse(result["checks"]["ios"])
        self.assertFalse(result["checks"]["python"])
        with self.assertRaises(ValueError):
            load_plan(scope(value.replace("ChatHistoryApi", "UnknownFeature")))

    def test_markdown_fixture_selects_exactly_both_rendering_cores(self):
        result = load_plan(scope("contracts/fixtures/message-markdown.json"))
        self.assertEqual(
            [
                "com.gmaicoson.socraticmind.chat.MarkdownContractTest",
                "com.gmaicoson.socraticmind.chat.MarkdownRendererTest",
            ],
            result["checks"]["android"],
        )
        self.assertEqual(
            ["MarkdownContractTests", "MarkdownRendererTests"], result["checks"]["ios"]
        )
        self.assertFalse(result["checks"]["python"])
        self.assertFalse(result["checks"]["mysql"])
        self.assertFalse(result["schema"])

    def test_markdown_logic_stays_platform_scoped_and_unknown_files_fail(self):
        value = "ios/Packages/MindCore/Sources/MindCore/Chat/Markdown/MarkdownParser.swift"
        result = load_plan(scope(value))
        self.assertEqual(
            ["MarkdownContractTests", "MarkdownRendererTests"], result["checks"]["ios"]
        )
        self.assertFalse(result["checks"]["android"])
        self.assertFalse(result["checks"]["python"])
        with self.assertRaises(ValueError):
            load_plan(scope(value.replace("MarkdownParser", "UnknownLogic")))

    def test_history_page_change_includes_its_renderer_and_account_state(self):
        result = load_plan(scope("ios/SocraticMind/Chat/ChatLibraryView.swift"))
        self.assertEqual(
            [
                "AvatarImageCodecTests",
                "AvatarImageLoaderTests",
                "ChatActionsModelTests",
                "ChatAvatarModelTests",
                "ChatLibraryModelTests",
                "ChatModelSelectionModelTests",
                "ChatModelSendTests",
                "ChatRegenerationContextTests",
                "ChatRegenerationTests",
                "ChatSuggestionsModelTests",
                "ChatTitleRefreshTests",
                "ChatTurnModelTests",
                "FileChatTurnJournalTests",
                "MarkdownContractTests",
                "MarkdownRendererTests",
                "SessionStoreTests",
            ],
            result["checks"]["ios"],
        )
        self.assertFalse(result["checks"]["android"])
        self.assertTrue(any("代码复制" in item for item in result["manual"]))

    def test_history_state_selects_only_its_account_dependency_and_keeps_ui_gap(self):
        result = load_plan(
            scope("ios/Packages/MindCore/Sources/MindCore/Chat/ChatLibraryModel.swift")
        )
        self.assertEqual(
            [
                "AvatarImageCodecTests",
                "AvatarImageLoaderTests",
                "ChatActionsModelTests",
                "ChatAvatarModelTests",
                "ChatLibraryModelTests",
                "ChatModelSelectionModelTests",
                "ChatModelSendTests",
                "ChatRegenerationContextTests",
                "ChatRegenerationTests",
                "ChatSuggestionsModelTests",
                "ChatTitleRefreshTests",
                "ChatTurnModelTests",
                "FileChatTurnJournalTests",
                "SessionStoreTests",
            ],
            result["checks"]["ios"],
        )
        self.assertFalse(result["checks"]["android"])
        self.assertFalse(result["checks"]["python"])
        self.assertFalse(result["checks"]["mysql"])
        self.assertTrue(any("滚动" in item for item in result["manual"]))


if __name__ == "__main__":
    unittest.main()
