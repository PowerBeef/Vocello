"""Detectors: `config/qc/detectors.json`, feature normalization and scoring.

Each detector reads at most four features and maps them to one score, its
`method`: `logistic`, an L2 logistic over the features' per-language z-scores
(oriented so that higher means more defective), fitted per language when the
labels allow, else pooled (`*`).

A fitted detector flags a take when its score reaches the fitted cut. Before a
fit (or for a detector the labels could not train) a detector with a
`provisional` rule scores with it, at report-only; one without scores
uncalibrated: the largest oriented z-score among its features, which ranks the
listening queue but never flags. A detector with `gateLanes` gates only in those
lanes (the clone detectors gate only in `clone-lane`).

A rule condition compares a feature with a fixed `value`, or with a percentile
of the take's language from the newest `config/qc/norms-v<N>.json` (`norm`, of
the condition's feature or of `normFeature`, bounded by `atLeast` and
`atMost`), falling back to `value` when the norms lack that language or feature.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable

from qc import store
from qc.store import Layout

METHODS = ("logistic",)
DIRECTIONS = ("higher", "lower")
ROLES = ("asrA", "asrB", "phones", "phonesB", "g2p", "pitchA", "pitchB", "speaker")
# Which runner roles a feature family reads (signal and engine features read only the WAV and the take).
# The phone features need both recognizers: an insertion counts only when both make it.
FEATURE_ROLES = {
    "asr": ("asrA", "asrB", "g2p"), "phones": ("phones", "phonesB", "g2p"), "pitch": ("pitchA", "pitchB"),
    "speaker": ("speaker",), "signal": (), "engine": (), "pause": (), "end": (), "level": (), "rate": ("g2p",),
}
LEVELS = ("report-only", "warn", "fail")
LANE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
RULE_OPS = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
# The percentiles a norms file holds for each language and feature (`qc.norms`).
NORM_PERCENTILES = ("p1", "p3", "p10", "p50", "p90", "p97", "p99")


class ConfigError(ValueError):
    """`config/qc/detectors.json` is invalid."""


def load_config(layout: Layout = Layout()) -> dict[str, Any]:
    path = layout.config / "detectors.json"
    config = store.read_json(path)
    validate_config(config, class_ids=_protocol_classes(layout))
    return config


def _protocol_classes(layout: Layout) -> set[str] | None:
    try:
        return {item["id"] for item in store.read_json(layout.protocol)["classes"]}
    except (OSError, ValueError, KeyError):
        return None


def validate_config(config: Any, *, class_ids: set[str] | None = None) -> None:
    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ConfigError(message)

    require(isinstance(config, dict) and config.get("schemaVersion") == 1, "unsupported detectors schemaVersion")
    require(isinstance(config.get("version"), int) and config["version"] >= 1, "version must be a positive integer")
    roles = config.get("models")
    require(isinstance(roles, dict) and set(roles) <= set(ROLES), f"models must map roles among {', '.join(ROLES)}")
    seen: set[str] = set()
    for detector in config.get("detectors", []):
        label = f"detector {detector.get('id')!r}"
        require(isinstance(detector.get("id"), str) and detector["id"] not in seen, f"{label}: duplicate or missing id")
        seen.add(detector["id"])
        if detector.get("advisory"):
            require(detector.get("class") is None or class_ids is None or detector["class"] in class_ids,
                    f"{label}: unknown class")
        else:
            require(class_ids is None or detector.get("class") in class_ids, f"{label}: unknown class")
        rule = detector.get("provisional")
        if rule is not None:
            require(isinstance(rule, dict) and rule and set(rule) <= {"all", "any", "none"},
                    f"{label}: provisional takes all, any and none lists")
            for conditions in rule.values():
                for condition in conditions:
                    require(_valid_condition(condition), f"{label}: bad provisional condition {condition!r}")
        require(detector.get("method") in METHODS, f"{label}: method must be one of {', '.join(METHODS)}")
        features = detector.get("features")
        require(isinstance(features, list) and 1 <= len(features) <= 4, f"{label}: one to four features")
        for item in features:
            require(item.get("direction") in DIRECTIONS, f"{label}: direction must be higher or lower")
            family = str(item.get("name", "")).split(".", 1)[0]
            require(family in FEATURE_ROLES, f"{label}: unknown feature family in {item.get('name')!r}")
        if "gateLanes" in detector:
            gate_lanes = detector["gateLanes"]
            require(isinstance(gate_lanes, list) and bool(gate_lanes)
                    and set(gate_lanes) <= set(config.get("lanes") or {}),
                    f"{label}: gateLanes must list lanes of the lanes map")
    for name in ("warn", "fail"):
        require(isinstance(config.get("levels", {}).get(name), dict), f"levels.{name} is required")
    lanes = config.get("lanes", {})
    require(isinstance(lanes, dict), "lanes must map lane names to definitions")
    for name, lane in lanes.items():
        require(isinstance(name, str) and LANE_NAME.fullmatch(name) is not None, f"lane {name!r}: invalid name")
        require(isinstance(lane, dict) and isinstance(lane.get("description"), str) and lane["description"],
                f"lane {name!r}: a description is required")
        models = lane.get("models")
        require(isinstance(models, list) and models and len(set(models)) == len(models)
                and set(models) <= set(roles), f"lane {name!r}: models must list roles of the models map once")


def lane_roles(config: dict[str, Any], lane: str | None) -> list[str]:
    """The roles a lane runs by default: its `lanes` entry, else every role of the models map."""

    definition = (config.get("lanes") or {}).get(lane or "")
    return list(definition["models"]) if definition else list(config["models"])


def gated_detectors(config: dict[str, Any], lane: str | None) -> set[str]:
    """The detectors a lane's gate reads: those with a feature the lane can measure, from the WAV
    and the take alone or from roles the lane runs, and, for a detector with `gateLanes`, only in
    those lanes. The others stay report-only in that lane, so a model it never runs cannot turn a
    gate into an error."""

    roles = set(lane_roles(config, lane))
    gated = set()
    for detector in config["detectors"]:
        if "gateLanes" in detector and lane not in detector["gateLanes"]:
            continue
        families = {item["name"].split(".", 1)[0] for item in detector["features"]}
        if any(set(FEATURE_ROLES[family]) <= roles for family in families):
            gated.add(detector["id"])
    return gated


def _valid_condition(condition: Any) -> bool:
    """`{feature, op}` with a numeric `value`, a `norm` percentile, or both (the value is then the
    fallback); `normFeature` names another feature's norm, and `atLeast` and `atMost` bound it."""

    if not isinstance(condition, dict):
        return False

    def number(key: str) -> bool:
        value = condition.get(key)
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    norm = condition.get("norm")
    return (condition.get("op") in RULE_OPS
            and str(condition.get("feature", "")).split(".", 1)[0] in FEATURE_ROLES
            and (norm is None or norm in NORM_PERCENTILES)
            and ("normFeature" not in condition or (norm is not None and isinstance(condition["normFeature"], str)))
            and (number("value") if "value" in condition else norm is not None)
            and all(number(key) for key in ("atLeast", "atMost") if key in condition))


