"""The detector registry and per-take detector scores (AQ-07, audit sections 5.5-5.7).

`config/audio-qc-detectors.json` declares each detector as `id@version`: its
class and stage, its score (components read from a Fast QC or Stage 0 field of
`measurements.json`, from a panel judge's metrics, from a judge's private
transcript aligned against the reference, or from a judge's raw output reduced
here), how the components combine, its direction, its strata (one threshold per
language, with the reason declared in advance, or one pooled threshold), its
language scope with a reason per exclusion, the injectors and severities its
detection rate is measured on with their matched shams, and its population
roles. Nothing here reads a file or runs a model: the callers load the
registry, the evidence, the private transcripts and the raw outputs and pass
them in.

`raw-output` components reduce a panel judge's raw (L1) output, which the
bundle does not keep, to a measure the panel's L2 metrics lack (`RAW_MEASURES`
names the engine whose output each reads). pYIN's frame track gives
`maxPitchStepSemitones`, the largest F0 change between voiced frames at most
50 ms apart, and `longestOctaveDisplacementSeconds`, the longest run of voiced
frames an octave's worth (9 semitones or more) from the take's median F0
(class F). A `raw-output` component of a deterministic DSP instrument (a `dsp`
judge with no learned weights, such as pYIN) is a measurement, not a family's
vote: it may stand alone in a `single` group when it is not from the
generator's lab and is at least shadow. Any other judge still decides a take
only if the registry says it votes (A6).

Combinations:

- `single`: one component.
- `consensus-min` (direction `above`): the smaller of two independent families'
  scores, so the take alarms only when both do.
- `consensus-max` (direction `below`): the larger of two, so both must be low.
- `difference`: the first component minus the second. The second may be a
  non-voting timing instrument (the same-lab aligner) only where the group
  requires both content voters of the language to have completed, which is
  the aligner's registry condition ("supplied only to detectors that already
  have content consensus").

A consensus component must come from a voting judge of its own family that is
not correlated with the generator's lab (A6), and both components of a group
must be in the judges' declared language scope. A panel judge whose registry
entry lists no languages (the speaker families, pYIN) runs on every take, so
it covers every product language. A `difference` may subtract two metrics of
one voting judge (class E: CAM++'s whole-take cosine minus a window's), so each
take is its own baseline.

`trailing_unmatched` compares a transcript with its reference on the primary
units of `lib/language_metrics.py` (words, or characters in zh, ja and ko) and
`edit_metrics`'s unit costs. It anchors the last matched reference unit as early
as any minimum-cost alignment that matches a unit allows and counts the
reference units after it (see its docstring): a definition over the set of
optimal alignments, so no backtrace tie order can pin a recurring last word to
a later occurrence.

`scoring_code_sha256` digests the code a score depends on (this module,
`language_metrics` and its normalization data); a plan binds it (A7).
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from lib import language_metrics

from .pcm import json_digest

REGISTRY_KIND = "audio-qc-detector-registry"
REGISTRY_SCHEMA_VERSION = 1
COMBINATIONS = ("single", "consensus-min", "consensus-max", "difference")
SOURCES = ("fastqc", "observations", "panel", "transcript-tail", "raw-output")
MEASUREMENT_SOURCES = frozenset({"fastqc", "observations"})
PANEL_SOURCES = frozenset({"panel", "transcript-tail", "raw-output"})
TRANSFORMS = ("absolute",)
TAIL_MEASURES = ("trailingUnmatchedFraction", "trailingUnmatched", "trailingDeletions")
# What this module reduces from a panel judge's raw (L1) output -> the engine whose output it reads
# (the judge registry's execution.engine).
RAW_MEASURES = {
    "maxPitchStepSemitones": "pyin-librosa",
    "longestOctaveDisplacementSeconds": "pyin-librosa",
}
# Pitch-track reductions (class F): voiced frames compared up to this far apart, and the distance from
# the take's median F0 that counts as an octave displacement.
PITCH_STEP_WINDOW_SECONDS = 0.05
OCTAVE_DISPLACEMENT_SEMITONES = 9.0
DIRECTIONS = ("above", "below")
CLASSES = tuple("ABCDEFGHIJ")
STAGES = (0, 1, 2)
TARGET_SEVERITIES = ("mild", "moderate", "severe")
MECHANISMS = ("T1-pcm-construction", "T1-parallel-corpus", "T2-codec-construction", "T3-controlled-generation")
POPULATIONS = ("N1", "N2", "N3", "S", "P1", "P2", "P3", "P4")
# A declared stratum gets its own threshold (audit 5.5: stratify only for a reason declared in advance).
STRATA = ("language",)
POOLED = "pooled"
ROLE_KEYS = ("fit", "confirmNegatives", "positives", "shams", "informational")
QUALIFYING_JUDGE_STATUSES = frozenset({"shadow", "warn", "gating"})
# The Stage 0 judge measurements.json speaks for (Fast QC v8 and its observations).
STAGE0_JUDGE = "fastqc@8"
# The Fast QC v8 numeric fields measurements.json keeps (scripts/audio_qc_calibration_set.py FASTQC_FIELDS).
FASTQC_SCORE_FIELDS = frozenset({
    "rmsDBFS", "dcOffset", "peak", "clippedSamples", "hotSamples", "nonFiniteSamples", "clickEvents",
    "longestSilenceMS", "trailingSilenceMS", "stepBurstPeakCount", "stepBurstPeakStartMS", "durationSeconds",
    "expectedPauseCount", "speakingRateTextUnits", "secondsPerTextUnit", "clickEventCount",
    "lowEnergyClickEventCount", "clickEventsPerSecond",
})
_DETECTOR_ID = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)+@[1-9][0-9]*$")
_INJECTOR_ID = re.compile(r"^[A-Z]{2,5}-[A-Z]{2,8}$")
_CODE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
_METRIC = re.compile(r"^[A-Za-z][A-Za-z0-9._]{0,63}$")


class DetectorError(ValueError):
    """A registry entry, an evidence shape or a score that the calibration refuses."""


def definition_digest(entry: Mapping[str, Any]) -> str:
    """The digest a plan binds (A7): any change to the entry makes a new definition."""
    return json_digest(dict(entry))


def scoring_sources() -> tuple[Path, ...]:
    """The files whose bytes decide a take's score: this module, language_metrics and its data."""
    return (Path(__file__).resolve(), Path(language_metrics.__file__).resolve(),
            *(Path(path).resolve() for path in language_metrics.NORMALIZATION_DATA_FILES))


