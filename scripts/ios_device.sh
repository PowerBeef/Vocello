#!/usr/bin/env bash
# On-device iPhone build/test driver for Vocello — CoreDevice via `devicectl`.
# Repository scripts own build, launch, telemetry, crash, and physical-device proof.
#
# Pairs with IOSDeviceDiagnosticsRunner (Sources/iOS/IOSDeviceDiagnosticsRunner.swift): `bench`
# launches the app with QVOICE_IOS_DEVICE_DIAGNOSTICS_SPEC set, the in-app runner
# performs one non-UI generation and writes a completion sentinel + telemetry into the
# App-Group container, and this script pulls them back and summarizes.
#
# Privacy: the signing team is DERIVED AT RUNTIME from the local keychain (the OU of
# the "Apple Development" cert) — never hardcoded/committed; $QWENVOICE_DEVELOPMENT_TEAM
# overrides. The device is auto-discovered, or pinned via $QVOICE_IOS_DEVICE_ID —
# neither is committed. Signing uses automatic provisioning by default and falls back
# to OFFLINE manual signing (the already-installed dev profile + the Apple Development
# identity) when no Apple ID is signed into Xcode — so no account login is needed.
#
# Usage:
#   scripts/ios_device.sh doctor                  # environment + device preflight
#   scripts/ios_device.sh build                   # signed device build (-Onone)
#   scripts/ios_device.sh install                 # install the built app
#   scripts/ios_device.sh launch [spec]           # launch (with device diagnostics if spec given)
#   scripts/ios_device.sh console [spec] [--voice-id SAVED_VOICE_ID]
#                                                 # attached launch, stream diagnostics stdout live
#   scripts/ios_device.sh pull [dest]             # pull the app-container diagnostics mirror
#   scripts/ios_device.sh bench [spec] [--label RUN_ID] [--memory-profile PROFILE]
#                               [--voice-id SAVED_VOICE_ID]
#   scripts/ios_device.sh lang-bench [--subset quick|full] [--label RUN_ID]
#                               [--diagnostic-cohort[=PATH]]
#                                                 # headless language/output matrix; optional
#                                                 # fixed-seed diagnostic cohort never publishes history
#   scripts/ios_device.sh delivery-reliability --plan PLAN.json --script-file SCRIPT.txt
#                                                 # governed Built-in Voice startup characterization
#   scripts/ios_device.sh speech-assets           # resolve/install DE/ES/JA/ZH DictationTranscriber
#   scripts/ios_device.sh enroll-clone-fixture --wav W.wav --transcript W.txt  # headless fixture voice enrollment
#                                                 # assets and recheck Vocello's legacy Speech readiness
#   scripts/ios_device.sh crashes [--test]         # pull + symbolicate on-device crash/hang diagnostics (MetricKit)
#   scripts/ios_device.sh debug [spec]             # attached launch + LLDB attach guidance (get-task-allow build)
#   scripts/ios_device.sh logs [spec] [--voice-id SAVED_VOICE_ID]
#                                                 # attached launch teeing stdout → build/artifacts/diagnostics/ios/logs/<run>.log
#   scripts/ios_device.sh profile [--kind cpu|memory] [--keep-trace] [spec]
#                                                 # exact-PID Instruments diagnostic generation
#   scripts/ios_device.sh memory --voice-id SAVED_VOICE_ID [--label ID]
#                                                 # one-process retained-memory qualification
#   scripts/ios_device.sh clone-conditioning [--label ID]
#                                                 # local-only transcript-backed vs x-vector proof
#   scripts/ios_device.sh memory-field-report [pulled-diagnostics]
#                                                 # local-only delayed MetricKit summary; never contacts phone
#   scripts/ios_device.sh preflight                # paired-device, signing, build, and dSYM readiness
#   scripts/ios_device.sh device-state [--json|--json-v2] [watch [--interval N] [--count N]]
#                                                 # paired-device reachability and lock state
#   scripts/ios_device.sh gate                 # explicit device gate: preflight → generation → crashes → verdict
#                                              # (generation needs Speed on device; QVOICE_GATE_SKIP_GENERATION=1 to skip)
#
# Device diagnostics spec: <mode>:<variant>:<text> (default custom:speed:<built-in sentence>).
#   mode ∈ custom|design|clone, variant ∈ speed|quality (iPhone is speed-only).
#
# Env:
#   QWENVOICE_DEVELOPMENT_TEAM   (optional) Apple team id; auto-derived from the keychain
#                                Apple Development cert OU when unset
#   QVOICE_IOS_MANUAL_SIGN       (optional) set to 1 to force offline manual signing
#                                (otherwise automatic, with auto-fallback to manual)
#   QVOICE_IOS_DEVICE_ID         (optional) devicectl device id/name/udid; else auto
#   QVOICE_IOS_BENCH_TIMEOUT     (optional) bench sentinel timeout seconds (default 300)
#   QVOICE_IOS_SPEECH_ASSET_TIMEOUT
#                                (optional) Speech asset bootstrap timeout seconds (default 1800)
#   QVOICE_IOS_PROFILE_START_TIMEOUT
#                                (optional) maximum tracer-start wait seconds (default 30)
#   QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID
#                                exact prepared saved-voice identifier required for clone diagnostics

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
. "$ROOT_DIR/scripts/lib/build_paths.sh"
. "$ROOT_DIR/scripts/lib/required_steps.sh"
. "$ROOT_DIR/scripts/lib/test_models.sh"

SCHEME="VocelloiOS"
CONFIG="Release"
BUNDLE_ID="com.patricedery.vocello"
APP_GROUP="group.com.patricedery.vocello.shared"
# Single shared physical-device iOS compilation cache. Retained evidence is
# always written below build/artifacts instead of being mixed into this tree.
DERIVED="$QVOICE_XCODE_IOS_DERIVED"
APP_PATH="$DERIVED/Build/Products/Release-iphoneos/Vocello.app"
PROJECT="$ROOT_DIR/QwenVoice.xcodeproj"
PROFILES_DIR="$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles"

# Reuse the shared storage-bloat advisory (warn-only; never deletes).
. "$ROOT_DIR/scripts/lib/build_cache.sh"
. "$ROOT_DIR/scripts/lib/ios_device_state.sh"

note() { printf '\033[0;36m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[0;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

uuid_set() {
  /usr/bin/dwarfdump --uuid "$1" 2>/dev/null \
    | awk '{ print toupper($2) }' \
    | LC_ALL=C sort -u
}

validate_dsym_identity() {
  local binary="$1" dsym="$2"
  local dwarf="$dsym/Contents/Resources/DWARF/Vocello"
  [[ -f "$binary" ]] || die "cannot validate dSYM: missing Mach-O $binary"
  [[ -f "$dwarf" ]] || die "cannot validate dSYM: missing DWARF binary $dwarf"
  local binary_uuids dsym_uuids
  binary_uuids="$(uuid_set "$binary")"
  dsym_uuids="$(uuid_set "$dwarf")"
  [[ -n "$binary_uuids" && "$binary_uuids" == "$dsym_uuids" ]] \
    || die "dSYM UUID mismatch for $binary (binary=${binary_uuids:-none}, dsym=${dsym_uuids:-none})"
}

validate_benchmark_label() {
  local value="$1"
  [[ -z "$value" || "$value" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$ ]] \
    || die "--label must be an opaque 1-96 character ID using letters, digits, dot, underscore, or hyphen"
}

benchmark_nonce() {
  python3 -c 'import secrets; print(secrets.token_hex(4))'
}

# Canonical history/telemetry cell for every one-take physical-device diagnostic.
# The publisher reconstructs this same identity from the successful sentinel.
device_benchmark_cell() {
  local spec="$1"
  local mode="${spec%%:*}"
  local remainder="${spec#*:}"
  local variant="${remainder%%:*}"
  printf '%s/%s/device' "$mode" "$variant"
}

capture_benchmark_source() {
  local artifacts="$1"
  local crash_before="$artifacts/crash-before"
  local dev
  dev="$(resolve_device)"
  mkdir -p "$crash_before"
  xcrun devicectl device copy from --device "$dev" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source "Library/Caches/Vocello/diagnostics" --destination "$crash_before" \
    >"$artifacts/crash-before-pull.log" 2>&1 \
    || die "could not establish the pre-run iOS crash baseline (see $artifacts/crash-before-pull.log)"
  python3 "$ROOT_DIR/scripts/publish_benchmark_history.py" snapshot \
    --output "$artifacts/benchmark-source.json" --crash-scope ios \
    --crash-diagnostics "$crash_before" >/dev/null \
    || die "could not capture pre-run benchmark provenance"
}

record_benchmark_history() {
  local artifacts="$1"
  python3 "$ROOT_DIR/scripts/benchmark_history.py" record --artifact-dir "$artifacts" || {
    warn "benchmark passed, but history publication failed; evidence is preserved in $artifacts"
    warn "repair: python3 scripts/benchmark_history.py record --artifact-dir '$artifacts'"
    return 1
  }
}

# Bash 3.2 unwinds function-local variables before an EXIT trap executes. Keep
# the one active physical-device profile's owned process/retention state in
# explicit globals so failure cleanup can still terminate the exact PID.
PROFILE_TRACE_ACTIVE=0
PROFILE_TRACE_PUBLISHED=0
PROFILE_TRACE_KIND=""
PROFILE_TRACE_PHASE=""
PROFILE_TRACE_ARTIFACTS=""
PROFILE_TRACE_PATH=""
PROFILE_TRACE_XCTRACE_PID=""
PROFILE_TRACE_DEVICE_CLEANUP=""

profile_failure_cleanup() {
  local status=$?
  trap - EXIT
  set +e
  [[ -z "$PROFILE_TRACE_XCTRACE_PID" ]] \
    || kill "$PROFILE_TRACE_XCTRACE_PID" >/dev/null 2>&1 || true
  [[ -z "$PROFILE_TRACE_DEVICE_CLEANUP" ]] || eval "$PROFILE_TRACE_DEVICE_CLEANUP"
  if (( status != 0 && PROFILE_TRACE_ACTIVE == 1 && PROFILE_TRACE_PUBLISHED == 0 )); then
    python3 "$ROOT_DIR/scripts/lib/profile_trace_retention.py" mark-failure \
      --root "$ROOT_DIR" --platform ios --kind "$PROFILE_TRACE_KIND" \
      --artifact-dir "$PROFILE_TRACE_ARTIFACTS" --trace "$PROFILE_TRACE_PATH" \
      --phase "$PROFILE_TRACE_PHASE" --exit-code "$status" >/dev/null \
      || warn "could not compact older failed $PROFILE_TRACE_KIND profile traces"
  fi
  exit "$status"
}

# device-state [--json|--json-v2] [watch [--interval N] [--count N]]
# Exit codes: 0 READY · 14 DEVICE_UNREACHABLE.
cmd_device_state() {
  local as_json=0 json_v2=0 watch=0 interval=2 count=3
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) as_json=1; shift ;;
      --json-v2) as_json=1; json_v2=1; shift ;;
      watch) watch=1; shift ;;
      --interval) interval="${2:?}"; shift 2 ;;
      --count) count="${2:?}"; shift 2 ;;
      *) die "unknown device-state flag: $1" ;;
    esac
  done

  local dev; dev="$(resolve_device 2>/dev/null || true)"

  if (( watch )); then
    local line verdict detail
    line="$(probe_device_state_watch "$dev" "$interval" "$count")"
    verdict="${line%%|*}"
    detail="${line#*|}"
    if (( as_json && json_v2 )); then
      probe_device_state_json "$dev"
    elif (( as_json )); then
      VERDICT="$verdict" DETAIL="$detail" ADVICE="$(device_state_advice "$verdict")" python3 -c '
import json, os
print(json.dumps({"verdict": os.environ["VERDICT"], "detail": os.environ["DETAIL"], "advice": os.environ["ADVICE"], "probeVersion": 1}))'
    else
      note "device state (watch): $verdict — $detail"
      note "  $(device_state_advice "$verdict")"
    fi
    exit "$(device_state_exit_code "$verdict")"
  fi

  if (( as_json && json_v2 )); then
    probe_device_state_json "$dev"
    local line verdict
    line="$(probe_device_state "$dev")"
    verdict="${line%%|*}"
    exit "$(device_state_exit_code "$verdict")"
  fi

  local line verdict detail
  line="$(probe_device_state "$dev")"
  verdict="${line%%|*}"
  detail="${line#*|}"
  if (( as_json )); then
    VERDICT="$verdict" DETAIL="$detail" ADVICE="$(device_state_advice "$verdict")" python3 -c '
import json, os
print(json.dumps({
    "verdict": os.environ["VERDICT"],
    "detail": os.environ["DETAIL"],
    "advice": os.environ["ADVICE"],
    "probeVersion": 1,
}))'
  else
    note "device state: $verdict — $detail"
    note "  $(device_state_advice "$verdict")"
  fi
  exit "$(device_state_exit_code "$verdict")"
}

# ─── Code signing (all values DERIVED AT RUNTIME; never hardcoded/committed) ──────
# Team id = the OU of the keychain "Apple Development" cert. NOTE: the team is the
# cert's OU, NOT the parenthetical in its CN ("Apple Development: …(XXXXXXXXXX)") —
# that parenthetical is a per-developer identifier; mistaking it for the team yields
# "No Account for Team …". $QWENVOICE_DEVELOPMENT_TEAM overrides if set.
derive_team() {
  if [[ -n "${QWENVOICE_DEVELOPMENT_TEAM:-}" ]]; then
    printf '%s' "$QWENVOICE_DEVELOPMENT_TEAM"; return 0
  fi
  local t
  t="$(security find-certificate -c "Apple Development" -p 2>/dev/null \
        | openssl x509 -noout -subject 2>/dev/null \
        | grep -oE 'OU=[A-Z0-9]+' | head -1 | cut -d= -f2)"
  [[ -n "$t" ]] || return 1
  export QWENVOICE_DEVELOPMENT_TEAM="$t"
  printf '%s' "$t"
}

require_team() {
  derive_team >/dev/null \
    || die "no signing team — set QWENVOICE_DEVELOPMENT_TEAM=<apple-team-id>, or install an 'Apple Development' certificate (Xcode → Settings → Accounts) so it can be auto-derived from the keychain"
}

