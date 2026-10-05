"""Lane runs: score a takes manifest, gate on its flags, queue takes worth hearing.

`run` scores the takes with each detector model, one model at a time and from
the cache when it can. After every role (the G2P role reads the scripts), a
second G2P pass reads the ASR transcripts not yet in the G2P cache, for the
sound-level transcript features. Then it computes the features and detector
scores (the provisional rules read the newest `config/qc/norms-v<N>.json`), and
writes these files under `build/private/qc/runs/<run-id>/`:
- `takes.json`: the manifest;
- `features.json`: the features, with the model identities and the scoring
  identity (`qc.detectors.scoring_identity`: the detectors configuration, the
  feature and detector code and the newest norms file);
- `flags.json`: the flags, each with its level and its evidence
  `{feature, value, start, end}`.

The level comes from the evaluation of the newest thresholds file (calibrated
on human controls or fitted on labels), applied only when the thresholds were
made on the same model identities and scoring identity as the run. Otherwise,
and before an evaluation exists, every flag is report-only and `flags.json`
(and `gate`) state why. Under human-reference thresholds, a flag of a language
the controls gave no reference (the provisional rule) stays report-only.

A lane named in the `lanes` map of `config/qc/detectors.json` runs its own roles
by default, and its gate reads only the detectors those roles (or the WAV alone)
can score, a detector's `gateLanes` aside (the clone detectors gate only in
`clone-lane`); any other lane name runs every role. A take marked `control` (a
negative control, such as the language bench's pinned hint over a script in
another language, or the clone lane's other speakers) is scored and flagged,
but always at report-only: it never gates.

`gate` turns a run's flags into an exit code: 0 pass, 3 warn, 1 fail, 2 error.
`queue` writes the most suspicious unlabelled takes as a label batch, which
`label serve` opens.
"""

from __future__ import annotations

import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from qc import detectors as detector_lib
from qc import features as feature_lib
from qc import fit as fit_lib
from qc import label, models, runtime, store
from qc import norms as norms_lib
from qc.store import Layout