def scoring_code_sha256() -> str:
    """One digest over the scoring sources (name and bytes of each), which a plan binds (A7).

    A module-source digest: any edit to these files between a plan and its
    confirmation makes the confirmation refuse, whether or not it moves a score.
    """
    digest = hashlib.sha256()
    for path in scoring_sources():
        digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def detector_entry(registry: Mapping[str, Any], detector: str) -> dict:
    for entry in registry.get("detectors") or ():
        if isinstance(entry, Mapping) and entry.get("id") == detector:
            return dict(entry)
    raise DetectorError(f"{detector} is not in the detector registry")


def role_set(registry: Mapping[str, Any], entry: Mapping[str, Any]) -> dict:
    roles = (registry.get("roleSets") or {}).get(entry.get("populations"))
    if not isinstance(roles, Mapping):
        raise DetectorError(f"{entry.get('id')}: unknown population role set {entry.get('populations')!r}")
    return dict(roles)


def components_of(entry: Mapping[str, Any]) -> list[dict]:
    """Every component of every group, once each."""
    seen: dict[str, dict] = {}
    for group in (entry.get("score") or {}).get("groups") or ():
        for component in group.get("components") or ():
            seen.setdefault(json_digest(component), dict(component))
    return list(seen.values())


def component_judge(component: Mapping[str, Any]) -> str:
    return STAGE0_JUDGE if component.get("source") in MEASUREMENT_SOURCES else str(component.get("judge"))


def component_key(component: Mapping[str, Any]) -> str:
    """A stable name for one component in the scores: judge and what it reads."""
    what = component.get("field") or component.get("metric") or component.get("measure")
    return f"{component_judge(component)}:{component.get('source')}:{what}"


def judges_of(entry: Mapping[str, Any]) -> list[str]:
    judges = {component_judge(component) for component in components_of(entry)}
    for group in (entry.get("score") or {}).get("groups") or ():
        judges.update(group.get("requiresComplete") or ())
    return sorted(judges)


def needs_measurements(entry: Mapping[str, Any]) -> bool:
    return any(component.get("source") in MEASUREMENT_SOURCES for component in components_of(entry))


def needs_panel(entry: Mapping[str, Any]) -> bool:
    return any(component.get("source") in PANEL_SOURCES for component in components_of(entry))


def needs_private(entry: Mapping[str, Any]) -> bool:
    return any(component.get("source") == "transcript-tail" for component in components_of(entry))


def needs_raw(entry: Mapping[str, Any]) -> bool:
    """The detector reduces a judge's raw (L1) output, which the caller exports and passes as `raw`."""
    return any(component.get("source") == "raw-output" for component in components_of(entry))


def group_for(entry: Mapping[str, Any], language: str) -> dict | None:
    for group in (entry.get("score") or {}).get("groups") or ():
        if language in (group.get("languages") or ()):
            return dict(group)
    return None


def in_scope(entry: Mapping[str, Any], language: str) -> bool:
    return language in ((entry.get("scope") or {}).get("languages") or ())


def strata_by(entry: Mapping[str, Any]) -> str | None:
    """The key the detector declares its thresholds per (`language`), or None for one pooled threshold."""
    strata = entry.get("strata")
    return None if strata is None else strata["by"]


def stratum(by: str | None, language: str) -> str:
    return POOLED if by is None else language


# --------------------------------------------------------------------------- #
# Registry validation
# --------------------------------------------------------------------------- #

def _judge_languages(judge: Mapping[str, Any]) -> set[str]:
    """The product languages a panel judge runs on: those its `panel.languages` lists, or every product
    language when its `panel` entry lists none (a language-free judge such as the speaker families or
    pYIN, which `panel_jobs.judge_scope` schedules on every take); a judge without a `panel` entry
    covers none."""
    panel = judge.get("panel")
    if isinstance(panel, Mapping) and not isinstance(panel.get("languages"), Mapping):
        return set(language_metrics.PRODUCT_LANGUAGES)
    codes = {code: name for name, code in language_metrics.LANGUAGE_LOCALE_CODES.items()}
    languages: set[str] = set()
    for values in ((judge.get("panel") or {}).get("languages") or {}).values():
        languages.update(codes.get(value, value) for value in values or ())
    return languages