# Echo the NAME of the installed *development* provisioning profile (get-task-allow=true)
# whose application-identifier == <team>.<BUNDLE_ID>. Empty if none. Lets manual signing
# reuse an already-present profile with zero Apple-account round-trip.
find_dev_profile_name() {
  local team="$1"
  [[ -d "$PROFILES_DIR" ]] || return 0
  local f plist appid gta name
  for f in "$PROFILES_DIR"/*.mobileprovision; do
    [[ -e "$f" ]] || continue
    plist="$(security cms -D -i "$f" 2>/dev/null)" || continue
    gta="$(/usr/libexec/PlistBuddy -c 'Print :Entitlements:get-task-allow' /dev/stdin <<<"$plist" 2>/dev/null)"
    [[ "$gta" == "true" ]] || continue
    appid="$(/usr/libexec/PlistBuddy -c 'Print :Entitlements:application-identifier' /dev/stdin <<<"$plist" 2>/dev/null)"
    if [[ "$appid" == "$team.$BUNDLE_ID" ]]; then
      name="$(/usr/libexec/PlistBuddy -c 'Print :Name' /dev/stdin <<<"$plist" 2>/dev/null)"
      [[ -n "$name" ]] && { printf '%s' "$name"; return 0; }
    fi
  done
  return 0
}

# Populate SIGN_ARGS for xcodebuild. auto = automatic signing + provisioning updates
# (needs the Apple ID present in Xcode). manual = the installed dev profile + the
# Apple Development identity, fully offline (no Apple-account contact).
SIGN_ARGS=()
build_sign_args() {
  local mode="$1" team="$2"
  if [[ "$mode" == manual ]]; then
    local prof; prof="$(find_dev_profile_name "$team")"
    [[ -n "$prof" ]] || die "manual signing: no installed development profile for $team.$BUNDLE_ID (generate one once via Xcode, or unset QVOICE_IOS_MANUAL_SIGN to use automatic signing)"
    note "manual signing → profile: $prof"
    SIGN_ARGS=(
      DEVELOPMENT_TEAM="$team"
      CODE_SIGN_STYLE=Manual
      PROVISIONING_PROFILE_SPECIFIER="$prof"
      CODE_SIGN_IDENTITY="Apple Development"
    )
  else
    SIGN_ARGS=(
      -allowProvisioningUpdates
      DEVELOPMENT_TEAM="$team"
      CODE_SIGN_STYLE=Automatic
    )
  fi
}

# Resolve the target device id. Prefer $QVOICE_IOS_DEVICE_ID; otherwise auto-pick a
# connected/paired CoreDevice (prefers "iPhone 17 Pro" when multiple are paired).
resolve_device() {
  if [[ -n "${QVOICE_IOS_DEVICE_ID:-}" ]]; then
    printf '%s' "$QVOICE_IOS_DEVICE_ID"
    return
  fi
  local tmp; tmp="$(mktemp)"
  xcrun devicectl list devices --json-output "$tmp" >/dev/null 2>&1 \
    || die "devicectl could not list devices (is Xcode 26 installed?)"
  local id
  id="$(python3 - "$tmp" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
devs = (data.get("result") or {}).get("devices") or []
def connected(d):
    cp = d.get("connectionProperties") or {}
    return cp.get("pairingState") == "paired" or cp.get("tunnelState") in ("connected", "available")
cands = [d for d in devs if connected(d)]
if not cands:
    sys.exit(3)
preferred = "iPhone 17 Pro"
for d in cands:
    props = d.get("deviceProperties") or {}
    if props.get("name") == preferred:
        print(d.get("identifier", ""))
        sys.exit(0)
if len(cands) == 1:
    print(cands[0].get("identifier", ""))
else:
    for d in cands:
        props = d.get("deviceProperties") or {}
        sys.stderr.write(f"  {d.get('identifier')}  {props.get('name','?')}\n")
    sys.exit(4)
PY
)" || {
    local code=$?
    rm -f "$tmp"
    [[ $code -eq 3 ]] && die "no paired iPhone found — connect via USB + trust this Mac, or set QVOICE_IOS_DEVICE_ID"
    [[ $code -eq 4 ]] && die "multiple devices found (above) — set QVOICE_IOS_DEVICE_ID to one"
    die "device discovery failed"
  }
  rm -f "$tmp"
  [[ -n "$id" ]] || die "could not resolve a device id"
  printf '%s' "$id"
}

# xctrace and CoreDevice intentionally expose different identifiers for the
# same physical phone. Resolve the Instruments UDID from CoreDevice's stable
# JSON, then require that xctrace currently lists it in the online Devices
# section before the profile lane launches or suspends Vocello.
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

resolve_xctrace_device() {
  local dev="$1"
  local details inventory
  details="$(mktemp)"
  inventory="$(mktemp)"
  xcrun devicectl device info details --device "$dev" \
    --json-output "$details" --quiet >/dev/null 2>&1 \
    || { rm -f "$details" "$inventory"; die "could not resolve the physical iPhone for Instruments"; }
  local udid
  udid="$(python3 - "$details" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
udid = (((payload.get("result") or {}).get("hardwareProperties") or {}).get("udid") or "")
if not udid:
    raise SystemExit(1)
print(udid)
PY
)" || { rm -f "$details" "$inventory"; die "CoreDevice did not report an Instruments UDID"; }
  xcrun xctrace list devices >"$inventory" 2>&1 \
    || { rm -f "$details" "$inventory"; die "xctrace could not list Instruments devices"; }
  local result status=0
  result="$(xctrace_inventory_status "$udid" <"$inventory")" || status=$?
  rm -f "$details" "$inventory"
  case "$status" in
    0) printf '%s' "$result" ;;
    20) die "Instruments sees the paired iPhone as offline — reconnect/unlock it and wait until 'xcrun xctrace list devices' shows it under Devices" ;;
    21) die "the paired iPhone is absent from Instruments — reconnect it and confirm Xcode device services before profiling" ;;
    *) die "could not match the CoreDevice phone to an Instruments device" ;;
  esac
}

cmd_doctor() {
  note "Vocello iOS device doctor"
  command -v xcrun >/dev/null || die "xcrun not found (install Xcode)"
  printf '  xcode: %s\n' "$(xcodebuild -version 2>/dev/null | head -1)" >&2
  require_ios_xcode_platform || die "selected Xcode lacks usable iOS Platform Support"
  local team_d
  if team_d="$(derive_team 2>/dev/null)" && [[ -n "$team_d" ]]; then
    local src="keychain"; [[ -n "${QWENVOICE_DEVELOPMENT_TEAM:-}" ]] && src="env"
    printf '  team:  %s (%s)\n' "$team_d" "$src" >&2
  else
    warn "no signing team — set QWENVOICE_DEVELOPMENT_TEAM, or add an Apple Development cert (Xcode → Settings → Accounts)"
  fi
  local dev; dev="$(resolve_device)"
  printf '  device: %s\n' "$dev" >&2
  if [[ -d "$APP_PATH" ]]; then
    printf '  app:   built (%s)\n' "$APP_PATH" >&2
    local ent; ent="$(codesign -d --entitlements :- "$APP_PATH" 2>/dev/null || true)"
    if grep -q 'application-groups' <<<"$ent"; then
      printf '  app group: OK (%s)\n' "$APP_GROUP" >&2
    else
      warn "app group missing from signed app — rebuild after fixing CODE_SIGN_ENTITLEMENTS (run: $0 build)"
    fi
    if grep -q 'increased-memory-limit' <<<"$ent"; then
      printf '  increased-memory-limit: OK\n' >&2
    else
      warn "increased-memory-limit missing from signed app"
    fi
  else
    printf '  app:   not built yet (run: %s build)\n' "$0" >&2
  fi
  note "doctor OK"
}

cmd_build() {
  require_ios_xcode_platform || die "iOS build is blocked by the selected Xcode toolchain"
  require_build_free_space device-build || die "iOS build storage preflight failed"
  local diagnostics_build=0
  case "${1:-}" in
    --device-diagnostics|--device-diagnostics-crash-test)
      diagnostics_build=1
      shift
      ;;
  esac
  [[ $# -eq 0 ]] || die "unknown build argument: $1"
  require_team
  ensure_project_regenerated
  ensure_spm_resolved "$QVOICE_SCRATCH_PACKAGE_RESOLUTION" \
    "$QVOICE_XCODE_SOURCE_PACKAGES" ios-device VocelloiOS Release \
    'generic/platform=iOS'
  local team; team="$(derive_team)"
  local dev; dev="$(resolve_device)"
  local producer="scripts/ios_device.sh build"
  (( diagnostics_build == 0 )) || producer+=" --device-diagnostics"
  note "building $SCHEME ($CONFIG, -Onone) for $dev (team $team)"
  mkdir -p "$DERIVED"
  local log="$DERIVED/device-build.log"

  local mode="auto"
  [[ "${QVOICE_IOS_MANUAL_SIGN:-}" == "1" ]] && mode="manual"

  _run_device_build() {
    build_sign_args "$1" "$team"
    local -a command=(
      xcb_run
      -project "$PROJECT" -scheme "$SCHEME" -configuration "$CONFIG"
      -destination "id=$dev" -derivedDataPath "$DERIVED"
      -clonedSourcePackagesDirPath "$QVOICE_XCODE_SOURCE_PACKAGES"
      -disableAutomaticPackageResolution
      -onlyUsePackageVersionsFromResolvedFile
      "${SIGN_ARGS[@]}"
    )
    if (( diagnostics_build )); then
      command+=('OTHER_SWIFT_FLAGS=$(inherited) -DQVOICE_DEVICE_DIAGNOSTICS')
    fi
    command+=(
      ARCHS=arm64 ONLY_ACTIVE_ARCH=YES
      SWIFT_OPTIMIZATION_LEVEL=-Onone SWIFT_COMPILATION_MODE=incremental
      build
    )
    set +e
    "${command[@]}" 2>&1 | tee "$log"
    local st=${PIPESTATUS[0]}; set -e; return $st
  }

  if _run_device_build "$mode"; then
    :
  elif [[ "$mode" == auto ]] \
       && grep -qiE "No Account for Team|requires a development team|No profiles for|No signing certificate|Provisioning profile" "$log"; then
    warn "automatic signing failed (Apple ID likely not signed into Xcode) — retrying offline with the installed development profile"
    _run_device_build manual || die "manual-signing build also failed (see $log)"
  else
    die "device build failed (see $log)"
  fi

  [[ -d "$APP_PATH" ]] || die "build finished but $APP_PATH is missing"
  write_build_provenance "$DERIVED/last-build.json" \
    "$producer" "$SCHEME" "$CONFIG" "id=$dev" arm64 \
    Onone "$mode" "$DERIVED" "$QVOICE_XCODE_SOURCE_PACKAGES"

  # Preserve this build's dSYM so `crashes` can symbolicate MetricKit/.ips payloads.
  local dsym_src="$DERIVED/Build/Products/Release-iphoneos/Vocello.app.dSYM"
  if [[ -d "$dsym_src" ]]; then
    local dsym_dst="$QVOICE_SYMBOLS_IOS/Vocello.app.dSYM"
    preserve_ios_dsym "$dsym_src" "$dsym_dst" "$APP_PATH/Vocello"
    /usr/libexec/PlistBuddy -c "Print :CFBundleVersion" "$APP_PATH/Info.plist" \
      > "$(dirname "$dsym_dst")/build-version.txt" 2>/dev/null || true
    write_build_provenance "$QVOICE_SYMBOLS_IOS/last-build.json" \
      "$producer" "$SCHEME" "$CONFIG" "id=$dev" arm64 \
      Onone "$mode" "$DERIVED" "$QVOICE_XCODE_SOURCE_PACKAGES"
    note "preserved dSYM → $dsym_dst (for crash symbolication)"
  else
    warn "no dSYM produced — crash symbolication won't be available for this build"
  fi

  note "built $APP_PATH"
  warn_if_storage_bloated
}

cmd_install() {
  [[ -d "$APP_PATH" ]] || die "no built app at $APP_PATH (run: $0 build)"
  local dev; dev="$(resolve_device)"
  note "installing on $dev"
  xcrun devicectl device install app --device "$dev" "$APP_PATH"
}

speech_asset_env_json() {
  local run_id="$1" locales="$2"
  QV_RUNID="$run_id" QV_LOCALES="$locales" python3 -c '
import json, os
print(json.dumps({
    "QWENVOICE_DEBUG": "1",
    "QVOICE_IOS_DEVICE_RUN_ID": os.environ["QV_RUNID"],
    "QVOICE_IOS_SPEECH_ASSET_LOCALES": os.environ["QV_LOCALES"],
}))'
}

pull_speech_asset_run() {
  local dev="$1" run_id="$2" destination="$3"
  rm -rf "$destination"
  mkdir -p "$destination"
  xcrun devicectl device copy from --device "$dev" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source "Library/Caches/Vocello/diagnostics/$run_id" \
    --destination "$destination" >/dev/null 2>&1
}

# Explicit, non-generation Speech bootstrap for the physical iPhone. AssetInventory's combined
# request installs only the four language-output locales and automatically manages this app's
# reservations. The result is local diagnostic evidence, never benchmark history.
# Headless benchmark clone-fixture enrollment. Replaces the retired Files-import UI
# path (the iPhone app deliberately ships no file import; users record with the
# microphone or reuse a Voice Design voice). Stages the exact reference WAV plus the
# mandatory transcript sidecar into the app's Documents, launches the app with
# QVOICE_IOS_DEVICE_ENROLL_VOICE_NAME, polls the enrollment sentinel, and reports the
# artifact identity. The runner deletes the staged inputs after a clean enrollment.
enroll_voice_env_json() {
  local run_id="$1" name="$2"
  QV_RUNID="$run_id" QV_NAME="$name" python3 -c '
import json, os
print(json.dumps({
    "QWENVOICE_DEBUG": "1",
    "QVOICE_IOS_DEVICE_RUN_ID": os.environ["QV_RUNID"],
    "QVOICE_IOS_DEVICE_ENROLL_VOICE_NAME": os.environ["QV_NAME"],
}))'
}

cmd_enroll_clone_fixture() {
  local wav="" transcript="" name=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --wav) wav="${2:?--wav requires a path}"; shift 2 ;;
      --wav=*) wav="${1#*=}"; shift ;;
      --transcript) transcript="${2:?--transcript requires a path}"; shift 2 ;;
      --transcript=*) transcript="${1#*=}"; shift ;;
      --name) name="${2:?--name requires a value}"; shift 2 ;;
      --name=*) name="${1#*=}"; shift ;;
      *) die "unknown flag: $1" ;;
    esac
  done
  [[ -n "$wav" && -f "$wav" ]] || die "enroll-clone-fixture requires --wav <existing .wav>"
  [[ -n "$transcript" && -f "$transcript" ]] \
    || die "enroll-clone-fixture requires --transcript <existing .txt> (transcript-backed identity is mandatory)"
  [[ -n "$name" ]] || name="$(basename "$wav" .wav)"

  local run_id="ios-enroll-voice-$(date -u +%Y%m%d-%H%M%S)-$(benchmark_nonce)"
  local artifacts="$QVOICE_ARTIFACTS_DIAGNOSTICS/ios/enroll-voice/$run_id"
  local pulled="$artifacts/pulled"
  local timeout="${QVOICE_IOS_ENROLL_TIMEOUT:-600}"
  [[ "$timeout" =~ ^[1-9][0-9]*$ ]] || die "QVOICE_IOS_ENROLL_TIMEOUT must be a positive integer"

  note "building and installing the exact Vocello app for fixture enrollment"
  cmd_build
  cmd_install >/dev/null

  local dev
  dev="$(resolve_device)"
  note "staging $name.wav + $name.txt into the app's Documents"
  xcrun devicectl device copy to --device "$dev" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source "$wav" --destination "Documents/$name.wav" >/dev/null
  xcrun devicectl device copy to --device "$dev" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source "$transcript" --destination "Documents/$name.txt" >/dev/null

  local env_json
  env_json="$(enroll_voice_env_json "$run_id" "$name")"
  note "enrolling '$name' through the headless diagnostics runner (runID=$run_id)"
  xcrun devicectl device process launch --device "$dev" --terminate-existing \
    -e "$env_json" "$BUNDLE_ID" >/dev/null

  local waited=0 sentinel=""
  while (( waited < timeout )); do
    sleep 5
    waited=$((waited + 5))
    if pull_speech_asset_run "$dev" "$run_id" "$pulled"; then
      sentinel="$(find "$pulled" -type f -name enroll-voice-done.json 2>/dev/null | head -1)"
      [[ -z "$sentinel" ]] || break
    fi
    local state verdict
    state="$(probe_device_state 2>/dev/null || true)"
    verdict="${state%%|*}"
    [[ "$verdict" != "DEVICE_UNREACHABLE" ]] \
      || die "fixture enrollment stopped at ${waited}s: $(device_state_advice "$verdict")"
  done
  [[ -n "$sentinel" && -f "$sentinel" ]] \
    || die "no enrollment completion evidence after ${timeout}s (runID=$run_id)"

  python3 - "$sentinel" <<'PY'
import json, sys
record = json.load(open(sys.argv[1]))
status = record.get("status")
print(f"enrollment status: {status}")
for key in ("requestedName", "voiceID", "stagedAudioSHA256", "stagedTranscriptSHA256",
            "qualityWarnings", "stagedInputsDeleted", "failureReason", "failureDescription"):
    value = record.get(key)
    if value is not None:
        print(f"  {key}: {value}")
if status != "pass":
    raise SystemExit(1)
PY

  note "enrollment evidence → $sentinel"
}

cmd_speech_assets() {
  [[ $# -eq 0 ]] || die "speech-assets accepts no arguments"
  local locales="de_DE,es_419,ja_JP,zh_CN"
  local run_id="ios-speech-assets-$(date -u +%Y%m%d-%H%M%S)-$(benchmark_nonce)"
  local artifacts="$QVOICE_ARTIFACTS_DIAGNOSTICS/ios/speech-assets/$run_id"
  local pulled="$artifacts/pulled"
  local timeout="${QVOICE_IOS_SPEECH_ASSET_TIMEOUT:-1800}"
  [[ "$timeout" =~ ^[1-9][0-9]*$ ]] \
    || die "QVOICE_IOS_SPEECH_ASSET_TIMEOUT must be a positive integer"

  note "building and installing the exact Vocello app for Speech asset bootstrap"
  cmd_build
  cmd_install >/dev/null

  local dev env_json
  dev="$(resolve_device)"
  env_json="$(speech_asset_env_json "$run_id" "$locales")"
  note "requesting DictationTranscriber assets for $locales (runID=$run_id)"
  xcrun devicectl device process launch --device "$dev" --terminate-existing \
    -e "$env_json" "$BUNDLE_ID" >/dev/null

  local waited=0 sentinel=""
  while (( waited < timeout )); do
    sleep 10
    waited=$((waited + 10))
    if pull_speech_asset_run "$dev" "$run_id" "$pulled"; then
      sentinel="$(find "$pulled" -type f -name speech-assets-done.json 2>/dev/null | head -1)"
      [[ -z "$sentinel" ]] || break
    fi
    local state verdict
    state="$(probe_device_state 2>/dev/null || true)"
    verdict="${state%%|*}"
    [[ "$verdict" != "DEVICE_UNREACHABLE" ]] \
      || die "Speech asset bootstrap stopped at ${waited}s: $(device_state_advice "$verdict")"
    if (( waited % 30 == 0 )); then
      note "…Speech assets still resolving/downloading (${waited}s, runID=$run_id)"
    fi
  done
  [[ -n "$sentinel" && -f "$sentinel" ]] \
    || die "no Speech asset completion evidence after ${timeout}s (runID=$run_id)"

  python3 "$ROOT_DIR/scripts/check_ios_speech_assets.py" "$sentinel" --run-id "$run_id"

  note "Speech asset evidence → $sentinel"
}

device_diagnostics_env_json() {
  local spec="$1" run_id="$2"
  QV_SPEC="$spec" QV_RUNID="$run_id" python3 -c '
import json, os
env = {
    "QWENVOICE_DEBUG": "1",
    "QVOICE_IOS_DEVICE_RUN_ID": os.environ["QV_RUNID"],
    "QVOICE_IOS_DEVICE_DIAGNOSTICS_SPEC": os.environ["QV_SPEC"],
}
for key, value in os.environ.items():
    if (key.startswith("QWENVOICE_") or key.startswith("QVOICE_")) and key not in env:
        env[key] = value
print(json.dumps(env))'
}

require_diagnostic_clone_voice() {
  local spec="$1"
  if [[ "$spec" == clone:* && -z "${QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID:-}" ]]; then
    die "clone diagnostics require --voice-id <exact-prepared-saved-voice-id>"
  fi
}

# A completed generation is not publishable when the app lost foreground ownership
# or CallKit observed an interruption. Keep this check in the runner script as a
# defense for sentinels produced by older installed builds that reported status=ok.
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

# launch [spec]: with a spec, set the non-UI diagnostics + telemetry env; otherwise, a plain launch.
# Optional QVOICE_LAUNCH_RUN_ID overrides the per-launch diagnostics run id (lang-bench).
cmd_launch() {
  local spec="${1:-}"
  local dev; dev="$(resolve_device)"
  if [[ -n "$spec" ]]; then
    require_diagnostic_clone_voice "$spec"
    local run_id="${QVOICE_LAUNCH_RUN_ID:-ios-$(date +%Y%m%d-%H%M%S)}"
    note "launching device diagnostics ($spec), runID=$run_id"
    local env_json
    # Benchmark A/B passthrough: any caller-set QWENVOICE_*/QVOICE_* tuning env
    # (e.g. QWENVOICE_STREAMING_PREVIEW_DATA=off, QWENVOICE_FORCE_MEMORY_CLASS)
    # is forwarded into the launched app's env so on-device benches are reproducible.
    env_json="$(device_diagnostics_env_json "$spec" "$run_id")"
    xcrun devicectl device process launch --device "$dev" \
      --terminate-existing -e "$env_json" "$BUNDLE_ID" >&2
    printf '%s\n' "$run_id"   # stdout: ONLY the runID (consumed by bench)
  else
    note "launching $BUNDLE_ID"
    xcrun devicectl device process launch --device "$dev" --terminate-existing "$BUNDLE_ID"
  fi
}

