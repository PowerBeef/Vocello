#!/usr/bin/env python3
"""AQ-07 warn-level qualification of the registered detectors (audit sections 5.4-5.9).

Each detector in `config/audio-qc-detectors.json` is qualified at the policy's
`warn` operating point on two FLEURS-derived N2 cohorts: the calibration
cohort (FLEURS dev) fits the threshold from clean clips only, and the
untouched confirmation cohort (FLEURS test), with the P1 positives and S shams
injected over it, confirms it once. No model runs here; the panel and the
Stage 0 scorer produce the inputs.

Every input is bound to what it claims to measure: a cohort manifest to its own
`manifestDigest`; a panel bundle to its `bundleDigest`, and each evidence
record to its take's audio digest, text digest and language in the cohort or
the injection set; `measurements.json` to its `clipsSHA256`, the takes manifest
and injection set it names, and each clip's audio digest; an injection set to
its `entriesSHA256` and to the cohort manifest it was built on (always checked).

Commands:
  scores   --detector ID --role calibration|confirmation|informational --cohort MANIFEST
           [--n1-manifest FILE] [--bundle DIR] [--measurements FILE] [--injection-set FILE]
           [--positive-bundle DIR] [--positive-measurements FILE] --output FILE
           Per-unit scores (family, language, speaker, script, population,
           injector, severity, score or abstention with its reason, and each
           component), ids and digests only, with the scoring code's digest and
           the evidence identity (orchestrator source, metric versions). An N2
           cohort names its FLEURS split through the N1 manifest it pins
           (--n1-manifest). Positives are the injection set's entries. A
           confirmation role needs the detector's committed plan naming that
           cohort, the planned injection construction and panels computed from
           scratch after the plan (see confirm); calibration and informational
           roles refuse a FLEURS test cohort and any cohort a plan names as
           confirmation (A5).
  plan     --detector ID --calibration-cohort MANIFEST --confirmation-cohort MANIFEST
           [--confirmation-n1-manifest FILE] --calibration-scores FILE --alpha A
           --injection-catalog-seed N --injection-sample-seed N
           --injection-sample-per-cell N --injection-classes A,B,... [--operating-point warn]
           Write config/audio-qc-preregistrations/<id>.json: the split-conformal
           rule, alpha (below the warn FAR bound), the declared cohort split
           (both manifests by kind and digest, disjoint by family and script,
           the FLEURS speaker limitation) and the bindings (definition,
           calibration scores, policy, scoring code, evidence identity, and the
           confirmation-side injection construction with the injector catalog
           version). Refuses calibration scores below the calibration floor per
           stratum, with missing evidence, or from a panel whose orchestrator,
           metric reduction or metric versions are not the current code's (the
           confirmation panels will run it), a confirmation cohort that is not
           FLEURS test, a cohort another plan uses in the other role, and a
           confirmation cohort that already holds scores, a panel bundle or
           measurements. The lead reviews and commits it.
  derive   --detector ID --calibration-scores FILE [--output FILE]
           The split-conformal threshold from the calibration cohort's clean
           N2 scores, one per family, per declared stratum (language) or
           pooled, each stratum at least the calibration floor; refuses a plan
           not committed at HEAD.
  confirm  --detector ID --calibration-scores FILE --confirmation-scores FILE [--n3-scores FILE]
           Once per plan digest. Before anything is recorded: the bindings and
           output, evidence and scoring-code identities across both cohorts
           (A7), the planned injection construction, confirmation panels
           computed from scratch after the plan's commit (a start time after
           it, an empty cache root, no L1 hit, no adoption), every expected
           unit present with evidence and no failed judge row (an unavailable
           row is the run's failure, not an abstention), and the warn minimums
           counted on scored units (negatives, positives per severe cell, a
           sham cell per injector). Then the confirmation N2 negatives, the P1 positives and
           the S shams against the warn operating point (evaluate_confirmation),
           with the phi audit of consensus families; writes the ledger entry
           beside the plan and the tracked record
           benchmarks/audio-qc-calibration/<id>/record-<plan digest 16>.json
           (digests, counts, rates with Clopper-Pearson bounds, threshold,
           scope, limitations, verdict; no text or path).
  report   [--scores FILE ...] [--output FILE]
           Markdown across the registry: plan and confirmation status per
           detector, and the calibration score quantiles of the given files.
  validate The registry, every committed plan and ledger entry and every
           record, each against the current registry entry; a ledger entry
           without its record; and any plan, ledger entry or record a commit
           later deleted, modified or renamed (contract gate).
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from lib.jsonio import sha256_json  # noqa: E402
from lib.language_metrics import ACCURACY_METRIC_VERSION, TEXT_NORMALIZATION, text_sha256  # noqa: E402
from lib.qc_pipeline.evidence import privacy_errors  # noqa: E402
from lib.qc_qualification import correlation, detectors as registry_lib, thresholds  # noqa: E402
from lib.qc_qualification.pcm import json_digest  # noqa: E402
from lib.qc_qualification.stats import family_rate  # noqa: E402

REGISTRY = "config/audio-qc-detectors.json"
JUDGES = "config/audio-qc-judges.json"
POLICY = "config/audio-qc-qualification-policy.json"
RECORDS = "benchmarks/audio-qc-calibration"
SCORES_KIND = "audio-qc-detector-scores"
SCORES_SCHEMA = "vocello.audioqc.detector-scores/2"
RECORD_KIND = "audio-qc-calibration-record"
RECORD_SCHEMA = "vocello.audioqc.qc-calibration/1"
MEASUREMENTS_KIND = "audio-qc-calibration-measurements"
INJECTION_SET_KIND = "audio-qc-injection-set"
BUNDLE_SCHEMA = "vocello.audioqc.private-bundle/1"
N1_KIND, N2_KIND, N3_KIND = "audio-qc-n1-cohort", "audio-qc-n2-cohort", "audio-qc-calibration-takes"
COHORT_KINDS = {N2_KIND: "N2", N1_KIND: "N1", N3_KIND: "N3"}
FLEURS_KINDS = frozenset({N2_KIND, N1_KIND})
FLEURS_SPLITS = ("dev", "test")
ROLES = ("calibration", "confirmation", "informational")
SUPPORTED_OPERATING_POINTS = ("warn",)
FLEURS_SPEAKER_UNIT = "language:fleurs-unidentified"
FLEURS_DISJOINT_BY = ("family", "script")
MAX_RECORD_BYTES = 64 * 1024
PI_MAX = (0.05, 0.10, 0.20)
SKIPPED_DIRECTORIES = frozenset({"roundtrip", "inputs", "logs", "wav", "evidence", "private", "batches",
                                 "batch-out", "batch-results"})
# An in-scope unit whose expected evidence is absent (the bundle lacks the take, a consumed judge was not
# run on it, or measurements.json lacks the clip): never a qualification input.
EVIDENCE_GAPS = ("no-evidence", "not-measured")
# An in-scope unit a consumed judge's row failed on (admission timeout, row timeout, crash, envelope
# breach): the run's failure, never the detector's abstention, so a confirmation never starts on it.
RUN_FAILURES = ("judge-unavailable",)
ORCHESTRATOR_SOURCE = Path(__file__).resolve().parent / "audio_qc_orchestrator.py"
# The metric-definition versions a panel measurement records beside its metrics (A7).
METRIC_VERSION_KEYS = ("accuracyMetricVersion", "textNormalization")
# The orchestrator's `startedAt` (UTC).
STARTED_AT_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
# Why a sham cell's A4 test cannot fail: every sham clip's audio is a clean cohort take's.
UNINFORMATIVE_SHAM = "sham-audio-is-clean-cohort-audio"
# The injection set's recorded construction -> the plan binding that pre-registers it (A5).
INJECTION_BINDINGS = {"catalogVersion": "injectorCatalogVersion", "catalogSeed": "injectionCatalogSeed",
                      "sampleSeed": "injectionSampleSeed", "samplePerCell": "injectionSamplePerCell",
                      "classes": "injectionClasses"}


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
    name = Path(path).name
    manifest = load_json(path, "the cohort manifest")
    kind = manifest.get("kind") if isinstance(manifest, dict) else None
    if kind not in COHORT_KINDS:
        raise CalibrationError(f"{name} is not a cohort manifest ({sorted(COHORT_KINDS)})")
    digest = manifest.get("manifestDigest")
    if not is_sha256(digest):
        raise CalibrationError(f"{name} has no manifestDigest")
    if sha256_json({key: value for key, value in manifest.items() if key != "manifestDigest"}, ascii=False) != digest:
        raise CalibrationError(f"{name} does not match its manifestDigest (edited after it was written)")
    population = COHORT_KINDS[kind]
    takes: dict[str, dict] = {}
    for take in manifest.get("takes") or ():
        if kind == N1_KIND and take.get("eligible") is not True:
            continue
        if kind == N2_KIND and take.get("eligible") is False:
            continue
        if kind == N3_KIND and take.get("status") != "generated":
            continue
        take_id, language = take.get("takeID"), take.get("language")
        if not take_id or not language or not take.get("family"):
            raise CalibrationError(f"{name}: a take lacks its id, family or language")
        if not is_sha256(take.get("wavSHA256")):
            raise CalibrationError(f"{name}: {take_id} pins no WAV digest")
        text = take.get("textSHA256")
        if not is_sha256(text):
            text = text_sha256(take["text"]) if isinstance(take.get("text"), str) else None
        if kind in FLEURS_KINDS:
            speaker = f"{language}:fleurs-unidentified"
        else:
            speaker = f"voice:{(take.get('voice') or {}).get('id')}"
        takes[take_id] = {"takeID": take_id, "family": take["family"], "language": language,
                          "scriptID": str(take.get("scriptID")), "speaker": speaker,
                          "wavSHA256": take["wavSHA256"], "textSHA256": text}
    if not takes:
        raise CalibrationError(f"{name} has no eligible takes")
    return {"kind": kind, "population": population, "manifestDigest": digest, "fileSHA256": file_sha256(path),
            "runID": manifest.get("runID"), "takes": takes, "directory": Path(path).resolve().parent, "name": name,
            "fleursSplit": manifest.get("fleursSplit") if kind == N1_KIND else None,
            "n1ManifestSHA256": manifest.get("n1ManifestSHA256") if kind == N2_KIND else None}


def cohort_split(cohort: Mapping[str, Any], n1_manifest: Path | None) -> str | None:
    """The FLEURS split (dev or test) a FLEURS-derived cohort was drawn from; None for another corpus.

    An N1 manifest names its own split; an N2 manifest pins its N1 manifest by
    file digest (`n1ManifestSHA256`), which must then be given.
    """
    if cohort["kind"] != N2_KIND and n1_manifest is not None:
        raise CalibrationError("an N1 manifest is given only for an N2 cohort, which pins it by n1ManifestSHA256")
    if cohort["kind"] not in FLEURS_KINDS:
        return None
    split = cohort["fleursSplit"]
    if cohort["kind"] == N2_KIND:
        if n1_manifest is None:
            raise CalibrationError(f"{cohort['name']} is an N2 cohort: pass the N1 manifest it was resynthesized "
                                   "from (n1ManifestSHA256) so its FLEURS split is known (A5)")
        if file_sha256(n1_manifest) != cohort["n1ManifestSHA256"]:
            raise CalibrationError(f"{Path(n1_manifest).name} is not the N1 manifest {cohort['name']} pins "
                                   "(n1ManifestSHA256)")
        source = load_json(n1_manifest, "the N1 manifest")
        if not isinstance(source, dict) or source.get("kind") != N1_KIND:
            raise CalibrationError(f"{Path(n1_manifest).name} is not an {N1_KIND} manifest")
        split = source.get("fleursSplit")
    if split not in FLEURS_SPLITS:
        raise CalibrationError(f"{cohort['name']} names no FLEURS split ({' or '.join(FLEURS_SPLITS)})")
    return split


def corpus_split(roles: Mapping[str, Any], role: str) -> str | None:
    """The FLEURS split a role set declares for a role (`fleurs-dev` -> dev), or None for another corpus."""
    corpus = str((roles.get(role) or {}).get("corpus") or "")
    return corpus.removeprefix("fleurs-") if corpus.startswith("fleurs-") else None


def load_measurements(path: Path) -> dict:
    name = Path(path).name
    data = load_json(path, "the measurements")
    if not isinstance(data, dict) or data.get("kind") != MEASUREMENTS_KIND or not isinstance(data.get("clips"), list):
        raise CalibrationError(f"{name} is not an {MEASUREMENTS_KIND} file")
    if json_digest(data["clips"]) != data.get("clipsSHA256"):
        raise CalibrationError(f"{name} does not match its clipsSHA256 (edited after scoring)")
    return {"clips": data["clips"], "identity": json_digest(data.get("subject") or {}),
            "fileSHA256": file_sha256(path), "clipsSHA256": data["clipsSHA256"],
            "takesManifestSHA256": data.get("takesManifestSHA256"), "entriesSHA256": data.get("entriesSHA256"),
            "startedAt": data.get("startedAt"), "name": name}


def construction_value(key: str, value: Any) -> str:
    """One construction parameter as a plan binding holds it (classes comma-joined, sorted)."""
    if key == "classes":
        return ",".join(sorted(str(item) for item in value or ()))
    return str(value)


def load_injection_set(path: Path) -> dict:
    name = Path(path).name
    data = load_json(path, "the injection set")
    if not isinstance(data, dict) or data.get("kind") != INJECTION_SET_KIND \
            or not isinstance(data.get("entries"), list):
        raise CalibrationError(f"{name} is not an {INJECTION_SET_KIND} file")
    if json_digest(data["entries"]) != data.get("entriesSHA256"):
        raise CalibrationError(f"{name}'s entries differ from its entriesSHA256 (edited after injection)")
    source = data.get("sourceManifest") if isinstance(data.get("sourceManifest"), dict) else {}
    if not is_sha256(source.get("sha256")):
        raise CalibrationError(f"{name} names no source manifest digest")
    sampling = data.get("sampling") if isinstance(data.get("sampling"), dict) else {}
    swap = data.get("languageSwap") if isinstance(data.get("languageSwap"), dict) else {}
    construction = {
        "catalogVersion": data.get("catalogVersion"), "catalogSeed": data.get("catalogSeed"),
        "classes": sorted(str(item) for item in data.get("classes") or ()),
        "samplePerCell": sampling.get("perCell", 0) if sampling else 0,
        "sampleSeed": sampling.get("seed") if sampling else swap.get("seed"),
        # The catalog version each T1 recipe carries, inside entriesSHA256 (the header's is outside it).
        "entryCatalogVersions": sorted({entry["injection"]["catalogVersion"] for entry in data["entries"]
                                        if isinstance(entry, dict) and isinstance(entry.get("injection"), dict)
                                        and isinstance(entry["injection"].get("catalogVersion"), int)}),
    }
    return {"entries": data["entries"], "sourceManifestSHA256": source["sha256"], "fileSHA256": file_sha256(path),
            "entriesSHA256": data["entriesSHA256"], "construction": construction, "name": name}


class Bundle:
    """A private panel bundle (read-only): its own digest, and each file checked against its digest."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        manifest = load_json(self.directory / "bundle.json", "the panel bundle")
        if not isinstance(manifest, dict) or manifest.get("schema") != BUNDLE_SCHEMA:
            raise CalibrationError(f"{self.directory.name} is not a {BUNDLE_SCHEMA} bundle")
        body = {key: value for key, value in manifest.items() if key != "bundleDigest"}
        if manifest.get("bundleDigest") != sha256_json(body, ascii=False, allow_nan=False):
            raise CalibrationError(f"{self.directory.name}: bundle.json does not match its bundleDigest")
        self.manifest = manifest
        self.takes = {entry["takeID"]: entry for entry in manifest.get("takes") or ()}

    def identity(self) -> dict:
        cache = self.manifest.get("cache")
        return {"bundleDigest": self.manifest.get("bundleDigest"), "runID": self.manifest.get("runID"),
                "manifestSHA256": self.manifest.get("manifestSHA256"),
                "orchestratorSHA256": self.manifest.get("orchestratorSHA256"),
                "startedAt": self.manifest.get("startedAt"),
                "cacheRootEmptyAtStart": self.manifest.get("cacheRootEmptyAtStart"),
                "cache": cache if isinstance(cache, dict) else None}

    def judge_metrics(self, judge: str) -> dict:
        """The judge's L2 metric definition and sources digest as the bundle header records them."""
        recorded = self.manifest.get("judgeMetrics")
        value = recorded.get(judge) if isinstance(recorded, dict) else None
        value = value if isinstance(value, dict) else {}
        return {"definition": value.get("definition"), "sourcesSHA256": value.get("sourcesSHA256")}

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

    def measurements(self, take_id: str, *, audio_sha256: str, text_sha256: str | None,
                     language: str) -> dict[str, dict] | None:
        """The take's measurements by judge, or None when the bundle lacks it; refused when the evidence
        was measured on other audio, text or language than the cohort or the injection set declares."""
        evidence = self._read(take_id, "evidence")
        if evidence is None:
            return None
        take = evidence.get("take") if isinstance(evidence.get("take"), dict) else {}
        where = f"{self.directory.name}: {take_id}"
        if take.get("takeID") != take_id:
            raise CalibrationError(f"{where}: its evidence belongs to another take")
        if take.get("audioSHA256") != audio_sha256:
            raise CalibrationError(f"{where}: its evidence was measured on other audio than the manifest's")
        if text_sha256 is not None and take.get("textSHA256") != text_sha256:
            raise CalibrationError(f"{where}: its evidence was scored against another text")
        if take.get("language") != language:
            raise CalibrationError(f"{where}: its evidence expected another language")
        return {measurement["judge"]: measurement for measurement in evidence.get("measurements") or ()}

    def private(self, take_id: str) -> dict | None:
        private = self._read(take_id, "private")
        if private is not None and private.get("takeID") != take_id:
            raise CalibrationError(f"{self.directory.name}: {take_id}'s private file belongs to another take")
        return private


