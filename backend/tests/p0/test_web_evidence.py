import json
import uuid
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from core import ai_client, context_budget
from core.config import LLMProfile, settings
from core.context_budget import ContextWindowExceeded, count_messages, ensure_fits
from models import ChatMessage, User
from services.chat_context import PreparedChatContext, assemble_chat_context, iter_history_blocks
from services.chat_lifecycle import begin_chat_turn, finish_chat_turn
from services.chat_summaries import SessionSummary, run_one_summary_job
from services.web_evidence import (
    apply_web_context,
    cited_source_ids,
    compact_web_references,
    hydrate_summary_web_sources,
    invalid_source_ids,
    message_web_sources,
    resolve_web_references,
)


RETRIEVED_AT = "2026-09-30T16:00:00Z"


def source(source_id="s1", **overrides):
    return {
        "id": source_id,
        "title": f"Release notes {source_id}",
        "url": f"https://docs.example.org/releases/{source_id}",
        "domain": "docs.example.org",
        "excerpt": "The current documented release supports this feature. " * 35,
        "published_at": None,
        "retrieved_at": RETRIEVED_AT,
        **overrides,
    }


def snapshot(*sources, **overrides):
    return {
        "schema_version": 1,
        "strategy_version": "auto-v1",
        "config_version": "test",
        "requested_mode": "auto",
        "status": "ready",
        "decision": {"need_search": True},
        "queries": ["current release"],
        "searched_at": RETRIEVED_AT,
        "sources": list(sources) or [source()],
        "cited_source_ids": [],
        "error_code": None,
        "warnings": [],
        "metrics": {"search_queries": 1},
        **overrides,
    }


@pytest.fixture
def profile(monkeypatch):
    def configure(**overrides):
        configured = LLMProfile(
            id="evidence-test",
            name="Evidence test",
            model="unknown-evidence-model",
            api_key="test-key",
            base_url="https://llm.example.test/v1",
            **overrides,
        )
        monkeypatch.setattr(context_budget, "resolve_llm_profile", lambda *_: configured)
        monkeypatch.setattr(ai_client, "resolve_llm_profile", lambda *_args, **_kwargs: configured)
        return configured

    configure()
    monkeypatch.setattr(settings, "web_evidence_tokens", 4000)
    return configure


def prepared_context():
    messages = [
        {"role": "system", "content": "Answer the current question."},
        {"role": "user", "content": "We discussed the tool's 2025 release."},
        {"role": "assistant", "content": "The previous claim must remain available."},
        {"role": "user", "content": "Does it still apply to the latest release?"},
    ]
    return PreparedChatContext(messages, messages[1:-1], [], count_messages(messages), False, False)


def test_evidence_budget_preserves_history_and_limits_saved_and_injected_sources(profile):
    prepared = prepared_context()
    web = snapshot(*(source(f"s{index}", excerpt="长片段内容" * 600) for index in range(1, 6)))
    originals = deepcopy((prepared, web))

    result, saved = apply_web_context(prepared, web, "evidence-test")

    assert (prepared, web) == originals
    assert all(message in result.messages for message in prepared.messages)
    assert result.messages[-1] == prepared.messages[-1]
    assert result.history == prepared.history
    assert saved["status"] == "ready"
    assert 0 < len(saved["sources"]) < 5
    assert result.input_tokens == ensure_fits(result.messages, "evidence-test")
    assert result.input_tokens - prepared.input_tokens <= settings.web_evidence_tokens
    evidence = next(m for m in result.messages if m["content"].startswith("本轮联网参考资料"))
    assert json.loads(evidence["content"].split("\n", 1)[1]) == saved["sources"]
    assert saved["metrics"] == web["metrics"]
    assert any(warning["code"] == "WEB_EVIDENCE_TRUNCATED" for warning in saved["warnings"])


