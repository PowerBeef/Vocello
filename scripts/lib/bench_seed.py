"""The UI benchmark's seed policy (audit #29), mirrored from Swift.

`Sources/QwenVoiceCore/BenchSeedPolicy.swift` derives each benchmark take's
sampling seed from the cell it measures when the registered knob
`QWENVOICE_BENCH_SEED_POLICY` names a cell-hash policy; the lane checkers and the
history validator recompute it here, so a take that sampled with another seed
never publishes under the policy.

A run's seed policy (``run.seedPolicy``) is one of:

* ``generated``: every take sampled with a fresh random seed (the default
  before the knob, and a lane run without it);
* ``requested``: every take sampled with a seed its request named outside a
  benchmark policy (a pinned draft seed);
* ``cell-hash-v1`` or ``cell-hash-v2``: every take sampled with
  ``cell_seed(<take cell>, <policy>)``. v2 is the lanes' default since RF-61
  (maintainer decision 2026-11-15): under v1 the hybrid model's
  ``design/short/warm#1`` take ran on in silence and Fast QC refused it on every
  run. That result stays on record with v1, and the seeds do not move again for
  a refused take: a v2 cell that is refused stands.
"""

from __future__ import annotations

import hashlib

CELL_HASH_V1 = "cell-hash-v1"
CELL_HASH_V2 = "cell-hash-v2"
GENERATED = "generated"
REQUESTED = "requested"
_CELL_HASH_DOMAINS = {
    CELL_HASH_V1: b"vocello-ui-bench-seed-v1",
    CELL_HASH_V2: b"vocello-ui-bench-seed-v2",
}
CELL_HASH_POLICIES = frozenset(_CELL_HASH_DOMAINS)
SEED_POLICIES = frozenset({GENERATED, REQUESTED}) | CELL_HASH_POLICIES
# The lanes' default (scripts/ui_test.sh --seed-policy).
DEFAULT_LANE_SEED_POLICY = CELL_HASH_V2
# The policies a benchmark lane can select.
LANE_SEED_POLICIES = (CELL_HASH_V2, CELL_HASH_V1, GENERATED)
POLICY_ENVIRONMENT_KEY = "QWENVOICE_BENCH_SEED_POLICY"
CELL_SCHEDULE_ENVIRONMENT_KEY = "QWENVOICE_BENCH_SEED_CELLS"


def cell_seed(cell: str, policy: str = CELL_HASH_V1) -> int:
    """The seed a cell-hash policy assigns to a benchmark cell ID such as
    ``custom/short/warm#1``: the first eight bytes, big-endian, of
    SHA-256(<the policy's domain> NUL <cell ID>)."""
    digest = hashlib.sha256(_CELL_HASH_DOMAINS[policy] + b"\0" + cell.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def run_seed_policy(takes: list[tuple[str, dict]]) -> tuple[str | None, list[str]]:
    """The run's seed policy from each take's engine row notes, and failures.

    `takes` is (cell, notes) in take order. A policy run needs every row to
    name the policy and to have sampled with its cell's seed as a requested
    seed. Without a policy stamp, every seed generated reads ``generated`` and
    every seed requested (a pinned draft seed) reads ``requested``; a mix of
    the two claims no policy (None). Rows that disagree about the policy fail.
    """
    failures: list[str] = []
    policies = {str((notes or {}).get("samplingSeedPolicy") or "") for _, notes in takes}
    if len(policies) == 1 and policies <= CELL_HASH_POLICIES:
        policy = next(iter(policies))
        for cell, notes in takes:
            source = notes.get("samplingSeedSource")
            try:
                seed = int(str(notes.get("samplingSeed")))
            except (TypeError, ValueError):
                seed = None
            if source != "requested" or seed != cell_seed(cell, policy):
                failures.append(
                    f"take {cell} sampled with seed {notes.get('samplingSeed')!r} ({source}), "
                    f"not its {policy} seed {cell_seed(cell, policy)}"
                )
        return policy, failures
    if policies == {""}:
        sources = {(notes or {}).get("samplingSeedSource") for _, notes in takes}
        if sources == {"generated"}:
            return GENERATED, failures
        if sources == {"requested"}:
            return REQUESTED, failures
        return None, failures
    failures.append(f"takes name different seed policies: {sorted(policies)}")
    return None, failures


def expected_policy_failure(expected: str | None, observed: str | None) -> list[str]:
    """A failure when the lane asked for one policy and the rows ran another."""
    if expected is None or expected == observed:
        return []
    return [
        f"the lane selected seed policy {expected}, but the rows sampled under "
        f"{observed or 'no single policy'} (an app built without internal diagnostics "
        "ignores the knob)"
    ]
