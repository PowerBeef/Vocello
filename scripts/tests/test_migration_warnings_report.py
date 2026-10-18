"""The nightly migrate-mode report: which settings a given Xcode takes, and what a build log flags."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("migration_warnings_report",
                                              ROOT / "scripts/ci/migration_warnings_report.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE  # dataclasses resolve string annotations through sys.modules
SPEC.loader.exec_module(MODULE)

SMS = "SWIFT_STRICT_MEMORY_SAFETY"
NNBD = "SWIFT_UPCOMING_FEATURE_NONISOLATED_NONSENDING_BY_DEFAULT"
IIC = "SWIFT_UPCOMING_FEATURE_INFER_ISOLATED_CONFORMANCES"


def enumeration(name: str, *values: str) -> str:
    """One setting as Xcode 27.1's Swift.xcspec writes it, a nested CommandLineArgs included."""
    listed = "".join(f"\n                    {value}," for value in values)
    arguments = "".join(f'\n                    {value} = ( "-flag-{value.lower()}" );' for value in values)
    return f"""            {{
                Name = "{name}";
                Type = Enumeration;
                Values = ({listed}
                );
                DefaultValue = "NO";
                CommandLineArgs = {{{arguments}
                }};
                DisplayName = "{name.title()}";
            }},
"""


def boolean(name: str) -> str:
    return f"""            {{
                Name = {name};
                Type = Boolean;
                DefaultValue = NO;
                CommandLineArgs = {{
                    YES = ( "-flag" );
                    NO = ();
                }};
            }},
"""


def spec(*settings: str) -> str:
    return "(\n    {\n        Identifier = com.apple.xcode.tools.swift.compiler;\n        Options = (\n" \
        + "".join(settings) + "        );\n    }\n)\n"


ALL_MIGRATE = spec(enumeration(SMS, "YES", "MIGRATE", "NO"), enumeration(NNBD, "YES", "MIGRATE", "NO"),
                   enumeration(IIC, "YES", "MIGRATE", "NO"))

REPO = "/Users/example/work/Vocello Repo/Vocello"


def log(*lines: str) -> str:
    return "\n".join(lines) + "\n"


SWIFT_FILE = f"{REPO}/Sources/QwenVoiceCore/MLXTTSEngine.swift"
TEST_FILE = f"{REPO}/Tests/VocelloCoreTests/StoreTests.swift"
PACKAGE_FILE = f"{REPO}/Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Generation.swift"
CHECKOUT = f"{REPO}/build/cache/xcode/source-packages/checkouts/mlx-swift/Source/Cmlx/complex.h"
UNSAFE = "expression uses unsafe constructs but is not marked with 'unsafe' [#StrictMemorySafety]"
NONSENDING = ("feature 'NonisolatedNonsendingByDefault' will cause nonisolated async instance method 'load()' "
              "to run on the caller's actor; use @concurrent to preserve behavior [#NonisolatedNonsendingByDefault]")
BUILD_LOG = log(
    "SwiftCompile normal arm64 Compiling\\ MLXTTSEngine.swift",
    f"{SWIFT_FILE}:12:9: warning: {UNSAFE}",
    f"{SWIFT_FILE}:12:9: note: reference to unsafe global function 'memcpy'",
    f"{SWIFT_FILE}:12:9: warning: {UNSAFE}",  # the emit-module job repeats it
    f"{SWIFT_FILE}:40:5: warning: {NONSENDING}",
    f"\x1b[1m{TEST_FILE}:7:3: warning: {UNSAFE}\x1b[0m",
    f"{TEST_FILE}:7:3: warning: {UNSAFE}",  # VocelloCoreTests compiles the file again
    f"{PACKAGE_FILE}:299:15: warning: 'Sendable'-conforming struct 'AudioGenerationCompletion' has "
    "non-Sendable type 'MLXArray'",
    f"{PACKAGE_FILE}:300:1: warning: capture of 'refAudio' with non-Sendable type 'MLXArray?' in a "
    "'@Sendable' closure [#SendableClosureCaptures]",
    f"{CHECKOUT}:157:3: warning: 'static_assert' with no message is a C++17 extension [-Wc++17-extensions]",
    f"{CHECKOUT}:157:3: warning: 'static_assert' with no message is a C++17 extension [-Wc++17-extensions]",
    "libtool: warning: 'Numerics.o' has no symbols",
    "warning: Run script build phase 'Lint' will be run during every build",
    "** TEST BUILD SUCCEEDED **",
)