def test_small_remaining_window_fails_evidence_without_removing_history(profile):
    prepared = prepared_context()
    profile(max_input_tokens=prepared.input_tokens + 500)
    result, web = apply_web_context(prepared, snapshot(), "evidence-test")
    assert web["status"] == "failed"
    assert web["error_code"] == "WEB_EVIDENCE_INSUFFICIENT"
    assert web["sources"] == []
    assert all(message in result.messages for message in prepared.messages)
    assert any("未取得可用联网证据" in message["content"] for message in result.messages)
    ensure_fits(result.messages, "evidence-test")


def test_full_window_rejects_instead_of_silently_losing_honesty_instruction(profile):
    prepared = prepared_context()
    profile(max_input_tokens=prepared.input_tokens)
    with pytest.raises(ContextWindowExceeded):
        apply_web_context(prepared, snapshot(), "evidence-test")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("off", "联网已关闭"),
        ("skipped", "未执行新搜索"),
        ("failed", "未取得可用联网证据"),
        ("unavailable", "未取得可用联网证据"),
    ],
)
def test_unsearched_modes_have_truthful_instructions_and_no_evidence(profile, status, expected):
    result, web = apply_web_context(
        prepared_context(),
        snapshot(status=status, requested_mode="off" if status == "off" else "auto"),
        "evidence-test",
    )
    assert web["sources"] == []
    assert any(expected in message["content"] for message in result.messages)
    assert not any("本轮联网参考资料" in message["content"] for message in result.messages)


def test_partial_search_keeps_usable_sources_and_does_not_claim_total_failure(profile):
    result, saved = apply_web_context(
        prepared_context(),
        snapshot(
            warnings=[{"code": "WEB_SEARCH_FAILED", "message": "部分搜索失败", "retryable": True}]
        ),
        "evidence-test",
    )
    assert saved["status"] == "ready"
    assert saved["sources"]
    assert any("部分可用资料" in message["content"] for message in result.messages)
    assert not any("未取得可用联网证据" in message["content"] for message in result.messages)


def test_unsupported_url_reading_does_not_invite_model_to_invent_page_contents(profile):
    result, saved = apply_web_context(
        prepared_context(),
        snapshot(status="skipped", error_code="WEB_URL_FETCH_UNSUPPORTED"),
        "evidence-test",
    )
    assert saved["sources"] == []
    assert any("未读取该网页" in message["content"] for message in result.messages)
    assert any("提供正文" in message["content"] for message in result.messages)


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://user:secret@example.org",
        "http://127.0.0.1/",
        "https://localhost/",
    ],
)
def test_unsafe_snapshot_sources_cannot_be_injected_or_restored(profile, url):
    result, web = apply_web_context(prepared_context(), snapshot(source(url=url)), "evidence-test")
    assert web["sources"] == []
    assert url not in json.dumps(result.messages)


@pytest.mark.parametrize(
    ("content", "valid", "invalid"),
    [
        ("[[source:s2]][[source:s1]] and [[source:s2]] [[source:s99]]", ["s2", "s1"], ["s99"]),
        ("`[[source:s1]]` prose [[source:s2]]", ["s2"], []),
        ("``a ` [[source:s1]]\n still code`` [[source:s2]]", ["s2"], []),
        ("```python\n[[source:s1]]\n```\n[[source:s2]]", ["s2"], []),
        ("````\n```\n[[source:s1]]\n````\n[[source:s2]]", ["s2"], []),
        ("~~~\n[[source:s99]]\n~~~\n[[source:s1]]", ["s1"], []),
        ("[[source:s2]]\n```\n[[source:s1]]", ["s2"], []),
        ("    [[source:s99]]\n\t[[source:s1]]\n[[source:s2]]", ["s2"], []),
        (r"\[[source:s1]] \\[[source:s2]]", ["s2"], []),
        ("<code>[[source:s1]]</code> <pre>[[source:s99]]</pre> [[source:s2]]", ["s2"], []),
        ("[label [[source:s1]]](https://example.org) [[source:s2]]", ["s2"], []),
        ("[label [[source:s1]]][docs] [[source:s2]]\n\n[docs]: https://example.org", ["s2"], []),
        ("> ```\n> [[source:s99]]\n> ```\n[[source:s1]]", ["s1"], []),
        ("[[source:invented]] and `[[source:s99]]`", [], ["invented"]),
    ],
)
def test_citations_ignore_examples_and_links_and_share_invalid_marker_rules(
    content, valid, invalid
):
    sources = [source("s1"), source("s2")]
    assert cited_source_ids(content, sources) == valid
    assert invalid_source_ids(content, sources) == invalid


