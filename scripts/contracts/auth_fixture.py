"""Synthetic auth endpoint assertions consumed by both native HTTP contract tests."""

import json
from pathlib import Path
from urllib.parse import parse_qs


DATA = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/fixtures/auth.json").read_text()
)


def response(method: str, path: str, headers, body: bytes = b"") -> tuple[int, dict]:
    fields = DATA["credentials"]
    grant = {**DATA["grant"], "user": DATA["user"]}
    if method == "GET" and path == "/api/auth/me":
        if headers.get("Authorization") != "Bearer " + grant["access_token"]:
            return 401, {"detail": "登录已失效"}
        return 200, DATA["user"]
    if method != "POST":
        return 405, {"detail": "unexpected method"}
    if path == "/api/auth/login":
        actual = parse_qs(body.decode())
        expected = {"username": [fields["email"]], "password": [fields["password"]]}
        valid = headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded")
        return (
            (200, grant) if valid and actual == expected else (400, {"detail": "wrong login form"})
        )
    if not headers.get("Content-Type", "").startswith("application/json"):
        return 415, {"detail": "expected JSON"}
    actual = json.loads(body)
    if path == "/api/auth/register":
        expected = {key: fields[key] for key in ("username", "email", "password", "code")}
        result = grant
    elif path == "/api/auth/send-code":
        if actual.get("purpose") not in {"register", "reset"}:
            return 400, {"detail": "wrong code purpose"}
        expected = {"email": fields["email"], "purpose": actual["purpose"]}
        result = {"message": DATA["messages"]["code"]}
    elif path == "/api/auth/reset-password":
        expected = {key: fields[key] for key in ("email", "code", "new_password")}
        result = {"message": DATA["messages"]["reset"]}
    else:
        return 404, {"detail": "unexpected auth path"}
    return (200, result) if actual == expected else (400, {"detail": "wrong auth fields"})