def _component_errors(component: Any, where: str, judges: Mapping[str, Any]) -> list[str]:
    if not isinstance(component, Mapping):
        return [f"{where} must be an object"]
    source = component.get("source")
    errors: list[str] = []
    allowed = {"source", "transform"}
    if source in MEASUREMENT_SOURCES:
        allowed.add("field")
        field = component.get("field")
        if source == "fastqc" and field not in FASTQC_SCORE_FIELDS:
            errors.append(f"{where}.field must be a Fast QC v8 field measurements.json keeps")
        if source == "observations" and field not in {name for name, _ in _observation_measures()}:
            errors.append(f"{where}.field must be a Stage 0 observation measurements.json keeps")
    elif source in PANEL_SOURCES:
        allowed.update({"judge", "metric"} if source == "panel" else {"judge", "measure"})
        judge = component.get("judge")
        if judge not in judges:
            errors.append(f"{where}.judge {judge!r} is not in config/audio-qc-judges.json")
        if source == "panel" and not _METRIC.fullmatch(str(component.get("metric") or "")):
            errors.append(f"{where}.metric must name a panel metric")
        if source == "transcript-tail" and component.get("measure") not in TAIL_MEASURES:
            errors.append(f"{where}.measure must be one of {TAIL_MEASURES}")
        if source == "raw-output":
            measure = component.get("measure")
            if measure not in RAW_MEASURES:
                errors.append(f"{where}.measure must be one of {tuple(RAW_MEASURES)}")
            elif isinstance(judges.get(judge), Mapping) \
                    and (judges[judge].get("execution") or {}).get("engine") != RAW_MEASURES[measure]:
                errors.append(f"{where}: {measure} reduces the raw output of a {RAW_MEASURES[measure]} judge, "
                              f"not {judge}'s")
    else:
        return [f"{where}.source must be one of {SOURCES}"]
    if component.get("transform") is not None and component.get("transform") not in TRANSFORMS:
        errors.append(f"{where}.transform must be one of {TRANSFORMS}")
    extra = set(component) - allowed
    if extra:
        errors.append(f"{where} has unknown keys {sorted(extra)}")
    return errors


def _observation_measures() -> tuple[tuple[str, str], ...]:
    from lib import audio_qc  # deferred: numpy-backed, only the validator needs its field map
    return tuple(audio_qc.QC_SIGNAL_METRIC_MAP)


def _voter_errors(judge_id: str, judges: Mapping[str, Any], where: str) -> list[str]:
    judge = judges.get(judge_id)
    if not isinstance(judge, Mapping):
        return []
    errors = []
    if not judge.get("voting"):
        errors.append(f"{where}: {judge_id} does not vote, so it cannot be a consensus family (A6)")
    if (judge.get("independence") or {}).get("generatorLabCorrelated"):
        errors.append(f"{where}: {judge_id} shares the generator's lab and never votes (A6)")
    if judge.get("status") not in QUALIFYING_JUDGE_STATUSES:
        errors.append(f"{where}: {judge_id} is {judge.get('status')}, below shadow")
    return errors


def _is_instrument(judge: Any) -> bool:
    """A deterministic DSP measurement with no learned weights (pYIN): no family, no training labels."""
    return isinstance(judge, Mapping) and judge.get("kind") == "dsp" \
        and (judge.get("pins") or {}).get("digestStatus") == "no-learned-weights"


def _instrument_errors(judge_id: str, judges: Mapping[str, Any], where: str) -> list[str]:
    """A DSP instrument's raw output may score a `single` detector alone: not same-lab, at least shadow."""
    judge = judges.get(judge_id)
    if not isinstance(judge, Mapping):
        return []
    errors = []
    if (judge.get("independence") or {}).get("generatorLabCorrelated"):
        errors.append(f"{where}: {judge_id} shares the generator's lab and never decides a take (A6)")
    if judge.get("status") not in QUALIFYING_JUDGE_STATUSES:
        errors.append(f"{where}: {judge_id} is {judge.get('status')}, below shadow")
    return errors


