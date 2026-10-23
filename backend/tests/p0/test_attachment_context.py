"""Attachment evidence, bounded preparation and provenance contracts."""

import base64
import json
import uuid
from time import monotonic

import pytest

from core.config import settings
from core.context_budget import count_messages, ensure_fits
from core.errors import ApiError
from models.attachment import Attachment, AttachmentChunk
from services.attachments import summaries
from services.attachments.config import IMAGE_TOKEN_ESTIMATE, LIMITS
from services.attachments.context import (
    prepare_attachments,
    iter_prepare_attachments,
    PreparedAttachments,
)
from services.attachments.evidence import hydrate_message_sources
from services.attachments.retrieval import AttachmentRetriever, Chunk
from services.chat_context import assemble_chat_context, iter_history_blocks
from services.chat_lifecycle import begin_chat_turn, finish_chat_turn


@pytest.fixture(autouse=True)
def configure(monkeypatch, tmp_path):
    monkeypatch.setenv("ATTACHMENT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(
        settings,
        "llm_models",
        json.dumps(
            [
                {
                    "id": "attachment-context",
                    "name": "附件测试",
                    "model": "unmapped-model",
                    "api_key": "test",
                    "base_url": "https://example.test/v1",
                    "tokenizer_encoding": "utf8_bytes",
                }
            ]
        ),
    )
    monkeypatch.setattr(settings, "llm_default_model_id", "attachment-context")


def document_turn(db, user, paragraphs=None):
    key = str(uuid.uuid4())
    attachment = Attachment(
        id=key,
        user_id=user.id,
        client_upload_id=key,
        draft_session_id="files",
        name="讲义.pdf",
        mime_type="application/pdf",
        kind="document",
        size=100,
        sha256="a" * 64,
        storage_key=f"{key}/original.pdf",
        status="ready",
        revision=1,
        topic_id=None,
        mode="normal",
        warnings=[],
        coverage={"recognized_pages": [1]},
    )
    db.add(attachment)
    db.flush()
    for index, text in enumerate(
        paragraphs or ["第一章介绍梯度下降法及其收敛条件。", "第二章解释如何选择学习率。"]
    ):
        db.add(
            AttachmentChunk(
                attachment_id=key,
                revision=1,
                chunk_id=f"page-{index + 1}",
                position=index,
                text=text,
                locator={"page": index + 1},
                block_type="paragraph",
                title_path=[],
                asset_refs=[],
            )
        )
    db.commit()
    started = begin_chat_turn(
        db,
        user_id=user.id,
        topic_id=None,
        session_id="files",
        node_key="normal",
        user_input="",
        mode="normal",
        request_id=str(uuid.uuid4()),
        model_id="attachment-context",
        attachment_ids=[key],
    )
    return attachment, started


def arguments(started, question=""):
    return dict(
        session=started.session,
        user_message_id=started.user_message.id,
        model_id="attachment-context",
        user_input=question,
        mode="normal",
        check_active=lambda: None,
        deadline=monotonic() + 90,
    )


def test_visual_budget_is_fixed_per_image_not_base64_length():
    def messages(data):
        return [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看图"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64," + base64.b64encode(data).decode()
                        },
                    },
                ],
            }
        ]

    assert count_messages(messages(b"small")) == count_messages(messages(b"large" * 1000))
    assert ensure_fits(messages(b"small")) >= IMAGE_TOKEN_ESTIMATE
    with pytest.raises(ValueError, match="data URL"):
        count_messages(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://private.example/image.png"},
                        }
                    ],
                }
            ]
        )


def test_visual_limits_apply_to_the_actual_payload(monkeypatch):
    # Stale per-model flags and oversized token bounds no longer block images.
    config = json.loads(settings.llm_models)
    config[0].update(
        image_input="unsupported", max_images=1, max_image_bytes=3, vision_token_budget=250000
    )
    monkeypatch.setattr(settings, "llm_models", json.dumps(config))
    monkeypatch.setitem(LIMITS, "max_image_bytes", 3)
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,YWJj"}}
    assert ensure_fits([{"role": "user", "content": [image] * 9}]) >= IMAGE_TOKEN_ESTIMATE * 9
    with pytest.raises(ApiError):
        count_messages([{"role": "user", "content": [image] * 10}])
    image["image_url"]["url"] = "data:image/png;base64,YWJjZA=="
    with pytest.raises(ApiError):
        count_messages([{"role": "user", "content": [image]}])