# --------------------------------------------------------------------------- #
# scores
# --------------------------------------------------------------------------- #

def _identities(collected: dict[str, set], versions: dict[str, dict[str, set]],
                measurements: Mapping[str, Mapping] | None, judges: Iterable[str]) -> None:
    for judge in judges:
        measurement = (measurements or {}).get(judge)
        if not measurement:
            continue
        if measurement.get("outputIdentity"):
            collected.setdefault(judge, set()).add(measurement["outputIdentity"])
        if measurement.get("status") == "complete":
            for key in METRIC_VERSION_KEYS:
                value = (measurement.get("metrics") or {}).get(key)
                if isinstance(value, str):
                    versions.setdefault(judge, {}).setdefault(key, set()).add(value)


def _unit(meta: Mapping[str, Any], scored: Mapping[str, Any], **extra: Any) -> dict:
    unit = {"unitID": meta["takeID"], "family": meta["family"], "language": meta["language"],
            "speaker": meta["speaker"], "scriptID": meta["scriptID"], "population": meta["population"],
            "injectorID": None, "variant": None, "severity": None, "mechanism": None, "cell": None,
            "cleanAudio": None}
    unit.update(extra)
    unit.update(inScope=scored["inScope"], score=scored["score"], components=scored["components"],
                abstain=scored["abstain"])
    return unit


