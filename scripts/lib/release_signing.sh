#!/usr/bin/env bash
# Release re-signing of the code inside the app's embedded frameworks, the release
# notarization of every distributed artifact, and the installer-package signer check.
#
# Sourced by scripts/release.sh, which defines `run_codesign TARGET [ARGS...]` (the
# release identity, keychain and secure timestamp), by scripts/verify_release_bundle.sh,
# which uses `release_is_macho` so the signer and the verifier agree on what is code, and by
# scripts/verify_packaged_cli.sh, which uses `release_pkg_signer` as release.sh does.
#
# Xcode's build-time signing seals each framework but leaves the code nested inside it as
# the vendor shipped it. Sparkle.framework (RF-23) carries the Autoupdate executable and
# Updater.app, which notarization rejects unless they carry the Developer ID, a secure
# timestamp and the hardened runtime, so every framework is re-signed inside-out.

# shellcheck shell=bash

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "error: scripts/lib/release_signing.sh must be sourced" >&2
    exit 1
fi

# Whether PATH is a Mach-O file (thin or universal), by the same test
# assert_macos_bundle_arm64_only uses.
release_is_macho() {
    [ -f "$1" ] && [ ! -L "$1" ] || return 1
    /usr/bin/file -b "$1" 2>/dev/null | grep -q 'Mach-O'
}

# Whether a Mach-O file is the main executable of the bundle that contains it, which
# codesign signs as part of that bundle: <bundle>/Contents/MacOS/<x>,
# <name>.framework/<name> or <name>.framework/Versions/<v>/<name>.
release_is_bundle_executable() {
    local path="$1" name parent
    name="$(basename "$path")"
    parent="$(dirname "$path")"
    if [ "$(basename "$parent")" = "MacOS" ] && [ "$(basename "$(dirname "$parent")")" = "Contents" ]; then
        return 0
    fi
    [ "$(basename "$parent")" = "$name.framework" ] && return 0
    [ "$(basename "$(dirname "$parent")")" = "Versions" ] \
        && [ "$(basename "$(dirname "$(dirname "$parent")")")" = "$name.framework" ]
}

