"""Keep SwiftPM tests and the Xcode host on the same reviewed source revisions."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ci.run_checks import swift_tests
from scripts.quality.changed_files import ROOT


class PackageResolutionTests(unittest.TestCase):
    def test_both_swift_resolutions_match_reviewed_sources_and_license_bytes(self):
        manifest = json.loads((ROOT / "docs/third-party/markdown-dependencies.json").read_text())
        expected = {}
        for item in manifest["dependencies"]:
            self.assertEqual(
                item["license_sha256"],
                hashlib.sha256((ROOT / item["license"]).read_bytes()).hexdigest(),
            )
            if item["identity"].startswith("swift-"):
                expected[item["identity"]] = {
                    "kind": "remoteSourceControl",
                    "location": item["location"],
                    "state": {"revision": item["revision"], "version": item["version"]},
                }
        for relative in [
            "ios/Packages/MindCore/Package.resolved",
            "ios/SocraticMind.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved",
        ]:
            value = json.loads((ROOT / relative).read_text())
            actual = {
                pin["identity"]: {key: pin[key] for key in ("kind", "location", "state")}
                for pin in value["pins"]
            }
            self.assertEqual(expected, actual, relative)
            self.assertEqual(len(expected), len(value["pins"]), "Duplicate pins are not allowed")
        package = (ROOT / "ios/Packages/MindCore/Package.swift").read_text()
        markdown = expected["swift-markdown"]
        self.assertIn(
            f'.package(url: "{markdown["location"]}", exact: "{markdown["state"]["version"]}")',
            package,
        )

    def test_ci_uses_resolved_versions_and_preserves_explicit_test_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch("scripts.ci.run_checks.ROOT", Path(temporary)),
                patch("scripts.ci.run_checks.run") as run,
                patch("scripts.ci.run_checks.xml_count"),
            ):
                swift_tests(["MarkdownContractTests", "MarkdownRendererTests"])
            command = run.call_args.args[0]
            self.assertIn("--force-resolved-versions", command)
            self.assertEqual(
                "MarkdownContractTests|MarkdownRendererTests",
                command[command.index("--filter") + 1],
            )


if __name__ == "__main__":
    unittest.main()
