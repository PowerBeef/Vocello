"""Fit detector thresholds on one rater's labels; evaluate them out of fold, once per label set.

`fit` joins the rater's labels (`build/private/qc/labels`) to the features of
the `qc.py run` outputs (`build/private/qc/runs/*/features.json`), which must
carry the current scoring identity (`qc.detectors.scoring_identity`), and
writes `config/qc/thresholds-v<N>.json`:
- per detector, an L2 logistic with the cut that maximizes the weighted F1;
- per language when it has at least 60 clean and 20 positive takes, and one
  pooled model on per-language z-scores when the detector has at least
  `fit.pooledMinPositive` (10) positives; below that floor it keeps its
  provisional rule, report-only;
- sample weights of 1 / inclusion probability, so the enrichment does not bias
  the fit;
- `crossValidation`: the same fit once per fold of script families
  (`label.fold_for_family`, k = `fit.crossValidationFolds`), each without that
  fold's families, with the digest of each fold's training labels. The final
  `detectors` are fitted on every label.

A positive is a class ticked at `fit.positiveMinSeverity` (moderate) or worse;
a milder tick counts on neither side. Queue batches train but are never
evaluated, and the 60/40 `split` of a batch item is not used. The file records
the rater, the model and scoring identities and the label-set digests. It is
committed before `eval` runs.

`eval` scores every labelled probability-sample take with the models of its own
family's fold, so no take is scored by a model fitted on its script. It refuses
a thresholds file that is not committed unchanged, a version already scored,
features or scoring code other than the fit's, labels changed since the fit,
and a label set an earlier evaluation scored, unless the thresholds file
declares `reuse: {"reason"}` (`qc.py fit --reuse-reason`). It writes
`benchmarks/qc/eval-v<N>.json` with aggregates only, and appends the scored
take tokens to the private ledger `build/private/qc/eval-ledger.jsonl`:
- per detector and language: weighted precision and recall with Clopper-Pearson
  bounds (on the Kish effective sample size), clean false alarms and kappa;
- the level each detector earns: warn when the precision lower bound is at
  least 0.6 and the recall at least 0.6; fail when the precision lower bound is
  at least 0.8 and the clean false-alarm upper bound at most 5%. A detector
  gates only the languages its evaluation covers.
"""

from __future__ import annotations

import math
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from qc import detectors as detector_lib
from qc import label, store
from qc import norms as norms_lib
from qc.store import Layout

THRESHOLDS_SCHEMA = "vocello.qc.thresholds/2"
EVAL_SCHEMA = "vocello.qc.eval/2"
THRESHOLDS_RE = re.compile(r"^thresholds-v(\d+)\.json$")
EVAL_RE = re.compile(r"^eval-v(\d+)\.json$")
EVAL_LEDGER = "eval-ledger.jsonl"
LINGUISTIC = {"stutter", "mispronunciation", "wrong-language"}
SEVERITY_RANK = {"none": 0, "mild": 1, "moderate": 2, "severe": 3}
DEFAULT_MIN_SEVERITY = "moderate"
DEFAULT_FOLDS = 5
DEFAULT_POOLED_MIN_POSITIVE = 10
SCORING_CHANGED = "scoring code (feature, detector, phone or pitch code, detectors.json or norms)"


