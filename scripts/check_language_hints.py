#!/usr/bin/env python3
"""Gate language-bench telemetry (Phase 2 — hint contract, no ASR).

Validates pulled engine rows for one language-bench run:
  - one row per predeclared take (run + cell + generation + optional seed);
  - notes.languageHint matches the matrix expected resolved hint;
  - generation finished successfully;
  - audioQC passes or warns; a fail remains a quality-gate failure.

Usage:
  scripts/check_language_hints.py <diagnostics-dir> \\
      --run-id ios-lang-bench-20260705-120000 \\
      --matrix config/language-bench-matrix.json \\
      --corpus config/language-bench-corpus.json \\
      [--subset quick|full]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from language_bench_evidence import (
    expected_language_hint_source,
    exact_sentinels,
    load_json as load_evidence_json,
    seed_value,
    validate_plan_against_sources,
    stable_default_seed,
)


def load_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def corpus_scripts(corpus: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for entry in corpus.get("languages") or []:
        lang_id = entry.get("id")
        script = entry.get("script")
        if isinstance(lang_id, str) and isinstance(script, str):
            out[lang_id] = script
    return out


def select_cells(matrix: dict[str, Any], subset: str) -> list[dict[str, Any]]:
    cells = matrix.get("cells") or []
    if subset == "full":
        return list(cells)
    if subset == "quick":
        return [c for c in cells if c.get("quick")]
    raise SystemExit(f"unknown subset '{subset}' (use quick | full)")


def qc_verdict(row: dict[str, Any]) -> str:
    """The row's Fast QC verdict. A row with no QC block is a failure: every
    shipping generation carries one, so its absence means the evidence is not
    the engine's, not that the audio was clean."""
    qc = row.get("audioQC")
    if not isinstance(qc, dict):
        return "fail:missing-audioQC"
    verdict = qc.get("verdict")
    if isinstance(verdict, str):
        return verdict
    flags = qc.get("flags")
    if isinstance(flags, list) and flags:
        return "fail:" + ",".join(str(f) for f in flags)
    return "pass"


def finish_ok(row: dict[str, Any]) -> bool:
    reason = row.get("finishReason")
    if reason is None:
        return True
    if not isinstance(reason, str):
        return False
    normalized = reason.lower()
    # `eos` is the canonical successful stop for Qwen3 streaming generations.
    if normalized in {"eos", "completed", "complete", "done", "ok"}:
        return True
    if normalized in {"failed", "cancelled", "canceled", "superseded"}:
        return False
    # An unknown terminal reason is not a completed generation until the
    # vocabulary above learns it; guessing here would let a new failure mode
    # pass the hint gate silently.
    return False


