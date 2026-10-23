"""The UI helper must not expose real accounts or unrelated log contents."""

import tempfile
import json
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from scripts.dev.auth_ui_fixture import development_code, handler, synthetic_cases


class AuthUIFixtureTests(unittest.TestCase):
    def test_allocating_a_case_does_not_reuse_an_old_code_or_change_other_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "logs").mkdir()
            cases = synthetic_cases()
            old_email = cases["ios"]["email"]
            android_case = cases["android"].copy()
            (root / "logs/backend.log").write_text(
                f"[DEV] 验证码 to={old_email} code=123456 purpose=register（SMTP 未配置）\n"
            )
            with ThreadingHTTPServer(("127.0.0.1", 0), handler(root, cases)) as server:
                thread = Thread(target=server.serve_forever, daemon=True)
                thread.start()
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                try:
                    connection.request("GET", "/code/ios/register")
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read()), {"code": "123456"})
                    connection.request("POST", "/case/ios")
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertNotEqual(json.loads(response.read())["email"], old_email)
                    connection.request("GET", "/code/ios/register")
                    response = connection.getresponse()
                    self.assertEqual(response.status, 404)
                    response.read()
                    self.assertEqual(cases["android"], android_case)
                finally:
                    connection.close()
                    server.shutdown()
                    thread.join(timeout=2)

    def test_cases_are_fresh_reserved_addresses_and_valid_username_lengths(self):
        first, second = synthetic_cases(), synthetic_cases()
        for platform, case in first.items():
            self.assertTrue(case["email"].endswith("@example.test"))
            self.assertLessEqual(len(case["username"]), 20)
            self.assertNotEqual(case["email"], second[platform]["email"])

    def test_only_exact_synthetic_email_purpose_and_dev_code_are_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "backend.log"
            email = "ui-ios-a@example.test"
            log.write_text(
                f"[DEV] 验证码 to={email} code=123456 purpose=register（SMTP 未配置）\n"
                f"[DEV] 验证码 to={email} code=654321 purpose=reset（SMTP 未配置）\n"
                "[DEV] 验证码 to=real@example.com code=999999 purpose=register（SMTP 未配置）\n"
                "other private log contents\n"
            )
            self.assertEqual("123456", development_code(log, email, "register"))
            self.assertEqual("654321", development_code(log, email, "reset"))
            self.assertIsNone(development_code(log, "other@example.test", "register"))
            self.assertIsNone(development_code(log, "real@example.com", "register"))
            self.assertIsNone(development_code(log, email, "../register"))


if __name__ == "__main__":
    unittest.main()
