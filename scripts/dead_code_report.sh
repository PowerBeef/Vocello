#!/usr/bin/env bash
# Report-only dead-code scan (workflow audit P3-4, DW-04): no finding fails it.
#
# Compiles the macOS app (QwenVoice), the CLI (VocelloCLI) and the iOS app
# (VocelloiOS, generic device SDK, unsigned) into one scratch DerivedData root
# with the index store kept, then runs the pinned Periphery
# (config/toolchain.json artifactPins.periphery) over that index for all three
# schemes, so code that only one product uses is not reported as unused. The
# results are limited to owned code (Sources/ and Packages/VocelloQwen3Core/)
# and written to build/artifacts/dead-code/periphery.json, which
# scripts/ci/periphery_report.py summarizes for the nightly `dead-code` job. No
# finding is a verdict: Periphery cannot see a use through reflection, a string
# lookup or a target outside these schemes.
#
#   scripts/dead_code_report.sh         compile, scan and write the JSON
#   scripts/dead_code_report.sh help    this text
#
# It exits non-zero only when a compile or Periphery fails. The compiles are
# Release at -Onone, incremental, with the internal-diagnostics condition on, so
# code that only those builds use is indexed as used. Periphery must be the
# pinned version on PATH: ./scripts/install_pinned_tools.sh periphery. The
# scratch root (build/scratch/derived-data/dead-code) is removed on exit,
# whatever the result; the JSON and the compile and scan logs stay under
# build/artifacts/dead-code.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USAGE="usage: ./scripts/dead_code_report.sh [help]"