class FitError(RuntimeError):
    """The labels or features cannot support a fit or an evaluation."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- inputs -----------------------------------------------------------------------

def feature_rows(layout: Layout, runs: Iterable[str] | None = None
                 ) -> tuple[dict[str, dict[str, Any]], dict[str, Any], str | None]:
    """The newest features per take token across runs, the runs' model identities and their scoring
    identity (`scoringSHA256`, None for a run older than it). Runs that disagree on a model identity
    or on the scoring identity are refused: name runs of one identity."""

    directories = sorted((path for path in layout.runs.glob("*") if (path / "features.json").is_file()),
                         key=lambda path: path.stat().st_mtime)
    if runs:
        wanted = set(runs)
        directories = [path for path in directories if path.name in wanted]
    else:  # the human-controls lane measures detectors on people; it never trains them
        from qc.controls import CONTROLS_LANE

        directories = [path for path in directories
                       if store.read_json(path / "features.json").get("lane") != CONTROLS_LANE]
    rows: dict[str, dict[str, Any]] = {}
    identities: dict[str, Any] = {}
    scorings: set[str | None] = set()
    for directory in directories:
        document = store.read_json(directory / "features.json")
        scorings.add(document.get("scoringSHA256"))
        if len(scorings) > 1:
            raise FitError(f"runs were scored with different {SCORING_CHANGED}; name runs of one scoring "
                           "identity with --runs")
        for role, identity in document.get("models", {}).items():
            if identity.get("available"):
                previous = identities.get(role)
                if previous and previous["runnerSHA256"] != identity["runnerSHA256"]:
                    raise FitError(f"runs disagree on the {role} model identity; refit from runs of one identity")
                identities[role] = {"id": identity["id"], "runnerSHA256": identity["runnerSHA256"]}
        for row in document.get("takes", []):
            rows[row["token"]] = dict(row, run=directory.name)
    return rows, identities, next(iter(scorings), None)


def label_rows(layout: Layout, batches: Iterable[str] | None = None, rater: str | None = None) -> list[dict[str, Any]]:
    """Every labelled primary item of one rater: token, script family (its cross-validation fold),
    split (recorded by the batch, unused by fit and eval), weight, probability sample or not, label.

    Each row carries the configured severity bar (`fit.positiveMinSeverity`), which `positive` and
    `usable` read.
    """

    names = list(batches) if batches else label.batch_names(layout)
    rater = rater or label.default_rater(layout)
    min_severity = detector_lib.load_config(layout).get("fit", {}).get("positiveMinSeverity", DEFAULT_MIN_SEVERITY)
    if min_severity not in SEVERITY_RANK or min_severity == "none":
        raise FitError(f"fit.positiveMinSeverity must be mild, moderate or severe, not {min_severity!r}")
    rows = []
    for name in names:
        batch = label.load_batch(layout, name)
        probability = batch.get("kind") == "sample"
        for entry in label.labelled_takes(layout, name, rater):
            item, take = entry["item"], entry["take"]
            inclusion = item.get("inclusionProbability")
            rows.append({
                "batch": name, "token": take["token"], "language": take.get("language"), "split": item["split"],
                "family": str(take.get("family") or take.get("takeID") or take["token"]),
                "weight": 1.0 / inclusion if probability and inclusion else 1.0, "probabilitySample": probability,
                "rater": rater, "minSeverity": min_severity, "label": entry["label"],
            })
    return rows


def label_set_digest(rows: list[dict[str, Any]]) -> str:
    payload = sorted((row["batch"], row.get("rater", "maintainer"), row["token"], row["split"],
                      row.get("minSeverity", DEFAULT_MIN_SEVERITY), row["label"].get("verdict"),
                      store.canonical_json(row["label"].get("classes") or {})) for row in rows)
    return store.sha256_text(store.canonical_json(payload))


def _severity(label_row: dict[str, Any], class_id: str) -> int:
    value = ((label_row["label"].get("classes") or {}).get(class_id) or {}).get("severity", "none")
    return SEVERITY_RANK.get(value, 0)


def positive(label_row: dict[str, Any], class_id: str) -> bool:
    """The class ticked at the configured severity or worse (moderate by default)."""

    return _severity(label_row, class_id) >= SEVERITY_RANK[label_row.get("minSeverity", DEFAULT_MIN_SEVERITY)]


def is_clean(label_row: dict[str, Any]) -> bool:
    return label_row["label"].get("verdict") == "acceptable" and not label.defect_present(label_row["label"])


def usable(label_row: dict[str, Any], class_id: str) -> bool:
    """Whether the label says yes or no about this class.

    Acoustic-only labels say nothing about the linguistic classes; a tick below the severity bar
    (mild, by default) and an uncertain verdict without a qualifying tick count on neither side.
    """

    if label_row["label"].get("acousticOnly") and class_id in LINGUISTIC:
        return False
    if positive(label_row, class_id):
        return True
    if _severity(label_row, class_id) > 0:
        return False
    return label_row["label"].get("verdict") != "uncertain"


# --- the fit ------------------------------------------------------------------------

def fit_logistic(x: np.ndarray, y: np.ndarray, weights: np.ndarray, l2: float) -> tuple[float, list[float]]:
    """Weighted L2 logistic regression by Newton steps (intercept not penalized)."""

    n, d = x.shape
    design = np.hstack([np.ones((n, 1)), x])
    weights = weights * (n / weights.sum())
    beta = np.zeros(d + 1)
    penalty = np.diag([0.0] + [l2] * d)
    for _ in range(100):
        p = 1.0 / (1.0 + np.exp(-np.clip(design @ beta, -30, 30)))
        gradient = design.T @ (weights * (y - p)) - penalty @ beta
        hessian = design.T @ (design * (weights * p * (1 - p))[:, None]) + penalty + 1e-9 * np.eye(d + 1)
        step = np.linalg.solve(hessian, gradient)
        beta += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return float(beta[0]), [float(value) for value in beta[1:]]


def best_cut(scores: list[float], y: list[int], weights: list[float]) -> float | None:
    """The cut (score >= cut flags) that maximizes the weighted F1; None without a positive."""

    if not any(y):
        return None
    best_f1, best = -1.0, None
    for cut in sorted(set(scores)):
        tp = sum(w for s, t, w in zip(scores, y, weights) if s >= cut and t)
        fp = sum(w for s, t, w in zip(scores, y, weights) if s >= cut and not t)
        fn = sum(w for s, t, w in zip(scores, y, weights) if s < cut and t)
        f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
        if f1 > best_f1:
            best_f1, best = f1, cut
    return best


def fit_detector(detector: dict[str, Any], train: list[dict[str, Any]], features: dict[str, dict[str, Any]],
                 norm: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    class_id = detector["class"]
    entry: dict[str, Any] = {"class": class_id, "method": detector["method"],
                             "features": [item["name"] for item in detector["features"]], "models": {}}
    if detector.get("advisory") or class_id is None:
        entry.update(reportOnly=True, advisory=True, reason="advisory: provisional rule only")
        return entry
    names = [item["name"] for item in detector["features"]]

    def measured(row: dict[str, Any]) -> bool:
        values = features[row["token"]]["features"]
        return any((values.get(name) or {}).get("value") is not None for name in names)

    rows = [row for row in train if row["token"] in features and usable(row, class_id) and measured(row)]
    positives = sum(positive(row, class_id) for row in rows)
    entry["train"] = {"takes": len(rows), "positives": positives,
                      "clean": sum(is_clean(row) for row in rows)}
    if not rows or positives == 0:
        entry.update(reportOnly=True, reason="no positive labels with these features measured")
        return entry

    def design(subset: list[dict[str, Any]]) -> np.ndarray:
        return np.array([detector_lib.vector(detector, features[row["token"]]["features"], row["language"], norm)[0]
                         for row in subset], dtype=float)

    def fit_scope(subset: list[dict[str, Any]]) -> dict[str, Any] | None:
        y = [int(positive(row, class_id)) for row in subset]
        weights = [row["weight"] for row in subset]
        if not any(y):
            return None
        x = design(subset)
        intercept, coefficients = fit_logistic(x, np.array(y, dtype=float), np.array(weights, dtype=float),
                                               settings.get("l2", 1.0))
        scores = [detector_lib.sigmoid(intercept + float(np.dot(coefficients, row))) for row in x]
        return {"intercept": intercept, "weights": coefficients, "cut": best_cut(scores, y, weights),
                "n": len(subset), "positives": sum(y)}

    languages = sorted({row["language"] for row in rows})
    for language in languages:
        subset = [row for row in rows if row["language"] == language]
        clean = sum(is_clean(row) for row in subset)
        hits = sum(positive(row, class_id) for row in subset)
        if clean >= settings.get("perLanguageMinClean", 60) and hits >= settings.get("perLanguageMinPositive", 20):
            fitted = fit_scope(subset)
            if fitted:
                entry["models"][language] = fitted
    floor = settings.get("pooledMinPositive", DEFAULT_POOLED_MIN_POSITIVE)
    pooled = fit_scope(rows) if positives >= floor else None
    if pooled:
        entry["models"]["*"] = pooled
    entry["reportOnly"] = not entry["models"]
    if entry["reportOnly"]:
        entry["reason"] = "no fit" if positives >= floor else \
            f"{positives} positive labels, below the pooled floor of {floor}: the provisional rule stays"
    return entry


def fit_settings(config: dict[str, Any]) -> dict[str, Any]:
    """The `fit` block of the detectors configuration, with its fold count and pooled floor checked."""

    settings = dict(config.get("fit", {}))
    for key, default, minimum in (("crossValidationFolds", DEFAULT_FOLDS, 2),
                                  ("pooledMinPositive", DEFAULT_POOLED_MIN_POSITIVE, 1)):
        value = settings.setdefault(key, default)
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise FitError(f"fit.{key} must be an integer of at least {minimum}, not {value!r}")
    return settings


def next_version(layout: Layout) -> int:
    versions = [int(match.group(1)) for path in layout.config.glob("thresholds-v*.json")
                if (match := THRESHOLDS_RE.match(path.name))]
    return max(versions, default=0) + 1


def latest_thresholds(layout: Layout) -> Path | None:
    candidates = [(int(match.group(1)), path) for path in layout.config.glob("thresholds-v*.json")
                  if (match := THRESHOLDS_RE.match(path.name))]
    return max(candidates)[1] if candidates else None


def fold_training(rows: list[dict[str, Any]], fold: int, k: int) -> list[dict[str, Any]]:
    """The labelled rows a fold's models train on: every row whose script family is in another fold."""

    return [row for row in rows if label.fold_for_family(row["family"], k) != fold]