def test_small_document_is_complete_and_default_intent_is_not_saved(db_session, auth_user):
    item, started = document_turn(db_session, auth_user)
    result = prepare_attachments(db_session, **arguments(started))
    assert [s["locator"]["page"] for s in result.sources] == [1, 2]
    prepared = assemble_chat_context(
        db_session,
        session=started.session,
        user_message_id=started.user_message.id,
        model_id="attachment-context",
        node_key="normal",
        node_label="",
        node_sub="",
        user_input="",
        mode="normal",
        ai_style="标准",
        kind="qa",
        attachments=result,
    )
    assert "概括资料" in prepared.messages[-1]["content"]
    assert started.user_message.content == ""
    assert prepared.attachment_derived
    assert "收敛条件" in json.dumps(prepared.messages, ensure_ascii=False)


def test_chinese_ngram_retrieval_hits_far_page_with_neighbors():
    chunks = [Chunk("doc", 1, f"p{i}", i, "普通背景材料" * 80, {"page": i + 1}) for i in range(30)]
    chunks[24] = Chunk(
        "doc", 1, "target", 24, "梯度下降需要降低学习率以达到稳定收敛。", {"page": 25}
    )
    selected = AttachmentRetriever().select(
        chunks, "梯度下降为何收敛", model_id="attachment-context", token_budget=3500
    )
    assert chunks[24] in selected
    assert chunks[23] in selected or chunks[25] in selected
    exact = AttachmentRetriever().select(
        chunks, "第25页", model_id="attachment-context", token_budget=3500
    )
    assert exact == [chunks[24]]


def test_summary_covers_every_block_and_reuses_valid_private_cache(
    db_session, auth_user, monkeypatch
):
    item, started = document_turn(
        db_session, auth_user, [f"第{i}个主题：" + "科学资料内容" * 55 for i in range(60)]
    )
    seen = []

    def call(messages, model_id, timeout):
        seen.extend(json.loads(messages[-1]["content"]))
        assert 0 < timeout <= 90
        return "本组资料概括，保留范围与关键事实。"

    monkeypatch.setattr(summaries, "_call", call)
    events = list(iter_prepare_attachments(db_session, **arguments(started, "总结整份文件")))
    result = events[-1]
    assert isinstance(result, PreparedAttachments)
    assert len(seen) == 60
    assert sum(len(source["covered_chunk_ids"]) for source in result.sources) == 60
    assert any(
        e.get("type") == "attachment_context_progress" for e in events if isinstance(e, dict)
    )
    monkeypatch.setattr(
        summaries, "_call", lambda *_: pytest.fail("Existing complete batches must be reused")
    )
    again = prepare_attachments(db_session, **arguments(started, "总结整份文件"))
    assert [s["covered_chunk_ids"] for s in again.sources] == [
        s["covered_chunk_ids"] for s in result.sources
    ]


def test_cancel_after_batch_prevents_next_call(db_session, auth_user, monkeypatch):
    item, started = document_turn(db_session, auth_user, ["科学资料内容" * 55 for _ in range(60)])
    calls = []
    monkeypatch.setattr(summaries, "_call", lambda *_: calls.append(1) or "分段内容")
    cancelled = False

    def check():
        if cancelled:
            raise ApiError(status_code=409, code="CHAT_REQUEST_CANCELLED", message="取消")

    kwargs = arguments(started, "总结整份文件")
    kwargs["check_active"] = check
    iterator = iter_prepare_attachments(db_session, **kwargs)
    for event in iterator:
        if isinstance(event, dict) and event.get("type") == "attachment_context_progress":
            cancelled = True
            break
    with pytest.raises(ApiError) as caught:
        next(iterator)
    assert caught.value.code == "CHAT_REQUEST_CANCELLED"
    assert len(calls) == 1


def test_deadline_stops_before_model_call(db_session, auth_user, monkeypatch):
    item, started = document_turn(db_session, auth_user)
    monkeypatch.setattr(summaries, "_call", lambda *_: pytest.fail("Deadline expired"))
    kwargs = arguments(started)
    kwargs["deadline"] = monotonic() - 1
    with pytest.raises(ApiError) as caught:
        prepare_attachments(db_session, **kwargs)
    assert caught.value.code == "ATTACHMENT_PREPARATION_TIMEOUT"


def test_file_sources_reject_forged_positions_and_deleted_files(db_session, auth_user):
    item, started = document_turn(db_session, auth_user)
    result = prepare_attachments(db_session, **arguments(started))
    started.ai_message.content = "结论。[[source:s6]]"
    started.ai_message.metadata_json = {"status": "complete", "web": {"sources": result.sources}}
    db_session.commit()
    good = hydrate_message_sources(db_session, user_id=auth_user.id, messages=[started.ai_message])[
        started.ai_message.id
    ]
    assert good[0]["excerpt"] and not good[0].get("deleted")
    started.ai_message.metadata_json = {
        "status": "complete",
        "web": {"sources": [{**result.sources[0], "locator": {"page": 199}}]},
    }
    bad = hydrate_message_sources(db_session, user_id=auth_user.id, messages=[started.ai_message])[
        started.ai_message.id
    ]
    assert bad[0]["deleted"] and not bad[0]["excerpt"]
    started.ai_message.metadata_json = {"status": "complete", "web": {"sources": result.sources}}
    item.status = "deleted"
    db_session.commit()
    deleted = hydrate_message_sources(
        db_session, user_id=auth_user.id, messages=[started.ai_message]
    )[started.ai_message.id]
    assert all(source["deleted"] and not source["excerpt"] for source in deleted)