def _group_errors(entry: Mapping[str, Any], group: Any, where: str, judges: Mapping[str, Any]) -> list[str]:
    if not isinstance(group, Mapping):
        return [f"{where} must be an object"]
    errors: list[str] = []
    combination = (entry.get("score") or {}).get("combination")
    components = group.get("components")
    if not isinstance(components, list) or not components:
        return [f"{where}.components must be a non-empty list"]
    for index, component in enumerate(components):
        errors.extend(_component_errors(component, f"{where}.components[{index}]", judges))
    if errors:
        return errors
    languages = group.get("languages")
    if not isinstance(languages, list) or not languages or len(set(languages)) != len(languages):
        errors.append(f"{where}.languages must be a non-empty list without repeats")
        languages = []
    wanted = 1 if combination == "single" else 2
    if len(components) != wanted:
        errors.append(f"{where}: a {combination} group has {wanted} component(s)")
        return errors
    panel_judges = [component["judge"] for component in components if component["source"] in PANEL_SOURCES]
    for judge_id in panel_judges:
        scope = _judge_languages(judges.get(judge_id) or {})
        missing = sorted(set(languages) - scope)
        if missing:
            errors.append(f"{where}: {judge_id} does not cover {missing}")
    required = group.get("requiresComplete", [])
    if not isinstance(required, list) or any(judge not in judges for judge in required):
        errors.append(f"{where}.requiresComplete must list registry judges")
        required = []
    if set(group) - {"languages", "components", "requiresComplete"}:
        errors.append(f"{where} has unknown keys")
    if combination in ("consensus-min", "consensus-max"):
        first, second = (component_judge(component) for component in components)
        if first == second:
            errors.append(f"{where}: consensus needs two judges")
        for judge_id in (first, second):
            errors.extend(_voter_errors(judge_id, judges, where))
        families = [(judges.get(judge_id) or {}).get("family") for judge_id in (first, second)]
        if None in families or families[0] == families[1]:
            errors.append(f"{where}: consensus needs two recognizer families, got {families}")
    elif combination == "single":
        if panel_judges and components[0]["source"] == "raw-output" and _is_instrument(judges.get(panel_judges[0])):
            errors.extend(_instrument_errors(panel_judges[0], judges, where))
        elif panel_judges:
            errors.extend(_voter_errors(panel_judges[0], judges, where))
    elif combination == "difference":
        errors.extend(_voter_errors(component_judge(components[0]), judges, where))
        timing = judges.get(component_judge(components[1])) or {}
        if not timing.get("voting"):
            voters = [judge_id for judge_id in required if not _voter_errors(judge_id, judges, where)]
            families = {(judges.get(judge_id) or {}).get("family") for judge_id in voters}
            if len(voters) < 2 or len(families) < 2:
                errors.append(f"{where}: a non-voting timing component needs two completed content voters "
                              "of different families (requiresComplete)")
            for judge_id in required:
                scope = _judge_languages(judges.get(judge_id) or {})
                if set(languages) - scope:
                    errors.append(f"{where}: requiresComplete judge {judge_id} does not cover the group")
    return errors


