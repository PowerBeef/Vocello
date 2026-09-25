#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from benchmark_memory import MemoryEvidenceError, load_ios_memory_budget, qualify_memory_rows  # noqa: E402


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
    headroom: float = 3000.0, uptime_offset: int = 0,
) -> list[dict]:
    kinds = [("start", None)] + [("boundary", name) for name in boundaries]
    kinds += [("periodic", None), ("stop", None)]
    result = []
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

    def test_periodic_coverage_warns_above_95_percent_and_fails_below_it(self) -> None:
        engine, base = self.ios_fixture()
        periodic = next(item for item in base if item["kind"] == "periodic")
        extras = []
        for offset in range(1, 20):
            sample = copy.deepcopy(periodic)
            sample["capturedElapsedNS"] += offset * 1_000_000
            sample["capturedUptimeNS"] += offset * 1_000_000
            sample["tMS"] = sample["capturedElapsedNS"] // 1_000_000
            extras.append(sample)
        sidecar = base[:-1] + extras + base[-1:]
        warning_row = row(engine["generationID"], sidecar, layer="engine", ios=True)
        warning_row["summary"]["missedPeriodicDeadlineCount"] = 1
        self.write_sidecar("engine", engine["generationID"], sidecar)
        qualified, _ = qualify_memory_rows(
            rows=[warning_row], diagnostics=self.root, platform="ios"
        )
        self.assertEqual(qualified[0].status, "qualifiedWithWarnings")
        self.assertIn("memory.sampler.coverage", qualified[0].warnings)

        failed_row = copy.deepcopy(warning_row)
        failed_row["summary"]["missedPeriodicDeadlineCount"] = 2
        with self.assertRaisesRegex(MemoryEvidenceError, "below 95%"):
            qualify_memory_rows(rows=[failed_row], diagnostics=self.root, platform="ios")

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

    def test_ios_guarded_threshold_warns_and_critical_threshold_fails(self) -> None:
        engine, guarded = self.ios_fixture()
        guarded = samples(
            role="engine", boundaries=ENGINE_BOUNDARIES, ios=True,
            footprint=4600.0, headroom=700.0,
        )
        engine = row(engine["generationID"], guarded, layer="engine", ios=True)
        self.write_sidecar("engine", engine["generationID"], guarded)
        qualified, _ = qualify_memory_rows(rows=[engine], diagnostics=self.root, platform="ios")
        self.assertEqual(qualified[0].status, "qualifiedWithWarnings")
        self.assertIn("memory.headroom.guarded", qualified[0].warnings)

        critical = samples(
            role="engine", boundaries=ENGINE_BOUNDARIES, ios=True,
            footprint=5330.0, headroom=700.0,
        )
        engine = row(engine["generationID"], critical, layer="engine", ios=True)
        self.write_sidecar("engine", engine["generationID"], critical)
        with self.assertRaises(MemoryEvidenceError):
            qualify_memory_rows(rows=[engine], diagnostics=self.root, platform="ios")

    def test_ios_footprint_bands_are_the_declared_shipping_policy(self) -> None:
        # V-4: the gate uses the app's MiB bands (4,500 guarded, 5,200 critical),
        # not its former 4.5/5.2 GiB copies. The fixture's peak is footprint + 19.
        bands = load_ios_memory_budget()
        self.assertEqual(
            (bands["guardedFootprintMB"], bands["criticalFootprintMB"],
             bands["healthyHeadroomMB"], bands["guardedHeadroomMB"],
             bands["criticalGPUWorkingSetUsageRatio"]),
            (4500.0, 5200.0, 768.0, 384.0, 0.8),
        )

        def qualify(footprint: float) -> object:
            sidecar = samples(
                role="engine", boundaries=ENGINE_BOUNDARIES, ios=True, footprint=footprint,
            )
            engine = row(f"generation-band-{int(footprint)}", sidecar, layer="engine", ios=True)
            self.write_sidecar("engine", engine["generationID"], sidecar)
            return qualify_memory_rows(rows=[engine], diagnostics=self.root, platform="ios")[0][0]

        below = qualify(4470.0)  # peak 4489
        self.assertNotIn("memory.footprint.guarded", below.warnings)
        guarded = qualify(4490.0)  # peak 4509: guarded now, silent under 4.5 GiB
        self.assertIn("memory.footprint.guarded", guarded.warnings)
        self.assertEqual(guarded.status, "qualifiedWithWarnings")
        with self.assertRaises(MemoryEvidenceError):
            qualify(5190.0)  # peak 5209: critical now, accepted under 5.2 GiB

    def test_ios_memory_budget_contract_fails_closed(self) -> None:
        cases = {
            "missing": None,
            "wrong-schema": {"schemaVersion": 2},
            "non-positive": {"schemaVersion": 1, "healthyHeadroomMB": 768, "guardedHeadroomMB": 0,
                             "guardedFootprintMB": 4500, "criticalFootprintMB": 5200,
                             "criticalGPUWorkingSetUsageRatio": 0.8},
            "inverted": {"schemaVersion": 1, "healthyHeadroomMB": 384, "guardedHeadroomMB": 768,
                         "guardedFootprintMB": 4500, "criticalFootprintMB": 5200,
                         "criticalGPUWorkingSetUsageRatio": 0.8},
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

    def test_macos_ui_uses_aligned_app_and_engine_samples_not_independent_peaks(self) -> None:
        generation_id = "generation-macos-001"
        engine_samples = samples(role="engine", boundaries=ENGINE_BOUNDARIES, ios=False, footprint=2500)
        app_samples = samples(
            role="app", boundaries=["app_submit", "app_terminal"], ios=False,
            footprint=200, uptime_offset=10_000_000,
        )
        # Put each layer's individual peak at opposite ends. The combined peak
        # must come from an aligned pair, never max(engine)+max(app).
        engine_samples[0]["physFootprintMB"] = 1000
        engine_samples[-1]["physFootprintMB"] = 3000
        app_samples[0]["physFootprintMB"] = 900
        app_samples[-1]["physFootprintMB"] = 100
        engine = row(generation_id, engine_samples, layer="engine", ios=False)
        app = row(generation_id, app_samples, layer="app", ios=False)
        self.write_sidecar("engine", generation_id, engine_samples)
        self.write_sidecar("app", generation_id, app_samples)
        qualified, aggregate = qualify_memory_rows(
            rows=[engine], app_rows=[app], diagnostics=self.root, platform="macos",
            require_app_layer=True,
        )
        self.assertEqual(aggregate["sampleSidecarCount"], 2)
        self.assertLess(
            qualified[0].metrics["peakPhysicalFootprintMB"],
            max(item["physFootprintMB"] for item in engine_samples)
            + max(item["physFootprintMB"] for item in app_samples),
        )
        self.assertEqual(qualified[0].metrics["mlxPeakMB"], 2200.0)
        self.assertGreater(qualified[0].metrics["gpuWorkingSetUsageRatioPeak"], 0)

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

    def test_macos_alignment_coverage_warns_at_95_percent_and_fails_below(self) -> None:
        generation_id = "generation-macos-alignment"
        base_uptime = 10_000_000_000

        def fixture(engine_times_ms: list[int]) -> tuple[dict, dict]:
            engine_samples = samples(
                role="engine", boundaries=ENGINE_BOUNDARIES, ios=False, footprint=2500
            )
            app_samples = samples(
                role="app", boundaries=["app_submit", "app_terminal"],
                ios=False, footprint=200,
            )
            self.assertEqual(len(engine_samples), len(engine_times_ms))
            for sample, offset_ms in zip(engine_samples, engine_times_ms, strict=True):
                sample["capturedUptimeNS"] = base_uptime + offset_ms * 1_000_000
            for sample, offset_ms in zip(
                app_samples, [0, 500, 1000, 1500, 3000], strict=True
            ):
                sample["capturedUptimeNS"] = base_uptime + offset_ms * 1_000_000
            engine = row(generation_id, engine_samples, layer="engine", ios=False)
            app = row(generation_id, app_samples, layer="app", ios=False)
            self.write_sidecar("engine", generation_id, engine_samples)
            self.write_sidecar("app", generation_id, app_samples)
            return engine, app

        engine, app = fixture(list(range(0, 1800, 100)) + [2200, 3000])
        qualified, _ = qualify_memory_rows(
            rows=[engine], app_rows=[app], diagnostics=self.root,
            platform="macos", require_app_layer=True,
        )
        self.assertEqual(qualified[0].metrics["alignedProcessSampleCoverage"], 0.95)
        self.assertEqual(qualified[0].metrics["alignedEngineSampleCoverage"], 0.95)
        self.assertEqual(qualified[0].metrics["alignedAppSampleCoverage"], 1.0)
        self.assertEqual(qualified[0].status, "qualifiedWithWarnings")
        self.assertIn("memory.alignment.coverage", qualified[0].warnings)

        engine, app = fixture(list(range(0, 1700, 100)) + [2100, 2300, 3000])
        with self.assertRaisesRegex(MemoryEvidenceError, "below 95%"):
            qualify_memory_rows(
                rows=[engine], app_rows=[app], diagnostics=self.root,
                platform="macos", require_app_layer=True,
            )

    def test_macos_alignment_uses_same_generation_edge_samples_within_cadence(self) -> None:
        generation_id = "generation-macos-edge-alignment"
        base_uptime = 10_000_000_000
        engine_samples = samples(
            role="engine", boundaries=ENGINE_BOUNDARIES, ios=False, footprint=2500
        )
        app_samples = samples(
            role="app", boundaries=["app_submit", "app_terminal"],
            ios=False, footprint=200,
        )

        # This mirrors a real short warm take: the app sampler starts 1 ms
        # before the engine sampler, while its next periodic sample lands just
        # beyond 500 ms from the initial engine boundary cluster.  The app's
        # start sample is valid same-generation evidence and must be available
        # to pair those engine samples even though it is just outside the
        # strict overlap interval.
        engine_times = list(range(1, 11)) + [522, 868, 1008, 1518] + list(range(1926, 1932))
        self.assertEqual(len(engine_samples), len(engine_times))
        app_times = [0, 0, 522, 1008, 1501, 2001, 2246, 2247]
        periodic = copy.deepcopy(next(item for item in app_samples if item["kind"] == "periodic"))
        app_samples = [copy.deepcopy(app_samples[0]), copy.deepcopy(app_samples[1])]
        app_samples.extend(copy.deepcopy(periodic) for _ in range(4))
        app_samples.extend([copy.deepcopy(app_samples[1]), copy.deepcopy(samples(
            role="app", boundaries=["app_submit", "app_terminal"],
            ios=False, footprint=200,
        )[-1])])
        app_samples[-2]["boundary"] = "app_terminal"
        self.assertEqual(len(app_samples), len(app_times))

        for index, (sample, offset_ms) in enumerate(zip(engine_samples, engine_times, strict=True)):
            sample["capturedElapsedNS"] = index * 40_000_000
            sample["capturedUptimeNS"] = base_uptime + offset_ms * 1_000_000
            sample["tMS"] = index * 40
        for index, (sample, offset_ms) in enumerate(zip(app_samples, app_times, strict=True)):
            sample["capturedElapsedNS"] = index * 40_000_000
            sample["capturedUptimeNS"] = base_uptime + offset_ms * 1_000_000
            sample["tMS"] = index * 40

        engine = row(generation_id, engine_samples, layer="engine", ios=False)
        app = row(generation_id, app_samples, layer="app", ios=False)
        self.write_sidecar("engine", generation_id, engine_samples)
        self.write_sidecar("app", generation_id, app_samples)
        qualified, _ = qualify_memory_rows(
            rows=[engine], app_rows=[app], diagnostics=self.root,
            platform="macos", require_app_layer=True,
        )
        self.assertEqual(qualified[0].metrics["alignedEngineSampleCoverage"], 1.0)
        self.assertEqual(qualified[0].metrics["alignedAppSampleCoverage"], 1.0)
        self.assertEqual(qualified[0].metrics["alignedProcessSampleCoverage"], 1.0)

    def test_macos_alignment_rejects_reverse_asymmetric_app_coverage(self) -> None:
        generation_id = "generation-macos-app-alignment"
        base_uptime = 10_000_000_000
        engine_samples = samples(
            role="engine", boundaries=ENGINE_BOUNDARIES, ios=False, footprint=2500
        )
        engine_times = list(range(0, 100, 10)) + list(range(2910, 3010, 10))
        self.assertEqual(len(engine_samples), len(engine_times))
        for sample, offset_ms in zip(engine_samples, engine_times, strict=True):
            sample["capturedUptimeNS"] = base_uptime + offset_ms * 1_000_000

        template = samples(
            role="app", boundaries=["app_submit", "app_terminal"],
            ios=False, footprint=200,
        )
        periodic = copy.deepcopy(next(item for item in template if item["kind"] == "periodic"))
        app_samples = [copy.deepcopy(template[0]), copy.deepcopy(template[1])]
        for _ in range(20):
            app_samples.append(copy.deepcopy(periodic))
        app_samples.extend([copy.deepcopy(template[2]), copy.deepcopy(template[-1])])
        app_times = [0, 10] + list(range(600, 2501, 100)) + [2990, 3000]
        self.assertEqual(len(app_samples), len(app_times))
        for index, (sample, offset_ms) in enumerate(zip(app_samples, app_times, strict=True)):
            sample["capturedElapsedNS"] = index * 40_000_000
            sample["capturedUptimeNS"] = base_uptime + offset_ms * 1_000_000
            sample["tMS"] = index * 40
        # This peak has no aligned engine sample and must never enter a publishable aggregate.
        app_samples[len(app_samples) // 2]["physFootprintMB"] = 5000

        engine = row(generation_id, engine_samples, layer="engine", ios=False)
        app = row(generation_id, app_samples, layer="app", ios=False)
        self.write_sidecar("engine", generation_id, engine_samples)
        self.write_sidecar("app", generation_id, app_samples)
        with self.assertRaisesRegex(MemoryEvidenceError, "below 95%"):
            qualify_memory_rows(
                rows=[engine], app_rows=[app], diagnostics=self.root,
                platform="macos", require_app_layer=True,
            )


if __name__ == "__main__":
    unittest.main()
