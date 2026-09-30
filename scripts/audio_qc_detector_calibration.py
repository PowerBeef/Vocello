#!/usr/bin/env python3
"""AQ-07 qualification of the registered detectors at warn and fail (audit sections 5.4-5.9).

Each detector in `config/audio-qc-detectors.json` is qualified at one of the
policy's operating points on two cohorts its role set names: the calibration
cohort fits the threshold from clean clips only, and the untouched
confirmation cohort, with the positives and shams built over it, confirms it
once. No model runs here; the panel and the Stage 0 scorer produce the inputs.

Operating points. `warn` (the default) is what AQ-07 confirms first. A `fail`
point (`fail`, or `evidenceLaneFail`, whose policy `appliesTo` keeps it off
product lanes; decision 5) is pre-registered as its own plan beside the warn
plan of the same detector version (`<id>.fail.json`) and confirmed once on its
own: FAR on N2 at <= 1% pooled and <= 5% per language over all ten languages
(1,240 families, 124 per language; the calibration cohort is held to the same
floor per stratum), the N3 flag rate on an N3 cohort the plan names
(`n3CohortDigest`, scored after the plan under `--role bound`, 60 families
per language; A2), detection >= 0.90 on severe and >= 0.70 on moderate cells
of two construction mechanisms (A3), shams per injector, and clean abstention
<= 5%. A detector whose definition cannot meet that (confirmed on N3, fewer
than ten languages, fewer than two mechanisms with severe and moderate cells)
is refused at plan time. A qualified record's `level` is `fail` and carries the
N3 bound, which the lane gates accept for fail and warn gates.

Cohorts per role set (`COHORT_RULES`), each with the disjointness it proves on
the ids at plan and confirm time:

- `fleurs-n2`: FLEURS dev and test N2 (or N1), disjoint by family and script;
  FLEURS publishes no speaker ids, so each unit's speaker is
  `<language>:fleurs-unidentified`, a lower bound (a declared limitation).
  Dev and test are spent: the v1 warn plans confirmed on test.
- `fleurs-reserve-n2` (and `accent-natural-n2`'s negatives): FLEURS train's
  reserve cohorts N2 (or N1), by a fixed rule the role set states: reserve-1
  fits, reserve-2 confirms at warn, reserve-3 (`failCorpus`) is held back for
  a fail point. Every reserve cohort past the first is a confirmation split,
  never scored for calibration or information, and a FLEURS corpus a
  confirmed plan scored is refused as any new plan's confirmation, whichever
  resynthesis of it the plan names (A5).
- `speaker-labeled-n2`: N2 (or N1) of a speaker-labelled corpus, the N1
  manifest naming its `split` (calibration or confirmation), its `corpus` and
  each recording's `speaker`; disjoint by family, speaker and script. The
  role set names the corpus (`<corpus>-calibration`, `<corpus>-confirmation`):
  the class E speaker cohort `audio_qc_corpora.py cohort --source speaker`
  writes, each take naming its reference clip. A confirmed plan spends the
  corpus's confirmation split, whichever resynthesis of it a new plan names.
- `n3-takes`, `n3-codec-trace`, `n3-controlled-generation`: the two splits of
  the N3 take plan (`audio_qc_calibration_takes.py`), disjoint by family (script
  x voice x seed), speaker (a Built-in speaker or a Voice Design brief, never
  shared across splits) and script (the pool's split).
- `n3-long-form`: long-form N3 takes (the take plan's `long-form` cell), each
  carrying a `longForm` block with at least one seam; disjoint as N3.

A role whose corpus is still `pending-...` in the registry is not plannable.
Positives are the role set's population: P1 (a T1 PCM injection), P2 (a T2
codec-trace mutation, `injection.provenance` naming the trace, recipe and
decoder digests) or P3 (a T3 knob take, naming the knob and recipe), each
beside its S shams; this driver reads them from an injection set and builds
none. A `T4-natural-labelled` target's positives are instead a labelled
corpus's own recordings (P4, `accent-natural-n2`: non-native speech with a low
published pronunciation score): the role set declares the label tier, source,
field and rules, `plan --natural-positives` binds the corpus's cohort (its
confirmation split, N2 like the negatives, sharing no speaker, family or
script with them) and the label rule, and `scores --role confirmation
--natural-positives` reads each take's label from its manifest or its N1
recording, keeps the takes the rule turns into a severity the target declares,
and scores them from their own panel (`--natural-bundle`, computed after the
plan like every confirmation panel) and measurements. They have no sham (A4
matches processed positives), and a detector whose positives are all natural
plans no injection set. The cohort is the corpus split the role set names
(`<corpus>-confirmation`, as `audio_qc_corpora.py cohort` writes it), and a
published (T4) label labels a positive only under a dated exception of the
qualification policy (`labelTierExceptions`) naming the detector, the corpus,
the label field and the positives' languages; the plan binds the corpus split
(`naturalPositivesSource`), which a confirmation spends.

Every input is bound to what it claims to measure: a cohort manifest to its own
`manifestDigest`; a panel bundle to its `bundleDigest`, and each evidence
record to its take's audio digest, text digest and language in the cohort or
the injection set; `measurements.json` to its `clipsSHA256`, the takes manifest
and injection set it names, and each clip's audio digest; an injection set to
its `entriesSHA256` and to the cohort manifest it was built on (always checked).

Commands:
  scores   --detector ID --role calibration|confirmation|informational|bound --cohort MANIFEST
           [--n1-manifest FILE] [--bundle DIR] [--measurements FILE] [--injection-set FILE]
           [--positive-bundle DIR] [--positive-measurements FILE] [--raw-outputs FILE ...]
           [--positive-raw-outputs FILE ...] [--natural-positives MANIFEST --natural-n1-manifest FILE
           --natural-bundle DIR [--natural-measurements FILE]]
           [--operating-point warn|fail|evidenceLaneFail] --output FILE
           Per-unit scores (family, language, speaker, script, population,
           injector, severity, score or abstention with its reason, and each
           component), ids and digests only, with the scoring code's digest and
           the evidence identity (orchestrator source, metric versions). An N2
           cohort names its split (and a labelled corpus its speakers) through
           the N1 manifest it pins (--n1-manifest); an N3 takes manifest names
           its take-plan split. Positives are the injection set's entries, of
           the role set's positive population. A `raw-output` detector reads
           its judge's raw output from `audio_qc_calibration_set.py
           raw-outputs` exports bound to the manifest and bundle (a missing
           output is an evidence gap), a seam measure a long-form take's seams,
           and a speaker detector requires the panel to have embedded the
           reference clip each take declares. A confirmation role needs the
           detector's committed plan naming that cohort, the planned injection
           construction and panels computed from scratch after the plan (see
           confirm); calibration and informational roles refuse the role set's
           confirmation split (FLEURS test, the confirmation take split) and
           any cohort a plan names as confirmation or as its N3 bound (A5). The
           bound role scores a fail plan's N3 cohort (--operating-point names
           the plan), fresh after the plan like a confirmation panel.
  plan     --detector ID --calibration-cohort MANIFEST --confirmation-cohort MANIFEST
           [--confirmation-n1-manifest FILE] [--calibration-n1-manifest FILE]
           --calibration-scores FILE --alpha A [--injection-catalog-seed N
           --injection-sample-seed N --injection-sample-per-cell N --injection-classes A,B,...]
           [--injection-catalog-version N] [--tier-catalog-version T2=N ...]
           [--natural-positives MANIFEST --natural-n1-manifest FILE]
           [--operating-point warn|fail|evidenceLaneFail] [--n3-cohort MANIFEST]
           Write config/audio-qc-preregistrations/<id>.json (<id>.<point>.json
           at a fail point, with its N3 cohort): the split-conformal rule,
           alpha (below the point's FAR bound), the declared cohort split
           (both manifests by kind and digest, what the role set's cohorts are
           disjoint by, the speaker unit and claim, the limitations) and the
           bindings (definition, calibration scores, policy, scoring code,
           evidence identity, and the confirmation-side injection construction
           with its catalog version: this repository's injector catalog and
           the calibration set's schedule (`injectionSchedule`) for P1, the
           declared one for P2 or P3; for natural positives, their cohort's
           digest, corpus split and label rule instead). Refuses a role set whose corpus is
           pending, calibration scores below the calibration floor per stratum,
           with missing evidence, or from a panel whose orchestrator, metric
           reduction or metric versions are not the current code's (the
           confirmation panels will run it), a confirmation cohort that is not
           the role set's confirmation split (at a fail point its held-back
           `failCorpus`, when it names one), cohorts that share a family,
           script or (where identified) speaker, a cohort another plan uses in
           the other role, a confirmation cohort that already holds scores,
           a panel bundle or measurements, and a FLEURS or labelled corpus a
           confirmed plan already scored, whichever resynthesis of it the
           cohort is. The lead reviews and commits it.
  derive   --detector ID --calibration-scores FILE [--output FILE] [--operating-point P]
           The split-conformal threshold from the calibration cohort's clean
           N2 scores, one per family, per declared stratum (language) or
           pooled, each stratum at least the calibration floor; refuses a plan
           not committed at HEAD.
  confirm  --detector ID --calibration-scores FILE --confirmation-scores FILE [--n3-scores FILE]
           [--operating-point P]
           Once per plan digest. Before anything is recorded: the bindings and
           output, evidence and scoring-code identities across both cohorts
           (A7), the planned injection construction, confirmation panels
           computed from scratch after the plan's commit (a start time after
           it, an empty cache root, no L1 hit, no adoption), every expected
           unit present with evidence and no failed judge row (an unavailable
           row is the run's failure, not an abstention), and the point's
           minimums counted on scored units (warn: negatives, positives per
           severe cell, a sham cell per injector; fail: see above, with its N3
           bound scores). Then the confirmation negatives, the positives and
           the S shams (and at fail the N3 bound) against the plan's operating
           point (evaluate_confirmation),
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
           without its record; a plan or record at an operating point that
           refuses its detector's combination (a fail point refuses a
           two-family mean); and any plan, ledger entry or record a commit
           later deleted, modified or renamed (contract gate).
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from audio_qc_calibration_takes import long_form_issues, seam_seconds, voice_key  # noqa: E402
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
# FLEURS train's reserve cohorts (`audio_qc_corpora.py extract`: an N1 manifest of split `reserve-<k>`, FLEURS
# split train, with its `reserve` block), disjoint by FLoRes sentence from dev, test and each other. Their role
# sets follow one fixed rule, which the registry states: reserve-1 fits, reserve-2 confirms at warn and reserve-3
# (`failCorpus`) is held back for a fail point; no reserve cohort past the first is ever scored for calibration or
# information (A5).
RESERVE_SPLIT = re.compile(r"reserve-([1-9][0-9]*)")
# The split a non-FLEURS cohort declares (the N3 take plan's, a speaker-labelled N1 manifest's).
DECLARED_SPLITS = ("calibration", "confirmation")
# The splits a confirmation (or a fail plan's N3 bound) draws from, whatever the role set (and every reserve
# cohort past the first, `is_confirmation_split`).
CONFIRMATION_SPLITS = ("test", "confirmation")
# A FLEURS-derived corpus names fixed recordings (dev, test, a reserve cohort of the pinned sampling): once a
# confirmation scored it, no new plan confirms on it, whichever N2 resynthesis of it the plan names (A5).
FLEURS_CORPUS_PREFIX = "fleurs-"
# What an N1 (or N3) manifest names of its split, corpus and speakers.
SOURCE_KEYS = ("split", "fleursSplit", "corpus", "dataset", "reserve")
# `bound`: the N3 cohort a fail plan bounds the flag rate on (A2), scored after the plan like a confirmation.
ROLES = ("calibration", "confirmation", "informational", "bound")
SUPPORTED_OPERATING_POINTS = ("warn", "fail", "evidenceLaneFail")
# The level a qualified record at each operating point gates at (audit 3.3; decision 5): the evidence-lane
# fail point is a fail level whose policy `appliesTo` keeps it off product lanes.
POINT_LEVELS = {"warn": "warn", "fail": "fail", "evidenceLaneFail": "fail"}
FAIL_POINTS = tuple(point for point, level in POINT_LEVELS.items() if level == "fail")
# The severities a fail point measures detection on, per mechanism (tprSevereMin, tprModerateMin).
FAIL_SEVERITIES = frozenset(thresholds.SEVERITY_FLOORS)
FLEURS_SPEAKER_UNIT = "language:fleurs-unidentified"
FLEURS_DISJOINT_BY = ("family", "script")
# A role set whose corpus the registry still names `pending-...` has no data decision yet.
PENDING_CORPUS_PREFIX = "pending-"
# P2 and P3 positives are declared with their provenance (audit 5.1, T2 and T3); P1's is its T1 recipe.
POSITIVE_PROVENANCE = {"P2": ("T2", ("traceSHA256", "recipeSHA256", "decoderSHA256")),
                       "P3": ("T3", ("knob", "recipeSHA256"))}
# The positive population each construction tier builds (audit 5.1: P1 PCM, P2 codec, P3 knob), and the
# natural failures a corpus labels (P4, `T4-natural-labelled`: read from their own cohort, never constructed).
TIER_POPULATIONS = {"T1": "P1", "T2": "P2", "T3": "P3", "T4": "P4"}
POPULATION_TIERS = {population: tier for tier, population in TIER_POPULATIONS.items()}
# A registered generation knob's id (config/runtime-debug-knobs.json style): an identifier, never free text.
KNOB_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


@dataclass(frozen=True)
class CohortRule:
    """What a role set's cohorts are and what their split proves."""
    name: str
    kinds: frozenset[str]
    fleurs: bool
    disjoint_by: tuple[str, ...]
    speaker_unit: str
    speaker_claim: str
    long_form: bool = False


