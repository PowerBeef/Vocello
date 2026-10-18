"""Run the real lane scripts' shell code against recorded stand-ins.

Tests that use this assert what a lane script does, never what its source says
(docs/reference/tooling-and-evidence.md, "Common mistakes"). There are two ways in:

* `LaneShell` sources scripts/macos_test.sh or scripts/ios_device.sh through the
  harmless `help` dispatch of their `main`: with `$0` set to /dev/null it prints
  nothing, so every shipped function is defined exactly as it ships and the real
  `main` stays callable. Every variable that names a path under the real build
  tree is then moved into the sandbox, and the test body replaces what must not
  run and calls the function under test.
* `ScriptSandbox` runs a whole script that has no `main` (scripts/ui_test.sh,
  scripts/build_ui_test_bundles.sh) from a temporary root that holds a symlink to
  the real script beside stand-in libraries and helpers, so its `ROOT_DIR` is the
  sandbox and nothing it reaches is real.

Native tools (xcodebuild, xcrun, xctrace, devicectl, ...) are PATH shims that
record their arguments and refuse unless a test gives them a behaviour. Repository
Python helpers that publish, prune or write outside a run directory refuse the
same way until a test stands one in with `helper()`. So nothing builds, installs,
records a trace, publishes history or touches a phone. Every call (a shim, a
helper stand-in, or a function a test body stubs with `qv_stub`) lands in one
ordered log, read back with `calls()`.

`ui_function()` is the one remaining reader of script text: scripts/ui_test.sh
runs its lane at top level and defines its functions between the steps, so it
cannot be sourced without running a lane. The tests that use it execute the
function they load and assert on its effects.
"""
from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SEPARATOR = "\x1f"

# Every tool a lane script could reach that builds, signs, profiles, installs, talks to a
# phone, keeps the host awake, samples a process or changes a global setting.
NATIVE_TOOLS = (
    "xcodebuild", "xcrun", "xctrace", "devicectl", "xcodegen", "swift", "swiftc", "clang",
    "codesign", "security", "caffeinate", "lldb", "osascript", "open", "defaults", "tccutil",
    "launchctl", "pkill", "killall", "sudo", "sample",
)

# Repository helpers that publish records, prune results or write a ledger outside the
# run directory. They refuse until a test gives them a behaviour.
GUARDED_HELPERS = (
    "scripts/benchmark_history.py",
    "scripts/publish_benchmark_history.py",
    "scripts/summarize_generation_telemetry.py",
    "scripts/lib/profile_trace_retention.py",
    "scripts/lane_ledger.py",
)

# The build-output paths scripts/lib/build_paths.sh exports, for a stand-in of that library.
BUILD_PATHS = (
    "QVOICE_XCODE_MACOS_DERIVED", "QVOICE_XCODE_MACOS_OPTIMIZED_DERIVED", "QVOICE_XCODE_MACOS_TSAN_DERIVED",
    "QVOICE_XCODE_IOS_DERIVED", "QVOICE_XCODE_SOURCE_PACKAGES", "QVOICE_SWIFTPM_RUNTIME_CACHE",
    "QVOICE_DELIVERY_ANALYSIS_CACHE", "QVOICE_SCRATCH_FOUNDATION", "QVOICE_SCRATCH_PACKAGE_RESOLUTION",
    "QVOICE_SCRATCH_TRANSIENT", "QVOICE_SCRATCH_RELEASE_MACOS", "QVOICE_SCRATCH_RELEASE_IOS",
    "QVOICE_SCRATCH_XCODEBUILDMCP_MACOS", "QVOICE_SCRATCH_XCODEBUILDMCP_IOS", "QVOICE_SCRATCH_CI",
    "QVOICE_ARTIFACTS_MACOS", "QVOICE_ARTIFACTS_IOS", "QVOICE_ARTIFACTS_UI_TESTS",
    "QVOICE_ARTIFACTS_DIAGNOSTICS", "QVOICE_SYMBOLS_MACOS", "QVOICE_SYMBOLS_IOS",
    "QVOICE_ARTIFACTS_FOUNDATION", "QVOICE_DIST_MACOS", "QVOICE_DIST_IOS", "QVOICE_ARTIFACTS_UI_BUNDLES",
    "QVOICE_SCRATCH_DEAD_CODE", "QVOICE_ARTIFACTS_DEAD_CODE",
)


