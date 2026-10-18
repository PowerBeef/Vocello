#!/usr/bin/env bash
# Install SHA-pinned CI tools from official release artifacts.
#
# GitHub's macOS runner pools serve mixed image generations during an image
# roll, so `brew install <tool>` yields whichever formula index the drawn
# runner carries — flapping the exact-version toolchain validation. This
# script makes the drifting tools deterministic (xcodegen, ripgrep,
# xcbeautify and shellcheck): it
# downloads the release artifact recorded in config/toolchain.json
# `artifactPins`, verifies the pinned SHA-256, and installs the binary into
# an install prefix ahead of the image's copies on PATH.
#
# Usage: scripts/install_pinned_tools.sh [--prefix DIR] [TOOL...]
#   Default prefix: $HOME/.qwenvoice-pinned-tools/bin
#   Default tools: xcodegen ripgrep xcbeautify shellcheck. Name other
#   `artifactPins` entries (for example gh, which release jobs need, or
#   swiftlint and ruff, which `scripts/dev.sh lint` uses) to install them.
#   Unsuffixed entries are Apple-silicon macOS artifacts; the Linux contracts
#   job names the `-linux-x86_64` entries (shellcheck, ruff, swiftlint),
#   which install the same version under the same binary name. A pin whose
#   archived binary has another name (SwiftLint's Linux zip ships the fully
#   static `swiftlint-static`) names its command with `binaryName`, the name
#   the wrapper is installed under; it defaults to the archived file's name.
#   In GitHub Actions the prefix is appended to $GITHUB_PATH so subsequent
#   steps resolve the pinned binaries first.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT_DIR/config/toolchain.json"

PREFIX="$HOME/.qwenvoice-pinned-tools/bin"
if [[ "${1:-}" == "--prefix" ]]; then
    PREFIX="${2:?--prefix requires a directory}"
    shift 2
fi
# Bash 3.2 (macOS) treats "${array[@]}" of an empty array as unset under set -u,
# so the default list is assigned rather than left empty.
if [[ $# -gt 0 ]]; then
    TOOLS=("$@")
else
    TOOLS=(xcodegen ripgrep xcbeautify shellcheck)
fi
mkdir -p "$PREFIX"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# The command a pin installs: its `binaryName`, else the archived binary's file name.
pinned_binary_name() {
    python3 -c "import json,os;pin=json.load(open('$MANIFEST'))['artifactPins']['$1'];print(pin.get('binaryName') or os.path.basename(pin['archivePath']))"
}

install_pin() {
    local tool="$1"
    local url sha archive_path version binary_name
    url="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['artifactPins']['$tool']['url'])")"
    sha="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['artifactPins']['$tool']['sha256'])")"
    archive_path="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['artifactPins']['$tool']['archivePath'])")"
    version="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['artifactPins']['$tool']['version'])")"
    binary_name="$(pinned_binary_name "$tool")"

    local artifact="$workdir/$tool-artifact"
    curl -fsSL --retry 3 -o "$artifact" "$url"
    local observed
    if command -v shasum >/dev/null 2>&1; then
        observed="$(shasum -a 256 "$artifact" | cut -d' ' -f1)"
    else
        observed="$(sha256sum "$artifact" | cut -d' ' -f1)"
    fi
    if [[ "$observed" != "$sha" ]]; then
        echo "error: $tool artifact SHA-256 mismatch (expected $sha, observed $observed)" >&2
        return 1
    fi

    local extract="$workdir/$tool-extract"
    mkdir -p "$extract"
    case "$url" in
        *.zip) unzip -q "$artifact" -d "$extract" ;;
        *.tar.gz|*.tgz) tar -xzf "$artifact" -C "$extract" ;;
        *.tar.xz) tar -xJf "$artifact" -C "$extract" ;;
        *)
            echo "error: unsupported artifact format for $tool: $url" >&2
            return 1
            ;;
    esac

    local binary="$extract/$archive_path"
    if [[ ! -f "$binary" ]]; then
        echo "error: $tool artifact does not contain expected path $archive_path" >&2
        return 1
    fi
    # XcodeGen resolves its bundled SettingPresets relative to argv[0], so a
    # plain symlink breaks it ("No macOS settings found"). Keep each tool's
    # extracted tree intact and expose the binary through an exec wrapper,
    # which passes the real absolute path as argv[0].
    local tool_home="${PREFIX%/bin}/share/$tool-$version"
    rm -rf "$tool_home"
    mkdir -p "$(dirname "$tool_home")"
    mv "$extract" "$tool_home"
    chmod +x "$tool_home/$archive_path"
    local wrapper
    wrapper="$PREFIX/$binary_name"
    printf '#!/usr/bin/env bash\nexec "%s" "$@"\n' "$tool_home/$archive_path" > "$wrapper"
    chmod +x "$wrapper"
    echo "installed $tool $version -> $wrapper"
}

for tool in "${TOOLS[@]}"; do
    install_pin "$tool"
done

if [[ -n "${GITHUB_PATH:-}" ]]; then
    echo "$PREFIX" >> "$GITHUB_PATH"
fi

for tool in "${TOOLS[@]}"; do
    binary="$(pinned_binary_name "$tool")"
    PATH="$PREFIX:$PATH" "$binary" --version | head -2
done
