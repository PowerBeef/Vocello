#!/usr/bin/env bash
# Explicit native app UI automation. This command is never called by ordinary CI,
# deterministic gates, or release packaging.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT_DIR/scripts/lib/build_paths.sh"
. "$ROOT_DIR/scripts/lib/build_cache.sh"
. "$ROOT_DIR/scripts/lib/required_steps.sh"
PROJECT="$ROOT_DIR/QwenVoice.xcodeproj"
MAC_DERIVED="$QVOICE_XCODE_MACOS_DERIVED"
IOS_DERIVED="$QVOICE_XCODE_IOS_DERIVED"
BUNDLE_ID_IOS="com.patricedery.vocello"
MAC_TAKE_MANIFEST="/tmp/vocello-bench-current-take.json"
MAC_APP_EXECUTABLE="$MAC_DERIVED/Build/Products/Release/Vocello.app/Contents/MacOS/Vocello"
MAC_ENGINE_EXECUTABLES=(
  "$MAC_DERIVED/Build/Products/Release/Vocello.app/Contents/XPCServices/QwenVoiceEngineService.xpc/Contents/MacOS/QwenVoiceEngineService"
  "$MAC_DERIVED/Build/Products/Release/QwenVoiceEngineService.xpc/Contents/MacOS/QwenVoiceEngineService"
)
. "$ROOT_DIR/scripts/lib/test_models.sh"
test_models_init "$ROOT_DIR"

note() { printf '\033[0;36m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[0;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

validate_benchmark_label() {
  local value="$1"
  [[ -z "$value" || "$value" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$ ]] \
    || die "--label must be an opaque 1-96 character ID using letters, digits, dot, underscore, or hyphen"
}

usage() {
  cat >&2 <<'EOF'
Usage:
  scripts/ui_test.sh macos smoke [--long-form-segments N]
  scripts/ui_test.sh macos benchmark [--modes custom,design,clone] [--lengths short,medium,long] [--warm 3] [--label RUN_ID]
  scripts/ui_test.sh ios smoke
  scripts/ui_test.sh ios benchmark [--modes custom,design,clone] [--lengths short,medium,long] [--warm 3] [--label RUN_ID]
  scripts/ui_test.sh ios model-download

The iOS destination is the paired physical iPhone only. Simulator destinations are unsupported.
`model-download` is an opt-in isolated lifecycle proof and never runs in smoke, benchmark, CI, or release.
Benchmark clone-fixture enrollment moved to the headless diagnostics runner:
`scripts/ios_device.sh enroll-clone-fixture` (the iPhone app no longer ships a Files-import UI).
No lane retries automatically. A failed run keeps its log, xcresult, screenshots, and diagnostics.
RUN_ID is an opaque 1-96 character identifier using letters, digits, dot, underscore, or hyphen.
EOF
  exit 2
}

[[ $# -ge 2 ]] || usage
platform="$1"
lane="$2"
shift 2
[[ "$platform" == "macos" || "$platform" == "ios" ]] || usage
[[ "$lane" == "smoke" || "$lane" == "benchmark" || "$lane" == "model-download" ]] || usage
[[ "$lane" != "model-download" || "$platform" == "ios" ]] || usage

modes="custom,design,clone"
lengths="short,medium,long"
warm=3
label=""
long_form_segments=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --modes) modes="${2:?--modes requires a value}"; shift 2 ;;
    --modes=*) modes="${1#*=}"; shift ;;
    --lengths) lengths="${2:?--lengths requires a value}"; shift 2 ;;
    --lengths=*) lengths="${1#*=}"; shift ;;
    --warm) warm="${2:?--warm requires a value}"; shift 2 ;;
    --warm=*) warm="${1#*=}"; shift ;;
    --label) label="${2:?--label requires a value}"; shift 2 ;;
    --label=*) label="${1#*=}"; shift ;;
    --long-form-segments) long_form_segments="${2:?--long-form-segments requires a value}"; shift 2 ;;
    --long-form-segments=*) long_form_segments="${1#*=}"; shift ;;
    -h|--help|help) usage ;;
    *) die "unknown flag: $1" ;;
  esac
done
validate_benchmark_label "$label"

if [[ "$lane" != "benchmark" && ( "$modes" != "custom,design,clone" || "$lengths" != "short,medium,long" || "$warm" != 3 || -n "$label" ) ]]; then
  die "benchmark flags are accepted only by the benchmark lane"
fi

# Optional macOS-smoke-only scaling of the long-form journey. Local evidence
# only: it changes the planned segment count of the existing journey, never
# what publishes.
if [[ -n "$long_form_segments" ]]; then
  [[ "$platform" == "macos" && "$lane" == "smoke" ]] \
    || die "--long-form-segments applies to the macOS smoke lane only"
  [[ "$long_form_segments" =~ ^[0-9]+$ ]] \
    && (( long_form_segments >= 2 && long_form_segments <= 12 )) \
    || die "--long-form-segments must be an integer between 2 and 12"
fi

python3 - "$modes" "$lengths" "$warm" <<'PY' || exit $?
import sys
modes = [v.strip() for v in sys.argv[1].split(',') if v.strip()]
lengths = [v.strip() for v in sys.argv[2].split(',') if v.strip()]
try:
    warm = int(sys.argv[3])
except ValueError:
    raise SystemExit("error: --warm must be an integer")
if not modes or len(modes) != len(set(modes)) or set(modes) - {"custom", "design", "clone"}:
    raise SystemExit("error: --modes must be a unique subset of custom,design,clone")
if not lengths or len(lengths) != len(set(lengths)) or set(lengths) - {"short", "medium", "long"}:
    raise SystemExit("error: --lengths must be a unique subset of short,medium,long")
if warm < 1:
    raise SystemExit("error: --warm must be at least 1")
PY

