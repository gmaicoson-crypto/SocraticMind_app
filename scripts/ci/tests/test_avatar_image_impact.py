"""Avatar image consumers stay explicit and never request application packaging."""

import unittest

from scripts.ci.impact import load_plan
from scripts.ci.tests.test_impact import scope


class AvatarImageImpactTests(unittest.TestCase):
    def test_image_implementations_select_cache_policy_and_state_on_the_same_platform(self):
        cases = [
            (
                "android/core/chat/src/main/kotlin/com/gmaicoson/socraticmind/chat/images/AvatarImageLoader.kt",
                "android",
                [
                    "com.gmaicoson.socraticmind.chat.AvatarImageLoaderTest",
                    "com.gmaicoson.socraticmind.chat.AvatarImagePolicyTest",
                    "com.gmaicoson.socraticmind.chat.ChatAvatarControllerTest",
                ],
            ),
            (
                "ios/Packages/MindCore/Sources/MindCore/Images/AvatarImageCodec.swift",
                "ios",
                [
                    "AvatarImageCodecTests",
                    "AvatarImageLoaderTests",
                    "ChatAvatarModelTests",
                ],
            ),
        ]
        for path, lane, expected in cases:
            with self.subTest(path=path):
                result = load_plan(scope(path))
                self.assertEqual(expected, result["checks"][lane])
                for other in {"ios", "android", "python", "mysql"} - {lane}:
                    self.assertFalse(result["checks"][other])
                self.assertTrue(any("系统照片提供方" in item for item in result["manual"]))
                with self.assertRaises(ValueError):
                    load_plan(
                        scope(
                            path.replace("AvatarImageLoader", "UnknownImage").replace(
                                "AvatarImageCodec", "UnknownImage"
                            )
                        )
                    )

    def test_system_picker_paths_are_registered_without_triggering_device_builds(self):
        for path, lane, expected in [
            (
                "android/app/src/main/java/com/gmaicoson/socraticmind/avatarui/ChatAvatarPickerDialog.kt",
                "android",
                [
                    "com.gmaicoson.socraticmind.chat.AvatarImageLoaderTest",
                    "com.gmaicoson.socraticmind.chat.AvatarImagePolicyTest",
                    "com.gmaicoson.socraticmind.chat.ChatAvatarControllerTest",
                ],
            ),
            (
                "ios/SocraticMind/Avatars/ChatAvatarPickerSheet.swift",
                "ios",
                [
                    "AvatarImageCodecTests",
                    "AvatarImageLoaderTests",
                    "ChatAvatarModelTests",
                ],
            ),
        ]:
            result = load_plan(scope(path))
            self.assertEqual(expected, result["checks"][lane])
            self.assertFalse(result["checks"]["python"])
            self.assertTrue(any("自动任务不构建" in item for item in result["manual"]))

    def test_real_webp_fixture_change_reaches_its_decoder_consumer(self):
        result = load_plan(scope("backend/assets/avatars/AI/normal/AI_normal.webp"))
        self.assertIn("AvatarImageCodecTests", result["checks"]["ios"])
        self.assertIn("pytest:tests/p0/test_avatar_presets.py", result["checks"]["python"])

    def test_avatar_state_and_delete_hook_select_their_platform_consumers(self):
        result = load_plan(
            scope("ios/Packages/MindCore/Sources/MindCore/Chat/ChatAvatarModel.swift")
        )
        self.assertEqual(
            [
                "AvatarImageCodecTests",
                "AvatarImageLoaderTests",
                "ChatAvatarModelTests",
            ],
            result["checks"]["ios"],
        )
        self.assertFalse(result["checks"]["android"])
        self.assertFalse(result["checks"]["python"])
        self.assertTrue(any("选择器" in item for item in result["manual"]))
        result = load_plan(
            scope(
                "android/core/chat/src/main/kotlin/com/gmaicoson/socraticmind/chat/ChatActionsController.kt"
            )
        )
        self.assertEqual(
            [
                "com.gmaicoson.socraticmind.chat.AvatarImageLoaderTest",
                "com.gmaicoson.socraticmind.chat.AvatarImagePolicyTest",
                "com.gmaicoson.socraticmind.chat.ChatActionsControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatAvatarControllerTest",
            ],
            result["checks"]["android"],
        )
        self.assertFalse(result["checks"]["ios"])
        self.assertFalse(result["checks"]["python"])

    def test_avatar_fixture_selects_both_adapters_and_stores_without_device_builds(self):
        result = load_plan(scope("contracts/fixtures/chat-avatar.json"))
        self.assertEqual(
            [
                "AvatarImageCodecTests",
                "AvatarImageLoaderTests",
                "ChatAvatarAPIContractTests",
                "ChatAvatarModelTests",
                "FileChatAvatarStoreTests",
            ],
            result["checks"]["ios"],
        )
        self.assertEqual(
            [
                "com.gmaicoson.socraticmind.chat.AvatarImageLoaderTest",
                "com.gmaicoson.socraticmind.chat.AvatarImagePolicyTest",
                "com.gmaicoson.socraticmind.chat.ChatAvatarApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatAvatarControllerTest",
                "com.gmaicoson.socraticmind.chat.FileChatAvatarStoreTest",
            ],
            result["checks"]["android"],
        )
        self.assertIn("pytest:tests/p0/test_chat_avatars.py", result["checks"]["python"])
        self.assertTrue(result["schema"])
        self.assertFalse(result["checks"]["mysql"])

    def test_shared_account_io_covers_recovery_and_avatar_but_store_is_platform_scoped(self):
        result = load_plan(
            scope(
                "android/core/chat/src/main/kotlin/com/gmaicoson/socraticmind/chat/AccountFileStorage.kt"
            )
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
                "com.gmaicoson.socraticmind.chat.ChatSuggestionsControllerTest",
                "com.gmaicoson.socraticmind.chat.ChatTurnControllerTest",
                "com.gmaicoson.socraticmind.chat.FileChatAvatarStoreTest",
                "com.gmaicoson.socraticmind.chat.FileChatTurnJournalTest",
            ],
            result["checks"]["android"],
        )
        self.assertFalse(result["checks"]["ios"])
        self.assertFalse(result["checks"]["python"])
        result = load_plan(
            scope("ios/Packages/MindCore/Sources/MindCore/Chat/FileChatAvatarStore.swift")
        )
        self.assertEqual(
            [
                "AvatarImageCodecTests",
                "AvatarImageLoaderTests",
                "ChatAvatarModelTests",
                "FileChatAvatarStoreTests",
            ],
            result["checks"]["ios"],
        )
        self.assertFalse(result["checks"]["android"])
        self.assertFalse(result["checks"]["python"])
        self.assertTrue(result["manual"])
