import sys
import os
import contextlib
import io
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


def _evidence(optimization="-O"):
    return {
        "historyRecord": {
            "run": {"kind": "engine-generation", "platform": "macos", "matrixScope": "focused"},
            "hardware": {"profileID": "mac-mini-m2-8gb", "osVersion": "26.6.2", "osBuild": "25G83"},
            "toolchain": {
                "optimization": optimization, "xcodeVersion": "26.6", "xcodeBuild": "17F113",
                "swiftVersion": "Apple Swift version 6.3.3",
            },
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
    # The single cold take regressed on footprint (+35 %); the warm medians did not.
    current = [_make_cell(warm, 0.58, 23.6, 421.0, 2270.0, "pass"),
               _make_cell(cold, 0.75, 9.0, 1540.0, 3313.0, "pass")]
    assert [r["metric"] for r in sgt.compare_summaries(baseline, current)] == ["physFootMB"]
    assert sgt.compare_summaries(baseline, current, states=("warm",)) == []
    # A warm regression is still reported, and a cold cell missing from either
    # side is not a coverage failure when only warm cells carry the verdict.
    worse = [_make_cell(warm, 0.70, 23.6, 421.0, 2270.0, "pass")]
    reported = sgt.compare_summaries(baseline, worse, states=("warm",))
    assert [(r["metric"], tuple(r["cellKey"])) for r in reported] == [("rtf", warm)]


def test_footprint_threshold_has_a_floor_and_widens_with_the_baseline_takes_dispersion():
    key = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    # A baseline whose three takes agreed (MAD 0.05 MB, the committed M2 baseline)
    # no longer collapses to the flat 5 %: the +10.5 % identical-source drift that
    # failed a gate run (b88d6d03) stays under the footprint floor.
    baseline = [_make_cell(key, 0.58, 23.6, 420.0, 2273.0, "pass")]
    baseline[0].update({"n": 3, "physFootMAD": 0.047})
    current = [_make_cell(key, 0.58, 23.6, 420.0, 2511.3, "pass")]  # +10.5 %
    assert sgt.compare_summaries(baseline, current) == []
    gross = [_make_cell(key, 0.58, 23.6, 420.0, 3000.0, "pass")]  # +32 %
    assert [r["metric"] for r in sgt.compare_summaries(baseline, gross)] == ["physFootMB"]
    # Three warm takes whose sampled peaks were 2022, 2273 and 2640 MB: MAD 251 MB,
    # so the footprint threshold widens past the floor to 3 × 251 / 2273 = 33 %.
    baseline[0].update({"physFootMAD": 251.0})
    assert sgt.compare_summaries(baseline, gross) == []
    far = [_make_cell(key, 0.58, 23.6, 420.0, 3100.0, "pass")]  # +36 %
    assert [r["metric"] for r in sgt.compare_summaries(baseline, far)] == ["physFootMB"]
    # The footprint dispersion never loosens the rtf verdict.
    slower = [_make_cell(key, 0.62, 23.6, 420.0, 2273.0, "pass")]  # +6.9 %
    assert [r["metric"] for r in sgt.compare_summaries(baseline, slower)] == ["rtf"]


def _gate_cell(key, *, rtf=0.58, first_chunk=440.0, mlx=2324.7, phys=2600.0, n=3):
    cell = _make_cell(key, rtf, 23.6, None, phys, "pass")
    cell.update({
        "n": n, "rtfMAD": 0.0, "physFootMAD": 0.05,
        "engineFirstChunkMS": first_chunk, "engineFirstChunkMAD": 0.0,
        "mlxPeakMB": mlx, "mlxPeakMAD": 0.0,
    })
    return cell


def test_engine_first_chunk_and_mlx_peak_are_judged_against_their_floors():
    key = ("custom", "pro_custom_speed", "warm", "medium")
    baseline = [_gate_cell(key)]
    assert sgt.compare_summaries(baseline, [_gate_cell(key, first_chunk=440.0 * 1.14)]) == []
    later = sgt.compare_summaries(baseline, [_gate_cell(key, first_chunk=440.0 * 1.16)])
    assert [r["metric"] for r in later] == ["engineFirstChunkMS"]
    # The exact MLX peak is the tight memory signal: 1.5 % passes, 2.5 % regresses,
    # while the sampled footprint has to move by more than its 30 % floor.
    assert sgt.compare_summaries(baseline, [_gate_cell(key, mlx=2324.7 * 1.015)]) == []
    grown = sgt.compare_summaries(baseline, [_gate_cell(key, mlx=2324.7 * 1.025)])
    assert [r["metric"] for r in grown] == ["mlxPeakMB"]
    assert sgt.compare_summaries(baseline, [_gate_cell(key, phys=2600.0 * 1.25)]) == []


def test_a_baseline_saved_before_the_new_metrics_is_not_judged_on_them():
    """The committed M2 baseline has no engineFirstChunkMS or mlxPeakMB key."""
    key = ("custom", "pro_custom_speed", "warm", "medium")
    legacy = _make_cell(key, 0.5578, 23.6, None, 2614.3, "pass")
    legacy.update({"n": 3, "rtfMAD": 0.0096, "physFootMAD": 0.047})
    details = []
    assert sgt.compare_summaries([legacy], [_gate_cell(key, rtf=0.56, phys=2650.0)], details=details) == []
    skipped = {row["metric"] for row in details if not row["judged"]}
    assert skipped == {"engineFirstChunkMS", "mlxPeakMB"}
    # A key that is present but empty is still a coverage failure.
    empty = dict(legacy, mlxPeakMB=None)
    assert [r["metric"] for r in sgt.compare_summaries([empty], [_gate_cell(key, rtf=0.56)])] == [
        "coverage.mlxPeakMB"
    ]


def test_metric_threshold_names_the_basis_that_decided_it():
    cell = _gate_cell(("custom", "m", "warm", "medium"))
    assert sgt.metric_threshold(cell, "rtf", 0.05, "rtfMAD") == (0.05, "floor")
    assert sgt.metric_threshold(cell, "physFootMB", 0.05, "physFootMAD") == (0.30, "floor")
    cell["rtfMAD"] = 0.02  # 3 × 0.02 / 0.58 = 10.3 %
    limit, basis = sgt.metric_threshold(cell, "rtf", 0.05, "rtfMAD")
    assert abs(limit - 0.06 / 0.58) < 1e-12 and "MAD" in basis
    cell.update({"runCount": 3, "runSpread": {"rtf": 0.12}})
    limit, basis = sgt.metric_threshold(cell, "rtf", 0.05, "rtfMAD")
    assert limit == 0.12 and "3 seeded runs" in basis
    # Two pooled runs are not enough for a between-run threshold.
    cell["runCount"] = 2
    assert abs(sgt.metric_threshold(cell, "rtf", 0.05, "rtfMAD")[0] - 0.06 / 0.58) < 1e-12


def _run_cells(rtf, first_chunk, phys, mlx=2324.7, counts=(85, 85, 85)):
    key = ("custom", "pro_custom_speed", "warm", "medium")
    cell = _gate_cell(key, rtf=rtf, first_chunk=first_chunk, mlx=mlx, phys=phys)
    cell["generatedTokens"] = counts[1]
    cell["generatedTokenCounts"] = list(counts)
    return [cell]


def test_pooled_baseline_takes_medians_and_the_between_run_range():
    runs = [
        {"runID": "a", "sourceCommit": "c" * 40, "cells": _run_cells(0.578, 440.0, 2273.0)},
        {"runID": "b", "sourceCommit": "c" * 40, "cells": _run_cells(0.594, 470.0, 2511.0)},
        {"runID": "c", "sourceCommit": "c" * 40, "cells": _run_cells(0.585, 452.0, 2315.0)},
    ]
    [pooled] = sgt.pooled_cells(runs)
    assert pooled["runCount"] == 3 and pooled["n"] == 3
    assert pooled["rtf"] == 0.585 and pooled["physFootMB"] == 2315.0
    assert abs(pooled["runSpread"]["rtf"] - (0.594 - 0.578) / 0.585) < 1e-12
    assert pooled["generatedTokenCounts"] == [85] * 9
    # No seed run regresses against the baseline it helped build ...
    for run in runs:
        assert sgt.compare_summaries([pooled], run["cells"]) == []
    # ... and a synthetic +6 % RTF on the pooled median is still flagged.
    slower = _run_cells(0.585 * 1.06, 452.0, 2315.0)
    assert [r["metric"] for r in sgt.compare_summaries([pooled], slower)] == ["rtf"]


def test_host_load_is_judged_on_the_busiest_judged_take_and_low_power():
    def evidence(loads, *, low_power=False, first_sample=2.0):
        takes = [
            {"warmState": state, "metrics": {"loadAverage1M": load, "lowPowerMode": 0.0}}
            for state, load in loads
        ]
        return {"historyRecord": {
            "hardware": {"loadAverage1M": first_sample, "thermalState": "nominal", "lowPowerMode": low_power},
            "takes": takes,
        }}

    quiet_start_busy_warm = evidence([("cold", 2.0), ("warm", 3.0), ("warm", 17.5), ("warm", 4.0)])
    assert sgt.host_load_verdict(quiet_start_busy_warm, cpu_count=8, states=("warm",))
    # The cold take is informational: its load alone never decides the warm verdict.
    busy_cold_only = evidence([("cold", 30.0), ("warm", 3.0), ("warm", 3.0), ("warm", 3.0)])
    assert sgt.host_load_verdict(busy_cold_only, cpu_count=8, states=("warm",)) == []
    assert sgt.host_load_verdict(busy_cold_only, cpu_count=8)
    # Evidence without per-take load falls back to the run's first sample.
    legacy = {"historyRecord": {"hardware": {"loadAverage1M": 17.0}, "takes": [{"warmState": "warm"}]}}
    assert sgt.host_load_verdict(legacy, cpu_count=8, states=("warm",))
    assert sgt.host_load_verdict(evidence([("warm", 1.0)], low_power=True), cpu_count=8)
    per_take_low_power = evidence([("warm", 1.0)])
    per_take_low_power["historyRecord"]["takes"][0]["metrics"]["lowPowerMode"] = 1.0
    assert sgt.host_load_verdict(per_take_low_power, cpu_count=8, states=("warm",))


def test_identity_differences_name_every_mismatched_or_one_sided_key():
    baseline = {"a": 1, "b": 2, "c": 3}
    current = {"a": 1, "b": 5, "d": 4}
    assert sgt.identity_differences(baseline, current) == ["b", "c", "d"]
    assert sgt.identity_differences(baseline, current, keys=("a", "b")) == ["b"]


def test_identity_comes_from_the_evidence_not_the_comparing_host():
    identity = sgt.baseline_identity_from_evidence(_evidence())
    assert (identity["osBuild"], identity["xcodeBuild"]) == ("25G83", "17F113")
    newer = _evidence()
    newer["historyRecord"]["toolchain"]["xcodeBuild"] = "17F200"
    assert sgt.identity_differences(identity, sgt.baseline_identity_from_evidence(newer)) == ["xcodeBuild"]
    older = _evidence()
    del older["historyRecord"]["hardware"]["osBuild"]
    try:
        sgt.baseline_identity_from_evidence(older)
    except ValueError:
        pass
    else:
        raise AssertionError("evidence without the run-time host identity must not seed or compare")


def test_determinism_report_flags_disagreeing_seeded_takes_and_changed_output():
    evidence = {"historyRecord": {"takes": [{"seed": 19790615}, {"seed": 19790615}]}}
    current = _run_cells(0.58, 440.0, 2600.0, counts=(85, 83, 85))
    baseline = _run_cells(0.58, 440.0, 2600.0, counts=(87, 87, 87))
    report = sgt.determinism_report(evidence, current, baseline)
    assert report["seed"] == 19790615
    [entry] = report["cells"]
    assert entry["consistent"] is False and entry["engineOutputChanged"] is True
    unseeded = sgt.determinism_report({"historyRecord": {"takes": [{}, {}]}}, current)
    assert unseeded["seed"] is None


# --- Offline replay of committed M2 gate evidence ------------------------------
#
# Values copied from committed evidence so pruning a record cannot break the test:
# - D: the warm takes of mac-gate-bench-20260912-234613-c8f8a8c6 (commit b88d6d03).
# - A, B, C: the three identical-source gate runs the b88d6d03 commit message
#   records (warm phys_footprint peaks per take; C failed the old flat 5 %
#   footprint threshold at +10.5 %), and A's warm RTF median and MAD as the
#   baseline file saved at b88d6d03 recorded them. B's and C's per-take RTFs
#   were not recorded, so their footprint cells are replayed alone.
_GATE_CELL = ("custom", "pro_custom_speed", "warm", "medium")
_REPLAY_D = [
    {"rtf": 0.601006, "tokps": 23.0456, "physFootMB": 2668.94, "mlxPeakMB": 2324.687,
     "firstChunkArrivalMS": 501.4, "generatedTokens": 87},
    {"rtf": 0.593373, "tokps": 23.5152, "physFootMB": 2643.17, "mlxPeakMB": 2324.687,
     "firstChunkArrivalMS": 438.0, "generatedTokens": 83},
    {"rtf": 0.591324, "tokps": 23.2711, "physFootMB": 2648.72, "mlxPeakMB": 2324.687,
     "firstChunkArrivalMS": 425.7, "generatedTokens": 85},
]
_REPLAY_FOOTPRINTS = {
    "A": (2022.0, 2273.0, 2640.0), "B": (2278.0, 2676.0, 2315.0), "C": (2471.0, 2511.0, 2645.0),
    "D": tuple(take["physFootMB"] for take in _REPLAY_D),
}


def _replay_cells(runs):
    """Cells of one run through the summarizer's own aggregation."""
    accumulator = sgt.CellAccumulator(key=_GATE_CELL)
    for run in runs:
        accumulator.add_run({**run, "qcVerdict": "pass"})
    cells = sgt.build_summary({_GATE_CELL: accumulator.finalize()})
    cells[0]["n"] = len(runs)  # a footprint-only replay carries no RTF to count takes by
    return cells


def test_offline_replay_of_committed_gate_runs_has_no_false_regression():
    footprint = {
        name: _replay_cells([{"physFootMB": value} for value in values])
        for name, values in _REPLAY_FOOTPRINTS.items()
    }
    # Every ordered pair of the four engine-identical runs: the footprint moved
    # up to +16.5 % (A 2273 -> D 2649 MB), under its 30 % floor.
    for base in footprint.values():
        for current in footprint.values():
            assert sgt.compare_summaries(base, current, states=("warm",)) == []
    # Run A with the collapsed dispersion of the committed baseline (MAD 0.047 MB)
    # instead of its own 251 MB: the flat 5 % used to fail C (+10.5 %) and D (+16.5 %).
    collapsed = [dict(footprint["A"][0], physFootMAD=0.047)]
    for name in ("B", "C", "D"):
        assert sgt.compare_summaries(collapsed, footprint[name], states=("warm",)) == []

    record = _replay_cells(_REPLAY_D)
    baseline_a = _replay_cells([{"rtf": 0.5769}, {"rtf": 0.5782}, {"rtf": 0.5795}])
    assert abs(baseline_a[0]["rtfMAD"] - 0.0013) < 1e-9
    rtf_only = [{"rtf": take["rtf"]} for take in _REPLAY_D]
    assert sgt.compare_summaries(baseline_a, _replay_cells(rtf_only), states=("warm",)) == []  # +2.6 %
    assert sgt.compare_summaries(_replay_cells(rtf_only), baseline_a, states=("warm",)) == []
    # The complete record against itself, every metric judged.
    details = []
    assert sgt.compare_summaries(record, record, states=("warm",), details=details) == []
    assert {row["metric"] for row in details if row["judged"]} == {
        "rtf", "engineFirstChunkMS", "physFootMB", "mlxPeakMB", "tokps",
    }


def test_offline_replay_still_flags_a_synthetic_six_percent_rtf_rise():
    record = _replay_cells(_REPLAY_D)
    slower = _replay_cells([dict(take, rtf=take["rtf"] * 1.06) for take in _REPLAY_D])
    assert [r["metric"] for r in sgt.compare_summaries(record, slower, states=("warm",))] == ["rtf"]
    baseline_a = _replay_cells([{"rtf": 0.5769}, {"rtf": 0.5782}, {"rtf": 0.5795}])
    slower_a = _replay_cells([{"rtf": value * 1.06} for value in (0.5769, 0.5782, 0.5795)])
    assert [r["metric"] for r in sgt.compare_summaries(baseline_a, slower_a, states=("warm",))] == ["rtf"]


# --- End-to-end: the gate's summarizer invocations over a synthetic run -------

_WARM_CELL = ["custom", "pro_custom_speed", "warm", "medium"]


def _write_gate_run(root, run_id, *, rtfs=(0.60, 0.58, 0.59), loads=(2.0, 2.0, 2.0),
                    dirty=False, commit="c" * 40, xcode_build="17F113", seed=19790615):
    """A diagnostics directory and evidence manifest shaped like one gate bench run."""
    diag = os.path.join(root, run_id, "diagnostics")
    os.makedirs(os.path.join(diag, "engine"))
    takes, rows = [], []
    plan = [("cold", 0.70, 2.0)] + [("warm", rtf, load) for rtf, load in zip(rtfs, loads)]
    for index, (state, rtf, load) in enumerate(plan, start=1):
        generation_id = f"{run_id}-{index}"
        cell = f"custom/speed/medium/{state}#{0 if state == 'cold' else index - 2}"
        rows.append({
            "generationID": generation_id, "mode": "custom", "modelID": "pro_custom_speed",
            "warmState": state, "finishReason": "eos",
            "notes": {"benchRunID": run_id, "promptChars": 100},
            "derivedMetrics": {
                "realTimeFactor": rtf, "audioSecondsPerWallSecond": 1.7, "tokensPerSecond": 23.5,
                "audioSeconds": 6.8, "generatedTokenCount": 85,
            },
            "summary": {"physFootprintPeakMB": 2600.0 + index},
            "memoryMetrics": {"mlxCumulativePeakMB": 2324.7},
            "chunkTimeline": [{"arrivalMS": 440.0 + index}],
            "audioQC": {"verdict": "pass"},
        })
        takes.append({
            "takeIndex": index, "generationID": generation_id, "cell": cell,
            "status": "passed", "finishReason": "completed", "warmState": state,
            "output": {"readableWAV": True, "atomicPublish": True},
            "audioQC": {"verdict": "pass"}, "layerCompleteness": "complete", "layers": ["engine"],
            "seed": seed, "metrics": {"loadAverage1M": load, "lowPowerMode": 0.0},
        })
    with open(os.path.join(diag, "engine", "generations.jsonl"), "w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    evidence = _evidence()
    history = evidence["historyRecord"]
    history["toolchain"]["xcodeBuild"] = xcode_build
    history.update({
        "schemaVersion": 2,
        "run": {**history["run"], "id": run_id, "status": "passed"},
        "source": {"commit": commit, "dirty": dirty},
        "takes": takes,
    })
    evidence.update({
        "schemaVersion": 2, "benchmarkKind": "engine-generation", "platform": "macos",
        "runID": run_id, "status": "passed",
        "expectedTakeCount": len(takes), "actualTakeCount": len(takes),
    })
    manifest = os.path.join(root, run_id, "benchmark-evidence.json")
    with open(manifest, "w", encoding="utf-8") as stream:
        json.dump(evidence, stream)
    return diag, manifest


def _summarize(*arguments):
    """Run the summarizer's main quietly; return (exit code, printed text)."""
    output = io.StringIO()
    with mock.patch.object(sys, "argv", ["summarize_generation_telemetry.py", *arguments]):
        with contextlib.redirect_stdout(output):
            status = sgt.main()
    return status, output.getvalue()


def _gate_args(diag, manifest, run_id):
    return [diag, "--run-id", run_id, "--evidence-manifest", manifest, "--engine-only",
            "--compare-states", "warm"]


def test_governed_seed_round_trips_pools_and_still_flags_a_six_percent_rtf_rise():
    with tempfile.TemporaryDirectory() as tmp:
        staged = os.path.join(tmp, "staged", "mac-gate-bench.json")
        verdict_path = os.path.join(tmp, "verdict.json")
        first = _write_gate_run(tmp, "run-1", rtfs=(0.600, 0.580, 0.590))
        # The printed repair command seeds from the run's own evidence, and the
        # seeded baseline compares that same evidence with exit 0.
        assert _summarize(*_gate_args(*first, "run-1"), "--seed-baseline", staged)[0] == 0
        status, _text = _summarize(
            *_gate_args(*first, "run-1"), "--compare-baseline", staged,
            "--require-baseline-identity", "--verdict-json", verdict_path,
        )
        assert status == 0
        with open(verdict_path, encoding="utf-8") as stream:
            verdict = json.load(stream)
        assert verdict["verdict"] == "pass" and len(verdict["baseline"]["sha256"]) == 64
        judged = {row["metric"]: row for row in verdict["comparisons"] if row["judged"]}
        assert judged["physFootMB"]["threshold"] == 0.30 and judged["mlxPeakMB"]["threshold"] == 0.02
        # Three takes spread 0.580-0.600: 3 MAD / median (5.1 %) beats the 5 % floor.
        assert judged["rtf"]["threshold"] > 0.05 and "MAD" in judged["rtf"]["basis"]
        assert set(judged) == {"rtf", "engineFirstChunkMS", "physFootMB", "mlxPeakMB", "tokps"}

        for index, rtfs in ((2, (0.594, 0.586, 0.590)), (3, (0.578, 0.582, 0.580))):
            run = _write_gate_run(tmp, f"run-{index}", rtfs=rtfs)
            assert _summarize(*_gate_args(*run, f"run-{index}"), "--seed-baseline", staged)[0] == 0
        # Seeding the same run twice changes nothing.
        assert _summarize(*_gate_args(*first, "run-1"), "--seed-baseline", staged)[0] == 0
        with open(staged, encoding="utf-8") as stream:
            document = json.load(stream)
        assert [run["runID"] for run in document["seededRuns"]] == ["run-1", "run-2", "run-3"]
        [warm] = [cell for cell in document["cells"] if cell["cellKey"] == _WARM_CELL]
        assert warm["runCount"] == 3 and warm["rtf"] == 0.59

        repeat = _write_gate_run(tmp, "run-4", rtfs=(0.593, 0.588, 0.591))
        assert _summarize(*_gate_args(*repeat, "run-4"), "--compare-baseline", staged,
                          "--require-baseline-identity")[0] == 0
        slower = _write_gate_run(tmp, "run-5", rtfs=(0.6254, 0.6254, 0.6254))  # +6 %
        assert _summarize(*_gate_args(*slower, "run-5"), "--compare-baseline", staged,
                          "--require-baseline-identity")[0] == 2

        # A run from another commit starts a new staged baseline instead of pooling.
        moved = _write_gate_run(tmp, "run-6", commit="d" * 40)
        assert _summarize(*_gate_args(*moved, "run-6"), "--seed-baseline", staged)[0] == 0
        with open(staged, encoding="utf-8") as stream:
            assert [run["runID"] for run in json.load(stream)["seededRuns"]] == ["run-6"]


def test_governed_seed_refuses_a_loaded_host_a_dirty_tree_and_short_cells():
    with tempfile.TemporaryDirectory() as tmp:
        staged = os.path.join(tmp, "mac-gate-bench.json")
        loaded = _write_gate_run(tmp, "loaded", loads=(2.0, 1000.0, 2.0))
        assert _summarize(*_gate_args(*loaded, "loaded"), "--seed-baseline", staged)[0] == 3
        dirty = _write_gate_run(tmp, "dirty", dirty=True)
        assert _summarize(*_gate_args(*dirty, "dirty"), "--seed-baseline", staged)[0] == 1
        clean = _write_gate_run(tmp, "clean")
        assert _summarize(*_gate_args(*clean, "clean"), "--seed-baseline", staged,
                          "--seed-minimum-takes", "5")[0] == 1
        assert not os.path.exists(staged)


def test_a_loaded_run_is_inconclusive_before_the_baseline_identity_is_judged():
    with tempfile.TemporaryDirectory() as tmp:
        staged = os.path.join(tmp, "mac-gate-bench.json")
        seed = _write_gate_run(tmp, "seed")
        assert _summarize(*_gate_args(*seed, "seed"), "--seed-baseline", staged)[0] == 0
        # A newer Xcode build is another identity: BASELINE INVALID on a quiet host ...
        newer = _write_gate_run(tmp, "newer", xcode_build="17F200")
        assert _summarize(*_gate_args(*newer, "newer"), "--compare-baseline", staged,
                          "--require-baseline-identity")[0] == 1
        # ... but INCONCLUSIVE when the host was also loaded (audit V-7).
        busy = _write_gate_run(tmp, "busy", xcode_build="17F200", loads=(1000.0, 2.0, 2.0))
        assert _summarize(*_gate_args(*busy, "busy"), "--compare-baseline", staged,
                          "--require-baseline-identity")[0] == 3


def _expected_identity(tmp, *, matrix_hash="a" * 64, dirty=False, commit="c" * 40):
    history = _evidence()["historyRecord"]
    history["inputs"] = {"matrixHash": matrix_hash}
    history["source"] = {"commit": commit, "dirty": dirty}
    for key in ("evidence", "models"):
        history.pop(key)
    path = os.path.join(tmp, f"expected-{matrix_hash[:4]}-{dirty}.json")
    with open(path, "w", encoding="utf-8") as stream:
        json.dump({"schemaVersion": 1, "historyRecord": history}, stream)
    return path


def test_preflight_predicts_whether_the_gate_can_compare_or_seed():
    with tempfile.TemporaryDirectory() as tmp:
        committed = os.path.join(tmp, "mac-gate-bench.json")
        staged = os.path.join(tmp, "staged.json")
        expected = _expected_identity(tmp)
        # No committed baseline: the bench runs without a comparison.
        assert _summarize("--preflight-baseline", committed, "--expected-identity", expected)[0] == 0
        with open(committed, "w", encoding="utf-8") as stream:
            json.dump(sgt.baseline_document(_run_cells(0.58, 440.0, 2600.0), _evidence()), stream)
        assert _summarize("--preflight-baseline", committed, "--expected-identity", expected)[0] == 0
        # A seeded gate changes the matrix hash: predicted BASELINE INVALID within seconds.
        reseeded = _expected_identity(tmp, matrix_hash="e" * 64)
        status, text = _summarize("--preflight-baseline", committed, "--expected-identity", reseeded)
        assert status == 1 and "matrixHash" in text
        # A baseline bound only to the OS and Xcode marketing versions (the committed
        # M2 file) lacks the build numbers the identity now requires.
        with open(committed, encoding="utf-8") as stream:
            partial = json.load(stream)
        for key in ("osBuild", "xcodeBuild", "swiftVersion"):
            del partial["identity"][key]
        with open(committed, "w", encoding="utf-8") as stream:
            json.dump(partial, stream)
        assert _summarize("--preflight-baseline", committed, "--expected-identity", expected)[0] == 1
        # Seeding needs a clean commit; otherwise it may start or join a staged baseline.
        dirty = _expected_identity(tmp, dirty=True)
        assert _summarize("--preflight-baseline", staged, "--expected-identity", dirty, "--seeding")[0] == 1
        assert _summarize("--preflight-baseline", staged, "--expected-identity", expected, "--seeding")[0] == 0


def _drop_host_identity(manifest):
    """Evidence captured before the run-time host identity was recorded."""
    with open(manifest, encoding="utf-8") as stream:
        evidence = json.load(stream)
    history = evidence["historyRecord"]
    for key in ("osVersion", "osBuild"):
        history["hardware"].pop(key)
    for key in ("xcodeVersion", "xcodeBuild", "swiftVersion"):
        history["toolchain"].pop(key)
    with open(manifest, "w", encoding="utf-8") as stream:
        json.dump(evidence, stream)


def test_evidence_without_host_identity_still_compares_with_a_baseline_that_has_none():
    """The identity is derived only when the baseline has one to compare."""
    with tempfile.TemporaryDirectory() as tmp:
        diag, manifest = _write_gate_run(tmp, "old")
        _drop_host_identity(manifest)
        arguments = _gate_args(diag, manifest, "old")
        # An ad-hoc baseline saved without evidence carries no identity.
        adhoc = os.path.join(tmp, "adhoc.json")
        assert _summarize(diag, "--run-id", "old", "--engine-only", "--save-baseline", adhoc)[0] == 0
        with open(adhoc, encoding="utf-8") as stream:
            assert "identity" not in json.load(stream)
        assert _summarize(*arguments, "--compare-baseline", adhoc)[0] == 0
        # A legacy cell array has no identity either.
        legacy = os.path.join(tmp, "legacy.json")
        with open(adhoc, encoding="utf-8") as stream:
            cells = json.load(stream)["cells"]
        with open(legacy, "w", encoding="utf-8") as stream:
            json.dump(cells, stream)
        assert _summarize(*arguments, "--compare-baseline", legacy)[0] == 0
        # A baseline saved before host identity existed compares on the rest.
        pre_host = os.path.join(tmp, "pre-host.json")
        identity = sgt.baseline_identity_from_evidence(_evidence())
        for key in sgt.HOST_IDENTITY_KEYS:
            identity.pop(key)
        with open(pre_host, "w", encoding="utf-8") as stream:
            json.dump({"schemaVersion": 2, "rtfDefinition": "wall/audio", "identity": identity,
                       "cells": cells}, stream)
        assert _summarize(*arguments, "--compare-baseline", pre_host, "--require-baseline-identity")[0] == 0
        # A governed baseline bound to a host identity cannot compare that evidence ...
        governed = os.path.join(tmp, "governed.json")
        with open(governed, "w", encoding="utf-8") as stream:
            json.dump(sgt.baseline_document(cells, _evidence()), stream)
        status, text = _summarize(*arguments, "--compare-baseline", governed)
        assert status == 1 and "osBuild" in text
        # ... and --require-baseline-identity still rejects a baseline without one.
        assert _summarize(*arguments, "--compare-baseline", adhoc, "--require-baseline-identity")[0] == 1
