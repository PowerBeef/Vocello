#!/usr/bin/env python3
"""CoreDevice probe helpers for ios_device_state.sh — devicectl JSON + lockState."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _run_devicectl(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["xcrun", "devicectl", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", "xcrun not found"
    except subprocess.TimeoutExpired:
        return 124, "", "devicectl timed out"


def _load_json_output(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def list_devices_json() -> dict[str, Any]:
    tmp = Path("/tmp") / f"devicectl-list-{Path(__file__).stem}.json"
    code, _, err = _run_devicectl(["list", "devices", "--json-output", str(tmp)])
    if code != 0 or not tmp.is_file():
        return {"error": err.strip() or f"devicectl list failed (exit {code})"}
    try:
        return _load_json_output(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _devices(data: dict[str, Any]) -> list[dict[str, Any]]:
    return (data.get("result") or {}).get("devices") or []


def _connected(d: dict[str, Any]) -> bool:
    cp = d.get("connectionProperties") or {}
    tunnel = cp.get("tunnelState", "")
    pairing = cp.get("pairingState", "")
    return pairing == "paired" or tunnel in ("connected", "available")


def _reachable(d: dict[str, Any]) -> bool:
    cp = d.get("connectionProperties") or {}
    if cp.get("tunnelState", "") in ("connected", "available"):
        return True
    # A paired network device may expose Connect to Device while its tunnel is
    # intentionally lazy. devicectl acquires that tunnel on the first operation.
    capabilities = d.get("capabilities") or []
    can_connect = any(
        item.get("featureIdentifier") == "com.apple.coredevice.feature.connectdevice"
        for item in capabilities
        if isinstance(item, dict)
    )
    return cp.get("pairingState") == "paired" and can_connect


def pick_device(data: dict[str, Any], device_id: str | None = None) -> dict[str, Any] | None:
    devs = _devices(data)
    if device_id:
        for d in devs:
            if d.get("identifier") == device_id:
                return d
        return None
    cands = [d for d in devs if _connected(d)]
    if not cands:
        return None
    preferred = "iPhone 17 Pro"
    for d in cands:
        props = d.get("deviceProperties") or {}
        if props.get("name") == preferred:
            return d
    if len(cands) == 1:
        return cands[0]
    return cands[0]


def summarize_device(d: dict[str, Any]) -> dict[str, Any]:
    cp = d.get("connectionProperties") or {}
    props = d.get("deviceProperties") or {}
    tunnel = cp.get("tunnelState", "")
    pairing = cp.get("pairingState", "")
    reachable = _reachable(d)
    return {
        "identifier": d.get("identifier"),
        "name": props.get("name"),
        "tunnelState": tunnel,
        "pairingState": pairing,
        "transportType": cp.get("transportType"),
        "availableForDevelopment": reachable,
    }


def query_lock_state(device_id: str) -> dict[str, Any]:
    tmp = Path("/tmp") / f"devicectl-lock-{Path(__file__).stem}.json"
    code, _, err = _run_devicectl(
        ["device", "info", "lockState", "--device", device_id, "--json-output", str(tmp)]
    )
    if code != 0 or not tmp.is_file():
        return {"state": "unknown", "error": (err or f"exit {code}").strip()}
    try:
        raw = _load_json_output(tmp)
    finally:
        tmp.unlink(missing_ok=True)

    return summarize_lock_state(raw)


def summarize_lock_state(raw: dict[str, Any]) -> dict[str, Any]:
    result = raw.get("result") or raw
    lock = result.get("lockState") or result
    unlocked = lock.get("unlockedSinceBoot")
    passcode = lock.get("passcodeRequired")
    # unlockedSinceBoot survives later Auto-Lock; it is not current lock state.
    # Keep missing/malformed current evidence unknown, never coerce strings.
    current_known = isinstance(passcode, bool)
    return {
        "state": "known" if current_known else "unknown",
        "unlockedSinceBoot": unlocked if isinstance(unlocked, bool) else None,
        "passcodeRequired": passcode if current_known else None,
        "deviceLocked": passcode if current_known else None,
    }


def probe_coredevice(device_id: str | None = None) -> dict[str, Any]:
    data = list_devices_json()
    if "error" in data:
        return {"reachable": False, "error": data["error"]}
    dev = pick_device(data, device_id)
    if not dev:
        return {"reachable": False, "error": "no matching device"}
    summary = summarize_device(dev)
    out: dict[str, Any] = {"reachable": _reachable(dev), **summary}
    ident = summary.get("identifier")
    if ident:
        out["lock"] = query_lock_state(str(ident))
    return out


def automation_blockers(*, verdict: str, coredevice: dict[str, Any]) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    if verdict == "DEVICE_UNREACHABLE":
        blockers.append("device_unreachable")
    return len(blockers) == 0, blockers


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: ios_coredevice_probe.py list|reachable|lock-state|probe [--device ID]", file=sys.stderr)
        return 2

    cmd = sys.argv[1]
    device_id = None
    args = sys.argv[2:]
    if "--device" in args:
        idx = args.index("--device")
        if idx + 1 < len(args):
            device_id = args[idx + 1]

    if cmd == "list":
        data = list_devices_json()
        dev = pick_device(data, device_id)
        if not dev:
            print(json.dumps({"reachable": False, "error": "device not found"}))
            return 1
        print(json.dumps(summarize_device(dev), indent=2))
        return 0

    if cmd == "reachable":
        data = list_devices_json()
        dev = pick_device(data, device_id)
        if dev and _reachable(dev):
            return 0
        return 1

    if cmd == "lock-state":
        if not device_id:
            data = list_devices_json()
            dev = pick_device(data, None)
            device_id = (dev or {}).get("identifier")
        if not device_id:
            print(json.dumps({"state": "unknown", "error": "no device"}))
            return 1
        print(json.dumps(query_lock_state(str(device_id)), indent=2))
        return 0

    if cmd == "probe":
        print(json.dumps(probe_coredevice(device_id), indent=2))
        return 0

    if cmd == "automation":
        verdict = "READY"
        core: dict[str, Any] = {}
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--verdict" and i + 1 < len(sys.argv):
                verdict = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--core-json" and i + 1 < len(sys.argv):
                core = json.loads(sys.argv[i + 1])
                i += 2
            elif sys.argv[i] == "--device" and i + 1 < len(sys.argv):
                device_id = sys.argv[i + 1]
                i += 2
            else:
                i += 1
        if not core:
            core = probe_coredevice(device_id)
        ready, blockers = automation_blockers(verdict=verdict, coredevice=core)
        print(json.dumps({"readyForAutomation": ready, "blockers": blockers}, indent=2))
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
