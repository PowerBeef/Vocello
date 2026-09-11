#!/usr/bin/env bash
# Claude Code PreToolUse hook (matcher: Edit|Write|MultiEdit|NotebookEdit).
#
# Reads `tool_input.file_path` and refuses (exit 2) direct edits of files the
# repository generates or freezes, naming the generator so the fix is one
# command away. Pinned historical or superseded documents are not blocked --
# a deliberate re-pin uses the same Edit tool -- but the hook asks for
# confirmation through the permission decision "ask" so an accidental edit of
# a pinned body is noticed before it happens.
#
# Path checks are plain `case` globs on the repository-relative path; the hook
# never reads git state and finishes in milliseconds.

set -euo pipefail

payload="$(cat 2>/dev/null || true)"
file_path="$(printf '%s' "$payload" \
  | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))
except Exception:
    print("")' 2>/dev/null || true)"

[[ -n "$file_path" ]] || exit 0

root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
relative="${file_path#"$root"/}"
relative="${relative#./}"

block() {
  echo "generated-file guard: BLOCKED — $relative is generated or frozen; do not hand-edit it." >&2
  echo "Regenerate it instead: $1" >&2
  exit 2
}

case "$relative" in
  docs/INDEX.md)
    block "python3 scripts/documentation_contract.py rebuild-index (or python3 scripts/refresh_derived_artifacts.py refresh)" ;;
  docs/INDEX.json)
    block "python3 scripts/doc_metadata.py rebuild-index (or python3 scripts/refresh_derived_artifacts.py refresh)" ;;
  docs/ROADMAP.md)
    block "edit config/roadmap.json, then python3 scripts/roadmap.py render" ;;
  docs/project-health.md)
    block "python3 scripts/project_health.py rebuild-summary" ;;
  config/derived-doc-facts.json)
    block "python3 scripts/doc_metadata.py derive-facts" ;;
  Sources/Resources/qwenvoice_production_model_catalog.json)
    block "edit config/model-artifact-receipts.json, then python3 scripts/model_catalog_contract.py rebuild" ;;
  docs/charts/*.svg)
    block "python3 scripts/generate_readme_charts.py" ;;
  benchmarks/HISTORY.md)
    block "python3 scripts/benchmark_history.py (regenerated from benchmarks/runs)" ;;
  benchmarks/runs/*)
    block "frozen evidence is never edited; publish a new record with scripts/publish_benchmark_history.py" ;;
  QwenVoice.xcodeproj/*)
    block "edit project.yml, then ./scripts/regenerate_project.sh --fast" ;;
  Packages/VocelloQwen3Core/CURRENT_INVENTORY.json)
    block "python3 scripts/vendor_runtime_contract.py rebuild-current-inventory" ;;
  Packages/VocelloQwen3Core/FACADE_API_BASELINE.json)
    block "python3 scripts/vendor_runtime_contract.py rebuild-facade-api-baseline" ;;
esac

# Pinned bodies: ask rather than block.
case "$relative" in
  docs/*.md|.claude/rules/*.md|benchmarks/*.md|design_references/*.md)
    if [[ -f "$root/$relative" ]] && head -n 12 "$root/$relative" | grep -Eq '^status: (historical|superseded)$'; then
      python3 - "$relative" <<'PY'
import json, sys
relative = sys.argv[1]
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": (
            f"{relative} is a pinned historical/superseded document (contentDigest). "
            "Editing its body requires re-pinning the digest (see /refresh-docs). Confirm this edit is deliberate."
        ),
    }
}))
PY
    fi
    ;;
esac

exit 0
