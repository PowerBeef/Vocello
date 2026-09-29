#!/usr/bin/env python3
"""AQ-07 warn-level qualification of the registered detectors (audit sections 5.4-5.9).

Each detector in `config/audio-qc-detectors.json` is qualified at the policy's
`warn` operating point on two FLEURS-derived N2 cohorts: the calibration
cohort (FLEURS dev) fits the threshold from clean clips only, and the
untouched confirmation cohort (FLEURS test), with the P1 positives and S shams
injected over it, confirms it once. No model runs here; the panel and the
Stage 0 scorer produce the inputs.

Commands:
  scores   --detector ID --role calibration|confirmation|informational --cohort MANIFEST
           [--bundle DIR] [--measurements FILE] [--injection-set FILE]
           [--positive-bundle DIR] [--positive-measurements FILE] --output FILE
           Per-unit scores (family, language, speaker, script, population,
           injector, severity, score or abstention with its reason, and each
           component), ids and digests only. A confirmation role needs the
           detector's committed plan naming that cohort; a cohort a plan names
           as confirmation is never scored under another role.
  plan     --detector ID --calibration-cohort MANIFEST --confirmation-cohort MANIFEST
           --calibration-scores FILE --alpha A [--operating-point warn]
           Write config/audio-qc-preregistrations/<id>.json: the split-conformal
           rule, alpha (below the warn FAR bound), the declared cohort split
           (both manifests by kind and digest, disjoint by family and script,
           the FLEURS speaker limitation) and the bindings (definition,
           calibration scores, policy). Refuses when the confirmation cohort
           already holds scores, a panel bundle or measurements. The lead
           reviews and commits it.
  derive   --detector ID --calibration-scores FILE [--output FILE]
           The split-conformal threshold from the calibration cohort's clean
           N2 scores, one per family, per declared stratum (language) or
           pooled; refuses a plan not committed at HEAD.
  confirm  --detector ID --calibration-scores FILE --confirmation-scores FILE [--n3-scores FILE]
           Once per plan digest: the confirmation N2 negatives, the P1
           positives and the S shams against the warn operating point
           (evaluate_confirmation), with the phi audit of consensus families;
           writes the ledger entry beside the plan and the tracked record
           benchmarks/audio-qc-calibration/<id>/record-<plan digest 16>.json
           (digests, counts, rates with Clopper-Pearson bounds, threshold,
           scope, limitations, verdict; no text or path).
  report   [--scores FILE ...] [--output FILE]
           Markdown across the registry: plan and confirmation status per
           detector, and the calibration score quantiles of the given files.
  validate The registry, every committed plan and ledger entry and every
           record (contract gate).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from lib.qc_pipeline.evidence import privacy_errors  # noqa: E402
from lib.qc_qualification import correlation, detectors as registry_lib, thresholds  # noqa: E402
from lib.qc_qualification.pcm import json_digest  # noqa: E402
from lib.qc_qualification.stats import family_rate  # noqa: E402

REGISTRY = "config/audio-qc-detectors.json"
JUDGES = "config/audio-qc-judges.json"
POLICY = "config/audio-qc-qualification-policy.json"
RECORDS = "benchmarks/audio-qc-calibration"
SCORES_KIND = "audio-qc-detector-scores"
SCORES_SCHEMA = "vocello.audioqc.detector-scores/1"
RECORD_KIND = "audio-qc-calibration-record"
RECORD_SCHEMA = "vocello.audioqc.qc-calibration/1"
MEASUREMENTS_KIND = "audio-qc-calibration-measurements"
INJECTION_SET_KIND = "audio-qc-injection-set"
BUNDLE_SCHEMA = "vocello.audioqc.private-bundle/1"
COHORT_KINDS = {"audio-qc-n2-cohort": "N2", "audio-qc-n1-cohort": "N1", "audio-qc-calibration-takes": "N3"}
FLEURS_KINDS = frozenset({"audio-qc-n2-cohort", "audio-qc-n1-cohort"})
ROLES = ("calibration", "confirmation", "informational")
SUPPORTED_OPERATING_POINTS = ("warn",)
FLEURS_SPEAKER_UNIT = "language:fleurs-unidentified"
FLEURS_DISJOINT_BY = ("family", "script")
MAX_RECORD_BYTES = 64 * 1024
PI_MAX = (0.05, 0.10, 0.20)
SKIPPED_DIRECTORIES = frozenset({"roundtrip", "inputs", "logs", "wav", "evidence", "private", "batches",
                                 "batch-out", "batch-results"})


class CalibrationError(ValueError):
    """An input, a plan or a precondition the qualification refuses."""


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, what: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CalibrationError(f"{what} {Path(path).name} is unreadable: {error}") from error


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


class Repository:
    """The configuration a run reads and the tracked places it writes, under one root."""

    def __init__(self, root: Path = REPO) -> None:
        self.root = Path(root).resolve()
        self.registry_path = self.root / REGISTRY
        self.judges_path = self.root / JUDGES
        self.policy_path = self.root / POLICY
        self.records = self.root / RECORDS
        self.store = thresholds.PreRegistrationStore.repository(self.root)
        self.ledger = thresholds.ConfirmationLedger.repository(self.root)

    def registry(self) -> dict:
        return load_json(self.registry_path, "the detector registry")

    def judges(self) -> dict:
        return load_json(self.judges_path, "the judge registry")

    def policy(self) -> dict:
        return load_json(self.policy_path, "the qualification policy")

    def entry(self, detector: str) -> tuple[dict, dict]:
        registry = self.registry()
        errors = registry_lib.registry_errors(registry, self.judges())
        if errors:
            raise CalibrationError("the detector registry does not validate: " + "; ".join(errors[:3]))
        try:
            return registry, registry_lib.detector_entry(registry, detector)
        except registry_lib.DetectorError as error:
            raise CalibrationError(str(error)) from error

    def check_output(self, path: Path) -> Path:
        """Scores and derivations are raw evidence: never written into the tree outside build/."""
        resolved = Path(path).resolve()
        if resolved.is_relative_to(self.root) and not resolved.is_relative_to(self.root / "build"):
            raise CalibrationError(f"{path} is inside the repository; write scores under build/ (untracked)")
        return resolved


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #

def load_cohort(path: Path) -> dict:
    manifest = load_json(path, "the cohort manifest")
    kind = manifest.get("kind") if isinstance(manifest, dict) else None
    if kind not in COHORT_KINDS:
        raise CalibrationError(f"{Path(path).name} is not a cohort manifest ({sorted(COHORT_KINDS)})")
    digest = manifest.get("manifestDigest")
    if not is_sha256(digest):
        raise CalibrationError(f"{Path(path).name} has no manifestDigest")
    population = COHORT_KINDS[kind]
    takes: dict[str, dict] = {}
    for take in manifest.get("takes") or ():
        if kind == "audio-qc-n1-cohort" and take.get("eligible") is not True:
            continue
        if kind == "audio-qc-n2-cohort" and take.get("eligible") is False:
            continue
        if kind == "audio-qc-calibration-takes" and take.get("status") != "generated":
            continue
        take_id, language = take.get("takeID"), take.get("language")
        if not take_id or not language or not take.get("family"):
            raise CalibrationError(f"{Path(path).name}: a take lacks its id, family or language")
        if kind in FLEURS_KINDS:
            speaker = f"{language}:fleurs-unidentified"
        else:
            speaker = f"voice:{(take.get('voice') or {}).get('id')}"
        takes[take_id] = {"takeID": take_id, "family": take["family"], "language": language,
                          "scriptID": str(take.get("scriptID")), "speaker": speaker}
    if not takes:
        raise CalibrationError(f"{Path(path).name} has no eligible takes")
    return {"kind": kind, "population": population, "manifestDigest": digest, "fileSHA256": file_sha256(path),
            "runID": manifest.get("runID"), "takes": takes, "directory": Path(path).resolve().parent}


def load_measurements(path: Path) -> dict:
    data = load_json(path, "the measurements")
    if not isinstance(data, dict) or data.get("kind") != MEASUREMENTS_KIND or not isinstance(data.get("clips"), list):
        raise CalibrationError(f"{Path(path).name} is not an {MEASUREMENTS_KIND} file")
    return {"clips": data["clips"], "identity": json_digest(data.get("subject") or {}),
            "fileSHA256": file_sha256(path), "clipsSHA256": data.get("clipsSHA256")}


def load_injection_set(path: Path) -> dict:
    data = load_json(path, "the injection set")
    if not isinstance(data, dict) or data.get("kind") != INJECTION_SET_KIND \
            or not isinstance(data.get("entries"), list):
        raise CalibrationError(f"{Path(path).name} is not an {INJECTION_SET_KIND} file")
    return {"entries": data["entries"], "sourceManifest": data.get("sourceManifest") or {},
            "fileSHA256": file_sha256(path), "entriesSHA256": data.get("entriesSHA256")}


class Bundle:
    """A private panel bundle (read-only): evidence and private files, each checked against its digest."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        manifest = load_json(self.directory / "bundle.json", "the panel bundle")
        if not isinstance(manifest, dict) or manifest.get("schema") != BUNDLE_SCHEMA:
            raise CalibrationError(f"{self.directory.name} is not a {BUNDLE_SCHEMA} bundle")
        self.manifest = manifest
        self.takes = {entry["takeID"]: entry for entry in manifest.get("takes") or ()}

    def identity(self) -> dict:
        return {"bundleDigest": self.manifest.get("bundleDigest"), "runID": self.manifest.get("runID"),
                "manifestSHA256": self.manifest.get("manifestSHA256")}

    def _read(self, take_id: str, key: str) -> dict | None:
        entry = self.takes.get(take_id)
        if entry is None:
            return None
        path = self.directory / entry[key]
        if not path.resolve().is_relative_to(self.directory.resolve()):
            raise CalibrationError(f"{self.directory.name}: {take_id} points outside the bundle")
        if file_sha256(path) != entry[f"{key}SHA256"]:
            raise CalibrationError(f"{self.directory.name}: {take_id}'s {key} file differs from its digest")
        return load_json(path, f"the {key} file")

    def measurements(self, take_id: str) -> dict[str, dict] | None:
        evidence = self._read(take_id, "evidence")
        if evidence is None:
            return None
        return {measurement["judge"]: measurement for measurement in evidence.get("measurements") or ()}

    def private(self, take_id: str) -> dict | None:
        return self._read(take_id, "private")


