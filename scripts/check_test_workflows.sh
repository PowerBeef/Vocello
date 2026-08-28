#!/usr/bin/env bash
# Keep the repository on one app-UI automation stack: XCUITest.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

fail() { printf '\033[0;31m[test-workflow]\033[0m %s\n' "$*" >&2; exit 1; }
command -v rg >/dev/null 2>&1 || fail "ripgrep is required"

echo "==> XCUITest workflow consistency check" >&2

# The memory-pressure synchronization stress suite has an explicit sanitizer
# escape hatch, but ordinary deterministic checks must remain sanitizer-free.
rg -q 'QWENVOICE_ENABLE_TSAN:-0' scripts/macos_test.sh \
  || fail "macOS core-test lost its opt-in Thread Sanitizer switch"
rg -q 'sanitizer_setting="YES"' scripts/macos_test.sh \
  || fail "macOS core-test no longer enables Thread Sanitizer for the opt-in value"
rg -q -- '-enableThreadSanitizer "\$sanitizer_setting"' scripts/macos_test.sh \
  || fail "macOS core-test no longer routes the opt-in switch to xcodebuild"
rg -q 'cmd_tsan()' scripts/macos_test.sh \
  || fail "macOS scheduled TSan subset command is missing"
rg -q 'scripts/macos_test.sh tsan' .github/workflows/tsan.yml \
  || fail "scheduled TSan workflow no longer invokes the repository subset"

for required_policy_surface in \
  config/build-output-policy.json \
  config/codex-session-storage-policy.json \
  config/documentation-contract.json \
  config/public-product-facts.json \
  config/orchestration-contract.json \
  config/project-health-contract.json \
  config/quality-promotion-contract.json \
  config/tsan-policy.json \
  docs/project-health.md \
  scripts/build_output_policy.py \
  scripts/dev.sh \
  scripts/development_workflow.py \
  scripts/tree_fingerprint.py \
  scripts/codex_session_storage.py \
  scripts/cli_version_contract.py \
  scripts/saved_voice_lifecycle_contract.py \
  scripts/documentation_contract.py \
  scripts/model_catalog_contract.py \
  scripts/evidence_impact.py \
  scripts/quality_promotion.py \
  scripts/vendor_runtime_contract.py \
  scripts/supply_chain_contract.py \
  scripts/swift_dependency_snapshot.py \
  scripts/swift_dependency_updates.py \
  scripts/entitlement_contract.py \
  scripts/release_evidence.py \
  scripts/release_sbom.py \
  scripts/required_step_ledger.py \
  scripts/project_health.py \
  scripts/build_cleanup.py \
  scripts/clean_build_caches.sh \
  scripts/lib/build_paths.sh \
  scripts/lib/build_cache.sh \
  scripts/lib/required_steps.sh \
  scripts/lib/profile_trace_retention.py \
  scripts/lib/build_artifact_retention.py \
  scripts/lib/storage_preflight.py \
  scripts/lib/ios_platform_preflight.py \
  scripts/python_test_contract.py \
  scripts/tests/test_build_output_policy.py \
  scripts/tests/test_codex_session_storage.py \
  scripts/tests/test_codex_hook_contract.py \
  scripts/tests/test_cli_version_contract.py \
  scripts/tests/test_saved_voice_lifecycle_contract.py \
  scripts/tests/test_documentation_contract.py \
  scripts/tests/test_model_catalog_contract.py \
  scripts/tests/test_evidence_impact.py \
  scripts/tests/test_quality_promotion.py \
  scripts/tests/test_vendor_runtime_contract.py \
  scripts/tests/test_supply_chain_contract.py \
  scripts/tests/test_swift_dependency_snapshot.py \
  scripts/tests/test_swift_dependency_updates.py \
  scripts/tests/test_entitlement_contract.py \
  scripts/tests/test_release_evidence.py \
  scripts/tests/test_required_step_ledger.py \
  scripts/tests/test_project_health.py \
  scripts/tests/test_refresh_derived_artifacts.py \
  scripts/tests/test_build_routing_contract.py \
  scripts/tests/test_development_workflow.py \
  scripts/tests/test_tree_fingerprint.py \
  scripts/tests/test_clean_build_caches.py \
  scripts/tests/test_profile_trace_retention.py \
  scripts/tests/test_storage_preflight.py \
  scripts/tests/test_ios_platform_preflight.py \
  scripts/tests/test_python_test_contract.py; do
  [[ -f "$required_policy_surface" ]] \
    || fail "required build-output policy surface is missing: $required_policy_surface"
