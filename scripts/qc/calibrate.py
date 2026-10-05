"""Calibrate the detectors on human controls; evaluate them on the controls and the confirmations.

No label is needed. `qc.py calibrate --controls <runs...>` reads `controls`-lane runs
(`build/private/qc/runs/<id>/features.json`: human read speech, every take a control;
`takes.json` gives each recording's speaker family `human:<source>:<speaker>`) and writes
`config/qc/thresholds-v<N>.json` with `method: "human-reference"`. Per detector and language with
at least `--min-controls` (150) human recordings that measure one of its features:
- the recordings split by speaker, a fixed hash of the family (`half_for_family`), into a
  calibration half and a check half, so no speaker sits on both sides;
- each feature measured on at least `MIN_FEATURE_VALUES` (30) calibration recordings gets a
  quantile table of its oriented values (`qc.detectors.QUANTILE_GRID`); a feature no recording
  measures (the engine's finish reason) is `unreferenced` and ignored by the score;
- a take's score is its largest human percentile among those features (`qc.detectors.human_rank`);
- the cut is the lowest score that at most 1 - `--quantile` (1%) of the calibration half reach,
  or 1.0 (above every calibration recording on some feature) when no lower score does;
- the check half, which shaped neither the tables nor the cut, gives the human false-alarm rate
  at that cut with Clopper-Pearson bounds.

The advisory loudness detector and the clone detectors (their features need a clone's reference
clip) stay report-only with their provisional rules, and so does every language without enough
controls. `--runs` adds, per detector and language, the share of generated takes the reference
would flag. The file holds aggregates only: quantile tables, cuts, counts and digests, never a
take id, path or text.

`evaluate` (`qc.py eval` on a human-reference file) re-measures the check half on the same
controls and scores the maintainer's chat confirmations (`qc.confirm`). A detector warns in a
language when its human false-alarm rate is at most `levels.humanReference.warnFalseAlarmRate`
(2%) and the rate's upper bound at most `warnFalseAlarmUpper` (6%); it fails there when, besides,
at least `failMinConfirmed` (17) confirmed takes it flagged (any language) give a precision lower
bound of at least `levels.fail.precisionLower` (0.8). The label set is the confirmations plus the
controls' digest, so new confirmations may be evaluated again on the same thresholds version (the
evaluation replaces `eval-v<N>.json`); the same label set needs the calibration's
`--reuse-reason`.
"""

from __future__ import annotations

import bisect
import json
import math
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from qc import detectors as detector_lib
from qc import fit, label, store
from qc import norms as norms_lib
from qc.confirm import CONFIRM_KIND
from qc.controls import CONTROLS_LANE
from qc.store import Layout

HUMAN_REFERENCE = detector_lib.HUMAN_REFERENCE
SPLIT_SALT = "vocello.qc.calibrate/1"
CALIBRATION_SHARE = 0.5
CALIBRATION, CHECK = "calibration", "check"
DEFAULT_QUANTILE = 0.99
DEFAULT_MIN_CONTROLS = 150
# A feature's quantile table needs at least this many calibration recordings in its language.
MIN_FEATURE_VALUES = 30


class CalibrationError(fit.FitError):
    """The controls cannot support a calibration, or its evaluation."""


def half_for_family(family: str) -> str:
    """`calibration` or `check`: a speaker family keeps its half in every calibration."""

    bucket = int(store.sha256_text(f"{SPLIT_SALT}:{family}")[:8], 16) / 2**32
    return CALIBRATION if bucket < CALIBRATION_SHARE else CHECK


def _value(features: dict[str, Any], name: str) -> float | None:
    value = (features.get(name) or {}).get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def _significant(value: float) -> float:
    return float(f"{value:.6g}") + 0.0  # six significant digits; + 0.0 turns -0.0 into 0.0


def quantile_table(values: Iterable[float]) -> list[float]:
    """The values' percentiles on `QUANTILE_GRID` (linear interpolation), to six significant digits."""

    table = np.percentile(np.asarray(list(values), dtype=float), detector_lib.QUANTILE_GRID)
    rounded = [_significant(float(value)) for value in table]
    for index in range(1, len(rounded)):
        rounded[index] = max(rounded[index], rounded[index - 1])
    return rounded