# --------------------------------------------------------------------------- #
# scores
# --------------------------------------------------------------------------- #

def _identities(collected: dict[str, set], measurements: Mapping[str, Mapping] | None, judges: Iterable[str]) -> None:
    for judge in judges:
        measurement = (measurements or {}).get(judge)
        if measurement and measurement.get("outputIdentity"):
            collected.setdefault(judge, set()).add(measurement["outputIdentity"])


def _unit(meta: Mapping[str, Any], scored: Mapping[str, Any], **extra: Any) -> dict:
    unit = {"unitID": meta["takeID"], "family": meta["family"], "language": meta["language"],
            "speaker": meta["speaker"], "scriptID": meta["scriptID"], "population": meta["population"],
            "injectorID": None, "variant": None, "severity": None, "mechanism": None, "cell": None}
    unit.update(extra)
    unit.update(inScope=scored["inScope"], score=scored["score"], components=scored["components"],
                abstain=scored["abstain"])
    return unit


def build_scores(entry: Mapping[str, Any], cohort: Mapping[str, Any], *, role: str,
                 bundle: Bundle | None = None, measurements: Mapping[str, Any] | None = None,
                 injection_set: Mapping[str, Any] | None = None, positive_bundle: Bundle | None = None,
                 positive_measurements: Mapping[str, Any] | None = None) -> dict:
    """Every cohort take's score, then every positive and sham of the detector's injectors."""
    detector = entry["id"]
    if registry_lib.needs_measurements(entry) and measurements is None:
        raise CalibrationError(f"{detector} reads measurements.json: pass --measurements")
    if registry_lib.needs_panel(entry) and bundle is None:
        raise CalibrationError(f"{detector} reads panel evidence: pass --bundle")
    judges = registry_lib.judges_of(entry)
    panel_judges = [judge for judge in judges if judge != registry_lib.STAGE0_JUDGE]
    identities: dict[str, set] = {}
    skipped: Counter = Counter()
    units: list[dict] = []
    clean_clips: dict[str, dict] = {}
    if measurements is not None:
        identities.setdefault(registry_lib.STAGE0_JUDGE, set()).add(measurements["identity"])
        for clip in measurements["clips"]:
            if clip.get("injection") is None and clip.get("population") == cohort["population"]:
                clean_clips[clip.get("sourceTakeID") or clip.get("clipID")] = clip
    for take_id in sorted(cohort["takes"]):
        meta = {**cohort["takes"][take_id], "population": cohort["population"]}
        evidence = bundle.measurements(take_id) if bundle is not None else None
        private = bundle.private(take_id) if bundle is not None and registry_lib.needs_private(entry) \
            and evidence is not None else None
        _identities(identities, evidence, panel_judges)
        scored = registry_lib.score_take(entry, meta["language"], clip=clean_clips.get(take_id),
                                         measurements=evidence if bundle is not None else None, private=private)
        units.append(_unit(meta, scored))
    wanted = registry_lib.target_injectors(entry)
    positives: list[tuple[dict, dict]] = []
    if injection_set is not None:
        source_digest = injection_set["sourceManifest"].get("sha256")
        if source_digest and source_digest not in (cohort["fileSHA256"], cohort["manifestDigest"]):
            raise CalibrationError("the injection set was built on another cohort manifest")
        for item in injection_set["entries"]:
            injection = item.get("injection") or {}
            if injection.get("injectorID") in wanted:
                positives.append((item, injection))
    elif positive_measurements is not None:
        for clip in positive_measurements["clips"]:
            injection = clip.get("injection") or {}
            if clip.get("population") in ("P1", "S") and injection.get("injectorID") in wanted:
                positives.append(({"takeID": clip["clipID"], "sourceTakeID": clip.get("sourceTakeID"),
                                   "family": clip.get("family"), "language": clip.get("language")},
                                  {**injection, "population": clip.get("population")}))
    if positives and positive_bundle is None and positive_measurements is None:
        raise CalibrationError("positives need --positive-bundle or --positive-measurements to be scored")
    if positive_measurements is not None:
        identities.setdefault(registry_lib.STAGE0_JUDGE, set()).add(positive_measurements["identity"])
    injected_clips = {clip.get("clipID"): clip for clip in (positive_measurements or {}).get("clips") or ()
                      if clip.get("injection") is not None}
    for item, injection in positives:
        source = cohort["takes"].get(item.get("sourceTakeID"))
        if source is None:
            raise CalibrationError(f"{item.get('takeID')}: its source take is not in the cohort; positives are "
                                   "built on the cohort they confirm with")
        injector_id = injection.get("injectorID")
        declared = registry_lib.target_mechanism(entry, injector_id)
        mechanism = injection.get("mechanism") or declared
        if mechanism != declared:
            skipped[f"mechanism-mismatch:{injector_id}"] += 1
            continue
        population = injection.get("population")
        if population not in ("P1", "S"):
            raise CalibrationError(f"{item.get('takeID')}: an injection is P1 or S, not {population!r}")
        language = item.get("language") or source["language"]
        meta = {"takeID": item["takeID"], "family": item.get("family") or source["family"], "language": language,
                "speaker": f"{language}:fleurs-unidentified" if cohort["kind"] in FLEURS_KINDS else source["speaker"],
                "scriptID": source["scriptID"], "population": population}
        evidence = positive_bundle.measurements(item["takeID"]) if positive_bundle is not None else None
        private = positive_bundle.private(item["takeID"]) if positive_bundle is not None \
            and registry_lib.needs_private(entry) and evidence is not None else None
        _identities(identities, evidence, panel_judges)
        clip = injected_clips.get(item["takeID"])
        if clip is not None and (clip.get("injection") or {}).get("injectorID") != injector_id:
            raise CalibrationError(f"{item['takeID']}: the measurements and the injection set disagree")
        severity = injection.get("severity")
        cell = registry_lib.target_cell(entry, injector_id, severity, mechanism) if population == "P1" else None
        sham = population == "S" and registry_lib.sham_of(entry, injector_id, mechanism)
        scored = registry_lib.score_take(entry, language, clip=clip,
                                         measurements=evidence if positive_bundle is not None else None,
                                         private=private)
        units.append(_unit(meta, scored, injectorID=injector_id, variant=injection.get("variant"),
                           severity=severity, mechanism=mechanism, cell=cell, sham=bool(sham)))
    by_population = Counter(unit["population"] for unit in units)
    abstained = Counter(unit["abstain"] for unit in units if unit["abstain"])
    document = {
        "schema": SCORES_SCHEMA, "kind": SCORES_KIND,
        "privacy": "ids and digests only: no text, transcript or path",
        "detector": detector, "detectorDefinitionSHA256": registry_lib.definition_digest(entry),
        "class": entry["class"], "direction": entry["direction"], "combination": entry["score"]["combination"],
        "role": role,
        "cohort": {"kind": cohort["kind"], "population": cohort["population"],
                   "manifestDigest": cohort["manifestDigest"], "fileSHA256": cohort["fileSHA256"],
                   "runID": cohort.get("runID"), "takes": len(cohort["takes"])},
        "sources": {
            "bundle": bundle.identity() if bundle else None,
            "measurements": {key: measurements[key] for key in ("fileSHA256", "clipsSHA256", "identity")}
            if measurements else None,
            "injectionSet": {key: injection_set[key] for key in ("fileSHA256", "entriesSHA256")}
            if injection_set else None,
            "positiveBundle": positive_bundle.identity() if positive_bundle else None,
            "positiveMeasurements": {key: positive_measurements[key] for key in ("fileSHA256", "clipsSHA256",
                                                                                 "identity")}
            if positive_measurements else None,
        },
        "judgeIdentities": {judge: sorted(values) for judge, values in sorted(identities.items())},
        "counts": {"units": len(units), "byPopulation": dict(sorted(by_population.items())),
                   "abstained": dict(sorted(abstained.items())), "skipped": dict(sorted(skipped.items()))},
        "units": units,
    }
    document["scoresSHA256"] = json_digest(document)
    return document


