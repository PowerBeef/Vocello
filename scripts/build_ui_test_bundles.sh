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

MODE="${1:-all}"
case "$MODE" in
  macos|ios|all) ;;
  *) die "usage: ./scripts/build_ui_test_bundles.sh [macos|ios|all]" ;;
esac

build() {
  local scheme="$1" destination="$2" derived="$3"
  shift 3
  note "compiling $scheme (build only, never run)"
  # `build-for-testing`, not `test`: this produces the bundle and stops. The
  # runner is never launched, no app is installed, no device is touched.
  xcodebuild build-for-testing \
    -project "$ROOT_DIR/QwenVoice.xcodeproj" \
    -scheme "$scheme" \
    -configuration Release \
    -destination "$destination" \
    -derivedDataPath "$derived" \
    -skipPackagePluginValidation \
    "$@" >"$LOG_DIR/$scheme.log" 2>&1 \
    || die "$scheme failed to compile (see build/artifacts/ui-bundles/$scheme.log)"
}

LOG_DIR="$ROOT_DIR/build/artifacts/ui-bundles"
mkdir -p "$LOG_DIR"

if [[ "$MODE" == "macos" || "$MODE" == "all" ]]; then
  build VocelloMacUI "platform=macOS,arch=arm64" "$ROOT_DIR/build/cache/xcode/macos"
fi

if [[ "$MODE" == "ios" || "$MODE" == "all" ]]; then
  # Generic device SDK, never a Simulator, and unsigned: a compile needs no
  # identity and no phone.
  build VocelloiOSUI "generic/platform=iOS" "$ROOT_DIR/build/cache/xcode/ios-device" \
    CODE_SIGNING_ALLOWED=NO
fi

note "UI test bundles compiled"