def choose_cut(scores: list[float], quantile: float) -> float:
    """The lowest score that at most 1 - `quantile` of `scores` reach (score >= cut flags), or 1.0
    when even the highest score is reached by more (ties at the top)."""

    ordered = sorted(scores)
    allowed = (1.0 - quantile) * len(ordered)
    for value in sorted(set(ordered)):
        if len(ordered) - bisect.bisect_left(ordered, value) <= allowed + 1e-9:
            return float(value)
    return 1.0


def _scores(detector: dict[str, Any], rows: list[dict[str, Any]], reference: dict[str, Any]) -> list[float]:
    scores = []
    for row in rows:
        best = detector_lib.human_reference_best(detector, row["features"], reference)
        if best is not None:
            scores.append(best[0])
    return scores


def _rate(scores: list[float], cut: float) -> dict[str, Any]:
    return fit.weighted_rate([score >= cut for score in scores], [1.0] * len(scores))


# --- inputs -------------------------------------------------------------------------

def _run_directory(layout: Layout, run_id: str) -> Path:
    directory = layout.runs / run_id
    if (not run_id or Path(run_id).name != run_id or not (directory / "features.json").is_file()
            or not (directory / "takes.json").is_file()):
        raise CalibrationError(f"run {run_id} has no features.json and takes.json under build/private/qc/runs")
    return directory


def _read_runs(layout: Layout, run_ids: list[str], what: str
               ) -> tuple[list[tuple[str, dict[str, Any], dict[str, Any]]], dict[str, Any], str | None]:
    """Each run's features document and takes by token, the runs' model identities and their one
    scoring identity; runs that disagree on either are refused."""

    documents, identities, scorings = [], {}, set()
    for run_id in run_ids:
        directory = _run_directory(layout, run_id)
        document = store.read_json(directory / "features.json")
        takes = {take["token"]: take for take in store.read_json(directory / "takes.json").get("takes", [])}
        documents.append((run_id, document, takes))
        scorings.add(document.get("scoringSHA256"))
        if len(scorings) > 1:
            raise CalibrationError(f"the {what} runs were scored with different {fit.SCORING_CHANGED}; "
                                   "name runs of one scoring identity")
        for role, identity in (document.get("models") or {}).items():
            if identity.get("available"):
                previous = identities.get(role)
                if previous and previous["runnerSHA256"] != identity["runnerSHA256"]:
                    raise CalibrationError(f"the {what} runs disagree on the {role} model identity; "
                                           "name runs of one identity")
                identities[role] = {"id": identity["id"], "runnerSHA256": identity["runnerSHA256"]}
    return documents, identities, next(iter(scorings), None)


def load_controls(layout: Layout, run_ids: Iterable[str]) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    """The human recordings of `controls`-lane runs: token, language, speaker family, its source
    corpus and split half, and the features; then the model identities and the scoring identity.
    A run of another lane, or a take not marked a human control, is refused."""

    run_ids = list(dict.fromkeys(run_ids))
    if not run_ids:
        raise CalibrationError("name at least one controls run (--controls)")
    documents, identities, scoring = _read_runs(layout, run_ids, "controls")
    rows: dict[str, dict[str, Any]] = {}
    for run_id, document, takes in documents:
        if document.get("lane") != CONTROLS_LANE:
            raise CalibrationError(f"run {run_id} is a {document.get('lane')} run, not a {CONTROLS_LANE} run "
                                   "of human recordings")
        for row in document.get("takes", []):
            take = takes.get(row["token"]) or {}
            if not take.get("control") or take.get("mode") != "human":
                raise CalibrationError(f"run {run_id} holds a take that is not a human control; only human "
                                       "recordings calibrate")
            family = str(take.get("family") or take.get("takeID") or row["token"])
            parts = family.split(":")
            rows[row["token"]] = {
                "token": row["token"], "language": row.get("language") or take.get("language"), "family": family,
                "source": parts[1] if len(parts) >= 3 and parts[0] == "human" else "unknown",
                "half": half_for_family(family), "features": row.get("features") or {},
            }
    return list(rows.values()), identities, scoring