def _without_evidence(scored: Mapping[str, Any]) -> dict:
    """An in-scope unit whose evidence is absent abstains as such, never as a judge's own abstention."""
    return {**scored, "score": None, "abstain": "no-evidence"} if scored["inScope"] else dict(scored)


def _run_failed(entry: Mapping[str, Any], language: str, scored: Mapping[str, Any],
                measurements: Mapping[str, Mapping] | None) -> dict:
    """A unit that abstained because a judge its group consumes (or requires complete) failed its row."""
    group = registry_lib.group_for(entry, language) if scored["inScope"] else None
    if group is None or scored["abstain"] is None:
        return dict(scored)
    judges = {component["judge"] for component in group["components"]
              if component["source"] in registry_lib.PANEL_SOURCES} | set(group.get("requiresComplete") or ())
    if any(((measurements or {}).get(judge) or {}).get("status") == "unavailable" for judge in judges):
        return {**scored, "score": None, "abstain": "judge-unavailable"}
    return dict(scored)


def _check_private(private: Mapping[str, Any] | None, text_digest: str | None, where: str) -> None:
    if private is not None and text_digest is not None \
            and text_sha256(str(private.get("referenceText") or "")) != text_digest:
        raise CalibrationError(f"{where}: its private reference text is not the manifest's text")


