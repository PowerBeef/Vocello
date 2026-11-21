#!/usr/bin/env bash
# Safely regenerate the Xcode project from project.yml.
# XcodeGen overwrites the entitlements file, so we back it up and restore it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Regeneration alone by default; --verify also runs the contract gate afterwards.
# --fast is accepted as the historical spelling of the default.
MODE="regenerate"
case "${1:-}" in
    ""|--fast) ;;
    --verify) MODE="verify" ;;
    *)
        echo "usage: ./scripts/regenerate_project.sh [--fast|--verify]" >&2
        exit 2
        ;;
esac

cd "$PROJECT_DIR"

# shellcheck source=lib/python.sh
. "$SCRIPT_DIR/lib/python.sh"
vocello_use_selected_python "$PROJECT_DIR"
# shellcheck source=lib/build_paths.sh
. "$SCRIPT_DIR/lib/build_paths.sh"
GENERATION_CACHE_DIR="$QVOICE_XCODE_SOURCE_PACKAGES/.qwenvoice-cache"
GENERATION_STAMP="$GENERATION_CACHE_DIR/project-generation.sha256"

if ! command -v xcodegen >/dev/null 2>&1; then
    echo "error: xcodegen is required to regenerate the project." >&2
    echo "Install the pinned version with ./scripts/install_pinned_tools.sh and put" >&2
    echo "\$HOME/.qwenvoice-pinned-tools/bin on PATH (docs/reference/development-workflow.md, New Mac setup)." >&2
    exit 1
fi

ENTITLEMENTS="Sources/QwenVoice.entitlements"
# The backup lives in a private directory mktemp creates, not under a name in
# /tmp another process could predict and create first. The backup file itself
# appears only once the copy is complete, so the exit trap never restores an
# empty or partial file over the entitlements.
BACKUP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/qwenvoice-entitlements.XXXXXX")"
BACKUP="$BACKUP_DIR/QwenVoice.entitlements"

cleanup() {
    if [ -f "$BACKUP" ]; then
        echo "==> Restoring entitlements..."
        if ! cp "$BACKUP" "$ENTITLEMENTS"; then
            echo "error: could not restore $ENTITLEMENTS; its backup is kept at $BACKUP" >&2
            return
        fi
    fi
    rm -rf "$BACKUP_DIR"
}
trap cleanup EXIT

generation_digest="$(python3 "$SCRIPT_DIR/project_generation.py" digest)"
echo "==> Backing up entitlements..."
cp "$ENTITLEMENTS" "$BACKUP.partial"
mv "$BACKUP.partial" "$BACKUP"

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
# because an unrelated repository check failed.
mkdir -p "$GENERATION_CACHE_DIR"
python3 "$SCRIPT_DIR/project_generation.py" record --stamp "$GENERATION_STAMP" --expected-signature "$generation_digest"

if [[ "$MODE" == "verify" ]]; then
    bash "$SCRIPT_DIR/check_project_inputs.sh"
else
    echo "==> Project regenerated; run scripts/dev.sh check (or --verify) to validate the tree."
fi

echo "==> Done. Project regenerated at QwenVoice.xcodeproj"
