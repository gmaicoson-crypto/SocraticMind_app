"""Validate the frozen decision dataset only. Never imports or calls any model.

Run: python backend/evals/validate_web_search_cases.py [path/to/dataset.json]
Human annotation and real decision accuracy remain separate acceptance gates.
"""

import argparse
from collections import Counter
import json
from pathlib import Path

CATEGORIES = {"stable": 20, "latest": 20, "followup": 10, "restricted": 10}
REASONS = {
    "stable_knowledge",
    "current_information",
    "verify_claim",
    "find_resources",
    "explicit_search",
    "user_restricted",
    "insufficient_context",
    "unsupported_url_fetch",
}
FRESHNESS = {"any", "day", "week", "month", "year"}


def validate_dataset(data: dict) -> dict:
    if data.get("schema_version") != 1:
        raise ValueError("unsupported dataset schema")
    if data.get("annotation_status") not in {"draft_requires_human_review", "human_reviewed"}:
        raise ValueError("annotation status must be explicit")
    cases = data.get("cases")
    if not isinstance(cases, list) or len(cases) != 60:
        raise ValueError("dataset must contain exactly 60 cases")
    counts = Counter()
    seen = set()
    for case in cases:
        case_id, category = case.get("id"), case.get("category")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError("case ids must be unique non-empty strings")
        seen.add(case_id)
        if category not in CATEGORIES:
            raise ValueError(f"{case_id}: unknown category")
        counts[category] += 1
        prompt = case.get("user_input")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"{case_id}: missing question")
        context = case.get("context_messages")
        if not isinstance(context, list) or len(context) > 4:
            raise ValueError(f"{case_id}: invalid bounded context")
        for message in context:
            if message.get("role") not in {"user", "assistant"} or not isinstance(
                message.get("content"), str
            ):
                raise ValueError(f"{case_id}: invalid context message")
        if category == "followup" and not context:
            raise ValueError(f"{case_id}: followup must define the referent context")
        expected = case.get("expected", {})
        need_search = expected.get("need_search")
        if not isinstance(need_search, bool):
            raise ValueError(f"{case_id}: missing boolean search label")
        if category in {"stable", "restricted"} and need_search:
            raise ValueError(f"{case_id}: category requires no search")
        if category == "latest" and not need_search:
            raise ValueError(f"{case_id}: latest category requires search")
        reasons = expected.get("allowed_reason_codes")
        if not isinstance(reasons, list) or not reasons or not set(reasons) <= REASONS:
            raise ValueError(f"{case_id}: invalid reason labels")
        if category == "restricted" and reasons != ["user_restricted"]:
            raise ValueError(f"{case_id}: restricted case must preserve user scope")
        freshness = expected.get("allowed_freshness")
        if not isinstance(freshness, list) or not freshness or not set(freshness) <= FRESHNESS:
            raise ValueError(f"{case_id}: invalid freshness labels")
        concepts = expected.get("query_concepts")
        if not isinstance(concepts, list) or any(
            not isinstance(item, str) or not item.strip() for item in concepts
        ):
            raise ValueError(f"{case_id}: invalid semantic query concepts")
        if need_search != bool(concepts):
            raise ValueError(
                f"{case_id}: searched cases must specify query concepts; skipped cases must not"
            )
        if not isinstance(expected.get("rationale"), str) or not expected["rationale"].strip():
            raise ValueError(f"{case_id}: missing annotation rationale")
    if dict(counts) != CATEGORIES or data.get("category_counts") != CATEGORIES:
        raise ValueError(
            "category counts must be 20 stable / 20 latest / 10 followup / 10 restricted"
        )
    return {
        "valid": True,
        "case_count": len(cases),
        "category_counts": dict(counts),
        "annotation_status": data["annotation_status"],
        "model_evaluation_performed": False,
        "note": "仅校验样本结构和标签一致性；未运行模型，未测量判断准确率。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path", nargs="?", type=Path, default=Path(__file__).with_name("web_search_cases.json")
    )
    args = parser.parse_args()
    try:
        result = validate_dataset(json.loads(args.path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, AttributeError) as error:
        parser.exit(1, f"Dataset validation failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
