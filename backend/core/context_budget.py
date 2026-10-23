"""Model-specific budgeting shared by conversation and summary requests.

Text tokenization can be exact for a known encoding; Chat Completions framing
remains an estimate. Unknown encodings use UTF-8 bytes, deliberately favouring
early compaction over undercounting. The final guard also reserves safety space.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Sequence

import tiktoken

from core.ai_client import resolve_llm_profile
from core.config import LLMProfile
from core.errors import ApiError
from services.attachments.config import IMAGE_TOKEN_ESTIMATE, LIMITS


@dataclass(frozen=True)
class ContextPolicy:
    context_window_tokens: int
    hard_input_limit: int
    target_input_tokens: int
    summary_trigger_tokens: int
    summary_target_tokens: int
    output_tokens: int
    safety_margin_tokens: int


class ContextWindowExceeded(ValueError):
    def __init__(self, input_tokens: int, input_limit: int):
        self.input_tokens = input_tokens
        self.input_limit = input_limit
        super().__init__(
            f"当前输入及必要上下文约 {input_tokens} token，超过输入上限 {input_limit}；"
            "请缩小引用范围或拆分输入。"
        )


def get_context_policy(model_id: str | None = None) -> ContextPolicy:
    profile = resolve_llm_profile(model_id)
    hard_limit = (
        profile.context_window_tokens
        - profile.generation_budget_tokens
        - profile.safety_margin_tokens
    )
    if profile.max_input_tokens is not None:
        hard_limit = min(hard_limit, profile.max_input_tokens)
    target = min(profile.target_input_tokens, hard_limit)
    trigger = min(profile.summary_trigger_tokens, target)
    summary_target = min(profile.summary_target_tokens, max(1, trigger * 2 // 3))
    return ContextPolicy(
        context_window_tokens=profile.context_window_tokens,
        hard_input_limit=hard_limit,
        target_input_tokens=target,
        summary_trigger_tokens=trigger,
        summary_target_tokens=summary_target,
        output_tokens=profile.generation_budget_tokens,
        safety_margin_tokens=profile.safety_margin_tokens,
    )


@lru_cache(maxsize=32)
def _load_encoding(model: str, encoding_name: str | None):
    if encoding_name == "utf8_bytes":
        return None
    if encoding_name:
        # A misspelled explicit encoding is a configuration error, not a claim
        # that an unrelated tokenizer is suitable for this service.
        return tiktoken.get_encoding(encoding_name)
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return None


def _profile_encoding(profile: LLMProfile):
    return _load_encoding(profile.model, profile.tokenizer_encoding)


def count_method(model_id: str | None = None) -> str:
    encoding = _profile_encoding(resolve_llm_profile(model_id))
    return (
        f"tiktoken:{encoding.name}+framing_estimate" if encoding else "utf8_bytes+framing_estimate"
    )


def _count_text(text: str, encoding) -> int:
    if encoding is None:
        return len(text.encode("utf-8"))
    # User code may literally contain tokenizer control-token spellings.
    return len(encoding.encode(text, disallowed_special=()))


def count_text(text: str, model_id: str | None = None) -> int:
    return _count_text(text, _profile_encoding(resolve_llm_profile(model_id)))


def count_messages(messages: Sequence[dict[str, Any]], model_id: str | None = None) -> int:
    """Count text and a system-owned image allowance on the actual wire payload.

    Image estimates are independent of base64 length and legacy model settings.
    The provider remains authoritative for actual image token usage.
    """
    profile = resolve_llm_profile(model_id)
    encoding = _profile_encoding(profile)
    total, images, binary_bytes = 16, 0, 0
    for message in messages:
        total += 12
        for key, value in message.items():
            if value is None:
                continue
            if key == "content" and isinstance(value, list):
                for part in value:
                    if not isinstance(part, dict):
                        raise ValueError("无效的多模态消息内容")
                    if part.get("type") == "text":
                        total += 8 + _count_text(str(part.get("text", "")), encoding)
                    elif part.get("type") == "image_url":
                        image = part.get("image_url", {})
                        url = image.get("url", "") if isinstance(image, dict) else ""
                        # Only the server's private, normalized data may be sent.
                        import re

                        if not isinstance(url, str) or not re.fullmatch(
                            r"data:image/(?:jpeg|png|webp);base64,[A-Za-z0-9+/]+={0,2}", url
                        ):
                            raise ValueError("图片输入必须使用服务器校验后的 data URL")
                        encoded = url.partition(",")[2]
                        size = len(encoded) * 3 // 4 - len(encoded) + len(encoded.rstrip("="))
                        if size > LIMITS["max_image_bytes"]:
                            raise ApiError(
                                status_code=422,
                                code="ATTACHMENT_TOO_LARGE",
                                message="图片超过输入大小限制",
                                retryable=False,
                            )
                        binary_bytes += size
                        images += 1
                        total += 16 + IMAGE_TOKEN_ESTIMATE
                    else:
                        raise ValueError("当前消息仅支持文字和图片内容块")
            else:
                text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                total += _count_text(text, encoding)
    if images > LIMITS["max_attachments"] or binary_bytes > LIMITS["max_message_bytes"]:
        raise ApiError(
            status_code=422,
            code="ATTACHMENT_TOO_LARGE",
            message=f"每次最多 {LIMITS['max_attachments']} 张图片，且总大小不能超过 50 MiB",
            retryable=False,
        )
    return total


def ensure_fits(messages: Sequence[dict[str, Any]], model_id: str | None = None) -> int:
    """Validate the final payload immediately before sending; return its count."""
    policy = get_context_policy(model_id)
    input_tokens = count_messages(messages, model_id)
    if input_tokens > policy.hard_input_limit:
        raise ContextWindowExceeded(input_tokens, policy.hard_input_limit)
    return input_tokens


def uses_reasoning_parameters(model_id: str | None = None) -> bool:
    model = resolve_llm_profile(model_id).model.lower()
    return model.startswith(("o1", "o3", "o4", "gpt-5", "gpt-6"))


def completion_options(
    model_id: str | None = None, *, temperature: float | None = None
) -> dict[str, Any]:
    """Generation limits include reasoning tokens when the service uses them."""
    profile = resolve_llm_profile(model_id)
    parameter = profile.completion_token_parameter
    if parameter == "auto":
        parameter = "max_completion_tokens" if uses_reasoning_parameters(model_id) else "max_tokens"
    options = {parameter: profile.generation_budget_tokens}
    if (
        temperature is not None
        and profile.temperature is not None
        and not uses_reasoning_parameters(model_id)
    ):
        options["temperature"] = temperature
    return options