def registry_errors(registry: Any, judges_registry: Mapping[str, Any]) -> list[str]:
    """Every problem in the detector registry; empty when it is valid."""
    if not isinstance(registry, Mapping):
        return ["the detector registry must be an object"]
    errors: list[str] = []
    if registry.get("kind") != REGISTRY_KIND or registry.get("schemaVersion") != REGISTRY_SCHEMA_VERSION:
        errors.append(f"the registry declares kind {REGISTRY_KIND} and schemaVersion {REGISTRY_SCHEMA_VERSION}")
    judges = judges_registry.get("judges") or {}
    catalogs = {}
    for name in ("limitations", "risks", "exclusionReasons"):
        value = registry.get(name)
        if not isinstance(value, Mapping) or any(not _CODE.fullmatch(str(key)) or not isinstance(text, str)
                                                 or not text.strip() for key, text in value.items()):
            errors.append(f"{name} must map codes to statements")
            value = {}
        catalogs[name] = value
    role_sets = registry.get("roleSets")
    if not isinstance(role_sets, Mapping) or not role_sets:
        errors.append("roleSets must name at least one set of population roles")
        role_sets = {}
    for name, roles in role_sets.items():
        if not isinstance(roles, Mapping) or set(roles) != set(ROLE_KEYS):
            errors.append(f"roleSets.{name} declares exactly {ROLE_KEYS}")
            continue
        for key in ROLE_KEYS[:-1]:
            role = roles[key]
            if not isinstance(role, Mapping) or role.get("population") not in POPULATIONS \
                    or role.get("cohort") not in ("calibration", "confirmation"):
                errors.append(f"roleSets.{name}.{key} names a population and a cohort")
        if roles["fit"].get("cohort") != "calibration" or roles["confirmNegatives"].get("cohort") != "confirmation":
            errors.append(f"roleSets.{name}: fit is on the calibration cohort, confirmation on the other")
        if roles["positives"].get("cohort") != "confirmation" or roles["shams"].get("cohort") != "confirmation":
            errors.append(f"roleSets.{name}: positives and shams are built on the confirmation cohort")
        if not isinstance(roles["informational"], list) or not set(roles["informational"]) <= set(POPULATIONS):
            errors.append(f"roleSets.{name}.informational lists populations")
    detectors = registry.get("detectors")
    if not isinstance(detectors, list) or not detectors:
        return errors + ["detectors must be a non-empty list"]
    seen: set[str] = set()
    product = set(language_metrics.PRODUCT_LANGUAGES)
    for index, entry in enumerate(detectors):
        where = f"detectors[{index}]"
        if not isinstance(entry, Mapping):
            errors.append(f"{where} must be an object")
            continue
        detector = entry.get("id")
        if not isinstance(detector, str) or not _DETECTOR_ID.fullmatch(detector):
            errors.append(f"{where}.id must be a dotted id@version")
            continue
        where = detector
        if detector in seen:
            errors.append(f"{where} is declared twice")
        seen.add(detector)
        expected = {"id", "class", "stage", "measures", "score", "direction", "strata", "scope", "targets",
                    "shams", "populations", "limitations", "risks"}
        if set(entry) != expected:
            errors.append(f"{where} declares exactly {sorted(expected)}")
            continue
        strata = entry["strata"]
        if strata is not None and (not isinstance(strata, Mapping) or set(strata) != {"by", "reason"}
                                   or strata.get("by") not in STRATA or not isinstance(strata.get("reason"), str)
                                   or not strata["reason"].strip()):
            errors.append(f"{where}.strata is null (one pooled threshold) or names a key in {STRATA} and "
                          "the reason declared in advance")
        if entry["class"] not in CLASSES:
            errors.append(f"{where}.class must be one of A-J")
        if isinstance(entry["stage"], bool) or entry["stage"] not in STAGES:
            errors.append(f"{where}.stage must be 0, 1 or 2")
        if not isinstance(entry["measures"], str) or not entry["measures"].strip():
            errors.append(f"{where}.measures describes the score")
        if entry["direction"] not in DIRECTIONS:
            errors.append(f"{where}.direction must be one of {DIRECTIONS}")
        score = entry["score"]
        combination = score.get("combination") if isinstance(score, Mapping) else None
        if combination not in COMBINATIONS or set(score) != {"combination", "unit", "groups"} \
                or not _CODE.fullmatch(str(score.get("unit") or "")):
            errors.append(f"{where}.score declares combination ({COMBINATIONS}), unit and groups")
            continue
        if combination == "consensus-min" and entry["direction"] != "above":
            errors.append(f"{where}: consensus-min alarms only when both are high, so its direction is above")
        if combination == "consensus-max" and entry["direction"] != "below":
            errors.append(f"{where}: consensus-max alarms only when both are low, so its direction is below")
        groups = score.get("groups")
        if not isinstance(groups, list) or not groups:
            errors.append(f"{where}.score.groups must be a non-empty list")
            continue
        grouped: list[str] = []
        for position, group in enumerate(groups):
            errors.extend(_group_errors(entry, group, f"{where}.score.groups[{position}]", judges))
            if isinstance(group, Mapping) and isinstance(group.get("languages"), list):
                grouped.extend(group["languages"])
        if entry["stage"] == 0 and any(component.get("source") in PANEL_SOURCES
                                       for component in components_of(entry)):
            errors.append(f"{where}: a Stage 0 detector reads measurements.json only")
        scope = entry["scope"]
        if not isinstance(scope, Mapping) or set(scope) != {"languages", "exclusions"}:
            errors.append(f"{where}.scope declares languages and exclusions")
            continue
        languages = scope["languages"] if isinstance(scope["languages"], list) else []
        exclusions = scope["exclusions"] if isinstance(scope["exclusions"], list) else []
        excluded = []
        for exclusion in exclusions:
            if not isinstance(exclusion, Mapping) or set(exclusion) != {"language", "reason"} \
                    or exclusion.get("reason") not in catalogs["exclusionReasons"]:
                errors.append(f"{where}.scope.exclusions: each names a language and a declared reason")
                continue
            excluded.append(exclusion["language"])
        if len(set(languages)) != len(languages) or set(languages) & set(excluded) \
                or set(languages) | set(excluded) != product or len(set(excluded)) != len(excluded):
            errors.append(f"{where}.scope: the languages and exclusions partition the ten product languages")
        if len(languages) < 3:
            errors.append(f"{where}.scope: warn needs at least 3 languages")
        if sorted(grouped) != sorted(languages):
            errors.append(f"{where}.score.groups cover exactly the scope's languages, once each")
        targets, shams = entry["targets"], entry["shams"]
        if not isinstance(targets, list) or not targets:
            errors.append(f"{where}.targets must be a non-empty list")
            targets = []
        if not isinstance(shams, list):
            errors.append(f"{where}.shams must be a list")
            shams = []
        target_pairs = set()
        for target in targets:
            if not isinstance(target, Mapping) or set(target) != {"injectorID", "severities", "mechanism"} \
                    or not _INJECTOR_ID.fullmatch(str(target.get("injectorID"))) \
                    or target.get("mechanism") not in MECHANISMS \
                    or not isinstance(target.get("severities"), list) or not target["severities"] \
                    or not set(target["severities"]) <= set(TARGET_SEVERITIES):
                errors.append(f"{where}.targets: each names an injector id, its severities and its mechanism")
                continue
            target_pairs.add((target["injectorID"], target["mechanism"]))
        if not any("severe" in (target.get("severities") or ()) for target in targets if isinstance(target, Mapping)):
            errors.append(f"{where}.targets: warn measures detection on severe defects")
        sham_pairs = set()
        for sham in shams:
            if not isinstance(sham, Mapping) or set(sham) != {"injectorID", "mechanism"}:
                errors.append(f"{where}.shams: each names an injector id and its mechanism")
                continue
            sham_pairs.add((sham["injectorID"], sham["mechanism"]))
        if sham_pairs != target_pairs:
            errors.append(f"{where}: every target injector has its matched sham, and only those (A4)")
        if entry["populations"] not in role_sets:
            errors.append(f"{where}.populations must name a role set")
        for name, catalog in (("limitations", "limitations"), ("risks", "risks")):
            values = entry[name]
            if not isinstance(values, list) or any(value not in catalogs[catalog] for value in values):
                errors.append(f"{where}.{name} must list declared {catalog} codes")
    for name in ("limitations", "risks", "exclusionReasons"):
        used = set()
        for entry in detectors:
            if isinstance(entry, Mapping):
                if name == "exclusionReasons":
                    used.update(exclusion.get("reason") for exclusion in (entry.get("scope") or {}).get("exclusions")
                                or () if isinstance(exclusion, Mapping))
                else:
                    used.update(entry.get(name) or ())
        unused = sorted(set(catalogs[name]) - used)
        if unused:
            errors.append(f"{name} declares codes no detector uses: {unused}")
    return errors


