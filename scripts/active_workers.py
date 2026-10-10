#!/usr/bin/env python3
"""Host-wide Codex worker leases. Never use Git worktree locks as activity evidence.

Leases bind a session/agent id to a live Codex process and its start time. Unknown
ownership is inconclusive, not idle. Hooks are supplementary: the lead must also
join its known workers before measurements. No transcript or prompt is retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def directory() -> Path:
    override = os.environ.get("QVOICE_WORKER_DIRECTORY")
    if override:
        if not Path(override).is_absolute():
            raise ValueError("QVOICE_WORKER_DIRECTORY must be absolute")
        return Path(override)
    policy = json.loads((ROOT / "config/build-output-policy.json").read_text())
    return Path(policy["hostWorkerDirectory"]).expanduser()


def process(pid: int) -> dict | None:
    result = subprocess.run(["ps", "-p", str(pid), "-o", "ppid=", "-o", "lstart=", "-o", "comm="],
                            capture_output=True, text=True, check=False, timeout=3,
                            env={**os.environ, "LC_ALL": "C", "TZ": "UTC0"})
    if result.returncode == 1 and not result.stderr.strip():
        return None
    if result.returncode or not result.stdout.strip():
        raise RuntimeError("process ownership inventory unavailable")
    parts = result.stdout.strip().split(None, 6)
    if len(parts) != 7:
        raise RuntimeError("unreadable process ownership inventory")
    return {"pid": pid, "parent": int(parts[0]), "started": " ".join(parts[1:6]), "command": parts[6]}


def owner() -> dict:
    pid = os.getppid()
    for _ in range(16):
        info = process(pid)
        if not info:
            break
        if Path(info["command"]).name.lower() in ("codex", "codexcli", "codex-cli"):
            return {key: info[key] for key in ("pid", "started")}
        pid = info["parent"]
        if pid <= 1:
            break
    raise RuntimeError("no live Codex process owner found")


def key(session: str, agent: str = "") -> str:
    return hashlib.sha256((session + "\0" + agent).encode()).hexdigest()


def write_record(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value) + "\n")
    os.replace(temp, path)


def lifecycle(payload: dict, *, base: Path | None = None, identity: dict | None = None) -> None:
    base = base or directory()
    session = payload.get("session_id")
    event = payload.get("hook_event_name")
    if not isinstance(session, str) or not session:
        raise ValueError("worker lifecycle requires session_id")
    session_key = key(session)
    if event == "SessionEnd":
        # Neither interruption nor root teardown proves a worker has stopped.
        # Completed workers receive SubagentStop; abandoned leases age out when
        # their owning process dies. A live orphan therefore blocks measurement.
        (base / f"session-{session_key}.json").unlink(missing_ok=True)
        return
    if event == "SubagentStop":
        agent = payload.get("agent_id")
        if not isinstance(agent, str) or not agent:
            raise ValueError("worker stop requires agent_id")
        (base / f"worker-{key(session, agent)}.json").unlink(missing_ok=True)
        (base / f"error-{key(session, agent)}.json").unlink(missing_ok=True)
        return
    if event not in ("SessionStart", "SubagentStart"):
        return
    identity = identity or owner()
    if event == "SessionStart":
        (base / f"error-{key(session)}.json").unlink(missing_ok=True)
    common = {"schemaVersion": 1, "session": session_key, **identity}
    write_record(base / f"session-{session_key}.json", {**common, "kind": "session"})
    if event == "SubagentStart":
        agent = payload.get("agent_id")
        if not isinstance(agent, str) or not agent:
            raise ValueError("worker start requires agent_id")
        write_record(base / f"worker-{key(session, agent)}.json", {**common, "kind": "worker"})


def invalidate(payload: dict, *, base: Path | None = None) -> None:
    """A failed start must not leave an earlier 'tracking available' receipt."""
    base = base or directory()
    session = payload.get("session_id")
    if not isinstance(session, str) or not session:
        return
    receipt = base / f"session-{key(session)}.json"
    try:
        existing = json.loads(receipt.read_text())
        write_record(base / f"error-{key(session, str(payload.get('agent_id', '')))}.json",
                     {**existing, "kind": "tracking-error"})
    finally:
        receipt.unlink(missing_ok=True)


def snapshot(*, base: Path | None = None, inspect=process, session: str | None = None) -> dict:
    base = base or directory()
    session = session if session is not None else os.environ.get("QVOICE_WORKER_SESSION", "")
    current_tracked = False
    workers = 0
    stale = 0
    unknown = 0
    for path in base.glob("*.json"):
        try:
            record = json.loads(path.read_text())
            if record.get("schemaVersion") != 1 or record.get("kind") not in ("session", "worker", "tracking-error"):
                raise ValueError("unknown lease kind")
            actual = inspect(int(record["pid"]))
            if actual is None or actual["started"] != record["started"]:
                stale += 1
                continue
            if Path(actual["command"]).name.lower() not in ("codex", "codexcli", "codex-cli"):
                stale += 1
                continue
            if record["kind"] == "worker":
                workers += 1
            elif record["kind"] == "tracking-error":
                unknown += 1
            elif session and record.get("session") == session:
                current_tracked = True
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError):
            unknown += 1
    return {"trackingAvailable": current_tracked and unknown == 0,
            "activeWorkers": workers, "staleRecords": stale, "unknownRecords": unknown}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("status", "check"))
    parser.add_argument("--agents-allowed", action="store_true")
    args = parser.parse_args()
    try:
        report = snapshot()
    except (OSError, ValueError, KeyError) as error:
        print(f"worker tracking unavailable: {type(error).__name__}", file=sys.stderr)
        return 2
    if args.command == "status":
        print(json.dumps(report))
        return 0
    if report["unknownRecords"]:
        print("worker tracking has unreadable ownership; inspect leases before measurement", file=sys.stderr)
        return 2
    if report["activeWorkers"] and not args.agents_allowed:
        print(f"active-workers({report['activeWorkers']})", file=sys.stderr)
        return 1
    if not report["trackingAvailable"] and os.environ.get("QVOICE_LEAD_ONLY") != "1":
        print("worker tracking unavailable; join all workers, then explicitly use QVOICE_LEAD_ONLY=1", file=sys.stderr)
        return 2
    if report["activeWorkers"]:
        print(f"agents:{report['activeWorkers']}(allowed)", file=sys.stderr)
    elif not report["trackingAvailable"]:
        print("worker tracking unavailable; lead-only execution declared", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
