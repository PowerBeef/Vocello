#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MATRIX_PATH="$SCRIPT_DIR/../config/apple-platform-capability-matrix.json"
EXPECT_SIGNED_RELEASE="${QWENVOICE_EXPECT_SIGNED_RELEASE:-0}"
# Skip step [3/4] (launch the packaged app and confirm it stays running)
# when the host OS can't actually run the app — most importantly the
# GitHub Actions macOS runners, which ship Xcode 26 on a macOS-15 image
# and therefore can launch nothing built against the macOS 26 SDK. The
# build, sign, and bundle-content checks still run; only the GUI smoke
# is suppressed. Set QWENVOICE_SKIP_LAUNCH_SMOKE=1 in the CI environment.
SKIP_LAUNCH_SMOKE="${QWENVOICE_SKIP_LAUNCH_SMOKE:-0}"
TEAM_ID_INFO_KEY="QwenVoiceTeamIdentifier"

# shellcheck source=./lib/shared.sh
. "$SCRIPT_DIR/lib/shared.sh"

codesign_has_runtime_metadata() {
    local target="$1"
    local codesign_output
    if ! codesign_output="$(codesign -dv --verbose=4 "$target" 2>&1)"; then
        printf '%s\n' "$codesign_output" >&2
        return 1
    fi
    grep -q "Runtime Version" <<<"$codesign_output"
}

codesign_team_identifier() {
    local target="$1"
    codesign -dv --verbose=4 "$target" 2>&1 \
        | awk -F= '/^TeamIdentifier=/ { print $2; exit }'
}

