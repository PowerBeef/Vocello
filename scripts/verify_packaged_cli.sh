#!/usr/bin/env bash
# Verifies the CLI release outputs that release-metadata.txt names: the CLI DMG's folder, copied
# out and smoked, and with --include-pkg the installer package: its name, its release.sh report,
# its signature and ticket when a signed release is expected, its expanded payload, then a real
# install, upgrade and uninstall. Both copies of vocello must carry exactly the macos-cli
# entitlement set (scripts/entitlement_contract.py). Called by the managed artifact-verification
# step through `verify_packaged_dmg.sh … --include-cli [--include-pkg <pkg>]`, not a release lane.
#
# The install test writes to /usr/local with sudo, so it runs only on a GitHub-hosted Actions
# runner (CI=true, GITHUB_ACTIONS=true, RUNNER_ENVIRONMENT=github-hosted) with passwordless sudo,
# which is ephemeral; anywhere else, a self-hosted runner included, --include-pkg is refused with
# exit 2 before anything runs and sudo is never invoked. A local package is checked without root
# by `scripts/cli_package.py pkg-verify --root-free-install` (release.sh runs it).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/release_signing.sh
. "$SCRIPT_DIR/lib/release_signing.sh"

# What the installer package owns on the target volume. A test that sources this file moves
# these into a sandbox and stands in for sudo, installer and pkgutil.
PKG_RECEIPT="com.qwenvoice.cli"
PKG_TARGET="/"
PKG_LIB="/usr/local/lib/vocello"
PKG_BIN_LINK="/usr/local/bin/vocello"
PKG_COMPLETION_LINK="/usr/local/share/zsh/site-functions/_vocello"
# The folders, below the target volume, that postinstall links into or creates them in.
PKG_LINK_FOLDERS=(usr/local usr/local/bin usr/local/share usr/local/share/zsh usr/local/share/zsh/site-functions)
# The data store the CLI shares with the Mac app; installing and removing the CLI never touch it.
PKG_DATA_STORE="$HOME/Library/Application Support/QwenVoice"

fail() {
    echo "CLI package verification: $*" >&2
    exit 1
}

# Whether this host may run the install test: a GitHub-hosted runner with passwordless sudo.
# sudo is not consulted unless all three variables name one.
pkg_install_host_ready() {
    if [ "${CI:-}" != "true" ] || [ "${GITHUB_ACTIONS:-}" != "true" ] \
        || [ "${RUNNER_ENVIRONMENT:-}" != "github-hosted" ]; then
        return 1
    fi
    sudo -n true >/dev/null 2>&1
}

# A digest of the data store's names, types, sizes and modification times ("absent" when there
# is none); only the digest reaches the log.
pkg_data_store_state() {
    if [ ! -e "$PKG_DATA_STORE" ] && [ ! -L "$PKG_DATA_STORE" ]; then
        echo "absent"
        return 0
    fi
    find "$PKG_DATA_STORE" -exec stat -f '%N%t%HT%t%z%t%m' {} + | LC_ALL=C sort | shasum -a 256 | awk '{print $1}'
}

# metadata_value METADATA KEY: the single non-empty value of KEY.
metadata_value() {
    python3 - "$1" "$2" <<'PY'
import sys
from pathlib import Path
rows = [line.split('=', 1)[1] for line in Path(sys.argv[1]).read_text().splitlines()
        if line.startswith(sys.argv[2] + '=')]
if len(rows) != 1 or not rows[0]:
    raise SystemExit('missing/duplicate CLI release metadata')
print(rows[0])
PY
}

