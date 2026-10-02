"""Fit detector thresholds on the train labels; evaluate them once on the held-out labels.

`fit` joins the maintainer's labels (`build/private/qc/labels`) to the features
of the `qc.py run` outputs (`build/private/qc/runs/*/features.json`) and writes
`config/qc/thresholds-v<N>.json`:
- per detector, an L2 logistic (or one threshold) with the cut that maximizes
  the weighted F1 on the train split;
- per language when it has at least 60 clean and 20 positive train takes, else
  one pooled model on per-language z-scores;
- sample weights of 1 / inclusion probability, so the enrichment does not bias
  the fit;
- the LLM judges stay report-only unless their train-split kappa reaches 0.6.

The file records the model identities, the detectors digest and the label-set
digest. It is committed before `eval` runs.

`eval` refuses a thresholds file that is not committed unchanged, and refuses to
score a version twice. It writes `benchmarks/qc/eval-v<N>.json` with aggregates
only:
- per detector and language: weighted precision and recall with Clopper-Pearson
  bounds (on the Kish effective sample size), clean false alarms and kappa;
- the level each detector earns: warn when the precision lower bound is at
  least 0.6 and the recall at least 0.6; fail when the precision lower bound is
  at least 0.8 and the clean false-alarm upper bound at most 5%.
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

THRESHOLDS_SCHEMA = "vocello.qc.thresholds/1"
EVAL_SCHEMA = "vocello.qc.eval/1"
THRESHOLDS_RE = re.compile(r"^thresholds-v(\d+)\.json$")
LINGUISTIC = {"stutter", "mispronunciation", "wrong-language"}
SEVERITY_RANK = {"none": 0, "mild": 1, "moderate": 2, "severe": 3}
DEFAULT_MIN_SEVERITY = "moderate"


class FitError(RuntimeError):
    """The labels or features cannot support a fit or an evaluation."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- inputs -----------------------------------------------------------------------

def feature_rows(layout: Layout, runs: Iterable[str] | None = None) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """The newest features per take token across runs, and the runs' model identities."""

    directories = sorted((path for path in layout.runs.glob("*") if (path / "features.json").is_file()),
                         key=lambda path: path.stat().st_mtime)
    if runs:
        wanted = set(runs)
        directories = [path for path in directories if path.name in wanted]
    rows: dict[str, dict[str, Any]] = {}
    identities: dict[str, Any] = {}
    for directory in directories:
        document = store.read_json(directory / "features.json")
        for role, identity in document.get("models", {}).items():
            if identity.get("available"):
                previous = identities.get(role)
                if previous and previous["runnerSHA256"] != identity["runnerSHA256"]:
                    raise FitError(f"runs disagree on the {role} model identity; refit from runs of one identity")
                identities[role] = {"id": identity["id"], "runnerSHA256": identity["runnerSHA256"]}
        for row in document.get("takes", []):
            rows[row["token"]] = dict(row, run=directory.name)
    return rows, identities


