#!/usr/bin/env bash
# Local development router. Nothing here blocks a commit; CI on push is the gate.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# shellcheck source=lib/build_paths.sh
. "$ROOT_DIR/scripts/lib/build_paths.sh"

case "${1:-}" in
  check|lint|contracts|py|test|ios|build|run|regen|ci|status|plan|focused|checkpoint)
    exec python3 "$ROOT_DIR/scripts/development_workflow.py" "$@"
    ;;
  *)
    cat >&2 <<'EOF'
usage: scripts/dev.sh <command>

  check [--dry-run]        lint, contracts, selected tests, native lanes the dirty tree touches
  lint                     git diff --check, privacy scan, shellcheck on changed shell
  contracts                product and repository contracts
  py [--all | --lane product|research|darwin | tests...]
                           Python tests via pytest (changed consumers by default)
  test [--only A,B | --all]  macOS XCTest bundles
  ios                      generic device-SDK compile (incremental)
  build | run              dev-signed macOS app build / launch
  regen                    regenerate derived artifacts
  ci                       exactly what push CI runs, serially
  status                   branch, dirty paths, lanes, primary plan
EOF
    exit 2
    ;;
esac
