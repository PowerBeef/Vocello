#!/usr/bin/env bash
# Called by the existing managed artifact-verification step, not a release lane.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
[ "$#" -eq 1 ] || { echo "Usage: $0 release-metadata.txt" >&2; exit 1; }
METADATA_PATH="$1"
DIST_DIR="$(cd "$(dirname "$METADATA_PATH")" && pwd)"
metadata_value() {
    python3 - "$METADATA_PATH" "$1" <<'PY'
import sys
from pathlib import Path
rows = [line.split('=', 1)[1] for line in Path(sys.argv[1]).read_text().splitlines()
        if line.startswith(sys.argv[2] + '=')]
if len(rows) != 1 or not rows[0]:
    raise SystemExit('missing/duplicate CLI release metadata')
print(rows[0])
PY
}
CLI_NAME="$(metadata_value cli_dmg_name)"
[[ "$CLI_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9\ ._-]*\.dmg$ ]] || { echo "Unsafe CLI DMG name" >&2; exit 1; }
CLI_DMG="$DIST_DIR/$CLI_NAME"
[ -f "$CLI_DMG" ] || { echo "Missing CLI DMG" >&2; exit 1; }
VERSION="$(metadata_value marketing_version)"
BUILD="$(metadata_value build_number)"
COMMIT="$(metadata_value commit_sha)"
MANIFEST_DIGEST="$(metadata_value cli_manifest_sha256)"
if [ "${QWENVOICE_EXPECT_SIGNED_RELEASE:-0}" = 1 ]; then
    codesign --verify --verbose=4 "$CLI_DMG"
fi
if [ "${QWENVOICE_EXPECT_NOTARIZED_DMG:-0}" = 1 ]; then
    xcrun stapler validate "$CLI_DMG"
    spctl -a -vvv --type open --context context:primary-signature "$CLI_DMG"
fi
VERIFY_ROOT="$(mktemp -d /tmp/vocello-cli-package.XXXXXX)"
MOUNT_POINT="$VERIFY_ROOT/mount"
mkdir "$MOUNT_POINT"
ATTACHED=0
cleanup() {
    local status=$?
    if [ "$ATTACHED" = 1 ]; then
        if ! hdiutil detach "$MOUNT_POINT"; then
            echo "CLI verification mount retained: detach failed" >&2
            exit 1
        fi
    fi
    rm -rf "$VERIFY_ROOT"
    exit "$status"
}
trap cleanup EXIT
# No automatic retry; preserve a failed attachment as a failed verification.
hdiutil attach -mountpoint "$MOUNT_POINT" -nobrowse -readonly "$CLI_DMG"
ATTACHED=1
COPIED_CLI="$VERIFY_ROOT/Copied CLI with spaces"
ditto "$MOUNT_POINT/Vocello CLI" "$COPIED_CLI"
[ "$(shasum -a 256 "$COPIED_CLI/package-manifest.json" | awk '{print $1}')" = "$MANIFEST_DIGEST" ] || {
    echo "CLI manifest does not match release metadata" >&2; exit 1;
}
codesign --verify --strict "$COPIED_CLI/vocello"
for resource_bundle in "$COPIED_CLI"/*.bundle; do
    codesign --verify --strict "$resource_bundle"
done
if [ "${QWENVOICE_EXPECT_SIGNED_RELEASE:-0}" = 1 ]; then
    [ -n "${QWENVOICE_EXPECT_TEAM_ID:-}" ] || { echo "Missing expected CLI signing team" >&2; exit 1; }
    codesign -dvv "$COPIED_CLI/vocello" 2> "$VERIFY_ROOT/signature.txt"
    grep -Fq 'Authority=Developer ID Application:' "$VERIFY_ROOT/signature.txt"
    grep -Fxq "TeamIdentifier=$QWENVOICE_EXPECT_TEAM_ID" "$VERIFY_ROOT/signature.txt"
    grep -Eq 'flags=.*runtime' "$VERIFY_ROOT/signature.txt"
fi
python3 "$SCRIPT_DIR/cli_package.py" smoke --directory "$COPIED_CLI" \
    --version "$VERSION" --build "$BUILD" --commit "$COMMIT" \
    --artifact "$CLI_DMG" --report "$DIST_DIR/cli-package-verification.json"