def load_generated(layout: Layout, run_ids: Iterable[str], identities: dict[str, Any],
                   scoring_sha: str) -> list[dict[str, Any]]:
    """The generated takes of `--runs` (their control takes aside), scored with the controls'
    scoring identity and model identities."""

    run_ids = list(dict.fromkeys(run_ids))
    documents, generated_identities, scoring = _read_runs(layout, run_ids, "generated")
    if scoring != scoring_sha:
        raise CalibrationError(f"the generated runs were scored with other {fit.SCORING_CHANGED} than the "
                               "controls; rerun qc.py run on them")
    for role, identity in generated_identities.items():
        expected = identities.get(role)
        if expected and expected["runnerSHA256"] != identity["runnerSHA256"]:
            raise CalibrationError(f"the generated runs come from another {role} model identity than the controls")
    rows: dict[str, dict[str, Any]] = {}
    for run_id, document, takes in documents:
        if document.get("lane") == CONTROLS_LANE:
            raise CalibrationError(f"run {run_id} is a {CONTROLS_LANE} run; name it with --controls")
        for row in document.get("takes", []):
            if (takes.get(row["token"]) or {}).get("control"):
                continue
            rows[row["token"]] = {"token": row["token"], "language": row.get("language"),
                                  "features": row.get("features") or {}}
    return list(rows.values())


def controls_digest(rows: list[dict[str, Any]], scoring_sha: str | None) -> str:
    """The identity of the human evidence: the scoring identity and every control's token."""

    return store.sha256_text(store.canonical_json({"scoringSHA256": scoring_sha,
                                                   "takes": sorted(row["token"] for row in rows)}))


def _controls_summary(rows: list[dict[str, Any]], run_ids: list[str], scoring_sha: str | None) -> dict[str, Any]:
    languages: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = languages.setdefault(row["language"] or "unknown", {
            "takes": 0, "speakers": set(), CALIBRATION: 0, CHECK: 0, "sources": Counter()})
        bucket["takes"] += 1
        bucket["speakers"].add(row["family"])
        bucket[row["half"]] += 1
        bucket["sources"][row["source"]] += 1
    return {
        "runs": sorted(set(run_ids)), "takes": len(rows), "digest": controls_digest(rows, scoring_sha),
        "languages": {language: {"takes": value["takes"], "speakers": len(value["speakers"]),
                                 CALIBRATION: value[CALIBRATION], CHECK: value[CHECK],
                                 "sources": dict(sorted(value["sources"].items()))}
                      for language, value in sorted(languages.items())},
    }


# --- the calibration ------------------------------------------------------------------

def _language_reference(detector: dict[str, Any], rows: list[dict[str, Any]], generated: list[dict[str, Any]],
                        measured: set[str], quantile: float) -> dict[str, Any]:
    calibration = [row for row in rows if row["half"] == CALIBRATION]
    check = [row for row in rows if row["half"] == CHECK]
    tables: dict[str, list[float]] = {}
    counts: dict[str, int] = {}
    sparse = []
    for item in detector["features"]:
        name = item["name"]
        if name not in measured:
            continue
        values = [detector_lib.oriented(value, item["direction"]) for row in calibration
                  if (value := _value(row["features"], name)) is not None]
        counts[name] = len(values)
        if len(values) < MIN_FEATURE_VALUES:
            sparse.append(name)
            continue
        tables[name] = quantile_table(values)
    if not tables:
        return {"reason": f"no feature measured on {MIN_FEATURE_VALUES} calibration controls"}
    reference: dict[str, Any] = {"features": tables, "measured": counts}
    calibration_scores = _scores(detector, calibration, reference)
    cut = choose_cut(calibration_scores, quantile)
    reference["cut"] = cut
    reference[CALIBRATION] = dict(_rate(calibration_scores, cut),
                                  speakers=len({row["family"] for row in calibration}))
    reference[CHECK] = dict(_rate(_scores(detector, check, reference), cut),
                            speakers=len({row["family"] for row in check}))
    if sparse:
        reference["unreferenced"] = sparse
    if generated:
        reference["generated"] = _rate(_scores(detector, generated, reference), cut)
    return reference