def load_scores(path: Path) -> dict:
    document = load_json(path, "the scores")
    if not isinstance(document, dict) or document.get("kind") != SCORES_KIND or document.get("schema") != SCORES_SCHEMA:
        raise CalibrationError(f"{Path(path).name} is not a {SCORES_SCHEMA} file")
    claimed = document.get("scoresSHA256")
    body = {key: value for key, value in document.items() if key != "scoresSHA256"}
    if claimed != json_digest(body):
        raise CalibrationError(f"{Path(path).name} does not match its scoresSHA256 (edited after scoring)")
    return document


def plan_for_cohort(repository: Repository, detector: str) -> thresholds.PreRegistration | None:
    return repository.store.load(detector)


def command_scores(args: argparse.Namespace, repository: Repository) -> int:
    registry, entry = repository.entry(args.detector)
    cohort = load_cohort(args.cohort)
    plan = plan_for_cohort(repository, entry["id"])
    confirmation_digest = plan.cohorts.confirmation.manifest_digest if plan and plan.cohorts else None
    if args.role == "confirmation":
        if plan is None or confirmation_digest != cohort["manifestDigest"]:
            raise CalibrationError("a confirmation cohort is scored only under a plan that names it (A5): "
                                   f"run plan for {entry['id']} first and commit it")
        repository.store.require(plan)
    elif confirmation_digest == cohort["manifestDigest"]:
        raise CalibrationError(f"{entry['id']}'s plan names this cohort as its confirmation cohort; score it with "
                               "--role confirmation")
    if args.role == "calibration" and plan is not None and plan.cohorts \
            and plan.cohorts.calibration.manifest_digest != cohort["manifestDigest"]:
        raise CalibrationError(f"{entry['id']}'s plan pins another calibration cohort")
    if args.role == "calibration" and cohort["population"] != role_population(registry, entry, "fit"):
        raise CalibrationError(f"{entry['id']} fits on {role_population(registry, entry, 'fit')}, "
                               f"not {cohort['population']}")
    output = repository.check_output(args.output)
    document = build_scores(
        entry, cohort, role=args.role,
        bundle=Bundle(args.bundle) if args.bundle else None,
        measurements=load_measurements(args.measurements) if args.measurements else None,
        injection_set=load_injection_set(args.injection_set) if args.injection_set else None,
        positive_bundle=Bundle(args.positive_bundle) if args.positive_bundle else None,
        positive_measurements=load_measurements(args.positive_measurements) if args.positive_measurements else None,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    log(f"scores: {entry['id']} {args.role}: {document['counts']['units']} units "
        f"{document['counts']['byPopulation']}, abstained {document['counts']['abstained']}")
    print(json.dumps({"output": str(output), "scoresSHA256": document["scoresSHA256"],
                      "counts": document["counts"]}, indent=2))
    return 0


def role_population(registry: Mapping[str, Any], entry: Mapping[str, Any], role: str) -> str:
    return registry_lib.role_set(registry, entry)[role]["population"]


# --------------------------------------------------------------------------- #
# plan
# --------------------------------------------------------------------------- #

def scoring_artifacts(directory: Path) -> list[str]:
    """Anything in a cohort directory showing that the cohort was already scored."""
    found: list[str] = []

    def walk(folder: Path, depth: int) -> None:
        try:
            children = sorted(folder.iterdir())
        except OSError:
            return
        for child in children:
            if child.is_dir():
                if child.name.startswith("panel-bundle") and (child / "bundle.json").is_file():
                    found.append(f"{child.relative_to(directory).as_posix()}/bundle.json")
                elif depth < 3 and child.name not in SKIPPED_DIRECTORIES:
                    walk(child, depth + 1)
            elif child.suffix == ".json":
                if child.name == "measurements.json":
                    found.append(child.relative_to(directory).as_posix())
                    continue
                try:
                    with child.open("rb") as handle:
                        head = handle.read(4096)
                except OSError:
                    continue
                if SCORES_KIND.encode("utf-8") in head:
                    found.append(child.relative_to(directory).as_posix())

    walk(Path(directory), 0)
    return found


def _triples(cohort: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    return [(take["family"], take["speaker"], take["scriptID"]) for take in cohort["takes"].values()]


def build_plan(repository: Repository, registry: Mapping[str, Any], entry: Mapping[str, Any], *,
               calibration: Mapping[str, Any], confirmation: Mapping[str, Any], calibration_scores: Mapping[str, Any],
               alpha: float, operating_point: str) -> thresholds.PreRegistration:
    policy = repository.policy()
    if operating_point not in SUPPORTED_OPERATING_POINTS:
        raise CalibrationError(f"this driver pre-registers {SUPPORTED_OPERATING_POINTS} only")
    point = policy["operatingPoints"][operating_point]
    if not 0.0 < alpha < point["farPooledMax"]:
        raise CalibrationError(f"alpha must lie below the {operating_point} FAR bound {point['farPooledMax']} "
                               "to leave margin for the confirmation")
    roles = registry_lib.role_set(registry, entry)
    for cohort, role in ((calibration, "fit"), (confirmation, "confirmNegatives")):
        if cohort["kind"] not in FLEURS_KINDS:
            raise CalibrationError("a declared split pre-registers FLEURS-derived cohorts (N1 or N2) only")
        if cohort["population"] != roles[role]["population"]:
            raise CalibrationError(f"the {role} role is {roles[role]['population']}, not {cohort['population']}")
    if calibration_scores.get("detector") != entry["id"] or calibration_scores.get("role") != "calibration":
        raise CalibrationError("the calibration scores belong to another detector or role")
    if calibration_scores.get("detectorDefinitionSHA256") != registry_lib.definition_digest(entry):
        raise CalibrationError("the calibration scores were computed under another definition of the detector")
    if calibration_scores["cohort"]["manifestDigest"] != calibration["manifestDigest"]:
        raise CalibrationError("the calibration scores are not of the calibration cohort")
    artifacts = scoring_artifacts(confirmation["directory"])
    if artifacts:
        raise CalibrationError("the confirmation cohort already holds scores, a panel bundle or measurements "
                               f"({', '.join(artifacts[:3])}); A5 needs the plan committed before any of them")
    limitations = tuple((code, registry["limitations"][code]) for code in entry["limitations"])
    split = thresholds.CohortSplit(
        calibration=thresholds.CohortReference(calibration["kind"], calibration["manifestDigest"],
                                               roles["fit"].get("corpus", "")),
        confirmation=thresholds.CohortReference(confirmation["kind"], confirmation["manifestDigest"],
                                                roles["confirmNegatives"].get("corpus", "")),
        disjoint_by=FLEURS_DISJOINT_BY, speaker_unit=FLEURS_SPEAKER_UNIT, speaker_claim="lower-bound",
        limitations=limitations)
    bindings = (
        ("calibrationScoresSHA256", calibration_scores["scoresSHA256"]),
        ("detectorDefinitionSHA256", registry_lib.definition_digest(entry)),
        ("operatingPoint", operating_point),
        ("policySHA256", file_sha256(repository.policy_path)),
    )
    strata = () if entry["strata"] is None else ((entry["strata"]["by"], entry["strata"]["reason"]),)
    plan = thresholds.PreRegistration(
        detector=entry["id"], rule="split-conformal", alpha=alpha, direction=entry["direction"],
        confidence=policy["statistics"]["confidence"], population=roles["fit"]["population"],
        strata=strata, cohorts=split, bindings=bindings)
    thresholds.check_cohort_disjointness(plan, _triples(calibration), _triples(confirmation))
    return plan


def command_plan(args: argparse.Namespace, repository: Repository) -> int:
    registry, entry = repository.entry(args.detector)
    plan = build_plan(repository, registry, entry, calibration=load_cohort(args.calibration_cohort),
                      confirmation=load_cohort(args.confirmation_cohort),
                      calibration_scores=load_scores(args.calibration_scores), alpha=args.alpha,
                      operating_point=args.operating_point)
    if repository.ledger.outcome(plan.digest()) is not None:
        raise CalibrationError("this plan was already confirmed")
    existing = repository.store.load(entry["id"])
    if existing is not None and existing != plan:
        raise CalibrationError(f"{entry['id']} already has another plan; a changed plan needs a new detector version")
    path = repository.store.commit(plan)
    print(json.dumps({"plan": str(path.relative_to(repository.root)), "digest": plan.digest(),
                      "next": "review and commit the plan file; derive and confirm refuse it until then"}, indent=2))
    return 0


# --------------------------------------------------------------------------- #
# derive
# --------------------------------------------------------------------------- #

def committed_plan(repository: Repository, entry: Mapping[str, Any]) -> thresholds.PreRegistration:
    plan = repository.store.load(entry["id"])
    if plan is None:
        raise CalibrationError(f"{entry['id']} has no plan in {thresholds.PREREGISTRATION_DIRECTORY.name}/ (A5)")
    repository.store.require(plan)
    if plan.cohorts is None:
        raise CalibrationError("this driver reads plans with declared cohorts")
    if plan.binding("detectorDefinitionSHA256") != registry_lib.definition_digest(entry):
        raise CalibrationError(f"{entry['id']}'s definition changed after its plan (A7): it needs a new version")
    if plan.binding("policySHA256") != file_sha256(repository.policy_path):
        raise CalibrationError("the qualification policy changed after the plan was committed")
    return plan


def _in_scope(units: Iterable[Mapping[str, Any]], population: str, *, clean: bool = True) -> list[dict]:
    return [dict(unit) for unit in units if unit["population"] == population and unit["inScope"]
            and (not clean or unit["injectorID"] is None)]


def plan_strata(plan: thresholds.PreRegistration) -> str | None:
    if not plan.strata:
        return None
    if len(plan.strata) != 1 or plan.strata[0][0] not in registry_lib.STRATA:
        raise CalibrationError(f"this driver derives per {registry_lib.STRATA} stratum or pooled")
    return plan.strata[0][0]


def derivation(repository: Repository, entry: Mapping[str, Any], plan: thresholds.PreRegistration,
               calibration_scores: Mapping[str, Any]) -> dict:
    """One split-conformal threshold per declared stratum (or one pooled), from clean calibration families."""
    if calibration_scores.get("scoresSHA256") != plan.binding("calibrationScoresSHA256"):
        raise CalibrationError("these calibration scores are not the ones the plan binds")
    if calibration_scores["cohort"]["manifestDigest"] != plan.cohorts.calibration.manifest_digest:
        raise CalibrationError("the calibration scores are not of the plan's calibration cohort")
    by = plan_strata(plan)
    negatives = _in_scope(calibration_scores["units"], plan.population)
    wanted = [registry_lib.POOLED] if by is None else list(entry["scope"]["languages"])
    per: dict[str, dict] = {}
    for key in wanted:
        units = [unit for unit in negatives if registry_lib.stratum(by, unit["language"]) == key]
        judged = [(unit["family"], unit["score"]) for unit in units if unit["score"] is not None]
        result = thresholds.derive_threshold(plan, repository.store, judged)
        per[key] = {name: result[name] for name in ("threshold", "rank", "calibrationUnits", "calibrationClips",
                                                     "status", "minimumNegatives")}
        per[key]["abstention"] = family_rate((unit["family"], unit["score"] is None) for unit in units).as_dict()
        per[key]["summary"] = registry_lib.summarize(score for _, score in judged)
    status = "derived" if all(item["status"] == "derived" for item in per.values()) else "insufficient-negatives"
    return {
        "plan": plan.digest(), "detector": plan.detector, "rule": plan.rule, "alpha": plan.alpha,
        "direction": plan.direction, "unit": "source-family", "strata": by or registry_lib.POOLED,
        "status": status, "thresholds": {key: item["threshold"] for key, item in per.items()}, "byStratum": per,
        "calibrationAbstention": family_rate((unit["family"], unit["score"] is None)
                                             for unit in negatives).as_dict(),
    }


def unit_threshold(derived: Mapping[str, Any], language: str) -> float:
    by = None if derived["strata"] == registry_lib.POOLED else derived["strata"]
    value = derived["thresholds"].get(registry_lib.stratum(by, language))
    if value is None:
        raise CalibrationError(f"no threshold for {language}")
    return value


def command_derive(args: argparse.Namespace, repository: Repository) -> int:
    _, entry = repository.entry(args.detector)
    plan = committed_plan(repository, entry)
    result = derivation(repository, entry, plan, load_scores(args.calibration_scores))
    text = json.dumps(result, indent=2, allow_nan=False)
    if args.output:
        output = repository.check_output(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["status"] == "derived" else 1


# --------------------------------------------------------------------------- #
# confirm
# --------------------------------------------------------------------------- #

def _alarm(unit: Mapping[str, Any], derived: Mapping[str, Any]) -> bool | None:
    """The unit's alarm at its stratum's threshold; None when it abstained."""
    if unit["score"] is None:
        return None
    return registry_lib.component_alarm(unit["score"], unit_threshold(derived, unit["language"]),
                                        derived["direction"])


def _scored(unit: Mapping[str, Any], derived: Mapping[str, Any]) -> thresholds.ScoredUnit:
    return thresholds.ScoredUnit(unit["family"], unit["language"], unit["speaker"], unit["scriptID"],
                                 _alarm(unit, derived))


def confirmation_inputs(entry: Mapping[str, Any], units: Sequence[Mapping[str, Any]], population: str) -> dict:
    negatives = _in_scope(units, population)
    positives: dict[str, dict[str, list[dict]]] = {}
    shams: dict[str, list[dict]] = {}
    for unit in units:
        if not unit["inScope"]:
            continue
        if unit["population"] == "P1" and unit["cell"]:
            positives.setdefault(unit["mechanism"], {}).setdefault(unit["cell"], []).append(dict(unit))
        elif unit["population"] == "S" and unit.get("sham"):
            shams.setdefault(unit["mechanism"], []).append(dict(unit))
    return {"negatives": negatives, "positives": positives, "shams": shams}


def preconditions(entry: Mapping[str, Any], inputs: Mapping[str, Any], point: Mapping[str, Any]) -> list[str]:
    """What must hold before the one confirmation starts, counted from ids alone (never from scores)."""
    problems: list[str] = []
    floors = point["minimumUnits"]
    negatives = inputs["negatives"]
    families = {unit["family"] for unit in negatives}
    if len(families) < floors["good"]:
        problems.append(f"{len(families)} N2 negative families, the floor is {floors['good']}")
    for key, floor in (("language", floors["languages"]), ("speaker", floors["speakers"]),
                       ("scriptID", floors["scripts"])):
        count = len({unit[key] for unit in negatives})
        if count < floor:
            problems.append(f"{count} {key} values among the negatives, the floor is {floor}")
    for mechanism, cells in sorted(registry_lib.declared_cells(entry).items()):
        for cell in sorted(cells):
            if cell.rsplit("/", 1)[-1] != "severe":
                continue
            scored = inputs["positives"].get(mechanism, {}).get(cell, [])
            count = len({unit["family"] for unit in scored})
            if count < floors["bad"]:
                problems.append(f"{mechanism} {cell}: {count} positive families, the floor is {floors['bad']}")
        if not inputs["shams"].get(mechanism):
            problems.append(f"{mechanism}: no matched sham (A4)")
    return problems


def phi_audits(entry: Mapping[str, Any], units: Sequence[Mapping[str, Any]], derived: Mapping[str, Any],
               population: str) -> list[dict]:
    """Per consensus group: the two families' failure correlation, each voting at the unit's threshold.

    A family fails a clean negative when its own score alarms, and a target
    positive when it does not; units where either family abstained are left out.
    """
    if entry["score"]["combination"] not in ("consensus-min", "consensus-max"):
        return []
    direction = entry["direction"]
    audits = []
    for group in entry["score"]["groups"]:
        first, second = group["components"]
        keys = (registry_lib.component_key(first), registry_lib.component_key(second))
        a_failed, b_failed, families = [], [], []
        negatives = positives = 0
        for unit in units:
            if not unit["inScope"] or unit["language"] not in group["languages"]:
                continue
            if unit["population"] == population and unit["injectorID"] is None:
                expected = False
                negatives += 1
            elif unit["population"] == "P1" and unit["cell"]:
                expected = True
                positives += 1
            else:
                continue
            values = [unit["components"].get(key) for key in keys]
            if None in values:
                continue
            threshold = unit_threshold(derived, unit["language"])
            a_failed.append(registry_lib.component_alarm(values[0], threshold, direction) != expected)
            b_failed.append(registry_lib.component_alarm(values[1], threshold, direction) != expected)
            families.append(unit["family"])
        judges = (registry_lib.component_judge(first), registry_lib.component_judge(second))
        audit = correlation.failure_correlation(a_failed, b_failed, families=families, judges=judges)
        audits.append({"languages": sorted(group["languages"]), "labeledUnits": {"negatives": negatives,
                                                                                  "positives": positives},
                       **audit})
    return audits


def informational_n3(units: Sequence[Mapping[str, Any]], derived: Mapping[str, Any]) -> dict:
    """Report-only (N3 is unlabeled): the flag rate and the FAR bound f / (1 - pi_max) it implies."""
    n3 = [unit for unit in units if unit["population"] == "N3" and unit["inScope"] and unit["injectorID"] is None]
    flags = family_rate((unit["family"], _alarm(unit, derived)) for unit in n3 if unit["score"] is not None)
    return {"population": "N3", "flagRate": flags.as_dict(),
            "farBound": {str(pi): (None if flags.rate is None else round(flags.rate / (1.0 - pi), 6))
                         for pi in PI_MAX},
            "note": "report-only"}


def _check_pair(plan: thresholds.PreRegistration, calibration: Mapping[str, Any],
                confirmation: Mapping[str, Any]) -> None:
    if confirmation.get("role") != "confirmation" or confirmation.get("detector") != plan.detector:
        raise CalibrationError("the confirmation scores belong to another detector or role")
    if confirmation["cohort"]["manifestDigest"] != plan.cohorts.confirmation.manifest_digest:
        raise CalibrationError("the confirmation scores are not of the plan's confirmation cohort")
    if confirmation.get("detectorDefinitionSHA256") != calibration.get("detectorDefinitionSHA256"):
        raise CalibrationError("the two cohorts were scored under different definitions")
    if confirmation["judgeIdentities"] != calibration["judgeIdentities"]:
        raise CalibrationError("a consumed judge's output identity differs between the cohorts (A7)")
    for judge, values in confirmation["judgeIdentities"].items():
        if len(values) != 1:
            raise CalibrationError(f"{judge} ran under {len(values)} output identities")


def build_record(repository: Repository, entry: Mapping[str, Any], plan: thresholds.PreRegistration, *,
                 derived: Mapping[str, Any], outcome: Mapping[str, Any], calibration: Mapping[str, Any],
                 confirmation: Mapping[str, Any], inputs: Mapping[str, Any], disjointness: Mapping[str, Any],
                 phi: Sequence[Mapping[str, Any]], informational: Mapping[str, Any] | None) -> dict:
    qualified = outcome["status"] == "qualified"

    def counts(units: Iterable[Mapping[str, Any]]) -> dict:
        units = list(units)
        return {"clips": len(units), "families": len({unit["family"] for unit in units}),
                "abstainedClips": sum(1 for unit in units if unit["score"] is None)}

    positives = [unit for cells in inputs["positives"].values() for scored in cells.values() for unit in scored]
    shams = [unit for scored in inputs["shams"].values() for unit in scored]
    calibration_negatives = _in_scope(calibration["units"], plan.population)
    record = {
        "schema": RECORD_SCHEMA, "kind": RECORD_KIND,
        "detector": entry["id"], "class": entry["class"], "stage": entry["stage"],
        "direction": entry["direction"], "combination": entry["score"]["combination"],
        "judges": [{"judge": judge, "outputIdentities": values}
                   for judge, values in sorted(confirmation["judgeIdentities"].items())],
        "operatingPoint": plan.binding("operatingPoint"),
        "verdict": outcome["status"], "level": "warn" if qualified else None, "reasons": list(outcome["reasons"]),
        "planSHA256": plan.digest(),
        "detectorDefinitionSHA256": registry_lib.definition_digest(entry),
        "registries": {"detectorsSHA256": file_sha256(repository.registry_path),
                       "judgesSHA256": file_sha256(repository.judges_path),
                       "policySHA256": file_sha256(repository.policy_path)},
        "cohorts": {
            "calibration": {**plan.cohorts.calibration.as_dict(), "scoresSHA256": calibration["scoresSHA256"]},
            "confirmation": {**plan.cohorts.confirmation.as_dict(), "scoresSHA256": confirmation["scoresSHA256"]},
        },
        # Plural count keys: a tracked record may never carry a key named "script".
        "split": {"method": "declared-cohorts", "disjointBy": list(disjointness["disjointBy"]),
                  "counts": {f"{key}s" if key != "family" else "families": value
                             for key, value in disjointness["counts"].items()}},
        "speakers": {"unit": FLEURS_SPEAKER_UNIT, "claim": plan.cohorts.speaker_claim,
                     "count": len({unit["speaker"] for unit in inputs["negatives"]})},
        "threshold": {"strata": derived["strata"], "values": dict(derived["thresholds"]),
                      "ranks": {key: item["rank"] for key, item in derived["byStratum"].items()},
                      "calibrationUnits": {key: item["calibrationUnits"] for key, item in derived["byStratum"].items()},
                      "alpha": plan.alpha, "rule": plan.rule, "unit": "source-family"},
        "counts": {"calibration": counts(calibration_negatives),
                   "confirmation": {"N2": counts(inputs["negatives"]), "P1": counts(positives), "S": counts(shams)}},
        "rates": {key: outcome[key] for key in ("farPooled", "farPerLanguage", "cleanAbstention", "mechanisms",
                                                "mechanismsMeeting", "mechanismsMin", "shams")},
        "phiAudit": list(phi),
        "scope": {"languages": list(entry["scope"]["languages"]),
                  "exclusions": [dict(item) for item in entry["scope"]["exclusions"]]},
        "limitations": list(entry["limitations"]), "risks": list(entry["risks"]),
        "informational": dict(informational) if informational else None,
        "ledgerOutcomeSHA256": json_digest(dict(outcome)),
    }
    return record


def record_path(repository: Repository, detector: str, plan_digest: str) -> Path:
    return repository.records / detector / f"record-{plan_digest[:16]}.json"


def command_confirm(args: argparse.Namespace, repository: Repository) -> int:
    registry, entry = repository.entry(args.detector)
    plan = committed_plan(repository, entry)
    if repository.ledger.outcome(plan.digest()) is not None:
        raise CalibrationError("this plan was already confirmed; confirmation runs once (A5)")
    calibration = load_scores(args.calibration_scores)
    confirmation = load_scores(args.confirmation_scores)
    derived = derivation(repository, entry, plan, calibration)
    if derived["status"] != "derived":
        short = {key: item["calibrationUnits"] for key, item in derived["byStratum"].items()
                 if item["status"] != "derived"}
        raise CalibrationError(f"no threshold for {short} (calibration families per stratum); "
                               f"{next(iter(derived['byStratum'].values()))['minimumNegatives']} needed")
    _check_pair(plan, calibration, confirmation)
    disjointness = thresholds.check_cohort_disjointness(
        plan, [(unit["family"], unit["speaker"], unit["scriptID"]) for unit in calibration["units"]],
        [(unit["family"], unit["speaker"], unit["scriptID"]) for unit in confirmation["units"]])
    policy = repository.policy()
    point = policy["operatingPoints"][plan.binding("operatingPoint")]
    inputs = confirmation_inputs(entry, confirmation["units"], plan.population)
    problems = preconditions(entry, inputs, point)
    if problems:
        raise CalibrationError("the confirmation cannot start, nothing was recorded: " + "; ".join(problems))
    threshold = dict(derived["thresholds"])
    arguments = dict(
        operating_point=point, confidence=plan.confidence,
        n2_negatives=[_scored(unit, derived) for unit in inputs["negatives"]],
        positives={mechanism: {cell: [_scored(unit, derived) for unit in scored] for cell, scored in cells.items()}
                   for mechanism, cells in inputs["positives"].items()},
        shams={mechanism: [_scored(unit, derived) for unit in scored] for mechanism, scored in inputs["shams"].items()})
    preview = thresholds.evaluate_confirmation(plan, threshold, **arguments)
    phi = phi_audits(entry, confirmation["units"], derived, plan.population)
    informational = informational_n3(load_scores(args.n3_scores)["units"], derived) if args.n3_scores else None
    record = build_record(repository, entry, plan, derived=derived, outcome=preview, calibration=calibration,
                          confirmation=confirmation, inputs=inputs, disjointness=disjointness, phi=phi,
                          informational=informational)
    problems = record_errors(record)
    if problems:
        raise CalibrationError("the record would not validate, nothing was recorded: " + "; ".join(problems[:3]))
    path = record_path(repository, entry["id"], plan.digest())
    if path.exists():
        raise CalibrationError(f"{path.relative_to(repository.root)} already exists")
    outcome = repository.ledger.confirm(plan, repository.store, threshold, **arguments)
    if json_digest(outcome) != record["ledgerOutcomeSHA256"]:
        raise CalibrationError("the ledger outcome differs from the evaluated one")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"verdict": record["verdict"], "reasons": record["reasons"],
                      "record": str(path.relative_to(repository.root)),
                      "ledger": str(repository.ledger.path(plan.digest()).relative_to(repository.root))}, indent=2))
    return 0 if record["verdict"] == "qualified" else 3


