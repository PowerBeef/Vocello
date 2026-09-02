#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("vendor_runtime_contract", ROOT / "scripts/vendor_runtime_contract.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class VendorRuntimeContractTests(unittest.TestCase):
    def test_repository_contract_is_valid(self) -> None:
        self.assertEqual(MODULE.validate(ROOT), [])

    def test_generated_project_and_dependency_automation_use_owned_path(self) -> None:
        self.assertIn(
            "Packages/VocelloQwen3Core",
            (ROOT / "QwenVoice.xcodeproj/project.pbxproj").read_text(encoding="utf-8"),
        )
        self.assertIn(
            'directory: "/Packages/VocelloQwen3Core"',
            (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"),
        )

    def test_facade_api_baseline_is_canonical_and_hides_raw_runtime_types(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        baseline = MODULE.load_json(runtime / MODULE.FACADE_API_BASELINE_NAME)
        self.assertEqual(baseline, MODULE.make_facade_api_baseline(runtime))
        self.assertTrue(baseline["publicDeclarations"])
        self.assertEqual(
            [
                declaration
                for declaration in baseline["publicDeclarations"]
                if MODULE.FORBIDDEN_FACADE_API_TYPES.search(declaration)
            ],
            [],
        )
        self.assertEqual(
            MODULE.legacy_compatibility_declaration_errors(
                baseline["publicDeclarations"]
            ),
            [],
        )
        # Phase 14b: the retired SPI and its loaded-model surface may not
        # appear in the public baseline at all.
        self.assertEqual(
            [
                declaration
                for declaration in baseline["publicDeclarations"]
                if MODULE.LEGACY_COMPATIBILITY_SPI_ATTRIBUTE in declaration
                or "VocelloQwen3LoadedModel:" in declaration
            ],
            [],
        )

    def test_facade_canonicalizer_preserves_only_legacy_spi_attribute_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "Facade.swift"
            source.write_text(
                """
@_spi(VocelloQwen3LegacyCompatibility)
@available(macOS 26.0, *)
public final class VocelloQwen3LoadedModel {}

@discardableResult
public func stableFacadeEntryPoint() -> Bool { true }
""",
                encoding="utf-8",
            )
            self.assertEqual(
                MODULE.canonical_public_declarations(source),
                [
                    "@_spi(VocelloQwen3LegacyCompatibility) "
                    "@available(macOS 26.0, *) "
                    "public final class VocelloQwen3LoadedModel",
                    "public func stableFacadeEntryPoint() -> Bool",
                ],
            )

    def test_retired_legacy_symbols_may_not_return_publicly_or_via_spi(self) -> None:
        ordinary_declarations = (
            "public class VocelloQwen3LoadedModel: Sendable",
            "public enum VocelloQwen3GenerationEvent: Sendable",
            "public protocol VocelloQwen3GenerationSession: Sendable",
            "public final class VocelloQwen3ModelGenerationSession: Sendable",
            "public extension VocelloQwen3LoadedModel",
        )
        for declaration in ordinary_declarations:
            with self.subTest(declaration=declaration):
                errors = MODULE.legacy_compatibility_declaration_errors([declaration])
                self.assertEqual(len(errors), 1)
                self.assertIn("retired public", errors[0])
                spi_errors = MODULE.legacy_compatibility_declaration_errors(
                    [f"{MODULE.LEGACY_COMPATIBILITY_SPI_ATTRIBUTE} {declaration}"]
                )
                self.assertEqual(len(spi_errors), 1)
                self.assertIn("retired", spi_errors[0])

        self.assertEqual(
            MODULE.legacy_compatibility_declaration_errors(
                [
                    "final class VocelloQwen3ModelGenerationSession: Sendable",
                    "public func loadedModelFacts() -> VocelloQwen3LoadedModelFacts?",
                ]
            ),
            [],
        )

    def test_legacy_compatibility_spi_consumers_match_the_precise_allowlist(self) -> None:
        observed = MODULE.legacy_compatibility_spi_consumers(ROOT)
        self.assertEqual(observed, set())
        self.assertEqual(MODULE.LEGACY_COMPATIBILITY_SPI_CONSUMERS, frozenset())
        self.assertEqual(MODULE.legacy_compatibility_consumer_errors(observed), [])

        extra = {"Sources/QwenVoiceCore/UnapprovedConsumer.swift"}
        self.assertTrue(
            any(
                "unapproved" in error
                for error in MODULE.legacy_compatibility_consumer_errors(extra)
            )
        )

    def test_legacy_compatibility_metadata_matches_enforced_boundary(self) -> None:
        compatibility = MODULE.load_json(
            ROOT / MODULE.RUNTIME_RELATIVE / MODULE.COMPATIBILITY_NAME
        )
        self.assertEqual(MODULE.legacy_compatibility_metadata_errors(compatibility), [])

        drifted = json.loads(json.dumps(compatibility))
        drifted["sourceCompatibility"]["retiredLegacySPI"]["consumerAllowlist"].append(
            "Sources/QwenVoiceCore/UnapprovedConsumer.swift"
        )
        self.assertIn(
            "COMPATIBILITY retired SPI consumer allowlist must stay empty",
            MODULE.legacy_compatibility_metadata_errors(drifted),
        )

        reintroduced = json.loads(json.dumps(compatibility))
        reintroduced["sourceCompatibility"]["temporaryLegacySPI"] = {
            "name": MODULE.LEGACY_COMPATIBILITY_SPI
        }
        self.assertIn(
            "COMPATIBILITY must not reintroduce the temporary legacy SPI record",
            MODULE.legacy_compatibility_metadata_errors(reintroduced),
        )

    def test_facade_type_filter_rejects_third_party_cache_types(self) -> None:
        self.assertIsNotNone(
            MODULE.FORBIDDEN_FACADE_API_TYPES.search(
                "public static func load(cache: HubCache)"
            )
        )
        self.assertIsNone(
            MODULE.FORBIDDEN_FACADE_API_TYPES.search(
                "public static func load(cachePolicy: VocelloQwen3CachePolicy)"
            )
        )

    def test_every_retained_file_has_owned_capability_coverage(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        inventory = MODULE.load_json(runtime / MODULE.CURRENT_INVENTORY_NAME)
        contract = MODULE.load_json(runtime / MODULE.CAPABILITIES_NAME)
        patterns = [
            pattern
            for capability in contract["capabilities"]
            for pattern in capability["sourcePatterns"]
        ]
        uncovered = []
        for entry in inventory["entries"]:
            if not MODULE.matches(entry["path"], patterns):
                uncovered.append(entry["path"])
        self.assertEqual(uncovered, [])
        self.assertEqual(MODULE.facade_capability_boundary_errors(contract), [])

        drifted = copy.deepcopy(contract)
        actor_generation = next(
            item
            for item in drifted["capabilities"]
            if item["id"] == MODULE.SHIPPING_ACTOR_CAPABILITY_ID
        )
        actor_generation["state"] = "internal"
        self.assertTrue(
            any(
                "shipping actor/session capability" in error
                for error in MODULE.facade_capability_boundary_errors(drifted)
            )
        )

    def test_immutable_baseline_and_current_inventory_are_separate(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        baseline = MODULE.load_json(runtime / MODULE.BASELINE_NAME)
        inventory = MODULE.load_json(runtime / MODULE.CURRENT_INVENTORY_NAME)
        baseline_paths = {entry["path"] for entry in baseline["entries"]}
        added_paths = {
            entry["path"]
            for entry in inventory["entries"]
            if entry["upstreamStatus"] == "added"
        }
        self.assertTrue(added_paths)
        self.assertTrue(added_paths.isdisjoint(baseline_paths))
        self.assertTrue(all(len(entry["sha256"]) == 64 for entry in baseline["entries"]))
        self.assertEqual(
            inventory,
            MODULE.make_current_inventory(runtime, baseline, "vocello-qwen3-core"),
        )

    def test_changed_or_added_implementation_files_have_semantic_coverage(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        inventory = MODULE.load_json(runtime / MODULE.CURRENT_INVENTORY_NAME)
        capabilities = MODULE.load_json(runtime / MODULE.CAPABILITIES_NAME)
        patches = MODULE.load_json(runtime / MODULE.PATCHES_NAME)
        capability_patterns = [
            pattern
            for capability in capabilities["capabilities"]
            for pattern in capability["sourcePatterns"]
        ]
        patch_patterns = [
            pattern
            for patch in patches["patches"]
            for pattern in patch["files"]
        ]
        impacted = [
            entry["path"]
            for entry in inventory["entries"]
            if entry["upstreamStatus"] in {"modified", "added"}
            and MODULE.matches(entry["path"], list(MODULE.IMPLEMENTATION_SCOPE))
        ]
        self.assertTrue(impacted)
        self.assertEqual(
            [path for path in impacted if not MODULE.matches(path, capability_patterns)],
            [],
        )
        self.assertEqual(
            [path for path in impacted if not MODULE.matches(path, patch_patterns)],
            [],
        )
        patches_by_id = {entry["id"]: entry for entry in patches["patches"]}
        unlinked = [
            path
            for path in impacted
            if not any(
                MODULE.matches(path, capability["sourcePatterns"])
                and any(
                    MODULE.matches(path, patches_by_id[patch_id]["files"])
                    for patch_id in capability["upstreamDeltaIDs"]
                )
                for capability in capabilities["capabilities"]
            )
        ]
        self.assertEqual(unlinked, [])

    def test_semantic_delta_entries_have_controlled_live_references(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        ledger = MODULE.load_json(runtime / MODULE.PATCHES_NAME)
        states = set(ledger["allowedStates"])
        dispositions = set(ledger["allowedUpstreamDispositions"])
        evidence_classes = set(ledger["allowedEvidenceClasses"])
        for entry in ledger["patches"]:
            self.assertIn(entry["state"], states)
            self.assertIn(entry["upstreamDisposition"], dispositions)
            self.assertIn(entry["evidenceClass"], evidence_classes)
            self.assertTrue(MODULE.expanded(runtime, entry["files"]))
            self.assertTrue(MODULE.expanded(runtime, entry["tests"]))
            self.assertTrue(MODULE.expanded(runtime, entry["documentation"]))
            self.assertTrue(entry["removalCriteria"].strip())

    def test_lineage_digest_pins_immutable_import_inventory(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        lineage = MODULE.load_json(runtime / MODULE.LINEAGE_NAME)
        self.assertEqual(
            lineage["baselineInventory"]["sha256"],
            MODULE.sha256(runtime / MODULE.BASELINE_NAME),
        )

    def test_owned_targets_do_not_import_repository_layers(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        ownership = MODULE.load_json(runtime / MODULE.OWNERSHIP_NAME)
        forbidden = set(ownership["forbiddenRepositoryImports"])
        for contract in ownership["targets"].values():
            imports = MODULE.swift_imports(runtime / contract["sourceRoot"])
            self.assertEqual(imports & forbidden, set())

    def test_import_scanner_includes_preconcurrency_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Imports.swift").write_text(
                "import Foundation\n@preconcurrency import MLX\n",
                encoding="utf-8",
            )
            self.assertEqual(MODULE.swift_imports(root), {"Foundation", "MLX"})

    def test_owned_target_dependency_inventory_matches_package(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        package = (runtime / "Package.swift").read_text(encoding="utf-8")
        blocks = MODULE.package_target_blocks(package)
        ownership = MODULE.load_json(runtime / MODULE.OWNERSHIP_NAME)
        names = set(ownership["targets"])
        for target, contract in ownership["targets"].items():
            actual = {
                candidate
                for candidate in names
                if candidate != target and f'"{candidate}"' in blocks[target]
            }
            self.assertEqual(actual, set(contract["allowedRuntimeTargetDependencies"]))

    def test_baseline_builder_is_deterministic(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        lineage = MODULE.load_json(runtime / MODULE.LINEAGE_NAME)
        # Reusing the runtime as a synthetic upstream proves ordering/shape without network access.
        rebuilt = MODULE.make_baseline(
            runtime,
            runtime,
            lineage["origin"]["commit"],
            "vocello-qwen3-core",
        )
        self.assertEqual(
            [entry["path"] for entry in rebuilt["entries"]],
            sorted(entry["path"] for entry in rebuilt["entries"]),
        )
        self.assertTrue(all(len(entry["sha256"]) == 64 for entry in rebuilt["entries"]))

    def test_baseline_rebuild_preserves_the_immutable_path_set(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        baseline = MODULE.load_json(runtime / MODULE.BASELINE_NAME)
        paths = [entry["path"] for entry in baseline["entries"]]
        rebuilt = MODULE.make_baseline(
            runtime,
            runtime,
            baseline["upstreamCommit"],
            baseline["componentID"],
            paths,
        )
        self.assertEqual([entry["path"] for entry in rebuilt["entries"]], paths)

    def test_current_benchmark_records_have_truthful_runtime_capability_status(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        contract = MODULE.load_json(runtime / MODULE.CAPABILITIES_NAME)
        records = MODULE.benchmark_records(ROOT)
        measured_capabilities = [
            item for item in contract["capabilities"] if item.get("benchmarkRecordIDs")
        ]
        self.assertTrue(measured_capabilities)
        for item in measured_capabilities:
            fresh = MODULE.capability_benchmark_is_fresh(ROOT, runtime, item, records)
            if item["evidenceClass"] == "benchmark":
                self.assertEqual(item["benchmarkEvidenceStatus"], "verified")
                self.assertTrue(fresh)
            else:
                self.assertEqual(item["evidenceClass"], "diagnostic")
                self.assertEqual(item["benchmarkEvidenceStatus"], "diagnostic")
                self.assertTrue(item["benchmarkEvidenceReason"])
                self.assertFalse(fresh)

    def test_stale_benchmark_cannot_be_reclassified_as_verified(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        contract = MODULE.load_json(runtime / MODULE.CAPABILITIES_NAME)
        records = MODULE.benchmark_records(ROOT)
        capability = copy.deepcopy(
            next(item for item in contract["capabilities"] if item.get("benchmarkRecordIDs"))
        )
        capability["evidenceClass"] = "benchmark"
        capability["benchmarkRecordIDs"] = [
            "macos-xcui-benchmark-20260713-185716-7f12cd35"
        ]
        capability["benchmarkEvidenceStatus"] = "verified"
        errors = MODULE.capability_benchmark_evidence_errors(
            ROOT,
            runtime,
            capability,
            records,
            set(contract["allowedBenchmarkEvidenceStatuses"]),
        )
        self.assertTrue(any("must be diagnostic or unverified" in error for error in errors))

    def test_failed_or_unvalidated_benchmark_is_never_fresh_evidence(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        record = copy.deepcopy(next(iter(MODULE.benchmark_records(ROOT).values())))
        record["run"]["status"] = "failed"
        record["evidence"]["validatorPassed"] = False
        record["digest"] = MODULE.canonical_record_digest(record)
        self.assertFalse(MODULE.benchmark_record_is_eligible(record))
        self.assertFalse(
            MODULE.benchmark_record_matches_sources(
                ROOT,
                runtime,
                ["Sources/MLXAudioCore/ModelUtils.swift"],
                record,
            )
        )

    def test_dependency_drift_invalidates_runtime_benchmark_evidence(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        records = MODULE.benchmark_records(ROOT)
        eligible = [record for record in records.values() if MODULE.benchmark_record_is_eligible(record)]
        self.assertTrue(eligible)
        git_blob = MODULE.git_blob

        def blob_with_dependency_drift(repo_root: Path, commit: str, path: Path) -> bytes | None:
            blob = git_blob(repo_root, commit, path)
            if path.name == "Package.resolved" and blob is not None:
                payload = json.loads(blob)
                for pin in payload["pins"]:
                    if pin["identity"] == "mlx-swift":
                        pin["state"]["revision"] = "0" * 40
                        break
                return json.dumps(payload, sort_keys=True).encode("utf-8")
            return blob

        with mock.patch.object(MODULE, "git_blob", side_effect=blob_with_dependency_drift):
            self.assertFalse(
                MODULE.benchmark_record_matches_sources(
                    ROOT,
                    runtime,
                    ["Sources/MLXAudioCore/ModelUtils.swift"],
                    eligible[0],
                )
            )

    def test_benchmark_neutral_security_dependency_drift_preserves_evidence(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        records = MODULE.benchmark_records(ROOT)
        record = records["macos-xcui-benchmark-20260801-182943-b0b5a448"]
        git_blob = MODULE.git_blob

        # Tree-independence: synthesize the "historical" package manifest and
        # lockfile from the CURRENT tree so the only difference is the injected
        # neutral drift. Reading them from the record's real commit made the
        # test break on every legitimate non-neutral pin bump (first hit:
        # swift-transformers 1.3.3), which is the contract working — not the
        # property under test here.
        def blob_with_neutral_drift(repo_root: Path, commit: str, path: Path) -> bytes | None:
            if path.name == "Package.swift":
                return (runtime / "Package.swift").read_bytes()
            if path.name == "Package.resolved":
                payload = json.loads((runtime / "Package.resolved").read_bytes())
                for pin in payload["pins"]:
                    if pin["identity"] == "swift-nio":
                        pin["state"] = {"revision": "0" * 40, "version": "2.99.0"}
                        break
                return json.dumps(payload, sort_keys=True).encode("utf-8")
            if path.as_posix().endswith("Sources/MLXAudioCore/ModelUtils.swift"):
                return (runtime / "Sources/MLXAudioCore/ModelUtils.swift").read_bytes()
            return git_blob(repo_root, commit, path)

        with mock.patch.object(MODULE, "git_blob", side_effect=blob_with_neutral_drift):
            self.assertTrue(
                MODULE.benchmark_record_matches_sources(
                    ROOT,
                    runtime,
                    ["Sources/MLXAudioCore/ModelUtils.swift"],
                    record,
                )
            )

    def test_benchmark_neutral_dependency_source_drift_invalidates_evidence(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        records = MODULE.benchmark_records(ROOT)
        record = records["macos-xcui-benchmark-20260801-182943-b0b5a448"]
        git_blob = MODULE.git_blob

        for field, value in (
            ("kind", "localSourceControl"),
            ("location", "https://example.invalid/swift-nio.git"),
        ):
            with self.subTest(field=field):
                def blob_with_source_drift(
                    repo_root: Path,
                    commit: str,
                    path: Path,
                ) -> bytes | None:
                    # Same tree-independence as the neutral-drift test above.
                    if path.name == "Package.swift":
                        return (runtime / "Package.swift").read_bytes()
                    if path.name == "Package.resolved":
                        payload = json.loads((runtime / "Package.resolved").read_bytes())
                        for pin in payload["pins"]:
                            if pin["identity"] == "swift-nio":
                                pin[field] = value
                                break
                        return json.dumps(payload, sort_keys=True).encode("utf-8")
                    if path.as_posix().endswith("Sources/MLXAudioCore/ModelUtils.swift"):
                        return (runtime / "Sources/MLXAudioCore/ModelUtils.swift").read_bytes()
                    return git_blob(repo_root, commit, path)

                with mock.patch.object(MODULE, "git_blob", side_effect=blob_with_source_drift):
                    self.assertFalse(
                        MODULE.benchmark_record_matches_sources(
                            ROOT,
                            runtime,
                            ["Sources/MLXAudioCore/ModelUtils.swift"],
                            record,
                        )
                    )

    def test_benchmark_neutral_dependency_must_resolve_and_cannot_be_direct(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        compatibility = MODULE.load_json(runtime / MODULE.COMPATIBILITY_NAME)
        pin_descriptors = MODULE.resolved_pin_descriptors(
            (runtime / "Package.resolved").read_bytes()
        )
        self.assertEqual(
            MODULE.benchmark_neutral_dependency_errors(
                compatibility["package"],
                pin_descriptors,
            ),
            [],
        )

        unknown = copy.deepcopy(compatibility["package"])
        unknown["benchmarkNeutralResolvedDependencies"]["missing-package"] = "transport only"
        self.assertTrue(
            any(
                "absent from the lock" in error
                for error in MODULE.benchmark_neutral_dependency_errors(unknown, pin_descriptors)
            )
        )

        direct = copy.deepcopy(compatibility["package"])
        direct["benchmarkNeutralResolvedDependencies"]["mlx-swift"] = "not permitted"
        self.assertTrue(
            any(
                "direct runtime dependency cannot be benchmark-neutral" in error
                for error in MODULE.benchmark_neutral_dependency_errors(direct, pin_descriptors)
            )
        )

    def test_contract_references_cannot_escape_the_runtime_root(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        for reference in ("../README.md", "/tmp/reference", "Sources/../../README.md"):
            self.assertFalse(MODULE.safe_contract_reference(reference))
            self.assertEqual(MODULE.expanded(runtime, [reference]), [])
        self.assertTrue(MODULE.safe_contract_reference("Sources/**/*.swift"))

    def test_trailing_recursive_glob_expands_to_files_on_every_runtime(self) -> None:
        # Issue #69: on Python <= 3.12 a trailing "**" matches directories only,
        # so contract scopes like "Tests/**" resolved to zero files. expanded()
        # must normalize the pattern before glob so every runtime sees files.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "Tests" / "Suite"
            nested.mkdir(parents=True)
            (nested / "CaseA.swift").write_text("// a\n", encoding="utf-8")
            (root / "Tests" / "Top.swift").write_text("// b\n", encoding="utf-8")

            observed: list[str] = []
            original_glob = Path.glob

            def recording_glob(self: Path, pattern: str, *args: object, **kwargs: object):
                observed.append(pattern)
                return original_glob(self, pattern, *args, **kwargs)

            with unittest.mock.patch.object(Path, "glob", recording_glob):
                resolved = MODULE.expanded(root, ["Tests/**"])

            self.assertEqual(observed, ["Tests/**/*"])
            self.assertEqual(
                [path.name for path in resolved],
                ["CaseA.swift", "Top.swift"],
            )

    def test_patch_state_and_upstream_disposition_combinations_are_controlled(self) -> None:
        self.assertTrue(MODULE.patch_state_disposition_valid("active", "local-only"))
        self.assertTrue(MODULE.patch_state_disposition_valid("shared", "upstreamed"))
        self.assertTrue(MODULE.patch_state_disposition_valid("removed", "obsolete"))
        self.assertFalse(MODULE.patch_state_disposition_valid("active", "obsolete"))
        self.assertFalse(MODULE.patch_state_disposition_valid("removed", "local-only"))
        self.assertFalse(MODULE.patch_state_disposition_valid("unknown", "local-only"))

    def test_immutable_baseline_requires_a_clean_upstream_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
            tracked = checkout / "Package.swift"
            tracked.write_text("// swift-tools-version: 6.0\n", encoding="utf-8")
            subprocess.run(["git", "add", "Package.swift"], cwd=checkout, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Contract Test",
                    "-c",
                    "user.email=contract@example.invalid",
                    "commit",
                    "-qm",
                    "baseline",
                ],
                cwd=checkout,
                check=True,
            )
            self.assertTrue(MODULE.git_checkout_is_clean(checkout))
            tracked.write_text("// modified\n", encoding="utf-8")
            self.assertFalse(MODULE.git_checkout_is_clean(checkout))
            tracked.write_text("// swift-tools-version: 6.0\n", encoding="utf-8")
            (checkout / "untracked.txt").write_text("untracked\n", encoding="utf-8")
            self.assertFalse(MODULE.git_checkout_is_clean(checkout))

    def test_relocation_records_semantic_changes_instead_of_claiming_byte_parity(self) -> None:
        runtime = ROOT / MODULE.RUNTIME_RELATIVE
        lineage = MODULE.load_json(runtime / MODULE.LINEAGE_NAME)
        relocation = lineage["monorepoRelocation"]
        inventory = MODULE.load_json(runtime / MODULE.RELOCATION_INVENTORY_NAME)
        self.assertEqual(relocation["classification"], "semantic-move-with-modifications-and-additions")
        expected = {"identical": 65, "modified": 11, "added": 12, "removed": 0}
        self.assertEqual(inventory["summary"], expected)
        self.assertEqual(relocation["fileComparison"], inventory["summary"])
        self.assertEqual(
            relocation["inventory"]["sha256"],
            MODULE.sha256(runtime / MODULE.RELOCATION_INVENTORY_NAME),
        )


if __name__ == "__main__":
    unittest.main()