# pkg_check_artifact PKG DIST_DIR PKG_NAME REPORT_NAME MANIFEST_DIGEST VERSION BUILD COMMIT
# The package is the one release-metadata.txt names, in the same folder, and the one release.sh
# verified: its report names these bytes, the sealed manifest and this release. A signed release
# also needs the release team's Developer ID Installer signature, and a notarized one a valid
# stapled ticket that Gatekeeper accepts for installation.
pkg_check_artifact() {
    local pkg="$1" dist="$2" name="$3" report_name="$4" manifest="$5"
    local version="$6" build="$7" commit="$8" signer
    [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9\ ._-]*-cli\.pkg$ ]] || fail "unsafe CLI installer package name in the metadata"
    [ "$report_name" = "cli-pkg-verification.json" ] || fail "unexpected CLI installer package report name in the metadata"
    [ -f "$pkg" ] && [ ! -L "$pkg" ] || fail "the CLI installer package is missing or a link"
    [ "$(basename "$pkg")" = "$name" ] || fail "the CLI installer package is not the one the release metadata names"
    [ "$(cd "$(dirname "$pkg")" && pwd -P)" = "$(cd "$dist" && pwd -P)" ] \
        || fail "the CLI installer package is not beside its release metadata"
    [ -f "$dist/$report_name" ] && [ ! -L "$dist/$report_name" ] || fail "release.sh's CLI installer package report is missing"
    python3 - "$dist/$report_name" "$name" "$(shasum -a 256 "$pkg" | awk '{print $1}')" \
        "$(stat -f '%z' "$pkg")" "$manifest" "$version" "$build" "$commit" <<'PY' \
        || fail "release.sh's CLI installer package report does not bind this package and release"
import json
import sys
from pathlib import Path
report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
name, sha256, size, manifest, version, build, commit = sys.argv[2:]
expected_release = {"marketingVersion": version, "buildNumber": build, "commitSHA": commit}
if (report.get("status") != "passed" or report.get("release") != expected_release
        or report.get("manifestSHA256") != manifest
        or report.get("artifact") != {"name": name, "bytes": int(size), "sha256": sha256}):
    raise SystemExit(1)
PY
    if [ "${QWENVOICE_EXPECT_SIGNED_RELEASE:-0}" = 1 ]; then
        [ -n "${QWENVOICE_EXPECT_TEAM_ID:-}" ] || fail "missing expected CLI installer signing team"
        signer="$(release_pkg_signer "$pkg")" || fail "the CLI installer package lacks a Developer ID signature"
        case "$signer" in
            "Developer ID Installer: "*" ($QWENVOICE_EXPECT_TEAM_ID)") ;;
            *) fail "the CLI installer package is not signed by the release team's Developer ID Installer identity" ;;
        esac
    fi
    if [ "${QWENVOICE_EXPECT_NOTARIZED_DMG:-0}" = 1 ]; then
        xcrun stapler validate "$pkg" || fail "the CLI installer package has no valid stapled ticket"
        spctl -a -vvv -t install "$pkg" || fail "Gatekeeper rejected the CLI installer package for installation"
    fi
}

# pkg_check_payload PKG WORK_DIR MANIFEST_DIGEST
# Expand the package into WORK_DIR: its payload holds the sealed manifest, and its vocello carries
# exactly the macos-cli entitlement set (none), as the DMG folder's does.
pkg_check_payload() {
    local pkg="$1" expanded="$2/expanded-cli-pkg" manifest="$3" payload
    pkgutil --expand-full "$pkg" "$expanded" || fail "could not expand the CLI installer package"
    payload="$expanded/vocello-cli.pkg/Payload"
    [ -f "$payload/vocello" ] && [ ! -L "$payload/vocello" ] || fail "the CLI installer package's payload has no vocello"
    [ "$(shasum -a 256 "$payload/package-manifest.json" | awk '{print $1}')" = "$manifest" ] \
        || fail "the CLI installer package's payload differs from the sealed folder"
    python3 "$SCRIPT_DIR/entitlement_contract.py" verify-bundle --role macos-cli --bundle "$payload/vocello" \
        || fail "the CLI installer package's vocello carries entitlements outside the macos-cli role"
}

pkg_install() {
    sudo installer -pkg "$1" -target "$PKG_TARGET" || fail "installer could not install $(basename "$1")"
}