FLEURS_RULE = CohortRule("fleurs", FLEURS_KINDS, True, FLEURS_DISJOINT_BY, FLEURS_SPEAKER_UNIT, "lower-bound")
SPEAKER_LABELED_RULE = CohortRule("speaker-labeled", FLEURS_KINDS, False, ("family", "speaker", "script"),
                                  "corpus-speaker", "identified")
TAKES_RULE = CohortRule("vocello-takes", frozenset({N3_KIND}), False, ("family", "speaker", "script"),
                        "vocello-voice", "identified")
COHORT_RULES = {
    "fleurs-n2": FLEURS_RULE,
    "fleurs-reserve-n2": FLEURS_RULE,
    "accent-natural-n2": FLEURS_RULE,
    "speaker-labeled-n2": SPEAKER_LABELED_RULE,
    "n3-takes": TAKES_RULE,
    "n3-codec-trace": TAKES_RULE,
    "n3-controlled-generation": TAKES_RULE,
    "n3-long-form": replace(TAKES_RULE, name="vocello-long-form", long_form=True),
}
MAX_RECORD_BYTES = 64 * 1024
PI_MAX = (0.05, 0.10, 0.20)
SKIPPED_DIRECTORIES = frozenset({"roundtrip", "inputs", "logs", "wav", "evidence", "private", "batches",
                                 "batch-out", "batch-results"})
# An in-scope unit whose expected evidence is absent (the bundle lacks the take, a consumed judge was not
# run on it, measurements.json lacks the clip, or the raw-output export lacks the judge's output for it):
# never a qualification input.
EVIDENCE_GAPS = ("no-evidence", "not-measured", "no-raw-output")
RAW_OUTPUTS_KIND = "audio-qc-raw-outputs"
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
# A second construction tier's catalog version (a fail point's T2 beside T1): `injectorCatalogVersionT2`.
TIER_CATALOG_BINDING = "injectorCatalogVersion"
INJECTION_BINDINGS = {"catalogVersion": "injectorCatalogVersion", "catalogSeed": "injectionCatalogSeed",
                      "sampleSeed": "injectionSampleSeed", "samplePerCell": "injectionSamplePerCell",
                      "classes": "injectionClasses"}
# Which variants the set draws beside the sweep (audio_qc_calibration_set.SCHEDULE_VERSION): a P1 plan binds the
# schedule of the code it was planned with; a plan without the binding (every v1 plan) expects schedule 1.
SCHEDULE_BINDING = "injectionSchedule"
UNSCHEDULED = 1


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
        # FLEURS-derived until `resolve_cohort` reads a speaker-labelled corpus's labels.
        speaker = _voice_speaker(take.get("voice")) if kind == N3_KIND else f"{language}:fleurs-unidentified"
        label = take.get("speaker")
        takes[take_id] = {"takeID": take_id, "family": take["family"], "language": language,
                          "scriptID": str(take.get("scriptID")), "speaker": speaker,
                          "wavSHA256": take["wavSHA256"], "textSHA256": text,
                          "speakerLabel": label if isinstance(label, str) and label else None,
                          "n1TakeID": take.get("n1TakeID"), "seams": _seams(take.get("longForm"), f"{name}: {take_id}"),
                          "referenceSHA256": reference_digest(take, f"{name}: {take_id}")}
    if not takes:
        raise CalibrationError(f"{name} has no eligible takes")
    return {"kind": kind, "population": population, "manifestDigest": digest, "fileSHA256": file_sha256(path),
            "runID": manifest.get("runID"), "takes": takes, "directory": Path(path).resolve().parent, "name": name,
            "fleursSplit": manifest.get("fleursSplit") if kind == N1_KIND else None,
            "n1ManifestSHA256": manifest.get("n1ManifestSHA256") if kind == N2_KIND else None,
            # What names the split and the speakers: the manifest itself (N1, N3) or the N1 an N2 pins.
            "source": {key: manifest.get(key) for key in SOURCE_KEYS} if kind != N2_KIND else None}


def _voice_speaker(voice: Any) -> str:
    """An N3 take's speaker: its Built-in speaker or its Voice Design brief (the take plan's voice key); a
    voice of another kind (a clone) by a digest of its identity."""
    voice = voice if isinstance(voice, Mapping) else {}
    try:
        return f"voice:{voice_key(dict(voice))}"
    except (KeyError, TypeError):
        return f"voice:{voice.get('kind')}-{json_digest(dict(voice))[:16]}"


def reference_digest(take: Mapping[str, Any], where: str) -> str | None:
    """The WAV digest of the reference clip a take declares (`reference`: another utterance of its speaker, or
    a clone's reference), which a speaker judge scores it against; None when it declares none."""
    reference = take.get("reference")
    if reference is None:
        return None
    digest = reference.get("wavSHA256") if isinstance(reference, Mapping) else None
    if not is_sha256(digest) or not isinstance(reference.get("wavPath"), str):
        raise CalibrationError(f"{where}: its reference names its WAV path and digest")
    if digest == take.get("wavSHA256"):
        raise CalibrationError(f"{where}: a take is never its own reference clip")
    return digest


def _seams(block: Any, where: str) -> list[float] | None:
    """A long-form take's seam times in seconds, or None for a take without a `longForm` block."""
    if block is None:
        return None
    issues = long_form_issues(block)
    if issues:
        raise CalibrationError(f"{where}: {issues[0]}")
    return seam_seconds(block)


def resolve_cohort(cohort: dict, n1_manifest: Path | None) -> str | None:
    """The split a cohort was drawn from, finalizing each take's speaker where the corpus labels it.

    FLEURS (an N1 manifest naming its `fleursSplit`): dev or test, or a train
    reserve cohort by its `split` (`reserve-<k>`, which its `reserve` block
    confirms), and speakers stay `<language>:fleurs-unidentified`. A
    speaker-labelled corpus: the N1
    manifest's `split` (calibration or confirmation), and each take's speaker is
    its corpus label (the take's own `speaker`, else its N1 recording's through
    `n1TakeID`), digested with the corpus name. An N3 takes manifest: its take
    plan's split. An N2 manifest pins its N1 manifest by file digest
    (`n1ManifestSHA256`), which must then be given.
    """
    if cohort["kind"] != N2_KIND and n1_manifest is not None:
        raise CalibrationError("an N1 manifest is given only for an N2 cohort, which pins it by n1ManifestSHA256")
    source, labels = cohort["source"], {}
    if cohort["kind"] == N3_KIND:
        split = source.get("split")
        if split not in DECLARED_SPLITS:
            raise CalibrationError(f"{cohort['name']} names no take-plan split ({' or '.join(DECLARED_SPLITS)})")
        return split
    if cohort["kind"] == N2_KIND:
        if n1_manifest is None:
            raise CalibrationError(f"{cohort['name']} is an N2 cohort: pass the N1 manifest it was resynthesized "
                                   "from (n1ManifestSHA256) so its FLEURS split is known (A5)")
        if file_sha256(n1_manifest) != cohort["n1ManifestSHA256"]:
            raise CalibrationError(f"{Path(n1_manifest).name} is not the N1 manifest {cohort['name']} pins "
                                   "(n1ManifestSHA256)")
        document = load_json(n1_manifest, "the N1 manifest")
        if not isinstance(document, dict) or document.get("kind") != N1_KIND:
            raise CalibrationError(f"{Path(n1_manifest).name} is not an {N1_KIND} manifest")
        source = {key: document.get(key) for key in SOURCE_KEYS}
        labels = {take.get("takeID"): take.get("speaker") for take in document.get("takes") or ()
                  if isinstance(take, Mapping)}
    if source.get("fleursSplit") is not None or source.get("split") not in DECLARED_SPLITS:
        split = source.get("fleursSplit")
        if split == "train":
            split = reserve_split(cohort, source)
        if not is_fleurs_split(split):
            raise CalibrationError(f"{cohort['name']} names no FLEURS split ({' or '.join(FLEURS_SPLITS)} or a "
                                   "train reserve cohort)")
        return split
    corpus = str(source.get("corpus") or source.get("dataset") or "")
    for take_id, take in cohort["takes"].items():
        label = take["speakerLabel"] or labels.get(take["n1TakeID"])
        if not isinstance(label, str) or not label or not corpus:
            raise CalibrationError(f"{cohort['name']}: {take_id} names no speaker or corpus; a corpus other than "
                                   "FLEURS labels each recording's speaker")
        take["speaker"] = "speaker:" + hashlib.sha256(f"{corpus}|{label}".encode("utf-8")).hexdigest()[:16]
    cohort["corpus"] = corpus
    return source["split"]


def reserve_index(split: Any) -> int | None:
    """k of a FLEURS train reserve cohort's split `reserve-<k>`, else None."""
    match = RESERVE_SPLIT.fullmatch(split) if isinstance(split, str) else None
    return int(match.group(1)) if match else None


def is_fleurs_split(split: Any) -> bool:
    """FLEURS dev, test or a train reserve cohort."""
    return split in FLEURS_SPLITS or reserve_index(split) is not None


def is_confirmation_split(split: Any) -> bool:
    """A split never scored for calibration or information: FLEURS test, a declared confirmation split, or a
    reserve cohort past the first (the second confirms at warn, the later ones are held back)."""
    return split in CONFIRMATION_SPLITS or (reserve_index(split) or 0) > 1


def reserve_split(cohort: Mapping[str, Any], source: Mapping[str, Any]) -> str:
    """A FLEURS train cohort's split: a reserve cohort, named by its manifest's `split` and its `reserve` block."""
    split = source.get("split")
    block = source.get("reserve")
    if reserve_index(split) is None or not isinstance(block, Mapping) or block.get("cohort") != reserve_index(split):
        raise CalibrationError(f"{cohort['name']}: a FLEURS train cohort is a reserve cohort, split reserve-<k> with "
                               "its reserve block (audio_qc_corpora.py extract)")
    return split


def cohort_rule(entry: Mapping[str, Any]) -> CohortRule:
    rule = COHORT_RULES.get(entry.get("populations"))
    if rule is None:
        raise CalibrationError(f"{entry.get('id')}: this driver has no cohort rule for role set "
                               f"{entry.get('populations')!r}")
    return rule


def role_corpus(roles: Mapping[str, Any], role: str, operating_point: str = "warn") -> str:
    """The corpus a role's cohort comes from: at a fail point the confirmation's held-back corpus, when the role
    set names one (`failCorpus`), else the role's `corpus`."""
    value = roles.get(role) or {}
    if role == "confirmNegatives" and operating_point in FAIL_POINTS and value.get("failCorpus"):
        return str(value["failCorpus"])
    return str(value.get("corpus") or "")


def corpus_split(roles: Mapping[str, Any], role: str, operating_point: str = "warn") -> str | None:
    """The FLEURS split a role set declares for a role (`fleurs-dev` -> dev, `fleurs-reserve-2` -> reserve-2), or
    None for another corpus."""
    corpus = role_corpus(roles, role, operating_point)
    return corpus.removeprefix(FLEURS_CORPUS_PREFIX) if corpus.startswith(FLEURS_CORPUS_PREFIX) else None


def expected_split(rule: CohortRule, roles: Mapping[str, Any], role: str, operating_point: str = "warn") -> str | None:
    """The split a role's cohort must come from: a FLEURS split (dev, test or a reserve cohort; a fail point's
    confirmation its held-back one), or the declared calibration or confirmation split (the role's own cohort)."""
    return corpus_split(roles, role, operating_point) if rule.fleurs else (roles.get(role) or {}).get("cohort")


def split_name(split: str | None) -> str:
    return f"FLEURS {split}" if is_fleurs_split(split) else f"the {split} split"


def scores_split(scores: Mapping[str, Any]) -> str | None:
    """The split a scores document's cohort came from."""
    cohort = scores.get("cohort") or {}
    return cohort.get("fleursSplit") or cohort.get("split")


def cohort_rule_problems(cohort: Mapping[str, Any], rule: CohortRule, roles: Mapping[str, Any]) -> list[str]:
    """Why a cohort is not one of its role set's (kind, long-form seams, a pending corpus)."""
    problems = []
    if cohort["kind"] not in rule.kinds:
        problems.append(f"{cohort['name']} is an {cohort['kind']} manifest; the {rule.name} cohorts are "
                        f"{' or '.join(sorted(rule.kinds))}")
    if rule.long_form:
        flat = sorted(take_id for take_id, take in cohort["takes"].items() if not take.get("seams"))
        if flat:
            problems.append(f"{len(flat)} takes of {cohort['name']} carry no long-form seam (e.g. {flat[0]}); a "
                            "long-form cohort holds assembled projects with at least one seam")
    return problems


def pending_corpora(roles: Mapping[str, Any]) -> list[str]:
    return [f"{role} ({roles[role]['corpus']})" for role in ("fit", "confirmNegatives", "positives")
            if str((roles.get(role) or {}).get("corpus") or "").startswith(PENDING_CORPUS_PREFIX)]


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
    schedule = data.get("schedule")
    if isinstance(schedule, dict):
        # The variants the set drew beside the sweep (a set without one drew schedule 1, the sweep alone).
        construction["schedule"] = schedule.get("version")
    tiers: dict[str, set[int]] = {}
    for entry in data["entries"]:
        injection = entry.get("injection") if isinstance(entry, dict) else None
        if isinstance(injection, dict) and isinstance(injection.get("catalogVersion"), int) \
                and not isinstance(injection.get("catalogVersion"), bool):
            tier = str(injection.get("mechanism") or "T1-").split("-", 1)[0]
            tiers.setdefault(tier, set()).add(injection["catalogVersion"])
    if set(tiers) - {"T1"}:
        # A declared T2 or T3 construction: each tier's catalog versions, bound per tier by the plan.
        construction["tierCatalogVersions"] = {tier: sorted(versions) for tier, versions in sorted(tiers.items())}
    return {"entries": data["entries"], "sourceManifestSHA256": source["sha256"], "fileSHA256": file_sha256(path),
            "entriesSHA256": data["entriesSHA256"], "construction": construction, "name": name}


