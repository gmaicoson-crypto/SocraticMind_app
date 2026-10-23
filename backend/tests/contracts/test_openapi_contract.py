import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]


def test_native_title_json_entry_and_legacy_route_coexist():
    schema = json.loads((ROOT / "contracts/openapi/socraticmind.json").read_text())
    entry = schema["paths"]["/api/chat/session-titles"]["put"]
    reference = entry["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    request = schema["components"]["schemas"][reference.rsplit("/", 1)[1]]
    assert set(request["required"]) == {"session_id", "title"}
    assert request["properties"]["title"]["maxLength"] == 40
    assert request["properties"]["session_id"]["maxLength"] == 100
    assert "put" in schema["paths"]["/api/chat/session-titles/{session_id}"]


def test_snapshot_matches_isolated_provider():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/contracts/export_openapi.py"), "--check"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_auth_and_chat_inputs_are_declared():
    schema = json.loads((ROOT / "contracts/openapi/socraticmind.json").read_text())
    login = schema["paths"]["/api/auth/login"]["post"]["requestBody"]["content"]
    assert "application/x-www-form-urlencoded" in login
    assert "application/json" not in login
    chat = schema["components"]["schemas"]["ChatRequest"]
    assert {"request_id", "session_id", "topic_id", "node_key", "user_input"}.issubset(
        chat["required"]
    )
    assert "regenerate_message_id" in chat["properties"]
    assert "attachment_ids" in chat["properties"]
    assert "/api/auth/refresh" not in schema["paths"]
