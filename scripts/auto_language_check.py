#!/usr/bin/env python3
"""Plan and check the macOS Studio language UI check against engine receipts.

`prepare` turns the tracked spec (config/auto-language-check.json) into a run
plan that the XCUITest receives as one base64 line. Most takes leave the
language on Auto; a take with an explicit `selection` chooses that language
first, so its chip shows the plain name and the engine must speak it even when
the script is written in another language. `validate` reads the test's
per-take manifest records from the xcodebuild log, matches each take to this
run's engine generation rows and checks that the language the chip showed is
the language the engine was asked to speak. The summary carries digests,
labels and language codes, never the script text.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
from pathlib import Path
from typing import Any

import ios_startup_reliability as startup
from lib import jsonio  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
EXIT_PASS, EXIT_FAIL, EXIT_CONTRACT, EXIT_ROWS_NOT_PRESENT = 0, 1, 2, 75
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
RUN_ID = startup.SAFE_ID
SHA256 = re.compile(r"^[0-9a-f]{64}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MODES = ("custom", "design", "clone")
LANGUAGE_NAMES = {
    "english": "English", "chinese": "Chinese", "japanese": "Japanese", "korean": "Korean",
    "german": "German", "french": "French", "russian": "Russian", "portuguese": "Portuguese",
    "spanish": "Spanish", "italian": "Italian",
}
LANGUAGES = frozenset(LANGUAGE_NAMES) | {"auto"}
NAME_TO_LANGUAGE = {name: language for language, name in LANGUAGE_NAMES.items()}
# Latin-script languages whose corpus sentence the engine must name as its
# detected target; the others carry it when present (advisory).
WITNESS_REQUIRED = frozenset({"english", "french", "german", "spanish", "italian", "portuguese"})
OPTIONAL_TAKE_FIELDS = frozenset({"knownMismatch", "requireAudioPass", "selection", "textLanguage"})
KNOWN_MISMATCHES = {"D6": {"mode": "custom", "expectedChip": "auto", "expectedEngine": "english"}}
D6_OVERRIDE_KEY = "QWENVOICE_CUSTOM_AUTO_LANGUAGE"
MANIFEST_MARKER = "VOCELLO_AUTO_LANGUAGE_TAKE="
MANIFEST = re.compile(r"VOCELLO_AUTO_LANGUAGE_TAKE=([A-Za-z0-9+/=]+)")
MAX_MANIFEST_LINE_BYTES = 8 * 1024
MAX_SCRIPT_CHARACTERS = 500
MAX_CHIP_VALUE_CHARACTERS = 128
# ios_startup_reliability's private-field walk covers script/text/error/message,
# paths and URLs; a manifest also never carries transcripts or prompts.
EXTRA_PRIVATE_KEYS = frozenset({"transcript", "prompt", "instruction", "spokentext"})
PLAN_KEYS = {"schemaVersion", "source", "planDigest", "takes"}
PLAN_TAKE_KEYS = {
    "takeID", "mode", "selection", "selectionTitle", "scriptKey", "script", "scriptDigest", "expectedChip",
    "expectedEngine", "expectedChipValue", "expectedRecommendedTitle", "witness", "witnessLanguage",
    "requireAudioPass", "knownMismatch",
}
MANIFEST_KEYS = {
    "schemaVersion", "runID", "planDigest", "takeID", "mode", "chip", "menu", "generationID",
    "visibleErrorShown",
}
CHIP_KEYS = {"expectedValue", "observedValue", "stable"}
MENU_KEYS = {"opened", "recommendedSeen", "autoItemSeen", "valueUnchanged"}
QUALITY_OUTCOMES_PASSING = {"pass", "warning"}
# The engine's runtime profile signature joins its fields with "|" and lists
# with ","; ios_startup_reliability's identity pattern predates that format.
PROFILE_SIGNATURE = re.compile(r"[A-Za-z0-9._:|,-]{1,2048}")


class ContractError(startup.ContractError):
    pass


class RowsNotPresent(Exception):
    pass


def chip_value(language: str, selection: str = "auto") -> str:
    """The chip's value: "<Name>, Auto" or "Auto" on Auto, the plain name for an explicit selection."""
    if selection != "auto":
        return LANGUAGE_NAMES[selection]
    return "Auto" if language == "auto" else f"{LANGUAGE_NAMES[language]}, Auto"


