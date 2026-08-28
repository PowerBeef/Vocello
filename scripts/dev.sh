#!/usr/bin/env bash
# Fast local development router. Repository gates remain authoritative.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# shellcheck source=lib/build_paths.sh
. "$ROOT_DIR/scripts/lib/build_paths.sh"

case "${1:-plan}" in
  plan|focused|checkpoint)
    exec python3 "$ROOT_DIR/scripts/development_workflow.py" "${1:-plan}" "${@:2}"
    ;;
  *)
    echo "usage: scripts/dev.sh [plan|focused|checkpoint]" >&2
    exit 2
    ;;
esac
