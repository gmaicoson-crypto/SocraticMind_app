"""Physical line policy and exact-path historical debt; independent of CLI and Git."""

import hashlib
from datetime import date
from pathlib import Path, PurePosixPath


LIMITS = {"ui": (250, 400), "route": (250, 400), "source": (300, 500), "test": (500, 800)}
SOURCE_SUFFIXES = {".py", ".kt", ".kts", ".swift", ".sh"}


def physical_lines(content: bytes) -> int:
    return content.count(b"\n") + int(bool(content) and not content.endswith(b"\n"))


def safe_path(root: Path, value: str) -> Path:
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError(f"Expected repository-relative path: {value}")
    path = root / value
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError(f"Path is not a regular repository file: {value}")
    return path


def classify(value: str, content: bytes) -> str | None:
    path = PurePosixPath(value)
    if path.suffix not in SOURCE_SUFFIXES:
        return None
    parts = {part.lower() for part in path.parts}
    if parts & {"tests", "test", "androidtest", "testfixtures"} or any(
        part.endswith(("tests", "uitests")) for part in parts
    ):
        return "test"
    if value.startswith("backend/routers/"):
        return "route"
    if parts & {"screens", "components", "designsystem", "views"} or any(
        marker in content for marker in (b"@Composable", b"import SwiftUI")
    ):
        return "ui"
    return "source"


def validate_baselines(root: Path, entries: list[dict], manifest: dict, today: date) -> dict:
    sources = {item["target"]: item for item in manifest["files"]}
    registered = {}
    for entry in entries:
        value = entry["path"]
        path = safe_path(root, value)
        if value in registered or not path.is_file():
            raise ValueError(f"Duplicate or stale baseline: {value}")
        for field in ("reason", "responsible", "task", "split_direction", "retire_when"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f"Missing {field} for {value}")
        if entry["rule"] != "file_lines" or entry["category"] not in LIMITS:
            raise ValueError(f"Invalid baseline rule/category: {value}")
        registered_on = date.fromisoformat(entry["registered_on"])
        review_by = date.fromisoformat(entry["review_by"])
        if (
            not registered_on <= today <= review_by
            or not 0 <= (review_by - registered_on).days <= 60
        ):
            raise ValueError(f"Expired or invalid review period: {value}")
        origin = sources.get(value)
        if (
            origin is None
            or origin["source_sha256"] != entry["source_sha256"]
            or entry["source_commit"] != manifest["commit"]
        ):
            raise ValueError(f"Unverified historical source: {value}")
        content = path.read_bytes()
        category = classify(value, content)
        # Moving a mixed UI/route file cannot silently relax its recorded category.
        if category != entry["category"]:
            raise ValueError(f"Baseline classification changed: {value}")
        count = physical_lines(content)
        maximum = entry["max_lines"]
        if type(maximum) is not int or maximum <= LIMITS[category][1]:
            raise ValueError(f"Unnecessary or invalid baseline: {value}")
        if count != maximum:
            raise ValueError(
                f"Baseline must tighten or be removed after shrink, never grow: {value}"
            )
        registered[value] = entry
    return registered


def historical_migrations(manifest: dict) -> dict[str, str]:
    return {
        item["target"]: item["source_sha256"]
        for item in manifest["files"]
        if item["target"].startswith("backend/alembic/versions/")
    }


def inspect_file(
    value: str, content: bytes, baselines: dict, history: dict, before: bytes | None
) -> dict:
    category = classify(value, content)
    count = physical_lines(content)
    report = {"path": value, "category": category, "lines": count, "status": "pass"}
    if value in history:
        report["category"] = "historical-migration"
        if hashlib.sha256(content).hexdigest() != history[value]:
            report.update(status="fail", reason="Historical migration bytes changed")
        return report
    if category is None:
        report["status"] = "not-source"
        return report
    warning, maximum = LIMITS[category]
    report.update(warning=warning, maximum=maximum)
    if before is not None:
        report["before"] = physical_lines(before)
    if value in baselines:
        maximum = baselines[value]["max_lines"]
        if before is not None:
            maximum = min(maximum, physical_lines(before))
        report.update(allowed=maximum, task=baselines[value]["task"])
    if count > maximum:
        report.update(status="fail", reason="File exceeds allowed physical lines")
    elif count >= warning:
        report.update(status="warning", reason="Review responsibility and record the decision")
    return report
