#!/usr/bin/env bash
# Cheap, exact greps for product invariants that no unit test can see.
# Each check names the invariant it protects; there is no prose denylist and
# no assertion about the text of other scripts or workflows.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

fail() { printf '\033[0;31m[repo-invariants]\033[0m %s\n' "$*" >&2; exit 1; }
command -v rg >/dev/null 2>&1 || fail "ripgrep is required"

# Physical iPhone only: no Simulator destination or Simulator tool route anywhere active.
out="$(rg -n -i 'platform=iOS Simulator|build_run_sim|test_sim|launch_sim' \
  CLAUDE.md README.md .claude docs scripts project.yml .github \
  --glob '!scripts/repo_invariants.sh' 2>/dev/null || true)"
[[ -z "$out" ]] || fail "Simulator route in an active surface:\n$out"

# One UI driver: ordinary CI and release workflows never execute UI tests.
ci_error="$(python3 - <<'PY'
from pathlib import Path
import re

paths = (
    Path('.github/workflows/ci.yml'),
    Path('.github/workflows/release.yml'),
    Path('.github/workflows/promote-release.yml'),
)
patterns = {
    r'\btest-without-building\b': 'executes XCUITest',
    r'\bscripts/ui_test\.sh\b': 'invokes an app UI lane',
    r'\bxcodebuild\s+test\b': 'executes xcodebuild test',
    r'\b(?:VocelloMacUI|VocelloiOSUI|VocelloMacUITests|VocelloiOSUITests)\b': 'references an isolated UI-test scheme or bundle',
}
for path in paths:
    if not path.is_file():
        continue
    text = path.read_text(encoding='utf-8')
    for pattern, label in patterns.items():
        if re.search(pattern, text):
            raise SystemExit(f'{path} {label}; UI execution must stay explicit')
PY
2>&1 || true)"
[[ -z "$ci_error" ]] || fail "$ci_error"

# Release-only configuration: no generic DEBUG branch in shippable sources.
out="$(rg -n --pcre2 '^[\t ]*#(?:if|elseif)\b[^\n]*\bDEBUG\b' Sources --glob '*.swift' 2>/dev/null || true)"
[[ -z "$out" ]] || fail "generic #if DEBUG branch in shippable Sources:\n$out"

# Genuine controls: no hidden UI-test markers, preview runtimes or onboarding bypasses.
hidden_hook_pattern='HiddenAccessibilityMarker|QWENVOICE_UI_TEST_HOOKS|QVOICE_IOS_SKIP_ONBOARDING|QVOICE_IOS_TEST_CUSTOM_TEXT|screenPresenceMarker|MacUITestSurfaceMarkers|IOSStudioBenchHooks|IOSPreviewRuntime|IOSPreviewCaptureBridge|QVOICE_PREVIEW_|mainWindow_(?:ready|activeScreen|disabledSidebarItems|lastGenerationComplete|lastTelemetryFlushed|composeReady)|iosStudio_(?:lastGenerationComplete|generationError|benchClearScript)'
out="$(rg -n "$hidden_hook_pattern" Sources Tests scripts project.yml \
  --glob '!scripts/repo_invariants.sh' 2>/dev/null || true)"
[[ -z "$out" ]] || fail "hidden UI-test marker or hook; assert real visible state instead:\n$out"

# Genuine controls: identifiers belong on visible controls, not invisible one-point anchors.
python3 - <<'PY'
from pathlib import Path

errors = []
for path in Path("Sources").rglob("*.swift"):
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if ".frame(width: 1, height: 1" not in line.replace("1.0", "1"):
            continue
        region = "\n".join(lines[max(0, index - 10):min(len(lines), index + 11)])
        if ".opacity(0.01)" in region and ".accessibilityIdentifier(" in region:
            errors.append(f"{path}:{index + 1}: invisible one-point accessibility marker")
if errors:
    raise SystemExit("\n".join(errors))
PY

# UI tests synchronise on conditions and stable identifiers. The two perf scenario
# files are the recorded exemption: their paced sleeps are the measured workload.
out="$(rg -n '\b(?:sleep|usleep)\s*\(|Thread\.sleep|coordinate\s*\(' \
  Tests/UIAutomationSupport Tests/VocelloMacUITests Tests/VocelloiOSUITests 2>/dev/null \
  | rg -v '^Tests/Vocello(Mac|iOS)UITests/Vocello(Mac|iOS)PerfUITests\.swift:' || true)"
[[ -z "$out" ]] || fail "UI tests must use condition waits and exact elements, not delays or coordinates:\n$out"
out="$(rg -n 'matching\s*\(\s*NSPredicate\s*\(\s*format:\s*"label|buttons\s*\[\s*"(?:Generate|Custom|Design|Clone|Dismiss)' \
  Tests/UIAutomationSupport Tests/VocelloMacUITests Tests/VocelloiOSUITests 2>/dev/null || true)"
[[ -z "$out" ]] || fail "UI tests must use stable accessibility identifiers, not visible-label fallbacks:\n$out"

# MLX facade boundary: the owned package carries exactly one test suite.
for entry in Packages/VocelloQwen3Core/Tests/*/; do
  [[ "$(basename "$entry")" == "Qwen3RuntimeTests" ]] \
    || fail "unexpected test directory in the owned runtime package: $entry"
done

echo "==> Repository invariants hold" >&2