# --------------------------------------------------------------------------- #
# Trailing alignment (class C truncation)
# --------------------------------------------------------------------------- #

def _alignment_path(reference: Sequence[Any], hypothesis: Sequence[Any]) -> list[str]:
    """Operations from start to end (M, S, D, I) on edit_metrics's tie order (for its totals only)."""
    rows, columns = len(reference), len(hypothesis)
    cost = [[0] * (columns + 1) for _ in range(rows + 1)]
    step = [[""] * (columns + 1) for _ in range(rows + 1)]
    for column in range(1, columns + 1):
        cost[0][column], step[0][column] = column, "I"
    for row in range(1, rows + 1):
        cost[row][0], step[row][0] = row, "D"
        for column in range(1, columns + 1):
            same = reference[row - 1] == hypothesis[column - 1]
            best, operation = cost[row - 1][column - 1] + (not same), "M" if same else "S"
            if cost[row - 1][column] + 1 < best:
                best, operation = cost[row - 1][column] + 1, "D"
            if cost[row][column - 1] + 1 < best:
                best, operation = cost[row][column - 1] + 1, "I"
            cost[row][column], step[row][column] = best, operation
    path: list[str] = []
    row, column = rows, columns
    while row or column:
        operation = step[row][column]
        path.append(operation)
        if operation in ("M", "S"):
            row, column = row - 1, column - 1
        elif operation == "D":
            row -= 1
        else:
            column -= 1
    path.reverse()
    return path


def _prefix_costs(reference: Sequence[Any], hypothesis: Sequence[Any]) -> list[list[int]]:
    """cost[i][j]: the edit distance (unit costs) between reference[:i] and hypothesis[:j]."""
    rows, columns = len(reference), len(hypothesis)
    cost = [[column for column in range(columns + 1)]] + [[row] + [0] * columns for row in range(1, rows + 1)]
    for row in range(1, rows + 1):
        for column in range(1, columns + 1):
            cost[row][column] = min(cost[row - 1][column - 1] + (reference[row - 1] != hypothesis[column - 1]),
                                    cost[row - 1][column] + 1, cost[row][column - 1] + 1)
    return cost


def _match_free_costs(reference: Sequence[Any], hypothesis: Sequence[Any]) -> list[list[int]]:
    """cost[i][j]: the cheapest alignment of reference[i:] with hypothesis[j:] that matches no unit
    (every pair it makes is a substitution of two different units, every other unit an insertion or
    a deletion)."""
    rows, columns = len(reference), len(hypothesis)
    cost = [[0] * (columns + 1) for _ in range(rows + 1)]
    for column in range(columns + 1):
        cost[rows][column] = columns - column
    for row in range(rows - 1, -1, -1):
        cost[row][columns] = rows - row
        for column in range(columns - 1, -1, -1):
            best = min(cost[row + 1][column], cost[row][column + 1]) + 1
            if reference[row] != hypothesis[column]:
                best = min(best, cost[row + 1][column + 1] + 1)
            cost[row][column] = best
    return cost


def trailing_unmatched(reference: Sequence[Any], hypothesis: Sequence[Any]) -> dict:
    """Reference units after the last matched one, anchored as early as any optimal alignment allows.

    Among every alignment of minimum edit cost (unit costs, as
    `language_metrics.edit_metrics`) that matches at least one unit, take the
    earliest reference position `k` at which one of them makes its last match:
    the reference units after `k` are the ones no optimal reading of the
    transcript needs to have been spoken. `trailingUnmatched` is
    `len(reference) - k`, the whole reference when no optimal alignment matches
    any unit (an optimal alignment without a match has no last match, so where
    one ties with a matching alignment the match anchors: `[a, b]` heard as
    `[b, c]` scores 0). The definition is over the set of optimal alignments,
    so it does not depend on a backtrace's tie order: a truncated take whose
    last heard word recurs later in the reference is not pinned to that later
    occurrence, while a complete take, whose only optimal alignments match its
    last unit, scores 0. It resolves ties only: a spurious late word that
    matches a later reference unit (a hallucination at the end of the audio)
    lowers the cost strictly and still anchors the tail there. A match at
    (i, j) is the last of an optimal alignment exactly when the prefix cost to
    (i - 1, j - 1) plus the cheapest match-free alignment of the two suffixes
    equals the total.

    `trailingDeletions` counts the trailing units such an alignment deletes
    rather than substitutes (the most, over the alignments anchored at `k`);
    the fraction is over the reference length. The substitution, insertion and
    deletion totals are `edit_metrics`'s own alignment's.
    """
    count, heard = len(reference), len(hypothesis)
    prefix = _prefix_costs(reference, hypothesis)
    suffix = _match_free_costs(reference, hypothesis)
    total = prefix[count][heard]
    anchor, deletions = 0, total - heard
    for row in range(1, count + 1):
        # The suffix after a last match at (row, column) deletes its cost minus the hypothesis units it consumes.
        found = [suffix[row][column] - (heard - column) for column in range(1, heard + 1)
                 if reference[row - 1] == hypothesis[column - 1]
                 and prefix[row - 1][column - 1] + suffix[row][column] == total]
        if found:
            anchor, deletions = row, max(found)
            break
    path = _alignment_path(reference, hypothesis)
    unmatched = count - anchor
    return {
        "referenceUnits": count,
        "trailingUnmatched": unmatched,
        "trailingDeletions": deletions,
        "trailingUnmatchedFraction": (unmatched / count) if count else None,
        "substitutions": path.count("S"), "insertions": path.count("I"), "deletions": path.count("D"),
    }