# console [spec]: launch ATTACHED with the device-diagnostics env and stream
# the app's stdout live. Blocks until the app exits / Ctrl-C.
# Best for diagnosing a failed bench — you watch exactly where the runner gets.
cmd_console() {
  local spec="custom:speed:Console device diagnostic."
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --voice-id) export QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID="${2:-}"; shift 2 ;;
      --voice-id=*) export QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID="${1#*=}"; shift ;;
      *) spec="$1"; shift ;;
    esac
  done
  [[ "$spec" == *:* ]] || spec="custom:speed:$spec"
  require_diagnostic_clone_voice "$spec"
  local dev; dev="$(resolve_device)"
  local run_id="ios-console-$(date +%Y%m%d-%H%M%S)"
  note "attached launch ($spec), runID=$run_id — Ctrl-C to detach"
  local env_json
  env_json="$(device_diagnostics_env_json "$spec" "$run_id")"
  xcrun devicectl device process launch --device "$dev" --console --terminate-existing \
    -e "$env_json" "$BUNDLE_ID"
}

# pull [dest]: copy the diagnostics mirror to the governed diagnostics artifact root.
# IMPORTANT: devicectl `copy from` can read the app's OWN data container
# (appDataContainer) but NOT the App-Group container — any App-Group source fails with
# a bogus "File paths cannot contain '..'". IOSDeviceDiagnosticsRunner mirrors the sentinel +
# engine telemetry to Library/Caches/Vocello/diagnostics in the app container, and we
# pull from there. devicectl copies the SOURCE DIR'S CONTENTS into dest.
cmd_pull() {
  local dest="${1:-$QVOICE_ARTIFACTS_DIAGNOSTICS/ios/device-diagnostics}"
  local dev; dev="$(resolve_device)"
  mkdir -p "$dest"
  note "pulling diagnostics from app container → $dest"
  # 1>&2: keep devicectl chatter off this function's stdout (reserved for the path).
  xcrun devicectl device copy from --device "$dev" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source "Library/Caches/Vocello/diagnostics" --destination "$dest" 1>&2 \
    || die "could not pull diagnostics (has a diagnostic run happened on THIS installed build?)"
  printf '%s\n' "$dest"
}

# wait_device_diagnostics_sentinel RUN_ID TIMEOUT DEST
# Polls pulled diagnostics until device-diagnostics-done.json exists for RUN_ID.
# Returns 0 and prints the sentinel path on success; dies on timeout/interference.
wait_device_diagnostics_sentinel() {
  local run_id="$1" timeout="${2:-300}" dest="$3"
  local waited=0 sentinel=""
  local interference_streak=0 interference_state=""
  while (( waited < timeout )); do
    sleep 10
    waited=$((waited + 10))
    cmd_pull "$dest" >/dev/null 2>&1 || true
    # Require RUN_ID to be the sentinel's immediate parent. Profile artifacts
    # also contain RUN_ID higher in their path, so a broad */RUN_ID/* match can
    # otherwise select an unrelated historical sentinel from the pulled tree.
    sentinel="$(find "$dest" -type f -path "*/${run_id}/device-diagnostics-done.json" 2>/dev/null | head -1)"
    if [[ -n "$sentinel" && -f "$sentinel" ]]; then
      note "sentinel found after ${waited}s (runID=$run_id)"
      printf '%s\n' "$sentinel"
      return 0
    fi
    local state verdict
    state="$(probe_device_state 2>/dev/null || true)"
    verdict="${state%%|*}"
    case "$verdict" in
      DEVICE_UNREACHABLE)
        die "run doomed at ${waited}s — $verdict: $(device_state_advice "$verdict") (${state#*|})"
        ;;
      *)
        interference_streak=0
        ;;
    esac
    note "…still generating (${waited}s / runID=$run_id)"
  done
  die "no sentinel after ${timeout}s for runID=$run_id — Device state: $(probe_device_state 2>/dev/null || echo unknown)"
}

# wait_memory_qualification_sentinel RUN_ID TIMEOUT DEST
# Same bounded physical-device polling contract as the single-take helper. The PASS result
# remains the only publishable barrier; a separate failure marker stops the wait promptly.
wait_memory_qualification_sentinel() {
  local run_id="$1" timeout="${2:-900}" dest="$3"
  local waited=0 sentinel="" failure=""
  while (( waited < timeout )); do
    sleep 10
    waited=$((waited + 10))
    cmd_pull "$dest" >/dev/null 2>&1 || true
    failure="$(find "$dest" -type f -path "*/${run_id}/memory-qualification-failure.json" 2>/dev/null | head -1)"
    if [[ -n "$failure" && -f "$failure" ]]; then
      if python3 - "$failure" "$run_id" <<'PY' >&2
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
expected_run_id = sys.argv[2]
if path.stat().st_size > 4096:
    raise SystemExit(1)
record = json.loads(path.read_text(encoding="utf-8"))
allowed = set((
    "schemaVersion", "status", "runID", "policyID", "failedAt", "failureCode",
    "completedTakeCount", "expectedTakeCount", "failedTakeIndex", "failedCell",
))
if set(record) - allowed:
    raise SystemExit(2)
if record.get("schemaVersion") != 1 or record.get("status") != "failed":
    raise SystemExit(3)
if record.get("runID") != expected_run_id:
    raise SystemExit(4)
print(
    "memory qualification failed "
    f"code={record.get('failureCode', 'unknown')} "
    f"completed={record.get('completedTakeCount', '?')}/{record.get('expectedTakeCount', '?')}"
)
PY
      then
        :
      else
        warn "memory qualification produced an invalid bounded failure marker: $failure"
      fi
      return 22
    fi
    sentinel="$(find "$dest" -type f -path "*/${run_id}/memory-qualification-result.json" 2>/dev/null | head -1)"
    if [[ -n "$sentinel" && -f "$sentinel" ]]; then
      note "memory qualification sentinel found after ${waited}s (runID=$run_id)"
      printf '%s\n' "$sentinel"
      return 0
    fi
    local state verdict
    state="$(probe_device_state 2>/dev/null || true)"
    verdict="${state%%|*}"
    [[ "$verdict" != "DEVICE_UNREACHABLE" ]] \
      || die "memory qualification doomed at ${waited}s: $(device_state_advice "$verdict")"
    note "…memory qualification still running (${waited}s / runID=$run_id)"
  done
  die "no memory-qualification-result.json after ${timeout}s for runID=$run_id"
}

# wait_clone_conditioning_sentinel RUN_ID TIMEOUT DEST
# Poll for the two-take PASS record. A bounded allowlisted failure marker stops the
# wait promptly but can never be mistaken for acceptance evidence.
wait_clone_conditioning_sentinel() {
  local run_id="$1" timeout="${2:-900}" dest="$3"
  local waited=0 sentinel="" failure=""
  while (( waited < timeout )); do
    sleep 10
    waited=$((waited + 10))
    cmd_pull "$dest" >/dev/null 2>&1 || true
    failure="$(find "$dest" -type f -path "*/${run_id}/clone-conditioning-failure.json" 2>/dev/null | head -1)"
    if [[ -n "$failure" && -f "$failure" ]]; then
      python3 - "$failure" "$run_id" <<'PY' >&2 || true
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
record = json.loads(path.read_text(encoding="utf-8"))
allowed = {
    "schemaVersion", "status", "runID", "failedAt", "failureCode",
    "completedTakeCount", "expectedTakeCount", "failedTakeIndex",
}
if path.stat().st_size > 4096 or set(record) - allowed:
    raise SystemExit(1)
if record.get("schemaVersion") != 1 or record.get("status") != "failed":
    raise SystemExit(2)
if record.get("runID") != sys.argv[2]:
    raise SystemExit(3)
print(
    "clone-conditioning acceptance failed "
    f"code={record.get('failureCode', 'unknown')} "
    f"completed={record.get('completedTakeCount', '?')}/2"
)
PY
      return 22
    fi
    sentinel="$(find "$dest" -type f -path "*/${run_id}/clone-conditioning-result.json" 2>/dev/null | head -1)"
    if [[ -n "$sentinel" && -f "$sentinel" ]]; then
      note "clone-conditioning sentinel found after ${waited}s (runID=$run_id)"
      printf '%s\n' "$sentinel"
      return 0
    fi
    local state verdict
    state="$(probe_device_state 2>/dev/null || true)"
    verdict="${state%%|*}"
    [[ "$verdict" != "DEVICE_UNREACHABLE" ]] \
      || die "clone-conditioning acceptance doomed at ${waited}s: $(device_state_advice "$verdict")"
    note "…clone-conditioning acceptance still running (${waited}s / runID=$run_id)"
  done
  die "no clone-conditioning-result.json after ${timeout}s for runID=$run_id"
}

# Poll the terminal record written last by IOSStartupReliabilityRunner. A typed
# harness-failure marker stops the poll, but never substitutes for a represented
# per-take result.
pull_startup_reliability_run() {
  local run_id="$1" destination="$2"
  local dev; dev="$(resolve_device)"
  local run_destination="$destination/$run_id"
  mkdir -p "$run_destination"
  xcrun devicectl device copy from --device "$dev" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source "Library/Caches/Vocello/diagnostics/$run_id" \
    --destination "$run_destination" --timeout 60 --quiet
}

# After host validation succeeds, relaunch the diagnostics build with a
# narrowly registered cleanup request. The app removes the collected run and
# generation-scoped WAV/codec artifacts from both containers, then writes a
# small privacy-safe acknowledgement outside the removed run directory.
cleanup_startup_reliability_device_evidence() {
  local run_id="$1" dev="$2" artifacts="$3"
  local env_json launch_json="$artifacts/cleanup-launch.json" cleanup_pid=""
  local cleanup_pull="$artifacts/cleanup-pull"
  env_json="$(python3 -c '
import json, sys
run_id = sys.argv[1]
print(json.dumps({
    "QWENVOICE_DEBUG": "1",
    "QWENVOICE_NATIVE_TELEMETRY_MODE": "verbose",
    "QVOICE_IOS_DEVICE_RUN_ID": run_id,
    "QVOICE_IOS_DEVICE_DELIVERY_RELIABILITY_CLEANUP_RUN_ID": run_id,
}, sort_keys=True))
' "$run_id")"
  xcrun devicectl device process launch --device "$dev" --terminate-existing \
    -e "$env_json" --json-output "$launch_json" "$BUNDLE_ID" \
    >"$artifacts/cleanup-launch.log" 2>&1 || return 1
  cleanup_pid="$(read_devicectl_launch_pid "$launch_json")" || return 1
  rm -f "$launch_json"
  [[ "$cleanup_pid" =~ ^[0-9]+$ ]] || return 1
  mkdir -p "$cleanup_pull"
  local waited=0 marker="$cleanup_pull/${run_id}.json"
  while (( waited < 30 )); do
    sleep 1
    waited=$((waited + 1))
    xcrun devicectl device copy from --device "$dev" \
      --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
      --source "Library/Caches/Vocello/diagnostics/cleanup/${run_id}.json" \
      --destination "$marker" --timeout 15 --quiet >/dev/null 2>&1 || true
    [[ -f "$marker" ]] || continue
    python3 - "$marker" "$run_id" <<'PY' || return 1
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
expected = {"schemaVersion": 1, "status": "collected_evidence_removed", "runID": sys.argv[2]}
raise SystemExit(0 if value == expected else 1)
PY
    cp "$marker" "$artifacts/device-evidence-cleanup.json"
    xcrun devicectl device process terminate --device "$dev" \
      --pid "$cleanup_pid" --quiet >/dev/null 2>&1 || true
    rm -rf "$cleanup_pull"
    return 0
  done
  xcrun devicectl device process terminate --device "$dev" \
    --pid "$cleanup_pid" --quiet >/dev/null 2>&1 || true
  return 1
}