def quote(value: str | Path) -> str:
    return shlex.quote(str(value))


class _Sandbox:
    """A temporary directory with the call log, the PATH shims and the helper stand-ins."""

    def __init__(self, test: unittest.TestCase) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="vocello shell sandbox ")
        test.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name).resolve()
        self.root = self.path
        self.bin = self.path / "bin"
        self.helpers = self.path / "helpers"
        self.home = self.path / "home"
        self.build = self.path / "build"
        self.log = self.path / "calls.log"
        for directory in (self.bin, self.helpers, self.home, self.build):
            directory.mkdir()
        self.log.touch()
        self.record = self.path / "record.sh"
        self.record.write_text(
            f": \"${{QV_CALLS:={self.log}}}\"\n"
            "# qv_record NAME ARGS...: append one call to the ordered log.\n"
            "qv_record() {\n"
            "  local IFS=$'\\x1f' line\n"
            '  line="$*"\n'
            "  printf '%s\\n' \"${line//$'\\n'/\\\\n}\" >>\"$QV_CALLS\"\n"
            "}\n"
            "# qv_stub NAME [STATUS]: replace a shell function with one that records its call.\n"
            "qv_stub() {\n"
            '  local name="$1" status="${2:-0}"\n'
            '  eval "$name() { qv_record $name \\"\\$@\\"; return $status; }"\n'
            "}\n",
            encoding="utf-8",
        )
        for tool in NATIVE_TOOLS:
            self.tool(tool)
        for helper in GUARDED_HELPERS:
            self.helper(helper)
        self._python_shim()

    @staticmethod
    def _refusal(name: str) -> str:
        return f"printf 'shell_stubs: %s refused (the test gave it no behaviour)\\n' {quote(name)} >&2\nexit 97"

    # ── stand-ins ────────────────────────────────────────────────────────────
    def tool(self, name: str, behaviour: str | None = None) -> None:
        """A PATH shim: records `name` and its arguments, then runs `behaviour` (bash, with "$@")."""
        self._recorded_script(self.bin / name, name, behaviour if behaviour is not None else self._refusal(name))

    def helper(self, relative: str, behaviour: str | None = None) -> None:
        """Stand in for a repository Python helper (`python3 .../scripts/x.py ARGS`).

        The call is recorded as `scripts/x.py ARGS`; `behaviour` then runs in bash with
        the arguments as "$@" and `qv_record` available. Without one, the helper refuses."""
        body = behaviour if behaviour is not None else self._refusal(relative)
        (self.helpers / relative.replace("/", "__")).write_text(
            f". {quote(self.record)}\n{body}\n", encoding="utf-8",
        )

    def executable(self, relative: str, behaviour: str = "exit 0") -> Path:
        """A recorded stand-in at a path the script runs directly, below the sandbox root."""
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        self._recorded_script(target, relative, behaviour)
        return target

    def file(self, relative: str, text: str = "") -> Path:
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def _recorded_script(self, target: Path, name: str, behaviour: str) -> None:
        target.write_text(
            f"#!/usr/bin/env bash\n. {quote(self.record)}\nqv_record {quote(name)} \"$@\"\n{behaviour}\n",
            encoding="utf-8",
        )
        target.chmod(0o755)

    def _python_shim(self) -> None:
        shim = self.bin / "python3"
        shim.write_text(
            "#!/usr/bin/env bash\n"
            'case "${1:-}" in\n'
            '  scripts/*.py) relative="$1" ;;\n'
            '  */scripts/*.py) relative="scripts/${1##*/scripts/}" ;;\n'
            '  *) relative="" ;;\n'
            "esac\n"
            'if [[ -n "$relative" ]]; then\n'
            f'  stand_in={quote(self.helpers)}/"${{relative//\\//__}}"\n'
            '  if [[ -f "$stand_in" ]]; then\n'
            f"    . {quote(self.record)}\n"
            "    shift\n"
            '    qv_record "$relative" "$@"\n'
            '    exec bash "$stand_in" "$@"\n'
            "  fi\n"
            "fi\n"
            f'exec {quote(sys.executable)} "$@"\n',
            encoding="utf-8",
        )
        shim.chmod(0o755)

    # ── running ──────────────────────────────────────────────────────────────
    def environment(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("QWENVOICE_", "QVOICE_"))
        }
        environment.update({
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "HOME": str(self.home),
            "QV_SANDBOX": str(self.path),
            "QV_CALLS": str(self.log),
            "QV_REAL_PYTHON": sys.executable,
        })
        environment.update(extra or {})
        return environment

    # ── reading ──────────────────────────────────────────────────────────────
    def calls(self) -> list[list[str]]:
        """Every recorded call in order, as [name, *arguments]."""
        return [line.split(SEPARATOR) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def calls_to(self, name: str, *prefix: str) -> list[list[str]]:
        """The arguments of each call to `name` whose arguments start with `prefix`."""
        return [
            call[1:] for call in self.calls()
            if call[0] == name and call[1:1 + len(prefix)] == list(prefix)
        ]

    def names(self) -> list[str]:
        return [call[0] for call in self.calls()]

    def index(self, name: str, *prefix: str, last: bool = False) -> int:
        """The position of the first (or last) call to `name` whose arguments start with `prefix`."""
        positions = [
            position for position, call in enumerate(self.calls())
            if call[0] == name and call[1:1 + len(prefix)] == list(prefix)
        ]
        if not positions:
            raise AssertionError(f"no call to {name} {' '.join(prefix)} in {self.calls()}")
        return positions[-1] if last else positions[0]


def option(arguments: list[str], name: str) -> str:
    """The value after `name` in an argument list."""
    return arguments[arguments.index(name) + 1]


class LaneShell(_Sandbox):
    """scripts/macos_test.sh or scripts/ios_device.sh, sourced with every function as shipped."""

    def __init__(self, test: unittest.TestCase, script: str) -> None:
        super().__init__(test)
        self.script = ROOT / "scripts" / script
        if not self.script.is_file():
            raise FileNotFoundError(self.script)

    def run(self, body: str, *, env: Mapping[str, str] | None = None,
            timeout: float = 60) -> subprocess.CompletedProcess[str]:
        """Source the lane, move every build-tree path into the sandbox, then run `body`."""
        script = (
            "set -euo pipefail\n"
            f". {quote(self.record)}\n"
            f". {quote(self.script)} help\n"
            # Values the lane derived from the build tree while it was sourced (its
            # build-output paths, DERIVED, APP_PATH, APP_BUNDLE, ...) now name the sandbox.
            '__qv_real_build="$QVOICE_BUILD_ROOT"\n'
            f"__qv_sandbox_build={quote(self.build)}\n"
            "for __qv_name in $(compgen -v); do\n"
            '  case "$__qv_name" in __qv_*|BASH*|FUNCNAME|PIPESTATUS|GROUPS|DIRSTACK) continue ;; esac\n'
            '  __qv_value="${!__qv_name-}"\n'
            '  [[ "$__qv_value" == "$__qv_real_build" || "$__qv_value" == "$__qv_real_build"/* ]] || continue\n'
            '  printf -v "$__qv_name" \'%s\' "$__qv_sandbox_build${__qv_value#"$__qv_real_build"}"\n'
            "done\n"
            + body
        )
        return subprocess.run(
            ["bash", "-c", script, "/dev/null"], cwd=ROOT, env=self.environment(env),
            text=True, capture_output=True, timeout=timeout, check=False,
        )


# A `libraries` value for scripts/lib/build_paths.sh: every build-output path in the sandbox.
SANDBOX_BUILD_PATHS = "<every build-output path in the sandbox>"


class ScriptSandbox(_Sandbox):
    """A whole script run from a temporary root: the real script, stand-in libraries.

    `libraries` maps a library path (`scripts/lib/x.sh`) to stand-in text, to
    SANDBOX_BUILD_PATHS, or to None to link the real library. Stand-in text may call
    `qv_record` and `qv_stub`."""

    def __init__(self, test: unittest.TestCase, script: str, libraries: Mapping[str, str | None]) -> None:
        super().__init__(test)
        self.root = self.path / "root"
        self.script = self.root / script
        self.script.parent.mkdir(parents=True)
        self.script.symlink_to(ROOT / script)
        for relative, text in libraries.items():
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if text is None:
                target.symlink_to(ROOT / relative)
            elif text == SANDBOX_BUILD_PATHS:
                target.write_text(self._build_paths_library(), encoding="utf-8")
            else:
                target.write_text(f". {quote(self.record)}\n{text}\n", encoding="utf-8")

    def _build_paths_library(self) -> str:
        lines = [f"export QVOICE_BUILD_ROOT={quote(self.build)}"]
        lines += [f"export {name}={quote(self.build / name.lower())}" for name in BUILD_PATHS]
        return "\n".join(lines) + "\n"

    def run_script(self, *arguments: str, env: Mapping[str, str] | None = None,
                   timeout: float = 60) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.script), *arguments], cwd=self.root, env=self.environment(env),
            text=True, capture_output=True, timeout=timeout, check=False,
        )