def fit(layout: Layout, *, batches: Iterable[str] | None = None, runs: Iterable[str] | None = None,
        rater: str | None = None, reuse_reason: str | None = None) -> Path:
    """Write the next thresholds file: the out-of-fold models `eval` scores with, then the final
    models fitted on every label. `reuse_reason` declares why this file may be evaluated on a label
    set an earlier evaluation already scored."""

    config = detector_lib.load_config(layout)
    settings = fit_settings(config)
    if reuse_reason is not None and not reuse_reason.strip():
        raise FitError("a reuse needs its reason")
    features, identities, run_scoring = feature_rows(layout, runs)
    if not features:
        raise FitError("no run features under build/private/qc/runs (run qc.py run first)")
    scoring = detector_lib.scoring_identity(layout)
    if run_scoring != scoring["sha256"]:
        raise FitError(f"the run features were scored with other {SCORING_CHANGED} than the current; "
                       "rerun qc.py run on the labelled takes, then fit from that run (--runs)")
    rater = rater or label.default_rater(layout)
    labelled = [row for row in label_rows(layout, batches, rater) if row["token"] in features]
    if not labelled:
        raise FitError("no labelled takes with features")
    norm = detector_lib.normalization(features.values(), detector_lib.feature_names(config))
    k = settings["crossValidationFolds"]
    folds = []
    for fold in range(k):
        training = fold_training(labelled, fold, k)
        folds.append({"fold": fold, "takes": len(training), "labelSetDigest": label_set_digest(training),
                      "detectors": {detector["id"]: fit_detector(detector, training, features, norm, settings)
                                    for detector in config["detectors"]}})
    fitted = {detector["id"]: fit_detector(detector, labelled, features, norm, settings)
              for detector in config["detectors"]}
    version = next_version(layout)
    document = {
        "schema": THRESHOLDS_SCHEMA, "version": version, "createdAt": utc_now(),
        "detectorsVersion": config["version"], "detectorsSHA256": detector_lib.config_digest(layout),
        "scoringSHA256": scoring["sha256"], "scoring": {"files": scoring["files"], "norms": scoring["norms"]},
        "models": identities, "rater": rater,
        "labelSet": {"batches": sorted({row["batch"] for row in labelled}), "takes": len(labelled),
                     "digest": label_set_digest(labelled)},
        "crossValidation": {"k": k, "salt": label.FOLD_SALT, "folds": folds},
        "normalization": norm, "detectors": fitted,
    }
    if reuse_reason is not None:
        document["reuse"] = {"reason": reuse_reason.strip()}
    path = layout.config / f"thresholds-v{version}.json"
    store.write_json_atomic(path, document)
    return path


