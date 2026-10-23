import json
import logging
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from core.config import settings
from schemas.structured_ai import (
    AssessmentScore,
    DiagnosticQuestions,
    QuestionScore,
)
from services.agent.structured_ai import (
    RunContext,
    StructuredAIError,
    generate_structured,
    high_risk_notice,
)


@pytest.fixture(autouse=True)
def standard_test_model(monkeypatch):
    monkeypatch.setattr(settings, "llm_models", "")
    monkeypatch.setattr(settings, "llm_default_model_id", "")
    monkeypatch.setattr(settings, "llm_model", "test-model")


def response(content: str, tokens: int = 12):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(total_tokens=tokens),
    )


def questions_payload():
    return {
        "questions": [
            {"question_id": "q1", "dimension": "prior_knowledge", "prompt": "Q1"},
            {"question_id": "q2", "dimension": "application", "prompt": "Q2"},
            {"question_id": "q3", "dimension": "limits", "prompt": "Q3"},
        ]
    }


def client_with(*results):
    calls = []
    queued = iter(results)

    def create(**kwargs):
        calls.append(kwargs)
        result = next(queued)
        if isinstance(result, Exception):
            raise result
        return result

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client, calls


def test_parses_json_and_tracks_tokens():
    client, calls = client_with(response(json.dumps(questions_payload()), tokens=21))

    result = generate_structured(
        DiagnosticQuestions,
        [{"role": "user", "content": "Create questions"}],
        RunContext(run_id="run-1", call_type="diagnostic_questions"),
        client=client,
    )

    assert result.value.questions[0].question_id == "q1"
    assert result.token_usage == 21
    assert result.attempts == 1
    assert calls[0]["temperature"] <= 0.3
    assert calls[0]["timeout"] == 60


@pytest.mark.parametrize(
    "finish_reason,code", [("length", "AI_OUTPUT_LIMIT"), ("content_filter", "AI_CONTENT_FILTERED")]
)
def test_incomplete_finish_never_accepts_even_valid_json(finish_reason, code):
    incomplete = response(json.dumps(questions_payload()))
    incomplete.choices[0].finish_reason = finish_reason
    client, calls = client_with(incomplete)
    with pytest.raises(StructuredAIError) as error:
        generate_structured(
            DiagnosticQuestions,
            [],
            RunContext(run_id="incomplete", call_type="test"),
            client=client,
        )
    assert error.value.code == code
    assert len(calls) == 1


def test_accepts_markdown_json_and_repairs_only_once():
    payload = json.dumps(questions_payload())
    markdown_client, _ = client_with(response(f"```json\n{payload}\n```"))
    assert (
        generate_structured(
            DiagnosticQuestions,
            [],
            RunContext(run_id="run-2", call_type="diagnostic_questions"),
            client=markdown_client,
        ).attempts
        == 1
    )

    repair_client, calls = client_with(response("not json", 5), response(payload, 7))
    result = generate_structured(
        DiagnosticQuestions,
        [],
        RunContext(run_id="run-3", call_type="diagnostic_questions"),
        client=repair_client,
    )
    assert result.attempts == 2
    assert result.token_usage == 12
    assert calls[-1]["temperature"] == 0


def test_invalid_output_after_repair_is_retryable():
    client, _ = client_with(response("bad"), response("still bad"))

    with pytest.raises(StructuredAIError) as error:
        generate_structured(
            DiagnosticQuestions,
            [],
            RunContext(run_id="run-4", call_type="diagnostic_questions"),
            client=client,
        )
    assert error.value.code == "STRUCTURED_OUTPUT_INVALID"
    assert error.value.retryable is True


def test_missing_choices_is_repaired_as_invalid_output():
    client, _ = client_with(
        SimpleNamespace(choices=[], usage=None),
        response(json.dumps(questions_payload())),
    )
    result = generate_structured(
        DiagnosticQuestions,
        [],
        RunContext(run_id="run-empty", call_type="diagnostic_questions"),
        client=client,
    )
    assert result.attempts == 2


@pytest.mark.parametrize(
    ("exception", "code"),
    [
        (TimeoutError("slow"), "AI_TIMEOUT"),
        (type("RateLimit", (Exception,), {"status_code": 429})("limited"), "AI_RATE_LIMITED"),
        (type("Upstream", (Exception,), {"status_code": 503})("down"), "AI_UPSTREAM_ERROR"),
    ],
)
def test_maps_retryable_upstream_errors(exception, code):
    client, _ = client_with(exception)
    with pytest.raises(StructuredAIError) as error:
        generate_structured(
            DiagnosticQuestions,
            [],
            RunContext(run_id="run-error", call_type="diagnostic_questions"),
            client=client,
        )
    assert error.value.code == code
    assert error.value.retryable is True


