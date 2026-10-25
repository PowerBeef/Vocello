#!/usr/bin/env bash
# Fail-closed required-step ledger helpers. Source from repository orchestrators.

QVOICE_REQUIRED_STEP_TOOL="${QVOICE_REQUIRED_STEP_TOOL:-$ROOT_DIR/scripts/required_step_ledger.py}"
QVOICE_ORCHESTRATION_CONTRACT="${QVOICE_ORCHESTRATION_CONTRACT:-$ROOT_DIR/config/orchestration-contract.json}"
QVOICE_REQUIRED_STEP_WORKFLOW=""

required_steps_init() {
  local ledger="$1" workflow="$2" run_id="$3"
  QVOICE_REQUIRED_STEP_WORKFLOW="$workflow"
  python3 "$QVOICE_REQUIRED_STEP_TOOL" --contract "$QVOICE_ORCHESTRATION_CONTRACT" init \
    --ledger "$ledger" --workflow "$workflow" --run-id "$run_id"
}

required_step_run() {
  local ledger="$1" step="$2"
  shift 2
  local status=0 started_at
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if python3 "$QVOICE_REQUIRED_STEP_TOOL" --contract "$QVOICE_ORCHESTRATION_CONTRACT" \
      fault-requested --workflow "$QVOICE_REQUIRED_STEP_WORKFLOW" --step "$step"; then
    printf '[fault-injection] required step %s:%s forced to fail\n' \
      "$QVOICE_REQUIRED_STEP_WORKFLOW" "$step" >&2
    status=97
  else
    set +e
    "$@"
    status=$?
    set -e
  fi
  python3 "$QVOICE_REQUIRED_STEP_TOOL" record --ledger "$ledger" \
    --step "$step" --exit-code "$status" --started-at "$started_at" || return 98
  return "$status"
}

required_step_record() {
  local ledger="$1" step="$2" status="$3" started_at="${4:-}"
  python3 "$QVOICE_REQUIRED_STEP_TOOL" record --ledger "$ledger" \
    --step "$step" --exit-code "$status" ${started_at:+--started-at "$started_at"}
}

required_steps_finalize() {
  local ledger="$1"
  python3 "$QVOICE_REQUIRED_STEP_TOOL" finalize --ledger "$ledger"
}