# --------------------------------------------------------------------------- #
# Records and validation
# --------------------------------------------------------------------------- #

RECORD_KEYS = frozenset({
    "schema", "kind", "detector", "class", "stage", "direction", "combination", "judges", "operatingPoint",
    "verdict", "level", "reasons", "planSHA256", "detectorDefinitionSHA256", "registries", "cohorts", "split",
    "speakers", "threshold", "counts", "rates", "phiAudit", "scope", "limitations", "risks", "informational",
    "ledgerOutcomeSHA256",
})


def record_errors(record: Any) -> list[str]:
    """Errors in one qc-calibration record; empty when it is complete, consistent and privacy-safe."""
    if not isinstance(record, Mapping) or record.get("schema") != RECORD_SCHEMA or record.get("kind") != RECORD_KIND:
        return [f"a qc-calibration record declares {RECORD_SCHEMA} and kind {RECORD_KIND}"]
    errors: list[str] = []
    if set(record) != RECORD_KEYS:
        errors.append(f"a record holds exactly {sorted(RECORD_KEYS)}")
        return errors
    if record["verdict"] not in ("qualified", "refused"):
        errors.append("verdict is qualified or refused")
    if (record["verdict"] == "qualified") != (not record["reasons"]):
        errors.append("a qualified record has no reasons and a refused one has at least one")
    if record["level"] != ("warn" if record["verdict"] == "qualified" else None):
        errors.append("level is warn for a qualified warn record and null otherwise")
    if record["operatingPoint"] not in SUPPORTED_OPERATING_POINTS:
        errors.append(f"operatingPoint is one of {SUPPORTED_OPERATING_POINTS}")
    for key in ("planSHA256", "detectorDefinitionSHA256", "ledgerOutcomeSHA256"):
        if not is_sha256(record[key]):
            errors.append(f"{key} must be a SHA-256")
    for key, value in (record["registries"] or {}).items():
        if not is_sha256(value):
            errors.append(f"registries.{key} must be a SHA-256")
    for side in ("calibration", "confirmation"):
        cohort = (record["cohorts"] or {}).get(side) or {}
        if not is_sha256(cohort.get("manifestDigest")) or not is_sha256(cohort.get("scoresSHA256")):
            errors.append(f"cohorts.{side} pins its manifest and scores by SHA-256")
    threshold = record["threshold"] or {}
    values = threshold.get("values")
    if not isinstance(values, Mapping) or not values or any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            for value in values.values()):
        errors.append("threshold.values maps each stratum to a finite threshold")
    elif threshold.get("strata") == registry_lib.POOLED and set(values) != {registry_lib.POOLED}:
        errors.append("a pooled threshold has the one value 'pooled'")
    elif threshold.get("strata") == "language" and set(values) != set((record["scope"] or {}).get("languages") or ()):
        errors.append("a per-language threshold covers exactly the scope's languages")
    if not isinstance(record["phiAudit"], list):
        errors.append("phiAudit must be a list")
    elif record["combination"] in ("consensus-min", "consensus-max") and not record["phiAudit"]:
        errors.append("a consensus rule records its phi audit (section 5.7)")
    rates = record["rates"] or {}
    if not isinstance(rates.get("farPooled"), Mapping) or not isinstance(rates.get("mechanisms"), Mapping):
        errors.append("rates carry the pooled FAR and the detection per mechanism")
    errors.extend(privacy_errors(dict(record)))
    size = len(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=True).encode("utf-8"))
    if size > MAX_RECORD_BYTES:
        errors.append(f"a record is at most {MAX_RECORD_BYTES} bytes")
    return errors


