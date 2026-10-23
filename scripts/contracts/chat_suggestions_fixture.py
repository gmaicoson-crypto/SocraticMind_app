"""Synthetic suggestions contract, shared by native adapters; never invokes an external model."""

import json
from pathlib import Path


DATA = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/fixtures/chat-suggestions.json").read_text()
)


def response(query, headers):
    bearer = headers.get("Authorization", "")
    if not bearer.startswith("Bearer suggestions-"):
        return 401, {"detail": "登录已失效"}
    case = bearer.removeprefix("Bearer suggestions-")
    if case in {"unavailable", "configuration"}:
        return (503 if case == "unavailable" else 422), {"detail": "建议不可用"}
    expected = {
        "mode": ["normal"],
        "session_id": [DATA["target"]["session_id"]],
        "exclude": DATA["wire_exclude"],
    }
    if case == "topic":
        expected.update(
            mode=["socratic"], topic_id=["7"], node_key=["节点 /+🙂"], model=["model /+🙂"]
        )
    if query != expected:
        return 400, {"detail": "wrong suggestion query"}
    payload = DATA["result"]
    if case == "fallback":
        payload = DATA["fallback"]
    elif case == "empty":
        payload = {**payload, "suggestions": []}
    elif case == "source":
        payload = {**payload, "source": "local"}
    elif case == "duplicate":
        payload = {**payload, "suggestions": ["重复", "重复"]}
    elif case == "blank":
        payload = {**payload, "suggestions": [" "]}
    elif case == "type":
        payload = {**payload, "suggestions": [True]}
    elif case == "many":
        payload = {**payload, "suggestions": [str(i) for i in range(13)]}
    elif case == "long":
        payload = {**payload, "suggestions": ["🙂" * 5001]}
    elif case == "budget":
        payload = {**payload, "suggestions": ["🙂" * 4999 + str(i) for i in range(12)]}
    return 200, payload