done

# The manifest owns every generated path. Load its validated exports before
# checking individual producer scripts, then enforce tracked-reference and
# compatibility-link consistency through the policy helper itself.
# shellcheck source=lib/build_paths.sh
. "$ROOT_DIR/scripts/lib/build_paths.sh"
python3 scripts/build_output_policy.py validate \
  || fail "build-output policy validation failed"

for required in \
  Tests/UIAutomationSupport \
  Tests/VocelloMacUITests \
  Tests/VocelloiOSUITests; do
  [[ -d "$required" ]] || fail "required XCUITest source directory is missing: $required"
done

for retired in \
  .mirroir-mcp \
  .agents/skills/vocello-macos-ui-qa \
  .agents/skills/vocello-ios-ui-qa \
  scripts/macos_agent_ui.sh \
  scripts/ios_agent_ui.sh \
  scripts/lib/macos_agent_ui.py \
  scripts/lib/ios_agent_ui.py \
  scripts/lib/computer_use_routing.py \
  scripts/test_macos_agent_ui.py \
  scripts/test_computer_use_routing.py \
  config/macos-ui-scenarios.json \
  config/ios-ui-scenarios.json \
  config/macos-test-impact.json \
  config/ios-test-impact.json \
  qa/macos-ui-attestation.json \
  qa/ios-ui-attestation.json \
  docs/reference/computer-use-failure-analysis.md \
  docs/reference/ui-smoke-runbooks.md \
  docs/reference/ios-device-probe.md \
  benchmarks/macos-multi-mode-ui-xpc-audit-2026-06-29.md \
  docs/macos-review-baselines \
  docs/ios-review-baselines \
  scripts/install_mirroir_user_config.sh \
  scripts/ios_mirroir_preflight.sh \
  scripts/ios_mobile_mcp.sh \
  scripts/lib/ios_mirror_discovery.sh \
  scripts/lib/ios_agent_bench_drive.sh \
  scripts/lib/ios_vision_bridge.sh \
  scripts/lib/ios_measure.sh \
  scripts/frontend_status_capture.sh \
  scripts/perf_investigation.sh \
  scripts/build_and_run.sh \
  Sources/iOS/IOSPreviewSupport.swift \
  Sources/iOS/IOSAutorunHarness.swift \
  benchmarks/macos-frontend-status-audit-2026-06-29.md \
  benchmarks/perf-investigation-2026-06-29.md \
  benchmarks/benchmarking-procedure-audit-2026-06-29.md \
  docs/reference/telemetry-harness-review.md \
  docs/superpowers/plans/2026-06-16-telemetry-phase-4.md \
  Tests/DeviceProbeFixtures/text-call-active.txt \
  Tests/DeviceProbeFixtures/text-mirror-active.txt \
  Tests/DeviceProbeFixtures/text-mirror-connecting.txt \
  Tests/DeviceProbeFixtures/text-phone-in-use.txt; do
  [[ ! -e "$retired" ]] || fail "retired UI harness artifact still exists: $retired"
done

active=(AGENTS.md README.md .gitignore .agents .codex benchmarks docs scripts config .github project.yml QwenVoice.xcodeproj/project.pbxproj Sources Tests website Packages/VocelloQwen3Core)
excludes=(
  --glob '!scripts/check_test_workflows.sh'
  --glob '!scripts/clean_build_caches.sh'
  --glob '!scripts/documentation_contract.py'
  --glob '!scripts/tests/test_documentation_contract.py'
  --glob '!docs/audits/archive/**'
)

# Policy prose may name retired harnesses (Mirroir, Peekaboo, computer-use, etc.).
# Fail closed on wiring: missing retired artifacts above, and the retired command
# forms below. Do not reintroduce a prose keyword denylist.