def load_raw_outputs(path: Path) -> dict:
    """A raw-output export (`audio_qc_calibration_set.py raw-outputs`): one judge's raw output per take."""
    name = Path(path).name
    data = load_json(path, "the raw-output export")
    if not isinstance(data, dict) or data.get("kind") != RAW_OUTPUTS_KIND or data.get("schemaVersion") != 1 \
            or not isinstance(data.get("takes"), dict):
        raise CalibrationError(f"{name} is not an {RAW_OUTPUTS_KIND} schema 1 file")
    if json_digest(data["takes"]) != data.get("takesSHA256"):
        raise CalibrationError(f"{name}: its takes differ from its takesSHA256 (edited after the export)")
    judge = (data.get("judge") or {}).get("judge")
    source = (data.get("takesManifest") or {}).get("sha256")
    bundle = (data.get("bundle") or {}).get("bundleDigest")
    if not isinstance(judge, str) or not is_sha256(source) or not is_sha256(bundle):
        raise CalibrationError(f"{name} names no judge, takes manifest or bundle")
    return {"judge": judge, "takes": data["takes"], "sourceSHA256": source, "bundleDigest": bundle,
            "fileSHA256": file_sha256(path), "takesSHA256": data["takesSHA256"], "name": name}


def load_natural_positives(entry: Mapping[str, Any], roles: Mapping[str, Any], path: Path,
                           n1_manifest: Path | None, *, bundle: "Bundle | None" = None,
                           measurements: Mapping[str, Any] | None = None) -> dict:
    """A detector's natural labelled positives: a labelled corpus's cohort (N2, resynthesized like the negatives),
    each take's label read from its manifest or its N1 recording's (the role set's `labels.field`) and turned into
    a severity by the label rules. Only takes whose severity the natural target declares are positives; the rest
    are counted as outside the rule. The cohort is its corpus's confirmation split, with its speakers."""
    targets = registry_lib.natural_targets(entry)
    labels = (roles.get("positives") or {}).get("labels")
    if not targets or not isinstance(labels, Mapping):
        raise CalibrationError(f"{entry['id']} declares no natural labelled positives")
    cohort = load_cohort(path)
    split = resolve_cohort(cohort, n1_manifest)
    if split != "confirmation":
        raise CalibrationError(f"{cohort['name']}: natural positives are their corpus's confirmation split, not "
                               f"{split_name(split)}")
    if cohort["population"] != roles["confirmNegatives"]["population"]:
        raise CalibrationError(f"{cohort['name']} is {cohort['population']}; natural positives are measured in the "
                               f"negatives' domain ({roles['confirmNegatives']['population']})")
    declared = (roles.get("positives") or {}).get("corpus")
    if declared and declared != f"{cohort.get('corpus')}-{split}":
        raise CalibrationError(f"{cohort['name']}: natural positives are {cohort.get('corpus')}-{split}; the role set "
                               f"names {declared}")
    own = {take.get("takeID"): take for take in load_json(path, "the natural positives").get("takes") or ()
           if isinstance(take, Mapping)}
    recordings = {} if n1_manifest is None else {
        take.get("takeID"): take for take in load_json(n1_manifest, "the N1 manifest").get("takes") or ()
        if isinstance(take, Mapping)}
    (target,) = targets
    severities: dict[str, str] = {}
    outside = 0
    for take_id, take in cohort["takes"].items():
        value = registry_lib.label_value(own.get(take_id) or {}, labels["field"])
        if value is None:
            value = registry_lib.label_value(recordings.get(take["n1TakeID"]) or {}, labels["field"])
        severity = registry_lib.label_severity(labels, value)
        if severity in target["severities"]:
            severities[take_id] = severity
        else:
            outside += 1
    return {"cohort": cohort, "split": split, "labels": dict(labels), "labelsSHA256": json_digest(dict(labels)),
            "target": target, "severities": severities, "outsideRule": outside, "bundle": bundle,
            "measurements": measurements}


def natural_source(natural: Mapping[str, Any]) -> dict:
    """What a scores document and a plan pin of the natural positives: the cohort and the label rule."""
    cohort = natural["cohort"]
    return {"kind": cohort["kind"], "manifestDigest": cohort["manifestDigest"], "fileSHA256": cohort["fileSHA256"],
            "corpus": cohort.get("corpus"), "split": natural["split"], "labelsSHA256": natural["labelsSHA256"],
            "positives": len(natural["severities"]), "outsideRule": natural["outsideRule"]}


def natural_label_problems(policy: Mapping[str, Any], entry: Mapping[str, Any], natural: Mapping[str, Any]) -> list[str]:
    """Why the policy does not admit the natural positives' labels. A published label (T4) qualifies negatives
    only, unless a dated, detector-scoped exception (`labelTierExceptions`) names this detector, the corpus, the
    label field and every language the positives are in."""
    labels, cohort = natural["labels"], natural["cohort"]
    corpus = cohort.get("corpus")
    languages = sorted({take["language"] for take in cohort["takes"].values()})
    for exception in policy.get("labelTierExceptions") or ():
        if not isinstance(exception, Mapping):
            continue
        if (exception.get("tier"), exception.get("population"), exception.get("detector"), exception.get("corpus"),
                exception.get("field")) != (labels.get("tier"), TIER_POPULATIONS["T4"], entry["id"], corpus,
                                            labels.get("field")):
            continue
        outside = [language for language in languages if language not in (exception.get("languages") or ())]
        return [f"the policy admits {corpus}'s {labels.get('field')} as positive labels in "
                f"{', '.join(exception.get('languages') or ()) or 'no language'} only, not "
                f"{', '.join(outside)}"] if outside else []
    return [f"the policy lets {labels.get('tier')} published labels qualify negatives only, and no labelTierExceptions "
            f"entry admits {corpus}'s {labels.get('field')} as positive labels for {entry['id']}"]


def raw_output_judges(entry: Mapping[str, Any]) -> set[str]:
    return {component["judge"] for component in registry_lib.components_of(entry)
            if component.get("source") == "raw-output"}


def bind_raw_outputs(entry: Mapping[str, Any], exports: Sequence[Mapping[str, Any]], *, source_sha256: str,
                     bundle: "Bundle | None", what: str) -> dict[str, Mapping[str, Any]]:
    """The detector's raw-output exports by judge, each bound to the manifest the panel ran over and its bundle."""
    wanted = raw_output_judges(entry)
    found: dict[str, Mapping[str, Any]] = {}
    for export in exports:
        if export["judge"] not in wanted:
            raise CalibrationError(f"{export['name']} exports {export['judge']}, which {entry['id']} does not reduce")
        if export["judge"] in found:
            raise CalibrationError(f"{what}: two exports of {export['judge']}")
        if export["sourceSHA256"] != source_sha256:
            raise CalibrationError(f"{export['name']} was exported for another manifest than the {what}")
        if bundle is None or export["bundleDigest"] != bundle.identity()["bundleDigest"]:
            raise CalibrationError(f"{export['name']} was exported from another panel bundle than the {what}'s")
        found[export["judge"]] = export
    missing = sorted(wanted - set(found))
    if missing:
        raise CalibrationError(f"{entry['id']} reduces the raw output of {', '.join(missing)}: pass the {what}'s "
                               "export (audio_qc_calibration_set.py raw-outputs)")
    return found


def raw_for(take_id: str, audio_sha256: str, evidence: Mapping[str, Mapping] | None,
            exports: Mapping[str, Mapping[str, Any]], where: str) -> dict[str, Mapping[str, Any]]:
    """The take's raw output per judge; a judge without a complete exported output is left out (the unit then
    abstains no-raw-output, an evidence gap). The export must hold the audio and output identity the evidence
    records."""
    raw: dict[str, Mapping[str, Any]] = {}
    for judge, export in exports.items():
        record = export["takes"].get(take_id)
        if not isinstance(record, Mapping) or record.get("status") != "complete":
            continue
        measurement = (evidence or {}).get(judge) or {}
        if record.get("audioSHA256") != audio_sha256:
            raise CalibrationError(f"{where}: {export['name']} holds another audio's {judge} output")
        if record.get("outputIdentity") != measurement.get("outputIdentity"):
            raise CalibrationError(f"{where}: {export['name']} holds {judge} output of another identity than its "
                                   "evidence")
        if isinstance(record.get("output"), Mapping):
            raw[judge] = record["output"]
    return raw


def reference_judges(entry: Mapping[str, Any]) -> set[str]:
    """The panel judges whose metrics a detector reads only against a reference clip (the speaker families)."""
    from lib.qc_pipeline.panel_jobs import PanelJobError, profile  # deferred: read only for speaker detectors

    judges = set()
    for component in registry_lib.components_of(entry):
        if component.get("source") != "panel":
            continue
        try:
            if profile(component["judge"]).needs_reference:
                judges.add(component["judge"])
        except PanelJobError:
            continue
    return judges


def check_reference(private: Mapping[str, Any] | None, declared: str | None, where: str) -> None:
    """The panel embedded the reference clip the manifest declares for the take, or none when it declares none
    (the orchestrator records its digest in the take's private file)."""
    embedded = (private or {}).get("referenceAudioSHA256")
    if embedded == declared:
        return
    if declared is None:
        raise CalibrationError(f"{where}: the panel scored it against a reference clip its manifest does not declare")
    if embedded is None:
        raise CalibrationError(f"{where}: its manifest declares a reference clip the panel did not embed (build the "
                               "panel manifest with the current audio_qc_orchestrator.py manifest)")
    raise CalibrationError(f"{where}: its evidence was measured against another reference clip than its manifest's")


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


def positive_populations(roles: Mapping[str, Any], entry: Mapping[str, Any]) -> tuple[str, ...]:
    """The positive populations a detector's confirmation reads: its role set's, then the population of each
    other construction tier its targets declare (a fail point's second mechanism, A3: T1 P1 beside T2 P2)."""
    primary = roles["positives"]["population"]
    tiers = {TIER_POPULATIONS.get(str(target["mechanism"]).split("-", 1)[0]) for target in entry.get("targets") or ()}
    return (primary, *sorted(population for population in tiers if population and population != primary))


def _populations(value: str | Sequence[str]) -> tuple[str, ...]:
    return (value,) if isinstance(value, str) else tuple(value)


def provenance_problems(population: str, injection: Mapping[str, Any], mechanism: str | None) -> list[str]:
    """Why a declared P2 or P3 positive does not name its construction (T2 trace, recipe and decoder; T3 knob
    and recipe) or its tier's mechanism; empty for P1 and S, whose recipe is their T1 injection."""
    if population not in POSITIVE_PROVENANCE:
        return []
    tier, keys = POSITIVE_PROVENANCE[population]
    provenance = injection.get("provenance") if isinstance(injection.get("provenance"), Mapping) else {}
    problems = []
    if provenance.get("tier") != tier or not str(mechanism or "").startswith(f"{tier}-"):
        problems.append(f"a {population} positive is a {tier} construction")
    for key in keys:
        value = provenance.get(key)
        if not (is_sha256(value) if key.endswith("SHA256") else isinstance(value, str) and KNOB_ID.fullmatch(value)):
            problems.append(f"a {population} positive names its {key}")
    # Its construction catalog is bound by the plan per tier (see injection_construction_problems).
    if isinstance(injection.get("catalogVersion"), bool) or not isinstance(injection.get("catalogVersion"), int):
        problems.append(f"a {population} positive names its construction catalogVersion")
    return problems


def _natural_units(entry: Mapping[str, Any], cohort: Mapping[str, Any], natural: Mapping[str, Any], *,
                   identities: dict, versions: dict, panel_judges: Sequence[str], referenced: set[str]) -> list[dict]:
    """The natural positives' units (P4 at their label's severity), bound to their own evidence."""
    positives = natural["cohort"]
    shared = sorted({take["speaker"] for take in positives["takes"].values()}
                    & {take["speaker"] for take in cohort["takes"].values()})
    if shared:
        raise CalibrationError(f"the natural positives share {len(shared)} speakers with the cohort; they come from "
                               "another corpus's recordings")
    needs_panel, needs_measurements = registry_lib.needs_panel(entry), registry_lib.needs_measurements(entry)
    bundle, measurements = natural.get("bundle"), natural.get("measurements")
    if raw_output_judges(entry):
        raise CalibrationError(f"{entry['id']} reduces raw outputs, which natural positives do not export")
    if needs_panel and bundle is None:
        raise CalibrationError(f"{entry['id']} reads panel evidence: its natural positives need --natural-bundle")
    if needs_measurements and measurements is None:
        raise CalibrationError(f"{entry['id']} reads measurements.json: its natural positives need "
                               "--natural-measurements")
    if measurements is not None:
        if measurements["takesManifestSHA256"] != positives["fileSHA256"]:
            raise CalibrationError(f"--natural-measurements ({measurements['name']}) scored another takes manifest")
        identities.setdefault(registry_lib.STAGE0_JUDGE, set()).add(measurements["identity"])
    clips = {clip.get("sourceTakeID") or clip.get("clipID"): clip for clip in (measurements or {}).get("clips") or ()
             if clip.get("injection") is None}
    target = natural["target"]
    population = TIER_POPULATIONS["T4"]
    units = []
    for take_id in sorted(natural["severities"]):
        take, severity = positives["takes"][take_id], natural["severities"][take_id]
        where = f"{positives['name']}: {take_id}"
        evidence = bundle.measurements(take_id, audio_sha256=take["wavSHA256"], text_sha256=take["textSHA256"],
                                       language=take["language"]) if bundle is not None and needs_panel else None
        private = bundle.private(take_id) if (registry_lib.needs_private(entry) or referenced) \
            and evidence is not None else None
        _check_private(private, take["textSHA256"], where)
        if referenced and evidence is not None:
            check_reference(private, take.get("referenceSHA256"), where)
        clip = clips.get(take_id) if needs_measurements else None
        if clip is not None and clip.get("wavSHA256") != take["wavSHA256"]:
            raise CalibrationError(f"{where}: measurements.json measured other audio than the manifest's")
        _identities(identities, versions, evidence, panel_judges)
        scored = registry_lib.score_take(entry, take["language"], clip=clip, measurements=evidence, private=private)
        if (needs_panel and evidence is None) or (needs_measurements and clip is None):
            scored = _without_evidence(scored)
        elif needs_panel:
            scored = _run_failed(entry, take["language"], scored, evidence)
        units.append(_unit({**take, "population": population}, scored, injectorID=target["injectorID"],
                           severity=severity, mechanism=registry_lib.NATURAL_MECHANISM,
                           cell=registry_lib.target_cell(entry, target["injectorID"], severity,
                                                         registry_lib.NATURAL_MECHANISM),
                           sham=False, cleanAudio=False))
    return units


