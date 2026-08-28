#!/usr/bin/env bash
# Safely regenerate the Xcode project from project.yml.
# XcodeGen overwrites the entitlements file, so we back it up and restore it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

MODE="checkpoint"
case "${1:-}" in
    "") ;;
    --fast) MODE="fast" ;;
    *)
        echo "usage: ./scripts/regenerate_project.sh [--fast]" >&2
        exit 2
        ;;
esac

cd "$PROJECT_DIR"

# shellcheck source=lib/build_paths.sh
. "$SCRIPT_DIR/lib/build_paths.sh"
GENERATION_CACHE_DIR="$QVOICE_XCODE_SOURCE_PACKAGES/.qwenvoice-cache"
GENERATION_STAMP="$GENERATION_CACHE_DIR/project.yml.sha256"

if ! command -v xcodegen >/dev/null 2>&1; then
    echo "error: xcodegen is required to regenerate the project." >&2
    echo "Install it with: brew install xcodegen" >&2
    exit 1
fi

ENTITLEMENTS="Sources/QwenVoice.entitlements"
BACKUP="/tmp/QwenVoice.entitlements.backup.$$"

cleanup() {
    if [ -f "$BACKUP" ]; then
        echo "==> Restoring entitlements..."
        cp "$BACKUP" "$ENTITLEMENTS"
        rm -f "$BACKUP"
    fi
}
trap cleanup EXIT

echo "==> Backing up entitlements..."
cp "$ENTITLEMENTS" "$BACKUP"

echo "==> Running xcodegen..."
xcodegen generate

# XcodeGen 2.45.4 cannot directly generate schemes for the CLI tool or the
# app-host-free iOS unit-test product. Render both shared schemes from generated target IDs so
# every Xcode invocation can still use an explicit managed DerivedData path.
python3 "$SCRIPT_DIR/generate_cli_scheme.py"
python3 "$SCRIPT_DIR/generate_ios_logic_scheme.py"

# Project generation and repository validation have different invalidation
# domains. Persist the source digest as soon as XcodeGen and both narrow scheme
# renderers succeed so a later build never regenerates the same project merely
# because an unrelated documentation or governance check failed.
mkdir -p "$GENERATION_CACHE_DIR"
generation_digest="$(/usr/bin/shasum -a 256 project.yml | awk '{print $1}')"
generation_stamp_next="$(mktemp "$GENERATION_CACHE_DIR/project.yml.sha256.next.XXXXXX")"
printf '%s\n' "$generation_digest" > "$generation_stamp_next"
mv -f "$generation_stamp_next" "$GENERATION_STAMP"

if [[ "$MODE" == "checkpoint" ]]; then
    bash "$SCRIPT_DIR/check_project_inputs.sh"
else
    echo "==> Fast regeneration complete; checkpoint validation intentionally deferred."
    echo "==> Run QVOICE_GATES=quick ./scripts/check_project_inputs.sh before commit."
fi

echo "==> Done. Project regenerated at QwenVoice.xcodeproj"
