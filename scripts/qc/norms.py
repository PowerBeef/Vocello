"""Per-language pause, pace and ending norms from the pool: `qc.py norms`.

A fixed "natural pause" of 0.2-0.3 s, or one abrupt-end cut, is tuned to French and English
rhythm. `qc.py norms --takes <runs...>` measures every take of a pool from its audio and its
cached results (the aligner's words and the G2P phones; nothing runs a model), per language:

- `pause.gap_seconds`: every within-sentence pause of at least 100 ms (`qc.features.pause_gaps`,
  the measure `pause.anomalous` takes the longest of). The pause rule reads its p99: a take has
  several pauses, so the pool's own defective pauses barely move it, unlike the p99 of each
  take's longest pause, which a defect rate above 1% pushes past the defects themselves;
- `pause.longest_gap_seconds` (each take's longest, from the audio), `pause.word_gap_seconds`
  (every silence between two aligned words) and `pause.unpunctuated_gap_seconds` (each take's
  longest silence between two aligned words with no punctuation between them in the script):
  descriptive;
- `rate.phones_per_second` and `rate.syllables_per_second`: the articulation rate, over the speech
  span minus its pauses of 100 ms or more;
- `end.tail_seconds`, `end.decay_db_per_ms`, `end.drop_db_60ms` and `end.file_tail_seconds` (the
  file after the last speech frame): how the take ends.

It writes `config/qc/norms-v<N>.json`: per language and feature, `n`, the mean and the
percentiles of `qc.detectors.NORM_PERCENTILES`, plus counts and one digest of the pool's audio
digests. It never holds a take id, path or text. The provisional rules read the newest file
(`qc.detectors.condition_threshold`); a fit on the labels overrides them.

Takes the engine did not finish (`finishReason` other than `eos`) are left out, and a language
gets a feature only from at least `--min-count` values.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from qc import detectors as detector_lib
from qc import features as feature_lib
from qc import models, runtime, store
from qc.store import Layout

NORMS_SCHEMA = "vocello.qc.norms/1"
NORMS_RE = re.compile(r"^norms-v(\d+)\.json$")
NORM_FEATURES = (
    "pause.gap_seconds", "pause.longest_gap_seconds", "pause.word_gap_seconds", "pause.unpunctuated_gap_seconds",
    "rate.phones_per_second", "rate.syllables_per_second", "end.tail_seconds", "end.decay_db_per_ms",
    "end.drop_db_60ms", "end.file_tail_seconds",
)
# The shortest non-speech stretch that counts as a pause: below it, a gap is a consonant closure.
PAUSE_MIN_SECONDS = feature_lib.ARTICULATION_PAUSE_SECONDS
ROLES = ("align", "g2p")
DEFAULT_MIN_COUNT = 100


# --- the norms files --------------------------------------------------------------

def _versions(layout: Layout) -> list[tuple[int, Path]]:
    return sorted((int(match.group(1)), path) for path in layout.config.glob("norms-v*.json")
                  if (match := NORMS_RE.match(path.name)))


def latest(layout: Layout) -> Path | None:
    versions = _versions(layout)
    return versions[-1][1] if versions else None


def next_version(layout: Layout) -> int:
    versions = _versions(layout)
    return versions[-1][0] + 1 if versions else 1


def load(layout: Layout) -> dict[str, Any] | None:
    """The newest norms document, or None (the provisional rules then keep their fixed values)."""

    path = latest(layout)
    if path is None:
        return None
    document = store.read_json(path)
    if not isinstance(document, dict) or document.get("schema") != NORMS_SCHEMA:
        raise ValueError(f"{path.name} is not a {NORMS_SCHEMA} document")
    return dict(document, file=path.name)


# --- measuring ------------------------------------------------------------------

def take_measures(take: dict[str, Any], results: dict[str, Any], *, layout: Layout, model_ids: dict[str, str],
                  load_audio: Callable[[str], tuple[np.ndarray, int]] = feature_lib.read_wav
                  ) -> dict[str, list[float]] | None:
    """One take's values for each norm feature (a list, since a take has several pauses), or None
    when its audio cannot be read."""

    try:
        samples, rate = load_audio(take["audio"])
    except (OSError, ValueError):
        return None
    profile = feature_lib.frame_profile(samples, rate)
    aligned = feature_lib.outputs(results, "align")
    pauses = feature_lib.pause_gaps(samples, rate, profile=profile, minimum=PAUSE_MIN_SECONDS)
    found: dict[str, Any] = {}
    found.update(feature_lib.pause_features(samples, rate, aligned, profile=profile, text=take.get("text"),
                                            language=take.get("language")))
    found.update(feature_lib.end_features(samples, rate, profile=profile))
    expected = feature_lib.expected_phones(take, results, layout, model_ids)[0]
    found.update(feature_lib.rate_features(expected, feature_lib.speech_span(samples, rate, profile=profile), pauses))
    measures = {name: [found[name]["value"]] for name in NORM_FEATURES
                if name in found and found[name].get("value") is not None}
    for name, values in (("pause.gap_seconds", pauses), ("pause.word_gap_seconds", feature_lib.word_gaps(aligned))):
        if values:
            measures[name] = values
    return measures


def summarize(values: Iterable[float]) -> dict[str, Any]:
    data = np.asarray([float(value) for value in values], dtype=np.float64)
    summary: dict[str, Any] = {"n": int(data.size), "mean": round(float(data.mean()), 4)}
    for key in detector_lib.NORM_PERCENTILES:
        summary[key] = round(float(np.percentile(data, int(key[1:]))), 4)
    return summary


def compute(layout: Layout, takes: list[dict[str, Any]], *, min_count: int = DEFAULT_MIN_COUNT,
            load_audio: Callable[[str], tuple[np.ndarray, int]] = feature_lib.read_wav,
            echo: Callable[[str], None] = lambda line: print(line, file=sys.stderr, flush=True)) -> dict[str, Any]:
    """The norms document of a pool (without its version), from the cached align and G2P results."""

    config = detector_lib.load_config(layout)
    model_ids = dict(config["models"])
    registry = {model["id"]: model for model in models.load_registry(layout)}
    role_models: dict[str, tuple[dict[str, Any], str]] = {}
    for role in ROLES:
        model = registry.get(model_ids.get(role, ""))
        if model is None:
            continue
        try:
            role_models[role] = (model, runtime.runner_identity(layout, model))
        except runtime.RunnerError:
            continue
    values: dict[str, dict[str, list[float]]] = {}
    counts: dict[str, int] = {}
    found = {role: 0 for role in role_models}
    excluded = {"control": 0, "finishNotEOS": 0, "audioUnreadable": 0}
    digests = []
    for index, take in enumerate(takes, start=1):
        if index % 500 == 0:
            echo(f"qc norms: {index}/{len(takes)} takes")
        if take.get("control"):  # human controls and negative controls are not the pool
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
        measures = take_measures(take, results, layout=layout, model_ids=model_ids, load_audio=load_audio)
        if measures is None:
            excluded["audioUnreadable"] += 1
            continue
        for role in results:
            found[role] += 1
        language = take.get("language") or "unknown"
        counts[language] = counts.get(language, 0) + 1
        digests.append(take["audioSHA256"])
        bucket = values.setdefault(language, {})
        for name, items in measures.items():
            bucket.setdefault(name, []).extend(items)
    languages = {}
    for language, by_name in sorted(values.items()):
        kept = {name: summarize(items) for name, items in sorted(by_name.items()) if len(items) >= min_count}
        if kept:
            languages[language] = kept
    return {
        "schema": NORMS_SCHEMA, "percentiles": list(detector_lib.NORM_PERCENTILES), "minCount": min_count,
        "detectorsVersion": config["version"],
        "pool": {"takes": len(takes), "measured": len(digests), "excluded": excluded,
                 "audioSHA256": store.sha256_text("\n".join(sorted(digests)))},
        "models": {role: {"id": model["id"], "runnerSHA256": identity, "results": found[role]}
                   for role, (model, identity) in role_models.items()},
        "counts": dict(sorted(counts.items())), "languages": languages,
    }


def write(layout: Layout, document: dict[str, Any]) -> Path:
    version = next_version(layout)
    path = layout.config / f"norms-v{version}.json"
    stamped = dict(document, version=version,
                   createdAt=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    store.write_json_atomic(path, stamped)
    return path


def summary_lines(document: dict[str, Any]) -> list[str]:
    """One line per language: takes, pause (every pause) p50/p99, rate p1/p50/p99 and tail p1/p50."""

    def stats(language: str, name: str, keys: tuple[str, ...]) -> str:
        found = document["languages"].get(language, {}).get(name, {})
        return "/".join("-" if found.get(key) is None else f"{found[key]:.3g}" for key in keys)

    lines = [f"{'language':<11} {'takes':>5}  {'pause p50/p99 s':>16}  {'phones/s p1/p50/p99':>20}  "
             f"{'tail p1/p50 s':>14}"]
    for language, count in document["counts"].items():
        lines.append(f"{language:<11} {count:>5}  "
                     f"{stats(language, 'pause.gap_seconds', ('p50', 'p99')):>16}  "
                     f"{stats(language, 'rate.phones_per_second', ('p1', 'p50', 'p99')):>20}  "
                     f"{stats(language, 'end.tail_seconds', ('p1', 'p50')):>14}")
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
