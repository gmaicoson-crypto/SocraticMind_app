"""Resolve GitHub PR merge-base or push endpoints without interpolating event text in a shell."""

import argparse
import json
import os
import re
from pathlib import Path

from scripts.ci.impact import LANES, load_plan
from scripts.quality.changed_files import ROOT, collect, git, revision


def sha(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Expected a full GitHub commit SHA")
    return value


def event_scope(root: Path, name: str, event: dict) -> dict:
    if name == "pull_request":
        request = event["pull_request"]
        head = revision(root, sha(request["head"]["sha"]))
        base = revision(root, sha(request["base"]["sha"]))
        before = git(root, "merge-base", base, head).stdout.decode().strip()
        return collect(root, before, head)
    if name == "push":
        after = sha(event["after"])
        before = sha(event["before"])
        if after == "0" * 40:
            raise ValueError("Deleted branch has no checkable head")
        return collect(root, None if before == "0" * 40 else before, after, before == "0" * 40)
    raise ValueError(f"Unsupported event: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    scope = event_scope(ROOT, os.environ["GITHUB_EVENT_NAME"], event)
    if revision(ROOT, "HEAD") != scope["head"]:
        raise ValueError("Checkout must match the event head, not GitHub's synthetic merge commit")
    result = load_plan(scope)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        for lane in LANES:
            enabled = bool(result["checks"][lane] or result["files"][lane])
            enabled |= lane == "python" and result["schema"]
            output.write(f"{lane}={str(enabled).lower()}\n")
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary:
        summary.write("Affected groups: " + ", ".join(result["groups"]) + "\n\n")
        summary.write("```json\n" + json.dumps(result["checks"], indent=2) + "\n```\n")
        for item in result["manual"]:
            summary.write("- Pending separate validation: " + item + "\n")


if __name__ == "__main__":
    main()