def build_scores(entry: Mapping[str, Any], cohort: Mapping[str, Any], *, role: str, split: str | None = None,
                 bundle: Bundle | None = None, measurements: Mapping[str, Any] | None = None,
                 injection_set: Mapping[str, Any] | None = None, positive_bundle: Bundle | None = None,
                 positive_measurements: Mapping[str, Any] | None = None) -> dict:
    """Every cohort take's score, then every positive and sham of the detector's injectors."""
    detector = entry["id"]
    needs_panel, needs_measurements = registry_lib.needs_panel(entry), registry_lib.needs_measurements(entry)
    needs_private = registry_lib.needs_private(entry)
    if needs_measurements and measurements is None:
        raise CalibrationError(f"{detector} reads measurements.json: pass --measurements")
    if needs_panel and bundle is None:
        raise CalibrationError(f"{detector} reads panel evidence: pass --bundle")
    if (positive_bundle is not None or positive_measurements is not None) and injection_set is None:
        raise CalibrationError("positives are the injection set's entries: pass --injection-set")
    if injection_set is not None and injection_set["sourceManifestSHA256"] != cohort["fileSHA256"]:
        raise CalibrationError("the injection set was built on another cohort manifest")
    for source, what in ((measurements, "--measurements"), (positive_measurements, "--positive-measurements")):
        if source is not None and source["takesManifestSHA256"] != cohort["fileSHA256"]:
            raise CalibrationError(f"{what} ({source['name']}) scored another takes manifest")
    if measurements is not None and injection_set is not None and measurements["entriesSHA256"] is not None \
            and measurements["entriesSHA256"] != injection_set["entriesSHA256"]:
        raise CalibrationError(f"--measurements ({measurements['name']}) scored another injection set")
    if positive_measurements is not None and positive_measurements["entriesSHA256"] != injection_set["entriesSHA256"]:
        raise CalibrationError(f"--positive-measurements ({positive_measurements['name']}) did not score this "
                               "injection set")
    judges = registry_lib.judges_of(entry)
    panel_judges = [judge for judge in judges if judge != registry_lib.STAGE0_JUDGE]
    identities: dict[str, set] = {}
    versions: dict[str, dict[str, set]] = {}
    orchestrators: set[str] = set()
    reductions: dict[str, set[tuple]] = {}
    skipped: Counter = Counter()
    units: list[dict] = []
    clean_clips: dict[str, dict] = {}
    if needs_panel:
        for source in (bundle, positive_bundle):
            if source is None:
                continue
            digest = source.identity()["orchestratorSHA256"]
            if not is_sha256(digest):
                raise CalibrationError(f"{source.directory.name} records no orchestrator source digest")
            orchestrators.add(digest)
            for judge in panel_judges:
                recorded = source.judge_metrics(judge)
                reductions.setdefault(judge, set()).add((recorded["definition"], recorded["sourcesSHA256"]))
    if measurements is not None:
        identities.setdefault(registry_lib.STAGE0_JUDGE, set()).add(measurements["identity"])
        for clip in measurements["clips"]:
            if clip.get("injection") is None and clip.get("population") == cohort["population"]:
                clean_clips[clip.get("sourceTakeID") or clip.get("clipID")] = clip
    for take_id in sorted(cohort["takes"]):
        take = cohort["takes"][take_id]
        meta = {**take, "population": cohort["population"]}
        where = f"{cohort['name']}: {take_id}"
        evidence = bundle.measurements(take_id, audio_sha256=take["wavSHA256"], text_sha256=take["textSHA256"],
                                       language=take["language"]) if bundle is not None and needs_panel else None
        private = bundle.private(take_id) if needs_private and evidence is not None else None
        _check_private(private, take["textSHA256"], where)
        clip = clean_clips.get(take_id) if needs_measurements else None
        if clip is not None and clip.get("wavSHA256") != take["wavSHA256"]:
            raise CalibrationError(f"{where}: measurements.json measured other audio than the manifest's")
        _identities(identities, versions, evidence, panel_judges)
        scored = registry_lib.score_take(entry, meta["language"], clip=clip, measurements=evidence, private=private)
        if (needs_panel and evidence is None) or (needs_measurements and clip is None):
            scored = _without_evidence(scored)
        elif needs_panel:
            scored = _run_failed(entry, meta["language"], scored, evidence)
        units.append(_unit(meta, scored))
    wanted = registry_lib.target_injectors(entry)
    positives: list[tuple[dict, dict]] = []
    for item in (injection_set or {}).get("entries") or ():
        injection = item.get("injection") or {}
        if injection.get("injectorID") in wanted:
            positives.append((item, injection))
    if positives and needs_panel and positive_bundle is None:
        raise CalibrationError(f"{detector} reads panel evidence: its positives need --positive-bundle")
    if positives and needs_measurements and positive_measurements is None:
        raise CalibrationError(f"{detector} reads measurements.json: its positives need --positive-measurements")
    if positive_measurements is not None:
        identities.setdefault(registry_lib.STAGE0_JUDGE, set()).add(positive_measurements["identity"])
    injected_clips = {clip.get("clipID"): clip for clip in (positive_measurements or {}).get("clips") or ()
                      if clip.get("injection") is not None}
    cohort_audio = {take["wavSHA256"] for take in cohort["takes"].values()}
    for item, injection in positives:
        source = cohort["takes"].get(item.get("sourceTakeID"))
        if source is None:
            raise CalibrationError(f"{item.get('takeID')}: its source take is not in the cohort; positives are "
                                   "built on the cohort they confirm with")
        wav = item.get("wavSHA256")
        if not is_sha256(wav):
            raise CalibrationError(f"{item.get('takeID')}: the injection set pins no WAV digest for it")
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
        text = item.get("textSHA256") if is_sha256(item.get("textSHA256")) else None
        where = f"{injection_set['name']}: {item['takeID']}"
        meta = {"takeID": item["takeID"], "family": item.get("family") or source["family"], "language": language,
                "speaker": f"{language}:fleurs-unidentified" if cohort["kind"] in FLEURS_KINDS else source["speaker"],
                "scriptID": source["scriptID"], "population": population}
        evidence = positive_bundle.measurements(item["takeID"], audio_sha256=wav, text_sha256=text,
                                                language=language) \
            if positive_bundle is not None and needs_panel else None
        private = positive_bundle.private(item["takeID"]) if needs_private and evidence is not None else None
        _check_private(private, text, where)
        _identities(identities, versions, evidence, panel_judges)
        clip = injected_clips.get(item["takeID"]) if needs_measurements else None
        if clip is not None:
            recorded = clip.get("injection") or {}
            if recorded.get("injectorID") != injector_id or recorded.get("severity") != injection.get("severity") \
                    or recorded.get("variant") != injection.get("variant"):
                raise CalibrationError(f"{item['takeID']}: the measurements and the injection set disagree")
            if clip.get("wavSHA256") != wav:
                raise CalibrationError(f"{where}: measurements.json measured other audio than the set's")
        severity = injection.get("severity")
        cell = registry_lib.target_cell(entry, injector_id, severity, mechanism) if population == "P1" else None
        sham = population == "S" and registry_lib.sham_of(entry, injector_id, mechanism)
        # Clean cohort audio: a byte copy of a cohort take (a language swap's donor) or an identity construction.
        clean = wav in cohort_audio or (injection.get("outputPCMSHA256") is not None
                                        and injection.get("outputPCMSHA256") == injection.get("sourcePCMSHA256"))
        scored = registry_lib.score_take(entry, language, clip=clip, measurements=evidence, private=private)
        if (needs_panel and evidence is None) or (needs_measurements and clip is None):
            scored = _without_evidence(scored)
        elif needs_panel:
            scored = _run_failed(entry, language, scored, evidence)
        units.append(_unit(meta, scored, injectorID=injector_id, variant=injection.get("variant"),
                           severity=severity, mechanism=mechanism, cell=cell, sham=bool(sham), cleanAudio=clean))
    by_population = Counter(unit["population"] for unit in units)
    abstained = Counter(unit["abstain"] for unit in units if unit["abstain"])
    document = {
        "schema": SCORES_SCHEMA, "kind": SCORES_KIND,
        "privacy": "ids and digests only: no text, transcript or path",
        "detector": detector, "detectorDefinitionSHA256": registry_lib.definition_digest(entry),
        "scoringCodeSHA256": registry_lib.scoring_code_sha256(),
        "class": entry["class"], "direction": entry["direction"], "combination": entry["score"]["combination"],
        "role": role,
        "cohort": {"kind": cohort["kind"], "population": cohort["population"],
                   "manifestDigest": cohort["manifestDigest"], "fileSHA256": cohort["fileSHA256"],
                   "runID": cohort.get("runID"), "takes": len(cohort["takes"]), "fleursSplit": split},
        "sources": {
            "bundle": bundle.identity() if bundle and needs_panel else None,
            "measurements": {key: measurements[key] for key in ("fileSHA256", "clipsSHA256", "identity",
                                                                "takesManifestSHA256", "entriesSHA256",
                                                                "startedAt")}
            if measurements else None,
            "injectionSet": {key: injection_set[key] for key in ("fileSHA256", "entriesSHA256",
                                                                 "sourceManifestSHA256", "construction")}
            if injection_set else None,
            "positiveBundle": positive_bundle.identity() if positive_bundle and needs_panel else None,
            "positiveMeasurements": {key: positive_measurements[key]
                                     for key in ("fileSHA256", "clipsSHA256", "identity", "takesManifestSHA256",
                                                 "entriesSHA256", "startedAt")}
            if positive_measurements else None,
        },
        "judgeIdentities": {judge: sorted(values) for judge, values in sorted(identities.items())},
        # What else shapes a score, compared across the cohorts and bound by the plan (A7).
        "evidenceIdentity": {
            "orchestratorSHA256": sorted(orchestrators),
            "judgeMetrics": {judge: [{"definition": definition, "sourcesSHA256": sources}
                                     for definition, sources in sorted(pairs, key=repr)]
                             for judge, pairs in sorted(reductions.items())},
            "metricVersions": {judge: {key: sorted(values) for key, values in sorted(keys.items())}
                               for judge, keys in sorted(versions.items())},
        },
        "counts": {"units": len(units), "byPopulation": dict(sorted(by_population.items())),
                   "abstained": dict(sorted(abstained.items())), "skipped": dict(sorted(skipped.items())),
                   "expected": {"cohortTakes": len(cohort["takes"]), "injections": len(positives)}},
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


def declared_cohorts(repository: Repository) -> dict[str, dict[str, list[str]]]:
    """Every plan file's cohorts by role: {calibration|confirmation: {manifest digest: [detectors]}}."""
    found: dict[str, dict[str, list[str]]] = {"calibration": {}, "confirmation": {}}
    directory = repository.store.directory
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("confirmation-"):
            continue
        try:
            plan = thresholds.PreRegistration.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, thresholds.PreRegistrationError) as error:
            raise CalibrationError(f"{path.name} is not a readable plan ({error}); run validate") from error
        if plan.cohorts is None:
            continue
        found["calibration"].setdefault(plan.cohorts.calibration.manifest_digest, []).append(plan.detector)
        found["confirmation"].setdefault(plan.cohorts.confirmation.manifest_digest, []).append(plan.detector)
    return found


