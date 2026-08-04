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

Usage:
    python3 scripts/roadmap.py validate [--strict]
    python3 scripts/roadmap.py render [--check]
    python3 scripts/roadmap.py status [--plan ID] [--json]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ROADMAP_PATH = "config/roadmap.json"
RENDER_PATH = "docs/ROADMAP.md"

PLAN_STATUSES = ("active", "complete", "parked", "superseded")
ITEM_STATUSES = ("planned", "in-flight", "done", "declined", "parked", "superseded")
TERMINAL = ("done", "declined", "superseded")
OWNERS = ("backend-mlx", "release-qa", "ios", "macos", "backend-and-platform")

# An in-flight item untouched for this long is surfaced. Not a failure: real work
# stalls for real reasons. Silence is the problem, not slowness.
IN_FLIGHT_STALE_DAYS = 21


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
    return f"unknown evidence kind {kind!r} (benchmark|commit|doc|file)"


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
# validation
# --------------------------------------------------------------------------

def validate(root: pathlib.Path, today: _dt.date | None = None) -> dict:
    today = today or _dt.date.today()
    data = load(root)
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

        warnings.extend(f"item {iid}: {f}" for f in staleness_findings(root, item, today))

    # Dependency integrity, resolved after every item is known.
    for iid, item in items.items():
        for blocker in item.get("blockedBy", []):
            if blocker not in items:
                errors.append(f"item {iid}: blockedBy unknown item {blocker}")
                continue
            if item.get("status") in ("in-flight", "done") and \
                    items[blocker].get("status") not in TERMINAL:
                errors.append(
                    f"item {iid} is {item['status']} but its blocker {blocker} is "
                    f"{items[blocker].get('status')}"
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

def progress(root: pathlib.Path) -> dict:
    data = load(root)
    out = []
    for plan in data["plans"]:
        owned = [i for i in data["items"] if i.get("plan") == plan["id"]]
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


def render(root: pathlib.Path) -> str:
    data = load(root)
    report = progress(root)
    lines = [
        "# Roadmap",
        "",
        "> Generated by `python3 scripts/roadmap.py render`. Do not edit manually.",
        "> State lives in `config/roadmap.json`; narrative documents cite it rather than",
        "> restating it. Evidence references are resolved against the repository by",
        "> `python3 scripts/roadmap.py validate`.",
        "",
    ]
    order = {"active": 0, "parked": 1, "complete": 2, "superseded": 3}
    plans = sorted(data["plans"], key=lambda p: (order.get(p.get("status"), 9), p["id"]))
    summary = {p["id"]: p for p in report["plans"]}

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
            lines += ["_No items yet._", ""]
            continue
        lines += ["| Item | Status | Title | Evidence |", "| --- | --- | --- | --- |"]
        for item in sorted(owned, key=lambda i: _item_sort_key(i["id"])):
            evidence = ", ".join(f"`{e}`" for e in item.get("evidence", [])) or "—"
            lines.append(
                f"| `{item['id']}` | {item['status']} | {item['title']} | {evidence} |"
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
                lines += [f"- **`{item['id']}`** ({item['status']}) — {item['title']}.",
                          f"  {label}: {detail}", ""]
    return "\n".join(lines).rstrip() + "\n"


def _item_sort_key(item_id: str):
    """Numeric-aware id ordering: DP-2 sorts before DP-10."""
    match = re.match(r"^([A-Za-z]+)-(\d+)$", item_id)
    if match:
        return (match.group(1), int(match.group(2)))
    return (item_id, 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["validate", "render", "status"])
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--check", action="store_true", help="render: verify, do not write")
    parser.add_argument("--strict", action="store_true", help="validate: warnings fail too")
    parser.add_argument("--plan", help="status: limit to one plan")
    parser.add_argument("--json", action="store_true", help="status: machine-readable")
    args = parser.parse_args(argv)
    root = pathlib.Path(args.root).resolve()

    try:
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
