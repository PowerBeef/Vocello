"""Human-speech controls: every detector measured on people before it is trusted on takes.

`build` writes a `vocello.qc.takes/1` manifest of human read speech from the
extracted speaker corpora (MLS for French, LibriTTS-R for English by default):
a deterministic sample per language, at most a few clips per speaker, each
marked `control: true` with mode `human`, cell `control` and family
`human:<source>:<speaker>`. Run it with `qc.py run --takes <manifest> --lane
controls`; a control take is scored and flagged, but always at report-only, and
the controls lane stays out of `fit`, `queue`, norms and references.

`report` compares a controls run with generated runs: per detector and
language, the share of takes each provisional rule (or fitted threshold)
flags, with Clopper-Pearson bounds, and the median and p90 of every feature. A
detector that flags a tenth of human recordings measures something other than
defects.
"""

from __future__ import annotations

import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from qc import corpora, store
from qc.store import Layout

CONTROLS_LANE = "controls"
DEFAULT_SOURCES = ("mls:french", "libritts-r:english")
DEFAULT_PER_LANGUAGE = 150
DEFAULT_PER_SPEAKER = 3
MIN_SECONDS = 2.0
MAX_SECONDS = 20.0
REPORT_SCHEMA = "vocello.qc.controls-report/1"


class ControlsError(RuntimeError):
    """The corpora or runs cannot support the controls."""


def _manifest(source: str) -> tuple[dict[str, Any], Path]:
    registry = corpora.load_registry()
    directory = corpora.source_directory(registry, source)
    path = directory / corpora.EXTRACTED_DIRECTORY / corpora.MANIFEST_NAME
    if not path.is_file():
        raise ControlsError(f"{source}: no extraction at {path.parent}")
    manifest = store.read_json(path)
    issues = corpora.manifest_issues(manifest, corpora.extraction_identity(registry, source))
    if issues:
        raise ControlsError(f"{source}: {'; '.join(issues)}")
    return manifest, path.parent


def _parse_sources(sources: Iterable[str]) -> list[tuple[str, str]]:
    parsed = []
    for item in sources:
        source, _, language = item.partition(":")
        if not source or not language:
            raise ControlsError(f"a control source is <corpus>:<language>, not {item!r}")
        parsed.append((source, store.normalize_language(language)))
    return parsed


def build_manifest(sources: Iterable[str] = DEFAULT_SOURCES, *, per_language: int = DEFAULT_PER_LANGUAGE,
                   per_speaker: int = DEFAULT_PER_SPEAKER, seed: int = 0) -> dict[str, Any]:
    """A deterministic sample of human clips per (corpus, language), spread over speakers."""

    takes: list[dict[str, Any]] = []
    for source, language in _parse_sources(sources):
        manifest, root = _manifest(source)
        clips = [clip for clip in manifest["clips"]
                 if store.normalize_language(clip.get("language") or "") == language and clip.get("text")
                 and MIN_SECONDS <= float(clip.get("durationSeconds") or 0) <= MAX_SECONDS
                 and not clip.get("clippedSamples")]
        by_speaker: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for clip in sorted(clips, key=lambda clip: clip["clipID"]):
            by_speaker[str(clip.get("speaker"))].append(clip)
        rng = random.Random(f"vocello.qc.controls/1:{source}:{language}:{seed}")
        speakers = sorted(by_speaker)
        rng.shuffle(speakers)
        for speaker in speakers:
            rng.shuffle(by_speaker[speaker])
        chosen: list[dict[str, Any]] = []
        for round_index in range(per_speaker):
            for speaker in speakers:
                if len(chosen) >= per_language:
                    break
                if round_index < len(by_speaker[speaker]):
                    chosen.append(by_speaker[speaker][round_index])
        if len(chosen) < per_language:
            raise ControlsError(f"{source}:{language}: {len(chosen)} usable clips, {per_language} wanted")
        for clip in chosen:
            audio = (root / clip["wavPath"]).resolve()
            if not audio.is_file():
                raise ControlsError(f"{source}: missing clip {clip['clipID']}")
            take_id = f"human-{source}-{clip['clipID']}"
            family = f"human:{source}:{clip.get('speaker')}"
            takes.append({
                "takeID": take_id, "token": store.take_token(f"controls:{source}", clip["clipID"]),
                "audio": str(audio), "audioSHA256": clip["wavSHA256"], "language": language,
                "text": clip["text"], "mode": "human", "voice": family, "cell": "control",
                "reference": None, "referenceSHA256": None, "referenceText": None,
                "finishReason": None, "seed": None, "family": family, "control": True,
            })
    return {"schema": store.TAKES_SCHEMA, "source": f"controls-{seed}", "takes": takes}