if [[ "$platform" == "ios" ]]; then
  require_ios_xcode_platform \
    || die "iOS UI build is blocked by the selected Xcode toolchain"
fi
require_build_free_space "ui-$lane" \
  || die "$platform $lane storage preflight failed before build or target launch"

if [[ "$platform" == "macos" && "$lane" == "benchmark" && ",${modes}," == *",clone,"* ]]; then
  mac_test_clone_fixture_current \
    || die "benchmark clone reference is stale; run: scripts/macos_test.sh models ensure"
fi

command -v xcodebuild >/dev/null 2>&1 || die "xcodebuild not found"
[[ -d "$PROJECT" ]] || die "missing $PROJECT (run ./scripts/regenerate_project.sh)"
ensure_project_regenerated
if [[ "$platform" == "macos" ]]; then
  ensure_spm_resolved "$QVOICE_SCRATCH_PACKAGE_RESOLUTION" \
    "$QVOICE_XCODE_SOURCE_PACKAGES" ui-macos VocelloMacUI Release \
    'platform=macOS,arch=arm64'
else
  ensure_spm_resolved "$QVOICE_SCRATCH_PACKAGE_RESOLUTION" \
    "$QVOICE_XCODE_SOURCE_PACKAGES" ui-ios VocelloiOSUI Release \
    'generic/platform=iOS'
fi

timestamp="$(date -u +%Y%m%d-%H%M%S)"
nonce="$(uuidgen | tr '[:upper:]' '[:lower:]' | cut -c1-8)"
run_id="${platform}-xcui-${lane}-${timestamp}-${nonce}"
out="$QVOICE_ARTIFACTS_UI_TESTS/$platform/$run_id"
result="$out/result.xcresult"
mkdir -p "$out"
step_ledger="$out/required-steps.json"
required_steps_init "$step_ledger" "ui-$platform-$lane" "$run_id"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '%s\n' "$started_at" >"$out/started-at.txt"
printf '%s\n' "${label:-$run_id}" >"$out/label.txt"

write_run_metadata() {
  local status="$1" finished_at="${2:-}" exit_code="${3:-}"
  python3 - "$out/run.json" "$platform" "$lane" "$run_id" "$modes" "$lengths" \
    "$warm" "${label:-$run_id}" "$started_at" "$finished_at" "$status" "$exit_code" <<'PY'
import json, os, pathlib, sys, tempfile

path = pathlib.Path(sys.argv[1])
payload = {
    "platform": sys.argv[2], "lane": sys.argv[3], "runID": sys.argv[4],
    "modes": sys.argv[5].split(','), "lengths": sys.argv[6].split(','),
    "warm": int(sys.argv[7]), "label": sys.argv[8], "status": sys.argv[11],
    "startedAt": sys.argv[9], "finishedAt": sys.argv[10] or None,
    "exitCode": int(sys.argv[12]) if sys.argv[12] else None,
    "schemaVersion": 2,
}
path.parent.mkdir(parents=True, exist_ok=True)
descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
}

run_finalized=0
write_run_metadata running
record_early_failure() {
  local status=$?
  trap - EXIT
  set +e
  write_test_summary || true
  write_run_metadata failed "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$status"
  exit "$status"
}
trap record_early_failure EXIT
required_step_run "$step_ledger" source-provenance \
  python3 "$ROOT_DIR/scripts/publish_benchmark_history.py" snapshot \
  --output "$out/benchmark-source.json" --crash-scope none >/dev/null \
  || die "could not capture pre-run source provenance"

export_attachments() {
  [[ -d "$result" ]] || return 0
  rm -rf "$out/attachments"
  if ! xcrun xcresulttool export attachments --path "$result" \
      --output-path "$out/attachments" >"$out/attachments.log" 2>&1; then
    warn "could not export xcresult attachments (see $out/attachments.log)"
  fi
}

# Advisory only: an undecided mic/speech TCC grant means macOS can raise a
# system permission dialog mid-run. Warn so the operator settles the grant once
# (docs/reference/macos-permissions.md); never blocks the lane. Degrades
# gracefully when the terminal lacks Full Disk Access to read the TCC database.
# Known limitation: this checks row EXISTENCE for the bundle id only — TCC keys
# grants to bundle id + code identity, and the lane's ad-hoc-signed app may not
# match an existing row, so a prompt can still appear despite a decided row.
# That path is only reachable when the virtual-microphone fixture is broken;
# the smoke suite asserts the fixture explicitly.
mac_ui_preflight() {
  local tcc_db="$HOME/Library/Application Support/com.apple.TCC/TCC.db"
  local svc rows
  for svc in kTCCServiceMicrophone kTCCServiceSpeechRecognition; do
    if ! rows="$(sqlite3 -readonly "$tcc_db" \
        "SELECT auth_value FROM access WHERE service='$svc' AND client='com.qwenvoice.app';" \
        2>/dev/null)"; then
      note "ui-preflight: TCC database unreadable (no Full Disk Access) — cannot verify $svc"
      continue
    fi
    if [[ -z "$rows" ]]; then
      warn "ui-preflight: no $svc decision recorded for com.qwenvoice.app — a system permission dialog may appear mid-run; settle it once (docs/reference/macos-permissions.md). Note: an existing row keyed to a different code identity can still prompt for the ad-hoc lane build."
    fi
  done
  return 0
}

# Per-test verdict summary parsed from the xcodebuild log into a compact
# sidecar next to run.json (run.json's schema stays untouched).
write_test_summary() {
  [[ -f "$out/xcodebuild.log" ]] || return 0
  python3 - "$out/xcodebuild.log" "$out/test-results.json" <<'SUMMARY'
import json, pathlib, re, sys

log = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
pattern = re.compile(
    r"Test Case '-\[[\w.]+ (\w+)\]' (passed|failed) \((\d+\.\d+) seconds\)"
)
results = [
    {"test": m.group(1), "verdict": m.group(2), "seconds": float(m.group(3))}
    for m in pattern.finditer(log)
]
payload = {"schemaVersion": 1, "tests": results}
pathlib.Path(sys.argv[2]).write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
for r in results:
    print(f"  {r['verdict']:>6}  {r['seconds']:8.1f}s  {r['test']}")
SUMMARY
}