# On a stock Mac those folders belong to root and no one else can change them, the only state in
# which postinstall links the command. A hosted runner gives /usr/local/bin to its own user, so
# its ephemeral copies are set to that state first (the folder itself, never its contents); one
# that does not exist yet is left for postinstall to create.
pkg_prepare_stock_folders() {
    local folder path
    for folder in "${PKG_LINK_FOLDERS[@]}"; do
        path="${PKG_TARGET%/}/$folder"
        [ -d "$path" ] && [ ! -L "$path" ] || continue
        if ! sudo chown root:wheel "$path" || ! sudo chmod go-w "$path"; then
            fail "could not give $path to root, as a stock Mac has it"
        fi
    done
}

# The installed CLI: its receipt at this version, a real folder holding the sealed manifest,
# the two relative links postinstall makes, the command link resolving into the folder, and
# the smoke run through that link.
pkg_check_installed() {
    local version="$1" build="$2" commit="$3" manifest="$4" info resolved
    info="$(pkgutil --pkg-info "$PKG_RECEIPT")" || fail "the installer left no $PKG_RECEIPT receipt"
    printf '%s\n' "$info" | grep -Fx "version: $version" >/dev/null \
        || fail "the $PKG_RECEIPT receipt does not record version $version"
    [ -d "$PKG_LIB" ] && [ ! -L "$PKG_LIB" ] || fail "$PKG_LIB is not a real folder after installing"
    [ -L "$PKG_BIN_LINK" ] && [ "$(readlink "$PKG_BIN_LINK")" = "../lib/vocello/vocello" ] \
        || fail "$PKG_BIN_LINK is not the relative link into $PKG_LIB"
    [ -L "$PKG_COMPLETION_LINK" ] && [ "$(readlink "$PKG_COMPLETION_LINK")" = "../../../lib/vocello/_vocello" ] \
        || fail "$PKG_COMPLETION_LINK is not the relative link into $PKG_LIB"
    resolved="$(cd -P "$(dirname "$PKG_BIN_LINK")/../lib/vocello" 2>/dev/null && pwd -P)" \
        || fail "$PKG_BIN_LINK does not resolve"
    [ "$resolved" = "$(cd -P "$PKG_LIB" && pwd -P)" ] || fail "$PKG_BIN_LINK does not resolve into $PKG_LIB"
    [ "$(shasum -a 256 "$PKG_LIB/package-manifest.json" | awk '{print $1}')" = "$manifest" ] \
        || fail "the installed manifest differs from the sealed folder's"
    python3 "$SCRIPT_DIR/cli_package.py" smoke --directory "$PKG_LIB" --launcher "$PKG_BIN_LINK" \
        --version "$version" --build "$build" --commit "$commit" \
        || fail "the installed CLI failed its smoke run through $PKG_BIN_LINK"
}

pkg_check_removed() {
    local path
    if pkgutil --pkg-info "$PKG_RECEIPT" >/dev/null 2>&1; then
        fail "uninstall.sh left the $PKG_RECEIPT receipt"
    fi
    for path in "$PKG_LIB" "$PKG_BIN_LINK" "$PKG_COMPLETION_LINK"; do
        [ ! -e "$path" ] && [ ! -L "$path" ] || fail "uninstall.sh left $path"
    done
}

