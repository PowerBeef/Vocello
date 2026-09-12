#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC2034  # read by matrix_read in lib/shared.sh
MATRIX_PATH="$SCRIPT_DIR/../config/apple-platform-capability-matrix.json"

# shellcheck source=./lib/shared.sh
. "$SCRIPT_DIR/lib/shared.sh"

entitlements_to_file() {
    local target="$1"
    local output_path="$2"
    /usr/bin/codesign -d --entitlements :- "$target" >"$output_path" 2>/dev/null \
        || fail "Could not read entitlements for $target"
}

plist_array_contains() {
    local plist_path="$1"
    local key="$2"
    local expected_value="$3"
    PLIST_PATH="$plist_path" PLIST_KEY="$key" EXPECTED_VALUE="$expected_value" python3 - <<'PY'
import os
import plistlib
from pathlib import Path

plist_path = Path(os.environ["PLIST_PATH"])
key = os.environ["PLIST_KEY"]
expected = os.environ["EXPECTED_VALUE"]
data = plistlib.loads(plist_path.read_bytes())
values = data.get(key, [])
if not isinstance(values, list) or expected not in values:
    raise SystemExit(1)
PY
}

plist_bool_true() {
    local plist_path="$1"
    local key="$2"
    PLIST_PATH="$plist_path" PLIST_KEY="$key" python3 - <<'PY'
import os
import plistlib
from pathlib import Path

plist_path = Path(os.environ["PLIST_PATH"])
key = os.environ["PLIST_KEY"]
data = plistlib.loads(plist_path.read_bytes())
if data.get(key) is not True:
    raise SystemExit(1)
PY
}

metadata_read() {
    local metadata_path="$1"
    local key="$2"
    grep -E "^${key}=" "$metadata_path" | head -n1 | cut -d= -f2-
}

verify_app_bundle() {
    local app_path="$1"
    local label="$2"
    local temp_root="$3"

    [ -d "$app_path" ] || fail "$label app bundle missing: $app_path"

    local info_plist="$app_path/Info.plist"
    [ -f "$info_plist" ] || fail "$label app Info.plist missing: $info_plist"

    local bundle_id
    bundle_id="$(plist_read "$info_plist" CFBundleIdentifier)"
    [ "$bundle_id" = "$IOS_APP_BUNDLE_ID" ] || fail "$label app bundle identifier mismatch: expected $IOS_APP_BUNDLE_ID, got ${bundle_id:-missing}"

    # The iOS engine runs in-process (MLXTTSEngine) — the app embeds NO
    # ExtensionKit extension. (The old VocelloEngineExtension .appex was removed:
    # a non-UI extension is Jetsam-capped at a tiny per-process budget that the
    # increased-memory-limit entitlement does not raise.)
    local extension_paths=()
    while IFS= read -r extension_path; do
        extension_paths+=("$extension_path")
    done < <(find "$app_path" -type d -name '*.appex' | sort)
    [ "${#extension_paths[@]}" -eq 0 ] || fail "$label app must embed zero .appex bundles (engine is in-process); found ${#extension_paths[@]}: ${extension_paths[*]}"

    local app_entitlements="$temp_root/${label}_app_entitlements.plist"
    entitlements_to_file "$app_path" "$app_entitlements"

    for required_app_group in "${IOS_REQUIRED_APP_GROUPS[@]}"; do
        plist_array_contains "$app_entitlements" "com.apple.security.application-groups" "$required_app_group" \
            || fail "$label app is missing App Group $required_app_group"
    done

    if [ "$IOS_APP_EXPECTS_INCREASED_MEMORY_LIMIT" = "true" ]; then
        plist_bool_true "$app_entitlements" "com.apple.developer.kernel.increased-memory-limit" \
            || fail "$label app is missing com.apple.developer.kernel.increased-memory-limit=true"
    fi
}