mac_crash_marker="$out/.mac-crash-marker"
touch "$mac_crash_marker"

check_mac_crash_delta() {
  local root="$HOME/Library/Logs/DiagnosticReports" new
  new="$(find "$root" \( -name 'Vocello-*.ips' -o -name 'QwenVoiceEngineService-*.ips' -o -name '*engine-service*.ips' \) -newer "$mac_crash_marker" -print 2>/dev/null || true)"
  [[ -z "$new" ]] || { printf '%s\n' "$new" >"$out/new-crashes.txt"; die "new Vocello crash report detected (see $out/new-crashes.txt)"; }
}

check_ios_crash_delta() {
  snapshot_ios_crashes "$out/crashes-after" || return 1
  local new_crashes
  new_crashes="$(comm -13 "$out/crashes-before/hashes.txt" "$out/crashes-after/hashes.txt" || true)"
  [[ -z "$new_crashes" ]] \
    || { printf '%s\n' "$new_crashes" >"$out/new-crashes.txt"; return 1; }
}

process_executable_path() {
  local pid="$1" path=""
  if command -v lsof >/dev/null 2>&1; then
    path="$(lsof -a -p "$pid" -d txt -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)"
  fi
  if [[ -z "$path" ]]; then
    path="$(ps -p "$pid" -o comm= 2>/dev/null | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  fi
  printf '%s' "$path"
}

path_is_one_of() {
  local candidate="$1"
  shift
  local expected
  for expected in "$@"; do
    [[ "$candidate" == "$expected" ]] && return 0
  done
  return 1
}

