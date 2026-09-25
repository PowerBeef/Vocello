import sys
import os
import json
import shutil
import tempfile
import inspect
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import summarize_generation_telemetry as sgt


def _make_cell(key, rtf, tokps, ttfc, phys, qc):
    return {
        "cellKey": list(key),
        "mode": key[0],
        "modelID": key[1],
        "warmState": key[2],
        "lenBucket": key[3],
        "n": 1,
        "rtf": rtf,
        "tokps": tokps,
        "ttfcMS": ttfc,
        "physFootMB": phys,
        "qcVerdict": qc,
    }


def test_rtf_increase_regression():
    """Standard RTF (wall ÷ audio) regresses when it rises."""
    key = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    baseline = [_make_cell(key, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    current = [_make_cell(key, rtf=1.1, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    regressions = sgt.compare_summaries(baseline, current, threshold=0.05)
    assert len(regressions) == 1
    assert regressions[0]["metric"] == "rtf"
    assert abs(regressions[0]["delta"] - 0.1) < 1e-9


def test_rtf_decrease_is_an_improvement():
    key = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    baseline = [_make_cell(key, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    current = [_make_cell(key, rtf=0.9, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    assert sgt.compare_summaries(baseline, current, threshold=0.05) == []


def test_legacy_baseline_compares_the_decode_speedup():
    """A pre-cutover baseline stored the speedup under rtf; compare it with decodeSpeedupX."""
    key = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    baseline = [_make_cell(key, rtf=2.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    current = [_make_cell(key, rtf=0.6, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    current[0]["decodeSpeedupX"] = 1.7
    regressions = sgt.compare_summaries(
        baseline, current, threshold=0.05, baseline_definition="legacy-speedup"
    )
    assert [r["metric"] for r in regressions] == ["rtf"]
    assert regressions[0]["current"] == 1.7
    current[0]["decodeSpeedupX"] = 2.05
    assert sgt.compare_summaries(
        baseline, current, threshold=0.05, baseline_definition="legacy-speedup"
    ) == []


def test_tokps_decrease_regression():
    key = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    baseline = [_make_cell(key, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    current = [_make_cell(key, rtf=1.0, tokps=900.0, ttfc=300.0, phys=4000.0, qc="pass")]
    regressions = sgt.compare_summaries(baseline, current, threshold=0.05)
    assert len(regressions) == 1
    assert regressions[0]["metric"] == "tokps"
    assert abs(regressions[0]["delta"] - (-0.1)) < 1e-9


def test_within_threshold_no_regression():
    key = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    baseline = [_make_cell(key, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    current = [_make_cell(key, rtf=1.02, tokps=990.0, ttfc=305.0, phys=4020.0, qc="pass")]
    regressions = sgt.compare_summaries(baseline, current, threshold=0.05)
    assert regressions == []


def test_qc_verdict_worsens():
    key = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    baseline = [_make_cell(key, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    current = [_make_cell(key, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="warn:clipping")]
    regressions = sgt.compare_summaries(baseline, current, threshold=0.05)
    assert len(regressions) == 1
    assert regressions[0]["metric"] == "qcVerdict"
    assert regressions[0]["baseline"] == "pass"
    assert regressions[0]["current"] == "warn:clipping"


def test_cell_missing_in_baseline():
    """A cell present only in current is an explicit coverage change."""
    key1 = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    key2 = ("custom", "Qwen3-TTS-12Hz-1.7B-8bit", "warm", "medium")
    baseline = [_make_cell(key1, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    current = [
        _make_cell(key1, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass"),
        _make_cell(key2, rtf=1.2, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass"),
    ]
    regressions = sgt.compare_summaries(baseline, current, threshold=0.05)
    assert [item["metric"] for item in regressions] == ["coverage.cell"]
    assert regressions[0]["baseline"] == "missing"


def test_cell_missing_in_current():
    """A cell present only in baseline fails closed."""
    key1 = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    key2 = ("custom", "Qwen3-TTS-12Hz-1.7B-8bit", "warm", "medium")
    baseline = [
        _make_cell(key1, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass"),
        _make_cell(key2, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass"),
    ]
    current = [_make_cell(key1, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    regressions = sgt.compare_summaries(baseline, current, threshold=0.05)
    assert [item["metric"] for item in regressions] == ["coverage.cell"]
    assert regressions[0]["current"] == "missing"


def test_missing_metric_none():
    """A required metric missing on either side fails closed."""
    key = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    baseline = [_make_cell(key, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    current = [_make_cell(key, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    baseline[0]["rtf"] = None
    regressions = sgt.compare_summaries(baseline, current, threshold=0.05)
    assert [item["metric"] for item in regressions] == ["coverage.rtf"]


def test_reviewed_cell_key_migration_preserves_comparison():
    old_key = ("custom", "legacy-model", "warm", "medium")
    new_key = ("custom", "current-model", "warm", "medium")
    baseline = [_make_cell(old_key, 1.0, 1000.0, 300.0, 4000.0, "pass")]
    current = [_make_cell(new_key, 1.0, 1000.0, 300.0, 4000.0, "pass")]
    migrations = [
        {
            "baselineCellKey": list(old_key),
            "currentCellKey": list(new_key),
            "reason": "reviewed model identity rename",
        }
    ]
    assert sgt.compare_summaries(baseline, current, migrations=migrations) == []


def test_migration_contract_rejects_unreviewed_or_ambiguous_rows():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "migrations.json")
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(
                {
                    "schemaVersion": 1,
                    "migrations": [
                        {
                            "baselineCellKey": ["custom", "old", "warm", "medium"],
                            "currentCellKey": ["custom", "new", "warm", "medium"],
                            "reason": "",
                        }
                    ],
                },
                stream,
            )
        try:
            sgt.load_baseline_migrations(path)
        except ValueError as error:
            assert "requires a reason" in str(error)
        else:
            raise AssertionError("unreviewed migration unexpectedly passed")


def test_exact_same_values_no_regression():
    """Zero delta never triggers a regression."""
    key = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    baseline = [_make_cell(key, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    current = [_make_cell(key, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    regressions = sgt.compare_summaries(baseline, current, threshold=0.05)
    assert regressions == []


def test_improvement_no_regression():
    """Improvements (RTF down, tokps up) are never flagged."""
    key = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    baseline = [_make_cell(key, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    current = [_make_cell(key, rtf=0.5, tokps=2000.0, ttfc=150.0, phys=2000.0, qc="pass")]
    regressions = sgt.compare_summaries(baseline, current, threshold=0.05)
    assert regressions == []


def test_save_and_compare_baseline_cli():
    """End-to-end: save a baseline, compare unchanged (exit 0), mutate baseline to force regression (exit 2)."""
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "telemetry_variants.jsonl")
    with tempfile.TemporaryDirectory() as tmp:
        engine_dir = os.path.join(tmp, "engine")
        os.makedirs(engine_dir)
        shutil.copy(fixture_path, os.path.join(engine_dir, "generations.jsonl"))
        baseline_path = os.path.join(tmp, "baseline.json")

        # Save baseline.
        with mock.patch.object(
            sys, "argv", ["summarize_generation_telemetry.py", tmp, "--save-baseline", baseline_path]
        ):
            assert sgt.main() == 0
        with open(baseline_path, "r", encoding="utf-8") as f:
            baseline = json.load(f)
        assert baseline["rtfDefinition"] == "wall/audio"
        assert all("cellKey" in cell for cell in baseline["cells"])

        # Compare unchanged baseline: no regression.
        with mock.patch.object(
            sys,
            "argv",
            ["summarize_generation_telemetry.py", tmp, "--compare-baseline", baseline_path],
        ):
            assert sgt.main() == 0

        # Mutate saved baseline so the current run appears regressed.
        for cell in baseline["cells"]:
            cell["rtf"] = 0.01  # baseline claims generation was far faster; current is worse
        with open(baseline_path, "w", encoding="utf-8") as f:
            json.dump(baseline, f, indent=2)

        with mock.patch.object(
            sys,
            "argv",
            ["summarize_generation_telemetry.py", tmp, "--compare-baseline", baseline_path],
        ):
            assert sgt.main() == 2


def _evidence(optimization="-O", device_class="floor_8gb_mac", forced=False):
    return {
        "historyRecord": {
            "run": {
                "kind": "engine-generation", "platform": "macos", "matrixScope": "focused",
                "runtimePolicy": {"deviceClass": device_class, "deviceClassForced": forced},
            },
            "hardware": {"profileID": "mac-mini-m2-8gb"},
            "toolchain": {"optimization": optimization},
            "inputs": {"matrixHash": "a" * 64, "corpusHash": "b" * 64},
            "models": [{
                "mode": "custom", "modelID": "fixture", "variant": "speed",
                "quantization": "4-bit", "revision": "c" * 40,
                "artifactVersion": "v1", "integrityDigest": "d" * 64,
                "runtimeProfileSignature": "fixture", "fixtureDigest": "not-applicable",
            }],
            "evidence": {"telemetrySchemaVersion": 8, "qcAlgorithmVersion": 6},
        }
    }


def test_governed_baseline_binds_optimization_and_topology():
    cells = [_make_cell(("custom", "fixture", "warm", "medium"), 1.0, 2.0, 3.0, 4.0, "pass")]
    document = sgt.baseline_document(cells, _evidence("-O"))
    assert document["schemaVersion"] == 2
    assert document["identity"]["optimization"] == "-O"
    assert sgt.baseline_cells(
        document,
        current_identity=sgt.baseline_identity_from_evidence(_evidence("-O")),
        require_identity=True,
    ) == cells
    try:
        sgt.baseline_cells(
            document,
            current_identity=sgt.baseline_identity_from_evidence(_evidence("-Onone")),
            require_identity=True,
        )
    except ValueError as error:
        assert "differs" in str(error)
    else:
        raise AssertionError("cross-optimization baseline unexpectedly passed")


def test_device_class_binds_the_governed_identity():
    cells = [_make_cell(("custom", "fixture", "warm", "medium"), 1.0, 2.0, 3.0, 4.0, "pass")]
    document = sgt.baseline_document(cells, _evidence())
    assert document["identity"]["deviceClass"] == "floor_8gb_mac"
    assert not sgt.baseline_lacks_device_class(document)
    other_tier = sgt.baseline_identity_from_evidence(_evidence(device_class="mid_16gb_mac"))
    try:
        sgt.baseline_cells(document, current_identity=other_tier, require_identity=True)
    except ValueError:
        pass
    else:
        raise AssertionError("a baseline from another memory tier unexpectedly compared")
    # A baseline saved before the device-class identity still compares, and the
    # caller notes it.
    legacy = {**document, "identity": dict(document["identity"])}
    legacy["identity"].pop("deviceClass")
    assert sgt.baseline_lacks_device_class(legacy)
    assert sgt.baseline_cells(legacy, current_identity=other_tier, require_identity=True) == cells


def test_governed_identity_refuses_forced_or_unstamped_evidence():
    unstamped = _evidence()
    unstamped["historyRecord"]["run"].pop("runtimePolicy")
    for evidence in (_evidence(forced=True), unstamped):
        try:
            sgt.baseline_identity_from_evidence(evidence)
        except ValueError:
            continue
        raise AssertionError("forced or unstamped evidence unexpectedly produced an identity")


def test_forced_memory_class_rows_are_never_saved_or_compared():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "telemetry_variants.jsonl")
    with open(fixture_path, "r", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    with tempfile.TemporaryDirectory() as tmp:
        engine_dir = os.path.join(tmp, "engine")
        os.makedirs(engine_dir)
        baseline_path = os.path.join(tmp, "baseline.json")
        shutil.copy(fixture_path, os.path.join(engine_dir, "generations.jsonl"))
        with mock.patch.object(
            sys, "argv", ["summarize_generation_telemetry.py", tmp, "--save-baseline", baseline_path]
        ):
            assert sgt.main() == 0
        # One forced row among the selection refuses both routes.
        rows[0]["notes"]["deviceClassForced"] = "true"
        with open(os.path.join(engine_dir, "generations.jsonl"), "w", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(row) + "\n" for row in rows))
        forced_baseline = os.path.join(tmp, "forced-baseline.json")
        with mock.patch.object(
            sys, "argv", ["summarize_generation_telemetry.py", tmp, "--save-baseline", forced_baseline]
        ):
            assert sgt.main() == 1
        assert not os.path.exists(forced_baseline)
        with mock.patch.object(
            sys, "argv", ["summarize_generation_telemetry.py", tmp, "--compare-baseline", baseline_path]
        ):
            assert sgt.main() == 1
        # The plain summary still reports forced rows.
        with mock.patch.object(sys, "argv", ["summarize_generation_telemetry.py", tmp]):
            assert sgt.main() == 0


def _unstamped_evidence():
    """Evidence from rows that predate the device-class stamp."""
    evidence = _evidence()
    evidence["historyRecord"]["run"].pop("runtimePolicy")
    return evidence


def _run_with_evidence(diag_dir, evidence, *arguments):
    """Run the CLI with `evidence` as the selected manifest and a fixed host."""
    argv = [
        "summarize_generation_telemetry.py", diag_dir, "--engine-only",
        "--evidence-manifest", "evidence.json", *arguments,
    ]
    with mock.patch.object(sys, "argv", argv), mock.patch.object(
        sgt, "load_evidence_selection", return_value=(evidence, "", None, None)
    ), mock.patch.object(
        sgt, "host_identity", return_value={"osVersion": "26.6", "xcodeVersion": "26.6"}
    ):
        return sgt.main()


def _telemetry_dir(tmp):
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "telemetry_variants.jsonl")
    engine_dir = os.path.join(tmp, "engine")
    os.makedirs(engine_dir)
    shutil.copy(fixture_path, os.path.join(engine_dir, "generations.jsonl"))
    return tmp


def test_a_refused_identity_leaves_the_existing_baseline_intact():
    with tempfile.TemporaryDirectory() as tmp:
        diag_dir = _telemetry_dir(tmp)
        baselines = os.path.join(tmp, "baselines")
        os.makedirs(baselines)
        baseline_path = os.path.join(baselines, "gate.json")
        original = b'{\n  "schemaVersion": 2,\n  "committed": true\n}\n'
        with open(baseline_path, "wb") as handle:
            handle.write(original)
        for evidence in (_unstamped_evidence(), _evidence(forced=True)):
            assert _run_with_evidence(diag_dir, evidence, "--save-baseline", baseline_path) == 1
            with open(baseline_path, "rb") as handle:
                assert handle.read() == original
            assert os.listdir(baselines) == ["gate.json"]
        # Stamped evidence saves, in the encoding the committed baseline uses.
        assert _run_with_evidence(diag_dir, _evidence(), "--save-baseline", baseline_path) == 0
        with open(baseline_path, "rb") as handle:
            saved = handle.read()
        document = json.loads(saved)
        assert document["identity"]["deviceClass"] == "floor_8gb_mac"
        assert saved == (json.dumps(document, indent=2) + "\n").encode("utf-8")
        assert list(document) == ["schemaVersion", "rtfDefinition", "identity", "cells"]
        assert os.listdir(baselines) == ["gate.json"]


def test_unstamped_evidence_compares_with_baselines_that_do_not_bind_the_tier():
    with tempfile.TemporaryDirectory() as tmp:
        diag_dir = _telemetry_dir(tmp)
        ad_hoc = os.path.join(tmp, "ad-hoc.json")
        with mock.patch.object(
            sys, "argv", ["summarize_generation_telemetry.py", diag_dir, "--save-baseline", ad_hoc]
        ):
            assert sgt.main() == 0
        # An ad-hoc baseline declares no identity, so the evidence needs none.
        assert _run_with_evidence(diag_dir, _unstamped_evidence(), "--compare-baseline", ad_hoc) == 0
        # ...unless the caller requires one.
        assert _run_with_evidence(
            diag_dir, _unstamped_evidence(), "--compare-baseline", ad_hoc, "--require-baseline-identity"
        ) == 1

        bound = os.path.join(tmp, "bound.json")
        assert _run_with_evidence(diag_dir, _evidence(), "--save-baseline", bound) == 0
        # A baseline that binds the tier refuses evidence that cannot prove it.
        assert _run_with_evidence(
            diag_dir, _unstamped_evidence(), "--compare-baseline", bound, "--require-baseline-identity"
        ) == 1
        # A baseline saved before the device-class identity compares without it,
        # as it did before the stamp existed; forced evidence is still refused.
        with open(bound, "r", encoding="utf-8") as handle:
            legacy = json.load(handle)
        legacy["identity"].pop("deviceClass")
        legacy_path = os.path.join(tmp, "legacy.json")
        with open(legacy_path, "w", encoding="utf-8") as handle:
            json.dump(legacy, handle, indent=2)
        for evidence in (_unstamped_evidence(), _evidence()):
            assert _run_with_evidence(
                diag_dir, evidence, "--compare-baseline", legacy_path, "--require-baseline-identity"
            ) == 0
        assert _run_with_evidence(
            diag_dir, _evidence(forced=True), "--compare-baseline", legacy_path, "--require-baseline-identity"
        ) == 1


def test_governed_baseline_rejects_legacy_unidentified_metrics():
    try:
        sgt.baseline_cells([], current_identity={}, require_identity=True)
    except ValueError as error:
        assert "legacy baseline" in str(error)
    else:
        raise AssertionError("legacy baseline unexpectedly passed governed comparison")


def load_tests(_loader, _tests, _pattern):
    """Expose function-style tests to the repository's unittest-only gate."""
    suite = unittest.TestSuite()
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(function):
            suite.addTest(unittest.FunctionTestCase(function, description=name))
    return suite


def test_threshold_widens_with_baseline_dispersion_and_n_is_required():
    key = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    baseline = [_make_cell(key, rtf=0.60, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    baseline[0].update({"n": 3, "rtfMAD": 0.03})  # 3 MAD / median = 15 %
    current = [_make_cell(key, rtf=0.68, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    assert sgt.compare_summaries(baseline, current, threshold=0.05) == []
    current = [_make_cell(key, rtf=0.70, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    assert [r["metric"] for r in sgt.compare_summaries(baseline, current, threshold=0.05)] == ["rtf"]
    # A one-take baseline keeps the flat threshold even with a recorded MAD.
    baseline[0].update({"n": 1})
    current = [_make_cell(key, rtf=0.64, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    assert [r["metric"] for r in sgt.compare_summaries(baseline, current, threshold=0.05)] == ["rtf"]
    # No sample count is a coverage failure, never a silent pass.
    baseline[0]["n"] = None
    assert [r["metric"] for r in sgt.compare_summaries(baseline, current, threshold=0.05)] == ["coverage.n"]


def test_host_load_makes_the_comparison_inconclusive():
    quiet = {"historyRecord": {"hardware": {"loadAverage1M": 2.1, "thermalState": "nominal"}}}
    assert sgt.host_load_verdict(quiet, cpu_count=8) == []
    busy = {"historyRecord": {"hardware": {"loadAverage1M": 17.0, "thermalState": "nominal"}}}
    assert any("load average" in reason for reason in sgt.host_load_verdict(busy, cpu_count=8))
    hot = {"historyRecord": {"hardware": {"loadAverage1M": 1.0, "thermalState": "serious"}}}
    assert any("thermal" in reason for reason in sgt.host_load_verdict(hot, cpu_count=8))
    assert sgt.host_load_verdict(None) == []


def test_legacy_baseline_identity_without_host_keys_still_compares():
    identity = {"kind": "engine-generation", "optimization": "-O"}
    payload = {"schemaVersion": 2, "identity": identity, "cells": [{"cellKey": ["a", "b", "c", "d"], "n": 1}]}
    current = {**identity, "osVersion": "26.6.2", "xcodeVersion": "26.6"}
    assert sgt.baseline_cells(payload, current_identity=current, require_identity=True) == payload["cells"]
    assert sgt.baseline_lacks_host_identity(payload)
    bound = {"schemaVersion": 2, "identity": current, "cells": payload["cells"]}
    assert not sgt.baseline_lacks_host_identity(bound)
    try:
        sgt.baseline_cells(bound, current_identity={**current, "xcodeVersion": "27.0"}, require_identity=True)
    except ValueError as error:
        assert "identity differs" in str(error)
    else:
        raise AssertionError("a different Xcode must not compare")


def test_states_restricts_the_verdict_to_the_named_warm_states():
    warm = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    cold = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "cold", "medium")
    baseline = [_make_cell(warm, 0.58, 23.6, 420.0, 2273.0, "pass"),
                _make_cell(cold, 1.57, 8.8, 6379.0, 2454.0, "pass")]
    # The single cold take regressed on footprint; the warm medians did not.
    current = [_make_cell(warm, 0.58, 23.6, 421.0, 2270.0, "pass"),
               _make_cell(cold, 0.75, 9.0, 1540.0, 2586.5, "pass")]
    assert [r["metric"] for r in sgt.compare_summaries(baseline, current)] == ["physFootMB"]
    assert sgt.compare_summaries(baseline, current, states=("warm",)) == []
    # A warm regression is still reported, and a cold cell missing from either
    # side is not a coverage failure when only warm cells carry the verdict.
    worse = [_make_cell(warm, 0.70, 23.6, 421.0, 2270.0, "pass")]
    reported = sgt.compare_summaries(baseline, worse, states=("warm",))
    assert [(r["metric"], tuple(r["cellKey"])) for r in reported] == [("rtf", warm)]


def test_footprint_threshold_widens_with_the_baseline_takes_dispersion():
    key = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    baseline = [_make_cell(key, 0.58, 23.6, 420.0, 2273.0, "pass")]
    current = [_make_cell(key, 0.58, 23.6, 420.0, 2511.3, "pass")]  # +10.5 %
    assert [r["metric"] for r in sgt.compare_summaries(baseline, current)] == ["physFootMB"]
    # Three warm takes whose sampled peaks were 2022, 2273 and 2640 MB: MAD 251 MB,
    # so the footprint threshold becomes 3 × 251 / 2273 = 33 %.
    baseline[0].update({"n": 3, "physFootMAD": 251.0})
    assert sgt.compare_summaries(baseline, current) == []
    far = [_make_cell(key, 0.58, 23.6, 420.0, 3100.0, "pass")]  # +36 %
    assert [r["metric"] for r in sgt.compare_summaries(baseline, far)] == ["physFootMB"]
    # The footprint dispersion never loosens the rtf verdict.
    slower = [_make_cell(key, 0.62, 23.6, 420.0, 2273.0, "pass")]  # +6.9 %
    assert [r["metric"] for r in sgt.compare_summaries(baseline, slower)] == ["rtf"]