# Query only the exact CoreDevice PID returned by the launch response. An empty
# successful result means that process has exited; a failed query is unknown and
# must not be mistaken for process death. The temporary inventory is never retained
# because it can contain host/device tool metadata unrelated to the governed run.
startup_reliability_process_is_alive() {
  local dev="$1" target_pid="$2" inventory
  [[ "$target_pid" =~ ^[0-9]+$ ]] || return 2
  inventory="$(mktemp)"
  if ! xcrun devicectl device info processes --device "$dev" \
      --filter "processIdentifier == $target_pid" \
      --json-output "$inventory" --quiet --timeout 15 >/dev/null 2>&1; then
    rm -f "$inventory"
    return 2
  fi
  local status=0
  python3 - "$inventory" "$target_pid" <<'PY' || status=$?
import json
import sys

try:
    payload = json.load(open(sys.argv[1], encoding="utf-8"))
    target = int(sys.argv[2])
    rows = (payload.get("result") or {}).get("runningProcesses") or []
except (OSError, TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(2)
raise SystemExit(0 if any(row.get("processIdentifier") == target for row in rows) else 1)
PY
  rm -f "$inventory"
  return "$status"
}

wait_startup_reliability_result() {
  local run_id="$1" timeout="$2" dest="$3" dev="$4" target_pid="$5"
  local waited=0 terminal="" failure=""
  while (( waited < timeout )); do
    sleep 10
    waited=$((waited + 10))
    pull_startup_reliability_run "$run_id" "$dest" >/dev/null 2>&1 || true
    terminal="$(find "$dest" -type f -path "*/${run_id}/startup-reliability-result.json" 2>/dev/null | head -1)"
    if [[ -n "$terminal" && -f "$terminal" ]]; then
      note "startup-reliability terminal found after ${waited}s (runID=$run_id)"
      printf '%s\n' "$terminal"
      return 0
    fi
    failure="$(find "$dest" -type f -path "*/${run_id}/startup-reliability-failure.json" 2>/dev/null | head -1)"
    if [[ -n "$failure" && -f "$failure" ]]; then
      warn "startup-reliability runner emitted a typed harness failure: $failure"
      return 22
    fi
    local state verdict
    state="$(probe_device_state 2>/dev/null || true)"
    verdict="${state%%|*}"
    [[ "$verdict" != "DEVICE_UNREACHABLE" ]] \
      || { warn "startup-reliability device became unreachable at ${waited}s"; return 23; }
    local process_status=0
    if startup_reliability_process_is_alive "$dev" "$target_pid"; then
      process_status=0
    else
      process_status=$?
    fi
    if (( process_status == 1 )); then
      warn "startup-reliability process exited before terminal evidence at ${waited}s"
      return 27
    fi
    (( process_status == 0 )) \
      || warn "startup-reliability exact-process liveness was temporarily unavailable at ${waited}s"
    note "…startup reliability still running (${waited}s / runID=$run_id)"
  done
  warn "no startup-reliability-result.json after ${timeout}s for runID=$run_id"
  return 24
}

snapshot_startup_reliability_crashes() {
  local destination="$1"
  local pulled="$destination/pull"
  local log="$destination/pull.log"
  local dev; dev="$(resolve_device)"
  mkdir -p "$pulled"
  if ! xcrun devicectl device copy from --device "$dev" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source "Library/Caches/Vocello/diagnostics/crashes" \
    --destination "$pulled" --timeout 30 --quiet >"$log" 2>&1; then
    if grep -Fq 'Failed to retrieve the file node for Library/Caches/Vocello/diagnostics/crashes' "$log" \
      && grep -Fq 'CoreDeviceError error 7000' "$log"; then
      : >"$destination/hashes.txt"
      rm -rf "$pulled"
      return 0
    fi
    warn "could not collect startup-reliability crash snapshot"
    return 1
  fi
  while IFS= read -r -d '' crash; do
    local hash
    hash="$(shasum -a 256 "$crash" | awk '{print $1}')"
    printf '%s\n' "$hash"
  done < <(find "$pulled" -type f -path '*/crashes/*' -print0 2>/dev/null) \
    | LC_ALL=C sort -u >"$destination/hashes.txt"
  rm -rf "$pulled"
}

# Snapshot CoreDevice's systemCrashLogs domain. Raw reports remain local and
# untracked; callers compare content hashes and sanitize only the new delta.
snapshot_startup_reliability_system_crashes() {
  local destination="$1"
  local pulled="$destination/pull"
  local dev; dev="$(resolve_device)"
  mkdir -p "$pulled"
  if ! xcrun devicectl device copy from --device "$dev" \
      --domain-type systemCrashLogs --source . --destination "$pulled" \
      --timeout 60 --quiet >"$destination/pull.log" 2>&1; then
    warn "could not collect CoreDevice systemCrashLogs snapshot"
    return 1
  fi
  while IFS= read -r -d '' crash; do
    local hash
    hash="$(shasum -a 256 "$crash" | awk '{print $1}')"
    printf '%s\t%s\n' "$hash" "$crash"
  done < <(find "$pulled" -type f -print0 2>/dev/null) \
    | LC_ALL=C sort -u >"$destination/inventory.tsv"
  cut -f1 "$destination/inventory.tsv" | LC_ALL=C sort -u >"$destination/hashes.txt"
}

collect_startup_reliability_system_crash_delta() {
  local before="$1" after="$2" destination="$3"
  mkdir -p "$destination/raw"
  comm -13 "$before/hashes.txt" "$after/hashes.txt" >"$destination/new-hashes.txt" || true
  while IFS= read -r hash; do
    [[ -n "$hash" ]] || continue
    local source
    source="$(awk -F '\t' -v target="$hash" '$1 == target {print $2; exit}' "$after/inventory.tsv")"
    [[ -n "$source" && -f "$source" ]] || continue
    cp "$source" "$destination/raw/${hash}.ips"
  done <"$destination/new-hashes.txt"
  python3 "$ROOT_DIR/scripts/ios_startup_reliability.py" sanitize-system-crashes \
    --input-dir "$destination/raw" \
    --process Vocello --process com.patricedery.vocello \
    --output "$destination/system-crash-summary.json"
}

read_devicectl_launch_pid() {
  local launch_json="$1"
  python3 - "$launch_json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
def find(value):
    if isinstance(value, dict):
        direct = value.get("processIdentifier")
        if isinstance(direct, int):
            return direct
        for child in value.values():
            found = find(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find(child)
            if found is not None:
                return found
    return None
pid = find(payload)
if pid is None:
    raise SystemExit(1)
print(pid)
PY
}

# lang-bench [--subset quick|full] [--label RUN_ID] [--diagnostic-cohort[=PATH]]:
# Headless on-device language matrix — one diagnostic generation per cell, gated by
# scripts/check_language_hints.py on exact run/cell/generation/seed correlation.
# Normal quick/full runs retain one take per cell and publish history on PASS. The optional
# fixed-seed cohort is diagnostic-only and evaluates every predeclared take without retries.
cmd_lang_bench() {
  require_team
  note "lang-bench requires Built-in Voice (Speed) on device — install via Settings → Model Downloads if diagnostics fail"
  local subset="full" label="" cohort=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --subset) subset="${2:-full}"; shift 2 ;;
      --subset=*) subset="${1#*=}"; shift ;;
      --label) label="${2:-}"; shift 2 ;;
      --label=*) label="${1#*=}"; shift ;;
      --diagnostic-cohort) cohort="$ROOT_DIR/config/language-bench-diagnostic-cohort.json"; shift ;;
      --diagnostic-cohort=*) cohort="${1#*=}"; [[ -n "$cohort" ]] || die "--diagnostic-cohort path cannot be empty"; shift ;;
      *) die "unknown lang-bench arg '$1' (try --subset quick|full --label lang-check-v1 [--diagnostic-cohort])" ;;
    esac
  done
  validate_benchmark_label "$label"
  [[ "$subset" == "quick" || "$subset" == "full" ]] || die "--subset must be quick or full"
  if [[ -n "$cohort" && "${QVOICE_LANG_BENCH_SKIP_OUTPUT:-0}" == "1" ]]; then
    die "diagnostic cohorts require structured output verification; QVOICE_LANG_BENCH_SKIP_OUTPUT is unsupported"
  fi

  local matrix="$ROOT_DIR/config/language-bench-matrix.json"
  local corpus="$ROOT_DIR/config/language-bench-corpus.json"
  [[ -f "$matrix" && -f "$corpus" ]] || die "missing language bench config (expected $matrix and $corpus)"
  [[ -z "$cohort" || -f "$cohort" ]] || die "diagnostic cohort config not found: $cohort"

  local run_id
  if [[ -n "$cohort" ]]; then
    run_id="ios-lang-cohort-$(date -u +%Y%m%d-%H%M%S)-$(benchmark_nonce)"
  else
    run_id="ios-lang-bench-$(date -u +%Y%m%d-%H%M%S)-$(benchmark_nonce)"
  fi
  local artifacts="$QVOICE_ARTIFACTS_IOS/language-bench/$run_id"
  local plan="$artifacts/language-run-plan.json"
  local started_at
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local dest="$QVOICE_ARTIFACTS_DIAGNOSTICS/ios/device-diagnostics"
  # Three bounded 45-second Speech passes occur after generation. The outer bound leaves
  # enough room for a genuine cold model load without changing the fast success path.
  local cell_timeout="${QVOICE_IOS_LANG_BENCH_CELL_TIMEOUT:-360}"
  mkdir -p "$artifacts"
  rm -rf "$dest"

  local -a plan_args=(
    plan --run-id "$run_id" --matrix "$matrix" --corpus "$corpus"
    --subset "$subset" --output "$plan"
  )
  [[ -n "$cohort" ]] && plan_args+=(--cohort "$cohort")
  python3 "$ROOT_DIR/scripts/language_bench_evidence.py" "${plan_args[@]}" \
    || die "could not create immutable language-run plan"

  cmd_build
  cmd_install
  capture_benchmark_source "$artifacts"
  # The snapshot retains the crash baseline digest. Keeping a second complete copy of the
  # device's historical diagnostics in this run artifact obscures current-run evidence.
  rm -rf "$artifacts/crash-before"

  export QVOICE_MAC_BENCH_RUN_ID="$run_id"
  if [[ "${QVOICE_LANG_BENCH_SKIP_OUTPUT:-0}" != "1" ]]; then
    export QVOICE_IOS_DEVICE_DIAGNOSTICS_VERIFY_OUTPUT=1
    note "lang-bench: output verification ON (Speech — grant once in Settings if needed)"
  else
    unset QVOICE_IOS_DEVICE_DIAGNOSTICS_VERIFY_OUTPUT
  fi
  if [[ -n "$cohort" ]]; then
    note "lang-bench: runID=$run_id fixed-seed diagnostic cohort → $artifacts"
  else
    note "lang-bench: runID=$run_id subset=$subset → $artifacts"
  fi

  local cell_json cell_count=0 cell_fail=0
  while IFS= read -r cell_json; do
    [[ -n "$cell_json" ]] || continue
    cell_count=$((cell_count + 1))
    local cell_id mode variant ui_hint text child_run_id spec sentinel seed sampling_variation
    local custom_speaker design_instruction st
    cell_id="$(CELL="$cell_json" python3 -c 'import json,os; print(json.loads(os.environ["CELL"])["cellID"])')"
    mode="$(CELL="$cell_json" python3 -c 'import json,os; print(json.loads(os.environ["CELL"])["mode"])')"
    variant="$(CELL="$cell_json" python3 -c 'import json,os; print(json.loads(os.environ["CELL"]).get("variant","speed"))')"
    ui_hint="$(CELL="$cell_json" python3 -c 'import json,os; print(json.loads(os.environ["CELL"]).get("uiHint","auto"))')"
    text="$(CELL="$cell_json" CORPUS="$corpus" python3 -c '
