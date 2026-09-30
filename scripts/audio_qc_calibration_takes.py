#!/usr/bin/env python3
"""The AQ-07 natural calibration takes (population N3): plan, batch files, binding, validation.

Population N3 of the audio QC audit (section 5.1) is natural Vocello takes over
the committed CC0 script pool (`config/audio-qc-script-pool.json`). The unit of
independence is the family, one script x voice x seed. The committed take
policy (`config/audio-qc-calibration-takes.json`) organizes the takes in cells,
each one of the product's generation paths:

- `standard`: each language's three voices per split (two Built-in speakers
  and one Voice Design brief) in rotation, plus a donor subset spoken by the
  next voice. It is the version 1 layout: its batch ids, take ids and seed
  identity are unchanged, so a batch whose voice is unchanged keeps its seed.
- `clone`: Voice Clone takes conditioned on human reference clips of the
  pinned speaker corpora (`config/audio-qc-corpora.json`, extracted by
  `scripts/audio_qc_corpora.py extract`), same-language and cross-language,
  chosen by a seeded rule. Each clone take records its `reference` (the copied
  clip's WAV path relative to the manifest, digest, corpus, speaker), which
  `audio_qc_orchestrator.py manifest --from-calibration-takes` passes to the
  speaker judges.
- `cross-lingual`: every Built-in speaker of the split and Voice Design briefs
  written in English and in the target language speaking each language; each
  take records its voice's language (`voiceLanguage`) beside its target
  language.
- `long-form`: multi-segment projects, pool scripts joined above the
  product planner's runtime token limit, run through `vocello batch
  --long-form` (the apps' long-form path: planner, streaming segment takes,
  bounded assembler). Long-form takes form the n3-long-form cohort, so a plan
  holds them alone.

A Built-in speaker, a Voice Design brief and a clone reference speaker belong
to one split (`speakerPartition`), as the qualification driver's disjointness
check requires. This module is offline and device-free; `scripts/macos_test.sh
qc-takes` runs the generator between its steps.

Commands:
  validate-policy     check the committed take policy against the speaker contract and the corpora registry
  plan                write an immutable take plan for one split of the pool (`--cells`, default the
                      policy's defaultCells; the clone cell reads the extracted speaker corpora)
  batch-files         write one line file per batch (copying each clone reference beside them), and
                      print one unit-separated row per batch for the lane
  collect-diagnostics copy the engine diagnostics rows the lane's batches wrote (reduced to the codes,
                      digests and introspection numbers the manifest binds) into the run, before the
                      engine's capped log trims them
  manifest            bind every batch's `vocello batch --json` output to the
                      plan by item index, move each WAV to wav/<takeID>.wav and
                      write the takes manifest (a planned take without output
                      is recorded as missing, never dropped)
  validate-manifest   recompute the digests and check the manifest's plan binding

Seeds: `vocello batch --seed` applies one seed to every item of a batch, so a
seed belongs to one (split, cell, language, mode, voice) batch, derived like the
seed identity of `language_bench_evidence.py` (the first 8 bytes of a SHA-256,
masked to 63 bits). The standard cell keeps the version 1 identity; every other
cell appends its name. Each script is spoken once per voice, so a family is
still script x voice x seed (a long-form project stands in for the script).

Everything this module writes (plans, line files, reference copies, WAVs,
manifests, collected diagnostics) is an untracked build artifact. A manifest
records WAV paths relative to itself, never an absolute local path.

Engine-time evidence. With `--diagnostics`, each generated take also carries
`engineIntrospection`, the talker's introspection summary (codebook-0 token
cycles, per-step entropy, the EOS trajectory; the telemetry row's
`engineIntrospection`, which `audio_qc_observations.introspection_summary`
mirrors), from the engine row whose `samplingWAVDigest` is the take's WAV
digest: the WAV's exact bytes bind the row, so no generation id is needed. A
take whose row the diagnostics no longer hold, or whose rows disagree, carries
null, and the manifest counts it (`introspection`). The lane collects each
batch's rows into the run (`collect-diagnostics`) and raises the registered
log cap, so a long run keeps them. A long-form take carries `longForm`
(`long_form_block`): the assembled output's frame count, the assembler's
maximum segment-boundary jump and each seam's output frame, from its
`LongFormAssemblyEvidence`, whose output digest must be the take's WAV digest;
its segments' introspection summaries are bound by each segment WAV's digest
(`longFormSegments`). `audio_qc_calibration_set.py score` copies both into
measurements.json, the Stage 0 evidence the `introspection` and `longform`
detector sources read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from typing import Any, Iterable, Mapping, Sequence
import unicodedata

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib import jsonio  # noqa: E402
from lib.language_metrics import (  # noqa: E402
    LANGUAGE_LOCALE_CODES,
    MAX_TEXT_CHARACTERS,
    is_sha256,
    text_sha256,
)

REPO = SCRIPT_DIR.parent
DEFAULT_POOL = REPO / "config" / "audio-qc-script-pool.json"
DEFAULT_POLICY = REPO / "config" / "audio-qc-calibration-takes.json"
CORPORA_REGISTRY = REPO / "config" / "audio-qc-corpora.json"
SPEAKER_CONTRACT = REPO / "Sources" / "Resources" / "qwenvoice_contract.json"

POOL_KIND = "audio-qc-script-pool"
POLICY_KIND = "audio-qc-calibration-takes-policy"
PLAN_KIND = "audio-qc-calibration-take-plan"
MANIFEST_KIND = "audio-qc-calibration-takes"
SPLITS = ("calibration", "confirmation")
STANDARD, CLONE, CROSS_LINGUAL, LONG_FORM = "standard", "clone", "cross-lingual", "long-form"
CELLS = (STANDARD, CLONE, CROSS_LINGUAL, LONG_FORM)
ROLES = ("primary", "donor", "secondary", "project")
MODES = ("custom", "design", "clone")
VOICE_MODES = {"builtin": "custom", "design": "design", "clone": "clone"}
SEED_IDENTITY = "audio-qc-calibration-seed-v1"
DONOR_IDENTITY = "audio-qc-calibration-donor-v1"
CROSS_LINGUAL_DONOR_IDENTITY = "audio-qc-calibration-cross-lingual-donor-v1"
CLONE_SPEAKER_SPLIT_IDENTITY = "audio-qc-clone-speaker-split-v1"
CLONE_REFERENCE_IDENTITY = "audio-qc-clone-reference-v1"
CLONE_SECONDARY_IDENTITY = "audio-qc-clone-secondary-v1"
LONG_FORM_IDENTITY = "audio-qc-long-form-v1"
GENDERS = frozenset({"male", "female"})
UINT63_MASK = (1 << 63) - 1
MAX_BRIEF_CHARACTERS = 240

SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}\Z")
SCRIPT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
SPEAKER_ID = re.compile(r"[a-z][a-z0-9_]{1,31}\Z")
BRIEF_ID = re.compile(r"[a-z][a-z0-9-]{1,31}\Z")
REFERENCE_KEY = re.compile(r"ref[0-9a-f]{12}\Z")
SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
# The unit separator delimits the lane's per-batch rows; every character Swift
# counts as a newline would split one planned text into two batch items.
FIELD_SEPARATOR = "\x1f"
LINE_BREAKS = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e\x85  ")

# The fields a manifest take copies from its planned take, unchanged; a version 1 plan has only the first.
PLANNED_FIELDS = (
    "takeID", "family", "scriptID", "language", "role", "mode", "variant", "variation", "voice", "seed",
    "batchID", "text", "textSHA256",
)
PLANNED_OPTIONAL_FIELDS = ("cell", "voiceLanguage", "projectScripts")
OUTPUT_FIELDS = ("wavPath", "wavSHA256", "durationSeconds", "finishReason", "status", "missingReason", "textBinding",
                 "rejection", "failure", "engineIntrospection", "longForm", "longFormSegments", "reference")
# The telemetry row's engineIntrospection (GenerationEngineIntrospection; algorithm 1): its numbers, the ones the
# summary leaves null when the take has none (no exact cycle, no observed step, no likely EOS), and its seams.
INTROSPECTION_NUMBERS = (
    "algorithmVersion", "codecFrameCount", "longestRepeatedTokenRunFrames", "tokenCyclePeriod",
    "tokenCycleSpanFrames", "tokenCycleRepeats", "tokenCycleStartFrame", "observedStepCount", "entropyMeanNats",
    "entropyP95Nats", "longestHighEntropyRunSteps", "eosProbabilityFinal", "eosProbabilityMax",
    "eosProbabilityMaxStep", "eosFirstLikelyStep", "eosLikelyStepsWithoutStop",
)
INTROSPECTION_REQUIRED = ("algorithmVersion", "codecFrameCount", "observedStepCount")
# A take's long-form block: the assembled output (LongFormAssemblyEvidence) reduced to what the detectors read.
LONG_FORM_SCHEMA_VERSION = 1
LONG_FORM_KEYS = ("schemaVersion", "algorithmVersion", "sampleRate", "segmentCount", "outputFrameCount",
                  "maximumSegmentBoundaryJump", "seamFrames")
# One segment of a long-form take (no text, no path): the planner's boundary and the engine's take of it.
LONG_FORM_SEGMENT_KEYS = ("index", "boundary", "intendedPauseMilliseconds", "effectiveSeed", "durationSeconds",
                          "finishReason", "wavSHA256", "engineIntrospection")
LONG_FORM_BOUNDARIES = frozenset({"paragraph", "sentence", "semicolon_or_colon", "safe_clause", "whitespace",
                                  "grapheme", "end_of_text"})
# A clone take's reference clip as the manifest records it (the copy beside the manifest, never the corpus path).
REFERENCE_KEYS = ("wavPath", "wavSHA256", "referenceKey", "corpus", "clipID", "speaker", "gender", "language",
                  "durationSeconds", "transcriptSHA256")
TAKE_STATUSES = ("generated", "rejected", "failed", "missing")
# A resumed batch segment's stdout: `<batchID>@<offset>.json` (offset 0 is `<batchID>.json`).
GENERATION_ID = re.compile(r"^[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")
SEGMENT_FILE = re.compile(r"^(?P<batch>.+)@(?P<offset>[1-9][0-9]{0,5})\.json$")
QC_REJECTION_CODE = "audio.quality_rejected"
ENGINE_CODE = re.compile(r"^[a-z0-9_.]{1,96}$")
QC_FLAG = re.compile(r"^[a-z0-9_:(),.-]{1,96}$")
# collect-diagnostics: the engine logs it reads and the digests of the source lines it has taken.
ENGINE_LOGS = ("generations.jsonl", "generation-failures.jsonl")
COLLECTED_LINES = "collected-lines.txt"
# What a reduced row keeps beside the trace digest (`StartupReliabilityArtifactEvidence.telemetryNotes`), the
# controlled-generation EOS hold's timings (`Qwen3EOSSuppressionWindow.evidence`) and the tokenizer digest form.
TRACE_NOTES = {"codecTraceFrameCount": re.compile(r"[0-9]{1,5}"), "codecTraceComplete": re.compile(r"true|false")}
EOS_HOLD_TIMINGS = ("talker_eos_suppression_frames", "talker_eos_suppression_start_frame")
TOKENIZER_DIGEST = re.compile(r"(?:sha256:)?[0-9a-f]{64}")


class TakeError(ValueError):
    """A pool, policy, plan, batch output or manifest is unusable."""


def load_json(path: Path) -> Any:
    return jsonio.load_json(path, error=TakeError, reject_duplicate_keys=True, redact="name")


def canonical_digest(value: Any) -> str:
    return jsonio.sha256_json(value, ascii=False)


def self_digest(value: dict[str, Any], field: str) -> str:
    unsigned = dict(value)
    unsigned.pop(field, None)
    return canonical_digest(unsigned)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def text_issues(text: Any) -> list[str]:
    """Why a text cannot be one `vocello batch --file` line, bound back by its exact text."""
    if not isinstance(text, str) or not text:
        return ["empty"]
    issues = []
    if any(character in LINE_BREAKS for character in text):
        issues.append("line-break")
    if FIELD_SEPARATOR in text:
        issues.append("unit-separator")
    if any(unicodedata.category(character) == "Cc" for character in text if character not in LINE_BREAKS
           and character != FIELD_SEPARATOR):
        issues.append("control-character")
    if text != text.strip():
        # The batch reader trims every line, so an edge space would never match.
        issues.append("edge-whitespace")
    if len(text) > MAX_TEXT_CHARACTERS:
        issues.append("too-long")
    return issues


def _count(value: Any, *, positive: bool = False) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and (value > 0 if positive else value >= 0)


def _positive_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def _relative_posix(value: Any) -> bool:
    """A relative POSIX path with no parent step (a corpus path under its root, a WAV beside its manifest)."""
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


# --------------------------------------------------------------------------- #
# Policy
# --------------------------------------------------------------------------- #

def contract_speakers(path: Path = SPEAKER_CONTRACT) -> set[str]:
    contract = load_json(path)
    groups = contract.get("speakers")
    if not isinstance(groups, dict) or not groups:
        raise TakeError("the speaker contract has no Built-in speakers")
    speakers: set[str] = set()
    for values in groups.values():
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise TakeError("the speaker contract lists malformed Built-in speakers")
        speakers.update(values)
    return speakers


def contract_speaker_languages(path: Path = SPEAKER_CONTRACT) -> dict[str, str]:
    """Each Built-in speaker's native language (the contract's speakerMetadata), as a canonical language id."""
    metadata = load_json(path).get("speakerMetadata")
    if not isinstance(metadata, dict) or not metadata:
        raise TakeError("the speaker contract has no speaker metadata")
    languages: dict[str, str] = {}
    for speaker, entry in metadata.items():
        native = entry.get("nativeLanguage") if isinstance(entry, dict) else None
        language = native.strip().lower() if isinstance(native, str) else None
        if language not in LANGUAGE_LOCALE_CODES:
            raise TakeError(f"the speaker contract names no product language as {speaker}'s native language")
        languages[speaker] = language
    return languages


def _split_brief_families(policy: Mapping[str, Any]) -> dict[str, set[str]]:
    """The Voice Design briefs each split speaks: its brief, that brief's translations and its cross-lingual briefs."""
    briefs = policy.get("designBriefs") if isinstance(policy.get("designBriefs"), dict) else {}
    families: dict[str, set[str]] = {}
    for split in SPLITS:
        entry = (policy.get("splits") or {}).get(split) or {}
        roots = {entry.get("designBrief"), *(entry.get("crossLingualBriefs") or [])}
        families[split] = {brief_id for brief_id, brief in briefs.items()
                           if isinstance(brief, dict) and brief.get("concept") in roots}
    return families


