#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
export ROOT_DIR="$PROJECT_DIR"
# shellcheck source=lib/build_paths.sh
. "$SCRIPT_DIR/lib/build_paths.sh"
PROJECT_FILE="$PROJECT_DIR/QwenVoice.xcodeproj"
SCHEME="QwenVoice"
CONFIGURATION="Release"
# Release compilation is deliberately isolated from the incremental developer
# cache. Only the signed app, DMG, and metadata live under dist/macos.
BUILD_DIR="$QVOICE_DIST_MACOS"
SOURCE_PACKAGES_DIR="$QVOICE_XCODE_SOURCE_PACKAGES"
DERIVED_DATA_PATH="$QVOICE_SCRATCH_RELEASE_MACOS"
RELEASE_ARTIFACT_DIR="$QVOICE_ARTIFACTS_MACOS/release"
BUILD_RESULT_BUNDLE_PATH="$RELEASE_ARTIFACT_DIR/macos-release-build.xcresult"
DEFAULT_OUTPUT_NAME="Vocello-macos26"
TOTAL_START="$(date +%s)"
export BUILD_CACHE_DIR="$SOURCE_PACKAGES_DIR/.qwenvoice-cache"

# shellcheck source=lib/build_cache.sh
. "$SCRIPT_DIR/lib/build_cache.sh"
# shellcheck source=lib/release_signing.sh
. "$SCRIPT_DIR/lib/release_signing.sh"

SKIP_BUILD=false
OUTPUT_NAME="$DEFAULT_OUTPUT_NAME"
PREFLIGHT="none"
SIGNING_MODE="${QWENVOICE_SIGNING_MODE:-ad-hoc}"
SIGNING_IDENTITY="${QWENVOICE_SIGNING_IDENTITY:-}"
# The "Developer ID Installer: … (TEAMID)" identity that signs the CLI installer package
# (productsign) in developer-id mode; release.yml resolves it from its keychain as it does
# the app identity.
INSTALLER_IDENTITY="${APPLE_DEV_ID_INSTALLER:-}"
CODESIGN_KEYCHAIN="${QWENVOICE_CODESIGN_KEYCHAIN:-}"
RELEASE_TEAM_ID="${QWENVOICE_DEVELOPMENT_TEAM:-${APPLE_TEAM_ID:-}}"
# Notarization is opt-in. Either pass --notarize or set QWENVOICE_NOTARIZE=1.
# Only valid with --signing-mode developer-id and the opt-in API key flow below.
NOTARIZE="${QWENVOICE_NOTARIZE:-0}"

release_fail() {
    echo "Error: $*" >&2
    exit 1
}

usage() {
    cat >&2 <<EOF
Usage: $0 [--skip-build] [--output-name <basename>] [--preflight none|full] [--signing-mode ad-hoc|developer-id] [--signing-identity <identity>] [--installer-identity <identity>] [--codesign-keychain <path>] [--notarize]

Build the macOS app and CLI, sign and package separate DMGs and the CLI installer
package (<basename>-cli.pkg), and emit release metadata.

--signing-mode developer-id needs --signing-identity (or QWENVOICE_SIGNING_IDENTITY), a
"Developer ID Application: … (TEAMID)" identity, and --installer-identity (or
APPLE_DEV_ID_INSTALLER), the "Developer ID Installer: … (TEAMID)" identity that signs
the CLI installer package. Both belong to the release Team ID (APPLE_TEAM_ID or
QWENVOICE_DEVELOPMENT_TEAM). Ad-hoc mode leaves the installer package unsigned.

--notarize submits both DMGs and the installer package to Apple's notarization service
via the App Store Connect API key flow, then staples each ticket. Requires
--signing-mode developer-id and these env vars:
  APPLE_API_KEY_PATH   - path to the AuthKey_XXXXXX.p8 file (required)
  APPLE_API_KEY_ID     - the 10-char key ID from the .p8 filename (required)
  APPLE_API_ISSUER_ID  - the App Store Connect "Issuer ID" UUID. REQUIRED
                         for Team API keys; omit (or leave empty) for
                         Individual API keys (notarytool rejects
                         --issuer with anything non-UUID).
Notarization typically takes 1-5 minutes of wall-clock per artifact.
EOF
    exit 1
}

