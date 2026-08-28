#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-all}"
INCREMENTAL=0
if [[ "${2:-}" == "--incremental" ]]; then
  INCREMENTAL=1
elif [[ -n "${2:-}" ]]; then
  echo "usage: ./scripts/build_foundation_targets.sh [macos|ios|all] [--incremental]" >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_FILE="$ROOT_DIR/QwenVoice.xcodeproj"
MATRIX_PATH="$ROOT_DIR/config/apple-platform-capability-matrix.json"
. "$ROOT_DIR/scripts/lib/shared.sh"
# shellcheck source=lib/build_paths.sh
. "$ROOT_DIR/scripts/lib/build_paths.sh"
# shellcheck source=lib/build_cache.sh
. "$ROOT_DIR/scripts/lib/build_cache.sh"
FOUNDATION_BUILD_ROOT="$QVOICE_ARTIFACTS_FOUNDATION"
FOUNDATION_DERIVED_ROOT="$QVOICE_SCRATCH_FOUNDATION"
SOURCE_PACKAGES_DIR="$QVOICE_XCODE_SOURCE_PACKAGES"

usage() {
  cat >&2 <<'EOF'
usage: ./scripts/build_foundation_targets.sh [macos|ios|all] [--incremental]

  --incremental  Local iOS checkpoint only: reuse the governed ios-device
                 DerivedData and Release optimization settings. CI/default
                 verification retains the disposable clean foundation tree.
EOF
}

prepare_paths() {
  mkdir -p "$FOUNDATION_BUILD_ROOT" "$FOUNDATION_DERIVED_ROOT"
}

# The foundation build exists only to prove the targets compile. Its DerivedData
# trees are large (1-2 GB each for the MLX stack) and serve no purpose after the
# pass/fail is known, so remove them on exit (success OR failure). The small
# .xcresult bundles + summary.json are kept for inspection. This enforces the
# "single build at a time" policy: no second build tree lingers on disk.
cleanup_foundation_derived_data() {
  (( INCREMENTAL == 0 )) || return 0
  rm -rf "$FOUNDATION_DERIVED_ROOT" 2>/dev/null || true
}

write_summary() {
  local status="$1"
  local summary_path="$FOUNDATION_BUILD_ROOT/summary.json"
  python3 - "$summary_path" "$MODE" "$status" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

summary_path = Path(sys.argv[1])
summary = {
    "mode": sys.argv[2],
    "status": sys.argv[3],
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "result_bundles": {
        "macos": "qwenvoice-macos-build.xcresult",
        "ios": "vocello-ios-generic-build.xcresult",
        "iosLogic": "vocello-ios-logic-generic-build.xcresult",
    },
}
summary_path.write_text(json.dumps(summary, indent=2) + "\n")
PY
}

run_foundation_build() {
  local label="$1"
  local log_path="$2"
  shift 2
  rm -f "$log_path"
  echo "Building $label (full log: ${log_path#$ROOT_DIR/})"
  local status=0
  if xcb_run "$@" >"$log_path" 2>&1; then
    echo "Built $label"
    return 0
  else
    status=$?
  fi
  echo "error: $label failed; final log follows" >&2
  tail -n 120 "$log_path" >&2 || true
  return "$status"
}

build_macos() {
  local derived_data_path="$FOUNDATION_DERIVED_ROOT/macos"
  local result_bundle_path="$FOUNDATION_BUILD_ROOT/qwenvoice-macos-build.xcresult"
  local log_path="$FOUNDATION_BUILD_ROOT/qwenvoice-macos-build.log"

  ensure_spm_resolved "$QVOICE_SCRATCH_PACKAGE_RESOLUTION" "$SOURCE_PACKAGES_DIR" \
    foundation-macos QwenVoice Release 'platform=macOS,arch=arm64'
  rm -rf "$derived_data_path" "$result_bundle_path"

  run_foundation_build "macOS foundation target" "$log_path" \
    -project "$PROJECT_FILE" \
    -scheme QwenVoice \
    -configuration Release \
    -destination 'platform=macOS,arch=arm64' \
    -derivedDataPath "$derived_data_path" \
    -clonedSourcePackagesDirPath "$SOURCE_PACKAGES_DIR" \
    -disableAutomaticPackageResolution \
    -onlyUsePackageVersionsFromResolvedFile \
    -resultBundlePath "$result_bundle_path" \
    -resultBundleVersion 3 \
    ARCHS=arm64 \
    ONLY_ACTIVE_ARCH=YES \
    CODE_SIGN_STYLE=Manual \
    CODE_SIGN_IDENTITY="-" \
    CODE_SIGN_ALLOW_ENTITLEMENTS_MODIFICATION=YES \
    SWIFT_OPTIMIZATION_LEVEL="-Onone" \
    SWIFT_COMPILATION_MODE="incremental" \
    build
  write_build_provenance "$FOUNDATION_BUILD_ROOT/last-build.json" \
    "scripts/build_foundation_targets.sh macos" QwenVoice Release \
    "platform=macOS,arch=arm64" arm64 Onone ad-hoc \
    "$derived_data_path" "$SOURCE_PACKAGES_DIR"
}

