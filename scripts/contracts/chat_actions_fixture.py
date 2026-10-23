"""Synthetic title and deletion wire contracts; no external service or persisted user data."""

import json
from pathlib import Path


DATA = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/fixtures/chat-actions.json").read_text()
)


def response(method, path, query, headers, body=b""):
    bearer = headers.get("Authorization", "")
    if not bearer.startswith("Bearer actions-"):
        return 401, {"detail": "登录已失效"}
    case = bearer.removeprefix("Bearer actions-")
    if case == "missing":
        return 404, {"detail": "对话不存在"}
    if case == "unavailable":
        return 503, {"detail": "暂不可用"}
    if case == "unsupported":
        return 405, {"detail": "Method Not Allowed"}
    if method == "GET" and path == "/api/chat/session-titles":
        if query != {"ids": [DATA["session_id"]]}:
            return 400, {"detail": "wrong title query"}
        if case == "empty":
            return 200, []
        if case == "duplicate":
            return 200, DATA["titles"] * 2
        for item in DATA["invalid_titles"]:
            if case == item["id"]:
                return 200, [item["payload"]]
        return 200, DATA["titles"]
    if not headers.get("Content-Type", "").startswith("application/json"):
        return 415, {"detail": "JSON required"}
    try:
        value = json.loads(body)
    except ValueError:
        return 400, {"detail": "invalid JSON"}
    if method == "PUT" and path == "/api/chat/session-titles":
        if value != {"session_id": DATA["session_id"], "title": DATA["renamed"]["title"]}:
            return 400, {"detail": "wrong rename body"}
        for item in DATA["invalid_titles"]:
            if case == item["id"]:
                return 200, item["payload"]
        return 200, DATA["renamed"]
    if method == "DELETE" and (
        (path == "/api/chat/session" and value == {"session_id": DATA["session_id"]})
        or (path == "/api/chat/messages" and value == {"ids": DATA["message_ids"]})
    ):
        return 200, {
            "deleted": {"negative": -1, "excessive": 3, "string": "2", "boolean": True}.get(case, 2)
        }
    return 400, {"detail": "wrong action request"}