def _brief_issues(briefs: Mapping[str, Any]) -> list[str]:
    issues = []
    for brief_id, brief in briefs.items():
        brief = brief if isinstance(brief, dict) else {}
        text = brief.get("text")
        if not BRIEF_ID.fullmatch(str(brief_id)):
            issues.append(f"design brief id {brief_id!r} is unsafe")
        if text_issues(text) or len(text) > MAX_BRIEF_CHARACTERS:
            issues.append(f"design brief {brief_id!r} must be one trimmed line of at most {MAX_BRIEF_CHARACTERS} characters")
        if brief.get("language") not in LANGUAGE_LOCALE_CODES:
            issues.append(f"design brief {brief_id!r} names no product language")
        concept = brief.get("concept")
        root = briefs.get(concept) if isinstance(concept, str) else None
        if not isinstance(root, dict) or root.get("concept") != concept or root.get("language") != "english":
            issues.append(f"design brief {brief_id!r} must name an English brief of its own as its concept")
    return issues


def _split_issues(policy: Mapping[str, Any], briefs: Mapping[str, Any], languages: Sequence[str]) -> list[str]:
    splits = policy.get("splits")
    if not isinstance(splits, dict) or set(splits) != set(SPLITS):
        return [f"splits must declare exactly {', '.join(SPLITS)}"]
    issues = []
    for split in SPLITS:
        entry = splits[split] if isinstance(splits[split], dict) else {}
        brief_id = entry.get("designBrief")
        if brief_id not in briefs or briefs[brief_id].get("concept") != brief_id:
            issues.append(f"split {split} names an unknown design brief or a translation")
            continue
        for language in languages:
            if language == "english":
                continue
            native = [key for key, brief in briefs.items()
                      if brief.get("concept") == brief_id and brief.get("language") == language]
            if len(native) != 1:
                issues.append(f"split {split} needs exactly one {language} translation of {brief_id}")
        extras = entry.get("crossLingualBriefs")
        if (not isinstance(extras, list) or len(set(extras)) != len(extras)
                or any(extra not in briefs or briefs[extra].get("concept") != extra or extra == brief_id
                       for extra in extras)):
            issues.append(f"split {split} crossLingualBriefs must list distinct English briefs besides its own")
        for key in ("expectedTakeCount", "expectedScriptsPerLanguage"):
            expected = entry.get(key)
            if expected is not None and not _count(expected, positive=True):
                issues.append(f"split {split} has an invalid {key}")
    families = _split_brief_families(policy)
    if families["calibration"] & families["confirmation"]:
        issues.append("the splits must use different design briefs (disjoint by speaker)")
    return issues


def _partition_issues(policy: Mapping[str, Any], speakers: set[str], genders: Mapping[str, str]) -> list[str]:
    partition = policy.get("speakerPartition")
    if not isinstance(partition, dict) or not all(isinstance(partition.get(split), list) for split in SPLITS):
        return ["speakerPartition must list each split's Built-in speakers"]
    issues = []
    sides = [partition[split] for split in SPLITS]
    if any(len(set(side)) != len(side) for side in sides) or set(sides[0]) & set(sides[1]):
        issues.append("speakerPartition gives each Built-in speaker to exactly one split")
    if set(sides[0]) | set(sides[1]) != speakers:
        issues.append("speakerPartition must cover exactly the contract's Built-in speakers")
    if any(speaker not in genders for side in sides for speaker in side):
        issues.append("every partitioned speaker needs a gender in speakerGenders")
    return issues


def _clone_issues(config: Mapping[str, Any], policy: Mapping[str, Any], languages: Sequence[str],
                  registry: Mapping[str, Any]) -> list[str]:
    issues = []
    sources = config.get("referenceSources")
    registered = registry.get("sources") if isinstance(registry.get("sources"), dict) else {}
    if not isinstance(sources, dict) or set(sources) != set(languages):
        return ["cells.clone.referenceSources must name every policy language"]
    for language, names in sources.items():
        if not isinstance(names, list) or len(set(names)) != len(names):
            issues.append(f"cells.clone.referenceSources.{language} must list distinct sources")
            continue
        for name in names:
            entry = registered.get(name)
            labels = entry.get("labels") if isinstance(entry, dict) and isinstance(entry.get("labels"), dict) else {}
            if not isinstance(entry, dict) or "speaker" not in {entry.get("group"), *(entry.get("alsoIn") or [])}:
                issues.append(f"clone reference source {name!r} is not a registered speaker corpus")
            elif language not in (entry.get("languages") or []):
                issues.append(f"clone reference source {name!r} does not cover {language}")
            elif not labels.get("speaker") or not labels.get("text"):
                issues.append(f"clone reference source {name!r} labels no speaker or no transcript")
    if not any(sources.values()):
        issues.append("cells.clone needs at least one reference source")
    excluded = config.get("excludedSources") or {}
    if not isinstance(excluded, dict) or any(name not in registered or any(name in names for names in sources.values())
                                             for name in excluded):
        issues.append("cells.clone.excludedSources must name registered sources it does not use")
    window = config.get("referenceWindowSeconds") if isinstance(config.get("referenceWindowSeconds"), dict) else {}
    bounds = [window.get(key) for key in ("minimum", "preferredMinimum", "maximum")]
    if not all(_positive_number(value) for value in bounds) or not bounds[0] <= bounds[1] <= bounds[2]:
        issues.append("cells.clone.referenceWindowSeconds must order 0 < minimum <= preferredMinimum <= maximum")
    emotions = config.get("referenceEmotions")
    if not isinstance(emotions, list) or not all(isinstance(value, str) and value for value in emotions):
        issues.append("cells.clone.referenceEmotions must list canonical emotions")
    counts = [config.get(key) for key in ("primaryReferencesPerLanguage", "secondaryReferencesPerLanguage",
                                          "scriptsPerReference")]
    if not all(_count(value, positive=True) for value in counts):
        issues.append("cells.clone reference counts must be positive integers")
    else:
        for split in SPLITS:
            scripts = ((policy.get("splits") or {}).get(split) or {}).get("expectedScriptsPerLanguage")
            if _count(scripts, positive=True) and (counts[0] * counts[2] != scripts or counts[1] * counts[2] > scripts):
                issues.append(f"cells.clone gives each of the {split} split's {scripts} scripts one primary take")
    return issues


def _long_form_issues_of_policy(config: Mapping[str, Any], languages: Sequence[str]) -> list[str]:
    issues = []
    chosen = config.get("languages")
    if (not isinstance(chosen, list) or len(set(chosen)) != len(chosen) or len(chosen) < 3
            or any(language not in languages for language in chosen)):
        issues.append("cells.long-form.languages must list at least 3 distinct policy languages")
    if not _count(config.get("projectsPerLanguage"), positive=True):
        issues.append("cells.long-form.projectsPerLanguage must be a positive integer")
    limit = config.get("runtimeTokenLimit")
    window = config.get("estimateWindow") if isinstance(config.get("estimateWindow"), dict) else {}
    if not _count(limit, positive=True) or not _count(window.get("minimum"), positive=True) \
            or not _count(window.get("maximum"), positive=True) \
            or not limit < window["minimum"] <= window["maximum"]:
        issues.append("cells.long-form.estimateWindow must order runtimeTokenLimit < minimum <= maximum")
    unspaced = config.get("unspacedLanguages", [])
    if not isinstance(unspaced, list) or any(language not in LANGUAGE_LOCALE_CODES for language in unspaced):
        issues.append("cells.long-form.unspacedLanguages must list product languages")
    return issues


def _cell_issues(policy: Mapping[str, Any], languages: Sequence[str], registry: Mapping[str, Any]) -> list[str]:
    cells = policy.get("cells")
    if not isinstance(cells, dict) or set(cells) != set(CELLS):
        return [f"cells must configure exactly {', '.join(CELLS)}"]
    issues = []
    default = policy.get("defaultCells")
    if not isinstance(default, list) or not default or any(cell not in CELLS for cell in default) \
            or (LONG_FORM in default and len(default) > 1):
        issues.append("defaultCells must list known cells (long-form alone)")
    for cell in CELLS:
        config = cells[cell] if isinstance(cells[cell], dict) else {}
        expected = config.get("expectedTakeCount")
        if not isinstance(expected, dict) or set(expected) != set(SPLITS) \
                or not all(_count(value, positive=True) for value in expected.values()):
            issues.append(f"cells.{cell}.expectedTakeCount must give each split a positive count")
    clone = cells[CLONE] if isinstance(cells[CLONE], dict) else {}
    issues += _clone_issues(clone, policy, languages, registry)
    donors = (cells[CROSS_LINGUAL] if isinstance(cells[CROSS_LINGUAL], dict) else {}).get("donorScriptsPerLanguage")
    if not _count(donors):
        issues.append("cells.cross-lingual.donorScriptsPerLanguage must be a non-negative integer")
    issues += _long_form_issues_of_policy(cells[LONG_FORM] if isinstance(cells[LONG_FORM], dict) else {}, languages)
    return issues


def policy_issues(policy: Any, *, speakers: set[str], registry: Mapping[str, Any] | None = None) -> list[str]:
    if not isinstance(policy, dict):
        return ["the policy must be an object"]
    issues: list[str] = []
    if policy.get("schemaVersion") != 1 or policy.get("kind") != POLICY_KIND:
        issues.append(f"the policy is not {POLICY_KIND} schema 1")
    version = policy.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 2:
        issues.append("the policy version must be an integer of at least 2 (the cells layout)")
    generation = policy.get("generation") if isinstance(policy.get("generation"), dict) else {}
    # delivery "app-default": the lane passes `vocello batch --app-delivery`, so Custom and Design carry the
    # apps' Neutral preset instruction as a new Studio draft does (uninstructed takes wander in pitch).
    expected_generation = {"customMode": "custom", "designMode": "design", "cloneMode": "clone", "variant": "speed",
                           "variation": "expressive", "delivery": "app-default"}
    for key, value in expected_generation.items():
        if generation.get(key) != value:
            issues.append(f"generation.{key} must be {value!r}")
    seed_rule = policy.get("seedRule") if isinstance(policy.get("seedRule"), dict) else {}
    seed_generation = seed_rule.get("generation")
    if isinstance(seed_generation, bool) or not isinstance(seed_generation, int) or seed_generation < 1:
        issues.append("seedRule.generation must be a positive integer")
    if not isinstance(seed_rule.get("policy"), str) or not seed_rule["policy"]:
        issues.append("seedRule.policy must name the seed policy")
    assignment = policy.get("assignment") if isinstance(policy.get("assignment"), dict) else {}
    if not _count(assignment.get("donorScriptsPerLanguage")):
        issues.append("assignment.donorScriptsPerLanguage must be a non-negative integer")

    genders = policy.get("speakerGenders")
    if not isinstance(genders, dict) or any(value not in GENDERS for value in genders.values()):
        issues.append("speakerGenders must map speakers to male or female")
        genders = {}
    briefs = policy.get("designBriefs")
    if not isinstance(briefs, dict) or not briefs or not all(isinstance(brief, dict) for brief in briefs.values()):
        issues.append("designBriefs must name at least one brief")
        briefs = {}
    issues += _brief_issues(briefs)
    issues += _partition_issues(policy, speakers, genders)
    partition = policy.get("speakerPartition") if isinstance(policy.get("speakerPartition"), dict) else {}

    languages = policy.get("languages")
    if not isinstance(languages, list) or not languages:
        issues.append("languages must be a non-empty list")
        languages = []
    seen: list[str] = []
    for entry in languages:
        language = entry.get("language") if isinstance(entry, dict) else None
        if language not in LANGUAGE_LOCALE_CODES or language in seen:
            issues.append(f"language {language!r} is unknown or repeated")
            continue
        seen.append(language)
        voices: dict[str, list[str]] = {}
        for split in SPLITS:
            pair = entry.get(split)
            if (not isinstance(pair, list) or len(pair) != 2 or len(set(pair)) != 2
                    or not all(isinstance(speaker, str) and SPEAKER_ID.fullmatch(speaker) for speaker in pair)):
                issues.append(f"{language}: {split} needs two distinct Built-in speakers")
                continue
            unknown = [speaker for speaker in pair if speaker not in speakers]
            if unknown:
                issues.append(f"{language}: {split} names speakers absent from the contract: {', '.join(unknown)}")
            side = partition.get(split) if isinstance(partition.get(split), list) else []
            if any(speaker not in side for speaker in pair):
                issues.append(f"{language}: {split} names a speaker of the other split (speakerPartition)")
            # A split whose Built-in speakers have both genders pairs a male and a female in every language.
            if {genders.get(speaker) for speaker in side} >= GENDERS \
                    and {genders.get(speaker) for speaker in pair} != GENDERS:
                issues.append(f"{language}: {split} must pair a male and a female speaker")
            voices[split] = pair
        if len(voices) == len(SPLITS) and set(voices["calibration"]) & set(voices["confirmation"]):
            issues.append(f"{language}: the splits must not share a Built-in speaker")
    issues += _split_issues(policy, briefs, seen)
    if registry is None:
        registry = load_json(CORPORA_REGISTRY)
    issues += _cell_issues(policy, seen, registry)
    return issues


