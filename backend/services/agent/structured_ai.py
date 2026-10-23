import json
import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from ai.util import extract_json_from_markdown
from core.ai_client import get_ai_client, resolve_llm_profile
from core.context_budget import completion_options, ensure_fits


log = logging.getLogger(__name__)
SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True)
class RunContext:
    run_id: str
    call_type: str
    model: str | None = None


@dataclass(frozen=True)
class StructuredResult(Generic[SchemaT]):
    value: SchemaT
    token_usage: int
    latency_ms: int
    attempts: int
    usage_known: bool = True


class StructuredAIError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


HIGH_RISK_TERMS = {
    "medical",
    "medicine",
    "health",
    "first aid",
    "法律",
    "legal",
    "law",
    "finance",
    "financial",
    "投资",
    "医疗",
    "急救",
    "安全",
    "safety",
}


def high_risk_notice(domain: str, topic: str) -> str | None:
    combined = f"{domain} {topic}".lower()
    if any(term in combined for term in HIGH_RISK_TERMS):
        return "本内容仅用于学习，不替代专业判断、执业认证或现场安全指导。"
    return None


def _token_usage(response) -> int:
    usage = getattr(response, "usage", None)
    return int(getattr(usage, "total_tokens", 0) or 0)


def _usage_known(response) -> bool:
    tokens = getattr(getattr(response, "usage", None), "total_tokens", None)
    return isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0


def _response_content(response) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    return getattr(message, "content", "") or ""


def _parse(schema: type[SchemaT], content: str) -> SchemaT:
    data = json.loads(extract_json_from_markdown(content))
    return schema.model_validate(data)


def _map_upstream_error(error: Exception) -> StructuredAIError:
    if isinstance(error, StructuredAIError):
        return error
    status_code = getattr(error, "status_code", None)
    class_name = type(error).__name__.lower()
    if isinstance(error, TimeoutError) or "timeout" in class_name:
        return StructuredAIError("AI_TIMEOUT", "模型请求超时", retryable=True)
    if status_code == 429:
        return StructuredAIError("AI_RATE_LIMITED", "模型请求受限", retryable=True)
    if isinstance(status_code, int) and status_code >= 500:
        return StructuredAIError("AI_UPSTREAM_ERROR", "模型服务暂时不可用", retryable=True)
    return StructuredAIError("AI_REQUEST_FAILED", "模型请求失败", retryable=False)


def _call(
    client,
    *,
    model: str,
    profile_id: str,
    messages: list[dict],
    temperature: float,
    timeout: float = 60,
    output_tokens: int | None = None,
):
    ensure_fits(messages, profile_id)
    options = completion_options(profile_id, temperature=temperature)
    if output_tokens is not None:
        parameter = "max_completion_tokens" if "max_completion_tokens" in options else "max_tokens"
        options[parameter] = min(
            output_tokens, resolve_llm_profile(profile_id).generation_budget_tokens
        )
    response = client.chat.completions.create(
        model=model, messages=messages, **options, timeout=timeout
    )
    choices = getattr(response, "choices", None) or []
    finish_reason = getattr(choices[0], "finish_reason", None) if choices else None
    if finish_reason == "length":
        raise StructuredAIError(
            "AI_OUTPUT_LIMIT", "模型生成额度不足，结构化结果尚未完成", retryable=False
        )
    if finish_reason == "content_filter":
        raise StructuredAIError("AI_CONTENT_FILTERED", "模型服务中止了本次生成", retryable=False)
    return response


def generate_structured(
    schema: type[SchemaT],
    messages: list[dict],
    run_context: RunContext,
    *,
    client=None,
    timeout: float | None = None,
    output_tokens: int | None = None,
    max_repairs: int = 1,
) -> StructuredResult[SchemaT]:
    """Optional timeout covers all attempts; omitted preserves existing 60s calls."""
    if timeout is not None and timeout <= 0:
        raise ValueError("timeout 必须大于零")
    if output_tokens is not None and output_tokens <= 0:
        raise ValueError("output_tokens 必须大于零")
    if not 0 <= max_repairs <= 3:
        raise ValueError("max_repairs 必须在 0 到 3 之间")
    profile = resolve_llm_profile(run_context.model)
    ai_client = client or get_ai_client(profile.id)
    started = perf_counter()
    total_tokens = 0
    usage_known = True
    current_messages = messages
    for attempt in range(max_repairs + 1):
        remaining = 60 if timeout is None else timeout - (perf_counter() - started)
        try:
            if remaining <= 0:
                raise TimeoutError()
            response = _call(
                ai_client,
                model=profile.model,
                profile_id=profile.id,
                messages=current_messages,
                temperature=0.2 if attempt == 0 else 0,
                timeout=remaining,
                output_tokens=output_tokens,
            )
        except Exception as error:
            mapped = _map_upstream_error(error)
            log.warning(
                "structured_ai_failed run_id=%s call_type=%s model=%s code=%s",
                run_context.run_id,
                run_context.call_type,
                profile.model,
                mapped.code,
            )
            raise mapped from error

        total_tokens += _token_usage(response)
        usage_known = usage_known and _usage_known(response)
        content = _response_content(response)
        try:
            value = _parse(schema, content)
            break
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
            if attempt == max_repairs:
                log.warning(
                    "structured_ai_failed run_id=%s call_type=%s model=%s code=%s",
                    run_context.run_id,
                    run_context.call_type,
                    profile.model,
                    "STRUCTURED_OUTPUT_INVALID",
                )
                raise StructuredAIError(
                    "STRUCTURED_OUTPUT_INVALID", "模型结构化输出校验失败", retryable=True
                ) from error
            current_messages = [
                *messages,
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        "修复上一条回复的 JSON 格式和字段，使其严格符合以下 JSON Schema。"
                        "只返回 JSON，不要解释："
                        + json.dumps(schema.model_json_schema(), ensure_ascii=False)
                    ),
                },
            ]

    latency_ms = round((perf_counter() - started) * 1000)
    log.info(
        "structured_ai_complete run_id=%s call_type=%s model=%s tokens=%s latency_ms=%d attempts=%d",
        run_context.run_id,
        run_context.call_type,
        profile.model,
        total_tokens if usage_known else None,
        latency_ms,
        attempt + 1,
    )
    return StructuredResult(
        value=value,
        token_usage=total_tokens,
        latency_ms=latency_ms,
        attempts=attempt + 1,
        usage_known=usage_known,
    )