class PlanTests(unittest.TestCase):
    def test_values_come_from_each_settings_own_definition(self) -> None:
        text = spec(enumeration(SMS, "YES", "MIGRATE", "NO"), boolean(NNBD), enumeration(f"{IIC}_EXTRA", "YES"))
        self.assertEqual(MODULE.setting_values(text, SMS), ("YES", "MIGRATE", "NO"))
        self.assertEqual(MODULE.setting_values(text, NNBD), ("YES", "NO"))
        # A longer name, or a mention outside a `Name =` definition, is not a definition.
        self.assertIsNone(MODULE.setting_values(text + f"DefaultValue = \"$({IIC})\";", IIC))

    def test_a_nested_dictionary_does_not_end_the_definition(self) -> None:
        # The Boolean's CommandLineArgs closes with `};` before the next setting's Values; the
        # Boolean must not borrow them.
        text = spec(boolean(SMS), enumeration(NNBD, "YES", "MIGRATE", "NO"))
        self.assertEqual(MODULE.setting_values(text, SMS), ("YES", "NO"))

    def test_xcode_27_takes_every_setting_in_migrate_mode(self) -> None:
        choices = MODULE.plan(ALL_MIGRATE, {SMS: True, NNBD: True, IIC: True})
        self.assertEqual([(choice.setting, choice.value) for choice in choices],
                         [(SMS, "MIGRATE"), (NNBD, "MIGRATE"), (IIC, "MIGRATE")])
        self.assertEqual(MODULE.settings_argument(choices),
                         f"{SMS}=MIGRATE {NNBD}=MIGRATE {IIC}=MIGRATE")

    def test_an_older_xcode_skips_what_it_lacks_and_says_why(self) -> None:
        text = spec(boolean(SMS), boolean(NNBD))
        choices = {choice.setting: choice for choice in MODULE.plan(text, {SMS: True, NNBD: True, IIC: False})}
        self.assertEqual(choices[SMS].value, "YES")  # strict memory safety only warns either way
        self.assertIsNone(choices[NNBD].value)  # YES would change the language rules
        self.assertIn("no migrate mode", choices[NNBD].reason)
        self.assertIsNone(choices[IIC].value)
        self.assertIn("probe reports it absent", choices[IIC].reason)
        self.assertEqual(MODULE.settings_argument(list(choices.values())), f"{SMS}=YES")
        # The probe's verdict wins even where a definition could be parsed.
        self.assertIsNone(MODULE.plan(ALL_MIGRATE, {SMS: False, NNBD: True, IIC: True})[0].value)

    def test_plan_reads_the_owning_xcode_and_writes_the_step_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vocello migration ") as tmp:
            app = Path(tmp) / "Xcode.app"
            xcspec = app / "Contents/SharedFrameworks/SwiftBuild.framework/Resources/Swift.xcspec"
            xcspec.parent.mkdir(parents=True)
            xcspec.write_text(spec(enumeration(SMS, "YES", "MIGRATE", "NO"), boolean(NNBD)), encoding="utf-8")
            developer = app / "Contents/Developer"
            developer.mkdir(parents=True)
            github_output = Path(tmp) / "github-output"
            plan_path = Path(tmp) / "out/plan.json"
            stdout = io.StringIO()
            with mock.patch.object(MODULE, "_xcode_version", return_value="Xcode 26.6"), \
                    mock.patch.dict("os.environ", {"GITHUB_OUTPUT": str(github_output)}), redirect_stdout(stdout):
                code = MODULE.main(["plan", "--developer-dir", str(developer), "--output", str(plan_path),
                                    "--github-output"])
            self.assertEqual(code, 0)
            self.assertEqual(github_output.read_text(encoding="utf-8"), f"settings={SMS}=MIGRATE\n")
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["xcode"], "Xcode 26.6")
            self.assertEqual([entry["value"] for entry in payload["settings"]], ["MIGRATE", None, None])