# Reject only retired command/dispatch forms. Generic UI-test prose, code review, and Xcode's
# bundle.ui-testing target type are valid and intentionally do not match these expressions.
retired_alias_pattern='(?x)(?:
  (?<![[:alnum:]_-])bench-ui(?![[:alnum:]_-])
  | (?<![[:alnum:]_-])ui-report(?![[:alnum:]_-])
  | (?:^|[[:space:]`])(?:(?:\./)?scripts/)?(?:macos_test|ios_device)\.sh[[:space:]]+(?:ui-test|review)\b
  | (?:^|[[:space:]`])(?:(?:\./)?scripts/)?ios_device\.sh[[:space:]]+logic-test\b
  | ^[[:space:]]*(?:ui-test|review)\)
  | ^[[:space:]]*logic-test\)
  | --suite(?:=|[[:space:]]+)(?:quick|full|benchmark)\b
)'
out="$(rg -n --pcre2 "$retired_alias_pattern" "${active[@]}" "${excludes[@]}" 2>/dev/null || true)"
[[ -z "$out" ]] || fail "retired UI command or suite alias returned:\n$out"

# UI acceptance is explicit and independent; packaging/readiness may not reacquire a UI-result gate.
release_ui_gate_pattern='(?i:gated by fresh (?:macOS|iOS|frontend|UI)|requires fresh .*XCUITest|XCUITest .* prerequisite.*(?:release|packag|archive)|(?:release|packag|archive).*(?:requires|required).*XCUITest)'
out="$(rg -n --pcre2 "$release_ui_gate_pattern" AGENTS.md README.md .agents .codex docs scripts .github \
  "${excludes[@]}" 2>/dev/null || true)"
[[ -z "$out" ]] || fail "release packaging must remain independent of XCUITest evidence:\n$out"

# Pinned research may retain obsolete procedures only when every directly
# openable report identifies itself before the historical body begins.
python3 scripts/documentation_contract.py \
  || fail "active documentation contract failed"
python3 scripts/vendor_runtime_contract.py validate \
  || fail "owned Qwen3 runtime contract failed"

# Current guidance uses the typed playback-scheduled and heartbeat metrics. Keep
# the retired display names in compatibility code and historical evidence only.
# Likewise, an iOS Instruments profile is its own run; it cannot be described as
# executing during a UI/headless benchmark matrix.
python3 - <<'PY'
from pathlib import Path
import re

files = [
    Path("AGENTS.md"),
    Path("README.md"),
    Path("benchmarks/README.md"),
    Path("docs/project-map.html"),
    Path("Sources/VocelloCLI/BenchCommand.swift"),  # built-in `vocello bench --help`
]
files.extend(Path(".agents/rules").rglob("*.md"))
files.extend(
    path
    for path in Path("docs").rglob("*.md")
    if "releases" not in path.parts
    and not {"audits", "archive"}.issubset(path.parts)
    and path != Path("docs/reference/backend-optimization-research-report.md")
)

retired_metrics = re.compile(r"\b(?:TTFA|UIstall)\b")
profile_during_matrix = re.compile(
    r"(?:scripts/)?ios_device\.sh\s+profile\b[^\n]*(?:during|inside|within)\b[^\n]*(?:benchmark|matrix)\b",
    re.IGNORECASE,
)
errors = []
for path in files:
    text = path.read_text(encoding="utf-8")
    for pattern, label in (
        (retired_metrics, "retired telemetry display name"),
        (profile_during_matrix, "iOS profile incorrectly described as running during a benchmark matrix"),
    ):
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            errors.append(f"{path}:{line}: {label}: {match.group(0)}")
if errors:
    raise SystemExit("\n".join(errors))
PY

# QWENVOICE_FAKE_MIC_WAV left this list 2026-07-22 by explicit maintainer
# decision: it is now a registered input-substitution knob in
# config/runtime-debug-knobs.json (master-gated), feeding the genuine visible
# recording flow rather than hiding test UI.
hidden_hook_pattern='HiddenAccessibilityMarker|QWENVOICE_UI_TEST_HOOKS|QVOICE_IOS_SKIP_ONBOARDING|QVOICE_IOS_TEST_CUSTOM_TEXT|screenPresenceMarker|MacUITestSurfaceMarkers|IOSStudioBenchHooks|IOSPreviewRuntime|IOSPreviewCaptureBridge|QVOICE_PREVIEW_|mainWindow_(?:ready|activeScreen|disabledSidebarItems|lastGenerationComplete|lastTelemetryFlushed|composeReady)|iosStudio_(?:lastGenerationComplete|generationError|benchClearScript)'
out="$(rg -n "$hidden_hook_pattern" Sources Tests scripts docs project.yml \
  --glob '!scripts/check_test_workflows.sh' 2>/dev/null || true)"
