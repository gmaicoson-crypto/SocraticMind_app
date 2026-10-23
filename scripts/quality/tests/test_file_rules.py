import copy
import hashlib
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.quality.file_rules import (
    classify,
    inspect_file,
    physical_lines,
    safe_path,
    validate_baselines,
)


class PhysicalLineTests(unittest.TestCase):
    def test_counts_physical_lines_not_statements(self):
        for content, expected in (
            (b"", 0),
            (b"a", 1),
            (b"a\n", 1),
            (b"a\n\n", 2),
            (b"a\r\nb\r\n", 2),
            ("中文\n# 注释\n\n".encode(), 3),
        ):
            with self.subTest(content=content):
                self.assertEqual(expected, physical_lines(content))

    def test_exact_limit_passes_but_one_more_fails(self):
        for path, maximum in (
            ("backend/routers/example.py", 400),
            ("backend/services/example.py", 500),
            ("backend/tests/test_example.py", 800),
            ("ios/App/View.swift", 400),
        ):
            for extra, expected in ((0, "warning"), (1, "fail")):
                content = b"import SwiftUI\n" if path.endswith("swift") else b"# header\n"
                content += b"\n" * (maximum - 1 + extra)
                with self.subTest(path=path, extra=extra):
                    self.assertEqual(expected, inspect_file(path, content, {}, {}, None)["status"])

    def test_warning_is_inclusive(self):
        self.assertEqual("pass", inspect_file("a.py", b"\n" * 299, {}, {}, None)["status"])
        self.assertEqual("warning", inspect_file("a.py", b"\n" * 300, {}, {}, None)["status"])

    def test_test_classification_precedes_ui(self):
        self.assertEqual("test", classify("ios/AppTests/ViewTests.swift", b"import SwiftUI"))
        self.assertEqual("test", classify("android/core/src/test/kotlin/UITest.kt", b"@Composable"))

    def test_ui_marker_cannot_hide_in_common_folder(self):
        self.assertEqual("ui", classify("android/common/Helper.kt", b"@Composable fun Pane() {}"))
        self.assertEqual("ui", classify("ios/Common/Helper.swift", b"import SwiftUI"))

    def test_generated_comment_does_not_exempt_code(self):
        content = b"# generated\n" + b"\n" * 500
        self.assertEqual("fail", inspect_file("generated.py", content, {}, {}, None)["status"])

    def test_historical_migration_requires_exact_bytes(self):
        path = "backend/alembic/versions/old.py"
        content = b"# exact\n"
        history = {path: hashlib.sha256(content).hexdigest()}
        self.assertEqual("pass", inspect_file(path, content, {}, history, None)["status"])
        self.assertEqual("fail", inspect_file(path, content + b"\n", {}, history, None)["status"])

    def test_comparison_revision_prevents_limit_increase(self):
        path = "backend/services/big.py"
        baseline = {path: {"max_lines": 601, "task": "M2-03"}}
        result = inspect_file(path, b"\n" * 601, baseline, {}, b"\n" * 600)
        self.assertEqual("fail", result["status"])
        self.assertEqual(600, result["allowed"])

    def test_repository_path_cannot_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in ("../secret.py", "/secret.py", ""):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    safe_path(root, path)
            self.assertEqual(root / "中文 name.py", safe_path(root, "中文 name.py"))


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.value = "backend/services/legacy.py"
        self.file = self.root / self.value
        self.file.parent.mkdir(parents=True)
        self.file.write_bytes(b"\n" * 600)
        self.entry = {
            "path": self.value,
            "rule": "file_lines",
            "category": "source",
            "max_lines": 600,
            "reason": "fixed import",
            "responsible": "maintainer",
            "task": "M2-03",
            "split_direction": "separate IO and state",
            "retire_when": "below source limit",
            "source_sha256": "fixed-original-hash",
            "source_commit": "fixed-commit",
            "registered_on": "2026-10-22",
            "review_by": "2026-12-21",
        }
        self.manifest = {
            "commit": "fixed-commit",
            "files": [{"target": self.value, "source_sha256": "fixed-original-hash"}],
        }

    def validate(self, entries=None, today=date(2026, 10, 22)):
        return validate_baselines(self.root, entries or [self.entry], self.manifest, today)

    def test_current_verified_baseline_is_allowed(self):
        self.assertIn(self.value, self.validate())

    def test_expired_and_overlong_exceptions_fail(self):
        with self.assertRaises(ValueError):
            self.validate(today=date(2026, 12, 22))
        self.entry["review_by"] = "2026-12-22"
        with self.assertRaises(ValueError):
            self.validate()

    def test_reduced_files_require_explicit_tightening(self):
        self.file.write_bytes(b"\n" * 599)
        with self.assertRaises(ValueError):
            self.validate()
        self.entry["max_lines"] = 599
        self.assertIn(self.value, self.validate())

    def test_ordinary_files_must_retire_baseline(self):
        self.file.write_bytes(b"\n" * 500)
        self.entry["max_lines"] = 500
        with self.assertRaises(ValueError):
            self.validate()

    def test_deleted_or_renamed_files_require_record_cleanup(self):
        self.file.rename(self.file.with_name("renamed.py"))
        with self.assertRaises(ValueError):
            self.validate()

    def test_duplicate_source_forgery_and_missing_owner_fail(self):
        with self.assertRaises(ValueError):
            self.validate([self.entry, copy.deepcopy(self.entry)])
        for field in ("responsible", "source_sha256", "source_commit"):
            entry = copy.deepcopy(self.entry)
            entry[field] = ""
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate([entry])


if __name__ == "__main__":
    unittest.main()
