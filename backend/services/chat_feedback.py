"""Bounded provider usage and safe model-failure descriptions shared by live and restored turns."""

import logging
from threading import Lock

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)

from ai.agent import ChatStreamError
from core.context_budget import ContextWindowExceeded
from core.errors import ApiError


MAX_TOKEN_COUNT = 2**53 - 1
TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")
ERROR_DESCRIPTIONS = {
    "AI_TIMEOUT": ("等待模型回复超时，已保存的内容可在历史中查看；请稍后手动重试。", True),
    "AI_RATE_LIMITED": ("模型服务请求过于频繁，请稍后重试或切换模型。", True),
    "AI_QUOTA_EXCEEDED": ("模型服务额度不足，请检查服务配置或切换模型。", False),
    "AI_PROVIDER_AUTH_FAILED": ("模型服务凭据或权限不可用，请检查服务配置或切换模型。", False),
    "AI_REQUEST_REJECTED": ("模型服务未接受本次请求，请调整问题或切换模型。", False),
    "AI_CONNECTION_FAILED": ("与模型服务的连接中断，请查看已保存内容后手动重试。", True),
    "AI_PROVIDER_UNAVAILABLE": ("模型服务暂时不可用，请稍后重试或切换模型。", True),
    "AI_BUSY": ("当前生成请求较多，请稍后重试。", True),
    "AI_OUTPUT_LIMIT": ("回答达到模型输出长度上限，当前内容尚未完成；可调整问题后重试。", False),
    "AI_STREAM_INCOMPLETE": ("模型连接在回答完整结束前关闭，请查看已保存内容后手动重试。", True),
    "AI_CONTENT_FILTERED": ("模型服务中止了本次回答，请调整问题后重试。", False),
    "AI_EMPTY_RESPONSE": ("模型未返回可用回答，请重试或切换模型。", True),
    "AI_UNEXPECTED_FINISH_REASON": ("模型返回了不支持的结束状态，请重试或切换模型。", False),
    "CHAT_CONTEXT_TOO_LARGE": ("本次输入与上下文超过模型限制，请缩小范围后重试。", False),
    "ATTACHMENT_CONTEXT_TIMEOUT": ("资料处理或回答超时，请缩小范围后重试。", True),
    "USER_CANCELLED": ("本次生成已停止，已保存的内容可在历史中查看。", False),
    "CLIENT_DISCONNECTED": ("连接已断开，本次生成已停止；请查看已保存内容。", True),
    "GENERATION_LEASE_EXPIRED": ("此前生成未完整结束，请查看已保存内容后手动重试。", True),
}


def error_description(code: str) -> dict:
    message, retryable = ERROR_DESCRIPTIONS.get(
        code, ("本次回答未完成，请查看已有内容后手动重试。", True)
    )
    return {"code": code, "message": message, "retryable": retryable}


def classify_chat_error(error: Exception) -> ApiError | ChatStreamError:
    if isinstance(error, (ApiError, ChatStreamError)):
        return error
    if isinstance(error, ContextWindowExceeded):
        code = "CHAT_CONTEXT_TOO_LARGE"
    elif isinstance(error, (APITimeoutError, httpx.TimeoutException)):
        code = "AI_TIMEOUT"
    elif isinstance(error, RateLimitError):
        exhausted = isinstance(error.code, str) and error.code in {
            "insufficient_quota",
            "quota_exceeded",
        }
        code = "AI_QUOTA_EXCEEDED" if exhausted else "AI_RATE_LIMITED"
    elif isinstance(error, (AuthenticationError, PermissionDeniedError)):
        code = "AI_PROVIDER_AUTH_FAILED"
    elif isinstance(error, APIStatusError):
        code = "AI_PROVIDER_UNAVAILABLE" if error.status_code >= 500 else "AI_REQUEST_REJECTED"
    elif isinstance(error, (APIConnectionError, httpx.TransportError)):
        # The pinned openai 2.33 stream can still raise raw HTTPX transport exceptions.
        code = "AI_CONNECTION_FAILED"
    else:
        code = "AI_STREAM_ERROR"
    return ChatStreamError(**error_description(code))


def normalized_usage(value: object) -> dict | None:
    """Only a complete, internally consistent provider report is usage; missing is never zero."""
    if not isinstance(value, dict):
        return None
    result = {key: value.get(key) for key in TOKEN_FIELDS}
    if not all(type(count) is int and 0 <= count <= MAX_TOKEN_COUNT for count in result.values()):
        return None
    if result["prompt_tokens"] + result["completion_tokens"] != result["total_tokens"]:
        return None
    return result


class ChatUsageCollector:
    """One answer call, last report wins; worker callbacks never access a database or a later turn."""

    def __init__(self, request_id: str):
        self._lock = Lock()
        self._value = None
        self._closed = False
        self._request_id = request_id

    def record(self, value: object, *, estimated_input: int | None = None) -> None:
        usage = normalized_usage(value)
        with self._lock:
            if self._closed:
                return
            self._value = usage
        if usage is not None:
            logging.getLogger(__name__).info(
                "chat_token_usage request=%s estimated_input=%s input_delta=%s usage=%s",
                self._request_id,
                estimated_input,
                usage["prompt_tokens"] - estimated_input if estimated_input is not None else None,
                usage,
            )

    def finish(self) -> dict | None:
        with self._lock:
            self._closed = True
            return dict(self._value) if self._value is not None else None