def write_manifest(layout: Layout, manifest: dict[str, Any], name: str) -> Path:
    path = layout.private / "manifests" / f"{name}.takes.json"
    store.write_json_atomic(path, manifest)
    return path


# --- report ------------------------------------------------------------------------

def _run_dir(layout: Layout, run_id: str) -> Path:
    directory = layout.runs / run_id
    if not (directory / "flags.json").is_file() or not (directory / "features.json").is_file():
        raise ControlsError(f"run {run_id} has no flags.json and features.json")
    return directory


def _collect(layout: Layout, run_ids: Iterable[str], *, controls: bool) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    flagged: list[dict[str, Any]] = []
    features: dict[str, dict[str, Any]] = {}
    for run_id in run_ids:
        directory = _run_dir(layout, run_id)
        rows = {row["token"]: row for row in store.read_json(directory / "features.json")["takes"]}
        for entry in store.read_json(directory / "flags.json")["takes"]:
            if bool(entry.get("control")) != controls:
                continue
            flagged.append(entry)
            if entry["token"] in rows:
                features[entry["token"]] = rows[entry["token"]]
    return flagged, features


def _rates(entries: list[dict[str, Any]], detector_ids: list[str]) -> dict[str, dict[str, Any]]:
    from qc import fit  # the shared weighted rate and Clopper-Pearson bounds

    by_language: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        by_language[entry.get("language") or "unknown"].append(entry)
        by_language["*"].append(entry)
    out: dict[str, dict[str, Any]] = {}
    for detector_id in detector_ids:
        out[detector_id] = {}
        for language, rows in sorted(by_language.items()):
            hits = [any(flag["detector"] == detector_id for flag in row["flags"]) for row in rows]
            out[detector_id][language] = fit.weighted_rate(hits, [1.0] * len(hits))
    return out


def _feature_summary(rows: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows.values():
        for name, feature in (row.get("features") or {}).items():
            value = (feature or {}).get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool) and np.isfinite(value):
                values[name][row.get("language") or "unknown"].append(float(value))
                values[name]["*"].append(float(value))
    summary: dict[str, dict[str, Any]] = {}
    for name, by_language in sorted(values.items()):
        summary[name] = {language: {"n": len(series), "p50": round(float(np.percentile(series, 50)), 4),
                                    "p90": round(float(np.percentile(series, 90)), 4)}
                         for language, series in sorted(by_language.items())}
    return summary


def report(layout: Layout, control_runs: list[str], generated_runs: list[str]) -> dict[str, Any]:
    from qc import detectors as detector_lib

    if not control_runs:
        raise ControlsError("name at least one controls run")
    config = detector_lib.load_config(layout)
    detector_ids = [detector["id"] for detector in config["detectors"]]
    control_entries, control_rows = _collect(layout, control_runs, controls=True)
    if not control_entries:
        raise ControlsError("the controls runs hold no control take")
    generated_entries, generated_rows = _collect(layout, generated_runs, controls=False)
    return {
        "schema": REPORT_SCHEMA, "controlRuns": control_runs, "generatedRuns": generated_runs,
        "takes": {"controls": len(control_entries), "generated": len(generated_entries)},
        "flagRates": {"controls": _rates(control_entries, detector_ids),
                      "generated": _rates(generated_entries, detector_ids) if generated_entries else {}},
        "features": {"controls": _feature_summary(control_rows),
                     "generated": _feature_summary(generated_rows) if generated_rows else {}},
    }


def format_report(document: dict[str, Any], *, limit: float = 0.05) -> list[str]:
    """One line per detector and language that flags any control take; `!` marks a rate above `limit`."""

    lines = [f"controls {document['takes']['controls']} takes, generated {document['takes']['generated']} takes"]
    for detector_id, by_language in document["flagRates"]["controls"].items():
        for language, rate in by_language.items():
            if not rate["n"] or not rate["rate"]:
                continue
            generated = document["flagRates"]["generated"].get(detector_id, {}).get(language, {})
            mark = "!" if rate["rate"] > limit else " "
            lines.append(f"{mark} {detector_id:<26} {language:<8} controls {rate['rate']:.3f} "
                         f"[{rate['lower']:.3f}, {rate['upper']:.3f}] n={rate['n']}"
                         + (f"   generated {generated['rate']:.3f} n={generated['n']}" if generated.get("n") else ""))
    return lines
