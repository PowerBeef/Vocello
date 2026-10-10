#!/usr/bin/env bash
# The sourcing runner owns out/platform and consumes last_status.
# shellcheck disable=SC2154,SC2034
# Best-effort collectors are isolated: a callback's exit/die cannot end the
# runner's EXIT trap or replace the native command's status.
ui_finalization_attempted=0
ui_finalization_status=0
ui_finalization_last_status=0

ui_finalization_step() {
  local name="$1" status=0
  shift
  if (trap - EXIT INT TERM; set +e; "$@") >>"$out/ui-finalization.log" 2>&1; then
    status=0
  else
    status=$?
    ui_finalization_status=1
  fi
  ui_finalization_last_status="$status"
  printf '%s\t%s\n' "$name" "$status" >>"$out/ui-finalization.tsv"
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