[[ -z "$out" ]] || fail "hidden UI-test marker/hook returned; assert real visible state instead:\n$out"

# There is one shippable Release configuration and no generic DEBUG symbol.
# Runtime diagnostics use DebugMode/TelemetryGate; named QVOICE_* feature
# conditions remain valid when a behavior truly must be selected at compile time.
out="$(rg -n --pcre2 '^[\t ]*#(?:if|elseif)\b[^\n]*\bDEBUG\b' Sources \
  --glob '*.swift' 2>/dev/null || true)"
[[ -z "$out" ]] || fail "generic #if DEBUG branch returned in shippable Sources:\n$out"

# Detect structural one-point accessibility anchors even when their type/name is
# changed. Identifiers belong on the genuine visible control or state container.
python3 - <<'PY'
from pathlib import Path

errors = []
for path in Path("Sources").rglob("*.swift"):
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if ".frame(width: 1, height: 1" not in line.replace("1.0", "1"):
            continue
        start = max(0, index - 10)
        end = min(len(lines), index + 11)
        region = "\n".join(lines[start:end])
        if ".opacity(0.01)" in region and ".accessibilityIdentifier(" in region:
            errors.append(f"{path}:{index + 1}: invisible one-point accessibility marker")
if errors:
    raise SystemExit("\n".join(errors))
PY

python3 - <<'PY'
from pathlib import Path
import hashlib
import re

text = Path("scripts/lib/test_models.sh").read_text(encoding="utf-8")
approved_clone_sha256 = "03187893a3d82d38264d433f24828982c67ed42cddb71eefccb776b37ab9fe35"
approved_transcript_sha256 = "98a8e46ed2cd48354f6056dc889f9209641824e610a687eeb9ab91d310477234"
required = (
    'MAC_TEST_CLONE_VOICE_BRIEF=',
    'MAC_TEST_CLONE_REF_TRANSCRIPT=',
    f'MAC_TEST_CLONE_REF_SHA256="{approved_clone_sha256}"',
    f'MAC_TEST_CLONE_REF_TRANSCRIPT_SHA256="{approved_transcript_sha256}"',
    'generate --mode design --variant speed',
    '--voice-brief "$MAC_TEST_CLONE_VOICE_BRIEF"',
    'mac_test_clone_fixture_current',
    'shasum -a 256 "$audio_file"',
    '"$actual_sha256" == "$MAC_TEST_CLONE_REF_SHA256"',
)
missing = [token for token in required if token not in text]
if missing:
    raise SystemExit(f"clone benchmark fixture lost Voice Design provenance: {missing}")
transcript_match = re.search(r'^MAC_TEST_CLONE_REF_TRANSCRIPT="([^"]+)"$', text, re.MULTILINE)
if not transcript_match or hashlib.sha256(transcript_match.group(1).encode()).hexdigest() != approved_transcript_sha256:
    raise SystemExit("clone fixture transcript digest no longer identifies the exact stored transcript")
if 'generate --mode custom --variant speed' in text:
    raise SystemExit("clone benchmark fixture must not be synthesized from the default Custom speaker")

device_script = Path("scripts/ios_device.sh").read_text(encoding="utf-8")
runner = Path("Sources/iOS/IOSDeviceDiagnosticsRunner.swift").read_text(encoding="utf-8")
validator = Path("scripts/check_ios_clone_conditioning.py")
for token in (
    "clone-conditioning)",
    "cmd_build --device-diagnostics",
    "check_ios_clone_conditioning.py",
):
    if token not in device_script:
        raise SystemExit(f"physical-iPhone clone-conditioning contract lost {token!r}")
for token in (
    "#if QVOICE_DEVICE_DIAGNOSTICS",
    'expectedConditioningMode: "transcript_backed"',
    'expectedConditioningMode: "x_vector_only"',
    "scratchCleanupVerified: true",
):
    if token not in runner:
        raise SystemExit(f"compile-gated clone-conditioning runner lost {token!r}")
if not validator.is_file():
    raise SystemExit("clone-conditioning validator is missing")
