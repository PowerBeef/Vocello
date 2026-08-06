#!/usr/bin/env bash
# Install SHA-pinned CI tools from official release artifacts.
#
# GitHub's macOS runner pools serve mixed image generations during an image
# roll, so `brew install <tool>` yields whichever formula index the drawn
# runner carries — flapping the exact-version toolchain validation. This
# script makes the drifting tools (xcodegen, ripgrep, xcbeautify,
# shellcheck) deterministic: it
# downloads the release artifact recorded in config/toolchain.json
# `artifactPins`, verifies the pinned SHA-256, and installs the binary into
# an install prefix ahead of the image's copies on PATH.
#
# Usage: scripts/install_pinned_tools.sh [--prefix DIR]
#   Default prefix: $HOME/.qwenvoice-pinned-tools/bin
#   In GitHub Actions the prefix is appended to $GITHUB_PATH so subsequent
#   steps resolve the pinned binaries first.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT_DIR/config/toolchain.json"

PREFIX="$HOME/.qwenvoice-pinned-tools/bin"
if [[ "${1:-}" == "--prefix" ]]; then
    PREFIX="${2:?--prefix requires a directory}"
fi
mkdir -p "$PREFIX"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

install_pin() {
    local tool="$1"
    local url sha archive_path version
    url="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['artifactPins']['$tool']['url'])")"
    sha="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['artifactPins']['$tool']['sha256'])")"
    archive_path="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['artifactPins']['$tool']['archivePath'])")"
    version="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['artifactPins']['$tool']['version'])")"

    local artifact="$workdir/$tool-artifact"
    curl -fsSL --retry 3 -o "$artifact" "$url"
    local observed
    observed="$(shasum -a 256 "$artifact" | cut -d' ' -f1)"
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
    local wrapper="$PREFIX/$(basename "$archive_path")"
    printf '#!/usr/bin/env bash\nexec "%s" "$@"\n' "$tool_home/$archive_path" > "$wrapper"
    chmod +x "$wrapper"
    echo "installed $tool $version -> $wrapper"
}

install_pin xcodegen
install_pin ripgrep
install_pin xcbeautify
install_pin shellcheck

if [[ -n "${GITHUB_PATH:-}" ]]; then
    echo "$PREFIX" >> "$GITHUB_PATH"
fi

PATH="$PREFIX:$PATH" xcodegen --version
PATH="$PREFIX:$PATH" rg --version | head -1
PATH="$PREFIX:$PATH" xcbeautify --version
PATH="$PREFIX:$PATH" shellcheck --version | head -2
