"""The report-only dead-code lane, run: three compiles into one index store, then Periphery over all three.

The real scripts/dead_code_report.sh runs from a sandbox (scripts/tests/shell_stubs.py) whose
build_cache.sh records every `xcb_run` instead of compiling and whose `periphery` is a recorded
stand-in, so nothing builds or scans. The xcb_run tests source the real scripts/lib/build_cache.sh
over a recorded `xcodebuild`.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from shell_stubs import SANDBOX_BUILD_PATHS, ScriptSandbox, option, quote

ROOT = Path(__file__).resolve().parents[2]
PIN = json.loads((ROOT / "config/toolchain.json").read_text(encoding="utf-8"))["artifactPins"]["periphery"]["version"]
SCHEMES = ["QwenVoice", "VocelloCLI", "VocelloiOS"]


def lane(test: unittest.TestCase, *, version: str = PIN, failing_scheme: str = "") -> ScriptSandbox:
    """The lane over stand-ins: preflights record, `xcb_run` records and creates the index store."""
    sandbox = ScriptSandbox(test, "scripts/dead_code_report.sh", {
        "scripts/lib/shared.sh": None,
        "scripts/lib/build_paths.sh": SANDBOX_BUILD_PATHS,
        "scripts/lib/build_cache.sh": (
            "qv_stub require_build_free_space\nqv_stub require_ios_xcode_platform\n"
            "qv_stub ensure_project_regenerated\nqv_stub ensure_spm_resolved\n"
            "xcb_run() {\n"
            '  qv_record xcb_run "QVOICE_INDEX_STORE=${QVOICE_INDEX_STORE:-}" "$@"\n'
            '  local previous="" argument scheme=""\n'
            '  for argument in "$@"; do\n'
            '    [[ "$previous" != -derivedDataPath ]] || mkdir -p "$argument/Index.noindex/DataStore"\n'
            '    [[ "$previous" != -scheme ]] || scheme="$argument"\n'
            '    previous="$argument"\n'
            "  done\n"
            f'  if [[ "$scheme" == {quote(failing_scheme or "-")} ]]; then echo "error: no such module"; return 65; fi\n'
            "}\n"
        ),
    })
    sandbox.file("root/config/toolchain.json", json.dumps({"artifactPins": {"periphery": {"version": PIN}}}))
    sandbox.tool("periphery", (
        'case "$1" in\n'
        f"  version) echo {quote(version)} ;;\n"
        "  scan)\n"
        '    qv_record periphery-cwd "$PWD"\n'
        '    previous=""\n'
        '    for argument in "$@"; do\n'
        "      [[ \"$previous\" != --write-results ]] || printf '[]\\n' >\"$argument\"\n"
        '      previous="$argument"\n'
        "    done\n"
        "    echo '[]'\n"
        "    ;;\n"
        "  *) exit 64 ;;\n"
        "esac"
    ))
    return sandbox


class DeadCodeLaneTests(unittest.TestCase):
    def test_three_schemes_compile_into_one_index_that_periphery_scans(self) -> None:
        sandbox = lane(self)
        completed = sandbox.run_script()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        derived = str(sandbox.build / "qvoice_scratch_dead_code")
        artifacts = sandbox.build / "qvoice_artifacts_dead_code"

        builds = sandbox.calls_to("xcb_run")
        self.assertEqual([option(build, "-scheme") for build in builds], SCHEMES)
        self.assertEqual([option(build, "-destination") for build in builds],
                         ["platform=macOS,arch=arm64", "platform=macOS,arch=arm64", "generic/platform=iOS"])
        for build in builds:
            # The index store stays on (also on CI), every compile builds and stops, into one root.
            self.assertEqual(build[0], "QVOICE_INDEX_STORE=1")
            self.assertEqual(build[-1], "build")
            self.assertFalse({"test", "test-without-building", "build-for-testing"} & set(build), build)
            self.assertEqual(option(build, "-derivedDataPath"), derived)
            self.assertEqual(option(build, "-configuration"), "Release")
            self.assertIn("COMPILER_INDEX_STORE_ENABLE=YES", build)
            self.assertIn("SWIFT_OPTIMIZATION_LEVEL=-Onone", build)
        self.assertIn("CODE_SIGNING_ALLOWED=NO", builds[2])
        self.assertIn("CODE_SIGN_IDENTITY=-", builds[0])

        [scan] = sandbox.calls_to("periphery", "scan")
        self.assertEqual(option(scan, "--index-store-path"), f"{derived}/Index.noindex/DataStore")
        self.assertEqual([scan[index + 1] for index, word in enumerate(scan) if word == "--schemes"], SCHEMES)
        self.assertEqual([scan[index + 1] for index, word in enumerate(scan) if word == "--report-include"],
                         ["Sources/**/*.swift", "Packages/VocelloQwen3Core/**/*.swift"])
        for flag in ("--skip-build", "--exclude-tests", "--relative-results", "--retain-objc-accessible",
                     "--retain-codable-properties", "--retain-swift-ui-previews", "--disable-update-check"):
            self.assertIn(flag, scan)
        self.assertNotIn("--strict", scan)  # report-only: findings never fail the scan
        self.assertEqual(option(scan, "--project-root"), str(sandbox.root))
        self.assertEqual(option(scan, "--format"), "json")
        self.assertEqual(option(scan, "--write-results"), str(artifacts / "periphery.json"))
        self.assertEqual(sandbox.calls_to("periphery-cwd"), [[str(sandbox.root)]])

        # Preflights first, Periphery after the last compile, and the scratch root gone at exit.
        self.assertEqual(sandbox.calls_to("require_build_free_space"), [["dead-code-scan"]])
        first_build = sandbox.index("xcb_run")
        self.assertLess(sandbox.index("require_build_free_space"), first_build)
        self.assertLess(sandbox.index("ensure_spm_resolved"), first_build)
        self.assertLess(sandbox.index("xcb_run", last=True), sandbox.index("periphery", "scan"))
        self.assertFalse(Path(derived).exists())
        self.assertEqual(json.loads((artifacts / "periphery.json").read_text(encoding="utf-8")), [])
        self.assertEqual(sorted(path.name for path in artifacts.glob("*-build.log")),
                         sorted(f"{scheme}-build.log" for scheme in SCHEMES))
        self.assertFalse({"xcodebuild", "xcrun"} & set(sandbox.names()))

    def test_an_unpinned_periphery_stops_before_any_compile(self) -> None:
        sandbox = lane(self, version="0.0.1")
        completed = sandbox.run_script()
        self.assertEqual(completed.returncode, 1)
        self.assertIn(f"periphery 0.0.1 is not the pinned {PIN}", completed.stderr)
        self.assertIn("./scripts/install_pinned_tools.sh periphery", completed.stderr)
        self.assertEqual(sandbox.calls_to("xcb_run"), [])

    def test_a_failed_compile_skips_the_scan_and_still_removes_the_scratch_root(self) -> None:
        sandbox = lane(self, failing_scheme="VocelloiOS")
        completed = sandbox.run_script()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("VocelloiOS failed to compile", completed.stderr)
        self.assertIn("error: no such module", completed.stderr)  # the log's tail
        self.assertEqual(len(sandbox.calls_to("xcb_run")), 3)
        self.assertEqual(sandbox.calls_to("periphery", "scan"), [])
        self.assertFalse((sandbox.build / "qvoice_scratch_dead_code").exists())

    def test_help_prints_the_usage_and_runs_nothing(self) -> None:
        sandbox = lane(self)
        completed = sandbox.run_script("help")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("scripts/dead_code_report.sh help", completed.stderr)
        self.assertEqual(sandbox.calls(), [])
        unknown = sandbox.run_script("--strict")
        self.assertEqual(unknown.returncode, 2)
        self.assertIn("usage: ./scripts/dead_code_report.sh [help]", unknown.stderr)
        self.assertEqual(sandbox.calls(), [])


class IndexStoreOptInTests(unittest.TestCase):
    """xcb_run turns the index store off on CI unless its caller reads it (QVOICE_INDEX_STORE=1)."""

    def xcodebuild_arguments(self, **environment: str) -> list[str]:
        sandbox = ScriptSandbox(self, "scripts/dead_code_report.sh", {})
        sandbox.tool("xcodebuild", "exit 0")
        script = (
            "set -euo pipefail\n"
            f"ROOT_DIR={quote(ROOT)}\n"
            f". {quote(ROOT / 'scripts/lib/build_cache.sh')}\n"
            "xcb_run -scheme QwenVoice build\n"
        )
        completed = subprocess.run(
            ["bash", "-c", script], text=True, capture_output=True, timeout=60, check=False,
            env=sandbox.environment({
                # Pre-set build paths so sourcing build_cache.sh never loads the real policy.
                "QVOICE_BUILD_ROOT": str(sandbox.build),
                "QVOICE_XCODE_SOURCE_PACKAGES": str(sandbox.build / "source-packages"),
                "QVOICE_NATIVE_LOCK": str(sandbox.path / "native-build.lock"),
                **environment,
            }),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        [arguments] = sandbox.calls_to("xcodebuild")
        return arguments

    def test_ci_drops_the_index_store_unless_the_caller_keeps_it(self) -> None:
        self.assertIn("COMPILER_INDEX_STORE_ENABLE=NO", self.xcodebuild_arguments(CI="true"))
        self.assertNotIn("COMPILER_INDEX_STORE_ENABLE=NO",
                         self.xcodebuild_arguments(CI="true", QVOICE_INDEX_STORE="1"))
        self.assertNotIn("COMPILER_INDEX_STORE_ENABLE=NO", self.xcodebuild_arguments(CI="false"))
        self.assertIn("-skipPackagePluginValidation", self.xcodebuild_arguments(CI="true", QVOICE_INDEX_STORE="1"))


if __name__ == "__main__":
    unittest.main()