PY

# The two perf-lane scenario files are the deliberate exemptions: their
# fixed-interval sleeps ARE the measured workload (paced scroll sweeps, a
# 15 s idle window), not element synchronization — element waits still use
# VocelloUIWait — and their gesture coordinates are anchored on the window
# (macOS) or application root (iOS) precisely so per-event accessibility
# re-queries of deep elements stay out of the measured windows (the
# 2026-08-05 history-scroll Time Profiler finding); macOS additionally has
# no window-resize API other than the bottom-right corner drag.
out="$(rg -n '\b(?:sleep|usleep)\s*\(|Thread\.sleep|coordinate\s*\(' \
  Tests/UIAutomationSupport Tests/VocelloMacUITests Tests/VocelloiOSUITests 2>/dev/null \
  | rg -v '^Tests/Vocello(Mac|iOS)UITests/Vocello(Mac|iOS)PerfUITests\.swift:' || true)"
[[ -z "$out" ]] || fail "UI tests must use condition waits and exact elements, not delays/coordinates:\n$out"

out="$(rg -n 'matching\s*\(\s*NSPredicate\s*\(\s*format:\s*"label|buttons\s*\[\s*"(?:Generate|Custom|Design|Clone|Dismiss)' \
  Tests/UIAutomationSupport Tests/VocelloMacUITests Tests/VocelloiOSUITests 2>/dev/null || true)"
[[ -z "$out" ]] || fail "UI tests must use stable accessibility identifiers, not visible-label fallbacks:\n$out"

# Temporary Xcode work must live below build/scratch/derived-data. Keep the two
# historical one-off roots recognizable only in the cleanup migration; a new
# top-level *DerivedData* spelling in an active script would silently recreate
# the storage explosion that routine cleanup repairs.
python3 - <<'PY'
from pathlib import Path
import re

errors = []
roots = [Path("scripts"), Path(".github/workflows")]
legacy_cleanup_names = {
    "TelemetryAuditDerivedData",
    "DerivedData-ios-memory",
    "DerivedData-memory-failure",
}
# Match an actual repository-local top-level path component, not API/JSON
# identifiers such as `derivedDataPath` or `externalXcodeDerivedData`.
token = re.compile(
    r"(?P<path>(?:build|\$BUILD_DIR|\$\{BUILD_DIR\})/"
    r"(?P<name>[A-Za-z0-9._-]*DerivedData[A-Za-z0-9._-]*))"
)
for root in roots:
    if not root.exists():
        continue
    for path in root.rglob("*"):
        if not path.is_file() or "tests" in path.parts:
            continue
        if path.suffix not in {".sh", ".py", ".yml", ".yaml"}:
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in token.finditer(line):
                name = match.group("name")
                if path in {
                    Path("scripts/clean_build_caches.sh"),
                    Path("scripts/check_test_workflows.sh"),
                } and name in legacy_cleanup_names:
                    continue
                errors.append(
                    f"{path}:{line_number}: ad hoc DerivedData root {name}; "
                    "use build/scratch/derived-data/<purpose>"
                )
if errors:
    raise SystemExit("\n".join(errors))
PY

[[ "$QVOICE_SCRATCH_FOUNDATION" == "$QVOICE_BUILD_ROOT/scratch/"* ]] \
  || fail "QVOICE_SCRATCH_FOUNDATION must remain a classified scratch path"
[[ "$QVOICE_ARTIFACTS_FOUNDATION" == "$QVOICE_BUILD_ROOT/artifacts/"* ]] \
  || fail "QVOICE_ARTIFACTS_FOUNDATION must remain a classified artifact path"
[[ "$QVOICE_XCODE_SOURCE_PACKAGES" == "$QVOICE_BUILD_ROOT/cache/"* ]] \
  || fail "QVOICE_XCODE_SOURCE_PACKAGES must remain a classified cache path"
for foundation_policy_variable in \
  QVOICE_SCRATCH_FOUNDATION \
  QVOICE_ARTIFACTS_FOUNDATION \
  QVOICE_XCODE_SOURCE_PACKAGES; do
  rg -Fq "\$$foundation_policy_variable" scripts/build_foundation_targets.sh \
    || fail "foundation compile checks must consume $foundation_policy_variable from the build policy"
done
rg -q -- '--prune-ui-results' scripts/ui_test.sh \
  || fail "successful XCUITest runs must prune superseded result bundles"

# The macOS runner may signal only PIDs whose executable resolves to its exact
# DerivedData product. A name-wide kill could terminate a user's other Vocello.
rg -q 'process_executable_path' scripts/ui_test.sh \
  || fail "macOS UI runner lost exact executable identity validation"
rg -q 'Build/Products/Release/Vocello\.app/Contents/MacOS/Vocello' scripts/ui_test.sh \
  || fail "macOS UI runner lost its exact test-host executable path"
out="$(rg -n 'pkill[^\n]*(?:Vocello|QwenVoiceEngineService)' scripts/ui_test.sh 2>/dev/null || true)"
[[ -z "$out" ]] || fail "macOS UI runner must never name-kill Vocello processes:\n$out"

# The only app-UI topology is two isolated schemes and two UI-test bundles.
python3 - <<'PY'
from pathlib import Path
import re

text = Path("project.yml").read_text(encoding="utf-8")
for name in ("VocelloMacUI", "VocelloiOSUI", "VocelloMacUITests", "VocelloiOSUITests"):
    count = len(re.findall(rf"^  {re.escape(name)}:$", text, re.MULTILINE))
    if count != 1:
        raise SystemExit(f"project.yml must define {name} exactly once (found {count})")
for target, host in (("VocelloMacUITests", "QwenVoice"), ("VocelloiOSUITests", "VocelloiOS")):
    match = re.search(rf"^  {target}:\n(?P<body>(?:    .*\n|\n)*)", text, re.MULTILINE)
    body = match.group("body") if match else ""
    if "type: bundle.ui-testing" not in body or f"TEST_TARGET_NAME: {host}" not in body:
        raise SystemExit(f"{target} must remain an isolated UI-test bundle hosted by {host}")
for scheme in ("QwenVoice", "VocelloiOS"):
    match = re.search(rf"^  {scheme}:\n(?P<body>(?:    .*\n|\n)*)", text, re.MULTILINE)
    if match is None:
        raise SystemExit(f"project.yml is missing ordinary scheme {scheme}")
    body = match.group("body")
    if "VocelloMacUITests" in body or "VocelloiOSUITests" in body:
        raise SystemExit(f"ordinary scheme {scheme} must not include a UI-test bundle")

logic_target = re.search(
    r"^  VocelloiOSLogicTests:\n(?P<body>(?:    .*\n|\n)*)",
    text,
    re.MULTILINE,
)
logic_body = logic_target.group("body") if logic_target else ""
if "type: bundle.unit-test" not in logic_body or "platform: iOS" not in logic_body:
    raise SystemExit("VocelloiOSLogicTests must remain a standalone iOS unit-test bundle")
if "TEST_TARGET_NAME" in logic_body:
    raise SystemExit("VocelloiOSLogicTests must remain app-host-free")
core_target = re.search(
    r"^  VocelloCoreTests:\n(?P<body>(?:    .*\n|\n)*)",
    text,
    re.MULTILINE,
)
core_body = core_target.group("body") if core_target else ""
required_host_policy_sources = (
    "Tests/VocelloiOSLogicTests",
    "Sources/iOSSupport/Services/AppPaths.swift",
    "Sources/iOSSupport/Services/IOSModelDeliverySupport.swift",
    "Sources/iOSSupport/Services/IOSModelProgressPresentation.swift",
    "Sources/iOSSupport/Services/RuntimeReleaseCoordinator.swift",
)
missing_logic_policy_sources = [
    source for source in required_host_policy_sources if source not in logic_body
]
if missing_logic_policy_sources:
    raise SystemExit(
        "VocelloiOSLogicTests must compile the same platform-neutral policy surface: "
        + ", ".join(missing_logic_policy_sources)
    )
missing_host_policy_sources = [
    source for source in required_host_policy_sources if source not in core_body
]
if missing_host_policy_sources:
    raise SystemExit(
        "VocelloCoreTests must execute the platform-neutral iOS policy surface: "
        + ", ".join(missing_host_policy_sources)
    )
logic_template = Path("config/xcode-schemes/VocelloiOSLogic.xcscheme.template").read_text(
    encoding="utf-8"
)
if "VocelloiOSLogicTests" not in logic_template or "TestableReference" not in logic_template:
    raise SystemExit("VocelloiOSLogic generated scheme must own the standalone policy-test bundle")
PY

# Ordinary CI must neither compile UI-test bundles nor execute UI acceptance.
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
    text = path.read_text(encoding='utf-8')
    for pattern, label in patterns.items():
        if re.search(pattern, text):
            raise SystemExit(f'{path} {label}; UI execution must stay explicit')
PY
2>&1 || true)"
[[ -z "$ci_error" ]] || fail "$ci_error"
rg -q -- '-scheme VocelloiOSLogic' .github/workflows/ci.yml \
  || fail "ordinary CI must compile the standalone iOS logic-test bundle"
