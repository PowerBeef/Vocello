# Shared shell helpers for QwenVoice / Vocello release-verification scripts.
#
# Usage (from another script):
#
#   SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
#   MATRIX_PATH="${MATRIX_PATH:-$SCRIPT_DIR/../config/apple-platform-capability-matrix.json}"
#   . "$SCRIPT_DIR/lib/shared.sh"
#
# Callers must export or set `MATRIX_PATH` before sourcing this file. The
# helpers use `python3` for JSON parsing so the rest of the script can stay
# portable shell.
#
# This file is Tier 2.7: the three release-verification scripts previously
# embedded near-identical copies of matrix_read / plist_read / fail. Changing
# this file updates all callers at once.

# shellcheck shell=bash

# Quick fatal helper. Keeps stderr clean and uses an exit code that upstream
# CI can recognize.
fail() {
    echo "Error: $*" >&2
    exit 1
}

# Read a scalar or array from a plist file. Empty lines are suppressed. Non-
# existent keys print nothing and return success (consistent with the
# embedded copies this replaces).
plist_read() {
    local plist_path="$1"
    local key="$2"
    /usr/libexec/PlistBuddy -c "Print :$key" "$plist_path" 2>/dev/null
}

# Read a value from the apple-platform capability matrix. `selector` is a
# slash-separated path into the JSON tree, e.g. `macOS/app/bundleIdentifier`
# or `iOS/app/applicationGroups`. Lists print one item per line; scalars
# print a single line.
#
# The caller must have set `MATRIX_PATH` before invoking this helper.
matrix_read() {
    local selector="$1"
    if [ -z "${MATRIX_PATH:-}" ]; then
        fail "matrix_read: MATRIX_PATH is unset"
    fi
    MATRIX_PATH="$MATRIX_PATH" MATRIX_SELECTOR="$selector" python3 - <<'PY'
import json
import os
from pathlib import Path

data = json.loads(Path(os.environ["MATRIX_PATH"]).read_text())
value = data
for part in os.environ["MATRIX_SELECTOR"].split("/"):
    value = value[part]

if isinstance(value, bool):
    print("true" if value else "false")
elif isinstance(value, list):
    for item in value:
        print(item)
else:
    print(value)
PY
}


# --- Lane helpers shared by macos_test.sh, ui_test.sh and ios_device.sh -----------------
# Coloured progress lines on stderr; `die` exits 1. Byte-identical to the copies the
# three lane scripts carried until 2026-09-12.
note() { printf '\033[0;36m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[0;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

# `--label` values are opaque record identifiers, never free text.
validate_benchmark_label() {
  local value="$1"
  [[ -z "$value" || "$value" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$ ]] \
    || die "--label must be an opaque 1-96 character ID using letters, digits, dot, underscore, or hyphen"
}

benchmark_nonce() {
  python3 -c 'import secrets; print(secrets.token_hex(4))'
}

# QC v2 (scripts/qc.py) runs under the interpreter scripts/select_python.py picks, which
# honours VOCELLO_PYTHON, never under whichever python3 the shell finds first: that one
# can lack numpy, which turned every QC v2 score into an error (BKL-17). A lane calls
# this before it generates, so a missing dependency fails the lane at once; it sets
# QC_PYTHON.
require_qc_python() {
  local scripts_dir selected
  scripts_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  selected="$(python3 "$scripts_dir/select_python.py")" \
    || die "QC v2: no repository Python was found (scripts/select_python.py); set VOCELLO_PYTHON"
  "$selected" -c 'import numpy' >/dev/null 2>&1 \
    || die "QC v2: $selected cannot import numpy; install the pinned packages (config/toolchain.json) or set VOCELLO_PYTHON"
  # shellcheck disable=SC2034  # read by the lane script that sourced this file
  QC_PYTHON="$selected"
}

# Publish one qualified artifact directory into benchmarks/runs; the evidence is
# preserved and the exact repair command printed when publication fails.
record_benchmark_history() {
  local artifacts="$1"
  local scripts_dir
  scripts_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  python3 "$scripts_dir/benchmark_history.py" record --artifact-dir "$artifacts" || {
    warn "benchmark passed, but history publication failed; evidence is preserved in $artifacts"
    warn "repair: python3 scripts/benchmark_history.py record --artifact-dir '$artifacts'"
    return 1
  }
}
