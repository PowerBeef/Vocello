#!/usr/bin/env python3
"""Score takes with the pinned NISQA clip-quality judge and the deterministic onset-cluster detector.

The same judge the delivery cascade runs (`--clip-quality-config`), applied to any set of WAVs
so a benchmark or reproduction can pass the machine gate without listening: every take gets its
five NISQA dimensions, the registry's calibrated warn floor, and QC v7's step-burst figures
(the densest 20 ms window of sample-to-sample steps above a quarter of full scale, and where it
starts). With `--onset-window-ms` the judge also scores only the first N ms of each take.

When the set contains both onset-cluster takes (step-burst count at or above
`--onset-cluster-min`) and clean takes (count at most `--clean-max`), the report carries the
separation statistics of every judge score against that split: the rank AUC (probability that
a cluster take scores below a clean one) and Spearman's correlation with the count. Those
numbers are the perceptual judgement of the cluster; the script never decides for the reader.

Evidence carries file names, digests and numbers only; never paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any
import wave

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from delivery_analysis_cache import DeliveryAnalysisCache, atomic_json  # noqa: E402
from delivery_compact_model_adapter import CompactAdapterError, run_compact_adapter  # noqa: E402
from lib import playback_capture as pc  # noqa: E402

REPO = SCRIPT_DIR.parent
DEFAULT_CACHE_ROOT = Path(os.environ.get("QVOICE_DELIVERY_ANALYSIS_CACHE", REPO / "build/cache/delivery-analysis"))
SCHEMA_VERSION = 1
DIMENSIONS = ("mos", "noisiness", "discontinuity", "coloration", "loudness")
DEFAULT_ONSET_CLUSTER_MIN = 8
DEFAULT_CLEAN_MAX = 2


class ScreenError(ValueError):
    """The screen could not judge a take."""


def _read_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScreenError(f"cannot read the judge configuration: {error}") from error
    if not isinstance(config, dict) or config.get("adapterID") != "nisqa-v2":
        raise ScreenError("the clip-quality screen requires a prepared nisqa-v2 adapter configuration")
    floor = config.get("warnFloor")
    if not isinstance(floor, dict) or isinstance(floor.get("mos"), bool) or not isinstance(floor.get("mos"), (int, float)):
        raise ScreenError("the judge configuration carries no calibrated warn floor")
    return config


def step_burst(path: Path) -> tuple[int, float | None]:
    rate, samples = pc.read_wav(path)
    return pc.step_burst_peak(samples, rate)


def _onset_window(path: Path, window_ms: int, destination: Path) -> None:
    with wave.open(str(path), "rb") as reader:
        params = reader.getparams()
        frames = reader.readframes(min(reader.getnframes(), int(reader.getframerate() * window_ms / 1000)))
    with wave.open(str(destination), "wb") as writer:
        writer.setparams(params)
        writer.writeframes(frames)


def _scores(report: dict[str, Any]) -> dict[str, float]:
    outputs = report.get("outputs") or {}
    scores = {}
    for name in DIMENSIONS:
        value = outputs.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(float(value)):
            raise ScreenError(f"the judge returned no finite {name}")
        scores[name] = round(float(value), 4)
    return scores


def rank_auc(cluster: list[float], clean: list[float]) -> float | None:
    """Probability that a cluster take scores below a clean take (ties count half)."""
    if not cluster or not clean:
        return None
    a = np.asarray(cluster, dtype=np.float64)[:, None]
    b = np.asarray(clean, dtype=np.float64)[None, :]
    return round(float((a < b).mean() + 0.5 * (a == b).mean()), 4)


def spearman(values: list[float], counts: list[int]) -> float | None:
    if len(values) < 3 or len(set(values)) < 2 or len(set(counts)) < 2:
        return None
    ranks_a = np.argsort(np.argsort(np.asarray(values, dtype=np.float64)))
    ranks_b = np.argsort(np.argsort(np.asarray(counts, dtype=np.float64)))
    return round(float(np.corrcoef(ranks_a, ranks_b)[0, 1]), 4)


def separation(rows: list[dict[str, Any]], key: str, *, cluster_min: int, clean_max: int) -> dict[str, Any]:
    scored = [row for row in rows if isinstance(row.get(key), (int, float))]
    cluster = [row[key] for row in scored if row["stepBurstPeakCount"] >= cluster_min]
    clean = [row[key] for row in scored if row["stepBurstPeakCount"] <= clean_max]
    return {
        "score": key,
        "clusterTakes": len(cluster),
        "cleanTakes": len(clean),
        "clusterMedian": None if not cluster else round(float(np.median(cluster)), 4),
        "cleanMedian": None if not clean else round(float(np.median(clean)), 4),
        "aucClusterScoresLower": rank_auc(cluster, clean),
        "spearmanWithStepBurstCount": spearman([row[key] for row in scored], [row["stepBurstPeakCount"] for row in scored]),
    }


def screen(
    *, wav_paths: list[Path], config: dict[str, Any], cache: DeliveryAnalysisCache, lock_root: Path,
    onset_window_ms: int | None = None, cluster_min: int = DEFAULT_ONSET_CLUSTER_MIN, clean_max: int = DEFAULT_CLEAN_MAX,
    adapter=run_compact_adapter,
) -> dict[str, Any]:
    floor = float(config["warnFloor"]["mos"])
    rows: list[dict[str, Any]] = []
    for path in wav_paths:
        if not path.is_file():
            raise ScreenError(f"{path.name}: missing")
        count, start = step_burst(path)
        try:
            report, hit = adapter(wav_path=path, config=config, cache=cache, lock_root=lock_root)
        except CompactAdapterError as error:
            raise ScreenError(f"{path.name}: {error}") from error
        scores = _scores(report)
        row: dict[str, Any] = {
            "take": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            **scores,
            "belowWarnFloor": scores["mos"] < floor,
            "cacheHit": bool(hit),
            "stepBurstPeakCount": int(count),
            "stepBurstPeakStartMS": None if start is None else round(float(start), 1),
            "onsetCluster": int(count) >= cluster_min,
        }
        if onset_window_ms:
            with tempfile.TemporaryDirectory(prefix="vocello-clip-quality-onset-") as temporary:
                window = Path(temporary) / path.name
                _onset_window(path, onset_window_ms, window)
                try:
                    onset_report, _ = adapter(wav_path=window, config=config, cache=cache, lock_root=lock_root)
                except CompactAdapterError as error:
                    raise ScreenError(f"{path.name}: onset window: {error}") from error
            row["onsetMOS"] = _scores(onset_report)["mos"]
            row["onsetDeltaMOS"] = round(row["mos"] - row["onsetMOS"], 4)
        rows.append(row)
    keys = ["mos"] + (["onsetMOS", "onsetDeltaMOS"] if onset_window_ms else [])
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "clip-quality-screen",
        "promotionAuthority": False,
        "judge": {
            "adapterID": config["adapterID"], "modelID": config.get("modelID"),
            "weightsSHA256": config.get("weightsSHA256"), "warnFloorMOS": floor,
            "onsetWindowMS": onset_window_ms,
        },
        "onsetClusterDetector": {
            "stepThreshold": pc.STEP_BURST_THRESHOLD, "windowMS": pc.STEP_BURST_WINDOW_MS,
            "clusterMinCount": cluster_min, "cleanMaxCount": clean_max,
        },
        "takes": len(rows),
        "belowWarnFloor": sum(row["belowWarnFloor"] for row in rows),
        "onsetClusterTakes": sum(row["onsetCluster"] for row in rows),
        "separation": [separation(rows, key, cluster_min=cluster_min, clean_max=clean_max) for key in keys],
        "rows": rows,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True, help="prepared nisqa-v2 adapter configuration")
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--lock-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--onset-window-ms", type=int, help="also judge only the first N ms of every take")
    parser.add_argument("--onset-cluster-min", type=int, default=DEFAULT_ONSET_CLUSTER_MIN)
    parser.add_argument("--clean-max", type=int, default=DEFAULT_CLEAN_MAX)
    parser.add_argument("--json", type=Path, help="write the report here (untracked evidence)")
    parser.add_argument("wav", type=Path, nargs="+")
    args = parser.parse_args()
    try:
        config = _read_config(args.config)
        report = screen(
            wav_paths=args.wav, config=config, cache=DeliveryAnalysisCache(args.cache_root), lock_root=args.lock_root,
            onset_window_ms=args.onset_window_ms, cluster_min=args.onset_cluster_min, clean_max=args.clean_max,
        )
    except (ScreenError, ValueError, OSError) as error:
        print(f"Clip-quality screen: FAIL\n{error}", file=sys.stderr)
        return 1
    if args.json:
        atomic_json(args.json, report)
    width = max(len(row["take"]) for row in report["rows"])
    print(f"{'take':>{width}} {'mos':>5} {'floor':>5} {'steps':>5} {'start':>7}" + ("  onsetMOS" if args.onset_window_ms else ""))
    for row in report["rows"]:
        flag = "warn" if row["belowWarnFloor"] else "ok"
        print(f"{row['take']:>{width}} {row['mos']:5.2f} {flag:>5} {row['stepBurstPeakCount']:5d} {str(row['stepBurstPeakStartMS']):>7}"
              + (f"  {row['onsetMOS']:8.2f}" if args.onset_window_ms else ""))
    for entry in report["separation"]:
        print(f"separation {entry['score']}: cluster n={entry['clusterTakes']} median {entry['clusterMedian']} | "
              f"clean n={entry['cleanTakes']} median {entry['cleanMedian']} | AUC(cluster lower) {entry['aucClusterScoresLower']} | "
              f"spearman(count) {entry['spearmanWithStepBurstCount']}")
    print(f"takes {report['takes']}; below warn floor {report['belowWarnFloor']}; onset-cluster takes {report['onsetClusterTakes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
