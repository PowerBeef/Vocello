#!/usr/bin/env python3
"""Fail-closed per-take peak assertion for the Article 50 marking rollout.

CP-2's zero-peak design requires that publication-time audio marking leave
each take's peak footprint unchanged: the AudioSeal pass runs after
generation has ended, so nothing at or after the marking interval may exceed
the peak the take had already established. This checker reads the fresh
memory-qualification evidence manifest, walks every successful take's sample
sidecar, and asserts — within that take — that no sample at or after the
`before_marking` boundary exceeds the pre-marking peak beyond tolerance.

Within-take comparison is deliberate. Cross-run whole-lifecycle peak
comparison was tried first and refuted by its own control experiment
(2026-08-07): a `QWENVOICE_MARKING=off` run failed the cross-run bound worse
than the marked run in every mode, because per-take lifecycle peaks on the
8 GB canonical host swing hundreds of MB with system memory pressure across
back-to-back runs. The within-take marking-interval assertion measures the
marking pass itself (observed cost: +9 to +18 MB) and is immune to that
drift while still failing closed on any real regression — cache stacking,
a CPU-conv pathology, or an unreleased working set would each blow the
bound immediately.

The boundaries are captured by the adapter seam only when marking actually
executes, so a knob-disabled run fails this checker (missing boundaries)
and can never publish as marking evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def unwrap_record(document: dict) -> dict:
    """Accepts a tracked record or a lane evidence manifest (whose deferred
    record payload lives under `historyRecord`)."""
    inner = document.get("historyRecord")
    return inner if isinstance(inner, dict) else document


def footprint(row: dict) -> float | None:
    for key in ("physFootprintMB", "residentMB"):
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def check_take(take: dict, sidecar: Path, pct: float, floor: float,
               errors: list[str]) -> None:
    label = f"{take.get('cell', take.get('mode', '?'))}"
    if not sidecar.is_file():
        errors.append(f"{label}: sample sidecar missing: {sidecar.name}")
        return
    with sidecar.open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    rows = [r for r in rows if "capturedUptimeNS" in r and footprint(r) is not None]
    rows.sort(key=lambda r: r["capturedUptimeNS"])
    marks = {r["boundary"]: r["capturedUptimeNS"]
             for r in rows if r.get("kind") == "boundary"
             and r.get("boundary") in ("before_marking", "after_marking")}
    if set(marks) != {"before_marking", "after_marking"}:
        errors.append(
            f"{label}: marking boundaries absent — the publication marking "
            f"pass did not run (disabled or bypassed); unmarked takes cannot "
            f"publish as marking evidence")
        return
    before = marks["before_marking"]
    pre = [footprint(r) for r in rows if r["capturedUptimeNS"] <= before]
    post = [footprint(r) for r in rows if r["capturedUptimeNS"] > before]
    if not pre or not post:
        errors.append(f"{label}: sidecar has no samples on one side of the marking boundary")
        return
    peak_pre = max(pre)
    peak_post = max(post)
    allowed = peak_pre + max(peak_pre * pct / 100.0, floor)
    verdict = "PASS" if peak_post <= allowed else "FAIL"
    print(f"  {label:32} pre-marking peak {peak_pre:8.1f} MB  "
          f"at/after marking {peak_post:8.1f} MB  allowed {allowed:8.1f} MB  {verdict}")
    if peak_post > allowed:
        errors.append(
            f"{label}: footprint at/after the marking interval "
            f"({peak_post:.1f} MB) exceeds the take's pre-marking peak "
            f"({peak_pre:.1f} MB) beyond tolerance — the marking pass must "
            f"not raise the take peak")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path,
                        help="fresh memory-qualification benchmark-evidence.json "
                             "(sample sidecars are resolved beside it)")
    parser.add_argument("--tolerance-percent", type=float, default=5.0)
    parser.add_argument("--tolerance-mb", type=float, default=48.0,
                        help="floor absorbing sampler cadence noise; the marking "
                             "pass itself measures +9 to +18 MB")
    parser.add_argument("--sidecar-dir", type=Path, default=None,
                        help="override the sidecar directory (default: "
                             "runtime/diagnostics/engine beside the manifest)")
    args = parser.parse_args(argv)

    record = unwrap_record(json.loads(args.evidence.read_text(encoding="utf-8")))
    sidecar_dir = args.sidecar_dir or (
        args.evidence.parent / "runtime" / "diagnostics" / "engine")

    errors: list[str] = []
    takes = [t for t in record.get("takes", [])
             if t.get("status") in (None, "success", "passed", "passedWithWarnings")]
    if not takes:
        errors.append(f"{args.evidence}: no successful takes in the record")
    for take in takes:
        gid = take.get("generationID")
        if not isinstance(gid, str) or not gid:
            errors.append(f"take {take.get('cell', '?')}: missing generationID")
            continue
        check_take(take, sidecar_dir / f"samples-{gid}.jsonl",
                   args.tolerance_percent, args.tolerance_mb, errors)

    if errors:
        print("marking peak equality: FAIL", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("marking peak equality: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