import json, os
cell = json.loads(os.environ["CELL"])
corpus = json.load(open(os.environ["CORPUS"]))
scripts = {e["id"]: e["script"] for e in corpus["languages"]}
print(scripts[cell["scriptLang"]], end="")')"
    child_run_id="$(CELL="$cell_json" python3 -c 'import json,os; print(json.loads(os.environ["CELL"])["childRunID"])')"
    seed="$(CELL="$cell_json" python3 -c 'import json,os; print(json.loads(os.environ["CELL"])["seed"])')"
    sampling_variation="$(CELL="$cell_json" python3 -c 'import json,os; print(json.loads(os.environ["CELL"])["samplingVariation"])')"
    custom_speaker="$(CELL="$cell_json" python3 -c 'import json,os; print(json.loads(os.environ["CELL"]).get("customSpeakerID") or "", end="")')"
    design_instruction="$(CELL="$cell_json" python3 -c 'import json,os; print(json.loads(os.environ["CELL"]).get("designInstruction") or "", end="")')"
    spec="${mode}:${variant}:${text}"

    note "lang-bench take $cell_count: $cell_id ($mode, uiHint=$ui_hint, seed=$seed, variation=$sampling_variation)"
    export QVOICE_LAUNCH_RUN_ID="$child_run_id"
    export QVOICE_MAC_BENCH_CELL="$cell_id"
    export QVOICE_IOS_DEVICE_DIAGNOSTICS_SEED="$seed"
    export QVOICE_IOS_DEVICE_DIAGNOSTICS_VARIATION="$sampling_variation"
    if [[ -n "$custom_speaker" ]]; then
      export QVOICE_IOS_DEVICE_DIAGNOSTICS_CUSTOM_SPEAKER="$custom_speaker"
    else
      unset QVOICE_IOS_DEVICE_DIAGNOSTICS_CUSTOM_SPEAKER
    fi
    if [[ -n "$design_instruction" ]]; then
      export QVOICE_IOS_DEVICE_DIAGNOSTICS_DESIGN_INSTRUCTION="$design_instruction"
    else
      unset QVOICE_IOS_DEVICE_DIAGNOSTICS_DESIGN_INSTRUCTION
    fi
    if [[ "$ui_hint" == "auto" ]]; then
      unset QVOICE_IOS_DEVICE_DIAGNOSTICS_LANGUAGE
    else
      export QVOICE_IOS_DEVICE_DIAGNOSTICS_LANGUAGE="$ui_hint"
    fi

    # Scope verbose telemetry to this launch. device_diagnostics_env_json sees
    # the temporary value, and Bash restores the caller's prior value (including
    # the unset state) as soon as cmd_launch returns.
    QWENVOICE_NATIVE_TELEMETRY_MODE=verbose cmd_launch "$spec" >/dev/null
    set +e
    sentinel="$({ wait_device_diagnostics_sentinel "$child_run_id" "$cell_timeout" "$dest"; })"
    wait_st=$?
    set -e
    if (( wait_st != 0 )) || [[ -z "$sentinel" || ! -f "$sentinel" ]]; then
      warn "lang-bench cell $cell_id: timed out or failed (runID=$child_run_id)"
      cell_fail=$((cell_fail + 1))
      continue
    fi
    if ! python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("status")=="ok" else 1)' "$sentinel"; then
      warn "lang-bench cell $cell_id: diagnostics status != ok (see $sentinel)"
      cell_fail=$((cell_fail + 1))
    fi
  done < <(python3 - "$plan" "$corpus" <<'PY'
import json, sys
plan_path, corpus_path = sys.argv[1:3]
cells = json.load(open(plan_path))["takes"]
corpus = {e["id"]: e["script"] for e in json.load(open(corpus_path))["languages"]}
for cell in cells:
    cell = dict(cell)
    cell["script"] = corpus[cell["scriptLang"]]
    print(json.dumps(cell, ensure_ascii=False))
PY
)

  unset QVOICE_LAUNCH_RUN_ID QVOICE_MAC_BENCH_RUN_ID QVOICE_MAC_BENCH_CELL \
    QVOICE_IOS_DEVICE_DIAGNOSTICS_LANGUAGE QVOICE_IOS_DEVICE_DIAGNOSTICS_VERIFY_OUTPUT \
    QVOICE_IOS_DEVICE_DIAGNOSTICS_SEED QVOICE_IOS_DEVICE_DIAGNOSTICS_VARIATION \
    QVOICE_IOS_DEVICE_DIAGNOSTICS_CUSTOM_SPEAKER QVOICE_IOS_DEVICE_DIAGNOSTICS_DESIGN_INSTRUCTION

  [[ "$cell_count" -gt 0 ]] || die "lang-bench: no cells for subset=$subset"

  note "lang-bench: pulled $cell_count takes ($cell_fail diagnostic failures) — selecting exact evidence"
  local diag="$artifacts/diagnostics" collect_st=0
  local -a cohort_args=()
  [[ -n "$cohort" ]] && cohort_args+=(--cohort "$cohort")
  python3 "$ROOT_DIR/scripts/language_bench_evidence.py" collect \
    --source "$dest" --plan "$plan" --output "$diag" \
    --matrix "$matrix" --corpus "$corpus" --subset "$subset" \
    ${cohort_args[@]+"${cohort_args[@]}"} \
    | tee "$artifacts/evidence-collection.txt" || collect_st=$?

  local hint_st=0 output_st=0
  local -a hint_gate_args=()
  [[ -n "$cohort" ]] && hint_gate_args+=(--strict-qc)
  python3 "$ROOT_DIR/scripts/check_language_hints.py" "$diag" \
    --run-id "$run_id" --matrix "$matrix" --corpus "$corpus" --subset "$subset" --plan "$plan" \
    ${hint_gate_args[@]+"${hint_gate_args[@]}"} \
    ${cohort_args[@]+"${cohort_args[@]}"} \
    | tee "$artifacts/hint-gate.txt" || hint_st=$?

  if [[ "${QVOICE_LANG_BENCH_SKIP_OUTPUT:-0}" != "1" ]]; then
    python3 "$ROOT_DIR/scripts/check_language_output.py" "$diag" \
      --run-id "$run_id" --matrix "$matrix" --corpus "$corpus" --subset "$subset" --plan "$plan" \
      ${cohort_args[@]+"${cohort_args[@]}"} \
      | tee "$artifacts/output-gate.txt" || output_st=$?
  fi

  {
    echo "lang-bench runID=$run_id subset=$subset takes=$cell_count diagnostics_fail=$cell_fail"
    echo "classification=$([[ -n $cohort ]] && echo diagnostic-cohort || echo benchmark)"
    echo "evidence_collection=$([[ $collect_st -eq 0 ]] && echo PASS || echo FAIL)"
    echo "hint_gate=$([[ $hint_st -eq 0 ]] && echo PASS || echo FAIL)"
    if [[ "${QVOICE_LANG_BENCH_SKIP_OUTPUT:-0}" != "1" ]]; then
      echo "output_gate=$([[ $output_st -eq 0 ]] && echo PASS || echo FAIL)"
    else
      echo "output_gate=SKIPPED"
    fi
  } | tee "$artifacts/verdict.txt"

  if (( cell_fail > 0 || collect_st != 0 || hint_st != 0 || output_st != 0 )); then
    die "lang-bench FAIL · $artifacts"
  fi
  if [[ -n "$cohort" ]]; then
    note "lang-bench diagnostic cohort PASS · all $cell_count predeclared takes passed · no history record created"
    return 0
  fi
  local output_gate="pass"
  [[ "${QVOICE_LANG_BENCH_SKIP_OUTPUT:-0}" == "1" ]] && output_gate="not-performed"
  python3 "$ROOT_DIR/scripts/publish_benchmark_history.py" language \
    --artifact-dir "$artifacts" --snapshot "$artifacts/benchmark-source.json" \
    --platform ios --run-id "$run_id" --diagnostics "$diag" --crash-diagnostics "$dest" \
    --matrix "$matrix" --corpus "$corpus" --subset "$subset" \
    --plan "$plan" \
    --output-gate "$output_gate" --started-at "$started_at" --defer-record \
    ${label:+--label "$label"} \
    || die "language benchmark passed but evidence validation failed; artifacts are preserved in $artifacts"
  python3 "$ROOT_DIR/scripts/summarize_generation_telemetry.py" "$diag" \
    --run-id "$run_id" --evidence-manifest "$artifacts/benchmark-evidence.json" \
    --engine-only ${label:+--label "$label"} >"$artifacts/summary.txt" 2>&1 \
    || die "language evidence was valid but its frozen telemetry summary failed"
  record_benchmark_history "$artifacts" >/dev/null \
    || die "language history publication failed"
  note "lang-bench PASS · $artifacts"
}

cmd_bench() {
  require_team
  note "bench requires Built-in Voice (Speed) on device — confirm it in Settings → Model Downloads before generation"
  local spec="custom:speed:" label=""
  # parse: first non-flag arg = spec; --label RUN_ID; --memory-profile <profile>;
  # --voice-id <saved-voice-id> is mandatory for clone diagnostics.
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --label) label="${2:-}"; shift 2 ;;
      --label=*) label="${1#*=}"; shift ;;
      # Restriction simulation (memory dimension only): forwards
      # QVOICE_IOS_MEMORY_PROFILE so the app clamps its effective per-process
      # limit to the profile's entitled budget (iphone15pro → 5000 MB,
      # iphone14pro → 3600 MB: the 6 GB device class for floor feasibility).
      # Rows self-stamp notes.memoryProfile; GPU/thermal are NOT simulated.
      --memory-profile) export QVOICE_IOS_MEMORY_PROFILE="${2:-}"; shift 2 ;;
      --memory-profile=*) export QVOICE_IOS_MEMORY_PROFILE="${1#*=}"; shift ;;
      --voice-id) export QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID="${2:-}"; shift 2 ;;
      --voice-id=*) export QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID="${1#*=}"; shift ;;
      *) spec="$1"; shift ;;
    esac
  done
  validate_benchmark_label "$label"
  [[ "$spec" == *:* ]] || spec="custom:speed:$spec"   # bare text → custom:speed:<text>
  require_diagnostic_clone_voice "$spec"
  local run_id
  run_id="ios-engine-$(date -u +%Y%m%d-%H%M%S)-$(benchmark_nonce)"
  local artifacts="$QVOICE_ARTIFACTS_IOS/engine-bench/$run_id"
  mkdir -p "$artifacts"

  cmd_build
  cmd_install
  capture_benchmark_source "$artifacts"
  export QVOICE_LAUNCH_RUN_ID="$run_id"
  export QVOICE_MAC_BENCH_RUN_ID="$run_id"
  export QVOICE_MAC_BENCH_TAKE_INDEX=1
  export QVOICE_MAC_BENCH_CELL="$(device_benchmark_cell "$spec")"
  export QWENVOICE_NATIVE_TELEMETRY_MODE=verbose
  local launched_run_id; launched_run_id="$(cmd_launch "$spec" | tail -1)"
  unset QVOICE_LAUNCH_RUN_ID QVOICE_MAC_BENCH_RUN_ID QVOICE_MAC_BENCH_TAKE_INDEX \
    QVOICE_MAC_BENCH_CELL QWENVOICE_NATIVE_TELEMETRY_MODE
  [[ "$launched_run_id" == "$run_id" ]] || die "device launch returned the wrong run ID"

  local timeout="${QVOICE_IOS_BENCH_TIMEOUT:-300}"
  local dest="$QVOICE_ARTIFACTS_DIAGNOSTICS/ios/device-diagnostics"
  rm -rf "$dest"
  note "waiting for device-diagnostics sentinel (runID=$run_id, timeout=${timeout}s)…"
  local waited=0 sentinel=""
  local interference_streak=0 interference_state=""
  while (( waited < timeout )); do
    sleep 10; waited=$((waited + 10))
    cmd_pull "$dest" >/dev/null 2>&1 || true
    # devicectl nesting varies, so locate the sentinel by name+runID rather than a fixed path.
    sentinel="$(find "$dest" -name device-diagnostics-done.json -path "*/${run_id}/*" 2>/dev/null | head -1)"
    if [[ -n "$sentinel" && -f "$sentinel" ]]; then
      note "sentinel found after ${waited}s"
      break
    fi
    # Interference probe: abort fast instead of polling to the full timeout.
    # Competing UI ownership or a disconnected device dooms the run immediately.
    local state verdict
    state="$(probe_device_state 2>/dev/null || true)"
    verdict="${state%%|*}"
    case "$verdict" in
      DEVICE_UNREACHABLE)
        die "run doomed at ${waited}s — $verdict: $(device_state_advice "$verdict") (${state#*|})"
        ;;
      *)
        interference_streak=0
        ;;
    esac
    note "…still generating (${waited}s)"
  done

  local diagnostic_hint="$0 console \"$spec\""
  if [[ "$spec" == clone:* ]]; then
    diagnostic_hint+=" --voice-id \"$QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID\""
  fi
  [[ -n "$sentinel" && -f "$sentinel" ]] || die "no sentinel after ${timeout}s — device diagnostics did not write. Device state: $(probe_device_state 2>/dev/null || echo unknown). Diagnose live with: $diagnostic_hint"

  # The summarizer reads <dir>/engine/generations.jsonl — find the dir that holds it.
  local diag="$dest"
  local engine_jsonl; engine_jsonl="$(find "$dest" -path '*/engine/generations.jsonl' 2>/dev/null | head -1)"
  [[ -n "$engine_jsonl" ]] && diag="$(dirname "$(dirname "$engine_jsonl")")"

  note "── device diagnostics result ──────────────────"
  # Heredoc (quoted delimiter) so the Python body needs no shell-quote escaping.
  python3 - "$sentinel" <<'PY' >&2 || true
import json, sys
r = json.load(open(sys.argv[1]))
def num(x): return x if isinstance(x, (int, float)) else 0.0
print("  status   :", r.get("status"))
print("  mode     :", r.get("mode"), "/", r.get("variant"))
print("  model    :", r.get("modelID"))
if r.get("status") == "ok":
    print("  audio    : %.2fs   wall %.2fs   rtf %.2f"
          % (num(r.get("durationSeconds")), num(r.get("wallSeconds")), num(r.get("realtimeFactor"))))
    print("  finish   :", r.get("finishReason"))
    print("  out      :", r.get("audioPath"))
else:
    print("  error    :", r.get("error"))
for e in r.get("interruptions") or []:
    print("  ⚠ interruption: %s at t=%.1fs" % (e.get("type"), (e.get("atMS") or 0) / 1000.0))
print("  device   :", r.get("deviceModel"), r.get("systemName"), r.get("systemVersion"))
PY

  note "── telemetry summary (engine decode / RTF / audioQC / RAM) ──"
  require_uninterrupted_success_sentinel "$sentinel" \
    || die "device benchmark generation failed or was interrupted"
  python3 "$ROOT_DIR/scripts/publish_benchmark_history.py" ios-engine \
    --artifact-dir "$artifacts" --snapshot "$artifacts/benchmark-source.json" \
    --run-id "$run_id" --sentinel "$sentinel" --diagnostics "$diag" --crash-diagnostics "$dest" \
    --defer-record ${label:+--label "$label"} \
    || die "device benchmark passed but evidence validation failed; artifacts are preserved in $artifacts"
  python3 "$ROOT_DIR/scripts/summarize_generation_telemetry.py" "$diag" \
    --run-id "$run_id" --evidence-manifest "$artifacts/benchmark-evidence.json" \
    --engine-only ${label:+--label "$label"} >&2 \
    || die "strict frozen telemetry summary failed for runID=$run_id"
  record_benchmark_history "$artifacts" >/dev/null \
    || die "device benchmark history publication failed"
  note "bench PASS · $artifacts"
}

