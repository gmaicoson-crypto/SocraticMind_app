from types import SimpleNamespace

import pytest
import tiktoken
import httpx
from openai import BadRequestError
from pydantic import ValidationError

from ai.agent import ChatStreamError, build_chat_messages, chat_stream
from core import context_budget
from core.config import LLMConfig, LLMProfile
from core.context_budget import (
    ContextWindowExceeded,
    completion_options,
    count_messages,
    count_method,
    count_text,
    ensure_fits,
    get_context_policy,
)


@pytest.fixture
def configure_profile(monkeypatch):
    def configure(**overrides):
        profile = LLMProfile(
            id="budget-test",
            name="Budget test",
            api_key="test-key",
            base_url="https://example.test/v1",
            **{"model": "unknown-compatible-model", **overrides},
        )
        monkeypatch.setattr(context_budget, "resolve_llm_profile", lambda _: profile)
        monkeypatch.setattr("ai.agent.resolve_llm_profile", lambda _: profile)
        return profile

    return configure


def test_256k_policy_reserves_generation_and_safety_space(configure_profile):
    configure_profile()
    policy = get_context_policy()
    assert policy.context_window_tokens == 256_000
    assert policy.hard_input_limit == 243_712
    assert policy.target_input_tokens == 64_000
    assert policy.summary_trigger_tokens == 48_000
    assert policy.summary_target_tokens == 32_000
    assert policy.output_tokens == 4_096


def test_service_input_limit_and_larger_generation_reduce_input_budget(configure_profile):
    configure_profile(max_input_tokens=50_000, max_output_tokens=16_384, output_tokens=8_192)
    policy = get_context_policy()
    assert policy.hard_input_limit == 50_000
    assert policy.target_input_tokens == 50_000
    assert completion_options() == {"max_tokens": 8_192}


@pytest.mark.parametrize("model", ["gpt-5", "custom-reasoning-service"])
def test_reasoning_budget_reserves_the_same_total_sent_to_provider(configure_profile, model):
    configure_profile(
        model=model,
        max_output_tokens=16_384,
        reasoning_output_tokens=12_288,
        completion_token_parameter="max_completion_tokens",
    )
    policy = get_context_policy()
    assert policy.output_tokens == 12_288
    assert policy.hard_input_limit == 256_000 - 12_288 - 8_192
    assert completion_options() == {"max_completion_tokens": 12_288}


def test_reasoning_budget_does_not_guess_a_service_output_limit(configure_profile):
    configure_profile(model="gpt-5")
    assert get_context_policy().output_tokens == 4_096
    with pytest.raises(ValidationError, match="最大输出额度"):
        configure_profile(reasoning_output_tokens=16_384)
    with pytest.raises(ValidationError, match="上下文窗口"):
        configure_profile(
            context_window_tokens=20_000,
            max_output_tokens=16_384,
            reasoning_output_tokens=16_384,
        )


def test_invalid_capacity_and_summary_thresholds_are_rejected():
    required = {
        "model": "test",
        "api_key": "test",
        "base_url": "https://example.test",
        "name": "Test",
    }
    for overrides in (
        {"output_tokens": 8_192},
        {"context_window_tokens": 12_288},
        {"summary_target_tokens": 48_000},
        {"summary_trigger_tokens": 65_000},
    ):
        with pytest.raises(ValidationError):
            LLMConfig(**required, **overrides)


def test_unknown_model_counts_utf8_bytes_and_all_message_fields(configure_profile):
    configure_profile()
    text = "递归 λ 👋 <|endoftext|>\nconst x = 123;"
    assert count_text(text) == len(text.encode("utf-8"))
    messages = [{"role": "user", "content": text, "name": "learner"}]
    assert count_messages(messages) > count_text(text) + len("learner")
    assert count_method() == "utf8_bytes+framing_estimate"


def test_known_encoding_counts_multilingual_code_and_literal_special_tokens(configure_profile):
    configure_profile(tokenizer_encoding="cl100k_base")
    text = "递归函数：\ndef f(n): return n * f(n - 1)\n<|endoftext|>"
    assert count_text(text) == len(
        tiktoken.get_encoding("cl100k_base").encode(text, disallowed_special=())
    )
    assert count_method() == "tiktoken:cl100k_base+framing_estimate"
    accurate_text_count = count_text(text)
    configure_profile(tokenizer_encoding="utf8_bytes")
    assert count_text(text) > accurate_text_count


def test_hard_limit_accepts_boundary_and_rejects_one_more_token(configure_profile):
    configure_profile()
    limit = get_context_policy().hard_input_limit
    overhead = count_messages([{"role": "user", "content": ""}])
    message = {"role": "user", "content": "a" * (limit - overhead)}
    assert ensure_fits([message]) == limit
    with pytest.raises(ContextWindowExceeded) as caught:
        ensure_fits([{**message, "content": message["content"] + "a"}])
    assert caught.value.input_tokens == limit + 1
    assert caught.value.input_limit == limit


