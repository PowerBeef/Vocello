#!/usr/bin/env python3
"""Replay audio-QC evidence and screen failing bounds, under the threshold authority.

Two Fast-QC measures carry no failing bound: the QC v8 speaking rate
(`secondsPerTextUnit`, warn-only `speaking_rate_slow`, audit #10) and the QC v9
clustered click events per second (observational, audit #85; the per-sample
click fraction stays the bound). The maintainer delegated the open decisions to
the audit's recommendations on 2026-09-25, and both recommendations route any
failing bound through the threshold-change authority in
`docs/reference/audio-qc-engineering.md`: an untouched confirmation cohort and
independent reference evidence are required, and automatic metrics may screen
candidates only, never qualify a change. This tool is that screen. It replays
what exists, reproduces the current bands, reports each candidate's effect on a
calibration split and on the untouched split, and states which requirement is
missing. It never edits a threshold and never reports a bound as qualified: a
qualified change is a reviewed Swift edit with its evidence.

Commands:
  speaking-rate  replay the committed benchmark records (read-only): each take's
                 duration per letter or digit of its benchmark text, mapped by
                 cell exactly as the QC v8 seeding was.
  clicks         replay the committed records' clamped samples per second, and
                 optionally WAV files (such as the retained codec A/B takes)
                 through a mirror of the Swift clustered click counter.

Swift owns the thresholds; this tool reads them from the Swift source so the
replay can never drift from the bands it screens against.
"""

from __future__ import annotations

import argparse
from array import array
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys
from typing import Any, Iterable
import wave

REPO = Path(__file__).resolve().parents[1]
RECORDS = REPO / "benchmarks" / "runs"
ADAPTER_SOURCE = REPO / "Sources" / "QwenVoiceCore" / "GenerationOutputAdapter.swift"
BENCH_MATRIX_SOURCE = REPO / "Sources" / "QwenVoiceCore" / "BenchMatrixSpec.swift"
UI_CORPUS_SOURCE = REPO / "Tests" / "UIAutomationSupport" / "VocelloUIAutomationSupport.swift"
LANGUAGE_MATRIX = REPO / "config" / "language-bench-matrix.json"
LANGUAGE_CORPUS = REPO / "config" / "language-bench-corpus.json"

REPORT_SCHEMA = 1
# The QC v8 bands were seeded from every take committed before this instant
# (commit bec8c418); records finished later are the untouched split.
SPEAKING_RATE_SEEDING_CUT = "2026-09-25T08:35:53Z"
# The record kinds whose takes speak a benchmark text.
GENERATION_KINDS = frozenset({
    "engine-generation", "ui-generation", "memory-qualification", "language", "instrument-profile",
})
# Screening multiples of each class's warn band.
SPEAKING_RATE_CANDIDATE_FACTORS = (1.25, 1.5, 2.0)
# Audio QC runs at the engine's fixed 24 kHz output rate.
ENGINE_SAMPLE_RATE = 24_000
# Clustered-click mirror of `PCM16StreamLimiter` (QC v9): the slew clamp, the
# event gap, the envelope smoothing and the low-energy level.
SLEW_CLAMP = 0.42
CLICK_EVENT_GAP_SAMPLES = 240
CLICK_ENVELOPE_COEFFICIENT = 1.0 / 240.0
LOW_ENERGY_CLICK_ENVELOPE = 0.02
# A published sample moved by the clamp differs from its predecessor by the
# clamp up to PCM16 rounding.
PCM16_CLAMP_TOLERANCE = 2.0 / 32767.0
CLICK_CANDIDATES_PER_SECOND = (0.5, 1.0, 2.0, 5.0)
# The calibration floors the audio-QC calibration guidance sets per class.
MINIMUM_CONFIRMATION_PER_CLASS = 60


class BoundsError(RuntimeError):
    """The evidence or a source the replay reads is unusable."""


# --------------------------------------------------------------------------- #
# Swift sources (thresholds and benchmark texts)
# --------------------------------------------------------------------------- #