terminate_owned_processes() {
  local name="$1"
  shift
  local -a expected=("$@") pids=()
  local pid path attempt alive candidates
  candidates="$(pgrep -x "$name" 2>/dev/null || true)"
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    path="$(process_executable_path "$pid")"
    path_is_one_of "$path" "${expected[@]}" \
      || die "cannot establish exclusive $name ownership: PID $pid uses ${path:-an unknown executable}, not the exact XCUITest build product"
    pids+=("$pid")
  done <<<"$candidates"
  ((${#pids[@]} > 0)) || return 0

  kill "${pids[@]}" 2>/dev/null || true
  for attempt in {1..40}; do
    alive=false
    for pid in "${pids[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        path="$(process_executable_path "$pid")"
        if [[ -z "$path" ]] && ! kill -0 "$pid" 2>/dev/null; then
          continue
        fi
        path_is_one_of "$path" "${expected[@]}" \
          || die "$name PID $pid changed identity while waiting for termination"
        alive=true
      fi
    done
    $alive || return 0
    sleep 0.1
  done

  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      path="$(process_executable_path "$pid")"
      if [[ -z "$path" ]] && ! kill -0 "$pid" 2>/dev/null; then
        continue
      fi
      path_is_one_of "$path" "${expected[@]}" \
        || die "$name PID $pid changed identity before forced termination"
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
  for attempt in {1..20}; do
    alive=false
    for pid in "${pids[@]}"; do
      kill -0 "$pid" 2>/dev/null && alive=true
    done
    $alive || return 0
    sleep 0.1
  done
  die "could not retire the owned $name process"
}

terminate_macos_app() {
  terminate_owned_processes Vocello "$MAC_APP_EXECUTABLE"
  terminate_owned_processes QwenVoiceEngineService "${MAC_ENGINE_EXECUTABLES[@]}"
}

cleanup_macos_run() {
  # Cleanup must never terminate a different installation of Vocello. A path
  # mismatch remains visible as a suite failure instead of being name-killed.
  terminate_macos_app
  rm -f "$MAC_TAKE_MANIFEST" "$MAC_TAKE_MANIFEST.next"
}

cleanup_ui_run() {
  local status=$?
  trap - EXIT
  set +e
  [[ "$platform" != "macos" ]] || cleanup_macos_run
  if (( run_finalized == 0 )); then
    write_run_metadata failed "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$status"
  fi
  exit "$status"
}

trap cleanup_ui_run EXIT

derive_team() {
  if [[ -n "${QWENVOICE_DEVELOPMENT_TEAM:-}" ]]; then
    printf '%s' "$QWENVOICE_DEVELOPMENT_TEAM"
    return
  fi
  security find-certificate -c "Apple Development" -p 2>/dev/null \
    | openssl x509 -noout -subject 2>/dev/null \
    | grep -oE 'OU=[A-Z0-9]+' | head -1 | cut -d= -f2
}

ios_probe() {
  python3 "$ROOT_DIR/scripts/lib/ios_coredevice_probe.py" probe
}

snapshot_ios_crashes() {
  local destination="$1"
  rm -rf "$destination"
  mkdir -p "$destination"
  if ! "$ROOT_DIR/scripts/ios_device.sh" pull "$destination/pull" \
      >"$destination/pull.log" 2>&1; then
    warn "could not collect the iPhone crash snapshot (see $destination/pull.log)"
    return 1
  fi
  while IFS= read -r -d '' crash; do
    relative="${crash#"$destination/pull/"}"
    hash="$(shasum -a 256 "$crash" | awk '{print $1}')"
    printf '%s  %s\n' "$hash" "$relative"
  done < <(find "$destination/pull" -type f -path '*/crashes/*' -print0 2>/dev/null) \
    | sort >"$destination/hashes.txt"
  # Crash gating needs the stable hashes, not another copy of the device's complete historical
  # diagnostics tree. Exact payload retrieval remains available through ios_device.sh crashes.
  rm -rf "$destination/pull"
}

pull_ios_model_download_diagnostics() {
  local device="$1" destination="$2"
  rm -rf "$destination"
  mkdir -p "$destination"
  xcrun devicectl device copy from --device "$device" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE_ID_IOS" \
    --source "Library/Application Support/Q-Voice/model-download-acceptance/diagnostics/model-downloads" \
    --destination "$destination" >"$out/model-download-diagnostics-pull.log" 2>&1 \
    || return 1
  python3 - "$destination" "$ROOT_DIR/Sources/Resources/qwenvoice_production_model_catalog.json" <<'PY'
import json, os, pathlib, sys

root = pathlib.Path(sys.argv[1])
catalog = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
shared_component_bytes = sum(
    file.get("byteCount", 0)
    for component in catalog.get("sharedComponents", [])
    for file in component.get("contentIdentity", {}).get("files", [])
)
if shared_component_bytes <= 0:
    raise SystemExit("production catalog is missing shared-component byte identities")

files = sorted(root.glob("*.json"))
if not files or len(files) > 60:
    raise SystemExit(f"expected 1-60 compact diagnostic records, found {len(files)}")
if sum(path.stat().st_size for path in files) > 5 * 1024 * 1024:
    raise SystemExit("model-download diagnostics exceed the 5 MiB retention contract")
records = [json.loads(path.read_text(encoding="utf-8")) for path in files]
successes = sorted(
    (
        record for record in records
        if record.get("kind") == "success" and record.get("finalIntegrity") is True
    ),
    key=lambda value: value.get("capturedAtUTC", ""),
)
if len(successes) < 3:
    raise SystemExit(
        "the three-artifact lifecycle requires at least three final-integrity successes; "
        f"found {len(successes)}"
    )
terminal_times = sorted(
    record.get("capturedAtUTC", "") for record in records
    if record.get("kind") in {"success", "failure"}
)

validated = []
for success in successes[-3:]:
    success_time = success.get("capturedAtUTC", "")
    prior = [time for time in terminal_times if time < success_time]
    lower_bound = prior[-1] if prior else ""
    window = [
        record for record in records
        if lower_bound < record.get("capturedAtUTC", "") <= success_time
    ]
    metrics = [
        record for record in window
        if record.get("kind") == "task-metrics" and record.get("relativePath")
    ]
    expected = max(
        (record.get("totalBytes", 0) for record in window if record.get("kind") == "phase"),
        default=success.get("expectedBytes", 0),
    )
    wire = sum(max(0, record.get("transferredBytes", 0)) for record in metrics)
    protocols = sorted({record.get("protocolName") for record in metrics if record.get("protocolName")})
    if expected <= 0 or not protocols:
        raise SystemExit("a selected success is missing complete transfer metrics")
    # Model payload never rides cellular: the download session excludes it, so
    # any cellular payload transfer means the Wi-Fi pin regressed (or Wi-Fi
    # Assist found a new route around it).
    cellular_payload = [record for record in metrics if record.get("cellular") is True]
    if cellular_payload:
        raise SystemExit(
            f"{len(cellular_payload)} payload transfer(s) rode cellular; model "
            "downloads must stay pinned to Wi-Fi"
        )
    # Crawl gate: sustained sub-floor payload throughput is the autonomous
    # stand-in for the observed "download slows to a crawl" failure. The floor
    # is deliberately far below healthy Wi-Fi (tens of MB/s) so only genuine
    # collapse fails; override with QVOICE_IOS_DOWNLOAD_MIN_MBPS.
    floor_mbps = float(os.environ.get("QVOICE_IOS_DOWNLOAD_MIN_MBPS", "2"))
    network_seconds = success.get("networkSeconds") or 0
    artifact_mbps = (wire / network_seconds / 1_000_000) if network_seconds > 0 else None
    transfer_rates = sorted(
        record.get("transferredBytes", 0) / record["durationSeconds"] / 1_000_000
        for record in metrics
        if record.get("durationSeconds", 0) > 0
    )
    if artifact_mbps is not None and artifact_mbps < floor_mbps:
        raise SystemExit(
            f"payload throughput collapsed: {artifact_mbps:.2f} MB/s over "
            f"{network_seconds:.0f}s network window (floor {floor_mbps} MB/s); "
            f"slowest transfer {transfer_rates[0]:.2f} MB/s" if transfer_rates
            else f"payload throughput collapsed: {artifact_mbps:.2f} MB/s (floor {floor_mbps} MB/s)"
        )
    # The shared-component store omits exactly the verified tokenizer bytes from a
    # later artifact's plan. A success must therefore account for its full catalog
    # bytes either entirely on the wire or with exactly the component reused; any
    # other total is duplicate or missing payload and fails closed.
    if wire == expected:
        reused = 0
    elif wire == expected - shared_component_bytes:
        reused = shared_component_bytes
    else:
        raise SystemExit(
            "wire bytes match neither the full artifact nor exact shared-component reuse: "
            f"wire={wire} expected={expected} sharedComponent={shared_component_bytes}"
        )
    validated.append({
        "capturedAtUTC": success_time,
        "finalIntegrity": True,
        "expectedBytes": expected,
        "wireBytes": wire,
        "reusedComponentBytes": reused,
        "duplicateBytes": 0,
        "retryCount": success.get("retryCount", 0),
        "protocols": protocols,
        "thermalState": success.get("thermalState"),
        "networkSeconds": success.get("networkSeconds"),
        "verificationSeconds": success.get("verificationSeconds"),
        "installationSeconds": success.get("installationSeconds"),
        "payloadMBPerSecond": round(artifact_mbps, 3) if artifact_mbps is not None else None,
        "slowestTransferMBPerSecond": round(transfer_rates[0], 3) if transfer_rates else None,
        "medianTransferMBPerSecond": round(transfer_rates[len(transfer_rates) // 2], 3) if transfer_rates else None,
        "throughputFloorMBPerSecond": floor_mbps,
    })

if sum(1 for entry in validated if entry["reusedComponentBytes"] > 0) < 2:
    raise SystemExit(
        "the three-artifact lifecycle must observe shared-component reuse on at "
        "least two artifacts"
    )
summary = {
    "schemaVersion": 2,
    "sharedComponentBytes": shared_component_bytes,
    "artifacts": validated,
}
(root.parent / "validated-summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
}

# Combine the smoke journey's wall-clock line with the newest long-form v4
# manifest into a local per-run summary artifact. The test runner cannot read
# the app's Application Support tree, so this measurement is lane-owned.
# Local evidence only — never a registry record.
summarize_long_form_project_if_present() {
  local out_dir="$1"
  local wall
  # `|| true`: under `set -euo pipefail` a benchmark log without the long-form
  # token makes grep fail the whole pipeline and silently kill the lane here.
  wall=$(grep -oE 'LONGFORM_WALL_SECONDS=[0-9.]+' "$out_dir/xcodebuild.log" 2>/dev/null | tail -1 | cut -d= -f2 || true)
  [[ -n "$wall" ]] || return 0
  python3 - "$wall" "$out_dir/long-form-project-summary.txt" "$out_dir" <<'PY'
import glob, json, os, shutil, sys

wall = float(sys.argv[1])
out_dir = sys.argv[3]
outputs = os.path.expanduser(
    "~/Library/Application Support/QwenVoice-Debug/outputs/CustomVoice"
)
manifests = sorted(
    glob.glob(os.path.join(outputs, "long_form_manifest_*.json")),
    key=os.path.getmtime,
)
if not manifests:
    raise SystemExit(0)
manifest = json.load(open(manifests[-1]))
assembly = manifest.get("assembly") or {}
frames = assembly.get("outputFrameCount") or 0
sample_rate = assembly.get("sampleRate") or 24_000
audio = frames / sample_rate if sample_rate else 0
segment_rows = (manifest.get("execution") or {}).get("segments", [])
segments = len(segment_rows)
rtf = audio / wall if wall else 0
lines = [
    f"long-form project: {segments} segments, audio {audio:.1f}s, "
    f"wall {wall:.1f}s (plan+stream+QC+assembly), project RTF {rtf:.2f}"
]

# Per-segment memory trend (local evidence only). The engine telemetry rows
# already carry physical-footprint summaries; segments have no generationID
# in the manifest, so match the contiguous run of engine rows whose audio
# durations best fit the manifest's per-segment durations.
def flat(obj, found):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                flat(value, found)
            elif isinstance(value, (int, float)) and key not in found:
                found[key] = value
    elif isinstance(obj, list):
        for value in obj:
            flat(value, found)
    return found

diag = os.path.expanduser("~/Library/Application Support/QwenVoice-Debug/diagnostics")
engine_log = os.path.join(diag, "engine", "generations.jsonl")
durations = [s.get("audioDurationSeconds") or 0 for s in segment_rows]
if segments >= 2 and durations and os.path.isfile(engine_log):
    rows = []
    with open(engine_log) as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rows.append(flat(json.loads(raw), {}))
            except json.JSONDecodeError:
                continue
    audio_key = "audioSeconds"
    usable = [r for r in rows if audio_key in r]
    best = None
    for start in range(0, max(0, len(usable) - segments) + 1):
        window = usable[start:start + segments]
        if len(window) < segments:
            break
        cost = sum(abs(w[audio_key] - d) for w, d in zip(window, durations))
        if best is None or cost < best[0]:
            best = (cost, window)
    # Accept the match only when durations genuinely line up (<0.75 s mean
    # error) so a stale log cannot masquerade as this run's segments.
    if best and best[0] / segments < 0.75:
        lines.append(
            "per-segment memory (engine physical footprint, MB; matched by "
            "audio duration):"
        )
        cumulative = 0.0
        ends = []
        for index, row in enumerate(best[1]):
            cumulative += row.get(audio_key, 0)
            end_mb = row.get("physFootprintEndMB")
            ends.append(end_mb)
            lines.append(
                f"  segment {index:>2}: audio={row.get(audio_key, 0):6.1f}s "
                f"cumulative={cumulative:7.1f}s "
                f"start={row.get('physFootprintStartMB', float('nan')):7.1f} "
                f"end={end_mb if end_mb is not None else float('nan'):7.1f} "
                f"peak={row.get('physFootprintPeakMB', float('nan')):7.1f}"
            )
        known_ends = [e for e in ends if e is not None]
        if len(known_ends) >= 2:
            growth = known_ends[-1] - known_ends[0]
            lines.append(
                f"  end-footprint growth first→last: {growth:+.1f} MB "
                f"({100 * growth / known_ends[0]:+.2f}% of first segment end)"
            )
    else:
        lines.append(
            "per-segment memory: no contiguous engine-row window matched the "
            "manifest durations; inspect diagnostics manually"
        )

# Retain the compact per-generation logs beside the run artifacts (sample
# sidecars stay in the app support tree; they are bounded but large).
kept = os.path.join(out_dir, "diagnostics")
os.makedirs(kept, exist_ok=True)
for layer in ("app", "engine", "engine-service"):
    source = os.path.join(diag, layer, "generations.jsonl")
    if os.path.isfile(source):
        shutil.copy2(source, os.path.join(kept, f"{layer}-generations.jsonl"))
merged = os.path.join(diag, "generations-merged.jsonl")
if os.path.isfile(merged):
    shutil.copy2(merged, os.path.join(kept, "generations-merged.jsonl"))

with open(sys.argv[2], "w") as f:
    f.write("\n".join(lines) + "\n")
for line in lines:
    print(f"==> {line}")
PY
}

run_xcodebuild() {
  local -a command=("$@")
  set +e
  "${command[@]}" 2>&1 | while IFS= read -r line || [[ -n "$line" ]]; do
    printf '%s\n' "$line"
    if [[ "$line" == *"VOCELLO_BENCH_TAKE_MANIFEST="* ]]; then
      local encoded="${line##*VOCELLO_BENCH_TAKE_MANIFEST=}"
      if [[ "$encoded" =~ ^[A-Za-z0-9+/=]+$ ]]; then
        if printf '%s' "$encoded" | /usr/bin/base64 -D >"$MAC_TAKE_MANIFEST.next"; then
          mv -f "$MAC_TAKE_MANIFEST.next" "$MAC_TAKE_MANIFEST"
        fi
      fi
    fi
  done | tee "$out/xcodebuild.log"
  local -a pipeline_status=("${PIPESTATUS[@]}")
  local status=${pipeline_status[0]}
  set -e
  export_attachments
  return "$status"
}

validate_macos_benchmark() {
  local diagnostics="$HOME/Library/Application Support/QwenVoice-Debug/diagnostics"
  local evidence="$out/benchmark-evidence.json"
  local status=1 attempt
  for attempt in {1..60}; do
    if python3 "$ROOT_DIR/scripts/check_macos_xpc_bench.py" "$diagnostics" \
        --run-id "$run_id" --modes "$modes" --lengths "$lengths" --warm "$warm" \
        --label "${label:-$run_id}" --evidence-manifest "$evidence" \
        --crash-delta-passed \
        >"$out/benchmark-gate.txt" 2>&1; then
      status=0
      break
    fi
    sleep 1
  done
  cat "$out/benchmark-gate.txt" >&2
  (( status == 0 )) || return 1
  python3 "$ROOT_DIR/scripts/summarize_generation_telemetry.py" "$diagnostics" \
    --run-id "$run_id" --evidence-manifest "$evidence" \
    --label "${label:-$run_id}" --merged --show-variance \
    >"$out/telemetry-summary.txt" 2>&1
}

validate_ios_benchmark() {
  local diagnostics="$out/diagnostics"
  local evidence="$out/benchmark-evidence.json"
  local generation_map
  generation_map="$(python3 - "$out/attachments/manifest.json" "$out/attachments" <<'PY'
import json, pathlib, sys
manifest = pathlib.Path(sys.argv[1])
root = pathlib.Path(sys.argv[2])
if not manifest.is_file():
    raise SystemExit("missing exported attachment manifest")
matches = []
for test in json.loads(manifest.read_text(encoding="utf-8")):
    for attachment in test.get("attachments", []):
        name = attachment.get("suggestedHumanReadableName", "")
        if name.startswith("ios-benchmark-generation-map"):
            matches.append(root / attachment["exportedFileName"])
if len(matches) != 1 or not matches[0].is_file():
    raise SystemExit(f"expected one iOS generation-map attachment, found {len(matches)}")
print(matches[0])
PY
  )" || return 1
  rm -rf "$diagnostics"
  "$ROOT_DIR/scripts/ios_device.sh" pull "$diagnostics" >/dev/null \
    || return 1
  if ! python3 "$ROOT_DIR/scripts/check_ios_ui_benchmark.py" "$diagnostics" \
      --run-id "$run_id" --modes "$modes" --lengths "$lengths" --warm "$warm" \
      --generation-map "$generation_map" \
      --label "${label:-$run_id}" --evidence-manifest "$evidence" \
      --crash-delta-passed \
      | tee "$out/benchmark-gate.txt"; then
    return 1
  fi
  python3 "$ROOT_DIR/scripts/summarize_generation_telemetry.py" "$diagnostics" \
    --run-id "$run_id" --evidence-manifest "$evidence" \
    --label "${label:-$run_id}" >"$out/telemetry-summary.txt" 2>&1
  return 0
}

validate_ios_smoke() {
  local diagnostics="$out/diagnostics"
  rm -rf "$diagnostics"
  "$ROOT_DIR/scripts/ios_device.sh" pull "$diagnostics" >/dev/null \
    || return 1
  python3 "$ROOT_DIR/scripts/check_ios_smoke_acceptance.py" "$diagnostics" \
    --run-id "$run_id" | tee "$out/smoke-gate.txt"
}

preserve_ios_ui_dsym() {
  local products="$IOS_DERIVED/Build/Products/Release-iphoneos"
  local app="$products/Vocello.app"
  local source="$products/Vocello.app.dSYM"
  local destination="$QVOICE_SYMBOLS_IOS/Vocello.app.dSYM"
  [[ -f "$app/Vocello" && -d "$source" ]] || {
    warn "iOS UI build did not produce a symbol-preservable app/dSYM pair"
    return 1
  }
  preserve_ios_dsym "$source" "$destination" "$app/Vocello" || return 1
  /usr/libexec/PlistBuddy -c "Print :CFBundleVersion" "$app/Info.plist" \
    > "$(dirname "$destination")/build-version.txt" 2>/dev/null || true
}

if [[ "$platform" == "macos" ]]; then
  terminate_macos_app
  if [[ "$lane" == "smoke" ]]; then
    # The smoke class runs its seven ordered journeys (navigation/readiness,
    # completed generation + History, mid-generation cancellation, virtual-mic
    # recording, library surfaces, long-form project, line batch) in
    # method-name order.
    only_test="VocelloMacUITests/VocelloMacSmokeUITests"
    if [[ -n "$long_form_segments" ]]; then
      export TEST_RUNNER_QVOICE_MAC_LONGFORM_SEGMENTS="$long_form_segments"
    fi
  else
    only_test="VocelloMacUITests/VocelloMacBenchmarkUITests/testOrderedConfigurableMatrix"
    rm -f "$MAC_TAKE_MANIFEST" "$MAC_TAKE_MANIFEST.next"
    export TEST_RUNNER_QVOICE_MAC_BENCH_RUN_ID="$run_id"
    export TEST_RUNNER_QVOICE_MAC_BENCH_MODES="$modes"
    export TEST_RUNNER_QVOICE_MAC_BENCH_LENGTHS="$lengths"
    export TEST_RUNNER_QVOICE_MAC_BENCH_WARM="$warm"
    export TEST_RUNNER_QVOICE_MAC_BENCH_LABEL="${label:-$run_id}"
  fi

  note "macOS XCUITest $lane → $out"
  required_step_run "$step_ledger" ui-preflight mac_ui_preflight

  # Synthesize the shared virtual-microphone fixture for the recording
  # journey. It must live in /tmp: the app cannot read the runner's per-app
  # temporary directory without a TCC prompt, and the Xcode test runner
  # cannot write /tmp itself.
  python3 - <<'WAV'
import math, struct, wave
path = "/tmp/vocello-ui-virtual-mic.wav"
sr = 24000
frames = int(sr * 12.0)
with wave.open(path, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sr)
    data = bytearray()
    for i in range(frames):
        t = i / sr
        syllable = abs(math.sin(2 * math.pi * 2.4 * t))
        phrase = 1.0 if math.sin(2 * math.pi * 0.22 * t) > -0.55 else 0.0
        tone = 0.7 * math.sin(2 * math.pi * 175 * t) + 0.3 * math.sin(2 * math.pi * 330 * t)
        data += struct.pack("<h", int(0.28 * tone * syllable * phrase * 32767))
    w.writeframes(bytes(data))
WAV

  # Two-phase execution: an explicitly skippable build-for-testing (repeat
  # lanes on an unchanged tree skip the multi-minute rebuild entirely),
  # followed by test-without-building against the already-built products.
  # Ordinary CI never invokes this script; the workflow-YML guard on
  # test-without-building is unaffected.
  mac_fingerprint="$( { git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null; \
    git -C "$ROOT_DIR" status --porcelain 2>/dev/null; } | shasum -a 256 | cut -d' ' -f1)"
  mac_build_marker="$MAC_DERIVED/.vocello-ui-build-fingerprint"
  mac_products_ready="$(find "$MAC_DERIVED/Build/Products" -maxdepth 1 \
    -name 'VocelloMacUI_*.xctestrun' -print -quit 2>/dev/null || true)"
  if [[ -f "$mac_build_marker" && -n "$mac_products_ready" \
      && "$(cat "$mac_build_marker" 2>/dev/null)" == "$mac_fingerprint" ]]; then
    note "build-for-testing skipped — source fingerprint unchanged"
    required_step_record "$step_ledger" ui-build 0
  else
    rm -f "$mac_build_marker"
    required_step_run "$step_ledger" ui-build xcb_run build-for-testing \
      -project "$PROJECT" -scheme VocelloMacUI -configuration Release \
      -destination 'platform=macOS,arch=arm64' -derivedDataPath "$MAC_DERIVED" \
      -clonedSourcePackagesDirPath "$QVOICE_XCODE_SOURCE_PACKAGES" \
      -disableAutomaticPackageResolution \
      -onlyUsePackageVersionsFromResolvedFile \
      CODE_SIGN_STYLE=Manual CODE_SIGN_IDENTITY="-" ONLY_ACTIVE_ARCH=YES ARCHS=arm64 \
      SWIFT_OPTIMIZATION_LEVEL=-O \
      || die "macOS UI build-for-testing failed (see $out/xcodebuild.log)"
    printf '%s\n' "$mac_fingerprint" >"$mac_build_marker"
  fi
  required_step_run "$step_ledger" xcuitest run_xcodebuild xcb_run test-without-building \
    -project "$PROJECT" -scheme VocelloMacUI -configuration Release \
    -destination 'platform=macOS,arch=arm64' -derivedDataPath "$MAC_DERIVED" \
    -resultBundlePath "$result" -only-testing:"$only_test" \
    || die "macOS XCUITest failed (see $out/xcodebuild.log)"
  required_step_run "$step_ledger" crash-delta check_mac_crash_delta \
    || die "new Vocello crash report detected"
  summarize_long_form_project_if_present "$out"
  # The lane rebuilt the app/XPC products in the shared cache; re-preserve
  # their dSYMs so the build-output symbol-identity check stays consistent
  # (mirrors preserve_ios_ui_dsym on the device lane).
  preserve_macos_dsyms "$MAC_DERIVED/Build/Products/Release" \
    "$MAC_DERIVED/Build/Products/Release/Vocello.app" "$QVOICE_SYMBOLS_MACOS" \
    || warn "could not preserve macOS UI-lane dSYMs"
  write_build_provenance "$MAC_DERIVED/last-build.json" \
    "scripts/ui_test.sh macos $lane" VocelloMacUI Release \
    "platform=macOS,arch=arm64" arm64 O ad-hoc \
    "$MAC_DERIVED" "$QVOICE_XCODE_SOURCE_PACKAGES"
  write_build_provenance "$out/last-build.json" \
    "scripts/ui_test.sh macos $lane" VocelloMacUI Release \
    "platform=macOS,arch=arm64" arm64 O ad-hoc \
    "$MAC_DERIVED" "$QVOICE_XCODE_SOURCE_PACKAGES"
  [[ "$lane" != "benchmark" ]] || required_step_run "$step_ledger" \
    benchmark-validation validate_macos_benchmark \
    || die "macOS benchmark telemetry gate failed"
  terminate_macos_app
else
  probe="$(ios_probe)"
  device="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("identifier") or "")' <<<"$probe")"
  reachable="$(python3 -c 'import json,sys; print("1" if json.load(sys.stdin).get("reachable") else "0")' <<<"$probe")"
  locked="$(python3 -c 'import json,sys; print("1" if (json.load(sys.stdin).get("lock") or {}).get("deviceLocked") is True else "0")' <<<"$probe")"
  [[ -n "$device" && "$reachable" == "1" ]] \
    || die "paired iPhone is not reachable through CoreDevice; unlock it and check USB/local-network connectivity"
  [[ "$locked" == "0" ]] || die "paired iPhone is locked; unlock it and retry"
  team="$(derive_team || true)"
  [[ -n "$team" ]] || die "no Apple Development team found; set QWENVOICE_DEVELOPMENT_TEAM"
  required_step_run "$step_ledger" crash-baseline \
    snapshot_ios_crashes "$out/crashes-before" \
    || die "could not establish the pre-run iPhone crash snapshot"

  if [[ "$lane" == "smoke" ]]; then
    only_test="VocelloiOSUITests/VocelloiOSSmokeUITests"
    export TEST_RUNNER_QVOICE_IOS_SMOKE_RUN_ID="$run_id"
  elif [[ "$lane" == "benchmark" ]]; then
    only_test="VocelloiOSUITests/VocelloiOSBenchmarkUITests/testOrderedConfigurableMatrix"
    export TEST_RUNNER_QVOICE_IOS_BENCH_RUN_ID="$run_id"
    export TEST_RUNNER_QVOICE_IOS_BENCH_MODES="$modes"
    export TEST_RUNNER_QVOICE_IOS_BENCH_LENGTHS="$lengths"
    export TEST_RUNNER_QVOICE_IOS_BENCH_WARM="$warm"
    export TEST_RUNNER_QVOICE_IOS_BENCH_LABEL="${label:-$run_id}"
  else
    only_test="VocelloiOSUITests/VocelloiOSModelDownloadUITests/testIsolatedBackgroundDownloadAdoptionAndCleanup"
  fi

  note "physical-iPhone XCUITest $lane on $device → $out"
  required_step_run "$step_ledger" xcuitest run_xcodebuild xcb_run test \
    -project "$PROJECT" -scheme VocelloiOSUI -configuration Release \
    -destination "id=$device" -derivedDataPath "$IOS_DERIVED" \
    -clonedSourcePackagesDirPath "$QVOICE_XCODE_SOURCE_PACKAGES" \
    -disableAutomaticPackageResolution \
    -onlyUsePackageVersionsFromResolvedFile \
    -resultBundlePath "$result" -collect-test-diagnostics never \
    -only-testing:"$only_test" \
    -allowProvisioningUpdates DEVELOPMENT_TEAM="$team" CODE_SIGN_STYLE=Automatic \
    ARCHS=arm64 ONLY_ACTIVE_ARCH=YES \
    SWIFT_OPTIMIZATION_LEVEL=-O \
    || die "physical-iPhone XCUITest failed (see $out/xcodebuild.log)"
  preserve_ios_ui_dsym \
    || die "physical-iPhone XCUITest passed, but its current dSYM could not be preserved"

  if [[ "$lane" == "model-download" ]]; then
    required_step_run "$step_ledger" model-download-diagnostics \
      pull_ios_model_download_diagnostics "$device" "$out/model-download-diagnostics" \
      || die "could not collect or validate compact model-download diagnostics (see $out/model-download-diagnostics-pull.log)"
  fi

  required_step_run "$step_ledger" crash-delta check_ios_crash_delta \
    || die "could not establish a clean post-run iPhone crash delta"
  [[ "$lane" != "smoke" ]] || required_step_run "$step_ledger" \
    smoke-diagnostics validate_ios_smoke \
    || die "iOS smoke memory-pressure diagnostics gate failed"
  write_build_provenance "$IOS_DERIVED/last-build.json" \
    "scripts/ui_test.sh ios $lane" VocelloiOSUI Release "id=$device" arm64 \
    O automatic "$IOS_DERIVED" "$QVOICE_XCODE_SOURCE_PACKAGES"
  write_build_provenance "$out/last-build.json" \
    "scripts/ui_test.sh ios $lane" VocelloiOSUI Release "id=$device" arm64 \
    O automatic "$IOS_DERIVED" "$QVOICE_XCODE_SOURCE_PACKAGES"
  [[ "$lane" != "benchmark" ]] || required_step_run "$step_ledger" \
    benchmark-validation validate_ios_benchmark \
    || die "iOS benchmark telemetry gate failed"
fi

finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
note "per-test results:"
write_test_summary || true
write_run_metadata passed "$finished_at" 0
run_finalized=1

if [[ "$lane" == "benchmark" ]]; then
  if ! history_record="$(required_step_run "$step_ledger" history-publication \
      python3 "$ROOT_DIR/scripts/benchmark_history.py" record --artifact-dir "$out")"; then
    die "benchmark passed, but history publication failed; evidence is preserved in $out (repair: python3 scripts/benchmark_history.py record --artifact-dir '$out')"
  fi
  note "tracked benchmark record → $history_record"
fi

# Keep the most recent passing result for each platform/lane only after this
# run is durably marked as passed (and, for benchmarks, after history
# publication). Cleanup failure must not rewrite an otherwise valid UI verdict.
retention_status=0
if "$ROOT_DIR/scripts/clean_build_caches.sh" --prune-ui-results --ui-keep 1 \
    >"$out/result-retention.log" 2>&1; then
  note "pruned superseded XCUITest results (latest passing result retained per platform/lane)"
else
  retention_status=1
  warn "could not prune superseded XCUITest results (see $out/result-retention.log)"
fi
required_step_record "$step_ledger" result-retention "$retention_status"

required_steps_finalize "$step_ledger" \
  || die "$platform $lane required-step ledger did not pass"

note "$platform $lane PASS · $out"
