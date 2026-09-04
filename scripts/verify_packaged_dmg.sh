#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EXPECT_SIGNED_RELEASE="${QWENVOICE_EXPECT_SIGNED_RELEASE:-0}"
EXPECT_NOTARIZED_DMG="${QWENVOICE_EXPECT_NOTARIZED_DMG:-0}"

fail() {
    echo "Error: $*" >&2
    exit 1
}

if [ $# -lt 2 ] || [ $# -gt 3 ] || { [ $# -eq 3 ] && [ "$3" != "--include-cli" ]; }; then
    fail "Usage: $0 /path/to/Vocello-macos26.dmg /path/to/release-metadata.txt [--include-cli]"
fi

DMG_PATH="$1"
METADATA_PATH="$2"
INCLUDE_CLI="${3:-}"

[ -f "$DMG_PATH" ] || fail "DMG not found: $DMG_PATH"
[ -f "$METADATA_PATH" ] || fail "Metadata file not found: $METADATA_PATH"

DMG_PATH="$(cd "$(dirname "$DMG_PATH")" && pwd)/$(basename "$DMG_PATH")"
METADATA_PATH="$(cd "$(dirname "$METADATA_PATH")" && pwd)/$(basename "$METADATA_PATH")"

EXPECTED_DMG_NAME="$(grep -E '^dmg_name=' "$METADATA_PATH" | head -n1 | cut -d= -f2-)"
if [ -z "$EXPECTED_DMG_NAME" ]; then
    fail "Metadata is missing dmg_name: $METADATA_PATH"
fi

ACTUAL_DMG_NAME="$(basename "$DMG_PATH")"
if [ "$EXPECTED_DMG_NAME" != "$ACTUAL_DMG_NAME" ]; then
    fail "Metadata dmg_name '$EXPECTED_DMG_NAME' does not match DMG '$ACTUAL_DMG_NAME'"
fi

MOUNTED_DEVICE=""
TEMP_ROOT=""
ATTACH_MOUNTPOINT=""
LAST_ATTACH_STDERR=""

cleanup() {
    if [ -n "$MOUNTED_DEVICE" ]; then
        hdiutil detach "$MOUNTED_DEVICE" >/dev/null 2>&1 || true
    fi
    if [ -n "$LAST_ATTACH_STDERR" ] && [ -f "$LAST_ATTACH_STDERR" ]; then
        rm -f "$LAST_ATTACH_STDERR"
    fi
    if [ -n "$ATTACH_MOUNTPOINT" ] && [ -d "$ATTACH_MOUNTPOINT" ]; then
        rm -rf "$ATTACH_MOUNTPOINT"
    fi
    if [ -n "$TEMP_ROOT" ] && [ -d "$TEMP_ROOT" ]; then
        rm -rf "$TEMP_ROOT"
    fi
}
trap cleanup EXIT

echo "=== Vocello: Verify Packaged DMG ==="
echo ""
echo "[1/5] Verifying DMG trust state..."
if [ "$EXPECT_SIGNED_RELEASE" = "1" ]; then
    codesign --verify --verbose=4 "$DMG_PATH" >/dev/null 2>&1 || fail "Signed DMG code signature verification failed"
fi
if [ "$EXPECT_NOTARIZED_DMG" = "1" ]; then
    xcrun stapler validate "$DMG_PATH" >/dev/null 2>&1 || fail "Stapled notarization ticket is missing or invalid for $DMG_PATH"
    spctl -a -vvv --type open --context context:primary-signature "$DMG_PATH" >/dev/null 2>&1 || fail "Signed DMG was rejected by spctl"
    echo "[1/5] Stapled DMG trust checks OK"
elif [ "$EXPECT_SIGNED_RELEASE" = "1" ]; then
    echo "[1/5] Signed DMG code signature checks OK"
else
    echo "[1/5] DMG notarization checks skipped (set QWENVOICE_EXPECT_NOTARIZED_DMG=1 for release verification)"
fi
echo ""

echo "[2/5] Attaching DMG..."

ATTACH_PLIST="$(mktemp)"
LAST_ATTACH_STDERR="$(mktemp)"

ATTACH_DELAYS=(2 4 6 8 10)
ATTACH_ATTEMPT=1
ATTACH_SUCCESS=false

for ATTACH_DELAY in "${ATTACH_DELAYS[@]}"; do
    : >"$ATTACH_PLIST"
    ATTACH_MOUNTPOINT="$(mktemp -d /tmp/vocello-dmg-mount.XXXXXX)"
    if hdiutil attach -mountpoint "$ATTACH_MOUNTPOINT" -nobrowse -readonly -plist "$DMG_PATH" >"$ATTACH_PLIST" 2>"$LAST_ATTACH_STDERR"; then
        ATTACH_SUCCESS=true
        break
    fi

    rm -rf "$ATTACH_MOUNTPOINT"
    ATTACH_MOUNTPOINT=""

    if [ "$ATTACH_ATTEMPT" -lt "${#ATTACH_DELAYS[@]}" ]; then
        echo "Attach attempt $ATTACH_ATTEMPT failed; retrying in ${ATTACH_DELAY}s..." >&2
        sleep "$ATTACH_DELAY"
    fi
    ATTACH_ATTEMPT=$((ATTACH_ATTEMPT + 1))
done

if [ "$ATTACH_SUCCESS" != true ]; then
    ATTACH_ERROR="$(tr '\n' ' ' <"$LAST_ATTACH_STDERR" | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//')"
    rm -f "$ATTACH_PLIST"
    fail "Failed to attach DMG after ${#ATTACH_DELAYS[@]} attempts: $DMG_PATH${ATTACH_ERROR:+ ($ATTACH_ERROR)}"
fi

MOUNTED_DEVICE="$(python3 - "$ATTACH_PLIST" <<'PY'
import plistlib
import sys
from pathlib import Path

data = plistlib.loads(Path(sys.argv[1]).read_bytes())
for entity in data.get("system-entities", []):
    dev = entity.get("dev-entry")
    if dev:
        print(dev)
        break
PY
)"
MOUNT_POINT="$(python3 - "$ATTACH_PLIST" <<'PY'
import plistlib
import sys
from pathlib import Path