def config_digest(layout: Layout = Layout()) -> str:
    return store.sha256_file(layout.config / "detectors.json")


# The code that turns runner results into features and detector scores. `qc/features.py` imports
# `qc/phones.py` and `qc/pitch.py` by name at run time, so they are listed rather than scanned.
SCORING_SOURCES = ("qc/features.py", "qc/detectors.py", "qc/phones.py", "qc/pitch.py")


def scoring_identity(layout: Layout = Layout()) -> dict[str, Any]:
    """`{"sha256", "files", "norms"}`: what scores a take once the runners have run.

    `files` maps `config/qc/detectors.json` and the scoring code (`SCORING_SOURCES` under
    `scripts/`) to their SHA-256 (None for a missing file); `norms` is the newest norms file the
    provisional rules read (`{"file", "sha256"}`, or None). `sha256` covers both. Runs record it in
    `features.json` and fits in the thresholds file: thresholds apply only to features scored by
    the same code, configuration and norms.
    """

    from qc import norms as norms_lib  # qc.norms imports this module

    def digest(path: Any) -> str | None:
        return store.sha256_file(path) if path.is_file() else None

    files = {"config/qc/detectors.json": digest(layout.config / "detectors.json")}
    for relative in SCORING_SOURCES:
        files[f"scripts/{relative}"] = digest(layout.scripts / relative)
    newest = norms_lib.latest(layout)
    norms = {"file": newest.name, "sha256": store.sha256_file(newest)} if newest else None
    return {"sha256": store.sha256_text(store.canonical_json({"files": files, "norms": norms})),
            "files": files, "norms": norms}