def add_turn(
    db, user, content="Original claim [[source:s1]]", *, session_id="web-session", web=None
):
    request_id = str(uuid.uuid4())
    started = begin_chat_turn(
        db,
        user_id=user.id,
        topic_id=None,
        session_id=session_id,
        node_key="normal",
        user_input=f"Question {request_id}",
        mode="normal",
        request_id=request_id,
        model_id="evidence-test",
    )
    assert finish_chat_turn(
        db,
        user_id=user.id,
        request_id=request_id,
        generation_token=started.turn.generation_token,
        content=content,
        status="complete",
        web=web or snapshot(source(), source("s2")),
    )
    db.refresh(started.ai_message)
    return started


def assemble(db, started, **overrides):
    return assemble_chat_context(
        db,
        session=started.session,
        user_message_id=started.ai_message.id + 100,
        model_id="evidence-test",
        node_key="normal",
        node_label="",
        node_sub="",
        user_input="Is that still true?",
        mode="normal",
        ai_style="标准",
        kind="qa",
        **overrides,
    )


def test_history_reconstructs_only_persisted_actual_references_without_excerpts(
    db_session, auth_user, profile
):
    started = add_turn(db_session, auth_user)
    metadata = deepcopy(started.ai_message.metadata_json)
    metadata["web"]["cited_source_ids"] = ["s2"]  # stale checkpoint must not authorize a tail
    started.ai_message.metadata_json = metadata
    db_session.commit()

    block = next(iter_history_blocks(db_session, started.session))
    assert block.web_references == [
        {"message_id": started.ai_message.id, "source_id": "s1", "retrieved_at": RETRIEVED_AT}
    ]
    text = block.messages[-1]["content"]
    assert source()["url"] in text
    assert source("s2")["url"] not in text
    assert source()["excerpt"] not in text
    assert "本轮未重新核实" in text


def test_explicit_quote_keeps_source_mapping_once_and_excludes_duplicate_answer(
    db_session, auth_user, profile
):
    started = add_turn(db_session, auth_user)
    prepared = assemble(db_session, started, quote_source=started.ai_message)
    text = json.dumps(prepared.messages, ensure_ascii=False)
    assert text.count("Original claim") == 1
    assert text.count(source()["url"]) == 1
    assert source()["excerpt"] not in text
    assert "本条回答原文见用户引用的消息" in text


def test_summary_hydration_rejects_foreign_deleted_and_date_mismatched_sources(
    db_session, auth_user, profile
):
    own = add_turn(db_session, auth_user)
    foreign_user = User(
        username="foreign-web", email="foreign-web@example.org", hashed_password="unused"
    )
    db_session.add(foreign_user)
    db_session.commit()
    foreign = add_turn(db_session, foreign_user)
    valid = compact_web_references(message_web_sources(own.ai_message))[0]
    denied = compact_web_references(message_web_sources(foreign.ai_message))[0]
    references = [valid, denied, {**valid, "retrieved_at": "2025-01-01T00:00:00Z"}]
    hydrated = hydrate_summary_web_sources(
        db_session,
        own.session,
        {"web_references": references, "web_sources": [{"url": "https://invented.example/"}]},
    )
    assert hydrated["web_references"] == [valid]
    assert hydrated["web_sources"] == message_web_sources(own.ai_message)
    db_session.delete(own.ai_message)
    db_session.commit()
    assert resolve_web_references(db_session, own.session, references) == []


def run_summary(db_session, session, generate):
    session.summary_status = "pending"
    db_session.commit()

    def factory():
        return Session(bind=db_session.get_bind(), expire_on_commit=False)

    assert run_one_summary_job(factory, generate, target_session_id=session.id, force=True)
    db_session.refresh(session)


