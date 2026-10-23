"""Loopback-only synthetic HTTP fixture shared by Kotlin/JVM and Swift transport tests."""

import argparse
import json
import select
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from auth_fixture import response as auth_response
from chat_actions_fixture import response as actions_response
from chat_history_fixture import response as history_response
from chat_turn_fixture import frames as turn_frames
from chat_turn_fixture import response as turn_response


ROOT = Path(__file__).resolve().parents[2]
CASES = {
    item["id"]: item["wire"]
    for item in json.loads((ROOT / "contracts/fixtures/chat-streams.json").read_text())["cases"]
}
LOCK = threading.Lock()
RUNS = {}


def event(payload: dict | str) -> bytes:
    value = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return f"data: {value}\n\n".encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_arguments):
        pass  # No request bodies, tokens, or platform credentials in test output.

    def respond(self, status: int, payload: dict, **headers):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path.startswith("/api/auth/"):
            self.respond(*auth_response("GET", url.path, self.headers))
        elif url.path == "/api/chat/session-titles":
            self.respond(*actions_response("GET", url.path, parse_qs(url.query), self.headers))
        elif url.path.startswith("/api/chat/requests/") or (
            url.path == "/api/chat/session-messages"
            and self.headers.get("Authorization", "").startswith("Bearer turn-")
        ):
            self.respond(*turn_response("GET", url.path, parse_qs(url.query), self.headers))
        elif url.path in {"/api/chat/sessions", "/api/chat/session-messages"}:
            self.respond(*history_response(url.path, parse_qs(url.query), self.headers))
        elif url.path == "/health":
            self.respond(200, {"status": "ok"})
        elif url.path == "/idle-seed":
            # Model a peer which silently drops a later request on an old pooled socket.
            self.drop_next_mutation = True
            self.respond(200, {"status": "ok"})
        elif url.path == "/stats":
            identifier = parse_qs(url.query).get("id", [""])[0]
            with LOCK:
                run = RUNS.get(identifier, {})
                result = {"count": run.get("count", 0), "closed": run.get("closed", False)}
            self.respond(200, result)
        else:
            self.respond(404, {"detail": "not found"})

    def chat_action(self, method):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 65536:
            self.respond(413, {"detail": "fixture request too large"})
            self.close_connection = True
            return
        url = urlsplit(self.path)
        self.respond(
            *actions_response(
                method, url.path, parse_qs(url.query), self.headers, self.rfile.read(length)
            )
        )

    def do_PUT(self):
        self.chat_action("PUT")

    def do_DELETE(self):
        self.chat_action("DELETE")

    def do_POST(self):
        if self.path == "/fresh-mutation" and getattr(self, "drop_next_mutation", False):
            self.close_connection = True
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 65536:
            self.respond(413, {"detail": "fixture request too large"})
            self.close_connection = True
            return
        body = self.rfile.read(length)
        if self.path == "/fresh-mutation":
            self.drop_next_mutation = True
            self.respond(200, {"status": "ok"})
            return
        if self.path.startswith("/api/auth/"):
            self.respond(*auth_response("POST", self.path, self.headers, body))
            return
        if self.path in {"/api/chat/stream", "/api/chat/cancel"}:
            status, payload = turn_response("POST", self.path, {}, self.headers, body)
            if self.path == "/api/chat/stream" and status == 200:
                wire = turn_frames(payload.get("regeneration", False))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(wire)))
                self.end_headers()
                self.wfile.write(wire)
            else:
                self.respond(status, payload)
            return
        if self.path == "/echo-form":
            values = parse_qs(body.decode())
            valid = values == {"username": ["邮箱+test@example.test"], "password": ["p+& =中文"]}
            valid &= self.headers.get("Content-Type", "").startswith(
                "application/x-www-form-urlencoded"
            )
            self.respond(200 if valid else 400, {"valid": valid})
            return
        if self.headers.get("Authorization") != "Bearer contract-token":
            self.respond(401, {"detail": "登录已失效"})
            return
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            self.respond(415, {"detail": "JSON required"})
            return
        try:
            payload = json.loads(body)
        except ValueError:
            self.respond(400, {"detail": "invalid JSON"})
            return
        if self.path == "/echo-json":
            self.respond(200, {"text": payload["text"]})
        elif self.path == "/fail":
            self.respond(
                409, {"code": "VERSION_CONFLICT", "message": "版本已更新", "retryable": False}
            )
        elif self.path == "/invalid-form":
            self.respond(
                422,
                {
                    "detail": [
                        {
                            "loc": ["body", "password"],
                            "msg": "Value error, 密码至少 8 位",
                            "input": "synthetic-private-value",
                        }
                    ]
                },
            )
        elif self.path == "/redirect":
            self.respond(302, {}, Location="/echo-json")
        elif self.path == "/oversized":
            self.respond(200, {"text": "x" * 4096})
        elif self.path == "/release":
            with LOCK:
                run = RUNS[payload["request_id"]]
                run["release"].set()
            self.respond(200, {"released": True})
        elif self.path == "/stream":
            self.stream(payload)
        else:
            self.respond(404, {"detail": "not found"})

    def stream(self, payload: dict):
        case = payload["case"]
        identifier = payload["request_id"]
        with LOCK:
            run = RUNS.setdefault(
                identifier, {"count": 0, "closed": False, "release": threading.Event()}
            )
            run["count"] += 1
        if case == "wrong-type":
            self.respond(200, {})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            if case in CASES:
                for byte in CASES[case].encode():
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
            elif case == "gated":
                self.wfile.write(event({"text": "先到"}))
                self.wfile.flush()
                released = run["release"].wait(timeout=3)
                self.wfile.write(
                    event({"request_state": {"status": "complete" if released else "failed"}})
                )
                self.wfile.write(event("[DONE]"))
                self.wfile.flush()
            elif case in {"truncated", "cancel"}:
                self.wfile.write(event({"text": "部分"}))
                self.wfile.flush()
                if case == "cancel":
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        readable, _, _ = select.select([self.connection], [], [], 0.1)
                        if readable:
                            self.connection.recv(1)
                            break
            else:
                self.wfile.write(
                    event({"error": {"code": "BAD_CASE", "message": "fixture", "retryable": False}})
                )
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with LOCK:
                run["closed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-file", type=Path, required=True)
    arguments = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    value = {"url": f"http://127.0.0.1:{server.server_port}/"}
    temporary = arguments.ready_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    temporary.replace(arguments.ready_file)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
