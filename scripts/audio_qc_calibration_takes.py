#!/usr/bin/env python3
"""The AQ-07 natural calibration takes (population N3): plan, batch files, binding, validation.

Population N3 of the audio QC audit (section 5.1) is natural Vocello takes over
the committed CC0 script pool (`config/audio-qc-script-pool.json`). The unit of
independence is the family, one script x voice x seed. The committed take
policy (`config/audio-qc-calibration-takes.json`) names each language's three
voices per split (two Built-in speakers, male and female, and one Voice Design
brief), the seed rule and the donor subset. This module is offline and
device-free; `scripts/macos_test.sh qc-takes` runs the generator between its
steps.

Commands:
  validate-policy     check the committed take policy against the speaker contract
  plan                write an immutable take plan for one split of the pool
  batch-files         write one line file per batch for `vocello batch --file`,
                      and print one unit-separated row per batch for the lane
  manifest            bind every batch's `vocello batch --json` output to the
                      plan by item index, move each WAV to wav/<takeID>.wav and
                      write the takes manifest (a planned take without output
                      is recorded as missing, never dropped)
  validate-manifest   recompute the digests and check the manifest's plan binding

Seeds: `vocello batch --seed` applies one seed to every item of a batch, so a
seed belongs to one (split, language, mode, voice) batch, derived like the
seed identity of `language_bench_evidence.py` (the first 8 bytes of a SHA-256,
masked to 63 bits). Each script is spoken once per voice, so a family is still
script x voice x seed.

Everything this module writes (plans, line files, WAVs, manifests) is an
untracked build artifact. A manifest records WAV paths relative to itself,
never an absolute local path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Iterable, Sequence
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
SPEAKER_CONTRACT = REPO / "Sources" / "Resources" / "qwenvoice_contract.json"

POOL_KIND = "audio-qc-script-pool"
POLICY_KIND = "audio-qc-calibration-takes-policy"
PLAN_KIND = "audio-qc-calibration-take-plan"
MANIFEST_KIND = "audio-qc-calibration-takes"
SPLITS = ("calibration", "confirmation")
ROLES = ("primary", "donor")
SEED_IDENTITY = "audio-qc-calibration-seed-v1"
DONOR_IDENTITY = "audio-qc-calibration-donor-v1"
GENDERS = frozenset({"male", "female"})
UINT63_MASK = (1 << 63) - 1
MAX_BRIEF_CHARACTERS = 240

SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}\Z")
SCRIPT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
SPEAKER_ID = re.compile(r"[a-z][a-z0-9_]{1,31}\Z")
BRIEF_ID = re.compile(r"[a-z][a-z0-9-]{1,31}\Z")
# The unit separator delimits the lane's per-batch rows; every character Swift
# counts as a newline would split one planned text into two batch items.
FIELD_SEPARATOR = "\x1f"
LINE_BREAKS = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e\x85  ")

# The fields a manifest take copies from its planned take, unchanged.
PLANNED_FIELDS = (
    "takeID", "family", "scriptID", "language", "role", "mode", "variant", "variation", "voice", "seed",
    "batchID", "text", "textSHA256",
)
OUTPUT_FIELDS = ("wavPath", "wavSHA256", "durationSeconds", "finishReason", "status", "missingReason", "textBinding",
                 "rejection", "failure")
TAKE_STATUSES = ("generated", "rejected", "failed", "missing")
# A resumed batch segment's stdout: `<batchID>@<offset>.json` (offset 0 is `<batchID>.json`).
GENERATION_ID = re.compile(r"^[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")
SEGMENT_FILE = re.compile(r"^(?P<batch>.+)@(?P<offset>[1-9][0-9]{0,5})\.json$")
QC_REJECTION_CODE = "audio.quality_rejected"
ENGINE_CODE = re.compile(r"^[a-z0-9_.]{1,96}$")
QC_FLAG = re.compile(r"^[a-z0-9_:(),.-]{1,96}$")


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


def policy_issues(policy: Any, *, speakers: set[str]) -> list[str]:
    if not isinstance(policy, dict):
        return ["the policy must be an object"]
    issues: list[str] = []
    if policy.get("schemaVersion") != 1 or policy.get("kind") != POLICY_KIND:
        issues.append(f"the policy is not {POLICY_KIND} schema 1")
    version = policy.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        issues.append("the policy version must be a positive integer")
    generation = policy.get("generation") if isinstance(policy.get("generation"), dict) else {}
    expected_generation = {"customMode": "custom", "designMode": "design", "variant": "speed",
                           "variation": "expressive"}
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
    donors = assignment.get("donorScriptsPerLanguage")
    if isinstance(donors, bool) or not isinstance(donors, int) or donors < 0:
        issues.append("assignment.donorScriptsPerLanguage must be a non-negative integer")

    genders = policy.get("speakerGenders")
    if not isinstance(genders, dict) or any(value not in GENDERS for value in genders.values()):
        issues.append("speakerGenders must map speakers to male or female")
        genders = {}
    briefs = policy.get("designBriefs")
    if not isinstance(briefs, dict) or not briefs:
        issues.append("designBriefs must name at least one brief")
        briefs = {}
    for brief_id, brief in briefs.items():
        text = brief.get("text") if isinstance(brief, dict) else None
        if not BRIEF_ID.fullmatch(str(brief_id)):
            issues.append(f"design brief id {brief_id!r} is unsafe")
        if text_issues(text) or len(text) > MAX_BRIEF_CHARACTERS:
            issues.append(f"design brief {brief_id!r} must be one trimmed line of at most {MAX_BRIEF_CHARACTERS} characters")

    splits = policy.get("splits")
    split_briefs: dict[str, str] = {}
    if not isinstance(splits, dict) or set(splits) != set(SPLITS):
        issues.append(f"splits must declare exactly {', '.join(SPLITS)}")
    else:
        for split in SPLITS:
            entry = splits[split] if isinstance(splits[split], dict) else {}
            brief_id = entry.get("designBrief")
            if brief_id not in briefs:
                issues.append(f"split {split} names an unknown design brief")
            else:
                split_briefs[split] = brief_id
            expected = entry.get("expectedTakeCount")
            if expected is not None and (isinstance(expected, bool) or not isinstance(expected, int) or expected < 1):
                issues.append(f"split {split} has an invalid expectedTakeCount")
        if len(split_briefs) == len(SPLITS) and len(set(split_briefs.values())) != len(SPLITS):
            issues.append("the splits must use different design briefs (disjoint by speaker)")

    languages = policy.get("languages")
    if not isinstance(languages, list) or not languages:
        issues.append("languages must be a non-empty list")
        languages = []
    seen: set[str] = set()
    for entry in languages:
        language = entry.get("language") if isinstance(entry, dict) else None
        if language not in LANGUAGE_LOCALE_CODES or language in seen:
            issues.append(f"language {language!r} is unknown or repeated")
            continue
        seen.add(language)
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
            if {genders.get(speaker) for speaker in pair} != GENDERS:
                issues.append(f"{language}: {split} must pair a male and a female speaker")
            voices[split] = pair
        if len(voices) == len(SPLITS) and set(voices["calibration"]) & set(voices["confirmation"]):
            issues.append(f"{language}: the splits must not share a Built-in speaker")
    return issues


def load_policy(path: Path) -> dict[str, Any]:
    policy = load_json(path)
    issues = policy_issues(policy, speakers=contract_speakers())
    if issues:
        raise TakeError("the take policy is invalid: " + "; ".join(issues))
    return policy


def voice_key(voice: dict[str, Any]) -> str:
    return voice["id"] if voice["kind"] == "builtin" else f"design-{voice['briefID']}"


def voice_mode(voice: dict[str, Any]) -> str:
    return "custom" if voice["kind"] == "builtin" else "design"


def policy_voices(policy: dict[str, Any], language: str, split: str) -> list[dict[str, Any]]:
    """The language's voices for a split in rotation order: Built-in, Built-in, Voice Design."""
    entry = next(item for item in policy["languages"] if item["language"] == language)
    brief_id = policy["splits"][split]["designBrief"]
    return [{"kind": "builtin", "id": speaker} for speaker in entry[split]] + [
        {"kind": "design", "briefID": brief_id, "brief": policy["designBriefs"][brief_id]["text"]}
    ]