step_time() {
    local start="$1"
    local end
    end="$(date +%s)"
    echo "$((end - start))s"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --output-name)
            [ $# -ge 2 ] || usage
            OUTPUT_NAME="$2"
            shift 2
            ;;
        --preflight)
            [ $# -ge 2 ] || usage
            PREFLIGHT="$2"
            shift 2
            ;;
        --signing-mode)
            [ $# -ge 2 ] || usage
            SIGNING_MODE="$2"
            shift 2
            ;;
        --signing-identity)
            [ $# -ge 2 ] || usage
            SIGNING_IDENTITY="$2"
            shift 2
            ;;
        --installer-identity)
            [ $# -ge 2 ] || usage
            INSTALLER_IDENTITY="$2"
            shift 2
            ;;
        --codesign-keychain)
            [ $# -ge 2 ] || usage
            CODESIGN_KEYCHAIN="$2"
            shift 2
            ;;
        --notarize)
            NOTARIZE=1
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            usage
            ;;
    esac
done

if [[ "$OUTPUT_NAME" == *"/"* ]]; then
    release_fail "--output-name must not contain path separators"
fi

case "$SIGNING_MODE" in
    ad-hoc)
        ACTIVE_SIGNING_IDENTITY="-"
        ;;
    developer-id)
        [ -n "$SIGNING_IDENTITY" ] || release_fail "--signing-identity is required for developer-id signing"
        [ -n "$RELEASE_TEAM_ID" ] || release_fail "APPLE_TEAM_ID or QWENVOICE_DEVELOPMENT_TEAM is required for developer-id signing"
        [ -n "$INSTALLER_IDENTITY" ] \
            || release_fail "--installer-identity (or APPLE_DEV_ID_INSTALLER) is required for developer-id signing: the CLI installer package is signed with a Developer ID Installer identity"
        # productsign takes any identity whose name contains the argument; only the full
        # Developer ID Installer name of the release team may sign the package.
        case "$INSTALLER_IDENTITY" in
            "Developer ID Installer: "*" ($RELEASE_TEAM_ID)") ;;
            *) release_fail "the installer identity must be a 'Developer ID Installer: … ($RELEASE_TEAM_ID)' identity of the release Team ID" ;;
        esac
        ACTIVE_SIGNING_IDENTITY="$SIGNING_IDENTITY"
        ;;
    *)
        release_fail "Unsupported --signing-mode '$SIGNING_MODE' (expected ad-hoc or developer-id)"
        ;;
esac

if [ "$NOTARIZE" = "1" ]; then
    [ "$SIGNING_MODE" = "developer-id" ] || release_fail "--notarize requires --signing-mode developer-id (ad-hoc signatures are not notarizable)"
    [ -n "${APPLE_API_KEY_PATH:-}" ] || release_fail "APPLE_API_KEY_PATH env var is required for --notarize (path to the AuthKey_*.p8 file)"
    [ -f "${APPLE_API_KEY_PATH:-/dev/null}" ] || release_fail "APPLE_API_KEY_PATH points to a missing file: $APPLE_API_KEY_PATH"
    [ -n "${APPLE_API_KEY_ID:-}" ] || release_fail "APPLE_API_KEY_ID env var is required for --notarize"
    # APPLE_API_ISSUER_ID is required for Team API keys but MUST be
    # omitted for Individual API keys. We pass --issuer only when the
    # value looks like a real UUID; otherwise notarytool runs without
    # it. notarytool itself will fail with a clear error if the key
    # actually needed an issuer.
fi

case "$PREFLIGHT" in
    none|full)
        ;;
    *)
        release_fail "Unsupported --preflight '$PREFLIGHT' (expected none or full)"
        ;;