rg -q -- 'scripts/macos_test.sh test' .github/workflows/ci.yml \
  || fail "ordinary CI must execute the host-runnable iOS policy assertions"
rg -q -- 'run_mac_test_bundle VocelloCoreTests' scripts/macos_test.sh \
  || fail "macOS deterministic tests must execute VocelloCoreTests"
rg -q 'CODE_SIGNING_ALLOWED=NO' .github/workflows/ci.yml \
  || fail "generic iOS CI compilation must remain signing-independent"

# No simulator destination is supported for Vocello app UI automation.
out="$(rg -n -i 'platform=iOS Simulator|build_run_sim|test_sim|launch_sim' \
  AGENTS.md README.md .agents .codex docs scripts project.yml .github \
  --glob '!scripts/check_test_workflows.sh' 2>/dev/null || true)"
[[ -z "$out" ]] || fail "active Simulator workflow returned:\n$out"

# Validate relative Markdown links in active guidance so deleted harness documents
# cannot remain referenced. Immutable release notes, dated baselines, the legacy
# ledger, and pinned research bodies remain historical evidence rather than live
# operator instructions.
python3 - <<'PY'
from pathlib import Path
import re

files = [Path("AGENTS.md"), Path("README.md"), Path("benchmarks/README.md"), Path("website/AGENTS.md")]
files.extend(Path(".agents/rules").rglob("*.md"))
files.extend(
    path
    for path in Path("docs").rglob("*.md")
    if "releases" not in path.parts
    and path != Path("docs/reference/backend-optimization-research-report.md")
)