def calibrate_detector(detector: dict[str, Any], controls: list[dict[str, Any]], generated: list[dict[str, Any]],
                       *, quantile: float, min_controls: int, languages: Iterable[str]) -> dict[str, Any]:
    """One detector's human-reference entry: per language its quantile tables, cut and the
    calibration, check and generated rates; report-only where the controls cannot reference it."""

    names = [item["name"] for item in detector["features"]]
    entry: dict[str, Any] = {"class": detector.get("class"), "method": HUMAN_REFERENCE, "features": names,
                             "languages": {}}
    if detector.get("advisory") or detector.get("class") is None:
        entry.update(reportOnly=True, advisory=True, reason="advisory: provisional rule only")
        return entry
    if detector.get("gateLanes"):
        entry.update(reportOnly=True, reason=(
            f"clone-only (it gates in {', '.join(detector['gateLanes'])}): its features are measured against "
            "a clone's reference clip, which human recordings do not have; it keeps its provisional rule, "
            "report-only"))
        return entry
    measured = {name for row in controls for name in names if _value(row["features"], name) is not None}
    entry["unreferenced"] = [name for name in names if name not in measured]
    references: dict[str, Any] = {}
    report_only: dict[str, str] = {}
    for language in languages:
        humans = [row for row in controls if row["language"] == language]
        rows = [row for row in humans if any(_value(row["features"], name) is not None for name in measured)]
        if not humans:
            report_only[language] = "no human controls"
        elif len(rows) < min_controls:
            report_only[language] = f"{len(rows)} human controls measure its features, under {min_controls}"
        else:
            reference = _language_reference(detector, rows, [row for row in generated if row["language"] == language],
                                             measured, quantile)
            if "reason" in reference:
                report_only[language] = reference["reason"]
            else:
                references[language] = reference
    entry.update(languages=references, reportOnlyLanguages=report_only, reportOnly=not references)
    if not references:
        entry["reason"] = "no control measures its features" if not measured else \
            "no language has enough human controls"
    return entry


def calibrate(layout: Layout, *, controls: Iterable[str], runs: Iterable[str] | None = None,
              quantile: float = DEFAULT_QUANTILE, min_controls: int = DEFAULT_MIN_CONTROLS,
              reuse_reason: str | None = None) -> tuple[Path, dict[str, Any]]:
    """Write the next thresholds file, calibrated on the human controls; return it and its document.
    `reuse_reason` declares why its evaluation may score a label set an earlier one scored."""

    if not isinstance(quantile, (int, float)) or isinstance(quantile, bool) or not 0.5 <= quantile < 1.0:
        raise CalibrationError("--quantile must be at least 0.5 and below 1")
    if not isinstance(min_controls, int) or isinstance(min_controls, bool) or min_controls < 2:
        raise CalibrationError("--min-controls must be an integer of at least 2")
    if reuse_reason is not None and not reuse_reason.strip():
        raise CalibrationError("a reuse needs its reason")
    config = detector_lib.load_config(layout)
    scoring = detector_lib.scoring_identity(layout)
    control_runs = list(dict.fromkeys(controls))
    rows, identities, run_scoring = load_controls(layout, control_runs)
    if not rows:
        raise CalibrationError("the controls runs hold no human recording")
    if run_scoring != scoring["sha256"]:
        raise CalibrationError(f"the controls were scored with other {fit.SCORING_CHANGED} than the current; "
                               "rerun qc.py run --lane controls on them (the model results come from the cache)")
    generated_runs = list(dict.fromkeys(runs or []))
    generated = load_generated(layout, generated_runs, identities, scoring["sha256"]) if generated_runs else []
    languages = sorted(set(store.LANGUAGES) | {row["language"] for row in rows if row["language"]})
    detectors = {detector["id"]: calibrate_detector(detector, rows, generated, quantile=float(quantile),
                                                    min_controls=min_controls, languages=languages)
                 for detector in config["detectors"]}
    version = fit.next_version(layout)
    document: dict[str, Any] = {
        "schema": fit.THRESHOLDS_SCHEMA, "method": HUMAN_REFERENCE, "version": version, "createdAt": fit.utc_now(),
        "detectorsVersion": config["version"], "detectorsSHA256": detector_lib.config_digest(layout),
        "scoringSHA256": scoring["sha256"], "scoring": {"files": scoring["files"], "norms": scoring["norms"]},
        "models": identities, "quantile": float(quantile), "minControls": min_controls,
        "minFeatureValues": MIN_FEATURE_VALUES,
        "split": {"salt": SPLIT_SALT, "calibrationShare": CALIBRATION_SHARE, "groups": "speaker family"},
        "quantileGrid": list(detector_lib.QUANTILE_GRID),
        "controls": _controls_summary(rows, control_runs, run_scoring), "detectors": detectors,
    }
    if generated_runs:
        document["generated"] = {"runs": sorted(generated_runs), "takes": len(generated)}
    if reuse_reason is not None:
        document["reuse"] = {"reason": reuse_reason.strip()}
    path = layout.config / f"thresholds-v{version}.json"
    write_compact_json(path, document)
    return path, document


