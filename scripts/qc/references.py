"""Frozen scoring references from the pool: `qc.py references`.

`pitch.register_offset_st` holds a take to its voice's pitch median and `aesthetics.*_delta` hold it
to its cell's Audiobox medians. Taken from the run alone, those references moved with whatever else
the run held, so one take scored differently in two runs. `qc.py references --takes <runs...>`
freezes them from a pool's cached results (nothing runs a model):

- `voicePitch`: per voice (`mode|voice`, custom and design voices; a clone take is held to its own
  reference clip), the median of its takes' pitch medians over the frames both pitch trackers agree
  on (`qc.features.take_pitch_median`);
- `cellAesthetics`: per cell, the medians of Audiobox's PQ and CE.

It writes `config/qc/references-v<N>.json`: those aggregates with their counts, the model
identities and one digest of the pool's audio digests. It never holds a take id, path or text.
`qc.features.build_context` reads the newest file first and falls back to the run's own takes for
a voice or cell it lacks, recording which. Takes the engine did not finish (`finishReason` other
than `eos`) and control takes are left out, and a voice or cell needs `--min-count` takes.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from qc import detectors as detector_lib
from qc import features as feature_lib
from qc import models, runtime, store
from qc.store import Layout

REFERENCES_SCHEMA = "vocello.qc.references/1"
REFERENCES_RE = re.compile(r"^references-v(\d+)\.json$")
ROLES = ("pitchA", "pitchB", "aesthetics")
DEFAULT_MIN_COUNT = 3


# --- the references files ------------------------------------------------------------

def _versions(layout: Layout) -> list[tuple[int, Path]]:
    return sorted((int(match.group(1)), path) for path in layout.config.glob("references-v*.json")
                  if (match := REFERENCES_RE.match(path.name)))


def latest(layout: Layout) -> Path | None:
    versions = _versions(layout)
    return versions[-1][1] if versions else None


def next_version(layout: Layout) -> int:
    versions = _versions(layout)
    return versions[-1][0] + 1 if versions else 1


def load(layout: Layout) -> dict[str, Any] | None:
    """The newest references document with its `file` name and `sha256`, or None (the runs then
    keep their own references)."""

    path = latest(layout)
    if path is None:
        return None
    document = store.read_json(path)
    if not isinstance(document, dict) or document.get("schema") != REFERENCES_SCHEMA:
        raise ValueError(f"{path.name} is not a {REFERENCES_SCHEMA} document")
    return dict(document, file=path.name, sha256=store.sha256_file(path))


# --- measuring ------------------------------------------------------------------------

def _aggregate(values: list[float]) -> dict[str, Any]:
    return {"median": round(float(np.median(values)), 4), "n": len(values)}


def compute(layout: Layout, takes: list[dict[str, Any]], *, min_count: int = DEFAULT_MIN_COUNT,
            echo: Callable[[str], None] = lambda line: print(line, file=sys.stderr, flush=True)) -> dict[str, Any]:
    """The references document of a pool (without its version), from the cached pitch and
    Audiobox results."""

    config = detector_lib.load_config(layout)
    params = config.get("params", {})
    registry = {model["id"]: model for model in models.load_registry(layout)}
    role_models: dict[str, tuple[dict[str, Any], str]] = {}
    for role in ROLES:
        model = registry.get(config["models"].get(role, ""))
        if model is None:
            continue
        try:
            role_models[role] = (model, runtime.runner_identity(layout, model))
        except runtime.RunnerError:
            continue
    voice_pitch: dict[str, list[float]] = {}
    cells: dict[str, dict[str, list[float]]] = {}
    found = {role: 0 for role in role_models}
    excluded = {"control": 0, "finishNotEOS": 0}
    digests = []
    for index, take in enumerate(takes, start=1):
        if index % 500 == 0:
            echo(f"qc references: {index}/{len(takes)} takes")
        if take.get("control"):
            excluded["control"] += 1
            continue
        if take.get("finishReason") not in (None, "eos"):
            excluded["finishNotEOS"] += 1
            continue
        results = {}
        for role, (model, identity) in role_models.items():
            result = store.read_result(layout, model["id"], take["audioSHA256"], store.take_variant(model, take),
                                       identity)
            if result is not None and "outputs" in result:
                results[role] = result
                found[role] += 1
        digests.append(take["audioSHA256"])
        median = feature_lib.take_pitch_median(results, params)
        if median is not None and take.get("mode") != "clone":
            voice_pitch.setdefault(feature_lib.voice_key(take), []).append(float(median))
        aesthetics = feature_lib.outputs(results, "aesthetics")
        if aesthetics is not None:
            bucket = cells.setdefault(str(take.get("cell")), {})
            for axis in feature_lib.AESTHETICS_AXES:
                if aesthetics.get(axis) is not None:
                    bucket.setdefault(axis, []).append(float(aesthetics[axis]))
    cell_aesthetics = {}
    for cell, axes in sorted(cells.items()):
        kept = {axis: _aggregate(values) for axis, values in sorted(axes.items()) if len(values) >= min_count}
        if kept:
            cell_aesthetics[cell] = kept
    return {
        "schema": REFERENCES_SCHEMA, "minCount": min_count, "detectorsVersion": config["version"],
        "pitchAgreeCents": params.get("pitchAgreeCents", 50),
        "pool": {"takes": len(takes), "measured": len(digests), "excluded": excluded,
                 "audioSHA256": store.sha256_text("\n".join(sorted(digests)))},
        "models": {role: {"id": model["id"], "runnerSHA256": identity, "results": found[role]}
                   for role, (model, identity) in role_models.items()},
        "voicePitch": {key: _aggregate(values) for key, values in sorted(voice_pitch.items())
                       if len(values) >= min_count},
        "cellAesthetics": cell_aesthetics,
    }


def write(layout: Layout, document: dict[str, Any]) -> Path:
    version = next_version(layout)
    path = layout.config / f"references-v{version}.json"
    stamped = dict(document, version=version,
                   createdAt=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    store.write_json_atomic(path, stamped)
    return path


def summary_lines(document: dict[str, Any]) -> list[str]:
    """Counts, then one line per voice (pitch median, takes) and per cell (PQ and CE medians)."""

    pool = document["pool"]
    lines = [f"qc references: {pool['measured']} of {pool['takes']} takes measured; "
             f"{len(document['voicePitch'])} voices, {len(document['cellAesthetics'])} cells"]
    for key, entry in document["voicePitch"].items():
        lines.append(f"  voice {key:<32} pitch {entry['median']:+7.2f} st  n={entry['n']}")
    for cell, axes in document["cellAesthetics"].items():
        values = "  ".join(f"{axis} {entry['median']:.2f} (n={entry['n']})" for axis, entry in axes.items())
        lines.append(f"  cell  {cell:<32} {values}")
    return lines


def command(layout: Layout, takes_paths: list[str], *, min_count: int = DEFAULT_MIN_COUNT, dry_run: bool = False,
            echo: Callable[[str], None] = lambda line: print(line, file=sys.stderr, flush=True)
            ) -> tuple[dict[str, Any], Path | None]:
    takes = store.merge_takes(store.load_takes(path) for path in takes_paths)
    for take in takes:
        if not take.get("audioSHA256"):
            take["audioSHA256"] = store.audio_sha256(take["audio"])
    document = compute(layout, takes, min_count=min_count, echo=echo)
    return document, (None if dry_run else write(layout, document))
