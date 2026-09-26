#!/usr/bin/env python3
"""Audio-QC qualification engine commands (AQ-03, audit 2026-09-25 section 5).

Commands:
  validate-policy   check config/audio-qc-qualification-policy.json; part of the
                    deterministic contract gate.
  sample-sizes      print the exact one-sided Clopper-Pearson sample-size table.
  catalog           print the T1 injector catalog as JSON.
  meta-evaluation   "measure the present" (M1): run today's Fast QC v8, through
                    its Python mirror in scripts/lib/audio_qc.py, over clean
                    procedural sources, every T1 injection and sham of them and
                    the abstention fixtures; replay the committed benchmark
                    records read-only; write meta-evaluation.json and
                    meta-evaluation.md (default
                    build/artifacts/diagnostics/audio-qc-meta-evaluation/).

Report-only. Nothing here moves a threshold, rewrites a record or qualifies a
detector: procedural sources are T1 construction, not N2, so under A2 they can
never qualify a fail bound, and committed records hold only PASS and WARN
takes, so they bound warn-level flag rates on natural takes (N3) and say
nothing about how often a fail bound fires. The v8 bounds stay
`legacy-unqualified` (A10). No model, device, download or native build runs.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from lib import audio_qc
from lib.qc_qualification import fixtures, injectors, policy as policy_module, resampling
from lib.qc_qualification.pcm import json_digest
from lib.qc_qualification.stats import Rate, sample_size_table

REPO = Path(__file__).resolve().parents[1]
RECORDS = REPO / "benchmarks" / "runs"
DEFAULT_OUT = REPO / "build" / "artifacts" / "diagnostics" / "audio-qc-meta-evaluation"
SCHEMA = "vocello.audioqc.meta-evaluation/1"
GENERATOR = "audio-qc-meta-evaluation/1"
SUBJECT = "fastqc@8"
DEFAULT_SOURCES = 60
DEFAULT_STRATUM_SOURCES = 30
DEFAULT_SEED = 7
ENGINE_SAMPLE_RATE = 24_000
# The v8 flag families designed to catch each injector family's defect. An
# empty tuple means v8 has no detector for it: its alarms there are incidental.
TARGETS = {
    "SIG-CLICK": ("clicks",),
    "SIG-DROP": ("dropout", "cadence"),
    "SIG-CLIP": ("clipping", "hot"),
    "SIG-DC": ("dc_offset",),
    "SIG-LEVEL": ("low_level", "near_silent", "silent"),
    "SIG-NOISE": (),
    "SIG-SIL": ("terminal_silence",),
    "BND-TRUNC": (),
    "BND-RUNON": ("speaking_rate_slow",),
    "CNT-REP": ("speaking_rate_slow",),
    "CNT-DEL": (),
    "CNT-INS": ("speaking_rate_slow",),
    "PRS-OCT": (),
    "PRS-BRK": (),
    "PRS-RATE": ("speaking_rate_slow",),
    "IDN-SHIFT": (),
    "IDN-SWAP": (),
}
META_CODES = frozenset({"instability-warn", "written-output-warn"})


# --------------------------------------------------------------------------- #
# Procedural evidence
# --------------------------------------------------------------------------- #

def _qc(samples: np.ndarray, text: str) -> dict[str, Any]:
    return audio_qc.fast_qc_v8(samples, sample_rate=ENGINE_SAMPLE_RATE, text=text)


def _families(report: dict[str, Any]) -> set[str]:
    return set(report["flagLevels"])


def _rate(flags: Iterable[bool]) -> dict:
    values = list(flags)
    return Rate(sum(values), len(values)).as_dict()


def _flag_table(reports: list[dict[str, Any]]) -> dict[str, dict]:
    table: dict[str, dict] = {}
    for family, levels in audio_qc.FASTQC_V8_FLAGS.items():
        entry = {}
        for level in levels:
            entry[level] = _rate(report["flagLevels"].get(family) in ((level,) if level == "fail"
                                                                      else ("warn", "fail"))
                                 for report in reports)
        if any(value["events"] for value in entry.values()):
            table[family] = entry
    return table


def _clean(reports: list[dict[str, Any]]) -> dict:
    return {
        "units": len(reports),
        "alarm": _rate(report["verdict"] != "pass" for report in reports),
        "fail": _rate(report["verdict"] == "fail" for report in reports),
        "flags": _flag_table(reports),
    }


def _overlap(first: dict, second: dict) -> bool:
    return first["lower"] <= second["upper"] and second["lower"] <= first["upper"]


def _summary(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    def at(fraction: float) -> float:
        return round(ordered[min(len(ordered) - 1, int(fraction * len(ordered)))], 6)
    return {"count": len(ordered), "median": round(statistics.median(ordered), 6), "p90": at(0.9),
            "p99": at(0.99), "max": round(ordered[-1], 6)}


def procedural_evidence(sources: int, stratum_sources: int, seed: int) -> dict:
    modal = [fixtures.clean_fixture(index, "modal") for index in range(sources)]
    clean_reports: dict[str, list[dict]] = {}
    for stratum in fixtures.CLEAN_STRATA:
        pool = modal if stratum == "modal" else [fixtures.clean_fixture(index, stratum)
                                                 for index in range(stratum_sources)]
        clean_reports[stratum] = [_qc(fixture.samples, fixture.text) for fixture in pool]
    clean = {stratum: _clean(reports) for stratum, reports in clean_reports.items()}
    pooled_clean = [report for reports in clean_reports.values() for report in reports]
    modal_alarm = clean["modal"]["alarm"]

    rows = []
    shams = []
    click_rates: dict[str, list[float]] = {"clean": [report["clickEventsPerSecond"]
                                                     for report in clean_reports["modal"]]}
    pooled_sham_units: list[tuple[str, bool]] = []
    for injector in injectors.CATALOG.values():
        targets = TARGETS[injector.injector_id]
        for variant in injector.variants:
            reports = []
            for fixture in modal:
                injection = injectors.inject(injector.injector_id, variant.name, fixture, seed)
                reports.append(_qc(injection.samples, fixture.text))
            alarms = [report["verdict"] != "pass" for report in reports]
            row = {
                "injector": injector.key, "variant": variant.name, "severity": variant.severity,
                "classes": list(injector.classes), "parameters": dict(variant.parameters),
                "targets": list(targets), "units": len(reports),
                "alarm": _rate(alarms),
                "fail": _rate(report["verdict"] == "fail" for report in reports),
                "target": _rate(bool(_families(report) & set(targets)) for report in reports) if targets else None,
                "flags": {family: sum(1 for report in reports if family in report["flagLevels"])
                          for family in sorted({family for report in reports for family in report["flagLevels"]})},
            }
            if injector.injector_id == "SIG-CLICK":
                click_rates[f"{injector.key} {variant.name}"] = [report["clickEventsPerSecond"] for report in reports]
            if variant.severity in injectors.NON_DEFECT_SEVERITIES:
                row["a4"] = {"cleanModalAlarm": modal_alarm, "overlaps": _overlap(row["alarm"], modal_alarm)}
                shams.append(row)
                pooled_sham_units += [(fixture.family, alarm) for fixture, alarm in zip(modal, alarms)]
            else:
                rows.append(row)

    abstention = []
    for kind in fixtures.ABSTENTION_KINDS:
        fixture = fixtures.abstention_fixture(kind)
        report = _qc(fixture.samples, fixture.text)
        abstention.append({"fixture": kind, "durationSeconds": round(fixture.duration_seconds, 3),
                           "verdict": report["verdict"], "flags": report["flags"],
                           "passes": report["verdict"] == "pass"})

    detected_families = {row["injector"].split("@")[0] for row in rows
                         if row["target"] and row["severity"] == "severe" and row["target"]["events"]}
    blind = []
    for injector in injectors.CATALOG.values():
        if injector.injector_id in detected_families:
            continue
        severe = [row for row in rows if row["injector"] == injector.key and row["severity"] == "severe"]
        blind.append({"injector": injector.key, "defect": injector.defect,
                      "hasV8Detector": bool(TARGETS[injector.injector_id]),
                      "severeAlarm": [{"variant": row["variant"], **row["alarm"]} for row in severe]})
    return {
        "population": "T1 procedural sources (tones, glottal-pulse vowels, formant sequences, seeded noise); "
                      "neither N1 nor N2, so no fail bound can qualify on them (A2)",
        "sources": sources,
        "stratumSources": stratum_sources,
        "seed": seed,
        "clean": clean,
        "cleanPooled": _clean(pooled_clean),
        "detection": rows,
        "shams": shams,
        "shamsPooled": {**resampling.cluster_bootstrap_rate(pooled_sham_units, label="shams"),
                        "familyLevel": Rate(*resampling.family_level_events(pooled_sham_units)).as_dict()},
        "blindSpots": blind,
        "abstention": abstention,
        "clickEventsPerSecond": {name: _summary(values) for name, values in click_rates.items()},
    }


# --------------------------------------------------------------------------- #
# Committed evidence (read-only)
# --------------------------------------------------------------------------- #

def load_records(root: Path) -> list[tuple[str, dict[str, Any]]]:
    records = []
    for path in sorted(root.glob("*/*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        record = value.get("historyRecord", value) if isinstance(value, dict) else None
        if isinstance(record, dict) and isinstance(record.get("run"), dict):
            records.append((f"{path.parent.name}/{path.name}", record))
    return records


def _duration(take: dict[str, Any]) -> float | None:
    output = take.get("output") if isinstance(take.get("output"), dict) else {}
    for value in (output.get("durationSeconds"), take.get("durationSeconds"),
                  (take.get("metrics") or {}).get("audioSeconds")):
        if audio_qc.finite_number(value) is not None and value > 0:
            return float(value)
    return None


def _take_family(name: str, take: dict[str, Any]) -> str:
    seed = take.get("seed")
    if seed is not None:
        return f"seeded|{take.get('cell')}|{seed}|{take.get('modelRevision')}|{take.get('modelQuantization')}"
    return f"take|{name}|{take.get('generationID') or take.get('takeIndex')}"


def _replay(metrics: dict[str, Any], duration: float) -> dict[str, str]:
    """The v8 bounds on a recorded metric vector: pass, warn, fail or at-least-warn."""
    frames = duration * ENGINE_SAMPLE_RATE
    bounds = audio_qc.FASTQC_V8
    levels: dict[str, str] = {}
    clicks = audio_qc.finite_number(metrics.get("discontinuityCount"))
    if clicks is not None:
        fraction = clicks / frames
        levels["clicks"] = ("fail" if fraction > bounds["clickFailFraction"]
                            else "warn" if fraction > bounds["clickWarnFraction"] else "pass")
    clipped = audio_qc.finite_number(metrics.get("clipCount"))
    if clipped is not None:
        levels["clipping"] = ("fail" if clipped / frames > bounds["clipFailFraction"]
                              else "warn" if clipped > 0 else "pass")
    dc = audio_qc.finite_number(metrics.get("dcOffset"))
    if dc is not None:
        levels["dc_offset"] = ("fail" if abs(dc) > bounds["dcOffsetFail"]
                               else "warn" if abs(dc) > bounds["dcOffsetWarn"] else "pass")
    silence = audio_qc.finite_number(metrics.get("longestSilenceMS"))
    if silence is not None:
        levels["dropout"] = ("fail" if silence >= bounds["egregiousMS"]["declaredPauseOrLong"]
                             else "at-least-warn" if silence >= bounds["egregiousMS"]["noDeclaredPause"]
                             else "pass")
    nonfinite = audio_qc.finite_number(metrics.get("nonFiniteCount"))
    if nonfinite is not None:
        levels["nonfinite"] = "fail" if nonfinite > 0 else "pass"
    return levels


def committed_evidence(root: Path) -> dict:
    records = load_records(root)
    by_version: dict[int, list[dict]] = {}
    for name, record in records:
        for take in record.get("takes") or []:
            qc = take.get("audioQC")
            if not isinstance(qc, dict):
                continue
            duration = _duration(take)
            codes = [str(code) for code in qc.get("warningCodes") or [] if str(code) not in META_CODES]
            by_version.setdefault(int(qc.get("algorithmVersion", 1)), []).append({
                "family": _take_family(name, take),
                "verdict": str(qc.get("verdict")),
                "families": sorted({audio_qc.flag_family(code) for code in codes}),
                "replay": _replay(qc.get("metrics") or {}, duration) if duration else {},
                "clickEventsPerSecond": audio_qc.finite_number((qc.get("metrics") or {}).get("clickEventsPerSecond")),
            })
    versions = {}
    for version, takes in sorted(by_version.items()):
        flag_names = sorted({family for take in takes for family in take["families"]})
        warn_units = [(take["family"], take["verdict"] == "warn") for take in takes]
        replay: dict[str, dict] = {}
        for bound in ("clicks", "clipping", "dc_offset", "dropout", "nonfinite"):
            judged = [take for take in takes if bound in take["replay"]]
            if not judged:
                continue
            replay[bound] = {
                "takes": len(judged),
                "warnOrWorse": _rate(take["replay"][bound] != "pass" for take in judged),
                "fail": _rate(take["replay"][bound] == "fail" for take in judged),
            }
        versions[str(version)] = {
            "takes": len(takes),
            "families": len({take["family"] for take in takes}),
            "publishedVerdicts": {verdict: sum(1 for take in takes if take["verdict"] == verdict)
                                  for verdict in sorted({take["verdict"] for take in takes})},
            "warn": {**resampling.cluster_bootstrap_rate(warn_units, label=f"committed-v{version}"),
                     "familyLevel": Rate(*resampling.family_level_events(warn_units)).as_dict()},
            "flags": {family: _rate(family in take["families"] for take in takes) for family in flag_names},
            "v8BoundReplay": replay,
            "clickEventsPerSecond": _summary([take["clickEventsPerSecond"] for take in takes
                                              if take["clickEventsPerSecond"] is not None]),
        }
    digest = json_digest([[name, record.get("run", {}).get("id")]
                          for name, record in records])
    return {
        "population": "N3: natural Vocello takes in committed benchmark records (read-only)",
        "records": len(records),
        "recordSetSHA256": digest,
        "takes": sum(version["takes"] for version in versions.values()),
        "byAlgorithmVersion": versions,
        "caveats": [
            "Only PASS and WARN takes are ever published, so a fail rate on committed takes is zero by "
            "construction and bounds nothing.",
            "Takes carry no labels: a flag rate f bounds FAR only as f / (1 - pi_max), pi_max being the "
            "defect prevalence.",
            "The v8 bound replay applies today's bounds to each version's recorded metric vector; the "
            "dropout replay cannot see the text's pause budget, so 1.2-2.0 s reads at-least-warn.",
            "Unseeded takes are their own family; seeded takes share one per cell, seed and model.",
        ],
    }


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #

def _fraction(rate: dict | None) -> str:
    if rate is None:
        return "n/a"
    return f"{rate['events']}/{rate['units']}"


def _bound(rate: dict | None, side: str = "upper") -> str:
    if rate is None or rate["units"] == 0:
        return "n/a"
    return f"{rate[side]:.3f}"


def headline(report: dict) -> list[str]:
    procedural = report["procedural"]
    modal = procedural["clean"]["modal"]
    lines = [
        f"Clean procedural speech: v8 alarmed on {_fraction(modal['alarm'])} modal sources "
        f"(FAR <= {_bound(modal['alarm'])}, one-sided CP 95%) and on "
        f"{_fraction(procedural['cleanPooled']['alarm'])} across all five strata; the long-pause stratum "
        f"alone: {_fraction(procedural['clean']['long-pause']['alarm'])}.",
    ]
    for row in procedural["detection"]:
        if row["injector"].startswith("SIG-CLICK") and row["variant"] in ("moderate", "severe"):
            lines.append(f"Clicks {row['variant']} ({row['parameters']['amplitude']} FS, "
                         f"{row['parameters']['ratePerSecond']}/s): v8 `clicks` detected "
                         f"{_fraction(row['target'])} (TPR >= {_bound(row['target'], 'lower')}).")
    missing = [entry["injector"] for entry in procedural["blindSpots"] if not entry["hasV8Detector"]]
    silent = [entry["injector"] for entry in procedural["blindSpots"] if entry["hasV8Detector"]]
    lines.append(f"Blind spots: {len(missing)} of {len(injectors.CATALOG)} injector families have no v8 "
                 f"detector ({', '.join(missing) or 'none'})"
                 + (f", and {', '.join(silent)} never trips its target flag at severe." if silent else "."))
    passing = [entry["fixture"] for entry in procedural["abstention"] if entry["passes"]]
    lines.append(f"Abstention fixtures v8 passes (it cannot abstain): {len(passing)} of "
                 f"{len(procedural['abstention'])} ({', '.join(passing)}).")
    shams = [row for row in procedural["shams"] if not row["a4"]["overlaps"]]
    if shams:
        lines.append("Shams outside the clean interval (A4 would refuse the detector for these families): "
                     + ", ".join(f"{row['injector']} {row['variant']} {_fraction(row['alarm'])}" for row in shams)
                     + ".")
    committed = report.get("committed")
    if committed:
        v8 = committed["byAlgorithmVersion"].get("8")
        lines.append(f"Committed evidence: {committed['takes']} takes in {committed['records']} records."
                     + (f" QC v8: {v8['takes']} takes, warn {_fraction(v8['warn']['familyLevel'])} families "
                        f"(flag-rate bound {_bound(v8['warn']['familyLevel'])})." if v8 else ""))
    return lines


def markdown(report: dict) -> str:
    procedural = report["procedural"]
    out = [
        "<!-- Generated by scripts/audio_qc_qualification.py meta-evaluation. Do not edit. -->",
        "## Audio QC meta-evaluation M1: Fast QC v8, measured",
        "",
        f"Subject `{report['subject']['detector']}` through `{report['subject']['mirror']}`; calibration "
        f"`{report['subject']['calibration']}` (A10). Report-only: nothing here qualifies a bound. "
        f"Rates are k/n with one-sided Clopper-Pearson 95% bounds; one procedural source is one family.",
        "",
        "### Headline",
        "",
        *[f"- {line}" for line in report["headline"]],
        "",
        "### Clean procedural speech (negatives)",
        "",
        "| Stratum | Units | Alarm (warn or fail) | FAR upper | Fail | Flags seen |",
        "|---|---|---|---|---|---|",
    ]
    for stratum, entry in procedural["clean"].items():
        flags = ", ".join(sorted(entry["flags"])) or "none"
        out.append(f"| {stratum} | {entry['units']} | {_fraction(entry['alarm'])} | {_bound(entry['alarm'])} | "
                   f"{_fraction(entry['fail'])} | {flags} |")
    out += ["", "### Detection of T1 injections (positives)", "",
            "| Injector | Variant | Severity | Target v8 flags | Target detected | TPR lower | Any alarm | Fail |",
            "|---|---|---|---|---|---|---|---|"]
    for row in procedural["detection"]:
        target = ", ".join(row["targets"]) or "none (no v8 detector)"
        out.append(f"| {row['injector']} | {row['variant']} | {row['severity']} | {target} | "
                   f"{_fraction(row['target'])} | {_bound(row['target'], 'lower')} | {_fraction(row['alarm'])} | "
                   f"{_fraction(row['fail'])} |")
    out += ["", "### Shams and controls (A4)", "",
            "| Injector | Variant | Alarm | Clean modal alarm | Intervals overlap |", "|---|---|---|---|---|"]
    for row in procedural["shams"]:
        out.append(f"| {row['injector']} | {row['variant']} | {_fraction(row['alarm'])} | "
                   f"{_fraction(row['a4']['cleanModalAlarm'])} | {'yes' if row['a4']['overlaps'] else 'NO'} |")
    out += ["", "### Abstention fixtures (a judge must never pass these)", "",
            "| Fixture | Seconds | v8 verdict | Flags |", "|---|---|---|---|"]
    for entry in procedural["abstention"]:
        out.append(f"| {entry['fixture']} | {entry['durationSeconds']} | {entry['verdict']} | "
                   f"{', '.join(entry['flags']) or 'none'} |")
    committed = report.get("committed")
    if committed:
        out += ["", "### Committed evidence (N3, read-only)", "",
                f"{committed['takes']} takes with audio QC in {committed['records']} records "
                f"(record set `{committed['recordSetSHA256'][:12]}`).", "",
                "| QC version | Takes | Families | Warn (families) | Flag-rate upper | Replayed v8 clicks warn+ | "
                "Replayed v8 clicks fail |", "|---|---|---|---|---|---|---|"]
        for version, entry in committed["byAlgorithmVersion"].items():
            clicks = entry["v8BoundReplay"].get("clicks")
            out.append(f"| {version} | {entry['takes']} | {entry['families']} | "
                       f"{_fraction(entry['warn']['familyLevel'])} | {_bound(entry['warn']['familyLevel'])} | "
                       f"{_fraction(clicks['warnOrWorse']) if clicks else 'n/a'} | "
                       f"{_fraction(clicks['fail']) if clicks else 'n/a'} |")
        out += [""] + [f"- {caveat}" for caveat in committed["caveats"]]
    out += ["", f"Inputs: policy `{report['inputs']['policySHA256'][:12]}`, injector catalog "
                f"v{report['inputs']['catalogVersion']}, fixtures v{report['inputs']['fixtureVersion']}, "
                f"NumPy {report['inputs']['numpy']}.", ""]
    return "\n".join(out)


def meta_evaluation(*, sources: int, stratum_sources: int, seed: int, records: Path | None) -> dict:
    report = {
        "schema": SCHEMA,
        "generator": GENERATOR,
        "phase": "M1",
        "reportOnly": True,
        "subject": {"detector": SUBJECT, "mirror": audio_qc.FASTQC_V8_MIRROR, "calibration": "legacy-unqualified",
                    "replayConstants": audio_qc.FASTQC_V8},
        "inputs": {"policySHA256": policy_module.policy_digest(), "catalogVersion": injectors.CATALOG_VERSION,
                   "fixtureVersion": fixtures.FIXTURE_VERSION, "numpy": np.__version__},
        "procedural": procedural_evidence(sources, stratum_sources, seed),
        "committed": committed_evidence(records) if records is not None else None,
    }
    report["headline"] = headline(report)
    return report


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-policy", help="validate the qualification policy file")
    validate.add_argument("--policy", type=Path, default=policy_module.POLICY_PATH)
    commands.add_parser("sample-sizes", help="print the Clopper-Pearson sample-size table")
    commands.add_parser("catalog", help="print the T1 injector catalog")
    meta = commands.add_parser("meta-evaluation", help="measure Fast QC v8 (M1, report-only)")
    meta.add_argument("--sources", type=int, default=DEFAULT_SOURCES,
                      help="modal procedural sources (one family each); injections use them all")
    meta.add_argument("--stratum-sources", type=int, default=DEFAULT_STRATUM_SOURCES,
                      help="sources per other clean stratum")
    meta.add_argument("--seed", type=int, default=DEFAULT_SEED)
    meta.add_argument("--records", type=Path, default=RECORDS, help="committed benchmark records (read-only)")
    meta.add_argument("--no-records", action="store_true", help="skip the committed-evidence replay")
    meta.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if args.command == "validate-policy":
        try:
            errors = policy_module.validate_policy(policy_module.load_policy(args.policy))
        except policy_module.PolicyError as error:
            errors = [str(error)]
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        if errors:
            return 1
        print("audio-qc qualification policy: PASS")
        return 0
    if args.command == "sample-sizes":
        print(json.dumps(sample_size_table(), indent=2))
        return 0
    if args.command == "catalog":
        print(json.dumps(injectors.catalog_description(), indent=2, sort_keys=True))
        return 0
    if args.sources < 1 or args.stratum_sources < 1:
        parser.error("--sources and --stratum-sources must be positive")
    report = meta_evaluation(sources=args.sources, stratum_sources=args.stratum_sources, seed=args.seed,
                             records=None if args.no_records else args.records)
    args.out.mkdir(parents=True, exist_ok=True)
    json_path = args.out / "meta-evaluation.json"
    markdown_path = args.out / "meta-evaluation.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown(report), encoding="utf-8")
    for line in report["headline"]:
        print(f"- {line}")
    print(f"wrote {_display(json_path)} and {_display(markdown_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