def command_scores(args: argparse.Namespace, repository: Repository) -> int:
    registry, entry = repository.entry(args.detector)
    roles = registry_lib.role_set(registry, entry)
    cohort = load_cohort(args.cohort)
    split = cohort_split(cohort, args.n1_manifest)
    plan = repository.store.load(entry["id"])
    digest = cohort["manifestDigest"]
    confirmation_split = corpus_split(roles, "confirmNegatives")
    if args.role == "confirmation":
        if plan is None or plan.cohorts is None or plan.cohorts.confirmation.manifest_digest != digest:
            raise CalibrationError("a confirmation cohort is scored only under a plan that names it (A5): "
                                   f"run plan for {entry['id']} first and commit it")
        repository.store.require(plan)
        if confirmation_split is not None and split != confirmation_split:
            raise CalibrationError(f"the confirmation cohort is FLEURS {split}, not {confirmation_split}")
    else:
        named = declared_cohorts(repository)["confirmation"].get(digest)
        if named:
            raise CalibrationError(f"the plan of {', '.join(sorted(named))} names this cohort as its confirmation "
                                   "cohort; it is scored only under --role confirmation (A5)")
        if confirmation_split is not None and split == confirmation_split:
            raise CalibrationError(f"FLEURS {split} is the confirmation corpus: it is scored only under "
                                   "--role confirmation, never for calibration or information (A5)")
    if args.role == "calibration":
        if plan is not None and plan.cohorts and plan.cohorts.calibration.manifest_digest != digest:
            raise CalibrationError(f"{entry['id']}'s plan pins another calibration cohort")
        if cohort["population"] != roles["fit"]["population"]:
            raise CalibrationError(f"{entry['id']} fits on {roles['fit']['population']}, not {cohort['population']}")
        fit_split = corpus_split(roles, "fit")
        if fit_split is not None and split != fit_split:
            raise CalibrationError(f"{entry['id']} fits on FLEURS {fit_split}, not {split}")
    output = repository.check_output(args.output)
    document = build_scores(
        entry, cohort, role=args.role, split=split,
        bundle=Bundle(args.bundle) if args.bundle else None,
        measurements=load_measurements(args.measurements) if args.measurements else None,
        injection_set=load_injection_set(args.injection_set) if args.injection_set else None,
        positive_bundle=Bundle(args.positive_bundle) if args.positive_bundle else None,
        positive_measurements=load_measurements(args.positive_measurements) if args.positive_measurements else None,
    )
    if args.role == "confirmation":
        problems = confirmation_evidence_problems(repository, plan, document)
        if problems:
            raise CalibrationError("the confirmation evidence does not meet its plan: " + "; ".join(problems))
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
    """Anything in a cohort directory showing that the cohort was already scored (a convenience scan)."""
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


def _strata_keys(entry: Mapping[str, Any]) -> tuple[str | None, list[str]]:
    by = registry_lib.strata_by(entry)
    return by, [registry_lib.POOLED] if by is None else list(entry["scope"]["languages"])


def evidence_gaps(units: Iterable[Mapping[str, Any]]) -> Counter:
    return Counter(unit["abstain"] for unit in units if unit["inScope"] and unit["abstain"] in EVIDENCE_GAPS)


def calibration_problems(entry: Mapping[str, Any], scores: Mapping[str, Any], population: str,
                         floor: int) -> list[str]:
    """Why calibration scores cannot fit the plan: missing evidence, or a stratum below the calibration floor."""
    problems = []
    if scores["counts"].get("skipped"):
        problems.append(f"units were skipped ({scores['counts']['skipped']})")
    gaps = evidence_gaps(scores["units"])
    if gaps:
        problems.append(f"{sum(gaps.values())} in-scope units have no evidence ({dict(sorted(gaps.items()))})")
    by, keys = _strata_keys(entry)
    negatives = _in_scope(scores["units"], population)
    for key in keys:
        families = {unit["family"] for unit in negatives
                    if registry_lib.stratum(by, unit["language"]) == key and unit["score"] is not None}
        if len(families) < floor:
            problems.append(f"{key}: {len(families)} scored calibration families, the floor is {floor}")
    return problems


def current_evidence_problems(entry: Mapping[str, Any], identity: Mapping[str, Any]) -> list[str]:
    """Why calibration evidence differs from what a confirmation panel run now would record (A7).

    A plan binds the calibration evidence identity, and every confirmation
    panel runs after the plan with the current code, so evidence from another
    orchestrator, metric reduction or metric version would make the plan
    impossible to confirm: it is refused before the plan exists.
    """
    if not registry_lib.needs_panel(entry):
        return []
    from lib.qc_pipeline import panel_metrics  # deferred: the panel's reducers, read only at plan time
    from lib.qc_pipeline.layered_cache import metric_sources_digest
    from lib.qc_pipeline.panel_jobs import PanelJobError, profile

    problems = []
    if identity.get("orchestratorSHA256") != [file_sha256(ORCHESTRATOR_SOURCE)]:
        problems.append("the calibration panel ran another orchestrator than the current one; write its bundle "
                        "again with the current orchestrator (its L1 entries may be reused)")
    for judge in registry_lib.judges_of(entry):
        if judge == registry_lib.STAGE0_JUDGE:
            continue
        try:
            category = profile(judge).category
        except PanelJobError as error:
            problems.append(str(error))
            continue
        expected = {"definition": panel_metrics.metric_definition(category),
                    "sourcesSHA256": metric_sources_digest(panel_metrics.metric_sources(category))}
        if (identity.get("judgeMetrics") or {}).get(judge) != [expected]:
            problems.append(f"{judge}: the calibration panel reduced its metrics with other code than the current")
    current = {"accuracyMetricVersion": ACCURACY_METRIC_VERSION, "textNormalization": TEXT_NORMALIZATION}
    for judge, keys in sorted((identity.get("metricVersions") or {}).items()):
        for key, values in sorted(keys.items()):
            if values != [current[key]]:
                problems.append(f"{judge}: the calibration panel recorded {key} {values}, not {current[key]}")
    return problems


def build_plan(repository: Repository, registry: Mapping[str, Any], entry: Mapping[str, Any], *,
               calibration: Mapping[str, Any], confirmation: Mapping[str, Any], calibration_scores: Mapping[str, Any],
               alpha: float, operating_point: str, injection: Mapping[str, Any],
               confirmation_split: str | None = None) -> thresholds.PreRegistration:
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
    expected = corpus_split(roles, "confirmNegatives")
    if expected is not None and confirmation_split != expected:
        raise CalibrationError(f"the confirmation cohort is FLEURS {confirmation_split}; the role set confirms on "
                               f"FLEURS {expected}")
    if calibration_scores.get("detector") != entry["id"] or calibration_scores.get("role") != "calibration":
        raise CalibrationError("the calibration scores belong to another detector or role")
    if calibration_scores.get("detectorDefinitionSHA256") != registry_lib.definition_digest(entry):
        raise CalibrationError("the calibration scores were computed under another definition of the detector")
    if calibration_scores["cohort"]["manifestDigest"] != calibration["manifestDigest"] \
            or calibration_scores["cohort"]["fileSHA256"] != calibration["fileSHA256"]:
        raise CalibrationError("the calibration scores are not of the calibration cohort")
    fit_split = corpus_split(roles, "fit")
    if fit_split is not None and calibration_scores["cohort"].get("fleursSplit") != fit_split:
        raise CalibrationError(f"the calibration scores are not of FLEURS {fit_split}")
    scoring_code = registry_lib.scoring_code_sha256()
    if calibration_scores.get("scoringCodeSHA256") != scoring_code:
        raise CalibrationError("the calibration scores were computed by other scoring code; score them again (A7)")
    problems = current_evidence_problems(entry, calibration_scores["evidenceIdentity"])
    problems += calibration_problems(entry, calibration_scores, roles["fit"]["population"],
                                     point["minimumUnits"]["calibration"])
    if problems:
        raise CalibrationError("the calibration scores cannot fit a threshold: " + "; ".join(problems))
    declared = declared_cohorts(repository)
    if declared["confirmation"].get(calibration["manifestDigest"]):
        raise CalibrationError(f"the plan of {', '.join(declared['confirmation'][calibration['manifestDigest']])} "
                               "names the calibration cohort as its confirmation cohort (A5)")
    if declared["calibration"].get(confirmation["manifestDigest"]):
        raise CalibrationError(f"the plan of {', '.join(declared['calibration'][confirmation['manifestDigest']])} "
                               "fits on the confirmation cohort (A5)")
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
        ("scoringCodeSHA256", scoring_code),
        ("evidenceIdentitySHA256", json_digest(calibration_scores["evidenceIdentity"])),
        *((binding, construction_value(key, injection[key])) for key, binding in INJECTION_BINDINGS.items()),
    )
    strata = () if entry["strata"] is None else ((entry["strata"]["by"], entry["strata"]["reason"]),)
    plan = thresholds.PreRegistration(
        detector=entry["id"], rule="split-conformal", alpha=alpha, direction=entry["direction"],
        confidence=policy["statistics"]["confidence"], population=roles["fit"]["population"],
        strata=strata, cohorts=split, bindings=bindings)
    thresholds.check_cohort_disjointness(plan, _triples(calibration), _triples(confirmation))
    return plan