def primary_units(text: str, language: str) -> list[str]:
    """The units language_metrics scores a language on: characters in zh, ja and ko, words elsewhere."""
    words, characters = language_metrics.scoring_units(text, language)
    return characters if language_metrics.primary_accuracy_metric(language) == "characterErrorRate" else words


def transcript_tail(reference: str, hypothesis: str, language: str) -> dict:
    return trailing_unmatched(primary_units(reference, language), primary_units(hypothesis, language))


# --------------------------------------------------------------------------- #
# Raw-output reductions (class F pitch track)
# --------------------------------------------------------------------------- #

def _pitch_frames(output: Mapping[str, Any]) -> tuple[float, list[tuple[int, float]]] | None:
    """(hop in seconds, [(frame, F0 in semitones)]) of pYIN's voiced frames with a finite, positive F0;
    None when the output is not a frame track (hopSeconds, f0Hz and voiced of one length)."""
    hop = _finite(output.get("hopSeconds"))
    f0, voiced = output.get("f0Hz"), output.get("voiced")
    if hop is None or hop <= 0 or not isinstance(f0, list) or not isinstance(voiced, list) or len(f0) != len(voiced):
        return None
    frames = []
    for frame, (value, flag) in enumerate(zip(f0, voiced)):
        hertz = _finite(value)
        if flag is True and hertz is not None and hertz > 0:
            frames.append((frame, 12.0 * math.log2(hertz)))
    return hop, frames


def max_pitch_step(output: Mapping[str, Any]) -> float | None:
    """The largest F0 change, in semitones, between two voiced frames at most 50 ms apart.

    pYIN's HMM caps a transition at its maxTransitionRate (35.92 octaves per
    second, 4.3 semitones per 10 ms frame), so a pitch break or an octave jump
    spreads over two or three frames, or loses voicing for a frame or two:
    voiced frames up to `PITCH_STEP_WINDOW_SECONDS` apart are compared, whatever
    lies between them. None without two voiced frames that close.
    """
    track = _pitch_frames(output)
    if track is None:
        return None
    hop, frames = track
    reach = int(math.floor(PITCH_STEP_WINDOW_SECONDS / hop + 1e-9))
    best = None
    for position, (frame, tone) in enumerate(frames):
        earlier = position - 1
        while earlier >= 0 and frame - frames[earlier][0] <= reach:
            step = abs(tone - frames[earlier][1])
            if best is None or step > best:
                best = step
            earlier -= 1
    return best


def longest_octave_displacement(output: Mapping[str, Any]) -> float | None:
    """The longest run, in seconds, of consecutive voiced frames at least 9 semitones from the median F0
    of the take's voiced frames: an octave jump holds the displaced register for its span, where
    intonation passes through it. 0.0 when no frame is displaced; None without a voiced frame.
    An unvoiced frame ends a run."""
    track = _pitch_frames(output)
    if track is None or not track[1]:
        return None
    hop, frames = track
    tones = sorted(tone for _, tone in frames)
    middle = len(tones) // 2
    median = tones[middle] if len(tones) % 2 else (tones[middle - 1] + tones[middle]) / 2.0
    longest = run = 0
    previous = None
    for frame, tone in frames:
        displaced = abs(tone - median) >= OCTAVE_DISPLACEMENT_SEMITONES
        run = (run + 1 if previous == frame - 1 else 1) if displaced else 0
        previous = frame
        longest = max(longest, run)
    return longest * hop


RAW_REDUCERS = {
    "maxPitchStepSemitones": max_pitch_step,
    "longestOctaveDisplacementSeconds": longest_octave_displacement,
}


def raw_measure(measure: str, output: Mapping[str, Any]) -> float | None:
    """One `raw-output` measure of a judge's raw output, or None when the output has no value for it."""
    reducer = RAW_REDUCERS.get(measure)
    if reducer is None:
        raise DetectorError(f"unknown raw-output measure {measure!r}")
    return reducer(output)


# --------------------------------------------------------------------------- #
# Scoring one take
# --------------------------------------------------------------------------- #