FEATURES_SCHEMA = "vocello.qc.features/1"
FLAGS_SCHEMA = "vocello.qc.flags/1"
LEVEL_RANK = {"report-only": 0, "warn": 1, "fail": 2}
EXIT_PASS, EXIT_FAIL, EXIT_ERROR, EXIT_WARN = 0, 1, 2, 3
PITCH_ROLES = ("pitchA", "pitchB")
EXCERPT_ROLES = ("phones", "phonesB")  # the phone recognizers the excerpt test runs on a pause alone
LANE_RE = detector_lib.LANE_NAME


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _role_models(config: dict[str, Any], registry: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    by_id = {model["id"]: model for model in registry}
    return {role: by_id.get(model_id) for role, model_id in config["models"].items()}


def _reference_takes(takes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clone references as pseudo-takes, so the pitch models also measure each reference's register."""

    seen: dict[str, dict[str, Any]] = {}
    for take in takes:
        reference = take.get("reference")
        if not reference:
            continue
        digest = take.get("referenceSHA256") or store.audio_sha256(reference)
        seen.setdefault(digest, {"token": f"ref{digest[:13]}", "audio": reference, "audioSHA256": digest,
                                 "language": take.get("language"), "text": None, "reference": None,
                                 "referenceSHA256": None})
    return list(seen.values())


def run(layout: Layout, takes_path: str, lane: str, *, roles: list[str] | None = None,
        echo: Callable[[str], None] = lambda line: print(line, file=sys.stderr, flush=True),
        runner: Callable[..., runtime.RunnerReport] = runtime.run_runner) -> Path:
    if not LANE_RE.fullmatch(lane):
        raise ValueError(f"invalid lane name: {lane!r}")
    config = detector_lib.load_config(layout)
    manifest = store.load_takes(takes_path)
    takes = [dict(take) for take in manifest["takes"]]
    for take in takes:
        if not take.get("audioSHA256"):
            take["audioSHA256"] = store.audio_sha256(take["audio"])
        if take.get("reference") and not take.get("referenceSHA256"):
            take["referenceSHA256"] = store.audio_sha256(take["reference"])
    references = _reference_takes(takes)
    role_models = _role_models(config, models.load_registry(layout))
    selected = roles or detector_lib.lane_roles(config, lane)
    model_report: dict[str, Any] = {}
    with runtime.run_lock(layout):
        for role in selected:
            model = role_models.get(role)
            if model is None:
                model_report[role] = {"id": config["models"].get(role), "error": "not registered"}
                continue
            inputs = takes + (references if role in PITCH_ROLES else [])
            try:
                report = runner(model, inputs, layout=layout, echo=echo)
            except runtime.RunnerError as error:
                echo(f"qc run: {role}: {error}")
                model_report[role] = {"id": model["id"], "error": str(error)}
                continue
            model_report[role] = {"id": model["id"], "ran": report.ran, "cached": report.cached,
                                  "failed": len(report.failed), "peakRSSBytes": report.peak_rss_bytes,
                                  "seconds": report.seconds, "exitCode": report.exit_code,
                                  "timedOut": report.timed_out}

        # Read every role's cached results, run now or earlier.
        identities: dict[str, Any] = {}
        results_by_token: dict[str, dict[str, Any]] = {take["token"]: {} for take in takes}
        reference_results: dict[str, dict[str, Any]] = {ref["audioSHA256"]: {} for ref in references}
        for role, model in role_models.items():
            if model is None:
                identities[role] = {"id": config["models"][role], "runnerSHA256": None, "available": False}
                continue
            try:
                identity = runtime.runner_identity(layout, model)
            except runtime.RunnerError:
                identities[role] = {"id": model["id"], "runnerSHA256": None, "available": False}
                continue
            found = 0
            for take in takes:
                if model.get("languages", "any") != "any" and take.get("language") not in model["languages"]:
                    continue
                variant = store.take_variant(model, take)
                result = store.read_result(layout, model["id"], take["audioSHA256"], variant, identity)
                if result is not None:
                    results_by_token[take["token"]][role] = result
                    found += 1
            if role in PITCH_ROLES:
                for reference in references:
                    result = store.read_result(layout, model["id"], reference["audioSHA256"], None, identity)
                    if result is not None:
                        reference_results[reference["audioSHA256"]][role] = result
            identities[role] = {"id": model["id"], "runnerSHA256": identity, "available": found > 0, "results": found}

        # A second G2P pass, after the ASR roles ran (or were read from the cache): the transcripts'
        # phones for asr.phonetic_error_*. The cache is keyed by text, so only new transcripts run.
        if role_models.get("g2p") is not None and {"g2p", "asrA", "asrB"} & set(selected):
            transcripts = feature_lib.transcript_g2p_takes(takes, results_by_token, layout, dict(config["models"]))
            if transcripts:
                try:
                    runner(role_models["g2p"], transcripts, layout=layout, echo=echo)
                except runtime.RunnerError as error:
                    echo(f"qc run: transcript G2P: {error}")
            model_report["g2pTranscripts"] = {"texts": len(transcripts)}

        params = config.get("params", {})
        context = feature_lib.build_context(reference_results, params)
        rows = []
        for take in takes:
            values = feature_lib.extract(take, results_by_token[take["token"]], context, params=params,
                                         layout=layout, model_ids=dict(config["models"]))
            rows.append({"token": take["token"], "takeID": take.get("takeID"), "language": take.get("language"),
                         "features": values})
        model_report["excerptTest"] = excerpt_test(
            layout, takes, rows, {role: role_models.get(role) for role in EXCERPT_ROLES},
            {role: identities.get(role, {}) for role in EXCERPT_ROLES}, params,
            run_now={role for role in EXCERPT_ROLES if role in selected}, runner=runner, echo=echo)

    run_id = f"{lane}-{utc_stamp()}-{secrets.token_hex(2)}"
    directory = layout.runs / run_id
    directory.mkdir(parents=True, exist_ok=False)
    scoring = detector_lib.scoring_identity(layout)
    store.write_json_atomic(directory / "takes.json", dict(manifest, takes=takes), indent=None)
    store.write_json_atomic(directory / "features.json", {
        "schema": FEATURES_SCHEMA, "run": run_id, "lane": lane, "source": manifest.get("source"),
        "detectorsVersion": config["version"], "detectorsSHA256": detector_lib.config_digest(layout),
        "scoringSHA256": scoring["sha256"],
        "scoring": {"files": scoring["files"], "norms": scoring["norms"]}, "models": identities, "takes": rows,
    }, indent=None)
    controls = {take["token"] for take in takes if take.get("control")}
    flags = score_run(layout, config, rows, identities, lane=lane, controls=controls, scoring=scoring)
    flags.update(run=run_id, lane=lane, models=model_report)
    store.write_json_atomic(directory / "flags.json", flags, indent=None)
    counts = flags["summary"]
    echo(f"qc run: {run_id}: {len(takes)} takes; flagged fail={counts['fail']} warn={counts['warn']} "
         f"report-only={counts['report-only']}; errors={len(flags['errors'])}")
    return directory


def excerpt_test(layout: Layout, takes: list[dict[str, Any]], rows: list[dict[str, Any]],
                 models: dict[str, dict[str, Any] | None], identities: dict[str, dict[str, Any]],
                 params: dict[str, Any], *, run_now: set[str], runner: Callable[..., runtime.RunnerReport],
                 echo: Callable[[str], None]) -> dict[str, Any]:
    """Run the phone recognizers on each take's longest pause alone.

    The pause, from `excerptMinGapSeconds` (0.4 s) up, is cut `excerptEdgeSeconds` (40 ms) inside its
    edges into `build/cache/qc/work/excerpts/<audioSHA256>-<startMs>-<endMs>.wav`. With no speech
    around it to lean on, what a recognizer hears there is in the pause: `pause.excerpt_phones` is
    the most phones either recognizer hears at `excerptPhoneMinProb` or more, breath-like phones
    (`excerptIgnorePhones`) aside. Zero says the pause holds no speech sound; muting a pause inside
    its sentence proved nothing, since recognizers fill in phones over zeros. The excerpts' results
    are cached by the excerpt's own digest.
    """

    minimum = params.get("excerptMinGapSeconds", 0.4)
    edge = params.get("excerptEdgeSeconds", 0.04)
    floor = params.get("excerptPhoneMinProb", 0.5)
    ignore = set(params.get("excerptIgnorePhones", ["h", "ɦ"]))
    candidates = []
    for take, row in zip(takes, rows):
        gap = row["features"].get("pause.longest_gap_seconds") or {}
        if gap.get("value") is None or gap["value"] < minimum or gap.get("start") is None or gap.get("end") is None:
            continue
        start, end = gap["start"] + edge, gap["end"] - edge
        path = layout.work / "excerpts" / f"{take['audioSHA256']}-{int(start * 1000)}-{int(end * 1000)}.wav"
        if not path.is_file():
            feature_lib.excerpt_wav(take["audio"], path, start, end)
        digest = store.audio_sha256(path)
        candidates.append((row, gap, {
            "token": f"gap{digest[:13]}", "audio": str(path), "audioSHA256": digest,
            "language": take.get("language"), "text": None, "reference": None, "referenceSHA256": None}))
    report: dict[str, Any] = {"candidates": len(candidates), "tested": 0, "empty": 0}
    usable = {role: model for role, model in models.items()
              if model is not None and identities.get(role, {}).get("runnerSHA256")}
    if not candidates or not usable:
        return report
    for role, model in usable.items():
        if role not in run_now:
            continue
        try:
            runner(model, [candidate[2] for candidate in candidates], layout=layout, echo=echo)
        except runtime.RunnerError as error:
            echo(f"qc run: excerpt test ({role}): {error}")
    for row, gap, excerpt in candidates:
        heard = []
        for role, model in usable.items():
            result = store.read_result(layout, model["id"], excerpt["audioSHA256"], None,
                                       identities[role]["runnerSHA256"])
            if not result or "outputs" not in result:
                continue
            phones = [item for item in result["outputs"].get("phones") or []
                      if (item.get("prob") is None or item["prob"] >= floor) and item.get("phone") not in ignore]
            heard.append(len(phones))
        if not heard:
            continue
        count = max(heard)
        row["features"]["pause.excerpt_phones"] = feature_lib.feature(float(count), gap["start"], gap["end"])
        report["tested"] += 1
        report["empty"] += int(count == 0)
    return report


def score_run(layout: Layout, config: dict[str, Any], rows: list[dict[str, Any]],
              identities: dict[str, Any], *, lane: str | None = None,
              controls: set[str] | frozenset[str] = frozenset(),
              scoring: dict[str, Any] | None = None) -> dict[str, Any]:
    """Flags for a run's feature rows, with the newest applicable thresholds and levels.

    The thresholds apply only when they were fitted on the run's model identities and its scoring
    identity (`scoring`, by default the current one); `thresholdsReason` says why they did not, or
    why no level came from an evaluation. A detector outside the lane's gated set, and every flag
    of a control take, stays report-only."""

    thresholds_path = fit_lib.latest_thresholds(layout)
    thresholds = store.read_json(thresholds_path) if thresholds_path else None
    scoring = scoring or detector_lib.scoring_identity(layout)
    reason = "no thresholds fitted"
    if thresholds_path is not None and thresholds is not None:
        mismatch = _thresholds_mismatch(thresholds, identities, scoring["sha256"])
        reason = None if mismatch is None else f"{thresholds_path.name} {mismatch}"
    applicable = thresholds is not None and reason is None
    levels = fit_lib.levels_for(layout, thresholds_path) if applicable else {}
    if applicable and not levels:
        reason = f"{thresholds_path.name} has no evaluation"
    names = detector_lib.feature_names(config)
    run_norm = detector_lib.normalization(rows, names)
    # A human-reference file has no z-score statistics: its fallbacks rank on the run's own.
    norm = thresholds.get("normalization", run_norm) if applicable else run_norm
    gated = detector_lib.gated_detectors(config, lane)
    pool_norms = norms_lib.load(layout)  # the provisional rules' per-language percentiles
    out_takes, errors = [], []
    summary = {level: 0 for level in LEVEL_RANK}
    for row in rows:
        control = row["token"] in controls
        flags, scores, raw = [], {}, {}
        for detector in config["detectors"]:
            fitted = thresholds["detectors"].get(detector["id"]) if applicable else None
            if fitted and fitted.get("reportOnly"):
                fitted = None
            outcome = detector_lib.score(detector, row["features"], row["language"], fitted, norm, norms=pool_norms)
            raw[detector["id"]] = detector_lib.uncalibrated(detector, row["features"], row["language"], run_norm)
            scores[detector["id"]] = outcome["score"]
            level = levels.get(detector["id"], {}).get(row["language"], "report-only")
            if control or detector["id"] not in gated:
                level = "report-only"
            if outcome["score"] is None:
                if level != "report-only":
                    errors.append({"token": row["token"], "detector": detector["id"], "reason": "missing-inputs"})
                continue
            if outcome["cut"] is not None and outcome["score"] >= outcome["cut"]:
                if (fitted or {}).get("method") == detector_lib.HUMAN_REFERENCE \
                        and outcome["scope"] != detector_lib.HUMAN_REFERENCE:
                    level = "report-only"  # no human reference in this language: the provisional rule
                flag = {"detector": detector["id"], "class": detector["class"], "level": level,
                        "score": round(outcome["score"], 6), "cut": outcome["cut"], "scope": outcome["scope"],
                        "evidence": outcome.get("evidence") or detector_lib.evidence(detector, row["features"])}
                if outcome.get("rule"):
                    flag["rule"] = outcome["rule"]
                flags.append(flag)
        if flags:
            summary[max((flag["level"] for flag in flags), key=LEVEL_RANK.__getitem__)] += 1
        entry = {"token": row["token"], "takeID": row.get("takeID"), "language": row["language"],
                 "flags": flags, "scores": scores, "rawScores": raw}
        if control:
            entry["control"] = True
        out_takes.append(entry)
    return {
        "schema": FLAGS_SCHEMA, "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "thresholds": thresholds_path.name if thresholds_path else None, "thresholdsApplied": applicable,
        "thresholdsMethod": thresholds.get("method", "logistic") if applicable else None,
        "thresholdsReason": reason, "scoringSHA256": scoring["sha256"], "norms": (pool_norms or {}).get("file"),
        "levelsFromEval": bool(levels), "takes": out_takes, "errors": errors, "summary": summary,
    }


def _thresholds_mismatch(thresholds: dict[str, Any], identities: dict[str, Any], scoring_sha: str) -> str | None:
    """Why a thresholds file (fitted on labels or calibrated on human controls) does not apply to a
    run, or None when it does: it was made with other scoring code, configuration or norms, or on
    another identity of a model the run has results of."""

    if thresholds.get("scoringSHA256") != scoring_sha:
        return f"was fitted with other {fit_lib.SCORING_CHANGED}"
    for role, expected in thresholds.get("models", {}).items():
        current = identities.get(role) or {}
        if current.get("runnerSHA256") and current["runnerSHA256"] != expected.get("runnerSHA256"):
            return f"was fitted on another {role} model identity"
    return None


def lane_runs(layout: Layout, lane: str | None = None) -> list[Path]:
    runs = [path for path in layout.runs.glob("*") if (path / "flags.json").is_file()]
    if lane:
        runs = [path for path in runs if store.read_json(path / "flags.json").get("lane") == lane]
    return sorted(runs, key=lambda path: path.stat().st_mtime)


def gate(layout: Layout, lane: str, run_id: str | None = None) -> int:
    runs = [layout.runs / run_id] if run_id else lane_runs(layout, lane)[-1:]
    if not runs or not (runs[0] / "flags.json").is_file():
        print(f"qc gate: no run of lane {lane}", file=sys.stderr)
        return EXIT_ERROR
    flags = store.read_json(runs[0] / "flags.json")
    if flags.get("lane") != lane:
        print(f"qc gate: run {runs[0].name} belongs to lane {flags.get('lane')}", file=sys.stderr)
        return EXIT_ERROR
    worst = "pass"
    for take in flags["takes"]:
        for flag in take["flags"]:
            if flag["level"] == "fail":
                worst = "fail"
            elif flag["level"] == "warn" and worst == "pass":
                worst = "warn"
    summary = flags["summary"]
    note = "" if flags.get("levelsFromEval") else \
        f" (report-only: {flags.get('thresholdsReason') or 'no evaluated thresholds'})"
    print(f"qc gate {lane}: run {flags['run']}: {worst}; takes {len(flags['takes'])}, fail {summary['fail']}, "
          f"warn {summary['warn']}, report-only {summary['report-only']}, errors {len(flags['errors'])}{note}")
    if flags["errors"]:
        return EXIT_ERROR
    return {"fail": EXIT_FAIL, "warn": EXIT_WARN}.get(worst, EXIT_PASS)


def queue(layout: Layout, top: int, *, run_id: str | None = None, name: str | None = None) -> Path:
    """The `top` unlabelled takes most worth hearing, as a label batch (`kind: queue`)."""

    from qc.controls import CONTROLS_LANE

    runs = [layout.runs / run_id] if run_id else [
        path for path in lane_runs(layout) if store.read_json(path / "flags.json").get("lane") != CONTROLS_LANE][-1:]
    if not runs:
        raise FileNotFoundError("no run to queue from (run qc.py run first)")
    directory = runs[0]
    flags = store.read_json(directory / "flags.json")
    takes = {take["token"]: take for take in store.read_json(directory / "takes.json")["takes"]}
    labelled = set()
    for existing in label.batch_names(layout):
        batch = label.load_batch(layout, existing)
        labels = label.latest_labels(layout, existing)
        labelled.update(item["takeToken"] for item in batch["items"] if item["token"] in labels)

    def rank(entry: dict[str, Any]) -> tuple:
        # Advisory flags (loudness) never rank a take for listening.
        flags = [flag for flag in entry["flags"] if flag.get("class")]
        level = max((LEVEL_RANK[flag["level"]] for flag in flags), default=-1)
        raw = max((value for value in entry["rawScores"].values() if value is not None), default=float("-inf"))
        return (level, len(flags), raw)

    candidates = [entry for entry in flags["takes"] if entry["token"] not in labelled and entry["token"] in takes]
    chosen = sorted(candidates, key=rank, reverse=True)[:top]
    name = name or f"queue-{directory.name}"
    items = []
    for position, entry in enumerate(chosen):
        take = takes[entry["token"]]
        top_detectors = sorted(((value, detector) for detector, value in entry["rawScores"].items() if value is not None),
                               reverse=True)[:3]
        items.append({
            "token": label.label_token(name, 0, take["token"], 0), "takeToken": take["token"], "repeatOf": None,
            "split": label.split_for_family(str(take.get("family") or take.get("takeID"))),
            "inclusionProbability": None, "stratum": label.stratum(take), "enriched": True,
            "reasons": [flag["detector"] for flag in entry["flags"]] or [detector for _, detector in top_detectors],
            "order": position,
        })
    batch = {"schema": label.BATCH_SCHEMA, "batch": name, "kind": "queue", "createdAt": label.utc_now(),
             "params": {"run": directory.name, "top": top}, "items": items,
             "takes": {item["takeToken"]: takes[item["takeToken"]] for item in items}}
    label.write_batch(layout, batch, overwrite=True)
    store.write_json_atomic(layout.queues / f"{name}.json",
                            {"batch": name, "run": directory.name, "tokens": [item["takeToken"] for item in items]})
    return label.batch_path(layout, name)


def parse_roles(value: str | None, config: dict[str, Any]) -> list[str] | None:
    """`--models` accepts roles (asrA, pitchB, ...) or model ids."""

    if not value:
        return None
    by_id = {model_id: role for role, model_id in config["models"].items()}
    roles = []
    for item in (part.strip() for part in value.split(",") if part.strip()):
        if item in config["models"]:
            roles.append(item)
        elif item in by_id:
            roles.append(by_id[item])
        else:
            raise ValueError(f"unknown model or role: {item}")
    return roles