cmd_crashes() {
  local test_mode=0
  [[ "${1:-}" == "--test" ]] && test_mode=1
  local dev; dev="$(resolve_device)"

  if [[ $test_mode -eq 1 ]]; then
    note "crash-lane self-test: deliberately crashing the purpose-built diagnostics app…"
    cmd_build --device-diagnostics-crash-test
    cmd_install >/dev/null
    xcrun devicectl device process launch --device "$dev" --terminate-existing \
      -e '{"QWENVOICE_DEBUG":"1","QVOICE_IOS_DEVICE_DIAGNOSTICS_SPEC":"custom:speed:Crash diagnostics self-test.","QVOICE_IOS_DEVICE_DIAGNOSTICS_CRASH_TEST":"1","QVOICE_IOS_DEVICE_RUN_ID":"ios-crash-self-test"}' \
      "$BUNDLE_ID" >&2 || true
    sleep 4
    note "relaunching so IOSCrashObserver receives + writes the prior crash payload…"
    xcrun devicectl device process launch --device "$dev" --terminate-existing "$BUNDLE_ID" >&2 || true
    sleep 6
  fi

  local dest="$QVOICE_ARTIFACTS_DIAGNOSTICS/ios/device-diagnostics"
  rm -rf "$dest"
  cmd_pull "$dest" >/dev/null || die "could not pull diagnostics (run device diagnostics first, or use --test)"
  local crash_dir; crash_dir="$(find "$dest" -type d -name crashes 2>/dev/null | head -1)"
  if [[ -z "$crash_dir" ]] || [[ -z "$(find "$crash_dir" -maxdepth 1 -type f 2>/dev/null | head -1)" ]]; then
    note "no crash payloads in the pulled diagnostics — nothing to symbolicate."
    return 0
  fi

  note "── crash payloads ($crash_dir) ──"
  find "$crash_dir" -maxdepth 1 -type f | sort

  local dsym="$QVOICE_SYMBOLS_IOS/Vocello.app.dSYM"
  if [[ ! -d "$dsym" ]]; then
    warn "no preserved dSYM at $dsym — run '$0 build' to enable symbolication."
    return 0
  fi

  note "── symbolication (optional xcsym when on PATH; otherwise Xcode Organizer) ──"
  local f
  for f in "$crash_dir"/*; do
    [[ -f "$f" ]] || continue
    if command -v xcsym >/dev/null 2>&1; then
      xcsym crash "$f" --dsym "$dsym" 2>&1 || warn "xcsym failed on $(basename "$f")"
    else
      warn "xcsym not on PATH — use Xcode Organizer, or consult \$axiom-tools before installing xcsym:"
      warn "  xcsym crash \"$f\" --dsym \"$dsym\""
    fi
  done
}

# debug [spec]: build+install the get-task-allow build, then an attached console launch
# and the exact LLDB attach command. The LLDB session itself is interactive (paste it, or
# use the XcodeBuildMCP device/debugging workflow, or Xcode → Debug → Attach to Process).
# Burns-in safe (headless/locked works).
cmd_debug() {
  local spec="${1:-}"
  # Rebuild immediately before provenance capture so source/toolchain metadata
  # cannot be paired with an older installed profiling binary.
  cmd_build
  cmd_install >/dev/null
  local dev; dev="$(resolve_device)"
  note "debug: get-task-allow build installed on $dev — LLDB-attachable."
  note "  lldb"
  note "  (lldb) process attach --name Vocello --device $dev"
  note "  (or XcodeBuildMCP device/debugging workflow, or Xcode → Debug → Attach to Process)"
  if [[ -n "$spec" ]]; then
    note "attached launch ($spec) — Ctrl-C to detach"
    cmd_console "$spec"
  else
    note "attached launch (console) — Ctrl-C to detach"
    cmd_console
  fi
}

# logs [spec]: attached launch teeing the app's stdout/stderr to a retained, greppable
# file under the governed diagnostics root (device-diagnostics/QVoiceiOSApp prints + engine signposts).
# Replaces the ephemeral `console` stream with a saved log. Burns-in safe (headless).
cmd_logs() {
  local spec="custom:speed:Log capture device diagnostics."
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --voice-id) export QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID="${2:-}"; shift 2 ;;
      --voice-id=*) export QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID="${1#*=}"; shift ;;
      *) spec="$1"; shift ;;
    esac
  done
  [[ "$spec" == *:* ]] || spec="custom:speed:$spec"
  require_diagnostic_clone_voice "$spec"
  local dev; dev="$(resolve_device)"
  local run_id="ios-logs-$(date +%Y%m%d-%H%M%S)"
  local out="$QVOICE_ARTIFACTS_DIAGNOSTICS/ios/logs/${run_id}.log"
  mkdir -p "$(dirname "$out")"
  note "capturing attached launch logs → $out (Ctrl-C to stop)"
  local env_json
  env_json="$(device_diagnostics_env_json "$spec" "$run_id")"
  xcrun devicectl device process launch --device "$dev" --console --terminate-existing \
    -e "$env_json" "$BUNDLE_ID" 2>&1 | tee "$out"
  note "saved $out"
}

# profile [--kind cpu|memory] [spec]: record an Instruments/xctrace trace while device diagnostics runs one
# generation on-device (burns-in safe — headless, screen dark). The lane always records
# CPU Profiler and os_signpost in one trace; memory profiles also record Allocations and
# VM Tracker. QVOICE_IOS_PROFILE_DURATION controls the capture window (seconds, default 90),
# and QVOICE_IOS_MEMORY_PROFILE_DURATION may override it for memory captures. The engine
# emits OSSignpost intervals under
# com.qwenvoice.engine / com.patricedery.vocello. Produces
# build/artifacts/ios/profiles/<run-id>/<run-id>.trace + the in-app telemetry summary for the same run.
cmd_profile() {
  local kind="cpu"
  local spec=""
  local keep_trace=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --kind) kind="${2:-}"; shift 2 ;;
      --kind=*) kind="${1#*=}"; shift ;;
      --keep-trace) keep_trace=1; shift ;;
      -*) die "unknown profile flag: $1 (try --kind cpu|memory [--keep-trace])" ;;
      *) [[ -z "$spec" ]] || die "profile accepts one generation spec"; spec="$1"; shift ;;
    esac
  done
  case "$kind" in cpu|memory) ;; *) die "profile kind must be cpu or memory" ;; esac
  spec="${spec:-custom:speed:Profile device diagnostics.}"
  [[ "$spec" == *:* ]] || spec="custom:speed:$spec"
  python3 "$ROOT_DIR/scripts/lib/profile_trace_retention.py" preflight \
    --root "$ROOT_DIR" --kind "$kind" >/dev/null \
    || die "profile disk-space preflight failed before launching the target"
  require_diagnostic_clone_voice "$spec"
  require_team
  local cpu_instrument="CPU Profiler"
  local allocations_instrument="Allocations"
  local vm_tracker_instrument="VM Tracker"
  local -a instrument_args=(--instrument "$cpu_instrument")
  local capture_instruments="$cpu_instrument + os_signpost"
  if [[ "$kind" == "memory" ]]; then
    instrument_args+=(--instrument "$allocations_instrument" --instrument "$vm_tracker_instrument")
    capture_instruments="$cpu_instrument + $allocations_instrument + $vm_tracker_instrument + os_signpost"
  fi
  instrument_args+=(--instrument os_signpost)
  local duration="${QVOICE_IOS_PROFILE_DURATION:-90}"
  [[ "$kind" != "memory" ]] || duration="${QVOICE_IOS_MEMORY_PROFILE_DURATION:-$duration}"
  local tracer_start_timeout="${QVOICE_IOS_PROFILE_START_TIMEOUT:-30}"
  [[ "$duration" =~ ^[1-9][0-9]*$ ]] || die "QVOICE_IOS_PROFILE_DURATION must be a positive whole number of seconds"
  [[ "$tracer_start_timeout" =~ ^[1-9][0-9]*$ ]] \
    || die "QVOICE_IOS_PROFILE_START_TIMEOUT must be a positive whole number of seconds"
  local dev; dev="$(resolve_device)"
  command -v xctrace >/dev/null 2>&1 \
    || die "xctrace not found — install Xcode and use Instruments for native profiling"
  local xctrace_dev
  xctrace_dev="$(resolve_xctrace_device "$dev")"

  # Profiling evidence must describe the current checkout, not merely whatever
  # compatible app happens to remain in the persistent device cache.
  cmd_build
  cmd_install >/dev/null
  local run_id
  run_id="ios-${kind}-profile-$(date -u +%Y%m%d-%H%M%S)-$(benchmark_nonce)"
  local artifacts="$QVOICE_ARTIFACTS_IOS/profiles/$run_id"
  local trace="$artifacts/$run_id.trace"
  local toc="$artifacts/trace-toc.xml"
  local profile_summary="$artifacts/profile-summary.json"
  local history_record="$ROOT_DIR/benchmarks/runs/instrument-profile/$run_id.json"
  local retention_policy="summaryOnly"
  (( keep_trace == 0 )) || retention_policy="keptExplicitly"
  local launch_json="$artifacts/launch.json"
  local dest="$artifacts/device-diagnostics"
  mkdir -p "$artifacts"
  capture_benchmark_source "$artifacts"

  local target_pid="" xctrace_pid="" cleanup_command=""
  PROFILE_TRACE_ACTIVE=1
  PROFILE_TRACE_PUBLISHED=0
  PROFILE_TRACE_KIND="$kind"
  PROFILE_TRACE_PHASE="target-launch"
  PROFILE_TRACE_ARTIFACTS="$artifacts"
  PROFILE_TRACE_PATH="$trace"
  PROFILE_TRACE_XCTRACE_PID=""
  PROFILE_TRACE_DEVICE_CLEANUP=""
  trap profile_failure_cleanup EXIT

  local profile_label="instrument-${kind}-profile"
  note "profile: kind=$kind, instruments='$capture_instruments', ${duration}s, device=$dev (exact suspended PID)"
  local env_json
  export QVOICE_MAC_BENCH_RUN_ID="$run_id"
  export QVOICE_MAC_BENCH_TAKE_INDEX=1
  export QVOICE_MAC_BENCH_CELL="$(device_benchmark_cell "$spec")"
  local previous_telemetry_mode="${QWENVOICE_NATIVE_TELEMETRY_MODE:-}"
  export QWENVOICE_NATIVE_TELEMETRY_MODE=verbose
  env_json="$(device_diagnostics_env_json "$spec" "$run_id")"
  if [[ -n "$previous_telemetry_mode" ]]; then
    export QWENVOICE_NATIVE_TELEMETRY_MODE="$previous_telemetry_mode"
  else
    unset QWENVOICE_NATIVE_TELEMETRY_MODE
  fi
  unset QVOICE_MAC_BENCH_RUN_ID QVOICE_MAC_BENCH_TAKE_INDEX QVOICE_MAC_BENCH_CELL
  PROFILE_TRACE_PHASE="final-disk-preflight"
  python3 "$ROOT_DIR/scripts/lib/profile_trace_retention.py" preflight \
    --root "$ROOT_DIR" --kind "$kind" >/dev/null \
    || die "profile disk-space preflight failed after build/install and before target launch"
  # A long rebuild/install can change the CoreDevice-to-Instruments route. Resolve
  # it again at the point of use rather than trusting the earlier fail-fast probe.
  xctrace_dev="$(resolve_xctrace_device "$dev")"
  PROFILE_TRACE_PHASE="target-launch"
  xcrun devicectl device process launch --device "$dev" --terminate-existing --start-stopped \
    -e "$env_json" --json-output "$launch_json" "$BUNDLE_ID" \
    >"$artifacts/launch.log" 2>&1 \
    || die "could not launch the profiling target suspended (see $artifacts/launch.log)"
  target_pid="$(python3 - "$launch_json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
def find(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "processIdentifier" and isinstance(child, int):
                return child
        for child in value.values():
            if (found := find(child)) is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            if (found := find(child)) is not None:
                return found
    return None
pid = find(payload)
if pid is None:
    raise SystemExit(1)
print(pid)
PY
)" || die "devicectl launch result did not contain the exact target PID"
  [[ "$target_pid" =~ ^[0-9]+$ ]] || die "invalid profiling target PID"
  printf -v cleanup_command \
    'xcrun devicectl device process terminate --device %q --pid %q --quiet >/dev/null 2>&1 || true' \
    "$dev" "$target_pid"
  PROFILE_TRACE_DEVICE_CLEANUP="$cleanup_command"
  note "device diagnostics suspended (runID=$run_id pid=$target_pid); attaching Instruments"
  PROFILE_TRACE_PHASE="trace-recording"
  xcrun xctrace record --device "$xctrace_dev" "${instrument_args[@]}" \
    --attach "$target_pid" --time-limit "${duration}s" --no-prompt --output "$trace" \
    >"$artifacts/xctrace.log" 2>&1 &
  xctrace_pid=$!
  PROFILE_TRACE_XCTRACE_PID="$xctrace_pid"
  local tracer_start_deadline=$((SECONDS + tracer_start_timeout))
  local tracer_started=0
  while kill -0 "$xctrace_pid" >/dev/null 2>&1; do
    if grep -q '^Starting recording' "$artifacts/xctrace.log" 2>/dev/null; then
      tracer_started=1
      break
    fi
    if (( SECONDS >= tracer_start_deadline )); then
      kill "$xctrace_pid" >/dev/null 2>&1 || true
      wait "$xctrace_pid" >/dev/null 2>&1 || true
      die "xctrace did not report tracing startup within ${tracer_start_timeout}s"
    fi
    sleep 0.1
  done
  if (( tracer_started == 0 )); then
    wait "$xctrace_pid" >/dev/null 2>&1 || true
    die "xctrace exited before reporting tracing startup"
  fi
  xcrun devicectl device process resume --device "$dev" --pid "$target_pid" \
    >"$artifacts/resume.log" 2>&1 \
    || { kill "$xctrace_pid" >/dev/null 2>&1 || true; die "could not resume the profiled target"; }
  wait "$xctrace_pid" || die "xctrace failed (see $artifacts/xctrace.log)"
  xctrace_pid=""
  PROFILE_TRACE_XCTRACE_PID=""
  [[ -d "$trace" ]] || die "no trace produced at $trace"
  PROFILE_TRACE_PHASE="trace-export"
  xcrun xctrace export --input "$trace" --toc --output "$toc" \
    >"$artifacts/xctrace-export.log" 2>&1 \
    || die "trace table-of-contents validation failed (see $artifacts/xctrace-export.log)"
  [[ -s "$toc" ]] || die "trace table-of-contents export is empty"

  local sentinel
  PROFILE_TRACE_PHASE="generation-validation"
  sentinel="$({ wait_device_diagnostics_sentinel "$run_id" "$duration" "$dest"; })" \
    || die "profiled generation did not produce a success sentinel"
  require_uninterrupted_success_sentinel "$sentinel" \
    || die "profiled generation failed or was interrupted"
  local diag="$dest"
  local engine_jsonl; engine_jsonl="$(find "$dest" -path '*/engine/generations.jsonl' 2>/dev/null | head -1)"
  [[ -n "$engine_jsonl" ]] && diag="$(dirname "$(dirname "$engine_jsonl")")"
  PROFILE_TRACE_PHASE="evidence-validation"
  python3 "$ROOT_DIR/scripts/publish_benchmark_history.py" ios-profile \
    --artifact-dir "$artifacts" --snapshot "$artifacts/benchmark-source.json" \
    --run-id "$run_id" --sentinel "$sentinel" --diagnostics "$diag" --crash-diagnostics "$dest" \
    --trace "$trace" --toc "$toc" --template "$capture_instruments" --duration "$duration" \
    --target-process Vocello --target-pid "$target_pid" --profile-kind "$kind" --defer-record \
    --retention-policy "$retention_policy" --summary-artifact "$profile_summary" \
    --label "$profile_label" \
    || die "profile passed but evidence validation failed; artifacts are preserved in $artifacts"
  note "── telemetry for the profiled run ──"
  python3 "$ROOT_DIR/scripts/summarize_generation_telemetry.py" "$diag" \
    --run-id "$run_id" --evidence-manifest "$artifacts/benchmark-evidence.json" \
    --engine-only --label "$profile_label" >&2 \
    || die "profile evidence was valid but its frozen telemetry summary failed"
  PROFILE_TRACE_PHASE="history-publication"
  record_benchmark_history "$artifacts" >/dev/null \
    || die "profile history publication failed"
  PROFILE_TRACE_PUBLISHED=1
  PROFILE_TRACE_PHASE="retention-finalization"
  python3 "$ROOT_DIR/scripts/lib/profile_trace_retention.py" finalize-success \
    --root "$ROOT_DIR" --platform ios --kind "$kind" \
    --artifact-dir "$artifacts" --trace "$trace" --policy "$retention_policy" \
    --summary-artifact "$profile_summary" --history-record "$history_record" \
    || die "profile was published but raw-trace retention finalization failed; run routine cleanup"
  eval "$cleanup_command"
  trap - EXIT
  PROFILE_TRACE_ACTIVE=0
  PROFILE_TRACE_DEVICE_CLEANUP=""
  if (( keep_trace )); then
    note "trace retained explicitly → $trace"
    note "analyze: open in Instruments, or use optional: xcprof analyze \"$trace\""
    printf '%s\n' "$trace"
  else
    note "validated summary → $profile_summary"
    note "raw trace removed after successful history publication (use --keep-trace to retain one)"
    printf '%s\n' "$profile_summary"
  fi
}

# memory --voice-id ID [--label ID]: one persistent physical-device process executes the
# fixed Custom→Design→Clone Speed/medium plan, three retained takes per mode. This is a
# retention/pressure qualification record, not an Instruments trace; use `profile --kind memory`
# for Allocations + VM Tracker. The runner writes one terminal sentinel only after all nine takes.
cmd_memory() {
  require_team
  local label="memory-qualification" voice_id=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --label) label="${2:-}"; shift 2 ;;
      --label=*) label="${1#*=}"; shift ;;
      --voice-id) voice_id="${2:-}"; shift 2 ;;
      --voice-id=*) voice_id="${1#*=}"; shift ;;
      *) die "memory accepts only --voice-id SAVED_VOICE_ID and --label ID" ;;
    esac
  done
  validate_benchmark_label "$label"
  [[ -n "$voice_id" ]] || die "memory qualification requires --voice-id <exact-prepared-saved-voice-id>"
  local policy="$ROOT_DIR/config/memory-qualification-policy.json"
  [[ -f "$policy" ]] || die "memory qualification policy is missing: $policy"
  local run_id="ios-memory-qualification-$(date -u +%Y%m%d-%H%M%S)-$(benchmark_nonce)"
  local artifacts="$QVOICE_ARTIFACTS_IOS/memory/$run_id"
  local dest="$artifacts/device-diagnostics"
  local launch_json="$artifacts/launch.json"
  local timeout="${QVOICE_IOS_MEMORY_TIMEOUT:-900}"
  [[ "$timeout" =~ ^[1-9][0-9]*$ ]] || die "QVOICE_IOS_MEMORY_TIMEOUT must be a positive whole number of seconds"
  mkdir -p "$artifacts"
  local plan_json
  plan_json="$(python3 -c '
