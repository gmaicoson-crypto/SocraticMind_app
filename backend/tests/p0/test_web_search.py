import json
import logging
import threading
from time import monotonic
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from core.config import settings
from schemas.web_search import SearchDecision, WebSnapshot
from services import web_search as web


@pytest.fixture(autouse=True)
def isolated_search(monkeypatch):
    monkeypatch.setattr(settings, "llm_models", "")
    monkeypatch.setattr(settings, "llm_default_model_id", "")
    monkeypatch.setattr(settings, "llm_model", "test-model")
    monkeypatch.setattr(settings, "web_search_enabled", True)
    monkeypatch.setattr(settings, "tavily_api_key", "test-key")
    monkeypatch.setattr(settings, "web_search_api_base", "https://api.tavily.test")
    monkeypatch.setattr(settings, "web_decision_timeout_seconds", 0.15)
    monkeypatch.setattr(settings, "web_search_timeout_seconds", 0.15)
    monkeypatch.setattr(settings, "web_decision_input_tokens", 12000)
    executor = web.BoundedExecutor(3, 1)
    monkeypatch.setattr(web, "_get_executor", lambda: executor)
    yield
    executor.shutdown()


def decision(*queries, reason="current_information", freshness="month"):
    return SimpleNamespace(
        value=SearchDecision(
            need_search=bool(queries),
            queries=list(queries),
            reason_code=reason,
            freshness=freshness,
        ),
        token_usage=12,
    )


def source(url="https://example.com/releases", *, score=0.8):
    return {
        "title": "Release",
        "url": url,
        "domain": "example.com",
        "excerpt": "Evidence",
        "published_at": None,
        "retrieved_at": "2026-09-30T00:00:00Z",
        "_score": score,
    }


def collect(monkeypatch, outcome=None, provider=None, **overrides):
    monkeypatch.setattr(
        web, "generate_structured", lambda *a, **k: outcome or decision("Vue releases")
    )
    if provider:
        monkeypatch.setattr(web.TavilySearchProvider, "search", provider)
    params = {
        "web_mode": "auto",
        "model_id": "default",
        "user_input": "最新版有哪些变化？",
        "context_messages": [],
        "request_id": "test",
        "user_id": 1,
        "check_active": lambda: None,
        "reserve_search": lambda count: True,
    }
    params.update(overrides)
    return list(web.iter_web_search(**params))


@pytest.mark.parametrize(
    "payload",
    [
        {"need_search": True, "queries": [], "freshness": "any", "reason_code": "explicit_search"},
        {
            "need_search": False,
            "queries": ["q"],
            "freshness": "any",
            "reason_code": "stable_knowledge",
        },
        {
            "need_search": True,
            "queries": ["q"],
            "freshness": "any",
            "reason_code": "user_restricted",
        },
        {
            "need_search": True,
            "queries": ["q", "q"],
            "freshness": "any",
            "reason_code": "explicit_search",
        },
        {
            "need_search": True,
            "queries": ["q"],
            "freshness": "any",
            "reason_code": "explicit_search",
            "reasoning": "private",
        },
        {
            "need_search": "true",
            "queries": ["q"],
            "freshness": "any",
            "reason_code": "explicit_search",
        },
    ],
)
def test_decision_contract_rejects_invalid_states(payload):
    with pytest.raises(ValidationError):
        SearchDecision.model_validate(payload)


@pytest.mark.parametrize(
    "mode,enabled,key,status,code",
    [
        ("off", True, "key", "off", None),
        ("auto", False, "key", "unavailable", "WEB_UNAVAILABLE"),
        ("auto", True, "", "unavailable", "WEB_UNAVAILABLE"),
    ],
)
def test_off_and_unavailable_do_not_call_models_or_reserve(
    monkeypatch, mode, enabled, key, status, code
):
    monkeypatch.setattr(settings, "web_search_enabled", enabled)
    monkeypatch.setattr(settings, "tavily_api_key", key)

    def forbidden(*args, **kwargs):
        pytest.fail("must not call outside service")

    monkeypatch.setattr(web, "generate_structured", forbidden)
    events = list(
        web.iter_web_search(
            web_mode=mode,
            model_id="default",
            user_input="x",
            context_messages=[],
            request_id="r",
            user_id=1,
            check_active=lambda: None,
            reserve_search=forbidden,
        )
    )
    assert events[-1]["web"]["status"] == status
    assert events[-1]["web"]["error_code"] == code
    assert web.web_search_capabilities()["web_search"]["available"] == bool(enabled and key)


