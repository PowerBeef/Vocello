#!/usr/bin/env bash
# RF-23: prepares the Sparkle.framework that Xcode embeds in Vocello.app, as the
# macOS app target's last build phase, before Xcode seals the app.
#
# Vocello ships arm64 only and is not sandboxed. Sparkle's prebuilt framework is
# universal and carries two XPC services that only sandboxed hosts use (the
# Downloader service holds sandbox entitlements, and the app must stay the only
# entitled Mach-O). So the framework's Mach-O files are thinned to arm64, the XPC
# services are removed, and the nested code is re-signed inside-out with the
# build's identity. scripts/release.sh re-signs everything with the release
# identity, and scripts/verify_release_bundle.sh checks the result.
set -euo pipefail

framework="${TARGET_BUILD_DIR:?}/${FRAMEWORKS_FOLDER_PATH:?}/Sparkle.framework"
[[ -d "$framework" ]] || exit 0

rm -rf "$framework/XPCServices"
find "$framework/Versions" -mindepth 2 -maxdepth 2 -type d -name XPCServices -exec rm -rf {} +

while IFS= read -r -d '' candidate; do
    /usr/bin/file -b "$candidate" | grep -q 'Mach-O' || continue
    archs="$(/usr/bin/lipo -archs "$candidate")"
    [[ "$archs" == "arm64" ]] && continue
    [[ " $archs " == *" arm64 "* ]] || {
        echo "error: $candidate has no arm64 slice (found: $archs)" >&2
        exit 1
    }
    mode="$(/usr/bin/stat -f %Lp "$candidate")"
    /usr/bin/lipo "$candidate" -thin arm64 -output "$candidate.arm64"
    /bin/mv -f "$candidate.arm64" "$candidate"
    /bin/chmod "$mode" "$candidate"
done < <(find "$framework/Versions" -type f -print0)

[[ "${CODE_SIGNING_ALLOWED:-YES}" == "NO" ]] && exit 0
identity="${EXPANDED_CODE_SIGN_IDENTITY:-}"
[[ -n "$identity" ]] || identity="-"
sign=(/usr/bin/codesign --force --sign "$identity" --timestamp=none)
[[ "${ENABLE_HARDENED_RUNTIME:-NO}" == "YES" ]] && sign+=(--options runtime)

# Inside-out: the helper app and executable, then the framework that seals them.
while IFS= read -r -d '' nested; do
    "${sign[@]}" "$nested"
done < <(find "$framework/Versions" -mindepth 2 -maxdepth 2 \( -name '*.app' -o -name Autoupdate \) -print0)
"${sign[@]}" "$framework"
