"""Original context survives regeneration; rejected changes never replace an answer."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from core.config import settings
from models import ChatMessage, ChatTurn, Node, Topic
from models.attachment import Attachment, AttachmentChunk

CASES = json.loads(
    (
        Path(__file__).resolve().parents[3] / "contracts/fixtures/chat-regeneration-contexts.json"
    ).read_text()
)["cases"]


@pytest.fixture()
def context_generation(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("ATTACHMENT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(
        settings,
        "llm_models",
        json.dumps(
            [
                {
                    "id": "context-contract",
                    "name": "Context",
                    "model": "test-model",
                    "api_key": "test-key",
                    "base_url": "http://127.0.0.1:1/v1",
                    "tokenizer_encoding": "utf8_bytes",
                }
            ]
        ),
    )
    monkeypatch.setattr(settings, "llm_default_model_id", "context-contract")
    monkeypatch.setattr(settings, "web_search_enabled", False)

    def stream(**arguments):
        calls.append(arguments)
        yield "合成回答。"

    monkeypatch.setattr("routers.chat.chat_stream", stream)
    return calls


def seed(db, user, case):
    request = case["original_request"]
    if request["topic_id"]:
        db.add(Topic(id=7, user_id=user.id, title="递归"))
        db.flush()
        db.add(Node(topic_id=7, node_key="node-recursion", label="递归节点"))
    if request.get("quote_source_id"):
        for identifier in (91, 92):
            db.add(
                ChatMessage(
                    id=identifier,
                    user_id=user.id,
                    topic_id=None,
                    session_id=request["session_id"],
                    node_key=request["node_key"],
                    mode="normal",
                    role="ai",
                    message_type="chat",
                    content=f"完整引用原文 {identifier}：递归必须有终止条件。",
                    metadata_json={"kind": "qa", "status": "complete"},
                )
            )
    for index, key in enumerate(request.get("attachment_ids", [])):
        db.add(
            Attachment(
                id=key,
                user_id=user.id,
                client_upload_id=key,
                draft_session_id=request["session_id"],
                topic_id=None,
                mode="normal",
                name=f"合成资料-{index}.pdf",
                mime_type="application/pdf",
                kind="document",
                size=128,
                sha256="a" * 64,
                storage_key=f"{key}/original.pdf",
                status="ready",
                pages=1,
                revision=1,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
        )
        db.flush()
        db.add(
            AttachmentChunk(
                attachment_id=key,
                revision=1,
                chunk_id="page-1",
                position=0,
                text=f"合成资料-{index}：递归必须有终止条件。",
                locator={"page": 1},
                block_type="paragraph",
                title_path=[],
                asset_refs=[],
            )
        )
    db.commit()


def begin(client, db, user, case):
    seed(db, user, case)
    response = client.post("/api/chat/stream", json=case["original_request"])
    assert response.status_code == 200, response.text
    status = client.get(f"/api/chat/requests/{case['original_request']['request_id']}").json()
    assert status["status"] == "complete", status
    return status["msg_ids"]


@pytest.mark.parametrize("case", CASES, ids=lambda value: value["name"])
def test_regeneration_preserves_kind_quote_resources_and_question(
    client,
    db_session,
    auth_user,
    context_generation,
    case,
):
    original = begin(client, db_session, auth_user, case)
    question = db_session.get(ChatMessage, original["user"])
    metadata = deepcopy(question.metadata_json)
    original_count = db_session.query(ChatMessage).filter_by(role="user").count()
    payload = {**case["request"], "regenerate_message_id": original["ai"]}
    response = client.post("/api/chat/stream", json=payload)
    assert response.status_code == 200, response.text
    status = client.get(f"/api/chat/requests/{payload['request_id']}").json()
    assert status["status"] == "complete", status
    assert status["msg_ids"]["user"] == original["user"]
    assert status["msg_ids"]["ai"] != original["ai"]
    assert db_session.query(ChatMessage).filter_by(role="user").count() == original_count
    db_session.refresh(question)
    assert question.content == case["original_request"]["user_input"]
    assert question.metadata_json == metadata
    assert metadata["kind"] == payload["kind"]
    assert [item["id"] for item in metadata["attachment_snapshot"]] == payload.get(
        "attachment_ids", []
    )
    assert len(context_generation) == 2
    for call in context_generation:
        assert call["kind"] == payload["kind"]
        if payload.get("quote_source_id"):
            assert "完整引用原文 91" in str(call["prepared_messages"])
        for index, _key in enumerate(payload.get("attachment_ids", [])):
            assert f"合成资料-{index}" in str(call["prepared_messages"])
    history = client.get(
        "/api/chat/session-messages", params={"session_id": payload["session_id"]}
    ).json()["items"]
    projected = next(row for row in history if row["id"] == original["user"])
    expected = case["messages"][0]
    for key in ("role", "content", "node_key", "mode", "topic_id", "session_id", "message_type"):
        assert projected[key] == expected[key]
    for key, value in expected["metadata"].items():
        assert projected["metadata"][key] == value
    assert [item["id"] for item in projected["attachments"]] == payload.get("attachment_ids", [])
    for actual, expected_attachment in zip(
        projected["attachments"], expected["attachments"], strict=True
    ):
        for key in ("id", "revision", "accepted_coverage"):
            assert actual[key] == expected_attachment[key]
    answer = next(row for row in history if row["id"] == status["msg_ids"]["ai"])
    assert answer["metadata"]["kind"] == case["messages"][1]["metadata"]["kind"]
    assert answer["metadata"]["user_message_id"] == original["user"]
    assert original["ai"] not in {row["id"] for row in history}
    assert status["msg_ids"]["ai"] in {row["id"] for row in history}
    assert client.post("/api/chat/stream", json=payload).status_code == 200
    assert (
        len(context_generation) == 2
    )  # Idempotent replay still uses the same completed replacement.


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"quote_text": "替换引用"}, "CHAT_REGENERATE_INVALID"),
        ({"quote_source_id": 92}, "CHAT_REGENERATE_INVALID"),
        ({"quote_source_id": None}, "CHAT_REGENERATE_INVALID"),
        ({"quote_source_id": None, "quote_text": None}, "CHAT_REGENERATE_INVALID"),
        ({"quote_source_id": 999}, "CHAT_QUOTE_INVALID"),
        ({"_delete_source": True}, "CHAT_QUOTE_INVALID"),
    ],
)
def test_changed_or_missing_quote_cannot_start_replacement_and_can_be_cancelled(
    client,
    db_session,
    auth_user,
    context_generation,
    changes,
    code,
):
    case = CASES[0]
    ids = begin(client, db_session, auth_user, case)
    changes = dict(changes)
    if changes.pop("_delete_source", False):
        db_session.delete(db_session.get(ChatMessage, 91))
        db_session.commit()
    payload = {**case["request"], "regenerate_message_id": ids["ai"], **changes}
    response = client.post("/api/chat/stream", json=payload)
    assert response.status_code == 400
    assert response.json()["code"] == code
    assert len(context_generation) == 1
    assert db_session.get(ChatMessage, ids["ai"]).metadata_json["status"] == "complete"
    assert db_session.query(ChatTurn).filter_by(request_id=payload["request_id"]).first() is None
    cancelled = client.post(
        "/api/chat/cancel",
        json={"request_id": payload["request_id"], "session_id": payload["session_id"]},
    )
    assert cancelled.json() == {"status": "interrupted"}
    assert client.post("/api/chat/stream", json=payload).status_code in (400, 409)
    assert len(context_generation) == 1


@pytest.mark.parametrize("field,value", [("role", "ai"), ("message_type", "assessment")])
def test_misclassified_original_question_does_not_replace_the_answer(
    client,
    db_session,
    auth_user,
    context_generation,
    field,
    value,
):
    case = CASES[0]
    ids = begin(client, db_session, auth_user, case)
    setattr(db_session.get(ChatMessage, ids["user"]), field, value)
    db_session.commit()
    response = client.post(
        "/api/chat/stream", json={**case["request"], "regenerate_message_id": ids["ai"]}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "CHAT_REGENERATE_INVALID"
    assert db_session.get(ChatMessage, ids["ai"]).metadata_json["status"] == "complete"
    assert len(context_generation) == 1


@pytest.mark.parametrize("change", ["revision", "snapshot", "ids", "order"])
def test_attachment_changes_preserve_original_answer(
    client,
    db_session,
    auth_user,
    context_generation,
    change,
):
    case = CASES[1]
    ids = begin(client, db_session, auth_user, case)
    payload = {**case["request"], "regenerate_message_id": ids["ai"]}
    if change == "revision":
        db_session.get(Attachment, payload["attachment_ids"][0]).revision += 1
    elif change == "snapshot":
        question = db_session.get(ChatMessage, ids["user"])
        question.metadata_json = {**question.metadata_json, "attachment_snapshot": []}
    else:
        payload["attachment_ids"] = (
            payload["attachment_ids"][1:]
            if change == "ids"
            else list(reversed(payload["attachment_ids"]))
        )
    db_session.commit()
    response = client.post("/api/chat/stream", json=payload)
    assert response.status_code == 400
    assert response.json()["code"] == "CHAT_REGENERATE_INVALID"
    assert db_session.get(ChatMessage, ids["ai"]).metadata_json["status"] == "complete"
    assert len(context_generation) == 1


def test_legacy_plain_question_without_turn_metadata_still_regenerates(
    client,
    db_session,
    auth_user,
    context_generation,
):
    payload = {
        "request_id": "legacy-context-retry",
        "session_id": "legacy-context",
        "mode": "normal",
        "node_key": "__normal__",
        "topic_id": 0,
        "kind": "qa",
        "user_input": "  旧问题🙂  ",
        "ai_style": "标准",
        "regenerate_message_id": 102,
    }
    for identifier, role, content in [(101, "user", payload["user_input"]), (102, "ai", "旧回答")]:
        db_session.add(
            ChatMessage(
                id=identifier,
                user_id=auth_user.id,
                session_id=payload["session_id"],
                node_key=payload["node_key"],
                mode="normal",
                role=role,
                content=content,
                message_type="chat",
                metadata_json=None,
            )
        )
    db_session.commit()
    response = client.post("/api/chat/stream", json=payload)
    assert response.status_code == 200, response.text
    status = client.get("/api/chat/requests/legacy-context-retry").json()
    assert status["status"] == "complete"
    assert status["msg_ids"]["user"] == 101
    assert db_session.query(ChatMessage).filter_by(role="user").count() == 1
    assert len(context_generation) == 1