if [ $# -ne 3 ]; then
    fail "Usage: $0 /path/to/VocelloiOS-TestFlight.xcarchive /path/to/export_dir /path/to/release_metadata.txt"
fi

ARCHIVE_PATH="$1"
EXPORT_DIR="$2"
METADATA_PATH="$3"

[ -d "$ARCHIVE_PATH" ] || fail "Archive not found: $ARCHIVE_PATH"
[ -d "$EXPORT_DIR" ] || fail "Export directory not found: $EXPORT_DIR"
[ -f "$METADATA_PATH" ] || fail "Metadata file not found: $METADATA_PATH"

ARCHIVE_PATH="$(cd "$(dirname "$ARCHIVE_PATH")" && pwd)/$(basename "$ARCHIVE_PATH")"
EXPORT_DIR="$(cd "$(dirname "$EXPORT_DIR")" && pwd)/$(basename "$EXPORT_DIR")"
METADATA_PATH="$(cd "$(dirname "$METADATA_PATH")" && pwd)/$(basename "$METADATA_PATH")"

IOS_APP_BUNDLE_ID="$(matrix_read "iOS/app/bundleIdentifier")"
IOS_REQUIRED_APP_GROUPS=()
while IFS= read -r required_app_group; do
    IOS_REQUIRED_APP_GROUPS+=("$required_app_group")
done < <(matrix_read "iOS/app/applicationGroups")
IOS_APP_EXPECTS_INCREASED_MEMORY_LIMIT="$(matrix_read "iOS/app/booleanEntitlements/com.apple.developer.kernel.increased-memory-limit")"

TEMP_ROOT="$(mktemp -d)"
cleanup() {
    rm -rf "$TEMP_ROOT"
}
trap cleanup EXIT

ARCHIVE_INFO_PLIST="$ARCHIVE_PATH/Info.plist"
[ -f "$ARCHIVE_INFO_PLIST" ] || fail "Archive Info.plist missing: $ARCHIVE_INFO_PLIST"

ARCHIVE_APP_PATH="$(find "$ARCHIVE_PATH/Products/Applications" -maxdepth 1 -name '*.app' -type d | head -n1 || true)"
[ -n "$ARCHIVE_APP_PATH" ] || fail "No app bundle found in archive: $ARCHIVE_PATH"

DESTINATION_MODE="$(metadata_read "$METADATA_PATH" destination_mode)"
[ -n "$DESTINATION_MODE" ] || fail "Metadata missing destination_mode: $METADATA_PATH"

VALIDATED_DEVICE_MODEL="$(metadata_read "$METADATA_PATH" validated_device_model)"
[ -n "$VALIDATED_DEVICE_MODEL" ] || fail "Metadata missing validated_device_model: $METADATA_PATH"

VALIDATED_DEVICE_OS="$(metadata_read "$METADATA_PATH" validated_device_os)"
[ -n "$VALIDATED_DEVICE_OS" ] || fail "Metadata missing validated_device_os: $METADATA_PATH"

OWNED_DEVICE_VALIDATION_TARGET="$(metadata_read "$METADATA_PATH" owned_device_validation_target)"
[ -n "$OWNED_DEVICE_VALIDATION_TARGET" ] || fail "Metadata missing owned_device_validation_target: $METADATA_PATH"

OFFICIAL_MINIMUM_DEVICE="$(metadata_read "$METADATA_PATH" official_minimum_device)"
[ -n "$OFFICIAL_MINIMUM_DEVICE" ] || fail "Metadata missing official_minimum_device: $METADATA_PATH"

MINIMUM_DEVICE_PROOF_STATUS="$(metadata_read "$METADATA_PATH" minimum_device_proof_status)"
[ -n "$MINIMUM_DEVICE_PROOF_STATUS" ] || fail "Metadata missing minimum_device_proof_status: $METADATA_PATH"

TESTFLIGHT_UPLOAD_STATUS="$(metadata_read "$METADATA_PATH" testflight_upload_status)"
[ -n "$TESTFLIGHT_UPLOAD_STATUS" ] || fail "Metadata missing testflight_upload_status: $METADATA_PATH"

echo "=== Vocello iPhone: Verify Release Archive ==="
echo ""

echo "[1/3] Verifying archived app (in-process engine, no extension)..."
verify_app_bundle "$ARCHIVE_APP_PATH" "archive" "$TEMP_ROOT"
echo "[1/3] Archive bundle verification OK"
echo ""

echo "[2/3] Verifying export artifacts and metadata..."
IPA_PATH="$(metadata_read "$METADATA_PATH" ipa_path)"
if [ "$DESTINATION_MODE" = "export" ]; then
    [ -n "$IPA_PATH" ] && [ "$IPA_PATH" != "none" ] || fail "Export metadata did not record an IPA path for destination_mode=export"
    [ -f "$IPA_PATH" ] || fail "IPA recorded in metadata does not exist: $IPA_PATH"

    UNPACK_DIR="$TEMP_ROOT/export_unpacked"
    mkdir -p "$UNPACK_DIR"
    ditto -x -k "$IPA_PATH" "$UNPACK_DIR"
    EXPORTED_APP_PATH="$(find "$UNPACK_DIR/Payload" -maxdepth 1 -name '*.app' -type d | head -n1 || true)"
    [ -n "$EXPORTED_APP_PATH" ] || fail "No .app found inside exported IPA: $IPA_PATH"
    verify_app_bundle "$EXPORTED_APP_PATH" "export" "$TEMP_ROOT"
else
    if [ "$IPA_PATH" != "none" ] && [ -n "$IPA_PATH" ]; then
        [ -f "$IPA_PATH" ] || fail "Metadata recorded a non-existent IPA path: $IPA_PATH"
    fi
fi

case "$MINIMUM_DEVICE_PROOF_STATUS" in
    pending|recorded|not_applicable) ;;
    *)
        fail "Unexpected minimum_device_proof_status '$MINIMUM_DEVICE_PROOF_STATUS'"
        ;;
esac

case "$TESTFLIGHT_UPLOAD_STATUS" in
    not_requested|local_export_only|uploaded_via_xcodebuild) ;;
    *)
        fail "Unexpected testflight_upload_status '$TESTFLIGHT_UPLOAD_STATUS'"
        ;;
esac
echo "[2/3] Export and metadata verification OK"
echo ""

echo "[3/3] Summary"
echo "  owned_device_validation_target: $OWNED_DEVICE_VALIDATION_TARGET"
echo "  validated_device_model: $VALIDATED_DEVICE_MODEL"
echo "  validated_device_os: $VALIDATED_DEVICE_OS"
echo "  official_minimum_device: $OFFICIAL_MINIMUM_DEVICE"
echo "  minimum_device_proof_status: $MINIMUM_DEVICE_PROOF_STATUS"
echo "  testflight_upload_status: $TESTFLIGHT_UPLOAD_STATUS"
