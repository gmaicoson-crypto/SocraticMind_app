"""Assert native HTTP requests against synthetic cases; no learning business implementation."""

import json
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT / "contracts/fixtures/onboarding-wire.json").read_text())


def handle(handler, method, runs, lock):
    if not urlsplit(handler.path).path.startswith("/api/agent/"):
        return False
    authorization = handler.headers.get("Authorization", "")
    if not authorization.startswith("Bearer onboarding-"):
        handler.respond(401, {"code": "AUTH_REQUIRED", "message": "synthetic", "retryable": False})
        return True
    token = authorization.removeprefix("Bearer ")
    with lock:
        record = runs.setdefault(token, {})
        record["count"] = record.get("count", 0) + 1
    length = int(handler.headers.get("Content-Length", "0"))
    if length < 0 or length > 65536:
        handler.respond(413, {"detail": "fixture request too large"})
        handler.close_connection = True
        return True
    body = handler.rfile.read(length)
    name = token.removeprefix("onboarding-")
    case = next((item for item in DATA["cases"] if item["id"] == name), None)
    invalid = next((item for item in DATA["invalid"] if item["id"] == name), None)
    if invalid and method == "GET":
        handler.respond(200, invalid["wire"].encode())
        return True
    try:
        payload = json.loads(body) if body else None
    except (ValueError, UnicodeDecodeError):
        payload = "invalid JSON"
    if not case or (method, handler.path, json.dumps(payload, sort_keys=True)) != (
        case["method"],
        case["path"],
        json.dumps(case["body"], sort_keys=True),
    ):
        handler.respond(
            422,
            {"code": "FIXTURE_REQUEST_MISMATCH", "message": "request differs", "retryable": False},
        )
        return True
    handler.respond(case["status"], case["response"])
    return True
