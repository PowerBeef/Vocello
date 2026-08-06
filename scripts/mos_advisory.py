#!/usr/bin/env python3
"""ADVISORY naturalness (MOS-proxy) column for generated takes.

Scores generated WAVs with a pinned UTMOSv2 checkpoint (VoiceMOS 2024
fusion model) and reports a predicted mean-opinion score per take, plus the
paired neutral-reference delta for delivery takes. This is a dev-lane
advisory metric in the same class as ``emotion_advisory.py``: it is not a
CI gate, not a packaging prerequisite, never a publication input, and never
publishes benchmark history (roadmap CM-6's unpark condition, verbatim).
The deterministic QC and delivery gates remain the promoted verdicts.

An absolute MOS from a synthetic-speech predictor is domain-shifted for
this engine's audio; treat the column as *relative* signal (take-vs-take,
instructed-vs-neutral, build-vs-build on fixed seeds), never as an absolute
quality claim.

Memory rule (Mac mini M2 8 GB dev floor): run strictly AFTER generation
completes — never while the engine is resident. Inference is CPU; the
report records the process peak RSS so the first run on any machine
documents its envelope.

Backend: torch + utmosv2, lazy-imported inside ``score_wavs`` so this
module's report logic imports and unit-tests without them. One-time setup
(weights auto-download from Hugging Face on first inference):

  .venv/bin/pip install \
      "utmosv2 @ git+https://github.com/sarulab-speech/UTMOSv2.git@cc2700db57bb83ee13dc31ebe1b868c254e15d09"

Usage:
  scripts/mos_advisory.py --sidecar <archive-run>/bench-prosody.json \
      --wav-dir <archive-run> [--out mos-advisory.json] [--json]
  scripts/mos_advisory.py clip.wav [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ADVISORY_SCHEMA_VERSION = 1
UTMOSV2_GIT_COMMIT = "cc2700db57bb83ee13dc31ebe1b868c254e15d09"
UTMOSV2_CONFIG = "fusion_stage3"
UTMOSV2_FOLD = 0
UTMOSV2_SEED = 42
# fold0_s42_best_model.pth from huggingface.co/sarulab-speech/UTMOSv2. The
# library's own downloader shells out to wget (absent on this machine); fetch
# with curl into ~/.cache/utmosv2/models/fusion_stage3/ instead — see the
# testing-runbook's ML-backed analyzers section. Scoring fails closed on drift.
UTMOSV2_WEIGHTS_SHA256 = "c8149d988e4bbf3f347e6966b5d769de347a5f8c59ffca1dc4bd4bf5b8585e57"


def build_report(rows, scores):
    """Pure report assembly from sidecar rows plus basename→MOS scores.

    Every row contributes an entry; a WAV the scorer could not produce a
    number for is recorded in ``missing`` rather than silently dropped.
    """
    takes, missing = [], []
    for row in rows:
        delivery_wav = os.path.basename(row.get("deliveryWav") or "")
        neutral_wav = os.path.basename(row.get("neutralWav") or "")
        mos = scores.get(delivery_wav)
        neutral_mos = scores.get(neutral_wav)
        entry = {
            "generationID": row.get("generationID"),
            "delivery": row.get("delivery"),
            "seed": row.get("seed"),
            "model": row.get("model"),
            "mos": round(mos, 3) if mos is not None else None,
            "neutralMOS": round(neutral_mos, 3) if neutral_mos is not None else None,
            "deltaMOS": round(mos - neutral_mos, 3)
            if mos is not None and neutral_mos is not None else None,
        }
        takes.append(entry)
        for name, value in (("deliveryWav", mos), ("neutralWav", neutral_mos)):
            wav = os.path.basename(row.get(name) or "")
            if wav and value is None and wav not in missing:
                missing.append(wav)
    cells = {}
    for entry in takes:
        if entry["mos"] is None:
            continue
        key = f"{entry['delivery']}|{entry['model']}"
        cells.setdefault(key, {"mos": [], "delta": []})
        cells[key]["mos"].append(entry["mos"])
        if entry["deltaMOS"] is not None:
            cells[key]["delta"].append(entry["deltaMOS"])
    aggregates = {
        key: {
            "n": len(values["mos"]),
            "medianMOS": round(statistics.median(values["mos"]), 3),
            "medianDeltaMOS": round(statistics.median(values["delta"]), 3)
            if values["delta"] else None,
        }
        for key, values in sorted(cells.items())
    }
    scored = [entry["mos"] for entry in takes if entry["mos"] is not None]
    return {
        "advisory": "mos-proxy",
        "schemaVersion": ADVISORY_SCHEMA_VERSION,
        "gate": False,
        "takes": takes,
        "aggregates": aggregates,
        "overallMedianMOS": round(statistics.median(scored), 3) if scored else None,
        "scoredCount": len(scored),
        "missing": sorted(missing),
    }


def score_wavs(wav_dir):
    """Score every .wav in a directory with the pinned UTMOSv2 model.

    Lazy heavy imports; CPU-only; returns (basename→mos, provenance).
    """
    import hashlib

    import utmosv2  # noqa: PLC0415 — heavy, optional dev dependency

    weights = os.path.expanduser(
        f"~/.cache/utmosv2/models/{UTMOSV2_CONFIG}/fold{UTMOSV2_FOLD}_s42_best_model.pth"
    )
    if os.path.exists(weights):
        digest = hashlib.sha256(open(weights, "rb").read()).hexdigest()
        if digest != UTMOSV2_WEIGHTS_SHA256:
            raise RuntimeError(
                f"UTMOSv2 weights drifted: {digest[:16]}… != pinned "
                f"{UTMOSV2_WEIGHTS_SHA256[:16]}…; re-fetch the pinned checkpoint"
            )
    model = utmosv2.create_model(
        pretrained=True, config=UTMOSV2_CONFIG, fold=UTMOSV2_FOLD,
        seed=UTMOSV2_SEED, device="cpu",
    )
    results = model.predict(
        input_dir=wav_dir, device="cpu", verbose=False,
    )
    scores = {}
    for item in results if isinstance(results, list) else []:
        path = item.get("file_path") or item.get("file") or ""
        mos = item.get("predicted_mos", item.get("mos"))
        if path and isinstance(mos, (int, float)):
            scores[os.path.basename(str(path))] = float(mos)
    provenance = {
        "model": "UTMOSv2",
        "gitCommit": UTMOSV2_GIT_COMMIT,
        "config": UTMOSV2_CONFIG,
        "fold": UTMOSV2_FOLD,
        "seed": UTMOSV2_SEED,
        "device": "cpu",
        "peakRSSMB": round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1
        ),
    }
    return scores, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("wav", nargs="?", help="single WAV to score")
    parser.add_argument("--sidecar", help="bench-prosody.json from a bench archive run")
    parser.add_argument("--wav-dir", help="directory holding the run's WAVs")
    parser.add_argument("--out", help="write the advisory report JSON here")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args()

    if args.wav:
        scores, provenance = score_wavs(os.path.dirname(os.path.abspath(args.wav)) or ".")
        mos = scores.get(os.path.basename(args.wav))
        report = {
            "advisory": "mos-proxy", "schemaVersion": ADVISORY_SCHEMA_VERSION,
            "gate": False, "wav": os.path.basename(args.wav),
            "mos": round(mos, 3) if mos is not None else None,
            "provenance": provenance,
        }
        if mos is None:
            print(f"error: scorer produced no MOS for {args.wav}", file=sys.stderr)
            return 1
    else:
        if not (args.sidecar and args.wav_dir):
            parser.error("--sidecar and --wav-dir are required without a single WAV")
        with open(args.sidecar, "r", encoding="utf-8") as f:
            rows = json.load(f)
        scores, provenance = score_wavs(args.wav_dir)
        report = build_report(rows, scores)
        report["provenance"] = provenance
        if report["scoredCount"] == 0:
            print("error: no takes could be scored", file=sys.stderr)
            return 1

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    if args.json or not args.out:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
