#!/usr/bin/env bash
# Compiles the XCUITest bundles. Nothing else in this repository does.
#
# `scripts/dev.sh check` and push CI both build the app targets and run the
# deterministic suites, but the UI-test bundles are built only by the schemes
# `scripts/ui_test.sh` invokes — and `repo_invariants.sh` check #2 forbids CI
# from naming those bundles at all, because CI must never execute XCUITest.
# The result was that the code driving every acceptance lane had no compile
# gate: a syntax error there reached a human only when someone ran a lane, and
# the 2026-09-17 audit found it was also where the session's worst defects
# landed.
#
# Compiling is not executing, so this closes the gap without touching that
# invariant. It builds, and never runs, a test.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/shared.sh
. "$ROOT_DIR/scripts/lib/shared.sh"
# shellcheck source=lib/build_paths.sh
. "$ROOT_DIR/scripts/lib/build_paths.sh"
# shellcheck source=lib/build_cache.sh
. "$ROOT_DIR/scripts/lib/build_cache.sh"

MODE="${1:-all}"
case "$MODE" in
  macos|ios|all) ;;
  *) die "usage: ./scripts/build_ui_test_bundles.sh [macos|ios|all]" ;;
esac

# Each bundle compiles into the arena its lane uses, against the shared package
# checkout, so the compile warms the lane's cache instead of invalidating
# another one (PA-04): VocelloMacUI with exactly the macOS UI lane's settings in
# the optimized arena, VocelloiOSUI unsigned in the device arena.
build() {
  local scheme="$1" destination="$2" derived="$3"
  shift 3
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
    "$@" >"$LOG_DIR/$scheme.log" 2>&1 \
    || die "$scheme failed to compile (see $LOG_DIR/$scheme.log)"
}

LOG_DIR="$QVOICE_ARTIFACTS_UI_BUNDLES"
mkdir -p "$LOG_DIR"

ensure_project_regenerated || die "project regeneration failed"
ensure_spm_resolved "$QVOICE_SCRATCH_PACKAGE_RESOLUTION" "$QVOICE_XCODE_SOURCE_PACKAGES" \
  ui-bundles QwenVoice Release 'platform=macOS,arch=arm64' \
  || die "shared Swift package resolution failed"

if [[ "$MODE" == "macos" || "$MODE" == "all" ]]; then
  # The same settings as scripts/ui_test.sh's macOS build-for-testing.
  build VocelloMacUI "platform=macOS,arch=arm64" "$QVOICE_XCODE_MACOS_OPTIMIZED_DERIVED" \
    CODE_SIGN_STYLE=Manual CODE_SIGN_IDENTITY="-" ONLY_ACTIVE_ARCH=YES ARCHS=arm64 \
    QVOICE_INTERNAL_DIAGNOSTICS_SWIFT_FLAG=-DVOCELLO_INTERNAL_DIAGNOSTICS \
    SWIFT_OPTIMIZATION_LEVEL=-O
fi

if [[ "$MODE" == "ios" || "$MODE" == "all" ]]; then
  # Generic device SDK, never a Simulator, and unsigned: a compile needs no
  # identity and no phone.
  require_ios_xcode_platform || die "iOS compile is blocked by the selected Xcode toolchain"
  build VocelloiOSUI "generic/platform=iOS" "$QVOICE_XCODE_IOS_DERIVED" \
    CODE_SIGNING_ALLOWED=NO
fi

note "UI test bundles compiled"