class ReportTests(unittest.TestCase):
    def plan_payload(self, **values: str | None) -> dict:
        choices = MODULE.plan(ALL_MIGRATE, {SMS: True, NNBD: True, IIC: True})
        settings = []
        for choice in choices:
            value = values.get(choice.group, choice.value)
            reason = choice.reason if value else "skipped: the build-setting probe reports it absent from this Xcode"
            settings.append({**MODULE.asdict(choice), "value": value, "reason": reason})
        return {"schemaVersion": 1, "xcode": "Xcode 26.6", "settings": settings}

    def test_each_site_counts_once_with_a_repository_relative_file(self) -> None:
        sites, lines = MODULE.parse_log(BUILD_LOG, REPO)
        self.assertEqual(lines, 9)  # located warnings only: no notes, libtool or unlocated lines
        self.assertEqual([(site.file, site.line, site.group) for site in sites], [
            ("Sources/QwenVoiceCore/MLXTTSEngine.swift", 12, "StrictMemorySafety"),
            ("Sources/QwenVoiceCore/MLXTTSEngine.swift", 40, "NonisolatedNonsendingByDefault"),
            ("Tests/VocelloCoreTests/StoreTests.swift", 7, "StrictMemorySafety"),
            ("Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Generation.swift", 299, MODULE.NO_GROUP),
            ("Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Generation.swift", 300, "SendableClosureCaptures"),
            ("checkouts/mlx-swift/Source/Cmlx/complex.h", 157, "-Wc++17-extensions"),
        ])
        self.assertEqual(sites[0].message, "expression uses unsafe constructs but is not marked with 'unsafe'")
        self.assertEqual(MODULE.display_path("/Applications/Xcode.app/SDKs/usr/include/x.h", REPO),
                         "(outside the repository)/include/x.h")

    def test_areas_name_the_source_tree_they_belong_to(self) -> None:
        self.assertEqual(MODULE.area("Sources/QwenVoiceCore/MLXTTSEngine.swift"), "Sources/QwenVoiceCore")
        self.assertEqual(MODULE.area("Sources/ContentView.swift"), "Sources")
        self.assertEqual(MODULE.area("Packages/VocelloQwen3Core/Sources/A.swift"), "Packages/VocelloQwen3Core")
        self.assertEqual(MODULE.area("checkouts/mlx-swift/x.h"), "third-party packages")

    def test_the_report_tables_count_sites_per_setting_area_and_file(self) -> None:
        text = MODULE.render(BUILD_LOG, "qwenvoice-macos-migration.log", self.plan_payload(), REPO)
        self.assertIn("Xcode 26.6 compiled the macOS app and VocelloCoreTests", text)
        self.assertIn("the build succeeded. 6 distinct diagnostic site(s) from 9 log line(s).", text)
        self.assertIn(f"| `{SMS}` | `MIGRATE` | `#StrictMemorySafety` | 2 | 2 |", text)
        self.assertIn(f"| `{NNBD}` | `MIGRATE` | `#NonisolatedNonsendingByDefault` | 1 | 1 |", text)
        self.assertIn(f"| `{IIC}` | `MIGRATE` | `#InferIsolatedConformances` | 0 | 0 |", text)
        self.assertIn("| Sources/QwenVoiceCore | 1 | 1 | 0 |", text)
        self.assertIn("| Tests/VocelloCoreTests | 1 | 0 | 0 |", text)
        self.assertIn("| `Sources/QwenVoiceCore/MLXTTSEngine.swift` | 2 | 1 | 1 | 0 |", text)
        self.assertIn("| `-Wc++17-extensions` | 1 | 1 |", text)
        self.assertIn("| `#SendableClosureCaptures` | 1 | 1 |", text)
        self.assertIn("| `(no group)` | 1 | 1 |", text)
        self.assertNotIn(REPO, text)
        self.assertNotIn("Errors", text)

    def test_skipped_settings_are_named_with_their_reason(self) -> None:
        text = MODULE.render(BUILD_LOG, "x.log", self.plan_payload(InferIsolatedConformances=None), REPO)
        self.assertIn(f"| `{IIC}` | skipped | `#InferIsolatedConformances` | – | – |", text)
        self.assertIn(f"- `{IIC}`: skipped: the build-setting probe reports it absent from this Xcode.", text)
        self.assertIn("| Area | StrictMemorySafety | NonisolatedNonsendingByDefault |", text)

    def test_the_file_list_is_capped(self) -> None:
        lines = [f"{REPO}/Sources/F{index}.swift:1:1: warning: {UNSAFE}" for index in range(5)]
        text = MODULE.render(log(*lines), "x.log", self.plan_payload(), REPO, top=3)
        self.assertIn("#### Files with the most migration sites (3 of 5)", text)
        self.assertNotIn("Sources/F4.swift", text)

    def test_a_failed_build_reports_partial_counts_and_its_errors(self) -> None:
        failed = log(f"{SWIFT_FILE}:12:9: warning: {UNSAFE}",
                     f"{SWIFT_FILE}:90:1: error: sending 'value' risks causing data races [#SendingRisksDataRace]",
                     "** TEST BUILD FAILED **")
        text = MODULE.render(failed, "x.log", self.plan_payload(), REPO)
        self.assertIn("**the build failed**", text)
        self.assertIn("#### Errors (1)", text)
        self.assertIn("- `Sources/QwenVoiceCore/MLXTTSEngine.swift:90` sending 'value' risks causing data races",
                      text)

    def test_a_missing_log_is_reported_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vocello migration ") as tmp:
            summary = Path(tmp) / "summary.md"
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(self.plan_payload(StrictMemorySafety=None,
                                                              NonisolatedNonsendingByDefault=None,
                                                              InferIsolatedConformances=None)),
                                 encoding="utf-8")
            stdout = io.StringIO()
            with mock.patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(summary)}), redirect_stdout(stdout):
                code = MODULE.main(["report", str(Path(tmp) / "missing.log"), "--plan", str(plan_path),
                                    "--root", REPO])
            self.assertEqual(code, 0)
            written = summary.read_text(encoding="utf-8")
            self.assertIn("No build log at `missing.log`: every setting was skipped", written)
            self.assertEqual(written, stdout.getvalue())

    def test_the_report_writes_the_summary_and_its_output_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vocello migration ") as tmp:
            build_log = Path(tmp) / "qwenvoice-macos-migration.log"
            build_log.write_text(BUILD_LOG, encoding="utf-8")
            output = Path(tmp) / "report/migration-report.md"
            summary = Path(tmp) / "summary.md"
            with mock.patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(summary)}), redirect_stdout(io.StringIO()):
                code = MODULE.main(["report", str(build_log), "--root", REPO, "--output", str(output)])
            self.assertEqual(code, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), summary.read_text(encoding="utf-8"))
            # Without a plan every setting is listed as unrecorded and nothing is counted against it.
            self.assertIn(f"| `{SMS}` | skipped | `#StrictMemorySafety` | – | – |", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
