"""Shared synthetic model feedback cases; never contacts a provider."""

import json
from pathlib import Path

import httpx
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    PermissionDeniedError,
    RateLimitError,
)


DATA = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/fixtures/chat-feedback.json").read_text()
)
PRIVATE_DETAIL = "synthetic-private-key https://provider.example.test/private"


def provider_error(kind):
    request = httpx.Request("POST", "https://provider.example.test/v1/chat/completions")
    if kind == "sdk_timeout":
        return APITimeoutError(request=request)
    if kind == "stream_timeout":
        return httpx.ReadTimeout(PRIVATE_DETAIL, request=request)
    if kind == "sdk_connection":
        return APIConnectionError(message=PRIVATE_DETAIL, request=request)
    if kind == "stream_connection":
        return httpx.RemoteProtocolError(PRIVATE_DETAIL, request=request)
    if kind == "unexpected":
        return RuntimeError(PRIVATE_DETAIL)
    error_type, status, code = {
        "rate_limit": (RateLimitError, 429, "rate_limit_exceeded"),
        "quota": (RateLimitError, 429, "insufficient_quota"),
        "quota_alternate": (RateLimitError, 429, "quota_exceeded"),
        "invalid_quota_code": (RateLimitError, 429, ["insufficient_quota"]),
        "credentials": (AuthenticationError, 401, "invalid_api_key"),
        "permission": (PermissionDeniedError, 403, "permission_denied"),
        "request": (BadRequestError, 400, "invalid_request"),
        "unavailable": (InternalServerError, 503, "server_error"),
    }[kind]
    return error_type(
        PRIVATE_DETAIL,
        response=httpx.Response(status, request=request),
        body={"code": code, "message": PRIVATE_DETAIL},
    )