esac

if [ -n "$CODESIGN_KEYCHAIN" ] && [ ! -f "$CODESIGN_KEYCHAIN" ]; then
    release_fail "--codesign-keychain path does not exist: $CODESIGN_KEYCHAIN"
fi

require_build_free_space release \
    || release_fail "release storage preflight failed before readiness or signing work"

# This gate is unconditional: signing, notarization, and artifact creation never begin without
# deterministic build/test/crash checks. Model-dependent telemetry and XCUITest remain explicit
# QA lanes and are never packaging prerequisites.
"$SCRIPT_DIR/macos_test.sh" release-readiness

run_codesign() {
    local target="$1"
    shift

    local args=(codesign --force --sign "$ACTIVE_SIGNING_IDENTITY")
    if [ -n "$CODESIGN_KEYCHAIN" ]; then
        args+=(--keychain "$CODESIGN_KEYCHAIN")
    fi
    if [ "$SIGNING_MODE" = "developer-id" ]; then
        args+=(--timestamp)
    fi
    args+=("$@" "$target")
    "${args[@]}"
}

read_build_setting() {
    local file_path="$1"
    local key="$2"
    python3 - "$file_path" "$key" <<'PY'
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text()
key = sys.argv[2]
for line in text.splitlines():
    if " = " not in line:
        continue
    lhs, rhs = line.split(" = ", 1)
    if lhs.strip() == key:
        print(rhs.strip())
        break
PY
}

resolve_build_metadata() {
    local settings_path="$1"
    BUILT_PRODUCTS_DIR="$(read_build_setting "$settings_path" BUILT_PRODUCTS_DIR)"
    WRAPPER_NAME="$(read_build_setting "$settings_path" WRAPPER_NAME)"
    EXECUTABLE_NAME="$(read_build_setting "$settings_path" EXECUTABLE_NAME)"
    MARKETING_VERSION="$(read_build_setting "$settings_path" MARKETING_VERSION)"
    CURRENT_PROJECT_VERSION="$(read_build_setting "$settings_path" CURRENT_PROJECT_VERSION)"

    [ -n "$BUILT_PRODUCTS_DIR" ] || release_fail "Could not determine BUILT_PRODUCTS_DIR"
    [ -n "$WRAPPER_NAME" ] || release_fail "Could not determine WRAPPER_NAME"
    [ -n "$EXECUTABLE_NAME" ] || release_fail "Could not determine EXECUTABLE_NAME"
}

echo "=== Vocello: macOS Release Build ==="
echo ""
echo "  scheme: $SCHEME"
echo "  output DMG: $OUTPUT_NAME.dmg"
echo "  CLI installer package: $OUTPUT_NAME-cli.pkg"
echo "  preflight: $PREFLIGHT"
echo "  signing: $SIGNING_MODE"
if [ "$SIGNING_MODE" = "developer-id" ]; then
    echo "  signing identity: $SIGNING_IDENTITY"
    echo "  installer identity: $INSTALLER_IDENTITY"
    echo "  team id: $RELEASE_TEAM_ID"
fi
echo "  notarize: $([ "$NOTARIZE" = "1" ] && echo "yes" || echo "no")"
echo ""

mkdir -p "$BUILD_DIR" "$SOURCE_PACKAGES_DIR" "$RELEASE_ARTIFACT_DIR"
SHOW_BUILD_SETTINGS_LOG="$RELEASE_ARTIFACT_DIR/release-build-settings.log"

STEP_START="$(date +%s)"
echo "[1/8] Ensuring Xcode project is up to date..."
ensure_project_regenerated
echo "[1/8] Project up to date — done ($(step_time "$STEP_START"))"
echo ""

if [ "$PREFLIGHT" = "full" ]; then
    STEP_START="$(date +%s)"
    echo "[preflight] Running project input and foundation build gates..."
    "$SCRIPT_DIR/check_project_inputs.sh"
    "$SCRIPT_DIR/build_foundation_targets.sh" macos
    "$SCRIPT_DIR/build_foundation_targets.sh" ios
    echo "[preflight] Full preflight — done ($(step_time "$STEP_START"))"
    echo ""
