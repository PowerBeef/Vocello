#!/usr/bin/env python3
"""iPhone Mirroring state for the phone lanes (`scripts/ios_device.sh mirroring`).

    status [--json]                 whether iPhone Mirroring runs on this Mac, and whether the
                                    paired phone is reachable and locked (CoreDevice)
    stop                            quit iPhone Mirroring and wait until it has exited

XCUITest breaks under iPhone Mirroring even while CoreDevice reports the phone unlocked, so the
iOS `ui-preflight` refuses a lane while it runs; `stop` quits it, and Mirroring leaves the phone
locked for the maintainer to unlock. Mirroring is no test route: every UI check is an XCUITest
lane (maintainer decision 2026-11-17, docs/reference/development-workflow.md).

Refusals print `error: ...` to stderr and exit 1; usage errors exit 2.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

APP_NAME = "iPhone Mirroring"
APP_BUNDLE_ID = "com.apple.ScreenContinuity"
LIB = Path(__file__).resolve().parent

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class Refusal(Exception):
    pass


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
    }


def status(run: Runner) -> dict[str, Any]:
    return {"mirroringRunning": mirroring_running(run), "phone": phone_state(run)}


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
    commands.add_parser("stop")
    args = parser.parse_args(argv)
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
        elif args.command == "stop":
            stop(run)
            print("==> iPhone Mirroring is not running")
    except Refusal as refusal:
        print(refusal, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