def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def component_value(component: Mapping[str, Any], *, language: str, clip: Mapping[str, Any] | None = None,
                    measurements: Mapping[str, Mapping[str, Any]] | None = None,
                    private: Mapping[str, Any] | None = None,
                    raw: Mapping[str, Mapping[str, Any]] | None = None) -> tuple[float | None, str | None]:
    """One component's value for one take, or None with the abstention reason.

    `raw` maps a judge id to its raw (L1) output for the take; a `raw-output`
    component also needs the judge's measurement to have completed, so the
    evidence still binds the take's audio and the judge's output identity.
    """
    source = component["source"]
    if source in MEASUREMENT_SOURCES:
        if clip is None:
            return None, "not-measured"
        container = clip.get("fastQC" if source == "fastqc" else "observations") or {}
        value = _finite(container.get(component["field"]))
        if value is None:
            return None, "no-value"
    else:
        measurement = (measurements or {}).get(component["judge"])
        if measurement is None:
            return None, "not-measured"
        status = measurement.get("status")
        if status == "out-of-scope":
            return None, "judge-out-of-scope"
        if status != "complete":
            return None, "judge-unavailable"
        if source == "panel":
            value = _finite((measurement.get("metrics") or {}).get(component["metric"]))
            if value is None:
                return None, "no-value"
        elif source == "raw-output":
            output = (raw or {}).get(component["judge"])
            if not isinstance(output, Mapping):
                return None, "no-raw-output"
            value = _finite(raw_measure(component["measure"], output))
            if value is None:
                return None, "no-value"
        else:
            transcripts = (private or {}).get("transcripts") or {}
            hypothesis, reference = transcripts.get(component["judge"]), (private or {}).get("referenceText")
            if hypothesis is None and (measurement.get("metrics") or {}).get("transcriptEmpty") is True:
                # A completed recognizer that heard nothing keeps no private transcript; it matched no unit,
                # as its error rate of 1.0 already says.
                hypothesis = ""
            if not isinstance(hypothesis, str) or not isinstance(reference, str):
                return None, "no-transcript"
            value = transcript_tail(reference, hypothesis, language)[component["measure"]]
            if value is None:
                return None, "no-value"
            value = float(value)
    if component.get("transform") == "absolute":
        value = abs(value)
    return value, None


def combine(combination: str, values: Sequence[float]) -> float:
    if combination == "single":
        return values[0]
    if combination == "consensus-min":
        return min(values)
    if combination == "consensus-max":
        return max(values)
    if combination == "difference":
        return values[0] - values[1]
    raise DetectorError(f"unknown combination {combination!r}")


def score_take(entry: Mapping[str, Any], language: str, *, clip: Mapping[str, Any] | None = None,
               measurements: Mapping[str, Mapping[str, Any]] | None = None,
               private: Mapping[str, Any] | None = None,
               raw: Mapping[str, Mapping[str, Any]] | None = None) -> dict:
    """A detector's score of one take: {inScope, score, components, abstain}.

    A take outside the detector's languages is out of scope (A1) and never
    scored. Any missing component, or a content voter the group requires that
    did not complete, is an abstention with its reason, never a pass.
    """
    if not in_scope(entry, language):
        return {"inScope": False, "score": None, "components": {}, "abstain": "out-of-scope"}
    group = group_for(entry, language)
    if group is None:
        raise DetectorError(f"{entry.get('id')}: no score group covers {language}")
    for judge in group.get("requiresComplete") or ():
        if ((measurements or {}).get(judge) or {}).get("status") != "complete":
            return {"inScope": True, "score": None, "components": {}, "abstain": "content-voters-incomplete"}
    values: dict[str, float | None] = {}
    reason = None
    for component in group["components"]:
        value, why = component_value(component, language=language, clip=clip, measurements=measurements,
                                     private=private, raw=raw)
        values[component_key(component)] = None if value is None else round(value, 9)
        if value is None and reason is None:
            reason = why
    if reason is not None:
        return {"inScope": True, "score": None, "components": values, "abstain": reason}
    ordered = [values[component_key(component)] for component in group["components"]]
    return {"inScope": True, "score": round(combine(entry["score"]["combination"], ordered), 9),
            "components": values, "abstain": None}


def component_alarm(value: float, threshold: float, direction: str) -> bool:
    """One component's own vote at the detector's threshold."""
    return value > threshold if direction == "above" else value < threshold


def target_cell(entry: Mapping[str, Any], injector_id: str | None, severity: str | None,
                mechanism: str | None) -> str | None:
    """`<injectorID>/<severity>` when the injection is one the detector's detection rate is measured on."""
    for target in entry.get("targets") or ():
        if target["injectorID"] == injector_id and severity in target["severities"] \
                and target["mechanism"] == mechanism:
            return f"{injector_id}/{severity}"
    return None


def sham_of(entry: Mapping[str, Any], injector_id: str | None, mechanism: str | None) -> bool:
    return any(sham["injectorID"] == injector_id and sham["mechanism"] == mechanism
               for sham in entry.get("shams") or ())


def target_mechanism(entry: Mapping[str, Any], injector_id: str | None) -> str | None:
    for item in list(entry.get("targets") or ()) + list(entry.get("shams") or ()):
        if item["injectorID"] == injector_id:
            return item["mechanism"]
    return None


def target_injectors(entry: Mapping[str, Any]) -> set[str]:
    return {item["injectorID"] for item in list(entry.get("targets") or ()) + list(entry.get("shams") or ())}


def declared_cells(entry: Mapping[str, Any]) -> dict[str, set[str]]:
    """mechanism -> the cells the detector declares, for the confirmation's precondition."""
    cells: dict[str, set[str]] = {}
    for target in entry.get("targets") or ():
        for severity in target["severities"]:
            cells.setdefault(target["mechanism"], set()).add(f"{target['injectorID']}/{severity}")
    return cells


def summarize(values: Iterable[float], quantiles: Sequence[float] = (0.01, 0.05, 0.5, 0.95, 0.99)) -> dict:
    """Count, extremes and nearest-rank quantiles of finite values (descriptive only)."""
    ordered = sorted(value for value in values if value is not None and math.isfinite(value))
    if not ordered:
        return {"count": 0}
    result: dict[str, Any] = {"count": len(ordered), "min": ordered[0], "max": ordered[-1]}
    for fraction in quantiles:
        index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
        result[f"q{int(round(fraction * 100)):02d}"] = ordered[index]
    return result