if [ $# -ne 1 ]; then
    fail "Usage: $0 /path/to/QwenVoice.app|/path/to/Vocello.app"
fi

APP_PATH="$1"
[ -d "$APP_PATH" ] || fail "App bundle not found: $APP_PATH"
APP_PATH="$(cd "$(dirname "$APP_PATH")" && pwd)/$(basename "$APP_PATH")"

APP_INFO_PLIST="$APP_PATH/Contents/Info.plist"
[ -f "$APP_INFO_PLIST" ] || fail "Missing app Info.plist: $APP_INFO_PLIST"
EXPECTED_APP_BUNDLE_ID="$(matrix_read "macOS/app/bundleIdentifier")"
EXPECTED_XPC_BUNDLE_ID="$(matrix_read "macOS/xpcService/bundleIdentifier")"
REQUIRED_ABSENT_RESOURCE_PATHS=()
while IFS= read -r required_absent_path; do
    REQUIRED_ABSENT_RESOURCE_PATHS+=("$required_absent_path")
done < <(matrix_read "macOS/app/requiredAbsentResourcePaths")

APP_EXECUTABLE_NAME="$(plist_read "$APP_INFO_PLIST" CFBundleExecutable)"
[ -n "$APP_EXECUTABLE_NAME" ] || fail "Could not resolve app executable name from $APP_INFO_PLIST"
APP_BINARY="$APP_PATH/Contents/MacOS/$APP_EXECUTABLE_NAME"
APP_BUNDLE_ID="$(plist_read "$APP_INFO_PLIST" CFBundleIdentifier)"
[ "$APP_BUNDLE_ID" = "$EXPECTED_APP_BUNDLE_ID" ] || fail "App bundle identifier mismatch: expected $EXPECTED_APP_BUNDLE_ID, got ${APP_BUNDLE_ID:-missing}"
APP_TEAM_ID="$(plist_read "$APP_INFO_PLIST" "$TEAM_ID_INFO_KEY" || true)"

XPC_SERVICE_PATH="$(find "$APP_PATH/Contents/XPCServices" -maxdepth 1 -name '*.xpc' -type d | head -n1 || true)"
[ -n "$XPC_SERVICE_PATH" ] || fail "Bundled XPC service missing inside $APP_PATH/Contents/XPCServices"
XPC_INFO_PLIST="$XPC_SERVICE_PATH/Contents/Info.plist"
XPC_BUNDLE_ID="$(plist_read "$XPC_INFO_PLIST" CFBundleIdentifier)"
[ "$XPC_BUNDLE_ID" = "$EXPECTED_XPC_BUNDLE_ID" ] || fail "Bundled XPC service bundle identifier mismatch: expected $EXPECTED_XPC_BUNDLE_ID, got ${XPC_BUNDLE_ID:-missing}"
XPC_TEAM_ID="$(plist_read "$XPC_INFO_PLIST" "$TEAM_ID_INFO_KEY" || true)"
XPC_EXECUTABLE_NAME="$(plist_read "$XPC_INFO_PLIST" CFBundleExecutable)"
[ -n "$XPC_EXECUTABLE_NAME" ] || fail "Could not resolve XPC executable name from $XPC_INFO_PLIST"
XPC_SERVICE_BINARY="$XPC_SERVICE_PATH/Contents/MacOS/$XPC_EXECUTABLE_NAME"

RESOURCES_DIR="$APP_PATH/Contents/Resources"
TMP_UI_HOME=""
TMP_UI_FIXTURE=""
TMP_UI_STDOUT=""
TMP_UI_STDERR=""

cleanup() {
    pkill -x "$APP_EXECUTABLE_NAME" 2>/dev/null || true
    [ -n "$TMP_UI_HOME" ] && rm -rf "$TMP_UI_HOME"
    [ -n "$TMP_UI_FIXTURE" ] && rm -rf "$TMP_UI_FIXTURE"
    [ -n "$TMP_UI_STDOUT" ] && rm -f "$TMP_UI_STDOUT"
    [ -n "$TMP_UI_STDERR" ] && rm -f "$TMP_UI_STDERR"
    # bash 3.2 (the macOS system bash) propagates the cleanup function's
    # last command's exit code as the script's overall exit code from
    # within an EXIT trap, regardless of whether `exit 0` was called.
    # Each `[ -n "$EMPTY" ] && ...` above returns 1 when the var is
    # empty (e.g., when SKIP_LAUNCH_SMOKE=1 short-circuited before the
    # tmpdirs were created), which made the parent release.sh see this
    # script as failed even after `[4/4] Release bundle verification
    # passed`. Explicit `return 0` neutralizes that.
    return 0
}
trap cleanup EXIT

echo "=== Vocello: Verify Release Bundle ==="
echo ""

echo "[1/4] Checking native bundle contents..."
[ -x "$APP_BINARY" ] || fail "App binary missing: $APP_BINARY"
[ -d "$XPC_SERVICE_PATH" ] || fail "Bundled XPC service missing: $XPC_SERVICE_PATH"
[ -x "$XPC_SERVICE_BINARY" ] || fail "Bundled XPC service binary missing: $XPC_SERVICE_BINARY"
"$SCRIPT_DIR/check_backend_resource_contract.sh" --app-bundle "$APP_PATH" >/dev/null
for required_absent_path in "${REQUIRED_ABSENT_RESOURCE_PATHS[@]}"; do
    if [ -e "$APP_PATH/$required_absent_path" ]; then
        fail "Forbidden packaged path is present: $required_absent_path"
    fi
done
if find "$RESOURCES_DIR" -name "*.whl" -print -quit | grep -q .; then
    fail "Vendored wheel files must not be packaged into the native app bundle"
fi
if find "$RESOURCES_DIR" \( -name "*.pyc" -o -type d -name "__pycache__" \) -print -quit | grep -q .; then
    fail "Compiled Python artifacts must not be packaged into the native app bundle"
fi
echo "[1/4] Native bundle contents OK"
echo ""

echo "[2/4] Verifying app code signature..."
if [ "$EXPECT_SIGNED_RELEASE" = "1" ]; then
    codesign --verify --deep --strict "$APP_PATH" >/dev/null 2>&1 || fail "Signed release code signature verification failed"
    codesign_has_runtime_metadata "$APP_PATH" || fail "Signed release is missing hardened runtime metadata"
    codesign --verify --strict "$XPC_SERVICE_PATH" >/dev/null 2>&1 || fail "Bundled XPC service code signature verification failed"
    codesign_has_runtime_metadata "$XPC_SERVICE_PATH" || fail "Bundled XPC service is missing hardened runtime metadata"
    EXPECTED_TEAM_ID="${QWENVOICE_EXPECT_TEAM_ID:-${APPLE_TEAM_ID:-}}"
    [ -n "$APP_TEAM_ID" ] || fail "Signed release app Info.plist is missing $TEAM_ID_INFO_KEY"
    [ -n "$XPC_TEAM_ID" ] || fail "Signed release XPC Info.plist is missing $TEAM_ID_INFO_KEY"
    if [ -n "$EXPECTED_TEAM_ID" ]; then
        [ "$APP_TEAM_ID" = "$EXPECTED_TEAM_ID" ] || fail "App Team ID mismatch: expected $EXPECTED_TEAM_ID, got $APP_TEAM_ID"
        [ "$XPC_TEAM_ID" = "$EXPECTED_TEAM_ID" ] || fail "XPC Team ID mismatch: expected $EXPECTED_TEAM_ID, got $XPC_TEAM_ID"
    fi
    APP_SIGNATURE_TEAM_ID="$(codesign_team_identifier "$APP_PATH")"
    XPC_SIGNATURE_TEAM_ID="$(codesign_team_identifier "$XPC_SERVICE_PATH")"
    [ "$APP_SIGNATURE_TEAM_ID" = "$APP_TEAM_ID" ] || fail "App signature Team ID mismatch: Info.plist=$APP_TEAM_ID signature=${APP_SIGNATURE_TEAM_ID:-missing}"
    [ "$XPC_SIGNATURE_TEAM_ID" = "$XPC_TEAM_ID" ] || fail "XPC signature Team ID mismatch: Info.plist=$XPC_TEAM_ID signature=${XPC_SIGNATURE_TEAM_ID:-missing}"
    # Every nested framework must carry the release team identity too —
    # notarization rejects any ad-hoc Mach-O, and build-time signing
    # leaves frameworks ad-hoc until release re-signing covers them.
    while IFS= read -r -d '' framework_path; do
        FRAMEWORK_SIGNATURE_TEAM_ID="$(codesign_team_identifier "$framework_path")"
        [ "$FRAMEWORK_SIGNATURE_TEAM_ID" = "$APP_TEAM_ID" ] \
            || fail "Nested framework $(basename "$framework_path") signature Team ID mismatch: expected $APP_TEAM_ID, got ${FRAMEWORK_SIGNATURE_TEAM_ID:-missing (ad-hoc?)}"
    done < <(find "$APP_PATH/Contents/Frameworks" -maxdepth 1 -type d -name '*.framework' -print0 2>/dev/null)
    echo "[2/4] Signed release checks OK"
else
    echo "[2/4] Signature checks skipped (set QWENVOICE_EXPECT_SIGNED_RELEASE=1 for release verification)"
fi
echo ""

if [ "$SKIP_LAUNCH_SMOKE" = "1" ]; then
    echo "[3/4] Launch smoke skipped (QWENVOICE_SKIP_LAUNCH_SMOKE=1)."
    echo ""
    echo "[4/4] Release bundle verification passed (launch smoke skipped)."
    exit 0
fi

echo "[3/4] Launching packaged app in isolated native mode..."
TMP_UI_HOME="$(mktemp -d)"
TMP_UI_FIXTURE="$(mktemp -d)"
TMP_UI_STDOUT="$(mktemp)"
TMP_UI_STDERR="$(mktemp)"

mkdir -p \
    "$TMP_UI_FIXTURE/models" \
    "$TMP_UI_FIXTURE/outputs" \
    "$TMP_UI_FIXTURE/voices" \
    "$TMP_UI_FIXTURE/cache" \
    "$TMP_UI_FIXTURE/cache/stream_sessions"

pkill -x "$APP_EXECUTABLE_NAME" 2>/dev/null || true

HOME="$TMP_UI_HOME" \
USER="${USER:-$(id -un)}" \
LOGNAME="${LOGNAME:-${USER:-$(id -un)}}" \
QWENVOICE_DEBUG=1 \
QWENVOICE_APP_SUPPORT_DIR="$TMP_UI_FIXTURE" \
/usr/bin/open -n "$APP_PATH" \
>"$TMP_UI_STDOUT" 2>"$TMP_UI_STDERR"

if ! APP_EXECUTABLE_NAME="$APP_EXECUTABLE_NAME" python3 - <<'PY'
import os
import subprocess
import time

deadline = time.time() + 30
process_seen = False
name = os.environ["APP_EXECUTABLE_NAME"]

def is_running() -> bool:
    proc = subprocess.run(
        ["pgrep", "-x", name],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0

while time.time() < deadline:
    if is_running():
        process_seen = True
        time.sleep(2.0)
        if is_running():
            raise SystemExit(0)
        raise SystemExit(f"{name} launched but did not remain running long enough to pass startup smoke")
    time.sleep(0.25)

if process_seen:
    raise SystemExit(f"{name} process exited before startup smoke completed")
raise SystemExit(f"Timed out waiting for packaged {name} process to launch")
PY
then
    echo "Packaged-app smoke stdout tail:" >&2
    tail -n 40 "$TMP_UI_STDOUT" >&2 || true
    echo "Packaged-app smoke stderr tail:" >&2
    tail -n 80 "$TMP_UI_STDERR" >&2 || true
    fail "Isolated packaged-app startup smoke failed"
fi

echo "[3/4] Packaged app startup smoke OK"
echo ""

echo "[4/4] Release bundle verification passed."
