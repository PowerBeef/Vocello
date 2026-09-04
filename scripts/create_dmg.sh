#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
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
hdiutil create \
    -volname "$DISPLAY_NAME" \
    -srcfolder "$STAGING_DIR" \
    -ov \
    -format UDBZ \
    "$DMG_OUTPUT"

echo "[3/3] DMG created"
echo ""
echo "  DMG: $DMG_OUTPUT"
