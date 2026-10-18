#!/usr/bin/env python3
"""Single source of truth for plans, their items, and their progress.

Progress used to live in six places -- a 481-line checkpoint, a tiered roadmap, a
prose status report, a stage-closure review, a measurements appendix, and one
machine-readable `phaseStatus` block -- under seven overlapping identifier
schemes (Stage, Tier, Phase, P, R, M, Gate). Only the JSON block was queryable,
so "what is in flight right now" could not be answered without reading four
documents and reconciling them by hand.

This file replaces the *state*; the narrative documents keep the reasoning and
cite it. Two levels, because work here genuinely runs several programs at once:

    plans   an adopted program with a goal and a lifecycle
    items   a unit of work belonging to exactly one plan

Verification has two halves, and the first is the one that matters.

ACCURACY -- does the cited evidence exist, and does it say what the item claims?
It is easy to build a tracker where `status: done` is a self-assertion. Here a
done item must cite evidence, and every reference is resolved against the
repository: a benchmark reference must name a record that exists *and* passed, a
commit must exist *and* be reachable from main, a doc reference must resolve
including its anchor. An item cannot claim completion by asserting it.

ANTI-STALENESS -- has reality moved since the claim was made? Items bind to the
sources they describe, exactly as documents do, and drift is reported. An
in-flight item that has not been touched in a long time is surfaced rather than
left to rot. A plan whose items are all finished but which is still marked
active is a contradiction and fails.

FOCUS -- is the work going where the maintainer decided it should? An optional
`focusLock` makes the primary plan the only place for planned or in-flight work,
caps how much of it is in flight, and makes moving the primary plan a recorded
decision instead of an edit. Its optional `freeze` requires every commit after
the freeze commit to name an item of that plan in its subject. An item's optional
`due` date is surfaced once it passes.

EDITING -- a roadmap change is one command, not a hand edit of a 200 KB JSON file.
Each editing command changes the data in memory, runs the same validation as
`validate` on the result, and only then writes config/roadmap.json,
config/roadmap-archive.json and docs/ROADMAP.md together, in the files' own format;
a result that fails validation writes nothing. `updated` moves with a status or
gate change and on close (evidence), never for a title, date, blocker or note
alone unless --touch asks for it.

Usage:
    python3 scripts/roadmap.py validate [--strict]
    python3 scripts/roadmap.py render [--check]
    python3 scripts/roadmap.py status [--plan ID] [--json]

    python3 scripts/roadmap.py set ID [--status planned|in-flight|parked] [--due YYYY-MM-DD|none]
        [--title T] [--gate G] [--blocked-by ID,ID|none] [--unpark-when TEXT|none] [--touch]
    python3 scripts/roadmap.py note ID TEXT | --append TEXT  [--touch]
    python3 scripts/roadmap.py close ID [--status done|declined|superseded] [--superseded-by ID]
        [--evidence KIND:VALUE ...] [--reason TEXT] [--note TEXT]

    Every editing command also takes --dry-run (print the unified diff, write
    nothing), --date YYYY-MM-DD (the date written to `updated` and validated
    against; default today) and --root DIR (default: this checkout). Notes stay
    within 1200 characters and are never truncated. close moves the item to the
    end of the archive; done needs evidence, declined a reason, and superseded a
    winner, which lists the closed id in its legacyIds.
"""
from __future__ import annotations

import argparse
import copy
import datetime as _dt
import difflib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ROADMAP_PATH = "config/roadmap.json"
ARCHIVE_PATH = "config/roadmap-archive.json"
RENDER_PATH = "docs/ROADMAP.md"

PLAN_STATUSES = ("active", "complete", "parked", "superseded")
ITEM_STATUSES = ("planned", "in-flight", "done", "declined", "parked", "superseded")
TERMINAL = ("done", "declined", "superseded")
OWNERS = ("backend-mlx", "release-qa", "ios", "macos", "backend-and-platform")

# An in-flight item untouched for this long is surfaced. Not a failure: real work
# stalls for real reasons. Silence is the problem, not slowness. Two weeks: the
# September 2026 drift hid twelve idle items behind the previous 21-day window.
IN_FLIGHT_STALE_DAYS = 14
# Notes state the current position; history lives in git. Longer notes read as
# narrative and stop being checked.
NOTES_MAX_CHARS = 1200
LIVE_STATUSES = ("planned", "in-flight")
SHA = re.compile(r"[0-9a-f]{7,40}")


class RoadmapError(RuntimeError):
    """The roadmap file itself could not be read as a roadmap."""


def load(root: pathlib.Path) -> dict:
    path = root / ROADMAP_PATH
    if not path.exists():
        raise RoadmapError(f"missing {ROADMAP_PATH}")
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("plans", "items"):
        if not isinstance(data.get(key), list):
            raise RoadmapError(f"{ROADMAP_PATH}.{key} must be a list")
    return data


def load_archive(root: pathlib.Path) -> dict:
    """Finished work, counted toward progress. `validate_archive` checks its done items."""
    path = root / ARCHIVE_PATH
    if not path.exists():
        return {"plans": [], "items": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"plans": [], "items": []}


# --------------------------------------------------------------------------
# evidence resolution -- the accuracy half
# --------------------------------------------------------------------------

def _git(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=False)