errors = []
pattern = re.compile(r'\[[^\]]*\]\(([^)]+)\)')
for source in files:
    text = source.read_text(encoding='utf-8')
    for target in pattern.findall(text):
        target = target.strip().strip('<>')
        if not target or target.startswith(('#', 'http://', 'https://', 'mailto:', 'plugin://')):
            continue
        path_part = target.split('#', 1)[0]
        if not path_part:
            continue
        resolved = (source.parent / path_part).resolve()
        if not resolved.exists():
            errors.append(f'{source}: missing link target {target}')
if errors:
    raise SystemExit('\n'.join(errors))
PY

# Validate local HTML links in the active project map as well as Markdown links.
python3 - <<'PY'
from pathlib import Path
import re

errors = []
for source in Path("docs").rglob("*.html"):
    text = source.read_text(encoding="utf-8")
    for target in re.findall(r'(?:href|src)=["\']([^"\']+)["\']', text):
        if not target or target.startswith(("#", "http://", "https://", "data:", "mailto:")):
            continue
        path_part = target.split("#", 1)[0].split("?", 1)[0]
        if path_part and not (source.parent / path_part).resolve().exists():
            errors.append(f"{source}: missing HTML target {target}")
if errors:
    raise SystemExit("\n".join(errors))
PY

# Literal documented script commands must resolve to real dispatch forms. This
# deliberately checks active guidance, while immutable release notes stay history.
python3 - <<'PY'
from pathlib import Path
import re

roots = [
    Path("AGENTS.md"),
    Path("README.md"),
    Path(".agents/rules"),
    Path("docs/reference"),
    Path("benchmarks/README.md"),
    Path("docs/project-map.html"),
]
files = []
for root in roots:
    candidates = [root] if root.is_file() else root.rglob("*.md")
    files.extend(
        path
        for path in candidates
        if path != Path("docs/reference/backend-optimization-research-report.md")
    )
