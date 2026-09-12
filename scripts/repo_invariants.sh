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
ci_error="$(python3 - 2>&1 <<'PY' || true
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
)"
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

# Flaky-test quarantine buys time, never permanence: entries older than 30 days fail.
python3 - <<'PY'
import datetime, json, pathlib
document = json.loads(pathlib.Path("config/test-quarantine.json").read_text(encoding="utf-8"))
today = datetime.date.today()
errors = []
for entry in document.get("entries", []):
    identifier, since, note = entry.get("id"), entry.get("since"), entry.get("note")
    if not identifier or not since or not note:
        errors.append(f"quarantine entry needs id, since and note: {entry}")
        continue
    age = (today - datetime.date.fromisoformat(since)).days
    if age > 30:
        errors.append(f"quarantine entry {identifier} is {age} days old; fix or delete the test")
if errors:
    raise SystemExit("\n".join(errors))
PY

# MLX facade boundary: the owned package carries exactly one test suite.
for entry in Packages/VocelloQwen3Core/Tests/*/; do
  [[ "$(basename "$entry")" == "Qwen3RuntimeTests" ]] \
    || fail "unexpected test directory in the owned runtime package: $entry"
done

# One lifecycle authority: generation views never start model prewarm themselves.
out="$(rg -n 'prewarmModelIfNeeded' Sources/Views/Generate --glob '*.swift' 2>/dev/null || true)"
[[ -z "$out" ]] || fail "generation views must not start model prewarm directly:\n$out"

# Routing views observe the player through their owners, not directly.
python3 - <<'PY'
from pathlib import Path
import re

regions = (
    ("Sources/ContentView.swift", r"struct ContentView: View", r"private struct CustomVoiceScreenHost"),
    ("Sources/Views/Sidebar/SidebarView.swift", r"struct SidebarView: View", r"private struct SidebarFooterRegion"),
)
errors = []
for relative, start, end in regions:
    path = Path(relative)
    if not path.is_file():
        continue
    text = path.read_text(encoding="utf-8")
    begin = re.search(start, text)
    stop = re.search(end, text)
    region = text[begin.start(): stop.start()] if begin and stop else text
    if re.search(r"@EnvironmentObject.*AudioPlayerViewModel", region):
        errors.append(f"{relative}: routing must not observe AudioPlayerViewModel directly")
if errors:
    raise SystemExit("\n".join(errors))
PY

# Generated project: one shippable project, no test-support flags, no local cache references.
! grep -q "QW_TEST_SUPPORT" project.yml || fail "QW_TEST_SUPPORT must not be configured in the single shippable project"
! grep -qE 'path = .*(__pycache__|\.pyc)' QwenVoice.xcodeproj/project.pbxproj \
  || fail "project references local-only Python cache files; regenerate with ./scripts/regenerate_project.sh --fast"

# Monetization: one StoreKit owner on iOS, and no persisted or debug-gated paid flag.
out="$(rg -l 'import StoreKit|StoreKit\.Transaction|AppStore\.sync\(' Sources 2>/dev/null \
  | rg -v '^Sources/iOS/Commerce/IOSStoreKitClient\.swift$' || true)"
[[ -z "$out" ]] || fail "StoreKit may be used only by IOSStoreKitClient:\n$out"
out="$(rg -n 'UserDefaults|RuntimeDebugGate' \
  Sources/iOS/Commerce/IOSStoreKitClient.swift Sources/iOSSupport/Services/IOSExportPurchaseState.swift 2>/dev/null || true)"
[[ -z "$out" ]] || fail "paid access is derived from verified transactions, never persisted or debug-gated:\n$out"

# Monetization: one export boundary on iOS; macOS and the CLI export freely.
out="$(rg -n 'UIActivityViewController\(|ShareLink\(' Sources/iOS 2>/dev/null \
  | rg -v '^Sources/iOS/Commerce/IOSExportGate\.swift:' || true)"
[[ -z "$out" ]] || fail "iOS exports must route through IOSExportGate:\n$out"
out="$(rg -n 'IOSExportCommerce' Sources/VocelloCLI Sources/Views Sources/Services 2>/dev/null || true)"
[[ -z "$out" ]] || fail "macOS and CLI exports must not consult iOS commerce:\n$out"

# Monetization: the StoreKit test configuration is a test-bundle resource only; no app target
# bundles it and no shared scheme activates it.
python3 - <<'PY'
from pathlib import Path
owners, current, in_targets, target_type = [], None, False, {}
for line in Path("project.yml").read_text(encoding="utf-8").splitlines():
    if line.startswith("targets:"):
        in_targets = True
        continue
    if in_targets and line and not line[0].isspace():
        in_targets = False
    if not in_targets:
        continue
    if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
        current = line.strip()[:-1]
    elif current and line.strip().startswith("type:"):
        target_type[current] = line.split(":", 1)[1].strip()
    elif current and "Tests/Fixtures/VocelloExports.storekit" in line:
        owners.append(current)
if not owners:
    raise SystemExit("Tests/Fixtures/VocelloExports.storekit is not declared by any test target in project.yml")
bad = [name for name in owners if not target_type.get(name, "").startswith("bundle.")]
if bad:
    raise SystemExit("the StoreKit test configuration may live only in test bundles, not " + ", ".join(bad))
PY
out="$(rg -l 'VocelloExports\.storekit' QwenVoice.xcodeproj/xcshareddata/xcschemes 2>/dev/null || true)"
[[ -z "$out" ]] || fail "no shared scheme may activate the StoreKit test configuration:\n$out"

# Genuine controls: clone consent is owned by Settings on iOS; no other surface declares the control.
[[ "$(rg -c 'accessibilityIdentifier: "voiceCloning_consentAcknowledgment"' Sources/iOS/Settings/SettingsScreen.swift || true)" == "1" ]] \
  || fail "the clone consent control must be declared once in Sources/iOS/Settings/SettingsScreen.swift"
out="$(rg -n 'voiceCloning_consentAcknowledgment' Sources/iOS 2>/dev/null | rg -v 'Settings/SettingsScreen\.swift' || true)"
[[ -z "$out" ]] || fail "clone consent is settings-owned; no other iOS surface may declare it:\n$out"

# Release-only candidate acceptance: the preinstalled-candidate UI test drives the shipped app as is.
out="$(rg -n 'QWENVOICE_DEBUG|VOCELLO_INTERNAL_DIAGNOSTICS|appDataContainer' \
  Tests/VocelloiOSUITests/VocelloiOSCandidateAcceptanceUITests.swift 2>/dev/null || true)"
[[ -z "$out" ]] || fail "candidate acceptance must not enable diagnostics or reach into the app container:\n$out"

# One Python test root: pytest collects scripts/tests/test_*.py only, so a module
# anywhere else or named otherwise would be silently unrun.
out="$(find scripts -name 'test_*.py' -not -path 'scripts/tests/*' -print; find scripts/tests -maxdepth 1 -name '*.py' ! -name 'test_*.py' ! -name 'conftest.py' -print)"
[[ -z "$out" ]] || fail "Python tests live only in scripts/tests as test_*.py (pytest collects nothing else):\n$out"

# Evidence retention: benchmarks/ holds compact summaries only, each at most 256 KB.
if [[ -d benchmarks ]]; then
  raw="$(find benchmarks \
    \( -type f \( \
      -iname '*.jsonl' -o -iname '*.ndjson' -o -iname '*.jsonlines' \
      -o -iname '*.log' -o -iname '*.ips' -o -iname '*.tracev3' \
      -o -iname '*.wav' -o -iname '*.wave' -o -iname '*.aif' -o -iname '*.aiff' \
      -o -iname '*.caf' -o -iname '*.flac' -o -iname '*.mp3' -o -iname '*.m4a' \
      -o -iname '*.ogg' -o -iname '*.opus' \
      -o -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.gif' \
      -o -iname '*.heic' -o -iname '*.heif' -o -iname '*.tif' -o -iname '*.tiff' \
      -o -iname '*.webp' -o -iname '*.bmp' \
      -o -iname '*.xcresult' -o -iname '*.trace' -o -iname '*.xcarchive' -o -iname '*.dsym' \
    \) -o -type d \( \
      -iname '*.xcresult' -o -iname '*.trace' -o -iname '*.xcarchive' -o -iname '*.dsym' \
    \) \) -print)"
  [[ -z "$raw" ]] || fail "raw benchmark telemetry, audio, screenshots, logs and bundles must stay untracked:\n$raw"
  oversized="$(find benchmarks -type f -size +262144c -print)"
  [[ -z "$oversized" ]] || fail "committed benchmark file exceeds the 256 KB cap:\n$oversized"
fi

echo "==> Repository invariants hold" >&2
