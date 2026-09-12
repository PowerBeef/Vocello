#!/usr/bin/env bash
# Repository contract gate (T1 locally, T2 in CI): product and release contracts,
# exact product-invariant greps, the privacy scan, and the Python suite.
#
#   ./scripts/check_project_inputs.sh                       complete gate (release, scripts/dev.sh ci)
#   ./scripts/check_project_inputs.sh --local               same contracts; Python tests selected by the dirty tree
#   ./scripts/check_project_inputs.sh --python darwin-only  same contracts; only the macOS-bound Python modules
#                                                            (CI runs the rest on Linux)
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
        *) echo "usage: ./scripts/check_project_inputs.sh [--local] [--python all|darwin-only|selected|none]" >&2; exit 2 ;;
    esac
    shift
done
if [[ "$LOCAL_MODE" == 1 && -n "${CI:-}${GITHUB_ACTIONS:-}" ]]; then
    echo "error: local test selection is prohibited in CI" >&2
    exit 1
fi

echo "==> Validating checked-in project inputs..."

# Build-output ownership first: later validators rely on its exported paths.
python3 "$SCRIPT_DIR/build_output_policy.py" validate

# Generated project surfaces and product identity.
python3 "$SCRIPT_DIR/generate_cli_scheme.py" --check
python3 "$SCRIPT_DIR/generate_ios_logic_scheme.py" --check
python3 "$SCRIPT_DIR/cli_version_contract.py" validate
python3 "$SCRIPT_DIR/localization_contract.py" validate
python3 "$SCRIPT_DIR/saved_voice_lifecycle_contract.py" validate
python3 "$SCRIPT_DIR/entitlement_contract.py" validate
python3 "$SCRIPT_DIR/support_contact_contract.py" validate
python3 "$SCRIPT_DIR/public_facts_contract.py" validate
python3 "$SCRIPT_DIR/attribution_manifest.py" rebuild --check
python3 "$SCRIPT_DIR/attribution_manifest.py" validate

# Runtime, concurrency and backend contracts.
python3 "$SCRIPT_DIR/runtime_security_contract.py"
python3 "$SCRIPT_DIR/vendor_runtime_contract.py" validate
"$SCRIPT_DIR/check_backend_resource_contract.sh" --project
"$SCRIPT_DIR/check_qwen3_backend_only.sh"
python3 "$SCRIPT_DIR/validate_backend_risk_spine.py" --root "$PROJECT_DIR"
python3 "$SCRIPT_DIR/check_convergence_promotion_gate.py"

# Model delivery and App Store readiness.
python3 "$SCRIPT_DIR/model_catalog_contract.py" rebuild --check
python3 "$SCRIPT_DIR/model_catalog_contract.py" validate
python3 "$SCRIPT_DIR/model_host_availability.py" validate
python3 "$SCRIPT_DIR/ios_storage_protection_policy.py" validate
python3 "$SCRIPT_DIR/ios_device_eligibility.py" validate
python3 "$SCRIPT_DIR/app_store_connect_readiness.py" validate
python3 "$SCRIPT_DIR/ios_release_analyzer_warnings.py" validate

# Release evidence, supply chain and benchmark history.
python3 "$SCRIPT_DIR/supply_chain_contract.py"
python3 "$SCRIPT_DIR/required_step_ledger.py" validate-contract
python3 "$SCRIPT_DIR/evidence_impact.py" validate
python3 "$SCRIPT_DIR/quality_promotion.py" validate-contract
python3 "$SCRIPT_DIR/benchmark_history.py" validate --all
python3 "$SCRIPT_DIR/benchmark_history.py" rebuild-index --check
python3 "$SCRIPT_DIR/generate_readme_charts.py" --check

# Delivery and prosody research contracts (text-level; audio never gates ordinary CI).
python3 "$SCRIPT_DIR/check_delivery_instructions.py"
python3 "$SCRIPT_DIR/delivery_experiment.py" validate
python3 "$SCRIPT_DIR/delivery_evaluator.py" validate-v2-contract \
    --contract "$PROJECT_DIR/config/delivery-evaluator-v2-contract.json"
python3 "$SCRIPT_DIR/prosody_holdout_validation.py" validate-contract
python3 "$SCRIPT_DIR/prepare_delivery_compact_model_config.py" --validate-only

# Work authority: schema, blockers and a fresh render.
python3 "$SCRIPT_DIR/roadmap.py" validate
python3 "$SCRIPT_DIR/roadmap.py" render --check

# Exact product-invariant greps and the privacy scan.
"$SCRIPT_DIR/repo_invariants.sh"
python3 "$SCRIPT_DIR/privacy_scan.py"

# Python suite (pytest, parallel). selected: the modules the dirty tree affects;
# darwin-only: the macOS-bound modules (push CI runs the rest on Linux); all: everything.
case "$PYTHON_LANE" in
    selected) python3 "$SCRIPT_DIR/development_workflow.py" py ;;
    darwin-only) python3 -m pytest -n auto -m darwin_only ;;
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