def speaking_rate_bands(source: str) -> dict[str, dict[str, float]]:
    """The warn band and minimum judged units per script class, from Swift."""
    bands: dict[str, float] = {}
    for classes, value in re.findall(r"case (\.[a-z]+(?:, \.[a-z]+)*): return ([0-9.]+)", source):
        for name in re.findall(r"\.([a-z]+)", classes):
            bands[name] = float(value)
    minimum = re.search(r"scriptClass == \.alphabetic \? (\d+) : (\d+)", source)
    required = {"alphabetic", "chinese", "japanese", "korean"}
    if minimum is None or not required <= set(bands):
        raise BoundsError("AudioSpeakingRateQC bands were not found in the Swift source")
    return {
        name: {
            "slowSecondsPerUnit": bands[name],
            "minimumJudgedUnits": int(minimum.group(1) if name == "alphabetic" else minimum.group(2)),
        }
        for name in sorted(required)
    }


def benchmark_texts(matrix_source: str, ui_source: str) -> dict[str, str]:
    """`short`/`medium`/`long` of the CLI and macOS UI bench, plus the iOS UI long text."""
    texts = dict(re.findall(r'\("(short|medium|long)", "([^"]+)"\)', matrix_source))
    ios = re.search(r'#if os\(iOS\).*?longBenchmarkText =\s*"([^"]+)"', ui_source, re.S)
    if set(texts) != {"short", "medium", "long"} or ios is None:
        raise BoundsError("benchmark texts were not found in the Swift sources")
    texts["ios-ui-long"] = ios.group(1)
    return texts


def text_units(text: str) -> int:
    """Letters and digits, the unit `AudioSpeakingRateQC.measure` counts."""
    return sum(1 for character in text if character.isalpha() or character.isnumeric())


# --------------------------------------------------------------------------- #
# Committed records
# --------------------------------------------------------------------------- #