def _compact(value: Any, indent: int = 0) -> str:
    """Indented JSON whose lists of numbers stay on one line (the quantile tables)."""

    pad = " " * indent
    if isinstance(value, dict) and value:
        items = (f"{pad} {json.dumps(key, ensure_ascii=False)}: {_compact(value[key], indent + 1)}"
                 for key in sorted(value))
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(value, list) and any(isinstance(item, (dict, list)) for item in value):
        return "[\n" + ",\n".join(f"{pad} {_compact(item, indent + 1)}" for item in value) + "\n" + pad + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ": "))


def write_compact_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_compact(document) + "\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def summary_lines(document: dict[str, Any]) -> list[str]:
    controls = document["controls"]
    lines = [f"qc calibrate: {controls['takes']} human recordings in {len(controls['languages'])} languages, "
             f"quantile {document['quantile']}"]
    for detector_id, entry in document["detectors"].items():
        if entry.get("reportOnly"):
            lines.append(f"  {detector_id:<18} report-only: {entry.get('reason')}")
            continue
        for language, reference in sorted(entry["languages"].items()):
            check = reference[CHECK]
            rate = "-" if check["rate"] is None else f"{check['rate']:.3f} [{check['lower']:.3f}, {check['upper']:.3f}]"
            generated = reference.get("generated")
            lines.append(f"  {detector_id:<18} {language:<10} cut {reference['cut']:.4f}  human false alarms "
                         f"{rate} n={check['n']}"
                         + (f"  generated flagged {generated['rate']:.3f} n={generated['n']}"
                            if generated and generated["n"] else ""))
        skipped = entry.get("reportOnlyLanguages") or {}
        if skipped:
            lines.append(f"  {detector_id:<18} report-only in {', '.join(sorted(skipped))}")
    return lines


# --- the evaluation ------------------------------------------------------------------

def confirm_batches(layout: Layout, batches: Iterable[str] | None = None) -> list[str]:
    """The chat-confirmation batches (`kind: confirm`); a named batch of another kind is refused."""

    if batches:
        names = list(batches)
        for name in names:
            kind = label.load_batch(layout, name).get("kind")
            if kind != CONFIRM_KIND:
                raise CalibrationError(f"batch {name} is a {kind} batch; a human-reference evaluation reads "
                                       "confirm batches")
        return names
    return [name for name in label.batch_names(layout) if label.load_batch(layout, name).get("kind") == CONFIRM_KIND]


def label_set_digest(confirmations: list[dict[str, Any]], controls: str) -> str:
    return store.sha256_text(store.canonical_json({"confirmations": fit.label_set_digest(confirmations),
                                                   "controls": controls}))