# Sparkle's XPC services (Installer.xpc, Downloader.xpc) exist for sandboxed hosts. Vocello is
# not sandboxed and enables neither (no SUEnableInstallerLauncherService or
# SUEnableDownloaderService), so release packaging removes them, as Sparkle documents for
# non-sandboxed apps, instead of shipping nested code with its own entitlements. Any other
# framework is left alone.
release_prune_sparkle_services() {
    local framework="$1"
    [ "$(basename "$framework")" = "Sparkle.framework" ] || return 0
    rm -rf "$framework"/Versions/*/XPCServices "$framework/XPCServices" || return 1
    if [ -n "$(find "$framework" -name XPCServices -print 2>/dev/null)" ]; then
        echo "error: $framework still contains XPCServices after pruning" >&2
        return 1
    fi
}

# Re-sign one embedded framework inside-out. `find -depth` lists a directory after its
# contents, so every nested bundle (a *.framework, or a directory with Contents/MacOS such
# as Updater.app) and every other Mach-O (such as Autoupdate) is signed before the bundle
# that holds it; a bundle's own main executable is signed with its bundle. The framework is
# signed last. Nested code gets the hardened runtime and no entitlements, like the
# framework, and nothing is skipped silently: a listing or signing failure fails the call.
release_sign_framework() {
    local framework="$1" listing candidate status=0
    release_prune_sparkle_services "$framework" || return 1
    listing="$(mktemp "${TMPDIR:-/tmp}/vocello-nested-code.XXXXXX")" || return 1
    if ! find "$framework" -mindepth 1 -depth \( -type d -o -type f \) -print0 > "$listing"; then
        rm -f "$listing"
        echo "error: could not list the code inside $framework" >&2
        return 1
    fi
    while IFS= read -r -d '' candidate; do
        if [ -d "$candidate" ]; then
            case "$candidate" in
                *.framework) ;;
                *) [ -d "$candidate/Contents/MacOS" ] || continue ;;
            esac
        elif ! release_is_macho "$candidate" || release_is_bundle_executable "$candidate"; then
            continue
        fi
        if ! run_codesign "$candidate" --options runtime; then
            echo "error: could not sign ${candidate#"$framework"/} inside $(basename "$framework")" >&2
            status=1
            break
        fi
    done < "$listing"
    rm -f "$listing"
    [ "$status" -eq 0 ] || return 1
    run_codesign "$framework" --options runtime
}

# Submit ARTIFACT (either DMG or the CLI installer package) to Apple's notary service, wait for
# its verdict, then staple the ticket and validate it. The App Store Connect API key comes from
# APPLE_API_KEY_PATH and APPLE_API_KEY_ID; APPLE_API_ISSUER_ID is passed as --issuer only when it
# is a UUID: Team API keys need it, Individual API keys must omit it (notarytool rejects a
# non-UUID issuer). The issuer value is never printed. `notarytool submit --wait` exits 0
# whenever processing completes, including an Invalid verdict, so the verdict is checked
# explicitly; on any verdict but Accepted, Apple's per-issue log is fetched before failing so
# the reject reasons land in the release log. Every step is checked here rather than by the
# caller's `set -e`, which a `release_notarize ... || release_fail ...` caller suspends; any
# failure prints why and returns 1.
release_notarize() {
    local artifact="$1" output id status
    local key_args=(--key "${APPLE_API_KEY_PATH:-}" --key-id "${APPLE_API_KEY_ID:-}")
    if [ ! -f "$artifact" ] || [ -L "$artifact" ]; then
        echo "error: there is no artifact to notarize at $artifact" >&2
        return 1
    fi
    echo "  Submitting $(basename "$artifact") to Apple notarization via API key (typically 1-5 min)..."
    if [ -n "${APPLE_API_ISSUER_ID:-}" ] && [[ "$APPLE_API_ISSUER_ID" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
        key_args+=(--issuer "$APPLE_API_ISSUER_ID")
        echo "  Using Team API key (issuer present)."
    else
        echo "  Using Individual API key (no issuer)."
    fi
    if ! output="$(xcrun notarytool submit "$artifact" "${key_args[@]}" --wait 2>&1 | tee /dev/stderr)"; then
        echo "error: notarytool submission failed" >&2
        return 1
    fi
    id="$(printf '%s\n' "$output" | awk '/^[[:space:]]*id: /{print $2; exit}')"
    status="$(printf '%s\n' "$output" | awk '/^[[:space:]]*status: /{print $2}' | tail -1)"
    if [ "$status" != "Accepted" ]; then
        if [ -n "$id" ]; then
            echo "  Notarization verdict: ${status:-unknown}; fetching Apple's issue log..."
            xcrun notarytool log "$id" "${key_args[@]}" || true
        fi
        echo "error: notarization verdict: ${status:-unknown} (submission ${id:-unknown})" >&2
        return 1
    fi
    echo "  Stapling notarization ticket to $(basename "$artifact")..."
    if ! xcrun stapler staple "$artifact"; then
        echo "error: could not staple the notarization ticket to $(basename "$artifact")" >&2
        return 1
    fi
    if ! xcrun stapler validate "$artifact"; then
        echo "error: the stapled ticket on $(basename "$artifact") does not validate" >&2
        return 1
    fi
    echo "  Notarization OK and ticket stapled."
}

# Print the certificate that signed installer package PKG, as `pkgutil --check-signature` names
# it ("Developer ID Installer: Name (TEAMID)"), only when that check reports a developer
# certificate issued by Apple for distribution; return 1 otherwise. The caller compares it with
# the release identity or Team ID and keeps it out of every report.
release_pkg_signer() {
    local listing leaf
    listing="$(pkgutil --check-signature "$1" 2>/dev/null)" || return 1
    printf '%s\n' "$listing" | sed 's/^[[:space:]]*//' \
        | grep -Fx 'Status: signed by a developer certificate issued by Apple for distribution' >/dev/null \
        || return 1
    leaf="$(printf '%s\n' "$listing" | sed -n 's/^[[:space:]]*1\. //p')"
    leaf="${leaf%%$'\n'*}"
    [ -n "$leaf" ] || return 1
    printf '%s\n' "$leaf"
}
