#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("privacy_scan", ROOT / "scripts/privacy_scan.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrivacyScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, name: str, text: str) -> str:
        (self.root / name).write_text(text, encoding="utf-8")
        return name

    def test_developer_home_paths_are_rejected_but_the_placeholder_is_not(self) -> None:
        bad = self.write("a.md", "see " + "/Users/" + "someone/Library/Logs for details\n")
        ok = self.write("b.md", "see /Users/example/Library/Logs for details\n")
        findings = MODULE.scan(self.root, [bad, ok])
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("a.md:1", findings[0])

    def test_complete_private_key_block_is_rejected_but_a_mentioned_header_is_not(self) -> None:
        key = self.write("key.txt", "-----BEGIN " + "PRIVATE KEY-----\nabc\n-----END " + "PRIVATE KEY-----\n")
        prose = self.write("doc.md", "paste the file including the -----BEGIN PRIVATE KEY----- header\n")
        self.assertEqual([f.split(":")[0] for f in MODULE.scan(self.root, [key, prose])], ["key.txt"])

    def test_fixed_credential_prefixes_and_credential_files_are_rejected(self) -> None:
        token = self.write("cfg.json", '{"aws": "' + "AKIA" + "ABCDEFGHIJKLMNOP" + '"}\n')
        (self.root / "AuthKey.p8").write_bytes(b"\0binary")
        findings = MODULE.scan(self.root, [token, "AuthKey.p8"])
        self.assertTrue(any("credential-shaped token" in f for f in findings), findings)
        self.assertTrue(any("credential file" in f for f in findings), findings)

    def test_missing_and_binary_paths_are_skipped(self) -> None:
        (self.root / "blob.bin").write_bytes(b"\0\1\2/Users/" + b"someone/")
        self.assertEqual(MODULE.scan(self.root, ["missing.md", "blob.bin"]), [])

    def test_repository_tracked_tree_is_clean(self) -> None:
        self.assertEqual(MODULE.main(["--root", str(ROOT)]), 0)


if __name__ == "__main__":
    unittest.main()
