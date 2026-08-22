#!/usr/bin/env python3
"""Validate and materialize pre-registered Qwen3 delivery experiments.

This module is deliberately outside the product runtime.  It turns the
versioned delivery specification and corpus into immutable, digest-bound work
items for the macOS/CLI research lane.  It never changes shipped preset copy,
selects a take, downloads a model, or publishes benchmark evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from delivery_statistics import required_pairs


REPO = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = REPO / "config/delivery-experiment-contract.json"
DEFAULT_CORPUS = REPO / "config/delivery-evaluation-corpus.json"
PRODUCT_CONTRACT = REPO / "Sources/Resources/qwenvoice_contract.json"
SCHEMA_VERSION = 1
EXPECTED_PRESETS = (
    "neutral", "happy", "sad", "angry", "fearful", "surprised", "calm", "whisper"
)
EXPECTED_ARMS = (
    "current", "official-minimal", "acoustic-only", "emotion-acoustic",
    "emotion-acoustic-scene", "emotion-acoustic-scene-constraint",
)
EXPECTED_VARIANTS = ("speed", "quality")
EXPECTED_SEMANTIC_CONDITIONS = ("neutral", "congruent", "conflicting")
EXPECTED_LENGTHS = ("short", "medium", "long")
INSTRUCTION_LANGUAGES = ("english", "mandarin")
MIN_CONFIRMATORY_SEEDS = 8
MAX_CONFIRMATORY_SEEDS = 20
EXPECTED_EXTERNAL_MODEL_REQUIREMENTS = (
    "commercially-compatible-license",
    "immutable-revision-and-weight-digest",
    "declared-training-data-and-label-map",
    "untouched-holdout-calibration-improvement",
    "measured-eight-gigabyte-memory-compatibility",
    "offline-after-approved-acquisition",
    "sequential-subprocess-memory-release",
)


class ExperimentError(ValueError):
    """A delivery experiment contract is incomplete or internally inconsistent."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentError(f"cannot load {path}: {error}") from error


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExperimentError(f"{label} must be a non-empty string")
    return value.strip()