def load_policy(path: Path) -> dict[str, Any]:
    policy = load_json(path)
    issues = policy_issues(policy, speakers=contract_speakers())
    if issues:
        raise TakeError("the take policy is invalid: " + "; ".join(issues))
    return policy


def voice_key(voice: dict[str, Any]) -> str:
    """A voice's key in take ids, batch ids and seeds; KeyError for a voice of no known kind."""
    kind = voice["kind"]
    if kind == "builtin":
        return voice["id"]
    if kind == "design":
        return f"design-{voice['briefID']}"
    if kind == "clone":
        return f"clone-{voice['referenceKey']}"
    raise KeyError(kind)


def voice_mode(voice: dict[str, Any]) -> str:
    return VOICE_MODES[voice["kind"]]


def voice_language(policy: Mapping[str, Any], voice: Mapping[str, Any], natives: Mapping[str, str]) -> str:
    """The voice's own language: a Built-in speaker's native language, a brief's language, a reference's language."""
    if voice["kind"] == "builtin":
        return natives[voice["id"]]
    if voice["kind"] == "design":
        return policy["designBriefs"][voice["briefID"]]["language"]
    return voice["language"]


def _design_voice(policy: Mapping[str, Any], brief_id: str) -> dict[str, Any]:
    return {"kind": "design", "briefID": brief_id, "brief": policy["designBriefs"][brief_id]["text"]}


def policy_voices(policy: dict[str, Any], language: str, split: str) -> list[dict[str, Any]]:
    """The language's standard voices for a split in rotation order: Built-in, Built-in, Voice Design."""
    entry = next(item for item in policy["languages"] if item["language"] == language)
    brief_id = policy["splits"][split]["designBrief"]
    return [{"kind": "builtin", "id": speaker} for speaker in entry[split]] + [_design_voice(policy, brief_id)]


def native_brief(policy: Mapping[str, Any], split: str, language: str) -> str:
    """The split's brief written in the target language (the brief itself for English)."""
    concept = policy["splits"][split]["designBrief"]
    return next(brief_id for brief_id, brief in policy["designBriefs"].items()
                if brief["concept"] == concept and brief["language"] == language)


def cross_lingual_voices(policy: dict[str, Any], language: str, split: str) -> list[dict[str, Any]]:
    """The split's Built-in speakers the standard cell does not pair with the language, then the split's brief
    in the target language (not for English, where it is the standard cell's), then its English briefs."""
    entry = next(item for item in policy["languages"] if item["language"] == language)
    voices = [{"kind": "builtin", "id": speaker} for speaker in policy["speakerPartition"][split]
              if speaker not in entry[split]]
    if language != "english":
        voices.append(_design_voice(policy, native_brief(policy, split, language)))
    return voices + [_design_voice(policy, brief_id) for brief_id in policy["splits"][split]["crossLingualBriefs"]]


def batch_seed(policy: dict[str, Any], split: str, language: str, mode: str, key: str,
               cell: str = STANDARD) -> int:
    identity = f"{SEED_IDENTITY}|{policy['seedRule']['generation']}|{split}|{language}|{mode}|{key}"
    if cell != STANDARD:
        identity += f"|{cell}"
    return int.from_bytes(hashlib.sha256(identity.encode("utf-8")).digest()[:8], "big") & UINT63_MASK


def donor_rank(split: str, language: str, script_id: str, identity: str = DONOR_IDENTITY) -> str:
    return _sha(f"{identity}|{split}|{language}|{script_id}")


def select_donors(split: str, language: str, primaries: Sequence[tuple[str, int]], voice_count: int,
                  count: int, identity: str = DONOR_IDENTITY) -> set[str]:
    """Round-robin over the primary-voice groups, each ranked by its donor hash."""
    groups = [sorted((script_id for script_id, index in primaries if index == voice),
                     key=lambda script_id: donor_rank(split, language, script_id, identity))
              for voice in range(voice_count)]
    donors: list[str] = []
    depth = 0
    while len(donors) < count and any(depth < len(group) for group in groups):
        for group in groups:
            if depth < len(group) and len(donors) < count:
                donors.append(group[depth])
        depth += 1
    return set(donors)


# --------------------------------------------------------------------------- #
# Long-form projects
# --------------------------------------------------------------------------- #

def _graphemes(text: str) -> Iterable[str]:
    """Approximate extended grapheme clusters: a base character with its combining marks and joined characters."""
    cluster = ""
    joining = False
    for character in text:
        if cluster and (joining or unicodedata.combining(character) or character in "‍︎️"):
            cluster += character
            joining = character == "‍"
            continue
        if cluster:
            yield cluster
        cluster, joining = character, False
    if cluster:
        yield cluster