def read_engine_rows(diag: str, run_id: str) -> list[dict[str, Any]]:
    engine_path = os.path.join(diag, "engine", "generations.jsonl")
    if not os.path.isfile(engine_path):
        # Pulled iOS mirror may nest under an extra directory level.
        for root, _dirs, files in os.walk(diag):
            if "generations.jsonl" in files and root.endswith(os.path.join("engine")):
                engine_path = os.path.join(root, "generations.jsonl")
                break
    if not os.path.isfile(engine_path):
        raise FileNotFoundError(engine_path)

    rows: list[dict[str, Any]] = []
    with open(engine_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            notes = row.get("notes") or {}
            if notes.get("benchRunID") == run_id:
                rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate language-bench languageHint telemetry")
    parser.add_argument("diag", help="diagnostics dir containing engine/generations.jsonl")
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--matrix",
        default=os.path.join(os.path.dirname(__file__), "..", "config", "language-bench-matrix.json"),
    )
    parser.add_argument(
        "--corpus",
        default=os.path.join(os.path.dirname(__file__), "..", "config", "language-bench-corpus.json"),
    )
    parser.add_argument("--subset", choices=("quick", "full"), default="full")
    parser.add_argument(
        "--plan",
        help="immutable language-run plan; enables generation/seed-level correlation",
    )
    parser.add_argument("--cohort", help="tracked diagnostic-cohort config used to create the plan")
    parser.add_argument(
        "--strict-qc",
        action="store_true",
        help="require audioQC verdict=pass for a diagnostic cohort (warnings fail)",
    )
    args = parser.parse_args()

    matrix = load_json(args.matrix)
    corpus = load_json(args.corpus)
    scripts = corpus_scripts(corpus)
    cells = select_cells(matrix, args.subset)

    missing_scripts = sorted({c["scriptLang"] for c in cells if c.get("scriptLang") not in scripts})
    if missing_scripts:
        print(f"FAIL: corpus missing scriptLang ids: {', '.join(missing_scripts)}", file=sys.stderr)
        return 1

    try:
        rows = read_engine_rows(args.diag, args.run_id)
    except FileNotFoundError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    by_cell: dict[str, list[dict[str, Any]]] = {}
    by_generation: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        notes = row.get("notes") or {}
        cell_id = notes.get("benchCell")
        if isinstance(cell_id, str):
            by_cell.setdefault(cell_id, []).append(row)
        generation_id = row.get("generationID")
        if isinstance(generation_id, str):
            by_generation.setdefault(generation_id, []).append(row)

    failures: list[str] = []
    planned_takes: list[dict[str, Any]] | None = None
    sentinels: dict[str, tuple[Path, dict[str, Any]]] = {}
    if args.plan:
        try:
            plan = load_evidence_json(Path(args.plan))
            planned_takes = validate_plan_against_sources(
                plan,
                matrix_path=Path(args.matrix),
                corpus_path=Path(args.corpus),
                subset=args.subset,
                cohort_path=Path(args.cohort) if args.cohort else None,
            )
            if plan.get("runID") != args.run_id:
                failures.append("run plan belongs to another run ID")
            if args.strict_qc and plan.get("kind") != "diagnosticCohort":
                failures.append("--strict-qc is reserved for diagnostic-cohort plans")
            if plan.get("kind") == "diagnosticCohort" and not args.strict_qc:
                failures.append("diagnostic-cohort plans require --strict-qc")
            sentinels = exact_sentinels(Path(args.diag), plan)
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
            failures.append(f"invalid run plan/evidence: {error}")
            planned_takes = []

    expected_count = len(planned_takes) if planned_takes is not None else len(cells)
    print(
        f"language-hint gate: runID={args.run_id} subset={args.subset} "
        f"expected={expected_count} engine={len(rows)}"
    )

    if planned_takes is not None:
        matrix_by_id = {cell["id"]: cell for cell in cells}
        expected_generation_ids: set[str] = set()
        equivalence: dict[tuple[str, int | None], list[tuple[str, str]]] = {}
        for take in planned_takes:
            cell_id = take["cellID"]
            child_id = take["childRunID"]
            cell = matrix_by_id.get(cell_id)
            if cell is None:
                failures.append(f"{child_id}: planned cell is outside selected matrix")
                continue
            sentinel_pair = sentinels.get(child_id)
            if sentinel_pair is None:
                failures.append(f"{child_id}: missing exact sentinel")
                continue
            record = sentinel_pair[1]
            generation_id = record.get("generationID")
            if not isinstance(generation_id, str):
                failures.append(f"{child_id}: sentinel lacks generationID")
                continue
            expected_generation_ids.add(generation_id)
            matched = by_generation.get(generation_id, [])
            if len(matched) != 1:
                failures.append(f"{child_id}: generation {generation_id} expected 1 row, got {len(matched)}")
                continue
            row = matched[0]
            notes = row.get("notes") or {}
            actual_hint = notes.get("languageHint")
            expected_hint = take.get("expectedHint")
            requested_hint = take.get("uiHint", "auto")
            if notes.get("benchRunID") != args.run_id or notes.get("benchCell") != cell_id:
                failures.append(f"{child_id}: engine run/cell correlation mismatch")
            if actual_hint != expected_hint:
                failures.append(f"{child_id}: languageHint {actual_hint!r} != expected {expected_hint!r}")
            if record.get("requestedLanguageHint") != requested_hint:
                failures.append(f"{child_id}: requestedLanguageHint does not match the plan")
            if record.get("languageHintSource") != expected_language_hint_source(requested_hint):
                failures.append(f"{child_id}: languageHintSource does not match the plan")
            if row.get("mode") != take.get("mode"):
                failures.append(f"{child_id}: mode {row.get('mode')!r} != expected {take.get('mode')!r}")
            expected_seed = take.get("seed")
            if seed_value(record.get("seed")) != expected_seed:
                failures.append(f"{child_id}: sentinel seed does not match the plan")
            if expected_seed is not None and seed_value(notes.get("samplingSeed")) != expected_seed:
                failures.append(f"{child_id}: engine samplingSeed does not match the plan")
            expected_variation = take.get("samplingVariation")
            if record.get("samplingVariation") != expected_variation:
                failures.append(f"{child_id}: sentinel sampling variation does not match the plan")
            if notes.get("samplingVariation") != expected_variation:
                failures.append(f"{child_id}: engine samplingVariation does not match the plan")
            group = take.get("promptEquivalenceGroup")
            if isinstance(group, str) and group:
                prompt_digest = record.get("resolvedPromptAssemblyDigest")
                if record.get("promptDigestScope") != "resolved":
                    failures.append(f"{child_id}: promptDigestScope must be 'resolved'")
                if not isinstance(prompt_digest, str) or len(prompt_digest) != 64:
                    failures.append(f"{child_id}: missing resolved prompt-assembly digest")
                else:
                    equivalence.setdefault((group, expected_seed), []).append((child_id, prompt_digest))
            if not finish_ok(row):
                failures.append(f"{child_id}: finishReason={row.get('finishReason')!r}")
            verdict = qc_verdict(row)
            if verdict.startswith("fail") or (args.strict_qc and verdict != "pass"):
                failures.append(f"{child_id}: audioQC {verdict}")
            print(
                f"  {cell_id:<28} take={take['takeIndex']:<2} seed={expected_seed!s:<8} "
                f"hint={actual_hint!s:<10} mode={row.get('mode', '?'):<8} QC={verdict}"
            )
        extra = sorted(set(by_generation) - expected_generation_ids)
        if extra:
            failures.append(f"unexpected current-run generation rows: {', '.join(extra)}")
        for (group, seed), members in sorted(equivalence.items()):
            if len(members) < 2:
                failures.append(f"prompt equivalence group {group} seed {seed} has fewer than two takes")
                continue
            digests = {digest for _identity, digest in members}
            if len(digests) != 1:
                failures.append(
                    f"prompt equivalence group {group} seed {seed} differs across "
                    + ", ".join(identity for identity, _digest in members)
                )
    else:
        for cell in cells:
            cell_id = cell["id"]
            expected_hint = cell["expectedHint"]
            matched = by_cell.get(cell_id, [])
            if len(matched) != 1:
                failures.append(f"{cell_id}: expected 1 row, got {len(matched)}")
                continue
            row = matched[0]
            notes = row.get("notes") or {}
            actual_hint = notes.get("languageHint")
            if actual_hint != expected_hint:
                failures.append(
                    f"{cell_id}: languageHint '{actual_hint}' != expected '{expected_hint}'"
                )
            if row.get("mode") != cell.get("mode"):
                failures.append(
                    f"{cell_id}: mode '{row.get('mode')}' != expected '{cell.get('mode')}'"
                )
            if not finish_ok(row):
                failures.append(
                    f"{cell_id}: finishReason={row.get('finishReason')!r}"
                )
            # The macOS lane seeds every cell with the same stable per-cell seed
            # the iOS plan uses and samples expressively; a row without that
            # identity is not a reproducible benchmark take.
            expected_seed = stable_default_seed(cell)
            if seed_value(notes.get("samplingSeed")) != expected_seed:
                failures.append(f"{cell_id}: engine samplingSeed {notes.get('samplingSeed')!r} != stable seed {expected_seed}")
            if notes.get("samplingVariation") != "expressive":
                failures.append(f"{cell_id}: engine samplingVariation {notes.get('samplingVariation')!r} != expressive")
            verdict = qc_verdict(row)
            if verdict.startswith("fail"):
                failures.append(f"{cell_id}: audioQC {verdict}")
            print(
                f"  {cell_id:<28} hint={actual_hint!s:<10} "
                f"mode={row.get('mode', '?'):<8} QC={verdict}"
            )

    if failures:
        print("FAIL:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