def chip_language(value: Any, selection: str = "auto") -> str | None:
    """The language a chip value names, or None when it is not a chip value for this selection.

    Auto reads only "Auto" or "<Name>, Auto"; an explicit selection reads only a plain name.
    """
    if not isinstance(value, str):
        return None
    if selection != "auto":
        return NAME_TO_LANGUAGE.get(value)
    if value == "Auto":
        return "auto"
    if value.endswith(", Auto"):
        return NAME_TO_LANGUAGE.get(value[: -len(", Auto")])
    return None


def recommended_title(language: str) -> str | None:
    return None if language == "auto" else f"{LANGUAGE_NAMES[language]} — Detected"


def witness(language: str, from_corpus: bool) -> str:
    """An Auto take's witness level for the language its chip expects."""
    if language == "auto":
        return "absent"
    return "required" if language in WITNESS_REQUIRED and from_corpus else "advisory"


def explicit_witness(language: str | None) -> str:
    """An explicit take's witness level for the language its script is written in."""
    if language is None:
        return "absent"
    return "required" if language in WITNESS_REQUIRED else "advisory"


def plan_digest(plan: dict[str, Any]) -> str:
    return jsonio.sha256_json({key: value for key, value in plan.items() if key != "planDigest"})


def load_corpus(path: Path) -> dict[str, dict[str, str]]:
    corpus = jsonio.load_json(path, error=ContractError)
    if set(corpus) != {"schemaVersion", "description", "scripts"} or corpus["schemaVersion"] != 1:
        raise ContractError(f"corpus {path.name} does not match schema v1")
    scripts = corpus["scripts"]
    if not isinstance(scripts, dict):
        raise ContractError(f"corpus {path.name} scripts must be an object")
    for language, lengths in scripts.items():
        if not isinstance(lengths, dict) or not all(isinstance(text, str) and text.strip() for text in lengths.values()):
            raise ContractError(f"corpus {path.name} entry {language} is malformed")
    return scripts


def resolve_script(take_id: str, script: Any, corpus: dict[str, dict[str, str]]) -> tuple[str, str, bool]:
    """Return (scriptKey, sentence, fromCorpus) for one spec take."""
    if not isinstance(script, dict):
        raise ContractError(f"take {take_id} script must be an object")
    if set(script) == {"corpus", "length"}:
        language, length = script["corpus"], script["length"]
        if language not in corpus or language not in LANGUAGE_NAMES:
            raise ContractError(f"take {take_id} names unknown corpus language {language!r}")
        if length not in corpus[language]:
            raise ContractError(f"take {take_id} names unknown corpus length {length!r}")
        return f"corpus:{language}/{length}", corpus[language][length], True
    if set(script) == {"text"}:
        text = script["text"]
        if not isinstance(text, str) or not text.strip() or "\x00" in text or len(text) > MAX_SCRIPT_CHARACTERS:
            raise ContractError(f"take {take_id} edge text must be 1...{MAX_SCRIPT_CHARACTERS} characters")
        return f"edge:{take_id}", text, False
    raise ContractError(f"take {take_id} script must be {{corpus, length}} or {{text}}")


