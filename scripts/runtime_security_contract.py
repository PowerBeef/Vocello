#!/usr/bin/env python3
"""Validate runtime debug, concurrency, convergence, and release contracts."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_PATTERN = re.compile(r'["\']((?:QWENVOICE|QVOICE)_[A-Z0-9_]+)["\']')
ENV_KEY_PATTERN = re.compile(r'(?:QWENVOICE|QVOICE)_[A-Z0-9_]+')
UNCHECKED_PATTERN = re.compile(
    r"\b(?:final\s+|private\s+|public\s+|internal\s+)*"
    r"(?:class|struct|actor)\s+([A-Za-z_][A-Za-z0-9_]*)[^\n{]*@unchecked\s+Sendable"
)
UNSAFE_DECLARATION_PATTERN = re.compile(
    r"nonisolated\(unsafe\)[^\n]*(?:var|let)\s+([A-Za-z_][A-Za-z0-9_]*)"
)
LEGACY_COMPATIBILITY_SPI = "VocelloQwen3LegacyCompatibility"
LEGACY_COMPATIBILITY_SPI_PATTERN = re.compile(
    rf"@_spi\(\s*{re.escape(LEGACY_COMPATIBILITY_SPI)}\s*\)"
)
VOCELLO_QWEN3_CORE_IMPORT_PATTERN = re.compile(r"\bimport\s+VocelloQwen3Core\b")
PHASE2_ENGINE_ACTOR_STATUS_PENDING = (
    "shipping-through-phase4-implementation-complete-promotion-pending"
)
PHASE2_ENGINE_ACTOR_STATUS_PASSED = (
    "shipping-through-phase4-implementation-complete-overall-promotion-passed"
)
PHASE2_CLASSIFIED_SESSION_STATUS_PENDING = (
    "shipping-through-phase4-implementation-complete-promotion-pending"
)
PHASE2_CLASSIFIED_SESSION_STATUS_PASSED = (
    "shipping-through-phase4-implementation-complete-overall-promotion-passed"
)
PHASE4_PRODUCT_ADAPTER_STATUS_PENDING = (
    "shipping-implementation-complete-promotion-pending"
)
PHASE4_PRODUCT_ADAPTER_STATUS_PASSED = (
    "shipping-implementation-complete-overall-promotion-passed"
)
PHASE4_MODE_CUTOVER_PENDING = (
    "implementation-complete-focused-platform-acceptance-passed-"
    "overall-promotion-pending"
)
PHASE4_MODE_CUTOVER_PASSED = (
    "implementation-complete-focused-platform-acceptance-passed-"
    "overall-promotion-passed"
)
PHASE4_PROMOTION_EVIDENCE_PENDING = (
    "focused-platform-acceptance-passed-overall-promotion-pending"
)
PHASE4_PROMOTION_EVIDENCE_PASSED = (
    "overall-promotion-passed-phase0-5-6-closed-canonical-matrices"
)
PHASE2_ACTOR_CORRECTNESS_CLOSURE = {
    "abortLifecycle": "reserved-generating-aborting-single-owner-with-duplicate-abort-join",
    "criticalMemoryRelief": "typed-cache-trim-or-full-unload-generation-lease-transfer",
    "admissionReopen": "after-revalidated-relief-completion-only",
}
PHASE2_CLONE_HANDLE_LIFECYCLE = {
    "defaultCapacity": 1,
    "configuredCapacityMinimum": 1,
    "eviction": "least-recently-used",
    "explicitRelease": "first-release-true-repeat-release-false",
    "activeReservationAfterRelease": "retains-captured-prompt",
    "noncriticalCacheTrim": "preserves-handles",
    "criticalCacheTrim": "invalidates-handles",
    "fullUnload": "invalidates-handles-and-increments-model-epoch",
    "modelReload": "invalidates-handles-and-increments-model-epoch",
}
PHASE2_REQUIRED_STABLE_CONTRACTS = {
    "VocelloQwen3Engine",
    "VocelloQwen3GenerationReservation",
    "VocelloQwen3ClassifiedGenerationSession",
    "VocelloQwen3CloneHandle",
    "VocelloQwen3MemoryReliefAction",
}
# Phase 14a (2026-07-23) retired the combined-event characterization session and its
# protocol/event types; the classified session is the sole generation session.
PHASE2_INTERNAL_CHARACTERIZATION_SURFACES: set[str] = set()
PHASE4_MODE_AUTHORITY = "classified-session-generation-output-adapter"
PHASE4_IMPLEMENTATION_STATUS = "complete"
PHASE4_VERIFICATION_STATES = {"pending", "passed"}
PHASE4_IPHONE_ACCEPTANCE_STATES = {"pending-device", "passed"}
PHASE4_DIRECT_MODE_CALL_PATTERN = re.compile(
    r"\.(?:customVoiceStream|voiceDesignStream|voiceCloneStream|"
    r"generateCustomVoiceStream|generateVoiceDesignStream|generateVoiceCloneStream|"
    r"generateCustomVoice|generateVoiceDesign|generateVoiceClone)\s*\("
)


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain an object")
    return value


def swift_files(roots: list[str]) -> list[Path]:
    result: list[Path] = []
    for relative in roots:
        path = ROOT / relative
        if not path.is_dir():
            raise ValueError(f"source root does not exist: {relative}")
        result.extend(path.rglob("*.swift"))
    return sorted(set(result))


def phase2_legacy_spi_product_consumers(root: Path = ROOT) -> set[str]:
    consumers: set[str] = set()
    for path in sorted((root / "Sources").rglob("*.swift")):
        source = path.read_text(encoding="utf-8")
        source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
        source = re.sub(r"//[^\n]*", "", source)
        if (
            LEGACY_COMPATIBILITY_SPI_PATTERN.search(source)
            and VOCELLO_QWEN3_CORE_IMPORT_PATTERN.search(source)
        ):
            consumers.add(path.relative_to(root).as_posix())
    return consumers


def string_list_set(value: object) -> set[str] | None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return None
    return set(value)


def phase4_direct_mode_call_sites(
    source_paths: object,
    *,
    root: Path = ROOT,
) -> list[str]:
    """Return product-adapter call sites that bypass the classified session.

    Compatibility wrappers may continue to define the old methods temporarily, but the
    shipping product adapter may not invoke them after Phase 4 claims mode authority.
    """
    if not isinstance(source_paths, list):
        return []
    sites: list[str] = []
    for relative in source_paths:
        if not isinstance(relative, str):
            continue
        path = root / relative
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        for match in PHASE4_DIRECT_MODE_CALL_PATTERN.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            sites.append(f"{relative}:{line}")
    return sites


def debug_gate_enforcement_errors(
    *, relative_path: str, source: str, gated_keys: set[str], master_gate: str
) -> list[str]:
    """Reject a production-affecting key read outside the single gate API.

    Keys may be stored in a local constant before being passed to the gate, so
    enforcement is intentionally file-scoped. This is stricter than inventory
    alone while remaining stable under ordinary Swift refactors.
    """
    observed = set(ENV_PATTERN.findall(source)) & gated_keys
    observed.discard(master_gate)
    if not observed or relative_path.endswith("/RuntimeDebugGate.swift"):
        return []
    errors: list[str] = []
    for key in sorted(observed):
        direct_read = re.compile(
            rf"(?:ProcessInfo\.processInfo\.environment|environment|env)\s*"
            rf"\[\s*[\"']{re.escape(key)}[\"']\s*\]"
        )
        if direct_read.search(source):
            errors.append(
                f"production-affecting runtime key bypasses RuntimeDebugGate.value: "
                f"{relative_path}:{key}"
            )
    if errors:
        return errors
    if (
        "RuntimeDebugGate.value(" in source
        or "VocelloQwen3ImplementationDebugGate.value(" in source
    ):
        return []
    return [
        f"production-affecting runtime key has no explicit RuntimeDebugGate.value path: "
        f"{relative_path}:{key}"
        for key in sorted(observed)
    ]


def validate_debug_contract() -> list[str]:
    errors: list[str] = []
    contract = load_json(ROOT / "config/runtime-debug-knobs.json")
    if contract.get("schemaVersion") != 1:
        errors.append("runtime-debug-knobs schemaVersion must be 1")
    if contract.get("masterGate") != "QWENVOICE_DEBUG":
        errors.append("runtime-debug-knobs masterGate must be QWENVOICE_DEBUG")

    groups = contract.get("groups")
    if not isinstance(groups, list) or not groups:
        return errors + ["runtime-debug-knobs groups must be a non-empty array"]
    registered: set[str] = set()
    gated: set[str] = set()
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            errors.append(f"runtime-debug-knobs groups[{index}] must be an object")
            continue
        keys = group.get("keys")
        if not isinstance(keys, list) or not keys:
            errors.append(f"runtime-debug-knobs groups[{index}].keys must be non-empty")
            continue
        if not isinstance(group.get("purpose"), str) or not group["purpose"].strip():
            errors.append(f"runtime-debug-knobs groups[{index}] requires purpose")
        if group.get("gateRequired") is True and group.get("releaseBehavior") != "ignored-unless-master-gate-enabled":
            errors.append(f"runtime-debug-knobs groups[{index}] has invalid gated releaseBehavior")
        for key in keys:
            if not isinstance(key, str) or ENV_KEY_PATTERN.fullmatch(key) is None:
                errors.append(f"invalid runtime environment key: {key!r}")
            elif key in registered:
                errors.append(f"duplicate runtime environment key: {key}")
            else:
                registered.add(key)
                if group.get("gateRequired") is True:
                    gated.add(key)

    observed: set[str] = set()
    for path in swift_files(contract.get("sourceRoots", [])):
        source = path.read_text(encoding="utf-8")
        observed.update(ENV_PATTERN.findall(source))
        errors.extend(
            debug_gate_enforcement_errors(
                relative_path=path.relative_to(ROOT).as_posix(),
                source=source,
                gated_keys=gated,
                master_gate=contract["masterGate"],
            )
        )
    for missing in sorted(observed - registered):
        errors.append(f"unregistered runtime environment key: {missing}")
    for stale in sorted(registered - observed):
        errors.append(f"registered runtime environment key is not present in production Swift: {stale}")
    persisted_toggle = "QwenVoice.DebugModeEnabled"
    for path in swift_files(contract.get("sourceRoots", [])):
        if persisted_toggle in path.read_text(encoding="utf-8"):
            errors.append(
                f"persisted debug toggle bypasses the explicit process gate: "
                f"{path.relative_to(ROOT)}"
            )
    return errors


def validate_concurrency_contract() -> list[str]:
    errors: list[str] = []
    contract = load_json(ROOT / "config/concurrency-safety.json")
    if contract.get("schemaVersion") != 1:
        errors.append("concurrency-safety schemaVersion must be 1")
    entries = contract.get("entries")
    if not isinstance(entries, list) or not entries:
        return errors + ["concurrency-safety entries must be a non-empty array"]

    observed: set[tuple[str, str]] = set()
    observed_unsafe: set[tuple[str, str]] = set()
    for path in swift_files(contract.get("sourceRoots", [])):
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for match in UNCHECKED_PATTERN.finditer(text):
            observed.add((relative, match.group(1)))
        for match in UNSAFE_DECLARATION_PATTERN.finditer(text):
            observed_unsafe.add((relative, match.group(1)))

    registered_unsafe: set[tuple[str, str]] = set()
    unsafe_entries = contract.get("unsafeDeclarations")
    if not isinstance(unsafe_entries, list):
        errors.append("concurrency-safety unsafeDeclarations must be an array")
        unsafe_entries = []
    for index, entry in enumerate(unsafe_entries):
        if not isinstance(entry, dict):
            errors.append(f"concurrency-safety unsafeDeclarations[{index}] must be an object")
            continue
        source = entry.get("source")
        names = entry.get("names")
        if not isinstance(source, str) or not (ROOT / source).is_file():
            errors.append(f"concurrency-safety unsafeDeclarations[{index}] has missing source")
            continue
        if not isinstance(names, list) or not names:
            errors.append(f"concurrency-safety unsafeDeclarations[{index}] requires names")
            continue
        for field in ("owner", "invariant"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                errors.append(f"concurrency-safety unsafeDeclarations[{index}] requires {field}")
        for name in names:
            identity = (source, name)
            if identity not in observed_unsafe:
                errors.append(f"unsafe declaration entry does not resolve: {source}:{name}")
            registered_unsafe.add(identity)

    registered: set[tuple[str, str]] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"concurrency-safety entries[{index}] must be an object")
            continue
        sources = entry.get("sources") or [entry.get("source")]
        types = entry.get("types") or ([entry.get("type")] if entry.get("type") else [])
        if not all(isinstance(item, str) and (ROOT / item).is_file() for item in sources):
            errors.append(f"concurrency-safety entries[{index}] has missing source")
            continue
        if not types or not all(isinstance(item, str) and item for item in types):
            errors.append(f"concurrency-safety entries[{index}] requires types")
            continue
        if not isinstance(entry.get("owner"), str) or not entry["owner"].strip():
            errors.append(f"concurrency-safety entries[{index}] requires owner")
        if not isinstance(entry.get("invariant"), str) or not entry["invariant"].strip():
            errors.append(f"concurrency-safety entries[{index}] requires invariant")
        tests = entry.get("tests")
        if not isinstance(tests, list) or not tests:
            errors.append(f"concurrency-safety entries[{index}] requires tests")
        else:
            for test in tests:
                if not isinstance(test, str) or not (ROOT / test).is_file():
                    errors.append(f"concurrency-safety test does not resolve: {test!r}")
        for type_name in types:
            matches = [(source, type_name) for source in sources if (source, type_name) in observed]
            if len(matches) != 1:
                errors.append(
                    f"unchecked Sendable entry must resolve once: {entry.get('id')}:{type_name}"
                )
                continue
            registered.add(matches[0])
    for source, type_name in sorted(observed - registered):
        errors.append(f"unregistered unchecked Sendable declaration: {source}:{type_name}")
    for source, type_name in sorted(registered - observed):
        errors.append(f"stale unchecked Sendable registration: {source}:{type_name}")
    for source, name in sorted(observed_unsafe - registered_unsafe):
        errors.append(f"unregistered nonisolated unsafe declaration: {source}:{name}")
    for source, name in sorted(registered_unsafe - observed_unsafe):
        errors.append(f"stale nonisolated unsafe registration: {source}:{name}")
    return errors


def validate_release_contract() -> list[str]:
    errors: list[str] = []
    contract = load_json(ROOT / "config/release-evidence-contract.json")
    if contract.get("schemaVersion") != 1:
        errors.append("release-evidence-contract schemaVersion must be 1")
    if contract.get("publicationPolicy") != "draft-build-verify-attest-await-source-bound-promotion":
        errors.append(
            "release evidence must use draft-build-verify-attest-await-source-bound-promotion"
        )
    for key in ("sourceIdentity", "artifacts"):
        value = contract.get(key)
        if not isinstance(value, list) or not value or len(value) != len(set(value)):
            errors.append(f"release-evidence-contract {key} must be a unique non-empty array")
    if "requiredDeterministicChecks" in contract:
        errors.append(
            "release-evidence-contract cannot claim checks that are not bound to managed step manifests"
        )
    identity = contract.get("sourceIdentity") or []
    inputs = contract.get("sourceIdentityInputs")
    expected_digests = set(identity) - {"gitCommit", "treeDirty"}
    if not isinstance(inputs, dict) or set(inputs) != expected_digests:
        errors.append("release-evidence-contract must map every source digest to exact input paths")
    elif any(
        not isinstance(paths, list) or not paths or len(paths) != len(set(paths))
        for paths in inputs.values()
    ):
        errors.append("release-evidence-contract source input groups must be unique non-empty arrays")
    if not isinstance(contract.get("verificationFreshnessSeconds"), int):
        errors.append("release-evidence-contract must bound verification freshness")
    platforms = contract.get("platformVerification")
    if not isinstance(platforms, dict) or set(platforms) != {"macos", "ios"}:
        errors.append("release-evidence-contract must define macOS and iOS managed verification")
    else:
        workflows = load_json(ROOT / "config/orchestration-contract.json").get("workflows", {})
        for platform, definition in platforms.items():
            managed = workflows.get(definition.get("workflow"))
            if (
                not isinstance(managed, dict)
                or managed.get("sourceIdentityRequired") is not True
                or managed.get("requiredSteps") != definition.get("requiredSteps")
            ):
                errors.append(
                    f"release-evidence-contract {platform} steps differ from managed orchestration"
                )
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    promotion_workflow = (ROOT / ".github/workflows/promote-release.yml").read_text(encoding="utf-8")
    if "release.published" in workflow:
        errors.append("release workflow must not trigger after public release publication")
    if "--draft" not in workflow or "--latest" in workflow or "--draft=false" in workflow:
        errors.append("release workflow must create and verify a draft without publishing it")
    if (
        "scripts/release_evidence.py validate" not in promotion_workflow
        or "scripts/quality_promotion.py validate" not in promotion_workflow
        or "--draft=false" not in promotion_workflow
        or "--latest" not in promotion_workflow
    ):
        errors.append("promotion workflow must validate both evidence layers before publication")
    if "release_evidence.py" not in workflow:
        errors.append("release workflow does not invoke release_evidence.py")
    for required in (
        "capture-source-identity", "required_step_ledger.py run", "required_step_ledger.py finalize",
        "--source-identity", "--step-ledger", "release-verification.json",
    ):
        if required not in workflow:
            errors.append(f"release workflow does not bind managed verification evidence: {required}")
    evidence_source = (ROOT / "scripts/release_evidence.py").read_text(encoding="utf-8")
    if "import release_sbom" not in evidence_source:
        errors.append("release evidence does not generate the release SBOM")
    if '"managed-subprocess"' not in evidence_source or "validate_step_ledger" not in evidence_source:
        errors.append("release evidence can self-assert verification without managed step manifests")
    return errors


def runtime_refactor_contract_errors(
    contract: dict,
    *,
    decision_exists: bool = True,
    compatibility: dict | None = None,
    observed_spi_consumers: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    if contract.get("schemaVersion") != 1:
        errors.append("runtime-refactor-contract schemaVersion must be 1")
    if contract.get("status") != "active-staged-convergence":
        errors.append("runtime-refactor-contract must remain an active staged convergence")
    if contract.get("shippingPolicy") != "shadow-contracts-must-not-run-a-second-model-generation":
        errors.append("runtime-refactor-contract must prohibit a second shadow generation")
    if contract.get("rollbackPolicy") != "revert-the-owning-small-pull-request":
        errors.append("runtime-refactor-contract must use pull-request reversion for rollback")
    if not decision_exists:
        errors.append("runtime-refactor-contract decision does not resolve")

    checkpoint = contract.get("reviewCheckpoint")
    if not isinstance(checkpoint, dict):
        errors.append("runtime-refactor-contract review checkpoint must be an object")
    else:
        review_date = checkpoint.get("date")
        if not isinstance(review_date, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", review_date) is None:
            errors.append("runtime-refactor-contract review checkpoint date must use YYYY-MM-DD")
        base_revision = checkpoint.get("baseRevision")
        if (
            not isinstance(base_revision, str)
            or len(base_revision) != 40
            or any(character not in "0123456789abcdef" for character in base_revision)
        ):
            errors.append("runtime-refactor-contract review base revision must be a full Git SHA")
        source_state = checkpoint.get("sourceState")
        if (
            not isinstance(source_state, str)
            or not source_state
            or any(
                not (character.islower() or character.isdigit() or character == "-")
                for character in source_state
            )
        ):
            errors.append("runtime-refactor-contract review source state must be a safe token")
        verification = checkpoint.get("deterministicVerification")
        if not isinstance(verification, dict) or verification.get("status") != "passed":
            errors.append("runtime-refactor-contract deterministic checkpoint must report PASS")
        elif any(
            not isinstance(verification.get(key), int) or verification[key] <= 0
            for key in ("coreTests", "xpcIntegrationTests", "ownedRuntimeTests")
        ):
            errors.append("runtime-refactor-contract deterministic test counts must be positive")
        promotion = (
            (contract.get("phase4ProductCutover") or {}).get("overallPromotion")
            if isinstance(contract.get("phase4ProductCutover"), dict)
            else None
        )
        expected_evidence = (
            PHASE4_PROMOTION_EVIDENCE_PASSED
            if promotion == "passed"
            else PHASE4_PROMOTION_EVIDENCE_PENDING
        )
        if checkpoint.get("promotionEvidence") != expected_evidence:
            errors.append(
                "runtime-refactor-contract review checkpoint promotion evidence must match "
                "overall Phase 4 promotion state"
            )

    versions = contract.get("contractVersions")
    required_versions = {
        "productPlan": 1,
        "corePlan": 1,
        "evidenceIdentity": 1,
        "sampling": 2,
        "chunking": 1,
        "memory": 1,
        "telemetry": 9,
        "telemetryTransition": 9,
        "benchmarkEvidence": 3,
    }
    if versions != required_versions:
        errors.append("runtime-refactor-contract versions differ from shipping/shadow schemas")

    chunks = contract.get("constrainedTierChunkFrames")
    expected_chunks = {
        "custom": {"first": 7, "later": 7},
        "design": {"first": 7, "later": 14},
        "clone": {"first": 7, "later": 14},
    }
    if chunks != expected_chunks:
        errors.append("runtime-refactor-contract constrained-tier chunk frames drifted")

    characterization = contract.get("characterization")
    if not isinstance(characterization, dict):
        errors.append("runtime-refactor-contract characterization must be an object")
    else:
        if characterization.get("candidateBudgetsAreHypotheses") is not True:
            errors.append("runtime-refactor-contract candidate budgets must remain hypotheses")
        for key, minimum in (
            ("minimumCleanControlRuns", 3),
            ("minimumWarmTakesPerPromotedCell", 10),
            ("minimumColdTakesPerPromotedCell", 3),
        ):
            value = characterization.get(key)
            if not isinstance(value, int) or value < minimum:
                errors.append(f"runtime-refactor-contract {key} must be at least {minimum}")
        maximum_noise = characterization.get("maximumAcceptedTimingNoisePercent")
        if not isinstance(maximum_noise, (int, float)) or maximum_noise > 8:
            errors.append("runtime-refactor-contract cannot accept timing noise above 8 percent")

    authorities = contract.get("currentShippingAuthorities")
    if not isinstance(authorities, dict) or set(authorities) != {
        "runtime", "productSession", "ownedRuntimeFacade", "sampling", "memory",
        "planShadow", "telemetry", "benchmarkHistory", "modelStorage", "longForm",
        "quality", "custom", "design", "clone"
    }:
        errors.append("runtime-refactor-contract must name every current shipping authority")

    if compatibility is None:
        try:
            compatibility = load_json(
                ROOT / "Packages/VocelloQwen3Core/COMPATIBILITY.json"
            )
        except ValueError as exc:
            errors.append(str(exc))
            compatibility = {}
    if observed_spi_consumers is None:
        observed_spi_consumers = phase2_legacy_spi_product_consumers()

    phase2 = contract.get("phase2PublicMutationBoundary")
    expected_phase2_keys = {
        "status",
        "normalPublicMutationAuthority",
        "legacyShippingSPI",
        "legacyShippingSPIConsumers",
        "consumerAllowlistEnforcement",
        "combinedCompatibilitySession",
        "actorCorrectnessClosure",
        "cloneHandleLifecycle",
        "shippingAuthorityChanged",
    }
    if not isinstance(phase2, dict) or set(phase2) != expected_phase2_keys:
        errors.append(
            "runtime-refactor-contract must define the complete Phase 2 public mutation boundary"
        )
        phase2 = phase2 if isinstance(phase2, dict) else {}
    if phase2.get("status") != "complete-actor-owned-loading-spi-retired-2026-07-23":
        errors.append(
            "runtime-refactor-contract Phase 2 must record the retired-SPI actor-owned state"
        )
    if phase2.get("normalPublicMutationAuthority") != "VocelloQwen3Engine":
        errors.append("runtime-refactor-contract Phase 2 mutation authority must be the engine actor")
    if phase2.get("legacyShippingSPI") != LEGACY_COMPATIBILITY_SPI:
        errors.append("runtime-refactor-contract Phase 2 legacy SPI name drifted")
    if phase2.get("consumerAllowlistEnforcement") != (
        "scripts/vendor_runtime_contract.py::LEGACY_COMPATIBILITY_SPI_CONSUMERS"
    ):
        errors.append("runtime-refactor-contract Phase 2 SPI enforcement reference drifted")
    if phase2.get("combinedCompatibilitySession") != (
        "retired-2026-07-23-phase14a-classified-session-is-sole-generation-session"
    ):
        errors.append("runtime-refactor-contract combined compatibility session must remain retired")
    if phase2.get("actorCorrectnessClosure") != PHASE2_ACTOR_CORRECTNESS_CLOSURE:
        errors.append("runtime-refactor-contract Phase 2 actor correctness closure drifted")
    if phase2.get("cloneHandleLifecycle") != PHASE2_CLONE_HANDLE_LIFECYCLE:
        errors.append("runtime-refactor-contract Phase 2 clone-handle lifecycle drifted")
    if phase2.get("shippingAuthorityChanged") is not True:
        errors.append("runtime-refactor-contract must record the Phase 4 shipping-authority change")

    source_compatibility_value = compatibility.get("sourceCompatibility", {})
    source_compatibility = (
        source_compatibility_value if isinstance(source_compatibility_value, dict) else {}
    )
    spi_metadata_value = source_compatibility.get("retiredLegacySPI", {})
    spi_metadata = spi_metadata_value if isinstance(spi_metadata_value, dict) else {}
    if "temporaryLegacySPI" in source_compatibility:
        errors.append("COMPATIBILITY must not reintroduce the temporary legacy SPI record")
    if spi_metadata.get("name") != phase2.get("legacyShippingSPI"):
        errors.append("runtime-refactor-contract Phase 2 SPI differs from COMPATIBILITY")
    if spi_metadata.get("status") != "retired-2026-07-23-phase14b-actor-owned-loading":
        errors.append("COMPATIBILITY legacy SPI must remain retired")
    declared_consumers = string_list_set(phase2.get("legacyShippingSPIConsumers"))
    registered_consumers = string_list_set(spi_metadata.get("consumerAllowlist"))
    if declared_consumers is None:
        errors.append("runtime-refactor-contract Phase 2 SPI consumers must be a string list")
        declared_consumers = set()
    if registered_consumers is None:
        errors.append("COMPATIBILITY legacy SPI consumer allowlist must be a string list")
        registered_consumers = set()
    if declared_consumers != registered_consumers:
        errors.append("runtime-refactor-contract Phase 2 SPI consumers differ from COMPATIBILITY")
    if declared_consumers != observed_spi_consumers:
        errors.append("runtime-refactor-contract Phase 2 SPI consumers differ from actual imports")
    stable_contracts = string_list_set(source_compatibility.get("stableContracts"))
    if stable_contracts is None:
        errors.append("COMPATIBILITY stable contracts must be a string list")
        stable_contracts = set()
    if not PHASE2_REQUIRED_STABLE_CONTRACTS.issubset(stable_contracts):
        errors.append("COMPATIBILITY stable contracts omit a required Phase 2 actor contract")
    internal_surfaces = string_list_set(
        source_compatibility.get("internalCharacterizationSurfaces")
    )
    if internal_surfaces is None:
        errors.append("COMPATIBILITY internal characterization surfaces must be a string list")
        internal_surfaces = set()
    if internal_surfaces != PHASE2_INTERNAL_CHARACTERIZATION_SURFACES:
        errors.append("COMPATIBILITY internal characterization surface inventory drifted")
    phase4 = contract.get("phase4ProductCutover")
    expected_phase4_keys = {
        "implementationStatus",
        "shippingRuntime",
        "shippingProductSession",
        "modeAuthority",
        "modes",
        "shippingImplementationSources",
        "directModeStreamCallsAllowed",
        "audioBearingBufferedEventsAllowed",
        "mixedShippingAuthorityAllowed",
        "deterministicVerification",
        "macosFocusedAcceptance",
        "physicalIPhoneFocusedAcceptance",
        "overallPromotion",
    }
    if not isinstance(phase4, dict) or set(phase4) != expected_phase4_keys:
        errors.append("runtime-refactor-contract must define the complete Phase 4 product cutover")
        phase4 = phase4 if isinstance(phase4, dict) else {}
    if phase4.get("implementationStatus") != PHASE4_IMPLEMENTATION_STATUS:
        errors.append("runtime-refactor-contract Phase 4 implementation must be complete")
    if phase4.get("shippingRuntime") != "VocelloQwen3Engine":
        errors.append("runtime-refactor-contract Phase 4 runtime must be VocelloQwen3Engine")
    if phase4.get("shippingProductSession") != "GenerationOutputAdapter":
        errors.append("runtime-refactor-contract Phase 4 product session must be GenerationOutputAdapter")
    if phase4.get("modeAuthority") != PHASE4_MODE_AUTHORITY:
        errors.append("runtime-refactor-contract Phase 4 mode authority drifted")
    if phase4.get("modes") != ["custom", "design", "clone"]:
        errors.append("runtime-refactor-contract Phase 4 must cut over Custom, Design, and Clone together")
    implementation_sources = phase4.get("shippingImplementationSources")
    if (
        not isinstance(implementation_sources, list)
        or not implementation_sources
        or len(implementation_sources) != len(set(implementation_sources))
        or any(not isinstance(item, str) or not (ROOT / item).is_file() for item in implementation_sources)
    ):
        errors.append("runtime-refactor-contract Phase 4 shipping sources must resolve uniquely")
    else:
        adapter_sources = [
            item
            for item in implementation_sources
            if "GenerationOutputAdapter" in (ROOT / item).read_text(encoding="utf-8")
        ]
        if not adapter_sources:
            errors.append("runtime-refactor-contract Phase 4 shipping sources omit GenerationOutputAdapter")
        direct_sites = phase4_direct_mode_call_sites(implementation_sources)
        if direct_sites:
            errors.append(
                "runtime-refactor-contract Phase 4 shipping adapter invokes direct mode streams: "
                + ", ".join(direct_sites)
            )
        preview_is_published = any(
            "previewAudio: previewAudio" in (ROOT / item).read_text(encoding="utf-8")
            for item in implementation_sources
        )
        event_router = ROOT / "Sources/QwenVoiceCore/GenerationEventDeliveryProbe.swift"
        event_router_uses_dropping_buffer = (
            event_router.is_file()
            and ".bufferingNewest" in event_router.read_text(encoding="utf-8")
        )
        if preview_is_published and event_router_uses_dropping_buffer:
            errors.append(
                "runtime-refactor-contract Phase 4 adapter still routes preview PCM through "
                "the dropping GenerationEvent path"
            )
    if phase4.get("directModeStreamCallsAllowed") is not False:
        errors.append("runtime-refactor-contract Phase 4 cannot allow direct mode-stream calls")
    if phase4.get("audioBearingBufferedEventsAllowed") is not False:
        errors.append("runtime-refactor-contract Phase 4 cannot allow audio-bearing buffered events")
    if phase4.get("mixedShippingAuthorityAllowed") is not False:
        errors.append("runtime-refactor-contract Phase 4 cannot allow mixed shipping authority")
    if phase4.get("deterministicVerification") not in PHASE4_VERIFICATION_STATES:
        errors.append("runtime-refactor-contract Phase 4 deterministic verification state is invalid")
    if phase4.get("macosFocusedAcceptance") not in PHASE4_VERIFICATION_STATES:
        errors.append("runtime-refactor-contract Phase 4 macOS acceptance state is invalid")
    if phase4.get("physicalIPhoneFocusedAcceptance") not in PHASE4_IPHONE_ACCEPTANCE_STATES:
        errors.append("runtime-refactor-contract Phase 4 iPhone acceptance state is invalid")
    all_verification_passed = (
        phase4.get("deterministicVerification") == "passed"
        and phase4.get("macosFocusedAcceptance") == "passed"
        and phase4.get("physicalIPhoneFocusedAcceptance") == "passed"
    )
    if all_verification_passed:
        if phase4.get("overallPromotion") not in {"pending", "passed"}:
            errors.append("runtime-refactor-contract Phase 4 promotion state is invalid")
    elif phase4.get("overallPromotion") != "pending":
        errors.append("runtime-refactor-contract cannot promote Phase 4 before all acceptance passes")

    if isinstance(authorities, dict):
        expected_phase4_authorities = {
            "runtime": phase4.get("shippingRuntime"),
            "productSession": phase4.get("shippingProductSession"),
            "ownedRuntimeFacade": "VocelloQwen3Core",
            "custom": phase4.get("modeAuthority"),
            "design": phase4.get("modeAuthority"),
            "clone": phase4.get("modeAuthority"),
        }
        if any(authorities.get(key) != value for key, value in expected_phase4_authorities.items()):
            errors.append("runtime-refactor-contract current authorities differ from Phase 4 cutover")

    phases = contract.get("phaseStatus")
    required_phases = {
        "characterizationContract", "xpcReserveBeforeSideEffects",
        "synchronizedPressureSnapshot", "continuousCriticalReliefAdmission",
        "immutablePlans", "engineActor", "classifiedSessionChannels",
        "productOutputAdapter", "modeCutover", "requestLocalSamplingV2",
        "telemetryV9", "chunkAndPreviewExperiments", "sharedComponentStorage",
        "runtimeComponentReuse", "spokenTextPlanning", "longFormV4",
        "boundedAnalyzers", "unifiedQuality", "historyV3", "mechanicalRetirement",
    }
    if not isinstance(phases, dict) or set(phases) != required_phases:
        errors.append("runtime-refactor-contract must name every convergence phase status")
    elif not all(
        isinstance(value, str)
        and value
        and value == value.strip()
        and all(character.islower() or character.isdigit() or character == "-" for character in value)
        for value in phases.values()
    ):
        errors.append("runtime-refactor-contract phase statuses must be safe tokens")
    elif isinstance(authorities, dict):
        compatibility_modes = {authorities.get(mode) for mode in ("custom", "design", "clone")}
        if compatibility_modes != {PHASE4_MODE_AUTHORITY}:
            errors.append("runtime-refactor-contract cannot claim Phase 4 with mixed mode authority")
        expected_mode_cutover = (
            PHASE4_MODE_CUTOVER_PASSED
            if phase4.get("overallPromotion") == "passed"
            else PHASE4_MODE_CUTOVER_PENDING
        )
        if phases.get("modeCutover") != expected_mode_cutover:
            errors.append("runtime-refactor-contract Phase 4 mode-cutover status drifted")
        if isinstance(versions, dict) and versions.get("telemetry") == 8:
            expected_transition = (
                "partial-transition-projection-embedded-in-v8-"
                "live-producers-landed-history-authority-pending"
            )
            if phases.get("telemetryV9") != expected_transition or authorities.get("telemetry") != (
                "generation-telemetry-v8-with-partial-v9-transition-projection"
            ):
                errors.append(
                    "runtime-refactor-contract cannot claim complete telemetry v9 while schema v8 ships"
                )
        if isinstance(versions, dict) and versions.get("telemetry") == 9:
            if phases.get("telemetryV9") != "complete-sidecar-authority-with-v8-envelope":
                errors.append(
                    "runtime-refactor-contract telemetry v9 must declare complete sidecar authority"
                )
            if authorities.get("telemetry") != (
                "generation-telemetry-v8-envelope-with-complete-v9-sidecar-authority"
            ):
                errors.append(
                    "runtime-refactor-contract telemetry authority must match complete v9 sidecars"
                )
        if isinstance(phases, dict) and phases.get("requestLocalSamplingV2") != (
            "shipping-promotion-packaged-evidence-live"
        ):
            errors.append(
                "runtime-refactor-contract Phase 5 sampling status must be promotion-packaged"
            )
        if isinstance(versions, dict) and versions.get("benchmarkEvidence") == 2 and phases.get("historyV3") != "pending-stable-plan-session-quality-identities":
            errors.append("runtime-refactor-contract cannot claim history v3 while schema v2 ships")
        if isinstance(versions, dict) and versions.get("benchmarkEvidence") == 3:
            if str(phases.get("historyV3", "")).startswith("pending"):
                errors.append(
                    "runtime-refactor-contract benchmarkEvidence 3 requires a non-pending historyV3 status"
                )
            if not (ROOT / "benchmarks" / "schema-v3.json").is_file():
                errors.append(
                    "runtime-refactor-contract benchmarkEvidence 3 requires benchmarks/schema-v3.json"
                )
    expected_actor = (
        PHASE2_ENGINE_ACTOR_STATUS_PASSED
        if isinstance(phase4, dict) and phase4.get("overallPromotion") == "passed"
        else PHASE2_ENGINE_ACTOR_STATUS_PENDING
    )
    expected_classified = (
        PHASE2_CLASSIFIED_SESSION_STATUS_PASSED
        if isinstance(phase4, dict) and phase4.get("overallPromotion") == "passed"
        else PHASE2_CLASSIFIED_SESSION_STATUS_PENDING
    )
    expected_adapter = (
        PHASE4_PRODUCT_ADAPTER_STATUS_PASSED
        if isinstance(phase4, dict) and phase4.get("overallPromotion") == "passed"
        else PHASE4_PRODUCT_ADAPTER_STATUS_PENDING
    )
    if isinstance(phases, dict) and phases.get("engineActor") != expected_actor:
        errors.append("runtime-refactor-contract engine actor shipping status drifted")
    if isinstance(phases, dict) and phases.get("classifiedSessionChannels") != expected_classified:
        errors.append("runtime-refactor-contract classified-session shipping status drifted")
    if isinstance(phases, dict) and phases.get("productOutputAdapter") != expected_adapter:
        errors.append("runtime-refactor-contract product-output-adapter status drifted")
    compatibility_surfaces = contract.get("temporaryCompatibilitySurfaces")
    if not isinstance(compatibility_surfaces, list) or not compatibility_surfaces or len(compatibility_surfaces) != len(set(compatibility_surfaces)):
        errors.append("runtime-refactor-contract compatibility surfaces must be unique and non-empty")
    invariants = contract.get("invariants")
    if not isinstance(invariants, list) or not invariants or len(invariants) != len(set(invariants)):
        errors.append("runtime-refactor-contract invariants must be unique and non-empty")
    return errors


def validate_runtime_refactor_contract() -> list[str]:
    contract = load_json(ROOT / "config/runtime-refactor-contract.json")
    decision = contract.get("decision")
    decision_exists = isinstance(decision, str) and (ROOT / decision).is_file()
    return runtime_refactor_contract_errors(contract, decision_exists=decision_exists)


def validate_docs() -> list[str]:
    errors: list[str] = []
    threat = ROOT / "docs/decisions/runtime-hardening-and-trust-boundary.md"
    naming = ROOT / "docs/decisions/product-identity-compatibility.md"
    convergence = ROOT / "docs/decisions/runtime-streaming-quality-convergence.md"
    if not threat.is_file():
        errors.append("missing runtime hardening threat-model ADR")
    else:
        text = threat.read_text(encoding="utf-8")
        for required in ("app-sandbox", "disable-library-validation", "allow-unsigned-executable-memory"):
            if required not in text:
                errors.append(f"runtime hardening ADR missing entitlement: {required}")
    if not naming.is_file():
        errors.append("missing product identity compatibility ADR")
    if not convergence.is_file():
        errors.append("missing runtime streaming and quality convergence ADR")
    return errors


def main() -> int:
    errors: list[str] = []
    try:
        errors.extend(validate_debug_contract())
        errors.extend(validate_concurrency_contract())
        errors.extend(validate_runtime_refactor_contract())
        errors.extend(validate_release_contract())
        errors.extend(validate_docs())
    except ValueError as exc:
        errors.append(str(exc))
    if errors:
        for error in errors:
            print(f"error: {error}")
        return 1
    print("runtime security contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
