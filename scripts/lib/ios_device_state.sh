# Physical-iPhone CoreDevice readiness probe.
# Verdicts:
#   READY                0  — paired device is reachable for development
#   DEVICE_UNREACHABLE  14  — CoreDevice cannot reach the paired device

# shellcheck shell=bash

DEVICE_STATE_PROBE_PY="${ROOT_DIR:?}/scripts/lib/ios_coredevice_probe.py"

probe_device_state() {
  local dev="${1:-}" core_json reachable
  core_json="$(python3 "$DEVICE_STATE_PROBE_PY" probe ${dev:+--device "$dev"})"
  reachable="$(python3 -c 'import json,sys; print("1" if json.load(sys.stdin).get("reachable") else "0")' <<<"$core_json")"
  if [[ "$reachable" == "1" ]]; then
    printf '%s\n' "READY|paired physical iPhone is reachable"
  else
    printf '%s\n' "DEVICE_UNREACHABLE|resume the connection, then unlock and trust the paired iPhone"
  fi
}

probe_device_state_json() {
  local dev="${1:-}" core_json line verdict detail
  core_json="$(python3 "$DEVICE_STATE_PROBE_PY" probe ${dev:+--device "$dev"})"
  line="$(probe_device_state "$dev")"
  verdict="${line%%|*}"
  detail="${line#*|}"
  DEVICE_STATE_CORE="$core_json" DEVICE_STATE_VERDICT="$verdict" \
  DEVICE_STATE_DETAIL="$detail" python3 <<'PY'
import json, os
core = json.loads(os.environ["DEVICE_STATE_CORE"])
verdict = os.environ["DEVICE_STATE_VERDICT"]
print(json.dumps({
    "verdict": verdict,
    "detail": os.environ["DEVICE_STATE_DETAIL"],
    "confidence": "high",
    "advice": (
        "safe to run physical-device operations" if verdict == "READY"
        else "resume the connection, then unlock and trust the paired iPhone"
    ),
    "probeVersion": 4,
    "signals": {"coredevice": core},
}, indent=2))
PY
}

device_state_exit_code() {
  case "$1" in
    READY) echo 0 ;;
    DEVICE_UNREACHABLE) echo 14 ;;
    *) echo 1 ;;
  esac
}

device_state_advice() {
  case "$1" in
    READY) echo "safe to run physical-device operations" ;;
    DEVICE_UNREACHABLE) echo "resume the connection, then unlock and trust the paired iPhone" ;;
    *) echo "check the paired physical iPhone" ;;
  esac
}

probe_device_state_watch() {
  local dev="${1:-}" interval="${2:-2}" count="${3:-3}"
  local i verdict last="" samples=0 final_line=""
  for (( i = 0; i < count; i++ )); do
    final_line="$(probe_device_state "$dev")"
    verdict="${final_line%%|*}"
    if [[ "$verdict" == "$last" ]]; then samples=$((samples + 1)); else last="$verdict"; samples=1; fi
    (( i + 1 < count )) && sleep "$interval"
  done
  printf '%s\n' "$final_line"
  (( samples >= 2 )) || return 1
  return "$(device_state_exit_code "$verdict")"
}

guard_device_state() {
  local dev="${1:-}" line verdict
  line="$(probe_device_state "$dev")"
  verdict="${line%%|*}"
  [[ "$verdict" == "READY" ]] && return 0
  printf '\033[0;31m[device-state]\033[0m %s — %s (%s)\n' \
    "$verdict" "$(device_state_advice "$verdict")" "${line#*|}" >&2
  return "$(device_state_exit_code "$verdict")"
}


# --- Device-lane helpers shared with the tests (sourced, never sliced by text) ---

# Canonical benchmark cell for a `<mode>:<variant>:<text>` launch spec.
device_benchmark_cell() {
  local spec="$1"
  local mode="${spec%%:*}"
  local remainder="${spec#*:}"
  local variant="${remainder%%:*}"
  printf '%s/%s/device' "$mode" "$variant"
}

# Reads `xcrun xctrace list devices` on stdin: prints the UDID and exits 0 when the
# device is online, exits 20 when it is listed offline, 21 when it is absent.
xctrace_inventory_status() {
  local udid="$1"
  python3 -c '
import sys
udid = sys.argv[1]
section = None
for raw in sys.stdin:
    line = raw.replace("\u00a0", " ").strip()
    if line == "== Devices ==":
        section = "online"
        continue
    if line == "== Devices Offline ==":
        section = "offline"
        continue
    if line.startswith("== "):
        section = None
        continue
    if f"({udid})" not in line:
        continue
    if section == "online":
        print(udid)
        raise SystemExit(0)
    if section == "offline":
        raise SystemExit(20)
raise SystemExit(21)
' "$udid"
}

# A device-diagnostics sentinel counts only when it completed and saw no app-lifecycle
# interruption: exit 1 on a failed run, 2 on an interrupted one.
require_uninterrupted_success_sentinel() {
  local sentinel="$1"
  python3 - "$sentinel" <<'PY'
import json
import sys

record = json.load(open(sys.argv[1]))
if record.get("status") != "ok":
    print(f"sentinel status is {record.get('status')!r}: {record.get('error')}", file=sys.stderr)
    raise SystemExit(1)
interruptions = record.get("interruptions") or []
if interruptions:
    kinds = ", ".join(str(event.get("type") or "unknown") for event in interruptions)
    print(f"sentinel contains {len(interruptions)} interruption(s): {kinds}", file=sys.stderr)
    raise SystemExit(2)
PY
}