def evaluate(layout: Layout, thresholds: Path, document: dict[str, Any], output: Path, *,
             batches: Iterable[str] | None = None, runs: Iterable[str] | None = None,
             rater: str | None = None) -> Path:
    """Evaluate a committed human-reference thresholds file (`fit.evaluate` hands it over) and
    write `eval-v<N>.json`: per detector and language, the human false alarms re-measured on the
    check half, the confirmations' pooled precision and the level."""

    config = detector_lib.load_config(layout)
    rules = config["levels"]
    human = rules.get("humanReference")
    if not isinstance(human, dict):
        raise CalibrationError("config/qc/detectors.json has no levels.humanReference")
    if document.get("schema") != fit.THRESHOLDS_SCHEMA or not isinstance(document.get("controls"), dict):
        raise CalibrationError(f"{thresholds.name} is not a human-reference calibration of this qc.py")
    if document.get("scoringSHA256") != detector_lib.scoring_identity(layout)["sha256"]:
        raise CalibrationError(f"{thresholds.name} was calibrated with other {fit.SCORING_CHANGED} than the "
                               "current; recalibrate")
    recorded = document["controls"]
    try:
        rows, identities, scoring = load_controls(layout, recorded.get("runs") or [])
    except CalibrationError as error:
        raise CalibrationError(f"the controls {thresholds.name} was calibrated on cannot be read: {error}") from None
    if scoring != document["scoringSHA256"] or controls_digest(rows, scoring) != recorded.get("digest"):
        raise CalibrationError(f"the controls runs differ from those {thresholds.name} was calibrated on; recalibrate")
    fitted_models = document.get("models") or {}
    if any(identities.get(role) != fitted_models.get(role) for role in set(identities) | set(fitted_models)):
        raise CalibrationError(f"the controls runs come from other model identities than {thresholds.name}")
    rater = rater or label.default_rater(layout)
    names = confirm_batches(layout, batches)
    confirmations = fit.label_rows(layout, names, rater) if names else []
    features: dict[str, dict[str, Any]] = {}
    if confirmations:
        features, run_identities, run_scoring = fit.feature_rows(layout, runs)
        if features and run_scoring != document["scoringSHA256"]:
            raise CalibrationError(f"the run features were scored with other {fit.SCORING_CHANGED} than "
                                   f"{thresholds.name}; name runs of its scoring identity with --runs")
        for role, expected in fitted_models.items():
            current = run_identities.get(role)
            if current and current["runnerSHA256"] != expected.get("runnerSHA256"):
                raise CalibrationError(f"the run features come from another {role} model identity than "
                                       f"{thresholds.name}")
    scored = [row for row in confirmations if row["token"] in features]
    digest = label_set_digest(scored, recorded["digest"])
    earlier = fit._evaluated_before(layout, digest)
    reuse = (document.get("reuse") or {}).get("reason")
    if earlier and not (isinstance(reuse, str) and reuse.strip()):
        raise CalibrationError(f"{earlier} already scored this label set (these confirmations on these controls); "
                               "confirm new takes, or recalibrate with --reuse-reason to declare why it is "
                               "scored again")
    pool_norms = norms_lib.load(layout)
    results: dict[str, Any] = {}
    flagged_by: dict[str, set[str]] = {}  # each confirmed take's flagging detectors, for the agreement report
    for detector in config["detectors"]:
        entry = (document.get("detectors") or {}).get(detector["id"]) or {}
        if detector.get("advisory") or detector.get("class") is None:
            results[detector["id"]] = {"class": None, "advisory": True, "reportOnly": True, "languages": {}}
            continue
        if entry.get("reportOnly", True) or entry.get("method") != HUMAN_REFERENCE:
            results[detector["id"]] = {"class": detector["class"], "reportOnly": True, "reason": entry.get("reason"),
                                       "languages": {}}
            continue
        languages: dict[str, dict[str, Any]] = {}
        for language, reference in sorted(entry["languages"].items()):
            check = [row for row in rows if row["language"] == language and row["half"] == CHECK]
            measured = _rate(_scores(detector, check, reference), reference["cut"])
            stored = reference.get(CHECK) or {}
            if (measured["n"], measured["rate"]) != (stored.get("n"), stored.get("rate")):
                raise CalibrationError(f"the controls no longer reproduce the check half of {detector['id']} in "
                                       f"{language} recorded in {thresholds.name}; recalibrate")
            languages[language] = {"humanFalseAlarms": measured}
        hits, uncertain = [], 0
        for row in scored:
            outcome = detector_lib.score(detector, features[row["token"]]["features"], row["language"], entry, {},
                                         norms=pool_norms)
            if outcome["scope"] != HUMAN_REFERENCE or outcome["score"] is None or outcome["score"] < outcome["cut"]:
                continue
            flagged_by.setdefault(row["token"], set()).add(detector["id"])
            if row["label"].get("verdict") == "uncertain":
                uncertain += 1
                continue
            hits.append(row["label"].get("verdict") == "objectionable")
        precision = fit.weighted_rate(hits, [1.0] * len(hits))
        fail_ready = (len(hits) >= human["failMinConfirmed"] and precision["lower"] is not None
                      and precision["lower"] >= rules["fail"]["precisionLower"])
        for value in languages.values():
            alarms = value["humanFalseAlarms"]
            warn = (alarms["n"] > 0 and alarms["rate"] is not None and alarms["rate"] <= human["warnFalseAlarmRate"]
                    and alarms["upper"] <= human["warnFalseAlarmUpper"])
            value["level"] = "fail" if warn and fail_ready else "warn" if warn else "report-only"
        results[detector["id"]] = {
            "class": detector["class"], "method": HUMAN_REFERENCE, "reportOnly": False,
            "confirmations": {"flagged": len(hits) + uncertain, "uncertain": uncertain, "precision": precision,
                              "failReady": fail_ready},
            "languages": languages,
        }
    # Precision pooled over detectors by how many of them flagged the take: does agreement predict
    # an unusable take better than a lone flag?
    agreement: dict[str, Any] = {}
    for bucket, minimum, maximum in (("1", 1, 1), ("2+", 2, None)):
        bucket_hits = [row["label"].get("verdict") == "objectionable" for row in scored
                       if row["label"].get("verdict") != "uncertain"
                       and len(flagged_by.get(row["token"], ())) >= minimum
                       and (maximum is None or len(flagged_by.get(row["token"], ())) <= maximum)]
        agreement[bucket] = fit.weighted_rate(bucket_hits, [1.0] * len(bucket_hits))
    previous = store.read_json(output) if output.is_file() else None
    evaluation: dict[str, Any] = {
        "schema": fit.EVAL_SCHEMA, "version": document["version"], "createdAt": fit.utc_now(),
        "thresholds": thresholds.name, "thresholdsSHA256": store.sha256_file(thresholds),
        "commit": fit._head(layout.root), "rater": rater, "scoringSHA256": document["scoringSHA256"],
        "method": {"name": HUMAN_REFERENCE, "quantile": document.get("quantile"),
                   "salt": (document.get("split") or {}).get("salt"), "groups": "speaker family"},
        "labelSetDigest": digest,
        "labelSet": {"batches": sorted({row["batch"] for row in scored}), "takes": len(scored),
                     "confirmations": len(confirmations),
                     "controls": {"runs": recorded.get("runs"), "takes": len(rows), "digest": recorded["digest"]}},
        "levels": {"humanReference": human, "failPrecisionLower": rules["fail"]["precisionLower"]},
        "norms": (pool_norms or {}).get("file"), "detectors": results,
        "agreement": {"detectorsFlagging": agreement},
    }
    if isinstance(previous, dict):
        evaluation["replaces"] = {"labelSetDigest": previous.get("labelSetDigest"),
                                  "createdAt": previous.get("createdAt")}
    if earlier:
        evaluation["reuse"] = {"reason": reuse.strip(), "earlier": earlier}
    store.write_json_atomic(output, evaluation)
    store.append_jsonl(layout.private / fit.EVAL_LEDGER, {
        "version": document["version"], "labelSetDigest": digest, "controlsDigest": recorded["digest"],
        "tokens": sorted(row["token"] for row in scored), "evaluatedAt": evaluation["createdAt"]})
    return output
