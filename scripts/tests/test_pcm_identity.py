#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "pcm_identity.py"
SPEC = importlib.util.spec_from_file_location("pcm_identity", SCRIPT)
assert SPEC and SPEC.loader
identity = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = identity
SPEC.loader.exec_module(identity)


def take(key: str, digest: str, *, wall: float, audio: float = 10.0, warm: bool = True,
         first_chunk: float | None = 150.0) -> dict:
    mode, _, length = key.split("/")[0], None, key.split("/")[2]
    return {
        "key": key,
        "mode": mode,
        "length": length,
        "warmState": "warm" if warm else "cold",
        "pcmSHA256": digest,
        "audioSeconds": audio,
        "wallSeconds": wall,
        "firstChunkMS": first_chunk,
    }


def manifest(takes: list[dict], seed: int = 7) -> dict:
    return {"schemaVersion": identity.SCHEMA_VERSION, "seed": seed, "takes": takes}


class IdentityReportTests(unittest.TestCase):
    def test_equal_digests_are_identical_and_speed_is_paired_per_cell(self) -> None:
        before = manifest([
            take("custom/speed/medium/warm#0", "a" * 64, wall=3.0),
            take("custom/speed/medium/warm#1", "b" * 64, wall=3.2),
            take("custom/speed/medium/cold#0", "c" * 64, wall=5.0, warm=False),
        ])
        after = manifest([
            take("custom/speed/medium/warm#0", "a" * 64, wall=2.7),
            take("custom/speed/medium/warm#1", "b" * 64, wall=2.9),
            take("custom/speed/medium/cold#0", "c" * 64, wall=4.0, warm=False),
        ])
        report = identity.identity_report(before, after)
        self.assertTrue(report["identical"])
        self.assertEqual(report["comparedTakes"], 3)
        cell = report["warmSpeed"]["custom/medium"]
        self.assertEqual(cell["takes"], 2)
        self.assertAlmostEqual(cell["medianRTFBefore"], 0.31)
        self.assertAlmostEqual(cell["medianRTFAfter"], 0.28)
        self.assertLess(cell["rtfChangePercent"], 0)
        self.assertNotIn("hostCPU", report)

    def test_host_cpu_is_compared_only_over_identical_takes(self) -> None:
        takes = [take("custom/speed/medium/warm#0", "a" * 64, wall=3.0)]
        before = manifest(takes) | {"benchCPUSeconds": 20.0}
        after = manifest(takes) | {"benchCPUSeconds": 18.0}
        report = identity.identity_report(before, after)
        self.assertAlmostEqual(report["hostCPU"]["changePercent"], -10.0)
        changed = manifest([take("custom/speed/medium/warm#0", "f" * 64, wall=3.0)])
        changed["benchCPUSeconds"] = 18.0
        self.assertNotIn("hostCPU", identity.identity_report(before, changed))

    def test_one_changed_sample_stream_is_named(self) -> None:
        before = manifest([take("design/speed/short/warm#0", "a" * 64, wall=1.0)])
        after = manifest([take("design/speed/short/warm#0", "d" * 64, wall=1.0)])
        report = identity.identity_report(before, after)
        self.assertFalse(report["identical"])
        self.assertEqual(report["differing"], ["design/speed/short/warm#0"])

    def test_a_missing_or_extra_take_is_not_identity(self) -> None:
        before = manifest([
            take("clone/speed/short/warm#0", "a" * 64, wall=1.0),
            take("clone/speed/short/warm#1", "b" * 64, wall=1.0),
        ])
        after = manifest([
            take("clone/speed/short/warm#0", "a" * 64, wall=1.0),
            take("clone/speed/medium/warm#0", "e" * 64, wall=1.0),
        ])
        report = identity.identity_report(before, after)
        self.assertFalse(report["identical"])
        self.assertEqual(report["missing"], ["clone/speed/short/warm#1"])
        self.assertEqual(report["extra"], ["clone/speed/medium/warm#0"])

    def test_different_seeds_are_refused(self) -> None:
        with self.assertRaises(RuntimeError):
            identity.identity_report(manifest([], seed=1), manifest([], seed=2))

    def test_different_qos_clamps_are_refused(self) -> None:
        clamped = manifest([]) | {"qosClamp": "background"}
        with self.assertRaises(RuntimeError):
            identity.identity_report(manifest([]), clamped)
        self.assertTrue(identity.identity_report(clamped, dict(clamped))["identical"])


class OverrideParsingTests(unittest.TestCase):
    def test_only_runtime_keys_pass_through(self) -> None:
        self.assertEqual(
            identity.parse_overrides(["MLX_MAX_OPS_PER_BUFFER=80", "QWENVOICE_DEBUG=1"]),
            {"MLX_MAX_OPS_PER_BUFFER": "80", "QWENVOICE_DEBUG": "1"},
        )
        for bad in ("PATH=/tmp", "MLX_MAX_OPS_PER_BUFFER", "=3"):
            with self.assertRaises(ValueError):
                identity.parse_overrides([bad])


if __name__ == "__main__":
    unittest.main()
