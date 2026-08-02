# Shared build-cache helpers for QwenVoice / Vocello.
#
# Sourced by scripts/build.sh (debug/run path) and scripts/release.sh
# (release path) so that XcodeGen regeneration and SwiftPM resolution
# only run when their inputs have actually changed.
#
# Usage:
#
#   ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
#   . "$ROOT_DIR/scripts/lib/build_cache.sh"
#
#   ensure_project_regenerated
#   ensure_spm_resolved "<derived-data-path>" "<source-packages-dir>" \
#     "<context-tag>" "<scheme>" "<configuration>" "<destination>"
#   xcb_run <xcodebuild args...>
#
# Callers must have set ROOT_DIR before sourcing or pass it explicitly.

# shellcheck shell=bash

if [ -z "${ROOT_DIR:-}" ]; then
    ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

# shellcheck source=build_paths.sh
if [[ -z "${QVOICE_BUILD_ROOT:-}" ]]; then
    . "$ROOT_DIR/scripts/lib/build_paths.sh"
fi

BUILD_CACHE_DIR="${BUILD_CACHE_DIR:-$QVOICE_XCODE_SOURCE_PACKAGES/.qwenvoice-cache}"
PROJECT_YML="$ROOT_DIR/project.yml"
PROJECT_FILE="$ROOT_DIR/QwenVoice.xcodeproj"
PROJECT_RESOLVED="$PROJECT_FILE/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
QVOICE_ACTIVE_PACKAGE_LOCK=""
QVOICE_IOS_PLATFORM_PREFLIGHT_COMPLETE="${QVOICE_IOS_PLATFORM_PREFLIGHT_COMPLETE:-0}"

# Current Xcode releases require matching installed iOS Platform Support even
# for the generic physical-device SDK destination. This is a read-only host
# toolchain check: it never downloads a component or executes a Simulator.
require_ios_xcode_platform() {
    if [[ "$QVOICE_IOS_PLATFORM_PREFLIGHT_COMPLETE" == "1" ]]; then
        return 0
    fi
    python3 "$ROOT_DIR/scripts/lib/ios_platform_preflight.py" check || return 1
    QVOICE_IOS_PLATFORM_PREFLIGHT_COMPLETE=1
}

acquire_package_store_lock() {
    local source_packages="$1" lock_dir="$1/.qwenvoice-package-store.lock"
    local lock_owner="" _
    [[ -z "$QVOICE_ACTIVE_PACKAGE_LOCK" ]] || {
        echo "error: nested shared SwiftPM store lock is not supported" >&2
        return 1
    }
    mkdir -p "$source_packages"
    for _ in {1..1500}; do
        if mkdir "$lock_dir" 2>/dev/null; then
            printf '%s\n' "$$" > "$lock_dir/pid"
            QVOICE_ACTIVE_PACKAGE_LOCK="$lock_dir"
            return 0
        fi
        lock_owner="$(cat "$lock_dir/pid" 2>/dev/null || true)"
        if [[ "$lock_owner" =~ ^[1-9][0-9]*$ ]] && ! kill -0 "$lock_owner" 2>/dev/null; then
            rm -rf "$lock_dir"
            continue
        fi
        sleep 0.2
    done
    echo "error: timed out waiting for shared SwiftPM store lock: $lock_dir" >&2
    return 1
}

release_package_store_lock() {
    [[ -z "$QVOICE_ACTIVE_PACKAGE_LOCK" ]] || rm -rf "$QVOICE_ACTIVE_PACKAGE_LOCK"
    QVOICE_ACTIVE_PACKAGE_LOCK=""
}

# Print sha256 of a file, or empty string if the file is missing.
sha256_of() {
    local path="$1"
    if [ -f "$path" ]; then
        /usr/bin/shasum -a 256 "$path" | awk '{print $1}'
    fi
}

