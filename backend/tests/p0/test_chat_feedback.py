"""Malformed usage, cancellation fencing and safe SDK error translation."""

import logging
from concurrent.futures import ThreadPoolExecutor

import pytest

from ai.agent import ChatStreamError
from core.context_budget import ContextWindowExceeded
from core.errors import ApiError
from services.chat_feedback import ChatUsageCollector, classify_chat_error, normalized_usage
from tests.feedback_cases import DATA, PRIVATE_DETAIL, provider_error


@pytest.mark.parametrize("case", DATA["usage_cases"], ids=lambda case: case["name"])
def test_usage_contract_keeps_only_a_valid_complete_report(case):
    assert normalized_usage(case["input"]) == case["expected"]


@pytest.mark.parametrize("case", DATA["errors"], ids=lambda case: case["kind"])
def test_safe_error_contract(case):
    failure = classify_chat_error(provider_error(case["kind"]))
    assert (failure.code, failure.message, failure.retryable) == (
        case["code"],
        case["message"],
        case["retryable"],
    )
    assert PRIVATE_DETAIL not in failure.message


def test_known_application_errors_preserve_the_live_stream_contract():
    for failure in [
        ChatStreamError("AI_OUTPUT_LIMIT", "合成长度限制", retryable=False),
        ApiError(status_code=409, code="CHAT_REQUEST_CANCELLED", message="合成取消"),
    ]:
        assert classify_chat_error(failure) is failure
    assert classify_chat_error(ContextWindowExceeded(100, 50)).code == "CHAT_CONTEXT_TOO_LARGE"


def test_collector_copies_last_report_does_not_sum_and_seals_late_worker(caplog):
    collector = ChatUsageCollector("synthetic-feedback")
    value = DATA["reported_usage"] | {"provider_private": PRIVATE_DETAIL}
    with caplog.at_level(logging.INFO):
        collector.record(value, estimated_input=40)
        collector.record(value)
    value["total_tokens"] = -1
    first = collector.finish()
    assert first == DATA["reported_usage"]
    first["total_tokens"] = -1
    # A worker may outlive the UI cancellation; it cannot alter the sealed attempt.
    with ThreadPoolExecutor(max_workers=1) as worker:
        worker.submit(collector.record, DATA["zero_usage"]).result(timeout=2)
    assert collector.finish() == DATA["reported_usage"]
    assert PRIVATE_DETAIL not in caplog.text and "provider_private" not in caplog.text


def test_missing_or_latest_malformed_report_stays_unknown():
    assert ChatUsageCollector("no-report").finish() is None
    collector = ChatUsageCollector("malformed-final-report")
    collector.record(DATA["reported_usage"])
    collector.record({"total_tokens": 59})
    assert collector.finish() is None
    zero = ChatUsageCollector("reported-zero")
    zero.record(DATA["zero_usage"])
    assert zero.finish() == DATA["zero_usage"]