def conservative_token_estimate(text: str) -> int:
    """The long-form planner's conservative text-token estimate (estimator version 1).

    Mirrors `ConservativeTokenEstimator` in Sources/QwenVoiceCore/LongFormPlanning.swift:
    whitespace ends an ASCII word run and costs nothing; an ASCII letter, digit,
    apostrophe, underscore or hyphen extends the run, which costs ceil(length / 3);
    any other grapheme ends the run and costs max(1, ceil(UTF-8 bytes / 3)).
    """
    estimate, run = 0, 0
    for grapheme in _graphemes(text):
        if all(character.isspace() for character in grapheme):
            run = 0
            continue
        if len(grapheme) == 1 and grapheme.isascii() and (grapheme.isalnum() or grapheme in "'_-"):
            before = (run + 2) // 3
            run += 1
            estimate += (run + 2) // 3 - before
            continue
        run = 0
        estimate += max(1, (len(grapheme.encode("utf-8")) + 2) // 3)
    return estimate


def long_form_projects(policy: Mapping[str, Any], split: str, language: str,
                       scripts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The split's long-form projects of a language: pool scripts joined above the planner's token limit."""
    config = policy["cells"][LONG_FORM]
    window = config["estimateWindow"]
    joiner = "" if language in config.get("unspacedLanguages", []) else " "
    locale = LANGUAGE_LOCALE_CODES[language]
    projects: list[dict[str, Any]] = []
    for index in range(config["projectsPerLanguage"]):
        order = sorted(scripts, key=lambda script: _sha(f"{LONG_FORM_IDENTITY}|{split}|{language}|{index}|{script['id']}"))
        chosen: list[Mapping[str, Any]] = []
        estimate = 0
        for script in order:
            candidate = joiner.join(item["text"] for item in [*chosen, script])
            candidate_estimate = conservative_token_estimate(candidate)
            if candidate_estimate > window["maximum"]:
                continue
            chosen.append(script)
            estimate = candidate_estimate
            if estimate >= window["minimum"]:
                break
        if estimate < window["minimum"]:
            raise TakeError(f"{language}: the {split} split's scripts cannot fill long-form project {index + 1} "
                            f"to {window['minimum']} estimate units")
        text = joiner.join(script["text"] for script in chosen)
        if issues := text_issues(text):
            raise TakeError(f"{language}: long-form project {index + 1} cannot be one batch line ({', '.join(issues)})")
        projects.append({"id": f"lf-{locale}-{split[:3]}{index + 1:02d}", "text": text, "textSHA256": text_sha256(text),
                         "scripts": [script["id"] for script in chosen], "estimate": estimate})
    if len({project["text"] for project in projects}) != len(projects):
        raise TakeError(f"{language}: two long-form projects of the {split} split have the same text")
    return projects


# --------------------------------------------------------------------------- #
# Clone references
# --------------------------------------------------------------------------- #

def reference_key(source: str, clip_id: str) -> str:
    return "ref" + _sha(f"{source}|{clip_id}")[:12]


def _clip_eligible(clip: Mapping[str, Any], language: str, config: Mapping[str, Any]) -> bool:
    window = config["referenceWindowSeconds"]
    text, duration, speaker = clip.get("text"), clip.get("durationSeconds"), clip.get("speaker")
    if clip.get("language") != language or not isinstance(speaker, str) or not speaker.strip():
        return False
    # The transcript travels as one argument of one lane row: one line, never read as a flag.
    if text_issues(text) or text.startswith("-"):
        return False
    if not _positive_number(duration) or not window["minimum"] <= duration <= window["maximum"]:
        return False
    if clip.get("emotion") is not None and clip.get("emotionCanonical") not in config["referenceEmotions"]:
        return False
    clip_id = clip.get("clipID")
    return (isinstance(clip_id, str) and SCRIPT_ID.fullmatch(clip_id) is not None
            and clip.get("wavPath") == f"wav/{clip_id}.wav" and is_sha256(clip.get("wavSHA256")))


def _interleave(lists: Sequence[Sequence[Any]]) -> list[Any]:
    merged: list[Any] = []
    for depth in range(max((len(items) for items in lists), default=0)):
        merged.extend(items[depth] for items in lists if depth < len(items))
    return merged


def _gender_order(candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Female and male alternating (female first) where the corpus labels gender; the unlabelled after them."""
    by_gender = {gender: [item for item in candidates if item["gender"] == gender] for gender in ("female", "male")}
    unlabelled = [item for item in candidates if item["gender"] not in GENDERS]
    return _interleave([by_gender["female"], by_gender["male"]]) + unlabelled


def _corpus_manifest(corpora: Any, registry: Mapping[str, Any], source: str, root: Path) -> tuple[Path, dict]:
    directory = corpora.source_directory(registry, source, root) / corpora.EXTRACTED_DIRECTORY
    path = directory / corpora.MANIFEST_NAME
    if not path.is_file():
        raise TakeError(f"clone references: {source} is not extracted "
                        f"(python3 scripts/audio_qc_corpora.py extract --source {source})")
    manifest = load_json(path)
    if issues := corpora.manifest_issues(manifest, corpora.extraction_identity(registry, source)):
        raise TakeError(f"clone references: the {source} extraction is unusable: {issues[0]}")
    return directory, manifest


def reference_candidates(policy: Mapping[str, Any], split: str, *, corpora_root: Path | None = None,
                         registry: Mapping[str, Any] | None = None) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    """Each reference language's candidate references of a split, in allocation order, and the corpora read."""
    import audio_qc_corpora as corpora  # deferred: it imports this module, and numpy

    registry = registry if registry is not None else corpora.load_registry()
    root = corpora_root if corpora_root is not None else corpora.cache_root()
    config = policy["cells"][CLONE]
    candidates: dict[str, list[dict]] = {}
    read: dict[str, dict] = {}
    manifests: dict[str, tuple[Path, dict]] = {}
    splits_of: dict[str, set[str]] = {}
    for language in [entry["language"] for entry in policy["languages"]]:
        per_source = []
        for source in config["referenceSources"][language]:
            if source not in manifests:
                manifests[source] = _corpus_manifest(corpora, registry, source, root)
                directory, manifest = manifests[source]
                read[source] = {"manifestDigest": manifest["manifestDigest"],
                                "extractionSHA256": manifest["extractionSHA256"]}
                # A speaker belongs to one split in every language of the corpus (a reader of two languages
                # is one speaker), ranked over the whole source.
                everyone = sorted({clip["speaker"].strip() for clip in manifest["clips"] if isinstance(clip, dict)
                                   and isinstance(clip.get("speaker"), str) and clip["speaker"].strip()},
                                  key=lambda speaker: _sha(f"{CLONE_SPEAKER_SPLIT_IDENTITY}|{source}|{speaker}"))
                splits_of[source] = {speaker for rank, speaker in enumerate(everyone) if SPLITS[rank % 2] == split}
            directory, manifest = manifests[source]
            clips = [clip for clip in manifest["clips"] if isinstance(clip, dict) and clip.get("language") == language]
            mine = {str(clip["speaker"]).strip() for clip in clips
                    if isinstance(clip.get("speaker"), str) and clip["speaker"].strip() in splits_of[source]}
            chosen = []
            for speaker in mine:
                eligible = [clip for clip in clips if str(clip.get("speaker")).strip() == speaker
                            and _clip_eligible(clip, language, config)]
                preferred = [clip for clip in eligible
                             if clip["durationSeconds"] >= config["referenceWindowSeconds"]["preferredMinimum"]]
                pool = preferred or eligible
                if not pool:
                    continue
                clip = min(pool, key=lambda item: _sha(f"{CLONE_REFERENCE_IDENTITY}|{split}|{source}|{item['clipID']}"))
                corpus_path = (directory / clip["wavPath"]).relative_to(root).as_posix()
                gender = clip.get("gender") if clip.get("gender") in GENDERS else None
                chosen.append({
                    "referenceKey": reference_key(source, clip["clipID"]), "source": source, "clipID": clip["clipID"],
                    "speaker": speaker, "gender": gender, "language": language,
                    "durationSeconds": clip["durationSeconds"], "wavSHA256": clip["wavSHA256"],
                    "corpusPath": corpus_path, "transcript": clip["text"], "transcriptSHA256": text_sha256(clip["text"]),
                    "rank": _sha(f"{CLONE_REFERENCE_IDENTITY}|{split}|{source}|{speaker}"),
                })
            chosen.sort(key=lambda item: item["rank"])
            per_source.append(_gender_order(chosen))
        candidates[language] = _interleave(per_source)
    return candidates, read


def clone_allocation(policy: Mapping[str, Any], split: str, candidates: Mapping[str, list[dict]]) -> dict[str, dict]:
    """Each target language's primary and secondary references; a speaker serves one reference per split.

    Every language's primary same-language references are allocated first;
    then, in policy order, each language's cross-language references (its
    primaries when no corpus covers it, and its secondaries), drawn round-robin
    over the other reference languages starting after its own.
    """
    config = policy["cells"][CLONE]
    order = [entry["language"] for entry in policy["languages"]]
    primary, secondary = config["primaryReferencesPerLanguage"], config["secondaryReferencesPerLanguage"]
    used: set[tuple[str, str]] = set()
    cursors = {language: 0 for language in order}

    def next_from(language: str) -> dict | None:
        items = candidates.get(language, [])
        while cursors[language] < len(items):
            item = items[cursors[language]]
            cursors[language] += 1
            if (item["source"], item["speaker"]) not in used:
                used.add((item["source"], item["speaker"]))
                return item
        return None

    allocation = {language: {"primary": [], "secondary": []} for language in order}
    for language in order:
        if not config["referenceSources"][language]:
            continue
        while len(allocation[language]["primary"]) < primary:
            item = next_from(language)
            if item is None:
                raise TakeError(f"clone references: {language} has {len(allocation[language]['primary'])} eligible "
                                f"speakers in the {split} split, {primary} needed")
            allocation[language]["primary"].append(item)
    for index, language in enumerate(order):
        rotation = [other for other in order[index + 1:] + order[:index]
                    if other != language and config["referenceSources"][other]]
        wanted = (0 if config["referenceSources"][language] else primary) + secondary
        drawn: list[dict] = []
        exhausted: set[str] = set()
        while len(drawn) < wanted and len(exhausted) < len(rotation):
            for other in rotation:
                if len(drawn) == wanted or other in exhausted:
                    continue
                item = next_from(other)
                if item is None:
                    exhausted.add(other)
                else:
                    drawn.append(item)
        if len(drawn) < wanted:
            raise TakeError(f"clone references: the {split} split has {len(drawn)} cross-language references "
                            f"left for {language}, {wanted} needed")
        cross_primary = wanted - secondary
        allocation[language]["primary"] += drawn[:cross_primary]
        allocation[language]["secondary"] = drawn[cross_primary:]
    return allocation


def _clone_voice(reference: Mapping[str, Any]) -> dict[str, Any]:
    return {"kind": "clone", "referenceKey": reference["referenceKey"], "source": reference["source"],
            "clipID": reference["clipID"], "speaker": reference["speaker"], "gender": reference["gender"],
            "language": reference["language"]}


def _batch_reference(reference: Mapping[str, Any]) -> dict[str, Any]:
    return {key: reference[key] for key in ("referenceKey", "corpusPath", "wavSHA256", "durationSeconds",
                                            "transcript", "transcriptSHA256")}


# --------------------------------------------------------------------------- #
# Pool and plan
# --------------------------------------------------------------------------- #

def load_pool(path: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    pool = load_json(path)
    if pool.get("schemaVersion") != 1 or pool.get("kind") != POOL_KIND:
        raise TakeError(f"the script pool is not {POOL_KIND} schema 1")
    if not is_sha256(pool.get("poolDigest")):
        raise TakeError("the script pool declares no poolDigest")
    # The committed pool (scripts/audio_qc_script_pool.py) declares its
    # languages once and lists every script in one flat `entries` list, each
    # entry naming its language.
    languages = pool.get("languages")
    if not isinstance(languages, list) or not languages:
        raise TakeError("the script pool has no languages")
    by_language: dict[str, list[dict[str, Any]]] = {}
    for entry in languages:
        language = entry.get("language") if isinstance(entry, dict) else None
        if not isinstance(language, str) or language in by_language:
            raise TakeError(f"the script pool repeats or omits a language: {language!r}")
        by_language[language] = []
    scripts = pool.get("entries")
    if not isinstance(scripts, list):
        raise TakeError("the script pool's entries must be a list")
    script_ids: set[str] = set()
    for script in scripts:
        script_id = script.get("id") if isinstance(script, dict) else None
        if not isinstance(script_id, str) or not SCRIPT_ID.fullmatch(script_id) or script_id in script_ids:
            raise TakeError(f"a pool script id is unsafe or repeated: {script_id!r}")
        script_ids.add(script_id)
        language = script.get("language")
        if language not in by_language:
            raise TakeError(f"{script_id}: language {language!r} is not declared by the pool")
        if script.get("split") not in SPLITS:
            raise TakeError(f"{script_id}: unknown split {script.get('split')!r}")
        text = script.get("text")
        if not isinstance(text, str) or script.get("textSHA256") != text_sha256(text):
            raise TakeError(f"{script_id}: textSHA256 does not bind the script text")
        by_language[language].append(script)
    return pool, by_language


def _requested(values: Sequence[str] | None) -> list[str]:
    requested: list[str] = []
    for value in values or ():
        for item in value.split(","):
            item = item.strip()
            if item and item not in requested:
                requested.append(item)
    return requested


def _emit_cell(policy: dict[str, Any], natives: Mapping[str, str], *, cell: str, split: str, language: str,
               voices: Sequence[dict[str, Any]], assigned: Sequence[Sequence[tuple[Mapping[str, Any], str]]],
               references: Sequence[Mapping[str, Any]] | None = None,
               long_form: bool = False) -> tuple[list[dict], list[dict]]:
    """One batch per voice with members: its takes in script (or project) order, one derived seed."""
    takes: list[dict] = []
    batches: list[dict] = []
    for position, (voice, members) in enumerate(zip(voices, assigned)):
        if not members:
            continue
        key, mode = voice_key(voice), voice_mode(voice)
        seed = batch_seed(policy, split, language, mode, key, cell)
        # The standard cell keeps the version 1 batch ids; the other cells name themselves.
        batch_id = f"{split}-{language}-{key}" if cell == STANDARD else f"{split}-{cell}-{language}-{key}"
        own_language = voice_language(policy, voice, natives)
        take_ids = []
        for item, role in sorted(members, key=lambda member: member[0]["id"]):
            take_id = f"{item['id']}--{key}"
            take_ids.append(take_id)
            take = {
                "takeID": take_id, "family": f"{item['id']}:{key}:{seed}", "scriptID": item["id"],
                "language": language, "role": role, "mode": mode, "variant": "speed",
                "variation": "expressive", "voice": dict(voice), "seed": seed, "batchID": batch_id,
                "text": item["text"], "textSHA256": item["textSHA256"], "cell": cell, "voiceLanguage": own_language,
            }
            if "scripts" in item:
                take["projectScripts"] = list(item["scripts"])
            takes.append(take)
        batch = {
            "batchID": batch_id, "cell": cell, "language": language, "mode": mode, "variant": "speed",
            "variation": "expressive", "voice": dict(voice), "seed": seed, "takeIDs": take_ids,
        }
        if long_form:
            batch["longForm"] = True
        if references is not None:
            batch["reference"] = _batch_reference(references[position])
        batches.append(batch)
    return takes, batches


def _rotation(scripts: Sequence[Mapping[str, Any]], voice_count: int, *, split: str, language: str, donors: int,
              identity: str) -> list[list[tuple[Mapping[str, Any], str]]]:
    """Each script by its primary voice in rotation, and the donor subset by the next voice."""
    primaries = [(script["id"], index % voice_count) for index, script in enumerate(scripts)]
    chosen = select_donors(split, language, primaries, voice_count, donors, identity)
    assigned: list[list[tuple[Mapping[str, Any], str]]] = [[] for _ in range(voice_count)]
    for script, (_, primary) in zip(scripts, primaries):
        assigned[primary].append((script, "primary"))
        if script["id"] in chosen:
            assigned[(primary + 1) % voice_count].append((script, "donor"))
    return assigned


def _plan_cell(policy: dict[str, Any], natives: Mapping[str, str], cell: str, split: str, language: str,
               scripts: Sequence[Mapping[str, Any]], allocation: Mapping[str, dict] | None) -> tuple[list, list]:
    if cell == STANDARD:
        voices = policy_voices(policy, language, split)
        assigned = _rotation(scripts, len(voices), split=split, language=language,
                             donors=policy["assignment"]["donorScriptsPerLanguage"], identity=DONOR_IDENTITY)
        return _emit_cell(policy, natives, cell=cell, split=split, language=language, voices=voices, assigned=assigned)
    if cell == CROSS_LINGUAL:
        voices = cross_lingual_voices(policy, language, split)
        assigned = _rotation(scripts, len(voices), split=split, language=language,
                             donors=policy["cells"][CROSS_LINGUAL]["donorScriptsPerLanguage"],
                             identity=CROSS_LINGUAL_DONOR_IDENTITY)
        return _emit_cell(policy, natives, cell=cell, split=split, language=language, voices=voices, assigned=assigned)
    if cell == CLONE:
        assert allocation is not None
        config = policy["cells"][CLONE]
        primaries, secondaries = allocation[language]["primary"], allocation[language]["secondary"]
        references = [*primaries, *secondaries]
        assigned: list[list[tuple[Mapping[str, Any], str]]] = [[] for _ in references]
        for index, script in enumerate(scripts):
            assigned[index % len(primaries)].append((script, "primary"))
        ranked = sorted(scripts, key=lambda script: donor_rank(split, language, script["id"], CLONE_SECONDARY_IDENTITY))
        for index, script in enumerate(ranked[:len(secondaries) * config["scriptsPerReference"]]):
            assigned[len(primaries) + index % len(secondaries)].append((script, "secondary"))
        return _emit_cell(policy, natives, cell=cell, split=split, language=language,
                          voices=[_clone_voice(reference) for reference in references], assigned=assigned,
                          references=references)
    projects = long_form_projects(policy, split, language, scripts)
    voices = policy_voices(policy, language, split)
    assigned = [[] for _ in voices]
    for index, project in enumerate(projects):
        assigned[index % len(voices)].append((project, "project"))
    return _emit_cell(policy, natives, cell=cell, split=split, language=language, voices=voices, assigned=assigned,
                      long_form=True)


def requested_cells(policy: Mapping[str, Any], values: Sequence[str] | None) -> list[str]:
    cells = _requested(values) or list(policy["defaultCells"])
    unknown = [cell for cell in cells if cell not in CELLS]
    if unknown:
        raise TakeError(f"unknown cell(s): {', '.join(unknown)} (known: {', '.join(CELLS)})")
    if LONG_FORM in cells and len(cells) > 1:
        raise TakeError("long-form takes are the n3-long-form cohort: plan the long-form cell alone")
    return [cell for cell in CELLS if cell in cells]


def build_plan(*, pool_path: Path, policy_path: Path, split: str, run_id: str,
               languages: Sequence[str] | None = None, cells: Sequence[str] | None = None,
               corpora_root: Path | None = None) -> dict[str, Any]:
    if split not in SPLITS:
        raise TakeError(f"unknown split {split!r}")
    if not SAFE_RUN_ID.fullmatch(run_id):
        raise TakeError("the run id contains unsafe characters or is too long")
    policy = load_policy(policy_path)
    chosen_cells = requested_cells(policy, cells)
    pool, by_language = load_pool(pool_path)
    policy_languages = [entry["language"] for entry in policy["languages"]]
    requested = _requested(languages)
    if requested:
        unknown = sorted({language for language in requested
                          if language not in policy_languages or language not in by_language})
    else:
        # Every pool language is planned by default; one the policy lacks is refused, never skipped.
        unknown = sorted(language for language in by_language if language not in policy_languages)
    if unknown:
        raise TakeError(f"unknown language(s) for this pool and policy: {', '.join(unknown)}")
    selected = [language for language in policy_languages
                if language in (requested or by_language)]
    if not selected:
        raise TakeError("no language is selected")

    natives = contract_speaker_languages()
    allocation = references_read = None
    if CLONE in chosen_cells:
        # Allocated over every policy language, so a language subset plans the same references.
        candidates, references_read = reference_candidates(policy, split, corpora_root=corpora_root)
        allocation = clone_allocation(policy, split, candidates)
    takes: list[dict[str, Any]] = []
    batches: list[dict[str, Any]] = []
    for language in selected:
        scripts = sorted((script for script in by_language[language] if script["split"] == split),
                         key=lambda script: script["id"])
        if not scripts:
            raise TakeError(f"{language}: the {split} split is empty")
        texts: set[str] = set()
        for script in scripts:
            if issues := text_issues(script["text"]):
                raise TakeError(f"{script['id']}: the text cannot be one batch line ({', '.join(issues)})")
            if script["text"] in texts:
                raise TakeError(f"{script['id']}: the {split} split repeats a text in {language}")
            texts.add(script["text"])
        for cell in chosen_cells:
            if cell == LONG_FORM and language not in policy["cells"][LONG_FORM]["languages"]:
                continue
            cell_takes, cell_batches = _plan_cell(policy, natives, cell, split, language, scripts, allocation)
            takes.extend(cell_takes)
            batches.extend(cell_batches)
    if not takes:
        raise TakeError("the selected cells and languages plan no take")

    expected = (sum(policy["cells"][cell]["expectedTakeCount"][split] for cell in chosen_cells)
                if selected == policy_languages else None)
    plan: dict[str, Any] = {
        "schemaVersion": 1, "kind": PLAN_KIND, "runID": run_id, "split": split, "languages": selected,
        "cells": chosen_cells,
        "poolDigest": pool["poolDigest"], "poolVersion": pool.get("version"),
        "poolFileSHA256": jsonio.sha256_file(pool_path), "policyDigest": jsonio.sha256_file(policy_path),
        "policyVersion": policy["version"], "seedPolicy": policy["seedRule"]["policy"],
        "seedGeneration": policy["seedRule"]["generation"], "variant": "speed", "variation": "expressive",
        "delivery": policy["generation"]["delivery"],
        "expectedTakeCount": expected, "takeCount": len(takes), "batchCount": len(batches),
        "takes": takes, "batches": batches,
    }
    if references_read is not None:
        plan["references"] = {"registrySHA256": jsonio.sha256_file(CORPORA_REGISTRY), "sources": references_read}
    plan["planDigest"] = self_digest(plan, "planDigest")
    return plan


def _batch_reference_issues(reference: Any) -> list[str]:
    if not isinstance(reference, dict):
        return ["a clone batch names its reference clip"]
    issues = []
    if not REFERENCE_KEY.fullmatch(str(reference.get("referenceKey"))) or not is_sha256(reference.get("wavSHA256")):
        issues.append("a clone reference names its key and WAV digest")
    if not _relative_posix(reference.get("corpusPath")):
        issues.append("a clone reference's corpus path is relative to the corpora root")
    transcript = reference.get("transcript")
    if text_issues(transcript) or transcript.startswith("-") or reference.get("transcriptSHA256") != text_sha256(transcript):
        issues.append("a clone reference's transcript is one bound line")
    if not _positive_number(reference.get("durationSeconds")):
        issues.append("a clone reference names its duration")
    return issues


def validate_plan(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("schemaVersion") != 1 or plan.get("kind") != PLAN_KIND:
        raise TakeError(f"the plan is not {PLAN_KIND} schema 1")
    if plan.get("planDigest") != self_digest(plan, "planDigest"):
        raise TakeError("the plan digest does not match its content")
    if plan.get("split") not in SPLITS or not SAFE_RUN_ID.fullmatch(str(plan.get("runID"))):
        raise TakeError("the plan's split or run id is invalid")
    takes, batches = plan.get("takes"), plan.get("batches")
    if not isinstance(takes, list) or not takes or not isinstance(batches, list) or not batches:
        raise TakeError("the plan has no takes or no batches")
    if plan.get("takeCount") != len(takes) or plan.get("batchCount") != len(batches):
        raise TakeError("the plan's counts do not match its takes and batches")
    # A version 1 plan names no cells: every take is a standard take.
    cells = plan.get("cells", [STANDARD])
    if not isinstance(cells, list) or not cells or any(cell not in CELLS for cell in cells) \
            or (LONG_FORM in cells and len(cells) > 1):
        raise TakeError("the plan names unknown cells, or long-form beside another cell")
    by_id: dict[str, dict[str, Any]] = {}
    for take in takes:
        take_id = take.get("takeID") if isinstance(take, dict) else None
        if not isinstance(take_id, str) or not SAFE_RUN_ID.fullmatch(take_id) or take_id in by_id:
            raise TakeError(f"the plan has an unsafe or repeated take id: {take_id!r}")
        by_id[take_id] = take
        if text_issues(take.get("text")) or take.get("textSHA256") != text_sha256(take["text"]):
            raise TakeError(f"{take_id}: the planned text is invalid or unbound")
        voice = take.get("voice") if isinstance(take.get("voice"), dict) else {}
        if take.get("role") not in ROLES or take.get("mode") not in MODES \
                or VOICE_MODES.get(voice.get("kind")) != take.get("mode"):
            raise TakeError(f"{take_id}: invalid role, mode or voice")
        if take.get("cell", STANDARD) not in cells:
            raise TakeError(f"{take_id}: its cell is not one of the plan's")
        if (take.get("role") == "project") != (take.get("cell", STANDARD) == LONG_FORM):
            raise TakeError(f"{take_id}: only a long-form take is a project")
    batched: list[str] = []
    batch_ids: set[str] = set()
    for batch in batches:
        batch_id = batch.get("batchID") if isinstance(batch, dict) else None
        if not isinstance(batch_id, str) or not SAFE_RUN_ID.fullmatch(batch_id) or batch_id in batch_ids:
            raise TakeError(f"the plan has an unsafe or repeated batch id: {batch_id!r}")
        batch_ids.add(batch_id)
        members = batch.get("takeIDs")
        if not isinstance(members, list) or not members:
            raise TakeError(f"{batch_id}: the batch has no takes")
        seed = batch.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= UINT63_MASK:
            raise TakeError(f"{batch_id}: invalid seed")
        cell = batch.get("cell", STANDARD)
        if (batch.get("longForm") is True) != (cell == LONG_FORM) or batch.get("longForm") not in (None, True):
            raise TakeError(f"{batch_id}: only a long-form batch is marked longForm")
        if batch.get("mode") == "clone":
            if issues := _batch_reference_issues(batch.get("reference")):
                raise TakeError(f"{batch_id}: {issues[0]}")
            if batch["reference"]["referenceKey"] != (batch.get("voice") or {}).get("referenceKey"):
                raise TakeError(f"{batch_id}: the reference is not the batch voice's")
        elif "reference" in batch:
            raise TakeError(f"{batch_id}: only a clone batch names a reference")
        for take_id in members:
            take = by_id.get(take_id)
            if take is None or any(take.get(key) != batch.get(key) for key in (
                    "language", "mode", "variant", "variation", "voice", "seed")) or take.get("batchID") != batch_id \
                    or take.get("cell", STANDARD) != cell:
                raise TakeError(f"{batch_id}: take {take_id!r} does not belong to this batch")
        texts = [by_id[take_id]["text"] for take_id in members]
        if len(set(texts)) != len(texts):
            raise TakeError(f"{batch_id}: the batch repeats a text")
        batched.extend(members)
    if sorted(batched) != sorted(by_id):
        raise TakeError("every planned take must belong to exactly one batch")
    return plan


# --------------------------------------------------------------------------- #
# Batch files
# --------------------------------------------------------------------------- #

def _copy_reference(reference: Mapping[str, Any], corpora_root: Path, references_dir: Path) -> Path:
    """The clone reference beside the run (`<references>/<referenceKey>.wav`), its bytes verified."""
    destination = references_dir / f"{reference['referenceKey']}.wav"
    if destination.is_file() and jsonio.sha256_file(destination) == reference["wavSHA256"]:
        return destination
    source = corpora_root / PurePosixPath(reference["corpusPath"])
    if not source.is_file():
        raise TakeError(f"clone reference {reference['referenceKey']}: its corpus clip is missing "
                        "(python3 scripts/audio_qc_corpora.py extract)")
    references_dir.mkdir(parents=True, exist_ok=True)
    staging = destination.with_suffix(".partial")
    shutil.copyfile(source, staging)
    if jsonio.sha256_file(staging) != reference["wavSHA256"]:
        staging.unlink()
        raise TakeError(f"clone reference {reference['referenceKey']}: the corpus clip's bytes changed")
    staging.replace(destination)
    return destination


def write_batch_files(plan: dict[str, Any], out_dir: Path, *, references_dir: Path | None = None,
                      corpora_root: Path | None = None) -> list[dict[str, Any]]:
    """One line file per batch, one text (or long-form project) per line in plan order; each clone batch's
    reference copied into `references_dir` (default: beside `out_dir`)."""
    plan = validate_plan(plan)
    takes = {take["takeID"]: take for take in plan["takes"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    references_dir = references_dir if references_dir is not None else out_dir.parent / "references"
    if corpora_root is None and any(batch["mode"] == "clone" for batch in plan["batches"]):
        import audio_qc_corpora as corpora  # deferred: it imports this module, and numpy

        corpora_root = corpora.cache_root()
    rows = []
    for batch in plan["batches"]:
        path = out_dir / f"{batch['batchID']}.txt"
        lines = [takes[take_id]["text"] for take_id in batch["takeIDs"]]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        voice = batch["voice"]
        reference = transcript = ""
        if batch["mode"] == "clone":
            assert corpora_root is not None
            reference = str(_copy_reference(batch["reference"], corpora_root, references_dir).resolve())
            transcript = batch["reference"]["transcript"]
        rows.append({
            "batchID": batch["batchID"], "mode": batch["mode"], "variant": batch["variant"],
            "variation": batch["variation"], "seed": batch["seed"],
            "speaker": voice["id"] if voice["kind"] == "builtin" else "",
            "brief": voice["brief"] if voice["kind"] == "design" else "",
            "count": len(lines), "file": path, "reference": reference, "transcript": transcript,
            "longForm": "1" if batch.get("longForm") else "",
        })
    return rows


def batch_row_line(row: dict[str, Any]) -> str:
    fields = [row["batchID"], row["mode"], row["variant"], row["variation"], str(row["seed"]),
              row["speaker"], row["brief"], str(row["count"]), str(row["file"]),
              str(row.get("reference", "")), row.get("transcript", ""), row.get("longForm", "")]
    if any(FIELD_SEPARATOR in field or "\n" in field for field in fields):
        raise TakeError(f"{row['batchID']}: a batch field contains a separator")
    return FIELD_SEPARATOR.join(fields)


# --------------------------------------------------------------------------- #
# Binding the batch outputs
# --------------------------------------------------------------------------- #

def _parse_batch_stdout(path: Path) -> Any:
    """The batch's `--json` stdout: one JSON object (the last JSON line if anything precedes it)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError):
        return "unparseable"
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        for line in reversed(raw.splitlines()):
            if line.strip().startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    break
    return "unparseable"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _long_form_output(item: Mapping[str, Any]) -> dict[str, Any]:
    """A long-form item's project evidence (`vocello batch --long-form`): the assembly and the segment takes."""
    return {"assembly": item.get("longFormAssembly"), "segments": item.get("longFormSegments"),
            "planDigest": item.get("longFormPlanDigest")}


def batch_outcomes(result_path: Path, batch: dict[str, Any], planned: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each planned item's outcome, positionally by item index.

    Returns one dict per planned take: {"status": "generated", "audioPath",
    "durationSeconds", "finishReason", "textBinding"} (and, for a long-form
    project, "longForm": its assembly and segment takes) or {"status":
    "missing", "missingReason"}. A structurally foreign output (another mode or
    variant, another item count, a changed text, a single-take output for a
    long-form batch or the reverse) raises: it cannot be bound at all.
    """
    payload = _parse_batch_stdout(result_path)
    if payload is None:
        return [{"status": "missing", "missingReason": "no-batch-output"} for _ in planned]
    if not isinstance(payload, dict):
        return [{"status": "missing", "missingReason": "batch-output-unparseable"} for _ in planned]
    batch_id = batch["batchID"]
    if payload.get("mode") != batch["mode"] or payload.get("variant") != batch["variant"]:
        raise TakeError(f"{batch_id}: the batch output's mode or variant differs from the plan")
    long_form = batch.get("longForm") is True
    if (payload.get("longForm") is True) != long_form:
        raise TakeError(f"{batch_id}: the batch output is {'not ' if long_form else ''}a long-form batch's")
    items = payload.get("items")
    if not isinstance(items, list):
        raise TakeError(f"{batch_id}: the batch output has no items")
    outcomes: list[dict[str, Any]] = []
    if payload.get("schemaVersion") == 2:
        # FailedBatchJSON: every planned row, by index, with no text.
        if payload.get("plannedCount") != len(planned):
            raise TakeError(f"{batch_id}: the failed batch planned {payload.get('plannedCount')!r} items, "
                            f"the plan {len(planned)}")
        rows: dict[int, dict[str, Any]] = {}
        for row in items:
            index = row.get("index") if isinstance(row, dict) else None
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(planned) or index in rows:
                raise TakeError(f"{batch_id}: the failed batch has an invalid or repeated row index")
            rows[index] = row
        for index, _ in enumerate(planned):
            row = rows.get(index)
            if row is None:
                outcomes.append({"status": "missing", "missingReason": "batch-row-absent"})
                continue
            status = row.get("status")
            duration = _number(row.get("durationSeconds"))
            if status == "completed" and isinstance(row.get("audioPath"), str) and duration is not None:
                outcome = {"status": "generated", "audioPath": row["audioPath"], "durationSeconds": duration,
                           "finishReason": row.get("finishReason"), "textBinding": "index"}
                if long_form:
                    outcome["longForm"] = _long_form_output(row)
                outcomes.append(outcome)
                continue
            reason = f"batch-{status}" if isinstance(status, str) and re.fullmatch(r"[a-z_]{1,32}", status) \
                else "batch-row-invalid"
            code = row.get("errorCode")
            if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,64}", code) and code != status:
                reason += f":{code}"
            outcome = {"status": "missing", "missingReason": reason}
            generation_id = row.get("generationID")
            if status == "failed" and isinstance(generation_id, str) and GENERATION_ID.fullmatch(generation_id):
                outcome["generationID"] = generation_id.upper()
            outcomes.append(outcome)
        return outcomes
    if payload.get("schemaVersion") is not None:
        raise TakeError(f"{batch_id}: unsupported batch output schema {payload.get('schemaVersion')!r}")
    # BatchJSON: every item completed, with its text.
    if payload.get("count") != len(items) or len(items) != len(planned):
        raise TakeError(f"{batch_id}: the batch output has {len(items)} items, the plan {len(planned)}")
    for index, (item, take) in enumerate(zip(items, planned)):
        if not isinstance(item, dict) or item.get("index") != index:
            raise TakeError(f"{batch_id}: item {index} is out of order")
        if item.get("text") != take["text"]:
            raise TakeError(f"{take['takeID']}: the batch item's text differs from the planned text")
        duration = _number(item.get("durationSeconds"))
        if not isinstance(item.get("audioPath"), str) or duration is None:
            outcomes.append({"status": "missing", "missingReason": "batch-item-invalid"})
            continue
        outcome = {"status": "generated", "audioPath": item["audioPath"], "durationSeconds": duration,
                   "finishReason": item.get("finishReason"), "textBinding": "text"}
        if long_form:
            outcome["longForm"] = _long_form_output(item)
        outcomes.append(outcome)
    return outcomes


def batch_segments(batch_results: Path, batch_id: str) -> list[tuple[int, Path]]:
    """The batch's stdout segments, by start offset: the first invocation, then
    each resumption after a failed item (`<batchID>@<offset>.json`)."""
    segments = [(0, batch_results / f"{batch_id}.json")]
    if batch_results.is_dir():
        for path in batch_results.iterdir():
            match = SEGMENT_FILE.match(path.name)
            if match and match["batch"] == batch_id:
                segments.append((int(match["offset"]), path))
    return sorted(segments)


def segmented_outcomes(batch_results: Path, batch: dict[str, Any],
                       planned: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each planned item's outcome across the batch's segments.

    A segment at offset o re-runs the items from o (one seed for the whole
    batch, and each item's sampling depends only on the seed and its text, so a
    resumed item is the item the first invocation would have produced). An
    item's outcome comes from the last segment that starts at or before it.
    """
    outcomes: list[dict[str, Any]] = [{"status": "missing", "missingReason": "no-batch-output"} for _ in planned]
    for offset, path in batch_segments(batch_results, batch["batchID"]):
        if offset >= len(planned):
            raise TakeError(f"{batch['batchID']}: a resumed segment starts past the batch ({offset})")
        if offset and not path.is_file():
            continue
        for index, outcome in enumerate(batch_outcomes(path, batch, planned[offset:]), start=offset):
            outcomes[index] = outcome
    return outcomes


def next_segment_offset(result_path: Path, offset: int, count: int) -> str:
    """Where a stopped batch resumes: after its one failed item, or `stop`.

    Only a genuine generation failure resumes (the engine's mandatory QC
    rejection is one); a cancellation, an unreadable output or anything else
    stops the batch. `done` when the failed item was the batch's last.
    """
    payload = _parse_batch_stdout(result_path)
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 2 or not isinstance(payload.get("items"), list):
        return "stop"
    rows = sorted((row for row in payload["items"] if isinstance(row, dict) and isinstance(row.get("index"), int)
                   and not isinstance(row.get("index"), bool)), key=lambda row: row["index"])
    for row in rows:
        if row.get("status") == "completed":
            continue
        if row.get("status") == "failed" and row.get("errorCode") == "generation_failed":
            following = offset + row["index"] + 1
            return str(following) if following < count else "done"
        return "stop"
    return "stop"


def _jsonl(path: Path) -> Iterable[dict[str, Any]]:
    try:
        handle = path.open(encoding="utf-8")
    except FileNotFoundError:
        return
    with handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield value


def engine_failures(diagnostics: Path | None, generation_ids: set[str]) -> dict[str, dict[str, Any]]:
    """The engine's recorded failure for each generation id: its failure code
    and, for a mandatory QC rejection, the Fast QC flags that fired.

    Reads only codes and flag names (privacy-safe summaries), never messages.
    """
    found: dict[str, dict[str, Any]] = {}
    if diagnostics is None or not generation_ids:
        return found
    engine = diagnostics / "engine"
    for record in _jsonl(engine / "generation-failures.jsonl"):
        generation_id = str(record.get("generationID", "")).upper()
        code = record.get("errorCode")
        if generation_id in generation_ids and isinstance(code, str) and ENGINE_CODE.fullmatch(code):
            found.setdefault(generation_id, {})["errorCode"] = code
    for record in _jsonl(engine / "generations.jsonl"):
        generation_id = str(record.get("generationID", "")).upper()
        notes = record.get("notes")
        if generation_id not in generation_ids or not isinstance(notes, dict):
            continue
        flags = notes.get("audioQCFlags")
        if isinstance(flags, str):
            names = [flag for flag in flags.split(",") if QC_FLAG.fullmatch(flag)]
            if names:
                found.setdefault(generation_id, {})["audioQCFlags"] = names
    return found


def introspection_issues(block: Any) -> list[str]:
    """Why a take's engineIntrospection block is not the engine's summary; empty when it is."""
    if not isinstance(block, dict):
        return ["the introspection summary is an object"]
    issues = []
    unknown = set(block) - set(INTROSPECTION_NUMBERS) - {"seamCodecFrames", "wavSHA256"}
    if unknown:
        issues.append(f"the introspection summary has unknown fields {sorted(unknown)}")
    if "wavSHA256" in block and not is_sha256(block["wavSHA256"]):
        issues.append("introspection wavSHA256 names the generation's WAV digest")
    for key in INTROSPECTION_NUMBERS:
        value = block.get(key)
        if value is None and key not in INTROSPECTION_REQUIRED:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            issues.append(f"introspection {key} is a non-negative number")
    if not _count(block.get("algorithmVersion"), positive=True):
        issues.append("introspection algorithmVersion is a positive integer")
    seams = block.get("seamCodecFrames", [])
    if not isinstance(seams, list) or not all(_count(frame) for frame in seams):
        issues.append("introspection seamCodecFrames lists codec frames")
    return issues


def long_form_block(evidence: Any) -> dict[str, Any]:
    """A long-form take's `longForm` block from its assembler's LongFormAssemblyEvidence (the JSON it encodes).

    A seam is the output frame where a segment's content starts after the first
    (`segments[k].contentOutputRange.lowerBound`, k >= 1): the assembler measures
    its boundary jump there, between that frame and the one before it (the
    previous segment's last frame, or the inserted pause's last zero).
    """
    if not isinstance(evidence, dict) or not isinstance(evidence.get("segments"), list):
        raise TakeError("the long-form assembly evidence lists no segments")
    seams = []
    for segment in evidence["segments"][1:]:
        bounds = segment.get("contentOutputRange") if isinstance(segment, dict) else None
        if not isinstance(bounds, dict):
            raise TakeError("a long-form segment names no content output range")
        seams.append(bounds.get("lowerBound"))
    block = {"schemaVersion": LONG_FORM_SCHEMA_VERSION, "algorithmVersion": evidence.get("algorithmVersion"),
             "sampleRate": evidence.get("sampleRate"), "segmentCount": evidence.get("segmentCount"),
             "outputFrameCount": evidence.get("outputFrameCount"),
             "maximumSegmentBoundaryJump": evidence.get("maximumSegmentBoundaryJump"), "seamFrames": seams}
    if issues := long_form_issues(block):
        raise TakeError("the long-form assembly evidence is unusable: " + "; ".join(issues))
    return block


def long_form_issues(block: Any) -> list[str]:
    """Why a `longForm` block is not a long-form take's; empty when it is."""
    if not isinstance(block, dict) or set(block) != set(LONG_FORM_KEYS):
        return [f"a longForm block declares exactly {', '.join(LONG_FORM_KEYS)}"]
    issues = []
    if block["schemaVersion"] != LONG_FORM_SCHEMA_VERSION:
        issues.append(f"a longForm block is schema {LONG_FORM_SCHEMA_VERSION}")
    for key in ("algorithmVersion", "sampleRate", "segmentCount", "outputFrameCount"):
        if not _count(block[key], positive=True):
            issues.append(f"longForm {key} is a positive integer")
    if not _count(block["maximumSegmentBoundaryJump"]):
        issues.append("longForm maximumSegmentBoundaryJump is a non-negative integer")
    seams = block["seamFrames"]
    if not isinstance(seams, list) or not all(_count(frame, positive=True) for frame in seams):
        return issues + ["longForm seamFrames lists output frames"]
    if seams != sorted(set(seams)):
        issues.append("longForm seamFrames increase strictly")
    if _count(block["outputFrameCount"], positive=True) and any(frame >= block["outputFrameCount"] for frame in seams):
        issues.append("a longForm seam lies inside the output")
    if _count(block["segmentCount"], positive=True) and len(seams) != block["segmentCount"] - 1:
        issues.append("a longForm block names one seam per join (segmentCount - 1)")
    return issues


def seam_seconds(block: dict[str, Any]) -> list[float]:
    """A valid `longForm` block's seams, in seconds on the take's own timeline."""
    return [frame / block["sampleRate"] for frame in block["seamFrames"]]


def long_form_segment_issues(segments: Any, block: Mapping[str, Any] | None) -> list[str]:
    """Why a long-form take's `longFormSegments` are not its planned segments' takes; empty when they are."""
    if not isinstance(segments, list) or not segments:
        return ["a long-form take lists its segment takes"]
    issues = []
    if isinstance(block, dict) and block.get("segmentCount") != len(segments):
        issues.append("a long-form take lists one segment take per assembled segment")
    for position, segment in enumerate(segments):
        if not isinstance(segment, dict) or set(segment) != set(LONG_FORM_SEGMENT_KEYS):
            issues.append(f"a long-form segment declares exactly {', '.join(LONG_FORM_SEGMENT_KEYS)}")
            continue
        if segment["index"] != position or segment["boundary"] not in LONG_FORM_BOUNDARIES \
                or not _count(segment["intendedPauseMilliseconds"]) or not _count(segment["effectiveSeed"]) \
                or _number(segment["durationSeconds"]) is None \
                or (segment["wavSHA256"] is not None and not is_sha256(segment["wavSHA256"])):
            issues.append(f"long-form segment {position} is malformed")
        if segment["engineIntrospection"] is not None:
            issues.extend(f"segment {position}: {issue}" for issue in introspection_issues(segment["engineIntrospection"]))
    return issues


def engine_introspections(diagnostics: Path | None, wav_digests: set[str]) -> dict[str, list[dict[str, Any]]]:
    """Each WAV digest's engine introspection summaries, from the engine rows whose `samplingWAVDigest` is it.

    Rows without a summary, or with one that is not the engine's shape, are
    ignored. Each summary keeps the digest it was bound by (`wavSHA256`), so a
    clip that is not that WAV never carries it. A digest can have several rows (a resumed item re-generates it,
    the diagnostics root outlives runs); the caller binds only an agreed one.
    """
    found: dict[str, list[dict[str, Any]]] = {}
    if diagnostics is None or not wav_digests:
        return found
    for record in _jsonl(diagnostics / "engine" / "generations.jsonl"):
        notes = record.get("notes")
        digest = notes.get("samplingWAVDigest") if isinstance(notes, dict) else None
        block = record.get("engineIntrospection")
        if digest in wav_digests and not introspection_issues(block):
            summary = {key: block.get(key) for key in INTROSPECTION_NUMBERS}
            summary["seamCodecFrames"] = list(block.get("seamCodecFrames", []))
            # The WAV the generation wrote: a summary describes that audio only (a copied entry must not inherit it).
            summary["wavSHA256"] = digest
            if summary not in found.setdefault(digest, []):
                found[digest].append(summary)
    return found


def _agreed(summaries: Mapping[str, list[dict[str, Any]]], digest: Any) -> dict[str, Any] | None:
    # One summary, or several identical rows (a resumed item): bound. Rows that disagree: none.
    found = summaries.get(digest) if isinstance(digest, str) else None
    return found[0] if found and len(found) == 1 else None


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _long_form_segments(evidence: Mapping[str, Any], wav_root: Path, take_id: str) -> list[dict[str, Any]]:
    """The segment takes of a long-form project (no text, no path): each segment WAV's digest when it lies
    under the WAV root; its introspection is bound later by that digest."""
    segments = evidence.get("segments")
    if not isinstance(segments, list) or not segments:
        raise TakeError(f"{take_id}: the long-form output lists no segment takes")
    reduced = []
    for segment in segments:
        segment = segment if isinstance(segment, dict) else {}
        path = segment.get("audioPath")
        digest = None
        if isinstance(path, str):
            source = Path(path)
            source = (source if source.is_absolute() else wav_root / source).resolve()
            if _inside(source, wav_root) and source.is_file():
                digest = jsonio.sha256_file(source)
        reduced.append({"index": segment.get("index"), "boundary": segment.get("boundary"),
                        "intendedPauseMilliseconds": segment.get("intendedPauseMilliseconds"),
                        "effectiveSeed": segment.get("effectiveSeed"),
                        "durationSeconds": _number(segment.get("durationSeconds")),
                        "finishReason": segment.get("finishReason") if isinstance(segment.get("finishReason"), str)
                        else None, "wavSHA256": digest, "engineIntrospection": None})
    return reduced


def _manifest_reference(batch: Mapping[str, Any], references_dir: Path, run_dir: Path, take_id: str) -> dict[str, Any]:
    """A clone take's reference clip as the manifest records it: the copy beside the run, relative to it."""
    reference, voice = batch["reference"], batch["voice"]
    path = references_dir / f"{reference['referenceKey']}.wav"
    if not path.is_file() or jsonio.sha256_file(path) != reference["wavSHA256"]:
        raise TakeError(f"{take_id}: its clone reference copy is missing or changed (batch-files writes it)")
    return {"wavPath": os.path.relpath(path.resolve(), run_dir), "wavSHA256": reference["wavSHA256"],
            "referenceKey": reference["referenceKey"], "corpus": voice["source"], "clipID": voice["clipID"],
            "speaker": voice["speaker"], "gender": voice["gender"], "language": voice["language"],
            "durationSeconds": reference["durationSeconds"], "transcriptSHA256": reference["transcriptSHA256"]}


def build_manifest(*, plan_path: Path, batch_results: Path, wav_root: Path, output: Path,
                   copy: bool = False, diagnostics: Path | None = None,
                   references_dir: Path | None = None) -> dict[str, Any]:
    plan = validate_plan(load_json(plan_path))
    run_dir = output.resolve().parent
    wav_dir = run_dir / "wav"
    wav_dir.mkdir(parents=True, exist_ok=True)
    wav_root = wav_root.resolve()
    references_dir = (references_dir if references_dir is not None else run_dir / "references").resolve()
    takes_by_id = {take["takeID"]: take for take in plan["takes"]}
    batches_by_id = {batch["batchID"]: batch for batch in plan["batches"]}
    records: dict[str, dict[str, Any]] = {}
    bound: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for batch in plan["batches"]:
        planned = [takes_by_id[take_id] for take_id in batch["takeIDs"]]
        bound.extend(zip(planned, segmented_outcomes(batch_results, batch, planned)))
    failures = engine_failures(diagnostics, {outcome["generationID"] for _, outcome in bound
                                             if "generationID" in outcome})
    for take, outcome in bound:
        batch = batches_by_id[take["batchID"]]
        record = {field: take[field] for field in PLANNED_FIELDS}
        record.update({field: take[field] for field in PLANNED_OPTIONAL_FIELDS if field in take})
        record.update({field: None for field in OUTPUT_FIELDS})
        if batch["mode"] == "clone":
            record["reference"] = _manifest_reference(batch, references_dir, run_dir, take["takeID"])
        if outcome["status"] == "generated":
            source = Path(outcome["audioPath"])
            source = (source if source.is_absolute() else wav_root / source).resolve()
            if not _inside(source, wav_root):
                raise TakeError(f"{take['takeID']}: the batch wrote its audio outside the WAV root")
            destination = wav_dir / f"{take['takeID']}.wav"
            if source.is_file():
                if copy:
                    shutil.copyfile(source, destination)
                else:
                    shutil.move(str(source), str(destination))
            elif not destination.is_file():
                outcome = {"status": "missing", "missingReason": "output-file-missing"}
        if outcome["status"] == "generated":
            record.update(
                status="generated", wavPath=os.path.relpath(destination, run_dir),
                wavSHA256=jsonio.sha256_file(destination), durationSeconds=outcome["durationSeconds"],
                finishReason=outcome["finishReason"] if isinstance(outcome["finishReason"], str) else None,
                textBinding=outcome["textBinding"],
            )
            if batch.get("longForm"):
                evidence = outcome.get("longForm") or {}
                try:
                    record["longForm"] = long_form_block(evidence.get("assembly"))
                except TakeError as error:
                    raise TakeError(f"{take['takeID']}: {error}") from None
                # The assembler digests the file it published: its evidence describes exactly this WAV.
                if evidence["assembly"].get("outputDigest") != record["wavSHA256"]:
                    raise TakeError(f"{take['takeID']}: the long-form assembly evidence describes another WAV")
                record["longFormSegments"] = _long_form_segments(evidence, wav_root, take["takeID"])
        elif outcome.get("generationID") in failures and "errorCode" in failures[outcome["generationID"]]:
            # The engine recorded why this item failed. Its mandatory Fast QC
            # rejection is an outcome of the take, not a missing take: the
            # fielded detector flagged it, so N3 flag rates must count it.
            failure = failures[outcome["generationID"]]
            if failure["errorCode"].startswith(QC_REJECTION_CODE):
                record.update(status="rejected", rejection={
                    "errorCode": failure["errorCode"], "audioQCFlags": failure.get("audioQCFlags", [])})
            else:
                record.update(status="failed", failure={"errorCode": failure["errorCode"]})
        else:
            record.update(status="missing", missingReason=outcome["missingReason"])
        records[take["takeID"]] = record
    takes = [records[take["takeID"]] for take in plan["takes"]]
    if diagnostics is not None:
        generated = [take for take in takes if take["status"] == "generated"]
        digests = {take["wavSHA256"] for take in generated}
        digests |= {segment["wavSHA256"] for take in generated for segment in take["longFormSegments"] or ()
                    if segment["wavSHA256"]}
        summaries = engine_introspections(diagnostics, digests)
        for take in generated:
            if take.get("cell") == LONG_FORM:
                # The joined WAV has no engine row of its own: each segment's take has one.
                for segment in take["longFormSegments"] or ():
                    segment["engineIntrospection"] = _agreed(summaries, segment["wavSHA256"])
            else:
                take["engineIntrospection"] = _agreed(summaries, take["wavSHA256"])
    manifest: dict[str, Any] = {
        "schemaVersion": 1, "kind": MANIFEST_KIND, "runID": plan["runID"], "planDigest": plan["planDigest"],
        "poolDigest": plan["poolDigest"], "policyDigest": plan["policyDigest"], "split": plan["split"],
        "counts": status_counts(takes),
        "takes": takes,
    }
    if "cells" in plan:
        manifest["cells"] = cell_counts(takes, plan["cells"])
    if diagnostics is not None:
        manifest["introspection"] = introspection_counts(takes)
    manifest["manifestDigest"] = self_digest(manifest, "manifestDigest")
    jsonio.atomic_json(output, manifest, ascii=False, allow_nan=False)
    return manifest


# --------------------------------------------------------------------------- #
# Engine diagnostics collection
# --------------------------------------------------------------------------- #

def _reduced_generation(value: Mapping[str, Any]) -> dict[str, Any] | None:
    """An engine telemetry row reduced to what the manifest binds: its generation id, the WAV digest and Fast
    QC flag names of its notes, and its introspection summary. No message, text or path survives.

    The class I positives (`audio_qc_introspection_positives.py`) also read the codec trace a take recorded
    (`vocello batch --capture-codec-trace`: its digest, frame count and completeness), the speech tokenizer
    that generated it, and a controlled generation's EOS hold (its `timingsMS`)."""
    generation_id = value.get("generationID")
    if not isinstance(generation_id, str) or not GENERATION_ID.fullmatch(generation_id):
        return None
    row: dict[str, Any] = {"generationID": generation_id.upper()}
    notes = value.get("notes") if isinstance(value.get("notes"), dict) else {}
    kept: dict[str, Any] = {}
    if is_sha256(notes.get("samplingWAVDigest")):
        kept["samplingWAVDigest"] = notes["samplingWAVDigest"]
    flags = notes.get("audioQCFlags")
    if isinstance(flags, str) and flags and all(QC_FLAG.fullmatch(flag) for flag in flags.split(",")):
        kept["audioQCFlags"] = flags
    if is_sha256(notes.get("codecTraceSHA256")):
        kept["codecTraceSHA256"] = notes["codecTraceSHA256"]
        for key, pattern in TRACE_NOTES.items():
            if isinstance(notes.get(key), str) and pattern.fullmatch(notes[key]):
                kept[key] = notes[key]
    if kept:
        row["notes"] = kept
    block = value.get("engineIntrospection")
    if isinstance(block, dict) and not introspection_issues(block):
        row["engineIntrospection"] = block
    timings = value.get("timingsMS") if isinstance(value.get("timingsMS"), dict) else {}
    held = {key: timings[key] for key in EOS_HOLD_TIMINGS if _count(timings.get(key))}
    if held:
        row["timingsMS"] = held
    identity = value.get("modelRuntimeIdentity") if isinstance(value.get("modelRuntimeIdentity"), dict) else {}
    tokenizer = identity.get("speechTokenizerDigest")
    if isinstance(tokenizer, str) and TOKENIZER_DIGEST.fullmatch(tokenizer):
        row["speechTokenizerDigest"] = tokenizer
    return row


def _reduced_failure(value: Mapping[str, Any]) -> dict[str, Any] | None:
    generation_id, code = value.get("generationID"), value.get("errorCode")
    if not isinstance(generation_id, str) or not GENERATION_ID.fullmatch(generation_id) \
            or not isinstance(code, str) or not ENGINE_CODE.fullmatch(code):
        return None
    return {"generationID": generation_id.upper(), "errorCode": code}


def collect_diagnostics(source: Path, destination: Path, *, baseline: bool = False) -> dict[str, int]:
    """Copy the engine rows written since the last collection into the run's own diagnostics root.

    The engine front-trims its capped logs, so a long lane loses its early rows
    unless it keeps them: the lane collects after every batch segment. Each
    source line is taken once, by the SHA-256 of its bytes; `baseline` marks the
    lines already present as taken without copying them, so a run holds only
    its own rows. Rows are reduced (`_reduced_generation`, `_reduced_failure`)
    to the shape `engine_failures` and `engine_introspections` read, so the
    manifest binds against the run's root exactly as against the engine's.
    """
    engine_in, engine_out = source / "engine", destination / "engine"
    engine_out.mkdir(parents=True, exist_ok=True)
    seen_path = destination / COLLECTED_LINES
    try:
        seen = set(seen_path.read_text(encoding="utf-8").split())
    except FileNotFoundError:
        seen = set()
    counts = {"rows": 0, "failures": 0, "skipped": 0}
    taken: list[str] = []
    reducers = {"generations.jsonl": (_reduced_generation, "rows"),
                "generation-failures.jsonl": (_reduced_failure, "failures")}
    for name in ENGINE_LOGS:
        reducer, counter = reducers[name]
        try:
            handle = (engine_in / name).open("rb")
        except FileNotFoundError:
            continue
        with handle, (engine_out / name).open("a", encoding="utf-8") as out:
            for raw in handle:
                if not raw.endswith(b"\n"):
                    continue  # an unfinished last line: the next collection takes it whole
                key = hashlib.sha256(name.encode("utf-8") + b"\0" + raw).hexdigest()
                if key in seen:
                    continue
                seen.add(key)
                taken.append(key)
                if baseline:
                    continue
                try:
                    value = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    counts["skipped"] += 1
                    continue
                reduced = reducer(value) if isinstance(value, dict) else None
                if reduced is None:
                    counts["skipped"] += 1
                    continue
                out.write(json.dumps(reduced, sort_keys=True, ensure_ascii=False) + "\n")
                counts[counter] += 1
    with seen_path.open("a", encoding="utf-8") as out:
        out.writelines(key + "\n" for key in taken)
    counts["baseline" if baseline else "taken"] = len(taken)
    return counts


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def status_counts(takes: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts = {"planned": len(takes)}
    for status in TAKE_STATUSES:
        counts[status] = sum(1 for take in takes if isinstance(take, dict) and take.get("status") == status)
    return counts


def cell_counts(takes: Sequence[dict[str, Any]], cells: Sequence[str]) -> dict[str, dict[str, int]]:
    return {cell: status_counts([take for take in takes if isinstance(take, dict)
                                 and take.get("cell", STANDARD) == cell]) for cell in cells}


def introspection_counts(takes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Generated takes with and without a bound engine introspection summary; a long-form take's segments
    apart (its joined WAV has no engine row)."""
    generated = [take for take in takes if isinstance(take, dict) and take.get("status") == "generated"]
    single = [take for take in generated if take.get("cell") != LONG_FORM]
    bound = sum(1 for take in single if take.get("engineIntrospection") is not None)
    counts: dict[str, Any] = {"bound": bound, "unbound": len(single) - bound}
    segments = [segment for take in generated if take.get("cell") == LONG_FORM
                for segment in take.get("longFormSegments") or () if isinstance(segment, dict)]
    if len(single) != len(generated):
        segment_bound = sum(1 for segment in segments if segment.get("engineIntrospection") is not None)
        counts["longFormSegments"] = {"bound": segment_bound, "unbound": len(segments) - segment_bound}
    return counts


def manifest_digest_issues(manifest: Any) -> list[str]:
    """The manifest's own structure and self digest, without its plan or audio."""
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1 or manifest.get("kind") != MANIFEST_KIND:
        return [f"the manifest is not {MANIFEST_KIND} schema 1"]
    if manifest.get("manifestDigest") != self_digest(manifest, "manifestDigest"):
        return ["the manifest digest does not match its content"]
    return []


def _reference_issues(take: Mapping[str, Any], batch: Mapping[str, Any], root: Path) -> list[str]:
    """Why a clone take's recorded reference is not its planned clip's copy beside the manifest."""
    reference = take.get("reference")
    if not isinstance(reference, dict) or set(reference) != set(REFERENCE_KEYS):
        return [f"a clone take records its reference ({', '.join(REFERENCE_KEYS)})"]
    planned, voice = batch["reference"], batch["voice"]
    expected = {"wavSHA256": planned["wavSHA256"], "referenceKey": planned["referenceKey"],
                "corpus": voice["source"], "clipID": voice["clipID"], "speaker": voice["speaker"],
                "gender": voice["gender"], "language": voice["language"],
                "durationSeconds": planned["durationSeconds"], "transcriptSHA256": planned["transcriptSHA256"]}
    if any(reference.get(key) != value for key, value in expected.items()):
        return ["the recorded reference is not the planned clip"]
    if not _relative_posix(reference["wavPath"]):
        return ["the reference path must be relative to the manifest"]
    path = (root / reference["wavPath"]).resolve()
    if not _inside(path, root) or not path.is_file() or jsonio.sha256_file(path) != reference["wavSHA256"]:
        return ["the reference copy is missing or its bytes changed"]
    return []


def validate_manifest(manifest: Any, plan: Any, *, manifest_dir: Path) -> dict[str, Any]:
    errors = manifest_digest_issues(manifest)
    if errors:
        return {"status": "FAIL", "errors": errors}
    try:
        plan = validate_plan(plan)
    except TakeError as error:
        return {"status": "FAIL", "errors": [f"plan: {error}"]}
    for key in ("runID", "planDigest", "poolDigest", "policyDigest", "split"):
        if manifest.get(key) != plan.get(key):
            errors.append(f"the manifest's {key} does not match the plan")
    takes = manifest.get("takes")
    if not isinstance(takes, list):
        return {"status": "FAIL", "errors": errors + ["the manifest has no takes"]}
    planned_ids = [take["takeID"] for take in plan["takes"]]
    if [take.get("takeID") if isinstance(take, dict) else None for take in takes] != planned_ids:
        errors.append("the manifest's takes are not exactly the plan's takes in plan order")
        return {"status": "FAIL", "errors": errors}
    batches = {batch["batchID"]: batch for batch in plan["batches"]}
    root = manifest_dir.resolve()
    generated, digests = 0, []
    for take, planned in zip(takes, plan["takes"]):
        take_id = planned["takeID"]
        batch = batches[planned["batchID"]]
        if any(take.get(field) != planned[field] for field in PLANNED_FIELDS) \
                or any(take.get(field) != planned.get(field) for field in PLANNED_OPTIONAL_FIELDS):
            errors.append(f"{take_id}: the take differs from its planned take")
        if batch["mode"] == "clone":
            errors.extend(f"{take_id}: {issue}" for issue in _reference_issues(take, batch, root))
        elif take.get("reference") is not None:
            errors.append(f"{take_id}: only a clone take records a reference")
        if take.get("status") == "generated":
            generated += 1
            wav_path = take.get("wavPath")
            if not isinstance(wav_path, str) or Path(wav_path).is_absolute() or ".." in Path(wav_path).parts:
                errors.append(f"{take_id}: the WAV path must be relative to the manifest")
                continue
            path = (root / wav_path).resolve()
            if not _inside(path, root) or not path.is_file():
                errors.append(f"{take_id}: the WAV is missing")
            elif jsonio.sha256_file(path) != take.get("wavSHA256"):
                errors.append(f"{take_id}: the WAV bytes do not match their digest")
            else:
                digests.append(take["wavSHA256"])
            if _number(take.get("durationSeconds")) is None or take.get("textBinding") not in ("text", "index"):
                errors.append(f"{take_id}: invalid duration or text binding")
            if take.get("engineIntrospection") is not None:
                errors.extend(f"{take_id}: {issue}" for issue in introspection_issues(take["engineIntrospection"]))
            if batch.get("longForm"):
                if take.get("longForm") is None or take.get("engineIntrospection") is not None:
                    errors.append(f"{take_id}: a generated long-form take carries its longForm block, and its "
                                  "introspection per segment")
                else:
                    errors.extend(f"{take_id}: {issue}" for issue in long_form_issues(take["longForm"]))
                    errors.extend(f"{take_id}: {issue}"
                                  for issue in long_form_segment_issues(take.get("longFormSegments"), take["longForm"]))
            elif take.get("longForm") is not None:
                # A version 1 plan has no long-form batch; its takes validate their block all the same.
                errors.extend(f"{take_id}: {issue}" for issue in long_form_issues(take["longForm"]))
            if not batch.get("longForm") and take.get("longFormSegments") is not None:
                errors.append(f"{take_id}: only a long-form take lists segment takes")
        elif take.get("status") in ("missing", "rejected", "failed"):
            if any(take.get(field) is not None for field in ("wavPath", "wavSHA256", "durationSeconds",
                                                              "engineIntrospection", "longForm",
                                                              "longFormSegments")):
                errors.append(f"{take_id}: a take without output names no output")
            status = take["status"]
            if status == "missing" and not isinstance(take.get("missingReason"), str):
                errors.append(f"{take_id}: a missing take names its reason")
            rejection = take.get("rejection")
            if status == "rejected" and not (
                    isinstance(rejection, dict) and isinstance(rejection.get("errorCode"), str)
                    and rejection["errorCode"].startswith(QC_REJECTION_CODE)
                    and isinstance(rejection.get("audioQCFlags"), list)
                    and all(isinstance(flag, str) and QC_FLAG.fullmatch(flag) for flag in rejection["audioQCFlags"])):
                errors.append(f"{take_id}: a rejected take names the engine's QC rejection and its flags")
            failure = take.get("failure")
            if status == "failed" and not (isinstance(failure, dict) and isinstance(failure.get("errorCode"), str)
                                           and ENGINE_CODE.fullmatch(failure["errorCode"])):
                errors.append(f"{take_id}: a failed take names the engine's failure code")
        else:
            errors.append(f"{take_id}: unknown status {take.get('status')!r}")
    counts = status_counts(takes)
    if manifest.get("counts") != counts:
        errors.append("the manifest's counts do not match its takes")
    if "cells" in plan and manifest.get("cells") != cell_counts(takes, plan["cells"]):
        errors.append("the manifest's cell counts do not match its takes")
    if "introspection" in manifest and manifest["introspection"] != introspection_counts(takes):
        errors.append("the manifest's introspection counts do not match its takes")
    duplicates = len(digests) - len(set(digests))
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "counts": counts,
            "duplicateWavDigests": duplicates}


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    policy_command = commands.add_parser("validate-policy", help="check the committed take policy")
    policy_command.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    plan = commands.add_parser("plan", help="write an immutable take plan")
    plan.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    plan.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    plan.add_argument("--split", choices=SPLITS, required=True)
    plan.add_argument("--languages", nargs="+", metavar="LANGUAGE",
                      help="canonical language ids, space or comma separated (default: every pool language)")
    plan.add_argument("--cells", nargs="+", metavar="CELL",
                      help=f"cells ({', '.join(CELLS)}), space or comma separated (default: the policy's "
                           "defaultCells); long-form is planned alone")
    plan.add_argument("--corpora-root", type=Path,
                      help="the extracted speaker corpora (default: audio_qc_corpora.py's cache root); clone only")
    plan.add_argument("--run-id", required=True)
    plan.add_argument("--output", type=Path, required=True)
    files = commands.add_parser("batch-files", help="write one line file per batch")
    files.add_argument("--plan", type=Path, required=True)
    files.add_argument("--out-dir", type=Path, required=True)
    files.add_argument("--references-dir", type=Path,
                       help="where each clone reference is copied (default: <out-dir>/../references)")
    files.add_argument("--corpora-root", type=Path, help="the extracted speaker corpora (clone batches)")
    collect = commands.add_parser("collect-diagnostics",
                                  help="copy the engine rows written since the last collection into the run")
    collect.add_argument("--diagnostics", type=Path, required=True, help="the engine diagnostics root")
    collect.add_argument("--into", type=Path, required=True, help="the run's own diagnostics root")
    collect.add_argument("--baseline", action="store_true",
                         help="mark the rows already present as taken, without copying them")
    manifest = commands.add_parser("manifest", help="bind the batch outputs to the plan")
    manifest.add_argument("--plan", type=Path, required=True)
    manifest.add_argument("--batch-results", type=Path, required=True,
                          help="the directory of <batchID>.json batch stdouts")
    manifest.add_argument("--wav-root", type=Path, required=True,
                          help="the directory every batch output WAV must lie under")
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument("--copy", action="store_true", help="copy the WAVs instead of moving them")
    manifest.add_argument("--diagnostics", type=Path,
                          help="the engine diagnostics root (or the run's collected one); binds each failed item "
                               "to its recorded failure code and each WAV to its introspection summary")
    manifest.add_argument("--references-dir", type=Path,
                          help="the clone reference copies (default: references/ beside the manifest)")
    resume = commands.add_parser("next-offset", help="where a stopped batch resumes (an offset, done or stop)")
    resume.add_argument("--result", type=Path, required=True)
    resume.add_argument("--offset", type=int, required=True)
    resume.add_argument("--count", type=int, required=True)
    validate = commands.add_parser("validate-manifest", help="recompute digests and check the plan binding")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-policy":
            load_policy(args.policy)
            print(json.dumps({"status": "PASS", "policy": args.policy.name}))
            return 0
        if args.command == "plan":
            value = build_plan(pool_path=args.pool, policy_path=args.policy, split=args.split,
                               run_id=args.run_id, languages=args.languages, cells=args.cells,
                               corpora_root=args.corpora_root)
            if value["expectedTakeCount"] is not None and value["takeCount"] != value["expectedTakeCount"]:
                print(f"audio-qc-calibration-takes: note: {value['takeCount']} takes planned, "
                      f"the policy expects {value['expectedTakeCount']}", file=sys.stderr)
            jsonio.atomic_json(args.output, value, ascii=False, allow_nan=False)
            print(json.dumps({key: value[key] for key in (
                "runID", "split", "languages", "cells", "takeCount", "batchCount", "expectedTakeCount",
                "planDigest")}))
            return 0
        if args.command == "batch-files":
            rows = write_batch_files(load_json(args.plan), args.out_dir, references_dir=args.references_dir,
                                     corpora_root=args.corpora_root)
            for row in rows:
                print(batch_row_line(row))
            return 0
        if args.command == "collect-diagnostics":
            print(json.dumps(collect_diagnostics(args.diagnostics, args.into, baseline=args.baseline)))
            return 0
        if args.command == "manifest":
            value = build_manifest(plan_path=args.plan, batch_results=args.batch_results, wav_root=args.wav_root,
                                   output=args.output, copy=args.copy, diagnostics=args.diagnostics,
                                   references_dir=args.references_dir)
            print(json.dumps(value["counts"]))
            return 0
        if args.command == "next-offset":
            print(next_segment_offset(args.result, args.offset, args.count))
            return 0
        report = validate_manifest(load_json(args.manifest), load_json(args.plan), manifest_dir=args.manifest.parent)
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "PASS" else 1
    except (TakeError, OSError) as error:
        print(f"audio-qc-calibration-takes: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