# Skip the XcodeGen regeneration step when project.yml hasn't changed
# since the project was last generated. On cache miss, run
# regenerate_project.sh (which also runs check_project_inputs.sh).
ensure_project_regenerated() {
    mkdir -p "$BUILD_CACHE_DIR"
    local cache_file="$BUILD_CACHE_DIR/project.yml.sha256"
    local current
    current="$(sha256_of "$PROJECT_YML")"
    if [ -z "$current" ]; then
        echo "error: project.yml not found at $PROJECT_YML" >&2
        return 1
    fi

    local cached=""
    if [ -f "$cache_file" ]; then
        cached="$(cat "$cache_file" 2>/dev/null || true)"
    fi

    if [ -d "$PROJECT_FILE" ] && [ "$current" = "$cached" ]; then
        echo "==> project.yml unchanged; skipping XcodeGen"
        python3 "$ROOT_DIR/scripts/generate_cli_scheme.py" --check >/dev/null \
            || python3 "$ROOT_DIR/scripts/generate_cli_scheme.py"
        return 0
    fi

    echo "==> Regenerating Xcode project (project.yml changed or project missing)..."
    bash "$ROOT_DIR/scripts/regenerate_project.sh"
    printf '%s\n' "$current" > "$cache_file"
}

# Skip `xcodebuild -resolvePackageDependencies` only when the shared checkout,
# lockfile, Xcode toolchain, and destination used to create it still match.
# Resolution is serialized because every local lane consumes the same store.
#
# Args:
#   $1 = derived-data path (required)
#   $2 = shared cloned-source-packages directory (required)
#   $3 = producer context recorded for diagnostics (e.g. "dev", "release")
#   $4 = scheme whose package graph is being resolved (required)
#   $5 = configuration (required)
#   $6 = resolution destination (required)
ensure_spm_resolved() {
    local derived_data="${1:-}"
    local source_packages="${2:-}"
    local context="${3:-}"
    local scheme="${4:-}"
    local configuration="${5:-}"
    local destination="${6:-}"

    if [ -z "$derived_data" ] || [ -z "$source_packages" ] || [ -z "$context" ] \
        || [ -z "$scheme" ] || [ -z "$configuration" ] || [ -z "$destination" ]; then
        echo "error: ensure_spm_resolved requires <derived-data>, <source-packages>, <context>, <scheme>, <configuration>, and <destination>" >&2
        return 1
    fi

    # Fail before creating cache paths or resolving packages. `-showsdks`
    # alone is insufficient: Xcode may list iphoneos while the matching
    # component needed by generic/platform=iOS is absent.
    if [[ "$destination" == *"platform=iOS"* ]]; then
        require_ios_xcode_platform || return 1
    fi

    mkdir -p "$BUILD_CACHE_DIR" "$source_packages"
    # Pre-policy resolver stamps were context-only and could incorrectly let an
    # iOS lane reuse a macOS resolution. They are never consulted by this
    # scheme/configuration/destination-keyed implementation.
    rm -f "$BUILD_CACHE_DIR/swiftpm-resolution.json" \
        "$BUILD_CACHE_DIR"/Package.resolved.sha256.*
    local resolution_key="" cache_file=""
    resolution_key="$(printf '%s\n%s\n%s\n' "$scheme" "$configuration" "$destination" \
        | /usr/bin/shasum -a 256 | awk '{print substr($1, 1, 16)}')"
    cache_file="$BUILD_CACHE_DIR/swiftpm-resolution-$resolution_key.json"
    local current="" xcode_version="" fingerprint=""
    if [ -f "$PROJECT_RESOLVED" ]; then
        current="$(sha256_of "$PROJECT_RESOLVED")"
    fi
    [ -n "$current" ] || {
        echo "error: Package.resolved is missing or unreadable: $PROJECT_RESOLVED" >&2
        return 1
    }
    xcode_version="$(xcodebuild -version 2>/dev/null)" || {
        echo "error: xcodebuild is unavailable" >&2
        return 1
    }
    fingerprint="$(printf '%s\n%s\n%s\n%s\n%s\n%s\n' \
        "$current" "$xcode_version" "$source_packages" \
        "$scheme" "$configuration" "$destination" \
        | /usr/bin/shasum -a 256 | awk '{print $1}')"

    local store_present=0
    if [ -d "$source_packages/checkouts" ] \
        && find "$source_packages/checkouts" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null \
            | grep -q .; then
        store_present=1
    fi
    if (( store_present )) && python3 - "$cache_file" "$fingerprint" <<'PY'
import json
import sys

try:
    payload = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(1)
raise SystemExit(0 if payload.get("fingerprint") == sys.argv[2] else 1)
PY
    then
        echo "==> Shared Swift packages match lockfile/toolchain; skipping SPM resolve ($context)"
        write_build_provenance "$source_packages/last-build.json" \
            "SwiftPM resolution ($context)" "$scheme" "$configuration" "$destination" arm64 \
            none unsigned "$derived_data" "$source_packages"
        return 0
    fi

    acquire_package_store_lock "$source_packages" || return 1

    # Another waiter may have completed the same resolve while this process was
    # blocked. Recheck under the lock before invoking Xcode.
    store_present=0
    if [ -d "$source_packages/checkouts" ] \
        && find "$source_packages/checkouts" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null \
            | grep -q .; then
        store_present=1
    fi
    if (( store_present )) && python3 - "$cache_file" "$fingerprint" <<'PY'
import json
import sys

try:
    payload = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(1)
raise SystemExit(0 if payload.get("fingerprint") == sys.argv[2] else 1)
PY
    then
        release_package_store_lock
        echo "==> Shared Swift packages were resolved by another process ($context)"
        write_build_provenance "$source_packages/last-build.json" \
            "SwiftPM resolution ($context)" "$scheme" "$configuration" "$destination" arm64 \
            none unsigned "$derived_data" "$source_packages"
        return 0
    fi

    echo "==> Resolving shared Swift packages for '$context'..."
    local args=(
        -project "$PROJECT_FILE"
        -scheme "$scheme"
        -configuration "$configuration"
        -destination "$destination"
        -derivedDataPath "$derived_data"
        -clonedSourcePackagesDirPath "$source_packages"
        -disableAutomaticPackageResolution
        -onlyUsePackageVersionsFromResolvedFile
        -resolvePackageDependencies
    )
    if ! xcodebuild "${args[@]}"; then
        release_package_store_lock
        return 1
    fi
    if [ ! -d "$source_packages/checkouts" ] \
        || ! find "$source_packages/checkouts" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null \
            | grep -q .; then
        echo "error: Xcode reported a successful resolve but the shared checkout store is empty" >&2
        release_package_store_lock
        return 1
    fi

    local temp_cache="$cache_file.tmp.$$"
    if ! python3 - "$temp_cache" "$fingerprint" "$current" "$xcode_version" \
        "$source_packages" "$derived_data" "$scheme" "$configuration" \
        "$destination" "$context" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

path = sys.argv[1]
payload = {
    "schemaVersion": 1,
    "fingerprint": sys.argv[2],
    "packageResolvedSHA256": sys.argv[3],
    "xcodeVersion": sys.argv[4],
    "sourcePackagesPath": sys.argv[5],
    "resolutionDerivedDataPath": sys.argv[6],
    "scheme": sys.argv[7],
    "configuration": sys.argv[8],
    "destination": sys.argv[9],
    "context": sys.argv[10],
    "storePresent": True,
    "resolvedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
    then
        rm -f "$temp_cache"
        release_package_store_lock
        return 1
    fi
    if ! mv "$temp_cache" "$cache_file"; then
        rm -f "$temp_cache"
        release_package_store_lock
        return 1
    fi
    release_package_store_lock
    write_build_provenance "$source_packages/last-build.json" \
        "SwiftPM resolution ($context)" "$scheme" "$configuration" "$destination" arm64 \
        none unsigned "$derived_data" "$source_packages"
}

# Atomically record which owned invocation most recently populated a build root.
# All paths are stored relative to the checkout so the untracked stamp is useful
# without exposing a username or workstation path.
write_build_provenance() {
    local output="$1" producer="$2" scheme="$3" configuration="$4"
    local destination="$5" architecture="$6" optimization="$7" signing="$8"
    local derived_data="$9" source_packages="${10}"
    mkdir -p "$(dirname "$output")"
    python3 - "$output" "$ROOT_DIR" "$producer" "$scheme" "$configuration" \
        "$destination" "$architecture" "$optimization" "$signing" \
        "$derived_data" "$source_packages" <<'PY'
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

output = Path(sys.argv[1])
root = Path(sys.argv[2]).resolve()

def relative(value: str) -> str:
    return Path(value).resolve().relative_to(root).as_posix()

try:
    git_sha = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
except (OSError, subprocess.CalledProcessError):
    git_sha = "unknown"
try:
    xcode_version = subprocess.check_output(
        ["xcodebuild", "-version"], text=True, stderr=subprocess.DEVNULL,
    ).strip()
except (OSError, subprocess.CalledProcessError):
    xcode_version = "unknown"

payload = {
    "schemaVersion": 1,
    "producer": sys.argv[3],
    "status": "passed",
    "platform": (
        "ios"
        if "iOS" in sys.argv[6] or "iOS" in sys.argv[4]
        else "macos"
    ),
    "scheme": sys.argv[4],
    "configuration": sys.argv[5],
    "destination": sys.argv[6],
    "architecture": sys.argv[7],
    "optimization": sys.argv[8],
    "signing": sys.argv[9],
    "derivedDataPath": relative(sys.argv[10]),
    "sourcePackagesPath": relative(sys.argv[11]),
    "gitRevision": git_sha,
    "xcodeVersion": xcode_version,
    "finishedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}
temporary = output.with_name(output.name + f".tmp.{os.getpid()}")
temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(temporary, output)
PY
}

copy_tree_clone_first() {
    local source="$1" destination="$2"
    rm -rf "$destination"
    mkdir -p "$(dirname "$destination")"
    if cp -cR "$source" "$destination" 2>/dev/null; then
        return 0
    fi
    rm -rf "$destination"
    cp -R "$source" "$destination"
}

validate_dsym_uuid() {
    local binary="$1" dsym="$2" label="$3"
    [[ -f "$binary" ]] || { echo "error: $label binary is missing: $binary" >&2; return 1; }
    [[ -d "$dsym" ]] || { echo "error: $label dSYM is missing: $dsym" >&2; return 1; }
    local binary_uuids dsym_uuids uuid
    binary_uuids="$(xcrun dwarfdump --uuid "$binary" 2>/dev/null | awk '{print $2}' | sort -u)"
    dsym_uuids="$(xcrun dwarfdump --uuid "$dsym" 2>/dev/null | awk '{print $2}' | sort -u)"
    [[ -n "$binary_uuids" && -n "$dsym_uuids" ]] \
        || { echo "error: could not read $label Mach-O/dSYM UUIDs" >&2; return 1; }
    while IFS= read -r uuid; do
        [[ -n "$uuid" ]] || continue
        grep -qx "$uuid" <<<"$dsym_uuids" \
            || { echo "error: $label dSYM UUID does not match binary UUID $uuid" >&2; return 1; }
    done <<<"$binary_uuids"
}

assert_macho_arm64_only() {
    local binary="$1" label="$2" architectures=""
    [[ -f "$binary" ]] || { echo "error: $label is missing: $binary" >&2; return 1; }
    architectures="$(/usr/bin/lipo -archs "$binary" 2>/dev/null || true)"
    [[ "$architectures" == "arm64" ]] || {
        echo "error: $label must be arm64-only (found: ${architectures:-unknown})" >&2
        return 1
    }
}

assert_macos_bundle_arm64_only() {
    local app_bundle="$1" candidate
    assert_macho_arm64_only "$app_bundle/Contents/MacOS/Vocello" "Vocello executable" || return 1
    assert_macho_arm64_only \
        "$app_bundle/Contents/XPCServices/QwenVoiceEngineService.xpc/Contents/MacOS/QwenVoiceEngineService" \
        "QwenVoiceEngineService executable" || return 1
    while IFS= read -r -d '' candidate; do
        /usr/bin/file -b "$candidate" 2>/dev/null | grep -q 'Mach-O' || continue
        assert_macho_arm64_only "$candidate" "embedded Mach-O ${candidate#"$app_bundle"/}" || return 1
    done < <(find \
        "$app_bundle/Contents/MacOS" \
        "$app_bundle/Contents/XPCServices" \
        "$app_bundle/Contents/Frameworks" \
        -type f -print0 2>/dev/null)
}

# SwiftPM precompiled modules embed the absolute module-cache path. A one-time
# policy migration can therefore preserve package checkouts but must invalidate
# path-bound build products before the relocated scratch is reused.
ensure_swiftpm_scratch_location() {
    local package_path="$1" scratch_path="$2"
    local marker="$scratch_path/.qvoice-scratch-location-v1"
    local expected="$scratch_path" recorded="" temporary=""
    mkdir -p "$scratch_path"
    [[ ! -f "$marker" ]] || IFS= read -r recorded < "$marker" || true
    if [[ "$recorded" != "$expected" ]] \
        && find "$scratch_path" -mindepth 1 -maxdepth 1 -type d \
            \( -name '*-apple-*' -o -name debug -o -name release \) \
            -print -quit | grep -q .; then
        echo "==> Invalidating relocated SwiftPM build products in $scratch_path"
        swift package --package-path "$package_path" --scratch-path "$scratch_path" clean \
            || { echo "error: could not clean relocated SwiftPM scratch: $scratch_path" >&2; return 1; }
    fi
    temporary="$marker.tmp.$$"
    printf '%s\n' "$expected" > "$temporary"
    mv "$temporary" "$marker"
}

# Preserve only the current app and XPC-service symbols. Test/CLI dSYMs are
# reproducible and no longer consume the durable crash-symbolication budget.
preserve_macos_dsyms() {
    local products="$1" app_bundle="$2" destination="$3"
    local temporary="$destination.tmp.$$"
    local app_dsym="$products/Vocello.app.dSYM"
    local xpc_dsym="$products/QwenVoiceEngineService.xpc.dSYM"
    local app_binary="$app_bundle/Contents/MacOS/Vocello"
    local xpc_binary="$app_bundle/Contents/XPCServices/QwenVoiceEngineService.xpc/Contents/MacOS/QwenVoiceEngineService"
    validate_dsym_uuid "$app_binary" "$app_dsym" "Vocello" || return 1
    validate_dsym_uuid "$xpc_binary" "$xpc_dsym" "QwenVoiceEngineService" || return 1
    rm -rf "$temporary"
    mkdir -p "$temporary"
    copy_tree_clone_first "$app_dsym" "$temporary/Vocello.app.dSYM" \
        || { rm -rf "$temporary"; return 1; }
    copy_tree_clone_first "$xpc_dsym" "$temporary/QwenVoiceEngineService.xpc.dSYM" \
        || { rm -rf "$temporary"; return 1; }
    validate_dsym_uuid "$app_binary" "$temporary/Vocello.app.dSYM" "preserved Vocello" \
        || { rm -rf "$temporary"; return 1; }
    validate_dsym_uuid "$xpc_binary" "$temporary/QwenVoiceEngineService.xpc.dSYM" "preserved QwenVoiceEngineService" \
        || { rm -rf "$temporary"; return 1; }
    /usr/libexec/PlistBuddy -c "Print :CFBundleVersion" "$app_bundle/Contents/Info.plist" \
        > "$temporary/build-version.txt" 2>/dev/null || true
    rm -rf "$destination"
    mv "$temporary" "$destination"
    echo "==> Preserved current app/XPC dSYMs → $destination"
}

# Preserve exactly the dSYM matching the current physical-device iOS product.
# The pending clone is UUID-validated before it replaces the previous symbol
# set, so interrupted copies and stale builds cannot poison crash evidence.
preserve_ios_dsym() {
    local source="$1" destination="$2" binary="$3"
    local pending="${destination%.dSYM}.pending.$$.dSYM"
    validate_dsym_uuid "$binary" "$source" "iOS Vocello" || return 1
    rm -rf "$pending"
    mkdir -p "$(dirname "$destination")"
    copy_tree_clone_first "$source" "$pending" || { rm -rf "$pending"; return 1; }
    validate_dsym_uuid "$binary" "$pending" "preserved iOS Vocello" \
        || { rm -rf "$pending"; return 1; }
    rm -rf "$destination"
    mv "$pending" "$destination"
    echo "==> Preserved current iOS dSYM → $destination"
}

# Gracefully terminate Vocello if it's running. SIGTERM, poll ~10s, then
# SIGKILL fallback. This helper is used only by build-cache maintenance;
# explicit UI acceptance owns its exact test-host process separately.
quit_app_if_running() {
    if ! pgrep -x Vocello >/dev/null 2>&1; then
        return 0
    fi
    echo "==> Quitting running Vocello before cleanup"
    pkill -x Vocello >/dev/null 2>&1 || true
    for _ in {1..40}; do
        if ! pgrep -x Vocello >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.25
    done
    pkill -9 -x Vocello >/dev/null 2>&1 || true
    sleep 0.5
}

# Normal build completion is intentionally non-destructive. The policy-aware
# cleanup entrypoint owns scratch/evidence/cache retention; a build must never
# delete publication-repair evidence or distribution output as a side effect.
prune_stale_builds() {
    warn_if_storage_bloated
}

# Fail before a heavy build/test lane creates another partial cache or result
# tree. Thresholds and bounded cleanup guidance are owned by the checked-in
# build-output policy; callers pass only the stable lane identifier.
require_build_free_space() {
    local lane="${1:-}"
    [ -n "$lane" ] || {
        echo "error: require_build_free_space needs a governed lane identifier" >&2
        return 2
    }
    python3 "$ROOT_DIR/scripts/lib/storage_preflight.py" check \
        --root "$ROOT_DIR" --lane "$lane" >/dev/null
}

# Print a one-line reclaim hint if <dir> exceeds <limit_gb>. Advisory only; uses
# stat-based `du -sk` (fast) and is a no-op when the dir is absent.
_storage_warn_dir() {
    local path="$1" limit_gb="$2" label="$3" flag="${4:-}"
    [ -d "$path" ] || return 0
    # Parse `du -sk` with the `read` builtin (no awk/cut dependency on the hot path).
    local kb _rest limit_kb gb
    read -r kb _rest < <(du -sk "$path" 2>/dev/null) || true
    [ -n "${kb:-}" ] || return 0
    case "$kb" in ''|*[!0-9]*) return 0 ;; esac
    limit_kb=$(( limit_gb * 1024 * 1024 ))
    if [ "$kb" -gt "$limit_kb" ]; then
        gb=$(( kb / 1048576 ))
        echo "==> [storage] ${label} is ~${gb} GB (>${limit_gb} GB)" >&2
        [[ "$label" != "build/" ]] \
            || echo "==> [storage] inspect governed ownership: python3 scripts/build_output_policy.py status" >&2
        [[ -z "$flag" ]] \
            || echo "==> [storage] bounded reclaim: scripts/clean_build_caches.sh ${flag}" >&2
        # `--routine` is deliberately non-destructive: caches are aggressive-class
        # and artifacts are governed or preserved, so it reclaims almost nothing at
        # exactly the moment this warning fires. On 2026-08-02 it planned 692 KB
        # against a 20.8 GB tree. Name the modes that actually free space, or the
        # advice sends the reader to the one option that cannot help.
        if [[ "$label" == "build/" ]]; then
            echo "==> [storage] most of build/ is rebuildable Xcode/SwiftPM cache; free it with:" >&2
            echo "==>           scripts/clean_build_caches.sh --cache macos|ios   (one cache, keeps the other)" >&2
            echo "==>           scripts/clean_build_caches.sh --aggressive        (every cache)" >&2
            echo "==>           both rebuild on the next build; --routine will not touch them" >&2
        fi
    fi
}

# Non-fatal advisory called after every build: warn when reclaimable storage crosses
# a soft threshold (the project build/ tree, or the dev model cache). NEVER deletes,
# NEVER blocks. Thresholds (GB) overridable via env: QWENVOICE_BUILD_WARN_GB,
# QWENVOICE_MODELS_WARN_GB.
warn_if_storage_bloated() {
    _storage_warn_dir "$ROOT_DIR/build" "${QWENVOICE_BUILD_WARN_GB:-12}" "build/" "--routine"
    _storage_warn_dir "$HOME/Library/Application Support/QwenVoice-Debug/models" \
        "${QWENVOICE_MODELS_WARN_GB:-10}" "QwenVoice-Debug/models" "--models"
}

# Run xcodebuild, piping output through xcbeautify when it's on PATH and
# stdout is a terminal. Preserves xcodebuild's exit code in both cases.
#
# -skipPackagePluginValidation is passed unconditionally (reviewed with the
# mlx-swift 0.31.6 keep decision): mlx-swift >=0.31 ships a CudaBuild
# build-tool plugin whose interactive Xcode fingerprint approval cannot happen
# on headless invocations, and the plugin is inert on Darwin. Supply-chain
# identity does not rest on that fingerprint here: every package is
# exact-version pinned with lockstep-checked resolved files, and external
# Actions/tools use SHA pins per config/toolchain.json. Revisit if a pinned
# dependency ever ships a plugin that must execute on Darwin.
xcb_run() {
    acquire_package_store_lock "$QVOICE_XCODE_SOURCE_PACKAGES" || return 1
    local status=0
    local -a extra_args=(-skipPackagePluginValidation)
    if command -v xcbeautify >/dev/null 2>&1 && [ -t 1 ]; then
        set -o pipefail
        xcodebuild "$@" "${extra_args[@]}" | xcbeautify --renderer terminal || status=${PIPESTATUS[0]}
        set +o pipefail
    else
        xcodebuild "$@" "${extra_args[@]}" || status=$?
    fi
    release_package_store_lock
    return "$status"
}
