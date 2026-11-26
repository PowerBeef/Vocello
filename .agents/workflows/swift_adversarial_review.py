"""Adversarial 3-lens Swift review workflow for Vocello.

Reads the exact git diff in Python (giving the shell-free `vocello-swift-review`
subagent complete diff visibility) and fans out three read-only reviewers in
parallel:
  1. `vocello-swift-review` (Vocello runtime, persistence, privacy, UI boundaries)
  2. Apple / Swift 6 / SDK verifier (`axiom` + `sosumi` MCP tools, read-only)
  3. Privacy, concurrency-registry & release-only policy sweep (`flash` tier)

Args (JSON object):
  - base_ref (str, optional): git ref to diff against (default: "HEAD" for dirty
    working tree, or e.g. "origin/main" / "<sha>~1" for committed changes).
  - files (list[str], optional): explicit Swift file paths to scope the review.
"""

from pathlib import Path
import subprocess

ROOT = Path(WORKSPACES[0]) if WORKSPACES else Path.cwd()
base_ref = str(args.get("base_ref") or "HEAD")
explicit_files = [str(f) for f in (args.get("files") or [])]

phase("Collect Swift Diff")


def _run_git(git_args):
    res = subprocess.run(
        ["git", "-C", str(ROOT), *git_args],
        capture_output=True,
        text=True,
        check=False,
    )
    return res.stdout if res.returncode == 0 else ""


if explicit_files:
    swift_files = [f for f in explicit_files if f.endswith(".swift")]
else:
    if base_ref == "HEAD":
        changed = _run_git(["diff", "--name-only", "HEAD", "--", "Sources", "Tests", "Packages"])
        untracked = _run_git(["ls-files", "--others", "--exclude-standard", "--", "Sources", "Tests", "Packages"])
        raw_files = changed.splitlines() + untracked.splitlines()
    else:
        raw_files = _run_git(["diff", "--name-only", f"{base_ref}..HEAD", "--", "Sources", "Tests", "Packages"]).splitlines()
    swift_files = sorted({f.strip() for f in raw_files if f.strip().endswith(".swift")})

if not swift_files:
    log("No Swift files found to review.")
    print("RESULT: no Swift files changed.")
    raise SystemExit(0)

diff_cmd = (
    ["diff", "HEAD", "--", *swift_files]
    if base_ref == "HEAD"
    else ["diff", f"{base_ref}..HEAD", "--", *swift_files]
)
diff_text = _run_git(diff_cmd)
MAX_DIFF_CHARS = 48000
if len(diff_text) > MAX_DIFF_CHARS:
    diff_text = diff_text[:MAX_DIFF_CHARS] + "\n... [diff truncated; inspect individual files with read_file] ...\n"

log(f"Reviewing {len(swift_files)} Swift file(s) against {base_ref}: {', '.join(swift_files)}")

FINDING_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "CHANGES_REQUIRED", "BLOCKER"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["blocker", "high", "medium", "low"]},
                    "file": {"type": "string"},
                    "line": {"type": "string"},
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["severity", "file", "title", "detail"],
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["verdict", "findings", "summary"],
}

phase("Parallel Adversarial Review")

lenses = [
    {
        "name": "vocello-swift-review",
        "role": "Vocello Swift Reviewer",
        "type_name": "vocello-swift-review",
        "model": "inherit",
        "prompt": (
            "Read-only review — edit nothing. Review these Vocello Swift changes against "
            "AGENTS.md, docs/reference/native-engineering.md, and Vocello runtime, concurrency, "
            "GRDB persistence, StoreKit, privacy, and UI boundaries. Read any full file you need "
            "with read_file.\n\n"
            f"Changed Swift files ({len(swift_files)}):\n"
            + "\n".join(f"- {f}" for f in swift_files)
            + f"\n\nDiff against {base_ref}:\n```diff\n{diff_text}\n```"
        ),
    },
    {
        "name": "apple-sdk-axiom",
        "role": "Apple SDK & Concurrency Auditor",
        "type_name": "self",
        "model": "inherit",
        "prompt": (
            "Read-only review — edit nothing, run no builds or shell commands. "
            "Audit these Swift 6 / macOS 26 / iOS 26 changes for Swift concurrency safety "
            "(strict memory safety, NonisolatedNonsendingByDefault, InferIsolatedConformances, "
            "MemberImportVisibility), SwiftUI/Liquid Glass lifecycle pitfalls, and Apple SDK misuse. "
            "Use `axiom` MCP (`axiom_search_skills`, `axiom_read_skill`) and `sosumi` MCP "
            "(`searchAppleDocumentation`) where an Apple API contract or Swift 6 rule is relevant.\n\n"
            f"Changed Swift files ({len(swift_files)}):\n"
            + "\n".join(f"- {f}" for f in swift_files)
            + f"\n\nDiff against {base_ref}:\n```diff\n{diff_text}\n```"
        ),
    },
    {
        "name": "privacy-release-policy",
        "role": "Privacy & Release-Only Auditor",
        "type_name": "research",
        "model": "flash",
        "prompt": (
            "Read-only audit — edit nothing. Check these Swift changes for: "
            "(1) Release-only violations (any #if DEBUG, ungated debug knob missing "
            "VOCELLO_INTERNAL_DIAGNOSTICS / QWENVOICE_DEBUG=1, or Guideline 2.5.19 regressions "
            "leaking dormant iOS device/perf runners outside QVOICE_DEVICE_DIAGNOSTICS or "
            "shipping iOS QWENVOICE_* env-var reads), "
            "(2) Privacy leaks (prompts, transcripts, private host paths, credentials logged outside "
            "DiagnosticPrivacy), "
            "(3) Unregistered @unchecked Sendable / nonisolated(unsafe) missing from "
            "config/concurrency-safety.json, "
            "(4) Facade boundary leaks importing MLXAudio internals directly instead of VocelloQwen3Core.\n\n"
            f"Changed Swift files ({len(swift_files)}):\n"
            + "\n".join(f"- {f}" for f in swift_files)
            + f"\n\nDiff against {base_ref}:\n```diff\n{diff_text}\n```"
        ),
    },
]

results = await parallel(
    lenses,
    lambda lens: agent(
        lens["prompt"],
        schema=FINDING_SCHEMA,
        role=lens["role"],
        type_name=lens["type_name"],
        workspace="inherit",
        model=lens["model"],
    ),
)

phase("Synthesize Verdict")

worst = "PASS"
rank = {"PASS": 0, "CHANGES_REQUIRED": 1, "BLOCKER": 2}
all_findings = []
for lens, res in zip(lenses, results):
    verdict = res.get("verdict", "PASS")
    if rank.get(verdict, 0) > rank[worst]:
        worst = verdict
    log(f"[{lens['name']}] verdict={verdict} findings={len(res.get('findings', []))} — {res.get('summary', '')}")
    for f in res.get("findings", []):
        all_findings.append((lens["name"], f))

print(f"OVERALL VERDICT: {worst}")
print(f"FILES REVIEWED: {len(swift_files)}")
if all_findings:
    print("\nFINDINGS:")
    for lens_name, f in all_findings:
        loc = f"{f.get('file')}:{f.get('line')}" if f.get("line") else f.get("file", "")
        print(f"- [{f.get('severity', 'medium').upper()}] ({lens_name}) {loc} — {f.get('title')}: {f.get('detail')}")
        if f.get("fix"):
            print(f"  Suggested fix: {f['fix']}")
else:
    print("\nNo findings. Ready to record `--trailer 'Reviewed-by: vocello-swift-review'`.")