# --- evaluation -------------------------------------------------------------------------

def _betacf(a: float, b: float, x: float) -> float:
    tiny, qab, qap, qam = 1e-300, a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return h


def beta_cdf(x: float, a: float, b: float) -> float:
    """The regularized incomplete beta function I_x(a, b)."""

    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def beta_quantile(q: float, a: float, b: float) -> float:
    low, high = 0.0, 1.0
    for _ in range(100):
        middle = (low + high) / 2
        if beta_cdf(middle, a, b) < q:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def clopper_pearson(successes: float, trials: float, alpha: float = 0.05) -> tuple[float | None, float | None]:
    """Two-sided exact bounds; fractional counts (effective sizes) are allowed."""

    if trials <= 0:
        return None, None
    successes = min(max(successes, 0.0), trials)
    lower = 0.0 if successes <= 0 else beta_quantile(alpha / 2, successes, trials - successes + 1)
    upper = 1.0 if successes >= trials else beta_quantile(1 - alpha / 2, successes + 1, trials - successes)
    return round(lower, 4), round(upper, 4)


def weighted_rate(hits: list[bool], weights: list[float]) -> dict[str, Any]:
    """Weighted proportion with Clopper-Pearson bounds on the Kish effective sample size."""

    if not hits:
        return {"n": 0, "rate": None, "lower": None, "upper": None}
    total = sum(weights)
    rate = sum(w for hit, w in zip(hits, weights) if hit) / total
    effective = total**2 / sum(w * w for w in weights)
    lower, upper = clopper_pearson(rate * effective, effective)
    return {"n": len(hits), "rate": round(rate, 4), "lower": lower, "upper": upper}