import json, sys
p = json.load(open(sys.argv[1]))
keys = ("schemaVersion", "policyID", "modes", "variant", "length", "repetitionsPerMode", "seed")
plan = {key: p[key] for key in keys}
plan["runID"] = sys.argv[2]
print(json.dumps(plan, sort_keys=True, separators=(",", ":")))' "$policy" "$run_id")" \
    || die "could not construct the bounded memory qualification plan"

  cmd_build
  cmd_install >/dev/null
  capture_benchmark_source "$artifacts"
  rm -rf "$dest"
  local dev env_json
  dev="$(resolve_device)"
  export QVOICE_IOS_DEVICE_MEMORY_QUALIFICATION_SPEC="$plan_json"
  export QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID="$voice_id"
  export QVOICE_IOS_DEVICE_RUN_ID="$run_id"
  export QVOICE_MAC_BENCH_RUN_ID="$run_id"
  export QWENVOICE_NATIVE_TELEMETRY_MODE=verbose
  env_json="$(QV_RUNID="$run_id" python3 -c '
import json, os
keys = (
    "QVOICE_IOS_DEVICE_MEMORY_QUALIFICATION_SPEC",
    "QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID",
    "QVOICE_IOS_DEVICE_RUN_ID",
    "QVOICE_MAC_BENCH_RUN_ID",
    "QWENVOICE_NATIVE_TELEMETRY_MODE",
)
env = {"QWENVOICE_DEBUG": "1", **{key: os.environ[key] for key in keys}}
print(json.dumps(env, sort_keys=True))')"
  note "memory qualification: one process, Custom→Design→Clone, 3 retained takes per mode"
  xcrun devicectl device process launch --device "$dev" --terminate-existing \
    -e "$env_json" --json-output "$launch_json" "$BUNDLE_ID" >"$artifacts/launch.log" 2>&1 \
    || die "could not launch the memory qualification plan (see $artifacts/launch.log)"
  local target_pid
  target_pid="$(read_devicectl_launch_pid "$launch_json")" \
    || die "memory qualification launch did not return its exact process PID"
  [[ "$target_pid" =~ ^[0-9]+$ ]] || die "memory qualification returned an invalid process PID"
  local cleanup_command
  printf -v cleanup_command \
    'xcrun devicectl device process terminate --device %q --pid %q --quiet >/dev/null 2>&1 || true' \
    "$dev" "$target_pid"
  trap "$cleanup_command" EXIT
  unset QVOICE_IOS_DEVICE_MEMORY_QUALIFICATION_SPEC \
    QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID QVOICE_IOS_DEVICE_RUN_ID \
    QVOICE_MAC_BENCH_RUN_ID QWENVOICE_NATIVE_TELEMETRY_MODE

  local sentinel
  sentinel="$({ wait_memory_qualification_sentinel "$run_id" "$timeout" "$dest"; })" \
    || die "memory qualification failed or did not produce its PASS sentinel; no history was published (see $artifacts)"
  python3 - "$sentinel" <<'PY' \
    || die "memory qualification terminal sentinel is not a successful nine-take result"
import json, sys
record = json.load(open(sys.argv[1]))
takes = record.get("takes") or []
expected_modes = ["custom"] * 3 + ["design"] * 3 + ["clone"] * 3
expected_cells = [
    f"{mode}/speed/medium/retained#{repetition}"
    for mode in ("custom", "design", "clone")
    for repetition in range(3)
]
if record.get("status") != "pass" or len(takes) != 9:
    raise SystemExit(1)
if [take.get("mode") for take in takes] != expected_modes:
    raise SystemExit(2)
if [take.get("takeIndex") for take in takes] != list(range(1, 10)):
    raise SystemExit(3)
if [take.get("cell") for take in takes] != expected_cells:
    raise SystemExit(4)
PY
  local diag="$dest"
  local engine_jsonl
  engine_jsonl="$(find "$dest" -path '*/engine/generations.jsonl' 2>/dev/null | head -1)"
  [[ -n "$engine_jsonl" ]] && diag="$(dirname "$(dirname "$engine_jsonl")")"
  local output_dir="$(dirname "$sentinel")/outputs"
  python3 "$ROOT_DIR/scripts/publish_benchmark_history.py" memory-qualification \
    --artifact-dir "$artifacts" --snapshot "$artifacts/benchmark-source.json" \
    --platform ios --run-id "$run_id" --results "$sentinel" --diagnostics "$diag" \
    --output-dir "$output_dir" --label "$label" --defer-record \
    || die "memory sequence passed but qualification failed; artifacts are preserved in $artifacts"
  python3 "$ROOT_DIR/scripts/summarize_generation_telemetry.py" "$diag" \
    --run-id "$run_id" --evidence-manifest "$artifacts/benchmark-evidence.json" \
    --engine-only --label "$label" >"$artifacts/summary.txt" 2>&1 \
    || die "memory qualification evidence was valid but its frozen summary failed"
  record_benchmark_history "$artifacts" >/dev/null \
    || die "memory qualification history publication failed"
  eval "$cleanup_command"
  trap - EXIT
  note "memory qualification PASS · $artifacts"
}

# clone-conditioning [--label ID]: run two clone generations in one exact app process.
# Take 1 uses the canonical saved voice with its transcript; take 2 uses an exact
# purpose-owned audio copy without a sidecar or prepared voice ID. This is a local
# semantic acceptance lane and deliberately never publishes benchmark history.
cmd_clone_conditioning() {
  require_team
  local label="clone-conditioning" timeout="${QVOICE_IOS_CLONE_CONDITIONING_TIMEOUT:-900}"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --label) label="${2:-}"; shift 2 ;;
      --label=*) label="${1#*=}"; shift ;;
      *) die "clone-conditioning accepts only --label ID" ;;
    esac
  done
  validate_benchmark_label "$label"
  [[ "$timeout" =~ ^[1-9][0-9]*$ ]] \
    || die "QVOICE_IOS_CLONE_CONDITIONING_TIMEOUT must be a positive whole number of seconds"

  local run_id="ios-clone-conditioning-$(date -u +%Y%m%d-%H%M%S)-$(benchmark_nonce)"
  local artifacts="$QVOICE_ARTIFACTS_IOS/clone-conditioning/$run_id"
  local dest="$artifacts/device-diagnostics"
  local launch_json="$artifacts/launch.json"
  mkdir -p "$artifacts"

  cmd_build --device-diagnostics
  cmd_install >/dev/null
  capture_benchmark_source "$artifacts"
  rm -rf "$dest"

  local dev env_json target_pid cleanup_command sentinel diag engine_jsonl output_dir
  dev="$(resolve_device)"
  export QVOICE_IOS_DEVICE_CLONE_CONDITIONING_ACCEPTANCE=1
  export QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID="$MAC_TEST_CLONE_VOICE_NAME"
  export QVOICE_IOS_DEVICE_DIAGNOSTICS_EXPECTED_CLONE_AUDIO_SHA256="$MAC_TEST_CLONE_REF_SHA256"
  export QVOICE_IOS_DEVICE_DIAGNOSTICS_EXPECTED_CLONE_TRANSCRIPT_SHA256="$MAC_TEST_CLONE_REF_TRANSCRIPT_SHA256"
  export QVOICE_IOS_DEVICE_RUN_ID="$run_id"
  export QVOICE_MAC_BENCH_RUN_ID="$run_id"
  export QWENVOICE_NATIVE_TELEMETRY_MODE=verbose
  env_json="$(python3 -c '
import json, os
keys = (
    "QVOICE_IOS_DEVICE_CLONE_CONDITIONING_ACCEPTANCE",
    "QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID",
    "QVOICE_IOS_DEVICE_DIAGNOSTICS_EXPECTED_CLONE_AUDIO_SHA256",
    "QVOICE_IOS_DEVICE_DIAGNOSTICS_EXPECTED_CLONE_TRANSCRIPT_SHA256",
    "QVOICE_IOS_DEVICE_RUN_ID",
    "QVOICE_MAC_BENCH_RUN_ID",
    "QWENVOICE_NATIVE_TELEMETRY_MODE",
)
print(json.dumps({"QWENVOICE_DEBUG": "1", **{key: os.environ[key] for key in keys}}, sort_keys=True))
')"
  note "clone-conditioning: transcript-backed then x-vector-only in one exact process"
  xcrun devicectl device process launch --device "$dev" --terminate-existing \
    -e "$env_json" --json-output "$launch_json" "$BUNDLE_ID" >"$artifacts/launch.log" 2>&1 \
    || die "could not launch clone-conditioning acceptance (see $artifacts/launch.log)"
  target_pid="$(read_devicectl_launch_pid "$launch_json")" \
    || die "clone-conditioning launch did not return its exact process PID"
  [[ "$target_pid" =~ ^[0-9]+$ ]] || die "clone-conditioning returned an invalid process PID"
  printf -v cleanup_command \
    'xcrun devicectl device process terminate --device %q --pid %q --quiet >/dev/null 2>&1 || true' \
    "$dev" "$target_pid"
  trap "$cleanup_command" EXIT
  unset QVOICE_IOS_DEVICE_CLONE_CONDITIONING_ACCEPTANCE \
    QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID \
    QVOICE_IOS_DEVICE_DIAGNOSTICS_EXPECTED_CLONE_AUDIO_SHA256 \
    QVOICE_IOS_DEVICE_DIAGNOSTICS_EXPECTED_CLONE_TRANSCRIPT_SHA256 \
    QVOICE_IOS_DEVICE_RUN_ID QVOICE_MAC_BENCH_RUN_ID QWENVOICE_NATIVE_TELEMETRY_MODE

  sentinel="$({ wait_clone_conditioning_sentinel "$run_id" "$timeout" "$dest"; })" \
    || die "clone-conditioning acceptance failed; no PASS evidence was accepted (see $artifacts)"
  eval "$cleanup_command"
  trap - EXIT
  cmd_pull "$dest" >/dev/null 2>&1 || true

  diag="$dest"
  engine_jsonl="$(find "$dest" -path '*/engine/generations.jsonl' 2>/dev/null | head -1)"
  [[ -n "$engine_jsonl" ]] && diag="$(dirname "$(dirname "$engine_jsonl")")"
  output_dir="$(dirname "$sentinel")/outputs"
  python3 "$ROOT_DIR/scripts/check_ios_clone_conditioning.py" \
    --result "$sentinel" --diagnostics "$diag" --outputs "$output_dir" \
    --snapshot "$artifacts/benchmark-source.json" --crash-diagnostics "$dest" \
    --run-id "$run_id" --label "$label" \
    --expected-voice-id "$MAC_TEST_CLONE_VOICE_NAME" \
    --expected-audio-sha256 "$MAC_TEST_CLONE_REF_SHA256" \
    --expected-transcript-sha256 "$MAC_TEST_CLONE_REF_TRANSCRIPT_SHA256" \
    --output "$artifacts/clone-conditioning-validation.json" \
    || die "clone-conditioning evidence validation failed (see $artifacts)"
  note "clone-conditioning PASS · local evidence only · $artifacts"
}

# delivery-reliability --plan PLAN.json --script-file SCRIPT.txt
# Runs the schema-bound startup matrix in one diagnostics-compiled app process.
# The exact script is carried only by an ephemeral launch-spec file/environment
# value. Retained evidence contains its digest and character count.
cmd_delivery_reliability() {
  require_team
  local plan="" script_file="" timeout="${QVOICE_IOS_DELIVERY_RELIABILITY_TIMEOUT:-3600}"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --plan) plan="${2:-}"; shift 2 ;;
      --plan=*) plan="${1#*=}"; shift ;;
      --script-file) script_file="${2:-}"; shift 2 ;;
      --script-file=*) script_file="${1#*=}"; shift ;;
      *) die "delivery-reliability accepts only --plan PLAN.json and --script-file SCRIPT.txt" ;;
    esac
  done
  [[ -f "$plan" ]] || die "delivery-reliability requires a readable --plan"
  [[ -f "$script_file" ]] || die "delivery-reliability requires a readable --script-file"
  [[ "$timeout" =~ ^[1-9][0-9]*$ ]] \
    || die "QVOICE_IOS_DELIVERY_RELIABILITY_TIMEOUT must be a positive whole number of seconds"

  local run_id="ios-startup-reliability-$(date -u +%Y%m%d-%H%M%S)-$(benchmark_nonce)"
  local artifacts="$QVOICE_ARTIFACTS_DIAGNOSTICS/ios/startup-reliability/$run_id"
  local pulled="$artifacts/device-diagnostics"
  local launch_spec launch_json dev env_json target_pid="" cleanup_command="" wait_status=0
  mkdir -p "$artifacts"
  launch_spec="$(mktemp)"
  launch_json="$artifacts/launch.json"
  python3 "$ROOT_DIR/scripts/ios_startup_reliability.py" prepare \
    --plan "$plan" --script-file "$script_file" --run-id "$run_id" \
    --sanitized-output "$artifacts/sanitized-plan.json" --launch-output "$launch_spec" \
    || { rm -f "$launch_spec"; die "startup-reliability plan/script validation failed"; }

  cmd_build --device-diagnostics
  cmd_install >/dev/null
  snapshot_startup_reliability_crashes "$artifacts/crashes-before" \
    || { rm -f "$launch_spec"; die "could not establish the pre-run crash baseline"; }
  snapshot_startup_reliability_system_crashes "$artifacts/system-crashes-before" \
    || { rm -f "$launch_spec"; die "could not establish the pre-run systemCrashLogs baseline"; }
  rm -rf "$artifacts/system-crashes-before/pull"
  dev="$(resolve_device)"
  export QVOICE_IOS_DEVICE_DELIVERY_RELIABILITY_SPEC="$(<"$launch_spec")"
  export QVOICE_IOS_DEVICE_RUN_ID="$run_id"
  export QVOICE_MAC_BENCH_RUN_ID="$run_id"
  export QWENVOICE_NATIVE_TELEMETRY_MODE=verbose
  env_json="$(python3 -c '
