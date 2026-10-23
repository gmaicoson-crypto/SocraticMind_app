"""Select named test groups and their consumers; unknown business changes fail closed."""

import argparse
import fnmatch
import json
from pathlib import Path

from scripts.quality.changed_files import ROOT, collect, git, paths
from scripts.quality.file_rules import safe_path


LANES = ("python", "android", "ios", "mysql")


def plan(scope: dict, mapping: dict, imported: set[str], root: Path = ROOT) -> dict:
    groups = mapping["groups"]
    selected = set()
    reasons = {}
    unknown = []
    for value in scope["files"]:
        safe_path(root, value)
        matched = {
            name
            for name, group in groups.items()
            if any(fnmatch.fnmatchcase(value, pattern) for pattern in group["paths"])
        }
        if scope["initial"] and value in imported:
            matched.add("import-baseline")
        if not matched and value.startswith("backend/tests/") and value.endswith(".py"):
            # Tests are never silently auto-selected as a directory-wide suite.
            unknown.append(value)
        elif not matched and not any(
            fnmatch.fnmatchcase(value, pattern) for pattern in mapping["metadata"]
        ):
            unknown.append(value)
        selected.update(matched)
        if matched:
            reasons[value] = sorted(matched)
    if unknown:
        raise ValueError("Add affected test selectors for: " + ", ".join(unknown))
    for name, group in groups.items():
        if set(group.get("depends_on", [])) - groups.keys():
            raise ValueError(f"Unknown dependency in {name}")
    while True:
        consumers = {
            name for name, group in groups.items() if set(group.get("depends_on", [])) & selected
        }
        if consumers <= selected:
            break
        selected.update(consumers)
    checks = {lane: set() for lane in LANES}
    manual = set()
    for name in selected:
        group = groups[name]
        for lane, selectors in group.get("checks", {}).items():
            if lane not in LANES or not selectors or any(not value for value in selectors):
                raise ValueError(f"Invalid selectors for {name}/{lane}")
            checks[lane].update(selectors)
        manual.update(group.get("manual", []))
    formatting = set(scope["files"])
    expansions = {}
    for config, patterns in mapping.get("format_expansion", {}).items():
        if config in scope["files"]:
            available = paths(
                git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
            )
            expanded = sorted(
                value
                for value in available
                if any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns)
            )
            formatting.update(expanded)
            expansions[config] = expanded
    files = {lane: [] for lane in LANES}
    for value in sorted(formatting):
        suffix = Path(value).suffix
        lane = {".py": "python", ".kt": "android", ".kts": "android", ".swift": "ios"}.get(suffix)
        if lane:
            files[lane].append(value)
    return {
        "scope": scope,
        "groups": sorted(selected),
        "reasons": reasons,
        "checks": {lane: sorted(items) for lane, items in checks.items()},
        "files": files,
        "format_expansion": expansions,
        "manual": sorted(manual),
        "schema": "openapi" in selected or "import-baseline" in selected,
    }


def load_plan(scope: dict, root: Path = ROOT) -> dict:
    mapping = json.loads((root / "scripts/ci/impact-map.json").read_text())
    manifest = json.loads((root / "backend/upstream-manifest.json").read_text())
    return plan(scope, mapping, {item["target"] for item in manifest["files"]}, root)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    scope = json.loads(arguments.scope.read_text()) if arguments.scope else collect(ROOT)
    result = load_plan(scope)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"groups": result["groups"], "manual": result["manual"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
