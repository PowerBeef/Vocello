#!/usr/bin/env python3
"""Fail-closed macOS/CLI safety screen for the Angry bilingual prompt arm.

The lane is intentionally narrow: it proves exact request routing and rejects
any hard generation/audio-QC failure before the candidate can replace shipped
copy. It does not measure perceptual improvement and publishes nothing.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any


REPO = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
CANDIDATE_VERSION = "angry-bilingual-v3"
CELL_ID = "angry.normal"
FIXED_SEEDS = (32_060_826, 32_060_827, 32_060_828, 32_060_829)
ENGLISH_INSTRUCTION = (
    "Sound fiercely angry and frustrated. Use a tense, forceful voice, hard clipped "
    "consonants, strong energy, and fast emphatic pacing."
)
MANDARIN_INSTRUCTION = (
    "语气要强烈愤怒、充满挫败感。使用紧张有力的声音、硬朗辅音、短促重音、强能量和快速强调的节奏。"
)
ENGLISH_DICTION = (
    "Native English pronunciation with clear English diction and natural stress."
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class SafetyMatrixError(RuntimeError):
    """A fail-closed candidate-screen contract violation."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SafetyMatrixError(f"could not load {path.name}: {error}") from error


def _corpus_text(corpus: dict[str, Any], frame_id: str) -> str:
    matches = [
        frame for frame in corpus.get("semanticFrames", [])
        if isinstance(frame, dict) and frame.get("id") == frame_id
    ]
    if len(matches) != 1:
        raise SafetyMatrixError(f"corpus must contain exactly one {frame_id} frame")
    text = matches[0].get("texts", {}).get("medium")
    if not isinstance(text, str) or not text.strip():
        raise SafetyMatrixError(f"corpus frame {frame_id} has no medium text")
    return text


def build_plan(root: Path = REPO) -> tuple[dict[str, Any], dict[str, str]]:
    """Build the fixed matrix from checked-in speaker metadata and corpus text."""
    contract_path = root / "Sources/Resources/qwenvoice_contract.json"
    corpus_path = root / "config/delivery-evaluation-corpus.json"
    contract = _load_json(contract_path)
    corpus = _load_json(corpus_path)
    if not isinstance(contract, dict) or not isinstance(corpus, dict):
        raise SafetyMatrixError("speaker contract and delivery corpus must be objects")

    groups = contract.get("speakers")
    metadata = contract.get("speakerMetadata")
    if not isinstance(groups, dict) or not isinstance(metadata, dict):
        raise SafetyMatrixError("speaker contract is missing roster metadata")
    roster = [speaker for members in groups.values() for speaker in members]
    if len(roster) != len(set(roster)):
        raise SafetyMatrixError("speaker contract contains duplicate speaker ids")
    if set(roster) != set(metadata):
        raise SafetyMatrixError("every registered speaker must have exactly one metadata row")

    chinese_native = sorted(
        speaker for speaker in roster
        if str(metadata[speaker].get("nativeLanguage", "")).strip().lower() == "chinese"
    )
    if len(chinese_native) != 5:
        raise SafetyMatrixError(
            f"expected five contract-backed Chinese-native speakers, got {chinese_native}"
        )
    for speaker in ("aiden", "ryan"):
        native = str(metadata.get(speaker, {}).get("nativeLanguage", "")).lower()
        if native != "english":
            raise SafetyMatrixError(f"{speaker} must remain registered as English-native")
    if "vivian" not in chinese_native:
        raise SafetyMatrixError("Vivian must remain registered as Chinese-native")

    texts = {
        "english": _corpus_text(corpus, "en-angry"),
        "chinese": _corpus_text(corpus, "zh-angry"),
    }
    row_specs: list[dict[str, str]] = []
    for speaker in chinese_native:
        row_specs.append({
            "case": "native-chinese",
            "speakerID": speaker,
            "outputLanguage": "chinese",
            "instructionLanguage": "mandarin",
            "expectedInstruction": MANDARIN_INSTRUCTION,
        })
    for speaker in ("aiden", "ryan"):
        row_specs.append({
            "case": "native-english",
            "speakerID": speaker,
            "outputLanguage": "english",
            "instructionLanguage": "english",
            "expectedInstruction": f"{ENGLISH_INSTRUCTION} {ENGLISH_DICTION}",
        })
    row_specs.extend([
        {
            "case": "non-native-chinese-fallback",
            "speakerID": "aiden",
            "outputLanguage": "chinese",
            "instructionLanguage": "english",
            "expectedInstruction": ENGLISH_INSTRUCTION,
        },
        {
            "case": "non-chinese-output-fallback",
            "speakerID": "vivian",
            "outputLanguage": "english",
            "instructionLanguage": "english",
            "expectedInstruction": f"{ENGLISH_INSTRUCTION} {ENGLISH_DICTION}",
        },
    ])

    rows: list[dict[str, Any]] = []
    for spec in row_specs:
        for seed in FIXED_SEEDS:
            language = spec["outputLanguage"]
            text = texts[language]
            rows.append({
                "rowID": f"{spec['case']}__{spec['speakerID']}__{language}__{seed}",
                "case": spec["case"],
                "speakerID": spec["speakerID"],
                "speakerNativeLanguage": metadata[spec["speakerID"]]["nativeLanguage"],
                "outputLanguage": language,
                "seed": seed,
                "variation": "expressive",
                "deliveryCellID": CELL_ID,
                "expectedInstructionLanguage": spec["instructionLanguage"],
                "expectedInstructionDigest": sha256_text(spec["expectedInstruction"]),
                "scriptDigest": sha256_text(text),
                "scriptCharacters": len(text),
            })

    if len(rows) != 36 or len({row["rowID"] for row in rows}) != 36:
        raise SafetyMatrixError("safety matrix must contain 36 unique takes")
    plan = {
        "schemaVersion": SCHEMA_VERSION,
        "candidateVersion": CANDIDATE_VERSION,
        "boundary": (
            "Hard-failure and exact-routing safety only; this matrix has no perceptual "
            "improvement or semantic promotion authority."
        ),
        "fixedSeeds": list(FIXED_SEEDS),
        "contractDigest": file_sha256(contract_path),
        "corpusDigest": file_sha256(corpus_path),
        "canonicalInstructionDigests": {
            "english": sha256_text(ENGLISH_INSTRUCTION),
            "mandarin": sha256_text(MANDARIN_INSTRUCTION),
        },
        "rows": rows,
    }
    return plan, texts


