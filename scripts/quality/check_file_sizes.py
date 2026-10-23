"""Check explicitly selected files; --base adds a Git comparison for ratcheting debt."""

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path

from file_rules import historical_migrations, inspect_file, safe_path, validate_baselines


ROOT = Path(__file__).resolve().parents[2]


def git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, check=check)


def resolve_base(value: str | None) -> str | None:
    if value is None:
        return None
    return (
        git("rev-parse", "--verify", "--end-of-options", f"{value}^{{commit}}")
        .stdout.decode()
        .strip()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*")
    parser.add_argument("--files-from", type=Path, help="JSON array of repository-relative paths")
    parser.add_argument(
        "--base", help="Required comparison revision for PR / existing history checks"
    )
    parser.add_argument("--initial", action="store_true", help="Explicit initial commit comparison")
    arguments = parser.parse_args()
    if arguments.initial and arguments.base:
        parser.error("--initial and --base are mutually exclusive")
    paths = list(arguments.files)
    if arguments.files_from:
        selected = json.loads(arguments.files_from.read_text())
        if not isinstance(selected, list) or any(not isinstance(item, str) for item in selected):
            raise ValueError("File list must be an array of strings")
        paths.extend(selected)
    if not paths:
        parser.error("Provide explicit files or --files-from; no implicit whole-repository scan")
    base = resolve_base(arguments.base)
    if (
        base is None
        and not arguments.initial
        and git("rev-parse", "--verify", "HEAD", check=False).returncode == 0
    ):
        parser.error("Existing history requires --base so historical files cannot silently grow")
    manifest = json.loads((ROOT / "backend/upstream-manifest.json").read_text())
    baseline = json.loads((ROOT / "scripts/quality/file-size-baseline.json").read_text())
    if baseline.get("version") != 1:
        raise ValueError("Unsupported baseline schema")
    entries = validate_baselines(ROOT, baseline["files"], manifest, date.today())
    history = historical_migrations(manifest)
    reports = []
    for value in sorted(set(paths)):
        path = safe_path(ROOT, value)
        if not path.exists():
            was_tracked = (
                base and git("cat-file", "-e", f"{base}:{value}", check=False).returncode == 0
            )
            status = "deleted" if was_tracked and value not in history else "fail"
            reports.append({"path": value, "status": status, "reason": "Missing selected file"})
            continue
        before = None
        if base:
            old = git("show", f"{base}:{value}", check=False)
            if old.returncode == 0:
                before = old.stdout
        reports.append(inspect_file(value, path.read_bytes(), entries, history, before))
    print(json.dumps({"base": base, "files": reports}, ensure_ascii=False, indent=2))
    return int(any(report["status"] == "fail" for report in reports))


if __name__ == "__main__":
    raise SystemExit(main())