def detector_roles(detector: dict[str, Any]) -> set[str]:
    roles: set[str] = set()
    for item in detector["features"]:
        roles.update(FEATURE_ROLES[item["name"].split(".", 1)[0]])
    return roles


def feature_names(config: dict[str, Any]) -> list[str]:
    return sorted({item["name"] for detector in config["detectors"] for item in detector["features"]})


# --- normalization ----------------------------------------------------------------

def normalization(rows: Iterable[dict[str, Any]], names: Iterable[str]) -> dict[str, dict[str, dict[str, float]]]:
    """Per language and feature: mean, standard deviation and median of the present values."""

    values: dict[str, dict[str, list[float]]] = {}
    names = list(names)
    for row in rows:
        bucket = values.setdefault(row.get("language") or "unknown", {})
        for name in names:
            value = (row["features"].get(name) or {}).get("value")
            if value is not None:
                bucket.setdefault(name, []).append(float(value))
    stats: dict[str, dict[str, dict[str, float]]] = {}
    for language, by_name in values.items():
        stats[language] = {}
        for name, items in by_name.items():
            items = sorted(items)
            mean = sum(items) / len(items)
            variance = sum((item - mean) ** 2 for item in items) / len(items)
            middle = len(items) // 2
            median = items[middle] if len(items) % 2 else (items[middle - 1] + items[middle]) / 2
            stats[language][name] = {"mean": mean, "std": math.sqrt(variance), "median": median, "n": len(items)}
    return stats


def oriented(value: float, direction: str) -> float:
    return value if direction == "higher" else -value


def zscore(value: float | None, stats: dict[str, float] | None) -> float | None:
    if value is None or not stats:
        return None
    std = stats["std"]
    return 0.0 if std <= 1e-12 else (value - stats["mean"]) / std


def vector(detector: dict[str, Any], features: dict[str, Any], language: str,
           norm: dict[str, dict[str, dict[str, float]]]) -> tuple[list[float], int]:
    """Oriented z-scores of a detector's features; a missing value takes its language median
    (z close to 0). Returns the vector and how many features were present."""

    stats = norm.get(language, {})
    out, present = [], 0
    for item in detector["features"]:
        value = (features.get(item["name"]) or {}).get("value")
        column = stats.get(item["name"])
        if value is not None:
            present += 1
        elif column:
            value = column["median"]
        z = zscore(value, column)
        out.append(0.0 if z is None else oriented(z, item["direction"]))
    return out, present


def sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1.0 + exp)


def uncalibrated(detector: dict[str, Any], features: dict[str, Any], language: str,
                 norm: dict[str, dict[str, dict[str, float]]]) -> float | None:
    stats = norm.get(language, {})
    scores = []
    for item in detector["features"]:
        z = zscore((features.get(item["name"]) or {}).get("value"), stats.get(item["name"]))
        if z is not None:
            scores.append(oriented(z, item["direction"]))
    return max(scores) if scores else None


def language_norms(norms: dict[str, Any] | None, language: str | None) -> dict[str, Any]:
    """One language's percentiles from a norms document (`qc.norms`), keyed by feature."""

    return ((norms or {}).get("languages") or {}).get(language or "", {}) or {}


def condition_threshold(condition: dict[str, Any], norms: dict[str, Any] | None = None) -> float | None:
    """What a condition compares against: its language's `norm` percentile (of `normFeature`, else
    of its own feature) when `norms` (one language's) hold it, bounded by `atLeast` and `atMost`;
    else its fixed `value`; else None."""

    key = condition.get("norm")
    stats = _norm_stats(condition, norms) if key else {}
    if key and stats.get(key) is not None:
        value = float(stats[key])
        if "atLeast" in condition:
            value = max(value, float(condition["atLeast"]))
        if "atMost" in condition:
            value = min(value, float(condition["atMost"]))
        return value
    return None if condition.get("value") is None else float(condition["value"])


