#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
from typing import Any
import unittest
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import benchmark_memory  # noqa: E402
from benchmark_memory import (  # noqa: E402
    MemoryEvidenceError,
    load_ios_memory_budget,
    load_unobserved_gap_bound,
    qualify_memory_rows,
)


# Drops a policy block from a patched fixture policy.
ABSENT = object()

ENGINE_BOUNDARIES = [
    "before_preparation", "before_model_load", "after_model_load",
    "before_mode_preparation", "before_prewarm", "after_prewarm",
    "after_mode_preparation",
    "after_preparation", "session_start", "first_chunk",
    "final_audio_materialized", "before_final_wav", "before_audio_qc",
    "after_audio_qc", "after_final_wav", "post_generation", "terminal_success",
]
ENGINE_BOUNDARY_NAMES = [
    "preparation-start", "mode-preparation-start", "mode-preparation-end",
    "prewarm-start", "prewarm-end", "model-load-start", "model-load-end",
    "preparation-end", "session-start", "first-output",
    "final-audio-materialized", "final-wav-start", "audio-qc-start",
    "audio-qc-end", "final-wav-end", "post-generation-memory-action-start",
    "post-generation-memory-action-end", "terminal",
]


def samples(
    *, role: str, boundaries: list[str], ios: bool, footprint: float = 3000.0,
    headroom: float = 3000.0, uptime_offset: int = 0, kernel_ledgers: bool = False,
) -> list[dict]:
    kinds = [("start", None)] + [("boundary", name) for name in boundaries]
    kinds += [("periodic", None), ("stop", None)]
    result = []
    lifetime_peak = 0.0
    for index, (kind, boundary) in enumerate(kinds):
        elapsed = index * 40_000_000
        allocated = 2000.0 + index
        recommended = 5000.0
        sample = {
            "tMS": elapsed // 1_000_000,
            "capturedElapsedNS": elapsed,
            "capturedUptimeNS": 10_000_000_000 + uptime_offset + elapsed,
            "kind": kind,
            "boundary": boundary,
            "processRole": role,
            "memoryCaptureSucceeded": True,
            "threadCaptureSucceeded": True,
            "headroomCaptureSucceeded": True if ios else False,
            "metalCaptureSucceeded": True,
            "totalDeviceRAMMB": 8192.0,
            "residentMB": footprint - 200 + index,
            "physFootprintMB": footprint + index,
            "compressedMB": 20.0 + index,
            "gpuAllocatedMB": allocated,
            "gpuRecommendedWorkingSetMB": recommended,
            "gpuWorkingSetUsageRatio": allocated / recommended,
            "threads": 10,
            "thermalState": "nominal",
        }
        if ios:
            sample["headroomMB"] = headroom - index
            sample["impliedProcessLimitMB"] = sample["physFootprintMB"] + sample["headroomMB"]
        if kernel_ledgers:
            # The kernel's lifetime high-water mark: never below a reading and
            # never falling; the graphics ledger follows the Metal allocation.
            lifetime_peak = max(lifetime_peak, sample["physFootprintMB"])
            sample["kernelPhysFootprintPeakMB"] = lifetime_peak
            sample["graphicsFootprintMB"] = allocated - 100
        result.append(sample)
    return result


def row(generation_id: str, sample_rows: list[dict], *, layer: str, ios: bool) -> dict:
    footprint = [sample["physFootprintMB"] for sample in sample_rows]
    resident = [sample["residentMB"] for sample in sample_rows]
    compressed = [sample["compressedMB"] for sample in sample_rows]
    gpu = [sample["gpuAllocatedMB"] for sample in sample_rows]
    headroom = [sample.get("headroomMB") for sample in sample_rows if "headroomMB" in sample]
    boundaries = [sample["boundary"] for sample in sample_rows if sample["kind"] == "boundary"]
    required_names = ENGINE_BOUNDARY_NAMES if layer == "engine" else ["app-submit", "app-terminal"]
    coverage = {
        "totalSampleCount": len(sample_rows),
        "memorySuccessfulSampleCount": len(sample_rows),
        "memoryCaptureFailureCount": 0,
        "memoryCoverageRatio": 1.0,
        "threadSuccessfulSampleCount": len(sample_rows),
        "threadCaptureFailureCount": 0,
        "threadCoverageRatio": 1.0,
        "headroomSuccessfulSampleCount": len(sample_rows) if ios else 0,
        "headroomCoverageRatio": 1.0 if ios else 0.0,
        "metalSuccessfulSampleCount": len(sample_rows),
        "metalCoverageRatio": 1.0,
        "processResourceCaptureSucceeded": True,
        "processResourceCaptureFailureCount": 0,
    }
    boundary_coverage = {
        "requiredBoundaryNames": required_names,
        "satisfiedBoundaryNames": required_names,
        "missingBoundaryNames": [],
        "coverageRatio": 1.0,
    }
    summary = {
        "processRole": sample_rows[0]["processRole"],
        "sampleCount": len(sample_rows),
        "periodicSampleCount": sum(sample["kind"] == "periodic" for sample in sample_rows),
        "boundarySampleCount": len(boundaries),
        "captureFailureCount": 0,
        "missedPeriodicDeadlineCount": 0,
        "targetIntervalNS": 500_000_000,
        "residentPeakMB": max(resident),
        "physFootprintPeakMB": max(footprint),
        "compressedPeakMB": max(compressed),
        "gpuAllocatedPeakMB": max(gpu),
        "gpuRecommendedWorkingSetMB": max(
            sample["gpuRecommendedWorkingSetMB"] for sample in sample_rows
        ),
        "gpuWorkingSetUsageRatioPeak": max(
            sample["gpuWorkingSetUsageRatio"] for sample in sample_rows
        ),
        "captureCoverage": coverage,
        "boundaryCoverage": boundary_coverage,
        "resourceCaptureSucceeded": True,
        "resourceCaptureFailureCount": 0,
        "processResourceUsage": {
            "userCPUTimeMS": 20.0,
            "systemCPUTimeMS": 5.0,
            "minorPageFaults": 10,
            "majorPageFaults": 0,
            "voluntaryContextSwitches": 3,
            "involuntaryContextSwitches": 1,
            "blockInputOperations": 0,
            "blockOutputOperations": 2,
        },
    }
    if ios:
        summary.update({
            "headroomMinMB": min(headroom),
            "totalDeviceRAMMB": 8192.0,
        })
    memory_metrics = {
        "processRole": sample_rows[0]["processRole"],
        "captureCoverage": coverage,
        "boundaryCoverage": boundary_coverage,
        "worstPressureBand": "healthy",
        "events": [],
        "mlxCumulativePeakMB": 2200.0 if layer == "engine" else None,
        "mlxActivePeakMB": 2100.0 if layer == "engine" else None,
        "mlxCachePeakMB": 100.0 if layer == "engine" else None,
        "mlxStageCount": 1 if layer == "engine" else 0,
        "mlxStageNames": ["after_load"] if layer == "engine" else [],
    }
    return {
        "schemaVersion": 8,
        "generationID": generation_id,
        # macOS hosts the engine in the app process: both layers name one PID.
        "processIdentifier": 4242,
        "summary": summary,
        "memoryMetrics": memory_metrics,
        "backendMetrics": {"stages": []},
        "notes": {},
    }


class MemoryEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_sidecar(self, layer: str, generation_id: str, rows: list[dict]) -> None:
        directory = self.root / layer
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"samples-{generation_id}.jsonl").write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in rows),
            encoding="utf-8",
        )

    def ios_fixture(self, generation_id: str = "generation-001") -> tuple[dict, list[dict]]:
        sidecar = samples(role="engine", boundaries=ENGINE_BOUNDARIES, ios=True)
        return row(generation_id, sidecar, layer="engine", ios=True), sidecar

    def test_ios_exact_sidecar_is_qualified_and_unrelated_rows_do_not_enter_digest(self) -> None:
        engine, sidecar = self.ios_fixture()
        self.write_sidecar("engine", engine["generationID"], sidecar)
        qualified, aggregate = qualify_memory_rows(
            rows=[engine], diagnostics=self.root, platform="ios"
        )
        self.assertEqual(qualified[0].status, "qualified")
        self.assertEqual(qualified[0].metrics["samplerCaptureFailureCount"], 0)
        self.assertGreater(qualified[0].metrics["minimumHeadroomMB"], 0)
        digest = aggregate["sampleSidecarsDigest"]
        self.write_sidecar("engine", "unrelated-generation", sidecar)
        _, repeated = qualify_memory_rows(rows=[engine], diagnostics=self.root, platform="ios")
        self.assertEqual(repeated["sampleSidecarsDigest"], digest)

    def test_missing_nonfinite_failed_and_incomplete_memory_evidence_fail(self) -> None:
        engine, sidecar = self.ios_fixture()
        cases = []
        missing = copy.deepcopy(sidecar)
        missing[0].pop("residentMB")
        cases.append(missing)
        nonfinite = copy.deepcopy(sidecar)
        nonfinite[0]["residentMB"] = float("nan")
        cases.append(nonfinite)
        failed = copy.deepcopy(sidecar)
        failed[0]["memoryCaptureSucceeded"] = False
        cases.append(failed)
        incomplete = copy.deepcopy(sidecar)
        incomplete = [item for item in incomplete if item.get("boundary") != "after_model_load"]
        cases.append(incomplete)
        for index, rows in enumerate(cases):
            with self.subTest(index=index):
                fixture = copy.deepcopy(engine)
                if index == 3:
                    fixture = row(engine["generationID"], rows, layer="engine", ios=True)
                self.write_sidecar("engine", engine["generationID"], rows)
                with self.assertRaises(MemoryEvidenceError):
                    qualify_memory_rows(rows=[fixture], diagnostics=self.root, platform="ios")

    def test_required_resource_metal_headroom_and_budget_fields_are_strict(self) -> None:
        engine, original = self.ios_fixture()
        mutations = {
            "compressed": lambda rows: rows[0].pop("compressedMB"),
            "metal flag": lambda rows: rows[0].__setitem__("metalCaptureSucceeded", False),
            "headroom": lambda rows: rows[0].pop("headroomMB"),
            "implied limit": lambda rows: rows[0].pop("impliedProcessLimitMB"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                sidecar = copy.deepcopy(original)
                mutate(sidecar)
                self.write_sidecar("engine", engine["generationID"], sidecar)
                with self.assertRaises(MemoryEvidenceError):
                    qualify_memory_rows(rows=[engine], diagnostics=self.root, platform="ios")

        sidecar = copy.deepcopy(original)
        failed_resource = row(engine["generationID"], sidecar, layer="engine", ios=True)
        failed_resource["summary"]["resourceCaptureSucceeded"] = False
        failed_resource["summary"]["resourceCaptureFailureCount"] = 1
        failed_resource["summary"]["captureCoverage"]["processResourceCaptureSucceeded"] = False
        failed_resource["summary"]["captureCoverage"]["processResourceCaptureFailureCount"] = 1
        failed_resource["memoryMetrics"]["captureCoverage"] = failed_resource["summary"]["captureCoverage"]
        self.write_sidecar("engine", engine["generationID"], sidecar)
        with self.assertRaisesRegex(MemoryEvidenceError, "capture"):
            qualify_memory_rows(rows=[failed_resource], diagnostics=self.root, platform="ios")

    def test_thread_capture_failure_does_not_masquerade_as_memory_failure(self) -> None:
        engine, sidecar = self.ios_fixture()
        for sample in sidecar:
            sample["threadCaptureSucceeded"] = False
        engine = row(engine["generationID"], sidecar, layer="engine", ios=True)
        coverage = engine["summary"]["captureCoverage"]
        coverage.update({
            "threadSuccessfulSampleCount": 0,
            "threadCaptureFailureCount": len(sidecar),
            "threadCoverageRatio": 0.0,
        })
        engine["memoryMetrics"]["captureCoverage"] = coverage
        self.write_sidecar("engine", engine["generationID"], sidecar)
        qualified, _ = qualify_memory_rows(
            rows=[engine], diagnostics=self.root, platform="ios"
        )
        self.assertEqual(qualified[0].status, "qualified")

    def test_missed_deadlines_are_informational_under_contract_v2(self) -> None:
        # Coverage counts deadlines honoured, not whether the peak was seen
        # (audit #66): two missed deadlines with no long gap still qualify.
        engine, sidecar = self.ios_fixture()
        engine["summary"]["missedPeriodicDeadlineCount"] = 2
        self.write_sidecar("engine", engine["generationID"], sidecar)
        qualified, aggregate = qualify_memory_rows(
            rows=[engine], diagnostics=self.root, platform="ios"
        )
        self.assertEqual(aggregate["memoryContractVersion"], 2)
        self.assertEqual(qualified[0].status, "qualified")
        self.assertLess(qualified[0].metrics["samplerCoverage"], 1.0)
        self.assertEqual(qualified[0].metrics["samplerMissedDeadlineCount"], 2)
        self.assertEqual(qualified[0].metrics["samplerMaximumUnobservedGapMS"], 40.0)

    def gap_policy(self, floor_tiers: object = None, **block: object) -> Any:
        """A policy file declaring only the unobserved-gap bound, patched in.

        `floor_tiers` patches the floor-tier block's keys; ABSENT drops the block."""
        tiers: dict[str, Any] = {
            "deviceClasses": ["floor_8gb_mac", "iphone_pro"], "floorMS": 1000,
            "status": "provisional", "calibrationRunID": None,
        }
        if isinstance(floor_tiers, dict):
            tiers.update(floor_tiers)
        declared: dict[str, Any] = {
            "targetIntervalMultiple": 2.0, "floorMS": 500,
            "status": "provisional", "calibrationRunID": None,
        }
        if floor_tiers is not ABSENT:
            declared["floorTiers"] = tiers
        declared.update(block)
        path = self.root / "memory-qualification-policy.json"
        path.write_text(json.dumps({"unobservedGapBound": declared}), encoding="utf-8")
        return mock.patch.object(benchmark_memory, "MEMORY_QUALIFICATION_POLICY_PATH", path)

    def with_stop_after(self, engine: dict, base: list[dict], gap_ms: int,
                        target_ns: int = 500_000_000) -> dict:
        sidecar = copy.deepcopy(base)
        before_stop = sidecar[-2]
        stop = sidecar[-1]
        stop["capturedElapsedNS"] = before_stop["capturedElapsedNS"] + gap_ms * 1_000_000
        stop["capturedUptimeNS"] = before_stop["capturedUptimeNS"] + gap_ms * 1_000_000
        stop["tMS"] = stop["capturedElapsedNS"] // 1_000_000
        fixture = row(engine["generationID"], sidecar, layer="engine", ios=True)
        fixture["summary"]["targetIntervalNS"] = target_ns
        self.write_sidecar("engine", engine["generationID"], sidecar)
        return fixture

    def test_an_unobserved_gap_above_the_policy_bound_fails(self) -> None:
        engine, base = self.ios_fixture()
        with self.gap_policy(floor_tiers={"floorMS": 500}):
            # A 500 ms cadence: twice it, 1,000 ms, is the bound.
            qualified, _ = qualify_memory_rows(
                rows=[self.with_stop_after(engine, base, 1_000)],
                diagnostics=self.root, platform="ios",
            )
            self.assertEqual(qualified[0].metrics["samplerMaximumUnobservedGapMS"], 1_000.0)
            self.assertEqual(qualified[0].metrics["samplerUnobservedGapLimitMS"], 1_000.0)
            with self.assertRaisesRegex(MemoryEvidenceError, "unobserved for 1001.0 ms"):
                qualify_memory_rows(
                    rows=[self.with_stop_after(engine, base, 1_001)],
                    diagnostics=self.root, platform="ios",
                )
        # A 100 ms cadence on a Mac above the floor tiers: the 500 ms floor, not
        # twice the cadence, bounds it, so one scheduler stall on a fast-cadence
        # host does not fail a take.
        with self.gap_policy():
            for label, app_times, qualifies in (
                ("quiet", None, True), ("790 ms stall", [0, 5, 400, 810, 1_600], False),
            ):
                with self.subTest(label=label):
                    engine, engine_samples, app, app_samples = self.macos_pair(
                        "generation-fast-cadence", app_times_ms=app_times,
                    )
                    engine["notes"]["deviceClass"] = "high_memory_mac"
                    for layer in (engine, app):
                        layer["summary"]["targetIntervalNS"] = 100_000_000
                    if qualifies:
                        qualified, _ = self.qualify_macos(engine, engine_samples, app, app_samples)
                        self.assertEqual(qualified[0].metrics["samplerUnobservedGapLimitMS"], 500.0)
                    else:
                        with self.assertRaises(MemoryEvidenceError):
                            self.qualify_macos(engine, engine_samples, app, app_samples)

    def test_the_floor_tiers_keep_their_own_floor_until_calibrated(self) -> None:
        # The iPhone and the 8 GB Mac moved from 500 ms to a 250 ms cadence on
        # 2026-09-25. Twice it would halve their bound to 500 ms while only the
        # M6 is calibrated, so their tier keeps a 1,000 ms floor.
        engine, base = self.ios_fixture()
        with self.gap_policy():
            qualified, _ = qualify_memory_rows(
                rows=[self.with_stop_after(engine, base, 900, target_ns=250_000_000)],
                diagnostics=self.root, platform="ios",
            )
            self.assertEqual(qualified[0].metrics["samplerMaximumUnobservedGapMS"], 900.0)
            self.assertEqual(qualified[0].metrics["samplerUnobservedGapLimitMS"], 1_000.0)
            with self.assertRaises(MemoryEvidenceError):
                qualify_memory_rows(
                    rows=[self.with_stop_after(engine, base, 1_001, target_ns=250_000_000)],
                    diagnostics=self.root, platform="ios",
                )
            # A Mac takes its tier from the device class its engine row stamps:
            # a 790 ms stall at 250 ms passes the 8 GB floor tier and fails the
            # M6's 16 GB tier, as it does a row without the stamp.
            for device_class, qualifies in (
                ("floor_8gb_mac", True), ("mid_16gb_mac", False), (None, False),
            ):
                with self.subTest(device_class=device_class):
                    engine, engine_samples, app, app_samples = self.macos_pair(
                        f"generation-tier-{device_class}", app_times_ms=[0, 5, 400, 810, 1_600],
                    )
                    if device_class is not None:
                        engine["notes"]["deviceClass"] = device_class
                    for layer in (engine, app):
                        layer["summary"]["targetIntervalNS"] = 250_000_000
                    if qualifies:
                        qualified, _ = self.qualify_macos(engine, engine_samples, app, app_samples)
                        metrics = qualified[0].metrics
                        self.assertEqual(metrics["samplerMaximumUnobservedGapMS"], 790.0)
                        self.assertEqual(metrics["samplerUnobservedGapLimitMS"], 1_000.0)
                    else:
                        with self.assertRaises(MemoryEvidenceError):
                            self.qualify_macos(engine, engine_samples, app, app_samples)
        # A calibrated floor tier bounds its takes by the recorded floor.
        with self.gap_policy(floor_tiers={
            "floorMS": 600, "status": "calibrated", "calibrationRunID": "ios-memory-qualification-x",
        }):
            bound = load_unobserved_gap_bound()
            self.assertEqual(bound.limit_ms(250.0, floor_tier=True), 600.0)
            self.assertEqual(bound.limit_ms(250.0), 500.0)

    def test_a_malformed_unobserved_gap_bound_fails_closed(self) -> None:
        engine, base = self.ios_fixture()
        fixture = self.with_stop_after(engine, base, 100)
        cases: dict[str, dict[str, Any]] = {
            "multiple below one": {"targetIntervalMultiple": 0.5},
            "negative floor": {"floorMS": -1},
            "boolean floor": {"floorMS": True},
            "unknown status": {"status": "draft"},
            "calibrated without run": {"status": "calibrated"},
            "provisional with run": {"calibrationRunID": "mac-memory-qualification-x"},
            "no floor tiers": {"floor_tiers": ABSENT},
            "tier floor below the floor": {"floor_tiers": {"floorMS": 400}},
            "unknown tier class": {"floor_tiers": {"deviceClasses": ["iphone_pro", "floor_4gb_mac"]}},
            "tiers without the iPhone": {"floor_tiers": {"deviceClasses": ["floor_8gb_mac"]}},
            "tier calibrated without run": {"floor_tiers": {"status": "calibrated"}},
        }
        for label, block in cases.items():
            with self.subTest(label=label), self.gap_policy(**block):
                with self.assertRaises(MemoryEvidenceError):
                    qualify_memory_rows(rows=[fixture], diagnostics=self.root, platform="ios")
        with self.gap_policy(status="calibrated", calibrationRunID="mac-memory-qualification-x"):
            self.assertEqual(load_unobserved_gap_bound().limit_ms(250.0), 500.0)
        missing = self.root / "absent.json"
        with mock.patch.object(benchmark_memory, "MEMORY_QUALIFICATION_POLICY_PATH", missing):
            with self.assertRaises(MemoryEvidenceError):
                load_unobserved_gap_bound()

    def test_peak_fidelity_reports_the_miss_against_the_exact_mlx_peak(self) -> None:
        engine, sidecar = self.ios_fixture()
        self.write_sidecar("engine", engine["generationID"], sidecar)
        qualified, _ = qualify_memory_rows(rows=[engine], diagnostics=self.root, platform="ios")
        metrics = qualified[0].metrics
        # Sampled Metal peak 2,019 MB against the exact MLX peak of 2,200 MB.
        self.assertEqual(metrics["peakGPUAllocatedMB"], 2019.0)
        self.assertEqual(metrics["gpuPeakCaptureMissMB"], 181.0)
        self.assertEqual(qualified[0].status, "qualified")
        self.assertNotIn("kernelPhysFootprintPeakMB", metrics)

        engine["memoryMetrics"]["mlxCumulativePeakMB"] = 1500.0
        qualified, _ = qualify_memory_rows(rows=[engine], diagnostics=self.root, platform="ios")
        self.assertEqual(qualified[0].metrics["gpuPeakCaptureMissMB"], 0.0)

    def test_kernel_ledger_peak_is_exact_when_it_rose_inside_the_take(self) -> None:
        sidecar = samples(
            role="engine", boundaries=ENGINE_BOUNDARIES, ios=True, kernel_ledgers=True
        )
        # A 300 MB spike between two samples: the sampler misses it, the ledger does not.
        for sample in sidecar[10:]:
            sample["kernelPhysFootprintPeakMB"] = 3400.0
        engine = row("generation-kernel", sidecar, layer="engine", ios=True)
        engine["summary"].update({
            "kernelPhysFootprintPeakStartMB": 3000.0,
            "kernelPhysFootprintPeakMB": 3400.0,
            "graphicsFootprintEndMB": sidecar[-1]["graphicsFootprintMB"],
        })
        self.write_sidecar("engine", engine["generationID"], sidecar)
        qualified, _ = qualify_memory_rows(rows=[engine], diagnostics=self.root, platform="ios")
        metrics = qualified[0].metrics
        self.assertEqual(metrics["peakPhysicalFootprintMB"], 3000.0 + len(sidecar) - 1)
        self.assertEqual(metrics["kernelPhysFootprintPeakMB"], 3400.0)
        self.assertEqual(metrics["kernelPhysFootprintPeakExact"], 1)
        self.assertEqual(
            metrics["footprintPeakCaptureMissMB"], 3400.0 - metrics["peakPhysicalFootprintMB"]
        )
        self.assertEqual(metrics["graphicsFootprintEndMB"], sidecar[-1]["graphicsFootprintMB"])

        # A lifetime peak set before the take is only an upper bound: no miss claimed.
        for sample in sidecar:
            sample["kernelPhysFootprintPeakMB"] = 5000.0
        upper = row("generation-kernel-upper", sidecar, layer="engine", ios=True)
        self.write_sidecar("engine", upper["generationID"], sidecar)
        qualified, _ = qualify_memory_rows(rows=[upper], diagnostics=self.root, platform="ios")
        self.assertEqual(qualified[0].metrics["kernelPhysFootprintPeakExact"], 0)
        self.assertNotIn("footprintPeakCaptureMissMB", qualified[0].metrics)

    def test_inconsistent_kernel_ledgers_fail_closed(self) -> None:
        base = samples(role="engine", boundaries=ENGINE_BOUNDARIES, ios=True, kernel_ledgers=True)
        mutations = {
            "below a sampled footprint": lambda rows: [
                sample.__setitem__("kernelPhysFootprintPeakMB", 2000.0) for sample in rows
            ],
            "missing on one sample": lambda rows: rows[3].pop("kernelPhysFootprintPeakMB"),
            "graphics not finite": lambda rows: rows[3].__setitem__("graphicsFootprintMB", -1.0),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                sidecar = copy.deepcopy(base)
                mutate(sidecar)
                engine = row("generation-kernel-bad", sidecar, layer="engine", ios=True)
                self.write_sidecar("engine", engine["generationID"], sidecar)
                with self.assertRaises(MemoryEvidenceError):
                    qualify_memory_rows(rows=[engine], diagnostics=self.root, platform="ios")
        # The typed summary must repeat the sampled ledger exactly.
        engine = row("generation-kernel-summary", base, layer="engine", ios=True)
        engine["summary"]["kernelPhysFootprintPeakMB"] = 1.0
        self.write_sidecar("engine", engine["generationID"], base)
        with self.assertRaisesRegex(MemoryEvidenceError, "kernelPhysFootprintPeakMB"):
            qualify_memory_rows(rows=[engine], diagnostics=self.root, platform="ios")

    def test_a_dropped_graphics_ledger_read_is_tolerated(self) -> None:
        # The graphics ledger is only reported: a sample whose read the sampler
        # dropped does not fail the take, and the end value is published only
        # when the last sample read it.
        sidecar = samples(
            role="engine", boundaries=ENGINE_BOUNDARIES, ios=True, kernel_ledgers=True
        )
        sidecar[3].pop("graphicsFootprintMB")
        engine = row("generation-graphics-gap", sidecar, layer="engine", ios=True)
        self.write_sidecar("engine", engine["generationID"], sidecar)
        qualified, _ = qualify_memory_rows(rows=[engine], diagnostics=self.root, platform="ios")
        self.assertEqual(
            qualified[0].metrics["graphicsFootprintEndMB"], sidecar[-1]["graphicsFootprintMB"]
        )
        sidecar[-1].pop("graphicsFootprintMB")
        engine = row("generation-graphics-end", sidecar, layer="engine", ios=True)
        self.write_sidecar("engine", engine["generationID"], sidecar)
        qualified, _ = qualify_memory_rows(rows=[engine], diagnostics=self.root, platform="ios")
        self.assertNotIn("graphicsFootprintEndMB", qualified[0].metrics)

    def test_kernel_ledger_read_out_of_sidecar_order_still_qualifies(self) -> None:
        # A periodic capture stamps its clock, is preempted, and reads the
        # ledger after a later-stamped boundary capture: the earlier-sorted
        # sample holds the newer, higher lifetime peak. That proves nothing
        # about the kernel, so the take qualifies on the series-level bound.
        sidecar = samples(
            role="engine", boundaries=ENGINE_BOUNDARIES, ios=True, kernel_ledgers=True
        )
        sidecar[5]["kernelPhysFootprintPeakMB"] = sidecar[6]["kernelPhysFootprintPeakMB"] + 50.0
        engine = row("generation-kernel-interleaved", sidecar, layer="engine", ios=True)
        self.write_sidecar("engine", engine["generationID"], sidecar)
        qualified, _ = qualify_memory_rows(rows=[engine], diagnostics=self.root, platform="ios")
        self.assertEqual(
            qualified[0].metrics["kernelPhysFootprintPeakMB"],
            max(sample["kernelPhysFootprintPeakMB"] for sample in sidecar),
        )

    def test_each_required_engine_boundary_is_checked_from_the_raw_sidecar(self) -> None:
        engine, original = self.ios_fixture()
        # first_chunk has an intentional final_audio_materialized fallback for
        # non-streaming generation and is therefore not individually required.
        for boundary in (item for item in ENGINE_BOUNDARIES if item != "first_chunk"):
            with self.subTest(boundary=boundary):
                sidecar = [
                    item for item in copy.deepcopy(original)
                    if item.get("boundary") != boundary
                ]
                fixture = row(engine["generationID"], sidecar, layer="engine", ios=True)
                self.write_sidecar("engine", engine["generationID"], sidecar)
                with self.assertRaisesRegex(MemoryEvidenceError, "boundar"):
                    qualify_memory_rows(rows=[fixture], diagnostics=self.root, platform="ios")

    def test_engine_lifecycle_boundaries_must_follow_production_partial_order(self) -> None:
        engine, original = self.ios_fixture()
        cases = {
            "model load": ("before_model_load", "after_model_load"),
            "mode preparation": ("before_mode_preparation", "after_mode_preparation"),
            "stream output": ("first_chunk", "final_audio_materialized"),
            "finalization": ("before_audio_qc", "after_final_wav"),
            "terminal": ("post_generation", "terminal_success"),
        }
        for label, (earlier, later) in cases.items():
            with self.subTest(label=label):
                sidecar = copy.deepcopy(original)
                earlier_sample = next(
                    item for item in sidecar if item.get("boundary") == earlier
                )
                later_sample = next(
                    item for item in sidecar if item.get("boundary") == later
                )
                earlier_sample["boundary"], later_sample["boundary"] = (
                    later_sample["boundary"], earlier_sample["boundary"]
                )
                fixture = row(engine["generationID"], sidecar, layer="engine", ios=True)
                self.write_sidecar("engine", engine["generationID"], sidecar)
                with self.assertRaisesRegex(MemoryEvidenceError, "lifecycle boundary order"):
                    qualify_memory_rows(
                        rows=[fixture], diagnostics=self.root, platform="ios"
                    )

    def test_duplicate_lifecycle_boundary_is_rejected(self) -> None:
        engine, original = self.ios_fixture()
        sidecar = copy.deepcopy(original)
        source_index = next(
            index for index, item in enumerate(sidecar)
            if item.get("boundary") == "before_model_load"
        )
        sidecar.insert(source_index + 1, copy.deepcopy(sidecar[source_index]))
        for index, sample in enumerate(sidecar):
            sample["capturedElapsedNS"] = index * 40_000_000
            sample["capturedUptimeNS"] = 10_000_000_000 + index * 40_000_000
            sample["tMS"] = index * 40
        fixture = row(engine["generationID"], sidecar, layer="engine", ios=True)
        self.write_sidecar("engine", engine["generationID"], sidecar)
        with self.assertRaisesRegex(MemoryEvidenceError, "duplicate lifecycle"):
            qualify_memory_rows(rows=[fixture], diagnostics=self.root, platform="ios")

    def test_collapsed_lifecycle_alternatives_share_one_ordered_position(self) -> None:
        engine, _ = self.ios_fixture()
        boundaries = [
            boundary for boundary in ENGINE_BOUNDARIES
            if boundary not in {"before_prewarm", "after_prewarm"}
        ]
        mode_start = boundaries.index("before_mode_preparation")
        boundaries.insert(mode_start + 1, "prewarm_skipped")
        sidecar = samples(role="engine", boundaries=boundaries, ios=True)
        fixture = row(engine["generationID"], sidecar, layer="engine", ios=True)
        self.write_sidecar("engine", engine["generationID"], sidecar)
        qualified, _ = qualify_memory_rows(
            rows=[fixture], diagnostics=self.root, platform="ios"
        )
        self.assertEqual(qualified[0].status, "qualified")

    def test_lifecycle_branches_cannot_mix_collapsed_and_expanded_forms(self) -> None:
        engine, original = self.ios_fixture()
        mutations = {
            "prewarm": ("after_prewarm", "prewarm_skipped"),
            "post-generation": ("post_generation", "before_post_generation_trim"),
        }
        for label, (anchor, addition) in mutations.items():
            with self.subTest(label=label):
                sidecar = copy.deepcopy(original)
                anchor_index = next(
                    index for index, item in enumerate(sidecar)
                    if item.get("boundary") == anchor
                )
                injected = copy.deepcopy(sidecar[anchor_index])
                injected["boundary"] = addition
                sidecar.insert(anchor_index, injected)
                for index, sample in enumerate(sidecar):
                    sample["capturedElapsedNS"] = index * 40_000_000
                    sample["capturedUptimeNS"] = 10_000_000_000 + index * 40_000_000
                    sample["tMS"] = index * 40
                fixture = row(engine["generationID"], sidecar, layer="engine", ios=True)
                self.write_sidecar("engine", engine["generationID"], sidecar)
                with self.assertRaisesRegex(MemoryEvidenceError, "mixes collapsed"):
                    qualify_memory_rows(
                        rows=[fixture], diagnostics=self.root, platform="ios"
                    )

    def test_post_generation_trim_requires_before_and_after_boundaries(self) -> None:
        engine, original = self.ios_fixture()
        trim_boundaries = [
            boundary for boundary in ENGINE_BOUNDARIES
            if boundary != "post_generation"
        ]
        terminal_index = trim_boundaries.index("terminal_success")
        trim_boundaries.insert(terminal_index, "before_post_generation_trim")
        before_only = samples(role="engine", boundaries=trim_boundaries, ios=True)
        incomplete = row(engine["generationID"], before_only, layer="engine", ios=True)
        self.write_sidecar("engine", engine["generationID"], before_only)
        with self.assertRaisesRegex(
            MemoryEvidenceError, "post-generation-memory-action-end"
        ):
            qualify_memory_rows(rows=[incomplete], diagnostics=self.root, platform="ios")

        complete_boundaries = list(trim_boundaries)
        before_index = complete_boundaries.index("before_post_generation_trim")
        complete_boundaries.insert(before_index + 1, "post_generation_trim")
        complete_samples = samples(
            role="engine", boundaries=complete_boundaries, ios=True
        )
        complete = row(engine["generationID"], complete_samples, layer="engine", ios=True)
        self.write_sidecar("engine", engine["generationID"], complete_samples)
        qualified, _ = qualify_memory_rows(
            rows=[complete], diagnostics=self.root, platform="ios"
        )
        self.assertEqual(qualified[0].status, "qualified")

    def qualify_ios_budget(
        self, footprint: float, headroom: float, *, remaining_offset: float | None = None,
    ) -> object:
        """Qualify one iPhone take; the fixture's footprint rises and its
        headroom falls by one MB per sample, over about twenty samples."""
        sidecar = samples(
            role="engine", boundaries=ENGINE_BOUNDARIES, ios=True,
            footprint=footprint, headroom=headroom,
        )
        if remaining_offset is not None:
            for sample in sidecar:
                sample["processLimitRemainingMB"] = sample["headroomMB"] + remaining_offset
        engine = row(
            f"generation-budget-{int(footprint)}-{int(headroom)}", sidecar, layer="engine", ios=True,
        )
        self.write_sidecar("engine", engine["generationID"], sidecar)
        return qualify_memory_rows(rows=[engine], diagnostics=self.root, platform="ios")[0][0]

    def test_ios_guarded_threshold_warns_and_critical_threshold_fails(self) -> None:
        # audit #68: the gate is the take's peak share of its own process budget.
        guarded = self.qualify_ios_budget(4600.0, 700.0)  # 4619 / 5300 = 0.87
        self.assertEqual(guarded.status, "qualifiedWithWarnings")
        self.assertIn("memory.budget.guarded", guarded.warnings)
        self.assertIn("memory.headroom.guarded", guarded.warnings)
        # 5519 / 5980 = 0.923, while the headroom (461 MiB) clears its own band.
        with self.assertRaisesRegex(MemoryEvidenceError, "process budget"):
            self.qualify_ios_budget(5500.0, 480.0)
        # An absolute footprint the old 5,200 MiB band failed is judged by its
        # budget: 5349 / 6830 = 0.78 on a device that grants 6.8 GB.
        roomy = self.qualify_ios_budget(5330.0, 1500.0)
        self.assertEqual(roomy.status, "qualified")
        self.assertAlmostEqual(roomy.metrics["peakProcessBudgetUtilization"], 5349 / 6830, places=6)

    def test_ios_evidence_gate_is_the_declared_budget_policy(self) -> None:
        # One threshold source: the app's bands and the evidence fractions come
        # from config/ios-memory-budget-policy.json (V-4, audit #68).
        bands = load_ios_memory_budget()
        self.assertEqual(
            (bands["guardedFootprintMB"], bands["criticalFootprintMB"],
             bands["healthyHeadroomMB"], bands["guardedHeadroomMB"],
             bands["criticalGPUWorkingSetUsageRatio"],
             bands["evidenceGuardedBudgetUtilization"],
             bands["evidenceCriticalBudgetUtilization"]),
            (4500.0, 5200.0, 768.0, 384.0, 0.8, 0.8, 0.92),
        )
        # The same-call limit_bytes_remaining wins over the separate headroom
        # reading for the budget, and their drift is published.
        take = self.qualify_ios_budget(4000.0, 1500.0, remaining_offset=-100.0)
        self.assertAlmostEqual(
            take.metrics["peakProcessBudgetUtilization"], 4019 / (4019 + 1381), places=6,
        )
        self.assertEqual(take.metrics["processLimitRemainingDriftMB"], 100.0)
        without = self.qualify_ios_budget(4000.0, 1500.0)
        self.assertNotIn("processLimitRemainingDriftMB", without.metrics)

    def test_ios_memory_budget_contract_fails_closed(self) -> None:
        cases = {
            "missing": None,
            "wrong-schema": {"schemaVersion": 2},
            "non-positive": {"schemaVersion": 1, "healthyHeadroomMB": 768, "guardedHeadroomMB": 0,
                             "guardedFootprintMB": 4500, "criticalFootprintMB": 5200,
                             "criticalGPUWorkingSetUsageRatio": 0.8},
            "inverted": {"schemaVersion": 1, "healthyHeadroomMB": 384, "guardedHeadroomMB": 768,
                         "guardedFootprintMB": 4500, "criticalFootprintMB": 5200,
                         "criticalGPUWorkingSetUsageRatio": 0.8,
                         "evidenceGuardedBudgetUtilization": 0.8,
                         "evidenceCriticalBudgetUtilization": 0.92},
            "no-evidence-gate": {"schemaVersion": 1, "healthyHeadroomMB": 768, "guardedHeadroomMB": 384,
                                 "guardedFootprintMB": 4500, "criticalFootprintMB": 5200,
                                 "criticalGPUWorkingSetUsageRatio": 0.8},
            "inverted-evidence-gate": {"schemaVersion": 1, "healthyHeadroomMB": 768, "guardedHeadroomMB": 384,
                                       "guardedFootprintMB": 4500, "criticalFootprintMB": 5200,
                                       "criticalGPUWorkingSetUsageRatio": 0.8,
                                       "evidenceGuardedBudgetUtilization": 0.95,
                                       "evidenceCriticalBudgetUtilization": 0.92},
        }
        for name, document in cases.items():
            path = self.root / f"policy-{name}.json"
            if document is not None:
                path.write_text(json.dumps(document), encoding="utf-8")
            with self.subTest(case=name), self.assertRaises(MemoryEvidenceError):
                load_ios_memory_budget(path)

    def test_hard_trim_and_application_warning_fail(self) -> None:
        engine, sidecar = self.ios_fixture()
        self.write_sidecar("engine", engine["generationID"], sidecar)
        engine["memoryMetrics"]["events"] = [{
            "kind": "trim-action", "trimLevel": "hardTrim",
        }]
        engine["backendMetrics"]["stages"] = [{
            "stage": "memory_trim", "metadata": {"level": "hardTrim"},
        }]
        with self.assertRaisesRegex(MemoryEvidenceError, "hardTrim"):
            qualify_memory_rows(rows=[engine], diagnostics=self.root, platform="ios")

    def test_typed_pressure_kinds_have_distinct_counts_and_severity(self) -> None:
        engine, sidecar = self.ios_fixture()
        self.write_sidecar("engine", engine["generationID"], sidecar)
        engine["memoryMetrics"]["events"] = [
            {"kind": "pressure-signal", "trimLevel": "softTrim"},
            {
                "kind": "budget-transition", "previousPressureBand": "healthy",
                "currentPressureBand": "guarded",
            },
            {"kind": "trim-action", "trimLevel": "softTrim"},
        ]
        engine["backendMetrics"]["stages"] = [
            {"stage": "memory_pressure", "metadata": {"level": "softTrim"}},
            {
                "stage": "memory_budget_transition",
                "metadata": {"previousBand": "healthy", "currentBand": "guarded"},
            },
            {"stage": "memory_trim", "metadata": {"level": "softTrim"}},
        ]
        qualified, _ = qualify_memory_rows(
            rows=[engine], diagnostics=self.root, platform="ios"
        )
        self.assertEqual(qualified[0].metrics["memoryPressureEventCount"], 1)
        self.assertEqual(qualified[0].metrics["memoryTrimCount"], 1)
        self.assertEqual(qualified[0].status, "qualifiedWithWarnings")

        failure_cases = (
            (
                {"kind": "budget-transition", "currentPressureBand": "critical"},
                {"stage": "memory_budget_transition", "metadata": {"currentBand": "critical"}},
                "critical",
            ),
            (
                {"kind": "unload"},
                {"stage": "memory_unload", "metadata": {}},
                "unload",
            ),
            (
                {"kind": "memory-exit"},
                None,
                "memory exit",
            ),
        )
        for event, mark, message in failure_cases:
            with self.subTest(event=event["kind"]):
                candidate = copy.deepcopy(engine)
                candidate["memoryMetrics"]["events"] = [event]
                candidate["backendMetrics"]["stages"] = [mark] if mark else []
                with self.assertRaisesRegex(MemoryEvidenceError, message):
                    qualify_memory_rows(
                        rows=[candidate], diagnostics=self.root, platform="ios"
                    )

    def policy_clear_fixture(self) -> dict:
        boundaries = [
            boundary for boundary in ENGINE_BOUNDARIES if boundary != "post_generation"
        ]
        terminal_index = boundaries.index("terminal_success")
        boundaries[terminal_index:terminal_index] = [
            "before_post_generation_trim", "post_generation_trim",
        ]
        sidecar = samples(role="engine", boundaries=boundaries, ios=True)
        engine = row("generation-policy-clear", sidecar, layer="engine", ios=True)
        self.write_sidecar("engine", engine["generationID"], sidecar)
        engine["memoryMetrics"]["events"] = [{
            "kind": "trim-action", "source": "post-generation",
            "trimLevel": "softTrim", "reasonCode": "post_generation_cache_clear",
        }]
        engine["backendMetrics"]["stages"] = [{
            "stage": "memory_trim",
            "metadata": {
                "level": "softTrim", "reason": "post_generation_cache_clear",
                "source": "post-generation",
            },
        }]
        return engine

    def test_routine_policy_cache_clear_is_counted_but_is_not_pressure(self) -> None:
        engine = self.policy_clear_fixture()
        qualified, aggregate = qualify_memory_rows(
            rows=[engine], diagnostics=self.root, platform="ios"
        )
        take = qualified[0]
        self.assertEqual(take.status, "qualified")
        self.assertEqual(take.warnings, ())
        self.assertEqual(aggregate["status"], "qualified")
        self.assertEqual(take.metrics["policyCacheClearCount"], 1)
        self.assertEqual(take.metrics["maximumPressureLevel"], 0)
        # Still a trim action: the legacy trim fields keep their meaning.
        self.assertEqual(take.metrics["memoryTrimCount"], 1)
        self.assertEqual(take.metrics["maximumTrimLevel"], 1)

    def test_only_the_exact_policy_clear_escapes_the_soft_trim_warning(self) -> None:
        # A kernel soft trim, a runtime (budget-relief) soft trim and a store
        # trim whose reason only starts with post_generation all stay pressure.
        variants = (
            ("kernel", "memory_pressure_warning"),
            ("runtime", "post_generation_cache_clear"),
            ("post-generation", "post_generation_guarded"),
        )
        for source, reason in variants:
            with self.subTest(source=source, reason=reason):
                engine = self.policy_clear_fixture()
                engine["memoryMetrics"]["events"][0].update(
                    {"source": source, "reasonCode": reason}
                )
                engine["backendMetrics"]["stages"][0]["metadata"].update(
                    {"source": source, "reason": reason}
                )
                qualified, _ = qualify_memory_rows(
                    rows=[engine], diagnostics=self.root, platform="ios"
                )
                take = qualified[0]
                self.assertEqual(take.status, "qualifiedWithWarnings")
                self.assertIn("memory.pressure.soft_trim", take.warnings)
                self.assertEqual(take.metrics["policyCacheClearCount"], 0)
                self.assertEqual(take.metrics["maximumPressureLevel"], 1)
                self.assertEqual(take.metrics["memoryTrimCount"], 1)

    def test_policy_clear_typed_event_and_stage_mark_must_agree(self) -> None:
        engine = self.policy_clear_fixture()
        # The stage mark says pressure trim while the typed event says routine
        # clear: the cross-check refuses rather than trusting either side.
        engine["backendMetrics"]["stages"][0]["metadata"]["source"] = "kernel"
        with self.assertRaises(MemoryEvidenceError):
            qualify_memory_rows(rows=[engine], diagnostics=self.root, platform="ios")

    def macos_pair(
        self, generation_id: str, *, engine_times_ms: list[int] | None = None,
        app_times_ms: list[int] | None = None, kernel_ledgers: bool = False,
    ) -> tuple[dict, list[dict], dict, list[dict]]:
        """Two sidecars of one process: the app sampler brackets the engine's."""
        base_uptime = 10_000_000_000
        engine_samples = samples(
            role="engine", boundaries=ENGINE_BOUNDARIES, ios=False, footprint=2500,
            kernel_ledgers=kernel_ledgers,
        )
        app_samples = samples(
            role="app", boundaries=["app_submit", "app_terminal"], ios=False,
            footprint=2500, kernel_ledgers=kernel_ledgers,
        )
        # The app sampler's order: start, submit, periodic, terminal, stop.
        app_samples = [app_samples[index] for index in (0, 1, 3, 2, 4)]
        if kernel_ledgers:
            lifetime_peak = 0.0
            for sample in app_samples:
                lifetime_peak = max(lifetime_peak, sample["physFootprintMB"])
                sample["kernelPhysFootprintPeakMB"] = lifetime_peak
        engine_times_ms = engine_times_ms or [10 + 40 * index for index in range(len(engine_samples))]
        app_times_ms = app_times_ms or [0, 5, 400, 810, 820]
        for layer_samples, times in ((engine_samples, engine_times_ms), (app_samples, app_times_ms)):
            self.assertEqual(len(layer_samples), len(times))
            for index, (sample, offset_ms) in enumerate(zip(layer_samples, times, strict=True)):
                sample["capturedElapsedNS"] = index * 40_000_000
                sample["capturedUptimeNS"] = base_uptime + offset_ms * 1_000_000
                sample["tMS"] = index * 40
        return (
            row(generation_id, engine_samples, layer="engine", ios=False), engine_samples,
            row(generation_id, app_samples, layer="app", ios=False), app_samples,
        )

    def qualify_macos(self, engine: dict, engine_samples: list[dict], app: dict, app_samples: list[dict]):
        self.write_sidecar("engine", engine["generationID"], engine_samples)
        self.write_sidecar("app", app["generationID"], app_samples)
        return qualify_memory_rows(
            rows=[engine], app_rows=[app], diagnostics=self.root, platform="macos",
            require_app_layer=True,
        )

    def test_same_process_layers_form_one_series_and_are_never_summed(self) -> None:
        # Both samplers read the one hosting process (audit #1/#2): the peak is
        # the largest single reading, never a sum of the two layers' readings.
        engine, engine_samples, app, app_samples = self.macos_pair("generation-macos-001")
        engine_samples[0]["physFootprintMB"] = 1000
        engine_samples[-1]["physFootprintMB"] = 3000
        app_samples[0]["physFootprintMB"] = 900
        app_samples[2]["physFootprintMB"] = 2990
        app_samples[-1]["physFootprintMB"] = 1100
        engine = row(engine["generationID"], engine_samples, layer="engine", ios=False)
        app = row(app["generationID"], app_samples, layer="app", ios=False)
        qualified, aggregate = self.qualify_macos(engine, engine_samples, app, app_samples)
        metrics = qualified[0].metrics
        self.assertEqual(aggregate["sampleSidecarCount"], 2)
        self.assertEqual(aggregate["memoryContractVersion"], 2)
        self.assertEqual(metrics["peakPhysicalFootprintMB"], 3000)
        # The series spans the app's submit-to-terminal window.
        self.assertEqual(metrics["physicalFootprintStartMB"], 900)
        self.assertEqual(metrics["physicalFootprintEndMB"], 1100)
        self.assertEqual(metrics["memoryTimeToPeakMS"], 770.0)
        # Metal likewise: the largest single reading (engine 2,019 MB), not 2,019 + 2,004.
        self.assertEqual(metrics["peakGPUAllocatedMB"], 2019.0)
        self.assertEqual(metrics["gpuWorkingSetUsageRatioPeak"], 2019.0 / 5000.0)
        self.assertEqual(metrics["mlxPeakMB"], 2200.0)
        self.assertEqual(metrics["gpuPeakCaptureMissMB"], 181.0)
        self.assertEqual(metrics["samplerSampleCount"], len(engine_samples) + len(app_samples))
        for key in (
            "alignedProcessSampleCount", "alignedProcessSampleCoverage",
            "alignedEngineSampleCoverage", "alignedAppSampleCoverage",
        ):
            self.assertNotIn(key, metrics)
        self.assertEqual(qualified[0].status, "qualified")

    def test_realistic_in_process_readings_give_a_single_process_peak(self) -> None:
        # Both layers read one footprint curve at interleaved times. The v1
        # aggregate summed each uptime pair and reported about twice the peak.
        engine, engine_samples, app, app_samples = self.macos_pair("generation-macos-curve")

        def process_footprint(uptime_ms: int) -> float:
            return 2000.0 + (400.0 if 395 <= uptime_ms <= 405 else uptime_ms / 10)

        for layer_samples in (engine_samples, app_samples):
            for sample in layer_samples:
                uptime_ms = (sample["capturedUptimeNS"] - 10_000_000_000) // 1_000_000
                sample["physFootprintMB"] = process_footprint(uptime_ms)
                sample["residentMB"] = sample["physFootprintMB"] - 200
        engine = row(engine["generationID"], engine_samples, layer="engine", ios=False)
        app = row(app["generationID"], app_samples, layer="app", ios=False)
        qualified, _ = self.qualify_macos(engine, engine_samples, app, app_samples)
        # The app's periodic reading at 400 ms is the only one inside the spike.
        self.assertEqual(qualified[0].metrics["peakPhysicalFootprintMB"], 2400.0)
        self.assertLess(qualified[0].metrics["peakPhysicalFootprintMB"], 2 * 2000.0)

    def test_duplicate_uptimes_are_counted_once(self) -> None:
        engine, engine_samples, app, app_samples = self.macos_pair(
            "generation-macos-duplicate", app_times_ms=[0, 10, 50, 810, 820],
        )
        # App readings at 10 and 50 ms share the engine's uptimes: the engine's are kept.
        app_samples[1]["physFootprintMB"] = 9999
        app_samples[2]["physFootprintMB"] = 9999
        engine = row(engine["generationID"], engine_samples, layer="engine", ios=False)
        app = row(app["generationID"], app_samples, layer="app", ios=False)
        qualified, _ = self.qualify_macos(engine, engine_samples, app, app_samples)
        self.assertLess(qualified[0].metrics["peakPhysicalFootprintMB"], 9999)

    def test_one_series_gap_rule_uses_both_layers_readings(self) -> None:
        # The engine sampler left 700 ms unobserved; the app sampler's reading
        # at 400 ms observed the process in between, so the take qualifies.
        engine_times = [10 + 5 * index for index in range(19)] + [900]
        engine, engine_samples, app, app_samples = self.macos_pair(
            "generation-macos-gap", engine_times_ms=engine_times,
            app_times_ms=[0, 5, 400, 950, 960],
        )
        qualified, _ = self.qualify_macos(engine, engine_samples, app, app_samples)
        self.assertEqual(qualified[0].metrics["samplerMaximumUnobservedGapMS"], 500.0)

        engine, engine_samples, app, app_samples = self.macos_pair(
            "generation-macos-gap-fail", engine_times_ms=engine_times,
            app_times_ms=[0, 5, 10, 2000, 2010],
        )
        with self.assertRaisesRegex(MemoryEvidenceError, "unobserved for 1100.0 ms"):
            self.qualify_macos(engine, engine_samples, app, app_samples)

    def test_two_processes_or_a_missing_pid_never_qualify(self) -> None:
        for label, engine_pid, app_pid, message in (
            ("split", 4242, 4343, "app PID 4343 and engine PID 4242 differ"),
            ("missing", 4242, None, "process identifier"),
            ("invalid", True, 4242, "process identifier"),
        ):
            with self.subTest(label=label):
                engine, engine_samples, app, app_samples = self.macos_pair(f"generation-pid-{label}")
                engine["processIdentifier"] = engine_pid
                if app_pid is None:
                    app.pop("processIdentifier")
                else:
                    app["processIdentifier"] = app_pid
                with self.assertRaisesRegex(MemoryEvidenceError, message):
                    self.qualify_macos(engine, engine_samples, app, app_samples)

    def test_one_series_kernel_ledgers_come_from_both_layers(self) -> None:
        engine, engine_samples, app, app_samples = self.macos_pair(
            "generation-macos-kernel", kernel_ledgers=True,
        )
        # The process-wide ledger read by the app at 810 ms caught a spike.
        app_samples[3]["kernelPhysFootprintPeakMB"] = 3600.0
        app_samples[4]["kernelPhysFootprintPeakMB"] = 3600.0
        app = row(app["generationID"], app_samples, layer="app", ios=False)
        qualified, _ = self.qualify_macos(engine, engine_samples, app, app_samples)
        metrics = qualified[0].metrics
        self.assertEqual(metrics["kernelPhysFootprintPeakMB"], 3600.0)
        self.assertEqual(metrics["kernelPhysFootprintPeakExact"], 1)
        self.assertEqual(metrics["footprintPeakCaptureMissMB"], 3600.0 - 2519.0)
        self.assertEqual(metrics["graphicsFootprintEndMB"], app_samples[-1]["graphicsFootprintMB"])

        engine, engine_samples, app, app_samples = self.macos_pair(
            "generation-macos-kernel-mixed", kernel_ledgers=True,
        )
        for sample in app_samples:
            sample.pop("kernelPhysFootprintPeakMB")
            sample.pop("graphicsFootprintMB")
        with self.assertRaisesRegex(MemoryEvidenceError, "different kernel ledgers"):
            self.qualify_macos(engine, engine_samples, app, app_samples)

    def test_missing_app_boundary_fails_macos_ui_qualification(self) -> None:
        generation_id = "generation-macos-app-boundary"
        engine_samples = samples(
            role="engine", boundaries=ENGINE_BOUNDARIES, ios=False, footprint=2500
        )
        app_samples = samples(
            role="app", boundaries=["app_submit"], ios=False, footprint=200
        )
        engine = row(generation_id, engine_samples, layer="engine", ios=False)
        app = row(generation_id, app_samples, layer="app", ios=False)
        self.write_sidecar("engine", generation_id, engine_samples)
        self.write_sidecar("app", generation_id, app_samples)
        with self.assertRaisesRegex(MemoryEvidenceError, "app memory boundaries"):
            qualify_memory_rows(
                rows=[engine], app_rows=[app], diagnostics=self.root,
                platform="macos", require_app_layer=True,
            )

    def test_app_lifecycle_terminal_cannot_precede_submit(self) -> None:
        generation_id = "generation-macos-app-order"
        engine_samples = samples(
            role="engine", boundaries=ENGINE_BOUNDARIES, ios=False, footprint=2500
        )
        app_samples = samples(
            role="app", boundaries=["app_terminal", "app_submit"],
            ios=False, footprint=200,
        )
        engine = row(generation_id, engine_samples, layer="engine", ios=False)
        app = row(generation_id, app_samples, layer="app", ios=False)
        self.write_sidecar("engine", generation_id, engine_samples)
        self.write_sidecar("app", generation_id, app_samples)
        with self.assertRaisesRegex(MemoryEvidenceError, "lifecycle boundary order"):
            qualify_memory_rows(
                rows=[engine], app_rows=[app], diagnostics=self.root,
                platform="macos", require_app_layer=True,
            )


if __name__ == "__main__":
    unittest.main()