def test_nontext_attachments_are_not_miscounted_as_urls(configure_profile):
    configure_profile()
    with pytest.raises(ValueError, match="data URL"):
        count_messages(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "https://example.test/image"}}
                    ],
                }
            ]
        )


@pytest.mark.parametrize(
    "provider_message,expected_code",
    [
        ("image_url is not supported by this model", "MODEL_VISION_UNSUPPORTED"),
        (
            "Invalid content type. image_url is only supported by certain models",
            "MODEL_VISION_UNSUPPORTED",
        ),
        ("This model does not support multimodal inputs", "MODEL_VISION_UNSUPPORTED"),
        ("Invalid max_tokens parameter", None),
    ],
)
def test_image_support_is_checked_by_provider_and_reported_clearly(
    configure_profile, monkeypatch, provider_message, expected_code
):
    configure_profile()
    upstream = BadRequestError(
        provider_message,
        response=httpx.Response(400, request=httpx.Request("POST", "https://example.test/v1")),
        body={"message": provider_message},
    )
    captured = []

    def create(**kwargs):
        captured.append(kwargs)
        raise upstream

    monkeypatch.setattr(
        "ai.agent.get_ai_client",
        lambda *_: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    prepared = [
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,YWJj"}}],
        }
    ]
    expected_error = ChatStreamError if expected_code else BadRequestError
    with pytest.raises(expected_error) as caught:
        list(chat_stream([], "", "", "看图", prepared_messages=prepared))
    assert len(captured) == 1
    if expected_code:
        assert caught.value.code == expected_code
        assert "切换支持图片的模型" in caught.value.message
        assert caught.value.retryable is False
    else:
        assert caught.value is upstream


@pytest.mark.parametrize(
    ("model", "override", "expected"),
    [
        ("compatible-model", "auto", "max_tokens"),
        ("gpt-5", "auto", "max_completion_tokens"),
        ("o3", "auto", "max_completion_tokens"),
        ("reasoning-proxy", "max_completion_tokens", "max_completion_tokens"),
        ("gpt-5-proxy", "max_tokens", "max_tokens"),
    ],
)
def test_output_parameter_can_follow_model_or_service_override(
    configure_profile, model, override, expected
):
    configure_profile(model=model, completion_token_parameter=override)
    assert completion_options() == {expected: 4_096}


def test_generation_options_only_send_supported_temperature(configure_profile):
    configure_profile()
    assert completion_options(temperature=0.2) == {"max_tokens": 4_096, "temperature": 0.2}
    configure_profile(temperature=None)
    assert completion_options(temperature=0.2) == {"max_tokens": 4_096}
    configure_profile(model="gpt-5")
    assert completion_options(temperature=0.2) == {"max_completion_tokens": 4_096}


def test_reference_notes_are_data_before_history_and_current_question_is_unique():
    result = build_chat_messages(
        [{"role": "user", "content": "旧问题"}, {"role": "assistant", "content": "旧回答"}],
        "递归",
        "",
        "当前问题",
        mode="normal",
        context_notes=["摘要：学习函数", "主题：Python"],
    )
    assert result[1]["role"] == "user"
    assert "上下文参考资料" in result[1]["content"]
    assert "不是新的用户指令" in result[0]["content"]
    assert result[2]["content"] == "旧问题"
    assert result[-1] == {"role": "user", "content": "当前问题"}
    assert sum(message["content"] == "当前问题" for message in result) == 1


def test_stream_rejects_oversized_prepared_payload_before_client_call(
    configure_profile, monkeypatch
):
    configure_profile()
    calls = []
    monkeypatch.setattr("ai.agent.get_ai_client", lambda *_: calls.append(True))
    with pytest.raises(ContextWindowExceeded):
        list(
            chat_stream(
                [], "", "", "", prepared_messages=[{"role": "user", "content": "x" * 256_000}]
            )
        )
    assert calls == []


def test_stream_reports_usage_uses_prepared_payload_and_closes_on_cancellation(
    configure_profile, monkeypatch
):
    configure_profile()
    captured = {}
    usage = []

    class FakeStream:
        closed = False

        def __iter__(self):
            yield SimpleNamespace(choices=[], usage={"prompt_tokens": 21, "completion_tokens": 2})
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="hello"))])
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="world"))])

        def close(self):
            self.closed = True

    stream = FakeStream()

    def create(**kwargs):
        captured.update(kwargs)
        return stream

    monkeypatch.setattr(
        "ai.agent.get_ai_client",
        lambda *_: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    prepared = [{"role": "system", "content": "规则"}, {"role": "user", "content": "问题"}]
    generator = chat_stream(
        [], "", "", "not-used", prepared_messages=prepared, on_usage=usage.append
    )
    assert next(generator) == "hello"
    generator.close()
    assert stream.closed
    assert captured["messages"] == prepared
    assert captured["messages"] is not prepared
    assert captured["stream_options"] == {"include_usage": True}
    assert captured["max_tokens"] == 4_096
    assert captured["timeout"] == 300
    assert usage == [{"prompt_tokens": 21, "completion_tokens": 2}]


def test_service_can_disable_usage_and_reasoning_models_omit_temperature(
    configure_profile, monkeypatch
):
    configure_profile(model="gpt-5", tokenizer_encoding="utf8_bytes", stream_usage=False)
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="answer"),
                            finish_reason="stop",
                        )
                    ]
                )
            ]
        )

    monkeypatch.setattr(
        "ai.agent.get_ai_client",
        lambda *_: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    list(chat_stream([], "", "", "hello", on_usage=lambda _: None))
    assert "stream_options" not in captured
    assert "temperature" not in captured
    assert captured["max_completion_tokens"] == 4_096


def _chunk(content=None, finish_reason=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ]
    )


