"""One real-HTTP lifecycle scenario against an owned temporary persistent environment."""

import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

import httpx

from scripts.dev.local_environment import ROOT
from scripts.dev.mysql_runtime import stop_owned


class LocalBackendLifecycleTests(unittest.TestCase):
    def command(self, directory: Path, operation: str) -> list[str]:
        return [
            sys.executable,
            "-m",
            "scripts.dev.local_backend",
            operation,
            "--directory",
            str(directory),
        ]

    @contextmanager
    def server(self, directory: Path):
        with (directory / "supervisor.log").open("ab") as log:
            process = subprocess.Popen(
                [*self.command(directory, "run"), "--port", "0"],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 60
                runtime = directory / "runtime.json"
                while not runtime.exists():
                    self.assertIsNone(
                        process.poll(), "Local service exited; inspect its isolated log"
                    )
                    self.assertLess(time.monotonic(), deadline, "Local service readiness timed out")
                    time.sleep(0.1)
                url = json.loads(runtime.read_text())["url"]
                with httpx.Client(base_url=url, trust_env=False, timeout=10) as client:
                    yield client
            finally:
                stop_owned(process)
                self.assertEqual(0, process.returncode)
                self.assertFalse((directory / "runtime.json").exists())
                self.assertFalse((directory / "mysql.sock").exists())

    def test_restart_preserves_account_token_and_avatar(self):
        self.assertIsNotNone(
            shutil.which("mysqld"), "mysqld is required; do not silently skip this test"
        )
        with tempfile.TemporaryDirectory(prefix="sm-local-test-", dir="/tmp") as temporary:
            directory = Path(temporary)
            result = subprocess.run(
                self.command(directory, "init"), cwd=ROOT, capture_output=True, timeout=60
            )
            self.assertEqual(0, result.returncode, "Isolated environment init failed")
            secret_file = (directory / "identity.json").read_bytes()
            png = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5V8AAAAASUVORK5CYII="
            )
            with self.server(directory) as client:
                self.assertEqual({"status": "ok"}, client.get("/health").json())
                sent = client.post(
                    "/api/auth/send-code",
                    json={"email": "local-fixture@example.test", "purpose": "register"},
                )
                self.assertEqual(200, sent.status_code)
                code = re.search(r"code=(\d{6})", (directory / "logs/backend.log").read_text())
                self.assertIsNotNone(code)
                registered = client.post(
                    "/api/auth/register",
                    json={
                        "username": "本地测试",
                        "email": "local-fixture@example.test",
                        "password": "LocalFixture123",
                        "code": code.group(1),
                    },
                )
                self.assertEqual(200, registered.status_code)
                preset = client.get(registered.json()["user"]["avatar_url"])
                self.assertEqual(200, preset.status_code)
                self.assertTrue(preset.headers["content-type"].startswith("image/webp"))
                self.assertEqual(b"RIFF", preset.content[:4])
                headers = {"Authorization": "Bearer " + registered.json()["access_token"]}
                uploaded = client.post(
                    "/api/auth/avatar",
                    headers=headers,
                    files={"file": ("tiny.png", png, "image/png")},
                )
                self.assertEqual(200, uploaded.status_code)
                avatar_url = uploaded.json()["avatar_url"]
                self.assertEqual(
                    png, (directory / "avatars" / avatar_url.rsplit("/", 1)[1]).read_bytes()
                )
            self.assertEqual(secret_file, (directory / "identity.json").read_bytes())
            with self.server(directory) as client:
                profile = client.get("/api/auth/me", headers=headers)
                self.assertEqual(200, profile.status_code)
                self.assertEqual("本地测试", profile.json()["username"])
                self.assertEqual(avatar_url, profile.json()["avatar_url"])
                self.assertEqual(png, client.get(avatar_url).content)
                topics = client.get("/api/topics", headers=headers)
                self.assertEqual(200, topics.status_code)
                self.assertTrue(topics.json())


if __name__ == "__main__":
    unittest.main()
