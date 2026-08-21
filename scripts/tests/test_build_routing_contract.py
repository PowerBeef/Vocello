#!/usr/bin/env python3
"""Static regression checks for the repository build-output routing contract."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import unittest


ROOT = Path(__file__).resolve().parents[2]


class BuildRoutingContractTests(unittest.TestCase):
    def text(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def assert_tokens(self, relative: str, *tokens: str) -> None:
        text = self.text(relative)
        missing = [token for token in tokens if token not in text]
        self.assertFalse(missing, f"{relative} is missing {missing}")

    def test_local_xcode_lanes_use_policy_paths_pinned_packages_and_explicit_identity(self) -> None:
        common = (
            "-derivedDataPath",
            "-clonedSourcePackagesDirPath",
            "-disableAutomaticPackageResolution",
            "-onlyUsePackageVersionsFromResolvedFile",
        )
        for relative in (
            "scripts/build.sh",
            "scripts/build_foundation_targets.sh",
            "scripts/macos_test.sh",
            "scripts/ios_device.sh",
            "scripts/ui_test.sh",
            "scripts/release.sh",
        ):
            with self.subTest(relative=relative):
                self.assert_tokens(relative, *common)
                self.assert_tokens(relative, "configuration", "ARCHS=arm64")

    def test_cli_uses_generated_scheme_and_canonical_derived_data(self) -> None:
        build = self.text("scripts/build.sh")
        start = build.index("build_cli() {")
        end = build.index("\ncmd_cli() {", start)
        body = build[start:end]
        for token in (
            'python3 "$ROOT_DIR/scripts/generate_cli_scheme.py"',
            '-scheme "$CLI_TARGET"',
            '-derivedDataPath "$DERIVED_DATA"',
            '-clonedSourcePackagesDirPath "$SOURCE_PACKAGES_DIR"',
        ):
            source = self.text("scripts/lib/build_cache.sh") if token.startswith("python3") else body
            self.assertIn(token, source)
        self.assertNotIn('-target "$CLI_TARGET"', body)
        self.assertNotIn("SYMROOT=", body)
        self.assertNotIn("OBJROOT=", body)
        self.assertTrue(
            (ROOT / "QwenVoice.xcodeproj/xcshareddata/xcschemes/VocelloCLI.xcscheme").is_file()
        )

    def test_benchmark_cli_is_shipping_optimized_and_hash_bound(self) -> None:
        build = self.text("scripts/build.sh")
        self.assertIn("cli-optimized [args...]", build)
        self.assertIn('SWIFT_OPTIMIZATION_LEVEL="$swift_optimization"', build)
        self.assertIn('swift_optimization="-O"', build)
        self.assertIn('compilation_mode="wholemodule"', build)
        self.assertIn('write_build_provenance "$CLI_BUILT.provenance.json"', build)
        self.assertIn('"$SOURCE_PACKAGES_DIR" "$CLI_BUILT"', build)

        macos = self.text("scripts/macos_test.sh")
        self.assertNotIn('"$SCRIPT_DIR/build.sh" cli >/dev/null', macos)
        self.assertNotIn('"$ROOT_DIR/scripts/build.sh" cli >>"$log"', macos)
        self.assertGreaterEqual(macos.count('build.sh" cli-optimized'), 5)

        publisher = self.text("scripts/publish_benchmark_history.py")
        for token in (
            "validated_macos_cli_optimization",
            '"producer": "scripts/build.sh cli-optimized"',
            '"optimization": "O"',
            'provenance.get("executableSHA256") != digest_file(resolved)',
        ):
            self.assertIn(token, publisher)

    def test_macos_lanes_are_arm64_only(self) -> None:
        for relative in (
            "scripts/build.sh",
            "scripts/build_foundation_targets.sh",
            "scripts/macos_test.sh",
            "scripts/ui_test.sh",
            "scripts/release.sh",
        ):
            with self.subTest(relative=relative):
                self.assert_tokens(relative, "ONLY_ACTIVE_ARCH=YES", "ARCHS=arm64")
        self.assert_tokens(
            "scripts/lib/build_cache.sh",
            "assert_macos_bundle_arm64_only",
            "assert_macho_arm64_only",
        )

    def test_owned_swiftpm_commands_always_have_an_explicit_scratch_path(self) -> None:
        errors: list[str] = []
        for path in (ROOT / "scripts").rglob("*.sh"):
            if "tests" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"\bswift\s+(?:build|test)\b", text):
                window = text[match.start() : match.start() + 500]
                if "--scratch-path" not in window:
                    line = text.count("\n", 0, match.start()) + 1
                    errors.append(f"{path.relative_to(ROOT)}:{line}")
        self.assertFalse(errors, "SwiftPM commands lack --scratch-path: " + ", ".join(errors))
        self.assert_tokens(
            "scripts/lib/build_cache.sh",
            "ensure_swiftpm_scratch_location",
            ".qvoice-scratch-location-v1",
            "swift package --package-path",
        )
        self.assert_tokens(
            "scripts/macos_test.sh",
            'ensure_swiftpm_scratch_location "$runtime_package" "$QVOICE_SWIFTPM_RUNTIME_CACHE"',
        )

    def test_owned_runtime_uses_a_tracked_lock_in_xcode_lockstep(self) -> None:
        runtime_lock = ROOT / "Packages/VocelloQwen3Core/Package.resolved"
        xcode_lock = ROOT / "QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
        self.assertTrue(runtime_lock.is_file(), "owned runtime Package.resolved must be tracked")

        def pins(path: Path) -> dict[str, dict[str, str]]:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return {pin["identity"]: pin["state"] for pin in payload["pins"]}

        runtime_pins = pins(runtime_lock)
        xcode_pins = pins(xcode_lock)
        self.assertTrue(runtime_pins.keys() <= xcode_pins.keys())
        for identity, state in runtime_pins.items():
            with self.subTest(identity=identity):
                self.assertEqual(state, xcode_pins[identity])

        swift_nio = runtime_pins.get("swift-nio")
        self.assertIsNotNone(swift_nio, "owned runtime lock must include swift-nio")
        swift_nio_version = tuple(
            int(component) for component in swift_nio["version"].split(".")
        )
        self.assertGreaterEqual(
            swift_nio_version,
            (2, 100, 0),
            "swift-nio must retain the 2.100.0 security baseline",
        )

        macos = self.text("scripts/macos_test.sh")
        self.assertGreaterEqual(macos.count("--force-resolved-versions"), 3)

    def test_ci_build_and_archive_commands_are_explicit_and_pinned(self) -> None:
        for relative in (".github/workflows/ci.yml", ".github/workflows/release.yml"):
            text = self.text(relative)
            for match in re.finditer(r"xcodebuild\s+(?:build|archive)\b", text):
                window = text[match.start() : match.start() + 1200]
                for token in (
                    "-derivedDataPath",
                    "-clonedSourcePackagesDirPath",
                    "-disableAutomaticPackageResolution",
                    "-onlyUsePackageVersionsFromResolvedFile",
                    "ARCHS=arm64",
                    "ONLY_ACTIVE_ARCH=YES",
                ):
                    self.assertIn(token, window, f"{relative} command lacks {token}")

    def test_local_package_resolution_is_platform_aware_and_pinned(self) -> None:
        resolver = self.text("scripts/lib/build_cache.sh")
        for token in (
            'local scheme="${4:-}"',
            'local configuration="${5:-}"',
            'local destination="${6:-}"',
            '-scheme "$scheme"',
            '-configuration "$configuration"',
            '-destination "$destination"',
            '-derivedDataPath "$derived_data"',
            '-clonedSourcePackagesDirPath "$source_packages"',
            "-disableAutomaticPackageResolution",
            "-onlyUsePackageVersionsFromResolvedFile",
            "swiftpm-resolution-$resolution_key.json",
            'rm -f "$BUILD_CACHE_DIR/swiftpm-resolution.json"',
            '"scheme": sys.argv[7]',
            '"configuration": sys.argv[8]',
            '"destination": sys.argv[9]',
        ):
            self.assertIn(token, resolver)

        calls: dict[str, list[tuple[str, str, str]]] = {}
        for path in (ROOT / "scripts").rglob("*.sh"):
            if "tests" in path.parts or path.name == "build_cache.sh":
                continue
            text = re.sub(r"\\\n\s*", " ", path.read_text(encoding="utf-8"))
            for line in text.splitlines():
                command = line.strip()
                if not command.startswith("ensure_spm_resolved "):
                    continue
                command = command.split("||", 1)[0].strip()
                tokens = shlex.split(command)
                self.assertEqual(
                    len(tokens), 7,
                    f"{path.relative_to(ROOT)} must pass context, scheme, configuration, and destination",
                )
                calls.setdefault(tokens[3], []).append(tuple(tokens[4:7]))

        expected = {
            "dev": [("QwenVoice", "Release", "$DESTINATION")] * 2,
            "foundation-macos": [("QwenVoice", "Release", "platform=macOS,arch=arm64")],
            "foundation-ios": [("VocelloiOS", "Release", "generic/platform=iOS")],
            "release": [("$SCHEME", "$CONFIGURATION", "platform=macOS,arch=arm64")],
            "macos-test": [("QwenVoice", "Release", "platform=macOS,arch=arm64")],
            "ios-device": [("VocelloiOS", "Release", "generic/platform=iOS")],
            "ui-macos": [("VocelloMacUI", "Release", "platform=macOS,arch=arm64")],
            "ui-ios": [("VocelloiOSUI", "Release", "generic/platform=iOS")],
        }
        self.assertEqual(calls, expected)

    def test_ios_platform_preflight_precedes_every_local_build_side_effect(self) -> None:
        cache = self.text("scripts/lib/build_cache.sh")
        resolver_start = cache.index("ensure_spm_resolved() {")
        resolver_end = cache.index("\n    acquire_package_store_lock", resolver_start)
        resolver = cache[resolver_start:resolver_end]
        self.assertLess(
            resolver.index("require_ios_xcode_platform"),
            resolver.index('mkdir -p "$BUILD_CACHE_DIR"'),
        )

        foundation = self.text("scripts/build_foundation_targets.sh")
        main = foundation[foundation.index('case "$MODE" in', foundation.index("build_ios()")) :]
        self.assertLess(main.index("require_ios_xcode_platform"), main.index("prepare_paths"))
        self.assertLess(main.index("require_ios_xcode_platform"), main.index("build_macos"))

        ui = self.text("scripts/ui_test.sh")
        self.assertLess(ui.index("require_ios_xcode_platform"), ui.index('require_build_free_space "ui-$lane"'))
        self.assertLess(ui.index("require_ios_xcode_platform"), ui.index("ensure_spm_resolved"))

        device = self.text("scripts/ios_device.sh")
        build_start = device.index("cmd_build() {")
        build_end = device.index("\ncmd_install() {", build_start)
        build = device[build_start:build_end]
        self.assertLess(build.index("require_ios_xcode_platform"), build.index("require_build_free_space"))
        self.assertLess(build.index("require_ios_xcode_platform"), build.index("ensure_project_regenerated"))
        self.assertLess(build.index("require_ios_xcode_platform"), build.index("ensure_spm_resolved"))
        doctor = device[device.index("cmd_doctor() {") : build_start]
        self.assertIn("require_ios_xcode_platform", doctor)

    def test_ci_ios_resolution_checks_platform_before_creating_caches(self) -> None:
        for relative in (".github/workflows/ci.yml", ".github/workflows/release.yml"):
            text = self.text(relative)
            for match in re.finditer(r"xcodebuild\s+-resolvePackageDependencies\b", text):
                start = text.rfind("run: |", 0, match.start())
                window = text[start : match.start()]
                self.assertIn("python3 scripts/lib/ios_platform_preflight.py check", window)
                self.assertLess(
                    window.index("ios_platform_preflight.py check"),
                    window.index("mkdir -p"),
                )

    def test_ios_platform_preflight_has_no_mutating_toolchain_command(self) -> None:
        helper = self.text("scripts/lib/ios_platform_preflight.py")
        self.assertIn('SDK_COMMAND = ("xcodebuild", "-showsdks", "-json")', helper)
        self.assertIn('RUNTIME_COMMAND = ("xcrun", "simctl", "list", "runtimes", "-j")', helper)
        inspected_commands = helper[helper.index("SDK_COMMAND") : helper.index("REPAIR_COMMAND")]
        for forbidden in ("downloadPlatform", "importPlatform", "runFirstLaunch", '"boot"', '"create"'):
            self.assertNotIn(forbidden, inspected_commands)

    def test_ci_package_resolvers_are_destination_explicit_and_pinned(self) -> None:
        required = (
            "-project QwenVoice.xcodeproj",
            "-scheme VocelloiOS",
            "-configuration Release",
            "-destination 'generic/platform=iOS'",
            "-derivedDataPath build/scratch/derived-data/ci/",
            "-clonedSourcePackagesDirPath build/cache/xcode/source-packages",
            "-disableAutomaticPackageResolution",
            "-onlyUsePackageVersionsFromResolvedFile",
        )
        for relative in (".github/workflows/ci.yml", ".github/workflows/release.yml"):
            text = self.text(relative)
            matches = list(re.finditer(r"xcodebuild\s+-resolvePackageDependencies\b", text))
            self.assertEqual(len(matches), 1, f"{relative} must own one explicit package resolve")
            start = matches[0].start()
            end = text.find("\n\n", start)
            window = text[start : len(text) if end == -1 else end]
            for token in required:
                self.assertIn(token, window, f"{relative} resolver lacks {token}")

    def test_mcp_profiles_have_managed_scratch_derived_data(self) -> None:
        text = self.text(".xcodebuildmcp/config.yaml")
        self.assertEqual(text.count("derivedDataPath:"), 2)
        self.assertIn("build/scratch/derived-data/xcodebuildmcp/macos", text)
        self.assertIn("build/scratch/derived-data/xcodebuildmcp/ios-device", text)

    def test_symbol_retention_is_current_product_only_and_uuid_validated(self) -> None:
        cache = self.text("scripts/lib/build_cache.sh")
        self.assertIn("validate_dsym_uuid", cache)
        self.assertIn("preserve_ios_dsym", cache)
        self.assertIn("Vocello.app.dSYM", cache)
        self.assertIn("QwenVoiceEngineService.xpc.dSYM", cache)
        ios = self.text("scripts/ios_device.sh")
        self.assertIn("validate_dsym_identity", ios)
        self.assertIn("QVOICE_SYMBOLS_IOS", ios)
        self.assertIn(
            'local binary="$1" dsym="$2"\n  local dwarf="$dsym/Contents/Resources/DWARF/Vocello"',
            ios,
        )
        policy = self.text("scripts/build_output_policy.py")
        self.assertIn("_symbol_identity_violations", policy)

    def test_benchmark_take_identity_uses_platform_appropriate_temporary_storage(self) -> None:
        context = self.text("Sources/QwenVoiceCore/BenchRunContext.swift")
        self.assertIn("#if os(iOS)", context)
        self.assertIn("FileManager.default.temporaryDirectory", context)
        self.assertIn(
            'URL(fileURLWithPath: "/tmp/vocello-bench-current-take.json"',
            context,
        )
        self.assertIn("try data.write(to: currentTakeFileURL, options: .atomic)", context)
        self.assertIn("currentTakeFileNotes() == payload", context)

        runner = self.text("Sources/iOS/IOSDeviceDiagnosticsRunner.swift")
        self.assertIn("try BenchRunContext.writeCurrentTakeFile", runner)
        self.assertIn("defer { BenchRunContext.clearCurrentTakeFile() }", runner)
        self.assertNotIn(
            'URL(fileURLWithPath: "/tmp/vocello-bench-current-take.json")',
            runner,
        )

    def test_ios_profile_rebuilds_before_install_and_source_snapshot(self) -> None:
        ios = self.text("scripts/ios_device.sh")
        start = ios.index("cmd_profile() {")
        end = ios.index("\n# memory", start)
        profile = ios[start:end]
        build_index = profile.index("\n  cmd_build\n")
        install_index = profile.index("\n  cmd_install >/dev/null\n")
        snapshot_index = profile.index("\n  capture_benchmark_source \"$artifacts\"\n")
        late_xctrace_index = profile.rindex('xctrace_dev="$(resolve_xctrace_device "$dev")"')
        launch_index = profile.index("xcrun devicectl device process launch")
        self.assertLess(build_index, install_index)
        self.assertLess(install_index, snapshot_index)
        self.assertLess(snapshot_index, late_xctrace_index)
        self.assertLess(late_xctrace_index, launch_index)
        self.assertEqual(profile.count('xctrace_dev="$(resolve_xctrace_device "$dev")"'), 2)

    def test_ui_lifecycle_metadata_is_atomic_and_failure_aware(self) -> None:
        text = self.text("scripts/ui_test.sh")
        for token in (
            "write_run_metadata running",
            "write_run_metadata failed",
            "write_run_metadata passed",
            "os.replace(temporary, path)",
        ):
            self.assertIn(token, text)

    def test_heavy_lanes_fail_fast_through_the_storage_contract(self) -> None:
        cache = self.text("scripts/lib/build_cache.sh")
        self.assertIn("require_build_free_space()", cache)
        self.assertIn("scripts/lib/storage_preflight.py", cache)
        required_routes = {
            "scripts/build.sh": ("require_build_free_space development-build",),
            "scripts/build_foundation_targets.sh": (
                "require_build_free_space foundation-compile",
            ),
            "scripts/ui_test.sh": ('require_build_free_space "ui-$lane"',),
            "scripts/macos_test.sh": (
                "require_build_free_space language-benchmark",
                "require_build_free_space memory-qualification",
                "require_build_free_space telemetry-overhead",
            ),
            "scripts/ios_device.sh": (
                "require_build_free_space device-build",
                "require_build_free_space language-benchmark",
                "require_build_free_space memory-qualification",
            ),
            "scripts/release.sh": ("require_build_free_space release",),
        }
        for relative, tokens in required_routes.items():
            with self.subTest(relative=relative):
                self.assert_tokens(relative, *tokens)

        ios = self.text("scripts/ios_device.sh")
        build_start = ios.index("cmd_build() {")
        build_end = ios.index("\ncmd_install() {", build_start)
        self.assertIn("require_build_free_space device-build", ios[build_start:build_end])
        main = ios[ios.index("main() {") :]
        for command in ("install", "launch"):
            branch = main[main.index(f"    {command})") :]
            branch = branch[: branch.index(";;")]
            self.assertNotIn("require_build_free_space", branch)

    def test_owned_runtime_never_owns_a_generated_dot_build(self) -> None:
        self.assertFalse(
            (ROOT / "Packages" / "VocelloQwen3Core" / ".build").exists(),
            "migrate the owned runtime SwiftPM cache to build/cache/swiftpm/mlx-audio-runtime",
        )

    def test_only_classified_top_level_build_roots_remain(self) -> None:
        build = ROOT / "build"
        if not build.exists():
            return
        allowed = {
            ".DS_Store",  # Finder metadata, not a build-output root.
            "cache",
            "scratch",
            "artifacts",
            "dist",
            "Vocello.app",
            "vocello",
        }
        unknown = sorted(path.name for path in build.iterdir() if path.name not in allowed)
        self.assertEqual(unknown, [], f"unclassified build roots remain: {unknown}")


if __name__ == "__main__":
    unittest.main()
