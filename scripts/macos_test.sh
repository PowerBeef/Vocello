#!/usr/bin/env bash
# macOS deterministic testing and telemetry driver.
#
# macOS is the native development host. The engine runs OUT-OF-PROCESS in
# an XPC service (com.qwenvoice.app.engine-service) — a separate process that can crash
# independently and be retired under memory pressure. Several lanes target the app AND the
# service. Build/run/release stay in scripts/build.sh; this script adds the lanes.
#
# usage:
#   scripts/macos_test.sh preflight [--strict-models]  # Xcode + app + dSYMs + XPC + model status
#   scripts/macos_test.sh core-test                 # VocelloCoreTests (core + host-runnable iOS policy, no models)
#                                                    # opt-in: QWENVOICE_ENABLE_TSAN=1
#   scripts/macos_test.sh tsan                      # scheduled core + injectable XPC transport TSan subset
#   scripts/macos_test.sh lang-bench [--subset quick|full] [--label RUN_ID]
#                                                 # headless macOS language-hint matrix (vocello CLI)
#   scripts/macos_test.sh test                      # Core + XPC transport + Qwen3 runtime tests (no UI)
#   scripts/macos_test.sh telemetry-overhead        # seeded PCM + RTF/TTFC (explicit, model-dependent)
#   scripts/macos_test.sh crashes [--test]          # collect + xcsym-symbolicate .ips (app + XPC service)
#   scripts/macos_test.sh debug                     # LLDB attach guidance (app + XPC service PID)
#   scripts/macos_test.sh logs                      # retained os_log → build/artifacts/macos/logs/<run>.log
#   scripts/macos_test.sh profile [--kind cpu|memory] [--keep-trace] [spec]
#                                                    # exact-PID xctrace vocello bench
#   scripts/macos_test.sh memory [--label ID]        # retained-memory qualification sequence
#   scripts/macos_test.sh gate                      # inputs → build_foundation → test → crashes
#                                                    # optional: QWENVOICE_GATE_BENCH=1 adds bounded vocello bench
#   scripts/macos_test.sh release-readiness         # deterministic packaging gate (no UI)
#   scripts/macos_test.sh models check|ensure|install  # test model fixture (Speed variant)
#   scripts/macos_test.sh help

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_DIR="$ROOT_DIR/scripts"
# shellcheck source=lib/build_paths.sh
. "$SCRIPT_DIR/lib/build_paths.sh"
# shellcheck source=lib/build_cache.sh
. "$SCRIPT_DIR/lib/build_cache.sh"
. "$SCRIPT_DIR/lib/required_steps.sh"
. "$SCRIPT_DIR/lib/test_models.sh"
test_models_init "$ROOT_DIR"
APP_NAME="Vocello"
BUNDLE_ID="com.qwenvoice.app"
APP_BUNDLE="$QVOICE_BUILD_ROOT/$APP_NAME.app"
APP_BINARY="$APP_BUNDLE/Contents/MacOS/$APP_NAME"
XPC_BUNDLE="$APP_BUNDLE/Contents/XPCServices/QwenVoiceEngineService.xpc"
DSYM_DIR="$QVOICE_SYMBOLS_MACOS"

note() { printf '\033[0;36m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[0;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

validate_benchmark_label() {
  local value="$1"
  [[ -z "$value" || "$value" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$ ]] \
    || die "--label must be an opaque 1-96 character ID using letters, digits, dot, underscore, or hyphen"
}

benchmark_nonce() {
  python3 -c 'import secrets; print(secrets.token_hex(4))'
}

string_sha256() {
  VALUE="$1" python3 -c 'import hashlib,os; print(hashlib.sha256(os.environ["VALUE"].encode()).hexdigest())'
}

capture_benchmark_source() {
  local artifacts="$1"
  python3 "$SCRIPT_DIR/publish_benchmark_history.py" snapshot \
    --output "$artifacts/benchmark-source.json" --crash-scope macos >/dev/null \
    || die "could not capture pre-run benchmark provenance"
}

require_profile_model() {
  local mode="$1" variant="$2"
  case "$mode" in custom|design|clone) ;; *) die "profile mode must be custom, design, or clone" ;; esac
  case "$variant" in speed|quality) ;; *) die "profile variant must be speed or quality" ;; esac
  require_mac_benchmark_models "pro_${mode}_${variant}"
  [[ "$mode" != "clone" ]] || require_mac_benchmark_clone_fixture
}

record_benchmark_history() {
  local artifacts="$1"
  python3 "$SCRIPT_DIR/benchmark_history.py" record --artifact-dir "$artifacts" || {
    warn "benchmark passed, but history publication failed; evidence is preserved in $artifacts"
    warn "repair: python3 scripts/benchmark_history.py record --artifact-dir '$artifacts'"
    return 1
  }
}

# Bash 3.2 has no timed `wait`. Treat a disappeared or zombie child as
# waitable, then let the caller collect its real exit status with `wait`.
profile_child_finished() {
  local pid="$1" state=""
  [[ -n "$pid" ]] || return 0
  kill -0 "$pid" >/dev/null 2>&1 || return 0
  state="$(ps -o state= -p "$pid" 2>/dev/null | tr -d '[:space:]' || true)"
  [[ -z "$state" || "$state" == *Z* ]]
}

# Bash 3.2 unwinds function-local variables before an EXIT trap executes. Keep
# the one active profile's owned process/retention state in explicitly prefixed
# globals so failure cleanup is effective rather than a static-looking no-op.
PROFILE_TRACE_ACTIVE=0
PROFILE_TRACE_PUBLISHED=0
PROFILE_TRACE_KIND=""
PROFILE_TRACE_PHASE=""
PROFILE_TRACE_ARTIFACTS=""
PROFILE_TRACE_PATH=""
PROFILE_TRACE_TARGET_PID=""
PROFILE_TRACE_LAUNCHER_PID=""
PROFILE_TRACE_XCTRACE_PID=""

profile_failure_cleanup() {
  local status=$?
  trap - EXIT
  set +e
  [[ -z "$PROFILE_TRACE_XCTRACE_PID" ]] \
    || kill "$PROFILE_TRACE_XCTRACE_PID" >/dev/null 2>&1 || true
  [[ -z "$PROFILE_TRACE_TARGET_PID" ]] \
    || kill -CONT "$PROFILE_TRACE_TARGET_PID" >/dev/null 2>&1 || true
  [[ -z "$PROFILE_TRACE_TARGET_PID" ]] \
    || kill "$PROFILE_TRACE_TARGET_PID" >/dev/null 2>&1 || true
  [[ -z "$PROFILE_TRACE_LAUNCHER_PID" ]] \
    || kill "$PROFILE_TRACE_LAUNCHER_PID" >/dev/null 2>&1 || true
  if (( status != 0 && PROFILE_TRACE_ACTIVE == 1 && PROFILE_TRACE_PUBLISHED == 0 )); then
    python3 "$SCRIPT_DIR/lib/profile_trace_retention.py" mark-failure \
      --root "$ROOT_DIR" --platform macos --kind "$PROFILE_TRACE_KIND" \
      --artifact-dir "$PROFILE_TRACE_ARTIFACTS" --trace "$PROFILE_TRACE_PATH" \
      --phase "$PROFILE_TRACE_PHASE" --exit-code "$status" >/dev/null \
      || warn "could not compact older failed $PROFILE_TRACE_KIND profile traces"
  fi
  exit "$status"
}

ensure_app() { [[ -d "$APP_BUNDLE" ]] || "$SCRIPT_DIR/build.sh" build; }

