#!/usr/bin/env python3
"""Build an immutable language-run plan and collect only its exact evidence.

This module is intentionally offline and device-free. ``ios_device.sh`` uses it
to declare every take before generation and, after the device run, to extract a
small run-scoped evidence tree from the append-only diagnostics mirror. It never
retries, launches a process, writes tracked history, or scans outputs by prompt.
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
import tempfile
from typing import Any, Iterable
import unicodedata
import wave
from lib import jsonio  # noqa: E402


SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}\Z")
UINT64_MAX = (1 << 64) - 1
MIN_ALPHABETIC_WORDS = 15
MIN_CJK_CHARACTERS = 24
CJK_LANGUAGES = {"chinese", "japanese"}
SPEAKER_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "Sources"
    / "Resources"
    / "qwenvoice_contract.json"
)


class EvidenceError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return jsonio.load_json(path, error=EvidenceError)


def canonical_digest(value: Any) -> str:
    return jsonio.sha256_json(value, ascii=False, allow_nan=True)


file_digest = jsonio.sha256_file


def selected_matrix_cells(
    matrix: dict[str, Any], subset: str, cohort: dict[str, Any] | None
) -> list[dict[str, Any]]:
    raw_cells = matrix.get("cells")
    if not isinstance(raw_cells, list) or not raw_cells:
        raise EvidenceError("language matrix has no cells")
    cells: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for value in raw_cells:
        if not isinstance(value, dict) or not isinstance(value.get("id"), str):
            raise EvidenceError("language matrix contains a malformed cell")
        cell_id = value["id"]
        if cell_id in by_id:
            raise EvidenceError(f"language matrix has duplicate cell id {cell_id!r}")
        by_id[cell_id] = value

    if cohort is not None:
        ids = cohort.get("cellIDs")
        if not isinstance(ids, list) or not ids or not all(isinstance(v, str) for v in ids):
            raise EvidenceError("diagnostic cohort must contain a non-empty cellIDs array")
        if len(set(ids)) != len(ids):
            raise EvidenceError("diagnostic cohort cellIDs must be unique")
        missing = [cell_id for cell_id in ids if cell_id not in by_id]
        if missing:
            raise EvidenceError(f"diagnostic cohort has unknown cells: {', '.join(missing)}")
        return [dict(by_id[cell_id]) for cell_id in ids]

    if subset == "quick":
        cells = [dict(value) for value in raw_cells if value.get("quick") is True]
    elif subset == "full":
        cells = [dict(value) for value in raw_cells]
    else:
        raise EvidenceError(f"unknown subset {subset!r}")
    if not cells:
        raise EvidenceError(f"language matrix selection is empty for {subset}")
    return cells


def validate_seeds(cohort: dict[str, Any] | None) -> list[int | None]:
    if cohort is None:
        return [None]
    raw = cohort.get("seeds")
    if not isinstance(raw, list) or not raw:
        raise EvidenceError("diagnostic cohort must contain a non-empty seeds array")
    seeds: list[int] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= UINT64_MAX:
            raise EvidenceError(f"invalid UInt64 cohort seed: {value!r}")
        seeds.append(value)
    if len(set(seeds)) != len(seeds):
        raise EvidenceError("diagnostic cohort seeds must be unique")
    return seeds


def stable_default_seed(cell: dict[str, Any]) -> int:
    """One stable take per normal cell, paired for pinned/Auto comparisons."""
    identity = (
        f"language-bench-seed-v1|{cell.get('mode')}|{cell.get('scriptLang')}"
    ).encode("utf-8")
    # Keep the generated UInt64 within signed-JSON interoperability range while
    # still retaining 63 deterministic bits of seed entropy.
    return int.from_bytes(hashlib.sha256(identity).digest()[:8], "big") & ((1 << 63) - 1)


def normalized_script_unit_count(text: str, language: str) -> int:
    folded = unicodedata.normalize("NFKC", text).lower()
    if language in CJK_LANGUAGES:
        return sum(character.isalnum() for character in folded)
    count = 0
    in_token = False
    for character in folded:
        if character.isalnum():
            if not in_token:
                count += 1
                in_token = True
        else:
            in_token = False
    return count


def supported_custom_speaker_ids() -> set[str]:
    contract = load_json(SPEAKER_CONTRACT_PATH)
    groups = contract.get("speakers")
    if not isinstance(groups, dict) or not groups:
        raise EvidenceError("qwenvoice_contract.json has no Custom speaker groups")
    speakers: set[str] = set()
    for values in groups.values():
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise EvidenceError("qwenvoice_contract.json contains malformed Custom speakers")
        speakers.update(values)
    if not speakers:
        raise EvidenceError("qwenvoice_contract.json has no Custom speakers")
    return speakers


def build_plan(
    *,
    run_id: str,
    matrix_path: Path,
    corpus_path: Path,
    subset: str,
    cohort_path: Path | None,
) -> dict[str, Any]:
    if not SAFE_ID.fullmatch(run_id):
        raise EvidenceError("run id contains unsafe characters or is too long")
    matrix = load_json(matrix_path)
    corpus = load_json(corpus_path)
    cohort = load_json(cohort_path) if cohort_path else None
    supported_speakers = supported_custom_speaker_ids()
    fixtures: dict[str, dict[str, str]] = {}
    for entry in corpus.get("languages") or []:
        if not isinstance(entry, dict):
            raise EvidenceError("language corpus contains a malformed entry")
        language = entry.get("id")
        script = entry.get("script")
        speaker = entry.get("customSpeakerID")
        instruction = entry.get("designInstruction")
        if (
            not isinstance(language, str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{1,31}", language)
            or language in fixtures
            or not isinstance(script, str)
            or script != script.strip()
            or not script
            or not isinstance(speaker, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{1,31}", speaker)
            or not isinstance(instruction, str)
            or instruction != instruction.strip()
            or not 1 <= len(instruction) <= 240
        ):
            raise EvidenceError("language corpus contains an invalid or duplicate fixture")
        if speaker not in supported_speakers:
            raise EvidenceError(
                f"{language}: Custom speaker {speaker!r} is absent from qwenvoice_contract.json"
            )
        unit_count = normalized_script_unit_count(script, language)
        minimum = MIN_CJK_CHARACTERS if language in CJK_LANGUAGES else MIN_ALPHABETIC_WORDS
        if unit_count < minimum:
            raise EvidenceError(
                f"{language}: script has {unit_count} normalized units; requires at least {minimum}"
            )
        fixtures[language] = {
            "script": script,
            "customSpeakerID": speaker,
            "designInstruction": instruction,
        }
    cells = selected_matrix_cells(matrix, subset, cohort)
    design_instructions = {
        fixtures[str(cell.get("scriptLang"))]["designInstruction"]
        for cell in cells
        if cell.get("mode") == "design"
        and str(cell.get("scriptLang")) in fixtures
    }
    if len(design_instructions) > 1:
        raise EvidenceError(
            "language benchmark Design cells must share one corpus-owned instruction"
        )
    seeds = validate_seeds(cohort)
    selected_groups = sorted(
        {
            cell["promptEquivalenceGroup"]
            for cell in cells
            if isinstance(cell.get("promptEquivalenceGroup"), str)
            and cell["promptEquivalenceGroup"]
        }
    )
    if cohort is not None:
        declared_groups = cohort.get("promptEquivalenceGroups")
        if not isinstance(declared_groups, list) or not all(
            isinstance(group, str) and group for group in declared_groups
        ):
            raise EvidenceError("diagnostic cohort must declare promptEquivalenceGroups")
        if len(set(declared_groups)) != len(declared_groups):
            raise EvidenceError("diagnostic cohort promptEquivalenceGroups must be unique")
        if sorted(declared_groups) != selected_groups:
            raise EvidenceError(
                "diagnostic cohort prompt-equivalence declarations do not match its selected cells"
            )
    for group in selected_groups:
        if sum(cell.get("promptEquivalenceGroup") == group for cell in cells) < 2:
            raise EvidenceError(f"prompt equivalence group {group!r} has fewer than two cells")

    takes: list[dict[str, Any]] = []
    # Seed-major ordering keeps pinned/Auto comparisons adjacent for the exact
    # same RNG seed. This ordering is declared before any generation executes.
    take_pairs: list[tuple[int, int, dict[str, Any]]] = []
    if cohort is None:
        take_pairs = [
            (0, stable_default_seed(cell), cell)
            for cell in cells
        ]
    else:
        take_pairs = [
            (seed_index, seed, cell)
            for seed_index, seed in enumerate(seeds)
            for cell in cells
        ]
    for seed_index, seed, cell in take_pairs:
        cell_id = cell["id"]
        script_lang = cell.get("scriptLang")
        if script_lang not in fixtures:
            raise EvidenceError(f"{cell_id}: corpus lacks scriptLang {script_lang!r}")
        mode = cell.get("mode")
        if mode not in {"custom", "design"}:
            raise EvidenceError(f"{cell_id}: unsupported language-benchmark mode {mode!r}")
        if mode == "design" and (
            cell.get("uiHint") == "auto"
            or cell.get("uiHint") != cell.get("expectedHint")
        ):
            raise EvidenceError(
                f"{cell_id}: Design language validation requires the explicit target language"
            )
        fixture = fixtures[script_lang]
        design_instruction = fixture["designInstruction"] if mode == "design" else None
        child_id = f"{run_id}--{cell_id}"
        if cohort is not None:
            child_id += f"--s{seed_index + 1:02d}"
        if not SAFE_ID.fullmatch(child_id):
            raise EvidenceError(f"child run id is unsafe or too long: {child_id}")
        takes.append(
            {
                "takeIndex": len(takes) + 1,
                "seedIndex": seed_index if cohort is not None else None,
                "seed": seed,
                "samplingVariation": "expressive",
                "cellID": cell_id,
                "childRunID": child_id,
                "mode": mode,
                "variant": cell.get("variant", "speed"),
                "uiHint": cell.get("uiHint", "auto"),
                "scriptLang": script_lang,
                "expectedHint": cell.get("expectedHint"),
                "customSpeakerID": fixture["customSpeakerID"] if mode == "custom" else None,
                "designInstruction": design_instruction,
                "designInstructionDigest": (
                    hashlib.sha256(design_instruction.encode("utf-8")).hexdigest()
                    if design_instruction is not None else None
                ),
                "promptEquivalenceGroup": cell.get("promptEquivalenceGroup"),
                "skipOutputVerification": bool(cell.get("skipOutputVerification")),
                "expectedOutcome": cell.get("expectedOutcome", "pass"),
            }
        )

    plan: dict[str, Any] = {
        "schemaVersion": 1,
        "runID": run_id,
        "subset": subset,
        "kind": "diagnosticCohort" if cohort is not None else "languageBenchmark",
        "matrixDigest": file_digest(matrix_path),
        "corpusDigest": file_digest(corpus_path),
        "cohortID": cohort.get("id") if cohort is not None else None,
        "cohortDigest": file_digest(cohort_path) if cohort_path is not None else None,
        "seedPolicy": "explicit-cohort-v1" if cohort is not None else "sha256-v1-mode-script-language-63bit",
        "samplingVariation": "expressive",
        "promptEquivalenceGroups": selected_groups,
        "requireEveryTakePass": bool(cohort.get("requireEveryTakePass", True)) if cohort else True,
        "takeCount": len(takes),
        "takes": takes,
    }
    plan["planDigest"] = canonical_digest(plan)
    return plan


def validate_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    expected_digest = plan.get("planDigest")
    unsigned = dict(plan)
    unsigned.pop("planDigest", None)
    if expected_digest != canonical_digest(unsigned):
        raise EvidenceError("language run plan digest mismatch")
    if plan.get("schemaVersion") != 1:
        raise EvidenceError("language run plan schemaVersion must be 1")
    kind = plan.get("kind")
    if kind not in {"languageBenchmark", "diagnosticCohort"}:
        raise EvidenceError("language run plan has an unsupported kind")
    if plan.get("subset") not in {"quick", "full"}:
        raise EvidenceError("language run plan has an invalid subset")
    if plan.get("samplingVariation") != "expressive":
        raise EvidenceError("language run plan must use expressive sampling")
    expected_seed_policy = (
        "explicit-cohort-v1" if kind == "diagnosticCohort"
        else "sha256-v1-mode-script-language-63bit"
    )
    if plan.get("seedPolicy") != expected_seed_policy:
        raise EvidenceError("language run plan has an invalid seed policy")
    for digest_key in ("matrixDigest", "corpusDigest"):
        digest = plan.get(digest_key)
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise EvidenceError(f"language run plan has invalid {digest_key}")
    if kind == "diagnosticCohort":
        if not isinstance(plan.get("cohortID"), str) or not plan["cohortID"]:
            raise EvidenceError("diagnostic cohort plan lacks cohortID")
        if not isinstance(plan.get("cohortDigest"), str) or re.fullmatch(r"[0-9a-f]{64}", plan["cohortDigest"]) is None:
            raise EvidenceError("diagnostic cohort plan lacks cohortDigest")
    elif plan.get("cohortID") is not None or plan.get("cohortDigest") is not None:
        raise EvidenceError("normal language benchmark plan contains cohort identity")
    groups = plan.get("promptEquivalenceGroups")
    if (
        not isinstance(groups, list)
        or not all(isinstance(group, str) and group for group in groups)
        or groups != sorted(set(groups))
    ):
        raise EvidenceError("language run plan has invalid promptEquivalenceGroups")
    run_id = plan.get("runID")
    if not isinstance(run_id, str) or not SAFE_ID.fullmatch(run_id):
        raise EvidenceError("language run plan has invalid runID")
    takes = plan.get("takes")
    if not isinstance(takes, list) or not takes or len(takes) != plan.get("takeCount"):
        raise EvidenceError("language run plan has invalid take count")
    child_ids: set[str] = set()
    indexes: list[int] = []
    for take in takes:
        if not isinstance(take, dict):
            raise EvidenceError("language run plan contains a malformed take")
        child = take.get("childRunID")
        if not isinstance(child, str) or not SAFE_ID.fullmatch(child) or not child.startswith(f"{run_id}--"):
            raise EvidenceError("language run plan contains an invalid child run id")
        if child in child_ids:
            raise EvidenceError(f"language run plan repeats child run id {child}")
        child_ids.add(child)
        index = take.get("takeIndex")
        if isinstance(index, bool) or not isinstance(index, int):
            raise EvidenceError(f"{child}: invalid take index")
        indexes.append(index)
        seed = take.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= UINT64_MAX:
            raise EvidenceError(f"{child}: invalid seed")
        if take.get("samplingVariation") != "expressive":
            raise EvidenceError(f"{child}: language take must use expressive sampling")
        mode = take.get("mode")
        if mode == "custom":
            if (
                not isinstance(take.get("customSpeakerID"), str)
                or not re.fullmatch(r"[a-z][a-z0-9_]{1,31}", take["customSpeakerID"])
                or take.get("designInstruction") is not None
                or take.get("designInstructionDigest") is not None
            ):
                raise EvidenceError(f"{child}: invalid Custom fixture contract")
        elif mode == "design":
            instruction = take.get("designInstruction")
            digest = take.get("designInstructionDigest")
            if (
                take.get("customSpeakerID") is not None
                or not isinstance(instruction, str)
                or instruction != instruction.strip()
                or not 1 <= len(instruction) <= 240
                or digest != hashlib.sha256(instruction.encode("utf-8")).hexdigest()
            ):
                raise EvidenceError(f"{child}: invalid Design fixture contract")
        else:
            raise EvidenceError(f"{child}: unsupported language-benchmark mode")
        if kind == "languageBenchmark":
            if take.get("seedIndex") is not None or child != f"{run_id}--{take.get('cellID')}":
                raise EvidenceError(f"{child}: invalid normal benchmark take identity")
        else:
            seed_index = take.get("seedIndex")
            if isinstance(seed_index, bool) or not isinstance(seed_index, int) or seed_index < 0:
                raise EvidenceError(f"{child}: invalid cohort seed index")
            if child != f"{run_id}--{take.get('cellID')}--s{seed_index + 1:02d}":
                raise EvidenceError(f"{child}: invalid cohort take identity")
    if indexes != list(range(1, len(takes) + 1)):
        raise EvidenceError("language run plan take indexes are not contiguous and ordered")
    return takes


def validate_plan_against_sources(
    plan: dict[str, Any],
    *,
    matrix_path: Path,
    corpus_path: Path,
    subset: str,
    cohort_path: Path | None,
) -> list[dict[str, Any]]:
    """Rebuild the entire plan from tracked inputs and require byte-semantic equality."""
    validate_plan(plan)
    expected = build_plan(
        run_id=plan["runID"],
        matrix_path=matrix_path,
        corpus_path=corpus_path,
        subset=subset,
        cohort_path=cohort_path,
    )
    if plan != expected:
        raise EvidenceError("language run plan does not match its tracked matrix/corpus/cohort inputs")
    return plan["takes"]


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise EvidenceError(f"{path}:{line_number}: invalid JSON: {error}") from error
            if isinstance(value, dict):
                yield value


def exact_sentinels(source: Path, plan: dict[str, Any]) -> dict[str, tuple[Path, dict[str, Any]]]:
    takes = validate_plan(plan)
    expected = {take["childRunID"] for take in takes}
    matches: dict[str, list[Path]] = {child: [] for child in expected}
    unexpected: list[str] = []
    run_prefix = f"{plan['runID']}--"
    for path in source.rglob("device-diagnostics-done.json"):
        parent = path.parent.name
        if parent in expected:
            matches[parent].append(path)
        elif parent.startswith(run_prefix):
            unexpected.append(parent)
    if unexpected:
        raise EvidenceError(
            "unexpected current-run sentinels: " + ", ".join(sorted(set(unexpected)))
        )
    out: dict[str, tuple[Path, dict[str, Any]]] = {}
    failures: list[str] = []
    for child in sorted(expected):
        paths = matches[child]
        if len(paths) != 1:
            failures.append(f"{child}: expected 1 sentinel, got {len(paths)}")
            continue
        record = load_json(paths[0])
        if record.get("runID") != child:
            failures.append(f"{child}: sentinel runID mismatch")
            continue
        out[child] = (paths[0], record)
    if failures:
        raise EvidenceError("; ".join(failures))
    return out


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def verify_output_file(path: Path, record: dict[str, Any], child: str) -> dict[str, Any]:
    evidence = record.get("outputEvidence")
    if not isinstance(evidence, dict):
        raise EvidenceError(f"{child}: missing structured outputEvidence")
    if not path.is_file():
        raise EvidenceError(f"{child}: missing mirrored output.wav")
    digest = file_digest(path)
    byte_count = path.stat().st_size
    try:
        with wave.open(str(path), "rb") as stream:
            actual_sample_rate = stream.getframerate()
            actual_channels = stream.getnchannels()
            actual_frames = stream.getnframes()
    except (OSError, EOFError, wave.Error) as error:
        raise EvidenceError(f"{child}: mirrored output.wav is unreadable: {error}") from error
    actual_duration = actual_frames / actual_sample_rate if actual_sample_rate > 0 else 0
    if evidence.get("sha256") != digest:
        raise EvidenceError(f"{child}: output WAV SHA-256 mismatch")
    if evidence.get("artifactRelativePath") != "output.wav":
        raise EvidenceError(f"{child}: output artifact path is not the canonical output.wav")
    if evidence.get("byteCount") != byte_count:
        raise EvidenceError(f"{child}: output WAV byte count mismatch")
    for field in ("durationSeconds", "sampleRate"):
        if number(evidence.get(field)) is None or float(evidence[field]) <= 0:
            raise EvidenceError(f"{child}: invalid outputEvidence.{field}")
    for field in ("channelCount", "frameCount"):
        value = evidence.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise EvidenceError(f"{child}: invalid outputEvidence.{field}")
    if (
        int(float(evidence["sampleRate"])) != actual_sample_rate
        or evidence["channelCount"] != actual_channels
        or evidence["frameCount"] != actual_frames
        or not math.isclose(float(evidence["durationSeconds"]), actual_duration, rel_tol=1e-6, abs_tol=1e-6)
    ):
        raise EvidenceError(f"{child}: output WAV metadata mismatch")
    return {
        "relativePath": f"runs/{child}/output.wav",
        "sha256": digest,
        "byteCount": byte_count,
        "durationSeconds": float(evidence["durationSeconds"]),
        "sampleRate": float(evidence["sampleRate"]),
        "channelCount": evidence["channelCount"],
        "frameCount": evidence["frameCount"],
    }


def find_layer_jsonl(source: Path, layer: str) -> Path | None:
    direct = source / layer / "generations.jsonl"
    if direct.is_file():
        return direct
    matches = [path for path in source.rglob("generations.jsonl") if path.parent.name == layer]
    if len(matches) > 1:
        raise EvidenceError(f"found duplicate {layer} generations.jsonl files")
    return matches[0] if matches else None


def seed_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def telemetry_finish_succeeded(row: dict[str, Any]) -> bool:
    reason = row.get("finishReason")
    return isinstance(reason, str) and reason.lower() in {
        "eos", "completed", "complete", "done", "ok"
    }


def expected_language_hint_source(ui_hint: Any) -> str:
    return "auto" if ui_hint == "auto" else "explicit"


def valid_app_completion(row: dict[str, Any]) -> bool:
    frontend = row.get("frontendMetrics")
    if not isinstance(frontend, dict):
        return False
    completed_ms = frontend.get("submitToCompletedMS")
    return isinstance(completed_ms, (int, float)) and not isinstance(completed_ms, bool) and completed_ms > 0


def collect(
    source: Path,
    plan_path: Path,
    output: Path,
    *,
    matrix_path: Path | None = None,
    corpus_path: Path | None = None,
    subset: str | None = None,
    cohort_path: Path | None = None,
) -> dict[str, Any]:
    plan = load_json(plan_path)
    if matrix_path is not None and corpus_path is not None and subset is not None:
        takes = validate_plan_against_sources(
            plan,
            matrix_path=matrix_path,
            corpus_path=corpus_path,
            subset=subset,
            cohort_path=cohort_path,
        )
    else:
        takes = validate_plan(plan)
    sentinels = exact_sentinels(source, plan)
    generation_to_take: dict[str, dict[str, Any]] = {}
    run_entries: list[dict[str, Any]] = []

    temp_parent = output.parent
    temp_parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=temp_parent))
    try:
        for take in takes:
            child = take["childRunID"]
            sentinel_path, record = sentinels[child]
            generation_id = record.get("generationID")
            if not isinstance(generation_id, str) or not generation_id:
                raise EvidenceError(f"{child}: missing generationID")
            if generation_id in generation_to_take:
                raise EvidenceError(f"duplicate generationID {generation_id}")
            generation_to_take[generation_id] = take
            if record.get("mode") != take.get("mode") or record.get("variant") != take.get("variant"):
                raise EvidenceError(f"{child}: sentinel mode/variant mismatch")
            if seed_value(record.get("seed")) != take.get("seed"):
                raise EvidenceError(f"{child}: sentinel seed does not match the declared plan")
            if record.get("samplingVariation") != take.get("samplingVariation"):
                raise EvidenceError(f"{child}: sentinel sampling variation does not match the plan")
            requested_hint = take.get("uiHint", "auto")
            if record.get("requestedLanguageHint") != requested_hint:
                raise EvidenceError(f"{child}: sentinel requested language hint does not match the plan")
            if record.get("languageHintSource") != expected_language_hint_source(requested_hint):
                raise EvidenceError(f"{child}: sentinel language-hint source does not match the plan")
            if take["mode"] == "custom" and record.get("customSpeakerID") != take.get("customSpeakerID"):
                raise EvidenceError(f"{child}: sentinel Custom speaker does not match the plan")
            if take["mode"] == "design" and record.get("fixtureDigest") != take.get("designInstructionDigest"):
                raise EvidenceError(f"{child}: sentinel Design instruction does not match the plan")

            run_dir = temp / "runs" / child
            run_dir.mkdir(parents=True)
            shutil.copy2(sentinel_path, run_dir / "device-diagnostics-done.json")
            for name in ("native-events.jsonl", "memory-contexts.jsonl", "manifest.json"):
                candidate = sentinel_path.parent / name
                if candidate.is_file():
                    shutil.copy2(candidate, run_dir / name)

            output_summary = None
            if record.get("status") == "ok":
                output_summary = verify_output_file(sentinel_path.parent / "output.wav", record, child)
                shutil.copy2(sentinel_path.parent / "output.wav", run_dir / "output.wav")
            run_entries.append(
                {
                    "takeIndex": take["takeIndex"],
                    "childRunID": child,
                    "cellID": take["cellID"],
                    "seed": take.get("seed"),
                    "generationID": generation_id,
                    "status": record.get("status"),
                    "sentinelSHA256": file_digest(sentinel_path),
                    "output": output_summary,
                }
            )

        expected_generations = set(generation_to_take)
        for layer in ("engine", "app"):
            jsonl = find_layer_jsonl(source, layer)
            if jsonl is None:
                raise EvidenceError(f"missing {layer}/generations.jsonl")
            by_generation: dict[str, list[dict[str, Any]]] = {
                generation: [] for generation in expected_generations
            }
            unexpected: list[str] = []
            for row in iter_jsonl(jsonl):
                generation = row.get("generationID")
                notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
                if generation in expected_generations:
                    by_generation[generation].append(row)
                elif notes.get("benchRunID") == plan["runID"]:
                    unexpected.append(str(generation))
            if unexpected:
                raise EvidenceError(f"{layer}: unexpected current-run generation rows: {unexpected}")

            selected: list[dict[str, Any]] = []
            for take in takes:
                generation = run_entries[take["takeIndex"] - 1]["generationID"]
                matches = by_generation[generation]
                if len(matches) != 1:
                    raise EvidenceError(
                        f"{layer}: generation {generation} expected 1 row, got {len(matches)}"
                    )
                row = matches[0]
                notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
                if not isinstance(row.get("schemaVersion"), int) or row["schemaVersion"] < 7:
                    raise EvidenceError(
                        f"{layer}: generation {generation} is older than telemetry schema v7"
                    )
                if row.get("layer") != layer:
                    raise EvidenceError(
                        f"{layer}: generation {generation} declares layer {row.get('layer')!r}"
                    )
                if notes.get("benchRunID") != plan["runID"] or notes.get("benchCell") != take["cellID"]:
                    raise EvidenceError(f"{layer}: generation {generation} has wrong run/cell correlation")
                if row.get("mode") != take["mode"]:
                    raise EvidenceError(f"{layer}: generation {generation} has wrong mode")
                if not telemetry_finish_succeeded(row):
                    raise EvidenceError(f"{layer}: generation {generation} did not finish successfully")
                if layer == "engine":
                    if seed_value(notes.get("samplingSeed")) != take["seed"]:
                        raise EvidenceError(f"{layer}: generation {generation} lacks exact samplingSeed proof")
                    if notes.get("samplingVariation") != take.get("samplingVariation"):
                        raise EvidenceError(f"{layer}: generation {generation} lacks exact samplingVariation proof")
                elif not valid_app_completion(row):
                    raise EvidenceError(
                        f"app: generation {generation} lacks a positive submitToCompletedMS"
                    )
                selected.append(row)

            layer_dir = temp / layer
            layer_dir.mkdir(parents=True)
            with (layer_dir / "generations.jsonl").open("w", encoding="utf-8") as handle:
                for row in selected:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            for generation in expected_generations:
                samples = jsonl.parent / f"samples-{generation}.jsonl"
                if samples.is_file():
                    shutil.copy2(samples, layer_dir / samples.name)

        manifest: dict[str, Any] = {
            "schemaVersion": 1,
            "runID": plan["runID"],
            "planDigest": plan["planDigest"],
            "takeCount": len(run_entries),
            "takes": run_entries,
        }
        manifest["manifestDigest"] = canonical_digest(manifest)
        with (temp / "collection-manifest.json").open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
        shutil.copy2(plan_path, temp / "language-run-plan.json")

        if output.exists():
            shutil.rmtree(output)
        os.replace(temp, output)
        return manifest
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def write_json_atomic(path: Path, value: Any) -> None:
    jsonio.atomic_json(path, value, ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="write a predeclared language-run plan")
    plan_parser.add_argument("--run-id", required=True)
    plan_parser.add_argument("--matrix", type=Path, required=True)
    plan_parser.add_argument("--corpus", type=Path, required=True)
    plan_parser.add_argument("--subset", choices=("quick", "full"), required=True)
    plan_parser.add_argument("--cohort", type=Path)
    plan_parser.add_argument("--output", type=Path, required=True)

    collect_parser = subparsers.add_parser("collect", help="collect exact run-scoped evidence")
    collect_parser.add_argument("--source", type=Path, required=True)
    collect_parser.add_argument("--plan", type=Path, required=True)
    collect_parser.add_argument("--output", type=Path, required=True)
    collect_parser.add_argument("--matrix", type=Path, required=True)
    collect_parser.add_argument("--corpus", type=Path, required=True)
    collect_parser.add_argument("--subset", choices=("quick", "full"), required=True)
    collect_parser.add_argument("--cohort", type=Path)

    validate_parser = subparsers.add_parser("validate-plan", help="validate a plan offline")
    validate_parser.add_argument("plan", type=Path)
    validate_parser.add_argument("--matrix", type=Path, required=True)
    validate_parser.add_argument("--corpus", type=Path, required=True)
    validate_parser.add_argument("--subset", choices=("quick", "full"), required=True)
    validate_parser.add_argument("--cohort", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "plan":
            plan = build_plan(
                run_id=args.run_id,
                matrix_path=args.matrix,
                corpus_path=args.corpus,
                subset=args.subset,
                cohort_path=args.cohort,
            )
            write_json_atomic(args.output, plan)
            print(f"plan={args.output} takes={plan['takeCount']} digest={plan['planDigest']}")
        elif args.command == "collect":
            manifest = collect(
                args.source,
                args.plan,
                args.output,
                matrix_path=args.matrix,
                corpus_path=args.corpus,
                subset=args.subset,
                cohort_path=args.cohort,
            )
            print(
                f"evidence={args.output} takes={manifest['takeCount']} "
                f"digest={manifest['manifestDigest']}"
            )
        else:
            validate_plan_against_sources(
                load_json(args.plan),
                matrix_path=args.matrix,
                corpus_path=args.corpus,
                subset=args.subset,
                cohort_path=args.cohort,
            )
            print("PASS")
    except (EvidenceError, OSError, json.JSONDecodeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
