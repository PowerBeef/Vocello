#!/usr/bin/env python3
"""Verify pinned local evaluator assets and emit an untracked adapter config."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from delivery_analysis_cache import atomic_json, digest, file_sha256


REPO = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = REPO / "config/delivery-evaluator-v2-candidates.json"
DEFAULT_MODEL_ROOT = REPO / "build/cache/delivery-analysis/external-models"
RUNTIME_SOURCE = REPO / "scripts/delivery_compact_model_runtime.py"
ADAPTER_LAYER_SOURCE = REPO / "scripts/delivery_compact_model_adapter.py"
SUPERVISOR_SOURCE = REPO / "scripts/delivery_resource_supervisor.py"


class PreparationError(ValueError):
    """Pinned local assets or their execution environment do not match."""


def _sha(value: Any, label: str) -> str:
    if (
        not isinstance(value, str) or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise PreparationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def validate_candidate_contract(contract: dict[str, Any]) -> dict[str, Any]:
    expected_order = ["sensevoice-small-q8", "distilhubert"]
    if (
        contract.get("schemaVersion") != 1
        or contract.get("kind") != "delivery-evaluator-v2-external-candidates"
        or contract.get("status") != "experimental"
    ):
        raise PreparationError("candidate contract schema or status is invalid")
    if contract.get("promotionAuthority") is not False or contract.get("normalCIPrerequisite") is not False:
        raise PreparationError("candidate contract changed its research-only boundary")
    if contract.get("candidateOrder") != expected_order:
        raise PreparationError("candidate order drifted")
    candidates = contract.get("candidates")
    if not isinstance(candidates, dict) or set(candidates) != set(expected_order):
        raise PreparationError("candidate coverage differs from the registered order")
    for adapter_id in expected_order:
        candidate = candidates[adapter_id]
        if not isinstance(candidate, dict):
            raise PreparationError(f"{adapter_id} candidate must be an object")
        for field in (
            "modelID", "sourceRevision", "sourceURI", "license",
            "trainingDataDeclaration", "trainingDataSourceURI", "weightsFile",
        ):
            if not isinstance(candidate.get(field), str) or not candidate[field].strip():
                raise PreparationError(f"{adapter_id} requires {field}")
        _sha(candidate.get("weightsSHA256"), f"{adapter_id}.weightsSHA256")
        if candidate.get("commercialUseCompatible") is not True:
            raise PreparationError(f"{adapter_id} is not commercially compatible")
        if not isinstance(candidate.get("labelMap"), dict) or not candidate["labelMap"]:
            raise PreparationError(f"{adapter_id} label map is missing")
        if not isinstance(candidate.get("preprocessingConfig"), dict):
            raise PreparationError(f"{adapter_id} preprocessing config is missing")
    runtime = candidates["sensevoice-small-q8"].get("runtime")
    if not isinstance(runtime, dict):
        raise PreparationError("SenseVoice runtime identity is missing")
    for field in ("archiveSHA256", "binarySHA256"):
        _sha(runtime.get(field), f"sensevoice.{field}")
    supporting = candidates["distilhubert"].get("supportingFiles")
    dependencies = candidates["distilhubert"].get("runtimeDependencies")
    if not isinstance(supporting, dict) or not supporting:
        raise PreparationError("DistilHuBERT supporting-file identity is missing")
    for name, value in supporting.items():
        _sha(value, f"distilhubert.{name}")
    if not isinstance(dependencies, dict) or set(dependencies) != {
        "python", "torch", "transformers", "safetensors", "numpy"
    } or any(not isinstance(value, str) or not value for value in dependencies.values()):
        raise PreparationError("DistilHuBERT runtime dependency pins are incomplete")
    required_gates = {
        "two-clean-eight-gib-host-runs", "serial-process-isolation",
        "post-exit-memory-recovery", "untouched-human-holdout-gain",
        "no-vad-dimension-regression", "no-preset-regression",
    }
    if set(contract.get("adoptionRequirements", [])) != required_gates:
        raise PreparationError("candidate adoption requirements drifted")
    return contract


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PreparationError(f"cannot read {path.name}") from error
    if not isinstance(value, dict):
        raise PreparationError(f"{path.name} must contain an object")
    return value


def _verified(path: Path, expected: str, label: str) -> Path:
    if not path.is_file() or file_sha256(path) != expected:
        raise PreparationError(f"{label} is missing or its SHA-256 digest changed")
    return path


def _runtime_versions(python: Path) -> dict[str, str]:
    command = [str(python), "-c", (
        "import json,sys,torch,transformers,safetensors,numpy;"
        "print(json.dumps({'python':'.'.join(map(str,sys.version_info[:3])),"
        "'torch':torch.__version__,'transformers':transformers.__version__,"
        "'safetensors':safetensors.__version__,'numpy':numpy.__version__},sort_keys=True))"
    )]
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise PreparationError("DistilHuBERT runtime dependencies cannot be inspected")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise PreparationError("DistilHuBERT runtime dependency output is invalid") from error
    if not isinstance(value, dict) or any(not isinstance(item, str) for item in value.values()):
        raise PreparationError("DistilHuBERT runtime dependency inventory is invalid")
    return value


def prepare(adapter_id: str, *, contract_path: Path, model_root: Path) -> dict[str, Any]:
    contract = validate_candidate_contract(_read(contract_path))
    candidates = contract.get("candidates")
    if not isinstance(candidates, dict):  # validate_candidate_contract owns this invariant
        raise PreparationError("candidate contract schema is invalid")
    candidate = candidates.get(adapter_id)
    if not isinstance(candidate, dict):
        raise PreparationError("candidate is not registered")
    label_map = candidate["labelMap"]
    label_digest = digest(label_map)
    if adapter_id == "sensevoice-small-q8":
        weights = _verified(
            model_root / "sensevoice-q8" / candidate["weightsFile"],
            candidate["weightsSHA256"], "SenseVoice Q8 weights",
        )
        runtime = candidate["runtime"]
        _verified(
            model_root / "runtime-v0.1.9" / runtime["archiveFile"],
            runtime["archiveSHA256"], "SenseVoice runtime archive",
        )
        binary = _verified(
            model_root / "runtime-v0.1.9/extracted" / runtime["binaryFile"],
            runtime["binarySHA256"], "SenseVoice runtime binary",
        )
        source_digest = runtime["binarySHA256"]
        dependencies = {
            "runtimeRelease": runtime["release"],
            "runtimeArchiveSHA256": runtime["archiveSHA256"],
        }
        output_format = "sensevoice-tagged-text"
        command = [
            "{binary}", "-m", "{weights}", "-a", "{audio}",
            "--backend", "cpu", "--keep-tags",
        ]
    elif adapter_id == "distilhubert":
        model_dir = model_root / "distilhubert"
        weights = _verified(
            model_dir / candidate["weightsFile"], candidate["weightsSHA256"],
            "DistilHuBERT weights",
        )
        for name, expected in candidate["supportingFiles"].items():
            _verified(model_dir / name, expected, f"DistilHuBERT {name}")
        binary = model_root / "distilhubert-runtime-py314/bin/python"
        if not binary.is_file():
            raise PreparationError("DistilHuBERT Python runtime is missing")
        dependencies = _runtime_versions(binary)
        if dependencies != candidate["runtimeDependencies"]:
            raise PreparationError("DistilHuBERT runtime dependency versions drifted")
        source_digest = file_sha256(RUNTIME_SOURCE)
        output_format = "json"
        command = [
            "{binary}", str(RUNTIME_SOURCE), "distilhubert",
            "--weights", "{weights}", "--audio", "{audio}",
        ]
    else:  # pragma: no cover - contract owns this branch
        raise PreparationError("unsupported candidate")
    dependency_digest = digest(dependencies)
    preprocessing = dict(candidate["preprocessingConfig"])
    layer_digest = file_sha256(ADAPTER_LAYER_SOURCE)
    supervisor_digest = file_sha256(SUPERVISOR_SOURCE)
    preprocessing["executionIdentity"] = {
        "adapterSourceSHA256": source_digest,
        "adapterLayerSHA256": layer_digest,
        "resourceSupervisorSHA256": supervisor_digest,
        "runtimeDependenciesDigest": dependency_digest,
        "labelMapDigest": label_digest,
        "outputFormat": output_format,
    }
    return {
        "schemaVersion": 1,
        "executionIdentityVersion": 2,
        "adapterID": adapter_id,
        "modelID": candidate["modelID"],
        "sourceRevision": candidate["sourceRevision"],
        "weightsPath": str(weights),
        "weightsSHA256": candidate["weightsSHA256"],
        "binaryPath": str(binary),
        "binarySHA256": file_sha256(binary),
        "adapterSourceSHA256": source_digest,
        "adapterLayerSHA256": layer_digest,
        "resourceSupervisorSHA256": supervisor_digest,
        "runtimeDependencies": dependencies,
        "runtimeDependenciesDigest": dependency_digest,
        "license": candidate["license"],
        "commercialUseCompatible": candidate["commercialUseCompatible"],
        "trainingDataDeclaration": candidate["trainingDataDeclaration"],
        "sourceURI": candidate["sourceURI"],
        "trainingDataSourceURI": candidate["trainingDataSourceURI"],
        "labelMap": label_map,
        "labelMapDigest": label_digest,
        "preprocessingConfig": preprocessing,
        "preprocessingConfigDigest": digest(preprocessing),
        "offlineAfterAcquisition": True,
        "outputFormat": output_format,
        "commandTemplate": command,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("adapter", nargs="?", choices=("sensevoice-small-q8", "distilhubert"))
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.validate_only:
            if args.adapter is not None or args.output is not None:
                raise PreparationError("--validate-only does not accept an adapter or output")
            value = validate_candidate_contract(_read(args.contract))
            print(json.dumps({
                "status": "PASS", "candidateCount": len(value["candidates"]),
                "contractDigest": digest(value),
            }, sort_keys=True))
            return 0
        if args.adapter is None or args.output is None:
            raise PreparationError("adapter and --output are required for preparation")
        value = prepare(args.adapter, contract_path=args.contract, model_root=args.model_root)
        atomic_json(args.output, value)
        print(json.dumps({
            "adapterID": args.adapter,
            "configSHA256": file_sha256(args.output),
            "sourceRevision": value["sourceRevision"],
            "weightsSHA256": value["weightsSHA256"],
        }, sort_keys=True))
        return 0
    except PreparationError as error:
        print(f"Delivery compact model preparation: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