fi

STEP_START="$(date +%s)"
echo "[2/8] Ensuring Swift packages are resolved..."
ensure_spm_resolved "$QVOICE_SCRATCH_PACKAGE_RESOLUTION" "$SOURCE_PACKAGES_DIR" \
    release "$SCHEME" "$CONFIGURATION" 'platform=macOS,arch=arm64'
echo "[2/8] Swift packages ready — done ($(step_time "$STEP_START"))"
echo ""

STEP_START="$(date +%s)"
if $SKIP_BUILD; then
    echo "[3/8] Build Release — skipped"
else
    echo "[3/8] Building macOS Release app..."
    require_build_free_space release \
        || release_fail "release storage preflight failed immediately before isolated build"
    rm -f "$RELEASE_ARTIFACT_DIR/xcodebuild-release.log"
    rm -rf "$DERIVED_DATA_PATH"
    rm -rf "$BUILD_RESULT_BUNDLE_PATH"
    set +e
    xcb_run -project "$PROJECT_FILE" \
        -scheme "$SCHEME" \
        -configuration "$CONFIGURATION" \
        -destination "platform=macOS,arch=arm64" \
        -clonedSourcePackagesDirPath "$SOURCE_PACKAGES_DIR" \
        -disableAutomaticPackageResolution \
        -onlyUsePackageVersionsFromResolvedFile \
        -derivedDataPath "$DERIVED_DATA_PATH" \
        -resultBundlePath "$BUILD_RESULT_BUNDLE_PATH" \
        -resultBundleVersion 3 \
        CODE_SIGN_STYLE=Manual \
        CODE_SIGN_IDENTITY="-" \
        QWENVOICE_DEVELOPMENT_TEAM="$RELEASE_TEAM_ID" \
        CODE_SIGN_ALLOW_ENTITLEMENTS_MODIFICATION=YES \
        ONLY_ACTIVE_ARCH=YES \
        ARCHS=arm64 \
        SWIFT_OPTIMIZATION_LEVEL="-O" \
        SWIFT_COMPILATION_MODE="wholemodule" \
        build 2>&1 | tee "$RELEASE_ARTIFACT_DIR/xcodebuild-release.log"
    XCODEBUILD_STATUS=${PIPESTATUS[0]}
    set -e
    if [ "$XCODEBUILD_STATUS" -ne 0 ]; then
        release_fail "xcodebuild failed (see $RELEASE_ARTIFACT_DIR/xcodebuild-release.log)"
    fi
    write_build_provenance "$DERIVED_DATA_PATH/last-build.json" \
        "scripts/release.sh" "$SCHEME" "$CONFIGURATION" \
        "platform=macOS,arch=arm64" arm64 O ad-hoc \
        "$DERIVED_DATA_PATH" "$SOURCE_PACKAGES_DIR"
    write_build_provenance "$RELEASE_ARTIFACT_DIR/last-build.json" \
        "scripts/release.sh" "$SCHEME" "$CONFIGURATION" \
        "platform=macOS,arch=arm64" arm64 O ad-hoc \
        "$DERIVED_DATA_PATH" "$SOURCE_PACKAGES_DIR"
fi
echo "[3/8] Build Release — done ($(step_time "$STEP_START"))"
echo ""