@pytest.mark.parametrize("reason", ["stable_knowledge", "user_restricted", "insufficient_context"])
def test_semantic_skip_never_reserves_or_searches(monkeypatch, reason):
    def forbidden(*args):
        pytest.fail("skipped decision must not reserve")

    events = collect(monkeypatch, decision(reason=reason), reserve_search=forbidden)
    assert events[-1]["web"]["status"] == "skipped"
    assert events[-1]["web"]["queries"] == []


def test_url_fulltext_request_honestly_warns(monkeypatch):
    events = collect(monkeypatch, decision(reason="unsupported_url_fetch"))
    assert events[-1]["warning"]["code"] == "WEB_URL_FETCH_UNSUPPORTED"
    assert events[-1]["web"]["status"] == "skipped"


def test_quota_denial_happens_before_any_provider_call(monkeypatch):
    reserved = []

    def forbidden(*args):
        pytest.fail("quota-denied search must not run")

    events = collect(
        monkeypatch,
        decision("first", "second"),
        forbidden,
        reserve_search=lambda count: reserved.append(count) or False,
    )
    assert reserved == [2]
    assert events[-1]["warning"]["code"] == "WEB_QUOTA_EXCEEDED"


def test_selected_model_policy_context_and_secrets(monkeypatch):
    calls = []

    def generate(*args, **kwargs):
        calls.append((args, kwargs))
        return decision(reason="user_restricted")

    monkeypatch.setattr(web, "generate_structured", generate)
    list(
        web.iter_web_search(
            web_mode="auto",
            model_id="default",
            user_input="它还适用吗？password=private-token",
            context_messages=[
                {"role": "system", "content": "DO NOT UPLOAD FULL MEMORY"},
                {"role": "user", "content": "我在使用 Vue"},
                {"role": "assistant", "content": "了解"},
            ],
            request_id="r",
            user_id=1,
            check_active=lambda: None,
            reserve_search=lambda count: True,
        )
    )
    args, kwargs = calls[0]
    assert args[2].model == "default"
    assert kwargs["max_repairs"] == 0
    assert kwargs["output_tokens"] == settings.web_decision_output_tokens
    assert kwargs["timeout"] <= settings.web_decision_timeout_seconds
    prompt = json.dumps(args[1], ensure_ascii=False)
    assert "Vue" in prompt and "它还适用吗" in prompt
    assert "private-token" not in prompt and "DO NOT UPLOAD FULL MEMORY" not in prompt
    assert "user_restricted" in prompt and "UTC" in prompt


def test_secret_query_blocked_before_quota_or_external_transfer(monkeypatch, caplog):
    def forbidden(*args):
        pytest.fail("secret query must not be reserved")

    events = collect(monkeypatch, decision("api_key=private-value"), reserve_search=forbidden)
    assert events[-1]["warning"]["code"] == "WEB_DECISION_FAILED"
    assert events[-1]["web"]["queries"] == []
    assert "private-value" not in caplog.text


def test_oversized_current_question_is_not_silently_truncated(monkeypatch):
    events = collect(monkeypatch, user_input="重要问题" * 5000)
    assert events[-1]["warning"]["code"] == "WEB_DECISION_FAILED"
    assert events[-1]["web"]["decision"] is None