def build_scores(entry: Mapping[str, Any], cohort: Mapping[str, Any], *, role: str, split: str | None = None,
                 bundle: Bundle | None = None, measurements: Mapping[str, Any] | None = None,
                 injection_set: Mapping[str, Any] | None = None, positive_bundle: Bundle | None = None,
                 positive_measurements: Mapping[str, Any] | None = None,
                 positives_population: str | Sequence[str] = "P1",
                 raw_outputs: Sequence[Mapping[str, Any]] = (),
                 positive_raw_outputs: Sequence[Mapping[str, Any]] = (),
                 natural: Mapping[str, Any] | None = None) -> dict:
    """Every cohort take's score, then every positive and sham of the detector's injectors.

    Positives are the role set's populations (`positives_population`, see
    `positive_populations`: P1, or a declared P2 or P3 construction with its
    provenance), each of its construction tier; shams are S. `natural`
    (`load_natural_positives`) adds a labelled corpus's own recordings as P4
    positives of the detector's natural target, each at the severity its label
    earns, measured by their own panel and measurements; their speakers must be
    none of the cohort's. A
    `raw-output` detector reads its judge's raw output from the exports
    (`raw_outputs` for the cohort's panel, `positive_raw_outputs` for the
    injection set's), and a seam measure reads each take's long-form seams (a
    positive's own, else its source's). A detector reading a speaker judge's
    reference-relative metrics requires the panel to have embedded the reference
    clip each take declares.
    """
    detector = entry["id"]
    populations = (positives_population,) if isinstance(positives_population, str) else tuple(positives_population)
    needs_panel, needs_measurements = registry_lib.needs_panel(entry), registry_lib.needs_measurements(entry)
    needs_private = registry_lib.needs_private(entry)
    needs_seams, referenced = registry_lib.needs_seams(entry), reference_judges(entry)
    raw_judges = raw_output_judges(entry)
    if (raw_outputs or positive_raw_outputs) and not raw_judges:
        raise CalibrationError(f"{detector} reduces no judge's raw output: pass no raw-output export")
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
    natural_bundle = (natural or {}).get("bundle")
    if needs_panel:
        for source in (bundle, positive_bundle, natural_bundle):
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
    exports = bind_raw_outputs(entry, raw_outputs, source_sha256=cohort["fileSHA256"], bundle=bundle,
                               what="cohort") if raw_judges and needs_panel and bundle is not None else {}
    for take_id in sorted(cohort["takes"]):
        take = cohort["takes"][take_id]
        meta = {**take, "population": cohort["population"]}
        where = f"{cohort['name']}: {take_id}"
        evidence = bundle.measurements(take_id, audio_sha256=take["wavSHA256"], text_sha256=take["textSHA256"],
                                       language=take["language"]) if bundle is not None and needs_panel else None
        private = bundle.private(take_id) if (needs_private or referenced) and evidence is not None else None
        _check_private(private, take["textSHA256"], where)
        if referenced and evidence is not None:
            check_reference(private, take.get("referenceSHA256"), where)
        clip = clean_clips.get(take_id) if needs_measurements else None
        if clip is not None and clip.get("wavSHA256") != take["wavSHA256"]:
            raise CalibrationError(f"{where}: measurements.json measured other audio than the manifest's")
        _identities(identities, versions, evidence, panel_judges)
        raw = raw_for(take_id, take["wavSHA256"], evidence, exports, where) if exports else None
        scored = registry_lib.score_take(entry, meta["language"], clip=clip, measurements=evidence, private=private,
                                         raw=raw, seams=take.get("seams") if needs_seams else None)
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
    # A speaker judge scores audio against a reference clip, so cohort audio is clean only against the reference
    # its take is scored against (an impostor's sham is a cohort take presented against another take).
    cohort_audio = {(take["wavSHA256"], take["referenceSHA256"] if referenced else None)
                    for take in cohort["takes"].values()}
    positive_exports = bind_raw_outputs(entry, positive_raw_outputs, source_sha256=injection_set["fileSHA256"],
                                        bundle=positive_bundle, what="injection set") \
        if positives and raw_judges and needs_panel and positive_bundle is not None else {}
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
        if population not in (*populations, "S"):
            raise CalibrationError(f"{item.get('takeID')}: an injection is {' or '.join(populations)} or S, not "
                                   f"{population!r}")
        tier = str(mechanism or "").split("-", 1)[0]
        if population != "S" and TIER_POPULATIONS.get(tier) != population:
            raise CalibrationError(f"{item.get('takeID')}: a {population} positive is not a {tier} construction "
                                   f"({mechanism})")
        problems = provenance_problems(population, injection, mechanism)
        if problems:
            raise CalibrationError(f"{item.get('takeID')}: " + "; ".join(problems))
        language = item.get("language") or source["language"]
        text = item.get("textSHA256") if is_sha256(item.get("textSHA256")) else None
        where = f"{injection_set['name']}: {item['takeID']}"
        meta = {"takeID": item["takeID"], "family": item.get("family") or source["family"], "language": language,
                "speaker": f"{language}:fleurs-unidentified" if cohort["kind"] in FLEURS_KINDS
                and source["speaker"].endswith(":fleurs-unidentified") else source["speaker"],
                "scriptID": source["scriptID"], "population": population}
        evidence = positive_bundle.measurements(item["takeID"], audio_sha256=wav, text_sha256=text,
                                                language=language) \
            if positive_bundle is not None and needs_panel else None
        private = positive_bundle.private(item["takeID"]) \
            if (needs_private or referenced) and evidence is not None else None
        _check_private(private, text, where)
        if referenced and evidence is not None:
            check_reference(private, reference_digest(item, where), where)
        _identities(identities, versions, evidence, panel_judges)
        raw = raw_for(item["takeID"], wav, evidence, positive_exports, where) if positive_exports else None
        # A construction that moved the seams records its own long-form block; otherwise its source's hold.
        own = _seams(item.get("longForm"), where) if needs_seams else None
        seams = (own if own is not None else source.get("seams")) if needs_seams else None
        clip = injected_clips.get(item["takeID"]) if needs_measurements else None
        if clip is not None:
            recorded = clip.get("injection") or {}
            if recorded.get("injectorID") != injector_id or recorded.get("severity") != injection.get("severity") \
                    or recorded.get("variant") != injection.get("variant"):
                raise CalibrationError(f"{item['takeID']}: the measurements and the injection set disagree")
            if clip.get("wavSHA256") != wav:
                raise CalibrationError(f"{where}: measurements.json measured other audio than the set's")
        severity = injection.get("severity")
        cell = registry_lib.target_cell(entry, injector_id, severity, mechanism) \
            if population in populations else None
        sham = population == "S" and registry_lib.sham_of(entry, injector_id, mechanism)
        # A declared construction (P2, P3) keeps its provenance in its unit: digests and the knob's id only.
        extra = {"provenance": {key: (injection.get("provenance") or {}).get(key) for key in
                                ("tier", *POSITIVE_PROVENANCE[population][1])}} \
            if population in POSITIVE_PROVENANCE else {}
        # Clean cohort audio: a byte copy of a cohort take (a language swap's donor) or an identity construction.
        pair = (wav, reference_digest(item, where) if referenced else None)
        clean = pair in cohort_audio or (injection.get("outputPCMSHA256") is not None
                                         and injection.get("outputPCMSHA256") == injection.get("sourcePCMSHA256"))
        scored = registry_lib.score_take(entry, language, clip=clip, measurements=evidence, private=private, raw=raw,
                                         seams=seams)
        if (needs_panel and evidence is None) or (needs_measurements and clip is None):
            scored = _without_evidence(scored)
        elif needs_panel:
            scored = _run_failed(entry, language, scored, evidence)
        units.append(_unit(meta, scored, injectorID=injector_id, variant=injection.get("variant"),
                           severity=severity, mechanism=mechanism, cell=cell, sham=bool(sham), cleanAudio=clean,
                           **extra))
    if natural is not None:
        units.extend(_natural_units(entry, cohort, natural, identities=identities, versions=versions,
                                    panel_judges=panel_judges, referenced=referenced))
    by_population = Counter(unit["population"] for unit in units)
    abstained = Counter(unit["abstain"] for unit in units if unit["abstain"])
    cohort_block = {"kind": cohort["kind"], "population": cohort["population"],
                    "manifestDigest": cohort["manifestDigest"], "fileSHA256": cohort["fileSHA256"],
                    "runID": cohort.get("runID"), "takes": len(cohort["takes"]),
                    "fleursSplit": split if split in FLEURS_SPLITS else None}
    if split in DECLARED_SPLITS or reserve_index(split) is not None:
        cohort_block["split"] = split
    document = {
        "schema": SCORES_SCHEMA, "kind": SCORES_KIND,
        "privacy": "ids and digests only: no text, transcript or path",
        "detector": detector, "detectorDefinitionSHA256": registry_lib.definition_digest(entry),
        "scoringCodeSHA256": registry_lib.scoring_code_sha256(),
        "class": entry["class"], "direction": entry["direction"], "combination": entry["score"]["combination"],
        "role": role,
        "cohort": cohort_block,
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
    if natural is not None:
        # The natural positives' cohort and label rule, and the evidence they were measured with (A5, A7).
        measured = natural.get("measurements")
        document["sources"].update(
            naturalPositives=natural_source(natural),
            naturalBundle=natural_bundle.identity() if natural_bundle is not None and needs_panel else None,
            naturalMeasurements={key: measured[key] for key in ("fileSHA256", "clipsSHA256", "identity",
                                                                "takesManifestSHA256", "startedAt")}
            if measured is not None and needs_measurements else None)
        document["counts"]["expected"]["naturalPositives"] = len(natural["severities"])
    if raw_judges:
        # The raw-output exports read, each bound to its manifest and bundle (sorted by judge).
        for key, bound in (("rawOutputs", exports), ("positiveRawOutputs", positive_exports)):
            document["sources"][key] = [{name: export[name] for name in ("judge", "fileSHA256", "takesSHA256",
                                                                          "bundleDigest")}
                                        for _, export in sorted(bound.items())]
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
    """Every plan file's cohorts by role: {calibration|confirmation|bound|spent: {manifest digest: [detectors]}},
    `bound` being a fail plan's N3 cohort and `spent` a cohort already scored as confirmation evidence: the
    confirmation or N3 cohort of a plan with a ledger entry, or a record's informational N3 cohort. `spentSources`
    names, by corpus, the fixed recordings such a plan confirmed on: a FLEURS or speaker-labelled corpus (its
    confirmation cohort's source) and a labelled corpus's natural positives, so a new resynthesis of them is spent
    too."""
    found: dict[str, dict[str, list[str]]] = {"calibration": {}, "confirmation": {}, "bound": {}, "spent": {},
                                              "spentSources": {}}
    if repository.records.is_dir():
        for path in sorted(repository.records.glob("*/*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            digest = ((record.get("informational") or {}).get("manifestDigest")
                      if isinstance(record, Mapping) and isinstance(record.get("informational"), Mapping) else None)
            if is_sha256(digest):
                found["spent"].setdefault(digest, []).append(str(record.get("detector")))
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
        if plan.binding("n3CohortDigest"):
            found["bound"].setdefault(plan.binding("n3CohortDigest"), []).append(plan.detector)
        # A plan's natural positives are confirmation evidence like its confirmation cohort.
        if plan.binding("naturalPositivesDigest"):
            found["confirmation"].setdefault(plan.binding("naturalPositivesDigest"), []).append(plan.detector)
        if repository.ledger.outcome(plan.digest()) is not None:
            for digest in (plan.cohorts.confirmation.manifest_digest, plan.binding("n3CohortDigest"),
                           plan.binding("naturalPositivesDigest")):
                if digest:
                    found["spent"].setdefault(digest, []).append(plan.detector)
            source = plan.cohorts.confirmation.source
            labelled = plan.cohorts.speaker_unit == SPEAKER_LABELED_RULE.speaker_unit
            for corpus in (source if source.startswith(FLEURS_CORPUS_PREFIX) or labelled else None,
                           plan.binding("naturalPositivesSource")):
                if corpus:
                    found["spentSources"].setdefault(corpus, []).append(plan.detector)
    return found


def command_scores(args: argparse.Namespace, repository: Repository) -> int:
    registry, entry = repository.entry(args.detector)
    roles = registry_lib.role_set(registry, entry)
    rule = cohort_rule(entry)
    cohort = load_cohort(args.cohort)
    split = resolve_cohort(cohort, args.n1_manifest)
    plan = repository.store.load(entry["id"], args.operating_point)
    digest = cohort["manifestDigest"]
    confirmation_split = expected_split(rule, roles, "confirmNegatives", args.operating_point)
    if args.role == "bound":
        if args.operating_point == "warn":
            raise CalibrationError("the N3 bound belongs to a fail plan: pass --operating-point fail (or "
                                   "evidenceLaneFail)")
        if plan is None or plan.binding("n3CohortDigest") != digest:
            raise CalibrationError("an N3 bound cohort is scored only under the fail plan that names it (A5): run "
                                   f"plan for {entry['id']} at a fail operating point first and commit it")
        repository.store.require(plan)
        if cohort["population"] != "N3":
            raise CalibrationError(f"the N3 bound is scored on N3 takes, not {cohort['population']}")
        if args.injection_set or args.positive_bundle or args.positive_measurements:
            raise CalibrationError("the N3 bound has no positives: pass no injection set")
    elif args.role == "confirmation":
        if plan is None or plan.cohorts is None or plan.cohorts.confirmation.manifest_digest != digest:
            raise CalibrationError("a confirmation cohort is scored only under a plan that names it (A5): "
                                   f"run plan for {entry['id']} first and commit it")
        repository.store.require(plan)
        if confirmation_split is not None and split != confirmation_split:
            raise CalibrationError(f"the confirmation cohort is FLEURS {split}, not {confirmation_split}"
                                   if rule.fleurs else
                                   f"the confirmation cohort is {split_name(split)}, not the {confirmation_split} "
                                   "split")
    else:
        declared = declared_cohorts(repository)
        named = declared["confirmation"].get(digest)
        if named:
            raise CalibrationError(f"the plan of {', '.join(sorted(named))} names this cohort as its confirmation "
                                   "cohort; it is scored only under --role confirmation (A5)")
        if declared["bound"].get(digest):
            raise CalibrationError(f"the fail plan of {', '.join(sorted(declared['bound'][digest]))} bounds its N3 "
                                   "flag rate on this cohort; it is scored only under --role bound (A5)")
        if confirmation_split is not None and split == confirmation_split and cohort["kind"] in rule.kinds:
            raise CalibrationError(f"{split_name(split)} is the confirmation corpus: it is scored only under "
                                   "--role confirmation, never for calibration or information (A5)")
        if args.role in ("calibration", "informational") and is_confirmation_split(split):
            # Another role set's confirmation corpus (the N3 confirmation split for a FLEURS detector, FLEURS
            # test for an N3 one, a held-back reserve cohort) stays untouched too, planned or not.
            raise CalibrationError(f"{split_name(split)} is a confirmation split: it is scored only under --role "
                                   "confirmation or bound, never for calibration or information (A5)")
    if args.role == "calibration":
        if plan is not None and plan.cohorts and plan.cohorts.calibration.manifest_digest != digest:
            raise CalibrationError(f"{entry['id']}'s plan pins another calibration cohort")
        if cohort["population"] != roles["fit"]["population"]:
            raise CalibrationError(f"{entry['id']} fits on {roles['fit']['population']}, not {cohort['population']}")
        fit_split = expected_split(rule, roles, "fit")
        if fit_split is not None and split != fit_split:
            raise CalibrationError(f"{entry['id']} fits on FLEURS {fit_split}, not {split}" if rule.fleurs else
                                   f"{entry['id']} fits on the {fit_split} split, not {split_name(split)}")
    if args.role in ("calibration", "confirmation"):
        problems = cohort_rule_problems(cohort, rule, roles)
        if problems:
            raise CalibrationError("; ".join(problems))
    output = repository.check_output(args.output)
    natural = None
    if args.natural_positives is not None:
        # Natural positives, like constructed ones, are confirmation evidence only (A5).
        if args.role != "confirmation":
            raise CalibrationError("natural positives are confirmation evidence: score them under --role confirmation")
        natural = load_natural_positives(
            entry, roles, args.natural_positives, args.natural_n1_manifest,
            bundle=Bundle(args.natural_bundle) if args.natural_bundle else None,
            measurements=load_measurements(args.natural_measurements) if args.natural_measurements else None)
        problems = natural_label_problems(repository.policy(), entry, natural)
        if problems:
            raise CalibrationError("the natural positives' labels cannot qualify positives: " + "; ".join(problems))
    elif args.natural_n1_manifest or args.natural_bundle or args.natural_measurements:
        raise CalibrationError("--natural-* evidence belongs to --natural-positives")
    elif args.role == "confirmation" and registry_lib.natural_targets(entry):
        raise CalibrationError(f"{entry['id']} measures detection on natural labelled positives: pass "
                               "--natural-positives (the labelled corpus's cohort its plan names)")
    document = build_scores(
        entry, cohort, role=args.role, split=split,
        bundle=Bundle(args.bundle) if args.bundle else None,
        measurements=load_measurements(args.measurements) if args.measurements else None,
        injection_set=load_injection_set(args.injection_set) if args.injection_set else None,
        positive_bundle=Bundle(args.positive_bundle) if args.positive_bundle else None,
        positive_measurements=load_measurements(args.positive_measurements) if args.positive_measurements else None,
        positives_population=positive_populations(roles, entry),
        raw_outputs=[load_raw_outputs(path) for path in args.raw_outputs or ()],
        positive_raw_outputs=[load_raw_outputs(path) for path in args.positive_raw_outputs or ()],
        natural=natural,
    )
    if args.role == "confirmation":
        problems = confirmation_evidence_problems(repository, plan, document)
        if problems:
            raise CalibrationError("the confirmation evidence does not meet its plan: " + "; ".join(problems))
    if args.role == "bound":
        problems = freshness_problems(repository, plan, document, bound=True)
        if problems:
            raise CalibrationError("the N3 bound evidence does not meet its plan: " + "; ".join(problems))
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


def fail_like(point: Mapping[str, Any]) -> bool:
    """A fail operating point (`fail`, `evidenceLaneFail`): it names the population its FAR is confirmed on."""
    return "farPopulation" in point


def calibration_floor_of(point: Mapping[str, Any], by: str | None) -> int:
    """Scored calibration families each stratum needs. Warn states it (`minimumUnits.calibration`); a fail
    point states none, so the calibration cohort is held to the confirmation's negative floor for the same
    stratum (`n2NegativesPerLanguage` per language, `n2Negatives` pooled). The split-conformal rule needs
    ceil(1 / alpha) - 1 families on top (a smaller alpha needs more: 199 at 0.005), which `plan` and
    `derive` apply as well."""
    units = point["minimumUnits"]
    if "calibration" in units:
        return int(units["calibration"])
    return int(units["n2NegativesPerLanguage"] if by == "language" else units["n2Negatives"])


def fail_plan_problems(entry: Mapping[str, Any], roles: Mapping[str, Any], point: Mapping[str, Any]) -> list[str]:
    """Why a detector's definition cannot qualify at a fail point, whatever its confirmation shows: a
    combination the point refuses (a two-family mean qualifies at warn only), FAR confirmed on the point's
    population (A2), a per-language bound over the point's languages, and detection on severe and moderate cells
    of at least `mechanismsMin` construction mechanisms (A3)."""
    problems = []
    combination = entry["score"]["combination"]
    if combination in (point.get("refusedCombinations") or ()):
        problems.append(f"its {combination} combination qualifies at warn only; a fail level keeps strict two-family "
                        "consensus (policy decision mean-consensus-warn-only)")
    population = roles["confirmNegatives"]["population"]
    if population != point["farPopulation"]:
        problems.append(f"the fail FAR is confirmed on {point['farPopulation']} (A2); role set {entry['populations']} "
                        f"confirms on {population}")
    languages = len(entry["scope"]["languages"])
    if languages < point["minimumUnits"]["languages"]:
        problems.append(f"its scope holds {languages} languages; a fail bound covers {point['minimumUnits']['languages']}")
    complete = sorted(mechanism for mechanism, cells in registry_lib.declared_cells(entry).items()
                      if FAIL_SEVERITIES <= {cell.rsplit("/", 1)[-1] for cell in cells})
    required = int(point.get("mechanismsMin", 1))
    if len(complete) < required:
        problems.append(f"{len(complete)} construction mechanisms declare severe and moderate cells "
                        f"({', '.join(complete) or 'none'}); fail measures detection on {required} (A3)")
    return problems


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
               alpha: float, operating_point: str, injection: Mapping[str, Any] | None,
               confirmation_split: str | None = None, calibration_split: str | None = None,
               n3: Mapping[str, Any] | None = None,
               natural: Mapping[str, Any] | None = None) -> thresholds.PreRegistration:
    policy = repository.policy()
    if operating_point not in SUPPORTED_OPERATING_POINTS:
        raise CalibrationError(f"this driver pre-registers {SUPPORTED_OPERATING_POINTS} only")
    point = policy["operatingPoints"][operating_point]
    if not 0.0 < alpha < point["farPooledMax"]:
        raise CalibrationError(f"alpha must lie below the {operating_point} FAR bound {point['farPooledMax']} "
                               "to leave margin for the confirmation")
    roles = registry_lib.role_set(registry, entry)
    rule = cohort_rule(entry)
    if fail_like(point):
        problems = fail_plan_problems(entry, roles, point)
        if problems:
            raise CalibrationError(f"{entry['id']} cannot qualify at {operating_point}: " + "; ".join(problems))
        if n3 is None:
            raise CalibrationError(f"a {operating_point} plan names the N3 cohort its flag rate is bounded on "
                                   "(--n3-cohort, A2)")
        if n3["kind"] != N3_KIND:
            raise CalibrationError(f"the N3 bound cohort is an {N3_KIND} manifest, not {n3['kind']}")
        if n3["manifestDigest"] in (calibration["manifestDigest"], confirmation["manifestDigest"]):
            raise CalibrationError("the N3 bound cohort is neither the calibration nor the confirmation cohort")
    elif n3 is not None:
        raise CalibrationError(f"the {operating_point} point bounds no N3 flag rate: pass no --n3-cohort")
    pending = pending_corpora(roles)
    if pending:
        raise CalibrationError(f"role set {entry['populations']} names no corpus yet for {', '.join(pending)}: the "
                               "maintainer's data decision names it in config/audio-qc-detectors.json roleSets first")
    for cohort, role in ((calibration, "fit"), (confirmation, "confirmNegatives")):
        if cohort["kind"] not in rule.kinds:
            raise CalibrationError("a declared split pre-registers FLEURS-derived cohorts (N1 or N2) only"
                                   if rule is FLEURS_RULE else "; ".join(cohort_rule_problems(cohort, rule, roles)))
        if cohort["population"] != roles[role]["population"]:
            raise CalibrationError(f"the {role} role is {roles[role]['population']}, not {cohort['population']}")
        problems = cohort_rule_problems(cohort, rule, roles)
        if problems:
            raise CalibrationError("; ".join(problems))
    expected = expected_split(rule, roles, "confirmNegatives", operating_point)
    if expected is not None and confirmation_split != expected:
        raise CalibrationError(f"the confirmation cohort is FLEURS {confirmation_split}; the role set confirms on "
                               f"FLEURS {expected}" if rule.fleurs else
                               f"the confirmation cohort is {split_name(confirmation_split)}; the role set confirms "
                               f"on the {expected} split")
    if rule is SPEAKER_LABELED_RULE:
        # Speakers are digests of (corpus, label): both cohorts name one corpus, or disjointness is vacuous.
        corpora = {calibration.get("corpus"), confirmation.get("corpus")}
        if len(corpora) != 1 or None in corpora:
            raise CalibrationError("the two cohorts of a speaker-labelled split name one corpus (their N1 manifests' "
                                   "corpus), so their speakers compare")
        (corpus,) = corpora
        for role in ("fit", "confirmNegatives"):
            if roles[role].get("corpus") != f"{corpus}-{roles[role]['cohort']}":
                raise CalibrationError(f"role set {entry['populations']} names corpus {roles[role].get('corpus')} "
                                       f"for {role}, not {corpus}-{roles[role]['cohort']}")
    fit_split = expected_split(rule, roles, "fit")
    if calibration_split is not None and fit_split is not None and calibration_split != fit_split:
        raise CalibrationError(f"the calibration cohort is {split_name(calibration_split)}; the role set fits on "
                               f"{split_name(fit_split)}")
    if calibration_scores.get("detector") != entry["id"] or calibration_scores.get("role") != "calibration":
        raise CalibrationError("the calibration scores belong to another detector or role")
    if calibration_scores.get("detectorDefinitionSHA256") != registry_lib.definition_digest(entry):
        raise CalibrationError("the calibration scores were computed under another definition of the detector")
    if calibration_scores["cohort"]["manifestDigest"] != calibration["manifestDigest"] \
            or calibration_scores["cohort"]["fileSHA256"] != calibration["fileSHA256"]:
        raise CalibrationError("the calibration scores are not of the calibration cohort")
    if fit_split is not None and scores_split(calibration_scores) != fit_split:
        raise CalibrationError(f"the calibration scores are not of {split_name(fit_split)}")
    scoring_code = registry_lib.scoring_code_sha256()
    if calibration_scores.get("scoringCodeSHA256") != scoring_code:
        raise CalibrationError("the calibration scores were computed by other scoring code; score them again (A7)")
    problems = current_evidence_problems(entry, calibration_scores["evidenceIdentity"])
    problems += calibration_problems(entry, calibration_scores, roles["fit"]["population"],
                                     max(calibration_floor_of(point, registry_lib.strata_by(entry)),
                                         math.ceil(1.0 / alpha) - 1))
    if problems:
        raise CalibrationError("the calibration scores cannot fit a threshold: " + "; ".join(problems))
    declared = declared_cohorts(repository)
    if declared["confirmation"].get(calibration["manifestDigest"]):
        raise CalibrationError(f"the plan of {', '.join(declared['confirmation'][calibration['manifestDigest']])} "
                               "names the calibration cohort as its confirmation cohort (A5)")
    if declared["calibration"].get(confirmation["manifestDigest"]):
        raise CalibrationError(f"the plan of {', '.join(declared['calibration'][confirmation['manifestDigest']])} "
                               "fits on the confirmation cohort (A5)")
    if declared["bound"].get(calibration["manifestDigest"]):
        raise CalibrationError(f"the fail plan of {', '.join(declared['bound'][calibration['manifestDigest']])} "
                               "bounds its N3 flag rate on the calibration cohort (A5)")
    if n3 is not None and declared["calibration"].get(n3["manifestDigest"]):
        raise CalibrationError(f"the plan of {', '.join(declared['calibration'][n3['manifestDigest']])} fits on "
                               "the N3 bound cohort (A5)")
    natural_cohort = natural["cohort"] if natural is not None else None
    if natural_cohort is not None:
        problems = natural_label_problems(policy, entry, natural)
        if problems:
            raise CalibrationError("the natural positives' labels cannot qualify positives: " + "; ".join(problems))
        # Natural positives come from another corpus: no speaker, family or script of either cohort.
        for cohort, what in ((calibration, "calibration"), (confirmation, "confirmation")):
            for key in ("speaker", "family", "scriptID"):
                if {take[key] for take in natural_cohort["takes"].values()} & \
                        {take[key] for take in cohort["takes"].values()}:
                    raise CalibrationError(f"the natural positives share a {key} with the {what} cohort")
    confirmation_source = role_corpus(roles, "confirmNegatives", operating_point)
    # The labelled corpus split the natural positives are (`<corpus>-confirmation`, as the role set names it).
    natural_source = f"{natural['cohort'].get('corpus')}-{natural['split']}" if natural is not None else None
    # A FLEURS or speaker-labelled corpus names fixed recordings: a new resynthesis of a spent split is spent too.
    for corpus, what in ((confirmation_source if rule.fleurs or rule is SPEAKER_LABELED_RULE else None,
                          "confirmation corpus"),
                         (natural_source, "natural positives' corpus")):
        spent = declared["spentSources"].get(corpus) if corpus else None
        if spent:
            raise CalibrationError(f"the {what} {corpus} was already scored as confirmation evidence (for "
                                   f"{', '.join(sorted(set(spent)))}: a confirmed plan); A5 needs recordings no "
                                   "confirmation has scored, whichever resynthesis of them the plan names")
    for cohort, what in ((confirmation, "confirmation cohort"), (n3, "N3 bound cohort"),
                         (natural_cohort, "natural positives cohort")):
        spent = declared["spent"].get(cohort["manifestDigest"]) if cohort is not None else None
        if spent:
            raise CalibrationError(f"the {what} was already scored as confirmation evidence (for "
                                   f"{', '.join(sorted(set(spent)))}: a confirmed plan or a record's informational "
                                   "N3); A5 needs a cohort no confirmation has scored")
        artifacts = scoring_artifacts(cohort["directory"]) if cohort is not None else []
        if artifacts:
            raise CalibrationError(f"the {what} already holds scores, a panel bundle or measurements "
                                   f"({', '.join(artifacts[:3])}); A5 needs the plan committed before any of them")
    limitations = tuple((code, registry["limitations"][code]) for code in entry["limitations"])
    split = thresholds.CohortSplit(
        calibration=thresholds.CohortReference(calibration["kind"], calibration["manifestDigest"],
                                               roles["fit"].get("corpus", "")),
        confirmation=thresholds.CohortReference(confirmation["kind"], confirmation["manifestDigest"],
                                                confirmation_source),
        disjoint_by=rule.disjoint_by, speaker_unit=rule.speaker_unit, speaker_claim=rule.speaker_claim,
        limitations=limitations)
    bindings = (
        ("calibrationScoresSHA256", calibration_scores["scoresSHA256"]),
        ("detectorDefinitionSHA256", registry_lib.definition_digest(entry)),
        ("operatingPoint", operating_point),
        ("policySHA256", file_sha256(repository.policy_path)),
        ("scoringCodeSHA256", scoring_code),
        ("evidenceIdentitySHA256", json_digest(calibration_scores["evidenceIdentity"])),
        *((binding, construction_value(key, injection[key])) for key, binding in INJECTION_BINDINGS.items()
          if injection is not None),
        *(((SCHEDULE_BINDING, str(injection["schedule"])),) if (injection or {}).get("schedule") else ()),
        *((f"{TIER_CATALOG_BINDING}{tier}", str(version))
          for tier, version in sorted(((injection or {}).get("tierCatalogVersions") or {}).items())),
        # A fail point's N3 flag-rate bound is confirmation evidence too: its cohort is pre-registered (A2, A5).
        *((("n3CohortDigest", n3["manifestDigest"]),) if n3 is not None else ()),
        # Natural positives: the labelled cohort, its corpus and the rule that selects them are pre-registered (A5).
        *((("naturalPositivesDigest", natural["cohort"]["manifestDigest"]),
           ("naturalLabelsSHA256", natural["labelsSHA256"]),
           ("naturalPositivesSource", natural_source)) if natural is not None else ()),
    )
    strata = () if entry["strata"] is None else ((entry["strata"]["by"], entry["strata"]["reason"]),)
    plan = thresholds.PreRegistration(
        detector=entry["id"], rule="split-conformal", alpha=alpha, direction=entry["direction"],
        confidence=policy["statistics"]["confidence"], population=roles["fit"]["population"],
        strata=strata, cohorts=split, bindings=bindings)
    thresholds.check_cohort_disjointness(plan, _triples(calibration), _triples(confirmation))
    return plan


def tier_catalog_version(value: str) -> tuple[str, int]:
    tier, _, version = value.partition("=")
    if tier not in ("T2", "T3") or not version.isdigit():
        raise argparse.ArgumentTypeError("TIER=N, with TIER T2 or T3")
    return tier, int(version)


def injection_classes(value: str) -> list[str]:
    classes = sorted({item.strip().upper() for item in value.split(",") if item.strip()})
    if not classes or not set(classes) <= set(registry_lib.CLASSES):
        raise argparse.ArgumentTypeError("classes are letters A-J, comma-separated")
    return classes


def command_plan(args: argparse.Namespace, repository: Repository) -> int:
    from lib.qc_qualification import injectors  # deferred: NumPy-backed, only its catalog version is read

    registry, entry = repository.entry(args.detector)
    rule = cohort_rule(entry)
    roles = registry_lib.role_set(registry, entry)
    positives = roles["positives"]["population"]
    flags = {"--injection-catalog-seed": args.injection_catalog_seed, "--injection-sample-seed":
             args.injection_sample_seed, "--injection-sample-per-cell": args.injection_sample_per_cell,
             "--injection-classes": args.injection_classes}
    constructed = registry_lib.constructed_targets(entry)
    if not constructed:
        # Every positive is a natural recording: no injection set is built, so none is declared.
        given = [flag for flag, value in flags.items() if value is not None]
        if given or args.injection_catalog_version is not None or args.tier_catalog_version:
            raise CalibrationError(f"{entry['id']} has natural positives only: pass no injection flags "
                                   f"({', '.join(given) or '--injection-catalog-version'})")
        catalog_version = None
    elif any(value is None for value in flags.values()):
        raise CalibrationError("the plan declares how the confirmation injection set will be built: pass "
                               + ", ".join(flag for flag, value in flags.items() if value is None))
    # P1 positives come from this repository's T1 catalog; a declared P2 or P3 construction names its own.
    elif positives == "P1":
        catalog_version = injectors.CATALOG_VERSION
        if args.injection_catalog_version not in (None, catalog_version):
            raise CalibrationError(f"P1 positives are built with injector catalog {catalog_version}")
    elif args.injection_catalog_version is None:
        raise CalibrationError(f"{positives} positives are a declared construction: pass --injection-catalog-version "
                               "(the version of the catalog the confirmation set will be built with)")
    else:
        catalog_version = args.injection_catalog_version
    confirmation = load_cohort(args.confirmation_cohort)
    calibration = load_cohort(args.calibration_cohort)
    calibration_split = None
    if args.calibration_n1_manifest is not None or calibration["kind"] != N2_KIND:
        calibration_split = resolve_cohort(calibration, args.calibration_n1_manifest)
    elif not rule.fleurs:
        raise CalibrationError(f"{calibration['name']} is an N2 cohort: pass --calibration-n1-manifest (the N1 "
                               "manifest it pins) so its split and speakers are known")
    # A second tier's positives (a fail point's T2 beside T1) are built from that tier's catalog, bound too.
    # (Natural P4 positives are no construction: they have no catalog.)
    tiers = [POPULATION_TIERS[population] for population in positive_populations(roles, entry)[1:]
             if population != TIER_POPULATIONS["T4"]]
    declared_tiers = dict(args.tier_catalog_version or ())
    if sorted(declared_tiers) != sorted(tiers):
        raise CalibrationError(f"{entry['id']} reads {', '.join(tiers) or 'no'} second-tier constructions: pass "
                               "--tier-catalog-version TIER=N for each, and only those")
    injection = {"catalogVersion": catalog_version, "catalogSeed": args.injection_catalog_seed,
                 "sampleSeed": args.injection_sample_seed, "samplePerCell": args.injection_sample_per_cell,
                 "classes": args.injection_classes, "tierCatalogVersions": declared_tiers} if constructed else None
    if injection is not None and positives == "P1":
        # This repository's calibration set builds P1 positives, with the schedule of the code planning them.
        import audio_qc_calibration_set  # deferred: NumPy-backed, only its schedule version is read

        injection["schedule"] = audio_qc_calibration_set.SCHEDULE_VERSION
    natural = None
    if registry_lib.natural_targets(entry):
        if args.natural_positives is None:
            raise CalibrationError(f"{entry['id']} measures detection on natural labelled positives: pass "
                                   "--natural-positives (and its --natural-n1-manifest) so the plan names them (A5)")
        natural = load_natural_positives(entry, roles, args.natural_positives, args.natural_n1_manifest)
    elif args.natural_positives is not None or args.natural_n1_manifest is not None:
        raise CalibrationError(f"{entry['id']} declares no natural labelled positives")
    n3 = None
    if args.n3_cohort is not None:
        n3 = load_cohort(args.n3_cohort)
        if n3["kind"] != N3_KIND:
            raise CalibrationError(f"the N3 bound cohort is an {N3_KIND} manifest, not {n3['kind']}")
        resolve_cohort(n3, None)
    plan = build_plan(repository, registry, entry, calibration=calibration,
                      confirmation=confirmation,
                      confirmation_split=resolve_cohort(confirmation, args.confirmation_n1_manifest),
                      calibration_split=calibration_split,
                      calibration_scores=load_scores(args.calibration_scores), alpha=args.alpha,
                      operating_point=args.operating_point, injection=injection, n3=n3, natural=natural)
    if repository.ledger.outcome(plan.digest()) is not None:
        raise CalibrationError("this plan was already confirmed")
    existing = repository.store.load(entry["id"], args.operating_point)
    if existing is not None and existing != plan:
        raise CalibrationError(f"{entry['id']} already has another {args.operating_point} plan; a changed plan "
                               "needs a new detector version")
    path = repository.store.commit(plan)
    print(json.dumps({"plan": str(path.relative_to(repository.root)), "digest": plan.digest(),
                      "next": "review and commit the plan file; derive and confirm refuse it until then"}, indent=2))
    return 0


# --------------------------------------------------------------------------- #
# derive
# --------------------------------------------------------------------------- #

def committed_plan(repository: Repository, entry: Mapping[str, Any],
                   operating_point: str = "warn") -> thresholds.PreRegistration:
    plan = repository.store.load(entry["id"], operating_point)
    if plan is None:
        raise CalibrationError(f"{entry['id']} has no {operating_point} plan in "
                               f"{thresholds.PREREGISTRATION_DIRECTORY.name}/ (A5)")
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
    return calibration_floor_of(repository.policy()["operatingPoints"][plan.binding("operatingPoint")],
                                plan_strata(plan))


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
    plan = committed_plan(repository, entry, args.operating_point)
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


def confirmation_inputs(entry: Mapping[str, Any], units: Sequence[Mapping[str, Any]], population: str,
                        positives_population: str | Sequence[str] = "P1") -> dict:
    negatives = _in_scope(units, population)
    positives: dict[str, dict[str, list[dict]]] = {}
    shams: dict[str, list[dict]] = {}
    for unit in units:
        if not unit["inScope"]:
            continue
        if unit["population"] in _populations(positives_population) and unit["cell"]:
            positives.setdefault(unit["mechanism"], {}).setdefault(unit["cell"], []).append(dict(unit))
        elif unit["population"] == "S" and unit.get("sham"):
            shams.setdefault(unit["injectorID"], []).append(dict(unit))
    return {"negatives": negatives, "positives": positives, "shams": shams}


def _scored_families(units: Iterable[Mapping[str, Any]]) -> set[str]:
    return {unit["family"] for unit in units if unit["score"] is not None}


def evidence_problems(scores: Mapping[str, Any], what: str = "") -> list[str]:
    """Every expected unit of a scores document is present, has its evidence and no failed judge row."""
    problems: list[str] = []
    counts = scores["counts"]
    if counts.get("skipped"):
        problems.append(f"{what}units were skipped ({counts['skipped']}); every expected unit is scored")
    expected = counts.get("expected") or {}
    natural = registry_lib.NATURAL_MECHANISM
    cohort_units = sum(1 for unit in scores["units"] if unit["injectorID"] is None)
    injected_units = sum(1 for unit in scores["units"] if unit["injectorID"] is not None
                         and unit.get("mechanism") != natural)
    natural_units = sum(1 for unit in scores["units"] if unit.get("mechanism") == natural)
    if (cohort_units, injected_units) != (expected.get("cohortTakes"), expected.get("injections")):
        problems.append(f"{what}{cohort_units} cohort and {injected_units} injected units, where the manifests "
                        f"list {expected.get('cohortTakes')} and {expected.get('injections')}")
    if natural_units != expected.get("naturalPositives", 0):
        problems.append(f"{what}{natural_units} natural positive units, where their label rule selects "
                        f"{expected.get('naturalPositives', 0)}")
    gaps = evidence_gaps(scores["units"])
    if gaps:
        problems.append(f"{what}{sum(gaps.values())} in-scope units have no evidence "
                        f"({dict(sorted(gaps.items()))}); every expected unit needs its evidence")
    failed = sum(1 for unit in scores["units"] if unit["inScope"] and unit["abstain"] in RUN_FAILURES)
    if failed:
        problems.append(f"{what}{failed} in-scope units have a failed judge row (unavailable: an admission or row "
                        "timeout, a crash or an envelope breach); run that panel again on a new cache root")
    return problems


def fail_minimum_problems(entry: Mapping[str, Any], inputs: Mapping[str, Any], point: Mapping[str, Any],
                          n3_units: Sequence[Mapping[str, Any]]) -> list[str]:
    """The fail point's minimum units, counted on scored families: N2 negatives pooled and per language over
    its language count, positives per declared severe and moderate cell, a sham cell per injector, and N3
    negatives per language of the N2 negatives."""
    floors = point["minimumUnits"]
    problems = []
    negatives = [unit for unit in inputs["negatives"] if unit["score"] is not None]
    population = next((unit["population"] for unit in inputs["negatives"]), point["farPopulation"])
    families = _scored_families(negatives)
    if len(families) < floors["n2Negatives"]:
        problems.append(f"{len(families)} scored {population} negative families, the fail floor is "
                        f"{floors['n2Negatives']}")
    languages = sorted({unit["language"] for unit in negatives})
    if len(languages) < floors["languages"]:
        problems.append(f"{len(languages)} languages among the scored negatives, the fail floor is "
                        f"{floors['languages']}")
    for language in languages:
        count = len(_scored_families(unit for unit in negatives if unit["language"] == language))
        if count < floors["n2NegativesPerLanguage"]:
            problems.append(f"{language}: {count} scored {population} negative families, the fail floor is "
                            f"{floors['n2NegativesPerLanguage']}")
    cell_floor = floors["positivesPerCell"]
    for mechanism, cells in sorted(registry_lib.declared_cells(entry).items()):
        for cell in sorted(cells):
            if cell.rsplit("/", 1)[-1] not in FAIL_SEVERITIES:
                continue
            count = len(_scored_families(inputs["positives"].get(mechanism, {}).get(cell, [])))
            if count < cell_floor:
                problems.append(f"{mechanism} {cell}: {count} scored positive families, the fail floor is {cell_floor}")
    for injector in sham_cells(entry):
        count = len(_scored_families(inputs["shams"].get(injector, [])))
        if count < cell_floor:
            problems.append(f"{injector}: {count} scored sham families, the fail floor is {cell_floor} (A4)")
    n3_floor = floors["n3NegativesPerLanguage"]
    for language in languages:
        count = len(_scored_families(unit for unit in n3_units if unit["language"] == language))
        if count < n3_floor:
            problems.append(f"{language}: {count} scored N3 families, the fail floor is {n3_floor} (A2)")
    return problems


def preconditions(entry: Mapping[str, Any], inputs: Mapping[str, Any], point: Mapping[str, Any],
                  scores: Mapping[str, Any], n3: Mapping[str, Any] | None = None) -> list[str]:
    """What must hold before the one confirmation starts, counted on scored units (never on alarms).

    Every expected unit is present and has its evidence, and the operating
    point's minimums hold on the units that did not abstain: a detector that
    (nearly) always abstains is refused here, never recorded as refused. A fail
    point also needs its N3 bound scores (`n3`) complete.
    """
    problems = evidence_problems(scores)
    floors = point["minimumUnits"]
    if fail_like(point):
        problems += evidence_problems(n3, "N3 bound: ") if n3 is not None else ["no N3 bound scores"]
        return problems + fail_minimum_problems(entry, inputs, point, _in_scope((n3 or {}).get("units") or (), "N3"))
    negatives = [unit for unit in inputs["negatives"] if unit["score"] is not None]
    families = _scored_families(negatives)
    population = next((unit["population"] for unit in inputs["negatives"]), "N2")
    if len(families) < floors["good"]:
        problems.append(f"{len(families)} scored {population} negative families, the floor is {floors['good']}")
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
    schedule = str(recorded.get("schedule", UNSCHEDULED))
    if schedule != (plan.binding(SCHEDULE_BINDING) or str(UNSCHEDULED)):
        problems.append(f"the injection set drew schedule {schedule}, the plan declares "
                        f"{plan.binding(SCHEDULE_BINDING) or UNSCHEDULED} (A5)")
    planned = plan.binding(INJECTION_BINDINGS["catalogVersion"])
    tier_versions = recorded.get("tierCatalogVersions")
    extra = {key.removeprefix(TIER_CATALOG_BINDING): value for key, value in plan.bindings
             if key.startswith(TIER_CATALOG_BINDING) and key != TIER_CATALOG_BINDING}
    if tier_versions is None:
        entry_versions = [str(value) for value in recorded.get("entryCatalogVersions") or ()]
        if planned is not None and any(value != planned for value in entry_versions):
            problems.append(f"the injection set's entries carry catalog versions {entry_versions}, the plan declares "
                            f"{planned} (A5)")
        if extra:
            problems.append(f"the plan declares {', '.join(sorted(extra))} constructions the injection set lacks")
        return problems
    for tier, versions in sorted(tier_versions.items()):
        expected = extra.get(tier, planned)
        if [str(value) for value in versions] != [expected]:
            problems.append(f"the injection set's {tier} entries carry catalog versions {versions}, the plan "
                            f"declares {expected} (A5)")
    missing = sorted(set(extra) - set(tier_versions))
    if missing:
        problems.append(f"the plan declares {', '.join(missing)} constructions the injection set lacks")
    return problems


def natural_positive_problems(plan: thresholds.PreRegistration, scores: Mapping[str, Any]) -> list[str]:
    """The natural positives are the labelled cohort and label rule the plan names (A5)."""
    source = (scores.get("sources") or {}).get("naturalPositives")
    planned = plan.binding("naturalPositivesDigest")
    if planned is None:
        return ["the plan names no natural positives; the scores carry some"] if source else []
    if not source:
        return ["the confirmation scores carry no natural positives; the plan names a labelled cohort"]
    problems = []
    if source.get("manifestDigest") != planned:
        problems.append("the natural positives are another cohort than the plan names (A5)")
    if source.get("labelsSHA256") != plan.binding("naturalLabelsSHA256"):
        problems.append("the natural positives were labelled by another rule than the plan's (A5)")
    return problems


def plans_injection(plan: thresholds.PreRegistration) -> bool:
    return any(plan.binding(binding) is not None for binding in INJECTION_BINDINGS.values())


def confirmation_evidence_problems(repository: Repository, plan: thresholds.PreRegistration,
                                   scores: Mapping[str, Any]) -> list[str]:
    # A detector whose positives are all natural recordings plans no injection set.
    injected = injection_construction_problems(plan, scores) \
        if plans_injection(plan) or (scores.get("sources") or {}).get("injectionSet") else []
    return injected + natural_positive_problems(plan, scores) + freshness_problems(repository, plan, scores)


def freshness_problems(repository: Repository, plan: thresholds.PreRegistration, scores: Mapping[str, Any], *,
                       bound: bool = False) -> list[str]:
    """Every panel and measurement behind confirmation-side scores computed from scratch after the plan (A5)."""
    problems = []
    planned_at = repository.store.commit_time(plan)
    sources = scores.get("sources") or {}
    cohort = "the N3 bound cohort's" if bound else "the confirmation cohort's"
    for key, what in (("bundle", f"{cohort} panel bundle"), ("positiveBundle", "the positives' panel bundle"),
                      ("naturalBundle", "the natural positives' panel bundle")):
        problems.extend(panel_freshness_problems(sources.get(key), planned_at, what))
    for key, what in (("measurements", f"{cohort} measurements"),
                      ("positiveMeasurements", "the positives' measurements"),
                      ("naturalMeasurements", "the natural positives' measurements")):
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
               population: str, positives_population: str | Sequence[str] = "P1") -> list[dict]:
    """Per consensus group: the two families' failure correlation, each voting at the unit's threshold.

    A family fails a clean negative when its own score alarms, and a target
    positive when it does not; units where either family abstained are left out.
    """
    if entry["score"]["combination"] not in registry_lib.CONSENSUS_COMBINATIONS:
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
            elif unit["population"] in _populations(positives_population) and unit["cell"]:
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


