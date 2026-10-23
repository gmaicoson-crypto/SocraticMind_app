"""Collect NUL-safe paths from Git without mutating the index or guessing HEAD~1."""

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *arguments], check=check, capture_output=True)


def revision(root: Path, value: str) -> str:
    return (
        git(root, "rev-parse", "--verify", "--end-of-options", f"{value}^{{commit}}")
        .stdout.decode()
        .strip()
    )


def paths(result: subprocess.CompletedProcess) -> set[str]:
    return {item.decode("utf-8") for item in result.stdout.split(b"\0") if item}


def collect(
    root: Path, base: str | None = None, head: str | None = None, initial: bool = False
) -> dict:
    if initial and base:
        raise ValueError("Initial comparison and --base are mutually exclusive")
    if head and not (base or initial):
        raise ValueError("Commit comparison requires --base or explicit --initial")
    if head:
        after = revision(root, head)
        before = revision(root, base) if base else None
        selected = (
            paths(git(root, "ls-tree", "-r", "--name-only", "-z", after))
            if initial
            else paths(git(root, "diff", "--name-only", "--no-renames", "-z", before, after, "--"))
        )
    else:
        after = "worktree"
        existing = git(root, "rev-parse", "--verify", "HEAD", check=False)
        before = (
            revision(root, base)
            if base
            else (existing.stdout.decode().strip() if existing.returncode == 0 else None)
        )
        if initial:
            before = None
        selected = (
            paths(git(root, "diff", "--name-only", "--no-renames", "-z", before, "--"))
            if before
            else paths(git(root, "ls-files", "--cached", "-z"))
        )
        selected |= paths(git(root, "ls-files", "--others", "--exclude-standard", "-z"))
    return {"base": before, "head": after, "initial": before is None, "files": sorted(selected)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--initial", action="store_true")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = collect(ROOT, arguments.base, arguments.head, arguments.initial)
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if arguments.output:
        arguments.output.write_text(serialized)
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