def take_expectations(
    take_id: str, take: dict[str, Any], selection: str, from_corpus: bool, script_language: str | None,
) -> dict[str, Any]:
    """The chip, menu and witness expectations of one spec take.

    `script_language` is the language the script is written in: the corpus language, the edge
    text's declared textLanguage, or None for text the recognizer should not name.
    """
    mode, expected_chip, expected_engine = take["mode"], take["expectedChip"], take["expectedEngine"]
    known = take.get("knownMismatch")
    if selection != "auto":
        if known is not None:
            raise ContractError(f"take {take_id} knownMismatch is only valid on auto takes")
        if (expected_chip, expected_engine) != (selection, selection):
            raise ContractError(
                f"take {take_id} selects {selection} but expects chip {expected_chip} and engine {expected_engine}"
            )
        return {
            "selectionTitle": LANGUAGE_NAMES[selection],
            "expectedChipValue": chip_value(selection, selection),
            "expectedRecommendedTitle": None,
            "witness": explicit_witness(script_language),
            "witnessLanguage": script_language,
            "knownMismatch": None,
        }
    if from_corpus and script_language != expected_chip:
        raise ContractError(f"take {take_id} expects chip {expected_chip} for a {script_language} corpus sentence")
    if script_language is not None and script_language != expected_chip:
        raise ContractError(f"take {take_id} declares textLanguage {script_language} but expects chip {expected_chip}")
    if known is not None:
        rule = KNOWN_MISMATCHES.get(known)
        if rule is None:
            raise ContractError(f"take {take_id} names unknown knownMismatch {known!r}")
        if mode != rule["mode"]:
            raise ContractError(f"take {take_id} knownMismatch {known} is only valid for {rule['mode']} takes")
        if (expected_chip, expected_engine) != (rule["expectedChip"], rule["expectedEngine"]):
            raise ContractError(f"take {take_id} knownMismatch {known} expects chip {rule['expectedChip']} and engine {rule['expectedEngine']}")
    elif expected_engine != expected_chip:
        raise ContractError(f"take {take_id} expects the engine to diverge from the chip without a knownMismatch")
    level = witness(expected_chip, from_corpus)
    return {
        "selectionTitle": None,
        "expectedChipValue": chip_value(expected_chip),
        "expectedRecommendedTitle": recommended_title(expected_chip),
        "witness": level,
        "witnessLanguage": None if level == "absent" else expected_chip,
        "knownMismatch": known,
    }


def build_plan(spec_path: Path, *, root: Path = ROOT) -> dict[str, Any]:
    spec = jsonio.load_json(spec_path, error=ContractError, reject_duplicate_keys=True)
    if set(spec) != {"schemaVersion", "description", "corpus", "takes"} or spec["schemaVersion"] != SCHEMA_VERSION:
        raise ContractError("spec does not match schema v1")
    if not isinstance(spec["corpus"], str) or spec["corpus"].startswith("/") or ".." in Path(spec["corpus"]).parts:
        raise ContractError("spec corpus must be a repository-relative path")
    corpus = load_corpus(root / spec["corpus"])
    takes = spec["takes"]
    if not isinstance(takes, list) or not 1 <= len(takes) <= 64:
        raise ContractError("spec takes must contain 1...64 rows")
    required = {"takeID", "mode", "script", "expectedChip", "expectedEngine"}
    seen_ids: set[str] = set()
    seen_scripts: set[tuple[str, str, str]] = set()
    custom_corpus_languages: set[str] = set()
    planned: list[dict[str, Any]] = []
    for position, take in enumerate(takes, 1):
        if not isinstance(take, dict) or not required.issubset(take):
            raise ContractError(f"take {position} is missing required fields")
        if set(take) - (required | OPTIONAL_TAKE_FIELDS):
            raise ContractError(f"take {position} has unknown fields")
        take_id = take["takeID"]
        if not isinstance(take_id, str) or not SAFE_ID.fullmatch(take_id):
            raise ContractError(f"take {position} takeID is not allowlisted")
        if take_id in seen_ids:
            raise ContractError(f"duplicate takeID {take_id}")
        seen_ids.add(take_id)
        mode = take["mode"]
        if mode not in MODES:
            raise ContractError(f"take {take_id} has unsupported mode {mode!r}")
        expected_chip, expected_engine = take["expectedChip"], take["expectedEngine"]
        for field, value in (("expectedChip", expected_chip), ("expectedEngine", expected_engine)):
            if not isinstance(value, str) or value not in LANGUAGES:
                raise ContractError(f"take {take_id} has unsupported language {field}={value!r}")
        selection = take.get("selection", "auto")
        if not isinstance(selection, str) or selection not in LANGUAGES:
            raise ContractError(f"take {take_id} has unsupported selection {selection!r}")
        script_key, sentence, from_corpus = resolve_script(take_id, take["script"], corpus)
        text_language = take.get("textLanguage")
        if text_language is not None:
            if from_corpus:
                raise ContractError(f"take {take_id} declares textLanguage on a corpus sentence")
            if not isinstance(text_language, str) or text_language not in LANGUAGE_NAMES:
                raise ContractError(f"take {take_id} has unsupported textLanguage {text_language!r}")
        script_language = take["script"]["corpus"] if from_corpus else text_language
        expectations = take_expectations(take_id, take, selection, from_corpus, script_language)
        require_audio = take.get("requireAudioPass", True)
        if not isinstance(require_audio, bool):
            raise ContractError(f"take {take_id} requireAudioPass must be boolean")
        script_digest = jsonio.sha256_bytes(sentence.encode("utf-8"))
        if (mode, script_digest, selection) in seen_scripts:
            raise ContractError(f"take {take_id} repeats another {mode} take's script and selection")
        seen_scripts.add((mode, script_digest, selection))
        if mode == "custom" and from_corpus and selection == "auto":
            custom_corpus_languages.add(expected_chip)
        planned.append({
            "takeID": take_id,
            "mode": mode,
            "selection": selection,
            "selectionTitle": expectations["selectionTitle"],
            "scriptKey": script_key,
            "script": sentence,
            "scriptDigest": script_digest,
            "expectedChip": expected_chip,
            "expectedEngine": expected_engine,
            "expectedChipValue": expectations["expectedChipValue"],
            "expectedRecommendedTitle": expectations["expectedRecommendedTitle"],
            "witness": expectations["witness"],
            "witnessLanguage": expectations["witnessLanguage"],
            "requireAudioPass": require_audio,
            "knownMismatch": expectations["knownMismatch"],
        })
    missing = sorted(set(LANGUAGE_NAMES) - custom_corpus_languages)
    if missing:
        raise ContractError("Custom Auto takes miss corpus languages: " + ",".join(missing))
    source = spec_path.resolve()
    try:
        source_name = source.relative_to(root.resolve()).as_posix()
    except ValueError:
        source_name = spec_path.name
    plan: dict[str, Any] = {"schemaVersion": SCHEMA_VERSION, "source": source_name, "takes": planned}
    plan["planDigest"] = plan_digest(plan)
    return plan


