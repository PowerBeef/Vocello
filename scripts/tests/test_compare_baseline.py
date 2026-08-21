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


def test_rtf_decrease_regression():
    key = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    baseline = [_make_cell(key, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    current = [_make_cell(key, rtf=0.9, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    regressions = sgt.compare_summaries(baseline, current, threshold=0.05)
    assert len(regressions) == 1
    assert regressions[0]["metric"] == "rtf"
    assert abs(regressions[0]["delta"] - (-0.1)) < 1e-9


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
    """Improvements (RTF up, tokps up) are never flagged."""
    key = ("custom", "Qwen3-TTS-12Hz-1.7B-4bit", "warm", "medium")
    baseline = [_make_cell(key, rtf=1.0, tokps=1000.0, ttfc=300.0, phys=4000.0, qc="pass")]
    current = [_make_cell(key, rtf=2.0, tokps=2000.0, ttfc=150.0, phys=2000.0, qc="pass")]
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
        assert isinstance(baseline, list)
        assert all("cellKey" in cell for cell in baseline)

        # Compare unchanged baseline: no regression.
        with mock.patch.object(
            sys,
            "argv",
            ["summarize_generation_telemetry.py", tmp, "--compare-baseline", baseline_path],
        ):
            assert sgt.main() == 0

        # Mutate saved baseline so the current run appears regressed.
        for cell in baseline:
            cell["rtf"] = 10.0  # baseline claims RTF was much better; current is worse
        with open(baseline_path, "w", encoding="utf-8") as f:
            json.dump(baseline, f, indent=2)

        with mock.patch.object(
            sys,
            "argv",
            ["summarize_generation_telemetry.py", tmp, "--compare-baseline", baseline_path],
        ):
            assert sgt.main() == 2


def load_tests(_loader, _tests, _pattern):
    """Expose function-style tests to the repository's unittest-only gate."""
    suite = unittest.TestSuite()
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(function):
            suite.addTest(unittest.FunctionTestCase(function, description=name))
    return suite