def summary_value(messages, **overrides):
    payload = json.loads(messages[-1]["content"])
    data = {
        "goal": "Check the release as of September 2026",
        "conclusions": [
            "A release feature was discussed; current validity still requires verification."
        ],
        "unresolved": [],
        "node_keys": ["normal"],
        "source_message_ids": [
            message_id for turn in payload["turns"] for message_id in turn["message_ids"]
        ],
        "web_references": [
            reference for turn in payload["turns"] for reference in turn["web_references"]
        ],
        **overrides,
    }
    return SimpleNamespace(value=SessionSummary.model_validate(data), token_usage=100)


def test_summary_preserves_only_input_web_references_and_rehydrates_original_urls(
    db_session, auth_user, profile
):
    first = add_turn(db_session, auth_user, "Original claim [[source:s1]] " + "discussion " * 1500)
    add_turn(db_session, auth_user, "Latest answer stays verbatim.")
    captured = []

    def generate(_schema, messages, _context):
        captured.append(json.loads(messages[-1]["content"]))
        return summary_value(messages)

    run_summary(db_session, first.session, generate)
    assert first.session.summary_json is not None
    refs = first.session.summary_json["web_references"]
    assert refs == [
        {"message_id": first.ai_message.id, "source_id": "s1", "retrieved_at": RETRIEVED_AT}
    ]
    assert set(refs[0]) == {"message_id", "source_id", "retrieved_at"}
    assert "检索时间不是发布时间" in str(captured)
    prepared = assemble(db_session, first)
    assert source()["url"] in str(prepared.messages)
    assert source()["excerpt"] not in str(prepared.messages)


@pytest.mark.parametrize(
    "corruption",
    ["unknown_source", "wrong_date", "outside_input", "invented_url", "lost_ownership"],
)
def test_summary_rejects_fabricated_or_no_longer_authorized_web_reference(
    db_session, auth_user, profile, corruption
):
    first = add_turn(db_session, auth_user, "Original claim [[source:s1]] " + "discussion " * 1500)
    latest = add_turn(db_session, auth_user)
    reference = compact_web_references(message_web_sources(first.ai_message))[0]

    def generate(_schema, messages, _context):
        corrupted = {**reference}
        if corruption == "unknown_source":
            corrupted["source_id"] = "s99"
        elif corruption == "wrong_date":
            corrupted["retrieved_at"] = "2025-01-01T00:00:00Z"
        elif corruption == "outside_input":
            corrupted["message_id"] = latest.ai_message.id
        elif corruption == "invented_url":
            corrupted["url"] = "https://invented.example/"
        else:
            db_session.query(ChatMessage).filter_by(id=first.ai_message.id).update(
                {"session_id": "another-session"}
            )
            db_session.commit()
        return summary_value(messages, web_references=[corrupted])

    run_summary(db_session, first.session, generate)
    assert first.session.summary_status == "failed"
    assert first.session.summary_json is None


def test_summary_without_actual_web_citations_saves_empty_reference_list(
    db_session, auth_user, profile
):
    first = add_turn(
        db_session,
        auth_user,
        "Stable explanation and a code example `[[source:s1]]`. " + "discussion " * 1500,
    )
    add_turn(db_session, auth_user, "A latest answer without citations.")
    run_summary(
        db_session, first.session, lambda _schema, messages, _context: summary_value(messages)
    )
    assert first.session.summary_json["web_references"] == []


def test_summary_provider_exception_does_not_log_queries_or_source_content(
    db_session, auth_user, profile, caplog
):
    first = add_turn(db_session, auth_user, "Original claim [[source:s1]] " + "discussion " * 1500)
    add_turn(db_session, auth_user, "Latest answer.")

    def fail(_schema, _messages, _context):
        raise RuntimeError("private-query-secret provider echoed source text")

    run_summary(db_session, first.session, fail)
    assert first.session.summary_status == "failed"
    assert "RuntimeError" in caplog.text
    assert "private-query-secret" not in caplog.text
    assert "provider echoed" not in caplog.text