def _norm_stats(condition: dict[str, Any], norms: dict[str, Any] | None) -> dict[str, Any]:
    return (norms or {}).get(condition.get("normFeature") or condition["feature"]) or {}


def _condition(condition: dict[str, Any], features: dict[str, Any], norms: dict[str, Any] | None) -> bool:
    value = (features.get(condition["feature"]) or {}).get("value")
    threshold = condition_threshold(condition, norms)
    return value is not None and threshold is not None and RULE_OPS[condition["op"]](value, threshold)


def rule_holds(rule: dict[str, Any], features: dict[str, Any], norms: dict[str, Any] | None = None) -> bool | None:
    """A provisional rule: every `all`, at least one `any` (when given), no `none` condition.
    `norms` are the take's language's (`language_norms`). None when an `all` condition, or every
    `any` condition, lacks its feature or its threshold (a norm-only condition without norms)."""

    def missing(condition: dict[str, Any]) -> bool:
        return ((features.get(condition["feature"]) or {}).get("value") is None
                or condition_threshold(condition, norms) is None)

    if any(missing(condition) for condition in rule.get("all", [])):
        return None
    if rule.get("any") and all(missing(condition) for condition in rule["any"]):
        return None
    holds = all(_condition(condition, features, norms) for condition in rule.get("all", []))
    if rule.get("any"):
        holds = holds and any(_condition(condition, features, norms) for condition in rule["any"])
    return holds and not any(_condition(condition, features, norms) for condition in rule.get("none", []))


def rule_thresholds(rule: dict[str, Any], norms: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The resolved conditions of a rule, for a flag's record: feature, op, threshold, and the norm
    (`<feature>:<percentile>`) when it set the threshold."""

    resolved = []
    for kind in ("all", "any", "none"):
        for condition in rule.get(kind, []):
            threshold = condition_threshold(condition, norms)
            key = condition.get("norm")
            from_norm = bool(key) and _norm_stats(condition, norms).get(key) is not None
            source = f"{condition.get('normFeature') or condition['feature']}:{key}" if from_norm else None
            resolved.append({"when": kind, "feature": condition["feature"], "op": condition["op"],
                             "threshold": None if threshold is None else round(threshold, 6), "norm": source})
    return resolved


def score(detector: dict[str, Any], features: dict[str, Any], language: str,
          fitted: dict[str, Any] | None, norm: dict[str, dict[str, dict[str, float]]], *,
          norms: dict[str, Any] | None = None) -> dict[str, Any]:
    """`{"score", "cut", "scope", "present"}`. A fitted detector scores with its model and cut; an
    unfitted one with its provisional rule (score 1 or 0, cut 1, scope "provisional", and the
    resolved `rule`) when it has one, else uncalibrated with no cut. `norm` holds the z-score
    statistics; `norms` is a norms document whose percentiles the rule conditions may read."""

    names = [item["name"] for item in detector["features"]]
    present = sum(1 for name in names if (features.get(name) or {}).get("value") is not None)
    models = (fitted or {}).get("models") or {}
    model = models.get(language) or models.get("*")
    if not fitted or not model or present == 0:
        rule = detector.get("provisional")
        own = language_norms(norms, language)
        holds = rule_holds(rule, features, own) if rule else None
        if holds is not None:
            return {"score": 1.0 if holds else 0.0, "cut": 1.0, "scope": "provisional", "present": present,
                    "rule": rule_thresholds(rule, own)}
        return {"score": uncalibrated(detector, features, language, norm) if present else None,
                "cut": None, "scope": None, "present": present}
    scope = language if language in models else "*"
    values, _ = vector(detector, features, language, norm)
    logit = model["intercept"] + sum(weight * value for weight, value in zip(model["weights"], values))
    return {"score": sigmoid(logit), "cut": model["cut"], "scope": scope, "present": present}


def evidence(detector: dict[str, Any], features: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for item in detector["features"]:
        entry = features.get(item["name"]) or {}
        if entry.get("value") is not None:
            out.append({"feature": item["name"], "value": entry["value"], "start": entry.get("start"),
                        "end": entry.get("end")})
    return out