def validate_observations(
    plan: dict[str, Any], observations: list[dict[str, Any]]
) -> dict[str, Any]:
    expected = {row["rowID"]: row for row in plan["rows"]}
    observed_ids = [row.get("rowID") for row in observations]
    if len(observed_ids) != len(set(observed_ids)):
        raise SafetyMatrixError("observations contain duplicate row ids")
    if set(observed_ids) != set(expected):
        missing = sorted(set(expected) - set(observed_ids))
        extra = sorted(set(observed_ids) - set(expected))
        raise SafetyMatrixError(f"observation coverage mismatch: missing={missing}, extra={extra}")

    failures: list[dict[str, Any]] = []
    for observation in observations:
        row = expected[observation["rowID"]]
        status = observation.get("status")
        if status == "hard-failure":
            failures.append(observation)
            continue
        if status != "passed":
            raise SafetyMatrixError(f"{row['rowID']}: invalid status {status!r}")
        comparisons = {
            "instructionLanguage": row["expectedInstructionLanguage"],
            "instructionDigest": row["expectedInstructionDigest"],
            "deliveryCellID": CELL_ID,
        }
        for key, expected_value in comparisons.items():
            if observation.get(key) != expected_value:
                raise SafetyMatrixError(
                    f"{row['rowID']}: {key} mismatch; expected {expected_value!r}, "
                    f"got {observation.get(key)!r}"
                )
        audio_digest = observation.get("audioDigest")
        if not isinstance(audio_digest, str) or HEX64.fullmatch(audio_digest) is None:
            raise SafetyMatrixError(f"{row['rowID']}: missing valid audio digest")
        if not isinstance(observation.get("durationSeconds"), (int, float)) \
                or observation["durationSeconds"] <= 0:
            raise SafetyMatrixError(f"{row['rowID']}: invalid duration")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "candidateVersion": CANDIDATE_VERSION,
        "status": "blocked" if failures else "passed",
        "takeCount": len(observations),
        "passedCount": len(observations) - len(failures),
        "hardFailureCount": len(failures),
        "blockingRows": [
            {
                "rowID": failure["rowID"],
                "exitCode": failure.get("exitCode"),
                "errorDigest": failure.get("errorDigest"),
            }
            for failure in failures
        ],
        "authority": "hard-failure-and-routing-safety-only",
    }


def _source_identity(root: Path, binary: Path) -> dict[str, Any]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    diff = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--binary", "HEAD"],
        cwd=root, check=True, capture_output=True,
    ).stdout
    return {
        "gitCommit": head,
        "gitDiffDigest": sha256_bytes(diff),
        "binaryDigest": file_sha256(binary),
        "candidateSourceDigest": file_sha256(
            root / "Sources/QwenVoiceCore/EmotionPreset.swift"
        ),
        "routingSourceDigest": file_sha256(
            root / "Sources/QwenVoiceCore/GenerationSemantics.swift"
        ),
    }


