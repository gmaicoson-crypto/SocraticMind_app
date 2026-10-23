import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.dev.local_backend import status
from scripts.dev.local_environment import child_environment, exclusive_directory, identity, prepare


class LocalEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sm-env-test-", dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def test_identity_and_private_paths_survive_repeated_setup(self):
        with exclusive_directory(self.directory):
            self.assertTrue(prepare(self.directory))
            original = identity(self.directory)
            self.assertFalse(prepare(self.directory))
            self.assertEqual(original, identity(self.directory))
            for name in ("identity.json", ".env"):
                self.assertEqual(0o600, (self.directory / name).stat().st_mode & 0o777)
        self.assertEqual({"state": "stopped", "data_preserved": True}, status(self.directory))

    def test_foreign_data_is_not_adopted(self):
        (self.directory / "existing.sql").write_text("do not touch")
        with exclusive_directory(self.directory), self.assertRaises(ValueError):
            prepare(self.directory)
        self.assertEqual("do not touch", (self.directory / "existing.sql").read_text())

    def test_concurrent_environment_owners_are_rejected(self):
        with exclusive_directory(self.directory):
            with self.assertRaises(RuntimeError), exclusive_directory(self.directory):
                self.fail("Second owner entered")

    def test_shared_directory_and_identity_are_rejected(self):
        self.directory.chmod(0o755)
        with self.assertRaises(ValueError), exclusive_directory(self.directory):
            self.fail("Unsafe directory entered")
        self.directory.chmod(0o700)
        with exclusive_directory(self.directory):
            prepare(self.directory)
            (self.directory / "identity.json").chmod(0o644)
            with self.assertRaises(ValueError):
                identity(self.directory)

    def test_parent_database_and_credentials_do_not_leak_into_child(self):
        with exclusive_directory(self.directory):
            prepare(self.directory)
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "foreign",
                "SECRET_KEY": "foreign",
                "LLM_API_KEY": "foreign",
                "SMTP_HOST": "foreign",
            },
        ):
            environment = child_environment(self.directory)
        self.assertNotIn("LLM_API_KEY", environment)
        self.assertNotIn("SMTP_HOST", environment)
        self.assertNotEqual("foreign", environment["SECRET_KEY"])
        self.assertIn("socraticmind_local", environment["DATABASE_URL"])
        self.assertEqual(str(self.directory / "avatars"), environment["AVATAR_STORAGE_DIR"])

    def test_status_cannot_follow_an_external_runtime_address(self):
        with exclusive_directory(self.directory):
            prepare(self.directory)
        value = {
            "id": identity(self.directory)["id"],
            "url": "http://127.0.0.1:8765@remote.example",
        }
        (self.directory / "runtime.json").write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            status(self.directory)


if __name__ == "__main__":
    unittest.main()
