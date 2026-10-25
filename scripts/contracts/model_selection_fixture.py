"""Exact synthetic model directory / choice assertions; never calls an external model."""

import copy
import json
from pathlib import Path


DATA = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/fixtures/model-selection.json").read_text()
)


def response(method: str, path: str, query: dict, headers, body: bytes = b""):
    bearer = headers.get("Authorization", "")
    if not bearer.startswith("Bearer models-"):
        return 401, {"detail": "登录已失效"}
    case = bearer.removeprefix("Bearer models-")
    if method == "GET" and path == "/api/llm/models":
        if query:
            return 400, {"detail": "unexpected query"}
        return directory(case)
    if case == "unavailable":
        return DATA["unavailable"]["status"], DATA["unavailable"]["payload"]
    expected = next((item["request"] for item in DATA["requests"] if item["name"] == case), None)
    if expected is None:
        return 400, {"detail": "unknown model case"}
    if method == "POST" and path == "/api/chat/stream":
        if not headers.get("Content-Type", "").startswith("application/json"):
            return 415, {"detail": "JSON required"}
        if json.loads(body) == expected:
            return 200, {"stream": True}
    if method == "GET" and path == "/api/chat/suggestions":
        expected_query = {"mode": [expected["mode"]], "session_id": [expected["session_id"]]}
        if "model" in expected:
            expected_query["model"] = [expected["model"]]
        if query == expected_query:
            return 200, {"suggestions": ["合成模型建议🙂"], "source": "ai"}
    return 400, {"detail": "model choice mismatch"}


def directory(case: str):
    result = copy.deepcopy(DATA["catalog"])
    first = result["models"][0]
    if case == "empty":
        result["models"] = []
    elif case == "duplicate":
        result["models"].append(first.copy())
    elif case == "many":
        result["models"] = [{**first, "id": f"id-{index}"} for index in range(257)]
    elif case in {"id", "name", "model"}:
        first[case] = "🙂" * (101 if case == "id" else 201)
    elif case == "blank":
        first["id"] = " "
    elif case == "type":
        first["id"] = 123
    elif case == "source":
        first["source"] = "unknown"
    elif case == "budget":
        result["models"] = [
            {**first, "id": f"id-{index}", "name": "🙂" * 200, "model": "🙂" * 200}
            for index in range(256)
        ]
    elif case == "unicode":
        result["models"] = [{**first, "id": identifier} for identifier in ["é", "e\u0301"]]
    elif case == "failure":
        return 503, {"message": "目录暂不可用"}
    return 200, result
