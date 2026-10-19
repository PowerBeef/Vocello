#!/usr/bin/env bash
# Cheap, exact greps for product invariants that no unit test can see.
# Each check names the invariant it protects; there is no prose denylist. A check
# reads a script's text only where the invariant lives in a lane that needs a
# phone or the app's UI to run, so no test can execute it; each such check says so.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

fail() { printf '\033[0;31m[repo-invariants]\033[0m %s\n' "$*" >&2; exit 1; }
command -v rg >/dev/null 2>&1 || fail "ripgrep is required"

# Physical iPhone only: no Simulator destination or Simulator tool route anywhere active.
out="$(rg -n -i 'platform=iOS Simulator|build_run_sim|test_sim|launch_sim' \
  CLAUDE.md README.md .claude website/CLAUDE.md docs scripts project.yml .github \
  --glob '!scripts/repo_invariants.sh' 2>/dev/null \
  || true)"
[[ -z "$out" ]] || fail "Simulator route in an active surface:\n$out"

# One UI driver: no workflow executes UI tests. Compiling them is allowed
# (push CI runs scripts/build_ui_test_bundles.sh --gate, build-for-testing
# only, PA-24); executing them is not: no test-without-building, no app UI lane
# and no xcodebuild or xcb_run `test` action, whatever the scheme. Comment
# lines are prose, not invocations; continued lines are joined first.
ci_error="$(python3 - 2>&1 <<'PY' || true
from pathlib import Path
import re

paths = sorted(Path('.github/workflows').glob('*.yml')) + sorted(Path('.github/actions').rglob('*.yml'))
patterns = {
    r'\btest-without-building\b': 'executes XCUITest (test-without-building)',
    r'\bscripts/ui_test\.sh\b': 'invokes an app UI lane (scripts/ui_test.sh)',
    r'\b(?:xcodebuild|xcb_run)\b.*(?<![\w./-])test(?![\w.-])': 'runs an xcodebuild test action',
}
for path in paths:
    lines = [line for line in path.read_text(encoding='utf-8').splitlines() if not line.lstrip().startswith('#')]
    for line in re.sub(r'\\\n\s*', ' ', '\n'.join(lines)).splitlines():
        for pattern, label in patterns.items():
            if re.search(pattern, line):
                raise SystemExit(f'{path} {label}; UI tests compile in CI but never execute there')
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

# The deterministic lane runs the Xcode-built test bundles with the raw `xcrun xctest`
# runner, which never executes Swift Testing tests: the run passes without them
# (workflow audit P1-6, verified 2026-10-18). Until a runner executes them, tests in
# the Xcode test targets stay XCTest. The owned package's tests run under `swift test`.
out="$(rg -n '^\s*(@\w+\s+)*import\s+Testing\b' Tests 2>/dev/null || true)"
[[ -z "$out" ]] || fail "Swift Testing in an Xcode test target would never run under the lane's xctest runner:\n$out"

# UI tests synchronise on conditions, never on the clock. The two perf scenario
# files are the recorded exemption: their paced sleeps are the measured workload.
out="$(rg -n '\b(?:sleep|usleep)\s*\(|Thread\.sleep' \
  Tests/UIAutomationSupport Tests/VocelloMacUITests Tests/VocelloiOSUITests 2>/dev/null \
  | rg -v '^Tests/Vocello(Mac|iOS)UITests/Vocello(Mac|iOS)PerfUITests\.swift:' || true)"
[[ -z "$out" ]] || fail "UI tests must use condition waits, not delays:\n$out"

# UI tests act on exact elements, never on raw coordinates. Beyond the perf
# files, VocelloUIWindowFrame.swift is exempt for one reason that cannot be
# engineered away: macOS XCUITest exposes no window-resize API, so sizing a
# window to a known width means dragging its edge, and an edge is a point on a
# window rather than an element. It uses no delays; the sleep rule above still
# binds it.
out="$(rg -n 'coordinate\s*\(' \
  Tests/UIAutomationSupport Tests/VocelloMacUITests Tests/VocelloiOSUITests 2>/dev/null \
  | rg -v '^Tests/Vocello(Mac|iOS)UITests/Vocello(Mac|iOS)PerfUITests\.swift:' \
  | rg -v '^Tests/VocelloMacUITests/VocelloUIWindowFrame\.swift:' || true)"
[[ -z "$out" ]] || fail "UI tests must act on exact elements, not coordinates:\n$out"
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
out="$(rg -n 'prewarmModelIfNeeded' Sources/Views/Studio --glob '*.swift' 2>/dev/null || true)"
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
    if re.search(r"@EnvironmentObject.*AudioPlayerViewModel|@Environment\(AudioPlayerViewModel(\.PlaybackProgress)?\.self\)", region):
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
# Every source root the iOS app compiles (Sources/iOS, Sources/iOSSupport and the
# shared views) presents an activity or share surface only through IOSExportGate.
out="$(rg -n 'UIActivityViewController\(|ShareLink\(' Sources/iOS Sources/iOSSupport 2>/dev/null \
  | rg -v '^Sources/iOS/Commerce/IOSExportGate\.swift:' || true)"
