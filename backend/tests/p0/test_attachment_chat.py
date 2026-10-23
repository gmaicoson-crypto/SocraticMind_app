"""Chat integration: resources survive retries without escaping message scope."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from core.config import settings
from core.errors import ApiError
from models import ChatMessage, ChatSession, ChatTurn, User
from models.attachment import Attachment, AttachmentChunk, MessageAttachment, AttachmentCleanup
from routers import chat
from services.chat_lifecycle import (
    begin_chat_turn,
    finish_chat_turn,
    cancel_chat_turn,
    refresh_generation_lease,
)
from services.progress_archive import archive_and_delete_messages


@pytest.fixture(autouse=True)
def attachment_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTACHMENT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(
        settings,
        "llm_models",
        json.dumps(
            [
                {
                    "id": "attachment-test",
                    "name": "Test",
                    "model": "test-model",
                    "api_key": "test",
                    "base_url": "https://example.test/v1",
                    "tokenizer_encoding": "utf8_bytes",
                }
            ]
        ),
    )
    monkeypatch.setattr(settings, "llm_default_model_id", "attachment-test")


def document(
    db,
    user,
    *,
    session="attachment-chat",
    status="ready",
    text="递归需要终止条件，否则会无限调用自身。",
    **extra,
):
    key = str(uuid.uuid4())
    item = Attachment(
        id=key,
        user_id=user.id,
        client_upload_id=key,
        draft_session_id=session,
        topic_id=None,
        mode="normal",
        name="递归讲义.pdf",
        mime_type="application/pdf",
        kind="document",
        size=128,
        sha256="a" * 64,
        storage_key=f"{key}/original.pdf",
        status=status,
        pages=1,
        revision=1,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        **extra,
    )
    db.add(item)
    db.flush()
    db.add(
        AttachmentChunk(
            attachment_id=key,
            revision=1,
            chunk_id="page-1",
            position=0,
            text=text,
            locator={"page": 1},
            block_type="paragraph",
            title_path=[],
            asset_refs=[],
        )
    )
    db.commit()
    return item


def start(db, user, attachment, **overrides):
    return begin_chat_turn(
        db,
        **{
            "user_id": user.id,
            "topic_id": None,
            "session_id": "attachment-chat",
            "node_key": "normal",
            "user_input": "",
            "mode": "normal",
            "request_id": "attachment-request",
            "model_id": "attachment-test",
            "attachment_ids": [attachment.id],
            **overrides,
        },
    )


def complete(db, user, started):
    assert finish_chat_turn(
        db,
        user_id=user.id,
        request_id=started.turn.request_id,
        generation_token=started.turn.generation_token,
        content="需要终止条件。",
        status="complete",
    )


def events(response):
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")
    ]


def payload(item, **extra):
    return {
        "request_id": "wire-request",
        "session_id": "attachment-chat",
        "node_key": "normal",
        "topic_id": 0,
        "user_input": "",
        "mode": "normal",
        "attachment_ids": [item.id],
        **extra,
    }


def test_binding_is_atomic_and_idempotent(db_session, auth_user):
    item = document(db_session, auth_user)
    first = start(db_session, auth_user, item)
    complete(db_session, auth_user, first)
    replay = start(db_session, auth_user, item)
    assert replay.replayed
    assert replay.user_message.id == first.user_message.id
    assert db_session.query(MessageAttachment).count() == 1
    assert db_session.query(ChatMessage).count() == 2
    assert first.user_message.content == ""
    assert first.user_message.metadata_json["attachment_snapshot"][0]["revision"] == 1
    other = document(db_session, auth_user)
    with pytest.raises(ApiError) as error:
        start(db_session, auth_user, other)
    assert error.value.code == "CHAT_REQUEST_CONFLICT"


def test_unready_or_foreign_attachment_does_not_create_turn(db_session, auth_user):
    item = document(db_session, auth_user, status="processing")
    with pytest.raises(ApiError) as error:
        start(db_session, auth_user, item)
    assert error.value.code == "ATTACHMENT_NOT_READY"
    assert db_session.query(ChatTurn).count() == 0
    assert db_session.query(ChatMessage).count() == 0
    stranger = User(username="stranger", email="stranger@example.test", hashed_password="x")
    db_session.add(stranger)
    db_session.commit()
    item = document(db_session, stranger)
    with pytest.raises(ApiError) as error:
        start(db_session, auth_user, item)
    assert error.value.status_code == 404


def test_scope_mismatch_and_expiry_reject_binding(db_session, auth_user):
    item = document(db_session, auth_user, session="other-session")
    with pytest.raises(ApiError) as error:
        start(db_session, auth_user, item)
    assert error.value.code == "ATTACHMENT_SCOPE_MISMATCH"
    item.draft_session_id = "attachment-chat"
    item.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    with pytest.raises(ApiError):
        start(db_session, auth_user, item)
    assert db_session.query(MessageAttachment).count() == 0


def test_regeneration_keeps_original_resources_and_failed_answer(db_session, auth_user):
    item = document(db_session, auth_user)
    original = start(db_session, auth_user, item)
    complete(db_session, auth_user, original)
    regenerated = start(
        db_session,
        auth_user,
        item,
        request_id="regenerate",
        attachment_ids=[],
        regenerate_message_id=original.ai_message.id,
    )
    assert regenerated.user_message.id == original.user_message.id
    assert db_session.query(MessageAttachment).count() == 1
    finish_chat_turn(
        db_session,
        user_id=auth_user.id,
        request_id="regenerate",
        generation_token=regenerated.turn.generation_token,
        content="",
        status="failed",
    )
    assert db_session.get(ChatMessage, original.ai_message.id).content == "需要终止条件。"
    other = document(db_session, auth_user)
    with pytest.raises(ApiError) as error:
        start(
            db_session,
            auth_user,
            other,
            request_id="swap",
            regenerate_message_id=original.ai_message.id,
        )
    assert error.value.code == "CHAT_REGENERATE_INVALID"


def test_cancel_keeps_bound_resources(db_session, auth_user):
    item = document(db_session, auth_user)
    started = start(db_session, auth_user, item)
    cancelled = cancel_chat_turn(
        db_session,
        user_id=auth_user.id,
        session_id="attachment-chat",
        request_id=started.turn.request_id,
    )
    assert cancelled.status == "interrupted"
    assert db_session.get(Attachment, item.id).status == "ready"
    assert db_session.query(MessageAttachment).count() == 1


def test_answer_deletion_keeps_file_but_question_deletion_revokes_it(db_session, auth_user):
    item = document(db_session, auth_user)
    started = start(db_session, auth_user, item)
    complete(db_session, auth_user, started)
    question_id, answer_id = started.user_message.id, started.ai_message.id
    archive_and_delete_messages(db_session, user_id=auth_user.id, ids=[answer_id])
    db_session.commit()
    assert db_session.get(Attachment, item.id).status == "ready"
    assert db_session.query(MessageAttachment).count() == 1
    archive_and_delete_messages(db_session, user_id=auth_user.id, ids=[question_id])
    db_session.commit()
    db_session.expire_all()
    removed = db_session.get(Attachment, item.id)
    assert removed is None or removed.status == "deleted"
    assert db_session.query(AttachmentCleanup).count() == 1


def test_session_deletion_cleans_unbound_draft(db_session, auth_user):
    item = document(db_session, auth_user)
    archive_and_delete_messages(db_session, user_id=auth_user.id, session_id="attachment-chat")
    db_session.commit()
    db_session.expire_all()
    removed = db_session.get(Attachment, item.id)
    assert removed is None or removed.status == "deleted"
    assert db_session.query(AttachmentCleanup).count() == 1


def test_attachment_only_chat_history_followup_and_replay(
    client, db_session, auth_user, monkeypatch
):
    item = document(db_session, auth_user)
    calls = []
    monkeypatch.setattr(
        chat,
        "chat_stream",
        lambda **kwargs: calls.append(kwargs) or iter(["递归需要终止条件。[[source:s6]]"]),
    )
    first = client.post("/api/chat/stream", json=payload(item))
    assert first.status_code == 200
    assert not [e for e in events(first) if e.get("error")], first.text
    assert any(e.get("type") == "attachment_context_ready" for e in events(first))
    sent = json.dumps(calls[0]["prepared_messages"], ensure_ascii=False)
    assert "递归需要终止条件" in sent
    assert "page-1" in sent or "第 1" in sent or '"page": 1' in sent
    history = client.get("/api/chat/messages").json()
    user = next(m for m in history if m["role"] == "user")
    assert user["content"] == ""
    assert user["attachments"][0]["id"] == item.id
    ai = next(m for m in history if m["role"] == "ai")
    assert any(
        source.get("attachment_id") == item.id for source in ai["metadata"]["web"]["sources"]
    )
    replay = client.post("/api/chat/stream", json=payload(item))
    assert replay.status_code == 200
    assert len(calls) == 1
    followup = client.post(
        "/api/chat/stream",
        json=payload(
            item, request_id="followup", user_input="刚才文件第1页解释一下", attachment_ids=[]
        ),
    )
    assert not [e for e in events(followup) if e.get("error")], followup.text
    assert "递归需要终止条件" in json.dumps(calls[-1]["prepared_messages"], ensure_ascii=False)
    assert db_session.query(MessageAttachment).count() == 1


def test_search_never_receives_attachment_evidence(client, db_session, auth_user, monkeypatch):
    item = document(db_session, auth_user, text="私人讲义代号 ABC-PERSONAL 不得公开")
    searches = []
    original = chat.iter_web_search

    def observed(**kwargs):
        searches.append(kwargs)
        yield from original(**kwargs)

    monkeypatch.setattr(chat, "iter_web_search", observed)
    monkeypatch.setattr(chat, "chat_stream", lambda **kwargs: iter(["已阅读资料。 "]))
    response = client.post("/api/chat/stream", json=payload(item, user_input="概括讲义"))
    assert not [e for e in events(response) if e.get("error")], response.text
    assert searches[0]["web_mode"] == "off"
    assert searches[0]["context_messages"] == []
    assert "ABC-PERSONAL" not in searches[0]["user_input"]


def test_request_status_only_observes_and_expires_abandoned_work(client, db_session, auth_user):
    item = document(db_session, auth_user)
    started = start(db_session, auth_user, item)
    turn_count = db_session.query(ChatTurn).count()
    running = client.get(f"/api/chat/requests/{started.turn.request_id}").json()
    assert running["status"] == "generating"
    assert running["session_id"] == "attachment-chat"
    for update in (
        {"completed": 2, "total": 2, "cache_keys": ["verified-batch"]},
        {"status": "ready"},
    ):
        assert refresh_generation_lease(
            db_session,
            user_id=auth_user.id,
            request_id=started.turn.request_id,
            generation_token=started.turn.generation_token,
            preparation=update,
        )
    prepared = client.get(f"/api/chat/requests/{started.turn.request_id}").json()["preparation"]
    assert prepared == {
        "completed": 2,
        "total": 2,
        "cache_keys": ["verified-batch"],
        "status": "ready",
    }
    session = db_session.get(ChatSession, started.session.id)
    session.generation_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    recovered = client.get(f"/api/chat/requests/{started.turn.request_id}").json()
    assert recovered["status"] == "interrupted"
    assert recovered["error"]["retryable"] is True
    assert db_session.query(ChatTurn).count() == turn_count


def test_attachment_renewal_cannot_extend_persisted_deadline(db_session, auth_user):
    item = document(db_session, auth_user)
    started = start(db_session, auth_user, item)
    deadline = datetime.now(timezone.utc) + timedelta(seconds=180)
    args = dict(
        user_id=auth_user.id,
        request_id=started.turn.request_id,
        generation_token=started.turn.generation_token,
    )
    assert refresh_generation_lease(
        db_session, **args, preparation={"deadline_at": deadline.isoformat()}
    )
    assert refresh_generation_lease(db_session, **args, preparation={"status": "ready"})
    db_session.expire_all()
    session = db_session.get(ChatSession, started.session.id)
    assert session.generation_lease_until.replace(tzinfo=timezone.utc) == deadline
    turn = db_session.get(ChatTurn, started.turn.id)
    turn.preparation_json = {
        "deadline_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    }
    db_session.commit()
    assert not refresh_generation_lease(db_session, **args)


def test_attachment_history_compaction_is_scheduled_without_blocking(
    client, db_session, auth_user, monkeypatch
):
    item = document(db_session, auth_user)
    original = chat.assemble_chat_context
    scheduled = []

    def omitted(*args, **kwargs):
        prepared = original(*args, **kwargs)
        prepared.omitted_history = True
        return prepared

    monkeypatch.setattr(chat, "assemble_chat_context", omitted)
    monkeypatch.setattr(
        chat, "schedule_chat_summary", lambda *args, **kwargs: scheduled.append(kwargs)
    )
    monkeypatch.setattr(
        chat,
        "run_one_summary_job",
        lambda *args, **kwargs: pytest.fail(
            "Attachment turn must not block on historical compaction"
        ),
    )
    monkeypatch.setattr(
        chat,
        "chat_stream",
        lambda **kwargs: pytest.fail("Incomplete history must not reach the model"),
    )
    response = client.post("/api/chat/stream", json=payload(item))
    assert scheduled
    assert any(
        event.get("error", {}).get("code") == "CHAT_CONTEXT_NOT_READY" for event in events(response)
    )
    assert db_session.query(MessageAttachment).count() == 1
    assert db_session.query(ChatTurn).one().status == "failed"


def test_deleted_source_in_history_is_unavailable(client, db_session, auth_user, monkeypatch):
    item = document(db_session, auth_user)
    monkeypatch.setattr(
        chat, "chat_stream", lambda **kwargs: iter(["讲义指出终止条件。[[source:s6]]"])
    )
    response = client.post("/api/chat/stream", json=payload(item))
    assert not [e for e in events(response) if e.get("error")], response.text
    user_id = next(e["msg_ids"]["user"] for e in events(response) if "msg_ids" in e)
    client.request("DELETE", "/api/chat/messages", json={"ids": [user_id]})
    history = client.get("/api/chat/messages").json()
    ai = next(m for m in history if m["role"] == "ai")
    sources = ai["metadata"]["web"]["sources"]
    assert not any(
        source.get("excerpt") for source in sources if source.get("attachment_id") == item.id
    )
    assert all(
        source.get("deleted") for source in sources if source.get("attachment_id") == item.id
    )


def image_attachment(db, user):
    from PIL import Image
    from services.attachments.storage import AttachmentStorage

    item = document(db, user)
    item.kind = "image"
    item.name = "diagram.png"
    item.mime_type = "image/png"
    item.image_key = f"{item.id}/image.png"
    item.width = item.height = 32
    path = AttachmentStorage().path(item.image_key)
    path.parent.mkdir(parents=True)
    Image.new("RGB", (32, 32), "blue").save(path)
    db.commit()
    return item


def test_images_are_actual_multimodal_inputs_and_replay_does_not_reread(
    client, db_session, auth_user, monkeypatch
):
    item = image_attachment(db_session, auth_user)
    captured = []
    monkeypatch.setattr(
        chat,
        "chat_stream",
        lambda **kwargs: captured.append(kwargs) or iter(["蓝色方块。[[source:s6]]"]),
    )
    response = client.post("/api/chat/stream", json=payload(item))
    assert not [e for e in events(response) if e.get("error")], response.text
    parts = [
        p
        for m in captured[0]["prepared_messages"]
        if isinstance(m["content"], list)
        for p in m["content"]
    ]
    assert any(
        p.get("type") == "image_url" and p["image_url"]["url"].startswith("data:image/png;base64,")
        for p in parts
    )
    from services.attachments.storage import AttachmentStorage

    AttachmentStorage().path(item.image_key).unlink()
    replay = client.post("/api/chat/stream", json=payload(item))
    assert replay.status_code == 200
    assert len(captured) == 1


def test_nine_images_reach_provider_without_capability_configuration(
    client, db_session, auth_user, monkeypatch
):
    items = [image_attachment(db_session, auth_user) for _ in range(9)]
    captured = []
    monkeypatch.setattr(
        chat,
        "chat_stream",
        lambda **kwargs: captured.append(kwargs) or iter(["九张蓝色图片。"]),
    )
    response = client.post(
        "/api/chat/stream", json=payload(items[0], attachment_ids=[item.id for item in items])
    )
    assert response.status_code == 200
    assert not [e for e in events(response) if e.get("error")], response.text
    parts = [
        part
        for message in captured[0]["prepared_messages"]
        if isinstance(message["content"], list)
        for part in message["content"]
        if part.get("type") == "image_url"
    ]
    assert len(parts) == 9
    assert db_session.query(MessageAttachment).count() == 9


def test_tenth_attachment_is_rejected_before_binding_or_calling_provider(
    client, db_session, auth_user, monkeypatch
):
    items = [image_attachment(db_session, auth_user) for _ in range(10)]
    monkeypatch.setattr(chat, "chat_stream", lambda **kwargs: pytest.fail("Too many images"))
    response = client.post(
        "/api/chat/stream", json=payload(items[0], attachment_ids=[item.id for item in items])
    )
    assert response.status_code == 422
    assert db_session.query(MessageAttachment).count() == 0


def test_cancel_during_preparation_does_not_publish_sources(
    client, db_session, auth_user, monkeypatch
):
    from services.attachments import context

    item = document(db_session, auth_user)

    def prepare(db, **kwargs):
        cancel_chat_turn(
            db, user_id=auth_user.id, session_id="attachment-chat", request_id="wire-request"
        )
        yield {"status": "preparing", "completed": 1, "total": 2}
        pytest.fail("Canceled preparation must stop before another batch")

    monkeypatch.setattr(context, "iter_prepare_attachments", prepare)
    monkeypatch.setattr(
        chat, "chat_stream", lambda **kwargs: pytest.fail("Canceled request must not call provider")
    )
    response = client.post("/api/chat/stream", json=payload(item))
    assert any(e.get("error", {}).get("code") == "CHAT_REQUEST_CANCELLED" for e in events(response))
    assert db_session.query(ChatTurn).one().status == "interrupted"
    assert db_session.query(MessageAttachment).count() == 1
