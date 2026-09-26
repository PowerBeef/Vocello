#!/usr/bin/env python3
"""The audio QC judge registry: tiers, exclusions, retirements, adoption and snapshot pins."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio_qc_judges import (  # noqa: E402
    JudgeRegistryError,
    excluded_imports,
    judge_for_adapter,
    load_registry,
    require_executable,
    validate_registry,
    validate_repository,
    verify_hub_snapshot,
    verify_judge_snapshot,
)
import clone_speaker_similarity  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = (
    "config/audio-qc-judges.json",
    "config/delivery-evaluator-v2-candidates.json",
    "config/delivery-evaluator-v2-contract.json",
    "config/delivery-experiment-contract.json",
    "benchmarks/hardware-profiles.json",
)


class JudgeRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_registry()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _errors(self, mutate) -> list[str]:
        registry = copy.deepcopy(self.registry)
        mutate(registry)
        return validate_registry(registry, root=REPO)

    def _repository_copy(self) -> Path:
        """A minimal repository: the contracts, the files the registry names, an empty scripts/."""
        for relative in CONTRACTS:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / relative, target)
        for judge in self.registry["judges"].values():
            if judge["status"] == "retired":
                continue
            for relative in judge.get("legacyIdentifiers", {}).get("sources", []):
                target = self.root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("# fixture\n", encoding="utf-8")
        (self.root / "scripts").mkdir(exist_ok=True)
        return self.root

    def _rewrite(self, relative: str, mutate) -> None:
        path = self.root / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_tracked_registry_matches_the_repository(self) -> None:
        self.assertEqual(validate_repository(REPO), [])

    def test_no_judge_outside_retired_is_tier_c_or_unknown(self) -> None:
        judges = self.registry["judges"]
        for judge_id, judge in judges.items():
            with self.subTest(judge=judge_id):
                self.assertIn(judge["license"]["tier"], ("A", "B", "C"))
                if judge["status"] != "retired":
                    self.assertIn(judge["license"]["tier"], ("A", "B"))
        retired = {judge_id for judge_id, judge in judges.items() if judge["status"] == "retired"}
        self.assertEqual(retired, {"quality.nisqa-v2@1", "quality.utmosv2@1", "emotion.ser-wav2vec2-xlsr@2"})
        nisqa = judges["quality.nisqa-v2@1"]["license"]
        self.assertEqual((nisqa["tier"], nisqa["commercialUseCompatible"]), ("C", False))
        self.assertIn("CC BY-NC-SA 4.0", nisqa["weights"])

        def tier_c(registry):
            registry["judges"]["speaker.ecapa-voxceleb@1"]["license"]["tier"] = "C"
            registry["judges"]["speaker.ecapa-voxceleb@1"]["license"]["commercialUseCompatible"] = False
        self.assertIn("judge speaker.ecapa-voxceleb@1: a tier-C judge must be retired", self._errors(tier_c))

        def unknown(registry):
            del registry["judges"]["prosody@3"]["license"]["tier"]
        self.assertIn("judge prosody@3: license tier is unknown", self._errors(unknown))

        def quarantined_c(registry):
            registry["judges"]["quality.utmosv2@1"]["status"] = "quarantined"
        self.assertTrue(any("tier-C judge must be retired" in e for e in self._errors(quarantined_c)))

        def mislabeled(registry):
            registry["judges"]["quality.nisqa-v2@1"]["license"]["commercialUseCompatible"] = True
        self.assertTrue(any("contradicts tier C" in e for e in self._errors(mislabeled)))

    def test_tier_b_is_internal_evaluation_that_never_ships(self) -> None:
        def unaccepted(registry):
            del registry["judges"]["asr.whisper-small@1"]["tierBAcceptance"]
        self.assertTrue(any("decision-2a" in e for e in self._errors(unaccepted)))

        def shipped(registry):
            registry["judges"]["speaker.ecapa-voxceleb@1"]["ships"] = True
        self.assertIn("judge speaker.ecapa-voxceleb@1: a tier-B judge never ships", self._errors(shipped))

    def test_a_judge_from_the_generator_lab_never_votes(self) -> None:
        def same_lab(registry):
            registry["judges"]["asr.whisper-small@1"]["independence"]["generatorLabCorrelated"] = True
        self.assertTrue(any("never votes" in e for e in self._errors(same_lab)))

    def test_supervisor_provenance_is_never_output_identity(self) -> None:
        def leaked(registry):
            registry["judges"]["compact.distilhubert@1"]["identity"]["output"].append("resourceSupervisorSHA256")
        self.assertTrue(any("never output identity" in e for e in self._errors(leaked)))

    def test_runnable_neural_judges_load_only_after_digest_verification(self) -> None:
        def unpinned(registry):
            registry["judges"]["speaker.ecapa-voxceleb@1"]["pins"]["digestStatus"] = "revision-only"
        self.assertTrue(any("digest status" in e for e in self._errors(unpinned)))

        def empty(registry):
            registry["judges"]["asr.whisper-small@1"]["pins"]["files"] = {}
        self.assertTrue(any("lists its file digests" in e for e in self._errors(empty)))

    def test_exclusion_list_refuses_excluded_models_and_packages(self) -> None:
        def excluded_model(registry):
            registry["judges"]["compact.distilhubert@1"]["pins"]["repository"] = "utter-project/mHuBERT-147"
        self.assertTrue(any("mhubert-147-and-versa" in e for e in self._errors(excluded_model)))

        def excluded_package(registry):
            registry["judges"]["compact.distilhubert@1"]["pins"]["runtime"]["pykakasi"] = "2.3.0"
        self.assertTrue(any("package pykakasi is excluded" in e for e in self._errors(excluded_package)))

        def uncovered(registry):
            registry["excluded"] = [e for e in registry["excluded"] if e["id"] != "utmosv2"]
        self.assertIn("judge quality.utmosv2@1: a retired tier-C judge must be on the exclusion list",
                      self._errors(uncovered))

        root = self._repository_copy()
        self._rewrite("config/delivery-evaluator-v2-candidates.json",
                      lambda value: value["candidates"]["distilhubert"]["runtimeDependencies"].update(zhconv="1.4.3"))
        self.assertTrue(any("package zhconv is excluded" in e for e in validate_repository(root)))

    def test_exclusion_list_refuses_excluded_imports(self) -> None:
        scripts = self.root / "scripts"
        (scripts / "lib").mkdir(parents=True)
        (scripts / "clean.py").write_text("import numpy\nfrom pathlib import Path\n", encoding="utf-8")
        (scripts / "lib/japanese.py").write_text("import pykakasi\n", encoding="utf-8")
        (scripts / "aligner.py").write_text("from torchaudio.pipelines import MMS_FA\n", encoding="utf-8")
        (scripts / "quality.py").write_text(
            "def score():\n    from torchmetrics.functional.audio import nisqa\n    return nisqa\n",
            encoding="utf-8",
        )
        (scripts / "mos.py").write_text("import utmosv2.model\n", encoding="utf-8")
        errors = excluded_imports(scripts, self.registry)
        self.assertEqual(sorted(error.split(":")[0] for error in errors), [
            "scripts/aligner.py", "scripts/lib/japanese.py", "scripts/mos.py", "scripts/quality.py",
        ])
        self.assertEqual(excluded_imports(REPO / "scripts", self.registry), [])

    def test_retired_judges_stay_out_of_every_qc_path(self) -> None:
        root = self._repository_copy()
        self.assertEqual(validate_repository(root), [])
        (root / "scripts/mos_advisory.py").write_text("# fixture\n", encoding="utf-8")
        self.assertIn("judge quality.utmosv2@1: retired judge's scripts/mos_advisory.py still exists",
                      validate_repository(root))
        (root / "scripts/mos_advisory.py").unlink()
        self._rewrite("config/delivery-evaluator-v2-contract.json",
                      lambda value: value["cascade"]["finalistsOnly"].append("utmos"))
        self.assertIn("judge quality.utmosv2@1: cascade layer utmos is still requested", validate_repository(root))
        shutil.copyfile(REPO / "config/delivery-evaluator-v2-contract.json",
                        root / "config/delivery-evaluator-v2-contract.json")
        self._rewrite("config/delivery-experiment-contract.json",
                      lambda value: value["promotionGuardrails"].update(maximumMedianRelativeUTMOSRegression=0.1))
        self.assertIn("judge quality.utmosv2@1: guardrail maximumMedianRelativeUTMOSRegression still gates promotion",
                      validate_repository(root))
        shutil.copyfile(REPO / "config/delivery-experiment-contract.json",
                        root / "config/delivery-experiment-contract.json")

        def revive(value):
            value["candidateOrder"].append("nisqa-v2")
            value["candidates"]["nisqa-v2"] = value["retiredCandidates"]["nisqa-v2"]
        self._rewrite("config/delivery-evaluator-v2-candidates.json", revive)
        errors = validate_repository(root)
        self.assertIn("candidate nisqa-v2: registry judge quality.nisqa-v2@1 is retired", errors)
        self.assertIn("judge quality.nisqa-v2@1: adapter nisqa-v2 is still a live candidate", errors)

    def test_adoption_requires_two_clean_canonical_host_runs(self) -> None:
        root = self._repository_copy()
        self._rewrite("config/delivery-experiment-contract.json", lambda value: value["externalModelPolicy"].update(
            required=["measured-eight-gigabyte-memory-compatibility"]))
        errors = validate_repository(root)
        self.assertIn("config/delivery-experiment-contract.json: adoption must require two-clean-canonical-host-runs",
                      errors)
        self.assertIn("config/delivery-experiment-contract.json: adoption still names the 8 GB host", errors)
        shutil.copyfile(REPO / "config/delivery-experiment-contract.json",
                        root / "config/delivery-experiment-contract.json")

        def two_canonical(value):
            for profile in value["profiles"]:
                if profile["platform"] == "macos":
                    profile["canonical"] = True
        self._rewrite("benchmarks/hardware-profiles.json", two_canonical)
        self.assertIn("adoption must select exactly one canonical hardware profile", validate_repository(root))

    def test_execution_gate_refuses_blocked_or_unlicensed_judges(self) -> None:
        judge_id, judge = judge_for_adapter("whisper-small-mlx", self.registry)
        self.assertEqual(judge_id, "asr.whisper-small@1")
        self.assertIs(require_executable(judge_id, judge), judge)
        for status in ("retired", "quarantined"):
            blocked = dict(judge, status=status)
            with self.assertRaisesRegex(JudgeRegistryError, status):
                require_executable(judge_id, blocked)
        unknown = copy.deepcopy(judge)
        unknown["license"].pop("tier")
        with self.assertRaisesRegex(JudgeRegistryError, "license tier"):
            require_executable(judge_id, unknown)
        with self.assertRaisesRegex(JudgeRegistryError, "not registered"):
            judge_for_adapter("utmosv2", self.registry)


def _hub_snapshot(root: Path, files: dict[str, bytes], *, large: set[str]) -> Path:
    """A Hugging Face cache layout: blobs named by content address, snapshot symlinks."""
    blobs = root / "blobs"
    snapshot = root / "snapshots" / ("0" * 40)
    blobs.mkdir(parents=True)
    for name, content in files.items():
        if name in large:
            address = hashlib.sha256(content).hexdigest()
        else:
            address = hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()
        (blobs / address).write_bytes(content)
        link = snapshot / name
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(Path("../..") / "blobs" / address if "/" not in name
                        else Path("../../..") / "blobs" / address)
    return snapshot


class HubSnapshotVerificationTests(unittest.TestCase):
    FILES = {
        "hyperparams.yaml": b"pretrainer: fixture\n",
        "embedding_model.ckpt": b"fixture embedding weights",
        "nested/label_encoder.txt": b"'id10001' => 0\n",
    }

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.snapshot = _hub_snapshot(self.root, self.FILES, large={"embedding_model.ckpt"})

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_content_addressed_snapshot_verifies_and_reports_file_digests(self) -> None:
        digests = verify_hub_snapshot(self.snapshot)
        self.assertEqual(digests, {name: hashlib.sha256(content).hexdigest()
                                   for name, content in self.FILES.items()})
        pinned = {"embedding_model.ckpt": digests["embedding_model.ckpt"]}
        self.assertEqual(verify_hub_snapshot(self.snapshot, pinned), digests)

    def test_tampered_missing_unlinked_or_mispinned_files_refuse(self) -> None:
        blob = (self.snapshot / "embedding_model.ckpt").resolve()
        original = blob.read_bytes()
        blob.write_bytes(b"tampered")
        with self.assertRaisesRegex(JudgeRegistryError, "content address"):
            verify_hub_snapshot(self.snapshot)
        blob.write_bytes(original)
        with self.assertRaisesRegex(JudgeRegistryError, "registry pin"):
            verify_hub_snapshot(self.snapshot, {"embedding_model.ckpt": "0" * 64})
        with self.assertRaisesRegex(JudgeRegistryError, "registry pin"):
            verify_hub_snapshot(self.snapshot, {"classifier.ckpt": "0" * 64})
        copied = self.snapshot / "copied.bin"
        copied.write_bytes(b"not content addressed")
        with self.assertRaisesRegex(JudgeRegistryError, "content address"):
            verify_hub_snapshot(self.snapshot)
        pinned = {"copied.bin": hashlib.sha256(b"not content addressed").hexdigest()}
        self.assertIn("copied.bin", verify_hub_snapshot(self.snapshot, pinned))
        with self.assertRaisesRegex(JudgeRegistryError, "not in the local cache"):
            verify_hub_snapshot(self.root / "absent")

    def test_the_ecapa_loader_verifies_its_registered_snapshot(self) -> None:
        registry = load_registry()
        pins = registry["judges"][clone_speaker_similarity.ECAPA_JUDGE_ID]["pins"]
        self.assertEqual((pins["repository"], pins["revision"]),
                         (clone_speaker_similarity.ECAPA_SOURCE, clone_speaker_similarity.ECAPA_REVISION))
        digests = clone_speaker_similarity.verify_ecapa_snapshot(str(self.snapshot))
        self.assertEqual(set(digests), set(self.FILES))
        (self.snapshot / "hyperparams.yaml").resolve().write_bytes(b"pretrainer: swapped\n")
        with self.assertRaisesRegex(RuntimeError, "failed verification"):
            clone_speaker_similarity.verify_ecapa_snapshot(str(self.snapshot))

    def test_a_blocked_or_repinned_judge_refuses_its_snapshot(self) -> None:
        registry = load_registry()
        judge_id = "speaker.ecapa-voxceleb@1"
        pins = registry["judges"][judge_id]["pins"]
        with self.assertRaisesRegex(JudgeRegistryError, "different snapshot"):
            verify_judge_snapshot(judge_id, self.snapshot, repository=pins["repository"],
                                  revision="1" * 40, registry=registry)
        registry["judges"][judge_id]["status"] = "quarantined"
        with self.assertRaisesRegex(JudgeRegistryError, "quarantined"):
            verify_judge_snapshot(judge_id, self.snapshot, repository=pins["repository"],
                                  revision=pins["revision"], registry=registry)
        with self.assertRaisesRegex(JudgeRegistryError, "not registered"):
            verify_judge_snapshot("speaker.unknown@1", self.snapshot, repository="x", revision="y",
                                  registry=registry)


if __name__ == "__main__":
    unittest.main()
