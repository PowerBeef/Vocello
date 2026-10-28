#!/usr/bin/env bash
# RF-38: build, package, upload and read back the self-contained farm smoke test
# (Tests/VocelloiOSUITests/VocelloiOSFarmSmokeUITests.swift) on BrowserStack App Automate.
#
#   scripts/farm_smoke.sh package                    build Vocello and its UI-test runner, package both
#   scripts/farm_smoke.sh upload [PACKAGE] [--device "iPhone 15 Pro-27"]... [--force]
#   scripts/farm_smoke.sh results [PACKAGE] [--build ID] [--bundle]
#
# PACKAGE defaults to the newest directory under build/artifacts/ios/farm-smoke. `upload` and
# `results` are maintainer-run from a terminal: they use the maintainer's BrowserStack account,
# from BROWSERSTACK_USERNAME and BROWSERSTACK_ACCESS_KEY or a hidden prompt, and `upload` asks
# before it spends the account's minutes. The upload carries the team's development profile, and
# the test runner its sources' file paths (XCTest assertions embed them). The farm re-signs the app
# without increased-memory-limit, so every result is clone-off exploratory smoke evidence only.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT_DIR/scripts/lib/build_paths.sh"
. "$ROOT_DIR/scripts/lib/build_cache.sh"
. "$ROOT_DIR/scripts/lib/shared.sh"
. "$ROOT_DIR/scripts/lib/dev_signing.sh"

FARM_ROOT="$QVOICE_ARTIFACTS_IOS/farm-smoke"
HELPER="$ROOT_DIR/scripts/lib/farm_smoke.py"

usage() {
  sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

newest_package() {
  local newest
  newest="$(find "$FARM_ROOT" -mindepth 1 -maxdepth 1 -type d -name '[0-9]*' 2>/dev/null | sort | tail -n 1)"
  [[ -n "$newest" ]] || fail "no package under $FARM_ROOT; run scripts/farm_smoke.sh package first"
  printf '%s\n' "$newest"
}

stage=""
cleanup() {
  release_native_lock
  [[ -z "$stage" ]] || rm -rf "$stage"
}

# The Release, internal-diagnostics, optimized build the development iPhone lanes test, for any
# iPhone rather than the paired one, with this Mac's paths mapped out of C sources as every
# shipped iPhone build does. It shares the iOS DerivedData: ui_test.sh's fingerprint marker binds
# the products' digests, so its next lane rebuilds rather than testing these products.
package() {
  local team products log commit dirty=false fingerprint status=0
  team="$(derive_team)" || fail "no Apple Development team found; set QWENVOICE_DEVELOPMENT_TEAM"
  command -v xcodebuild >/dev/null 2>&1 || fail "xcodebuild not found"
  require_ios_xcode_platform || fail "the selected Xcode cannot build for iPhone"
  require_build_free_space device-build || fail "not enough free space for an iPhone build"
  ensure_project_regenerated || fail "project regeneration failed"
  ensure_spm_resolved "$QVOICE_SCRATCH_PACKAGE_RESOLUTION" "$QVOICE_XCODE_SOURCE_PACKAGES" \
    ui-ios VocelloiOSUI Release 'generic/platform=iOS' || fail "shared Swift package resolution failed"
  # The identity of the tree that is about to be built, untracked inputs included.
  commit="$(git -C "$ROOT_DIR" rev-parse HEAD)"
  [[ -z "$(git -C "$ROOT_DIR" status --porcelain)" ]] || dirty=true
  fingerprint="$(python3 "$ROOT_DIR/scripts/tree_fingerprint.py" --root "$ROOT_DIR" --build-inputs)" \
    || fail "could not fingerprint the build inputs"
  qvoice_path_map_settings "$ROOT_DIR"

  mkdir -p "$FARM_ROOT"
  stage="$(mktemp -d "$FARM_ROOT/.stage.XXXXXX")"
  trap cleanup EXIT
  log="$FARM_ROOT/last-build.log"
  products="$QVOICE_XCODE_IOS_DERIVED/Build/Products/Release-iphoneos"
  note "building Vocello and its UI-test runner for any iPhone (log: $log)"
  # Not xcb_run: the lock must also cover copying the products out of the shared DerivedData,
  # which other builds rewrite (the compile-only UI-bundle check leaves them unsigned), and the
  # lock does not nest. -skipPackagePluginValidation as in xcb_run.
  acquire_native_lock "xcodebuild:farm-smoke" || fail "could not take the native build lock"
  xcodebuild build-for-testing \
    -project "$ROOT_DIR/QwenVoice.xcodeproj" -scheme VocelloiOSUI -configuration Release \
    -destination "generic/platform=iOS" -derivedDataPath "$QVOICE_XCODE_IOS_DERIVED" \
    -clonedSourcePackagesDirPath "$QVOICE_XCODE_SOURCE_PACKAGES" \
    -disableAutomaticPackageResolution \
    -onlyUsePackageVersionsFromResolvedFile \
    -skipPackagePluginValidation \
    -allowProvisioningUpdates DEVELOPMENT_TEAM="$team" CODE_SIGN_STYLE=Automatic \
    ARCHS=arm64 ONLY_ACTIVE_ARCH=YES \
    QVOICE_INTERNAL_DIAGNOSTICS_SWIFT_FLAG=-DVOCELLO_INTERNAL_DIAGNOSTICS \
    SWIFT_OPTIMIZATION_LEVEL=-O "${QVOICE_PATH_MAP_SETTINGS[@]}" >"$log" 2>&1 || status=$?
  if (( status == 0 )); then
    if ! ditto "$products/Vocello.app" "$stage/Vocello.app" \
        || ! ditto "$products/VocelloiOSUITests-Runner.app" "$stage/VocelloiOSUITests-Runner.app"; then
      status=1
    fi
  fi
  release_native_lock
  if (( status != 0 )); then
    grep -E ' error: |\*\* TEST BUILD FAILED' "$log" | tail -n 40 >&2 || true
    fail "the farm build failed (see $log)"
  fi

  local bundle details
  for bundle in "$stage/Vocello.app" "$stage/VocelloiOSUITests-Runner.app"; do
    codesign --verify --strict --deep "$bundle" \
      || fail "$(basename "$bundle") is not validly signed"
    # Captured first: grep -q closing a pipe early would fail the pipeline under pipefail.
    details="$(codesign -dvv "$bundle" 2>&1)" || fail "cannot read $(basename "$bundle")'s signature"
    grep -q '^Authority=Apple Development' <<<"$details" \
      || fail "$(basename "$bundle") is not signed with an Apple Development identity"
  done
  python3 "$HELPER" package --products "$stage" --root "$FARM_ROOT" --commit "$commit" \
    --dirty "$dirty" --xcode "$(xcodebuild -version | head -n 1)" --fingerprint "$fingerprint"
}

command="${1:-}"
[[ $# -eq 0 ]] || shift
case "$command" in
  package)
    [[ $# -eq 0 ]] || fail "package takes no arguments"
    package
    ;;
  upload|results)
    if [[ $# -gt 0 && "$1" != -* ]]; then
      target="$1"
      shift
    else
      target="$(newest_package)"
    fi
    exec python3 "$HELPER" "$command" "$target" "$@"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