def level_for(row: dict[str, Any], rules: dict[str, Any], report_only: bool) -> str:
    if report_only:
        return "report-only"
    precision_lower = row["precision"]["lower"]
    recall = row["recall"]["rate"]
    clean_upper = row["cleanFalseAlarms"]["upper"]
    fail = rules["fail"]
    if (precision_lower is not None and precision_lower >= fail["precisionLower"]
            and clean_upper is not None and clean_upper <= fail["cleanFalseAlarmUpper"]):
        return "fail"
    warn = rules["warn"]
    if precision_lower is not None and precision_lower >= warn["precisionLower"] and recall is not None \
            and recall >= warn["recall"]:
        return "warn"
    return "report-only"


def committed_unchanged(root: Path, path: Path) -> bool:
    relative = str(path.resolve().relative_to(root.resolve()))
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", relative],
                             capture_output=True, check=False)
    if tracked.returncode != 0:
        return False
    clean = subprocess.run(["git", "-C", str(root), "diff", "--quiet", "HEAD", "--", relative],
                           capture_output=True, check=False)
    return clean.returncode == 0


def _evaluated_before(layout: Layout, digest: str) -> str | None:
    """The earlier evaluation (a `benchmarks/qc/eval-v*.json`, or a line of the private ledger)
    that already scored this label set, or None."""

    for path in sorted((layout.root / "benchmarks/qc").glob("eval-v*.json")):
        if not EVAL_RE.match(path.name):
            continue
        try:
            document = store.read_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(document, dict) and document.get("labelSetDigest") == digest:
            return path.name
    for row in store.read_jsonl(layout.private / EVAL_LEDGER):
        if isinstance(row, dict) and row.get("labelSetDigest") == digest:
            return f"evaluation v{row.get('version')} (private ledger)"
    return None