def test_attachment_only_history_keeps_user_turn_and_provenance(db_session, auth_user):
    item, started = document_turn(db_session, auth_user)
    finish_chat_turn(
        db_session,
        user_id=auth_user.id,
        request_id=started.turn.request_id,
        generation_token=started.turn.generation_token,
        content="资料讨论了学习率。",
        status="complete",
    )
    blocks = list(iter_history_blocks(db_session, started.session))
    assert blocks[0].messages[0]["role"] == "user"
    assert "讲义.pdf" in blocks[0].messages[0]["content"]
    assert "默认处理意图" in blocks[0].messages[0]["content"]
    assert blocks[0].attachment_derived


def test_text_model_may_continue_text_but_must_reject_history_visual_detail(
    db_session, auth_user, monkeypatch
):
    item, started = document_turn(db_session, auth_user)
    item.kind = "image"
    item.name = "示意图.png"
    item.image_key = f"{item.id}/image.png"
    from PIL import Image
    from services.attachments.storage import AttachmentStorage

    path = AttachmentStorage().path(item.image_key)
    path.parent.mkdir(parents=True)
    Image.new("RGB", (4, 4), "blue").save(path)
    db_session.commit()
    finish_chat_turn(
        db_session,
        user_id=auth_user.id,
        request_id=started.turn.request_id,
        generation_token=started.turn.generation_token,
        content="蓝色示意图。",
        status="complete",
    )
    followup = begin_chat_turn(
        db_session,
        user_id=auth_user.id,
        topic_id=None,
        session_id="files",
        node_key="normal",
        user_input="继续学习",
        mode="normal",
        request_id=str(uuid.uuid4()),
        model_id="attachment-context",
    )
    configuration = json.loads(settings.llm_models)
    configuration[0]["image_input"] = "unsupported"
    monkeypatch.setattr(settings, "llm_models", json.dumps(configuration))
    result = prepare_attachments(db_session, **arguments(followup, "继续学习"))
    assert not result.image_parts
    reread = prepare_attachments(db_session, **arguments(followup, "刚才图片中的颜色是什么"))
    assert any(part["type"] == "image_url" for part in reread.image_parts)


@pytest.mark.parametrize("reference", ["filename", "quote"])
def test_explicit_history_image_reference_reloads_without_capability_settings(
    db_session,
    auth_user,
    monkeypatch,
    reference,
):
    from PIL import Image
    from services.attachments.storage import AttachmentStorage

    item, started = document_turn(db_session, auth_user)
    item.kind = "image"
    item.name = "dog.png"
    item.image_key = f"{item.id}/image.png"
    path = AttachmentStorage().path(item.image_key)
    path.parent.mkdir(parents=True)
    Image.new("RGB", (4, 4), "blue").save(path)
    db_session.commit()
    image_context = prepare_attachments(db_session, **arguments(started))
    finish_chat_turn(
        db_session,
        user_id=auth_user.id,
        request_id=started.turn.request_id,
        generation_token=started.turn.generation_token,
        content="蓝色。[[source:s6]]",
        status="complete",
        web={"sources": image_context.sources},
    )
    question = "dog.png 里有什么？" if reference == "filename" else "详细解释一下"
    followup = begin_chat_turn(
        db_session,
        user_id=auth_user.id,
        topic_id=None,
        session_id="files",
        node_key="normal",
        user_input=question,
        mode="normal",
        request_id=str(uuid.uuid4()),
        model_id="attachment-context",
    )
    kwargs = arguments(followup, question)
    if reference == "quote":
        db_session.refresh(started.ai_message)
        kwargs["quote_source"] = started.ai_message
    result = prepare_attachments(db_session, **kwargs)
    assert any(part["type"] == "image_url" for part in result.image_parts)
    configuration = json.loads(settings.llm_models)
    configuration[0]["image_input"] = "unsupported"
    monkeypatch.setattr(settings, "llm_models", json.dumps(configuration))
    assert any(
        part["type"] == "image_url"
        for part in prepare_attachments(db_session, **kwargs).image_parts
    )
    # A source from a different scope cannot trigger private-image loading.
    if reference == "quote":
        from types import SimpleNamespace

        kwargs["quote_source"] = SimpleNamespace(
            user_id=auth_user.id + 1,
            session_id="files",
            topic_id=None,
            mode="normal",
        )
        assert not prepare_attachments(db_session, **kwargs).image_parts