def repository_errors(repository: Repository) -> list[str]:
    errors = [f"{REGISTRY}: {problem}"
              for problem in registry_lib.registry_errors(repository.registry(), repository.judges())]
    directory = repository.store.directory
    plans: dict[str, dict] = {}
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            where = f"{path.relative_to(repository.root).as_posix()}"
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                errors.append(f"{where}: unreadable ({error})")
                continue
            if path.name.startswith("confirmation-"):
                digest = path.stem.removeprefix("confirmation-")
                if not isinstance(data, Mapping) or data.get("schema") != thresholds.CONFIRMATION_SCHEMA \
                        or data.get("plan") != digest or data.get("status") not in ("qualified", "refused"):
                    errors.append(f"{where}: a ledger entry names its plan digest and its outcome")
                continue
            try:
                plan = thresholds.PreRegistration.from_dict(data)
            except thresholds.PreRegistrationError as error:
                errors.append(f"{where}: {error}")
                continue
            expected = f"{plan.detector}.json" if not path.name.startswith("plan-") else f"plan-{plan.digest()}.json"
            if path.name != expected:
                errors.append(f"{where}: the file is named {expected}")
            if path.read_text(encoding="utf-8") != json.dumps(plan.as_dict(), indent=2, sort_keys=True) + "\n":
                errors.append(f"{where}: not in the canonical form the store writes")
            plans[plan.digest()] = data
    if repository.records.is_dir():
        for path in sorted(repository.records.glob("*/*.json")):
            where = path.relative_to(repository.root).as_posix()
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                errors.append(f"{where}: unreadable ({error})")
                continue
            problems = record_errors(record)
            errors.extend(f"{where}: {problem}" for problem in problems)
            if problems:
                continue
            if path.parent.name != record["detector"] or path.name != f"record-{record['planSHA256'][:16]}.json":
                errors.append(f"{where}: the record lives at {record['detector']}/record-<plan digest 16>.json")
            if record["planSHA256"] not in plans:
                errors.append(f"{where}: its plan is not committed beside the ledger")
            outcome = repository.ledger.outcome(record["planSHA256"])
            if outcome is None or json_digest(outcome) != record["ledgerOutcomeSHA256"] \
                    or outcome.get("threshold") != record["threshold"]["values"] \
                    or outcome.get("status") != record["verdict"] or outcome.get("reasons") != record["reasons"] \
                    or any(outcome.get(key) != value for key, value in record["rates"].items()):
                errors.append(f"{where}: its ledger entry is missing or differs from it")
    return errors


