import json
from pathlib import Path

import pytest

from evals.validate_web_search_cases import validate_dataset

DATASET = Path(__file__).parents[2] / "evals" / "web_search_cases.json"


def dataset():
    return json.loads(DATASET.read_text(encoding="utf-8"))


def test_decision_cases_cover_frozen_groups_without_claiming_live_accuracy():
    result = validate_dataset(dataset())
    assert result["case_count"] == 60
    assert result["model_evaluation_performed"] is False
    assert result["annotation_status"] == "draft_requires_human_review"
    assert result["category_counts"] == {
        "stable": 20,
        "latest": 20,
        "followup": 10,
        "restricted": 10,
    }


def test_duplicate_case_ids_are_rejected():
    data = dataset()
    data["cases"][1]["id"] = data["cases"][0]["id"]
    with pytest.raises(ValueError, match="unique"):
        validate_dataset(data)


def test_missing_followup_referent_is_rejected():
    data = dataset()
    case = next(case for case in data["cases"] if case["category"] == "followup")
    case["context_messages"] = []
    with pytest.raises(ValueError, match="referent"):
        validate_dataset(data)


def test_restricted_case_cannot_silently_change_to_search():
    data = dataset()
    data["cases"][-1]["expected"]["need_search"] = True
    with pytest.raises(ValueError, match="requires no search"):
        validate_dataset(data)