def test_success_deduplicates_ranks_and_limits_sources(monkeypatch):
    main_thread = threading.get_ident()
    reserved = []

    def provider(self, query, freshness, deadline, cancelled):
        assert threading.get_ident() != main_thread
        assert freshness == "month"
        suffix = "second" if query == "second" else "first"
        return web.SearchResult(
            [
                source(),
                *[source(f"https://example.com/{suffix}-{i}", score=i / 10) for i in range(7)],
            ],
            credits=1,
        )

    def reserve(count):
        assert threading.get_ident() == main_thread
        reserved.append(count)
        return True

    events = collect(monkeypatch, decision("first", "second"), provider, reserve_search=reserve)
    assert reserved == [2]
    result = events[-1]
    assert result["type"] == "web_sources" and result["final"] is False
    snapshot = result["web"]
    WebSnapshot.model_validate(snapshot)
    assert snapshot["status"] == "ready" and snapshot["metrics"]["search_credits"] == 2
    assert len(snapshot["sources"]) == 5
    assert [s["id"] for s in snapshot["sources"]] == ["s1", "s2", "s3", "s4", "s5"]
    assert snapshot["sources"][0]["url"] == "https://example.com/releases"
    assert len({s["url"] for s in snapshot["sources"]}) == 5
    assert events[0]["web"]["sources"] == []  # Immutable emitted state.


def test_partial_results_survive_one_query_failure(monkeypatch):
    def provider(self, query, *_):
        if query == "second":
            raise web.SearchProviderError("unavailable")
        return web.SearchResult([source()], credits=1)

    events = collect(monkeypatch, decision("first", "second"), provider)
    assert events[-1]["web"]["status"] == "ready"
    assert events[-1]["web"]["error_code"] == "WEB_SEARCH_FAILED"
    assert len(events[-1]["web"]["sources"]) == 1
    assert events[-1]["web"]["metrics"]["search_credits"] is None


def test_search_deadline_keeps_partial_results_and_shared_budget(monkeypatch):
    release = threading.Event()

    def provider(self, query, *_):
        if query == "slow":
            release.wait(2)
        return web.SearchResult([source()], credits=1)

    started = monotonic()
    try:
        events = collect(monkeypatch, decision("fast", "slow"), provider)
        assert monotonic() - started < 0.8
        assert events[-1]["web"]["status"] == "ready"
        assert events[-1]["web"]["warnings"][0]["code"] == "WEB_SEARCH_FAILED"
    finally:
        release.set()


def test_decision_timeout_leaves_worker_slot_occupied(monkeypatch):
    executor = web.BoundedExecutor(1, 0)
    monkeypatch.setattr(web, "_get_executor", lambda: executor)
    release, entered = threading.Event(), threading.Event()

    def slow(*args, **kwargs):
        entered.set()
        release.wait(2)
        return decision("query")

    monkeypatch.setattr(web, "generate_structured", slow)
    try:
        events = list(
            web.iter_web_search(
                web_mode="auto",
                model_id="default",
                user_input="latest?",
                context_messages=[],
                request_id="r",
                user_id=1,
                check_active=lambda: None,
                reserve_search=lambda _: True,
            )
        )
        assert entered.is_set()
        assert events[-1]["warning"]["code"] == "WEB_DECISION_FAILED"
        with pytest.raises(web.CapacityExceeded):
            executor.submit(lambda: None)
    finally:
        release.set()
        executor.shutdown()


def test_finished_worker_releases_slot_before_future_callbacks(monkeypatch):
    executor = web.BoundedExecutor(1, 0)
    callbacks = []

    class DeferredCallbacksFuture:
        def add_done_callback(self, callback):
            callbacks.append(callback)

        def cancelled(self):
            return False

    def submit(function, *args, **kwargs):
        function(*args, **kwargs)
        return DeferredCallbacksFuture()

    try:
        monkeypatch.setattr(executor._executor, "submit", submit)
        executor.submit(lambda: None)
        executor.submit(lambda: None)
        assert len(callbacks) == 2
    finally:
        executor.shutdown()


def test_cancelled_queued_worker_releases_slot():
    executor = web.BoundedExecutor(1, 1)
    entered, release = threading.Event(), threading.Event()

    def slow():
        entered.set()
        release.wait(2)

    try:
        first = executor.submit(slow)
        assert entered.wait(1)
        queued = executor.submit(lambda: None)
        assert queued.cancel()
        replacement = executor.submit(lambda: None)
        release.set()
        first.result(timeout=1)
        replacement.result(timeout=1)
    finally:
        release.set()
        executor.shutdown()


