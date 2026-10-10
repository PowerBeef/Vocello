#!/usr/bin/env bash
# The sourcing runner owns out/platform and consumes last_status.
# shellcheck disable=SC2154,SC2034
# Best-effort collectors are isolated: a callback's exit/die cannot end the
# runner's EXIT trap or replace the native command's status.
ui_finalization_attempted=0
ui_finalization_status=0
ui_finalization_last_status=0

# Monitor mode gives each background collector its own process group on the
# system Bash 3.2 as well as newer shells. Never signal the caller's group.
# Each callback has a 300-second default budget (124 on timeout), plus at most
# six seconds of bounded cleanup grace. A descendant left after callback success
# is retired and recorded as 125; neither case can establish collection PASS.
ui_finalization_stop_group() {
  local group="$1"
  kill -TERM -- "-$group" 2>/dev/null || true
  kill -KILL -- "-$group" 2>/dev/null || true
}

ui_finalization_step() {
  local name="$1" status=0 interrupted=0 callback_pid watchdog_pid
  local monitoring=0 previous_int previous_term timeout_seconds
  shift
  timeout_seconds="${QVOICE_UI_COLLECTION_TIMEOUT_SECONDS:-300}"
  [[ "$timeout_seconds" =~ ^[0-9]+([.][0-9]+)?$ && "$timeout_seconds" != "0" ]] || timeout_seconds=300
  previous_int="$(trap -p INT)"
  previous_term="$(trap -p TERM)"
  [[ "$-" != *m* ]] || monitoring=1
  set -m
  (set +m; trap - EXIT INT TERM; set +e; "$@") >>"$out/ui-finalization.log" 2>&1 &
  callback_pid=$!
  (
    set +m
    trap - EXIT INT TERM
    sleep "$timeout_seconds"
    printf 'timeout\n' >"$out/.ui-collection-timeout-$callback_pid"
    kill -TERM -- "-$callback_pid" 2>/dev/null || true
    # Attachment export has its own two-second cleanup; allow it to retire its
    # separate export group before the outer collector's final KILL.
    sleep 3
    kill -KILL -- "-$callback_pid" 2>/dev/null || true
  ) >>"$out/ui-finalization.log" 2>&1 &
  watchdog_pid=$!
  (( monitoring != 0 )) || set +m
  # Preserve intentional signal suppression in the EXIT finalizer. Otherwise
  # finish this owned group before replaying the signal to the original trap.
  if [[ "$previous_int" != "trap -- '' SIGINT" ]]; then
    trap 'interrupted=130; trap "" INT TERM; kill -TERM -- "-$callback_pid" 2>/dev/null || true' INT
  fi
  if [[ "$previous_term" != "trap -- '' SIGTERM" ]]; then
    trap 'interrupted=143; trap "" INT TERM; kill -TERM -- "-$callback_pid" 2>/dev/null || true' TERM
  fi
  wait "$callback_pid" 2>>"$out/ui-finalization.log" || status=$?
  if (( interrupted != 0 )); then
    # wait may return as soon as the parent trap runs, before callback cleanup.
    sleep 3
    status="$interrupted"
  fi
  ui_finalization_stop_group "$watchdog_pid"
  wait "$watchdog_pid" 2>>"$out/ui-finalization.log" || true
  # A callback can exit while its child remains alive. Retire that owned group
  # even after success; no collector is allowed to leave a background process.
  if kill -0 -- "-$callback_pid" 2>/dev/null; then
    (( status != 0 )) || status=125
    kill -TERM -- "-$callback_pid" 2>/dev/null || true
    sleep 3
    ui_finalization_stop_group "$callback_pid"
  fi
  wait "$callback_pid" 2>>"$out/ui-finalization.log" || true
  if [[ -f "$out/.ui-collection-timeout-$callback_pid" ]]; then
    (( interrupted != 0 )) || status=124
    rm -f "$out/.ui-collection-timeout-$callback_pid"
  fi
  (( status == 0 )) || ui_finalization_status=1
  ui_finalization_last_status="$status"
  printf '%s\t%s\n' "$name" "$status" >>"$out/ui-finalization.tsv"
  trap - INT TERM
  [[ -z "$previous_int" ]] || eval "$previous_int"
  [[ -z "$previous_term" ]] || eval "$previous_term"
  if (( interrupted == 130 )); then
    kill -INT "$$"
  elif (( interrupted == 143 )); then
    kill -TERM "$$"
  fi
  return 0
}

ui_finalize_collections() {
  (( ui_finalization_attempted == 0 )) || return "$ui_finalization_status"
  ui_finalization_attempted=1
  collect_ui_evidence
  if [[ "$platform" == "macos" ]]; then
    ui_finalization_step cleanup cleanup_macos_run
  fi
  python3 - "$out/ui-finalization.tsv" "$out/ui-finalization.json" <<'PY'
import json, pathlib, sys
source, output = map(pathlib.Path, sys.argv[1:])
steps = []
if source.exists():
    for line in source.read_text().splitlines():
        name, code = line.split("\t")
        steps.append({"step": name, "exitCode": int(code)})
output.write_text(json.dumps({"schemaVersion": 1, "steps": steps,
                             "status": "failed" if any(s["exitCode"] for s in steps) else "passed"},
                            indent=2, sort_keys=True) + "\n")
PY
  local receipt_status=$?
  (( receipt_status == 0 )) || ui_finalization_status=1
  return "$ui_finalization_status"
}

# Preserve an original product failure or signal exit. Evidence/restoration
# failure changes only otherwise-successful execution to failure.
ui_final_exit_status() {
  local original="$1" collection="$2"
  if (( original != 0 )); then
    printf '%s\n' "$original"
  elif (( collection != 0 )); then
    printf '1\n'
  else
    printf '0\n'
  fi
}
