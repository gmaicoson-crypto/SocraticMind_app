"""Native wire assertions for sending, cancelling and bounded request recovery; synthetic data only."""

import json
from pathlib import Path


DATA = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/fixtures/chat-turns.json").read_text()
)
CONTEXTS = json.loads(
    (
        Path(__file__).resolve().parents[2] / "contracts/fixtures/chat-regeneration-contexts.json"
    ).read_text()
)["cases"]
FEEDBACK = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/fixtures/chat-feedback.json").read_text()
)
FEEDBACK_WIRE = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/fixtures/chat-feedback-wire.json").read_text()
)["cases"]
RAW_USAGE = "__synthetic_raw_feedback_usage__"


def feedback(case):
    if any(case == "feedback-wire-" + item["name"] for item in FEEDBACK_WIRE):
        return {"status": "interrupted", "usage": RAW_USAGE, "error_code": "AI_TIMEOUT"}
    for item in FEEDBACK["usage_cases"]:
        if case == "feedback-usage-" + item["name"]:
            return {"status": "complete", "usage": item["input"]}
    for item in FEEDBACK["errors"]:
        if case == "feedback-error-" + item["kind"]:
            return {
                "status": item["status"],
                "usage": FEEDBACK["reported_usage"],
                "error_code": item["code"],
                "error": {
                    "code": item["code"],
                    "message": "synthetic-private-key",
                    "retryable": True,
                },
            }
    return {}


def response(method: str, path: str, query: dict, headers, body: bytes = b""):
    status, payload = _response(method, path, query, headers, body)
    case = headers.get("Authorization", "").removeprefix("Bearer turn-feedback-wire-")
    item = next((item for item in FEEDBACK_WIRE if case == item["name"]), None)
    if item and status == 200:
        if method == "GET" and path.startswith("/api/chat/requests/"):
            payload = payload | item.get("override", {})
        # Controlled fixture literals preserve decimal/exponent syntax through actual HTTP bytes.
        encoded = json.dumps(payload, ensure_ascii=False).replace(
            json.dumps(RAW_USAGE), item["usage_json"]
        )
        return status, encoded.encode()
    return status, payload


def _response(method: str, path: str, query: dict, headers, body: bytes = b""):
    bearer = headers.get("Authorization", "")
    if not bearer.startswith("Bearer turn-"):
        return 401, {"detail": "登录已失效"}
    case = bearer.removeprefix("Bearer turn-")
    request = DATA["request"]
    if method == "GET" and path == f"/api/chat/requests/{request['request_id']}":
        if report := feedback(case):
            return 200, DATA["status"] | report
        for item in DATA["invalid_status"]:
            if case == item["id"]:
                return 200, item["payload"]
        if case in {"generating", "complete", "failed", "interrupted"}:
            return 200, {**DATA["status"], "status": case}
        if case == "missing":
            return 404, {"code": "CHAT_REQUEST_NOT_FOUND", "message": "not found"}
        if case == "deleted":
            return 409, {"code": "CHAT_REQUEST_DELETED", "message": "deleted"}
        return 200, DATA["status"]
    if method == "GET" and path == "/api/chat/session-messages":
        try:
            identifier = int(query.get("snapshot_id", [""])[0])
        except ValueError:
            return 400, {"detail": "snapshot required"}
        if query != {
            "session_id": [request["session_id"]],
            "snapshot_id": [str(identifier)],
            "limit": ["1"],
        }:
            return 400, {"detail": "exact bounded lookup required"}
        visible = [m for m in DATA["messages"] if m["id"] <= identifier]
        if case == "neighbour":
            visible = [m for m in visible if m["id"] != identifier]
        items = sorted(visible, key=lambda m: m["id"], reverse=True)[:1]
        if report := feedback(case):
            items = [
                item | {"metadata": (item["metadata"] or {}) | report}
                if item["role"] == "ai"
                else item
                for item in items
            ]
        return 200, {"items": items, "snapshot_id": identifier, "next_before_id": None}
    if method == "POST":
        if not headers.get("Content-Type", "").startswith("application/json"):
            return 415, {"detail": "JSON required"}
        try:
            payload = json.loads(body)
        except ValueError:
            return 400, {"detail": "invalid JSON"}
        if path == "/api/chat/stream" and payload == request:
            return 200, {"stream": True}
        if path == "/api/chat/stream" and payload == DATA["regeneration_request"]:
            return 200, {"stream": True, "regeneration": True}
        if path == "/api/chat/stream" and any(payload == item["request"] for item in CONTEXTS):
            return 200, {"stream": True, "regeneration": True}
        if path == "/api/chat/cancel" and payload == {
            "request_id": request["request_id"],
            "session_id": request["session_id"],
        }:
            if report := feedback(case):
                return 200, {
                    "status": report["status"],
                    "msg_ids": DATA["status"]["msg_ids"],
                    "usage": report["usage"],
                }
            for item in DATA["cancel_cases"]:
                if case == item["id"]:
                    return 200, item["payload"]
    return 400, {"detail": "wrong turn request"}


def frames(regeneration: bool = False) -> bytes:
    payloads = [
        {"msg_ids": {"user": 101, "ai": 103} if regeneration else DATA["status"]["msg_ids"]},
        {"text": "你好，"},
        {"text": "世界🙂"},
        {"request_state": {"status": "complete"}},
        "[DONE]",
    ]
    return "".join(
        "data: " + (p if isinstance(p, str) else json.dumps(p, ensure_ascii=False)) + "\n\n"
        for p in payloads
    ).encode()