[[ -z "$out" ]] || fail "iOS exports must route through IOSExportGate:\n$out"
for shared in $(rg -l 'UIActivityViewController\(|ShareLink\(' Sources/SharedSupport 2>/dev/null || true); do
  rg -q '^\s*#if os\(iOS\)' "$shared" && rg -q 'IOSExportGate' "$shared" \
    || fail "shared view $shared shares audio without an iOS branch through IOSExportGate"
done
# Generated output never lands in the Files-visible Documents directory (UIFileSharingEnabled):
# the only Documents users are the two import pickers' default folder and the headless
# enrollment staging path, which reads references in and deletes them.
out="$(rg -n '\.documentDirectory' Sources/iOS Sources/iOSSupport Sources/SharedSupport 2>/dev/null \
  | rg -v '^Sources/iOS/(IOSVoicesView|IOSDeviceDiagnosticsRunner|App/RootView)\.swift:' || true)"
[[ -z "$out" ]] || fail "iOS writes outside the App Group container reach the Files app; keep outputs in AppPaths:\n$out"
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

# Purchase acceptance proves restoration: the iPhone purchase lane validates its local
# StoreKit evidence with --require-restoration, so a run that left the phone's Studio,
# tab or History filter changed is never purchase acceptance (the collector's own tests,
# scripts/tests/test_ios_purchase_acceptance.py, cover what the flag enforces). The lane
# needs a paired iPhone, so no test can run it; this keeps the flag on that call.
rg -q -U --multiline-dotall 'ios_purchase_acceptance\.py.{0,400}--require-restoration' scripts/ui_test.sh \
  || fail "scripts/ui_test.sh must run ios_purchase_acceptance.py with --require-restoration"

# Evidence ledgers: every UI lane in config/orchestration-contract.json binds each step it
# declares to a ledger call in scripts/ui_test.sh, and the lane announces PASS only after
# finalizing that ledger. The lanes need a phone or the app's UI, so no test can run them;
# the gate and release-readiness producers are behaviour-tested instead
# (scripts/tests/test_macos_gate.py, scripts/tests/test_profile_capture_contract.py).
ledger_error="$(python3 - 2>&1 <<'PY' || true
from pathlib import Path
import json
import re

producer = "scripts/ui_test.sh"
text = Path(producer).read_text(encoding="utf-8")
errors = []
for name in ("required_steps_init", "required_steps_finalize"):
    if name not in text:
        errors.append(f"{producer} never calls {name}")
workflows = json.loads(Path("config/orchestration-contract.json").read_text(encoding="utf-8"))["workflows"]
for workflow_id, workflow in workflows.items():
    if workflow["producer"] != producer:
        continue
    for step in workflow["requiredSteps"] + workflow.get("optionalSteps", []):
        if not re.search(rf"required_step_(?:run|record)[\s\S]{{0,100}}\b{re.escape(step)}\b", text):
            errors.append(f"{producer} binds no ledger call to step {step} that {workflow_id} declares")
if not re.search(r'required_steps_finalize[\s\S]{0,1400}note "\$platform \$lane PASS', text):
    errors.append(f"{producer} can announce PASS without finalizing its required-step ledger")
if errors:
    raise SystemExit("\n".join(errors))
PY
)"
[[ -z "$ledger_error" ]] || fail "$ledger_error"

# Release-only candidate acceptance: the preinstalled-candidate UI test drives the shipped app as is.
out="$(rg -n 'QWENVOICE_DEBUG|VOCELLO_INTERNAL_DIAGNOSTICS|appDataContainer' \
  Tests/VocelloiOSUITests/VocelloiOSCandidateAcceptanceUITests.swift 2>/dev/null || true)"
[[ -z "$out" ]] || fail "candidate acceptance must not enable diagnostics or reach into the app container:\n$out"

# One Python test root: pytest collects scripts/tests/test_*.py only, so a test module
# anywhere else, or a module there that defines tests under another name, would be
# silently unrun. Helper modules there (scripts/tests/shell_stubs.py) define no tests.
out="$(find scripts -name 'test_*.py' -not -path 'scripts/tests/*' -print
  find scripts/tests -maxdepth 1 -name '*.py' ! -name 'test_*.py' ! -name 'conftest.py' \
    -exec rg -l '^\s*def test_|^class \w+\(.*TestCase\)' {} + || true)"
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
