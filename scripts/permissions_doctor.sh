#!/usr/bin/env bash
# macOS permission (TCC) diagnostics for Vocello development.
#
# Read-only by default: prints the local build's code-signing identity and
# designated requirement (the thing TCC keys grants to), the app's TCC rows,
# available signing identities, microphone hardware, and on-device speech
# locales — then suggests remediations. The only mutating path is --reset-tcc.
#
# Background: TCC keys permission grants to bundle ID + code identity. Ad-hoc
# dev builds used to get a new identity every rebuild (grants invalidated each
# time); build.sh now signs with a stable Apple Development identity so grants
# survive. See docs/reference/macos-permissions.md.
#
# usage:
#   scripts/permissions_doctor.sh             # diagnose
#   scripts/permissions_doctor.sh --reset-tcc # reset Vocello's mic + speech TCC rows

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_BUNDLE="$ROOT_DIR/build/Vocello.app"
BUNDLE_ID="com.qwenvoice.app"
TCC_DB="$HOME/Library/Application Support/com.apple.TCC/TCC.db"

usage() {
    sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

decode_auth() {
    case "$1" in
        0) echo "denied" ;;
        1) echo "unknown" ;;
        2) echo "allowed" ;;
        3) echo "limited" ;;
        *) echo "auth=$1" ;;
    esac
}

section_signing() {
    echo "==> Code identity of build/Vocello.app"
    if [ ! -d "$APP_BUNDLE" ]; then
        echo "    (no local build at $APP_BUNDLE — run ./scripts/build.sh build)"
        return 0
    fi
    local info
    info="$(codesign -dvv "$APP_BUNDLE" 2>&1 || true)"
    echo "$info" | grep -E "^(Authority=|TeamIdentifier=|CDHash=|Signature=)" | sed 's/^/    /' || true
    if grep -q "Signature=adhoc" <<<"$info"; then
        cat <<'EOF'
    ⚠ AD-HOC signature: the designated requirement is pinned to this exact
      binary, so TCC grants (mic/speech) will NOT survive the next rebuild.
      Install an Apple Development certificate (Xcode → Settings → Accounts)
      or set QWENVOICE_DEV_SIGNING_IDENTITY, then rebuild.
EOF
    fi
    echo "    designated requirement:"
    codesign -d -r- "$APP_BUNDLE" 2>/dev/null | grep "designated" | sed 's/^/      /' || true
}

section_tcc() {
    echo "==> TCC rows for $BUNDLE_ID (user database)"
    if [ ! -r "$TCC_DB" ]; then
        cat <<'EOF'
    (cannot read the TCC database — give your terminal Full Disk Access in
     System Settings → Privacy & Security → Full Disk Access, or skip this check)
EOF
        return 0
    fi
    local rows
    rows="$(sqlite3 "$TCC_DB" \
        "SELECT service, auth_value, datetime(last_modified,'unixepoch','localtime') FROM access WHERE client='$BUNDLE_ID';" \
        2>/dev/null || true)"
    if [ -z "$rows" ]; then
        echo "    (no rows — the app has never been granted/denied anything, or rows were reset)"
        return 0
    fi
    while IFS='|' read -r service auth modified; do
        printf '    %-36s %-8s (since %s)\n' "$service" "$(decode_auth "$auth")" "$modified"
    done <<<"$rows"
}

section_identities() {
    echo "==> Available code-signing identities"
    security find-identity -v -p codesigning 2>/dev/null | sed 's/^/    /' || echo "    (none)"
}

section_mic() {
    echo "==> Microphone hardware"
    local inputs
    inputs="$(system_profiler SPAudioDataType 2>/dev/null \
        | awk '/Input Channels/ {print prev} {prev=$0}' | sed 's/^ *//;s/:$//' || true)"
    if [ -n "$inputs" ]; then
        echo "$inputs" | sed 's/^/    input: /'
    else
        echo "    ⚠ no audio-input device detected — the record UI shows its no-microphone"
        echo "      state; attach a real input device before testing microphone capture."
    fi
}

section_speech() {
    echo "==> On-device speech recognition (best-effort probe, ~15s)"
    local probe_out=""
    if command -v swift >/dev/null 2>&1; then
        local probe_file
        probe_file="$(mktemp /tmp/vocello-speech-probe.XXXXXX.swift)"
        cat > "$probe_file" <<'SWIFT'
import Speech
var onDevice: [String] = []
for locale in SFSpeechRecognizer.supportedLocales() {
    if let r = SFSpeechRecognizer(locale: locale), r.supportsOnDeviceRecognition {
        onDevice.append(locale.identifier)
    }
}
print("on-device locales: " + (onDevice.isEmpty ? "(none installed)" : onDevice.sorted().joined(separator: " ")))
SWIFT
        probe_out="$(swift "$probe_file" 2>/dev/null | grep "on-device locales" || true)"
        rm -f "$probe_file"
    fi
    echo "    ${probe_out:-"(probe unavailable — needs the swift toolchain)"}"
    local siri_enabled
    siri_enabled="$(defaults read com.apple.assistant.support "Assistant Enabled" 2>/dev/null || echo "unknown")"
    echo "    Siri enabled: $siri_enabled"
    if [ "$siri_enabled" = "0" ]; then
        cat <<'EOF'
    ⚠ Siri is disabled. On macOS, SFSpeechRecognizer authorization is
      auto-DENIED without ever showing a prompt while Siri is off — this is
      an OS gate, not an app bug. To use on-device transcription: enable
      Siri (System Settings → Apple Intelligence & Siri), then turn Vocello
      on under Privacy & Security → Speech Recognition (reset first if a
      denied row exists: tccutil reset SpeechRecognition com.qwenvoice.app).
EOF
    fi
}

section_remedies() {
    cat <<'EOF'
==> Remediations
    Reset Vocello's permission rows (forces clean re-prompts):
        tccutil reset Microphone com.qwenvoice.app
        tccutil reset SpeechRecognition com.qwenvoice.app
    System Settings panes:
        open "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
        open "x-apple.systempreferences:com.apple.preference.security?Privacy_SpeechRecognition"
    After changing grants in System Settings, relaunch the app (a running
    process caches a denied authorization for its lifetime).
EOF
}

reset_tcc() {
    echo "==> Resetting TCC rows for $BUNDLE_ID (Microphone + SpeechRecognition)"
    tccutil reset Microphone "$BUNDLE_ID"
    tccutil reset SpeechRecognition "$BUNDLE_ID"
    echo "==> Done. Relaunch the app to re-prompt."
}

main() {
    case "${1:-}" in
        --reset-tcc)
            reset_tcc
            ;;
        -h|--help|help)
            usage
            ;;
        "")
            section_signing
            section_tcc
            section_identities
            section_mic
            section_speech
            section_remedies
            ;;
        *)
            echo "error: unknown option '$1'" >&2
            usage
            exit 2
            ;;
    esac
}

main "$@"