@pytest.mark.parametrize("stage", ["decision", "search"])
def test_cancellation_propagates_during_wait_on_main_thread(monkeypatch, stage):
    entered, release = threading.Event(), threading.Event()
    main_thread = threading.get_ident()

    class Cancelled(Exception):
        pass

    def slow(*args, **kwargs):
        entered.set()
        release.wait(2)
        return decision("query") if stage == "decision" else web.SearchResult([source()])

    monkeypatch.setattr(
        web, "generate_structured", slow if stage == "decision" else lambda *a, **k: decision("q")
    )
    monkeypatch.setattr(web.TavilySearchProvider, "search", slow)

    def check():
        assert threading.get_ident() == main_thread
        if entered.is_set():
            raise Cancelled("stop")

    try:
        with pytest.raises(Cancelled):
            list(
                web.iter_web_search(
                    web_mode="auto",
                    model_id="default",
                    user_input="latest?",
                    context_messages=[],
                    request_id="r",
                    user_id=1,
                    check_active=check,
                    reserve_search=lambda _: True,
                )
            )
    finally:
        release.set()


def test_provider_basic_payload_size_url_and_dates(monkeypatch):
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://EXAMPLE.com:443/releases?utm_source=tracker&a=2#top",
                        "title": "A",
                        "content": "x" * 5000,
                        "published_date": "Tue, 11 Mar 2025 17:00:00 GMT",
                        "score": 0.9,
                    },
                    {"url": "javascript:alert(1)", "content": "bad"},
                    {
                        "url": "https://example.com/undated",
                        "content": "body",
                        "published_date": "nonsense",
                    },
                ],
                "usage": {"credits": 1},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = web.TavilySearchProvider(client=client).search(
            "Vue release", "week", monotonic() + 1, threading.Event()
        )
    payload = json.loads(captured[0].content)
    assert payload["query"] == "Vue release" and payload["time_range"] == "week"
    assert payload["search_depth"] == "basic" and payload["auto_parameters"] is False
    assert payload["include_answer"] is False and payload["include_raw_content"] is False
    assert captured[0].headers["authorization"] == "Bearer test-key"
    assert len(result.sources) == 2
    assert result.sources[0]["url"] == "https://example.com/releases?a=2"
    assert len(result.sources[0]["excerpt"]) == 2400
    assert result.sources[0]["published_at"] == "2025-03-11T17:00:00Z"
    assert result.sources[1]["published_at"] is None
    assert result.credits == 1


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/plain,bad",
        "https://user:pass@example.com",
        "http://127.0.0.1/",
        "http://localhost/a",
        "https://example.com\\@evil.test",
        "https://example.com/\nfoo",
    ],
)
def test_unsafe_source_urls_rejected(url):
    assert web.canonical_source_url(url) is None


def test_provider_body_budget_prevents_unbounded_result(monkeypatch):
    monkeypatch.setattr(settings, "web_search_max_response_bytes", 1024)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"a" * 1025))
    ) as client:
        with pytest.raises(web.SearchProviderError, match="超出预算"):
            web.TavilySearchProvider(client=client).search(
                "q", "any", monotonic() + 1, threading.Event()
            )


def test_provider_does_not_follow_redirect_or_retry():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://localhost/private"})

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        with pytest.raises(web.SearchProviderError):
            web.TavilySearchProvider(client=client).search(
                "q", "any", monotonic() + 1, threading.Event()
            )
    assert len(requests) == 1


def test_empty_successful_search_is_distinct_from_provider_failure(monkeypatch):
    events = collect(monkeypatch, provider=lambda *args: web.SearchResult([], credits=1))
    snapshot = events[-1]["web"]
    assert snapshot["status"] == "failed"
    assert snapshot["error_code"] == "WEB_NO_RESULTS"
    assert snapshot["metrics"]["search_credits"] == 1
    assert snapshot["sources"] == []