def _metrics(scored: list[tuple[dict[str, Any], bool]], class_id: str, rules: dict[str, Any],
             report_only: bool) -> dict[str, Any]:
    flagged_rows = [(row, flag) for row, flag in scored if flag]
    positives = [(row, flag) for row, flag in scored if positive(row, class_id)]
    clean = [(row, flag) for row, flag in scored if is_clean(row)]
    entry = {
        "n": len(scored), "positives": len(positives), "flagged": len(flagged_rows),
        "precision": weighted_rate([positive(row, class_id) for row, _ in flagged_rows],
                                   [row["weight"] for row, _ in flagged_rows]),
        "recall": weighted_rate([flag for _, flag in positives], [row["weight"] for row, _ in positives]),
        "cleanFalseAlarms": weighted_rate([flag for _, flag in clean], [row["weight"] for row, _ in clean]),
        "kappa": label.cohen_kappa([(flag, positive(row, class_id)) for row, flag in scored]),
    }
    entry["level"] = level_for(entry, rules, report_only)
    return entry


def evaluate(layout: Layout, *, thresholds: Path | None = None, batches: Iterable[str] | None = None,
             runs: Iterable[str] | None = None, rater: str | None = None) -> Path:
    """Score every labelled probability-sample take out of fold and write `eval-v<N>.json`.

    A take is scored with the models of its own family's fold, which never trained on its script.
    For a detector whose final fit is report-only, every take scores with its provisional rule, as
    in runs (the level stays report-only); for a fitted detector, a take whose fold is report-only
    is left out (`unscored`), so a language the folds cannot score earns no level.
    """

    thresholds = thresholds or latest_thresholds(layout)
    if thresholds is None or not thresholds.is_file():
        raise FitError("no thresholds file (run qc.py fit, then commit it)")
    if not committed_unchanged(layout.root, thresholds):
        raise FitError(f"{thresholds.name} is not committed unchanged; commit it before the evaluation")
    document = store.read_json(thresholds)
    version = document["version"]
    output = layout.root / "benchmarks/qc" / f"eval-v{version}.json"
    if output.exists():
        raise FitError(f"{output.name} exists: a thresholds version is evaluated once")
    validation = document.get("crossValidation") or {}
    if document.get("schema") != THRESHOLDS_SCHEMA or validation.get("salt") != label.FOLD_SALT:
        raise FitError(f"{thresholds.name} has no out-of-fold models; refit with this qc.py")
    config = detector_lib.load_config(layout)
    if document.get("scoringSHA256") != detector_lib.scoring_identity(layout)["sha256"]:
        raise FitError(f"{thresholds.name} was fitted with other {SCORING_CHANGED} than the current; refit")
    features, identities, run_scoring = feature_rows(layout, runs)
    if not features:
        raise FitError("no run features under build/private/qc/runs (run qc.py run first)")
    if run_scoring != document["scoringSHA256"]:
        raise FitError(f"the run features were scored with other {SCORING_CHANGED} than {thresholds.name} "
                       "was fitted on")
    fitted_models = document.get("models", {})
    changed = sorted(role for role in set(identities) | set(fitted_models)
                     if identities.get(role) != fitted_models.get(role))
    if changed:
        raise FitError(f"the run features come from other model identities than {thresholds.name} "
                       f"({', '.join(changed)})")
    fitted_rater = document.get("rater")
    rater = rater or fitted_rater or label.default_rater(layout)
    if fitted_rater and rater != fitted_rater:
        raise FitError(f"{thresholds.name} was fitted on the labels of rater {fitted_rater}, not {rater}")
    labelled = [row for row in label_rows(layout, batches, rater) if row["token"] in features]
    k = validation["k"]
    for entry in validation["folds"]:
        if label_set_digest(fold_training(labelled, entry["fold"], k)) != entry["labelSetDigest"]:
            raise FitError(f"the labels, or the takes with features, differ from those {thresholds.name} was fitted "
                           f"on (fold {entry['fold']}); evaluate with the fit's --batches and --runs, or refit")
    sample = [row for row in labelled if row["probabilitySample"]]
    if not sample:
        raise FitError("no labelled probability-sample takes with features")
    digest = label_set_digest(sample)
    earlier = _evaluated_before(layout, digest)
    reuse = (document.get("reuse") or {}).get("reason")
    if earlier and not (isinstance(reuse, str) and reuse.strip()):
        raise FitError(f"{earlier} already scored this label set; label new takes, or refit with "
                       "--reuse-reason to declare why it is scored again")
    folds = {entry["fold"]: entry["detectors"] for entry in validation["folds"]}
    norm = document["normalization"]
    pool_norms = norms_lib.load(layout)  # a report-only detector scores with its provisional rule, as in runs
    rules = config["levels"]
    results: dict[str, Any] = {}
    for detector in config["detectors"]:
        final = document["detectors"].get(detector["id"], {})
        if detector.get("advisory") or detector["class"] is None:
            results[detector["id"]] = {"class": None, "advisory": True, "reportOnly": True, "languages": {}}
            continue
        report_only = bool(final.get("reportOnly", True))
        scored: list[tuple[dict[str, Any], bool]] = []
        unscored = 0
        for row in sample:
            if not usable(row, detector["class"]):
                continue
            fitted = None
            if not report_only:
                fitted = folds[label.fold_for_family(row["family"], k)].get(detector["id"]) or {}
                if fitted.get("reportOnly", True):
                    unscored += 1
                    continue
            outcome = detector_lib.score(detector, features[row["token"]]["features"], row["language"], fitted,
                                         norm, norms=pool_norms)
            flagged = outcome["cut"] is not None and outcome["score"] is not None \
                and outcome["score"] >= outcome["cut"]
            scored.append((row, flagged))
        by_language: dict[str, list[tuple[dict[str, Any], bool]]] = {"*": scored}
        for row, flag in scored:
            by_language.setdefault(row["language"], []).append((row, flag))
        results[detector["id"]] = {
            "class": detector["class"], "reportOnly": report_only,
            "scoredWith": "provisional" if report_only else "out-of-fold", "unscored": unscored,
            "languages": {language: _metrics(subset, detector["class"], rules, report_only)
                          for language, subset in sorted(by_language.items())},
        }
    intra = {}
    protocol = label.load_protocol(layout)
    for name in sorted({row["batch"] for row in labelled}):
        intra[name] = label.repeat_agreement(label.load_batch(layout, name), label.latest_labels(layout, name, rater),
                                             protocol)
    evaluation = {
        "schema": EVAL_SCHEMA, "version": version, "createdAt": utc_now(),
        "thresholds": thresholds.name, "thresholdsSHA256": store.sha256_file(thresholds),
        "commit": _head(layout.root), "rater": rater, "scoringSHA256": document["scoringSHA256"],
        "method": {"name": "out-of-fold", "k": k, "salt": validation["salt"], "groups": "script family"},
        "labelSetDigest": digest,
        "labelSet": {"batches": sorted({row["batch"] for row in sample}), "takes": len(sample)},
        "norms": (pool_norms or {}).get("file"), "detectors": results, "intraRater": intra,
    }
    if earlier:
        evaluation["reuse"] = {"reason": reuse.strip(), "earlier": earlier}
    store.write_json_atomic(output, evaluation)
    store.append_jsonl(layout.private / EVAL_LEDGER, {
        "version": version, "labelSetDigest": digest, "tokens": sorted(row["token"] for row in sample),
        "evaluatedAt": evaluation["createdAt"]})
    return output


def _head(root: Path) -> str | None:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return result.stdout.strip() or None


def levels_for(layout: Layout, thresholds: Path) -> dict[str, dict[str, str]]:
    """Detector levels per language from the evaluation of exactly this thresholds file."""

    document = store.read_json(thresholds)
    path = layout.root / "benchmarks/qc" / f"eval-v{document['version']}.json"
    if not path.is_file():
        return {}
    evaluation = store.read_json(path)
    if evaluation.get("thresholdsSHA256") != store.sha256_file(thresholds):
        return {}
    return {detector_id: {language: entry["level"] for language, entry in value["languages"].items()}
            for detector_id, value in evaluation["detectors"].items()}
