#!/usr/bin/env python3
"""Source-bound Clone identity/language and French Voice Design diagnostics.

Personal audio, transcript text, absolute paths, generated audio, and raw errors
remain below an untracked run directory. Public JSON contains only stable aliases,
digests, counts, typed outcomes, and aggregate metrics. Generation is serial and
resumable; a failed row is retained and is never retried or replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from typing import Any

from check_language_output import audio_edge_evidence_issues


REPO = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = REPO / "config/voice-identity-language-reliability.json"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,95}\Z")
TERMINAL_STATUSES = {"PASS", "HARD_FAILURE", "BLOCKED_PREREQUISITE"}


class ReliabilityError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReliabilityError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise ReliabilityError(f"{path.name} must contain a JSON object")
    return value


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ReliabilityError(f"observations JSONL is corrupt at line {line_number}") from error
        if not isinstance(row, dict):
            raise ReliabilityError(f"observation {line_number} is not an object")
        rows.append(row)
    return rows


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("schemaVersion") != 1:
        raise ReliabilityError("reliability contract schemaVersion must be 1")
    aliases = contract.get("requiredReferenceAliases")
    if not isinstance(aliases, dict) or set(aliases.values()) != {"user", "control"}:
        raise ReliabilityError("contract reference aliases are incomplete")
    seeds = contract.get("fixedSeeds")
    if (
        not isinstance(seeds, list) or len(seeds) != 8
        or len(set(seeds)) != len(seeds)
        or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds)
    ):
        raise ReliabilityError("contract must declare eight unique UInt64 seeds")
    tokenizers = contract.get("tokenizerArms")
    if not isinstance(tokenizers, dict) or set(tokenizers) != {"current-fp16", "archived-fp32"}:
        raise ReliabilityError("contract tokenizer arms are incomplete")
    for arm, value in tokenizers.items():
        if (
            not isinstance(value, dict) or not HEX64.fullmatch(str(value.get("sha256", "")))
            or not isinstance(value.get("sizeBytes"), int) or value["sizeBytes"] <= 0
        ):
            raise ReliabilityError(f"{arm}: tokenizer identity is malformed")


def wav_metadata(path: Path) -> dict[str, Any]:
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            channels = handle.getnchannels()
            width = handle.getsampwidth()
    except (wave.Error, OSError) as error:
        raise ReliabilityError("reference audio must be a readable PCM WAV") from error
    if frames <= 0 or rate <= 0 or channels <= 0 or width not in {1, 2, 3, 4}:
        raise ReliabilityError("reference WAV metadata is invalid")
    return {
        "durationSeconds": round(frames / rate, 6),
        "sampleRate": rate,
        "channels": channels,
        "sampleWidthBytes": width,
        "frameCount": frames,
    }


def normalized_transcript(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ReliabilityError("a transcript input is unreadable") from error
    return text or None


def prepare_bundle(*, input_spec_path: Path, output: Path, contract: dict[str, Any]) -> dict[str, Any]:
    validate_contract(contract)
    if output.exists():
        raise ReliabilityError("bundle output already exists; use a new run directory")
    spec = load_json(input_spec_path)
    if spec.get("schemaVersion") != 1:
        raise ReliabilityError("private input spec schemaVersion must be 1")
    run_id = spec.get("runID")
    if not isinstance(run_id, str) or not SAFE_ID.fullmatch(run_id):
        raise ReliabilityError("private input spec has an invalid runID")
    references = spec.get("references")
    if not isinstance(references, list):
        raise ReliabilityError("private input spec references must be an array")
    expected_aliases = contract["requiredReferenceAliases"]
    by_alias = {row.get("alias"): row for row in references if isinstance(row, dict)}
    if set(by_alias) != set(expected_aliases) or len(by_alias) != len(references):
        raise ReliabilityError("private input spec must provide every required alias exactly once")

    private_root = output / "private"
    audio_root = private_root / "audio"
    transcript_root = private_root / "transcripts"
    audio_root.mkdir(parents=True)
    transcript_root.mkdir(parents=True)
    public_rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    for alias in expected_aliases:
        row = by_alias[alias]
        if row.get("role") != expected_aliases[alias]:
            raise ReliabilityError(f"{alias}: role does not match the tracked contract")
        audio_source = Path(str(row.get("audioPath", ""))).expanduser()
        if not audio_source.is_file():
            raise ReliabilityError(f"{alias}: reference audio is missing")
        digest = file_digest(audio_source)
        destination = audio_root / f"{digest}.wav"
        if not destination.exists():
            shutil.copy2(audio_source, destination)
        metadata = wav_metadata(destination)
        transcripts: dict[str, Any] = {}
        private_transcripts: dict[str, str | None] = {}
        for arm, key in (("reviewed", "reviewedTranscriptPath"), ("corrected", "correctedTranscriptPath")):
            raw_path = row.get(key)
            text = normalized_transcript(Path(str(raw_path)).expanduser() if raw_path else None)
            if text is None:
                transcripts[arm] = None
                private_transcripts[arm] = None
                continue
            transcript_sha = text_digest(text)
            transcript_destination = transcript_root / f"{transcript_sha}.txt"
            if not transcript_destination.exists():
                transcript_destination.write_text(text + "\n", encoding="utf-8")
            transcripts[arm] = {"sha256": transcript_sha, "characters": len(text)}
            private_transcripts[arm] = str(transcript_destination.relative_to(output))
        language = str(row.get("referenceLanguage", "auto")).lower()
        if language not in {"auto", "english", "french", "chinese", "japanese", "korean", "german", "spanish", "italian", "portuguese", "russian"}:
            raise ReliabilityError(f"{alias}: unsupported reference language")
        public_rows.append({
            "alias": alias,
            "role": expected_aliases[alias],
            "audioSHA256": digest,
            "audioBytes": destination.stat().st_size,
            **metadata,
            "referenceLanguage": language,
            "transcripts": transcripts,
        })
        private_rows.append({
            "alias": alias,
            "audio": str(destination.relative_to(output)),
            "transcripts": private_transcripts,
        })

    raw_profiles = spec.get("runtimeProfiles")
    if not isinstance(raw_profiles, dict) or "current-fp16" not in raw_profiles:
        raise ReliabilityError("private input spec requires the current-fp16 runtime profile")
    public_profiles: dict[str, Any] = {}
    private_profiles: dict[str, Any] = {}
    for arm, identity in contract["tokenizerArms"].items():
        raw = raw_profiles.get(arm)
        if raw is None:
            public_profiles[arm] = {"available": False, "tokenizerSHA256": identity["sha256"]}
            continue
        if not isinstance(raw, dict) or not raw.get("dataDir"):
            raise ReliabilityError(f"{arm}: runtime profile must provide dataDir")
        data_dir = Path(str(raw["dataDir"])).expanduser()
        if not data_dir.is_dir():
            raise ReliabilityError(f"{arm}: runtime data directory does not exist")
        matches = [
            path for path in data_dir.rglob("model.safetensors")
            if path.parent.name == "speech_tokenizer"
            and path.stat().st_size == identity["sizeBytes"]
            and file_digest(path) == identity["sha256"]
        ]
        if not matches:
            raise ReliabilityError(f"{arm}: pinned tokenizer was not found in the runtime root")
        public_profiles[arm] = {"available": True, "tokenizerSHA256": identity["sha256"]}
        private_profiles[arm] = {"dataDir": str(data_dir)}

    public_body = {
        "schemaVersion": 1,
        "runID": run_id,
        "references": public_rows,
        "runtimeProfiles": public_profiles,
        "contractSHA256": canonical_digest(contract),
    }
    public_manifest = {**public_body, "bundleDigest": canonical_digest(public_body)}
    private_manifest = {
        "schemaVersion": 1,
        "runID": run_id,
        "references": private_rows,
        "runtimeProfiles": private_profiles,
        "publicBundleDigest": public_manifest["bundleDigest"],
    }
    atomic_json(output / "bundle-manifest.json", public_manifest)
    atomic_json(private_root / "bundle-private.json", private_manifest)
    return public_manifest


def resolve_scripts(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    control = load_json(REPO / "config/ios-control-audit-corpus.json")["scripts"]
    bench_rows = load_json(REPO / "config/language-bench-corpus.json")["languages"]
    bench = {row["id"]: row["script"] for row in bench_rows}
    resolved: dict[str, dict[str, Any]] = {}
    for script_id, spec in contract["scripts"].items():
        language = spec["language"]
        source = spec["source"]
        if source.endswith("ios-control-audit-corpus.json"):
            text = control[language][spec["length"]]
        elif source.endswith("language-bench-corpus.json"):
            text = bench[language]
        else:
            raise ReliabilityError(f"{script_id}: unsupported corpus source")
        normalized = text.strip()
        resolved[script_id] = {
            "language": language,
            "length": spec["length"],
            "text": normalized,
            "sha256": text_digest(normalized),
            "characters": len(normalized),
        }
    return resolved


def tree_fingerprint() -> str:
    process = subprocess.run(
        [sys.executable, str(REPO / "scripts/tree_fingerprint.py"), "--root", str(REPO)],
        capture_output=True, text=True, check=False,
    )
    value = process.stdout.strip()
    if process.returncode or not HEX64.fullmatch(value):
        raise ReliabilityError("repository tree fingerprint failed")
    return value


def _row(row_id: str, **values: Any) -> dict[str, Any]:
    body = {"takeID": row_id, **values}
    return {**body, "rowDigest": canonical_digest(body)}


def build_plan(*, contract: dict[str, Any], bundle: dict[str, Any], source_identity: str | None = None) -> dict[str, Any]:
    validate_contract(contract)
    if bundle.get("contractSHA256") != canonical_digest(contract):
        raise ReliabilityError("bundle was prepared against a different contract")
    unsigned_bundle = dict(bundle)
    bundle_digest = unsigned_bundle.pop("bundleDigest", None)
    if bundle_digest != canonical_digest(unsigned_bundle):
        raise ReliabilityError("bundle manifest digest mismatch")
    references = {row["alias"]: row for row in bundle.get("references", [])}
    if set(references) != set(contract["requiredReferenceAliases"]):
        raise ReliabilityError("bundle reference aliases do not match the contract")
    scripts = resolve_scripts(contract)
    sys.path.insert(0, str(REPO / "scripts"))
    from check_delivery_instructions import load_presets
    presets = load_presets(REPO)
    seeds = contract["fixedSeeds"]
    tokenizer_arms = list(contract["tokenizerArms"])
    rows: list[dict[str, Any]] = []

    def clone_rows(aliases: list[str], seed_values: list[int], cohort: str) -> None:
        for alias in aliases:
            reference = references[alias]
            for transcript_arm in contract["clone"]["transcriptArms"]:
                transcript = None if transcript_arm == "audio-only" else reference["transcripts"].get(transcript_arm)
                for script_id in contract["clone"]["scriptIDs"]:
                    script = scripts[script_id]
                    for selection in contract["clone"]["languageSelections"]:
                        for tokenizer in tokenizer_arms:
                            for seed in seed_values:
                                blocked = None
                                if transcript_arm != "audio-only" and transcript is None:
                                    blocked = f"{transcript_arm}-transcript-missing"
                                if not bundle["runtimeProfiles"][tokenizer]["available"]:
                                    blocked = f"{tokenizer}-runtime-unavailable"
                                take_id = (
                                    f"clone-{cohort}-{alias}-{transcript_arm}-{script_id}-"
                                    f"{selection}-{tokenizer}-s{seed}"
                                )
                                rows.append(_row(
                                    take_id,
                                    cohort=cohort, mode="clone", referenceAlias=alias,
                                    transcriptArm=transcript_arm,
                                    transcriptDigest=transcript.get("sha256") if transcript else None,
                                    referenceLanguage=reference["referenceLanguage"],
                                    scriptID=script_id, scriptDigest=script["sha256"],
                                    targetLanguage=script["language"], languageSelection=selection,
                                    expectedStoredLanguage="auto" if selection == "auto" else script["language"],
                                    expectedFinalLanguage=script["language"], tokenizerArm=tokenizer,
                                    expectedTokenizerDigest=contract["tokenizerArms"][tokenizer]["sha256"],
                                    seed=seed, variation=contract["clone"]["primaryVariation"],
                                    warmState="observed", blockedPrerequisite=blocked,
                                ))

    clone_rows(contract["clone"]["coreReferenceAliases"], seeds, "core")
    clone_rows(contract["clone"]["controlReferenceAliases"], [seeds[0]], "control")
    for alias in contract["requiredReferenceAliases"]:
        reference = references[alias]
        script_id = "french-medium" if reference["referenceLanguage"] == "french" else "english-medium"
        script = scripts[script_id]
        for warm_state in ("cold", "warm"):
            take_id = f"clone-sentinel-{alias}-{warm_state}"
            transcript = reference["transcripts"].get("reviewed")
            rows.append(_row(
                take_id, cohort="sentinel", mode="clone", referenceAlias=alias,
                transcriptArm="reviewed", transcriptDigest=transcript.get("sha256") if transcript else None,
                referenceLanguage=reference["referenceLanguage"], scriptID=script_id,
                scriptDigest=script["sha256"], targetLanguage=script["language"],
                languageSelection="explicit", expectedStoredLanguage=script["language"],
                expectedFinalLanguage=script["language"], tokenizerArm="current-fp16",
                expectedTokenizerDigest=contract["tokenizerArms"]["current-fp16"]["sha256"],
                seed=seeds[0], variation=contract["clone"]["sentinelVariation"],
                warmState=warm_state,
                blockedPrerequisite="reviewed-transcript-missing" if transcript is None else None,
            ))

    design = contract["voiceDesign"]
    for script_id in design["scriptIDs"]:
        script = scripts[script_id]
        for selection in design["languageSelections"]:
            for delivery_arm in design["deliveryArms"]:
                for tokenizer in tokenizer_arms:
                    for seed in seeds:
                        blocked = None if bundle["runtimeProfiles"][tokenizer]["available"] else f"{tokenizer}-runtime-unavailable"
                        cell = design["deliveryCells"][delivery_arm]
                        delivery = None
                        if cell is not None:
                            preset_id, tier = cell.split(".", 1)
                            delivery = presets[preset_id][tier]
                        instruction = design_instruction(design["voiceBrief"], delivery)
                        take_id = f"design-core-{script_id}-{selection}-{delivery_arm}-{tokenizer}-s{seed}"
                        rows.append(_row(
                            take_id, cohort="core", mode="design", referenceAlias=None,
                            transcriptArm=None, transcriptDigest=None, referenceLanguage=None,
                            scriptID=script_id, scriptDigest=script["sha256"],
                            targetLanguage="french", languageSelection=selection,
                            expectedStoredLanguage="auto" if selection == "auto" else "french",
                            expectedFinalLanguage="french", deliveryArm=delivery_arm,
                            deliveryCellID=cell,
                            expectedInstructionDigest=text_digest(instruction),
                            expectedInstructionLanguage="english",
                            tokenizerArm=tokenizer,
                            expectedTokenizerDigest=contract["tokenizerArms"][tokenizer]["sha256"],
                            seed=seed, variation=design["primaryVariation"], warmState="observed",
                            blockedPrerequisite=blocked,
                        ))
    for script_id in design["scriptIDs"]:
        script = scripts[script_id]
        sentinel_cell = design["deliveryCells"]["current-neutral"]
        sentinel_preset_id, sentinel_tier = sentinel_cell.split(".", 1)
        sentinel_instruction = design_instruction(
            design["voiceBrief"], presets[sentinel_preset_id][sentinel_tier]
        )
        for warm_state in ("cold", "warm"):
            rows.append(_row(
                f"design-sentinel-{script_id}-{warm_state}",
                cohort="sentinel", mode="design", referenceAlias=None,
                transcriptArm=None, transcriptDigest=None, referenceLanguage=None,
                scriptID=script_id, scriptDigest=script["sha256"], targetLanguage="french",
                languageSelection="explicit", expectedStoredLanguage="french",
                expectedFinalLanguage="french", deliveryArm="current-neutral",
                deliveryCellID=sentinel_cell,
                expectedInstructionDigest=text_digest(sentinel_instruction),
                expectedInstructionLanguage="english",
                tokenizerArm="current-fp16",
                expectedTokenizerDigest=contract["tokenizerArms"]["current-fp16"]["sha256"],
                seed=seeds[0], variation=design["sentinelVariation"], warmState=warm_state,
                blockedPrerequisite=None,
            ))

    body = {
        "schemaVersion": 1,
        "kind": "voice-identity-language-reliability-plan",
        "runID": bundle["runID"],
        "sourceIdentity": source_identity or tree_fingerprint(),
        "contractDigest": canonical_digest(contract),
        "bundleDigest": bundle["bundleDigest"],
        "seedPolicy": "fixed-eight-v1-no-substitution",
        "takeCount": len(rows),
        "takes": rows,
    }
    return {**body, "planDigest": canonical_digest(body)}


def validate_plan(
    plan: dict[str, Any], contract: dict[str, Any], bundle: dict[str, Any],
    expected_source_identity: str | None = None,
) -> None:
    body = dict(plan)
    stored_digest = body.pop("planDigest", None)
    if stored_digest != canonical_digest(body):
        raise ReliabilityError("plan digest mismatch")
    if plan.get("schemaVersion") != 1 or plan.get("kind") != "voice-identity-language-reliability-plan":
        raise ReliabilityError("unsupported reliability plan")
    expected_source = expected_source_identity or tree_fingerprint()
    if plan.get("sourceIdentity") != expected_source:
        raise ReliabilityError("plan source identity differs from the current repository tree")
    if plan.get("contractDigest") != canonical_digest(contract) or plan.get("bundleDigest") != bundle.get("bundleDigest"):
        raise ReliabilityError("plan source contracts differ from current inputs")
    takes = plan.get("takes")
    if not isinstance(takes, list) or len(takes) != plan.get("takeCount") or not takes:
        raise ReliabilityError("plan take coverage is incomplete")
    identities: set[str] = set()
    for row in takes:
        if not isinstance(row, dict) or not SAFE_ID.fullmatch(str(row.get("takeID", ""))):
            raise ReliabilityError("plan contains an invalid take identity")
        if row["takeID"] in identities:
            raise ReliabilityError("plan contains duplicate take identities")
        identities.add(row["takeID"])
        row_body = dict(row)
        row_digest = row_body.pop("rowDigest", None)
        if row_digest != canonical_digest(row_body):
            raise ReliabilityError(f"{row['takeID']}: row digest mismatch")
        if row.get("seed") not in contract["fixedSeeds"]:
            raise ReliabilityError(f"{row['takeID']}: seed is not frozen")
        if row.get("expectedTokenizerDigest") != contract["tokenizerArms"][row["tokenizerArm"]]["sha256"]:
            raise ReliabilityError(f"{row['takeID']}: tokenizer identity drift")


def _trim_terminal_punctuation(value: str) -> str:
    return value.strip().rstrip(".!?。！？").rstrip()


def design_instruction(brief: str, delivery: str | None) -> str:
    description = _trim_terminal_punctuation(brief)
    if delivery is None:
        return description
    return (
        f"Voice character: {description}. "
        f"Delivery: {_trim_terminal_punctuation(delivery)}."
    )


def build_device_plan(
    *, contract: dict[str, Any], run_id: str,
    profile: str = "focused",
    source_identity: str | None = None,
) -> dict[str, Any]:
    validate_contract(contract)
    if not SAFE_ID.fullmatch(run_id):
        raise ReliabilityError("device runID is invalid")
    if profile not in {"closure", "focused", "characterization"}:
        raise ReliabilityError(
            "device profile must be closure, focused, or characterization"
        )
    scripts = resolve_scripts(contract)
    sys.path.insert(0, str(REPO / "scripts"))
    from check_delivery_instructions import load_presets
    presets = load_presets(REPO)
    tokenizer = contract["tokenizerArms"]["current-fp16"]["sha256"]
    seeds = contract["fixedSeeds"]
    rows: list[dict[str, Any]] = []

    def add(row_id: str, **values: Any) -> None:
        index = len(rows) + 1
        child = f"{run_id}-t{index:02d}-{canonical_digest(row_id)[:8]}"
        rows.append(_row(row_id, childRunID=child, **values))

    def add_clone(alias: str, script_id: str, selection: str, seed: int, variation: str) -> None:
        script = scripts[script_id]
        add(
            f"device-clone-{alias}-{script_id}-{selection}-{seed}-{variation}",
            mode="clone", referenceAlias=alias,
            scriptID=script_id, scriptDigest=script["sha256"],
            targetLanguage=script["language"], languageSelection=selection,
            expectedStoredLanguage="auto" if selection == "auto" else script["language"],
            expectedFinalLanguage=script["language"],
            expectedConditioningMode="clone_transcript_backed",
            expectedTokenizerDigest=tokenizer,
            seed=seed, variation=variation,
            deliveryArm=None, deliveryInstruction=None,
            expectedInstructionDigest=None,
            expectedInstructionLanguage=None,
        )

    clone = contract["clone"]
    if profile in {"closure", "focused"}:
        for alias in clone["coreReferenceAliases"]:
            for script_id in clone["scriptIDs"]:
                for selection in clone["languageSelections"]:
                    add_clone(alias, script_id, selection, seeds[0], clone["primaryVariation"])
    else:
        for alias in clone["coreReferenceAliases"]:
            for script_id in clone["scriptIDs"]:
                for seed in seeds:
                    add_clone(alias, script_id, "auto", seed, clone["primaryVariation"])
                add_clone(alias, script_id, "explicit", seeds[0], clone["primaryVariation"])
            add_clone(alias, clone["scriptIDs"][0], "explicit", seeds[0], clone["sentinelVariation"])

    design = contract["voiceDesign"]
    def add_design(script_id: str, selection: str, arm: str, seed: int, variation: str) -> None:
        script = scripts[script_id]
        cell = design["deliveryCells"][arm]
        delivery = None
        if cell is not None:
            preset_id, tier = cell.split(".", 1)
            delivery = presets[preset_id][tier]
        instruction = design_instruction(design["voiceBrief"], delivery)
        add(
            f"device-design-{script_id}-{selection}-{arm}-{seed}-{variation}",
            mode="design", referenceAlias=None,
            scriptID=script_id, scriptDigest=script["sha256"],
            targetLanguage="french", languageSelection=selection,
            expectedStoredLanguage="auto" if selection == "auto" else "french",
            expectedFinalLanguage="french",
            expectedConditioningMode="voice_design",
            expectedTokenizerDigest=tokenizer,
            seed=seed, variation=variation,
            deliveryArm=arm, deliveryInstruction=delivery,
            expectedInstructionDigest=text_digest(instruction),
            expectedInstructionLanguage="english",
        )

    if profile in {"closure", "focused"}:
        for script_id in design["scriptIDs"]:
            for selection in design["languageSelections"]:
                arms = (
                    ["current-neutral"]
                    if profile == "closure"
                    else design["deliveryArms"]
                )
                for arm in arms:
                    add_design(script_id, selection, arm, seeds[0], design["primaryVariation"])
    else:
        for script_id in design["scriptIDs"]:
            for arm in design["deliveryArms"]:
                for seed in seeds:
                    add_design(script_id, "auto", arm, seed, design["primaryVariation"])
                add_design(script_id, "explicit", arm, seeds[0], design["primaryVariation"])
        for arm in design["deliveryArms"]:
            add_design(
                design["scriptIDs"][1], "explicit", arm, seeds[0],
                design["sentinelVariation"],
            )

    body = {
        "schemaVersion": 2,
        "kind": "voice-identity-language-device-plan",
        "profile": profile,
        "runID": run_id,
        "sourceIdentity": source_identity or tree_fingerprint(),
        "contractDigest": canonical_digest(contract),
        "seedPolicy": (
            "fixed-closure-v2-no-retry" if profile == "closure"
            else "fixed-focused-v2-no-retry" if profile == "focused"
            else "fixed-eight-characterization-v2-no-retry"
        ),
        "takeCount": len(rows),
        "takes": rows,
    }
    return {**body, "planDigest": canonical_digest(body)}


def validate_device_plan(
    plan: dict[str, Any], contract: dict[str, Any],
    expected_source_identity: str | None = None,
) -> None:
    body = dict(plan)
    digest = body.pop("planDigest", None)
    if digest != canonical_digest(body):
        raise ReliabilityError("device plan digest mismatch")
    schema = plan.get("schemaVersion")
    if (
        schema not in {1, 2}
        or plan.get("kind") != "voice-identity-language-device-plan"
        or plan.get("contractDigest") != canonical_digest(contract)
    ):
        raise ReliabilityError("unsupported device reliability plan")
    expected_source = expected_source_identity or tree_fingerprint()
    if plan.get("sourceIdentity") != expected_source:
        raise ReliabilityError("device plan source identity differs from the current repository tree")
    takes = plan.get("takes")
    profile = "focused" if schema == 1 else plan.get("profile")
    expected_count = (
        14 if profile == "closure"
        else 26 if profile == "focused"
        else 122 if profile == "characterization"
        else None
    )
    if (
        expected_count is None
        or not isinstance(takes, list)
        or len(takes) != expected_count
        or plan.get("takeCount") != expected_count
    ):
        raise ReliabilityError("device plan does not contain its exact governed profile")
    seen: set[str] = set()
    children: set[str] = set()
    for row in takes:
        row_body = dict(row)
        row_digest = row_body.pop("rowDigest", None)
        if row_digest != canonical_digest(row_body):
            raise ReliabilityError(f"{row.get('takeID')}: device row digest mismatch")
        if row.get("takeID") in seen or row.get("childRunID") in children:
            raise ReliabilityError("device plan contains duplicate identities")
        seen.add(row["takeID"])
        children.add(row["childRunID"])
        allowed_seeds = (
            {contract["fixedSeeds"][0]}
            if profile in {"closure", "focused"}
            else set(contract["fixedSeeds"])
        )
        if row.get("seed") not in allowed_seeds:
            raise ReliabilityError(f"{row['takeID']}: device seed drift")
        if row.get("expectedTokenizerDigest") != contract["tokenizerArms"]["current-fp16"]["sha256"]:
            raise ReliabilityError(f"{row['takeID']}: device tokenizer drift")
    if schema == 2:
        expected = build_device_plan(
            contract=contract,
            run_id=plan["runID"],
            profile=profile,
            source_identity=plan["sourceIdentity"],
        )
        if plan != expected:
            raise ReliabilityError("device plan differs from its exact governed profile")


def load_private_device_map(path: Path, plan: dict[str, Any], contract: dict[str, Any]) -> dict[str, str]:
    value = load_json(path)
    if value.get("schemaVersion") != 1 or value.get("planDigest") != plan.get("planDigest"):
        raise ReliabilityError("private device map belongs to another plan")
    rows = value.get("references")
    if not isinstance(rows, list):
        raise ReliabilityError("private device map references must be an array")
    expected = set(contract["clone"]["coreReferenceAliases"])
    resolved: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ReliabilityError("private device map row is malformed")
        alias = row.get("alias")
        voice_id = row.get("voiceID")
        if alias not in expected or alias in resolved:
            raise ReliabilityError("private device map aliases are invalid")
        if not isinstance(voice_id, str) or not voice_id.strip() or len(voice_id) > 128:
            raise ReliabilityError(f"{alias}: private saved-voice ID is invalid")
        resolved[alias] = voice_id.strip()
    if set(resolved) != expected:
        raise ReliabilityError("private device map must contain both user reference aliases")
    return resolved


def compose_device_results(
    *, plan: dict[str, Any], contract: dict[str, Any],
    diagnostics_root: Path, transcription: Path, output: Path,
) -> dict[str, Any]:
    validate_device_plan(plan, contract)
    transcription_value = load_json(transcription)
    expected_aliases = set(contract["clone"]["coreReferenceAliases"])
    transcription_rows = transcription_value.get("references") or []
    observed_aliases = {row.get("alias") for row in transcription_rows if isinstance(row, dict)}
    if transcription_value.get("schemaVersion") != 1 or observed_aliases != expected_aliases:
        raise ReliabilityError("typed transcription evidence is incomplete or cross-run")

    public_transcription = []
    for row in transcription_rows:
        automatic = row.get("automaticTranscription") or {}
        public_transcription.append({
            "alias": row["alias"],
            "found": row.get("found") is True,
            "referenceAudioDigest": row.get("referenceAudioDigest"),
            "hasStoredTranscript": row.get("hasStoredTranscript"),
            "storedTranscriptDigest": row.get("storedTranscriptDigest"),
            "storedReferenceLanguage": row.get("storedReferenceLanguage"),
            "storedTranscriptSource": row.get("storedTranscriptSource"),
            "storedAutomaticTranscriptionOutcome": row.get("storedAutomaticTranscriptionOutcome"),
            "qualityWarnings": row.get("qualityWarnings") or [],
            "automaticOutcome": automatic.get("outcome"),
            "authorizationStatus": automatic.get("authorizationStatus"),
            "attemptedLocales": [
                {
                    "order": attempt.get("order"),
                    "localeIdentifier": attempt.get("localeIdentifier"),
                    "language": attempt.get("language"),
                    "status": attempt.get("status"),
                    "languageScore": attempt.get("languageScore"),
                    "averageConfidence": attempt.get("averageConfidence"),
                }
                for attempt in automatic.get("attempts", []) if isinstance(attempt, dict)
            ],
        })

    takes = []
    hard_failures = 0
    product_failures = 0
    harness_failures = 0
    audio_by_alias: dict[str, set[str]] = {}
    for row in plan["takes"]:
        matches = list(diagnostics_root.rglob(
            f"{row['childRunID']}/device-diagnostics-done.json"
        ))
        failures: list[str] = []
        evidence_gaps: list[str] = []
        root_cause: str | None = None
        failure_owner: str | None = None
        sentinel: dict[str, Any] = {}
        if len(matches) != 1:
            failures.append("missing-or-duplicate-sentinel")
            root_cause = "diagnostic_sentinel_unavailable"
            failure_owner = "harness"
        else:
            sentinel = load_json(matches[0])
            receipt_value = sentinel.get("requestReceipt")
            receipt = receipt_value if isinstance(receipt_value, dict) else {}
            common_expected = {
                "mode": row["mode"],
                "seed": row["seed"],
                "samplingVariation": row["variation"],
            }
            for key, expected_value in common_expected.items():
                if sentinel.get(key) != expected_value:
                    failures.append(f"sentinel-{key}-mismatch")
            if sentinel.get("status") == "ok":
                if sentinel.get("resolvedLanguageHint") != row["expectedFinalLanguage"]:
                    failures.append("sentinel-resolvedLanguageHint-mismatch")
                receipt_expected = {
                    "schemaVersion": 2,
                    "storedLanguageSelection": row["expectedStoredLanguage"],
                    "detectedTargetLanguage": row["targetLanguage"],
                    "finalModelLanguage": row["expectedFinalLanguage"],
                    "conditioningMode": row["expectedConditioningMode"],
                    "targetTextDigest": row["scriptDigest"],
                    "speechTokenizerDigest": row["expectedTokenizerDigest"],
                    "instructionDigest": row.get("expectedInstructionDigest"),
                    "modelFacingInstructionLanguage": row.get("expectedInstructionLanguage"),
                }
                for key, expected_value in receipt_expected.items():
                    if receipt.get(key) != expected_value:
                        failures.append(f"receipt-{key}-mismatch")
                verification = sentinel.get("outputVerification") or {}
                verification_failure = "successful_take_evidence_mismatch"
                verification_owner = "harness"
                edge_issues = audio_edge_evidence_issues(
                    verification, output_evidence=sentinel.get("outputEvidence"))
                already_classified_coverage_failure = (
                    verification.get("pass") is not True
                    and verification.get("skipReason")
                    == "speech_recognition_incomplete_temporal_coverage"
                )
                if edge_issues and not already_classified_coverage_failure:
                    verification_failure = "output-verification-inconclusive:audio-edge-evidence"
                    failures.append(verification_failure)
                    evidence_gaps.extend(edge_issues)
                elif verification.get("pass") is not True:
                    verification_failure, verification_owner, verification_gaps = (
                        classify_output_verification_failure(verification)
                    )
                    failures.append(verification_failure)
                    evidence_gaps.extend(verification_gaps)
                if failures:
                    receipt_or_sentinel_mismatch = any(
                        failure.startswith(("receipt-", "sentinel-"))
                        for failure in failures
                    )
                    if receipt_or_sentinel_mismatch:
                        root_cause = "successful_take_evidence_mismatch"
                        failure_owner = "harness"
                    else:
                        root_cause = verification_failure
                        failure_owner = verification_owner
            elif sentinel.get("status") == "error":
                schema = sentinel.get("schemaVersion")
                classification = sentinel.get("failureClassification")
                failure_code = sentinel.get("failureCode")
                allowed_classifications = {
                    "post_generation_qc",
                    "post_generation_failure",
                    "pre_audio_startup",
                    "unmaterialized_unknown",
                }
                if schema == 3 and classification in allowed_classifications:
                    safe_code = failure_code if _safe_diagnostic_identifier(failure_code) else "unknown"
                    root_cause = f"{classification}:{safe_code}"
                    failure_owner = (
                        "harness" if classification == "unmaterialized_unknown" else "product"
                    )
                    if not receipt:
                        evidence_gaps.append("request-receipt-unavailable")
                    audio_qc = sentinel.get("audioQC")
                    if classification == "post_generation_qc":
                        if not isinstance(audio_qc, dict) or audio_qc.get("verdict") != "fail":
                            evidence_gaps.append("failed-audio-qc-unavailable")
                        artifacts = sentinel.get("diagnosticArtifacts") or []
                        kinds = {
                            artifact.get("kind")
                            for artifact in artifacts if isinstance(artifact, dict)
                        }
                        for required_kind in ("codec_trace", "rejected_audio"):
                            if required_kind not in kinds:
                                evidence_gaps.append(f"{required_kind.replace('_', '-')}-unavailable")
                        if not isinstance(sentinel.get("codecReplay"), dict):
                            evidence_gaps.append("codec-replay-unavailable")
                else:
                    root_cause = "unclassified_generation_failure"
                    failure_owner = "product"
                    evidence_gaps.append("schema-v3-terminal-evidence-unavailable")
                failures.append(root_cause)
            else:
                failures.append("sentinel-status-invalid")
                root_cause = "sentinel_status_invalid"
                failure_owner = "harness"
            if row["mode"] == "clone":
                digest = receipt.get("referenceAudioDigest")
                if isinstance(digest, str):
                    audio_by_alias.setdefault(row["referenceAlias"], set()).add(digest)
        if failures:
            hard_failures += 1
            if failure_owner == "product":
                product_failures += 1
            if failure_owner == "harness" or evidence_gaps:
                harness_failures += 1
        takes.append({
            "takeID": row["takeID"],
            "childRunID": row["childRunID"],
            "status": "PASS" if not failures else "HARD_FAILURE",
            "failures": failures,
            "rootCause": root_cause,
            "failureOwner": failure_owner,
            "evidenceGaps": sorted(set(evidence_gaps)),
            "wordErrorRate": (sentinel.get("outputVerification") or {}).get("wordErrorRate"),
            "characterErrorRate": (sentinel.get("outputVerification") or {}).get("characterErrorRate"),
            "outputVerification": _public_output_verification(
                sentinel.get("outputVerification")
            ),
            "referenceTranscriptLanguage": (sentinel.get("requestReceipt") or {}).get(
                "referenceTranscriptLanguage"
            ),
            "audioQC": _public_audio_qc(sentinel.get("audioQC")),
            "diagnosticArtifacts": _public_diagnostic_artifacts(
                sentinel.get("diagnosticArtifacts")
            ),
            "codecReplay": _public_codec_replay(sentinel.get("codecReplay")),
        })
    for alias, digests in audio_by_alias.items():
        if len(digests) != 1:
            hard_failures += 1
            harness_failures += 1
            takes.append({
                "takeID": f"identity-{alias}",
                "status": "HARD_FAILURE",
                "failures": ["reference-audio-identity-drift"],
                "rootCause": "reference_audio_identity_drift",
                "failureOwner": "harness",
                "evidenceGaps": [],
            })

    report = {
        "schemaVersion": 2,
        "runID": plan["runID"],
        "planDigest": plan["planDigest"],
        "status": "PASS" if hard_failures == 0 else "FAIL",
        "planned": plan["takeCount"],
        "hardFailures": hard_failures,
        "productFailures": product_failures,
        "harnessFailures": harness_failures,
        "transcription": sorted(public_transcription, key=lambda row: row["alias"]),
        "takes": takes,
        "semanticPromotionAuthority": False,
    }
    atomic_json(output, report)
    return report


def classify_output_verification_failure(
    verification: dict[str, Any],
) -> tuple[str, str, list[str]]:
    """Separate rejected generated output from unavailable verifier evidence.

    A consistent, locale-locked recognition result that violates the governed
    language or accuracy rule is product evidence: the generated take did not
    clear its acceptance gate. Missing, empty, inconsistent, or contradictory
    recognition remains a harness gap and cannot be converted into a product
    rejection. Neither branch is a PASS and neither changes the threshold.
    """
    reason = verification.get("skipReason")
    if reason == "speech_recognition_incomplete_temporal_coverage":
        return (
            f"output-verification-inconclusive:{reason}",
            "harness",
            ["output-recognition-temporal-coverage-incomplete"],
        )
    recognition = verification.get("recognition")
    if not isinstance(recognition, dict):
        return (
            "output-verification-inconclusive",
            "harness",
            ["output-recognition-evidence-unavailable"],
        )
    if recognition.get("evidenceConsistency") is not True:
        safe_reason = reason if _safe_diagnostic_identifier(reason) else "unavailable"
        return (
            f"output-verification-inconclusive:{safe_reason}",
            "harness",
            ["output-recognition-evidence-inconclusive"],
        )
    if verification.get("languagePass") is False:
        return ("output-language-verification-rejected", "product", [])
    if verification.get("accuracyPass") is False:
        return ("output-accuracy-verification-rejected", "product", [])
    return (
        "output-verification-contradictory",
        "harness",
        ["output-verification-fields-contradict-pass"],
    )


def _public_output_verification(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    recognition = value.get("recognition")
    public_recognition = None
    if isinstance(recognition, dict):
        repetitions = recognition.get("repetitions")
        temporal_coverage = []
        if isinstance(repetitions, list):
            for repetition in repetitions:
                if not isinstance(repetition, dict):
                    continue
                temporal_coverage.append({
                    "passIndex": repetition.get("passIndex"),
                    "segmentStartSeconds": repetition.get("segmentStartSeconds"),
                    "segmentEndSeconds": repetition.get("segmentEndSeconds"),
                    "timingCoverageSeconds": repetition.get("timingCoverageSeconds"),
                })
        public_recognition = {
            "algorithmVersion": recognition.get("algorithmVersion"),
            "consensusStatus": recognition.get("consensusStatus"),
            "evidenceConsistency": recognition.get("evidenceConsistency"),
            "selectedLocaleIdentifier": recognition.get("selectedLocaleIdentifier"),
            "repetitionCount": len(repetitions) if isinstance(repetitions, list) else 0,
            "temporalCoverage": temporal_coverage,
        }
    return {
        "algorithmVersion": value.get("algorithmVersion"),
        "pass": value.get("pass"),
        "skipReason": value.get("skipReason")
            if _safe_diagnostic_identifier(value.get("skipReason")) else None,
        "expectedLanguage": value.get("expectedLanguage"),
        "detectedLanguage": value.get("detectedLanguage"),
        "languagePass": value.get("languagePass"),
        "languageMatchScore": value.get("languageMatchScore"),
        "accuracyMetric": value.get("accuracyMetric"),
        "accuracyValue": value.get("accuracyValue"),
        "accuracyThreshold": value.get("accuracyThreshold"),
        "accuracyPass": value.get("accuracyPass"),
        "sourceAudioDurationSeconds": value.get("sourceAudioDurationSeconds"),
        "recognition": public_recognition,
    }


def _safe_diagnostic_identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 96
        and all(character.isalnum() or character in "._-" for character in value)
    )


def _public_audio_qc(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    allowed = (
        "algorithmVersion", "instabilityVerdict", "writtenOutputVerdict", "verdict",
        "flags", "rmsDBFS", "dcOffset", "peak", "clippedSamples", "hotSamples",
        "nonFiniteSamples", "clickEvents", "longestSilenceMS",
        "longestSilenceStartMS", "durationSeconds",
    )
    return {key: value[key] for key in allowed if key in value}


def _public_diagnostic_artifacts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    allowed = (
        "kind", "sha256", "byteCount", "durationSeconds", "codecFrameCount",
        "codeGroupRange", "codecChunkRanges", "complete",
    )
    return [
        {key: artifact[key] for key in allowed if key in artifact}
        for artifact in value if isinstance(artifact, dict)
    ]


def _public_codec_replay(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "status": value.get("status"),
        "failureCode": value.get("failureCode")
            if _safe_diagnostic_identifier(value.get("failureCode")) else None,
        "traceSHA256": value.get("traceSHA256"),
        "ranges": value.get("ranges") or [],
        "incrementalArtifact": _public_diagnostic_artifacts(
            [value.get("incrementalArtifact")]
        )[0] if isinstance(value.get("incrementalArtifact"), dict) else None,
        "incrementalAudioQC": _public_audio_qc(value.get("incrementalAudioQC")),
        "fullArtifact": _public_diagnostic_artifacts(
            [value.get("fullArtifact")]
        )[0] if isinstance(value.get("fullArtifact"), dict) else None,
        "fullAudioQC": _public_audio_qc(value.get("fullAudioQC")),
    }


def private_assets(bundle_root: Path, public_bundle: dict[str, Any]) -> dict[str, Any]:
    private = load_json(bundle_root / "private/bundle-private.json")
    if private.get("publicBundleDigest") != public_bundle.get("bundleDigest"):
        raise ReliabilityError("private and public bundle identities differ")
    return private


def delivery_roster(binary: Path, data_dir: Path) -> dict[str, str]:
    process = subprocess.run(
        [str(binary), "deliveries", "--shipped-only", "--json", "--data-dir", str(data_dir)],
        cwd=REPO, env={**os.environ, "QWENVOICE_DEBUG": "1"}, capture_output=True, text=True,
    )
    if process.returncode:
        raise ReliabilityError("delivery roster preflight failed")
    try:
        rows = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise ReliabilityError("delivery roster emitted invalid JSON") from error
    return {row["id"]: row["instruction"] for row in rows if isinstance(row, dict)}


def execute_plan(
    *, plan: dict[str, Any], contract: dict[str, Any], bundle_root: Path,
    binary: Path, run_dir: Path, max_takes: int | None,
) -> dict[str, Any]:
    bundle = load_json(bundle_root / "bundle-manifest.json")
    validate_plan(plan, contract, bundle)
    private = private_assets(bundle_root, bundle)
    if not binary.is_file():
        raise ReliabilityError("vocello CLI binary is missing")
    run_dir.mkdir(parents=True, exist_ok=True)
    retained_plan = run_dir / "execution-plan.json"
    if retained_plan.exists():
        if load_json(retained_plan) != plan:
            raise ReliabilityError("resume rejected: retained plan differs")
    else:
        atomic_json(retained_plan, plan)
    observations_path = run_dir / "observations.jsonl"
    observations = read_jsonl(observations_path)
    by_take: dict[str, dict[str, Any]] = {}
    for observation in observations:
        take_id = observation.get("takeID")
        if take_id in by_take or observation.get("planDigest") != plan["planDigest"]:
            raise ReliabilityError("observation stream is duplicated or cross-run")
        by_take[take_id] = observation
    references = {row["alias"]: row for row in private["references"]}
    profiles = private["runtimeProfiles"]
    scripts = resolve_scripts(contract)
    generated = 0
    roster_cache: dict[str, dict[str, str]] = {}
    audio_root = run_dir / "private/audio"
    audio_root.mkdir(parents=True, exist_ok=True)
    text_root = run_dir / "private/text"
    text_root.mkdir(parents=True, exist_ok=True)

    for row in plan["takes"]:
        if row["takeID"] in by_take:
            continue
        if max_takes is not None and generated >= max_takes:
            break
        if row.get("blockedPrerequisite"):
            observation = {
                "schemaVersion": 1, "takeID": row["takeID"],
                "planDigest": plan["planDigest"], "rowDigest": row["rowDigest"],
                "status": "BLOCKED_PREREQUISITE", "reason": row["blockedPrerequisite"],
            }
            append_jsonl(observations_path, observation)
            by_take[row["takeID"]] = observation
            continue
        profile = profiles.get(row["tokenizerArm"])
        if not isinstance(profile, dict):
            raise ReliabilityError(f"{row['takeID']}: private runtime profile is unavailable")
        data_dir = Path(profile["dataDir"])
        script = scripts[row["scriptID"]]["text"]
        script_path = text_root / f"{row['scriptDigest']}.txt"
        if not script_path.exists():
            script_path.write_text(script + "\n", encoding="utf-8")
        output = audio_root / f"{row['takeID']}.wav"
        command = [
            str(binary), "generate", "--mode", row["mode"], "--variant", "speed",
            "--text-file", str(script_path), "--seed", str(row["seed"]),
            "--variation", row["variation"], "--out", str(output), "--json", "--quiet",
            "--data-dir", str(data_dir),
        ]
        if row["languageSelection"] == "explicit":
            command += ["--language", row["targetLanguage"]]
        if row["mode"] == "clone":
            reference = references[row["referenceAlias"]]
            command += ["--reference", str(bundle_root / reference["audio"])]
            if row["transcriptArm"] != "audio-only":
                transcript_path = reference["transcripts"].get(row["transcriptArm"])
                if transcript_path is None:
                    raise ReliabilityError(f"{row['takeID']}: transcript disappeared after planning")
                transcript = (bundle_root / transcript_path).read_text(encoding="utf-8").strip()
                command += ["--transcript", transcript]
        else:
            command += ["--voice-brief", contract["voiceDesign"]["voiceBrief"]]
            cell = row.get("deliveryCellID")
            if cell is not None:
                cache_key = str(data_dir)
                if cache_key not in roster_cache:
                    roster_cache[cache_key] = delivery_roster(binary, data_dir)
                delivery = roster_cache[cache_key].get(cell)
                if delivery is None:
                    raise ReliabilityError(f"{row['takeID']}: delivery cell is missing")
                command += ["--delivery", delivery]
        process = subprocess.run(
            command, cwd=REPO, env={**os.environ, "QWENVOICE_DEBUG": "1"},
            capture_output=True, text=True,
        )
        generated += 1
        if process.returncode:
            material = (process.stdout + "\n" + process.stderr).encode("utf-8")
            observation = {
                "schemaVersion": 1, "takeID": row["takeID"],
                "planDigest": plan["planDigest"], "rowDigest": row["rowDigest"],
                "status": "HARD_FAILURE", "exitCode": process.returncode,
                "errorDigest": hashlib.sha256(material).hexdigest(),
            }
        else:
            try:
                payload = json.loads(process.stdout)
            except json.JSONDecodeError as error:
                raise ReliabilityError(f"{row['takeID']}: CLI result is not JSON") from error
            if not output.is_file():
                raise ReliabilityError(f"{row['takeID']}: CLI passed without audio")
            expected_conditioning = "clone_audio_only" if row.get("transcriptArm") == "audio-only" else (
                "clone_transcript_backed" if row["mode"] == "clone" else "voice_design"
            )
            checks = {
                "requestReceiptSchemaVersion": 2,
                "storedLanguageSelection": row["expectedStoredLanguage"],
                "detectedTargetLanguage": row["targetLanguage"],
                "finalModelLanguage": row["expectedFinalLanguage"],
                "conditioningMode": expected_conditioning,
                "targetTextDigest": row["scriptDigest"],
                "speechTokenizerDigest": row["expectedTokenizerDigest"],
            }
            if row["mode"] == "design":
                checks["deliveryInstructionDigest"] = row["expectedInstructionDigest"]
                checks["modelFacingInstructionLanguage"] = row["expectedInstructionLanguage"]
            mismatches = {
                key: {"expected": expected, "observed": payload.get(key)}
                for key, expected in checks.items() if payload.get(key) != expected
            }
            if row.get("transcriptDigest") is not None and payload.get("referenceTranscriptDigest") != row["transcriptDigest"]:
                mismatches["referenceTranscriptDigest"] = {
                    "expected": row["transcriptDigest"],
                    "observed": payload.get("referenceTranscriptDigest"),
                }
            observation = {
                "schemaVersion": 1, "takeID": row["takeID"],
                "planDigest": plan["planDigest"], "rowDigest": row["rowDigest"],
                "status": "PASS" if not mismatches else "HARD_FAILURE",
                "generationID": payload.get("generationID"),
                "audioFileName": output.name,
                "audioSHA256": file_digest(output),
                "durationSeconds": payload.get("durationSeconds"),
                "finishReason": payload.get("finishReason"),
                "requestReceiptSchemaVersion": payload.get("requestReceiptSchemaVersion"),
                "storedLanguageSelection": payload.get("storedLanguageSelection"),
                "detectedTargetLanguage": payload.get("detectedTargetLanguage"),
                "referenceTranscriptLanguage": payload.get("referenceTranscriptLanguage"),
                "finalModelLanguage": payload.get("finalModelLanguage"),
                "languageTokenMode": payload.get("languageTokenMode"),
                "conditioningMode": payload.get("conditioningMode"),
                "targetTextDigest": payload.get("targetTextDigest"),
                "referenceTranscriptDigest": payload.get("referenceTranscriptDigest"),
                "referenceAudioDigest": payload.get("referenceAudioDigest"),
                "modelArtifactVersion": payload.get("modelArtifactVersion"),
                "modelIntegrityManifestDigest": payload.get("modelIntegrityManifestDigest"),
                "speechTokenizerDigest": payload.get("speechTokenizerDigest"),
                "audioQC": payload.get("audioQC"),
                "receiptMismatches": mismatches,
            }
        append_jsonl(observations_path, observation)
        by_take[row["takeID"]] = observation

    required = {row["takeID"] for row in plan["takes"]}
    completed = set(by_take)
    summary = {
        "schemaVersion": 1,
        "runID": plan["runID"],
        "planDigest": plan["planDigest"],
        "status": "complete" if completed == required else "partial",
        "planned": len(required),
        "represented": len(completed),
        "passed": sum(row["status"] == "PASS" for row in by_take.values()),
        "hardFailures": sum(row["status"] == "HARD_FAILURE" for row in by_take.values()),
        "blockedPrerequisites": sum(row["status"] == "BLOCKED_PREREQUISITE" for row in by_take.values()),
        "remaining": len(required - completed),
        "generationProcessExited": True,
    }
    atomic_json(run_dir / "execution-summary.json", summary)
    return summary


def build_analysis_manifest(
    *, plan: dict[str, Any], bundle_root: Path, run_dir: Path,
) -> dict[str, Any]:
    bundle = load_json(bundle_root / "bundle-manifest.json")
    private = private_assets(bundle_root, bundle)
    reference_private = {row["alias"]: row for row in private["references"]}
    observations = {row["takeID"]: row for row in read_jsonl(run_dir / "observations.jsonl")}
    rows: list[dict[str, Any]] = []
    for plan_row in plan["takes"]:
        observation = observations.get(plan_row["takeID"])
        if observation is None or observation.get("status") != "PASS" or plan_row["mode"] != "clone":
            continue
        output = run_dir / "private/audio" / observation["audioFileName"]
        reference = bundle_root / reference_private[plan_row["referenceAlias"]]["audio"]
        if file_digest(output) != observation["audioSHA256"]:
            raise ReliabilityError(f"{plan_row['takeID']}: generated audio changed before analysis")
        rows.append({
            "generationID": observation["generationID"],
            "speakerID": plan_row["referenceAlias"],
            "scriptID": plan_row["scriptID"],
            "scriptTranslationGroup": plan_row["scriptID"],
            "seed": plan_row["seed"],
            "outputLanguage": plan_row["targetLanguage"],
            "preset": "clone-reference-fidelity",
            "instructedWAV": str(output), "neutralWAV": str(reference),
            "instructedSHA256": observation["audioSHA256"],
            "neutralSHA256": file_digest(reference),
        })
    if not rows:
        raise ReliabilityError("no passing Clone rows are available for analysis")
    source_files = [
        "scripts/voice_identity_language_reliability.py",
        "scripts/analyze_prosody.py",
        "scripts/clone_prosody_fidelity.py",
        "scripts/clone_speaker_similarity.py",
    ]
    body = {
        "schemaVersion": 1,
        "kind": "source-bound-clone-fidelity-input",
        "generationProcessExited": True,
        "executionPlanDigest": plan["planDigest"],
        "sourceDigests": {path: file_digest(REPO / path) for path in source_files},
        "rows": rows,
    }
    return {**body, "manifestDigest": canonical_digest(body)}


def _distribution(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2
    )
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return {
        "minimum": round(ordered[0], 4),
        "median": round(median, 4),
        "maximum": round(ordered[-1], 4),
        "mean": round(mean, 4),
        "standardDeviation": round(variance ** 0.5, 4),
    }


def _fidelity_diagnosis(
    plan: dict[str, Any], observations: dict[str, dict[str, Any]],
    fidelity_by_alias: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    diagnoses: list[dict[str, Any]] = []
    receipt_failures = [
        take_id for take_id, row in observations.items()
        if row.get("receiptMismatches")
    ]
    if receipt_failures:
        diagnoses.append({
            "layer": "request-receipt",
            "status": "divergent",
            "takeCount": len(receipt_failures),
            "takeIDs": sorted(receipt_failures),
            "nextAction": "repair request assembly before interpreting generated audio",
        })
    else:
        diagnoses.append({
            "layer": "request-receipt",
            "status": "consistent",
            "takeCount": sum(row.get("status") == "PASS" for row in observations.values()),
        })

    hard_failures = sorted(
        take_id for take_id, row in observations.items()
        if row.get("status") == "HARD_FAILURE"
    )
    if hard_failures:
        diagnoses.append({
            "layer": "generation-or-mandatory-qc",
            "status": "divergent",
            "takeCount": len(hard_failures),
            "takeIDs": hard_failures,
        })

    for alias, report in sorted(fidelity_by_alias.items()):
        flags = report["aggregate"]["flagCounts"]
        diagnoses.append({
            "layer": "reference-output-prosody",
            "referenceAlias": alias,
            "status": "divergent" if flags else "consistent",
            "takeCount": report["aggregate"]["count"],
            "flagCounts": flags,
            "scope": "advisory-uncalibrated-clone-fidelity-bounds",
        })

    design_rows = [row for row in plan["takes"] if row["mode"] == "design"]
    represented_design = [observations[row["takeID"]] for row in design_rows if row["takeID"] in observations]
    if represented_design:
        language_mismatch = [
            row for row in represented_design
            if row.get("status") == "PASS" and row.get("finalModelLanguage") != "french"
        ]
        diagnoses.append({
            "layer": "voice-design-language-routing",
            "status": "divergent" if language_mismatch else "consistent",
            "takeCount": len(represented_design),
            "mismatchCount": len(language_mismatch),
            "semanticOutputVerification": "requires-on-device-asr",
        })
    return diagnoses


def run_analysis(
    *, plan: dict[str, Any], bundle_root: Path, run_dir: Path,
    output: Path, include_speaker_similarity: bool,
) -> dict[str, Any]:
    summary = load_json(run_dir / "execution-summary.json")
    if summary.get("generationProcessExited") is not True:
        raise ReliabilityError("analysis cannot overlap a generator process")
    manifest = build_analysis_manifest(plan=plan, bundle_root=bundle_root, run_dir=run_dir)
    rows = manifest["rows"]
    sys.path.insert(0, str(REPO / "scripts"))
    from analyze_prosody import analyze as analyze_wav
    from clone_prosody_fidelity import evaluate_takes

    by_alias: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_alias.setdefault(row["speakerID"], []).append(row)
    fidelity: dict[str, dict[str, Any]] = {}
    feature_distributions: dict[str, dict[str, Any]] = {}
    speaker_similarity: dict[str, Any] = {"status": "not-requested"}

    for alias, alias_rows in sorted(by_alias.items()):
        reference_path = alias_rows[0]["neutralWAV"]
        reference_metrics = analyze_wav(reference_path)
        take_metrics = [analyze_wav(row["instructedWAV"]) for row in alias_rows]
        alias_report = evaluate_takes(reference_metrics, take_metrics)
        for verdict, row in zip(alias_report["takes"], alias_rows):
            verdict["clip"] = row["generationID"]
        fidelity[alias] = alias_report
        metric_names = sorted({
            key for verdict in alias_report["takes"] for key in verdict["metrics"]
        })
        feature_distributions[alias] = {
            metric: _distribution([
                verdict["metrics"][metric]
                for verdict in alias_report["takes"] if metric in verdict["metrics"]
            ])
            for metric in metric_names
        }

    if include_speaker_similarity:
        try:
            from clone_speaker_similarity import analyze_takes, ecapa_embedder, load_similarity_profile
            embed = ecapa_embedder()
            profile = load_similarity_profile(None)
            speaker_similarity = {"status": "complete", "references": {}}
            for alias, alias_rows in sorted(by_alias.items()):
                result = analyze_takes(
                    alias_rows[0]["neutralWAV"],
                    [row["instructedWAV"] for row in alias_rows],
                    embed,
                    profile,
                )
                for take, row in zip(result["takes"], alias_rows):
                    take["take"] = row["generationID"]
                result["reference"] = alias
                speaker_similarity["references"][alias] = result
        except Exception as error:
            speaker_similarity = {
                "status": "unavailable",
                "reasonType": type(error).__name__,
            }

    observations = {
        row["takeID"]: row for row in read_jsonl(run_dir / "observations.jsonl")
    }
    report = {
        "schemaVersion": 1,
        "reliabilityPlanDigest": plan["planDigest"],
        "analysisManifestDigest": manifest["manifestDigest"],
        "rowCount": len(rows),
        "generatorProcessExitedBeforeAnalysis": True,
        "prosodyFidelity": fidelity,
        "acrossTakeDistributions": feature_distributions,
        "speakerSimilarity": speaker_similarity,
        "diagnoses": _fidelity_diagnosis(plan, observations, fidelity),
        "semanticPromotionAuthority": False,
        "limitations": [
            "clone prosody bounds remain advisory until AV-07 calibration closes",
            "speaker similarity is advisory and omitted unless explicitly requested",
            "French semantic correctness requires the physical-device ASR campaign",
        ],
    }
    atomic_json(output, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare-bundle")
    prepare.add_argument("--input-spec", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--bundle-root", required=True, type=Path)
    plan_parser.add_argument("--output", required=True, type=Path)
    validate = sub.add_parser("validate-plan")
    validate.add_argument("--bundle-root", required=True, type=Path)
    validate.add_argument("--plan", required=True, type=Path)
    execute = sub.add_parser("execute")
    execute.add_argument("--bundle-root", required=True, type=Path)
    execute.add_argument("--plan", required=True, type=Path)
    execute.add_argument("--run-dir", required=True, type=Path)
    execute.add_argument("--binary", type=Path, default=REPO / "build/vocello")
    execute.add_argument("--max-takes", type=int)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--bundle-root", required=True, type=Path)
    analyze.add_argument("--plan", required=True, type=Path)
    analyze.add_argument("--run-dir", required=True, type=Path)
    analyze.add_argument("--output", required=True, type=Path)
    analyze.add_argument("--speaker-similarity", action="store_true")
    device_plan = sub.add_parser("device-plan")
    device_plan.add_argument("--run-id", required=True)
    device_plan.add_argument(
        "--profile", choices=("closure", "focused", "characterization"), default="focused"
    )
    device_plan.add_argument("--output", required=True, type=Path)
    validate_device = sub.add_parser("validate-device-plan")
    validate_device.add_argument("--plan", required=True, type=Path)
    validate_device.add_argument("--private-map", type=Path)
    compose_device = sub.add_parser("compose-device")
    compose_device.add_argument("--plan", required=True, type=Path)
    compose_device.add_argument("--diagnostics", required=True, type=Path)
    compose_device.add_argument("--transcription", required=True, type=Path)
    compose_device.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        contract = load_json(args.contract.resolve())
        validate_contract(contract)
        if args.command == "prepare-bundle":
            result = prepare_bundle(
                input_spec_path=args.input_spec.expanduser().resolve(),
                output=args.output.expanduser().resolve(), contract=contract,
            )
            payload = {"status": "PASS", "runID": result["runID"], "bundleDigest": result["bundleDigest"]}
        elif args.command == "device-plan":
            plan = build_device_plan(
                contract=contract, run_id=args.run_id, profile=args.profile
            )
            atomic_json(args.output.expanduser().resolve(), plan)
            payload = {
                "status": "PASS", "takeCount": plan["takeCount"],
                "planDigest": plan["planDigest"],
            }
        elif args.command in {"validate-device-plan", "compose-device"}:
            plan = load_json(args.plan.expanduser().resolve())
            validate_device_plan(plan, contract)
            if args.command == "validate-device-plan":
                if args.private_map:
                    load_private_device_map(
                        args.private_map.expanduser().resolve(), plan, contract
                    )
                payload = {
                    "status": "PASS", "takeCount": plan["takeCount"],
                    "planDigest": plan["planDigest"],
                }
            else:
                report = compose_device_results(
                    plan=plan, contract=contract,
                    diagnostics_root=args.diagnostics.expanduser().resolve(),
                    transcription=args.transcription.expanduser().resolve(),
                    output=args.output.expanduser().resolve(),
                )
                payload = {
                    "status": report["status"],
                    "takeCount": report["planned"],
                    "hardFailures": report["hardFailures"],
                }
                if report["status"] != "PASS":
                    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
                    return 2
        else:
            bundle_root = args.bundle_root.expanduser().resolve()
            bundle = load_json(bundle_root / "bundle-manifest.json")
            if args.command == "plan":
                plan = build_plan(contract=contract, bundle=bundle)
                atomic_json(args.output.expanduser().resolve(), plan)
                payload = {"status": "PASS", "takeCount": plan["takeCount"], "planDigest": plan["planDigest"]}
            else:
                plan = load_json(args.plan.expanduser().resolve())
                validate_plan(plan, contract, bundle)
                if args.command == "validate-plan":
                    payload = {"status": "PASS", "takeCount": plan["takeCount"], "planDigest": plan["planDigest"]}
                elif args.command == "execute":
                    payload = execute_plan(
                        plan=plan, contract=contract, bundle_root=bundle_root,
                        binary=args.binary.expanduser().resolve(),
                        run_dir=args.run_dir.expanduser().resolve(), max_takes=args.max_takes,
                    )
                else:
                    report = run_analysis(
                        plan=plan, bundle_root=bundle_root,
                        run_dir=args.run_dir.expanduser().resolve(),
                        output=args.output.expanduser().resolve(),
                        include_speaker_similarity=args.speaker_similarity,
                    )
                    payload = {"status": "PASS", "rows": report["rowCount"], "output": str(args.output)}
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (ReliabilityError, OSError, ValueError) as error:
        print(f"Voice identity/language reliability: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
