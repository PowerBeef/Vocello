# Local dev code-signing helpers for QwenVoice / Vocello.
#
# WHY: macOS TCC keys permission grants (microphone, speech recognition,
# files-and-folders) to the app's bundle ID + code-signing identity. Ad-hoc
# signatures ("-") derive their designated requirement from the binary's
# CDHash, which changes on every rebuild — so every `build.sh` rebuild used to
# invalidate the grants and re-prompt (sometimes invisibly). Signing local
# builds with a stable "Apple Development" certificate gives a stable
# designated requirement, so grants survive rebuilds.
#
# Resolution order (no identity is ever hardcoded — maintainer-privacy rule):
#   1. $QWENVOICE_DEV_SIGNING_IDENTITY (verbatim; "-" is the ad-hoc escape hatch)
#   2. first "Apple Development: …" identity in the keychain
#   3. "-" (ad-hoc) with a warning that TCC grants will not survive rebuilds
#
# Sourced by scripts/build.sh and scripts/ui_test.sh (the benchmark lane re-signs
# the XCTest runner with the same identity) — release.sh has its own signing flow
# and re-signs every component from scratch, so nothing dev-signed can ship.

# shellcheck shell=bash

resolve_dev_signing_identity() {
    if [ -n "${QWENVOICE_DEV_SIGNING_IDENTITY:-}" ]; then
        printf '%s\n' "$QWENVOICE_DEV_SIGNING_IDENTITY"
        return 0
    fi
    local detected
    detected="$(/usr/bin/security find-identity -v -p codesigning 2>/dev/null \
        | /usr/bin/sed -n 's/.*"\(Apple Development: [^"]*\)".*/\1/p' \
        | /usr/bin/head -n 1)"
    if [ -n "$detected" ]; then
        printf '%s\n' "$detected"
        return 0
    fi
    printf '%s\n' "-"
}

# Compare the resolved identity against the cached one. On change, remove the
# built app products so the next build re-signs + restages from scratch, and
# print the one-time TCC migration hint when moving from ad-hoc to a real
# certificate. Does NOT update the cache — call
# record_dev_signing_identity after a successful build.
#
# Args: $1 = resolved identity, $2 = xcodebuild app product path,
#       $3 = staged app bundle path
sync_dev_signing_cache() {
    local identity="$1" built_app="$2" staged_app="$3"
    mkdir -p "$BUILD_CACHE_DIR"
    local cache_file="$BUILD_CACHE_DIR/dev-signing-identity"
    local cached=""
    if [ -f "$cache_file" ]; then
        cached="$(cat "$cache_file" 2>/dev/null || true)"
    fi

    if [ "$identity" = "$cached" ]; then
        return 0
    fi

    if [ -d "$built_app" ] || [ -d "$staged_app" ]; then
        echo "==> Dev signing identity changed ('${cached:-none}' → '$identity'); forcing a fresh sign"
        quit_app_if_running
        rm -rf "$built_app" "$staged_app"
    fi

    if [ "$identity" != "-" ] && { [ -z "$cached" ] || [ "$cached" = "-" ]; }; then
        cat >&2 <<'EOF'
==> One-time TCC migration: previous ad-hoc builds left permission rows keyed
    to throwaway code identities. Reset them once so the stable-signed app
    prompts cleanly (run these yourself, or scripts/permissions_doctor.sh --reset-tcc):
        tccutil reset Microphone com.qwenvoice.app
        tccutil reset SpeechRecognition com.qwenvoice.app
    Note: the first signing with this certificate may show a keychain prompt
    ("codesign wants to sign using key…") — choose "Always Allow".
EOF
    fi
}

# Persist the identity used for the last successful build.
record_dev_signing_identity() {
    local identity="$1"
    mkdir -p "$BUILD_CACHE_DIR"
    printf '%s\n' "$identity" > "$BUILD_CACHE_DIR/dev-signing-identity"
}

# Fail loudly if a bundle is not signed with the expected identity.
# Args: $1 = bundle path, $2 = expected identity ("-" = ad-hoc)
assert_signing_identity() {
    local bundle="$1" expected="$2"
    local info
    info="$(/usr/bin/codesign -dvv "$bundle" 2>&1 || true)"
    if [ "$expected" = "-" ]; then
        if ! grep -q "Signature=adhoc" <<<"$info"; then
            echo "error: $bundle is not ad-hoc signed as expected" >&2
            echo "$info" >&2
            return 1
        fi
    else
        if ! grep -qF "Authority=$expected" <<<"$info"; then
            echo "error: $bundle is not signed by '$expected'" >&2
            echo "$info" >&2
            return 1
        fi
    fi
}
