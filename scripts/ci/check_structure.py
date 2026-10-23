"""Check selected text / structured files and source-size baselines without language runtimes."""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

from scripts.quality.changed_files import ROOT
from scripts.quality.file_rules import safe_path


def inspect_text(root: Path, value: str) -> None:
    path = safe_path(root, value)
    if not path.is_file() or path.suffix not in {".md", ".json", ".yml", ".yaml", ".toml"}:
        return
    if value == "backend/README.upstream.md":
        return  # Original reference material; preserve its source formatting and old links.
    content = path.read_bytes()
    text = content.decode("utf-8")
    if b"\r" in content or (content and (not content.endswith(b"\n") or content.endswith(b"\n\n"))):
        raise ValueError(f"Expected LF and one final newline: {value}")
    if any(line.endswith((" ", "\t")) for line in text.splitlines()):
        raise ValueError(f"Trailing whitespace: {value}")
    if path.suffix == ".json":
        json.loads(text)
    if path.suffix == ".toml":
        tomllib.loads(text)
    if path.suffix == ".md":
        for link in re.findall(r"\]\(([^)\s]+)\)", text):
            target = urlsplit(link)
            if target.scheme or not target.path or target.netloc:
                continue
            destination = path.parent / unquote(target.path)
            if not destination.resolve().is_relative_to(root.resolve()) or not destination.exists():
                raise ValueError(f"Broken local Markdown link in {value}: {link}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    arguments = parser.parse_args()
    plan = json.loads(arguments.plan.read_text())
    scope = plan["scope"]
    for value in scope["files"]:
        inspect_text(ROOT, value)
    if not scope["files"]:
        print("No changed files")
        return
    with tempfile.TemporaryDirectory(prefix="socratic-ci-") as temporary:
        selected = Path(temporary) / "files.json"
        selected.write_text(json.dumps(scope["files"]))
        command = [
            sys.executable,
            "scripts/quality/check_file_sizes.py",
            "--files-from",
            str(selected),
        ]
        command += ["--base", scope["base"]] if scope["base"] else ["--initial"]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
    warnings = [item for item in report["files"] if item["status"] == "warning"]
    print(
        json.dumps(
            {"status": "passed", "files": len(scope["files"]), "warnings": warnings},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