def encode_plan(plan: dict[str, Any]) -> bytes:
    return base64.b64encode(jsonio.canonical_bytes(plan)) + b"\n"


def prepare(spec_path: Path, output: Path, encoded_output: Path) -> dict[str, Any]:
    plan = build_plan(spec_path)
    jsonio.atomic_json(output, plan)
    jsonio.atomic_write_bytes(encoded_output, encode_plan(plan))
    return plan


def load_plan(path: Path) -> dict[str, Any]:
    plan = jsonio.load_json(path, error=ContractError, reject_duplicate_keys=True)
    if set(plan) != PLAN_KEYS or plan["schemaVersion"] != SCHEMA_VERSION:
        raise ContractError("plan does not match schema v1")
    if not isinstance(plan["planDigest"], str) or plan["planDigest"] != plan_digest(plan):
        raise ContractError("plan digest does not match its content")
    takes = plan["takes"]
    if not isinstance(takes, list) or not takes:
        raise ContractError("plan has no takes")
    seen: set[str] = set()
    for take in takes:
        if not isinstance(take, dict) or set(take) != PLAN_TAKE_KEYS:
            raise ContractError("plan take does not match schema v1")
        if take["takeID"] in seen:
            raise ContractError(f"plan repeats takeID {take['takeID']}")
        seen.add(take["takeID"])
        if jsonio.sha256_bytes(str(take["script"]).encode("utf-8")) != take["scriptDigest"]:
            raise ContractError(f"plan take {take['takeID']} script digest drifted")
    return plan


def reject_private_fields(value: Any) -> None:
    try:
        startup.recursively_reject_private_fields(value)
    except startup.ContractError as error:
        raise ContractError(f"manifest record carries a private field: {error}") from error
    _reject_extra_private_keys(value, "$")


