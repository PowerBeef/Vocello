#!/usr/bin/env bash
# Compiles the XCUITest bundles. It builds, and never runs, a test.
#
# The UI-test bundles are built only by the UI schemes, which the app-target
# builds and the deterministic suites never touch, so until 2026-09-17 a syntax
# error in the code that drives every acceptance lane reached a human only when
# someone ran a lane. `scripts/dev.sh check` runs this when UI-test sources or
# project.yml change, and push CI runs it with `--gate` in the macos-tests and
# ios-compile jobs (PA-24). Compiling is not executing: `repo_invariants.sh`
# check #2 still forbids every workflow from executing XCUITest.
#
# Two arenas:
#   default  each bundle compiles with its lane's exact settings in the lane's
#            arena (PA-04), so a local compile warms the next UI run.
#   --gate   each bundle compiles in the arena, and with the settings, of the
#            deterministic build that just ran there (`scripts/macos_test.sh
#            test` on macOS, `build_foundation_targets.sh ios --incremental` on
#            iOS), so the app host is already current and only the UI-test
#            target compiles. Push CI uses this right after those builds; on
#            a push that changed only the macOS UI-test sources the macOS
#            build is skipped and this brings the app host current itself.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/shared.sh
. "$ROOT_DIR/scripts/lib/shared.sh"
# shellcheck source=lib/build_paths.sh
. "$ROOT_DIR/scripts/lib/build_paths.sh"
# shellcheck source=lib/build_cache.sh
. "$ROOT_DIR/scripts/lib/build_cache.sh"

USAGE="usage: ./scripts/build_ui_test_bundles.sh [macos|ios|all] [--gate]"
MODE="all"
GATE=0
for argument in "$@"; do
  case "$argument" in
    macos|ios|all) MODE="$argument" ;;
    --gate) GATE=1 ;;
    *) die "$USAGE" ;;
  esac
done

build() {
  local scheme="$1" destination="$2" derived="$3"
  shift 3
  local log="$LOG_DIR/$scheme.log"
  note "compiling $scheme (build only, never run)"
  # `build-for-testing`, not `test`: this produces the bundle and stops. The
  # runner is never launched, no app is installed, no device is touched.
  # xcb_run holds the host-wide native lock for the whole compile.
  QVOICE_NATIVE_LOCK_LABEL="ui-bundles:$scheme" xcb_run build-for-testing \
    -project "$ROOT_DIR/QwenVoice.xcodeproj" \
    -scheme "$scheme" \
    -configuration Release \
    -destination "$destination" \
    -derivedDataPath "$derived" \
    -clonedSourcePackagesDirPath "$QVOICE_XCODE_SOURCE_PACKAGES" \
    -disableAutomaticPackageResolution \
    -onlyUsePackageVersionsFromResolvedFile \
    "$@" >"$log" 2>&1 \
    || { grep -E ' error: |\*\* TEST BUILD FAILED' "$log" | tail -n 40 >&2 || true
         die "$scheme failed to compile (see $log)"; }
  # How much this compile rebuilt: a handful of UI-test files when the app host
  # was current, hundreds when the settings drifted from the arena's last build.
  local compile_tasks
  compile_tasks="$(grep -c '^SwiftCompile ' "$log" 2>/dev/null || true)"
  note "$scheme compiled: ${compile_tasks:-0} SwiftCompile task(s) in $derived"
}

LOG_DIR="$QVOICE_ARTIFACTS_UI_BUNDLES"
mkdir -p "$LOG_DIR"

ensure_project_regenerated || die "project regeneration failed"
# Resolve under the key the platform's deterministic build already stamped
# (macos_test.sh for macOS, build_foundation_targets.sh ios for iOS), so a
# compile after that build never re-resolves the shared checkout.
if [[ "$MODE" == "ios" ]]; then
  ensure_spm_resolved "$QVOICE_SCRATCH_PACKAGE_RESOLUTION" "$QVOICE_XCODE_SOURCE_PACKAGES" \
    ui-bundles VocelloiOS Release 'generic/platform=iOS' \
    || die "shared Swift package resolution failed"
else
  ensure_spm_resolved "$QVOICE_SCRATCH_PACKAGE_RESOLUTION" "$QVOICE_XCODE_SOURCE_PACKAGES" \
    ui-bundles QwenVoice Release 'platform=macOS,arch=arm64' \
    || die "shared Swift package resolution failed"
fi

if [[ "$MODE" == "macos" || "$MODE" == "all" ]]; then
  if (( GATE == 1 )); then
    # scripts/macos_test.sh test's settings in its -Onone arena; keep them in
    # step with build_mac_test_bundles there.
    build VocelloMacUI "platform=macOS,arch=arm64" "$QVOICE_XCODE_MACOS_DERIVED" \
      -enableThreadSanitizer NO -enableCodeCoverage NO \
      ARCHS=arm64 ONLY_ACTIVE_ARCH=YES CODE_SIGN_STYLE=Manual CODE_SIGN_IDENTITY="-" \
      CODE_SIGN_ALLOW_ENTITLEMENTS_MODIFICATION=YES \
      QVOICE_INTERNAL_DIAGNOSTICS_SWIFT_FLAG=-DVOCELLO_INTERNAL_DIAGNOSTICS \
      SWIFT_OPTIMIZATION_LEVEL="-Onone" SWIFT_COMPILATION_MODE="incremental" \
      GCC_OPTIMIZATION_LEVEL="0" ENABLE_TESTABILITY=YES
  else
    # The same settings as scripts/ui_test.sh's macOS build-for-testing.
    build VocelloMacUI "platform=macOS,arch=arm64" "$QVOICE_XCODE_MACOS_OPTIMIZED_DERIVED" \
      CODE_SIGN_STYLE=Manual CODE_SIGN_IDENTITY="-" ONLY_ACTIVE_ARCH=YES ARCHS=arm64 \
      QVOICE_INTERNAL_DIAGNOSTICS_SWIFT_FLAG=-DVOCELLO_INTERNAL_DIAGNOSTICS \
      SWIFT_OPTIMIZATION_LEVEL=-O
  fi
fi

if [[ "$MODE" == "ios" || "$MODE" == "all" ]]; then
  # Generic device SDK, never a Simulator, and unsigned: a compile needs no
  # identity and no phone.
  require_ios_xcode_platform || die "iOS compile is blocked by the selected Xcode toolchain"
  if (( GATE == 1 )); then
    # build_foundation_targets.sh ios --incremental's settings, including its
    # QVOICE_FOUNDATION_SWIFT_OPTIMIZATION override (-O by default, -Onone in
    # push CI); keep them in step with build_ios there.
    optimization="${QVOICE_FOUNDATION_SWIFT_OPTIMIZATION:--O}"
    case "$optimization" in
      -O|-Onone) ;;
      *) die "QVOICE_FOUNDATION_SWIFT_OPTIMIZATION must be -O or -Onone (got '$optimization')" ;;
    esac
    swift_settings=(SWIFT_OPTIMIZATION_LEVEL="$optimization")
    [[ "$optimization" != "-Onone" ]] || swift_settings+=(SWIFT_COMPILATION_MODE=incremental)
    build VocelloiOSUI "generic/platform=iOS" "$QVOICE_XCODE_IOS_DERIVED" \
      CODE_SIGNING_ALLOWED=NO ARCHS=arm64 ONLY_ACTIVE_ARCH=YES "${swift_settings[@]}"
  else
    build VocelloiOSUI "generic/platform=iOS" "$QVOICE_XCODE_IOS_DERIVED" \
      CODE_SIGNING_ALLOWED=NO
  fi
fi

note "UI test bundles compiled"
