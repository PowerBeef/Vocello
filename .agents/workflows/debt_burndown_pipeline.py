"""Bounded parallel debt-burndown workflow in isolated `share` worktrees.

Spawns at most 3 editing workers concurrently (respecting Vocello's 4-agent-total
cap including the lead) on strictly disjoint file buckets. Each worker runs in
`workspace="share"` on the inherited model, runs only deterministic Python/lint
checks (never native builds, devices, models, or roadmap edits), commits on its
own worktree branch, and reports back its branch and commit SHA for the lead to
cherry-pick and validate warm on `main`.

Args (JSON object):
  - buckets (list[dict], required): up to 3 items, each with:
      - name (str): short lowercase label (e.g. "ruff-hooks", "pyright-ci")
      - files (list[str]): explicit disjoint relative file paths owned by this bucket
      - goal (str): concrete change + verification instructions
      - tests (list[str], optional): targeted pytest paths to run inside the worktree
"""

buckets = list(args.get("buckets") or [])
if not buckets:
    raise ValueError("Args must include a non-empty 'buckets' list.")
if len(buckets) > 3:
    raise ValueError("Vocello hard boundary: at most 3 concurrent editing workers (4 agents total including lead).")

seen_files = set()
for bucket in buckets:
    files = [str(f).strip() for f in (bucket.get("files") or []) if str(f).strip()]
    if not files:
        raise ValueError(f"Bucket {bucket.get('name')!r} must declare explicit 'files'.")
    overlap = seen_files & set(files)
    if overlap:
        raise ValueError(f"Buckets must own disjoint file sets; overlap found: {sorted(overlap)}")
    seen_files.update(files)

WORKER_SCHEMA = {
    "type": "object",
    "properties": {
        "bucket": {"type": "string"},
        "branch": {"type": "string"},
        "commit_sha": {"type": "string"},
        "files_changed": {"type": "array", "items": {"type": "string"}},
        "checks_run": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["bucket", "branch", "commit_sha", "files_changed", "checks_run"],
}

phase("Run Disjoint Share-Worktree Workers")


def make_worker(bucket):
    name = str(bucket.get("name") or "worker")
    files = [str(f) for f in bucket["files"]]
    goal = str(bucket.get("goal") or "")
    tests = [str(t) for t in (bucket.get("tests") or [])]
    tests_line = (
        f"Run targeted deterministic tests: `scripts/dev.sh py {' '.join(tests)}` and `scripts/dev.sh lint`."
        if tests
        else "Run `scripts/dev.sh lint` and any targeted `scripts/dev.sh py ...` tests for your edited files."
    )
    prompt = (
        f"You own bucket `{name}` in an isolated linked worktree (`workspace='share'`).\n\n"
        f"Owned files (edit ONLY these paths):\n"
        + "\n".join(f"- {f}" for f in files)
        + f"\n\nGoal:\n{goal}\n\n"
        "Strict Vocello worker boundaries:\n"
        "- Edit ONLY the owned files listed above.\n"
        "- NEVER edit config/roadmap.json, config/roadmap-archive.json, docs/ROADMAP.md, or docs/development-progress.md.\n"
        "- NEVER run native Xcode/SwiftPM builds, tests, devices, models, or measured lanes.\n"
        "- NEVER push, stash, or broadly stage (`git add -A` / `git add .`).\n"
        f"- {tests_line}\n"
        "- Stage explicit file paths and make one clean commit on your worktree branch (no AI co-author trailers).\n"
        "- Return your worktree branch name, commit SHA (`git rev-parse HEAD`), changed files, and checks run."
    )
    return agent(
        prompt,
        schema=WORKER_SCHEMA,
        role=f"Burndown: {name}",
        type_name="self",
        workspace="share",
        model="inherit",
    )


results = await parallel(buckets, make_worker)

phase("Integration Handoff")

print("WORKER COMMITS READY FOR LEAD INTEGRATION:")
for res in results:
    log(f"[{res['bucket']}] {res['branch']} @ {res['commit_sha']} ({len(res['files_changed'])} files)")
    print(f"- {res['bucket']}: branch={res['branch']} commit={res['commit_sha']}")
    print(f"  files: {', '.join(res['files_changed'])}")
    print(f"  checks: {', '.join(res['checks_run'])}")
    if res.get("notes"):
        print(f"  notes: {res['notes']}")
print("\nLead next steps: inspect diffs, `git cherry-pick` onto `main`, validate warm on `main`, then remove worktrees and branches.")