allowed = {
    "ios_device.sh": {"doctor", "build", "install", "launch", "console", "pull", "bench", "lang-bench", "delivery-reliability", "clone-conditioning", "speech-assets", "enroll-clone-fixture", "crashes", "debug", "logs", "profile", "memory", "memory-field-report", "preflight", "device-state", "gate", "help"},
    "macos_test.sh": {"preflight", "core-test", "tsan", "lang-bench", "test", "telemetry-overhead", "crashes", "debug", "logs", "profile", "memory", "gate", "release-readiness", "models", "help"},
    "ui_test.sh": {"macos", "ios"},
}
errors = []
command = re.compile(r"(?:\./)?scripts/(ios_device\.sh|macos_test\.sh|ui_test\.sh)\s+([a-z][a-z0-9-]*)")
baseline = re.compile(r"--compare-baseline(?:=|\s+)([^\s`\\]+)")
for path in files:
    text = path.read_text(encoding="utf-8")
    for script, subcommand in command.findall(text):
        if subcommand not in allowed[script]:
            errors.append(f"{path}: unsupported {script} command: {subcommand}")
    for argument in baseline.findall(text):
        if argument.startswith(("$", "<")):
            continue
        if Path(argument.strip('"\'')).suffix.lower() != ".json":
            errors.append(f"{path}: --compare-baseline requires a JSON baseline, not {argument}")
if errors:
    raise SystemExit("\n".join(errors))
PY

# Catch stale inline source/test/script paths in active guidance. Vendored MLX
# sources may be documented relative to their package root.
python3 - <<'PY'
from pathlib import Path
import glob
import re

roots = [
    Path("AGENTS.md"),
    Path("README.md"),
    Path(".agents/rules"),
    Path("docs/reference"),
    Path("benchmarks/README.md"),
    Path("docs/project-map.html"),
]
files = []
for root in roots:
    candidates = [root] if root.is_file() else root.rglob("*.md")
    files.extend(
        path
        for path in candidates
        if path != Path("docs/reference/backend-optimization-research-report.md")
    )
prefixes = ("Sources/", "Tests/", "scripts/", "config/", ".github/", "Packages/")
errors = []
for source in files:
    text = source.read_text(encoding="utf-8")
    for value in re.findall(r"`([^`\n]+)`", text):
        candidate = value.strip().split()[0].rstrip(".,;:")
        candidate = re.sub(r":\d+(?:-\d+)?$", "", candidate)
        if not candidate.startswith(prefixes) or not Path(candidate).suffix:
            continue
        if any(marker in candidate for marker in ("<", ">", "{", "}", "$")):
            continue
        matches = glob.glob(candidate) if "*" in candidate else ([candidate] if Path(candidate).exists() else [])
        if not matches and candidate.startswith("Sources/"):
            runtime = Path("Packages/VocelloQwen3Core") / candidate
            matches = [str(runtime)] if runtime.exists() else []
        if not matches:
            errors.append(f"{source}: stale inline path {candidate}")
if errors:
    raise SystemExit("\n".join(errors))
PY

# Tracked artifacts must not capture a developer's absolute home path. The
# explicit /Users/example privacy-test fixture is intentionally synthetic.
out="$(git grep -nE '/Users/[A-Za-z0-9._-]+/' -- ':!scripts/check_test_workflows.sh' 2>/dev/null \
  | rg -v '/Users/example/' || true)"
[[ -z "$out" ]] || fail "tracked developer home path returned; use a relative or redacted path:\n$out"

python3 scripts/validate_backend_risk_spine.py

# Script self-tests validate the gate/tooling scripts themselves (~75 s).
# QVOICE_GATES=quick may skip them ONLY while nothing under scripts/ or
# config/ has pending changes — the fast wiring/privacy/contract scans above
# always run. Default (unset) behavior is unchanged; ordinary CI and release
# lanes never set this and therefore always run the full suite.
python3 scripts/python_test_contract.py validate \
  || fail "Python test inventory/discovery contract failed"
if [[ "${QVOICE_GATES:-}" == "quick" ]] \
    && [[ -z "$(git status --porcelain -- scripts config 2>/dev/null)" ]]; then
  echo "==> quick gate mode: scripts/config unchanged — skipping script self-tests" >&2
else
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
fi

echo "==> XCUITest workflow consistency check passed" >&2
