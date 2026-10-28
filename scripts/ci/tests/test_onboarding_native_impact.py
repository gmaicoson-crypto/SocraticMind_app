"""Learning requests are platform-scoped; shared transport/scalars retain all consumers."""

import subprocess
import unittest
from unittest.mock import patch

from scripts.ci.impact import load_plan
from scripts.ci.run_checks import android_tests
from scripts.ci.tests.test_impact import scope


class OnboardingNativeImpactTests(unittest.TestCase):
    def test_native_learning_changes_stay_on_their_platform(self):
        for path, lane, expected in [
            (
                "android/core/learning/src/main/kotlin/com/gmaicoson/socraticmind/learning/OnboardingApi.kt",
                "android",
                "com.gmaicoson.socraticmind.learning.OnboardingApiContractTest",
            ),
            (
                "ios/Packages/MindCore/Sources/MindCore/Learning/OnboardingAPI.swift",
                "ios",
                "OnboardingAPIContractTests",
            ),
        ]:
            checks = load_plan(scope(path))["checks"]
            related = {
                "android": [
                    "com.gmaicoson.socraticmind.learning.FileOnboardingJournalTest",
                    "com.gmaicoson.socraticmind.learning.OnboardingControllerTest",
                ],
                "ios": ["FileOnboardingJournalTests", "OnboardingModelTests"],
            }
            self.assertEqual(sorted([expected, *related[lane]]), checks[lane])
            for other in {"python", "mysql", "android", "ios"} - {lane}:
                self.assertFalse(checks[other])

    def test_shared_native_fixture_selects_both_without_provider_tests(self):
        for path in [
            "contracts/fixtures/onboarding-wire.json",
            "scripts/contracts/onboarding_fixture.py",
        ]:
            checks = load_plan(scope(path))["checks"]
            self.assertEqual(
                [
                    "com.gmaicoson.socraticmind.learning.FileOnboardingJournalTest",
                    "com.gmaicoson.socraticmind.learning.OnboardingApiContractTest",
                    "com.gmaicoson.socraticmind.learning.OnboardingControllerTest",
                ],
                checks["android"],
            )
            self.assertEqual(
                [
                    "FileOnboardingJournalTests",
                    "OnboardingAPIContractTests",
                    "OnboardingModelTests",
                ],
                checks["ios"],
            )
            self.assertFalse(checks["python"])
            self.assertFalse(checks["mysql"])

    def test_shared_number_reader_and_provider_reach_every_consumer(self):
        checks = load_plan(
            scope("ios/Packages/MindCore/Sources/MindCore/Networking/JSONScalar.swift")
        )["checks"]
        for name in [
            "OnboardingAPIContractTests",
            "ChatFeedbackContractTests",
            "ChatHistoryAPIContractTests",
            "ChatTurnAPIContractTests",
        ]:
            self.assertIn(name, checks["ios"])
        self.assertFalse(checks["android"])
        provider = load_plan(scope("contracts/fixtures/onboarding-runs.json"))["checks"]
        self.assertIn(
            "com.gmaicoson.socraticmind.learning.OnboardingApiContractTest", provider["android"]
        )
        self.assertIn("OnboardingAPIContractTests", provider["ios"])
        self.assertTrue(provider["python"])
        self.assertTrue(provider["mysql"])

    def test_shared_storage_move_selects_chat_and_learning_without_provider(self):
        for path, lane, names in [
            (
                "android/core/storage/src/main/kotlin/com/gmaicoson/socraticmind/storage/AccountFileStorage.kt",
                "android",
                [
                    "FileChatAvatarStoreTest",
                    "FileChatTurnJournalTest",
                    "FileOnboardingJournalTest",
                    "OnboardingControllerTest",
                ],
            ),
            (
                "ios/Packages/MindCore/Sources/MindCore/Storage/AccountFileStorage.swift",
                "ios",
                [
                    "FileChatAvatarStoreTests",
                    "FileChatTurnJournalTests",
                    "FileOnboardingJournalTests",
                    "OnboardingModelTests",
                ],
            ),
        ]:
            checks = load_plan(scope(path))["checks"]
            for name in names:
                self.assertTrue(any(item.endswith(name) for item in checks[lane]))
            for other in {"python", "mysql", "android", "ios"} - {lane}:
                self.assertFalse(checks[other])

    def test_learning_runner_checks_jvm_graph_before_execution(self):
        selector = ["com.gmaicoson.socraticmind.learning.OnboardingApiContractTest"]
        for graph, allowed in [
            (
                ":core:network:jar SKIPPED\n:core:storage:jar SKIPPED\n:core:learning:test SKIPPED",
                True,
            ),
            (":core:storage:assemble SKIPPED", False),
            (":core:learning:assemble SKIPPED", False),
            (":app:assembleDebug SKIPPED", False),
            (":core:unknown:test SKIPPED", False),
        ]:
            with (
                patch(
                    "scripts.ci.run_checks.subprocess.run",
                    return_value=subprocess.CompletedProcess([], 0, stdout=graph),
                ),
                patch("scripts.ci.run_checks.run") as execute,
                patch("scripts.ci.run_checks.xml_count"),
            ):
                if allowed:
                    android_tests(selector)
                    self.assertIn(":core:learning:test", execute.call_args.args[0])
                    self.assertIn("--tests", execute.call_args.args[0])
                else:
                    with self.assertRaises(ValueError):
                        android_tests(selector)
                    execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