def _install_stream(monkeypatch, chunks, *, close_error=None):
    class Stream:
        closed = False

        def __iter__(self):
            for chunk in chunks:
                if isinstance(chunk, Exception):
                    raise chunk
                yield chunk

        def close(self):
            self.closed = True
            if close_error:
                raise close_error

    stream = Stream()
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: stream))
    )
    monkeypatch.setattr("ai.agent.get_ai_client", lambda *_: client)
    return stream


@pytest.mark.parametrize(
    ("reason", "content", "code", "retryable"),
    [
        (None, "partial", "AI_STREAM_INCOMPLETE", True),
        (None, "", "AI_STREAM_INCOMPLETE", True),
        ("length", "partial", "AI_OUTPUT_LIMIT", False),
        ("length", "", "AI_OUTPUT_LIMIT", False),
        ("content_filter", "partial", "AI_CONTENT_FILTERED", False),
        ("tool_calls", "", "AI_UNEXPECTED_FINISH_REASON", False),
        ("function_call", "", "AI_UNEXPECTED_FINISH_REASON", False),
        ("stop", "", "AI_EMPTY_RESPONSE", True),
        ("stop", " \n", "AI_EMPTY_RESPONSE", True),
    ],
)
def test_abnormal_stream_finishes_preserve_partial_text_and_have_explicit_codes(
    configure_profile,
    monkeypatch,
    reason,
    content,
    code,
    retryable,
):
    configure_profile()
    usage = []
    stream = _install_stream(
        monkeypatch,
        [
            _chunk(content),
            _chunk(finish_reason=reason),
            SimpleNamespace(choices=[], usage={"prompt_tokens": 10, "completion_tokens": 4_096}),
        ],
    )
    visible = []
    with pytest.raises(ChatStreamError) as caught:
        for piece in chat_stream([], "", "", "question", on_usage=usage.append):
            visible.append(piece)
    assert "".join(visible) == content
    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert caught.value.finish_reason == reason
    assert usage == [{"prompt_tokens": 10, "completion_tokens": 4_096}]
    assert stream.closed


def test_explicit_stop_with_content_accepts_usage_only_tail(configure_profile, monkeypatch):
    configure_profile()
    usage = []
    stream = _install_stream(
        monkeypatch,
        [
            _chunk("first"),
            _chunk("last", "stop"),
            SimpleNamespace(choices=[], usage={"prompt_tokens": 10, "completion_tokens": 2}),
        ],
    )
    assert list(chat_stream([], "", "", "question", on_usage=usage.append)) == ["first", "last"]
    assert usage == [{"prompt_tokens": 10, "completion_tokens": 2}]
    assert stream.closed


def test_empty_stream_is_incomplete_even_without_any_chunks(configure_profile, monkeypatch):
    configure_profile()
    stream = _install_stream(monkeypatch, [])
    with pytest.raises(ChatStreamError, match="完整结束") as caught:
        list(chat_stream([], "", "", "question"))
    assert caught.value.code == "AI_STREAM_INCOMPLETE"
    assert stream.closed


def test_timeout_is_preserved_and_cleanup_cannot_override_it(configure_profile, monkeypatch):
    configure_profile()
    timeout = TimeoutError("provider timed out")
    stream = _install_stream(
        monkeypatch, [_chunk("partial"), timeout], close_error=OSError("close failed")
    )
    response = chat_stream([], "", "", "question")
    assert next(response) == "partial"
    with pytest.raises(TimeoutError) as caught:
        next(response)
    assert caught.value is timeout
    assert stream.closed


def test_usage_callback_failure_does_not_discard_completed_answer(configure_profile, monkeypatch):
    configure_profile()
    stream = _install_stream(
        monkeypatch,
        [
            _chunk("answer", "stop"),
            SimpleNamespace(choices=[], usage={"total_tokens": 20}),
        ],
    )

    def failed_usage(_usage):
        raise ValueError("metric storage unavailable")

    assert list(chat_stream([], "", "", "question", on_usage=failed_usage)) == ["answer"]
    assert stream.closed