def load_records(root: Path) -> list[tuple[str, dict[str, Any]]]:
    records = []
    for path in sorted(root.glob("*/*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BoundsError(f"{path.name} is unreadable: {error}") from error
        record = value.get("historyRecord", value) if isinstance(value, dict) else None
        if isinstance(record, dict) and isinstance(record.get("run"), dict):
            records.append((path.name, record))
    return records


def take_duration(take: dict[str, Any]) -> float | None:
    output = take.get("output") if isinstance(take.get("output"), dict) else {}
    for value in (output.get("durationSeconds"), take.get("durationSeconds"),
                  (take.get("metrics") or {}).get("audioSeconds")):
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value)
    return None


def is_untouched(record: dict[str, Any], cut: str) -> bool:
    finished = str(record["run"].get("finishedAt") or record["run"].get("startedAt") or "")
    return finished > cut


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[min(rank, len(ordered) - 1)]


def summary(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "median": round(statistics.median(values), 4) if values else None,
        "p99": round(percentile(values, 0.99), 4) if values else None,
        "p995": round(percentile(values, 0.995), 4) if values else None,
        "max": round(max(values), 4) if values else None,
    }


# --------------------------------------------------------------------------- #
# Speaking rate (audit #10)
# --------------------------------------------------------------------------- #

def speaking_rate_rows(
    records: Iterable[tuple[str, dict[str, Any]]], *, texts: dict[str, str],
    language_matrix: dict[str, Any], language_corpus: dict[str, Any], corpus_digest: str,
    cut: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """One row per take whose text is known, with its rate and split."""
    cells = {cell["id"]: cell for cell in language_matrix.get("cells", []) if isinstance(cell, dict)}
    scripts = {entry["id"]: entry["script"] for entry in language_corpus.get("languages", [])}
    rows: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for name, record in records:
        kind, platform = record["run"].get("kind"), record["run"].get("platform")
        if kind not in GENERATION_KINDS:
            # The observer-effect lane, ui-perf and calibration corpora are not
            # benchmark takes of a text.
            for _ in record.get("takes") or []:
                skip(f"kind-{kind}")
            continue
        untouched = is_untouched(record, cut)
        for take in record.get("takes") or []:
            duration = take_duration(take)
            if duration is None:
                skip("no-duration")
                continue
            script_class = "alphabetic"
            if kind == "language":
                cell = cells.get(str(take.get("cell")))
                language = cell.get("scriptLang") if cell else None
                if language in ("chinese", "japanese"):
                    script_class = language
                units = (take.get("metrics") or {}).get("referenceCharacterCount")
                if units is None:
                    # Whisper-only records carry no count: the tracked corpus
                    # applies only when the record ran on this exact corpus.
                    if cell is None or record["inputs"].get("corpusHash") != corpus_digest:
                        skip("language-corpus-changed")
                        continue
                    units = text_units(scripts[language])
            else:
                length = take.get("length")
                if length not in ("short", "medium", "long"):
                    skip("no-benchmark-text")
                    continue
                key = "ios-ui-long" if (kind == "ui-generation" and platform == "ios" and length == "long") else length
                units = text_units(texts[key])
            if not units:
                skip("no-units")
                continue
            rows.append({
                "record": name, "kind": kind, "platform": platform, "cell": take.get("cell"),
                "scriptClass": script_class, "units": int(units), "durationSeconds": duration,
                "secondsPerUnit": duration / float(units), "untouched": untouched,
            })
    return rows, skipped


def speaking_rate_report(rows: list[dict[str, Any]], bands: dict[str, dict[str, float]],
                         skipped: dict[str, int], cut: str) -> dict[str, Any]:
    def judged(row: dict[str, Any]) -> bool:
        return row["units"] >= bands[row["scriptClass"]]["minimumJudgedUnits"]

    def over(row: dict[str, Any], bound: float) -> bool:
        return judged(row) and row["secondsPerUnit"] > bound

    flagged = [row for row in rows if over(row, bands[row["scriptClass"]]["slowSecondsPerUnit"])]
    classes: dict[str, Any] = {}
    for script_class in sorted({row["scriptClass"] for row in rows}):
        members = [row for row in rows if row["scriptClass"] == script_class]
        band = bands[script_class]["slowSecondsPerUnit"]
        calibration = [row for row in members if not row["untouched"]]
        untouched = [row for row in members if row["untouched"]]
        unflagged = [row["secondsPerUnit"] for row in members if not over(row, band)]
        warned = [row["secondsPerUnit"] for row in members if over(row, band)]
        classes[script_class] = {
            "warnSecondsPerUnit": band,
            "all": summary([row["secondsPerUnit"] for row in members]),
            "calibration": summary([row["secondsPerUnit"] for row in calibration]),
            "untouched": summary([row["secondsPerUnit"] for row in untouched]),
            "warned": {"calibration": sum(over(row, band) for row in calibration),
                       "untouched": sum(over(row, band) for row in untouched)},
            "separation": {
                "largestUnwarned": round(max(unflagged), 4) if unflagged else None,
                "smallestWarned": round(min(warned), 4) if warned else None,
            },
            "candidates": [
                {
                    "failSecondsPerUnit": round(band * factor, 4),
                    "factorOfWarnBand": factor,
                    "wouldFailCalibration": sum(over(row, band * factor) for row in calibration),
                    "wouldFailUntouched": sum(over(row, band * factor) for row in untouched),
                    "warnedTakesItWouldFail": sum(over(row, band * factor) for row in members if over(row, band)),
                }
                for factor in SPEAKING_RATE_CANDIDATE_FACTORS
            ],
        }
    untouched_rows = [row for row in rows if row["untouched"]]
    untouched_warned = [row for row in untouched_rows if over(row, bands[row["scriptClass"]]["slowSecondsPerUnit"])]
    return {
        "schemaVersion": REPORT_SCHEMA,
        "measure": "secondsPerTextUnit",
        "qcAlgorithmVersion": 8,
        "seedingCut": cut,
        "takes": len(rows),
        "skipped": dict(sorted(skipped.items())),
        "warned": [
            {key: (round(row[key], 4) if isinstance(row[key], float) else row[key])
             for key in ("record", "cell", "scriptClass", "units", "durationSeconds", "secondsPerUnit", "untouched")}
            for row in sorted(flagged, key=lambda item: -item["secondsPerUnit"])
        ],
        "classes": classes,
        "qualification": qualification(
            untouched_takes=len(untouched_rows), untouched_positives=len(untouched_warned),
            reference_evidence=None,
            label_source="the replay's own duration (a take counts as a run-on only by the rate the bound reads)",
        ),
    }


# --------------------------------------------------------------------------- #
# Clicks (audit #85)
# --------------------------------------------------------------------------- #

def click_events(samples: Iterable[float]) -> dict[str, int]:
    """Mirror of the QC v9 clustered click counter over published samples.

    The limiter clamps a step above SLEW_CLAMP, so in the published WAV a
    clamped sample differs from its predecessor by the clamp (up to PCM16
    rounding); clamped samples at most CLICK_EVENT_GAP_SAMPLES apart are one
    event, and an event is low-energy when the input envelope before it sits
    below LOW_ENERGY_CLICK_ENVELOPE. The published samples are the limited
    output, so the envelope reads the limited level: a screening mirror, not a
    replacement for the engine's count.
    """
    clamped = events = low_energy = 0
    last: int | None = None
    previous: float | None = None
    envelope = 0.0
    for index, sample in enumerate(samples):
        if previous is not None and abs(sample - previous) >= SLEW_CLAMP - PCM16_CLAMP_TOLERANCE:
            clamped += 1
            if last is None or index - last > CLICK_EVENT_GAP_SAMPLES:
                events += 1
                if envelope < LOW_ENERGY_CLICK_ENVELOPE:
                    low_energy += 1
            last = index
        envelope += (abs(sample) - envelope) * CLICK_ENVELOPE_COEFFICIENT
        previous = sample
    return {"clampedSamples": clamped, "clickEventCount": events, "lowEnergyClickEventCount": low_energy}


def read_pcm16_mono(path: Path) -> tuple[list[float], int]:
    try:
        with wave.open(str(path), "rb") as stream:
            if stream.getsampwidth() != 2 or stream.getnchannels() != 1:
                raise BoundsError(f"{path.name} is not 16-bit mono PCM")
            rate = stream.getframerate()
            frames = array("h")
            frames.frombytes(stream.readframes(stream.getnframes()))
    except (OSError, EOFError, wave.Error) as error:
        raise BoundsError(f"{path.name} is unreadable: {error}") from error
    if sys.byteorder == "big":
        frames.byteswap()
    return [value / 32767.0 for value in frames], rate


def wav_paths(inputs: Iterable[Path]) -> list[Path]:
    paths: list[Path] = []
    for item in inputs:
        if item.is_dir():
            paths.extend(sorted(path for path in item.rglob("*.wav") if path.is_file()))
        elif item.is_file():
            paths.append(item)
        else:
            raise BoundsError(f"{item} is neither a WAV nor a directory")
    return paths


def click_record_rows(records: Iterable[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Clamped samples per second of every committed take that reports them."""
    rows = []
    for name, record in records:
        for take in record.get("takes") or []:
            metrics = take.get("metrics") or {}
            qc_metrics = (take.get("audioQC") or {}).get("metrics") or {}
            count = metrics.get("discontinuityCount", qc_metrics.get("discontinuityCount"))
            duration = take_duration(take)
            if not isinstance(count, (int, float)) or isinstance(count, bool) or duration is None:
                continue
            verdict = (take.get("audioQC") or {}).get("instabilityVerdict")
            rows.append({
                "record": name, "cell": take.get("cell"), "clampedSamples": int(count),
                "durationSeconds": duration, "clampedPerSecond": count / duration,
                "instabilityVerdict": verdict,
                "clickEventsPerSecond": qc_metrics.get("clickEventsPerSecond", metrics.get("clickEventsPerSecond")),
            })
    return rows


def load_labels(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BoundsError(f"labels are unreadable: {error}") from error
    if not isinstance(value, dict) or not all(
        isinstance(entry, dict) and entry.get("label") in {"good", "bad"}
        and entry.get("split") in {"calibration", "confirmation"}
        for entry in value.values()
    ):
        raise BoundsError("labels map each WAV name to {label: good|bad, split: calibration|confirmation}")
    return value


def clicks_report(record_rows: list[dict[str, Any]], wav_rows: list[dict[str, Any]],
                  labels: dict[str, dict[str, str]], labels_digest: str | None) -> dict[str, Any]:
    fraction_bounds = {"warnFraction": 0.0005, "failFraction": 0.005}
    report: dict[str, Any] = {
        "schemaVersion": REPORT_SCHEMA,
        "measure": "clickEventsPerSecond",
        "qcAlgorithmVersion": 9,
        # The per-sample bound read as a rate at 24 kHz: its tolerance grows
        # with take length because it counts samples, not events (audit #85).
        "currentBoundAsClampedSamplesPerSecond": {
            "warn": fraction_bounds["warnFraction"] * ENGINE_SAMPLE_RATE,
            "fail": fraction_bounds["failFraction"] * ENGINE_SAMPLE_RATE,
        },
        "committedTakes": {
            "takes": len(record_rows),
            "withAnyClamp": sum(row["clampedSamples"] > 0 for row in record_rows),
            "withAnyClampWarned": sum(
                row["clampedSamples"] > 0 and row["instabilityVerdict"] == "warn" for row in record_rows),
            "clampedPerSecond": summary([row["clampedPerSecond"] for row in record_rows if row["clampedSamples"] > 0]),
            "reportingClickEventsPerSecond": sum(row["clickEventsPerSecond"] is not None for row in record_rows),
        },
    }
    if wav_rows:
        rates = [row["clickEventsPerSecond"] for row in wav_rows]
        report["wavTakes"] = {
            "takes": len(wav_rows),
            "clickEventsPerSecond": summary(rates),
            "lowEnergyShare": round(
                sum(row["lowEnergyClickEventCount"] for row in wav_rows)
                / max(1, sum(row["clickEventCount"] for row in wav_rows)), 4),
            "rows": wav_rows,
        }
        candidates = []
        for bound in CLICK_CANDIDATES_PER_SECOND:
            entry: dict[str, Any] = {"failEventsPerSecond": bound,
                                     "wouldFail": sum(rate > bound for rate in rates)}
            for split in ("calibration", "confirmation"):
                for label in ("good", "bad"):
                    members = [row for row in wav_rows
                               if labels.get(row["wav"], {}).get("split") == split
                               and labels.get(row["wav"], {}).get("label") == label]
                    entry[f"{split}{label.capitalize()}Failed"] = (
                        f"{sum(row['clickEventsPerSecond'] > bound for row in members)}/{len(members)}"
                    )
            candidates.append(entry)
        report["candidates"] = candidates
    confirmation = [row for row in wav_rows if labels.get(row["wav"], {}).get("split") == "confirmation"]
    report["qualification"] = qualification(
        untouched_takes=len(confirmation),
        untouched_positives=sum(labels[row["wav"]]["label"] == "bad" for row in confirmation),
        reference_evidence=labels_digest,
        label_source="the --labels file" if labels else "none (no labelled takes were supplied)",
    )
    return report


def qualification(*, untouched_takes: int, untouched_positives: int, reference_evidence: str | None,
                  label_source: str) -> dict[str, Any]:
    """What the threshold-change authority still needs; never `qualified: true`."""
    negatives = untouched_takes - untouched_positives
    cohort_met = (untouched_positives >= MINIMUM_CONFIRMATION_PER_CLASS
                  and negatives >= MINIMUM_CONFIRMATION_PER_CLASS)
    return {
        "qualified": False,
        "authority": "docs/reference/audio-qc-engineering.md#threshold-change-authority",
        "automaticMetricsMayScreenOnly": True,
        "untouchedConfirmationCohort": {
            "takes": untouched_takes, "positives": untouched_positives, "negatives": negatives,
            "minimumPerClass": MINIMUM_CONFIRMATION_PER_CLASS, "met": cohort_met,
        },
        "independentReferenceEvidence": {
            "digest": reference_evidence, "labelSource": label_source,
            "met": False if reference_evidence is None else None,
        },
        "decision": (
            "keep the measure without a failing bound; a candidate that screens well goes to "
            "explicit review with its independent reference evidence"
        ),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    rate = commands.add_parser("speaking-rate", help="replay committed records for the QC v8 speaking rate")
    rate.add_argument("--records", type=Path, default=RECORDS)
    rate.add_argument("--cut", default=SPEAKING_RATE_SEEDING_CUT,
                      help="records finished after this UTC instant form the untouched split")
    rate.add_argument("--list", action="store_true", help="print every warned take")
    clicks = commands.add_parser("clicks", help="replay clamp rates and screen per-second click bounds")
    clicks.add_argument("--records", type=Path, default=RECORDS)
    clicks.add_argument("--wav", type=Path, nargs="*", default=[],
                        help="WAV files or directories to run through the clustered-click mirror")
    clicks.add_argument("--labels", type=Path,
                        help="JSON: WAV name -> {label: good|bad, split: calibration|confirmation}")
    for command in (rate, clicks):
        command.add_argument("--output", type=Path, help="write the JSON report here")
    args = parser.parse_args(argv)
    try:
        records = load_records(args.records)
        if args.command == "speaking-rate":
            cut = datetime.fromisoformat(args.cut.replace("Z", "+00:00")).astimezone(timezone.utc)
            cut_text = cut.strftime("%Y-%m-%dT%H:%M:%SZ")
            rows, skipped = speaking_rate_rows(
                records,
                texts=benchmark_texts(BENCH_MATRIX_SOURCE.read_text(encoding="utf-8"),
                                      UI_CORPUS_SOURCE.read_text(encoding="utf-8")),
                language_matrix=json.loads(LANGUAGE_MATRIX.read_text(encoding="utf-8")),
                language_corpus=json.loads(LANGUAGE_CORPUS.read_text(encoding="utf-8")),
                corpus_digest=sha256_file(LANGUAGE_CORPUS), cut=cut_text,
            )
            report = speaking_rate_report(
                rows, speaking_rate_bands(ADAPTER_SOURCE.read_text(encoding="utf-8")), skipped, cut_text,
            )
            print(f"speaking-rate: takes={report['takes']} warned={len(report['warned'])} "
                  f"skipped={report['skipped']}")
            for name, block in report["classes"].items():
                print(f"  {name:<10} warn>{block['warnSecondsPerUnit']} n={block['all']['count']} "
                      f"median={block['all']['median']} p99.5={block['all']['p995']} max={block['all']['max']} "
                      f"untouched={block['untouched']['count']} separation={block['separation']}")
            if args.list:
                for row in report["warned"]:
                    print(f"    {row['secondsPerUnit']:.4f} s/unit {row['durationSeconds']:.2f} s "
                          f"{row['record']} {row['cell']}")
        else:
            labels = load_labels(args.labels)
            wav_rows = []
            for path in wav_paths(args.wav):
                samples, sample_rate = read_pcm16_mono(path)
                counts = click_events(samples)
                duration = len(samples) / float(sample_rate) if sample_rate else 0.0
                wav_rows.append({
                    "wav": path.name, **counts, "durationSeconds": round(duration, 4),
                    "clickEventsPerSecond": round(counts["clickEventCount"] / duration, 4) if duration else 0.0,
                })
            report = clicks_report(
                click_record_rows(records), wav_rows, labels,
                sha256_file(args.labels) if args.labels else None,
            )
            committed = report["committedTakes"]
            print(f"clicks: committedTakes={committed['takes']} withAnyClamp={committed['withAnyClamp']} "
                  f"warned={committed['withAnyClampWarned']} wavTakes={len(wav_rows)}")
        print(f"qualified={str(report['qualification']['qualified']).lower()} "
              f"(untouched cohort met={report['qualification']['untouchedConfirmationCohort']['met']}, "
              f"independent reference evidence met={report['qualification']['independentReferenceEvidence']['met']})")
        if args.output is not None:
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    except (BoundsError, OSError, ValueError) as error:
        print(f"derive-audio-qc-bounds: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