def test_structured_schemas_enforce_question_count_and_score_total():
    with pytest.raises(ValidationError):
        DiagnosticQuestions.model_validate({"questions": questions_payload()["questions"][:2]})

    scores = [
        QuestionScore(question_id=f"q{i}", score=4, rationale="Evidence") for i in range(1, 4)
    ]
    with pytest.raises(ValidationError):
        AssessmentScore(
            scores=scores,
            total_score=11,
            evaluation_confidence=0.9,
            critical_misconception=False,
            evidence="Strong",
            weaknesses=[],
        )


def test_high_risk_notice_is_deterministic():
    assert high_risk_notice("medical", "First aid")
    assert high_risk_notice("art", "Watercolor") is None


def test_logs_exclude_prompts_answers_and_provider_payloads(caplog):
    secret = "private-answer-never-log"
    client, _ = client_with(response(json.dumps(questions_payload())))
    logger = logging.getLogger("services.agent.structured_ai")
    logger.disabled = False
    with caplog.at_level(logging.INFO, logger=logger.name):
        generate_structured(
            DiagnosticQuestions,
            [{"role": "user", "content": secret}],
            RunContext(run_id="safe-log-run", call_type="diagnostic_questions"),
            client=client,
        )

    assert "safe-log-run" in caplog.text
    assert secret not in caplog.text
    assert "prior_knowledge" not in caplog.text


def test_optional_policy_limits_output_and_disables_repairs():
    client, calls = client_with(response("invalid"))
    with pytest.raises(StructuredAIError) as error:
        generate_structured(
            DiagnosticQuestions,
            [],
            RunContext(run_id="limited", call_type="web_decision"),
            client=client,
            timeout=5,
            output_tokens=256,
            max_repairs=0,
        )
    assert error.value.code == "STRUCTURED_OUTPUT_INVALID"
    assert len(calls) == 1
    assert 0 < calls[0]["timeout"] <= 5
    assert calls[0]["max_tokens"] == 256


def test_optional_policy_respects_reasoning_model_temperature_and_token_parameter(monkeypatch):
    monkeypatch.setattr(settings, "llm_model", "gpt-5-test")
    client, calls = client_with(response(json.dumps(questions_payload())))
    generate_structured(
        DiagnosticQuestions,
        [],
        RunContext(run_id="reasoning", call_type="web_decision"),
        client=client,
        timeout=5,
        output_tokens=2048,
        max_repairs=0,
    )
    assert calls[0]["max_completion_tokens"] == 2048
    assert "temperature" not in calls[0]
    assert "max_tokens" not in calls[0]


def test_optional_timeout_is_shared_by_repairs(monkeypatch):
    from services.agent import structured_ai

    readings = iter([10, 10, 14, 14])
    monkeypatch.setattr(structured_ai, "perf_counter", lambda: next(readings))
    client, calls = client_with(response("invalid"), response(json.dumps(questions_payload())))
    generate_structured(
        DiagnosticQuestions,
        [],
        RunContext(run_id="deadline", call_type="web_decision"),
        client=client,
        timeout=5,
    )
    assert calls[0]["timeout"] == 5
    assert calls[1]["timeout"] == 1


def test_absent_usage_preserves_legacy_count_but_is_explicitly_unknown():
    item = response(json.dumps(questions_payload()))
    item.usage = None
    client, _ = client_with(item)
    result = generate_structured(
        DiagnosticQuestions,
        [],
        RunContext(run_id="unknown-usage", call_type="web_decision"),
        client=client,
    )
    assert result.token_usage == 0
    assert result.usage_known is False


def test_missing_usage_in_one_repair_attempt_keeps_total_unknown():
    invalid = response("invalid")
    invalid.usage = None
    client, _ = client_with(invalid, response(json.dumps(questions_payload()), tokens=7))
    result = generate_structured(
        DiagnosticQuestions,
        [],
        RunContext(run_id="partial-usage", call_type="web_decision"),
        client=client,
    )
    assert result.token_usage == 7
    assert result.usage_known is False
