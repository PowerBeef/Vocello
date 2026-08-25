#!/usr/bin/env python3
"""Tests for the governed automatic delivery-prompt remediation layer."""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_experiment_runner import analyze_execution, run_execution_plan  # noqa: E402
from delivery_prompt_remediation import (  # noqa: E402
    DEFAULT_CONTRACT,
    RESULT_VOCABULARY,
    RemediationError,
    _reseal_plan,
    candidate_by_id,
    create_candidate_plan,
    decide,
    seed_reference_controls,
    validate_candidate_plan,
    validate_contract,
)


FAKE_BINARY = r'''#!/usr/bin/env python3
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import wave

PRESETS = ("neutral", "happy", "sad", "angry", "fearful", "surprised", "calm", "whisper")
args = sys.argv[1:]
if args[0] == "deliveries":
    print(json.dumps([
        {"preset": preset, "instruction": f"Production {preset}.",
         "intensity": "normal" if preset in {"happy", "angry"} else "strong"}
        for preset in PRESETS
    ]))
    raise SystemExit(0)
if args[0] != "generate":
    raise SystemExit(2)
def value(flag):
    return args[args.index(flag) + 1]
out = Path(value("--out"))
out.parent.mkdir(parents=True, exist_ok=True)
with wave.open(str(out), "wb") as wav:
    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
    samples = [int(8000 * math.sin(2 * math.pi * 180 * i / 24000)) for i in range(24000)]
    wav.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))
instruction = value("--delivery").strip()
counter = Path(os.environ["FAKE_REMEDIATION_COUNTER"])
count = int(counter.read_text() or "0") if counter.exists() else 0
counter.write_text(str(count + 1))
print(json.dumps({
    "generationID": hashlib.sha256(out.name.encode()).hexdigest()[:32],
    "audioPath": str(out), "durationSeconds": 1.0, "wallSeconds": 0.1,
    "finishReason": "eos",
    "deliveryInstructionChars": len(instruction),
    "deliveryInstructionDigest": hashlib.sha256(instruction.encode()).hexdigest(),
}))
'''


class DeliveryPromptRemediationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.binary = self.root / "vocello-fake"
        self.binary.write_text(FAKE_BINARY, encoding="utf-8")
        self.binary.chmod(self.binary.stat().st_mode | stat.S_IXUSR)
        self.counter = self.root / "calls.txt"
        self.previous_counter = os.environ.get("FAKE_REMEDIATION_COUNTER")
        os.environ["FAKE_REMEDIATION_COUNTER"] = str(self.counter)
        self.contract = json.loads(DEFAULT_CONTRACT.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        if self.previous_counter is None:
            os.environ.pop("FAKE_REMEDIATION_COUNTER", None)
        else:
            os.environ["FAKE_REMEDIATION_COUNTER"] = self.previous_counter
        self.temporary.cleanup()

    def _tiny_pair(self, plan: dict) -> dict:
        remediation = plan["remediation"]
        target = remediation["targetPreset"]
        competitor = remediation["competingPreset"]
        target_row = next(row for row in plan["rows"] if row["preset"] == target)
        competitor_row = next(
            row for row in plan["rows"]
            if row["preset"] == competitor
            and row["speakerID"] == target_row["speakerID"]
            and row["outputLanguage"] == target_row["outputLanguage"]
            and row["seed"] == target_row["seed"]
            and row["script"]["sha256"] == target_row["script"]["sha256"]
        )
        plan["rows"] = [target_row, competitor_row]
        return _reseal_plan(plan)

    def _run_pair(self, candidate_id: str = "surprised-onset-v2") -> tuple[Path, Path, dict, dict]:
        baseline = self._tiny_pair(create_candidate_plan(
            binary=self.binary, contract=self.contract, candidate_id=candidate_id,
            stage_name="screen", variant="speed", baseline=True,
        ))
        candidate = self._tiny_pair(create_candidate_plan(
            binary=self.binary, contract=self.contract, candidate_id=candidate_id,
            stage_name="screen", variant="speed", baseline=False,
        ))
        baseline_dir = self.root / "baseline"
        candidate_dir = self.root / "candidate"
        run_execution_plan(
            plan=baseline, binary=self.binary, data_dir=None, run_dir=baseline_dir,
            lock_root=self.root / "lock",
        )
        analyze_execution(baseline, baseline_dir)
        seed_reference_controls(
            baseline_run=baseline_dir, candidate_plan=candidate,
            candidate_run=candidate_dir, binary=self.binary,
            contract=self.contract, candidate_id=candidate_id,
            stage_name="screen", variant="speed",
        )
        run_execution_plan(
            plan=candidate, binary=self.binary, data_dir=None, run_dir=candidate_dir,
            lock_root=self.root / "lock",
        )
        analyze_execution(candidate, candidate_dir)
        return baseline_dir, candidate_dir, baseline, candidate

    def test_contract_pins_candidate_text_stages_and_authority_boundary(self) -> None:
        validated = validate_contract(self.contract)
        self.assertEqual(tuple(validated["resultVocabulary"]), RESULT_VOCABULARY)
        self.assertFalse(validated["acceptance"]["allowAutomaticSemanticPromotion"])
        self.assertEqual(len(validated["candidates"]), 6)
        changed = copy.deepcopy(self.contract)
        changed["candidates"][0]["instruction"] += " changed"
        with self.assertRaisesRegex(RemediationError, "digest mismatch"):
            validate_contract(changed)
        changed = copy.deepcopy(self.contract)
        changed["acceptance"]["allowAutomaticSemanticPromotion"] = True
        with self.assertRaisesRegex(RemediationError, "must remain disabled"):
            validate_contract(changed)

    def test_candidate_plan_changes_only_target_instruction_and_is_source_bound(self) -> None:
        plan = create_candidate_plan(
            binary=self.binary, contract=self.contract,
            candidate_id="fearful-urgent-v2", stage_name="screen",
            variant="speed", baseline=False,
        )
        validate_candidate_plan(
            plan, self.binary, self.contract, candidate_id="fearful-urgent-v2",
            stage_name="screen", variant="speed", role="candidate",
        )
        candidate = candidate_by_id(self.contract, "fearful-urgent-v2")
        target = [row for row in plan["rows"] if row["preset"] == "fearful"]
        control = [row for row in plan["rows"] if row["preset"] == "sad"]
        self.assertTrue(target and control)
        self.assertEqual({row["instruction"]["sha256"] for row in target}, {candidate["instructionSHA256"]})
        self.assertEqual({row["instruction"]["arm"] for row in control}, {"current"})
        self.assertEqual(plan["screeningSelection"]["scope"], "contract-screen")
        self.assertFalse(plan["remediation"]["semanticAuthority"])

    def test_confirmation_plan_is_contract_selected_and_covers_both_variants(self) -> None:
        for variant in ("speed", "quality"):
            plan = create_candidate_plan(
                binary=self.binary, contract=self.contract,
                candidate_id="happy-acoustic-v2", stage_name="variant-confirmation",
                variant=variant, baseline=False,
            )
            self.assertEqual({row["variant"] for row in plan["rows"]}, {variant})
            self.assertEqual(len({row["seed"] for row in plan["rows"]}), 8)
            self.assertEqual(len({(row["speakerID"], row["outputLanguage"]) for row in plan["rows"]}), 13)
            self.assertEqual({row["script"]["length"] for row in plan["rows"]}, {"short", "medium", "long"})

    def test_neutral_reference_is_reused_without_another_model_launch(self) -> None:
        baseline_dir, candidate_dir, _baseline, _candidate = self._run_pair()
        # One shared neutral control + two baseline takes + two candidate takes.
        # Reuse prevents a second neutral-control launch for the candidate arm.
        self.assertEqual(int(self.counter.read_text()), 5)
        baseline_state = json.loads((baseline_dir / "execution-state.json").read_text())
        candidate_state = json.loads((candidate_dir / "execution-state.json").read_text())
        self.assertEqual(set(baseline_state["references"]), set(candidate_state["references"]))
        source = baseline_dir / next(iter(baseline_state["references"].values()))["audio"]
        reused = candidate_dir / next(iter(candidate_state["references"].values()))["audio"]
        self.assertEqual(source.stat().st_ino, reused.stat().st_ino)

    def test_preset_specific_temporal_improvement_can_advance_without_semantic_authority(self) -> None:
        baseline_dir, candidate_dir, _baseline, _candidate = self._run_pair()
        payload = json.loads((candidate_dir / "acoustic-layer.json").read_text())
        for row in payload["rows"]:
            if row["preset"] != "surprised":
                continue
            row["derivedFeatures"]["pitch_shift_semitones"] = 2.0
            contours = row["temporalDeltaV1"]["derivedContours"]
            contours.update({
                "onsetToPeakPitchHz": 30.0,
                "maximumLocalRiseHz": 24.0,
                "normalizedPeakPosition": -0.5,
                "peakToEndPitchHz": -20.0,
                "contourAbruptnessHz": 25.0,
                "phraseFinalPitchSlopeHz": -10.0,
            })
            row["deliveryVerdict"]["passed"] = True
        (candidate_dir / "acoustic-layer.json").write_text(json.dumps(payload), encoding="utf-8")
        report = decide(
            baseline_run=baseline_dir, candidate_run=candidate_dir,
            binary=self.binary, contract=self.contract,
            candidate_id="surprised-onset-v2", stage_name="screen", variant="speed",
        )
        self.assertEqual(report["result"], "automatic_acoustic_improvement")
        self.assertTrue(report["eligibleForNextStage"])
        self.assertFalse(report["semanticAuthority"])
        self.assertFalse(report["productionCopyAuthority"])
        self.assertGreater(report["competingPresetDistance"]["medianDelta"], 0)

    def test_missing_temporal_feature_abstains_instead_of_leaving_the_denominator(self) -> None:
        baseline_dir, candidate_dir, _baseline, _candidate = self._run_pair()
        payload = json.loads((candidate_dir / "acoustic-layer.json").read_text())
        target = next(row for row in payload["rows"] if row["preset"] == "surprised")
        del target["temporalDeltaV1"]["derivedContours"]["onsetToPeakPitchHz"]
        (candidate_dir / "acoustic-layer.json").write_text(json.dumps(payload), encoding="utf-8")
        report = decide(
            baseline_run=baseline_dir, candidate_run=candidate_dir,
            binary=self.binary, contract=self.contract,
            candidate_id="surprised-onset-v2", stage_name="screen", variant="speed",
        )
        self.assertEqual(report["result"], "abstained_out_of_distribution")
        self.assertIn("temporal:onsetToPeakPitchHz", report["missingFeatures"])
        self.assertEqual(report["plannedPairCount"], 1)


if __name__ == "__main__":
    unittest.main()