def informational_n3(units: Sequence[Mapping[str, Any]], derived: Mapping[str, Any],
                     manifest_digest: str | None = None) -> dict:
    """Report-only (N3 is unlabeled): the flag rate and the FAR bound f / (1 - pi_max) it implies, and the N3
    cohort it was measured on (so no later fail plan bounds its flag rate on that scored cohort, A5)."""
    n3 = [unit for unit in units if unit["population"] == "N3" and unit["inScope"] and unit["injectorID"] is None]
    flags = family_rate((unit["family"], _alarm(unit, derived)) for unit in n3 if unit["score"] is not None)
    return {"population": "N3", "manifestDigest": manifest_digest, "flagRate": flags.as_dict(),
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


def check_bound(n3: Mapping[str, Any], plan: thresholds.PreRegistration, calibration: Mapping[str, Any]) -> None:
    """A fail plan's N3 bound scores: its cohort, scored under --role bound like the calibration (A7)."""
    problems = []
    if n3.get("detector") != plan.detector or n3.get("role") != "bound":
        problems.append("they are not this detector's N3 bound scores (--role bound)")
    if (n3.get("cohort") or {}).get("manifestDigest") != plan.binding("n3CohortDigest"):
        problems.append("their cohort is not the one the plan names (n3CohortDigest)")
    if n3.get("detectorDefinitionSHA256") != calibration.get("detectorDefinitionSHA256"):
        problems.append("they were scored under another definition")
    if n3.get("scoringCodeSHA256") != calibration.get("scoringCodeSHA256"):
        problems.append("they were scored by other scoring code (A7)")
    if n3.get("judgeIdentities") != calibration.get("judgeIdentities"):
        problems.append("a consumed judge's output identity differs from the calibration's (A7)")
    if n3.get("evidenceIdentity") != calibration.get("evidenceIdentity"):
        problems.append("the orchestrator source or a metric version differs from the calibration's (A7)")
    if problems:
        raise CalibrationError("the --n3-scores cannot bound the flag rate, nothing was recorded: "
                               + "; ".join(problems))


def _timestamp(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_record(repository: Repository, entry: Mapping[str, Any], plan: thresholds.PreRegistration, *,
                 derived: Mapping[str, Any], outcome: Mapping[str, Any], calibration: Mapping[str, Any],
                 confirmation: Mapping[str, Any], inputs: Mapping[str, Any], disjointness: Mapping[str, Any],
                 phi: Sequence[Mapping[str, Any]], informational: Mapping[str, Any] | None,
                 informative: Mapping[str, bool], planned_at: int,
                 positives_population: str | Sequence[str] = "P1",
                 bound: Mapping[str, Any] | None = None) -> dict:
    """The tracked record of one confirmation. A fail point's record also names its N3 bound (`bound`: the N3
    scores): its cohort, its panel, its N3 counts and the flag-rate bound the ledger outcome holds."""
    qualified = outcome["status"] == "qualified"
    point = plan.binding("operatingPoint")

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
              for key, role in (("bundle", plan.population),
                                ("positiveBundle", "+".join((*_populations(positives_population), "S"))),
                                ("naturalBundle", TIER_POPULATIONS["T4"]))
              if sources.get(key)]
    bound_panel = ((bound or {}).get("sources") or {}).get("bundle")
    if bound_panel:
        panels.append({"cohort": "N3", "bundleDigest": bound_panel["bundleDigest"],
                       "startedAt": bound_panel["startedAt"]})
    record = {
        "schema": RECORD_SCHEMA, "kind": RECORD_KIND,
        "detector": entry["id"], "class": entry["class"], "stage": entry["stage"],
        "direction": entry["direction"], "combination": entry["score"]["combination"],
        "judges": [{"judge": judge, "outputIdentities": values}
                   for judge, values in sorted(confirmation["judgeIdentities"].items())],
        "operatingPoint": point,
        "verdict": outcome["status"], "level": POINT_LEVELS.get(point) if qualified else None,
        "reasons": list(outcome["reasons"]),
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
                             "construction": dict(injection["construction"])} if injection else None,
            "planCommittedAt": _timestamp(planned_at),
            "confirmationPanels": panels,
        },
        # Plural count keys: a tracked record may never carry a key named "script".
        "split": {"method": "declared-cohorts", "disjointBy": list(disjointness["disjointBy"]),
                  "counts": {f"{key}s" if key != "family" else "families": value
                             for key, value in disjointness["counts"].items()}},
        "speakers": {"unit": plan.cohorts.speaker_unit, "claim": plan.cohorts.speaker_claim,
                     "count": len({unit["speaker"] for unit in inputs["negatives"]})},
        "threshold": {"strata": derived["strata"], "values": dict(derived["thresholds"]),
                      "ranks": {key: item["rank"] for key, item in derived["byStratum"].items()},
                      "calibrationUnits": {key: item["calibrationUnits"] for key, item in derived["byStratum"].items()},
                      "alpha": plan.alpha, "rule": plan.rule, "unit": "source-family"},
        "counts": {"calibration": counts(calibration_negatives),
                   "confirmation": {plan.population: counts(inputs["negatives"]),
                                    **{population: counts(unit for unit in positives
                                                          if unit["population"] == population)
                                       for population in _populations(positives_population)},
                                    "S": counts(shams)}},
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
    natural = sources.get("naturalPositives")
    if natural:
        # The labelled corpus's cohort and label rule the natural positives came from (A5), pinned like the others.
        record["cohorts"]["naturalPositives"] = {key: natural[key] for key in ("kind", "manifestDigest", "corpus",
                                                                               "split", "labelsSHA256")}
    if bound is not None:
        # The N3 flag-rate bound (A2): what the fail point confirms beside N2, pinned like the cohorts.
        record["cohorts"]["n3"] = {"kind": bound["cohort"]["kind"], "manifestDigest": bound["cohort"]["manifestDigest"],
                                   "scoresSHA256": bound["scoresSHA256"]}
        record["counts"]["confirmation"]["N3"] = counts(_in_scope(bound["units"], "N3"))
        record["rates"]["n3"] = outcome["n3"]
    return record


