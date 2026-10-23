"""Expose only synthetic UI-test cases and their DEV mail codes on loopback.

Run explicitly beside an isolated local_backend; this is never mounted in FastAPI.
Each test requests a fresh synthetic case, without deleting old test data.
"""

import argparse
import json
import re
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scripts.dev.local_environment import identity


def synthetic_cases() -> dict:
    run = uuid.uuid4().hex[:8]
    return {
        platform: {
            "username": f"ui_{platform}_{run}",
            "email": f"ui-{platform}-{run}@example.test",
            "password": "UiTesting123+",
            "newPassword": "UiChanged456+",
        }
        for platform in ("ios", "android")
    }


def development_code(log: Path, email: str, purpose: str) -> str | None:
    if purpose not in {"register", "reset"} or not email.endswith("@example.test"):
        return None
    pattern = rf"\[DEV\] 验证码 to={re.escape(email)} code=(\d{{6}}) purpose={purpose}（"
    matches = re.findall(pattern, log.read_text() if log.exists() else "")
    return matches[-1] if matches else None


def handler(directory: Path, cases: dict):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            parts = self.path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "case" and parts[1] in cases:
                cases[parts[1]] = synthetic_cases()[parts[1]]
                self.respond(cases[parts[1]])
            else:
                self.respond(None)

        def do_GET(self):
            parts = self.path.strip("/").split("/")
            result = None
            if len(parts) == 2 and parts[0] == "case" and parts[1] in cases:
                result = cases[parts[1]]
            elif len(parts) == 3 and parts[0] == "code" and parts[1] in cases:
                code = development_code(
                    directory / "logs/backend.log", cases[parts[1]]["email"], parts[2]
                )
                if code:
                    result = {"code": code}
            self.respond(result)

        def respond(self, result):
            body = json.dumps(result or {"error": "not available"}).encode()
            self.send_response(200 if result else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            pass  # Codes and test credentials are not console output.

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8766)
    arguments = parser.parse_args()
    directory = arguments.directory.resolve()
    identity(directory)  # Require an environment owned by the local launcher.
    with ThreadingHTTPServer(
        ("127.0.0.1", arguments.port), handler(directory, synthetic_cases())
    ) as server:
        print(f"Synthetic UI fixture ready on loopback port {server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