def validate_contract(contract: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(contract, dict) or contract.get("schemaVersion") != SCHEMA_VERSION:
        raise ExperimentError(f"delivery experiment schemaVersion must be {SCHEMA_VERSION}")
    if contract.get("compilerVersion") != 1:
        raise ExperimentError("delivery experiment compilerVersion must be 1")
    if contract.get("status") != "experimental-only":
        raise ExperimentError("delivery experiment must remain experimental-only")
    arms = contract.get("promptArms")
    if not isinstance(arms, list) or tuple(row.get("id") for row in arms) != EXPECTED_ARMS:
        raise ExperimentError(f"prompt arms must be exactly {EXPECTED_ARMS}")
    if len({row["id"] for row in arms}) != len(arms):
        raise ExperimentError("prompt arms contain duplicate ids")

    specs = contract.get("presets")
    if not isinstance(specs, dict) or tuple(specs) != EXPECTED_PRESETS:
        raise ExperimentError(f"preset order must be exactly {EXPECTED_PRESETS}")
    for preset, spec in specs.items():
        dimensions = spec.get("dimensions")
        if not isinstance(dimensions, dict) or set(dimensions) != {
            "valence", "arousal", "dominance"
        }:
            raise ExperimentError(f"{preset}: dimensions must contain valence/arousal/dominance")
        if any(value not in (-1, 0, 1) for value in dimensions.values()):
            raise ExperimentError(f"{preset}: dimensional directions must be -1, 0, or 1")
        languages = spec.get("instructionLanguages")
        if not isinstance(languages, dict) or tuple(languages) != INSTRUCTION_LANGUAGES:
            raise ExperimentError(f"{preset}: requires English and Mandarin instructions")
        for language, wording in languages.items():
            for field in ("minimal", "emotion", "acoustics", "scene", "constraint"):
                _nonempty(wording.get(field), f"{preset}.{language}.{field}")
        prohibitions = spec.get("prohibitedPhrases")
        if not isinstance(prohibitions, list) or any(
            not isinstance(value, str) or not value.strip() for value in prohibitions
        ):
            raise ExperimentError(f"{preset}: prohibitedPhrases must be a string array")

    sampling = contract.get("samplingProfiles")
    if not isinstance(sampling, dict) or tuple(sampling) != (
        "official", "balanced", "consistent"
    ):
        raise ExperimentError("sampling profiles must be official, balanced, consistent")
    for name, profile in sampling.items():
        if not (0.0 < profile.get("temperature", 0.0) <= 2.0):
            raise ExperimentError(f"{name}: invalid temperature")
        if not (0.0 < profile.get("topP", 0.0) <= 1.0):
            raise ExperimentError(f"{name}: invalid topP")
        if not isinstance(profile.get("topK"), int) or profile["topK"] <= 0:
            raise ExperimentError(f"{name}: invalid topK")

    combinations = contract.get("samplingCombinations")
    expected_combinations = {
        "official-official", "balanced-official", "balanced-matched",
        "consistent-official", "consistent-matched",
    }
    if not isinstance(combinations, list) or {
        row.get("id") for row in combinations
    } != expected_combinations:
        raise ExperimentError("samplingCombinations must contain the five pre-registered arms")

    guardrails = contract.get("promotionGuardrails")
    expected_guardrails = {
        "listenerMacroImprovementLower95Above": 0.0,
        "holmAlpha": 0.05,
        "maximumAbsoluteWEROrCERRegression": 0.01,
        "maximumMedianSpeakerSimilarityRegression": 0.02,
        "maximumMedianRelativeUTMOSRegression": 0.1,
        "maximumNewHardAudioQCFailures": 0,
        "minimumIndependentListeners": 3,
        "minimumFluentListenersPerLanguage": 1,
    }
    if guardrails != expected_guardrails:
        raise ExperimentError("promotion guardrails drifted from the pre-registered contract")
    external = contract.get("externalModelPolicy")
    if not isinstance(external, dict) or tuple(external.get("required", ())) != (
        EXPECTED_EXTERNAL_MODEL_REQUIREMENTS
    ):
        raise ExperimentError("external model adoption requirements are incomplete or reordered")
    excluded = external.get("excludedPendingReview")
    if not isinstance(excluded, list) or {
        row.get("id") for row in excluded if isinstance(row, dict)
    } != {"audeering-dimensional-models", "emotion2vec-plus"}:
        raise ExperimentError("external model exclusions must retain both unresolved candidates")
    return contract


def product_native_languages(product: dict[str, Any]) -> dict[str, str]:
    metadata = product.get("speakerMetadata")
    speakers = product.get("speakers", {}).get("Built-in")
    if not isinstance(metadata, dict) or not isinstance(speakers, list):
        raise ExperimentError("product contract lacks Built-in speaker metadata")
    return {
        speaker: _nonempty(metadata.get(speaker, {}).get("nativeLanguage"), f"{speaker}.nativeLanguage")
        for speaker in speakers
    }


def validate_corpus(corpus: dict[str, Any], product: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(corpus, dict) or corpus.get("schemaVersion") != SCHEMA_VERSION:
        raise ExperimentError(f"delivery corpus schemaVersion must be {SCHEMA_VERSION}")
    if corpus.get("splitPolicy") != "translation-group-and-script-id-disjoint":
        raise ExperimentError("corpus splitPolicy must prevent translated-script leakage")
    partitions = corpus.get("seedPartitions")
    if not isinstance(partitions, dict) or tuple(partitions) != (
        "calibration", "development", "confirmation"
    ):
        raise ExperimentError("corpus seedPartitions must cover the three ordered splits")
    intervals: list[tuple[int, int]] = []
    for split, bounds in partitions.items():
        if (
            not isinstance(bounds, dict)
            or set(bounds) != {"minimum", "maximum"}
            or isinstance(bounds["minimum"], bool)
            or isinstance(bounds["maximum"], bool)
            or not isinstance(bounds["minimum"], int)
            or not isinstance(bounds["maximum"], int)
            or bounds["minimum"] > bounds["maximum"]
        ):
            raise ExperimentError(f"{split}: invalid seed partition")
        interval = (bounds["minimum"], bounds["maximum"])
        if any(
            interval[0] <= existing[1] and existing[0] <= interval[1]
            for existing in intervals
        ):
            raise ExperimentError("corpus seed partitions overlap")
        intervals.append(interval)

    native = product_native_languages(product)
    declared = corpus.get("nativeSpeakerLanguages")
    if declared != native:
        raise ExperimentError("corpus native speaker mapping drifted from qwenvoice_contract.json")
    sentinels = corpus.get("crossLanguageSentinels")
    expected_sentinels = {
        ("aiden", "Chinese"), ("vivian", "English"),
        ("ono_anna", "English"), ("sohee", "English"),
    }
    if not isinstance(sentinels, list) or {
        (row.get("speakerID"), row.get("outputLanguage")) for row in sentinels
    } != expected_sentinels:
        raise ExperimentError("cross-language sentinels do not match the pre-registered roster")

    frames = corpus.get("semanticFrames")
    if not isinstance(frames, list) or not frames:
        raise ExperimentError("corpus needs semanticFrames")
    frame_ids: set[str] = set()
    coverage: dict[tuple[str, str, str], int] = {}
    for frame in frames:
        frame_id = _nonempty(frame.get("id"), "frame.id")
        if frame_id in frame_ids:
            raise ExperimentError(f"duplicate corpus frame id {frame_id}")
        frame_ids.add(frame_id)
        language = _nonempty(frame.get("language"), f"{frame_id}.language")
        target = _nonempty(frame.get("targetPreset"), f"{frame_id}.targetPreset")
        if target not in EXPECTED_PRESETS:
            raise ExperimentError(f"{frame_id}: unknown target preset {target}")
        _nonempty(frame.get("translationConcept"), f"{frame_id}.translationConcept")
        if frame.get("reviewStatus") not in {"maintainer-reviewed", "provisional"}:
            raise ExperimentError(f"{frame_id}: invalid reviewStatus")
        texts = frame.get("texts")
        if not isinstance(texts, dict) or tuple(texts) != EXPECTED_LENGTHS:
            raise ExperimentError(f"{frame_id}: texts must contain short/medium/long")
        for length, text in texts.items():
            _nonempty(text, f"{frame_id}.{length}")
            coverage[(language, target, length)] = coverage.get((language, target, length), 0) + 1

    required_languages = {"English", "Chinese", "Japanese", "Korean"}
    missing = [
        f"{language}/{preset}/{length}"
        for language in sorted(required_languages)
        for preset in EXPECTED_PRESETS
        for length in EXPECTED_LENGTHS
        if coverage.get((language, preset, length), 0) == 0
    ]
    if missing:
        raise ExperimentError(f"corpus coverage missing: {', '.join(missing[:8])}")

    affixes = corpus.get("splitAffixes")
    if not isinstance(affixes, dict) or set(affixes) != required_languages:
        raise ExperimentError("splitAffixes must cover English, Chinese, Japanese, and Korean")
    for language, splits in affixes.items():
        if not isinstance(splits, dict) or set(splits) != {
            "calibration", "development", "confirmation"
        }:
            raise ExperimentError(f"{language}: splitAffixes must cover all three splits")
        for split, lengths in splits.items():
            if not isinstance(lengths, dict) or tuple(lengths) != EXPECTED_LENGTHS:
                raise ExperimentError(f"{language}/{split}: splitAffixes need all lengths")
            for length, value in lengths.items():
                if not isinstance(value, dict) or set(value) != {"prefix", "suffix"}:
                    raise ExperimentError(
                        f"{language}/{split}/{length}: needs prefix and suffix"
                    )
                if not value["prefix"] and not value["suffix"]:
                    raise ExperimentError(
                        f"{language}/{split}/{length}: prefix and suffix cannot both be empty"
                    )
    return corpus


def compile_instruction(
    contract: dict[str, Any], preset: str, arm: str, language: str,
    *, production_instruction: str | None = None,
) -> dict[str, Any]:
    validate_contract(contract)
    if preset not in EXPECTED_PRESETS:
        raise ExperimentError(f"unknown preset {preset!r}")
    if arm not in EXPECTED_ARMS:
        raise ExperimentError(f"unknown prompt arm {arm!r}")
    if language not in INSTRUCTION_LANGUAGES:
        raise ExperimentError(f"unsupported instruction language {language!r}")
    if arm == "current":
        text = _nonempty(production_instruction, "current production instruction")
    else:
        wording = contract["presets"][preset]["instructionLanguages"][language]
        fields = {
            "official-minimal": ("minimal",),
            "acoustic-only": ("acoustics",),
            "emotion-acoustic": ("emotion", "acoustics"),
            "emotion-acoustic-scene": ("emotion", "acoustics", "scene"),
            "emotion-acoustic-scene-constraint": (
                "emotion", "acoustics", "scene", "constraint"
            ),
        }[arm]
        text = " ".join(wording[field].strip() for field in fields)
    normalized = " ".join(text.split())
    lowered = normalized.casefold()
    conflicts = [
        phrase for phrase in contract["presets"][preset]["prohibitedPhrases"]
        if phrase.casefold() in lowered
    ]
    if conflicts:
        raise ExperimentError(
            f"{preset}/{arm}/{language}: prohibited contradictory phrase(s): {conflicts}"
        )
    return {
        "compilerVersion": contract["compilerVersion"],
        "preset": preset,
        "arm": arm,
        "instructionLanguage": language,
        "text": normalized,
        "wordCount": len(normalized.split()),
        "sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "dimensions": contract["presets"][preset]["dimensions"],
    }


def sampling_policy(contract: dict[str, Any], combination_id: str) -> dict[str, Any]:
    validate_contract(contract)
    row = next(
        (entry for entry in contract["samplingCombinations"] if entry["id"] == combination_id),
        None,
    )
    if row is None:
        raise ExperimentError(f"unknown sampling combination {combination_id!r}")
    talker = dict(contract["samplingProfiles"][row["talker"]])
    subtalker = (
        dict(contract["samplingProfiles"][row["talker"]])
        if row["subtalker"] == "matched"
        else dict(contract["samplingProfiles"][row["subtalker"]])
    )
    return {"id": combination_id, "talker": talker, "subtalker": subtalker}


def seed_plan(effect_size: float) -> dict[str, Any]:
    requested = required_pairs(abs(effect_size))
    if requested is None:
        raise ExperimentError("effect size must be finite and greater than zero")
    selected = min(MAX_CONFIRMATORY_SEEDS, max(MIN_CONFIRMATORY_SEEDS, requested))
    return {
        "effectSize": effect_size,
        "requestedPairs": requested,
        "minimumSeeds": MIN_CONFIRMATORY_SEEDS,
        "maximumSeeds": MAX_CONFIRMATORY_SEEDS,
        "selectedSeeds": selected,
        "adequatelyPoweredWithinCap": requested <= MAX_CONFIRMATORY_SEEDS,
        "outcomeIfCapReached": "inconclusive" if requested > MAX_CONFIRMATORY_SEEDS else "eligible",
    }


def semantic_frame_index(corpus: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (row["language"], row["targetPreset"]): row
        for row in corpus["semanticFrames"]
    }


def conflicting_preset(contract: dict[str, Any], preset: str) -> str:
    target = contract["presets"][preset].get("conflictingPreset")
    if target not in EXPECTED_PRESETS or target == preset:
        raise ExperimentError(f"{preset}: invalid conflictingPreset {target!r}")
    return target


def script_for_condition(
    contract: dict[str, Any], corpus: dict[str, Any], *, language: str,
    preset: str, split: str, length: str, condition: str,
) -> dict[str, Any]:
    if condition not in EXPECTED_SEMANTIC_CONDITIONS:
        raise ExperimentError(f"invalid semantic condition {condition!r}")
    if length not in EXPECTED_LENGTHS:
        raise ExperimentError(f"invalid script length {length!r}")
    frame_preset = {
        "neutral": "neutral",
        "congruent": preset,
        "conflicting": conflicting_preset(contract, preset),
    }[condition]
    frame = semantic_frame_index(corpus).get((language, frame_preset))
    if frame is None:
        raise ExperimentError(f"no frame for {language}/{frame_preset}")
    affix = corpus["splitAffixes"][language][split][length]
    text = " ".join(
        part.strip() for part in (
            affix["prefix"], frame["texts"][length], affix["suffix"]
        ) if part.strip()
    )
    return {
        "scriptID": f"{frame['id']}:{split}:{length}",
        "translationGroup": f"{frame['translationConcept']}:{split}:{length}",
        "semanticCondition": condition,
        "semanticSourcePreset": frame_preset,
        "length": length,
        "language": language,
        "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "split": split,
        "reviewStatus": frame["reviewStatus"],
    }


def build_plan(
    contract: dict[str, Any], corpus: dict[str, Any], product: dict[str, Any], *,
    split: str, arm: str, instruction_language: str, variant: str,
    sampling_combination: str, seeds: list[int], production_instructions: dict[str, str],
) -> dict[str, Any]:
    validate_contract(contract)
    validate_corpus(corpus, product)
    if split not in {"calibration", "development", "confirmation"}:
        raise ExperimentError(f"invalid split {split!r}")
    seed_partition = corpus["seedPartitions"][split]
    if any(
        isinstance(seed, bool)
        or not isinstance(seed, int)
        or not seed_partition["minimum"] <= seed <= seed_partition["maximum"]
        for seed in seeds
    ):
        raise ExperimentError(
            f"{split} seeds must stay in {seed_partition['minimum']}..{seed_partition['maximum']}"
        )
    if variant not in EXPECTED_VARIANTS:
        raise ExperimentError(f"invalid model variant {variant!r}")
    if not seeds or len(seeds) != len(set(seeds)) or any(
        not isinstance(seed, int) or isinstance(seed, bool) or seed < 0 for seed in seeds
    ):
        raise ExperimentError("seeds must be a non-empty unique non-negative integer list")
    native = product_native_languages(product)
    speaker_language_cells = [
        {
            "speakerID": speaker_id,
            "nativeLanguage": language,
            "outputLanguage": language,
            "coverageRole": "native",
        }
        for speaker_id, language in native.items()
    ]
    speaker_language_cells.extend({
        "speakerID": row["speakerID"],
        "nativeLanguage": native[row["speakerID"]],
        "outputLanguage": row["outputLanguage"],
        "coverageRole": "cross-language-sentinel",
    } for row in corpus["crossLanguageSentinels"])
    rows: list[dict[str, Any]] = []
    for cell in speaker_language_cells:
        speaker_id = cell["speakerID"]
        language = cell["outputLanguage"]
        for preset in EXPECTED_PRESETS:
            instruction = compile_instruction(
                contract, preset, arm, instruction_language,
                production_instruction=production_instructions.get(preset),
            )
            neutral_reference_instruction = compile_instruction(
                contract, "neutral", "current", "english",
                production_instruction=production_instructions.get("neutral"),
            )
            for condition in EXPECTED_SEMANTIC_CONDITIONS:
                for length in EXPECTED_LENGTHS:
                    script = script_for_condition(
                        contract, corpus, language=language, preset=preset,
                        split=split, length=length, condition=condition,
                    )
                    for seed in seeds:
                        row = {
                            "speakerID": speaker_id,
                            "nativeLanguage": cell["nativeLanguage"],
                            "outputLanguage": language,
                            "coverageRole": cell["coverageRole"],
                            "preset": preset,
                            "instruction": instruction,
                            "neutralReferenceInstruction": neutral_reference_instruction,
                            "script": script,
                            "seed": seed,
                            "variant": variant,
                            "sampling": sampling_policy(contract, sampling_combination),
                        }
                        row["takeID"] = digest(row)[:24]
                        rows.append(row)
    identity = {
        "schemaVersion": SCHEMA_VERSION,
        "designation": split,
        "arm": arm,
        "instructionLanguage": instruction_language,
        "variant": variant,
        "samplingCombination": sampling_combination,
        "seeds": seeds,
        "contractDigest": digest(contract),
        "corpusDigest": digest(corpus),
        "productContractDigest": digest(product),
        "rows": rows,
    }
    identity["planDigest"] = digest(identity)
    return identity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    compile_command = commands.add_parser("compile")
    compile_command.add_argument("--preset", required=True, choices=EXPECTED_PRESETS)
    compile_command.add_argument("--arm", required=True, choices=EXPECTED_ARMS)
    compile_command.add_argument("--language", default="english", choices=INSTRUCTION_LANGUAGES)
    compile_command.add_argument("--production-instruction")
    power = commands.add_parser("seed-plan")
    power.add_argument("--effect-size", required=True, type=float)
    args = parser.parse_args()

    try:
        contract = validate_contract(_load(args.contract))
        corpus = validate_corpus(_load(args.corpus), _load(PRODUCT_CONTRACT))
        if args.command == "validate":
            print(json.dumps({
                "status": "PASS",
                "contractDigest": digest(contract),
                "corpusDigest": digest(corpus),
                "presetCount": len(contract["presets"]),
                "frameCount": len(corpus["semanticFrames"]),
            }, indent=2, sort_keys=True))
        elif args.command == "compile":
            print(json.dumps(compile_instruction(
                contract, args.preset, args.arm, args.language,
                production_instruction=args.production_instruction,
            ), indent=2, sort_keys=True, ensure_ascii=False))
        else:
            if not math.isfinite(args.effect_size):
                raise ExperimentError("effect size must be finite")
            print(json.dumps(seed_plan(args.effect_size), indent=2, sort_keys=True))
        return 0
    except ExperimentError as error:
        print(f"Delivery experiment contract: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
