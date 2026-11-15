"""Verify release guards and archive boundaries without HA dependencies."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from tools import build_release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.component = self.root / "custom_components/yeelight_curtain_ble"
        self.component.mkdir(parents=True)
        (self.component / "manifest.json").write_text('{"version":"0.1.1"}')
        (self.root / "INSTALL.md").write_text("Install")
        (self.root / "CHANGELOG.md").write_text(
            "# Changes\n\n## 0.1.1 — 2026-11-15\n\nNew presets.\n\n## 0.1.0\n\nOld notes.\n"
        )
        self.addCleanup(patch.stopall)
        patch.object(build_release, "ROOT", self.root).start()
        patch.object(build_release, "COMPONENT", self.component).start()

    def test_mismatched_tag_does_not_build(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            build_release.build_release("0.1.2")
        self.assertFalse((self.root / "dist").exists())

    def test_invalid_version_does_not_build(self):
        (self.component / "manifest.json").write_text('{"version":"../unsafe"}')
        with self.assertRaisesRegex(ValueError, "MAJOR.MINOR.PATCH"):
            build_release.build_release()
        self.assertFalse((self.root / "dist").exists())

    def test_missing_release_notes_does_not_build(self):
        (self.root / "CHANGELOG.md").write_text("## 0.1.0\n\nOld notes.\n")
        with self.assertRaisesRegex(ValueError, "Missing CHANGELOG"):
            build_release.build_release("0.1.1")
        self.assertFalse((self.root / "dist").exists())

    def test_archive_contains_assets_but_no_research_data(self):
        for name in ("presets/tree.gif", "brand/icon.png", "translations/ru.json", "client.py", "www/card.js"):
            target = self.component / name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(b"bundled asset")
        (self.component / "private.log").write_text("private")
        (self.root / "capture.cfa").write_text("private")
        output = build_release.build_release("0.1.1")
        with ZipFile(output) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(
                set(archive.namelist()),
                {"INSTALL.md"}
                | {
                    "custom_components/yeelight_curtain_ble/" + name
                    for name in (
                        "manifest.json", "presets/tree.gif", "brand/icon.png",
                        "translations/ru.json", "client.py",
                        "www/card.js",
                    )
                },
            )
            self.assertEqual(json.loads(archive.read("custom_components/yeelight_curtain_ble/manifest.json"))["version"], "0.1.1")
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        self.assertEqual(output.with_suffix(".zip.sha256").read_text(), f"{digest}  {output.name}\n")
        self.assertEqual((output.parent / "release-notes.md").read_text(), "New presets.\n")


if __name__ == "__main__":
    unittest.main()
