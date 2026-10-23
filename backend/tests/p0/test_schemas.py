from datetime import date

import pytest
from pydantic import ValidationError

from schemas.agent import OnboardingRequest, OutcomeType
from schemas.mastery import MasteryRequest
from schemas.memory import MemoryCreate, MemoryKind


def test_onboarding_schema_normalizes_and_validates_boundaries():
    request = OnboardingRequest(
        topic="  Linear algebra  ",
        goal="  Build a solid foundation  ",
        domain="  Mathematics  ",
        outcome_type=OutcomeType.CONCEPT,
        familiarity="beginner",
        daily_minutes=5,
        target_date=date(2026, 10, 1),
        timezone="America/Los_Angeles",
        use_diagnostic=True,
    )

    assert request.topic == "Linear algebra"
    assert request.goal == "Build a solid foundation"
    assert request.domain == "Mathematics"

    with pytest.raises(ValidationError):
        OnboardingRequest(
            topic="Topic",
            goal="Goal",
            domain="Domain",
            outcome_type="unknown",
            familiarity="beginner",
            daily_minutes=4,
            timezone="UTC",
        )


def test_memory_schema_rejects_unknown_kind_and_long_content():
    memory = MemoryCreate(kind=MemoryKind.GOAL, content="  Learn safely  ")
    assert memory.content == "Learn safely"

    with pytest.raises(ValidationError):
        MemoryCreate(kind="secret", content="value")
    with pytest.raises(ValidationError):
        MemoryCreate(kind=MemoryKind.GOAL, content="x" * 301)


def test_mastery_request_requires_bounded_request_id():
    assert MasteryRequest(request_id="request-1").request_id == "request-1"

    with pytest.raises(ValidationError):
        MasteryRequest(request_id="")
    with pytest.raises(ValidationError):
        MasteryRequest(request_id="x" * 101)
