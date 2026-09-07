#!/usr/bin/env python3
"""Delivery-analysis v2 compatibility projection of the bounded v3 analyzer.

Retains legacy field names for delivery_adherence and longform_carryover_probe,
but explicitly versions histogram percentiles and the shared cadence definition.
Historical v1 reports stay historical: do not merge or recalibrate them as v2.
Acoustic proxies do not establish emotion, listener preference or promotion.
No clip-sized PCM or frame matrix is materialized by this adapter.
"""
import json
import sys
from analyze_prosody import analyze as analyze_bounded

DELIVERY_ANALYSIS_VERSION = 2


def analyze(path):
    source = analyze_bounded(str(path), delivery_projection=True)
    return project_report(source)


def project_report(source):
    """Reuse an already extracted summary; no PCM access or second analysis."""
    identity = {"clip": source["clip"], "durationSec": source["durationSec"],
                "deliveryAnalysisVersion": DELIVERY_ANALYSIS_VERSION,
                "analyzerAlgorithmVersion": source["analyzerAlgorithmVersion"]}
    if "error" in source:
        return {**identity, "error": source["error"]}
    if source["analyzerAlgorithmVersion"] != 3:
        raise ValueError("delivery v2 projection requires analyzer v3")
    mapping = {
        "f0_median_hz": "f0_median_hz", "f0_p10_hz": "f0_p10_hz",
        "f0_p90_hz": "f0_p90_hz", "f0_range_hz": "f0_range_hz",
        "voiced_frac": "f0_voiced_frac", "rms_mean_db": "energy_rms_mean_db",
        "rms_p90_db": "energy_rms_p90_db", "syllable_rate_hz": "rate_syllable_rate_hz",
    }
    return {**identity, **{key: source[value] for key, value in mapping.items()},
            **source["deliveryProjection"],
            "analysisWorkingSetDurationBounded": source["analysisWorkingSetDurationBounded"],
            "analysisEstimatedPeakWorkingSetBytes": source["analysisEstimatedPeakWorkingSetBytes"]}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = [analyze(p) for p in args]
    if "--json" in sys.argv[1:]:
        print(json.dumps(out, indent=2))
    elif not out:
        print("usage: analyze_delivery.py <wav> [...] [--json]")
    else:
        keys = ["clip", "durationSec", "f0_median_hz", "f0_range_hz", "voiced_frac",
                "rms_voiced_db", "rms_p90_db", "syllable_rate_hz"]
        widths = {k: max(len(k), max(len(str(r.get(k, ""))) for r in out)) for k in keys}
        print("  ".join(k.ljust(widths[k]) for k in keys))
        for row in out:
            print("  ".join(str(row.get(k, "")).ljust(widths[k]) for k in keys))


if __name__ == "__main__":
    main()