def resolve_benchmark(root: pathlib.Path, run_id: str) -> str | None:
    """A benchmark reference must name a record that exists and passed."""
    matches = list((root / "benchmarks" / "runs").rglob(f"{run_id}.json"))
    if not matches:
        return f"benchmark record not found: {run_id}"
    try:
        record = json.loads(matches[0].read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return f"benchmark record {run_id} is not valid JSON: {error}"
    verdict = str(
        record.get("verdict")
        or record.get("status")
        or (record.get("result") or {}).get("verdict", "")
    ).lower()
    if verdict and verdict not in ("pass", "passed", "passedwithwarnings"):
        return f"benchmark {run_id} did not pass (verdict {verdict!r})"
    return None


def resolve_commit(root: pathlib.Path, sha: str) -> str | None:
    """A commit reference must exist and be reachable from main."""
    if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
        return f"not a commit sha: {sha!r}"
    if _git(root, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        return f"commit does not exist: {sha}"
    merge_base = _git(root, "merge-base", "--is-ancestor", sha, "main")
    if merge_base.returncode not in (0, 1):
        return None  # main unavailable (shallow clone / detached CI); do not guess
    if merge_base.returncode == 1:
        return f"commit {sha} is not reachable from main"
    return None


def resolve_doc(root: pathlib.Path, reference: str) -> str | None:
    """A doc reference must resolve, including its anchor if one is given."""
    path_part, _, anchor = reference.partition("#")
    target = root / path_part
    if not target.exists():
        return f"doc not found: {path_part}"
    if not anchor:
        return None
    text = target.read_text(encoding="utf-8")
    slugs = {
        re.sub(r"[^a-z0-9\s-]", "", heading.lower()).strip().replace(" ", "-")
        for heading in re.findall(r"(?m)^#{1,6}\s+(.+?)\s*$", text)
    }
    if anchor.lower() not in slugs:
        return f"anchor #{anchor} not found in {path_part}"
    return None


def resolve_evidence(root: pathlib.Path, reference: str) -> str | None:
    kind, _, value = reference.partition(":")
    if not value:
        return f"evidence must be '<kind>:<value>', got {reference!r}"
    if kind == "benchmark":
        return resolve_benchmark(root, value)
    if kind == "commit":
        return resolve_commit(root, value)
    if kind == "doc":
        return resolve_doc(root, value)
    if kind == "file":
        return None if (root / value).exists() else f"file not found: {value}"
    if kind == "run":
        return None  # a lane run ID; its artifacts stay untracked, so only the shape is checked
    return f"unknown evidence kind {kind!r} (benchmark|commit|doc|file|run)"


# Archived items keep the evidence they closed with. Files and doc anchors move after an
# item closes, so only the references that stay true forever are resolved there: a
# commit on main and a published benchmark record. Every reference must still have a
# known kind, and every done item must cite something.
ARCHIVE_RESOLVED_KINDS = ("commit", "benchmark")


def validate_archive(root: pathlib.Path, archive: dict | None = None) -> list[str]:
    errors: list[str] = []
    archive = load_archive(root) if archive is None else archive
    for item in archive.get("items", []):
        if item.get("status") != "done":
            continue
        iid = item.get("id", "?")
        evidence = item.get("evidence") or []
        if not evidence:
            errors.append(f"archived item {iid}: done requires evidence")
        for reference in evidence:
            kind, _, value = str(reference).partition(":")
            if not value or kind not in ("benchmark", "commit", "doc", "file", "run"):
                errors.append(f"archived item {iid}: evidence must be '<kind>:<value>' with a known kind, "
                              f"got {reference!r}")
            elif kind in ARCHIVE_RESOLVED_KINDS:
                problem = resolve_evidence(root, reference)
                if problem:
                    errors.append(f"archived item {iid}: evidence {problem}")
    return errors


# --------------------------------------------------------------------------
# staleness -- the second half
# --------------------------------------------------------------------------

def last_commit_epoch(root: pathlib.Path, relative: str) -> int | None:
    result = _git(root, "log", "-1", "--format=%ct", "--", relative)
    value = result.stdout.strip()
    return int(value) if value.isdigit() else None


def parse_date(value: str) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def staleness_findings(root: pathlib.Path, item: dict, today: _dt.date) -> list[str]:
    findings = []
    updated = parse_date(item.get("updated", ""))

    if item["status"] == "in-flight" and updated:
        age = (today - updated).days
        if age > IN_FLIGHT_STALE_DAYS:
            findings.append(
                f"in flight and untouched for {age} days (limit {IN_FLIGHT_STALE_DAYS}); "
                "update it, park it with unparkWhen, or close it"
            )

    # Same binding documents use: an item that describes code is suspect once
    # that code moves. Reported, never fatal -- any edit to a declared source
    # trips it, including ones that cannot affect the claim.
    if item["status"] == "done" and updated:
        for source in item.get("sourceOfTruth", []):
            if not (root / source).exists():
                continue
            source_time = last_commit_epoch(root, source)
            if source_time is None:
                continue
            source_date = _dt.date.fromtimestamp(source_time)
            if source_date > updated:
                findings.append(
                    f"marked done {updated}, but {source} changed on {source_date}; "
                    "confirm the completion still holds"
                )
    return findings


# --------------------------------------------------------------------------
# focus -- whether the work goes where the maintainer decided
# --------------------------------------------------------------------------

def freeze_findings(root: pathlib.Path, freeze, item_ids: set[str]) -> tuple[list[str], list[str]]:
    """Every commit after the freeze commit names an item of the focus plan in its subject.

    Only the subject counts: an id mentioned in passing in a body does not make a
    commit release work. History is never rewritten, so a commit that slipped
    through is accepted only by recording its sha in `freeze.exceptions` with a reason.
    """
    if not isinstance(freeze, dict) or not SHA.fullmatch(str(freeze.get("commit", ""))):
        return ["focusLock.freeze.commit must name the freeze commit's sha"], []
    errors: list[str] = []
    exceptions = freeze.get("exceptions") or {}
    if not isinstance(exceptions, dict):
        errors.append("focusLock.freeze.exceptions must map a commit sha to the reason it was accepted")
        exceptions = {}
    accepted = []
    for key, reason in exceptions.items():
        # A short or empty key would exempt every commit it prefixes.
        if SHA.fullmatch(str(key)) and str(reason).strip():
            accepted.append(str(key))
        else:
            errors.append(f"focusLock.freeze.exceptions entry {key!r} must map a 7-40 character commit sha "
                          "to the reason it was accepted")
    result = _git(root, "log", "--format=%H%x00%s%x1e", f"{freeze['commit']}..HEAD")
    if result.returncode != 0:
        return errors, [f"freeze commit {freeze['commit']} is not in local history; "
                        "commits after it were not checked"]
    names = re.compile(r"\b(?:" + "|".join(sorted(map(re.escape, item_ids), key=len, reverse=True)) + r")\b") \
        if item_ids else None
    for record in result.stdout.split("\x1e"):
        sha, _, subject = record.strip().partition("\x00")
        if not sha or any(sha.startswith(key) for key in accepted):
            continue
        if names is None or not names.search(subject):
            errors.append(f"commit {sha[:10]} after the freeze names no item of the focus plan in its subject: "
                          f"{subject[:80]}")
    return errors, []


def focus_findings(root: pathlib.Path, data: dict, items: dict,
                   archived: list[dict]) -> tuple[list[str], list[str]]:
    """Live work stays in the focus plan, within its in-flight cap, and the lock follows primaryPlan.

    Between September 4 and October 6, 2026 the primary plan was handed to the newest
    problem four times and the release items were parked each time; the lock makes that
    move a recorded decision instead of a one-line edit.
    """
    lock = data.get("focusLock")
    if lock is None:
        return [], []
    if not isinstance(lock, dict):
        return ["focusLock must be an object"], []
    errors: list[str] = []
    warnings: list[str] = []
    plan = lock.get("plan")
    if plan != data.get("primaryPlan"):
        errors.append("focusLock.plan must equal primaryPlan; moving the primary plan is a maintainer "
                      "decision, recorded by rewriting focusLock")
    if not parse_date(str(lock.get("decided", ""))):
        errors.append("focusLock.decided must be an ISO date")
    if not str(lock.get("decision") or "").strip():
        errors.append("focusLock.decision must record the maintainer's decision")
    cap = lock.get("maxInFlight")
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        errors.append("focusLock.maxInFlight must be a positive integer")
        cap = None

    in_flight = []
    for iid, item in items.items():
        status = item.get("status")
        if item.get("plan") != plan and status in LIVE_STATUSES:
            errors.append(f"item {iid} is {status} outside the focus plan {plan}; park it with "
                          f"unparkWhen, or re-home it into {plan} as a confirmed release blocker")
        elif item.get("plan") == plan and status == "in-flight":
            in_flight.append(iid)
    if cap is not None and len(in_flight) > cap:
        errors.append(f"focus plan {plan} has {len(in_flight)} items in flight "
                      f"({', '.join(sorted(in_flight))}); the focus lock allows {cap}")

    if lock.get("freeze") is not None:
        plan_ids: set[str] = set()
        for item in [*items.values(), *archived]:
            if item.get("plan") == plan and item.get("id"):
                plan_ids.add(item["id"])
                plan_ids.update(str(legacy) for legacy in item.get("legacyIds", []))
        freeze_errors, freeze_warnings = freeze_findings(root, lock["freeze"], plan_ids)
        errors += freeze_errors
        warnings += freeze_warnings
    return errors, warnings


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def validate(root: pathlib.Path, today: _dt.date | None = None,
             data: dict | None = None, archive: dict | None = None) -> dict:
    """Validate the roadmap on disk, or the in-memory `data` and `archive` an edit is about to write."""
    today = today or _dt.date.today()
    data = load(root) if data is None else data
    archive = load_archive(root) if archive is None else archive
    errors: list[str] = []
    warnings: list[str] = []

    plans = {}
    for plan in data["plans"]:
        pid = plan.get("id")
        if not pid:
            errors.append("a plan has no id")
            continue
        if pid in plans:
            errors.append(f"duplicate plan id: {pid}")
        plans[pid] = plan
        if plan.get("status") not in PLAN_STATUSES:
            errors.append(f"plan {pid}: status must be one of {PLAN_STATUSES}")
        if plan.get("owner") not in OWNERS:
            errors.append(f"plan {pid}: owner must be one of {OWNERS}")
        for required in ("title", "goal", "adopted"):
            if not plan.get(required):
                errors.append(f"plan {pid}: {required} is required")
        if plan.get("authority"):
            problem = resolve_doc(root, plan["authority"])
            if problem:
                errors.append(f"plan {pid}: authority {problem}")

    items = {}
    # One optional execution priority, not another status ledger. Older roadmaps
    # remain valid; all milestones and technical defects stay in the item table.
    if "primaryPlan" in data:
        primary = data["primaryPlan"]
        if not isinstance(primary, str) or primary not in plans:
            errors.append("primaryPlan must reference an existing plan")
        elif plans[primary].get("status") != "active":
            errors.append("primaryPlan must reference an active plan")

    legacy_seen = {}
    for item in data["items"]:
        iid = item.get("id")
        if not iid:
            errors.append("an item has no id")
            continue
        if iid in items:
            errors.append(f"duplicate item id: {iid}")
        items[iid] = item

        status = item.get("status")
        if status not in ITEM_STATUSES:
            errors.append(f"item {iid}: status must be one of {ITEM_STATUSES}")
            continue
        if item.get("plan") not in plans:
            errors.append(f"item {iid}: unknown plan {item.get('plan')!r}")
        if not item.get("title"):
            errors.append(f"item {iid}: title is required")
        if not item.get("updated") or not parse_date(item["updated"]):
            errors.append(f"item {iid}: updated must be an ISO date")
        if "due" in item:
            due = parse_date(str(item["due"]))
            if not due:
                errors.append(f"item {iid}: due must be an ISO date")
            elif status not in TERMINAL and due < today:
                warnings.append(f"item {iid}: due {item['due']} has passed; cut scope, move the date "
                                "with a recorded decision, or close it")

        for legacy in item.get("legacyIds", []):
            if legacy in legacy_seen:
                errors.append(
                    f"item {iid}: legacy id {legacy!r} already claimed by {legacy_seen[legacy]}"
                )
            legacy_seen[legacy] = iid

        # Status-conditional obligations. These are what stop a tracker from
        # degrading into a list of unexplained assertions.
        evidence = item.get("evidence", [])
        if status == "done" and not evidence:
            errors.append(f"item {iid}: done requires evidence")
        if status == "done":
            errors.append(
                f"item {iid}: done items belong in {ARCHIVE_PATH} (finished work leaves the open ledger)"
            )
        if status == "declined" and not item.get("reason"):
            errors.append(f"item {iid}: declined requires a reason")
        if status == "parked" and not item.get("unparkWhen"):
            errors.append(f"item {iid}: parked requires unparkWhen")
        if status == "superseded" and not item.get("supersededBy"):
            errors.append(f"item {iid}: superseded requires supersededBy")

        for reference in evidence:
            problem = resolve_evidence(root, reference)
            if problem:
                errors.append(f"item {iid}: evidence {problem}")

        # A source that does not exist cannot bind a claim; the September 2026
        # cleanup found four such paths behind open items.
        for source in item.get("sourceOfTruth", []):
            if not (root / source).exists():
                errors.append(f"item {iid}: sourceOfTruth not found: {source}")
        if len(item.get("notes") or "") > NOTES_MAX_CHARS:
            errors.append(
                f"item {iid}: notes exceed {NOTES_MAX_CHARS} characters "
                f"({len(item['notes'])}); keep the current position, leave history to git"
            )

        warnings.extend(f"item {iid}: {f}" for f in staleness_findings(root, item, today))

    errors.extend(validate_archive(root, archive))

    archived_items = archive.get("items", [])
    focus_errors, focus_warnings = focus_findings(root, data, items, archived_items)
    errors.extend(focus_errors)
    warnings.extend(focus_warnings)

    # Dependency integrity, resolved after every item is known. A blocker that
    # finished and moved to the archive is satisfied.
    archived_ids = {i.get("id") for i in archived_items}
    for iid, item in items.items():
        for blocker in item.get("blockedBy", []):
            if blocker in archived_ids and blocker not in items:
                continue
            if blocker not in items:
                errors.append(f"item {iid}: blockedBy unknown item {blocker}")
                continue
            if item.get("status") in ("in-flight", "done") and \
                    items[blocker].get("status") not in TERMINAL:
                errors.append(
                    f"item {iid} is {item['status']} but its blocker {blocker} is "
                    f"{items[blocker].get('status')}"
                )
            # Planned work behind parked work is parked in all but name.
            if item.get("status") == "planned" and items[blocker].get("status") == "parked":
                warnings.append(
                    f"item {iid} is effectively parked behind {blocker}; "
                    f"park it with unparkWhen or unpark {blocker}"
                )
        if item.get("supersededBy") and item["supersededBy"] not in items:
            errors.append(f"item {iid}: supersededBy unknown item {item['supersededBy']}")

    for iid in items:
        seen, cursor = set(), iid
        while cursor:
            if cursor in seen:
                errors.append(f"blockedBy cycle involving {iid}")
                break
            seen.add(cursor)
            blockers = items.get(cursor, {}).get("blockedBy", [])
            cursor = blockers[0] if blockers else None

    # Plan/item coherence: a finished plan cannot hold live work, and a plan
    # whose work is all finished is not still active.
    for pid, plan in plans.items():
        owned = [i for i in items.values() if i.get("plan") == pid]
        live = [i for i in owned if i.get("status") not in TERMINAL]
        if plan.get("status") == "complete" and live:
            errors.append(
                f"plan {pid} is complete but holds {len(live)} unfinished item(s): "
                + ", ".join(sorted(i["id"] for i in live))
            )
        if plan.get("status") == "active" and owned and not live:
            errors.append(
                f"plan {pid} is active but every item is finished; mark it complete"
            )
        if not owned:
            warnings.append(f"plan {pid} has no items")

    return {
        "plans": len(plans),
        "items": len(items),
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }


# --------------------------------------------------------------------------
# progress + render
# --------------------------------------------------------------------------

def progress(root: pathlib.Path, data: dict | None = None, archive: dict | None = None) -> dict:
    data = load(root) if data is None else data
    archived = (load_archive(root) if archive is None else archive).get("items", [])
    out = []
    for plan in sorted(data["plans"], key=lambda p: p["id"] != data.get("primaryPlan")):
        owned = [i for i in data["items"] + archived if i.get("plan") == plan["id"]]
        counts = {status: sum(1 for i in owned if i.get("status") == status)
                  for status in ITEM_STATUSES}
        finished = sum(counts[s] for s in TERMINAL)
        out.append({
            "id": plan["id"],
            "title": plan.get("title"),
            "status": plan.get("status"),
            "owner": plan.get("owner"),
            "items": len(owned),
            "finished": finished,
            "percent": round(100 * finished / len(owned)) if owned else None,
            "counts": {k: v for k, v in counts.items() if v},
        })
    return {"plans": out}


def render(root: pathlib.Path, data: dict | None = None, archive: dict | None = None) -> str:
    data = load(root) if data is None else data
    report = progress(root, data, archive)
    lines = [
        "# Roadmap",
        "",
        "> Generated by `python3 scripts/roadmap.py render`. Do not edit manually.",
        "> Open work lives in `config/roadmap.json`; finished items and completed plans are in",
        "> `config/roadmap-archive.json` and only count toward progress here.",
        "",
    ]
    order = {"active": 0, "parked": 1, "complete": 2, "superseded": 3}
    plans = sorted(data["plans"], key=lambda p: (
        p["id"] != data.get("primaryPlan"), order.get(p.get("status"), 9), p["id"]
    ))
    summary = {p["id"]: p for p in report["plans"]}

    if data.get("primaryPlan") in summary:
        primary = summary[data["primaryPlan"]]
        lines += [f"**Current execution plan: {primary['title']}** (`{primary['id']}`).",
                  "Follow its ordered milestones; the other plans retain the underlying defect records",
                  "and deferred backlog. Milestone progress is not a release-readiness score.", ""]
        lock = data.get("focusLock")
        if isinstance(lock, dict) and lock.get("plan") == primary["id"]:
            lines += [f"**Focus lock** (decided {lock.get('decided')}): {lock.get('decision')}",
                      f"Only this plan may hold planned or in-flight work, at most {lock.get('maxInFlight')} "
                      "items in flight.", ""]
            freeze = lock.get("freeze")
            if isinstance(freeze, dict) and freeze.get("commit"):
                lines += [f"**Frozen** at `{freeze['commit']}`: every later commit names an item of this plan "
                          "in its subject.", ""]

    lines += ["## Plans", "",
              "| Plan | Status | Owner | Progress |", "| --- | --- | --- | --- |"]
    for plan in plans:
        row = summary[plan["id"]]
        done = f"{row['finished']}/{row['items']}" if row["items"] else "no items"
        percent = f" ({row['percent']}%)" if row["percent"] is not None else ""
        lines.append(f"| `{plan['id']}` | {plan['status']} | {plan['owner']} | {done}{percent} |")
    lines.append("")

    for plan in plans:
        row = summary[plan["id"]]
        lines += [f"## {plan['title']}", "",
                  f"`{plan['id']}` · **{plan['status']}** · {plan['owner']} · adopted {plan['adopted']}", ""]
        lines += [f"{plan['goal']}", ""]
        if plan.get("authority"):
            # Relative to the rendered file, not the repo root, or the
            # documentation contract's link check fails.
            import os
            link = os.path.relpath(plan["authority"], pathlib.Path(RENDER_PATH).parent)
            lines += [f"Narrative authority: [`{plan['authority']}`]({link})", ""]
        owned = [i for i in data["items"] if i.get("plan") == plan["id"]]
        if not owned:
            lines += ["_No open items._", ""]
            continue
        lines += ["| Item | Status | Title | Blocked by |", "| --- | --- | --- | --- |"]
        for item in sorted(owned, key=lambda i: _item_sort_key(i["id"])):
            blocked = ", ".join(f"`{b}`" for b in item.get("blockedBy", [])) or "—"
            lines.append(
                f"| `{item['id']}` | {item['status']} | {item['title']} | {blocked} |"
            )
        lines.append("")
        # Open items carry their full gate/unpark text into the render: the
        # JSON is the authority, but a fresh session reads this file first,
        # and open work whose requirements are invisible here is open work
        # that gets re-derived from scratch.
        open_items = [
            i for i in sorted(owned, key=lambda i: _item_sort_key(i["id"]))
            if i["status"] not in TERMINAL
        ]
        if open_items:
            lines += ["### Open items in detail", ""]
            for item in open_items:
                detail = item.get("gate") or item.get("unparkWhen") or "(no gate text)"
                label = "unparkWhen" if (not item.get("gate") and item.get("unparkWhen")) else "gate"
                state = f"{item['status']}, due {item['due']}" if item.get("due") else item["status"]
                lines += [f"- **`{item['id']}`** ({state}) — {item['title']}.",
                          f"  {label}: {detail}"]
                # A parked item shows what would wake it next to what it must do.
                if item["status"] == "parked" and item.get("gate") and item.get("unparkWhen"):
                    lines.append(f"  unparkWhen: {item['unparkWhen']}")
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _item_sort_key(item_id: str):
    """Numeric-aware id ordering: DP-2 sorts before DP-10."""
    match = re.match(r"^([A-Za-z]+)-(\d+)$", item_id)
    if match:
        return (match.group(1), int(match.group(2)))
    return (item_id, 0)


# --------------------------------------------------------------------------
# editing -- one call per change, validated in memory before anything is written
# --------------------------------------------------------------------------

EDIT_COMMANDS = ("set", "note", "close")
EDITABLE_STATUSES = tuple(s for s in ITEM_STATUSES if s not in TERMINAL)
NONE = "none"  # the value that removes an optional field (--due, --blocked-by, --unpark-when)
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Where `set` and `note` insert a field the item does not have yet, so it lands where the
# ledger's items already keep it and the diff stays one small hunk. Keys outside this
# order keep their place; what `close` adds (evidence, reason, supersededBy, and the
# winner's legacyIds) goes last, as the archive's own closes do.
KEY_ORDER = ("id", "plan", "title", "status", "due", "blockedBy", "gate", "sourceOfTruth",
             "evidence", "updated", "unparkWhen", "notes")


class EditError(RuntimeError):
    """An editing command refused its input; nothing was written."""


def dump_json(data: dict) -> str:
    """The one format both roadmap files are kept in, so an edit rewrites only the lines it changes."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _read_json(root: pathlib.Path, relative: str, required: bool) -> tuple[str | None, dict | None]:
    path = root / relative
    if not path.exists():
        if required:
            raise RoadmapError(f"missing {relative}")
        return None, None
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise RoadmapError(f"{relative} is not valid JSON: {error}") from error
    if not isinstance(data, dict) or not all(isinstance(data.get(key), list) for key in ("plans", "items")):
        raise RoadmapError(f"{relative} must be an object with plans and items lists")
    if dump_json(data) != text:
        raise RoadmapError(f"{relative} is not in the format roadmap.py writes (json.dumps with indent=2 and "
                           "ensure_ascii=False, one trailing newline), so an edit would rewrite unrelated lines; "
                           "normalise it in a change of its own first")
    return text, data


def load_for_edit(root: pathlib.Path) -> tuple[dict, dict, dict[str, str | None]]:
    """Both files and the text each was read from.

    Unlike load_archive, an unreadable archive is an error here: writing the archive
    back from an empty fallback would erase the finished work.
    """
    roadmap_text, data = _read_json(root, ROADMAP_PATH, required=True)
    archive_text, archive = _read_json(root, ARCHIVE_PATH, required=False)
    render_path = root / RENDER_PATH
    before = {
        ROADMAP_PATH: roadmap_text,
        ARCHIVE_PATH: archive_text,
        RENDER_PATH: render_path.read_text(encoding="utf-8") if render_path.exists() else None,
    }
    return data, archive if archive is not None else {"plans": [], "items": []}, before


def _set_key(item: dict, key: str, value) -> None:
    """Set `key` in place, or insert a new key before the first later key of KEY_ORDER."""
    if key in item or key not in KEY_ORDER:
        item[key] = value
        return
    rank = KEY_ORDER.index(key)
    entries = list(item.items())
    position = next((index for index, (existing, _) in enumerate(entries)
                     if existing in KEY_ORDER and KEY_ORDER.index(existing) > rank), len(entries))
    entries.insert(position, (key, value))
    item.clear()
    item.update(entries)


def _live_item(data: dict, archive: dict, item_id: str) -> dict:
    for item in data["items"]:
        if item.get("id") == item_id:
            return item
    if any(item.get("id") == item_id for item in archive.get("items", [])):
        raise EditError(f"{item_id} is archived in {ARCHIVE_PATH}; only open items in {ROADMAP_PATH} can be edited")
    raise EditError(f"unknown item {item_id}")


def iso_date(value: str, flag: str) -> _dt.date:
    """A strict YYYY-MM-DD date; fromisoformat alone also takes forms the ledger never uses."""
    parsed = parse_date(value) if ISO_DATE.fullmatch(value) else None
    if parsed is None:
        raise EditError(f"{flag} must be an ISO date (YYYY-MM-DD), got {value!r}")
    return parsed


def _text(value: str, flag: str) -> str:
    text = value.strip()
    if not text:
        raise EditError(f"{flag} cannot be empty")
    return text


def _appended(existing: str | None, addition: str) -> str:
    existing = (existing or "").rstrip()
    return f"{existing} {addition}" if existing else addition


def _check_notes(item_id: str, notes: str) -> None:
    if len(notes) > NOTES_MAX_CHARS:
        raise EditError(
            f"{item_id}: notes would be {len(notes)} characters, {len(notes) - NOTES_MAX_CHARS} over the "
            f"{NOTES_MAX_CHARS}-character limit, and they are never truncated; keep the current position, "
            f"leave history to git, and rewrite them with: roadmap.py note {item_id} TEXT"
        )


def _changed_keys(before: dict, after: dict) -> list[str]:
    keys = list(dict.fromkeys([*before, *after]))
    return [key for key in keys if before.get(key) != after.get(key)]


def edit_set(data: dict, archive: dict, item_id: str, today: _dt.date, *, status: str | None = None,
             due: str | None = None, title: str | None = None, gate: str | None = None,
             blocked_by: str | None = None, unpark_when: str | None = None, touch: bool = False) -> dict:
    """Edit fields of an open item. `updated` moves with a status or gate change, or with `touch`."""
    item = _live_item(data, archive, item_id)
    if all(value is None for value in (status, due, title, gate, blocked_by, unpark_when)) and not touch:
        raise EditError("set needs at least one of --status, --due, --title, --gate, --blocked-by, "
                        "--unpark-when or --touch")
    before = copy.deepcopy(item)
    if status is not None:
        if status in TERMINAL:
            raise EditError(f"{status} is terminal and terminal items leave the open ledger; run: "
                            f"roadmap.py close {item_id} --status {status}")
        if status not in EDITABLE_STATUSES:
            raise EditError(f"--status must be one of {', '.join(EDITABLE_STATUSES)}, got {status!r}")
        _set_key(item, "status", status)
    if due is not None:
        if due == NONE:
            item.pop("due", None)
        else:
            _set_key(item, "due", iso_date(due, "--due").isoformat())
    if title is not None:
        _set_key(item, "title", _text(title, "--title"))
    if gate is not None:
        _set_key(item, "gate", _text(gate, "--gate"))
    if blocked_by is not None:
        blockers = [] if blocked_by == NONE else [part.strip() for part in blocked_by.split(",")]
        if not all(blockers) or len(set(blockers)) != len(blockers):
            raise EditError(f"--blocked-by takes distinct comma-separated item ids, or {NONE}; got {blocked_by!r}")
        if item_id in blockers:
            raise EditError(f"{item_id} cannot block itself")
        known = {other.get("id") for other in [*data["items"], *archive.get("items", [])]}
        unknown = [blocker for blocker in blockers if blocker not in known]
        if unknown:
            raise EditError(f"--blocked-by names unknown item(s): {', '.join(unknown)}")
        if blockers or "blockedBy" in item:
            _set_key(item, "blockedBy", blockers)
    if unpark_when is not None:
        if unpark_when == NONE:
            item.pop("unparkWhen", None)
        else:
            _set_key(item, "unparkWhen", _text(unpark_when, "--unpark-when"))

    # The ledger's rule: `updated` records a status, gate or evidence change, so editing a
    # title, a date or a blocker does not make old work look freshly touched.
    if touch or {"status", "gate"} & set(_changed_keys(before, item)):
        _set_key(item, "updated", today.isoformat())
    changed = _changed_keys(before, item)
    return {"ids": [item_id], "summary": f"set {item_id}: {', '.join(changed)}" if changed else "", "notices": []}


def edit_note(data: dict, archive: dict, item_id: str, today: _dt.date, *, text: str | None = None,
              append: str | None = None, touch: bool = False) -> dict:
    """Replace or append to an open item's notes, within NOTES_MAX_CHARS and never truncated."""
    item = _live_item(data, archive, item_id)
    if (text is None) == (append is None):
        raise EditError("note takes TEXT to replace the notes, or --append TEXT to add to them")
    notes = _text(text, "TEXT") if text is not None else _appended(item.get("notes"), _text(append, "--append"))
    _check_notes(item_id, notes)
    before = copy.deepcopy(item)
    _set_key(item, "notes", notes)
    if touch:
        _set_key(item, "updated", today.isoformat())
    changed = _changed_keys(before, item)
    return {"ids": [item_id], "summary": f"note {item_id}: {', '.join(changed)}" if changed else "", "notices": []}


def edit_close(root: pathlib.Path, data: dict, archive: dict, item_id: str, today: _dt.date, *,
               status: str = "done", superseded_by: str | None = None, note: str | None = None,
               evidence: list[str] | tuple[str, ...] = (), reason: str | None = None) -> dict:
    """Make an open item terminal and move it to the end of the archive, as the ledger's closes do.

    The item keeps its fields and their order; its status and `updated` change in place,
    `unparkWhen` goes (a closed item never wakes), a note is appended to its notes, and
    new evidence, the reason and supersededBy go last. A superseded item's id joins the
    winner's legacyIds, so references to it lead to the work that continues.
    """
    item = _live_item(data, archive, item_id)
    if status not in TERMINAL:
        raise EditError(f"--status must be one of {', '.join(TERMINAL)}, got {status!r}")
    if superseded_by is not None and status != "superseded":
        raise EditError("--superseded-by goes with --status superseded")
    if reason is not None and status != "declined":
        raise EditError("--reason goes with --status declined")

    winner = None
    if status == "superseded":
        if not superseded_by:
            raise EditError(f"superseding {item_id} needs --superseded-by ID, the open item that carries its work")
        if superseded_by == item_id:
            raise EditError(f"{item_id} cannot supersede itself")
        winner = next((other for other in data["items"] if other.get("id") == superseded_by), None)
        if winner is None:
            archived = any(other.get("id") == superseded_by for other in archive.get("items", []))
            raise EditError(f"--superseded-by {superseded_by} is {'archived' if archived else 'not an item'}; "
                            f"the winner must be an open item in {ROADMAP_PATH}")
    reason_text = _text(reason, "--reason") if reason is not None else None
    if status == "declined" and not (reason_text or item.get("reason")):
        raise EditError(f"declining {item_id} needs --reason TEXT")

    current = list(item.get("evidence") or [])
    added: list[str] = []
    for reference in evidence:
        problem = resolve_evidence(root, reference)
        if problem:
            raise EditError(f"--evidence {problem}")
        if reference not in current and reference not in added:
            added.append(reference)
    if status == "done" and not (current or added):
        raise EditError(f"closing {item_id} as done needs --evidence KIND:VALUE "
                        "(benchmark, commit, doc, file or run): done is never a bare assertion")
    notes = None
    if note is not None:
        notes = _appended(item.get("notes"), _text(note, "--note"))
        _check_notes(item_id, notes)

    _set_key(item, "status", status)
    _set_key(item, "updated", today.isoformat())
    item.pop("unparkWhen", None)
    if notes is not None:
        _set_key(item, "notes", notes)
    if added:
        item["evidence"] = [*current, *added]
    if reason_text is not None:
        item["reason"] = reason_text
    ids = [item_id]
    if winner is not None:
        item["supersededBy"] = winner["id"]
        legacy = list(winner.get("legacyIds") or [])
        if item_id not in legacy:
            winner["legacyIds"] = [*legacy, item_id]
        ids.append(winner["id"])

    index = next(index for index, other in enumerate(data["items"]) if other is item)
    del data["items"][index]
    archive.setdefault("items", []).append(item)

    notices = []
    dependents = sorted((other["id"] for other in data["items"] if item_id in other.get("blockedBy", [])),
                        key=_item_sort_key)
    if dependents and status != "done":
        target = f"set ID --blocked-by {winner['id']}" if winner else "set ID --blocked-by ..."
        notices.append(f"{', '.join(dependents)} {'is' if len(dependents) == 1 else 'are'} blocked by {item_id}, "
                       "which the archive now satisfies; if the blocking work continues elsewhere, run: "
                       f"roadmap.py {target}")
    destination = f"{status}, moved to {ARCHIVE_PATH}"
    if winner is not None:
        destination += f"; {winner['id']} lists it in legacyIds"
    return {"ids": ids, "summary": f"close {item_id}: {destination}", "notices": notices}


def _unified(relative: str, old: str | None, new: str) -> str:
    return "".join(difflib.unified_diff(
        (old or "").splitlines(keepends=True), new.splitlines(keepends=True),
        "/dev/null" if old is None else f"a/{relative}", f"b/{relative}"))


def _write(path: pathlib.Path, text: str) -> None:
    """Replace the file in one step, so an interrupted edit never leaves half a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    if path.exists():
        shutil.copymode(path, temporary)
    os.replace(temporary, path)


def apply_edit(root: pathlib.Path, today: _dt.date, dry_run: bool, mutate) -> int:
    """Run one edit: mutate in memory, validate the result, then write all three files or none."""
    data, archive, before = load_for_edit(root)
    result = mutate(data, archive)
    after = {ROADMAP_PATH: dump_json(data)}
    if before[ARCHIVE_PATH] is not None or archive.get("plans") or archive.get("items"):
        after[ARCHIVE_PATH] = dump_json(archive)
    if all(text == before[path] for path, text in after.items()):
        print(f"roadmap edit: no change; {result['ids'][0]} already says that")
        return 0
    after[RENDER_PATH] = render(root, data, archive)
    changed = {path: text for path, text in after.items() if text != before[path]}
    report = validate(root, today, data=data, archive=archive)

    if dry_run:
        for path, text in changed.items():
            sys.stdout.write(_unified(path, before[path], text))
    # The whole roadmap is validated; only what concerns the edited items is repeated here.
    pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, result["ids"])) + r")\b")
    related = [warning for warning in report["warnings"] if pattern.search(warning)]
    for warning in related:
        print(f"roadmap warning: {warning}", file=sys.stderr)
    for notice in result["notices"]:
        print(f"roadmap notice: {notice}", file=sys.stderr)
    for error in report["errors"]:
        print(f"roadmap error: {error}", file=sys.stderr)
    if not report["ok"]:
        print(f"roadmap edit refused, nothing was written: the result fails validation "
              f"({len(report['errors'])} error(s))", file=sys.stderr)
        return 1
    others = len(report["warnings"]) - len(related)
    tail = f"; {others} other warning(s), see roadmap.py validate" if others else ""
    if dry_run:
        print(f"{result['summary']} (dry run: validation passes, nothing written{tail})")
        return 0
    for path in (ARCHIVE_PATH, ROADMAP_PATH, RENDER_PATH):
        if path in changed:
            _write(root / path, changed[path])
    print(f"{result['summary']} (wrote {', '.join(changed)}{tail})")
    return 0


def _edit(root: pathlib.Path, args) -> int:
    try:
        today = iso_date(args.date, "--date") if args.date else _dt.date.today()
        if args.command == "set":
            def mutate(data, archive):
                return edit_set(data, archive, args.item_id, today, status=args.status, due=args.due,
                                title=args.title, gate=args.gate, blocked_by=args.blocked_by,
                                unpark_when=args.unpark_when, touch=args.touch)
        elif args.command == "note":
            def mutate(data, archive):
                return edit_note(data, archive, args.item_id, today, text=args.text, append=args.append,
                                 touch=args.touch)
        else:
            def mutate(data, archive):
                return edit_close(root, data, archive, args.item_id, today, status=args.status,
                                  superseded_by=args.superseded_by, note=args.note,
                                  evidence=args.evidence or [], reason=args.reason)
        return apply_edit(root, today, args.dry_run, mutate)
    except EditError as error:
        print(f"roadmap edit refused, nothing was written: {error}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], epilog=__doc__[__doc__.index("Usage:"):],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=str(REPO_ROOT), help="repository root (default: this checkout)")
    # Also accepted after the command, as the flat parser this replaced allowed.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=argparse.SUPPRESS, help="repository root (default: this checkout)")
    editing = argparse.ArgumentParser(add_help=False)
    editing.add_argument("--dry-run", action="store_true",
                         help="print the unified diff of every file the edit would change; write nothing")
    editing.add_argument("--date", metavar="YYYY-MM-DD",
                         help="the date written to updated and validated against (default: today)")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    command = commands.add_parser("validate", parents=[common], help="check the roadmap and its archive")
    command.add_argument("--strict", action="store_true", help="warnings fail too")
    command = commands.add_parser("render", parents=[common], help=f"write {RENDER_PATH}")
    command.add_argument("--check", action="store_true", help="verify, do not write")
    command = commands.add_parser("status", parents=[common], help="progress per plan")
    command.add_argument("--plan", help="limit to one plan")
    command.add_argument("--json", action="store_true", help="machine-readable")

    command = commands.add_parser(
        "set", parents=[common, editing], help="edit fields of an open item",
        description="Edit fields of an open item. updated moves to --date with a status or gate change, "
                    "or with --touch.")
    command.add_argument("item_id", metavar="ID")
    command.add_argument("--status", metavar="STATUS",
                         help=f"one of {', '.join(EDITABLE_STATUSES)}; terminal statuses go through close")
    command.add_argument("--due", metavar="YYYY-MM-DD|none")
    command.add_argument("--title")
    command.add_argument("--gate")
    command.add_argument("--blocked-by", metavar="ID,ID|none")
    command.add_argument("--unpark-when", metavar="TEXT|none")
    command.add_argument("--touch", action="store_true", help="move updated without a status or gate change")

    command = commands.add_parser(
        "note", parents=[common, editing], help="replace or append to an open item's notes",
        description=f"Replace or append to an open item's notes: at most {NOTES_MAX_CHARS} characters, "
                    "never truncated. updated moves only with --touch.")
    command.add_argument("item_id", metavar="ID")
    command.add_argument("text", metavar="TEXT", nargs="?", help="the new notes")
    command.add_argument("--append", metavar="TEXT", help="add TEXT after the current notes")
    command.add_argument("--touch", action="store_true", help="also move updated")

    command = commands.add_parser(
        "close", parents=[common, editing], help="make an open item terminal and move it to the archive",
        description=f"Make an open item terminal and move it to the end of {ARCHIVE_PATH}: updated moves "
                    "to --date, unparkWhen goes, and new evidence, reason and supersededBy go last; a "
                    "superseded item joins the winner's legacyIds.")
    command.add_argument("item_id", metavar="ID")
    command.add_argument("--status", choices=TERMINAL, default="done")
    command.add_argument("--superseded-by", metavar="ID", help="with superseded: the open item that carries the work")
    command.add_argument("--evidence", metavar="KIND:VALUE", action="append",
                         help="repeatable; done needs at least one reference (benchmark, commit, doc, file, run)")
    command.add_argument("--reason", metavar="TEXT", help="with declined: why")
    command.add_argument("--note", metavar="TEXT", help="append TEXT to the notes")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    root = pathlib.Path(args.root).resolve()

    try:
        if args.command in EDIT_COMMANDS:
            return _edit(root, args)

        if args.command == "render":
            text = render(root)
            target = root / RENDER_PATH
            if args.check:
                if not target.exists() or target.read_text(encoding="utf-8") != text:
                    print(f"error: {RENDER_PATH} is stale; run: "
                          "python3 scripts/roadmap.py render", file=sys.stderr)
                    return 1
                print(f"Roadmap render: fresh")
                return 0
            target.write_text(text, encoding="utf-8")
            print(f"Wrote {RENDER_PATH}")
            return 0

        if args.command == "status":
            report = progress(root)
            if args.plan:
                report["plans"] = [p for p in report["plans"] if p["id"] == args.plan]
                if not report["plans"]:
                    print(f"error: unknown plan {args.plan}", file=sys.stderr)
                    return 1
            if args.json:
                print(json.dumps(report, indent=2))
                return 0
            for plan in report["plans"]:
                counts = " ".join(f"{k}={v}" for k, v in plan["counts"].items())
                percent = f"{plan['percent']}%" if plan["percent"] is not None else "-"
                print(f"{plan['id']:<34} {plan['status']:<11} {percent:>5}  {counts}")
            return 0

        report = validate(root)
    except RoadmapError as error:
        print(f"roadmap error: {error}", file=sys.stderr)
        return 2

    for warning in report["warnings"]:
        print(f"roadmap warning: {warning}", file=sys.stderr)
    for error in report["errors"]:
        print(f"roadmap error: {error}", file=sys.stderr)
    if not report["ok"] or (args.strict and report["warnings"]):
        return 1
    print(f"Roadmap: PASS ({report['plans']} plans, {report['items']} items, "
          f"{len(report['warnings'])} warning(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
