#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts/build_output_policy.py"
MANIFEST = REPO_ROOT / "config/build-output-policy.json"

SPEC = importlib.util.spec_from_file_location("build_output_policy", HELPER)
assert SPEC and SPEC.loader
POLICY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = POLICY
SPEC.loader.exec_module(POLICY)


REQUIRED_EXPORTS = {
    "QVOICE_BUILD_ROOT",
    "QVOICE_XCODE_MACOS_DERIVED",
    "QVOICE_XCODE_IOS_DERIVED",
    "QVOICE_XCODE_SOURCE_PACKAGES",
    "QVOICE_SWIFTPM_RUNTIME_CACHE",
    "QVOICE_SCRATCH_FOUNDATION",
    "QVOICE_SCRATCH_PACKAGE_RESOLUTION",
    "QVOICE_SCRATCH_TRANSIENT",
    "QVOICE_SCRATCH_GATE_FINGERPRINT",
    "QVOICE_SCRATCH_RELEASE_MACOS",
    "QVOICE_SCRATCH_RELEASE_IOS",
    "QVOICE_SCRATCH_XCODEBUILDMCP_MACOS",
    "QVOICE_SCRATCH_XCODEBUILDMCP_IOS",
    "QVOICE_SCRATCH_CI",
    "QVOICE_ARTIFACTS_MACOS",
    "QVOICE_ARTIFACTS_IOS",
    "QVOICE_ARTIFACTS_UI_TESTS",
    "QVOICE_ARTIFACTS_DIAGNOSTICS",
    "QVOICE_ARTIFACTS_PROJECT_HEALTH",
    "QVOICE_ARTIFACTS_QUALITY_PROMOTION",
    "QVOICE_SYMBOLS_MACOS",
    "QVOICE_SYMBOLS_IOS",
    "QVOICE_ARTIFACTS_FOUNDATION",
    "QVOICE_DIST_MACOS",
    "QVOICE_DIST_IOS",
}


class BuildOutputPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "repo with a ' quote"
        (self.root / "config").mkdir(parents=True)
        self.document = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.write_manifest()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @property
    def manifest(self) -> Path:
        return self.root / "config/build-output-policy.json"

    def write_manifest(self, document: dict | None = None) -> None:
        self.manifest.write_text(
            json.dumps(document or self.document, indent=2) + "\n", encoding="utf-8"
        )

    def command(self, *arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        if env:
            environment.update(env)
        return subprocess.run(
            [
                "python3",
                str(HELPER),
                *arguments,
                "--repo-root",
                str(self.root),
                "--manifest",
                str(self.manifest),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=environment,
        )

    def initialize_git(self) -> None:
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def test_manifest_has_exact_nonoverlapping_contract_and_required_exports(self) -> None:
        policy = POLICY.load_policy(self.root, self.manifest)
        paths = [entry["path"] for entry in policy.entries]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(
            {name for name, _ in POLICY.shell_environment(policy)}, REQUIRED_EXPORTS
        )
        self.assertIn("build/cache/xcode/macos", paths)
        self.assertIn("build/cache/xcode/ios-device", paths)
        self.assertIn("build/scratch/derived-data/release-ios", paths)
        self.assertIn("build/dist/macos", paths)

    def test_manifest_rejects_absolute_escaping_and_overlapping_roots(self) -> None:
        cases = []
        absolute = copy.deepcopy(self.document)
        absolute["entries"][0]["path"] = "/tmp/not-managed"
        cases.append(absolute)
        escaping = copy.deepcopy(self.document)
        escaping["entries"][0]["path"] = "build/cache/../escape"
        cases.append(escaping)
        overlapping = copy.deepcopy(self.document)
        overlapping["entries"][1]["path"] = "build/cache/xcode/macos/nested"
        cases.append(overlapping)
        for document in cases:
            with self.subTest(path=document["entries"][0]["path"]):
                self.write_manifest(document)
                with self.assertRaises(POLICY.PolicyError):
                    POLICY.load_policy(self.root, self.manifest)

    def test_manifest_rejects_unknown_cleanup_and_migration_escape(self) -> None:
        invalid_cleanup = copy.deepcopy(self.document)
        invalid_cleanup["entries"][0]["cleanup"] = "whenever"
        self.write_manifest(invalid_cleanup)
        with self.assertRaises(POLICY.PolicyError):
            POLICY.load_policy(self.root, self.manifest)

    def test_manifest_rejects_invalid_heavy_lane_preflight(self) -> None:
        missing_lane = copy.deepcopy(self.document)
        del missing_lane["heavyLanePreflight"]["lanes"]["ui-benchmark"]
        self.write_manifest(missing_lane)
        with self.assertRaises(POLICY.PolicyError):
            POLICY.load_policy(self.root, self.manifest)

        unsafe_hint = copy.deepcopy(self.document)
        unsafe_hint["heavyLanePreflight"]["lanes"]["release"]["cleanupHint"] = (
            "scripts/clean_build_caches.sh --routine; rm -rf build"
        )
        self.write_manifest(unsafe_hint)
        with self.assertRaises(POLICY.PolicyError):
            POLICY.load_policy(self.root, self.manifest)

        invalid_migration = copy.deepcopy(self.document)
        invalid_migration["migrations"][0]["source"] = "benchmarks/HISTORY.md"
        self.write_manifest(invalid_migration)
        with self.assertRaises(POLICY.PolicyError):
            POLICY.load_policy(self.root, self.manifest)

    def test_shell_env_is_complete_absolute_and_shell_safe(self) -> None:
        result = self.command("shell-env")
        self.assertEqual(result.returncode, 0, result.stderr)
        exports: dict[str, str] = {}
        for line in result.stdout.splitlines():
            words = shlex.split(line)
            self.assertEqual(words[0], "export")
            name, value = words[1].split("=", 1)
            exports[name] = value
            self.assertTrue(Path(value).is_absolute())
        self.assertEqual(set(exports), REQUIRED_EXPORTS)
        self.assertEqual(exports["QVOICE_BUILD_ROOT"], str(self.root / "build"))

    def test_status_counts_allocated_bytes_without_following_symlinks(self) -> None:
        managed = self.root / "build/cache/xcode/macos"
        managed.mkdir(parents=True)
        (managed / "last-build.json").write_text(
            json.dumps(
                {
                    "producer": "fixture",
                    "status": "passed",
                    "finishedAt": "2026-07-13T00:00:00Z",
                    "absoluteSecret": "/not/reported",
                }
            ),
            encoding="utf-8",
        )
        outside = Path(self.temporary.name) / "outside.bin"
        outside.write_bytes(b"x" * (2 * 1024 * 1024))
        (managed / "outside-link").symlink_to(outside)

        external = Path(self.temporary.name) / "external-derived-data"
        matching = external / "QwenVoice-fixture"
        other = external / "Other-fixture"
        matching.mkdir(parents=True)
        other.mkdir(parents=True)
        (matching / "info.plist").write_bytes(
            plistlib.dumps({"WorkspacePath": str(self.root / "QwenVoice.xcodeproj")})
        )
        (matching / "payload").write_bytes(b"match")
        (other / "info.plist").write_bytes(
            plistlib.dumps({"WorkspacePath": str(self.root / "Other.xcodeproj")})
        )

        result = self.command(
            "status",
            "--json",
            env={"QVOICE_EXTERNAL_XCODE_DERIVED_DATA": str(external)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads(result.stdout)
        macos = next(item for item in status["roots"] if item["id"] == "xcode-macos-derived-data")
        self.assertLess(macos["allocatedBytes"], outside.stat().st_size)
        self.assertEqual(macos["lastProducer"]["producer"], "fixture")
        self.assertNotIn("absoluteSecret", macos["lastProducer"])
        reported = status["externalXcodeDerivedData"]
        self.assertEqual(reported["policy"], "report-only")
        self.assertEqual(len(reported["matchingEntries"]), 1)
        self.assertTrue(matching.exists())
        self.assertTrue(other.exists())
        self.assertIn("filesystem", status)
        self.assertGreater(status["filesystem"]["totalBytes"], 0)

    def test_a_nested_unowned_root_is_reported(self) -> None:
        # The regression this exists for: the check used to look one level deep
        # while governed paths are two to four levels deep, so a top-level name
        # like `scratch` was allowed wholesale and anything beneath it was
        # invisible. 3.43 GB sat in build/scratch/derived-data/p7-opt for ten
        # days while status reported unowned=0 and validate passed (2026-08-02).
        nested = self.root / "build/scratch/derived-data/ad-hoc-experiment"
        nested.mkdir(parents=True)
        (nested / "payload").write_bytes(b"unowned" * 512)

        status = json.loads(self.command("status", "--json").stdout)
        self.assertIn(
            "build/scratch/derived-data/ad-hoc-experiment",
            [item["path"] for item in status["unownedRoots"]],
        )
        self.assertGreater(status["unownedAllocatedBytes"], 0)

        validate_result = self.command("validate", "--json")
        self.assertEqual(validate_result.returncode, 1)
        violations = json.loads(validate_result.stdout)["violations"]
        self.assertTrue(any("ad-hoc-experiment" in item for item in violations))

        shutil.rmtree(nested)
        self.assertEqual(self.command("validate").returncode, 0)

    def test_governed_paths_and_their_ancestors_are_not_reported(self) -> None:
        # Descending must not flag the directories that exist only to hold
        # governed children, nor anything a producer legitimately owns beneath
        # its own root -- otherwise every build would fail the gate.
        governed = self.root / "build/scratch/transient"
        governed.mkdir(parents=True, exist_ok=True)
        (governed / "producer-output").write_bytes(b"owned")
        deep = governed / "nested/deeper"
        deep.mkdir(parents=True)
        (deep / "more-output").write_bytes(b"still owned")

        status = json.loads(self.command("status", "--json").stdout)
        self.assertEqual(status["unownedRoots"], [])
        self.assertEqual(self.command("validate").returncode, 0)

    def test_one_stray_root_is_one_finding_not_a_flood(self) -> None:
        stray = self.root / "build/scratch/derived-data/stray/a/b/c"
        stray.mkdir(parents=True)
        (stray / "payload").write_bytes(b"deep")

        status = json.loads(self.command("status", "--json").stdout)
        self.assertEqual(
            [item["path"] for item in status["unownedRoots"]],
            ["build/scratch/derived-data/stray"],
        )
        shutil.rmtree(self.root / "build/scratch/derived-data/stray")

    def test_status_and_validate_expose_unowned_top_level_build_roots(self) -> None:
        unknown = self.root / "build/ad-hoc-derived-data"
        unknown.mkdir(parents=True)
        (unknown / "payload").write_bytes(b"unowned")

        status_result = self.command("status", "--json")
        self.assertEqual(status_result.returncode, 0, status_result.stderr)
        status = json.loads(status_result.stdout)
        self.assertEqual(
            [item["path"] for item in status["unownedRoots"]],
            ["build/ad-hoc-derived-data"],
        )
        self.assertGreater(status["unownedAllocatedBytes"], 0)
        self.assertEqual(
            status["allocatedBytes"],
            status["managedAllocatedBytes"] + status["unownedAllocatedBytes"],
        )

        validate_result = self.command("validate", "--json")
        self.assertEqual(validate_result.returncode, 1)
        violations = json.loads(validate_result.stdout)["violations"]
        self.assertTrue(any("unowned generated root" in item for item in violations))

        (self.root / "build/.DS_Store").write_bytes(b"finder metadata")
        (unknown / "payload").unlink()
        unknown.rmdir()
        validate_result = self.command("validate", "--json")
        self.assertEqual(validate_result.returncode, 0, validate_result.stdout)

    def test_symbol_identity_requires_matching_dsym_for_current_product(self) -> None:
        policy = POLICY.load_policy(self.root, self.manifest)
        binary = (
            self.root
            / "build/cache/xcode/ios-device/Build/Products/Release-iphoneos/"
            "Vocello.app/Vocello"
        )
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"mach-o fixture")
        dsym = self.root / "build/artifacts/symbols/ios/Vocello.app.dSYM"

        with mock.patch.object(
            POLICY,
            "_macho_uuids",
            return_value=({"AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"}, None),
        ):
            missing = POLICY._symbol_identity_violations(policy)
        self.assertTrue(any("preserved dSYM is missing" in item for item in missing))

        dsym.mkdir(parents=True)
        with mock.patch.object(
            POLICY,
            "_macho_uuids",
            side_effect=lambda path: (
                ({"BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"}, None)
                if path == dsym
                else ({"AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"}, None)
            ),
        ):
            mismatch = POLICY._symbol_identity_violations(policy)
        self.assertTrue(any("does not match" in item for item in mismatch))

        with mock.patch.object(
            POLICY,
            "_macho_uuids",
            return_value=({"AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"}, None),
        ):
            self.assertEqual(POLICY._symbol_identity_violations(policy), [])

    def test_symbol_identity_self_heals_from_the_products_dsym(self) -> None:
        policy = POLICY.load_policy(self.root, self.manifest)
        products = (
            self.root / "build/cache/xcode/ios-device/Build/Products/Release-iphoneos"
        )
        binary = products / "Vocello.app/Vocello"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"mach-o fixture")
        sibling = products / "Vocello.app.dSYM"
        (sibling / "Contents").mkdir(parents=True)
        (sibling / "Contents/marker").write_text("rebuilt", encoding="utf-8")
        preserved = self.root / "build/artifacts/symbols/ios/Vocello.app.dSYM"
        preserved.mkdir(parents=True)

        current = {"AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"}
        with mock.patch.object(
            POLICY,
            "_macho_uuids",
            side_effect=lambda path: (
                ({"BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"}, None)
                if path == preserved
                else (current, None)
            ),
        ):
            self.assertEqual(POLICY._symbol_identity_violations(policy), [])

        # The stale preserved tree was replaced by a copy of the products dSYM.
        self.assertTrue((preserved / "Contents/marker").is_file())
        self.assertFalse(
            (preserved.with_name("repair-staging-" + preserved.name)).exists()
        )

        # Without a rebuilt sibling the check stays fail-closed.
        import shutil as _shutil

        _shutil.rmtree(sibling)
        _shutil.rmtree(preserved)
        preserved.mkdir(parents=True)
        with mock.patch.object(
            POLICY,
            "_macho_uuids",
            side_effect=lambda path: (
                ({"BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"}, None)
                if path == preserved
                else (current, None)
            ),
        ):
            failures = POLICY._symbol_identity_violations(policy)
        self.assertTrue(any("no rebuilt dSYM beside the product" in item for item in failures))

    def test_status_markdown_is_deterministic_and_manifest_owned(self) -> None:
        policy = POLICY.load_policy(self.root, self.manifest)
        expected = POLICY.render_policy_markdown_table(policy) + "\n"
        first = self.command("status", "--markdown")
        second = self.command("status", "--markdown")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, expected)
        self.assertEqual(second.stdout, expected)
        self.assertIn("build/cache/xcode/macos/", first.stdout)
        self.assertIn("Persistent incremental macOS Xcode cache", first.stdout)

        changed = copy.deepcopy(self.document)
        changed["entries"][0]["owner"] = "Changed fixture owner"
        self.write_manifest(changed)
        updated = self.command("status", "--markdown")
        self.assertEqual(updated.returncode, 0, updated.stderr)
        self.assertIn("Changed fixture owner", updated.stdout)
        self.assertNotEqual(updated.stdout, first.stdout)

    def test_validate_rejects_stale_generated_documentation_table(self) -> None:
        self.initialize_git()
        documentation = self.root / POLICY.POLICY_DOCUMENTATION_RELATIVE
        documentation.parent.mkdir(parents=True)
        policy = POLICY.load_policy(self.root, self.manifest)
        documentation.write_text(
            "# Storage\n\n" + POLICY.render_policy_markdown_table(policy) + "\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "-C", str(self.root), "add", documentation.relative_to(self.root)],
            check=True,
        )
        result = self.command("validate")
        self.assertEqual(result.returncode, 0, result.stderr)

        documentation.write_text(
            documentation.read_text(encoding="utf-8").replace(
                "Persistent incremental macOS Xcode cache",
                "Manually edited retention",
                1,
            ),
            encoding="utf-8",
        )
        result = self.command("validate", "--json")
        self.assertEqual(result.returncode, 1)
        violations = json.loads(result.stdout)["violations"]
        self.assertTrue(any("table is stale" in item for item in violations))

        documentation.write_text(
            "# Storage\n\n" + POLICY.render_policy_markdown_table(policy) + "\n",
            encoding="utf-8",
        )
        changed = copy.deepcopy(self.document)
        changed["entries"][0]["retention"] = "Changed manifest retention"
        self.write_manifest(changed)
        result = self.command("validate", "--json")
        self.assertEqual(result.returncode, 1)
        violations = json.loads(result.stdout)["violations"]
        self.assertTrue(any("table is stale" in item for item in violations))

    def test_validate_rejects_retired_tracked_reference_and_absolute_build_path(self) -> None:
        self.initialize_git()
        agents = self.root / "AGENTS.md"
        agents.write_text(
            f"legacy build/DerivedData and {self.root}/build/private\n", encoding="utf-8"
        )
        subprocess.run(["git", "-C", str(self.root), "add", "AGENTS.md"], check=True)
        result = self.command("validate", "--json")
        self.assertEqual(result.returncode, 1)
        violations = json.loads(result.stdout)["violations"]
        self.assertTrue(any("retired build-output reference" in item for item in violations))
        self.assertTrue(any("not portable" in item for item in violations))

        agents.write_text("canonical build/cache/xcode/macos\n", encoding="utf-8")
        result = self.command("validate")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reference_validation_rejects_legacy_ios_and_one_off_derived_data(self) -> None:
        self.initialize_git()
        script = self.root / "scripts/example.sh"
        script.parent.mkdir(parents=True)
        script.write_text(
            "x=build/ios/Build\ny=build/ios-logs\nz=build/TelemetryAuditDerivedData\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(self.root), "add", "scripts/example.sh"], check=True)
        result = self.command("validate", "--json")
        self.assertEqual(result.returncode, 1)
        violations = "\n".join(json.loads(result.stdout)["violations"])
        self.assertIn("build/ios/", violations)
        self.assertIn("build/ios-logs", violations)
        self.assertIn("build/TelemetryAuditDerivedData", violations)

    def test_reference_validation_covers_benchmark_and_website_guidance(self) -> None:
        self.initialize_git()
        benchmark = self.root / "benchmarks/README.md"
        website = self.root / "website/AGENTS.md"
        benchmark.parent.mkdir(parents=True)
        website.parent.mkdir(parents=True)
        benchmark.write_text("legacy build/DerivedData benchmark path\n", encoding="utf-8")
        website.write_text("legacy build/ios/Build website path\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.root), "add", "benchmarks/README.md", "website/AGENTS.md"],
            check=True,
        )
        result = self.command("validate", "--json")
        self.assertEqual(result.returncode, 1)
        violations = "\n".join(json.loads(result.stdout)["violations"])
        self.assertIn("benchmarks/README.md", violations)
        self.assertIn("website/AGENTS.md", violations)

    def test_reference_validation_excludes_immutable_benchmark_records(self) -> None:
        self.initialize_git()
        record = self.root / "benchmarks/runs/instrument-profile/legacy.json"
        record.parent.mkdir(parents=True)
        record.write_text('{"artifact":"build/macos/profiles/legacy.trace"}\n', encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.root), "add", "benchmarks/runs/instrument-profile/legacy.json"],
            check=True,
        )
        result = self.command("validate", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dry_run_never_writes_and_apply_is_idempotent(self) -> None:
        source = self.root / "build/foundation"
        source.mkdir(parents=True)
        (source / "result.txt").write_text("pass", encoding="utf-8")
        destination = self.root / "build/artifacts/foundation"

        result = self.command("migrate", "--dry-run", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(source.exists())
        self.assertFalse(destination.exists())

        result = self.command("migrate", "--apply", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(source.exists())
        self.assertEqual((destination / "result.txt").read_text(), "pass")

        result = self.command("migrate", "--apply", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        operation = next(
            item
            for item in json.loads(result.stdout)["operations"]
            if item["id"] == "legacy-foundation-artifacts"
        )
        self.assertEqual(operation["action"], "already-migrated")

    def test_apply_refuses_tracked_source_and_makes_no_other_move(self) -> None:
        self.initialize_git()
        tracked = self.root / "build/ui-tests/tracked.txt"
        tracked.parent.mkdir(parents=True)
        tracked.write_text("keep", encoding="utf-8")
        movable = self.root / "build/foundation/movable.txt"
        movable.parent.mkdir(parents=True)
        movable.write_text("move", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.root), "add", "-f", "build/ui-tests/tracked.txt"],
            check=True,
        )

        result = self.command("migrate", "--apply", "--json")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(tracked.exists())
        self.assertTrue(movable.exists())
        self.assertFalse((self.root / "build/artifacts/foundation").exists())

    def test_apply_never_overwrites_nonidentical_destination(self) -> None:
        source = self.root / "build/foundation"
        destination = self.root / "build/artifacts/foundation"
        source.mkdir(parents=True)
        destination.mkdir(parents=True)
        (source / "value").write_text("old", encoding="utf-8")
        (destination / "value").write_text("new", encoding="utf-8")

        result = self.command("migrate", "--apply")
        self.assertEqual(result.returncode, 2)
        self.assertEqual((source / "value").read_text(), "old")
        self.assertEqual((destination / "value").read_text(), "new")

    def test_matching_public_copy_becomes_relative_symlink_only_after_product_move(self) -> None:
        legacy_product = self.root / "build/DerivedData/Build/Products/Release/Vocello.app"
        public_copy = self.root / "build/Vocello.app"
        legacy_product.mkdir(parents=True)
        public_copy.mkdir(parents=True)
        (legacy_product / "binary").write_text("same", encoding="utf-8")
        (public_copy / "binary").write_text("same", encoding="utf-8")

        result = self.command("migrate", "--dry-run", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(public_copy.is_symlink())

        result = self.command("migrate", "--apply", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        canonical = self.root / "build/cache/xcode/macos/Build/Products/Release/Vocello.app"
        self.assertTrue(public_copy.is_symlink())
        self.assertFalse(os.path.isabs(os.readlink(public_copy)))
        self.assertEqual(public_copy.resolve(), canonical.resolve())
        self.assertEqual((public_copy / "binary").read_text(), "same")

    def test_nonmatching_public_copy_blocks_entire_migration(self) -> None:
        legacy_product = self.root / "build/DerivedData/Build/Products/Release/Vocello.app"
        public_copy = self.root / "build/Vocello.app"
        legacy_product.mkdir(parents=True)
        public_copy.mkdir(parents=True)
        (legacy_product / "binary").write_text("canonical", encoding="utf-8")
        (public_copy / "binary").write_text("different", encoding="utf-8")

        result = self.command("migrate", "--apply")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(legacy_product.exists())
        self.assertFalse(public_copy.is_symlink())
        self.assertEqual((public_copy / "binary").read_text(), "different")

    def test_ios_cache_pieces_are_extracted_before_remaining_evidence_merge(self) -> None:
        ios = self.root / "build/ios"
        (ios / "Build").mkdir(parents=True)
        (ios / "Build/product").write_text("app", encoding="utf-8")
        (ios / "profiles/run.trace").mkdir(parents=True)
        (ios / "profiles/run.trace/data").write_text("trace", encoding="utf-8")
        (ios / "evidence.json").write_text("{}", encoding="utf-8")

        result = self.command("migrate", "--apply", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.root / "build/cache/xcode/ios-device/Build/product").read_text(),
            "app",
        )
        self.assertEqual(
            (self.root / "build/artifacts/ios/profiles/run.trace/data").read_text(),
            "trace",
        )
        self.assertEqual(
            (self.root / "build/artifacts/ios/evidence.json").read_text(), "{}"
        )
        self.assertFalse(ios.exists())

    def test_identical_package_stores_are_consolidated_without_overwrite(self) -> None:
        mac = self.root / "build/DerivedData/SourcePackages"
        ios = self.root / "build/ios/SourcePackages"
        mac.mkdir(parents=True)
        ios.mkdir(parents=True)
        (mac / "resolved").write_text("same", encoding="utf-8")
        (ios / "resolved").write_text("same", encoding="utf-8")

        result = self.command("migrate", "--apply", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        destination = self.root / "build/cache/xcode/source-packages"
        self.assertEqual((destination / "resolved").read_text(), "same")
        self.assertFalse(mac.exists())
        self.assertFalse(ios.exists())

    def test_semantically_identical_swiftpm_stores_ignore_location_specific_git_bytes(self) -> None:
        mac = self.root / "build/DerivedData/SourcePackages"
        ios = self.root / "build/ios/SourcePackages"
        mac_checkout = mac / "checkouts" / "Example"
        mac_checkout.mkdir(parents=True)
        (mac / "workspace-state.json").write_text(
            json.dumps(
                {
                    "object": {
                        "dependencies": [
                            {
                                "subpath": "Example",
                                "state": {"checkoutState": {"revision": "fixture"}},
                            }
                        ]
                    },
                    "version": 6,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q"], cwd=mac_checkout, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=mac_checkout, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=mac_checkout, check=True)
        (mac_checkout / "Package.swift").write_text("// fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "Package.swift"], cwd=mac_checkout, check=True)
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_AUTHOR_DATE": "2026-07-13T00:00:00Z",
                "GIT_COMMITTER_DATE": "2026-07-13T00:00:00Z",
            }
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "fixture"],
            cwd=mac_checkout,
            env=environment,
            check=True,
        )
        subprocess.run(
            ["git", "remote", "add", "origin", str(mac / "repositories" / "Example")],
            cwd=mac_checkout,
            check=True,
        )
        shutil.copytree(mac, ios, symlinks=True)
        ios_config = ios / "checkouts" / "Example" / ".git" / "config"
        ios_config.write_text(
            ios_config.read_text(encoding="utf-8").replace(str(mac), str(ios)),
            encoding="utf-8",
        )

        result = self.command("migrate", "--apply", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        destination = self.root / "build/cache/xcode/source-packages"
        self.assertFalse(mac.exists())
        self.assertFalse(ios.exists())
        self.assertEqual(
            subprocess.check_output(
                ["git", "-C", str(destination / "checkouts" / "Example"), "status", "--porcelain"],
                text=True,
            ),
            "",
        )
        config = (destination / "checkouts" / "Example" / ".git" / "config").read_text()
        self.assertIn(str(destination), config)
        self.assertNotIn(str(mac), config)


if __name__ == "__main__":
    unittest.main()