def _run_candidate_check(binary: Path, data_dir: Path, env: dict[str, str]) -> None:
    result = subprocess.run(
        [str(binary), "deliveries", "--shipped-only", "--json", "--data-dir", str(data_dir)],
        cwd=REPO, env=env, check=False, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SafetyMatrixError("candidate delivery-roster preflight failed")
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SafetyMatrixError("candidate delivery-roster preflight emitted invalid JSON") from error
    angry = [row for row in rows if row.get("id") == CELL_ID]
    if len(angry) != 1 or angry[0].get("instruction") != ENGLISH_INSTRUCTION:
        raise SafetyMatrixError("debug arm did not resolve the exact Angry candidate")


def run_matrix(binary: Path, data_dir: Path, output: Path) -> dict[str, Any]:
    if not binary.is_file():
        raise SafetyMatrixError(f"CLI binary not found: {binary}")
    plan, texts = build_plan()
    output.mkdir(parents=True, exist_ok=False)
    audio_dir = output / "audio"
    audio_dir.mkdir()
    atomic_json(output / "plan.json", plan)

    env = dict(os.environ)
    env["QWENVOICE_DEBUG"] = "1"
    env["QWENVOICE_DELIVERY_INSTRUCTION_SET"] = CANDIDATE_VERSION
    _run_candidate_check(binary, data_dir, env)

    observations: list[dict[str, Any]] = []
    for index, row in enumerate(plan["rows"], start=1):
        output_wav = audio_dir / f"{index:02d}-{row['rowID']}.wav"
        command = [
            str(binary), "generate", "--mode", "custom", "--variant", "speed",
            "--speaker", row["speakerID"], "--language", row["outputLanguage"],
            "--delivery-cell", CELL_ID, "--seed", str(row["seed"]),
            "--variation", row["variation"], "--text", texts[row["outputLanguage"]],
            "--out", str(output_wav), "--json", "--quiet", "--data-dir", str(data_dir),
        ]
        result = subprocess.run(
            command, cwd=REPO, env=env, check=False, capture_output=True, text=True
        )
        if result.returncode != 0:
            error_material = (result.stdout + "\n" + result.stderr).encode("utf-8")
            observations.append({
                "rowID": row["rowID"],
                "status": "hard-failure",
                "exitCode": result.returncode,
                "errorDigest": sha256_bytes(error_material),
            })
            atomic_json(output / "observations.json", observations)
            continue
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise SafetyMatrixError(f"{row['rowID']}: CLI emitted invalid JSON") from error
        if not output_wav.is_file():
            raise SafetyMatrixError(f"{row['rowID']}: CLI passed without a WAV")
        observations.append({
            "rowID": row["rowID"],
            "status": "passed",
            "generationID": payload.get("generationID"),
            "durationSeconds": payload.get("durationSeconds"),
            "finishReason": payload.get("finishReason"),
            "instructionLanguage": payload.get("deliveryInstructionLanguage"),
            "instructionDigest": payload.get("deliveryInstructionDigest"),
            "deliveryCellID": payload.get("deliveryInstructionCellID"),
            "audioDigest": file_sha256(output_wav),
            "audioFileName": output_wav.name,
        })
        atomic_json(output / "observations.json", observations)

    atomic_json(output / "observations.json", observations)
    summary = validate_observations(plan, observations)
    summary["completedAt"] = utc_now()
    summary["sourceIdentity"] = _source_identity(REPO, binary)
    atomic_json(output / "summary.json", summary)
    return summary


def default_data_dir() -> Path:
    override = os.environ.get("QWENVOICE_APP_SUPPORT_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library/Application Support/QwenVoice-Debug"


def default_output() -> Path:
    token = datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPO / "build/artifacts/macos/delivery/angry-bilingual-v3" / token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("validate-plan", help="validate and print the fixed plan summary")
    run_parser = subparsers.add_parser("run", help="run all 36 serial safety takes")
    run_parser.add_argument("--binary", type=Path, default=REPO / "build/vocello")
    run_parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    run_parser.add_argument("--output", type=Path, default=default_output())
    validate_parser = subparsers.add_parser("validate-result", help="validate retained observations")
    validate_parser.add_argument("--observations", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        plan, _ = build_plan()
        if args.action == "validate-plan":
            print(json.dumps({
                "status": "passed", "takeCount": len(plan["rows"]),
                "fixedSeeds": plan["fixedSeeds"],
            }, sort_keys=True))
            return 0
        if args.action == "validate-result":
            observations = _load_json(args.observations.resolve())
            if not isinstance(observations, list):
                raise SafetyMatrixError("observations must be a JSON array")
            summary = validate_observations(plan, observations)
        else:
            summary = run_matrix(
                args.binary.resolve(), args.data_dir.expanduser().resolve(), args.output.resolve()
            )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if summary["status"] == "passed" else 1
    except SafetyMatrixError as error:
        print(f"Angry bilingual safety matrix: FAIL: {error}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
