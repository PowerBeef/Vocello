"""Build receipts bind an optimization label to the executable that ran (scripts/lib/build_provenance.py)."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from lib.build_provenance import ProvenanceError, load_build_provenance  # noqa: E402


class BuildProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.executable = self.root / "build" / "app"
        self.executable.parent.mkdir(parents=True)
        self.executable.write_bytes(b"machine code")
        self.receipt = self.root / "last-build.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, **overrides) -> Path:
        payload = {
            "schemaVersion": 1,
            "producer": "scripts/ios_device.sh build --optimized",
            "status": "passed",
            "platform": "ios",
            "optimization": "O",
            "executableRelativePath": "build/app",
            "executableSHA256": hashlib.sha256(b"machine code").hexdigest(),
        }
        payload.update(overrides)
        self.receipt.write_text(json.dumps(payload), encoding="utf-8")
        return self.receipt

    def test_a_complete_receipt_yields_the_normalised_optimization(self) -> None:
        receipt = load_build_provenance(self.write(), platform="ios", root=self.root)
        self.assertEqual(receipt["optimization"], "-O")
        self.assertEqual(receipt["executable"], self.executable.resolve())
        self.write(optimization="Onone")
        self.assertEqual(load_build_provenance(self.receipt, platform="ios", root=self.root)["optimization"], "-Onone")

    def test_receipts_that_cannot_prove_the_label_are_refused(self) -> None:
        cases = {
            "status": {"status": "failed"},
            "platform": {"platform": "macos"},
            "optimization": {"optimization": "Osize"},
            "executable": {"executableRelativePath": "build/missing"},
            "digest": {"executableSHA256": "0" * 64},
            "outside": {"executableRelativePath": "../outside"},
        }
        for name, overrides in cases.items():
            with self.subTest(name):
                self.write(**overrides)
                with self.assertRaises(ProvenanceError):
                    load_build_provenance(self.receipt, platform="ios", root=self.root)
        self.write()
        del_payload = json.loads(self.receipt.read_text())
        del del_payload["executableSHA256"]
        self.receipt.write_text(json.dumps(del_payload))
        with self.assertRaisesRegex(ProvenanceError, "digest"):
            load_build_provenance(self.receipt, platform="ios", root=self.root)

    def test_a_rebuilt_executable_invalidates_the_receipt(self) -> None:
        self.write()
        self.executable.write_bytes(b"rebuilt")
        with self.assertRaisesRegex(ProvenanceError, "changed since"):
            load_build_provenance(self.receipt, platform="ios", root=self.root)

    def test_the_executed_digest_and_producer_are_checked_when_given(self) -> None:
        self.write()
        with self.assertRaisesRegex(ProvenanceError, "binary that produced"):
            load_build_provenance(self.receipt, platform="ios", root=self.root, executed_sha256="f" * 64)
        with self.assertRaisesRegex(ProvenanceError, "producer"):
            load_build_provenance(
                self.receipt, platform="ios", root=self.root, producer_prefix="scripts/ui_test.sh",
            )
        receipt = load_build_provenance(
            self.receipt, platform="ios", root=self.root,
            executed_sha256=hashlib.sha256(b"machine code").hexdigest().upper(),
            producer_prefix="scripts/ios_device.sh build",
        )
        self.assertEqual(receipt["optimization"], "-O")


if __name__ == "__main__":
    unittest.main()