def batch_seed(policy: dict[str, Any], split: str, language: str, mode: str, key: str) -> int:
    identity = f"{SEED_IDENTITY}|{policy['seedRule']['generation']}|{split}|{language}|{mode}|{key}"
    return int.from_bytes(hashlib.sha256(identity.encode("utf-8")).digest()[:8], "big") & UINT63_MASK


def donor_rank(split: str, language: str, script_id: str) -> str:
    return hashlib.sha256(f"{DONOR_IDENTITY}|{split}|{language}|{script_id}".encode("utf-8")).hexdigest()


def select_donors(split: str, language: str, primaries: Sequence[tuple[str, int]], voice_count: int,
                  count: int) -> set[str]:
    """Round-robin over the primary-voice groups, each ranked by its donor hash."""
    groups = [sorted((script_id for script_id, index in primaries if index == voice),
                     key=lambda script_id: donor_rank(split, language, script_id))
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


def _requested_languages(values: Sequence[str] | None) -> list[str]:
    requested: list[str] = []
    for value in values or ():
        for item in value.split(","):
            item = item.strip()
            if item and item not in requested:
                requested.append(item)
    return requested


def build_plan(*, pool_path: Path, policy_path: Path, split: str, run_id: str,
               languages: Sequence[str] | None = None) -> dict[str, Any]:
    if split not in SPLITS:
        raise TakeError(f"unknown split {split!r}")
    if not SAFE_RUN_ID.fullmatch(run_id):
        raise TakeError("the run id contains unsafe characters or is too long")
    policy = load_policy(policy_path)
    pool, by_language = load_pool(pool_path)
    policy_languages = [entry["language"] for entry in policy["languages"]]
    requested = _requested_languages(languages)
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

    donor_count = policy["assignment"]["donorScriptsPerLanguage"]
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
        voices = policy_voices(policy, language, split)
        primaries = [(script["id"], index % len(voices)) for index, script in enumerate(scripts)]
        donors = select_donors(split, language, primaries, len(voices), donor_count)
        assigned: list[list[tuple[dict[str, Any], str]]] = [[] for _ in voices]
        for script, (_, primary) in zip(scripts, primaries):
            assigned[primary].append((script, "primary"))
            if script["id"] in donors:
                assigned[(primary + 1) % len(voices)].append((script, "donor"))
        for voice, members in zip(voices, assigned):
            if not members:
                continue
            key, mode = voice_key(voice), voice_mode(voice)
            seed = batch_seed(policy, split, language, mode, key)
            batch_id = f"{split}-{language}-{key}"
            take_ids = []
            for script, role in sorted(members, key=lambda member: member[0]["id"]):
                take_id = f"{script['id']}--{key}"
                take_ids.append(take_id)
                takes.append({
                    "takeID": take_id, "family": f"{script['id']}:{key}:{seed}", "scriptID": script["id"],
                    "language": language, "role": role, "mode": mode, "variant": "speed",
                    "variation": "expressive", "voice": dict(voice), "seed": seed, "batchID": batch_id,
                    "text": script["text"], "textSHA256": script["textSHA256"],
                })
            batches.append({
                "batchID": batch_id, "language": language, "mode": mode, "variant": "speed",
                "variation": "expressive", "voice": dict(voice), "seed": seed, "takeIDs": take_ids,
            })

    split_policy = policy["splits"][split]
    expected = split_policy.get("expectedTakeCount") if selected == policy_languages else None
    plan: dict[str, Any] = {
        "schemaVersion": 1, "kind": PLAN_KIND, "runID": run_id, "split": split, "languages": selected,
        "poolDigest": pool["poolDigest"], "poolVersion": pool.get("version"),
        "poolFileSHA256": jsonio.sha256_file(pool_path), "policyDigest": jsonio.sha256_file(policy_path),
        "policyVersion": policy["version"], "seedPolicy": policy["seedRule"]["policy"],
        "seedGeneration": policy["seedRule"]["generation"], "variant": "speed", "variation": "expressive",
        "expectedTakeCount": expected, "takeCount": len(takes), "batchCount": len(batches),
        "takes": takes, "batches": batches,
    }
    plan["planDigest"] = self_digest(plan, "planDigest")
    return plan


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
    by_id: dict[str, dict[str, Any]] = {}
    for take in takes:
        take_id = take.get("takeID") if isinstance(take, dict) else None
        if not isinstance(take_id, str) or not SAFE_RUN_ID.fullmatch(take_id) or take_id in by_id:
            raise TakeError(f"the plan has an unsafe or repeated take id: {take_id!r}")
        by_id[take_id] = take
        if text_issues(take.get("text")) or take.get("textSHA256") != text_sha256(take["text"]):
            raise TakeError(f"{take_id}: the planned text is invalid or unbound")
        if take.get("role") not in ROLES or take.get("mode") not in ("custom", "design"):
            raise TakeError(f"{take_id}: invalid role or mode")
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
        for take_id in members:
            take = by_id.get(take_id)
            if take is None or any(take.get(key) != batch.get(key) for key in (
                    "language", "mode", "variant", "variation", "voice", "seed")) or take.get("batchID") != batch_id:
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

def write_batch_files(plan: dict[str, Any], out_dir: Path) -> list[dict[str, Any]]:
    """One line file per batch, one text per line in plan order."""
    plan = validate_plan(plan)
    takes = {take["takeID"]: take for take in plan["takes"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for batch in plan["batches"]:
        path = out_dir / f"{batch['batchID']}.txt"
        lines = [takes[take_id]["text"] for take_id in batch["takeIDs"]]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        voice = batch["voice"]
        rows.append({
            "batchID": batch["batchID"], "mode": batch["mode"], "variant": batch["variant"],
            "variation": batch["variation"], "seed": batch["seed"],
            "speaker": voice["id"] if voice["kind"] == "builtin" else "",
            "brief": voice["brief"] if voice["kind"] == "design" else "",
            "count": len(lines), "file": path,
        })
    return rows


def batch_row_line(row: dict[str, Any]) -> str:
    fields = [row["batchID"], row["mode"], row["variant"], row["variation"], str(row["seed"]),
              row["speaker"], row["brief"], str(row["count"]), str(row["file"])]
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


def batch_outcomes(result_path: Path, batch: dict[str, Any], planned: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each planned item's outcome, positionally by item index.

    Returns one dict per planned take: {"status": "generated", "audioPath",
    "durationSeconds", "finishReason", "textBinding"} or {"status": "missing",
    "missingReason"}. A structurally foreign output (another mode or variant,
    another item count, a changed text) raises: it cannot be bound at all.
    """
    payload = _parse_batch_stdout(result_path)
    if payload is None:
        return [{"status": "missing", "missingReason": "no-batch-output"} for _ in planned]
    if not isinstance(payload, dict):
        return [{"status": "missing", "missingReason": "batch-output-unparseable"} for _ in planned]
    batch_id = batch["batchID"]
    if payload.get("mode") != batch["mode"] or payload.get("variant") != batch["variant"]:
        raise TakeError(f"{batch_id}: the batch output's mode or variant differs from the plan")
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
                outcomes.append({"status": "generated", "audioPath": row["audioPath"], "durationSeconds": duration,
                                 "finishReason": row.get("finishReason"), "textBinding": "index"})
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
        outcomes.append({"status": "generated", "audioPath": item["audioPath"], "durationSeconds": duration,
                         "finishReason": item.get("finishReason"), "textBinding": "text"})
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


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def build_manifest(*, plan_path: Path, batch_results: Path, wav_root: Path, output: Path,
                   copy: bool = False, diagnostics: Path | None = None) -> dict[str, Any]:
    plan = validate_plan(load_json(plan_path))
    run_dir = output.resolve().parent
    wav_dir = run_dir / "wav"
    wav_dir.mkdir(parents=True, exist_ok=True)
    wav_root = wav_root.resolve()
    takes_by_id = {take["takeID"]: take for take in plan["takes"]}
    records: dict[str, dict[str, Any]] = {}
    bound: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for batch in plan["batches"]:
        planned = [takes_by_id[take_id] for take_id in batch["takeIDs"]]
        bound.extend(zip(planned, segmented_outcomes(batch_results, batch, planned)))
    failures = engine_failures(diagnostics, {outcome["generationID"] for _, outcome in bound
                                             if "generationID" in outcome})
    for take, outcome in bound:
        record = {field: take[field] for field in PLANNED_FIELDS}
        record.update({field: None for field in OUTPUT_FIELDS})
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
    manifest: dict[str, Any] = {
        "schemaVersion": 1, "kind": MANIFEST_KIND, "runID": plan["runID"], "planDigest": plan["planDigest"],
        "poolDigest": plan["poolDigest"], "policyDigest": plan["policyDigest"], "split": plan["split"],
        "counts": status_counts(takes),
        "takes": takes,
    }
    manifest["manifestDigest"] = self_digest(manifest, "manifestDigest")
    jsonio.atomic_json(output, manifest, ascii=False, allow_nan=False)
    return manifest


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def status_counts(takes: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts = {"planned": len(takes)}
    for status in TAKE_STATUSES:
        counts[status] = sum(1 for take in takes if isinstance(take, dict) and take.get("status") == status)
    return counts


def manifest_digest_issues(manifest: Any) -> list[str]:
    """The manifest's own structure and self digest, without its plan or audio."""
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1 or manifest.get("kind") != MANIFEST_KIND:
        return [f"the manifest is not {MANIFEST_KIND} schema 1"]
    if manifest.get("manifestDigest") != self_digest(manifest, "manifestDigest"):
        return ["the manifest digest does not match its content"]
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
    root = manifest_dir.resolve()
    generated, digests = 0, []
    for take, planned in zip(takes, plan["takes"]):
        take_id = planned["takeID"]
        if any(take.get(field) != planned[field] for field in PLANNED_FIELDS):
            errors.append(f"{take_id}: the take differs from its planned take")
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
        elif take.get("status") in ("missing", "rejected", "failed"):
            if any(take.get(field) is not None for field in ("wavPath", "wavSHA256", "durationSeconds")):
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
    plan.add_argument("--run-id", required=True)
    plan.add_argument("--output", type=Path, required=True)
    files = commands.add_parser("batch-files", help="write one line file per batch")
    files.add_argument("--plan", type=Path, required=True)
    files.add_argument("--out-dir", type=Path, required=True)
    manifest = commands.add_parser("manifest", help="bind the batch outputs to the plan")
    manifest.add_argument("--plan", type=Path, required=True)
    manifest.add_argument("--batch-results", type=Path, required=True,
                          help="the directory of <batchID>.json batch stdouts")
    manifest.add_argument("--wav-root", type=Path, required=True,
                          help="the directory every batch output WAV must lie under")
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument("--copy", action="store_true", help="copy the WAVs instead of moving them")
    manifest.add_argument("--diagnostics", type=Path,
                          help="the engine diagnostics root; binds each failed item to its recorded failure code")
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
                               run_id=args.run_id, languages=args.languages)
            if value["expectedTakeCount"] is not None and value["takeCount"] != value["expectedTakeCount"]:
                print(f"audio-qc-calibration-takes: note: {value['takeCount']} takes planned, "
                      f"the policy expects {value['expectedTakeCount']}", file=sys.stderr)
            jsonio.atomic_json(args.output, value, ascii=False, allow_nan=False)
            print(json.dumps({key: value[key] for key in (
                "runID", "split", "languages", "takeCount", "batchCount", "expectedTakeCount", "planDigest")}))
            return 0
        if args.command == "batch-files":
            rows = write_batch_files(load_json(args.plan), args.out_dir)
            for row in rows:
                print(batch_row_line(row))
            return 0
        if args.command == "manifest":
            value = build_manifest(plan_path=args.plan, batch_results=args.batch_results, wav_root=args.wav_root,
                                   output=args.output, copy=args.copy, diagnostics=args.diagnostics)
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
