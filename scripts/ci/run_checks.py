"""Execute an explicit lane plan. No packaging, deployment, full-suite or fix commands."""

import argparse
import json
import re
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.ci.impact import LANES
from scripts.quality.changed_files import ROOT
from scripts.quality.check_changed import check


def run(arguments: list[str], cwd: Path = ROOT) -> None:
    print("Running: " + " ".join(arguments), flush=True)
    subprocess.run(arguments, cwd=cwd, check=True)


def xml_count(paths: list[Path], swift_selectors: list[str] = ()) -> int:
    count = 0
    found = set()
    for path in paths:
        tree = ET.parse(path).getroot()
        cases = list(tree.iter("testcase"))
        count += sum(case.find("skipped") is None for case in cases)
        for selector in swift_selectors:
            suite, _, method = selector.partition("/")
            if any(
                case.get("classname", "").endswith("." + suite)
                and (not method or case.get("name", "").removesuffix("()") == method)
                and case.find("skipped") is None
                for case in cases
            ):
                found.add(selector)
        if any(
            case.find("failure") is not None or case.find("error") is not None for case in cases
        ):
            raise ValueError("Test report contains failures")
    if count == 0:
        raise ValueError("Expected executed tests; no passing test cases were reported")
    if set(swift_selectors) - found:
        raise ValueError(f"Missing selected Swift tests: {set(swift_selectors) - found}")
    return count


def python_tests(selectors: list[str], mysql: bool = False) -> None:
    modules = [item.removeprefix("unittest:") for item in selectors if item.startswith("unittest:")]
    pytest = [item.removeprefix("pytest:") for item in selectors if item.startswith("pytest:")]
    if len(modules) + len(pytest) != len(selectors):
        raise ValueError("Python selectors must name unittest modules or pytest files / nodes")
    if modules:
        suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful() or result.testsRun <= len(result.skipped):
            raise ValueError("Expected successful, nonempty unittest selection")
    if pytest:
        for value in pytest:
            file = value.split("::")[0]
            if (
                not file.startswith("tests/")
                or not file.endswith(".py")
                or ".." in Path(file).parts
            ):
                raise ValueError("Select explicit pytest files or nodes, never a test directory")
        report = ROOT / ".tools" / ("ci-mysql.xml" if mysql else "ci-python.xml")
        run(
            [sys.executable, "-m", "pytest", "--tb=short", f"--junitxml={report}", *pytest],
            ROOT / "backend",
        )
        xml_count([report])


def android_tests(selectors: list[str]) -> None:
    modules = {}
    for item in selectors:
        match = re.fullmatch(r"com\.gmaicoson\.socraticmind\.(network|auth|chat)\.\w+Test", item)
        if not match:
            raise ValueError("Register explicit pure JVM test classes before adding another module")
        modules.setdefault(match.group(1), []).append(item)
    command = ["./gradlew", "--no-daemon", "--console", "plain"]
    for module, classes in sorted(modules.items()):
        command.append(f":core:{module}:test")
        for item in classes:
            command.extend(["--tests", item])
    # Check the actual graph before executing: source changes must not add APK-producing tasks.
    result = subprocess.run(
        [*command, "--dry-run"], cwd=ROOT / "android", capture_output=True, text=True, check=True
    )
    tasks = [line.split()[0] for line in result.stdout.splitlines() if line.startswith(":")]
    if not tasks or any(
        not task.startswith((":core:network:", ":core:auth:", ":core:chat:")) for task in tasks
    ):
        raise ValueError("Unexpected task outside registered pure JVM modules")
    if any(
        re.search(r"assemble|bundle|package|install|connected|androidTest", task, re.I)
        for task in tasks
    ):
        raise ValueError("Packaging / device task is forbidden in automatic checks")
    run(command, ROOT / "android")
    reports = [
        ROOT / f"android/core/{module}/build/test-results/test/TEST-{item}.xml"
        for module, classes in modules.items()
        for item in classes
    ]
    xml_count(reports)


def swift_tests(selectors: list[str]) -> None:
    if any(not re.fullmatch(r"\w+Tests(?:/\w+)?", item) for item in selectors):
        raise ValueError("Swift filters must name registered test suites / methods")
    report = ROOT / ".tools/ci-swift.xml"
    swift_report = report.with_name(report.stem + "-swift-testing.xml")
    for path in (report, swift_report):
        path.unlink(missing_ok=True)
    run(
        [
            "swift",
            "test",
            "--package-path",
            "ios/Packages/MindCore",
            "--filter",
            "|".join(selectors),
            "--xunit-output",
            str(report),
        ]
    )
    # SwiftPM emits Swift Testing separately from XCTest; never accept a stale or empty report.
    xml_count([path for path in (report, swift_report) if path.is_file()], selectors)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lane", choices=LANES)
    parser.add_argument("--plan", type=Path, required=True)
    arguments = parser.parse_args()
    plan = json.loads(arguments.plan.read_text())
    lane = arguments.lane
    scope = {**plan["scope"], "files": plan["files"][lane]}
    ROOT.joinpath(".tools").mkdir(exist_ok=True)
    if scope["files"]:
        check(scope)
    selectors = plan["checks"][lane]
    if selectors:
        if lane in {"python", "mysql"}:
            python_tests(selectors, lane == "mysql")
        elif lane == "android":
            android_tests(selectors)
        else:
            swift_tests(selectors)
    if lane == "python" and plan["schema"]:
        run([sys.executable, "scripts/contracts/export_openapi.py", "--check"])
    print(json.dumps({"lane": lane, "status": "passed", "selectors": selectors}))


if __name__ == "__main__":
    main()