def injection_classes(value: str) -> list[str]:
    classes = sorted({item.strip().upper() for item in value.split(",") if item.strip()})
    if not classes or not set(classes) <= set(registry_lib.CLASSES):
        raise argparse.ArgumentTypeError("classes are letters A-J, comma-separated")
    return classes


def command_plan(args: argparse.Namespace, repository: Repository) -> int:
    from lib.qc_qualification import injectors  # deferred: NumPy-backed, only its catalog version is read

    registry, entry = repository.entry(args.detector)
    confirmation = load_cohort(args.confirmation_cohort)
    injection = {"catalogVersion": injectors.CATALOG_VERSION, "catalogSeed": args.injection_catalog_seed,
                 "sampleSeed": args.injection_sample_seed, "samplePerCell": args.injection_sample_per_cell,
                 "classes": args.injection_classes}
    plan = build_plan(repository, registry, entry, calibration=load_cohort(args.calibration_cohort),
                      confirmation=confirmation,
                      confirmation_split=cohort_split(confirmation, args.confirmation_n1_manifest),
                      calibration_scores=load_scores(args.calibration_scores), alpha=args.alpha,
                      operating_point=args.operating_point, injection=injection)
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
    if plan.binding("scoringCodeSHA256") != registry_lib.scoring_code_sha256():
        raise CalibrationError("the scoring code (detectors.py, language_metrics.py and its data) changed after "
                               f"the plan (A7): {entry['id']} needs a new version")
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


def calibration_floor(repository: Repository, plan: thresholds.PreRegistration) -> int:
    return int(repository.policy()["operatingPoints"][plan.binding("operatingPoint")]["minimumUnits"]["calibration"])