def label_rows(layout: Layout, batches: Iterable[str] | None = None, rater: str | None = None) -> list[dict[str, Any]]:
    """Every labelled primary item of one rater: token, split, weight, probability sample or not, label.

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
        entry.update(reportOnly=True, reason="no positive train labels with these features measured")
        return entry

    def design(subset: list[dict[str, Any]]) -> np.ndarray:
        return np.array([detector_lib.vector(detector, features[row["token"]]["features"], row["language"], norm)[0]
                         for row in subset], dtype=float)

    def fit_scope(subset: list[dict[str, Any]]) -> dict[str, Any] | None:
        y = [int(positive(row, class_id)) for row in subset]
        weights = [row["weight"] for row in subset]
        if not any(y):
            return None
        if detector["method"] == "threshold":
            item = detector["features"][0]
            scores = []
            kept_y, kept_w = [], []
            for row, target, weight in zip(subset, y, weights):
                value = (features[row["token"]]["features"].get(item["name"]) or {}).get("value")
                if value is not None:
                    scores.append(detector_lib.oriented(value, item["direction"]))
                    kept_y.append(target)
                    kept_w.append(weight)
            cut = best_cut(scores, kept_y, kept_w)
            return None if cut is None else {"cut": cut, "n": len(scores), "positives": sum(kept_y)}
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
    pooled = fit_scope(rows)
    if pooled:
        entry["models"]["*"] = pooled
    if detector.get("llm"):
        item = detector["features"][0]
        pairs = []
        for row in rows:
            value = (features[row["token"]]["features"].get(item["name"]) or {}).get("value")
            if value is not None:
                pairs.append((value >= 0.5, positive(row, class_id)))
        kappa = label.cohen_kappa(pairs)
        entry["kappa"] = kappa
        if kappa is None or kappa < settings.get("llmKappaGate", 0.6):
            entry.update(reportOnly=True, reason=f"train kappa {kappa} below {settings.get('llmKappaGate', 0.6)}")
            return entry
    entry["reportOnly"] = not entry["models"]
    if entry["reportOnly"]:
        entry["reason"] = "no fit"
    return entry


def next_version(layout: Layout) -> int:
    versions = [int(match.group(1)) for path in layout.config.glob("thresholds-v*.json")
                if (match := THRESHOLDS_RE.match(path.name))]
    return max(versions, default=0) + 1


def latest_thresholds(layout: Layout) -> Path | None:
    candidates = [(int(match.group(1)), path) for path in layout.config.glob("thresholds-v*.json")
                  if (match := THRESHOLDS_RE.match(path.name))]
    return max(candidates)[1] if candidates else None


def fit(layout: Layout, *, batches: Iterable[str] | None = None, runs: Iterable[str] | None = None) -> Path:
    config = detector_lib.load_config(layout)
    features, identities = feature_rows(layout, runs)
    if not features:
        raise FitError("no run features under build/private/qc/runs (run qc.py run first)")
    labels = label_rows(layout, batches)
    train = [row for row in labels if row["split"] == "train" and row["token"] in features]
    if not train:
        raise FitError("no labelled train takes with features")
    norm = detector_lib.normalization(features.values(), detector_lib.feature_names(config))
    settings = config.get("fit", {})
    fitted = {detector["id"]: fit_detector(detector, train, features, norm, settings)
              for detector in config["detectors"]}
    version = next_version(layout)
    document = {
        "schema": THRESHOLDS_SCHEMA, "version": version, "createdAt": utc_now(),
        "detectorsVersion": config["version"], "detectorsSHA256": detector_lib.config_digest(layout),
        "models": identities,
        "labelSet": {"batches": sorted({row["batch"] for row in labels}), "trainTakes": len(train),
                     "digest": label_set_digest(train)},
        "normalization": norm, "detectors": fitted,
    }
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


def evaluate(layout: Layout, *, thresholds: Path | None = None, batches: Iterable[str] | None = None,
             runs: Iterable[str] | None = None) -> Path:
    thresholds = thresholds or latest_thresholds(layout)
    if thresholds is None or not thresholds.is_file():
        raise FitError("no thresholds file (run qc.py fit, then commit it)")
    if not committed_unchanged(layout.root, thresholds):
        raise FitError(f"{thresholds.name} is not committed unchanged; commit it before the held-out evaluation")
    document = store.read_json(thresholds)
    version = document["version"]
    output = layout.root / "benchmarks/qc" / f"eval-v{version}.json"
    if output.exists():
        raise FitError(f"{output.name} exists: the held-out split is scored once per thresholds version")
    config = detector_lib.load_config(layout)
    features, _ = feature_rows(layout, runs)
    labels = label_rows(layout, batches)
    heldout = [row for row in labels if row["split"] == "heldout" and row["probabilitySample"]
               and row["token"] in features]
    if not heldout:
        raise FitError("no labelled held-out takes with features")
    norm = document["normalization"]
    pool_norms = norms_lib.load(layout)  # a report-only detector scores with its provisional rule, as in runs
    rules = config["levels"]
    results: dict[str, Any] = {}
    for detector in config["detectors"]:
        fitted = document["detectors"].get(detector["id"], {})
        if detector.get("advisory") or detector["class"] is None:
            results[detector["id"]] = {"class": None, "advisory": True, "reportOnly": True, "languages": {}}
            continue
        rows = [row for row in heldout if usable(row, detector["class"])]
        by_language: dict[str, list[dict[str, Any]]] = {"*": rows}
        for row in rows:
            by_language.setdefault(row["language"], []).append(row)
        report = {}
        for language, subset in sorted(by_language.items()):
            scored = []
            for row in subset:
                outcome = detector_lib.score(detector, features[row["token"]]["features"], row["language"],
                                             None if fitted.get("reportOnly") else fitted, norm, norms=pool_norms)
                flagged = outcome["cut"] is not None and outcome["score"] is not None \
                    and outcome["score"] >= outcome["cut"]
                scored.append((row, flagged))
            flagged_rows = [(row, flag) for row, flag in scored if flag]
            positives = [(row, flag) for row, flag in scored if positive(row, detector["class"])]
            clean = [(row, flag) for row, flag in scored if is_clean(row)]
            entry = {
                "n": len(scored), "positives": len(positives), "flagged": len(flagged_rows),
                "precision": weighted_rate([positive(row, detector["class"]) for row, _ in flagged_rows],
                                           [row["weight"] for row, _ in flagged_rows]),
                "recall": weighted_rate([flag for _, flag in positives], [row["weight"] for row, _ in positives]),
                "cleanFalseAlarms": weighted_rate([flag for _, flag in clean], [row["weight"] for row, _ in clean]),
                "kappa": label.cohen_kappa([(flag, positive(row, detector["class"])) for row, flag in scored]),
            }
            entry["level"] = level_for(entry, rules, bool(fitted.get("reportOnly", True)))
            report[language] = entry
        results[detector["id"]] = {"class": detector["class"], "reportOnly": bool(fitted.get("reportOnly", True)),
                                   "languages": report}
    intra = {}
    protocol = label.load_protocol(layout)
    for name in sorted({row["batch"] for row in labels}):
        intra[name] = label.repeat_agreement(label.load_batch(layout, name), label.latest_labels(layout, name),
                                             protocol)
    evaluation = {
        "schema": EVAL_SCHEMA, "version": version, "createdAt": utc_now(),
        "thresholds": thresholds.name, "thresholdsSHA256": store.sha256_file(thresholds),
        "commit": _head(layout.root), "labelSet": {"heldoutTakes": len(heldout), "digest": label_set_digest(heldout)},
        "norms": (pool_norms or {}).get("file"), "detectors": results, "intraRater": intra,
    }
    store.write_json_atomic(output, evaluation)
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
