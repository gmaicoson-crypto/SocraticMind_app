"""Deterministic native history wire assertions. No backend or model is started."""

import json
from pathlib import Path


FIXTURES = Path(__file__).resolve().parents[2] / "contracts/fixtures"
DATA = json.loads((FIXTURES / "chat-history.json").read_text())
INVALID = {
    case["id"]: case
    for case in json.loads((FIXTURES / "invalid-history-pages.json").read_text())["cases"]
}


def response(path: str, query: dict, headers) -> tuple[int, dict]:
    bearer = headers.get("Authorization", "")
    if bearer.startswith("Bearer history-case-"):
        case = INVALID[bearer.removeprefix("Bearer history-case-")]
        return 200, case["payload"]
    if bearer != "Bearer contract-token":
        return 401, {"detail": "登录已失效"}
    if path == "/api/chat/sessions":
        if query == {"mode": ["socratic"], "limit": ["1"]}:
            return 200, DATA["empty"]
        first = {"mode": ["normal"], "limit": ["1"]}
        older = {**first, "snapshot_id": ["104"], "before_id": ["104"]}
        if query == first:
            return 200, DATA["sessions_first"]
        if query == older:
            return 200, DATA["sessions_older"]
    elif path == "/api/chat/session-messages":
        if query == {"session_id": ["empty"], "limit": ["2"]}:
            return 200, DATA["empty"]
        first = {"session_id": [DATA["session_id"]], "limit": ["2"]}
        older = {**first, "snapshot_id": ["104"], "before_id": ["103"]}
        if query == first:
            return 200, DATA["messages_first"]
        if query == older:
            return 200, DATA["messages_older"]
    return 400, {"detail": "wrong history path or query"}
