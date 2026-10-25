#!/usr/bin/env python3
"""iPhone Mirroring sessions for the computer-use workflow (`scripts/ios_device.sh mirroring`).

    status [--json]                 whether iPhone Mirroring runs on this Mac, and whether the
                                    paired phone is reachable and locked (CoreDevice)
    session LABEL                   start a record: session.json with the source commit and the
                                    installed Vocello version and build, and make it current
    capture LABEL --step TEXT [--observed TEXT]
                                    save the iPhone Mirroring window as NNN-LABEL.png in the current
                                    session and append one line to its steps.jsonl
    stop                            quit iPhone Mirroring and wait until it has exited

Records live under $QVOICE_MIRRORING_ROOT (ios_device.sh points it at
build/artifacts/ios/mirroring), untracked. They hold no device identifier, no absolute path and
no screen text beyond what the caller writes in --step and --observed. A record is not lane
evidence: an attended row closes only when the maintainer confirms it
(docs/reference/development-workflow.md, computer use).

Refusals print `error: ...` to stderr and exit 1; usage errors exit 2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

APP_NAME = "iPhone Mirroring"
APP_BUNDLE_ID = "com.apple.ScreenContinuity"
VOCELLO_BUNDLE_ID = "com.patricedery.vocello"
LIB = Path(__file__).resolve().parent
ROOT = LIB.parents[1]

Runner = Callable[..., "subprocess.CompletedProcess[str]"]

# JXA: the on-screen, normal-layer window of iPhone Mirroring. Window ids, not titles or
# coordinates, so the capture is exactly the mirrored phone and nothing behind it.
WINDOW_ID_SCRIPT = """
ObjC.import('CoreGraphics');
var raw = $.CGWindowListCopyWindowInfo($.kCGWindowListOptionOnScreenOnly, $.kCGNullWindowID);
var rows = ObjC.deepUnwrap(ObjC.castRefToObject(raw)) || [];
rows.filter(function (w) { return w.kCGWindowOwnerName === 'iPhone Mirroring' && w.kCGWindowLayer === 0; })
    .map(function (w) { return w.kCGWindowNumber; }).join(',');
"""


class Refusal(Exception):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slug(text: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-.")[:60]
    if not value:
        raise Refusal("error: a label needs at least one letter or digit")
    return value


def mirroring_running(run: Runner) -> bool:
    return run(["pgrep", "-xq", APP_NAME], capture_output=True, text=True).returncode == 0


def phone_state(run: Runner) -> dict[str, Any]:
    probe = run([sys.executable, str(LIB / "ios_coredevice_probe.py"), "probe"],
                capture_output=True, text=True)
    try:
        value = json.loads(probe.stdout) if probe.returncode == 0 else {}
    except json.JSONDecodeError:
        value = {}
    lock = value.get("lock") or {}
    return {
        "reachable": value.get("reachable") is True,
        "deviceLocked": lock.get("deviceLocked") if isinstance(lock.get("deviceLocked"), bool) else None,
        "identifier": value.get("identifier") if isinstance(value.get("identifier"), str) else None,
    }


def status(run: Runner) -> dict[str, Any]:
    phone = phone_state(run)
    return {
        "mirroringRunning": mirroring_running(run),
        "phone": {"reachable": phone["reachable"], "deviceLocked": phone["deviceLocked"]},
    }


def installed_vocello(run: Runner, device: str | None) -> dict[str, str] | str:
    """The installed Vocello's version and build, or "unverified" when CoreDevice cannot say."""
    if not device:
        return "unverified"
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "apps.json"
        listed = run(["xcrun", "devicectl", "device", "info", "apps", "--device", device,
                      "--bundle-id", VOCELLO_BUNDLE_ID, "--json-output", str(output), "--quiet"],
                     capture_output=True, text=True)
        if listed.returncode != 0 or not output.is_file():
            return "unverified"
        try:
            rows = json.loads(output.read_text()).get("result", {}).get("apps") or []
        except (json.JSONDecodeError, AttributeError):
            return "unverified"
    matches = [row for row in rows if isinstance(row, dict) and row.get("bundleIdentifier") == VOCELLO_BUNDLE_ID]
    if len(matches) != 1:
        return "unverified"
    return {"marketingVersion": str(matches[0].get("version")), "buildNumber": str(matches[0].get("bundleVersion"))}