def derivation(repository: Repository, entry: Mapping[str, Any], plan: thresholds.PreRegistration,
               calibration_scores: Mapping[str, Any], floor: int) -> dict:
    """One split-conformal threshold per declared stratum (or one pooled), from clean calibration families.

    A stratum below the calibration floor (`minimumUnits.calibration` of the
    plan's operating point, counted in scored families) has no threshold.
    """
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
        item = {name: result[name] for name in ("threshold", "rank", "calibrationUnits", "calibrationClips",
                                                 "status", "minimumNegatives")}
        item["minimumNegatives"] = max(result["minimumNegatives"], floor)
        if result["calibrationUnits"] < floor:
            item.update(status="insufficient-negatives", threshold=None, rank=None)
        item["abstention"] = family_rate((unit["family"], unit["score"] is None) for unit in units).as_dict()
        item["summary"] = registry_lib.summarize(score for _, score in judged)
        per[key] = item
    status = "derived" if all(item["status"] == "derived" for item in per.values()) else "insufficient-negatives"
    return {
        "plan": plan.digest(), "detector": plan.detector, "rule": plan.rule, "alpha": plan.alpha,
        "direction": plan.direction, "unit": "source-family", "strata": by or registry_lib.POOLED,
        "status": status, "thresholds": {key: item["threshold"] for key, item in per.items()}, "byStratum": per,
        "calibrationFloor": floor,
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
    result = derivation(repository, entry, plan, load_scores(args.calibration_scores),
                        calibration_floor(repository, plan))
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


def sham_cells(entry: Mapping[str, Any]) -> list[str]:
    """One sham cell per positive injector (A4): no injector's sham stands in for another's."""
    return sorted({sham["injectorID"] for sham in entry.get("shams") or ()})


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
            shams.setdefault(unit["injectorID"], []).append(dict(unit))
    return {"negatives": negatives, "positives": positives, "shams": shams}


def _scored_families(units: Iterable[Mapping[str, Any]]) -> set[str]:
    return {unit["family"] for unit in units if unit["score"] is not None}


def preconditions(entry: Mapping[str, Any], inputs: Mapping[str, Any], point: Mapping[str, Any],
                  scores: Mapping[str, Any]) -> list[str]:
    """What must hold before the one confirmation starts, counted on scored units (never on alarms).

    Every expected unit is present and has its evidence, and the warn minimums
    hold on the units that did not abstain: a detector that (nearly) always
    abstains is refused here, never recorded as refused.
    """
    problems: list[str] = []
    floors = point["minimumUnits"]
    counts = scores["counts"]
    if counts.get("skipped"):
        problems.append(f"units were skipped ({counts['skipped']}); every expected unit is scored")
    expected = counts.get("expected") or {}
    cohort_units = sum(1 for unit in scores["units"] if unit["injectorID"] is None)
    injected_units = sum(1 for unit in scores["units"] if unit["injectorID"] is not None)
    if (cohort_units, injected_units) != (expected.get("cohortTakes"), expected.get("injections")):
        problems.append(f"{cohort_units} cohort and {injected_units} injected units, where the manifests list "
                        f"{expected.get('cohortTakes')} and {expected.get('injections')}")
    gaps = evidence_gaps(scores["units"])
    if gaps:
        problems.append(f"{sum(gaps.values())} in-scope units have no evidence ({dict(sorted(gaps.items()))}); "
                        "every expected unit needs its evidence")
    failed = sum(1 for unit in scores["units"] if unit["inScope"] and unit["abstain"] in RUN_FAILURES)
    if failed:
        problems.append(f"{failed} in-scope units have a failed judge row (unavailable: an admission or row "
                        "timeout, a crash or an envelope breach); run that panel again on a new cache root")
    negatives = [unit for unit in inputs["negatives"] if unit["score"] is not None]
    families = _scored_families(negatives)
    if len(families) < floors["good"]:
        problems.append(f"{len(families)} scored N2 negative families, the floor is {floors['good']}")
    for key, floor in (("language", floors["languages"]), ("speaker", floors["speakers"]),
                       ("scriptID", floors["scripts"])):
        count = len({unit[key] for unit in negatives})
        if count < floor:
            problems.append(f"{count} {key} values among the scored negatives, the floor is {floor}")
    for mechanism, cells in sorted(registry_lib.declared_cells(entry).items()):
        for cell in sorted(cells):
            if cell.rsplit("/", 1)[-1] != "severe":
                continue
            count = len(_scored_families(inputs["positives"].get(mechanism, {}).get(cell, [])))
            if count < floors["bad"]:
                problems.append(f"{mechanism} {cell}: {count} scored positive families, the floor is {floors['bad']}")
    for injector in sham_cells(entry):
        count = len(_scored_families(inputs["shams"].get(injector, [])))
        if count < floors["bad"]:
            problems.append(f"{injector}: {count} scored sham families, the floor is {floors['bad']} (A4)")
    return problems


def sham_informative(entry: Mapping[str, Any], inputs: Mapping[str, Any]) -> dict[str, bool]:
    """False for a sham cell whose every clip is clean cohort audio: its A4 test cannot fail."""
    return {injector: not (inputs["shams"].get(injector)
                           and all(unit.get("cleanAudio") is True for unit in inputs["shams"][injector]))
            for injector in sham_cells(entry)}


def started_at_seconds(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, STARTED_AT_FORMAT).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def panel_freshness_problems(identity: Mapping[str, Any] | None, planned_at: int, what: str) -> list[str]:
    """A confirmation panel computed from scratch after the plan's commit (A5).

    It started after the commit, on a cache root holding no L1 or L2 entry,
    with no L1 hit and no adoption. L2 hits are then this run's own: identical
    audio under one request (an identity sham of two injectors, a language
    swap's donor) shares one L1 row and is reduced once.
    """
    if identity is None:
        return []
    problems = []
    started = started_at_seconds(identity.get("startedAt"))
    if started is None:
        problems.append(f"{what} records no start time; run it with the current orchestrator")
    elif started <= planned_at:
        problems.append(f"{what} started before its plan was committed (A5)")
    if identity.get("cacheRootEmptyAtStart") is not True:
        problems.append(f"{what} did not start on an empty cache root; run each confirmation panel with a new "
                        "--cache-root (A5)")
    cache = identity.get("cache")
    if not isinstance(cache, Mapping):
        problems.append(f"{what} records no cache counts")
    else:
        hits = (cache.get("L1") or {}).get("hits")
        if hits != 0:
            problems.append(f"{what} reused {hits} L1 entries; a confirmation panel is computed from scratch (A5)")
        adopted = sum(int((layer or {}).get("adopted") or 0) for layer in cache.values() if isinstance(layer, Mapping))
        if adopted:
            problems.append(f"{what} adopted {adopted} entries another run stored (A5)")
    return problems


def injection_construction_problems(plan: thresholds.PreRegistration, scores: Mapping[str, Any]) -> list[str]:
    """The injection set was built as the plan declared (A5)."""
    source = (scores.get("sources") or {}).get("injectionSet")
    if not source:
        return ["the confirmation scores name no injection set; the positives and shams come from one"]
    recorded = source.get("construction") or {}
    problems = []
    for key, binding in INJECTION_BINDINGS.items():
        expected = plan.binding(binding)
        if expected is None:
            problems.append(f"the plan binds no {binding}")
            continue
        actual = construction_value(key, recorded.get(key))
        if actual != expected:
            problems.append(f"the injection set's {key} is {actual}, the plan declares {expected} (A5)")
    planned = plan.binding(INJECTION_BINDINGS["catalogVersion"])
    entry_versions = [str(value) for value in recorded.get("entryCatalogVersions") or ()]
    if planned is not None and any(value != planned for value in entry_versions):
        problems.append(f"the injection set's entries carry catalog versions {entry_versions}, the plan declares "
                        f"{planned} (A5)")
    return problems


def confirmation_evidence_problems(repository: Repository, plan: thresholds.PreRegistration,
                                   scores: Mapping[str, Any]) -> list[str]:
    problems = injection_construction_problems(plan, scores)
    planned_at = repository.store.commit_time(plan)
    sources = scores.get("sources") or {}
    for key, what in (("bundle", "the confirmation cohort's panel bundle"),
                      ("positiveBundle", "the positives' panel bundle")):
        problems.extend(panel_freshness_problems(sources.get(key), planned_at, what))
    for key, what in (("measurements", "the confirmation cohort's measurements"),
                      ("positiveMeasurements", "the positives' measurements")):
        problems.extend(measurement_freshness_problems(sources.get(key), planned_at, what))
    return problems


def measurement_freshness_problems(source: Mapping[str, Any] | None, planned_at: int, what: str) -> list[str]:
    """Confirmation measurements (Fast QC, Stage 0) computed after the plan's commit (A5).

    `audio_qc_calibration_set.py score` stamps `startedAt` in its header, outside
    `clipsSHA256`, before any clip is measured.
    """
    if source is None:
        return []
    started = started_at_seconds(source.get("startedAt"))
    if started is None:
        return [f"{what} record no start time; measure them with the current audio_qc_calibration_set.py score"]
    if started <= planned_at:
        return [f"{what} started before its plan was committed (A5)"]
    return []


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
    """Both cohorts measured and scored alike, as the plan bound it (A7)."""
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
    if confirmation.get("scoringCodeSHA256") != calibration.get("scoringCodeSHA256") \
            or calibration.get("scoringCodeSHA256") != plan.binding("scoringCodeSHA256"):
        raise CalibrationError("the two cohorts were scored by different scoring code, or other code than the "
                               "plan's (A7)")
    if confirmation.get("evidenceIdentity") != calibration.get("evidenceIdentity"):
        raise CalibrationError("the orchestrator source or a metric version differs between the cohorts' "
                               "evidence (A7)")
    if json_digest(calibration["evidenceIdentity"]) != plan.binding("evidenceIdentitySHA256"):
        raise CalibrationError("the evidence identity differs from the plan's (A7)")


def check_n3(n3: Mapping[str, Any], calibration: Mapping[str, Any], entry: Mapping[str, Any]) -> None:
    """Informational N3 scores of the same detector, definition, scoring code and judge identities."""
    problems = []
    if n3.get("detector") != entry["id"] or n3.get("role") != "informational":
        problems.append("they are not this detector's informational scores")
    if n3.get("detectorDefinitionSHA256") != calibration.get("detectorDefinitionSHA256"):
        problems.append("they were scored under another definition")
    if n3.get("scoringCodeSHA256") != calibration.get("scoringCodeSHA256"):
        problems.append("they were scored by other scoring code")
    if n3.get("judgeIdentities") != calibration.get("judgeIdentities"):
        problems.append("a consumed judge's output identity differs from the calibration's")
    if (n3.get("cohort") or {}).get("population") != "N3":
        problems.append("their cohort is not N3")
    if problems:
        raise CalibrationError("the --n3-scores cannot be reported, nothing was recorded: " + "; ".join(problems))


def _timestamp(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_record(repository: Repository, entry: Mapping[str, Any], plan: thresholds.PreRegistration, *,
                 derived: Mapping[str, Any], outcome: Mapping[str, Any], calibration: Mapping[str, Any],
                 confirmation: Mapping[str, Any], inputs: Mapping[str, Any], disjointness: Mapping[str, Any],
                 phi: Sequence[Mapping[str, Any]], informational: Mapping[str, Any] | None,
                 informative: Mapping[str, bool], planned_at: int) -> dict:
    qualified = outcome["status"] == "qualified"

    def counts(units: Iterable[Mapping[str, Any]]) -> dict:
        units = list(units)
        return {"clips": len(units), "families": len({unit["family"] for unit in units}),
                "abstainedClips": sum(1 for unit in units if unit["score"] is None)}

    positives = [unit for cells in inputs["positives"].values() for scored in cells.values() for unit in scored]
    shams = [unit for scored in inputs["shams"].values() for unit in scored]
    calibration_negatives = _in_scope(calibration["units"], plan.population)
    sources = confirmation["sources"]
    injection = sources["injectionSet"]
    panels = [{"cohort": role, "bundleDigest": sources[key]["bundleDigest"], "startedAt": sources[key]["startedAt"]}
              for key, role in (("bundle", "N2"), ("positiveBundle", "P1+S")) if sources.get(key)]
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
        # What the scores depend on beside the judges (A7) and how the positives were built (A5).
        "evidence": {
            "scoringCodeSHA256": plan.binding("scoringCodeSHA256"),
            "evidenceIdentitySHA256": plan.binding("evidenceIdentitySHA256"),
            "orchestratorSHA256": list(confirmation["evidenceIdentity"]["orchestratorSHA256"]),
            "judgeMetrics": confirmation["evidenceIdentity"]["judgeMetrics"],
            "metricVersions": confirmation["evidenceIdentity"]["metricVersions"],
            "injectionSet": {"entriesSHA256": injection["entriesSHA256"],
                             "construction": dict(injection["construction"])},
            "planCommittedAt": _timestamp(planned_at),
            "confirmationPanels": panels,
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
        # A4 per injector; a cell whose shams are clean cohort audio is recorded but cannot fail.
        "a4": {"unit": "injector", "cells": sham_cells(entry),
               "uninformative": {injector: UNINFORMATIVE_SHAM
                                 for injector, flag in sorted(informative.items()) if not flag}},
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
    policy = repository.policy()
    point = policy["operatingPoints"][plan.binding("operatingPoint")]
    floors = point["minimumUnits"]
    derived = derivation(repository, entry, plan, calibration, int(floors["calibration"]))
    if derived["status"] != "derived":
        short = {key: item["calibrationUnits"] for key, item in derived["byStratum"].items()
                 if item["status"] != "derived"}
        raise CalibrationError(f"no threshold for {short} (calibration families per stratum); "
                               f"{next(iter(derived['byStratum'].values()))['minimumNegatives']} needed")
    _check_pair(plan, calibration, confirmation)
    expected_split = corpus_split(registry_lib.role_set(registry, entry), "confirmNegatives")
    if expected_split is not None and confirmation["cohort"].get("fleursSplit") != expected_split:
        raise CalibrationError(f"the confirmation scores are not of FLEURS {expected_split}")
    problems = confirmation_evidence_problems(repository, plan, confirmation)
    if problems:
        raise CalibrationError("the confirmation cannot start, nothing was recorded: " + "; ".join(problems))
    n3 = None
    if args.n3_scores:
        n3 = load_scores(args.n3_scores)
        check_n3(n3, calibration, entry)
    disjointness = thresholds.check_cohort_disjointness(
        plan, [(unit["family"], unit["speaker"], unit["scriptID"]) for unit in calibration["units"]],
        [(unit["family"], unit["speaker"], unit["scriptID"]) for unit in confirmation["units"]])
    inputs = confirmation_inputs(entry, confirmation["units"], plan.population)
    problems = preconditions(entry, inputs, point, confirmation)
    if problems:
        raise CalibrationError("the confirmation cannot start, nothing was recorded: " + "; ".join(problems))
    threshold = dict(derived["thresholds"])
    informative = sham_informative(entry, inputs)
    arguments = dict(
        operating_point=point, confidence=plan.confidence,
        n2_negatives=[_scored(unit, derived) for unit in inputs["negatives"]],
        positives={mechanism: {cell: [_scored(unit, derived) for unit in scored] for cell, scored in cells.items()}
                   for mechanism, cells in inputs["positives"].items()},
        shams={injector: [_scored(unit, derived) for unit in scored] for injector, scored in inputs["shams"].items()},
        sham_cells=sham_cells(entry), sham_minimum=int(floors["bad"]), sham_informative=informative)
    preview = thresholds.evaluate_confirmation(plan, threshold, **arguments)
    phi = phi_audits(entry, confirmation["units"], derived, plan.population)
    informational = informational_n3(n3["units"], derived) if n3 is not None else None
    record = build_record(repository, entry, plan, derived=derived, outcome=preview, calibration=calibration,
                          confirmation=confirmation, inputs=inputs, disjointness=disjointness, phi=phi,
                          informational=informational, informative=informative,
                          planned_at=repository.store.commit_time(plan))
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
    "verdict", "level", "reasons", "planSHA256", "detectorDefinitionSHA256", "registries", "cohorts", "evidence",
    "split", "speakers", "threshold", "counts", "rates", "a4", "phiAudit", "scope", "limitations", "risks",
    "informational", "ledgerOutcomeSHA256",
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
    evidence = record["evidence"] if isinstance(record["evidence"], Mapping) else {}
    if not is_sha256(evidence.get("scoringCodeSHA256")) or not is_sha256(evidence.get("evidenceIdentitySHA256")):
        errors.append("evidence pins the scoring code and the evidence identity by SHA-256")
    a4 = record["a4"] if isinstance(record["a4"], Mapping) else {}
    if not isinstance(a4.get("cells"), list) or not a4["cells"] \
            or not set(a4.get("uninformative") or {}) <= set(a4["cells"]):
        errors.append("a4 names its sham cells and which of them are uninformative")
    elif set((record["rates"] or {}).get("shams") or {}) != set(a4["cells"]):
        errors.append("rates.shams holds exactly the a4 cells")
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


def rewritten_files(repository: Repository) -> list[str]:
    """Plans, ledger entries and records that a commit in HEAD's history deleted, modified or renamed.

    They are written once (A5): deleting an unconfirmed plan to plan the same
    confirmation cohort again, or a ledger entry to confirm again, leaves this
    trace. Without Git history (not a checkout, a shallow boundary) nothing is
    reported.
    """
    directories = [path.relative_to(repository.root).as_posix()
                   for path in (repository.store.directory, repository.records)]
    try:
        result = subprocess.run(["git", "-C", str(repository.root), "log", "--diff-filter=DMR", "--format=",
                                 "--name-only", "--", *directories], capture_output=True, text=True, check=False)
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})


def repository_errors(repository: Repository) -> list[str]:
    registry = repository.registry()
    errors = [f"{REGISTRY}: {problem}" for problem in registry_lib.registry_errors(registry, repository.judges())]
    # A detector's current definition: a plan or record whose entry changed in place needs a version bump (A7).
    definitions = {entry["id"]: registry_lib.definition_digest(entry) for entry in registry.get("detectors") or ()
                   if isinstance(entry, Mapping) and isinstance(entry.get("id"), str)}

    def edited(detector: str, digest: Any) -> bool:
        return detector in definitions and definitions[detector] != digest

    errors.extend(f"{path}: a committed plan, ledger entry or record was later deleted, modified or renamed; "
                  "each is written once (A5)" for path in rewritten_files(repository))
    directory = repository.store.directory
    plans: dict[str, dict] = {}
    ledger: dict[str, str] = {}
    confirmed: set[str] = set()
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
                ledger[digest] = where
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
            if plan.binding("detectorDefinitionSHA256") is not None \
                    and edited(plan.detector, plan.binding("detectorDefinitionSHA256")):
                errors.append(f"{where}: {plan.detector}'s registry entry changed after its plan; a changed "
                              "definition needs a new version (A7)")
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
                confirmed.add(str(record.get("planSHA256")) if isinstance(record, Mapping) else "")
                continue
            confirmed.add(record["planSHA256"])
            if path.parent.name != record["detector"] or path.name != f"record-{record['planSHA256'][:16]}.json":
                errors.append(f"{where}: the record lives at {record['detector']}/record-<plan digest 16>.json")
            if edited(record["detector"], record["detectorDefinitionSHA256"]):
                errors.append(f"{where}: {record['detector']}'s registry entry changed after it was confirmed; a "
                              "changed definition needs a new version (A7)")
            if record["planSHA256"] not in plans:
                errors.append(f"{where}: its plan is not committed beside the ledger")
            outcome = repository.ledger.outcome(record["planSHA256"])
            if outcome is None or json_digest(outcome) != record["ledgerOutcomeSHA256"] \
                    or outcome.get("threshold") != record["threshold"]["values"] \
                    or outcome.get("status") != record["verdict"] or outcome.get("reasons") != record["reasons"] \
                    or any(outcome.get(key) != value for key, value in record["rates"].items()):
                errors.append(f"{where}: its ledger entry is missing or differs from it")
    # A ledger entry marks its plan confirmed for good; its record must exist beside it.
    errors.extend(f"{where}: a ledger entry without its record (the confirmation stopped after the ledger "
                  "write); the plan cannot be confirmed again" for digest, where in sorted(ledger.items())
                  if digest not in confirmed)
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
                            + (" (uninformative)" if sham.get("informative") is False else "")
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
    scores.add_argument("--n1-manifest", type=Path,
                        help="for an N2 cohort: the N1 manifest it pins (n1ManifestSHA256), naming its FLEURS split")
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
    plan.add_argument("--confirmation-n1-manifest", type=Path,
                      help="for an N2 confirmation cohort: the N1 manifest it pins, naming its FLEURS split")
    plan.add_argument("--calibration-scores", required=True, type=Path)
    plan.add_argument("--alpha", required=True, type=float)
    plan.add_argument("--operating-point", default="warn", choices=SUPPORTED_OPERATING_POINTS)
    plan.add_argument("--injection-catalog-seed", required=True, type=int,
                      help="the catalog seed the confirmation injection set will be built with")
    plan.add_argument("--injection-sample-seed", required=True, type=int)
    plan.add_argument("--injection-sample-per-cell", required=True, type=int)
    plan.add_argument("--injection-classes", required=True, type=injection_classes,
                      help="the classes the confirmation injection set will inject, comma-separated")
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