# Xcode 26.6 can finish compilation and then wait indefinitely before spawning
# `xctest` for hostless macOS bundles. Keep Xcode responsible for compilation,
# then execute the built deterministic bundles directly through the native runner.
build_mac_test_bundles() {
  local log_path="$1"
  local tsan="${QWENVOICE_ENABLE_TSAN:-0}"
  [[ "$tsan" == "0" || "$tsan" == "1" ]] \
    || die "QWENVOICE_ENABLE_TSAN must be 0 or 1"
  local sanitizer_setting="NO"
  local derived_data="$QVOICE_XCODE_MACOS_DERIVED"
  local build_command="scripts/macos_test.sh test"
  if [[ "$tsan" == "1" ]]; then
    sanitizer_setting="YES"
    derived_data="$QVOICE_XCODE_MACOS_TSAN_DERIVED"
    build_command="scripts/macos_test.sh tsan"
    note "Thread Sanitizer enabled for this deterministic test build"
  fi
  mkdir -p "$(dirname "$log_path")"
  if [[ "$tsan" == "0" && -d "$derived_data/Build/Products" ]]; then
    # Xcode does not always remove a sanitizer runtime left by an older shared-
    # cache build. Delete only that generated toolchain dylib before constructing
    # a normal product; all source, packages, and other cache products stay intact.
    find "$derived_data/Build/Products" -type f \
      -name 'libclang_rt.tsan_osx_dynamic.dylib' -delete
  fi
  ensure_project_regenerated || return 1
  ensure_spm_resolved "$QVOICE_SCRATCH_PACKAGE_RESOLUTION" "$QVOICE_XCODE_SOURCE_PACKAGES" \
    macos-test QwenVoice Release 'platform=macOS,arch=arm64' || return 1
  local xcode_status=0
  xcb_run build-for-testing -project "$ROOT_DIR/QwenVoice.xcodeproj" -scheme QwenVoice \
    -configuration Release -destination 'platform=macOS,arch=arm64' \
    -derivedDataPath "$derived_data" \
    -clonedSourcePackagesDirPath "$QVOICE_XCODE_SOURCE_PACKAGES" \
    -disableAutomaticPackageResolution -onlyUsePackageVersionsFromResolvedFile \
    -enableThreadSanitizer "$sanitizer_setting" \
    ARCHS=arm64 ONLY_ACTIVE_ARCH=YES CODE_SIGN_STYLE=Manual CODE_SIGN_IDENTITY="-" \
    CODE_SIGN_ALLOW_ENTITLEMENTS_MODIFICATION=YES \
    QVOICE_INTERNAL_DIAGNOSTICS_SWIFT_FLAG=-DVOCELLO_INTERNAL_DIAGNOSTICS \
    SWIFT_OPTIMIZATION_LEVEL="-Onone" SWIFT_COMPILATION_MODE="incremental" \
    ENABLE_TESTABILITY=YES > "$log_path" 2>&1 || xcode_status=$?
  (( xcode_status == 0 )) || return "$xcode_status"
  local products="$derived_data/Build/Products/Release"
  if [[ "$tsan" == "1" ]]; then
    assert_macos_tsan_bundle_architectures "$products/Vocello.app" || return 1
  else
    assert_macos_bundle_arm64_only "$products/Vocello.app" || return 1
  fi
  if [[ "$tsan" == "0" ]]; then
    preserve_macos_dsyms "$products" "$products/Vocello.app" "$QVOICE_SYMBOLS_MACOS" || return 1
  fi
  write_build_provenance "$derived_data/last-build.json" \
    "$build_command" QwenVoice Release \
    "platform=macOS,arch=arm64" arm64 Onone ad-hoc \
    "$derived_data" "$QVOICE_XCODE_SOURCE_PACKAGES" || return 1
  if [[ "$tsan" == "0" ]]; then
    write_build_provenance "$QVOICE_SYMBOLS_MACOS/last-build.json" \
      "$build_command" QwenVoice Release \
      "platform=macOS,arch=arm64" arm64 Onone ad-hoc \
      "$derived_data" "$QVOICE_XCODE_SOURCE_PACKAGES" || return 1
  fi
}

run_mac_test_bundle() {
  local bundle_name="$1" log_path="$2" tsan="${3:-0}" test_filter="${4:-}"
  local derived_data="$QVOICE_XCODE_MACOS_DERIVED"
  [[ "$tsan" != "1" ]] || derived_data="$QVOICE_XCODE_MACOS_TSAN_DERIVED"
  local products="$derived_data/Build/Products/Release"
  local bundle="$products/$bundle_name.xctest"
  local tsan_runtime="$bundle/Contents/Frameworks/libclang_rt.tsan_osx_dynamic.dylib"
  local xctest_runner=""
  [[ -d "$bundle" ]] || { echo "missing test bundle: $bundle" > "$log_path"; return 1; }
  [[ "$tsan" == "0" || "$tsan" == "1" ]] \
    || { echo "invalid TSan test-runner mode: $tsan" > "$log_path"; return 1; }
  if [[ "$tsan" == "1" ]]; then
    [[ -f "$tsan_runtime" ]] \
      || { echo "missing embedded ThreadSanitizer runtime: $tsan_runtime" > "$log_path"; return 1; }
    xctest_runner="$(xcrun --find xctest 2>/dev/null || true)"
    [[ -x "$xctest_runner" ]] \
      || { echo "could not resolve Xcode's xctest runner" > "$log_path"; return 1; }
    # Launch the resolved runner directly. Starting it through xcrun causes macOS
    # to strip DYLD_INSERT_LIBRARIES before xctest starts, loading TSan too late.
    if [[ -n "$test_filter" ]]; then
      DYLD_INSERT_LIBRARIES="$tsan_runtime" DYLD_FRAMEWORK_PATH="$products" \
        "$xctest_runner" -XCTest "$test_filter" "$bundle" > "$log_path" 2>&1
    else
      DYLD_INSERT_LIBRARIES="$tsan_runtime" DYLD_FRAMEWORK_PATH="$products" \
        "$xctest_runner" "$bundle" > "$log_path" 2>&1
    fi
    return
  fi
  if [[ -n "$test_filter" ]]; then
    DYLD_FRAMEWORK_PATH="$products" xcrun xctest -XCTest "$test_filter" "$bundle" > "$log_path" 2>&1
  else
    DYLD_FRAMEWORK_PATH="$products" xcrun xctest "$bundle" > "$log_path" 2>&1
  fi
}

# Xcode embeds its universal ThreadSanitizer runtime in instrumented products even
# when every repository-owned target is built for arm64 only. Keep the product and
# release validator strict; this test-only validator permits exactly that named
# toolchain runtime, and only when it still contains an arm64 slice.
assert_macos_tsan_bundle_architectures() {
  local app_bundle="$1" candidate architectures=""
  assert_macho_arm64_only "$app_bundle/Contents/MacOS/Vocello" "Vocello executable" || return 1
  assert_macho_arm64_only \
    "$app_bundle/Contents/XPCServices/QwenVoiceEngineService.xpc/Contents/MacOS/QwenVoiceEngineService" \
    "QwenVoiceEngineService executable" || return 1
  while IFS= read -r -d '' candidate; do
    /usr/bin/file -b "$candidate" 2>/dev/null | grep -q 'Mach-O' || continue
    if [[ "${candidate##*/}" == "libclang_rt.tsan_osx_dynamic.dylib" ]]; then
      architectures="$(/usr/bin/lipo -archs "$candidate" 2>/dev/null || true)"
      [[ " $architectures " == *" arm64 "* ]] || {
        echo "error: embedded ThreadSanitizer runtime lacks arm64 (found: ${architectures:-unknown})" >&2
        return 1
      }
      continue
    fi
    assert_macho_arm64_only "$candidate" "embedded Mach-O ${candidate#"$app_bundle"/}" || return 1
  done < <(find \
    "$app_bundle/Contents/MacOS" \
    "$app_bundle/Contents/XPCServices" \
    "$app_bundle/Contents/Frameworks" \
    -type f -print0 2>/dev/null)
}