if (( $# > 0 )); then
  case "$1" in
    help|-h|--help)
      sed -n '2,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
      exit 0
      ;;
  esac
  echo "$USAGE" >&2
  exit 2
fi

# shellcheck source=lib/shared.sh
. "$ROOT_DIR/scripts/lib/shared.sh"
# shellcheck source=lib/build_paths.sh
. "$ROOT_DIR/scripts/lib/build_paths.sh"
# shellcheck source=lib/build_cache.sh
. "$ROOT_DIR/scripts/lib/build_cache.sh"

DERIVED_ROOT="$QVOICE_SCRATCH_DEAD_CODE"
OUTPUT_DIR="$QVOICE_ARTIFACTS_DEAD_CODE"
RESULTS="$OUTPUT_DIR/periphery.json"
SCAN_LOG="$OUTPUT_DIR/periphery.log"
SOURCE_PACKAGES_DIR="$QVOICE_XCODE_SOURCE_PACKAGES"
MACOS_DESTINATION='platform=macOS,arch=arm64'
IOS_DESTINATION='generic/platform=iOS'
SCHEMES=(QwenVoice VocelloCLI VocelloiOS)
# Owned code, as globs relative to the repository root (Periphery's --project-root).
OWNED_GLOBS=('Sources/**/*.swift' 'Packages/VocelloQwen3Core/**/*.swift')
# Every compile passes these. A global -Onone keeps the cold compiles short;
# QVOICE_INTERNAL_DIAGNOSTICS_SWIFT_FLAG reaches only QwenVoiceCore.
COMMON_SETTINGS=(
  ARCHS=arm64
  ONLY_ACTIVE_ARCH=YES
  SWIFT_OPTIMIZATION_LEVEL=-Onone
  SWIFT_COMPILATION_MODE=incremental
  QVOICE_INTERNAL_DIAGNOSTICS_SWIFT_FLAG=-DVOCELLO_INTERNAL_DIAGNOSTICS
  COMPILER_INDEX_STORE_ENABLE=YES
)
# The foundation compile's signing: ad hoc on macOS, none for the device SDK.
MACOS_SIGNING=(CODE_SIGN_STYLE=Manual CODE_SIGN_IDENTITY="-" CODE_SIGN_ALLOW_ENTITLEMENTS_MODIFICATION=YES)
IOS_SIGNING=(CODE_SIGNING_ALLOWED=NO)
PERIPHERY_VERSION=""

require_pinned_periphery() {
  local pinned installed=""
  pinned="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["artifactPins"]["periphery"]["version"])' \
    "$ROOT_DIR/config/toolchain.json")" || die "cannot read the Periphery pin from config/toolchain.json"
  command -v periphery >/dev/null 2>&1 \
    || die "periphery is not on PATH; install the pinned $pinned with ./scripts/install_pinned_tools.sh periphery"
  installed="$(periphery version 2>/dev/null | head -n 1 | tr -d '[:space:]')" || true
  [[ "$installed" == "$pinned" ]] \
    || die "periphery ${installed:-of unknown version} is not the pinned $pinned; run ./scripts/install_pinned_tools.sh periphery"
  PERIPHERY_VERSION="$installed"
}

cleanup_derived_data() {
  rm -rf "$DERIVED_ROOT" 2>/dev/null || true
}

compile() {
  local scheme="$1" destination="$2"
  shift 2
  local log="$OUTPUT_DIR/$scheme-build.log"
  note "compiling $scheme for $destination with the index store on (log: ${log#"$ROOT_DIR"/})"
  # QVOICE_INDEX_STORE=1 keeps xcb_run from turning the index store off on CI;
  # xcb_run holds the host-wide native lock for the compile.
  QVOICE_INDEX_STORE=1 QVOICE_NATIVE_LOCK_LABEL="dead-code:$scheme" xcb_run \
    -project "$ROOT_DIR/QwenVoice.xcodeproj" \
    -scheme "$scheme" \
    -configuration Release \
    -destination "$destination" \
    -derivedDataPath "$DERIVED_ROOT" \
    -clonedSourcePackagesDirPath "$SOURCE_PACKAGES_DIR" \
    -disableAutomaticPackageResolution \
    -onlyUsePackageVersionsFromResolvedFile \
    "${COMMON_SETTINGS[@]}" \
    "$@" \
    build >"$log" 2>&1 \
    || { tail -n 120 "$log" >&2 || true
         die "$scheme failed to compile (full log: ${log#"$ROOT_DIR"/})"; }
}

scan() {
  local index_store="$DERIVED_ROOT/Index.noindex/DataStore"
  [[ -d "$index_store" ]] || die "the compiles left no index store at ${index_store#"$ROOT_DIR"/}"
  local -a arguments=(scan --project "$ROOT_DIR/QwenVoice.xcodeproj" --project-root "$ROOT_DIR")
  local scheme glob
  for scheme in "${SCHEMES[@]}"; do
    arguments+=(--schemes "$scheme")
  done
  for glob in "${OWNED_GLOBS[@]}"; do
    arguments+=(--report-include "$glob")
  done
  # --index-store-path implies --skip-build: Periphery reads the index and runs
  # only `xcodebuild -version`.
  arguments+=(
    --index-store-path "$index_store" --skip-build --skip-schemes-validation --exclude-tests
    --retain-objc-accessible --retain-codable-properties --retain-swift-ui-previews
    --disable-update-check --relative-results --format json --quiet --write-results "$RESULTS"
  )
  note "scanning ${SCHEMES[*]} with periphery $PERIPHERY_VERSION (log: ${SCAN_LOG#"$ROOT_DIR"/})"
  # Periphery prints the results it writes; only its diagnostics go to the log.
  if ! (cd "$ROOT_DIR" && periphery "${arguments[@]}") >/dev/null 2>"$SCAN_LOG"; then
    cat "$SCAN_LOG" >&2 || true
    die "periphery failed (log: ${SCAN_LOG#"$ROOT_DIR"/})"
  fi
  [[ -s "$RESULTS" ]] || die "periphery wrote no results to ${RESULTS#"$ROOT_DIR"/}"
}

require_pinned_periphery
require_ios_xcode_platform || die "the iOS compile is blocked by the selected Xcode toolchain"
require_build_free_space dead-code-scan || die "dead-code scan storage preflight failed"
mkdir -p "$OUTPUT_DIR"
rm -f "$RESULTS" "$SCAN_LOG" "$OUTPUT_DIR"/*-build.log
rm -rf "$DERIVED_ROOT"
trap cleanup_derived_data EXIT
ensure_project_regenerated || die "project regeneration failed"
ensure_spm_resolved "$QVOICE_SCRATCH_PACKAGE_RESOLUTION" "$SOURCE_PACKAGES_DIR" \
  dead-code-macos QwenVoice Release "$MACOS_DESTINATION" \
  || die "shared Swift package resolution failed"
ensure_spm_resolved "$QVOICE_SCRATCH_PACKAGE_RESOLUTION" "$SOURCE_PACKAGES_DIR" \
  dead-code-ios VocelloiOS Release "$IOS_DESTINATION" \
  || die "shared Swift package resolution failed"

compile QwenVoice "$MACOS_DESTINATION" "${MACOS_SIGNING[@]}"
compile VocelloCLI "$MACOS_DESTINATION" "${MACOS_SIGNING[@]}"
compile VocelloiOS "$IOS_DESTINATION" "${IOS_SIGNING[@]}"
scan
note "dead-code results: ${RESULTS#"$ROOT_DIR"/} (summary: python3 scripts/ci/periphery_report.py ${RESULTS#"$ROOT_DIR"/})"
