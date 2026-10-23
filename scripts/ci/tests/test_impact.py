import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from scripts.ci.check_structure import inspect_text
from scripts.ci.github_scope import event_scope, sha
from scripts.ci.impact import load_plan, plan
from scripts.ci.run_checks import android_tests, xml_count
from scripts.quality.changed_files import ROOT


def scope(*files, initial=False):
    return {
        "base": None if initial else "a" * 40,
        "head": "worktree",
        "initial": initial,
        "files": list(files),
    }


class ImpactTests(unittest.TestCase):
    def test_document_change_runs_no_business_suite(self):
        result = load_plan(scope("docs/delivery-plan.md"))
        self.assertTrue(all(not items for items in result["checks"].values()))

    def test_parser_change_expands_only_affected_platform_consumer(self):
        value = (
            "android/core/network/src/main/kotlin/com/gmaicoson/socraticmind/network/SseDecoder.kt"
        )
        result = load_plan(scope(value))
        self.assertEqual(8, len(result["checks"]["android"]))
        self.assertFalse(result["checks"]["ios"])
        self.assertFalse(result["checks"]["python"])
        self.assertEqual([value], result["files"]["android"])

    def test_wire_protocol_change_expands_provider_and_both_consumers(self):
        result = load_plan(scope("contracts/fixtures/chat-streams.json"))
        for lane in ("python", "android", "ios"):
            self.assertTrue(result["checks"][lane])
        self.assertFalse(result["checks"]["mysql"])

    def test_auth_contract_selects_only_auth_provider_and_consumers(self):
        result = load_plan(scope("contracts/fixtures/auth.json"))
        self.assertEqual(
            ["pytest:tests/contracts/test_auth_contract.py"], result["checks"]["python"]
        )
        self.assertEqual(
            [
                "com.gmaicoson.socraticmind.auth.AuthApiContractTest",
                "com.gmaicoson.socraticmind.auth.AuthFormControllerTest",
                "com.gmaicoson.socraticmind.auth.EncryptedTokenVaultTest",
                "com.gmaicoson.socraticmind.auth.SessionStoreTest",
                "com.gmaicoson.socraticmind.chat.ChatLibraryControllerTest",
            ],
            result["checks"]["android"],
        )
        self.assertEqual(
            [
                "AuthAPIContractTests",
                "AuthFormModelTests",
                "ChatLibraryModelTests",
                "KeychainTokenVaultTests",
                "SessionStoreTests",
            ],
            result["checks"]["ios"],
        )
        self.assertFalse(result["checks"]["mysql"])

    def test_new_auth_logic_requires_its_own_test_mapping(self):
        with self.assertRaises(ValueError):
            load_plan(
                scope(
                    "android/core/auth/src/main/kotlin/com/gmaicoson/socraticmind/auth/UnknownFeature.kt"
                )
            )

    def test_history_provider_selects_both_consumers_and_mysql_projection(self):
        result = load_plan(scope("backend/services/chat_history.py"))
        self.assertIn(
            "pytest:tests/contracts/test_chat_history_contract.py", result["checks"]["python"]
        )
        self.assertEqual(
            [
                "com.gmaicoson.socraticmind.auth.SessionStoreTest",
                "com.gmaicoson.socraticmind.chat.ChatHistoryApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatLibraryControllerTest",
            ],
            result["checks"]["android"],
        )
        self.assertEqual(
            ["ChatHistoryAPIContractTests", "ChatLibraryModelTests", "SessionStoreTests"],
            result["checks"]["ios"],
        )
        self.assertEqual(
            [
                "pytest:tests/integration/test_mysql_chat_history.py::test_mysql_history_window_and_unicode_projection"
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
                "com.gmaicoson.socraticmind.chat.ChatHistoryApiContractTest",
                "com.gmaicoson.socraticmind.chat.ChatLibraryControllerTest",
            ],
            result["checks"]["android"],
        )
        self.assertFalse(result["checks"]["ios"])
        self.assertFalse(result["checks"]["python"])
        with self.assertRaises(ValueError):
            load_plan(scope(value.replace("ChatHistoryApi", "UnknownFeature")))

    def test_chat_runner_allows_only_registered_jvm_graph_without_packaging(self):
        selected = ["com.gmaicoson.socraticmind.chat.ChatHistoryApiContractTest"]
        for graph, allowed in [
            (":core:network:jar SKIPPED\n:core:chat:test SKIPPED", True),
            (":app:assembleDebug SKIPPED\n:core:chat:test SKIPPED", False),
            (":core:chat:packageDebug SKIPPED\n:core:chat:test SKIPPED", False),
        ]:
            result = subprocess.CompletedProcess([], 0, stdout=graph)
            with (
                patch("scripts.ci.run_checks.subprocess.run", return_value=result),
                patch("scripts.ci.run_checks.run") as execute,
                patch("scripts.ci.run_checks.xml_count"),
            ):
                if allowed:
                    android_tests(selected)
                    self.assertIn(":core:chat:test", execute.call_args.args[0])
                    self.assertIn("--tests", execute.call_args.args[0])
                else:
                    with self.assertRaises(ValueError):
                        android_tests(selected)
                    execute.assert_not_called()

    def test_form_fixture_selects_both_forms_without_server_or_storage_suites(self):
        result = load_plan(scope("contracts/fixtures/auth-form.json"))
        self.assertEqual(
            ["com.gmaicoson.socraticmind.auth.AuthFormControllerTest"], result["checks"]["android"]
        )
        self.assertEqual(["AuthFormModelTests"], result["checks"]["ios"])
        self.assertFalse(result["checks"]["python"])

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
                "ChatLibraryModelTests",
                "MarkdownContractTests",
                "MarkdownRendererTests",
                "SessionStoreTests",
            ],
            result["checks"]["ios"],
        )
        self.assertFalse(result["checks"]["android"])
        self.assertTrue(any("代码复制" in item for item in result["manual"]))

    def test_swift_lock_files_expand_registered_consumers_and_pin_consistency(self):
        for value in [
            "ios/Packages/MindCore/Package.resolved",
            "ios/SocraticMind.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved",
        ]:
            result = load_plan(scope(value))
            self.assertEqual(10, len(result["checks"]["ios"]))
            self.assertIn("MarkdownContractTests", result["checks"]["ios"])
            self.assertEqual(
                ["unittest:scripts.ci.tests.test_package_resolution"], result["checks"]["python"]
            )
            self.assertFalse(result["checks"]["android"])

    def test_native_network_config_selects_configuration_guard_and_keeps_device_gap(self):
        result = load_plan(scope("android/app/src/debug/res/xml/network_security_config.xml"))
        self.assertEqual(
            ["unittest:scripts.ci.tests.test_native_configuration"], result["checks"]["python"]
        )
        self.assertTrue(result["manual"])

    def test_native_ui_tests_remain_explicit_and_do_not_enter_default_build_lanes(self):
        result = load_plan(
            scope(
                "ios/UITests/AuthFlowTests.swift",
                "android/uitests/src/main/kotlin/com/gmaicoson/socraticmind/uitests/AuthFlowTest.kt",
            )
        )
        self.assertEqual(
            ["unittest:scripts.dev.tests.test_auth_ui_fixture"], result["checks"]["python"]
        )
        self.assertFalse(result["checks"]["android"])
        self.assertFalse(result["checks"]["ios"])
        self.assertTrue(any("明确获准构建" in item for item in result["manual"]))

    def test_storage_change_selects_same_platform_session_without_provider_tests(self):
        result = load_plan(
            scope("ios/Packages/MindCore/Sources/MindCore/Authentication/KeychainTokenVault.swift")
        )
        self.assertEqual(
            ["ChatLibraryModelTests", "KeychainTokenVaultTests", "SessionStoreTests"],
            result["checks"]["ios"],
        )
        self.assertFalse(result["checks"]["android"])
        self.assertFalse(result["checks"]["python"])
        self.assertTrue(any("Keychain" in value for value in result["manual"]))

    def test_android_adapter_selects_crypto_and_session_and_keeps_device_gap_visible(self):
        result = load_plan(
            scope(
                "android/app/src/main/java/com/gmaicoson/socraticmind/storage/KeystoreTokenVault.kt"
            )
        )
        self.assertEqual(
            [
                "com.gmaicoson.socraticmind.auth.EncryptedTokenVaultTest",
                "com.gmaicoson.socraticmind.auth.SessionStoreTest",
                "com.gmaicoson.socraticmind.chat.ChatLibraryControllerTest",
            ],
            result["checks"]["android"],
        )
        self.assertFalse(result["checks"]["ios"])
        self.assertTrue(any("AndroidKeyStore" in value for value in result["manual"]))

    def test_history_state_selects_only_its_account_dependency_and_keeps_ui_gap(self):
        result = load_plan(
            scope("ios/Packages/MindCore/Sources/MindCore/Chat/ChatLibraryModel.swift")
        )
        self.assertEqual(["ChatLibraryModelTests", "SessionStoreTests"], result["checks"]["ios"])
        self.assertFalse(result["checks"]["android"])
        self.assertFalse(result["checks"]["python"])
        self.assertFalse(result["checks"]["mysql"])
        self.assertTrue(any("滚动" in item for item in result["manual"]))

    def test_account_container_covers_both_form_and_history_state(self):
        result = load_plan(
            scope("android/app/src/main/java/com/gmaicoson/socraticmind/account/AppViewModel.kt")
        )
        self.assertEqual(
            [
                "com.gmaicoson.socraticmind.auth.AuthFormControllerTest",
                "com.gmaicoson.socraticmind.auth.SessionStoreTest",
                "com.gmaicoson.socraticmind.chat.ChatLibraryControllerTest",
            ],
            result["checks"]["android"],
        )
        self.assertFalse(result["checks"]["ios"])

    def test_unknown_business_change_fails_instead_of_full_suite_or_noop(self):
        with self.assertRaisesRegex(ValueError, "Add affected test selectors"):
            load_plan(scope("backend/services/not_mapped.py"))

    def test_import_cohort_is_only_available_for_initial_source_paths(self):
        imported = "backend/services/mastery.py"
        self.assertIn("import-baseline", load_plan(scope(imported, initial=True))["groups"])
        with self.assertRaises(ValueError):
            load_plan(scope(imported))
        with self.assertRaises(ValueError):
            load_plan(scope("backend/services/new_business.py", initial=True))

    def test_deleted_source_keeps_mapping_and_rename_requires_new_path_mapping(self):
        old = "android/core/network/src/main/kotlin/com/gmaicoson/socraticmind/network/HttpTransport.kt"
        self.assertTrue(load_plan(scope(old))["checks"]["android"])
        with self.assertRaises(ValueError):
            load_plan(scope(old, old.replace("HttpTransport.kt", "NewTransport.kt")))

    def test_dependencies_and_paths_cannot_silently_escape(self):
        bad = {
            "groups": {"invalid": {"paths": ["x.py"], "depends_on": ["missing"]}},
            "metadata": [],
        }
        with self.assertRaises(ValueError):
            plan(scope("x.py"), bad, set())
        with self.assertRaises(ValueError):
            load_plan(scope("../outside.py"))

    def test_formatter_config_expands_code_and_records_why(self):
        result = load_plan(scope("ios/.swiftformat"))
        self.assertGreater(len(result["files"]["ios"]), 1)
        self.assertIn("ios/.swiftformat", result["format_expansion"])
        self.assertFalse(result["files"]["android"])

    def test_current_workflow_scripts_have_no_unmapped_test_gap(self):
        files = [str(path.relative_to(ROOT)) for path in (ROOT / "scripts/ci").rglob("*.py")]
        result = load_plan(scope(*files))
        self.assertIn("unittest:scripts.ci.tests.test_impact", result["checks"]["python"])

    def test_zero_skipped_and_failed_reports_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "results.xml"
            for content in [
                "<testsuite/>",
                "<testsuite><testcase><skipped/></testcase></testsuite>",
                "<testsuite><testcase><failure/></testcase></testsuite>",
            ]:
                path.write_text(content)
                with self.assertRaises(ValueError):
                    xml_count([path])
            path.write_text(
                "<testsuites><testsuite><testcase name='ran'/></testsuite></testsuites>"
            )
            self.assertEqual(1, xml_count([path]))

    def test_text_structure_rejects_broken_links_and_trailing_space(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            file = root / "guide.md"
            for content in ["[missing](absent.md)\n", "text \n", "text\r\n", "text\n\n"]:
                file.write_bytes(content.encode())
                with self.assertRaises(ValueError):
                    inspect_text(root, "guide.md")
            file.write_text("[self](guide.md)\n")
            inspect_text(root, "guide.md")

    def test_swift_report_must_cover_every_selected_suite_or_method(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result-swift-testing.xml"
            path.write_text(
                '<testsuite><testcase classname="MindCoreTests.HTTPTests" name="request()"/></testsuite>'
            )
            self.assertEqual(1, xml_count([path], ["HTTPTests/request"]))
            with self.assertRaises(ValueError):
                xml_count([path], ["HTTPTests", "MissingTests"])
            with self.assertRaises(ValueError):
                xml_count([path], ["HTTPTests/absent"])


class GithubScopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-b", "test/gy/ci")
        self.git("config", "user.name", "CI Scope Test")
        self.git("config", "user.email", "ci-scope@example.test")

    def git(self, *args):
        return (
            subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )

    def commit(self, name):
        (self.root / name).write_text("fixture\n")
        self.git("add", name)
        self.git("commit", "-m", "test: 创建 CI 范围样例")
        return self.git("rev-parse", "HEAD")

    def test_initial_push_and_following_push_use_event_endpoints(self):
        base = self.commit("base.md")
        result = event_scope(self.root, "push", {"before": "0" * 40, "after": base})
        self.assertEqual(["base.md"], result["files"])
        head = self.commit("feature.py")
        result = event_scope(self.root, "push", {"before": base, "after": head})
        self.assertEqual(["feature.py"], result["files"])

    def test_pr_uses_merge_base_not_new_changes_on_base_branch(self):
        ancestor = self.commit("ancestor.md")
        self.git("checkout", "-b", "test/gy/feature")
        head = self.commit("feature.py")
        self.git("checkout", "test/gy/ci")
        base = self.commit("unrelated.py")
        event = {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}
        result = event_scope(self.root, "pull_request", event)
        self.assertEqual(ancestor, result["base"])
        self.assertEqual(["feature.py"], result["files"])

    def test_bad_sha_deleted_branch_and_unknown_event_fail(self):
        for value in ["HEAD", "a; echo unsafe", "--help", "a" * 39, None]:
            with self.assertRaises(ValueError):
                sha(value)
        with self.assertRaises(ValueError):
            event_scope(self.root, "push", {"before": "a" * 40, "after": "0" * 40})
        with self.assertRaises(ValueError):
            event_scope(self.root, "pull_request_target", {})


if __name__ == "__main__":
    unittest.main()