# Use the same isolated Release products and optimization as the app. The public
# CLI must not inherit developer-only runtime capabilities from build.sh.
if ! $SKIP_BUILD; then
    xcb_run -project "$PROJECT_FILE" -scheme VocelloCLI \
        -configuration "$CONFIGURATION" -destination "platform=macOS,arch=arm64" \
        -clonedSourcePackagesDirPath "$SOURCE_PACKAGES_DIR" \
        -disableAutomaticPackageResolution -onlyUsePackageVersionsFromResolvedFile \
        -derivedDataPath "$DERIVED_DATA_PATH" \
        CODE_SIGN_STYLE=Manual CODE_SIGN_IDENTITY="-" ONLY_ACTIVE_ARCH=YES ARCHS=arm64 \
        QVOICE_INTERNAL_DIAGNOSTICS_SWIFT_FLAG="" \
        SWIFT_OPTIMIZATION_LEVEL="-O" SWIFT_COMPILATION_MODE="wholemodule" GCC_OPTIMIZATION_LEVEL="s" \
        build 2>&1 | tee "$RELEASE_ARTIFACT_DIR/xcodebuild-cli-release.log"
fi

STEP_START="$(date +%s)"
echo "[4/8] Resolving and copying built app..."
xcb_run -project "$PROJECT_FILE" \
    -scheme "$SCHEME" \
    -configuration "$CONFIGURATION" \
    -destination "platform=macOS,arch=arm64" \
    -clonedSourcePackagesDirPath "$SOURCE_PACKAGES_DIR" \
    -disableAutomaticPackageResolution \
    -onlyUsePackageVersionsFromResolvedFile \
    -derivedDataPath "$DERIVED_DATA_PATH" \
    QWENVOICE_DEVELOPMENT_TEAM="$RELEASE_TEAM_ID" \
    -showBuildSettings > "$SHOW_BUILD_SETTINGS_LOG"
resolve_build_metadata "$SHOW_BUILD_SETTINGS_LOG"
COMMIT_SHA="$(git -C "$PROJECT_DIR" rev-parse HEAD)"
CLI_STAGE_ROOT="$(mktemp -d "$BUILD_DIR/cli-stage.XXXXXX")"
trap 'rm -rf "$CLI_STAGE_ROOT"' EXIT
CLI_PATH="$CLI_STAGE_ROOT/Vocello CLI"
python3 "$SCRIPT_DIR/cli_package.py" stage --products "$BUILT_PRODUCTS_DIR" --directory "$CLI_PATH"

APP_SOURCE="$BUILT_PRODUCTS_DIR/$WRAPPER_NAME"
[ -d "$APP_SOURCE" ] || release_fail "Built app not found at $APP_SOURCE"
assert_macos_bundle_arm64_only "$APP_SOURCE"
preserve_macos_dsyms "$BUILT_PRODUCTS_DIR" "$APP_SOURCE" "$QVOICE_SYMBOLS_MACOS"
write_build_provenance "$QVOICE_SYMBOLS_MACOS/last-build.json" \
    "scripts/release.sh" "$SCHEME" "$CONFIGURATION" \
    "platform=macOS,arch=arm64" arm64 O ad-hoc \
    "$DERIVED_DATA_PATH" "$SOURCE_PACKAGES_DIR"

APP_PATH="$BUILD_DIR/$WRAPPER_NAME"
copy_tree_clone_first "$APP_SOURCE" "$APP_PATH"

APP_RESOURCES="$APP_PATH/Contents/Resources"
rm -rf "$APP_RESOURCES/backend" "$APP_RESOURCES/python" "$APP_RESOURCES/vendor" 2>/dev/null || true
rm -f "$APP_RESOURCES/ffmpeg" 2>/dev/null || true
find "$APP_RESOURCES" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$APP_RESOURCES" -name "*.pyc" -delete 2>/dev/null || true
find "$APP_RESOURCES" -name "*.whl" -delete 2>/dev/null || true
"$SCRIPT_DIR/check_backend_resource_contract.sh" --app-bundle "$APP_PATH" >/dev/null
echo "[4/8] App copied to $APP_PATH ($(step_time "$STEP_START"))"
echo ""

