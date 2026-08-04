#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import bench_delivery_prosody as prosody


class BenchCommandSourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (REPO / "Sources" / "VocelloCLI" / "BenchCommand.swift").read_text(
            encoding="utf-8"
        )

    def test_matrix_axes_use_strict_allowlist_validation(self) -> None:
        for option in ("modes", "variants", "lengths"):
            self.assertIn(f'args.string("{option}"),\n            option: "{option}"', self.source)
            self.assertIn(f'wasBareFlag: args.flag("{option}")', self.source)
        validator_start = self.source.index("private static func parseMatrixAxis(")
        validator = self.source[validator_start : self.source.index("static func printHelp()", validator_start)]
        self.assertIn("omittingEmptySubsequences: false", validator)
        self.assertIn("a comma-list value is required", validator)
        self.assertIn("!allowedSet.contains($0)", validator)
        self.assertIn("duplicate values are not allowed", validator)
        self.assertNotIn("skip unknown mode", self.source)

    def test_current_run_prosody_precedes_summary_and_receives_manifest(self) -> None:
        manifest = self.source.index("try writeResultsManifest(")
        prosody_call = self.source.index("try runDeliveryProsodyAnalysis(", manifest)
        summary_call = self.source.index("try runSummarizer(", manifest)
        self.assertLess(prosody_call, summary_call)
        self.assertIn('"--results-manifest", resultsManifest.path', self.source)

    def test_headless_cli_summary_is_explicitly_engine_only(self) -> None:
        summarizer = self.source[self.source.index("private static func runSummarizer"):]
        self.assertIn('"--run-id", runID,', summarizer)
        self.assertIn('"--evidence-manifest", evidenceManifest.path,', summarizer)
        self.assertIn('"--engine-only",', summarizer)

    def test_history_is_frozen_summarized_then_recorded(self) -> None:
        evidence = self.source.index("try prepareEngineHistoryEvidence(")
        summary = self.source.index("try runSummarizer(", evidence)
        record = self.source.index("try recordEngineHistory(", summary)
        self.assertLess(evidence, summary)
        self.assertLess(summary, record)
        preparation = self.source[self.source.index("private static func prepareEngineHistoryEvidence"):]
        self.assertIn('"--defer-record",', preparation)

    def test_missing_checkout_tools_retain_local_results(self) -> None:
        self.assertIn("if summarizerScript == nil, !noSummary, !telemetryOff", self.source)
        self.assertIn("if summarizerScript != nil {", self.source)
        self.assertIn("benchmark history not published; local manifest", self.source)

    def test_label_is_validated_before_runtime_or_generation_work(self) -> None:
        run_start = self.source.index("static func run(_ argv: [String]) async throws")
        label = self.source.index('let label = try validatedBenchmarkLabel(args.string("label"))', run_start)
        data_directory = self.source.index("let resolvedDataDir", label)
        generation = self.source.index("let runtime = try await CLIRuntime.bootstrap", data_directory)
        self.assertLess(label, data_directory)
        self.assertLess(label, generation)
        self.assertIn(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$", self.source)

    def test_memory_qualification_is_a_fixed_verbose_retention_protocol(self) -> None:
        self.assertIn('args.string("memory-qualification")', self.source)
        self.assertIn('rawPolicy == "retained-memory-v1"', self.source)
        self.assertIn('modes == ["custom", "design", "clone"]', self.source)
        self.assertIn('variants == ["speed"]', self.source)
        self.assertIn('lengths == ["medium"]', self.source)
        self.assertIn("warm == 3", self.source)
        self.assertIn("telemetryVerbose", self.source)
        self.assertIn("expectedTakeCount: 11", self.source)
        self.assertIn("let memoryQualification: BenchMemoryQualification?", self.source)
        self.assertIn('publisherSubcommand: memoryQualification == nil', self.source)
        self.assertIn('"memory-qualification"', self.source)
        self.assertIn('memoryQualification != nil && mode == .clone && n == 0', self.source)
        self.assertIn('let retainedWarmState', self.source)
        self.assertIn('intendedWarmState: retainedWarmState', self.source)

    def test_history_producing_benchmarks_default_to_verbose_memory_evidence(self) -> None:
        self.assertIn('args.string("telemetry") ?? "verbose"', self.source)
        self.assertIn("telemetryOff || telemetryVerbose || noSummary", self.source)
        self.assertIn("schema-v2 memory evidence", self.source)

    def test_zero_warm_is_an_explicit_cold_only_diagnostic_contract(self) -> None:
        self.assertIn("parsedWarm >= 0", self.source)
        self.assertIn("--warm must be a non-negative whole number", self.source)
        self.assertIn('warm == 0, modes.contains("clone")', self.source)
        self.assertIn('warm == 0, !deliveryItems.isEmpty', self.source)
        self.assertIn("Zero is", self.source)
        self.assertNotIn("let warm = max(1", self.source)

    def test_delivery_runs_archive_their_evidence(self) -> None:
        # 2026-08-04 audit: fixed per-cell filenames overwrote 17/18ths of the
        # DP-10 sweep's audio. Delivery runs must retain WAVs + manifests in a
        # per-run archive, fail-closed for the required files.
        self.assertIn("private static func archiveDeliveryEvidence(", self.source)
        self.assertIn("try archiveDeliveryEvidence(", self.source)
        self.assertIn("outputs/bench-archive", self.source)
        self.assertIn("evidence archive: missing required file", self.source)

    def test_delivery_cells_echo_their_instruction_and_default_to_strong(self) -> None:
        # Prompt-echo provenance (audit hardening item 2) plus the DP-8
        # ship-strong contract for bare preset names and the default set.
        self.assertIn("let deliveryInstruction: String?", self.source)
        self.assertIn("deliveryInstruction: item.instruction", self.source)
        self.assertIn("resolved an empty instruction", self.source)
        self.assertIn("use normal | strong", self.source)
        self.assertNotIn("subtle | normal | strong", self.source)
        self.assertIn(
            '["happy.strong", "calm.strong", "whisper.strong"]', self.source
        )


class BenchDeliveryProsodyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_dir = Path(self.temporary.name) / "data"
        self.diagnostics = self.data_dir / "diagnostics"
        self.bench_dir = self.data_dir / "outputs" / "bench"
        self.bench_dir.mkdir(parents=True)
        self.manifest = self.diagnostics / "benchmark-runs" / "run-current" / "bench-results.json"
        self.manifest.parent.mkdir(parents=True)

    @staticmethod
    def take(
        index: int,
        generation_id: str,
        name: str,
        *,
        delivery: str | None,
        mode: str = "custom",
        model: str = "pro_custom_speed",
        instruction: str | None = None,
    ) -> dict[str, object]:
        row: dict[str, object] = {
            "takeIndex": index,
            "generationID": generation_id,
            "outputFileName": name,
            "mode": mode,
            "modelID": model,
            "length": "medium",
            "warmState": "warm",
            "repetition": 0,
            "delivery": delivery,
        }
        if delivery is not None:
            row["deliveryInstruction"] = (
                instruction if instruction is not None else f"Speak {delivery}."
            )
        return row

    def write_manifest(self, takes: list[dict[str, object]]) -> None:
        self.manifest.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "runID": "run-current",
                    "label": "unit",
                    "seed": 9320,
                    "takes": takes,
                }
            ),
            encoding="utf-8",
        )
        for take in takes:
            (self.bench_dir / str(take["outputFileName"])).touch()

    def write_engine_rows(
        self,
        takes: list[dict[str, object]],
        prompt_chars: dict[str, int] | None = None,
        instruct_receipts: dict[str, dict[str, object] | None] | None = None,
    ) -> None:
        """Engine telemetry rows carrying the provenance the sidecar joins on.

        By default a delivery take gets an instruction receipt whose digest
        matches its manifest echo (a correctly plumbed instruction); pass
        ``instruct_receipts={generation_id: None}`` to drop the receipt or a
        dict to override its fields."""
        import hashlib as _hashlib
        engine_dir = self.diagnostics / "engine"
        engine_dir.mkdir(parents=True, exist_ok=True)
        lines = []
        for take in takes:
            generation_id = str(take["generationID"])
            default_chars = 300 if take.get("delivery") else 200
            notes: dict[str, object] = {
                "benchRunID": "run-current",
                "promptChars": (prompt_chars or {}).get(
                    generation_id, default_chars
                ),
                "promptDigest": f"digest-{generation_id}",
                "samplingObservedSeed": "9320",
            }
            if take.get("delivery"):
                echo = str(take.get("deliveryInstruction") or "")
                receipt: dict[str, object] | None = {
                    "instructChars": len(echo),
                    "instructDigest": _hashlib.sha256(echo.encode("utf-8")).hexdigest(),
                }
                if instruct_receipts is not None and generation_id in instruct_receipts:
                    receipt = instruct_receipts[generation_id]
                if receipt is not None:
                    notes.update(receipt)
            lines.append(json.dumps({"generationID": generation_id, "notes": notes}))
        (engine_dir / "generations.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    @staticmethod
    def metrics(path: str) -> dict[str, float]:
        instructed = "_d-" in Path(path).name
        return {
            "durationSec": 2.5,
            "f0_std_hz": 30.0 if instructed else 20.0,
            "rate_cv": 0.4 if instructed else 0.3,
            "pause_ratio": 0.1 if instructed else 0.2,
            "energy_roughness": 0.25 if instructed else 0.2,
            # Full analyzer fields consumed by the per-take prosody gate.
            "f0_turning_points_per_sec": 2.0,
            "rate_syllable_rate_hz": 4.0,
            "pauses_pause_speech_ratio": 0.1 if instructed else 0.2,
            "energy_envelope_roughness": 0.25 if instructed else 0.2,
            "rate_local_rate_cv": 0.4 if instructed else 0.3,
            "pauses_max_pause_seconds": 0.4,
        }

    def test_analysis_ignores_stale_shared_outputs(self) -> None:
        neutral = "custom_pro_custom_speed_medium_warm_0.wav"
        delivery = "custom_pro_custom_speed_medium_warm_d-happy.strong_0.wav"
        takes = [
            self.take(1, "neutral-current", neutral, delivery=None),
            self.take(2, "delivery-current", delivery, delivery="happy.strong"),
        ]
        self.write_manifest(takes)
        self.write_engine_rows(takes)
        # These valid-looking older files must never be discovered without a
        # corresponding current-run manifest entry.
        (self.bench_dir / "design_pro_design_speed_medium_warm_0.wav").touch()
        (self.bench_dir / "design_pro_design_speed_medium_warm_d-calm.normal_0.wav").touch()

        with mock.patch.object(prosody, "analyze", side_effect=self.metrics) as analyzer:
            results = prosody.analyze_run(self.diagnostics, self.manifest)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["runID"], "run-current")
        self.assertEqual(results[0]["generationID"], "delivery-current")
        self.assertEqual(results[0]["neutralGenerationID"], "neutral-current")
        self.assertEqual(results[0]["deliveryWav"], delivery)
        self.assertEqual(results[0]["neutralWav"], neutral)
        # Prompt provenance rides every row (audit hardening item 2).
        self.assertEqual(results[0]["seed"], 9320)
        self.assertEqual(results[0]["runLabel"], "unit")
        self.assertEqual(results[0]["instructEcho"], "Speak happy.strong.")
        self.assertEqual(results[0]["promptChars"], 300)
        self.assertEqual(results[0]["neutralPromptChars"], 200)
        self.assertEqual(results[0]["promptDigest"], "digest-delivery-current")
        analyzed_names = {Path(call.args[0]).name for call in analyzer.call_args_list}
        self.assertEqual(analyzed_names, {neutral, delivery})
        # Per-take prosody gate verdict rides the sidecar row, computed from
        # the same single analysis pass (no extra analyze calls).
        gate = results[0]["qualityGate"]
        self.assertIs(gate["passed"], True)
        self.assertEqual(gate["flags"], [])
        self.assertIn("f0_std_hz", gate["metrics"])
        self.assertEqual(len(analyzer.call_args_list), 2)

    def test_quality_gate_flags_ride_the_sidecar_row(self) -> None:
        neutral = "custom_pro_custom_speed_medium_warm_0.wav"
        delivery = "custom_pro_custom_speed_medium_warm_d-calm.normal_0.wav"
        takes = [
            self.take(1, "neutral-current", neutral, delivery=None),
            self.take(2, "delivery-current", delivery, delivery="calm.normal"),
        ]
        self.write_manifest(takes)
        self.write_engine_rows(takes)

        def monotone_metrics(path: str) -> dict[str, float]:
            metrics = dict(self.metrics(path))
            metrics["f0_std_hz"] = 0.1
            metrics["f0_turning_points_per_sec"] = 0.1
            return metrics

        with mock.patch.object(prosody, "analyze", side_effect=monotone_metrics):
            results = prosody.analyze_run(self.diagnostics, self.manifest)
        gate = results[0]["qualityGate"]
        self.assertIs(gate["passed"], False)
        self.assertIn("monotone", gate["flags"])

    def test_missing_current_run_neutral_fails(self) -> None:
        delivery = "custom_pro_custom_speed_medium_warm_d-happy.strong_0.wav"
        self.write_manifest([self.take(1, "delivery-current", delivery, delivery="happy.strong")])
        with self.assertRaisesRegex(ValueError, "no neutral reference"):
            prosody.analyze_run(self.diagnostics, self.manifest)

    def test_instruction_that_did_not_reach_the_engine_fails(self) -> None:
        neutral = "custom_pro_custom_speed_medium_warm_0.wav"
        delivery = "custom_pro_custom_speed_medium_warm_d-happy.strong_0.wav"
        takes = [
            self.take(1, "neutral-current", neutral, delivery=None),
            self.take(2, "delivery-current", delivery, delivery="happy.strong"),
        ]
        self.write_manifest(takes)
        # No engine-side instruction receipt means the instruction never
        # entered the request: exactly the silent plumbing null the provenance
        # check exists to catch. (Prompt lengths are equal by design — the
        # script text never includes the instruction — so they prove nothing.)
        self.write_engine_rows(takes, instruct_receipts={"delivery-current": None})
        with mock.patch.object(prosody, "analyze", side_effect=self.metrics):
            with self.assertRaisesRegex(ValueError, "did not reach the engine"):
                prosody.analyze_run(self.diagnostics, self.manifest)

    def test_receipt_digest_mismatch_fails(self) -> None:
        neutral = "custom_pro_custom_speed_medium_warm_0.wav"
        delivery = "custom_pro_custom_speed_medium_warm_d-happy.strong_0.wav"
        takes = [
            self.take(1, "neutral-current", neutral, delivery=None),
            self.take(2, "delivery-current", delivery, delivery="happy.strong"),
        ]
        self.write_manifest(takes)
        self.write_engine_rows(
            takes,
            instruct_receipts={
                "delivery-current": {"instructChars": 12, "instructDigest": "deadbeef"}
            },
        )
        with mock.patch.object(prosody, "analyze", side_effect=self.metrics):
            with self.assertRaisesRegex(ValueError, "does not match"):
                prosody.analyze_run(self.diagnostics, self.manifest)

    def test_neutral_cell_with_receipt_passes_and_prompt_lengths_are_ignored(self) -> None:
        # DP-18: the neutral preset's cell is an ordinary instructed take under
        # receipt semantics — its instruction is real even though the prompt
        # lengths tie the reference's (the script never includes instructions).
        neutral = "custom_pro_custom_speed_medium_warm_0.wav"
        delivery = "custom_pro_custom_speed_medium_warm_d-neutral.strong_0.wav"
        takes = [
            self.take(1, "neutral-current", neutral, delivery=None),
            self.take(2, "delivery-current", delivery, delivery="neutral.strong"),
        ]
        self.write_manifest(takes)
        self.write_engine_rows(
            takes, prompt_chars={"neutral-current": 200, "delivery-current": 200}
        )
        with mock.patch.object(prosody, "analyze", side_effect=self.metrics):
            results = prosody.analyze_run(self.diagnostics, self.manifest)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["delivery"], "neutral.strong")

    def test_receipt_on_the_neutral_reference_fails(self) -> None:
        # An instruction on the reference poisons every paired delta.
        neutral = "custom_pro_custom_speed_medium_warm_0.wav"
        delivery = "custom_pro_custom_speed_medium_warm_d-happy.strong_0.wav"
        takes = [
            self.take(1, "neutral-current", neutral, delivery=None),
            self.take(2, "delivery-current", delivery, delivery="happy.strong"),
        ]
        self.write_manifest(takes)
        self.write_engine_rows(
            takes,
            instruct_receipts={
                "neutral-current": {"instructChars": 20, "instructDigest": "aa"}
            },
        )
        # The fixture writer only stamps receipts on delivery takes; force one
        # onto the reference row by rewriting it with a delivery marker first.
        import hashlib as _hashlib
        engine_dir = self.diagnostics / "engine"
        echo = "Speak happy.strong."
        rows = [
            {"generationID": "neutral-current", "notes": {
                "benchRunID": "run-current", "promptChars": 200,
                "promptDigest": "digest-neutral-current",
                "samplingObservedSeed": "9320",
                "instructChars": 20, "instructDigest": "aa"}},
            {"generationID": "delivery-current", "notes": {
                "benchRunID": "run-current", "promptChars": 300,
                "promptDigest": "digest-delivery-current",
                "samplingObservedSeed": "9320",
                "instructChars": len(echo),
                "instructDigest": _hashlib.sha256(echo.encode()).hexdigest()}},
        ]
        (engine_dir / "generations.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
        )
        with mock.patch.object(prosody, "analyze", side_effect=self.metrics):
            with self.assertRaisesRegex(ValueError, "reference is not neutral"):
                prosody.analyze_run(self.diagnostics, self.manifest)

    def test_missing_engine_row_fails(self) -> None:
        neutral = "custom_pro_custom_speed_medium_warm_0.wav"
        delivery = "custom_pro_custom_speed_medium_warm_d-happy.strong_0.wav"
        takes = [
            self.take(1, "neutral-current", neutral, delivery=None),
            self.take(2, "delivery-current", delivery, delivery="happy.strong"),
        ]
        self.write_manifest(takes)
        self.write_engine_rows(takes[:1])
        with mock.patch.object(prosody, "analyze", side_effect=self.metrics):
            with self.assertRaisesRegex(ValueError, "no engine telemetry row"):
                prosody.analyze_run(self.diagnostics, self.manifest)

    def test_empty_delivery_instruction_fails(self) -> None:
        neutral = "custom_pro_custom_speed_medium_warm_0.wav"
        delivery = "custom_pro_custom_speed_medium_warm_d-happy.strong_0.wav"
        takes = [
            self.take(1, "neutral-current", neutral, delivery=None),
            self.take(
                2, "delivery-current", delivery, delivery="happy.strong", instruction="  "
            ),
        ]
        self.write_manifest(takes)
        self.write_engine_rows(takes)
        with mock.patch.object(prosody, "analyze", side_effect=self.metrics):
            with self.assertRaisesRegex(ValueError, "empty deliveryInstruction"):
                prosody.analyze_run(self.diagnostics, self.manifest)

    def test_filename_manifest_disagreement_fails(self) -> None:
        neutral = "custom_pro_custom_speed_medium_warm_0.wav"
        take = self.take(1, "neutral-current", neutral, delivery=None)
        take["length"] = "long"
        self.write_manifest([take])
        with self.assertRaisesRegex(ValueError, "disagrees with manifest fields"):
            prosody.collect_run_outputs(self.bench_dir, self.manifest)

    def test_sidecar_write_replaces_stale_content_atomically(self) -> None:
        self.diagnostics.mkdir(parents=True, exist_ok=True)
        output = self.diagnostics / "bench-prosody.json"
        output.write_text("stale", encoding="utf-8")
        rows = [{"runID": "run-current", "generationID": "delivery-current"}]
        written = prosody.write_results(self.diagnostics, rows)
        self.assertEqual(written, output)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), rows)
        self.assertEqual(list(self.diagnostics.glob(".bench-prosody-*.json")), [])


if __name__ == "__main__":
    unittest.main()
