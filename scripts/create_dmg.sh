#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/build_paths.sh
. "$SCRIPT_DIR/lib/build_paths.sh"
RELEASE_DIR="$QVOICE_DIST_MACOS"

APP_PATH="${1:-$RELEASE_DIR/Vocello.app}"
DMG_BASENAME="${2:-Vocello-macos26}"
DISPLAY_NAME="${QWENVOICE_DMG_DISPLAY_NAME:-Vocello}"
PAYLOAD_KIND="${3:-app}"
DMG_OUTPUT="$RELEASE_DIR/${DMG_BASENAME}.dmg"

echo "=== Vocello: Create DMG ==="
echo ""
echo "  Distribution root: $RELEASE_DIR"
echo ""

if [ ! -d "$APP_PATH" ]; then
    echo "Error: App not found at $APP_PATH" >&2
    echo "Usage: $0 [/path/to/QwenVoice.app|/path/to/Vocello.app] [dmg_basename]" >&2
    exit 1
fi

if [[ "$DMG_BASENAME" == *"/"* ]]; then
    echo "Error: DMG basename must not contain path separators: $DMG_BASENAME" >&2
    exit 1
fi
case "$PAYLOAD_KIND" in
    app) ;;
    cli)
        [ -x "$APP_PATH/vocello" ] && [ -f "$APP_PATH/package-manifest.json" ] || {
            echo "Error: CLI DMG requires a sealed executable payload" >&2; exit 1;
        }
        ;;
    *) echo "Error: payload kind must be app or cli" >&2; exit 1 ;;
esac

mkdir -p "$RELEASE_DIR"
rm -f "$DMG_OUTPUT"

echo "[1/3] Creating DMG staging directory..."
STAGING_DIR="$(mktemp -d)"
cleanup() {
    rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

cp -a "$APP_PATH" "$STAGING_DIR/"
if [ "$PAYLOAD_KIND" = app ]; then
    ln -s /Applications "$STAGING_DIR/Applications"
fi

echo "[2/3] Building compressed DMG..."
# hdiutil sizes its intermediate image from its own estimate of the folder, which came out
# short on GitHub's runners: copying the app's Metal library into the image failed with
# "No space left on device" (BKL-12). Size the image from the larger of the folder's
# logical and allocated sizes plus a fifth and 64 MB of headroom; the compressed DMG does
# not grow with it.
logical_kb="$(du -skA "$STAGING_DIR" | cut -f1)"
allocated_kb="$(du -sk "$STAGING_DIR" | cut -f1)"
payload_kb=$(( logical_kb > allocated_kb ? logical_kb : allocated_kb ))
hdiutil create \
    -volname "$DISPLAY_NAME" \
    -srcfolder "$STAGING_DIR" \
    -size "$(( payload_kb + payload_kb / 5 + 65536 ))k" \
    -ov \
    -format UDBZ \
    "$DMG_OUTPUT"

echo "[3/3] DMG created"
echo ""
echo "  DMG: $DMG_OUTPUT"