STEP_START="$(date +%s)"
echo "[5/8] Signing and verifying the final app bundle..."
# Re-sign nested code inside-out so every seal is valid and every
# Mach-O carries the release identity. Xcode's build-time signing uses
# the project's default ad-hoc identity ("-"), which notarization
# rejects ("not signed with a valid Developer ID certificate") — the
# 2.2.0 candidate failed exactly there on its embedded frameworks.
# Each framework first, inside-out (scripts/lib/release_signing.sh: the code nested in it,
# such as Sparkle's Autoupdate and Updater.app, then the framework; Sparkle's XPC services
# are removed because the app is not sandboxed), all without entitlements; then the app.
while IFS= read -r -d '' framework_path; do
    release_sign_framework "$framework_path" \
        || release_fail "Could not re-sign $(basename "$framework_path") and the code inside it"
done < <(find "$APP_PATH/Contents/Frameworks" -maxdepth 1 -type d -name '*.framework' -print0 2>/dev/null)
run_codesign "$APP_PATH" \
    --options runtime \
    --entitlements "$PROJECT_DIR/Sources/QwenVoice.entitlements"
codesign --verify --deep --strict "$APP_PATH"
if [ "$SIGNING_MODE" = "developer-id" ]; then
    QWENVOICE_EXPECT_SIGNED_RELEASE=1 \
    QWENVOICE_EXPECT_TEAM_ID="$RELEASE_TEAM_ID" \
        "$SCRIPT_DIR/verify_release_bundle.sh" "$APP_PATH"
else
    "$SCRIPT_DIR/verify_release_bundle.sh" "$APP_PATH"