def ui_lane_sandbox(test: unittest.TestCase) -> ScriptSandbox:
    """scripts/ui_test.sh over stand-in libraries: the storage, quiet-host, model and
    signing preflights pass and record, the ledger records its steps and runs them,
    `xcb_run` records and fails, and the shared helpers are the real ones. Python
    helpers below the sandbox root need `helper()` stand-ins; ui_bench_allocation.py
    has one (the canonical matrix)."""
    sandbox = ScriptSandbox(test, "scripts/ui_test.sh", {
        "scripts/lib/build_paths.sh": SANDBOX_BUILD_PATHS,
        "scripts/lib/build_cache.sh": "".join(f"qv_stub {name}\n" for name in (
            "require_build_free_space", "require_ios_xcode_platform", "ensure_project_regenerated",
            "ensure_spm_resolved", "write_build_provenance", "warn_if_storage_bloated",
        )) + 'xcb_run() { qv_record xcb_run "$@"; return 65; }\n',
        "scripts/lib/host_preflight.sh": "qv_stub require_quiet_host\nqv_stub settle_host_load\n",
        "scripts/lib/shared.sh": None,
        "scripts/lib/required_steps.sh": (
            'required_steps_init() { qv_record required_steps_init "$@"; }\n'
            'required_step_run() { qv_record required_step_run "$2"; shift 2; "$@"; }\n'
            'required_step_record() { qv_record required_step_record "$2" "$3"; }\n'
            "required_steps_finalize() { qv_record required_steps_finalize; }\n"
        ),
        "scripts/lib/ui_finalization.sh": None,
        "scripts/lib/dev_signing.sh": "".join(f"qv_stub {name}\n" for name in (
            "resolve_dev_signing_identity", "sync_dev_signing_cache", "record_dev_signing_identity",
            "assert_signing_identity",
        )),
        "scripts/lib/test_models.sh": (
            "MAC_TEST_CLONE_VOICE_NAME=fixture-voice\nqv_stub test_models_init\n"
            "qv_stub mac_test_clone_fixture_current\n"
        ),
    })
    sandbox.helper("scripts/ui_bench_allocation.py",
                   'case " $* " in *" --field name "*) echo canonical-fixture ;; esac')
    return sandbox