build_ios() {
  local derived_data_path="$FOUNDATION_DERIVED_ROOT/ios"
  local result_bundle_path="$FOUNDATION_BUILD_ROOT/vocello-ios-generic-build.xcresult"
  local logic_result_bundle_path="$FOUNDATION_BUILD_ROOT/vocello-ios-logic-generic-build.xcresult"
  local app_log_path="$FOUNDATION_BUILD_ROOT/vocello-ios-generic-build.log"
  local logic_log_path="$FOUNDATION_BUILD_ROOT/vocello-ios-logic-generic-build.log"
  local provenance_optimization="Onone"

  local -a swift_settings=(
    SWIFT_OPTIMIZATION_LEVEL=-Onone
    SWIFT_COMPILATION_MODE=incremental
  )
  if (( INCREMENTAL == 1 )); then
    derived_data_path="$QVOICE_XCODE_IOS_DERIVED"
    provenance_optimization="O"
    # Match physical-device UI lanes so package products remain reusable. The
    # internal diagnostics conditions are target-scoped and may rebuild only
    # owned QwenVoiceCore when the subsequent XCUITest lane needs them.
    swift_settings=(SWIFT_OPTIMIZATION_LEVEL=-O)
  fi

  ensure_spm_resolved "$QVOICE_SCRATCH_PACKAGE_RESOLUTION" "$SOURCE_PACKAGES_DIR" \
    foundation-ios VocelloiOS Release 'generic/platform=iOS'
  if (( INCREMENTAL == 0 )); then
    rm -rf "$derived_data_path"
  fi
  rm -rf "$result_bundle_path" "$logic_result_bundle_path"

  run_foundation_build "iOS app target" "$app_log_path" \
    -project "$PROJECT_FILE" \
    -scheme VocelloiOS \
    -configuration Release \
    -destination 'generic/platform=iOS' \
    -derivedDataPath "$derived_data_path" \
    -clonedSourcePackagesDirPath "$SOURCE_PACKAGES_DIR" \
    -disableAutomaticPackageResolution \
    -onlyUsePackageVersionsFromResolvedFile \
    -resultBundlePath "$result_bundle_path" \
    -resultBundleVersion 3 \
    CODE_SIGNING_ALLOWED=NO \
    ARCHS=arm64 \
    ONLY_ACTIVE_ARCH=YES \
    "${swift_settings[@]}" \
    build

  # Compile the standalone iOS policy-test bundle for the physical-device SDK.
  # `build` deliberately does not execute XCTest and does not require a phone.
  run_foundation_build "iOS logic-test target" "$logic_log_path" \
    -project "$PROJECT_FILE" \
    -scheme VocelloiOSLogic \
    -configuration Release \
    -destination 'generic/platform=iOS' \
    -derivedDataPath "$derived_data_path" \
    -clonedSourcePackagesDirPath "$SOURCE_PACKAGES_DIR" \
    -disableAutomaticPackageResolution \
    -onlyUsePackageVersionsFromResolvedFile \
    -resultBundlePath "$logic_result_bundle_path" \
    -resultBundleVersion 3 \
    CODE_SIGNING_ALLOWED=NO \
    ARCHS=arm64 \
    ONLY_ACTIVE_ARCH=YES \
    "${swift_settings[@]}" \
    build
  write_build_provenance "$FOUNDATION_BUILD_ROOT/last-build.json" \
    "scripts/build_foundation_targets.sh ios" VocelloiOS Release \
    "generic/platform=iOS" arm64 "$provenance_optimization" disabled \
    "$derived_data_path" "$SOURCE_PACKAGES_DIR"
  write_build_provenance "$FOUNDATION_BUILD_ROOT/ios-logic-last-build.json" \
    "scripts/build_foundation_targets.sh ios logic" VocelloiOSLogic Release \
    "generic/platform=iOS" arm64 "$provenance_optimization" disabled \
    "$derived_data_path" "$SOURCE_PACKAGES_DIR"
}

case "$MODE" in
  macos|ios|all) ;;
  *)
    usage
    exit 2
    ;;
esac

if (( INCREMENTAL == 1 )) && [[ "$MODE" != "ios" ]]; then
  echo "error: --incremental is supported only for the local iOS checkpoint" >&2
  exit 2
fi

if [[ "$MODE" == "ios" || "$MODE" == "all" ]]; then
  require_ios_xcode_platform \
    || { echo "error: iOS foundation compile blocked by the selected Xcode toolchain" >&2; exit 1; }
fi
require_build_free_space foundation-compile \
  || { echo "error: foundation compile storage preflight failed" >&2; exit 1; }
prepare_paths
trap cleanup_foundation_derived_data EXIT
ensure_project_regenerated

case "$MODE" in
  macos) build_macos ;;
  ios) build_ios ;;
  all)
    build_macos
    build_ios
    ;;
esac

write_summary "passed"