# pkg_install_test PKG VERSION BUILD COMMIT MANIFEST_DIGEST
# Install on the runner's startup disk, upgrade over a planted stale file (Installer never
# deletes a file the new payload lacks; preinstall must), then uninstall with the shipped
# uninstall.sh, leaving no receipt, folder or link and the shared data store as it was.
pkg_install_test() {
    local pkg="$1" version="$2" build="$3" commit="$4" manifest="$5" before path stale
    if pkgutil --pkg-info "$PKG_RECEIPT" >/dev/null 2>&1; then
        fail "this host already has a $PKG_RECEIPT receipt; the install test needs a clean runner"
    fi
    for path in "$PKG_LIB" "$PKG_BIN_LINK" "$PKG_COMPLETION_LINK"; do
        [ ! -e "$path" ] && [ ! -L "$path" ] || fail "$path already exists; the install test needs a clean runner"
    done
    before="$(pkg_data_store_state)" || fail "could not read the data store's state"
    pkg_prepare_stock_folders

    echo "  Installing $(basename "$pkg")..."
    pkg_install "$pkg"
    pkg_check_installed "$version" "$build" "$commit" "$manifest"

    echo "  Upgrading over a stale file from an older payload..."
    stale="$PKG_LIB/stale-file-from-an-older-version.txt"
    sudo touch "$stale" || fail "could not plant the stale-file probe"
    [ -f "$stale" ] || fail "the stale-file probe is missing before the upgrade"
    pkg_install "$pkg"
    [ ! -e "$stale" ] && [ ! -L "$stale" ] || fail "upgrading kept a file the new payload does not have"
    pkg_check_installed "$version" "$build" "$commit" "$manifest"

    echo "  Removing it with the shipped uninstall.sh..."
    sudo sh "$PKG_LIB/uninstall.sh" || fail "uninstall.sh failed"
    pkg_check_removed
    [ "$(pkg_data_store_state)" = "$before" ] || fail "installing or removing the CLI changed the data store"
    echo "  Install, upgrade and uninstall OK."
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    return 0
fi

usage() {
    echo "Usage: $0 release-metadata.txt [--include-pkg <name>-cli.pkg]" >&2
    exit 1
}
[ "$#" -eq 1 ] || [ "$#" -eq 3 ] || usage
METADATA_PATH="$1"
CLI_PKG=""
if [ "$#" -eq 3 ]; then
    [ "$2" = "--include-pkg" ] && [ -n "$3" ] || usage
    CLI_PKG="$3"
    if ! pkg_install_host_ready; then
        echo "verify_packaged_cli.sh: --include-pkg installs the package into /usr/local with sudo," \
            "so it runs only on a GitHub-hosted runner (CI=true, GITHUB_ACTIONS=true," \
            "RUNNER_ENVIRONMENT=github-hosted) with passwordless sudo. Refusing on this host;" \
            "check a local package with: python3 scripts/cli_package.py pkg-verify --root-free-install" >&2
        exit 2
    fi
fi
DIST_DIR="$(cd "$(dirname "$METADATA_PATH")" && pwd)"
CLI_NAME="$(metadata_value "$METADATA_PATH" cli_dmg_name)"
[[ "$CLI_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9\ ._-]*\.dmg$ ]] || { echo "Unsafe CLI DMG name" >&2; exit 1; }
CLI_DMG="$DIST_DIR/$CLI_NAME"
[ -f "$CLI_DMG" ] || { echo "Missing CLI DMG" >&2; exit 1; }
VERSION="$(metadata_value "$METADATA_PATH" marketing_version)"
BUILD="$(metadata_value "$METADATA_PATH" build_number)"
COMMIT="$(metadata_value "$METADATA_PATH" commit_sha)"
MANIFEST_DIGEST="$(metadata_value "$METADATA_PATH" cli_manifest_sha256)"
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
python3 "$SCRIPT_DIR/entitlement_contract.py" verify-bundle --role macos-cli --bundle "$COPIED_CLI/vocello" \
    || fail "the CLI DMG's vocello carries entitlements outside the macos-cli role"
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

if [ -n "$CLI_PKG" ]; then
    echo "Verifying the CLI installer package..."
    CLI_PKG_NAME="$(metadata_value "$METADATA_PATH" cli_pkg_name)"
    CLI_PKG_REPORT="$(metadata_value "$METADATA_PATH" cli_pkg_verification)"
    pkg_check_artifact "$CLI_PKG" "$DIST_DIR" "$CLI_PKG_NAME" "$CLI_PKG_REPORT" \
        "$MANIFEST_DIGEST" "$VERSION" "$BUILD" "$COMMIT"
    pkg_check_payload "$CLI_PKG" "$VERIFY_ROOT" "$MANIFEST_DIGEST"
    pkg_install_test "$CLI_PKG" "$VERSION" "$BUILD" "$COMMIT" "$MANIFEST_DIGEST"
fi