fi
echo "[5/8] Final app bundle verified ($(step_time "$STEP_START"))"
echo ""
for resource_bundle in "$CLI_PATH"/*.bundle; do
    run_codesign "$resource_bundle"
done
run_codesign "$CLI_PATH/vocello" --options runtime
codesign --verify --strict "$CLI_PATH/vocello"
python3 "$SCRIPT_DIR/cli_package.py" seal --directory "$CLI_PATH" \
    --version "$MARKETING_VERSION" --build "$CURRENT_PROJECT_VERSION" --commit "$COMMIT_SHA"
python3 "$SCRIPT_DIR/cli_package.py" smoke --directory "$CLI_PATH" \
    --version "$MARKETING_VERSION" --build "$CURRENT_PROJECT_VERSION" --commit "$COMMIT_SHA"
CLI_MANIFEST_SHA256="$(shasum -a 256 "$CLI_PATH/package-manifest.json" | awk '{print $1}')"
[[ "$CLI_MANIFEST_SHA256" =~ ^[0-9a-f]{64}$ ]] || release_fail "Could not digest the sealed CLI manifest"

# The sealed folder ships twice from the same bytes: as the installer package here and as the
# DMG folder below. The package is signed with the Developer ID Installer identity in
# developer-id mode (left unsigned under the same name otherwise), notarized and stapled like the
# DMGs, then expanded and checked against the sealed manifest, including a root-free install,
# upgrade and smoke through the installed link.
STEP_START="$(date +%s)"
echo "[6/8] Building, signing and verifying the CLI installer package..."
CLI_PKG_NAME="${OUTPUT_NAME}-cli.pkg"
CLI_PKG_PATH="$BUILD_DIR/$CLI_PKG_NAME"
CLI_UNSIGNED_PKG_PATH="$BUILD_DIR/${OUTPUT_NAME}-cli.unsigned.pkg"
CLI_PKG_VERIFICATION_NAME="cli-pkg-verification.json"
CLI_PKG_VERIFICATION_PATH="$BUILD_DIR/$CLI_PKG_VERIFICATION_NAME"
# An earlier run's package or report never stands in for this run's; the package tools refuse
# to overwrite either.
rm -f "$CLI_UNSIGNED_PKG_PATH" "$CLI_PKG_PATH" "$CLI_PKG_VERIFICATION_PATH" \
    || release_fail "Could not remove an earlier CLI installer package or its report"
python3 "$SCRIPT_DIR/cli_package.py" pkg --directory "$CLI_PATH" \
    --version "$MARKETING_VERSION" --build "$CURRENT_PROJECT_VERSION" --commit "$COMMIT_SHA" \
    --output "$CLI_UNSIGNED_PKG_PATH" \
    || release_fail "Could not build the CLI installer package"
[ -f "$CLI_UNSIGNED_PKG_PATH" ] && [ ! -L "$CLI_UNSIGNED_PKG_PATH" ] \
    || release_fail "The built CLI installer package is missing: $CLI_UNSIGNED_PKG_PATH"
if [ "$SIGNING_MODE" = "developer-id" ]; then
    productsign_args=(productsign --sign "$INSTALLER_IDENTITY" --timestamp)
    if [ -n "$CODESIGN_KEYCHAIN" ]; then
        productsign_args+=(--keychain "$CODESIGN_KEYCHAIN")
    fi
    "${productsign_args[@]}" "$CLI_UNSIGNED_PKG_PATH" "$CLI_PKG_PATH" \
        || release_fail "productsign could not sign $CLI_PKG_NAME with the Developer ID Installer identity"
    rm -f "$CLI_UNSIGNED_PKG_PATH" || release_fail "Could not remove the unsigned CLI installer package"
    CLI_PKG_SIGNER="$(release_pkg_signer "$CLI_PKG_PATH")" \
        || release_fail "$CLI_PKG_NAME carries no Developer ID signature after productsign"
    [ "$CLI_PKG_SIGNER" = "$INSTALLER_IDENTITY" ] \
        || release_fail "$CLI_PKG_NAME is not signed by the release installer identity"
    CLI_PKG_SIGNATURE="developer-id-installer"
else
    mv "$CLI_UNSIGNED_PKG_PATH" "$CLI_PKG_PATH" \
        || release_fail "Could not name the unsigned CLI installer package $CLI_PKG_NAME"
    CLI_PKG_SIGNATURE="unsigned"
fi
if [ "$NOTARIZE" = "1" ]; then
    release_notarize "$CLI_PKG_PATH" || release_fail "Notarization of $CLI_PKG_NAME failed"
    CLI_PKG_NOTARIZATION="stapled"
else
    CLI_PKG_NOTARIZATION="not-performed"
fi
# A new tree inside the staging root, which the exit trap removes.
CLI_PKG_EXPANDED="$CLI_STAGE_ROOT/expanded-cli-pkg"
pkgutil --expand-full "$CLI_PKG_PATH" "$CLI_PKG_EXPANDED" \
    || release_fail "Could not expand $CLI_PKG_NAME for verification"
python3 "$SCRIPT_DIR/cli_package.py" pkg-verify \
    --expanded "$CLI_PKG_EXPANDED" --artifact "$CLI_PKG_PATH" \
    --version "$MARKETING_VERSION" --build "$CURRENT_PROJECT_VERSION" --commit "$COMMIT_SHA" \
    --manifest-sha256 "$CLI_MANIFEST_SHA256" \
    --signature "$CLI_PKG_SIGNATURE" --notarization "$CLI_PKG_NOTARIZATION" \
    --report "$CLI_PKG_VERIFICATION_PATH" --root-free-install \
    || release_fail "$CLI_PKG_NAME failed its expanded-package verification"
rm -rf "$CLI_PKG_EXPANDED"
echo "[6/8] CLI installer package ready at $CLI_PKG_PATH ($(step_time "$STEP_START"))"
echo ""

STEP_START="$(date +%s)"
echo "[7/8] Creating and signing the DMG..."
"$SCRIPT_DIR/create_dmg.sh" "$APP_PATH" "$OUTPUT_NAME"
DMG_PATH="$BUILD_DIR/${OUTPUT_NAME}.dmg"
CLI_DMG_NAME="${OUTPUT_NAME}-cli"
QWENVOICE_DMG_DISPLAY_NAME="Vocello CLI" \
    "$SCRIPT_DIR/create_dmg.sh" "$CLI_PATH" "$CLI_DMG_NAME" cli
CLI_DMG_PATH="$BUILD_DIR/${CLI_DMG_NAME}.dmg"
# Both DMGs and the installer package share one notarization path
# (scripts/lib/release_signing.sh); nothing is published here.
APP_DMG_PATH="$DMG_PATH"
for DMG_PATH in "$APP_DMG_PATH" "$CLI_DMG_PATH"; do
    [ -f "$DMG_PATH" ] || release_fail "Created DMG is missing: $DMG_PATH"
    run_codesign "$DMG_PATH"
    codesign --verify --verbose=4 "$DMG_PATH"
    if [ "$NOTARIZE" = "1" ]; then
        release_notarize "$DMG_PATH" || release_fail "Notarization of $(basename "$DMG_PATH") failed"
    fi
done
DMG_PATH="$APP_DMG_PATH"

echo "[7/8] DMG ready at $DMG_PATH ($(step_time "$STEP_START"))"
echo ""

STEP_START="$(date +%s)"
echo "[8/8] Writing release metadata..."
APP_BINARY="$APP_PATH/Contents/MacOS/$EXECUTABLE_NAME"
extract_otool_field() {
    local field="$1"
    otool -l "$APP_BINARY" | awk -v key="$field" '
        $1 == "cmd" && $2 == "LC_BUILD_VERSION" { in_block = 1; next }
        in_block && $1 == key && !found { print $2; found = 1 }
    '
    # awk reads to the end: exiting early would leave otool writing to a closed
    # pipe, and its SIGPIPE (141) fails the release under pipefail.
}

APP_MINOS="$(extract_otool_field minos)"
SDK_VERSION="$(extract_otool_field sdk)"
[ -n "$APP_MINOS" ] || release_fail "Failed to extract app minOS from $APP_BINARY"
[ -n "$SDK_VERSION" ] || release_fail "Failed to extract SDK version from $APP_BINARY"

XCODE_VERSION="$(xcodebuild -version | awk 'NR==1 {print $2}')"
COMMIT_SHA="$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || true)"
[ -n "$COMMIT_SHA" ] || COMMIT_SHA="unknown"

METADATA_PATH="$BUILD_DIR/release-metadata.txt"
{
    echo "commit_sha=$COMMIT_SHA"
    echo "release_mode=macos-github"
    echo "release_brand=Vocello"
    echo "xcode_version=$XCODE_VERSION"
    echo "sdk_version=$SDK_VERSION"
    echo "app_minos=$APP_MINOS"
    echo "marketing_version=$MARKETING_VERSION"
    echo "build_number=$CURRENT_PROJECT_VERSION"
    echo "dmg_name=$OUTPUT_NAME.dmg"
    echo "cli_dmg_name=$CLI_DMG_NAME.dmg"
    echo "cli_pkg_name=$CLI_PKG_NAME"
    echo "cli_pkg_verification=$CLI_PKG_VERIFICATION_NAME"
    echo "cli_manifest_sha256=$CLI_MANIFEST_SHA256"
    echo "app_wrapper_name=$WRAPPER_NAME"
    echo "app_executable_name=$EXECUTABLE_NAME"
    echo "built_at_utc=$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
} > "$METADATA_PATH"
write_build_provenance "$BUILD_DIR/last-build.json" \
    "scripts/release.sh" "$SCHEME" "$CONFIGURATION" \
    "platform=macOS,arch=arm64" arm64 O "$SIGNING_MODE" \
    "$DERIVED_DATA_PATH" "$SOURCE_PACKAGES_DIR"
echo "[8/8] Release metadata written to $METADATA_PATH ($(step_time "$STEP_START"))"
echo ""

TOTAL_ELAPSED="$(( $(date +%s) - TOTAL_START ))"
echo "Vocello macOS release build complete."
echo "  App:      $APP_PATH"
echo "  DMG:      $DMG_PATH"
echo "  CLI DMG:  $CLI_DMG_PATH"
echo "  CLI pkg:  $CLI_PKG_PATH"
echo "  Metadata: $METADATA_PATH"
echo "  Total:    ${TOTAL_ELAPSED}s"

prune_stale_builds "$OUTPUT_NAME"
