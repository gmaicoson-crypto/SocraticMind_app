"""Read-only language checks and physical-size checks over an explicit Git scope."""

import argparse
import importlib.metadata
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.quality.changed_files import ROOT, collect, git, revision
from scripts.quality.file_rules import safe_path


def execute(arguments: list[str]) -> None:
    subprocess.run(arguments, cwd=ROOT, check=True)


def native_tool(name: str) -> str:
    spec = json.loads((ROOT / "scripts/tool-versions.json").read_text())["tools"][name]
    binary = ROOT / ".tools" / f"{name}-{spec['version']}" / name
    if not binary.is_file():
        raise ValueError(f"Install pinned {name} with scripts/dev/bootstrap_tools.py")
    argument = "version" if name == "swiftlint" else "--version"
    output = subprocess.check_output([str(binary), argument], cwd=ROOT, text=True)
    if not re.search(rf"(?<![\d.]){re.escape(spec['version'])}(?![\d.])", output):
        raise ValueError(f"Unexpected {name} version")
    return str(binary)


def language_checks(paths: list[str]) -> dict[str, int]:
    selected = {"python": [], "kotlin": [], "swift": []}
    languages = {".py": "python", ".kt": "kotlin", ".kts": "kotlin", ".swift": "swift"}
    for value in paths:
        path = safe_path(ROOT, value)
        if path.is_file() and path.suffix in languages:
            selected[languages[path.suffix]].append(str(path))
    if selected["python"]:
        lock = (ROOT / "backend/requirements-lock.txt").read_text()
        expected = re.search(r"^ruff==([^\s]+)$", lock, re.MULTILINE).group(1)
        if importlib.metadata.version("ruff") != expected:
            raise ValueError("Ruff version differs from the dependency lock")
        execute([sys.executable, "-m", "ruff", "format", "--check", *selected["python"]])
        execute([sys.executable, "-m", "ruff", "check", *selected["python"]])
    if selected["kotlin"]:
        execute([native_tool("ktlint"), *selected["kotlin"]])
    if selected["swift"]:
        execute(
            [
                native_tool("swiftformat"),
                "--lint",
                "--config",
                "ios/.swiftformat",
                *selected["swift"],
            ]
        )
        execute(
            [
                native_tool("swiftlint"),
                "lint",
                "--strict",
                "--config",
                "ios/.swiftlint.yml",
                *selected["swift"],
            ]
        )
    return {key: len(values) for key, values in selected.items()}


def check(scope: dict) -> dict:
    paths = scope["files"]
    if not isinstance(paths, list) or any(not isinstance(value, str) for value in paths):
        raise ValueError("Scope files must be a JSON string array")
    if scope["head"] != "worktree":
        if revision(ROOT, "HEAD") != scope["head"]:
            raise ValueError("Check out the scope's exact head before running checks")
        if (
            git(ROOT, "diff", "--quiet", check=False).returncode
            or git(ROOT, "diff", "--cached", "--quiet", check=False).returncode
        ):
            raise ValueError("Committed scope requires a clean tracked worktree and index")
    if not paths:
        return {"status": "no-applicable-files", "languages": {}, "files": []}
    counts = language_checks(paths)
    with tempfile.TemporaryDirectory(prefix="socratic-scope-") as temporary:
        file_list = Path(temporary) / "paths.json"
        file_list.write_text(json.dumps(paths))
        command = [
            sys.executable,
            str(ROOT / "scripts/quality/check_file_sizes.py"),
            "--files-from",
            str(file_list),
        ]
        command += ["--base", scope["base"]] if scope["base"] else ["--initial"]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        if result.returncode and not result.stdout:
            raise RuntimeError(result.stderr)
        sizes = json.loads(result.stdout)
        if result.returncode:
            failures = [item for item in sizes["files"] if item["status"] == "fail"]
            raise ValueError(f"File size / provenance checks failed: {failures}")
    return {"status": "passed", "languages": counts, "files": sizes["files"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", type=Path, help="Snapshot produced by changed_files")
    parser.add_argument(
        "--files", nargs="+", help="Explicit worktree file subset; no automatic tests"
    )
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    if arguments.scope and arguments.files:
        parser.error("--scope and --files are mutually exclusive")
    try:
        scope = json.loads(arguments.scope.read_text()) if arguments.scope else collect(ROOT)
        if arguments.files:
            scope["files"] = arguments.files
        report = check(scope)
        if arguments.report:
            arguments.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        warnings = sum(item["status"] == "warning" for item in report["files"])
        print(
            json.dumps(
                {"status": report["status"], "languages": report["languages"], "warnings": warnings}
            )
        )
        return 0
    except (
        ValueError,
        RuntimeError,
        OSError,
        subprocess.SubprocessError,
        importlib.metadata.PackageNotFoundError,
    ) as error:
        print(f"Changed-file checks failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