# crashes [--test]: collect macOS .ips crash reports (app + XPC service) from
# ~/Library/Logs/DiagnosticReports and symbolicate against the preserved build dSYMs.
# `--test` SIGSEGVs a launched app to verify the capture→symbolicate lane end-to-end.
cmd_crashes() {
  local test_mode=0
  [[ "${1:-}" == "--test" ]] && test_mode=1
  local dr="$HOME/Library/Logs/DiagnosticReports"

  if (( test_mode )); then
    note "crash-lane self-test: launch + SIGSEGV the app to force a .ips…"
    ensure_app
    pkill -x "$APP_NAME" >/dev/null 2>&1 || true
    /usr/bin/open -na "$APP_BUNDLE"
    local pid=""
    for _ in {1..20}; do pid="$(pgrep -xn "$APP_NAME" || true)"; [[ -n "$pid" ]] && break; sleep 0.25; done
    [[ -n "$pid" ]] || die "could not find $APP_NAME PID to crash"
    note "SIGSEGV pid $pid"
    kill -SEGV "$pid" 2>/dev/null || true
    sleep 5   # let macOS write the .ips
  fi

  local dest="$QVOICE_ARTIFACTS_MACOS/crashes/crashes-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$dest"
  note "collecting .ips from $dr (app: Vocello*, service: QwenVoiceEngineService* / *engine-service*)"
  local n=0 f
  shopt -s nullglob
  for f in "$dr"/Vocello-*.ips "$dr"/QwenVoiceEngineService-*.ips "$dr"/*engine-service*.ips; do
    cp "$f" "$dest/" 2>/dev/null || true
    n=$((n+1))
  done
  shopt -u nullglob
  (( n == 0 )) && { note "no crash reports found."; rmdir "$dest" 2>/dev/null || true; return 0; }
  note "collected $n crash report(s) → $dest"

  [[ -d "$DSYM_DIR" ]] || { warn "no preserved dSYMs at $DSYM_DIR — run: scripts/build.sh build"; return 0; }
  note "── symbolication (optional xcsym when on PATH; otherwise Xcode Organizer) ──"
  for f in "$dest"/*.ips; do
    [[ -f "$f" ]] || continue
    if command -v xcsym >/dev/null 2>&1; then
      xcsym crash "$f" --dsym-dir "$DSYM_DIR" 2>&1 || warn "xcsym failed on $(basename "$f")"
    else
      warn "xcsym not on PATH — use Xcode Organizer, or consult \$axiom-tools before installing xcsym:"
      warn "  xcsym crash \"$f\" --dsym-dir \"$DSYM_DIR\""
    fi
  done
}

# debug: launch the app and print LLDB attach commands for BOTH the app and the XPC
# engine service (a separate process — the macOS-unique bit). Dev builds have hardened
# runtime OFF, so LLDB attaches directly (no get-task-allow needed). The session is
# interactive. The XPC service is lazy — spawn it with a generation first if absent.
cmd_debug() {
  ensure_app
  pkill -x "$APP_NAME" >/dev/null 2>&1 || true
  /usr/bin/open -na "$APP_BUNDLE"
  local app_pid=""
  for _ in {1..30}; do app_pid="$(pgrep -xn "$APP_NAME" || true)"; [[ -n "$app_pid" ]] && break; sleep 0.25; done
  [[ -n "$app_pid" ]] || die "$APP_NAME did not launch"
  note "debug: $APP_NAME running (pid $app_pid) — hardened runtime OFF, LLDB-attachable."
  note "  lldb -p $app_pid        # app"
  local svc_pid; svc_pid="$(pgrep -xn QwenVoiceEngineService || true)"
  if [[ -n "$svc_pid" ]]; then
    note "  lldb -p $svc_pid        # XPC engine service (pid $svc_pid)"
  else
    note "  XPC service not running yet — trigger a generation to spawn it, then:"
    note "    lldb -p \$(pgrep -xn QwenVoiceEngineService)"
  fi
  note "  (or XcodeBuildMCP debugging, or Xcode → Debug → Attach to Process by PID)"
  note "  retained os_log: scripts/macos_test.sh logs   (subsystem $BUNDLE_ID)"
}

# logs: retain the app + XPC service os_log (subsystem com.qwenvoice.app) to a file
# under build/artifacts/macos/logs/<run>.log. Ctrl-C to stop.
cmd_logs() {
  local out="$QVOICE_ARTIFACTS_MACOS/logs/macos-logs-$(date +%Y%m%d-%H%M%S).log"
  mkdir -p "$(dirname "$out")"
  note "streaming os_log (subsystem $BUNDLE_ID) → $out (Ctrl-C to stop)"
  /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\"" 2>&1 | tee "$out"
  note "saved $out"
}

# profile [--kind cpu|memory] [spec]: Instruments/xctrace trace of a headless generation via the `vocello` CLI
# (engine IN-PROCESS — the deterministic engine profile; the same engine code runs in the
# XPC service). The engine emits OSSignpost intervals under subsystem com.qwenvoice.app,
# category 'performance'. The CPU lane records CPU Profiler + os_signpost. The memory
# lane also records Allocations + VM Tracker in that same trace. QVOICE_MAC_PROFILE_DURATION
# controls the capture window (seconds, default 90); QVOICE_MAC_MEMORY_PROFILE_DURATION
# overrides the memory safety cap (default 180). QVOICE_MAC_PROFILE_GRACE_TIMEOUT bounds target/tracer
# shutdown after the requested capture window (default 30 seconds for CPU, 60 for memory).
# Produces build/artifacts/macos/profiles/<run-id>/<run-id>.trace. (To profile the XPC service
# specifically — the production path — launch the app, 'xctrace record --attach
# QwenVoiceEngineService', and generate via the UI; see macos-testing.md.)
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
  spec="${spec:-custom:speed:Profile headless generation.}"
  [[ "$spec" == *:* ]] || spec="custom:speed:$spec"
  local mode="${spec%%:*}"
  local rest="${spec#*:}"
  local variant="${rest%%:*}"
  local cpu_instrument="CPU Profiler"
  local allocations_instrument="Allocations"
  local vm_tracker_instrument="VM Tracker"
  local memory_template="Allocations"
  local -a instrument_args
  local capture_instruments="$cpu_instrument + os_signpost"
  if [[ "$kind" == "memory" ]]; then
    # Apple's Allocations template already owns both Allocations and VM Tracker,
    # and configures VM Tracker with automatic snapshots disabled. Adding a
    # standalone VM Tracker instrument to a Blank trace enables stop-the-world
    # automatic snapshots, which can suspend the exact target for 1-2 seconds
    # and make its honest 500 ms in-process sampler fall below the 95% gate.
    instrument_args=(--template "$memory_template" --instrument "$cpu_instrument")
    capture_instruments="$cpu_instrument + $allocations_instrument + $vm_tracker_instrument + os_signpost"
  else
    instrument_args=(--instrument "$cpu_instrument")
  fi
  instrument_args+=(--instrument os_signpost)
  local duration="${QVOICE_MAC_PROFILE_DURATION:-90}"
  local profile_length="medium" profile_warm="1"
  [[ "$kind" != "memory" ]] || duration="${QVOICE_MAC_MEMORY_PROFILE_DURATION:-180}"
  if [[ "$kind" == "memory" ]]; then
    # Retention has its own multi-take lane. The Instruments memory lane focuses
    # on one cold long take: this captures model-load and sustained-generation
    # peaks while providing enough genuine 500 ms cadence opportunities for the
    # strict 95% coverage gate. The Allocations template above avoids automatic
    # VM snapshots rather than discounting profiler-induced sampler gaps.
    profile_length="long"
    profile_warm="0"
  fi
  local tracer_start_timeout="${QVOICE_MAC_PROFILE_START_TIMEOUT:-30}"
  local default_profile_grace_timeout=30
  [[ "$kind" != "memory" ]] || default_profile_grace_timeout=60
  local profile_grace_timeout="${QVOICE_MAC_PROFILE_GRACE_TIMEOUT:-$default_profile_grace_timeout}"
  [[ "$duration" =~ ^[1-9][0-9]*$ ]] \
    || die "the selected macOS profile duration must be a positive whole number of seconds"
  [[ "$tracer_start_timeout" =~ ^[1-9][0-9]*$ ]] \
    || die "QVOICE_MAC_PROFILE_START_TIMEOUT must be a positive whole number of seconds"
  [[ "$profile_grace_timeout" =~ ^[1-9][0-9]*$ ]] \
    || die "QVOICE_MAC_PROFILE_GRACE_TIMEOUT must be a positive whole number of seconds"
  python3 "$SCRIPT_DIR/lib/profile_trace_retention.py" preflight \
    --root "$ROOT_DIR" --kind "$kind" >/dev/null \
    || die "profile disk-space preflight failed before launching the target"
  command -v xctrace >/dev/null 2>&1 || die "xctrace not found — install Xcode and use Instruments for native profiling"
  # Rebuild immediately before provenance capture so the recorded source and
  # executable identity cannot describe a stale CLI binary.
  "$SCRIPT_DIR/build.sh" cli-optimized >/dev/null
  require_profile_model "$mode" "$variant"
  local run_id
  run_id="mac-${kind}-profile-$(date -u +%Y%m%d-%H%M%S)-$(benchmark_nonce)"
  local artifacts="$QVOICE_ARTIFACTS_MACOS/profiles/$run_id"
  local runtime="$artifacts/runtime"
  # The launcher is disposable generated tooling, not durable profile evidence.
  # Keep it below the policy-owned transient scratch root so routine cleanup can
  # reclaim it without touching validated profile summaries.
  local suspended_launcher="$QVOICE_SCRATCH_TRANSIENT/tools/spawn-suspended"
  local suspended_launcher_source="$SCRIPT_DIR/lib/spawn_suspended.c"
  mkdir -p "$(dirname "$suspended_launcher")"
  if [[ ! -x "$suspended_launcher" || "$suspended_launcher_source" -nt "$suspended_launcher" ]]; then
    xcrun clang -O2 -Wall -Wextra "$suspended_launcher_source" -o "$suspended_launcher" \
      || die "could not build exact-PID suspended launcher"
  fi
  local trace="$artifacts/$run_id.trace"
  local toc="$artifacts/trace-toc.xml"
  local profile_summary="$artifacts/profile-summary.json"
  local history_record="$ROOT_DIR/benchmarks/runs/instrument-profile/$run_id.json"
  local retention_policy="summaryOnly"
  (( keep_trace == 0 )) || retention_policy="keptExplicitly"
  local target_pid_file="$artifacts/target.pid"
  mkdir -p "$runtime"
  ln -s "$(debug_models_dir)" "$runtime/models"
  if [[ -f "$HOME/Library/Application Support/QwenVoice-Debug/voices/$MAC_TEST_CLONE_VOICE_NAME.wav" ]]; then
    mkdir -p "$runtime/voices"
    ln -s "$HOME/Library/Application Support/QwenVoice-Debug/voices/$MAC_TEST_CLONE_VOICE_NAME.wav" \
      "$runtime/voices/$MAC_TEST_CLONE_VOICE_NAME.wav"
    if [[ -f "$HOME/Library/Application Support/QwenVoice-Debug/voices/$MAC_TEST_CLONE_VOICE_NAME.txt" ]]; then
      ln -s "$HOME/Library/Application Support/QwenVoice-Debug/voices/$MAC_TEST_CLONE_VOICE_NAME.txt" \
        "$runtime/voices/$MAC_TEST_CLONE_VOICE_NAME.txt"
    fi
  fi
  capture_benchmark_source "$artifacts"
  local profile_label="instrument-${kind}-profile"
  note "profile: kind=$kind, instruments='$capture_instruments', ${duration}s, vocello bench (mode=$mode variant=$variant length=$profile_length warm=$profile_warm) — engine in-process"
  note "(engine OSSignpost intervals: subsystem com.qwenvoice.engine, category 'runtime')"
  # Start one owned shell process suspended, attach Instruments to that exact PID, then
  # exec the exact CLI binary in place. The PID survives exec, so trace TOC validation
  # proves the capture belongs to this run rather than another process with the same name.
  # `--no-summary` prevents the child engine lane from publishing a second record.
  local target_pid="" launcher_pid="" xctrace_pid=""
  PROFILE_TRACE_ACTIVE=1
  PROFILE_TRACE_PUBLISHED=0
  PROFILE_TRACE_KIND="$kind"
  PROFILE_TRACE_PHASE="target-launch"
  PROFILE_TRACE_ARTIFACTS="$artifacts"
  PROFILE_TRACE_PATH="$trace"
  PROFILE_TRACE_TARGET_PID=""
  PROFILE_TRACE_LAUNCHER_PID=""
  PROFILE_TRACE_XCTRACE_PID=""
  trap profile_failure_cleanup EXIT
  # Instruments records the target environment in the raw local trace. Start
  # the launcher under an explicit allowlist so unrelated desktop credentials
  # cannot be captured even though the trace itself remains untracked.
  PROFILE_TRACE_PHASE="final-disk-preflight"
  python3 "$SCRIPT_DIR/lib/profile_trace_retention.py" preflight \
    --root "$ROOT_DIR" --kind "$kind" >/dev/null \
    || die "profile disk-space preflight failed after build and before target launch"
  PROFILE_TRACE_PHASE="target-launch"
  (
    exec /usr/bin/env -i \
      HOME="$HOME" PATH="$PATH" TMPDIR="${TMPDIR:-/tmp}" \
      LANG="${LANG:-C.UTF-8}" LC_ALL="${LC_ALL:-C.UTF-8}" NO_COLOR=1 \
      QWENVOICE_DEBUG=1 QWENVOICE_NATIVE_TELEMETRY_MODE=verbose \
      "$suspended_launcher" "$target_pid_file" "$QVOICE_BUILD_ROOT/vocello" bench \
      --modes "$mode" --variants "$variant" \
      --lengths "$profile_length" --warm "$profile_warm" \
      --run-id "$run_id" --label "$profile_label" \
      --data-dir "$runtime" --no-summary
  ) >"$artifacts/target.log" 2>&1 &
  launcher_pid=$!
  PROFILE_TRACE_LAUNCHER_PID="$launcher_pid"
  local target_start_deadline=$((SECONDS + tracer_start_timeout))
  local target_suspended=0
  while kill -0 "$launcher_pid" >/dev/null 2>&1; do
    if [[ -s "$target_pid_file" ]]; then
      target_pid="$(tr -d '[:space:]' < "$target_pid_file")"
    fi
    if [[ "$target_pid" =~ ^[1-9][0-9]*$ ]] \
      && kill -0 "$target_pid" >/dev/null 2>&1 \
      && [[ "$(ps -o state= -p "$target_pid" 2>/dev/null || true)" == *T* ]]; then
      PROFILE_TRACE_TARGET_PID="$target_pid"
      target_suspended=1
      break
    fi
    (( SECONDS < target_start_deadline )) || die "profile target did not suspend within ${tracer_start_timeout}s"
    sleep 0.1
  done
  (( target_suspended == 1 )) || die "profile target exited before exact-PID attachment"
  PROFILE_TRACE_PHASE="trace-recording"
  xcrun xctrace record "${instrument_args[@]}" --attach "$target_pid" \
    --time-limit "${duration}s" --no-prompt --output "$trace" \
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
    (( SECONDS < tracer_start_deadline )) || die "xctrace did not report tracing startup within ${tracer_start_timeout}s"
    sleep 0.1
  done
  (( tracer_started == 1 )) || die "xctrace exited before reporting tracing startup"
  kill -CONT "$target_pid" >/dev/null 2>&1 || die "could not resume exact profiling target PID $target_pid"
  local profiled_pid="$target_pid"
  local target_status=0 tracer_status=0
  local target_finished=0 tracer_finished=0
  local profile_deadline=$((SECONDS + duration + profile_grace_timeout))
  while (( target_finished == 0 || tracer_finished == 0 )); do
    if (( target_finished == 0 )) && profile_child_finished "$launcher_pid"; then
      wait "$launcher_pid" || target_status=$?
      launcher_pid=""
      target_pid=""
      PROFILE_TRACE_LAUNCHER_PID=""
      PROFILE_TRACE_TARGET_PID=""
      target_finished=1
      (( target_status == 0 )) \
        || die "profiled vocello benchmark failed (see $artifacts/target.log; artifacts preserved in $artifacts)"
    fi
    if (( tracer_finished == 0 )) && profile_child_finished "$xctrace_pid"; then
      wait "$xctrace_pid" || tracer_status=$?
      xctrace_pid=""
      PROFILE_TRACE_XCTRACE_PID=""
      tracer_finished=1
      (( tracer_status == 0 )) \
        || die "xctrace failed (see $artifacts/xctrace.log; artifacts preserved in $artifacts)"
    fi
    (( target_finished == 0 || tracer_finished == 0 )) || break
    if (( SECONDS >= profile_deadline )); then
      die "profile target/tracer exceeded ${duration}s + ${profile_grace_timeout}s grace; artifacts preserved in $artifacts"
    fi
    sleep 0.1
  done
  (( target_status == 0 )) || die "profiled vocello benchmark failed (see $artifacts/target.log)"
  (( tracer_status == 0 )) || die "xctrace failed (see $artifacts/xctrace.log)"
  [[ -d "$trace" ]] || die "no trace produced at $trace"
  PROFILE_TRACE_PHASE="trace-export"
  xcrun xctrace export --input "$trace" --toc --output "$toc" \
    >"$artifacts/xctrace-export.log" 2>&1 \
    || die "trace table-of-contents validation failed (see $artifacts/xctrace-export.log)"
  [[ -s "$toc" ]] || die "trace table-of-contents export is empty"
  PROFILE_TRACE_PHASE="evidence-validation"
  python3 "$SCRIPT_DIR/publish_benchmark_history.py" profile \
    --artifact-dir "$artifacts" --snapshot "$artifacts/benchmark-source.json" \
    --platform macos --run-id "$run_id" \
    --results "$runtime/diagnostics/bench-results.json" \
    --diagnostics "$runtime/diagnostics" --output-dir "$runtime/outputs/bench" \
    --trace "$trace" --toc "$toc" --template "$capture_instruments" --duration "$duration" \
    --target-process vocello --target-pid "$profiled_pid" --profile-kind "$kind" --defer-record \
    --retention-policy "$retention_policy" --summary-artifact "$profile_summary" \
    || die "profile passed but evidence validation failed; artifacts are preserved in $artifacts"
  python3 "$SCRIPT_DIR/summarize_generation_telemetry.py" "$runtime/diagnostics" \
    --run-id "$run_id" --evidence-manifest "$artifacts/benchmark-evidence.json" \
    --engine-only --label "$profile_label" >&2 \
    || die "profile evidence was valid but its frozen telemetry summary failed"
  PROFILE_TRACE_PHASE="history-publication"
  record_benchmark_history "$artifacts" >/dev/null \
    || die "profile history publication failed"
  PROFILE_TRACE_PUBLISHED=1
  PROFILE_TRACE_PHASE="retention-finalization"
  python3 "$SCRIPT_DIR/lib/profile_trace_retention.py" finalize-success \
    --root "$ROOT_DIR" --platform macos --kind "$kind" \
    --artifact-dir "$artifacts" --trace "$trace" --policy "$retention_policy" \
    --summary-artifact "$profile_summary" --history-record "$history_record" \
    || die "profile was published but raw-trace retention finalization failed; run routine cleanup"
  trap - EXIT
  PROFILE_TRACE_ACTIVE=0
  if (( keep_trace )); then
    note "trace retained explicitly → $trace"
    note "analyze: open in Instruments, or use optional: xcprof analyze \"$trace\""
  else
    note "validated summary → $profile_summary"
    note "raw trace removed after successful history publication (use --keep-trace to retain one)"
  fi
  note "XPC service profile (production path): launch app, 'xctrace record --attach QwenVoiceEngineService', generate via UI."
}

# memory [--label ID]: retained-memory qualification, separate from Instruments.
# Runs one in-process Custom→Design→Clone Speed/medium sequence with three retained takes per
# mode (plus the CLI's real cold Custom/Design takes), then publishes only when telemetry-v8
# sidecars and the versioned within-mode retention policy pass. Use `profile --kind memory`
# when allocation stacks or VM maps are needed instead.
cmd_memory() {
  local label="memory-qualification"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --label) label="${2:-}"; shift 2 ;;
      --label=*) label="${1#*=}"; shift ;;
      *) die "memory accepts only --label ID; its mode order and take counts are policy-owned" ;;
    esac
  done
  validate_benchmark_label "$label"
  local policy="$ROOT_DIR/config/memory-qualification-policy.json"
  [[ -f "$policy" ]] || die "memory qualification policy is missing: $policy"
  "$SCRIPT_DIR/build.sh" cli-optimized >/dev/null
  require_mac_benchmark_models pro_custom_speed pro_design_speed pro_clone_speed
  require_mac_benchmark_clone_fixture

  local run_id="mac-memory-qualification-$(date -u +%Y%m%d-%H%M%S)-$(benchmark_nonce)"
  local artifacts="$QVOICE_ARTIFACTS_MACOS/memory/$run_id"
  local runtime="$artifacts/runtime"
  local debug_voices="$HOME/Library/Application Support/QwenVoice-Debug/voices"
  mkdir -p "$runtime"
  ln -s "$(debug_models_dir)" "$runtime/models"
  # FileManager's directory enumerator does not descend through a symlink used
  # as the voices-directory root. Keep a real isolated directory and expose
  # only the exact approved fixture files as symlinked entries.
  mkdir -p "$runtime/voices"
  ln -s "$debug_voices/$MAC_TEST_CLONE_VOICE_NAME.wav" \
    "$runtime/voices/$MAC_TEST_CLONE_VOICE_NAME.wav"
  ln -s "$debug_voices/$MAC_TEST_CLONE_VOICE_NAME.txt" \
    "$runtime/voices/$MAC_TEST_CLONE_VOICE_NAME.txt"
  capture_benchmark_source "$artifacts"

  note "memory qualification: Custom→Design→Clone, Speed/medium, 3 retained takes per mode"
  QWENVOICE_DEBUG=1 QWENVOICE_NATIVE_TELEMETRY_MODE=verbose \
    "$QVOICE_BUILD_ROOT/vocello" bench \
      --modes custom,design,clone --variants speed --lengths medium --warm 3 \
      --voice "$MAC_TEST_CLONE_VOICE_NAME" --telemetry verbose --seed 19790615 \
      --memory-qualification retained-memory-v1 \
      --run-id "$run_id" --label "$label" --data-dir "$runtime" --no-summary \
      >"$artifacts/bench.log" 2>&1 \
    || die "memory qualification generation sequence failed (see $artifacts/bench.log)"
  local results="$runtime/diagnostics/bench-results.json"
  [[ -s "$results" ]] || die "memory qualification did not produce bench-results.json"
  python3 "$SCRIPT_DIR/publish_benchmark_history.py" memory-qualification \
    --artifact-dir "$artifacts" --snapshot "$artifacts/benchmark-source.json" \
    --platform macos --run-id "$run_id" --results "$results" \
    --diagnostics "$runtime/diagnostics" --output-dir "$runtime/outputs/bench" \
    --label "$label" --defer-record \
    || die "memory sequence passed but qualification failed; artifacts are preserved in $artifacts"
  python3 "$SCRIPT_DIR/summarize_generation_telemetry.py" "$runtime/diagnostics" \
    --run-id "$run_id" --evidence-manifest "$artifacts/benchmark-evidence.json" \
    --engine-only --label "$label" >"$artifacts/summary.txt" 2>&1 \
    || die "memory qualification evidence was valid but its frozen summary failed"
  # CP-2 zero-peak (Article 50 marking): within every take, nothing at or
  # after the marking interval may exceed the take's pre-marking peak, and
  # the marking boundaries must be present (marking actually ran). Fail
  # closed before the record may publish.
  local equality_policy="$ROOT_DIR/config/marking-peak-equality.json"
  if [[ -f "$equality_policy" ]]; then
    python3 "$SCRIPT_DIR/check_marking_peak_equality.py" \
      "$artifacts/benchmark-evidence.json" \
      --tolerance-percent "$(python3 -c "import json;print(json.load(open('$equality_policy')).get('tolerancePercent',5.0))")" \
      --tolerance-mb "$(python3 -c "import json;print(json.load(open('$equality_policy')).get('toleranceMB',48.0))")" \
      || die "marking peak-equality assertion failed; the qualification record was not published"
  fi
  record_benchmark_history "$artifacts" >/dev/null \
    || die "memory qualification history publication failed"
  note "memory qualification PASS · $artifacts"
}

# preflight: one-shot readiness — Xcode, the app bundle, the embedded XPC service,
# the preserved dSYMs, and the Speed model. Fails fast with what's missing.
cmd_preflight() {
  local rc=0
  local strict_models=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --strict-models) strict_models=1; shift ;;
      *) die "unknown preflight flag: $1 (try --strict-models)" ;;
    esac
  done
  note "macOS preflight"
  command -v xcodebuild >/dev/null 2>&1 && note "  xcodebuild: OK" || { warn "  xcodebuild: ✗ not found"; rc=1; }
  if [[ -d "$APP_BUNDLE" ]]; then note "  app: OK $APP_BUNDLE"; else warn "  app: ✗ not built (run: scripts/build.sh build)"; rc=1; fi
  [[ -d "$XPC_BUNDLE" ]] && note "  xpc service: OK" || warn "  xpc service: ✗ not in bundle (rebuild)"
  if [[ -d "$DSYM_DIR" && -d "$APP_BUNDLE" ]] \
      && validate_dsym_uuid "$APP_BINARY" "$DSYM_DIR/Vocello.app.dSYM" "Vocello" \
      && validate_dsym_uuid \
        "$XPC_BUNDLE/Contents/MacOS/QwenVoiceEngineService" \
        "$DSYM_DIR/QwenVoiceEngineService.xpc.dSYM" "QwenVoiceEngineService"; then
    note "  dsyms: OK $DSYM_DIR (UUID-matched)"
  else
    warn "  dsyms: ✗ missing or UUID-mismatched (run: scripts/build.sh build)"
    rc=1
  fi
  if (( strict_models == 1 )); then
    check_mac_test_models --strict || rc=1
  else
    check_mac_test_models || warn "  models: not ready for generation lanes (run: $0 models ensure)"
  fi
  (( rc == 0 )) && note "preflight OK" || die "preflight not ready (see above)"
}

cmd_models() {
  local sub="${1:-check}"
  shift || true
  case "$sub" in
    check)
      check_mac_test_models || {
        note "Install once: $0 models ensure  (or $0 models install for canonical only)"
        note "Last resort: Vocello.app → Settings → Model Downloads"
        return 1
      }
      ;;
    ensure)
      ensure_mac_test_models --require
      ;;
    install)
      ensure_vocello_cli
      local id="${1:-pro_custom_speed}"
      note "installing $id into canonical store (shared with the app)…"
      "$TEST_MODELS_VOCELLO" models install "$id"
      link_debug_models_from_canonical || true
      ;;
    help|-h|--help)
      cat >&2 <<EOF
models — test fixture for macOS real-engine lanes

  $0 models check     read-only status (debug context, matches UI smoke)
  $0 models ensure    install if missing + link QwenVoice-Debug/models → canonical + clone voice
  $0 models install [id]   headless download via vocello (default: pro_custom_speed)

Escape: QVOICE_SKIP_MODEL_ENSURE=1  QVOICE_TEST_MODELS_NO_NETWORK=1
EOF
      ;;
    *)
      die "unknown models subcommand '$sub' (try: check|ensure|install|help)"
      ;;
  esac
}

# core-test: VocelloCoreTests (core semantics + host-runnable iOS policy, no models).
cmd_core_test() {
  local test_filter=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --only) test_filter="${2:-}"; shift 2 ;;
      --only=*) test_filter="${1#*=}"; shift ;;
      *) die "unknown core-test argument '$1' (try --only TestClass[/testMethod])" ;;
    esac
  done
  [[ -z "$test_filter" || "$test_filter" =~ ^[A-Za-z_][A-Za-z0-9_.]*(/[A-Za-z_][A-Za-z0-9_]*)?(,[A-Za-z_][A-Za-z0-9_.]*(/[A-Za-z_][A-Za-z0-9_]*)?)*$ ]] \
    || die "core-test --only must contain comma-separated TestClass or TestClass/testMethod identifiers"
  if [[ -n "$test_filter" ]]; then
    note "core-test: focused VocelloCoreTests selection $test_filter (no models)"
  else
    note "core-test: VocelloCoreTests (QwenVoiceCore + iOS policy semantics, no models)"
  fi
  local build_log="$QVOICE_ARTIFACTS_MACOS/tests/core-test-build.log"
  local test_log="$QVOICE_ARTIFACTS_MACOS/tests/core-test.log"
  rm -f "$test_log"
  set +e
  local build_st=0 st=0
  build_mac_test_bundles "$build_log" || build_st=$?
  if (( build_st == 0 )); then
    run_mac_test_bundle VocelloCoreTests "$test_log" 0 "$test_filter" || st=$?
  else
    st="$build_st"
  fi
  set -e
  if (( st == 0 )); then
    note "core-test PASS"
  elif (( build_st != 0 )); then
    warn "core-test BUILD FAIL (see build/artifacts/macos/tests/core-test-build.log)"
  else
    warn "core-test FAIL (see build/artifacts/macos/tests/core-test.log)"
  fi
  return "$st"
}

# Thread Sanitizer characterization deliberately excludes execution of the
# MLX/Metal runtime test bundle: the owned deterministic core and injectable XPC
# transport are the stable CPU subset, while MLX has its own single-owner/runtime
# tests. Xcode may still compile linked package targets while building the host.
# The
# scheduled workflow retains both logs and remains non-blocking only while the
# policy records characterization status.
cmd_tsan() {
  [[ $# -eq 0 ]] || die "tsan accepts no arguments"
  local run_id="tsan-$(date +%Y%m%d-%H%M%S)"
  local artifacts="$QVOICE_ARTIFACTS_MACOS/tests/$run_id"
  local build_st=0 core_st=0 transport_st=0
  mkdir -p "$artifacts"
  note "tsan: deterministic core and injectable XPC transport subset"
  set +e
  QWENVOICE_ENABLE_TSAN=1 build_mac_test_bundles "$artifacts/build.log" || build_st=$?
  if (( build_st == 0 )); then
    run_mac_test_bundle VocelloCoreTests "$artifacts/core.log" 1 || core_st=$?
    run_mac_test_bundle VocelloEngineIntegrationTests "$artifacts/transport.log" 1 || transport_st=$?
  else
    core_st="$build_st"
    transport_st="$build_st"
  fi
  set -e
  printf 'build=%s\ncore=%s\ntransport=%s\n' \
    "$build_st" "$core_st" "$transport_st" > "$artifacts/verdict.txt"
  cat "$artifacts/verdict.txt" >&2
  if (( build_st == 0 && core_st == 0 && transport_st == 0 )); then
    note "tsan characterization PASS · artifacts → $artifacts"
    return 0
  fi
  warn "tsan characterization FAIL · artifacts → $artifacts"
  return 1
}

cmd_lang_bench() {
  local subset="full" label=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --subset) subset="${2:-full}"; shift 2 ;;
      --subset=*) subset="${1#*=}"; shift ;;
      --label) label="${2:-}"; shift 2 ;;
      --label=*) label="${1#*=}"; shift ;;
      *) die "unknown lang-bench arg '$1' (try --subset quick|full --label lang-check-v1)" ;;
    esac
  done
  validate_benchmark_label "$label"
  [[ "$subset" == "quick" || "$subset" == "full" ]] || die "--subset must be quick or full"

  local matrix="$ROOT_DIR/config/language-bench-matrix.json"
  local corpus="$ROOT_DIR/config/language-bench-corpus.json"
  [[ -f "$matrix" && -f "$corpus" ]] || die "missing language bench config"

  "$SCRIPT_DIR/build.sh" cli-optimized >/dev/null

  # Resolve the exact model set selected by this language matrix before the
  # first generation. The check is read-only; downloads remain an explicit
  # `models ensure` repair action.
  while IFS= read -r model_id; do
    [[ -n "$model_id" ]] || continue
    require_mac_benchmark_models "$model_id"
  done < <(python3 - "$matrix" "$subset" <<'PY'
import json, sys
matrix, subset = json.load(open(sys.argv[1])), sys.argv[2]
cells = matrix["cells"] if subset == "full" else [c for c in matrix["cells"] if c.get("quick")]
for model_id in sorted({f"pro_{cell['mode']}_{cell.get('variant', 'speed')}" for cell in cells}):
    print(model_id)
PY
)

  local run_id
  run_id="mac-lang-bench-$(date -u +%Y%m%d-%H%M%S)-$(benchmark_nonce)"
  local artifacts="$QVOICE_ARTIFACTS_MACOS/language/lang-bench-$run_id"
  local started_at
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local diag_root
  diag_root="${HOME}/Library/Application Support/QwenVoice-Debug/diagnostics"
  mkdir -p "$artifacts"
  capture_benchmark_source "$artifacts"

  export QWENVOICE_DEBUG=1
  export QVOICE_MAC_BENCH_RUN_ID="$run_id"
  note "lang-bench: runID=$run_id subset=$subset (macOS in-process CLI)"

  local cell_json cell_count=0 cell_fail=0 voice_brief="A clear, steady narrator with a natural conversational tone."
  while IFS= read -r cell_json; do
    [[ -n "$cell_json" ]] || continue
    cell_count=$((cell_count + 1))
    local cell_id mode variant ui_hint text
    cell_id="$(CELL="$cell_json" python3 -c 'import json,os; print(json.loads(os.environ["CELL"])["id"])')"
    mode="$(CELL="$cell_json" python3 -c 'import json,os; print(json.loads(os.environ["CELL"])["mode"])')"
    variant="$(CELL="$cell_json" python3 -c 'import json,os; print(json.loads(os.environ["CELL"]).get("variant","speed"))')"
    ui_hint="$(CELL="$cell_json" python3 -c 'import json,os; print(json.loads(os.environ["CELL"]).get("uiHint","auto"))')"
    text="$(CELL="$cell_json" python3 -c 'import json,os; print(json.loads(os.environ["CELL"])["script"], end="")')"
    export QVOICE_MAC_BENCH_CELL="$cell_id"
    local -a generate_command=(
      "$QVOICE_BUILD_ROOT/vocello" generate --mode "$mode" --variant "$variant"
    )
    if [[ "$mode" == "design" ]]; then
      generate_command+=(--voice-brief "$voice_brief")
    elif [[ "$mode" != "custom" ]]; then
      die "lang-bench cell $cell_id: unsupported mode '$mode'"
    fi
    generate_command+=(--text "$text")
    if [[ "$ui_hint" != "auto" ]]; then
      generate_command+=(--language "$ui_hint")
    fi
    note "lang-bench cell $cell_count: $cell_id ($mode/$variant, uiHint=$ui_hint)"
    set +e
    # Scoped per generation: schema-v2 language publication requires the raw
    # v8 memory sidecar, while the caller's telemetry preference must survive.
    QWENVOICE_NATIVE_TELEMETRY_MODE=verbose \
      "${generate_command[@]}" >>"$artifacts/generate.log" 2>&1
    st=$?
    set -e
    if (( st != 0 )); then
      warn "lang-bench cell $cell_id: vocello generate exit $st"
      cell_fail=$((cell_fail + 1))
    fi
  done < <(python3 - "$matrix" "$corpus" "$subset" <<'PY'
import json, sys
matrix_path, corpus_path, subset = sys.argv[1:4]
cells = json.load(open(matrix_path))["cells"]
if subset == "quick":
    cells = [c for c in cells if c.get("quick")]
corpus = {e["id"]: e["script"] for e in json.load(open(corpus_path))["languages"]}
for cell in cells:
    cell = dict(cell)
    cell["script"] = corpus[cell["scriptLang"]]
    print(json.dumps(cell, ensure_ascii=False))
PY
)

  unset QVOICE_MAC_BENCH_RUN_ID QVOICE_MAC_BENCH_CELL

  [[ "$cell_count" -gt 0 ]] || die "lang-bench: no cells for subset=$subset"

  local hint_st=0
  python3 "$ROOT_DIR/scripts/check_language_hints.py" "$diag_root" \
    --run-id "$run_id" --matrix "$matrix" --corpus "$corpus" --subset "$subset" \
    | tee "$artifacts/hint-gate.txt" || hint_st=$?

  {
    echo "lang-bench runID=$run_id subset=$subset cells=$cell_count generate_fail=$cell_fail"
    echo "hint_gate=$([[ $hint_st -eq 0 ]] && echo PASS || echo FAIL)"
  } | tee "$artifacts/verdict.txt"

  if (( cell_fail > 0 || hint_st != 0 )); then
    die "lang-bench FAIL · $artifacts"
  fi
  python3 "$SCRIPT_DIR/publish_benchmark_history.py" language \
    --artifact-dir "$artifacts" --snapshot "$artifacts/benchmark-source.json" \
    --platform macos --run-id "$run_id" --diagnostics "$diag_root" \
    --matrix "$matrix" --corpus "$corpus" --subset "$subset" \
    --output-gate not-performed --started-at "$started_at" \
    --design-fixture-digest "$(string_sha256 "$voice_brief")" --defer-record \
    ${label:+--label "$label"} \
    || die "language benchmark passed but evidence validation failed; artifacts are preserved in $artifacts"
  python3 "$SCRIPT_DIR/summarize_generation_telemetry.py" "$diag_root" \
    --run-id "$run_id" --evidence-manifest "$artifacts/benchmark-evidence.json" \
    --engine-only ${label:+--label "$label"} >"$artifacts/summary.txt" 2>&1 \
    || die "language evidence was valid but its frozen telemetry summary failed"
  record_benchmark_history "$artifacts" >/dev/null \
    || die "language history publication failed"
  note "lang-bench PASS · $artifacts"
}

# test: deterministic Core, XPC transport, and owned Qwen3 runtime tests. No UI
# process is launched and no frontend action is synthesized.
cmd_test() {
  local run_id="mac-test-$(date +%Y%m%d-%H%M%S)"
  local artifacts="$QVOICE_ARTIFACTS_MACOS/tests/$run_id"
  mkdir -p "$artifacts"
  local test_build_st=0 core_st=0 transport_st=0 runtime_st=0

  note "test: compile deterministic macOS test bundles"
  set +e
  build_mac_test_bundles "$artifacts/xcode-test-build.log" || test_build_st=$?

  if (( test_build_st == 0 )); then
    note "test: VocelloCoreTests"
    run_mac_test_bundle VocelloCoreTests "$artifacts/core.log" || core_st=$?

    note "test: VocelloEngineIntegrationTests (injectable XPC transport)"
    run_mac_test_bundle VocelloEngineIntegrationTests "$artifacts/transport.log" || transport_st=$?
  else
    core_st="$test_build_st"
    transport_st="$test_build_st"
  fi

  note "test: Qwen3RuntimeTests (owned core runtime, seeded Metal fixture)"
  local runtime_package="$ROOT_DIR/Packages/VocelloQwen3Core"
  local mlx_bundle="$QVOICE_XCODE_MACOS_DERIVED/Build/Products/Release/mlx-swift_Cmlx.bundle"
  if ensure_swiftpm_scratch_location "$runtime_package" "$QVOICE_SWIFTPM_RUNTIME_CACHE" \
      && swift build --package-path "$runtime_package" \
      --scratch-path "$QVOICE_SWIFTPM_RUNTIME_CACHE" --configuration debug \
      --force-resolved-versions \
      --build-tests \
      > "$artifacts/runtime-build.log" 2>&1; then
    local runtime_bin runtime_resources
    runtime_bin="$(swift build --package-path "$runtime_package" \
      --scratch-path "$QVOICE_SWIFTPM_RUNTIME_CACHE" --configuration debug \
      --force-resolved-versions \
      --show-bin-path)"
    runtime_resources="$runtime_bin/MLXAudioPackageTests.xctest/Contents/Resources"
    if [[ -d "$mlx_bundle" ]]; then
      mkdir -p "$runtime_resources"
      rm -rf "$runtime_resources/mlx-swift_Cmlx.bundle"
      cp -R "$mlx_bundle" "$runtime_resources/"
      if assert_macho_arm64_only \
          "$runtime_bin/MLXAudioPackageTests.xctest/Contents/MacOS/MLXAudioPackageTests" \
          "MLXAudioPackageTests"; then
        # Partition-invariance is a full-float determinism contract. Disabling
        # TF32 also avoids MLX's NAX float32 GEMM path, whose runtime-compiled
        # kernel is not accepted by the Metal compiler bundled with Xcode 26.5
        # on GitHub's macOS 26 runner. No test is skipped or moved off Metal.
        MLX_ENABLE_TF32=0 swift test --package-path "$runtime_package" \
          --scratch-path "$QVOICE_SWIFTPM_RUNTIME_CACHE" --configuration debug \
          --force-resolved-versions \
          --skip-build \
          --filter Qwen3RuntimeTests \
          > "$artifacts/runtime.log" 2>&1 || runtime_st=$?
      else
        runtime_st=1
      fi
      if (( runtime_st == 0 )); then
        write_build_provenance "$QVOICE_SWIFTPM_RUNTIME_CACHE/last-build.json" \
          "scripts/macos_test.sh runtime" Qwen3RuntimeTests Debug \
          "platform=macOS,arch=arm64" arm64 Onone unsigned \
          "$QVOICE_SWIFTPM_RUNTIME_CACHE" "$QVOICE_SWIFTPM_RUNTIME_CACHE" \
          || runtime_st=$?
      fi
    else
      echo "missing MLX Metal resource bundle after Xcode test build: $mlx_bundle" \
        > "$artifacts/runtime.log"
      runtime_st=1
    fi
  else
    runtime_st=1
  fi

  set -e
  printf 'test_build=%s\ncore=%s\ntransport=%s\nruntime=%s\n' \
    "$test_build_st" "$core_st" "$transport_st" "$runtime_st" \
    > "$artifacts/verdict.txt"
  cat "$artifacts/verdict.txt" >&2
  if (( core_st == 0 && transport_st == 0 && runtime_st == 0 )); then
    note "test verdict: PASS · artifacts → $artifacts"
  else
    warn "test verdict: FAIL · artifacts → $artifacts"
    return 1
  fi
}

cmd_telemetry_overhead() {
  # Explicit model-dependent diagnostic. UI readiness is checked separately by
  # scripts/ui_test.sh before every UI-driven generation.
  check_mac_test_models --strict
  "$SCRIPT_DIR/build.sh" cli-optimized >/dev/null
  local verdict_path
  note "telemetry-overhead: 3 counterbalanced rotations; warm-up×1 + measured×2 per mode/rotation"
  verdict_path="$(python3 "$SCRIPT_DIR/telemetry_overhead.py" "$@")" \
    || die "telemetry-overhead FAIL (see the artifact path reported by telemetry_overhead.py)"
  [[ -f "$verdict_path" ]] || die "telemetry-overhead verdict missing: $verdict_path"
  note "telemetry-overhead PASS (local diagnostic; not benchmark-history eligible) · $verdict_path"
}

# gate: one-command macOS deterministic gate — inputs → build → Core,
# transport, and runtime tests → crashes.
# Optional bounded engine bench remains available with QWENVOICE_GATE_BENCH=1.

GATE_BENCH_BASELINE="$ROOT_DIR/benchmarks/baselines/mac-gate-bench.json"

run_gate_bench() {
  local gate_dir="$1"
  local log="$gate_dir/bench.log"
  local run_id="mac-gate-bench-$(date -u +%Y%m%d-%H%M%S)-$(benchmark_nonce)"
  local artifacts="$gate_dir/engine-benchmark"
  local runtime="$artifacts/runtime"
  local run_diag="$runtime/diagnostics"
  note "gate bench: custom/speed/medium warm×1 (engine in-process)"
  "$ROOT_DIR/scripts/build.sh" cli-optimized >>"$log" 2>&1 || return 1
  require_mac_benchmark_models pro_custom_speed >>"$log" 2>&1 || return 1
  mkdir -p "$runtime"
  ln -s "$(debug_models_dir)" "$runtime/models"
  capture_benchmark_source "$artifacts"

  QWENVOICE_DEBUG=1 "$QVOICE_BUILD_ROOT/vocello" bench --modes custom --variants speed \
    --lengths medium --warm 1 --run-id "$run_id" --label "mac-gate-bench" \
    --data-dir "$runtime" --force --no-summary >>"$log" 2>&1 || return 1
  [[ -s "$run_diag/engine/generations.jsonl" ]] \
    || { echo "gate bench: bench produced no run-scoped telemetry rows" >>"$log"; return 1; }
  [[ -s "$run_diag/bench-results.json" ]] \
    || { echo "gate bench: missing bench-results.json" >>"$log"; return 1; }

  # audioQC must pass on every row of THIS run.
  python3 - "$run_diag/engine/generations.jsonl" <<'PY' >>"$log" 2>&1 || return 1
import json, sys
fails = []
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    row = json.loads(line)
    qc = (row.get("audioQC") or {}).get("verdict")
    if qc == "fail":
        fails.append(row.get("generationID", "?"))
if fails:
    print(f"gate bench: audioQC fail on {len(fails)} row(s): {', '.join(fails)}", file=sys.stderr)
    sys.exit(1)
print("gate bench: audioQC pass on all rows")
PY

  # Freeze the exact validated take selection before any human summary or
  # comparison. The parent gate records it only after every gate step passes.
  python3 "$SCRIPT_DIR/publish_benchmark_history.py" engine \
    --artifact-dir "$artifacts" --snapshot "$artifacts/benchmark-source.json" \
    --platform macos --run-id "$run_id" \
    --results "$run_diag/bench-results.json" --diagnostics "$run_diag" \
    --output-dir "$runtime/outputs/bench" --label "mac-gate-bench" --defer-record \
    >>"$log" 2>&1 || return 1

  python3 "$ROOT_DIR/scripts/summarize_generation_telemetry.py" "$run_diag" \
    --run-id "$run_id" --evidence-manifest "$artifacts/benchmark-evidence.json" \
    --engine-only --label "mac-gate-bench" >>"$log" 2>&1 || return 1

  # Regression compare vs the committed baseline (exit 2 on >5% regression).
  if [[ -f "$GATE_BENCH_BASELINE" ]]; then
    if ! python3 "$ROOT_DIR/scripts/summarize_generation_telemetry.py" "$run_diag" \
        --run-id "$run_id" --evidence-manifest "$artifacts/benchmark-evidence.json" \
        --engine-only --compare-baseline "$GATE_BENCH_BASELINE" \
        --require-baseline-identity >>"$log" 2>&1; then
      echo "gate bench: REGRESSION vs $GATE_BENCH_BASELINE (see bench.log)" >>"$log"
      return 1
    fi
    echo "gate bench: no regression vs $(basename "$GATE_BENCH_BASELINE")" >>"$log"
  else
    echo "gate bench: no committed baseline at $GATE_BENCH_BASELINE — compare skipped" >>"$log"
    echo "  (seed one: run the gate bench, then summarize_generation_telemetry.py <run-diag> --save-baseline $GATE_BENCH_BASELINE)" >>"$log"
  fi
  return 0
}

gate_crash_delta() {
  local gate_dir="$1" crash_marker="$2"
  cmd_crashes >>"$gate_dir/crashes.log" 2>&1 || return 1
  local diagnostic_root="$HOME/Library/Logs/DiagnosticReports" new_ips
  new_ips="$(find "$diagnostic_root" \( -name 'Vocello-*.ips' -o -name 'QwenVoiceEngineService-*.ips' -o -name '*engine-service*.ips' \) -newer "$crash_marker" 2>/dev/null || true)"
  if [[ -n "$new_ips" ]]; then
    printf '%s\n' "$new_ips" >"$gate_dir/new-crashes.txt"
    return 1
  fi
}

cmd_gate() {
  local run_id="mac-gate-$(date +%Y%m%d-%H%M%S)"
  local gate_dir="$QVOICE_ARTIFACTS_MACOS/gates/gate-$run_id"
  local verdict="$gate_dir/verdict.txt"
  local step_ledger="$gate_dir/required-steps.json"
  mkdir -p "$gate_dir"
  local overall=0
  local gate_bench=0
  [[ "${QWENVOICE_GATE_BENCH:-0}" == "1" ]] && gate_bench=1
  local total_steps=4
  (( gate_bench )) && total_steps=5
  local workflow="macos-gate"
  (( gate_bench )) && workflow="macos-gate-with-benchmark"
  required_steps_init "$step_ledger" "$workflow" "$run_id"
  { echo "Vocello macOS gate — $run_id"; echo; } | tee "$verdict"

  # Marker for the gate-fatal crash-delta check: only .ips files newer than this
  # (i.e. crashes that happen DURING the gate run) fail the gate.
  local crash_marker="$gate_dir/.crash-marker"
  touch "$crash_marker"

  note "gate step 0/$total_steps: check_project_inputs"
  if required_step_run "$step_ledger" project-inputs \
      "$SCRIPT_DIR/check_project_inputs.sh" >>"$gate_dir/inputs.log" 2>&1; then
    echo "check_project_inputs: PASS" | tee -a "$verdict"
  else echo "check_project_inputs: FAIL" | tee -a "$verdict"; overall=1; fi

  note "gate step 1/$total_steps: build_foundation_targets macos"
  if required_step_run "$step_ledger" foundation-build \
      "$SCRIPT_DIR/build_foundation_targets.sh" macos >>"$gate_dir/build.log" 2>&1; then
    echo "build_foundation macos: PASS" | tee -a "$verdict"
  else echo "build_foundation macos: FAIL" | tee -a "$verdict"; overall=1; fi

  note "gate step 2/$total_steps: core-test (VocelloCoreTests)"
  if required_step_run "$step_ledger" core-tests cmd_core_test \
      >>"$gate_dir/core-test.log" 2>&1; then
    echo "core-test: PASS" | tee -a "$verdict"
  else echo "core-test: FAIL" | tee -a "$verdict"; overall=1; fi

  note "gate step 3/$total_steps: deterministic Core + XPC transport + Qwen3 runtime tests"
  if required_step_run "$step_ledger" deterministic-tests cmd_test \
      >>"$gate_dir/test.log" 2>&1; then
    echo "test: PASS" | tee -a "$verdict"
  else echo "test: FAIL" | tee -a "$verdict"; overall=1; fi

  note "gate step 4/$total_steps: crashes (GATE-FATAL on new .ips during this run)"
  if required_step_run "$step_ledger" crash-delta \
      gate_crash_delta "$gate_dir" "$crash_marker"; then
    echo "crashes: PASS (no new .ips)" | tee -a "$verdict"
  else
    echo "crashes: FAIL (see crashes.log/new-crashes.txt)" | tee -a "$verdict"
    overall=1
  fi

  if (( gate_bench )); then
    note "gate step 5/$total_steps: bounded vocello bench (QWENVOICE_GATE_BENCH=1)"
    if required_step_run "$step_ledger" benchmark-validation run_gate_bench "$gate_dir"; then
      echo "bench: PASS (see bench.log)" | tee -a "$verdict"
    else
      echo "bench: FAIL (see bench.log)" | tee -a "$verdict"; overall=1
    fi
  fi

  if (( overall == 0 && gate_bench )); then
    if required_step_run "$step_ledger" history-publication \
        record_benchmark_history "$gate_dir/engine-benchmark" >>"$gate_dir/bench.log" 2>&1; then
      echo "history: PASS" | tee -a "$verdict"
    else
      echo "history: FAIL (see bench.log)" | tee -a "$verdict"
      overall=1
    fi
  fi

  echo | tee -a "$verdict"
  if ! required_steps_finalize "$step_ledger"; then
    overall=1
  fi
  if (( overall == 0 )); then
    echo "GATE: PASS" | tee -a "$verdict"; note "gate PASS · $gate_dir"
  else
    echo "GATE: FAIL" | tee -a "$verdict"; note "gate FAIL · $gate_dir"
  fi
  cat "$verdict" >&2
  exit "$overall"
}

cmd_release_readiness() {
  [[ $# -eq 0 ]] || die "release-readiness accepts no arguments"
  local run_id="release-readiness-$(date +%Y%m%d-%H%M%S)"
  local out="$QVOICE_ARTIFACTS_MACOS/release-readiness/$run_id"
  local crash_marker="$out/.crash-marker"
  local step_ledger="$out/required-steps.json"
  mkdir -p "$out"
  touch "$crash_marker"
  required_steps_init "$step_ledger" macos-release-readiness "$run_id"

  note "release readiness: project inputs"
  required_step_run "$step_ledger" project-inputs \
    "$SCRIPT_DIR/check_project_inputs.sh" 2>&1 | tee "$out/project-inputs.log"

  note "release readiness: exact-path app build"
  required_step_run "$step_ledger" app-build \
    "$SCRIPT_DIR/build.sh" build 2>&1 | tee "$out/build.log"

  note "release readiness: deterministic macOS tests"
  required_step_run "$step_ledger" deterministic-tests cmd_test \
    2>&1 | tee "$out/tests.log"

  note "release readiness: crash delta"
  required_step_run "$step_ledger" crash-delta \
    gate_crash_delta "$out" "$crash_marker" \
    || die "release readiness found a crash-check failure (see $out/crashes.log and $out/new-crashes.txt)"

  required_steps_finalize "$step_ledger" \
    || die "release readiness required-step ledger did not pass"

  printf 'RELEASE READINESS: PASS\n' | tee "$out/verdict.txt"
  note "release readiness PASS · $out"
}

main() {
  local sub="${1:-help}"; shift || true
  case "$sub" in
    crashes) cmd_crashes "$@" ;;
    debug)   cmd_debug "$@" ;;
    logs)    cmd_logs "$@" ;;
    profile) cmd_profile "$@" ;;
    memory)
      require_build_free_space memory-qualification \
        || die "macOS memory qualification storage preflight failed"
      cmd_memory "$@"
      ;;
    preflight) cmd_preflight "$@" ;;
    core-test)
      require_build_free_space runtime-tests || die "macOS test storage preflight failed"
      cmd_core_test "$@"
      ;;
    tsan)
      require_build_free_space runtime-tests || die "macOS TSan storage preflight failed"
      cmd_tsan "$@"
      ;;
    lang-bench)
      require_build_free_space language-benchmark || die "language benchmark storage preflight failed"
      cmd_lang_bench "$@"
      ;;
    test)
      require_build_free_space runtime-tests || die "macOS test storage preflight failed"
      cmd_test "$@"
      ;;
    telemetry-overhead)
      require_build_free_space telemetry-overhead || die "telemetry-overhead storage preflight failed"
      cmd_telemetry_overhead "$@"
      ;;
    gate)
      require_build_free_space runtime-tests || die "macOS gate storage preflight failed"
      cmd_gate "$@"
      ;;
    release-readiness)
      require_build_free_space runtime-tests || die "release-readiness storage preflight failed"
      cmd_release_readiness "$@"
      ;;
    models)    cmd_models "$@" ;;
    help|-h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//' >&2
      ;;
    *) die "unknown subcommand '$sub' (try: preflight|core-test|tsan|lang-bench|test|telemetry-overhead|crashes|debug|logs|profile|memory|gate|release-readiness|models|help)" ;;
  esac
}

main "$@"
