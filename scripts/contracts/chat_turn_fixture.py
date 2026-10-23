"""Native wire assertions for sending, cancelling and bounded request recovery; synthetic data only."""

import json
from pathlib import Path


DATA = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/fixtures/chat-turns.json").read_text()
)


def response(method: str, path: str, query: dict, headers, body: bytes = b""):
    bearer = headers.get("Authorization", "")
    if not bearer.startswith("Bearer turn-"):
        return 401, {"detail": "登录已失效"}
    case = bearer.removeprefix("Bearer turn-")
    request = DATA["request"]
    if method == "GET" and path == f"/api/chat/requests/{request['request_id']}":
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
        if path == "/api/chat/cancel" and payload == {
            "request_id": request["request_id"],
            "session_id": request["session_id"],
        }:
            for item in DATA["cancel_cases"]:
                if case == item["id"]:
                    return 200, item["payload"]
    return 400, {"detail": "wrong turn request"}


def frames() -> bytes:
    payloads = [
        {"msg_ids": DATA["status"]["msg_ids"]},
        {"text": "你好，"},
        {"text": "世界🙂"},
        {"request_state": {"status": "complete"}},
        "[DONE]",
    ]
    return "".join(
        "data: " + (p if isinstance(p, str) else json.dumps(p, ensure_ascii=False)) + "\n\n"
        for p in payloads
    ).encode()
