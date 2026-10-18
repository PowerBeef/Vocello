#!/usr/bin/env bash
# Repository contract gate (T1 locally, T2 in CI): product and release contracts,
# exact product-invariant greps, the privacy scan, and the Python suite.
#
#   ./scripts/check_project_inputs.sh                       complete gate (release, scripts/dev.sh ci)
#   ./scripts/check_project_inputs.sh --local               contracts and Python tests selected by the dirty tree
#   ./scripts/check_project_inputs.sh --python none         same contracts; no Python suite (CI runs it in its own job)
#
# Every check here is deterministic and needs no model, phone or UI. Anything
# that asserts the wording of another script or workflow does not belong here.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

LOCAL_MODE=0
PYTHON_LANE=all
while [[ $# -gt 0 ]]; do
    case "$1" in
        --local) LOCAL_MODE=1; PYTHON_LANE=selected ;;
        --python) PYTHON_LANE="${2:-}"; shift ;;
        *) echo "usage: ./scripts/check_project_inputs.sh [--local] [--python all|selected|none]" >&2; exit 2 ;;
    esac
    shift
done
if [[ "$LOCAL_MODE" == 1 && -n "${CI:-}${GITHUB_ACTIONS:-}" ]]; then
    echo "error: local test selection is prohibited in CI" >&2
    exit 1
fi

echo "==> Validating checked-in project inputs..."

# Every product, release and repository contract, the exact product-invariant
# greps (scripts/repo_invariants.sh) and the privacy scan. They are independent
# read-only checks, so scripts/lib/contract_gate.py runs them in parallel and
# prints each one's output as one block in a fixed order; it lists them with
# the inputs each reads. --local skips a validator whose inputs the change does
# not touch; without it (CI, release, scripts/dev.sh ci) every validator runs.
if [[ "$LOCAL_MODE" == 1 ]]; then
    python3 "$SCRIPT_DIR/lib/contract_gate.py" --local
else
    python3 "$SCRIPT_DIR/lib/contract_gate.py"
fi

# Python suite (pytest, parallel). selected: the modules the dirty tree affects;
# all: everything.
case "$PYTHON_LANE" in
    selected) python3 "$SCRIPT_DIR/development_workflow.py" py ;;
    none) echo "==> Python suite skipped by request" >&2 ;;
    all)
        if [[ "${QVOICE_GATES:-}" == "quick" && -z "${CI:-}${GITHUB_ACTIONS:-}" ]] \
            && [[ -z "$(git -C "$PROJECT_DIR" status --porcelain -- scripts config 2>/dev/null)" ]]; then
            echo "==> quick gate mode: scripts/config unchanged — skipping the Python suite" >&2
        else
            python3 -m pytest -n auto
        fi ;;
    *) echo "error: unknown --python lane: $PYTHON_LANE" >&2; exit 2 ;;
esac

echo "==> Project inputs are clean."