def start_session(root: Path, label: str, run: Runner, now: str | None = None) -> Path:
    started = now or utc_now()
    name = f"mirroring-{started.replace('-', '').replace(':', '')}-{slug(label)}"
    session = root / name
    session.mkdir(parents=True, exist_ok=False)
    commit = run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True)
    record = {
        "schemaVersion": 1,
        "label": label,
        "startedAt": started,
        "sourceCommit": commit.stdout.strip() if commit.returncode == 0 else "unknown",
        "installedVocello": installed_vocello(run, phone_state(run)["identifier"]),
        "steps": "steps.jsonl",
        "evidence": "record for the maintainer's confirmation; never a lane verdict",
    }
    (session / "session.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    (root / "current-session").write_text(name + "\n")
    return session


def current_session(root: Path) -> Path:
    pointer = root / "current-session"
    name = pointer.read_text().strip() if pointer.is_file() else ""
    session = root / name
    if not name or "/" in name or not (session / "session.json").is_file():
        raise Refusal("error: no current mirroring session; run `mirroring session LABEL` first")
    return session


def mirroring_window(run: Runner) -> str:
    found = run(["osascript", "-l", "JavaScript", "-e", WINDOW_ID_SCRIPT], capture_output=True, text=True)
    ids = [part for part in found.stdout.strip().split(",") if part.isdigit()] if found.returncode == 0 else []
    if len(ids) != 1:
        raise Refusal("error: no single on-screen iPhone Mirroring window to capture")
    return ids[0]


def capture(root: Path, label: str, step: str, observed: str | None, run: Runner) -> dict[str, Any]:
    session = current_session(root)
    window = mirroring_window(run)
    steps = session / "steps.jsonl"
    number = 1 + (sum(1 for line in steps.read_text().splitlines() if line.strip()) if steps.is_file() else 0)
    image = session / f"{number:03d}-{slug(label)}.png"
    shot = run(["screencapture", "-x", "-o", "-l", window, str(image)], capture_output=True, text=True)
    if shot.returncode != 0 or not image.is_file() or image.stat().st_size == 0:
        image.unlink(missing_ok=True)
        raise Refusal("error: screencapture did not save the iPhone Mirroring window "
                      "(the capturing app may need Screen Recording permission)")
    entry = {
        "step": number,
        "at": utc_now(),
        "label": label,
        "action": step,
        "observed": observed,
        "file": image.name,
        "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
    }
    with steps.open("a") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def stop(run: Runner, wait_seconds: float = 10.0, sleep: Callable[[float], None] = time.sleep) -> None:
    if not mirroring_running(run):
        return
    run(["osascript", "-e", f'tell application id "{APP_BUNDLE_ID}" to quit'], capture_output=True, text=True)
    deadline = time.monotonic() + wait_seconds
    while mirroring_running(run):
        if time.monotonic() >= deadline:
            raise Refusal("error: iPhone Mirroring is still running; quit it before a phone lane")
        sleep(0.25)


def main(argv: Sequence[str] | None = None, run: Runner = subprocess.run) -> int:
    parser = argparse.ArgumentParser(prog="ios_device.sh mirroring", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    status_parser = commands.add_parser("status")
    status_parser.add_argument("--json", action="store_true")
    session_parser = commands.add_parser("session")
    session_parser.add_argument("label")
    capture_parser = commands.add_parser("capture")
    capture_parser.add_argument("label")
    capture_parser.add_argument("--step", required=True)
    capture_parser.add_argument("--observed")
    commands.add_parser("stop")
    args = parser.parse_args(argv)
    root = Path(os.environ.get("QVOICE_MIRRORING_ROOT") or ROOT / "build" / "artifacts" / "ios" / "mirroring")
    try:
        if args.command == "status":
            value = status(run)
            if args.json:
                print(json.dumps(value, sort_keys=True))
            else:
                phone = value["phone"]
                lock = {True: "locked", False: "unlocked", None: "lock state unknown"}[phone["deviceLocked"]]
                print(f"iPhone Mirroring: {'running' if value['mirroringRunning'] else 'not running'}; "
                      f"phone: {'reachable' if phone['reachable'] else 'unreachable'}, {lock}")
        elif args.command == "session":
            session = start_session(root, args.label, run)
            print(f"==> mirroring session {session.name}")
        elif args.command == "capture":
            entry = capture(root, args.label, args.step, args.observed, run)
            print(f"==> step {entry['step']}: {entry['file']}")
        elif args.command == "stop":
            stop(run)
            print("==> iPhone Mirroring is not running")
    except Refusal as refusal:
        print(refusal, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