def record_path(repository: Repository, detector: str, plan_digest: str) -> Path:
    return repository.records / detector / f"record-{plan_digest[:16]}.json"


def command_confirm(args: argparse.Namespace, repository: Repository) -> int:
    registry, entry = repository.entry(args.detector)
    plan = committed_plan(repository, entry, args.operating_point)
    if repository.ledger.outcome(plan.digest()) is not None:
        raise CalibrationError("this plan was already confirmed; confirmation runs once (A5)")
    calibration = load_scores(args.calibration_scores)
    confirmation = load_scores(args.confirmation_scores)
    policy = repository.policy()
    point = policy["operatingPoints"][plan.binding("operatingPoint")]
    floors = point["minimumUnits"]
    fail = fail_like(point)
    derived = derivation(repository, entry, plan, calibration, calibration_floor(repository, plan))
    if derived["status"] != "derived":
        short = {key: item["calibrationUnits"] for key, item in derived["byStratum"].items()
                 if item["status"] != "derived"}
        raise CalibrationError(f"no threshold for {short} (calibration families per stratum); "
                               f"{next(iter(derived['byStratum'].values()))['minimumNegatives']} needed")
    _check_pair(plan, calibration, confirmation)
    roles = registry_lib.role_set(registry, entry)
    positives_population = positive_populations(roles, entry)
    split = expected_split(cohort_rule(entry), roles, "confirmNegatives", plan.binding("operatingPoint") or "warn")
    if split is not None and scores_split(confirmation) != split:
        raise CalibrationError(f"the confirmation scores are not of {split_name(split)}")
    problems = confirmation_evidence_problems(repository, plan, confirmation)
    if problems:
        raise CalibrationError("the confirmation cannot start, nothing was recorded: " + "; ".join(problems))
    n3 = None
    if fail:
        # The fail point bounds the N3 flag rate on the cohort its plan names, scored after the plan (A2, A5).
        if not args.n3_scores:
            raise CalibrationError(f"a {plan.binding('operatingPoint')} confirmation bounds the N3 flag rate: pass "
                                   "--n3-scores (the plan's N3 cohort scored under --role bound)")
        n3 = load_scores(args.n3_scores)
        check_bound(n3, plan, calibration)
        problems = freshness_problems(repository, plan, n3, bound=True)
        if problems:
            raise CalibrationError("the confirmation cannot start, nothing was recorded: " + "; ".join(problems))
    elif args.n3_scores:
        if "N3" not in roles["informational"]:
            raise CalibrationError(f"role set {entry['populations']} reports no N3 informational rate (it reports "
                                   f"{roles['informational'] or 'none'}); nothing was recorded")
        n3 = load_scores(args.n3_scores)
        check_n3(n3, calibration, entry)
    disjointness = thresholds.check_cohort_disjointness(
        plan, [(unit["family"], unit["speaker"], unit["scriptID"]) for unit in calibration["units"]],
        [(unit["family"], unit["speaker"], unit["scriptID"]) for unit in confirmation["units"]])
    inputs = confirmation_inputs(entry, confirmation["units"], plan.population, positives_population)
    problems = preconditions(entry, inputs, point, confirmation, n3 if fail else None)
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
        sham_cells=sham_cells(entry), sham_minimum=int(floors["positivesPerCell" if fail else "bad"]),
        sham_informative=informative)
    if fail:
        arguments["n3_negatives"] = [_scored(unit, derived) for unit in _in_scope(n3["units"], "N3")]
    preview = thresholds.evaluate_confirmation(plan, threshold, **arguments)
    phi = phi_audits(entry, confirmation["units"], derived, plan.population, positives_population)
    informational = informational_n3(n3["units"], derived, (n3.get("cohort") or {}).get("manifestDigest")) \
        if n3 is not None and not fail else None
    record = build_record(repository, entry, plan, derived=derived, outcome=preview, calibration=calibration,
                          confirmation=confirmation, inputs=inputs, disjointness=disjointness, phi=phi,
                          informational=informational, informative=informative,
                          planned_at=repository.store.commit_time(plan), positives_population=positives_population,
                          bound=n3 if fail else None)
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
    point = record["operatingPoint"]
    if point not in SUPPORTED_OPERATING_POINTS:
        errors.append(f"operatingPoint is one of {SUPPORTED_OPERATING_POINTS}")
    level = POINT_LEVELS.get(point, "warn")
    if record["level"] != (level if record["verdict"] == "qualified" else None):
        errors.append(f"level is {level} for a qualified {point} record and null otherwise")
    # A fail record carries its N3 flag-rate bound (A2) and the N3 cohort it was measured on; a warn one neither.
    bounded = level == "fail"
    rates_n3 = (record["rates"] or {}).get("n3") if isinstance(record["rates"], Mapping) else None
    n3_cohort = (record["cohorts"] or {}).get("n3") if isinstance(record["cohorts"], Mapping) else None
    if bounded and (not isinstance(rates_n3, Mapping) or not isinstance(n3_cohort, Mapping)
                    or not is_sha256(n3_cohort.get("manifestDigest")) or not is_sha256(n3_cohort.get("scoresSHA256"))):
        errors.append("a fail record carries its N3 bound (rates.n3) and pins its N3 cohort and scores by SHA-256")
    if not bounded and (rates_n3 is not None or n3_cohort is not None):
        errors.append("a warn record carries no N3 bound")
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
    # Only a detector whose every positive is a natural recording (processed by nothing) has no sham cell.
    mechanisms = set(((record["rates"] or {}).get("mechanisms") or {}) if isinstance(record["rates"], Mapping) else ())
    natural_only = bool(mechanisms) and mechanisms <= {registry_lib.NATURAL_MECHANISM}
    if not isinstance(a4.get("cells"), list) or (not a4["cells"] and not natural_only) \
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
    elif record["combination"] in registry_lib.CONSENSUS_COMBINATIONS and not record["phiAudit"]:
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

    # A combination an operating point refuses (a two-family mean qualifies at warn only): no plan or record of it.
    points = repository.policy().get("operatingPoints") or {}

    def refused(combination: Any, point: Any) -> bool:
        value = points.get(point) if isinstance(point, str) else None
        return isinstance(value, Mapping) and combination in (value.get("refusedCombinations") or ())

    combinations = {entry["id"]: (entry.get("score") or {}).get("combination") for entry in registry.get("detectors")
                    or () if isinstance(entry, Mapping) and isinstance(entry.get("id"), str)}
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
            try:
                named = repository.store.detector_path(plan.detector, plan.binding("operatingPoint")).name
            except thresholds.PreRegistrationError as error:
                errors.append(f"{where}: {error}")
                continue
            expected = named if not path.name.startswith("plan-") else f"plan-{plan.digest()}.json"
            if path.name != expected:
                errors.append(f"{where}: the file is named {expected}")
            if path.read_text(encoding="utf-8") != json.dumps(plan.as_dict(), indent=2, sort_keys=True) + "\n":
                errors.append(f"{where}: not in the canonical form the store writes")
            if plan.binding("detectorDefinitionSHA256") is not None \
                    and edited(plan.detector, plan.binding("detectorDefinitionSHA256")):
                errors.append(f"{where}: {plan.detector}'s registry entry changed after its plan; a changed "
                              "definition needs a new version (A7)")
            if refused(combinations.get(plan.detector), plan.binding("operatingPoint")):
                errors.append(f"{where}: {plan.detector} combines by {combinations[plan.detector]}, which the "
                              f"{plan.binding('operatingPoint')} point refuses (a fail level keeps strict consensus)")
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
            if refused(record["combination"], record["operatingPoint"]):
                errors.append(f"{where}: a {record['operatingPoint']} record of a {record['combination']} detector; "
                              "the point refuses the combination (a fail level keeps strict consensus)")
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
    lines = ["# Audio-QC detector qualification", "", "Warn plans, and each fail-point plan as its own row.", "",
             "| Detector | Class | Direction | Strata | Score | Plan | Verdict | N2 FAR (upper) "
             "| Worst language (upper) | Clean abstention | Detection per cell (lower) | Shams overlap |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    rows = []
    for entry in registry["detectors"]:
        # The warn plan (or its absence), then any plan at a fail point beside it.
        rows.append((entry, "warn", repository.store.load(entry["id"])))
        rows.extend((entry, point, plan) for point in SUPPORTED_OPERATING_POINTS[1:]
                    if (plan := repository.store.load(entry["id"], point)) is not None)
    for entry, point, plan in rows:
        record = None
        if plan is not None:
            path = record_path(repository, entry["id"], plan.digest())
            record = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        status = "none" if plan is None else plan.digest()[:12]
        strata = registry_lib.strata_by(entry) or registry_lib.POOLED
        name = entry["id"] if point == "warn" else f"{entry['id']} ({point})"
        head = f"| {name} | {entry['class']} | {entry['direction']} | {strata} | {_describe_score(entry)} "
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
    scores.add_argument("--raw-outputs", type=Path, action="append",
                        help="a raw-output export of the cohort's panel (audio_qc_calibration_set.py raw-outputs), "
                             "one per judge the detector reduces")
    scores.add_argument("--positive-raw-outputs", type=Path, action="append",
                        help="the same for the injection set's panel")
    scores.add_argument("--natural-positives", type=Path,
                        help="confirmation only: the labelled corpus's cohort whose labels select natural positives")
    scores.add_argument("--natural-n1-manifest", type=Path,
                        help="the N1 manifest the natural positives' N2 cohort pins (speakers, split and labels)")
    scores.add_argument("--natural-bundle", type=Path, help="the natural positives' panel bundle")
    scores.add_argument("--natural-measurements", type=Path, help="the natural positives' measurements.json")
    scores.add_argument("--operating-point", default="warn", choices=SUPPORTED_OPERATING_POINTS,
                        help="the plan that names the cohort (confirmation and bound roles)")
    scores.add_argument("--output", required=True, type=Path)
    plan = commands.add_parser("plan", help="write the detector's pre-registration")
    plan.add_argument("--detector", required=True)
    plan.add_argument("--calibration-cohort", required=True, type=Path)
    plan.add_argument("--confirmation-cohort", required=True, type=Path)
    plan.add_argument("--confirmation-n1-manifest", type=Path,
                      help="for an N2 confirmation cohort: the N1 manifest it pins, naming its split (and speakers)")
    plan.add_argument("--calibration-n1-manifest", type=Path,
                      help="for an N2 calibration cohort of a speaker-labelled corpus: the N1 manifest it pins "
                           "(optional for FLEURS)")
    plan.add_argument("--injection-catalog-version", type=int,
                      help="for declared P2 or P3 positives: the construction catalog version the confirmation set "
                           "will carry (P1 uses this repository's injector catalog)")
    plan.add_argument("--calibration-scores", required=True, type=Path)
    plan.add_argument("--alpha", required=True, type=float)
    plan.add_argument("--operating-point", default="warn", choices=SUPPORTED_OPERATING_POINTS)
    plan.add_argument("--tier-catalog-version", type=tier_catalog_version, action="append",
                      help="TIER=N for each second construction tier the detector declares (e.g. T2=1)")
    plan.add_argument("--n3-cohort", type=Path,
                      help="for a fail point: the N3 takes manifest its flag rate is bounded on (A2)")
    plan.add_argument("--injection-catalog-seed", type=int,
                      help="the catalog seed the confirmation injection set will be built with (required unless "
                           "every positive is a natural recording)")
    plan.add_argument("--injection-sample-seed", type=int)
    plan.add_argument("--injection-sample-per-cell", type=int)
    plan.add_argument("--injection-classes", type=injection_classes,
                      help="the classes the confirmation injection set will inject, comma-separated")
    plan.add_argument("--natural-positives", type=Path,
                      help="for natural labelled positives: the labelled corpus's cohort (its confirmation split)")
    plan.add_argument("--natural-n1-manifest", type=Path,
                      help="the N1 manifest the natural positives' N2 cohort pins (speakers, split and labels)")
    derive = commands.add_parser("derive", help="the threshold under the committed plan")
    derive.add_argument("--detector", required=True)
    derive.add_argument("--calibration-scores", required=True, type=Path)
    derive.add_argument("--output", type=Path)
    derive.add_argument("--operating-point", default="warn", choices=SUPPORTED_OPERATING_POINTS)
    confirm = commands.add_parser("confirm", help="the one confirmation of the committed plan")
    confirm.add_argument("--detector", required=True)
    confirm.add_argument("--calibration-scores", required=True, type=Path)
    confirm.add_argument("--confirmation-scores", required=True, type=Path)
    confirm.add_argument("--n3-scores", type=Path,
                         help="warn: informational N3 scores; a fail point: its N3 bound scores (--role bound)")
    confirm.add_argument("--operating-point", default="warn", choices=SUPPORTED_OPERATING_POINTS)
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
