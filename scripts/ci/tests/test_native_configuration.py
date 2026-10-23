"""Prevent development-only cleartext exceptions from escaping into release configs."""

import plistlib
import unittest
import xml.etree.ElementTree as ET

from scripts.quality.changed_files import ROOT


class NativeConfigurationTests(unittest.TestCase):
    def test_android_cleartext_is_denied_except_explicit_debug_loopback_hosts(self):
        main = ET.parse(ROOT / "android/app/src/main/res/xml/network_security_config.xml").getroot()
        self.assertEqual("false", main.find("base-config").get("cleartextTrafficPermitted"))
        self.assertFalse(
            any(node.get("cleartextTrafficPermitted") == "true" for node in main.iter())
        )
        debug = ET.parse(
            ROOT / "android/app/src/debug/res/xml/network_security_config.xml"
        ).getroot()
        self.assertEqual("false", debug.find("base-config").get("cleartextTrafficPermitted"))
        permitted = []
        for group in debug.findall("domain-config"):
            if group.get("cleartextTrafficPermitted") == "true":
                for host in group.findall("domain"):
                    self.assertNotEqual("true", host.get("includeSubdomains"))
                    permitted.append(host.text)
        self.assertTrue(permitted)
        self.assertLessEqual(set(permitted), {"127.0.0.1", "localhost", "10.0.2.2"})
        manifest = ET.parse(ROOT / "android/app/src/main/AndroidManifest.xml").getroot()
        namespace = "{http://schemas.android.com/apk/res/android}"
        app = manifest.find("application")
        self.assertEqual(
            "@xml/network_security_config", app.get(namespace + "networkSecurityConfig")
        )
        self.assertEqual("false", app.get(namespace + "allowBackup"))

    def test_ios_release_has_no_ats_exception_and_debug_hosts_are_local(self):
        def plist(name):
            return plistlib.loads((ROOT / f"ios/Config/Info-{name}.plist").read_bytes())

        release = plist("Release")
        self.assertFalse(release.get("NSAppTransportSecurity"))
        debug = plist("Debug")["NSAppTransportSecurity"]
        self.assertNotIn("NSAllowsArbitraryLoads", debug)
        self.assertNotIn("NSAllowsLocalNetworking", debug)
        hosts = debug["NSExceptionDomains"]
        self.assertTrue(hosts)
        self.assertLessEqual(set(hosts), {"127.0.0.1", "localhost"})
        for values in hosts.values():
            self.assertIs(values["NSExceptionAllowsInsecureHTTPLoads"], True)
            self.assertIs(values["NSIncludesSubdomains"], False)


if __name__ == "__main__":
    unittest.main()