class UIFunctionShell(_Sandbox):
    """Functions of scripts/ui_test.sh (loaded with `ui_function`) run over the real
    scripts/lib/shared.sh, with the sandbox's shims, HOME and call log."""

    def run(self, names: tuple[str, ...], body: str, *, env: Mapping[str, str] | None = None,
            timeout: float = 60) -> subprocess.CompletedProcess[str]:
        script = (
            "set -euo pipefail\n"
            f". {quote(self.record)}\n"
            f". {quote(ROOT / 'scripts/lib/shared.sh')}\n"
            + "".join(ui_function(name) + "\n" for name in names)
            + body
        )
        return subprocess.run(
            ["bash", "-c", script], cwd=self.path, env=self.environment(env),
            text=True, capture_output=True, timeout=timeout, check=False,
        )


def ui_function(name: str) -> str:
    """One function of scripts/ui_test.sh, to be defined and run in a test shell.

    The one place a test reads shell text: ui_test.sh runs its lane at top level, so it
    cannot be sourced. The seam that would retire this is a source guard before the
    lane's first step, or these functions moving to scripts/lib."""
    text = (ROOT / "scripts/ui_test.sh").read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}$", text, re.MULTILINE | re.DOTALL)
    if match is None:
        raise AssertionError(f"scripts/ui_test.sh defines no function {name}")
    return match.group(0)