def _reject_extra_private_keys(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in EXTRA_PRIVATE_KEYS:
                raise ContractError(f"manifest record carries a private field at {path}.{key}")
            _reject_extra_private_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_extra_private_keys(child, f"{path}[{index}]")


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def validate_manifest_record(record: Any, plan: dict[str, Any], run_id: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ContractError("manifest record is not an object")
    reject_private_fields(record)
    if set(record) != MANIFEST_KEYS or record["schemaVersion"] != 1:
        raise ContractError("manifest record does not match schema v1")
    if record["runID"] != run_id:
        raise ContractError("manifest record run identity drifted")
    if record["planDigest"] != plan["planDigest"]:
        raise ContractError("manifest record plan identity drifted")
    take = next((row for row in plan["takes"] if row["takeID"] == record["takeID"]), None)
    if take is None:
        raise ContractError(f"manifest record names unknown take {record['takeID']!r}")
    if record["mode"] != take["mode"]:
        raise ContractError(f"manifest record for {take['takeID']} drifted from its planned mode")
    chip, menu = record["chip"], record["menu"]
    if not isinstance(chip, dict) or set(chip) != CHIP_KEYS:
        raise ContractError(f"manifest record for {take['takeID']} has a malformed chip")
    if chip["expectedValue"] != take["expectedChipValue"]:
        raise ContractError(f"manifest record for {take['takeID']} expected a different chip than the plan")
    observed = chip["observedValue"]
    if observed is not None and (not isinstance(observed, str) or len(observed) > MAX_CHIP_VALUE_CHARACTERS):
        raise ContractError(f"manifest record for {take['takeID']} has an invalid observed chip value")
    if not _is_bool(chip["stable"]):
        raise ContractError(f"manifest record for {take['takeID']} chip stability must be boolean")
    if not isinstance(menu, dict) or set(menu) != MENU_KEYS:
        raise ContractError(f"manifest record for {take['takeID']} has a malformed menu")
    if not all(_is_bool(menu[key]) for key in ("opened", "autoItemSeen", "valueUnchanged")) or (
        menu["recommendedSeen"] is not None and not _is_bool(menu["recommendedSeen"])
    ):
        raise ContractError(f"manifest record for {take['takeID']} menu evidence must be boolean")
    generation = record["generationID"]
    if generation is not None and (not isinstance(generation, str) or not UUID.fullmatch(generation)):
        raise ContractError(f"manifest record for {take['takeID']} generationID must be a lowercase UUID")
    if not _is_bool(record["visibleErrorShown"]):
        raise ContractError(f"manifest record for {take['takeID']} visibleErrorShown must be boolean")
    return record


def parse_manifest(log_path: Path, plan: dict[str, Any], run_id: str) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    text = log_path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if MANIFEST_MARKER not in line:
            continue
        if len(line.encode("utf-8")) > MAX_MANIFEST_LINE_BYTES:
            raise ContractError(f"a manifest line exceeds {MAX_MANIFEST_LINE_BYTES} bytes")
        for match in MANIFEST.finditer(line):
            try:
                payload = base64.b64decode(match.group(1), validate=True)
                record = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
            except (binascii.Error, UnicodeDecodeError, ValueError) as error:
                raise ContractError(f"manifest record is not base64 JSON: {type(error).__name__}") from error
            record = validate_manifest_record(record, plan, run_id)
            prior = records.get(record["takeID"])
            if prior is not None and prior != record:
                raise ContractError(f"conflicting manifest records for take {record['takeID']}")
            records[record["takeID"]] = record
    owners: dict[str, str] = {}
    for take_id, record in records.items():
        generation = record["generationID"]
        if generation is None:
            continue
        if generation in owners:
            raise ContractError(f"generationID is reused by takes {owners[generation]} and {take_id}")
        owners[generation] = take_id
    return records


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_run_rows(diagnostics: Path, run_id: str) -> list[tuple[str, dict[str, Any]]]:
    """This run's receipt-bearing engine rows, each with its original line."""
    path = diagnostics / "engine" / "generations.jsonl"
    try:
        data = path.read_text(encoding="utf-8", errors="strict")
    except FileNotFoundError as error:
        raise RowsNotPresent("engine generation rows are not yet present") from error
    except UnicodeDecodeError as error:
        raise ContractError("engine generation rows are not UTF-8") from error
    # The fragment after the last newline is empty or an append still in progress.
    complete = data.split("\n")[:-1]
    rows: list[tuple[str, dict[str, Any]]] = []
    for number, line in enumerate(complete, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as error:
            # The file is shared across runs: an older run's torn append must not
            # block this one, but a malformed row of this run fails closed.
            if run_id in line:
                raise ContractError(f"engine generation row {number} of this run is not JSON") from error
            continue
        if not isinstance(row, dict) or not isinstance(row.get("requestReceipt"), dict):
            continue
        notes = row.get("notes")
        if isinstance(notes, dict) and notes.get("benchRunID") == run_id:
            rows.append((line, row))
    if not rows:
        raise RowsNotPresent("no engine generation row carries this run ID yet")
    return rows


def validate_engine_receipt(receipt: Any) -> None:
    """ios_startup_reliability.validate_receipt, with the runtime profile signature checked here."""
    identity = receipt.get("modelRuntimeIdentity") if isinstance(receipt, dict) else None
    if isinstance(identity, dict) and identity.get("runtimeProfileSignature") is not None:
        signature = identity["runtimeProfileSignature"]
        if not isinstance(signature, str) or not PROFILE_SIGNATURE.fullmatch(signature):
            raise ContractError("requestReceipt.modelRuntimeIdentity.runtimeProfileSignature is invalid")
        remainder = {key: value for key, value in identity.items() if key != "runtimeProfileSignature"}
        receipt = {**receipt, "modelRuntimeIdentity": remainder}
    startup.validate_receipt(receipt, "requestReceipt")


def row_generation(row: dict[str, Any]) -> str:
    value = row.get("generationID") or row["requestReceipt"].get("generationID") or ""
    return str(value).lower()


def retry_attempt(row: dict[str, Any]) -> int:
    value = row["requestReceipt"].get("retryAttempt")
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


def active_override_keys(row: dict[str, Any]) -> list[str]:
    candidates = [row.get("runtimeDebugProvenance")]
    for container in (row.get("summary"), row):
        environment = container.get("runEnvironment") if isinstance(container, dict) else None
        if isinstance(environment, dict):
            candidates.append(environment.get("runtimeDebugProvenance"))
    keys: list[str] = []
    for provenance in candidates:
        if isinstance(provenance, dict) and isinstance(provenance.get("activeOverrideKeys"), list):
            keys.extend(str(key) for key in provenance["activeOverrideKeys"])
    return keys


def _terminal(rows: list[tuple[str, dict[str, Any]]]) -> tuple[str, dict[str, Any]] | None:
    if not rows:
        return None
    # The highest retry wins; among equals the later line is the newer row.
    return max(enumerate(rows), key=lambda item: (retry_attempt(item[1][1]), item[0]))[1]


def check_take(
    take: dict[str, Any], record: dict[str, Any] | None, row: dict[str, Any] | None, correlation: str
) -> dict[str, Any]:
    issues: list[str] = []
    observations: list[str] = []
    require_audio = take["requireAudioPass"]
    selection = take["selection"]
    explicit = selection != "auto"
    witness_language = take["witnessLanguage"]

    def audio(name: str) -> None:
        (issues if require_audio else observations).append(name)

    observed: dict[str, Any] = {
        "generationID": None, "chip": None, "storedLanguageSelection": None,
        "finalModelLanguage": None, "languageTokenMode": None, "detectedTargetLanguage": None,
        "languageHint": None, "finishReason": None,
        "fastQC": {"outcome": None, "audioQCVerdict": None},
        "speakerID": None, "referenceTranscriptLanguage": None, "modelID": None, "warmState": None,
    }
    if record is None:
        issues.append("missing_take")
    else:
        observed["generationID"] = record["generationID"]
        chip, menu = record["chip"], record["menu"]
        observed["chip"] = {"value": chip["observedValue"], "stable": chip["stable"]}
        if chip["observedValue"] != take["expectedChipValue"]:
            issues.append("chip_value_mismatch")
        if not chip["stable"]:
            issues.append("chip_unstable")
        if not menu["opened"]:
            issues.append("menu_not_opened")
        if not menu["autoItemSeen"]:
            issues.append("menu_auto_item_missing")
        if not menu["valueUnchanged"]:
            issues.append("menu_changed_value")
        if take["expectedRecommendedTitle"] is not None and menu["recommendedSeen"] is not True:
            issues.append("menu_recommended_missing")
        elif take["expectedRecommendedTitle"] is None and menu["recommendedSeen"] is True:
            observations.append("menu_recommended_seen_without_detection")
        if record["visibleErrorShown"]:
            audio("visible_error")
        if record["generationID"] is None and not record["visibleErrorShown"]:
            issues.append("missing_generation_id")
    if record is not None and row is None:
        issues.append("no_engine_row")

    if row is not None:
        receipt = row["requestReceipt"]
        raw_notes, raw_qc = row.get("notes"), row.get("audioQC")
        notes: dict[str, Any] = raw_notes if isinstance(raw_notes, dict) else {}
        audio_qc_verdict = raw_qc.get("verdict") if isinstance(raw_qc, dict) else None
        final = receipt.get("finalModelLanguage")
        observed.update({
            "storedLanguageSelection": receipt.get("storedLanguageSelection"),
            "finalModelLanguage": final,
            "languageTokenMode": receipt.get("languageTokenMode"),
            "detectedTargetLanguage": receipt.get("detectedTargetLanguage"),
            "languageHint": notes.get("languageHint"),
            "finishReason": row.get("finishReason"),
            "fastQC": {
                "outcome": notes.get("quality_registry_outcome"),
                "audioQCVerdict": audio_qc_verdict,
            },
            "speakerID": receipt.get("speakerID"),
            "referenceTranscriptLanguage": receipt.get("referenceTranscriptLanguage"),
            "modelID": receipt.get("modelID", row.get("modelID")),
            "warmState": receipt.get("warmState", row.get("warmState")),
        })
        try:
            validate_engine_receipt(receipt)
            if receipt["schemaVersion"] < 2:
                issues.append("receipt_schema_too_old")
        except startup.ContractError:
            issues.append("receipt_invalid")
        if receipt.get("storedLanguageSelection") != selection:
            issues.append("stored_selection_mismatch" if explicit else "stored_selection_not_auto")
        if final != receipt.get("language"):
            issues.append("language_final_drift")
        known_d6 = take["knownMismatch"] == "D6"
        if known_d6 and final == "auto":
            issues.append("d6_expectation_changed")
        elif final != take["expectedEngine"]:
            issues.append("engine_language_mismatch")
        observed_chip = chip_language(record["chip"]["observedValue"], selection) if record is not None else None
        if record is not None:
            if known_d6:
                if observed_chip == "auto" and final == "english":
                    observations.append("known_d6_chip_auto_engine_english")
            elif observed_chip != final:
                issues.append("chip_engine_mismatch")
        # An explicit selection always sends its language token; Auto thinks only when it resolved one.
        expected_mode = "think" if explicit or final != "auto" else "nothink"
        if receipt.get("languageTokenMode") != expected_mode:
            issues.append("token_mode_mismatch")
        # The witness is the language the text recognizer names for the script, which an explicit
        # selection need not share.
        detected = receipt.get("detectedTargetLanguage")
        if take["witness"] == "required":
            if detected != witness_language:
                issues.append("detected_target_mismatch")
        elif take["witness"] == "advisory":
            if detected is None:
                observations.append("detected_target_absent")
            elif detected != witness_language:
                issues.append("detected_target_mismatch")
        elif detected is not None:
            issues.append("detected_target_unexpected")
        if (explicit and witness_language is not None and witness_language != selection
                and detected == witness_language and final == selection):
            # The proof that a manual choice wins: the recognizer named another language and
            # the engine still spoke the selected one.
            observations.append("explicit_selection_overrode_detection")
        if notes.get("languageHint") != final:
            if take["mode"] == "clone":
                observations.append("clone_language_hint_differs")
            else:
                issues.append("language_hint_mismatch")
        if notes.get("promptDigest") != take["scriptDigest"]:
            issues.append("prompt_digest_mismatch")
        if row.get("mode") != take["mode"]:
            issues.append("mode_mismatch")
        if D6_OVERRIDE_KEY in active_override_keys(row):
            issues.append("d6_override_active")
        if row.get("finishReason") != "eos":
            audio("finish_not_eos")
        if notes.get("quality_registry_outcome") not in QUALITY_OUTCOMES_PASSING:
            audio("fast_qc_failed")
        if audio_qc_verdict == "fail":
            audio("audio_qc_failed")

    return {
        "takeID": take["takeID"],
        "mode": take["mode"],
        "scriptKey": take["scriptKey"],
        "scriptDigest": take["scriptDigest"],
        "expected": {
            "selection": selection,
            "chip": take["expectedChip"],
            "chipValue": take["expectedChipValue"],
            "engine": take["expectedEngine"],
            "recommendedTitle": take["expectedRecommendedTitle"],
            "witness": take["witness"],
            "witnessLanguage": witness_language,
            "requireAudioPass": require_audio,
            "knownMismatch": take["knownMismatch"],
        },
        "observed": observed,
        "correlation": correlation,
        "issues": issues,
        "observations": observations,
    }


def validate(
    plan_path: Path, log_path: Path, diagnostics: Path, run_id: str, output: Path,
    retain_rows: Path | None = None,
) -> dict[str, Any]:
    if not RUN_ID.fullmatch(run_id):
        raise ContractError("run ID is not allowlisted")
    plan = load_plan(plan_path)
    records = parse_manifest(log_path, plan, run_id)
    rows = read_run_rows(diagnostics, run_id)
    by_generation: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for line, row in rows:
        by_generation.setdefault(row_generation(row), []).append((line, row))
    claimed = {record["generationID"] for record in records.values() if record["generationID"]}
    retained: set[str] = set()
    takes: list[dict[str, Any]] = []
    for take in plan["takes"]:
        record = records.get(take["takeID"])
        matched: tuple[str, dict[str, Any]] | None = None
        correlation = "none"
        if record is not None and record["generationID"] is not None:
            matched = _terminal(by_generation.get(record["generationID"], []))
            correlation = "generationID" if matched else "none"
        elif record is not None and record["visibleErrorShown"]:
            candidates = [
                (line, row) for line, row in rows
                if row_generation(row) not in claimed
                and row.get("mode") == take["mode"]
                and isinstance(row.get("notes"), dict)
                and row["notes"].get("promptDigest") == take["scriptDigest"]
            ]
            matched = _terminal(candidates)
            correlation = "digest" if matched else "none"
        if matched is not None:
            retained.add(row_generation(matched[1]))
        takes.append(check_take(take, record, matched[1] if matched else None, correlation))
    failed = sum(bool(take["issues"]) for take in takes)
    summary = {
        "schemaVersion": SCHEMA_VERSION,
        "runID": run_id,
        "planDigest": plan["planDigest"],
        "result": "fail" if failed else "pass",
        "counts": {
            "plannedTakes": len(plan["takes"]),
            "manifestRecords": len(records),
            "matchedTakes": sum(take["correlation"] != "none" for take in takes),
            "digestCorrelatedTakes": sum(take["correlation"] == "digest" for take in takes),
            "passedTakes": len(takes) - failed,
            "failedTakes": failed,
            "issues": sum(len(take["issues"]) for take in takes),
            "observations": sum(len(take["observations"]) for take in takes),
        },
        "takes": takes,
    }
    if retain_rows is not None:
        kept = [line for line, row in rows if row_generation(row) in retained]
        jsonio.atomic_write_bytes(
            retain_rows / "engine" / "generations.jsonl",
            "".join(line + "\n" for line in kept).encode("utf-8"),
        )
    jsonio.atomic_json(output, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan and check the macOS Studio language UI check (Auto and explicit).")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare", help="build the run plan from the tracked spec")
    prepare_parser.add_argument("--spec", required=True, type=Path)
    prepare_parser.add_argument("--output", required=True, type=Path)
    prepare_parser.add_argument("--encoded-output", required=True, type=Path)
    validate_parser = sub.add_parser("validate", help="check manifest records against engine rows")
    validate_parser.add_argument("--plan", required=True, type=Path)
    validate_parser.add_argument("--xcodebuild-log", required=True, type=Path)
    validate_parser.add_argument("--diagnostics", required=True, type=Path)
    validate_parser.add_argument("--run-id", required=True)
    validate_parser.add_argument("--output", required=True, type=Path)
    validate_parser.add_argument("--retain-rows", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(args.spec, args.output, args.encoded_output)
            return EXIT_PASS
        summary = validate(
            args.plan, args.xcodebuild_log, args.diagnostics, args.run_id, args.output, args.retain_rows,
        )
    except RowsNotPresent as error:
        print(f"auto-language check: {error}", file=sys.stderr)
        return EXIT_ROWS_NOT_PRESENT
    except (startup.ContractError, jsonio.JSONReadError, OSError) as error:
        print(f"auto-language check contract failed: {error}", file=sys.stderr)
        return EXIT_CONTRACT
    counts = summary["counts"]
    print(
        f"auto-language check: {summary['result'].upper()} "
        f"({counts['passedTakes']}/{counts['plannedTakes']} takes, {counts['observations']} observations)"
    )
    for take in summary["takes"]:
        if take["issues"]:
            print(f"  {take['takeID']}: {', '.join(take['issues'])}")
    return EXIT_PASS if summary["result"] == "pass" else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
