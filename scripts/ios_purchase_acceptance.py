#!/usr/bin/env python3
"""Collect the opt-in physical XCUITest's local StoreKit result; never sandbox proof."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re

PHASES = ["local_environment", "initial_locked", "restore_not_owned", "purchase_failed",
          "purchased", "relaunch_entitlement", "restored", "revoked", "pending", "approved"]
PREFIX = "VOCELLO_LOCAL_PURCHASE_RESULT="


def _surfaces(state: str) -> list[str]:
    return [f"{state}_{mode}_{surface}" for mode in ("custom", "design", "clone")
            for surface in ("history", "player")]


# Schema 3 and earlier exercised History rows and the full player only.
LEGACY_EXPORT_PHASES = PHASES + ["owned_product_unavailable"] + _surfaces("owned") + _surfaces("revoked")
# Schema 4 takes StoreKit offline for relaunch, Restore and every owned export, and adds the
# Studio inline card's own Design take on each side of the refund.
EXPORT_PHASES = (PHASES + ["owned_offline_relaunch", "owned_offline_restore", "owned_design_studio"]
                 + _surfaces("owned") + ["revoked_design_studio"] + _surfaces("revoked"))
CURRENT_SCHEMA = 4
RESTORATION_FIELDS = {3: {"transactionsCleared", "tab", "historyFilter", "appStopped"}}
RESTORATION_FIELDS[4] = RESTORATION_FIELDS[3] | {"studio"}


def collect(log: str, run_id: str, fixture_digest: str, scenario: str = "lifecycle",
            require_restoration: bool = False) -> dict:
    if scenario not in {"lifecycle", "exports"}:
        raise ValueError("Unknown purchase scenario")
    markers = re.findall(re.escape(PREFIX) + r"([A-Za-z0-9+/=]+)", log)
    if len(markers) != 1:
        raise ValueError("Exactly one terminal local purchase result is required")
    result = json.loads(base64.b64decode(markers[0], validate=True))
    if not isinstance(result, dict):
        raise ValueError("Unexpected purchase result fields")
    schema = result.get("schemaVersion")
    restored = type(schema) is int and schema in RESTORATION_FIELDS
    fields = {
        "schemaVersion", "runID", "fixtureSHA256", "environment", "phases", "cleanup", "complete"
    } | ({"scenario", "restoration"} if restored else set())
    if set(result) != fields:
        raise ValueError("Unexpected purchase result fields")
    if (type(schema) is not int
            or schema != (schema if restored else (2 if scenario == "exports" else 1))
            or result["runID"] != run_id
            or not re.fullmatch(r"[0-9a-f]{64}", fixture_digest)
            or result["fixtureSHA256"] != fixture_digest or result["environment"] != "Xcode"):
        raise ValueError("Purchase identity/environment mismatch")
    if require_restoration and schema != CURRENT_SCHEMA:
        raise ValueError("Current acceptance requires explicit restoration evidence")
    exported = "restored" if scenario == "exports" else "notRequired"
    if restored:
        restoration = result["restoration"]
        if result["scenario"] != scenario:
            raise ValueError("Purchase scenario mismatch")
        if not isinstance(restoration, dict) or set(restoration) != RESTORATION_FIELDS[schema]:
            raise ValueError("Unexpected restoration fields")
        if (restoration["transactionsCleared"] is not True or restoration["appStopped"] is not True
                or restoration["tab"] != "restored" or restoration["historyFilter"] != exported
                or restoration.get("studio", exported) != exported):
            raise ValueError("Purchase restoration not fully observed")
    export_phases = EXPORT_PHASES if schema == CURRENT_SCHEMA else LEGACY_EXPORT_PHASES
    if (result["complete"] is not True or result["cleanup"] is not True
            or result["phases"] != (export_phases if scenario == "exports" else PHASES)):
        raise ValueError("Purchase lifecycle or restoration incomplete")
    return {**result, "scope": "physical-device-local-storekit-only",
            "scenario": scenario, "offlineAcceptance": False,
            "restorationVerified": restored,
            "liveAcceptance": False, "logSHA256": hashlib.sha256(log.encode()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fixture-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", choices=("lifecycle", "exports"), default="lifecycle")
    parser.add_argument("--require-restoration", action="store_true",
                        help="Require current explicit restoration proof; legacy results remain historical only")
    args = parser.parse_args()
    try:
        result = collect(args.log.read_text(), args.run_id, args.fixture_sha256, args.scenario,
                         args.require_restoration)
    except (ValueError, OSError, TypeError) as error:
        # Raw results remain in the xcresult/log even when qualification fails.
        result = {"scope": "physical-device-local-storekit-only", "status": "failed",
                  "reason": str(error), "liveAcceptance": False}
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        return 1
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