import json, os
keys = (
    "QVOICE_IOS_DEVICE_DELIVERY_RELIABILITY_SPEC",
    "QVOICE_IOS_DEVICE_RUN_ID",
    "QVOICE_MAC_BENCH_RUN_ID",
    "QWENVOICE_NATIVE_TELEMETRY_MODE",
)
print(json.dumps({"QWENVOICE_DEBUG": "1", **{key: os.environ[key] for key in keys}}, sort_keys=True))
')"
  unset QVOICE_IOS_DEVICE_DELIVERY_RELIABILITY_SPEC QVOICE_IOS_DEVICE_RUN_ID \
    QVOICE_MAC_BENCH_RUN_ID QWENVOICE_NATIVE_TELEMETRY_MODE
  rm -f "$launch_spec"

  note "startup reliability: schema-bound physical-device matrix (runID=$run_id)"
  xcrun devicectl device process launch --device "$dev" --terminate-existing \
    -e "$env_json" --json-output "$launch_json" "$BUNDLE_ID" \
    >"$artifacts/launch.log" 2>&1 \
    || die "could not launch startup-reliability diagnostics (see $artifacts/launch.log)"
  target_pid="$(read_devicectl_launch_pid "$launch_json")" \
    || die "startup-reliability launch did not return its exact process PID"
  # The launch response is needed only to bind the exact PID. Discard it before
  # collection so an OS tooling change cannot retain ephemeral launch input.
  rm -f "$launch_json"
  [[ "$target_pid" =~ ^[0-9]+$ ]] || die "startup-reliability returned an invalid process PID"
  printf -v cleanup_command \
    'xcrun devicectl device process terminate --device %q --pid %q --quiet >/dev/null 2>&1 || true' \
    "$dev" "$target_pid"
  trap "$cleanup_command" EXIT

  set +e
  wait_startup_reliability_result "$run_id" "$timeout" "$pulled" "$dev" "$target_pid" >/dev/null
  wait_status=$?
  set -e
  local process_exited=0
  (( wait_status == 27 )) && process_exited=1
  # Forensics are mandatory even after a timeout, typed failure, or disconnected
  # device. Keep each collection best-effort so the first failure is not erased.
  pull_startup_reliability_run "$run_id" "$pulled" >"$artifacts/final-pull.log" 2>&1 || true
  if ! snapshot_startup_reliability_crashes "$artifacts/crashes-after"; then
    warn "could not establish the post-run crash snapshot"
    wait_status=26
  fi
  if ! snapshot_startup_reliability_system_crashes "$artifacts/system-crashes-after"; then
    warn "could not establish the post-run systemCrashLogs snapshot"
    wait_status=26
  elif ! collect_startup_reliability_system_crash_delta \
      "$artifacts/system-crashes-before" "$artifacts/system-crashes-after" \
      "$artifacts/system-crash-delta"; then
    warn "could not sanitize the system crash-log delta"
    wait_status=26
  elif python3 - "$artifacts/system-crash-delta/system-crash-summary.json" <<'PY'
import json, sys
raise SystemExit(0 if json.load(open(sys.argv[1], encoding="utf-8")).get("reports") else 1)
PY
  then
    warn "startup-reliability produced a correlated system crash-log delta"
    wait_status=25
  fi
  rm -rf "$artifacts/system-crashes-after/pull"
  local crash_delta
  crash_delta="$(comm -13 "$artifacts/crashes-before/hashes.txt" "$artifacts/crashes-after/hashes.txt" 2>/dev/null || true)"
  if [[ -n "$crash_delta" ]]; then
    printf '%s\n' "$crash_delta" >"$artifacts/new-crashes.txt"
    wait_status=25
  fi
  eval "$cleanup_command"
  trap - EXIT

  if (( process_exited == 1 )); then
    python3 "$ROOT_DIR/scripts/ios_startup_reliability.py" compose-process-exit \
      --plan "$plan" --artifact-dir "$pulled" --run-id "$run_id" \
      --output "$artifacts/startup-reliability-forensics.json" \
      || warn "could not compose the process-exit forensic summary"
  fi

  (( wait_status == 0 )) \
    || die "startup-reliability run did not produce acceptable terminal evidence (status=$wait_status; see $artifacts)"
  python3 "$ROOT_DIR/scripts/ios_startup_reliability.py" validate-result \
    --plan "$plan" --artifact-dir "$pulled" --run-id "$run_id" \
    || die "startup-reliability evidence validation failed (see $artifacts)"
  cleanup_startup_reliability_device_evidence "$run_id" "$dev" "$artifacts" \
    || die "startup-reliability evidence was collected but device cleanup failed (see $artifacts)"
  note "startup reliability evidence → $artifacts"
}

# memory-field-report [pulled-diagnostics]: summarize privacy-reduced MetricKit memory
# aggregates already present on disk. MetricKit delivery is delayed and not run-correlated,
# so absence reports notYetDelivered and remains nonfatal. This command intentionally does
# not resolve, wake, pull from, or otherwise contact a physical iPhone.
cmd_memory_field_report() {
  [[ $# -le 1 ]] || die "memory-field-report accepts at most one local diagnostics path"
  local source="${1:-$QVOICE_ARTIFACTS_DIAGNOSTICS/ios/device-diagnostics}"
  python3 "$ROOT_DIR/scripts/ios_memory_field_report.py" "$source"
}

# preflight: physical-device reachability, signing, app, and dSYM.
# It fails fast with concrete remediation.
cmd_preflight() {
  local rc=0
  [[ $# -eq 0 ]] || die "preflight accepts no arguments"
  note "on-device preflight"

  local dev; dev="$(resolve_device 2>/dev/null)" || dev=""
  if [[ -z "$dev" ]]; then warn "  device: ✗ none resolved"; rc=1; else printf '  device: %s\n' "$dev" >&2; fi

  if [[ -n "$dev" ]]; then
    local tmp; tmp="$(mktemp)"
    if xcrun devicectl list devices --json-output "$tmp" >/dev/null 2>&1; then
      python3 - "$tmp" "$dev" <<'PY' >&2 || rc=1
import json, sys
data = json.load(open(sys.argv[1]))
devs = (data.get("result") or {}).get("devices") or []
m = next((d for d in devs if d.get("identifier") == sys.argv[2]), None)
if not m:
    print("  reachability: ✗ device not in devicectl list"); sys.exit(1)
cp = m.get("connectionProperties") or {}
tunnel, pairing = cp.get("tunnelState", ""), cp.get("pairingState", "")
ok = tunnel in ("connected", "available") or pairing == "paired"
print(f"  reachability: {'OK' if ok else 'FAIL'} tunnel={tunnel or '?'} pairing={pairing or '?'}")
sys.exit(0 if ok else 1)
PY
    else
      warn "  reachability: ✗ devicectl list failed"; rc=1
    fi
    rm -f "$tmp"
    if ! guard_device_state "$dev"; then rc=1; fi
  fi

  local team; team="$(derive_team 2>/dev/null)"
  if [[ -n "$team" ]]; then
    printf '  signing: OK team %s\n' "$team" >&2
  else
    warn "  signing: ✗ no team (set QWENVOICE_DEVELOPMENT_TEAM or add an Apple Development cert)"; rc=1
  fi

  if [[ -d "$APP_PATH" ]]; then
    printf '  app: OK %s\n' "$APP_PATH" >&2
    if [[ -d "$QVOICE_SYMBOLS_IOS/Vocello.app.dSYM" ]]; then
      validate_dsym_identity "$APP_PATH/Vocello" "$QVOICE_SYMBOLS_IOS/Vocello.app.dSYM"
      printf '  dsym: OK %s (UUID matches app)\n' "$QVOICE_SYMBOLS_IOS/Vocello.app.dSYM" >&2
    else
      warn "  dsym: ✗ none (run '$0 build' to enable crash symbolication)"
    fi
  else
    warn "  app: ✗ not built (run: $0 build)"; rc=1
  fi

  (( rc == 0 )) && note "preflight OK" || die "preflight not ready (see above)"
}

# Fail when ColdGeneration was skipped because the Speed model is missing on device.
_gate_generation_check() {
  local gate_dir="$1"
  # The gate must not launch an older app already present on the phone. Rebuild,
  # install the exact APP_PATH, then snapshot that same local binary identity before
  # the diagnostic generation starts.
  cmd_build
  cmd_install >/dev/null
  local run_id="ios-gate-bench-$(date -u +%Y%m%d-%H%M%S)-$(benchmark_nonce)"
  local artifacts="$gate_dir/engine-benchmark"
  mkdir -p "$artifacts"
  capture_benchmark_source "$artifacts"
  export QVOICE_LAUNCH_RUN_ID="$run_id"
  export QVOICE_MAC_BENCH_RUN_ID="$run_id"
  export QVOICE_MAC_BENCH_TAKE_INDEX=1
  export QVOICE_MAC_BENCH_CELL="$(device_benchmark_cell "custom:speed:Gate generation smoke.")"
  export QWENVOICE_NATIVE_TELEMETRY_MODE=verbose
  local launched_run_id
  launched_run_id="$(cmd_launch "custom:speed:Gate generation smoke." | tail -1)"
  unset QVOICE_LAUNCH_RUN_ID QVOICE_MAC_BENCH_RUN_ID QVOICE_MAC_BENCH_TAKE_INDEX \
    QVOICE_MAC_BENCH_CELL QWENVOICE_NATIVE_TELEMETRY_MODE
  [[ "$launched_run_id" == "$run_id" ]] || { echo "gate generation launched the wrong run ID"; return 1; }
  local timeout="${QVOICE_IOS_BENCH_TIMEOUT:-300}"
  local dest="$artifacts/device-diagnostics"
  rm -rf "$dest"
  local waited=0 sentinel=""
  local interference_streak=0
  while (( waited < timeout )); do
    sleep 10; waited=$((waited + 10))
    ( cmd_pull "$dest" ) >/dev/null 2>&1 || true
    sentinel="$(find "$dest" -name device-diagnostics-done.json -path "*/${run_id}/*" 2>/dev/null | head -1)"
    [[ -n "$sentinel" && -f "$sentinel" ]] && break
    # Fast-abort on interference (same policy as cmd_bench's poll loop).
    local state verdict
    state="$(probe_device_state 2>/dev/null || true)"
    verdict="${state%%|*}"
    case "$verdict" in
      DEVICE_UNREACHABLE)
        echo "aborted at ${waited}s — $verdict: $(device_state_advice "$verdict")"
        return 1
        ;;
      *) interference_streak=0 ;;
    esac
  done
  [[ -n "$sentinel" && -f "$sentinel" ]] || { echo "no device-diagnostics sentinel after ${timeout}s (device state: $(probe_device_state 2>/dev/null || echo unknown))"; return 1; }
  cp "$sentinel" "$gate_dir/generation-sentinel.json" 2>/dev/null || true
  python3 - "$sentinel" <<'PY' || return 1
import json, sys
r = json.load(open(sys.argv[1]))
print(f"status={r.get('status')} mode={r.get('mode')} rtf={r.get('realtimeFactor')} wall={r.get('wallSeconds')}s error={r.get('error')}")
for e in r.get("interruptions") or []:
    print(f"interruption: {e.get('type')} at t={(e.get('atMS') or 0) / 1000.0:.1f}s")
sys.exit(0 if r.get("status") == "ok" else 1)
PY
  require_uninterrupted_success_sentinel "$sentinel" || return 1
  local diag="$dest"
  local engine_jsonl
  engine_jsonl="$(find "$dest" -path '*/engine/generations.jsonl' 2>/dev/null | head -1)"
  [[ -n "$engine_jsonl" ]] && diag="$(dirname "$(dirname "$engine_jsonl")")"
  python3 "$ROOT_DIR/scripts/publish_benchmark_history.py" ios-engine \
    --artifact-dir "$artifacts" --snapshot "$artifacts/benchmark-source.json" \
    --run-id "$run_id" --sentinel "$sentinel" --diagnostics "$diag" \
    --crash-diagnostics "$dest" --label "ios-gate-bench" --defer-record || return 1
  python3 "$ROOT_DIR/scripts/summarize_generation_telemetry.py" "$diag" \
    --run-id "$run_id" --evidence-manifest "$artifacts/benchmark-evidence.json" \
    --engine-only --label "ios-gate-bench" || return 1
}

cmd_gate() {
  local run_id="ios-gate-$(date +%Y%m%d-%H%M%S)"
  local gate_dir="$QVOICE_ARTIFACTS_IOS/gates/$run_id"
  local verdict="$gate_dir/verdict.txt"
  local step_ledger="$gate_dir/required-steps.json"
  local workflow="ios-gate"
  [[ "${QVOICE_GATE_SKIP_GENERATION:-0}" != "1" ]] || workflow="ios-gate-without-generation"
  mkdir -p "$gate_dir"
  required_steps_init "$step_ledger" "$workflow" "$run_id"
  note "iOS device gate: project inputs"
  required_step_run "$step_ledger" project-inputs \
    "$ROOT_DIR/scripts/check_project_inputs.sh" >"$gate_dir/inputs.log" 2>&1 \
    || { echo "project-inputs: FAIL" | tee "$verdict"; return 1; }
  echo "project-inputs: PASS" | tee "$verdict"
  note "iOS device gate: physical-device preflight"
  required_step_run "$step_ledger" device-preflight cmd_preflight \
    >"$gate_dir/preflight.log" 2>&1 \
    || { echo "preflight: FAIL" | tee -a "$verdict"; return 1; }
  echo "preflight: PASS" | tee -a "$verdict"
  note "iOS device gate: headless generation"
  if [[ "${QVOICE_GATE_SKIP_GENERATION:-0}" == "1" ]]; then
    echo "generation: SKIPPED" | tee -a "$verdict"
  elif required_step_run "$step_ledger" generation _gate_generation_check "$gate_dir" \
      >"$gate_dir/generation.log" 2>&1; then
    echo "generation: PASS" | tee -a "$verdict"
  else
    echo "generation: FAIL" | tee -a "$verdict"; return 1
  fi
  note "iOS device gate: crashes"
  required_step_run "$step_ledger" crash-delta cmd_crashes \
    >"$gate_dir/crashes.log" 2>&1 \
    || { echo "crashes: FAIL" | tee -a "$verdict"; return 1; }
  echo "crashes: PASS" | tee -a "$verdict"
  if [[ "${QVOICE_GATE_SKIP_GENERATION:-0}" != "1" ]]; then
    required_step_run "$step_ledger" history-publication \
      record_benchmark_history "$gate_dir/engine-benchmark" >/dev/null \
      || { echo "history: FAIL" | tee -a "$verdict"; return 1; }
    echo "history: PASS" | tee -a "$verdict"
  fi
  required_steps_finalize "$step_ledger" \
    || { echo "GATE: FAIL (required-step ledger)" | tee -a "$verdict"; return 1; }
  echo "GATE: PASS" | tee -a "$verdict"
  note "iOS gate PASS · $gate_dir"
}

main() {
  local sub="${1:-help}"; shift || true
  case "$sub" in
    doctor)  cmd_doctor "$@" ;;
    build)   cmd_build "$@" ;;
    install) cmd_install "$@" ;;
    launch)  cmd_launch "$@" ;;
    console) cmd_console "$@" ;;
    device-state) cmd_device_state "$@" ;;
    pull)    cmd_pull "$@" ;;
    bench)
      require_build_free_space memory-qualification || die "iOS benchmark storage preflight failed"
      cmd_bench "$@"
      ;;
    lang-bench)
      require_build_free_space language-benchmark || die "iOS language benchmark storage preflight failed"
      cmd_lang_bench "$@"
      ;;
    delivery-reliability)
      require_build_free_space startup-reliability || die "iOS startup-reliability storage preflight failed"
      cmd_delivery_reliability "$@"
      ;;
    speech-assets) cmd_speech_assets "$@" ;;
    enroll-clone-fixture) cmd_enroll_clone_fixture "$@" ;;
    crashes) cmd_crashes "$@" ;;
    debug)   cmd_debug "$@" ;;
    logs)    cmd_logs "$@" ;;
    profile) cmd_profile "$@" ;;
    memory)
      require_build_free_space memory-qualification || die "iOS memory qualification storage preflight failed"
      cmd_memory "$@"
      ;;
    clone-conditioning)
      require_build_free_space memory-qualification || die "iOS clone-conditioning storage preflight failed"
      cmd_clone_conditioning "$@"
      ;;
    memory-field-report) cmd_memory_field_report "$@" ;;
    preflight) cmd_preflight "$@" ;;
    gate)
      require_build_free_space memory-qualification || die "iOS gate storage preflight failed"
      cmd_gate "$@"
      ;;
    help|-h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//' >&2 ;;
    *) die "unknown subcommand '$sub' (try: doctor|build|install|launch|console|device-state|pull|bench|lang-bench|delivery-reliability|speech-assets|enroll-clone-fixture|crashes|debug|logs|profile|memory|clone-conditioning|memory-field-report|preflight|gate|help)" ;;
  esac
}

main "$@"