def test_failed_decision_does_not_expose_provider_exception(monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise RuntimeError("secret-provider-payload")

    monkeypatch.setattr(web, "generate_structured", fail)
    logger = logging.getLogger(web.__name__)
    logger.disabled = False
    with caplog.at_level(logging.INFO, logger=logger.name):
        events = list(
            web.iter_web_search(
                web_mode="auto",
                model_id="default",
                user_input="private-question",
                context_messages=[],
                request_id="safe-r",
                user_id=1,
                check_active=lambda: None,
                reserve_search=lambda _: True,
            )
        )
    assert events[-1]["warning"]["code"] == "WEB_DECISION_FAILED"
    assert "secret-provider-payload" not in json.dumps(events)
    assert "secret-provider-payload" not in caplog.text
    assert "private-question" not in caplog.text
    assert "safe-r" in caplog.text


def test_results_completed_after_deadline_are_not_accepted():
    executor = web.BoundedExecutor(1, 0)
    deadline = monotonic() - 0.1
    try:
        future = executor.submit(lambda: "late")
        future.result(timeout=1)
        assert web._wait_finished([future], deadline, lambda: None) == []
    finally:
        executor.shutdown()


def test_quota_callback_cancellation_is_not_search_fallback(monkeypatch):
    class LostLease(Exception):
        pass

    def reserve(count):
        raise LostLease("lease")

    with pytest.raises(LostLease):
        collect(monkeypatch, reserve_search=reserve)


@pytest.mark.parametrize(
    "url",
    [
        "https://<script>.example/",
        "http://127.1/",
        "http://2130706433/",
        "http://0x7f.0.0.1/",
        "https://example.com/?q=" + "汉" * 700,
    ],
)
def test_malformed_or_alternate_local_urls_are_rejected(url):
    assert web.canonical_source_url(url) is None


def test_unknown_decision_usage_is_not_recorded_as_zero(monkeypatch):
    outcome = decision(reason="stable_knowledge")
    outcome.token_usage, outcome.usage_known = 0, False
    events = collect(monkeypatch, outcome=outcome)
    assert events[-1]["web"]["metrics"]["decision_tokens"] is None


def test_old_explicit_quote_and_node_are_preserved_before_recent_history():
    user_input = "这个说法有依据吗？"
    current = "当前学习节点：Vue（版本管理）\n\n学生说：" + user_input
    notes = [
        "用户明确引用的消息原文（消息 4）：\nVue 2 已终止维护。",
        "自动摘要：这是可选历史，不应上传决策模型。",
    ]
    context = [
        {"role": "system", "content": "完整学习记忆不用上传"},
        {
            "role": "user",
            "content": "上下文参考资料（JSON 数据）：\n" + json.dumps(notes, ensure_ascii=False),
        },
        {"role": "user", "content": "上一轮问题"},
        {"role": "assistant", "content": "上一轮回答"},
        {"role": "user", "content": "最新一轮问题"},
        {"role": "assistant", "content": "最新一轮回答"},
        {"role": "user", "content": current},
    ]
    messages = web._decision_messages("default", user_input, context)
    content = json.dumps(messages, ensure_ascii=False)
    assert "Vue 2 已终止维护" in content
    assert "上一轮问题" in content and "最新一轮问题" in content
    assert content.count(user_input) == 1
    assert content.count("当前学习节点") == 1
    assert "这是可选历史" not in content and "完整学习记忆不用上传" not in content


def test_oversized_explicit_quote_is_never_silently_dropped(monkeypatch):
    notes = ["用户明确引用的消息原文（消息 4）：\n" + "必要原文" * 6000]
    context = [
        {
            "role": "user",
            "content": "上下文参考资料（JSON 数据）：\n" + json.dumps(notes, ensure_ascii=False),
        },
        {"role": "user", "content": "最新一轮问题"},
        {"role": "assistant", "content": "最新一轮回答"},
    ]
    events = collect(monkeypatch, context_messages=context)
    assert events[-1]["warning"]["code"] == "WEB_DECISION_FAILED"
    assert events[-1]["web"]["decision"] is None