data = plistlib.loads(Path(sys.argv[1]).read_bytes())
for entity in data.get("system-entities", []):
    mount = entity.get("mount-point")
    if mount:
        print(mount)
        break
PY
)"
rm -f "$ATTACH_PLIST"

[ -n "$MOUNTED_DEVICE" ] || fail "Could not determine attached device for $DMG_PATH"
[ -n "$MOUNT_POINT" ] || fail "Could not determine mount point for $DMG_PATH"
[ -d "$MOUNT_POINT" ] || fail "Mount point does not exist: $MOUNT_POINT"
echo "[2/5] Attached at $MOUNT_POINT"
echo ""

echo "[3/5] Copying packaged app out of the DMG..."
SOURCE_APP="$(find "$MOUNT_POINT" -maxdepth 1 -name '*.app' -type d | head -n1)"
[ -n "$SOURCE_APP" ] || fail "No .app found inside mounted DMG: $MOUNT_POINT"

TEMP_ROOT="$(mktemp -d /tmp/vocello-packaged-dmg.XXXXXX)"
COPIED_APP="$TEMP_ROOT/$(basename "$SOURCE_APP")"
ditto "$SOURCE_APP" "$COPIED_APP"
xattr -dr com.apple.quarantine "$COPIED_APP" >/dev/null 2>&1 || true
[ -d "$COPIED_APP" ] || fail "Copied app missing after ditto: $COPIED_APP"
echo "[3/5] Copied app to $COPIED_APP"
echo ""

echo "[4/5] Validating packaged bundle contents..."
"$SCRIPT_DIR/verify_release_bundle.sh" "$COPIED_APP"
if [ "$INCLUDE_CLI" = "--include-cli" ]; then
    bash "$SCRIPT_DIR/verify_packaged_cli.sh" "$METADATA_PATH"
fi
echo "[4/5] Packaged bundle validation passed"
echo ""

echo "[5/5] DMG verification complete"
echo ""
echo "  DMG:      $DMG_PATH"
echo "  Metadata: $METADATA_PATH"
echo "  App:      $COPIED_APP"
