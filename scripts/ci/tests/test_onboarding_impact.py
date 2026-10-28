"""The shared run store affects onboarding, assessments and legacy message consumers."""

import unittest

from scripts.ci.impact import load_plan
from scripts.ci.tests.test_impact import scope


class OnboardingImpactTests(unittest.TestCase):
    def test_run_changes_include_provider_consumers_and_real_database_checks(self):
        for path in [
            "backend/routers/agent.py",
            "backend/schemas/agent.py",
            "backend/services/agent/orchestrator.py",
            "backend/services/agent/run_store.py",
            "backend/services/agent/onboarding_creation.py",
            "backend/services/assessments.py",
            "contracts/fixtures/onboarding-runs.json",
            "contracts/fixtures/onboarding-cancellation.json",
        ]:
            with self.subTest(path=path):
                checks = load_plan(scope(path))["checks"]
                for test in [
                    "test_onboarding_recovery",
                    "test_agent_permissions",
                    "test_assessment_service",
                ]:
                    self.assertIn(f"pytest:tests/p0/{test}.py", checks["python"])
                self.assertIn(
                    "pytest:tests/contracts/test_onboarding_contract.py", checks["python"]
                )
                self.assertIn(
                    "com.gmaicoson.socraticmind.network.SseContractTest", checks["android"]
                )
                self.assertIn("ChatHistoryAPIContractTests", checks["ios"])
                self.assertEqual(8, len(checks["mysql"]))
                self.assertIn(
                    "pytest:tests/contracts/test_onboarding_cancellation.py", checks["python"]
                )
                self.assertNotIn("pytest:tests/p0/test_auth_api.py", checks["python"])

    def test_mysql_test_only_does_not_expand_unrelated_suites(self):
        result = load_plan(scope("backend/tests/integration/test_mysql_onboarding_recovery.py"))
        self.assertEqual(4, len(result["checks"]["mysql"]))
        for lane in ["python", "android", "ios"]:
            self.assertFalse(result["checks"][lane])

    def test_plan_documents_do_not_run_business_tests(self):
        result = load_plan(scope("docs/m2-evidence-review.md", "docs/onboarding-implementation.md"))
        self.assertTrue(all(not values for values in result["checks"].values()))

    def test_cancel_mysql_test_changes_select_only_its_four_named_methods(self):
        result = load_plan(scope("backend/tests/integration/test_mysql_onboarding_cancellation.py"))
        self.assertEqual(4, len(result["checks"]["mysql"]))
        self.assertTrue(
            all(
                "test_mysql_onboarding_cancellation.py::" in item
                for item in result["checks"]["mysql"]
            )
        )
        for lane in ["python", "android", "ios"]:
            self.assertFalse(result["checks"][lane])

    def test_legacy_chat_test_correction_keeps_its_narrow_scope(self):
        result = load_plan(scope("backend/tests/p0/test_chat_context_edges.py"))
        self.assertEqual(["pytest:tests/p0/test_chat_context_edges.py"], result["checks"]["python"])
        for lane in ["android", "ios", "mysql"]:
            self.assertFalse(result["checks"][lane])


if __name__ == "__main__":
    unittest.main()
