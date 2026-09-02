#!/usr/bin/env bash
# Install the exact App Store Connect CLI used by the signed iOS release preflight.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT_DIR/config/toolchain.json"
PREFIX="$HOME/.qwenvoice-pinned-tools/bin"
if [[ "${1:-}" == "--prefix" ]]; then
  PREFIX="${2:?--prefix requires a directory}"
fi
mkdir -p "$PREFIX"

url="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['artifactPins']['asc']['url'])")"
sha="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['artifactPins']['asc']['sha256'])")"
version="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['artifactPins']['asc']['version'])")"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
artifact="$workdir/asc"
curl -fsSL --retry 3 -o "$artifact" "$url"
observed="$(shasum -a 256 "$artifact" | cut -d' ' -f1)"
if [[ "$observed" != "$sha" ]]; then
  echo "error: asc artifact SHA-256 mismatch" >&2
  exit 1
fi
chmod +x "$artifact"
cp "$artifact" "$PREFIX/asc"
observed_version="$("$PREFIX/asc" version)"
if [[ "$observed_version" != "$version"* ]]; then
  echo "error: asc expected $version, observed $observed_version" >&2
  exit 1
fi
echo "installed asc $version -> $PREFIX/asc"