def command_validate(args: argparse.Namespace, repository: Repository) -> int:
    errors = repository_errors(repository)
    for error in errors:
        print(f"audio-qc detectors: {error}", file=sys.stderr)
    if errors:
        return 1
    registry = repository.registry()
    print(f"audio-qc detectors: {len(registry['detectors'])} detectors, plans and records valid")
    return 0


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #

def _fraction(rate: Mapping[str, Any] | None, bound: str) -> str:
    if not rate or not rate.get("units"):
        return "-"
    return f"{rate['events']}/{rate['units']} ({bound} {rate[bound]:.3f})"


def _describe_score(entry: Mapping[str, Any]) -> str:
    parts = []
    for group in entry["score"]["groups"]:
        names = [registry_lib.component_key(component).split(":", 1)[0] + ":" +
                 str(component.get("field") or component.get("metric") or component.get("measure"))
                 for component in group["components"]]
        parts.append(" & ".join(names) if len(entry["score"]["groups"]) == 1
                     else f"{','.join(language[:2] for language in group['languages'])}: " + " & ".join(names))
    return f"{entry['score']['combination']}({'; '.join(parts)})"


def build_report(repository: Repository, scores: Sequence[Mapping[str, Any]] = ()) -> str:
    registry = repository.registry()
    lines = ["# Audio-QC detector qualification (warn)", "",
             "| Detector | Class | Direction | Strata | Score | Plan | Verdict | N2 FAR (upper) "
             "| Worst language (upper) | Clean abstention | Severe detection (lower) | Shams overlap |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for entry in registry["detectors"]:
        plan = repository.store.load(entry["id"])
        record = None
        if plan is not None:
            path = record_path(repository, entry["id"], plan.digest())
            record = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        status = "none" if plan is None else plan.digest()[:12]
        strata = registry_lib.strata_by(entry) or registry_lib.POOLED
        head = f"| {entry['id']} | {entry['class']} | {entry['direction']} | {strata} | {_describe_score(entry)} "
        if record is None:
            lines.append(f"{head}| {status} | {'planned' if plan else '-'} | - | - | - | - | - |")
            continue
        rates = record["rates"]
        languages = rates["farPerLanguage"]["languages"]
        worst = max(languages.items(), key=lambda item: item[1].get("upper") or 0.0) if languages else None
        detection = "; ".join(f"{cell} {_fraction(entry_rate, 'lower')}"
                              for mechanism in rates["mechanisms"].values()
                              for cell, entry_rate in mechanism["cells"].items()) or "-"
        overlap = ", ".join(f"{name}:{'yes' if sham.get('overlaps') else 'no'}"
                            for name, sham in rates["shams"].items())
        verdict = record["verdict"] + (f" ({', '.join(record['reasons'])})" if record["reasons"] else "")
        lines.append(f"{head}| {status} | {verdict} | {_fraction(rates['farPooled'], 'upper')} "
                     f"| {worst[0] + ' ' + _fraction(worst[1], 'upper') if worst else '-'} "
                     f"| {_fraction(rates['cleanAbstention'], 'upper')} | {detection} | {overlap or '-'} |")
    if scores:
        lines += ["", "## Calibration score quantiles (clean negatives, one row per language)", "",
                  "| Detector | Language | Units | Abstained | min | q01 | q05 | q50 | q95 | q99 | max |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for document in scores:
            units = [unit for unit in document["units"] if unit["injectorID"] is None and unit["inScope"]]
            for language in ["pooled"] + sorted({unit["language"] for unit in units}):
                chosen = units if language == "pooled" else [unit for unit in units if unit["language"] == language]
                summary = registry_lib.summarize(unit["score"] for unit in chosen)
                cells = [f"{summary.get(key):.4g}" if summary.get(key) is not None else "-"
                         for key in ("min", "q01", "q05", "q50", "q95", "q99", "max")]
                abstained = sum(1 for unit in chosen if unit["score"] is None)
                lines.append(f"| {document['detector']} | {language} | {len(chosen)} | {abstained} | "
                             + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def command_report(args: argparse.Namespace, repository: Repository) -> int:
    text = build_report(repository, [load_scores(path) for path in args.scores or ()])
    if args.output:
        output = repository.check_output(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


# --------------------------------------------------------------------------- #

def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    root.add_argument("--repo-root", type=Path, default=REPO, help=argparse.SUPPRESS)
    commands = root.add_subparsers(dest="command", required=True)
    scores = commands.add_parser("scores", help="per-unit detector scores of one cohort")
    scores.add_argument("--detector", required=True)
    scores.add_argument("--role", required=True, choices=ROLES)
    scores.add_argument("--cohort", required=True, type=Path)
    scores.add_argument("--bundle", type=Path)
    scores.add_argument("--measurements", type=Path)
    scores.add_argument("--injection-set", type=Path)
    scores.add_argument("--positive-bundle", type=Path)
    scores.add_argument("--positive-measurements", type=Path)
    scores.add_argument("--output", required=True, type=Path)
    plan = commands.add_parser("plan", help="write the detector's pre-registration")
    plan.add_argument("--detector", required=True)
    plan.add_argument("--calibration-cohort", required=True, type=Path)
    plan.add_argument("--confirmation-cohort", required=True, type=Path)
    plan.add_argument("--calibration-scores", required=True, type=Path)
    plan.add_argument("--alpha", required=True, type=float)
    plan.add_argument("--operating-point", default="warn", choices=SUPPORTED_OPERATING_POINTS)
    derive = commands.add_parser("derive", help="the threshold under the committed plan")
    derive.add_argument("--detector", required=True)
    derive.add_argument("--calibration-scores", required=True, type=Path)
    derive.add_argument("--output", type=Path)
    confirm = commands.add_parser("confirm", help="the one confirmation of the committed plan")
    confirm.add_argument("--detector", required=True)
    confirm.add_argument("--calibration-scores", required=True, type=Path)
    confirm.add_argument("--confirmation-scores", required=True, type=Path)
    confirm.add_argument("--n3-scores", type=Path)
    report = commands.add_parser("report", help="markdown summary across detectors")
    report.add_argument("--scores", type=Path, nargs="*")
    report.add_argument("--output", type=Path)
    commands.add_parser("validate", help="the registry, plans, ledger and records")
    return root


COMMANDS = {"scores": command_scores, "plan": command_plan, "derive": command_derive, "confirm": command_confirm,
            "report": command_report, "validate": command_validate}


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args, Repository(args.repo_root))
    except (CalibrationError, thresholds.PreRegistrationError, registry_lib.DetectorError) as error:
        print(f"audio-qc detectors: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
