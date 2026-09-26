#!/usr/bin/env python3
"""The audio QC judge registry: tiers, exclusions, identities, retirements, adoption and snapshot pins."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio_qc_judges import (  # noqa: E402
    JudgeRegistryError,
    load_registry,
    require_executable,
    require_loadable,
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
    "config/delivery-prompt-remediation-contract.json",
    "benchmarks/hardware-profiles.json",
)
ECAPA = "speaker.ecapa-voxceleb@1"
WHISPER = "asr.whisper-small@1"


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
        """A minimal repository: the contracts and the files the registry names."""
        for relative in CONTRACTS:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / relative, target)
        for judge in self.registry["judges"].values():
            if judge["status"] == "retired":
                continue
            worker = (judge.get("execution") or {}).get("worker")
            for relative in judge.get("legacyIdentifiers", {}).get("sources", []) + ([worker] if worker else []):
                target = self.root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("# fixture\n", encoding="utf-8")
        return self.root

    def _rewrite(self, relative: str, mutate) -> None:
        path = self.root / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_no_judge_outside_retired_is_tier_c_or_unknown(self) -> None:
        judges = self.registry["judges"]
        for judge_id, judge in judges.items():
            with self.subTest(judge=judge_id):
                self.assertIn(judge["license"]["tier"], ("A", "B", "C"))
                if judge["status"] != "retired":
                    self.assertIn(judge["license"]["tier"], ("A", "B"))
        retired = {judge_id for judge_id, judge in judges.items() if judge["status"] == "retired"}
        self.assertEqual(retired, {"quality.nisqa-v2@1", "quality.utmosv2@1", "emotion.ser-wav2vec2-xlsr@2",
                                   "compact.distilhubert@1", "delivery.fitted-heads@2"})
        nisqa = judges["quality.nisqa-v2@1"]["license"]
        self.assertEqual((nisqa["tier"], nisqa["commercialUseCompatible"]), ("C", False))
        self.assertIn("CC BY-NC-SA 4.0", nisqa["weights"])

        def tier_c(registry):
            registry["judges"][ECAPA]["license"]["tier"] = "C"
            registry["judges"][ECAPA]["license"]["commercialUseCompatible"] = False
        self.assertIn(f"judge {ECAPA}: a tier-C judge must be retired", self._errors(tier_c))

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
            del registry["judges"][WHISPER]["tierBAcceptance"]
        self.assertTrue(any("decision-2a" in e for e in self._errors(unaccepted)))

        def shipped(registry):
            registry["judges"][ECAPA]["ships"] = True
        self.assertIn(f"judge {ECAPA}: a tier-B judge never ships", self._errors(shipped))

    def test_a_judge_from_the_generator_lab_never_votes(self) -> None:
        def same_lab(registry):
            registry["judges"][WHISPER]["independence"]["generatorLabCorrelated"] = True
        self.assertTrue(any("never votes" in e for e in self._errors(same_lab)))

    def test_output_and_envelope_identities_never_share_a_component(self) -> None:
        def leaked_supervisor(registry):
            registry["judges"]["compact.distilhubert@1"]["identity"]["output"].append("resourceSupervisorSHA256")
        self.assertTrue(any("never output identity" in e for e in self._errors(leaked_supervisor)))

        # The reverse: what can change the output never hides in the envelope.
        for component in ("runtimeVersions", "torchVersion", "commandTemplate", "weightsSHA256"):
            def leaked_output(registry, component=component):
                registry["judges"][ECAPA]["identity"]["envelope"].append(component)
            with self.subTest(component=component):
                self.assertIn(
                    f"judge {ECAPA}: what can change the output is output identity, never envelope identity",
                    self._errors(leaked_output),
                )

    def test_runtime_and_host_are_output_identity(self) -> None:
        def unrecorded(registry):
            registry["judges"][ECAPA]["identity"]["output"].remove("runtimeVersions")
        self.assertTrue(any("runtime" in e and ECAPA in e for e in self._errors(unrecorded)))

        def unpinned(registry):
            registry["judges"][ECAPA]["pins"]["runtime"]["torch"] = ""
        self.assertTrue(any("runtime pins" in e for e in self._errors(unpinned)))

        for judge_id in ("compact.sensevoice-small-q8@1", WHISPER, ECAPA):
            def hostless(registry, judge_id=judge_id):
                identity = registry["judges"][judge_id]["identity"]
                identity["output"].remove("hostProfile")
                identity["envelope"].append("hostProfile")
            with self.subTest(judge=judge_id):
                self.assertIn(
                    f"judge {judge_id}: until its cross-host determinism is measured, the host is output identity",
                    self._errors(hostless),
                )

    def test_runnable_neural_judges_load_only_after_digest_verification(self) -> None:
        def unpinned(registry):
            registry["judges"][ECAPA]["pins"]["digestStatus"] = "revision-only"
        self.assertTrue(any("digest status" in e for e in self._errors(unpinned)))

        def empty(registry):
            registry["judges"][WHISPER]["pins"]["files"] = {}
        self.assertTrue(any("lists its file digests" in e for e in self._errors(empty)))

        def empty_snapshot(registry):
            registry["judges"][ECAPA]["pins"]["files"] = {}
        self.assertIn(f"judge {ECAPA}: a runnable snapshot judge pins every file of its snapshot",
                      self._errors(empty_snapshot))

        for pin in ({"sha256": "0" * 64}, {"lfsSHA256": "0" * 63}, {"gitBlobID": "0" * 64},
                    {"lfsSHA256": "0" * 64, "gitBlobID": "0" * 40}, {"gitBlobID": "0" * 40, "size": -1}):
            def malformed(registry, pin=pin):
                registry["judges"][ECAPA]["pins"]["files"]["hyperparams.yaml"] = pin
            with self.subTest(pin=pin):
                self.assertIn(f"judge {ECAPA}: snapshot file pins name an LFS SHA-256 or a git blob ID",
                              self._errors(malformed))

    def test_planned_retirements_are_explicitly_deferred(self) -> None:
        ecapa = self.registry["judges"][ECAPA]["plannedRetirement"]
        self.assertEqual((ecapa["item"], ecapa["status"]), ("AQ-07", "deferred"))

        def undated(registry):
            del registry["judges"][ECAPA]["plannedRetirement"]["status"]
        self.assertTrue(any("planned retirement" in e for e in self._errors(undated)))

    def test_distilhubert_and_the_fitted_heads_left_every_qc_path(self) -> None:
        """AQ-05 (audit sections 4.9 and 7.1): retired as measurands, not for their terms."""
        judges = self.registry["judges"]
        for judge_id in ("compact.distilhubert@1", "delivery.fitted-heads@2"):
            with self.subTest(judge=judge_id):
                judge = judges[judge_id]
                self.assertEqual((judge["status"], judge["calibration"], judge["license"]["tier"]),
                                 ("retired", "none", "A"))
                self.assertEqual(judge["retirement"]["item"], "AQ-05")
                self.assertNotIn("plannedRetirement", judge)
                self.assertNotIn("execution", judge)
        exclusion = {entry["id"]: entry for entry in self.registry["excluded"]}["distilhubert-and-uncalibrated-heads"]
        self.assertEqual(exclusion["category"], "measurand")
        pins = judges["compact.distilhubert@1"]["pins"]
        with self.assertRaisesRegex(JudgeRegistryError, "retired"):
            require_loadable("compact.distilhubert@1", pins["repository"], pins["revision"], registry=self.registry)
        root = self._repository_copy()
        # The heads' layer and the DistilHuBERT adapter never return to a live contract.
        self._rewrite("config/delivery-evaluator-v2-contract.json",
                      lambda value: value["cascade"]["optionalQualifiedLayers"].append("tiny-local-heads"))
        self.assertIn("judge delivery.fitted-heads@2: cascade layer tiny-local-heads is still requested",
                      validate_repository(root))
        shutil.copyfile(REPO / "config/delivery-evaluator-v2-contract.json",
                        root / "config/delivery-evaluator-v2-contract.json")
        self._rewrite("config/delivery-evaluator-v2-contract.json",
                      lambda value: value["compactAdapters"]["candidateOrder"].append("distilhubert"))
        self.assertIn("judge compact.distilhubert@1: adapter distilhubert is still a live candidate",
                      validate_repository(root))
        shutil.copyfile(REPO / "config/delivery-evaluator-v2-contract.json",
                        root / "config/delivery-evaluator-v2-contract.json")
        # A permissive judge retired as a measurand keeps its commercial license.
        self._rewrite("config/delivery-evaluator-v2-candidates.json",
                      lambda value: value["retiredCandidates"]["distilhubert"].update(commercialUseCompatible=False))
        self.assertIn("retired candidate distilhubert: commercialUseCompatible must match its registry tier A",
                      validate_repository(root))

    def test_admission_is_budgeted_and_the_recovery_switch_needs_m6_evidence(self) -> None:
        """Decision 9a: one budget, one GPU worker beside two CPU workers, a report-only switch."""
        admission = self.registry["admission"]
        self.assertEqual(admission["policy"], "budgeted-admission-after-generator-exit")
        self.assertEqual({lane: value["maximumConcurrent"] for lane, value in admission["lanes"].items()},
                         {"gpu": 1, "cpu": 2, "dsp": 4})
        self.assertIs(admission["recoveryRule"]["candidateBinding"], False)
        self.assertEqual(admission["recoveryRule"]["workerCapWhileWholeHostBinding"], 1)
        self.assertEqual(admission["recoveryRule"]["promotion"]["evidence"], [])

        def two_gpu(registry):
            registry["admission"]["lanes"]["gpu"]["maximumConcurrent"] = 2
        self.assertIn("admission runs one MLX GPU worker at a time beside at most two CPU workers",
                      self._errors(two_gpu))

        def uncapped(registry):
            registry["admission"]["recoveryRule"]["workerCapWhileWholeHostBinding"] = 2
        self.assertIn("while the whole-host recovery rule binds, admission caps the host at one worker",
                      self._errors(uncapped))

        def flipped(registry):
            registry["admission"]["recoveryRule"]["candidateBinding"] = True
        self.assertIn("a binding child-attributed recovery rule cites at least 2 recovery reports",
                      self._errors(flipped))

        def report(digest: str, **overrides) -> dict:
            value = {"recoveryReportSHA256": digest, "hardwareProfileID": "mac-mini-m6-16gb", "date": "2026-10-01",
                     "serialEnvelopes": 4, "serialCandidateWouldQualifyBindingFailure": 0, "unattributed": 0,
                     "byJudge": {WHISPER: 2, "compact.sensevoice-small-q8@1": 2}}
            return {**value, **overrides}

        def evidenced(registry, reports):
            registry["admission"]["recoveryRule"]["candidateBinding"] = True
            registry["admission"]["recoveryRule"]["promotion"]["evidence"] = reports
        self.assertEqual(self._errors(lambda r: evidenced(r, [report("a" * 64), report("b" * 64)])), [])
        misattributed = self._errors(lambda r: evidenced(
            r, [report("a" * 64), report("b" * 64, serialCandidateWouldQualifyBindingFailure=1)]))
        self.assertTrue(any("blamed a serial post-exit drop" in e for e in misattributed))
        self.assertTrue(any("canonical hardware profile" in e for e in self._errors(lambda r: evidenced(
            r, [report("a" * 64), report("b" * 64, hardwareProfileID="mac-mini-m2-8gb")]))))
        self.assertTrue(any("lacks envelopes of compact.sensevoice-small-q8@1" in e for e in self._errors(
            lambda r: evidenced(r, [report("a" * 64), report("b" * 64, byJudge={WHISPER: 1})]))))
        self.assertIn("recovery evidence reports must be distinct",
                      self._errors(lambda r: evidenced(r, [report("a" * 64), report("a" * 64)])))

        def oversized(registry):
            registry["judges"][WHISPER]["resources"]["provisionalCeilingBytes"] = 10 * 1024**3
        self.assertIn(f"judge {WHISPER}: its ceiling never fits the admission budget", self._errors(oversized))

        def measured(registry):
            registry["judges"][WHISPER]["resources"]["canonicalHostPeakBytes"] = 9 * 1024**3
        self.assertIn(f"judge {WHISPER}: its ceiling never fits the admission budget", self._errors(measured))

        def threadless(registry):
            registry["judges"][WHISPER]["identity"]["output"].remove("threads")
        self.assertIn(f"judge {WHISPER}: an orchestrated judge declares its thread count, which is output identity",
                      self._errors(threadless))

        def undeclared(registry):
            del registry["judges"]["prosody@3"]["execution"]
        self.assertTrue(any("judge prosody@3: execution names its lane" in e for e in self._errors(undeclared)))

        def retired_runs(registry):
            registry["judges"]["compact.distilhubert@1"]["execution"] = {"lane": "cpu", "orchestrated": False}
        self.assertIn("judge compact.distilhubert@1: a retired or quarantined judge declares no execution",
                      self._errors(retired_runs))

    def test_exclusion_list_refuses_excluded_models_and_packages(self) -> None:
        sensevoice = "compact.sensevoice-small-q8@1"

        def excluded_model(registry):
            registry["judges"][sensevoice]["pins"]["repository"] = "utter-project/mHuBERT-147"
        self.assertTrue(any("mhubert-147-and-versa" in e for e in self._errors(excluded_model)))

        def excluded_distilhubert(registry):
            registry["judges"][sensevoice]["pins"]["repository"] = "ntu-spml/distilhubert"
        self.assertTrue(any("distilhubert-and-uncalibrated-heads" in e for e in self._errors(excluded_distilhubert)))

        def excluded_package(registry):
            registry["judges"][sensevoice]["pins"]["runtime"]["pykakasi"] = "2.3.0"
        self.assertTrue(any("package pykakasi is excluded" in e for e in self._errors(excluded_package)))

        def uncovered(registry):
            registry["excluded"] = [e for e in registry["excluded"] if e["id"] != "utmosv2"]
        self.assertIn("judge quality.utmosv2@1: a retired tier-C judge must be on the exclusion list",
                      self._errors(uncovered))

        root = self._repository_copy()
        self._rewrite("config/delivery-evaluator-v2-candidates.json",
                      lambda value: value["candidates"]["whisper-small-mlx"]["runtimeDependencies"].update(zhconv="1.4.3"))
        self.assertTrue(any("package zhconv is excluded" in e for e in validate_repository(root)))

    def test_use_restrictions_bound_how_a_judge_runs(self) -> None:
        judge = copy.deepcopy(self.registry["judges"][ECAPA])
        judge["pins"]["repository"] = "mlx-community/Qwen2-Audio-7B-Instruct-4bit"

        def unacknowledged(registry):
            registry["judges"]["research.qwen2-audio-ab@1"] = copy.deepcopy(judge)
        self.assertIn(
            "judge research.qwen2-audio-ab@1: matches use restriction qwen2-audio-per-take-judge "
            "and must acknowledge it", self._errors(unacknowledged),
        )

        def per_take_verdict(registry):
            registry["judges"]["research.qwen2-audio-ab@1"] = dict(
                copy.deepcopy(judge), useRestriction="qwen2-audio-per-take-judge", status="gating",
            )
        self.assertIn(
            "judge research.qwen2-audio-ab@1: use restriction qwen2-audio-per-take-judge forbids votes "
            "and verdicts", self._errors(per_take_verdict),
        )

        def research_only(registry):
            registry["judges"]["research.qwen2-audio-ab@1"] = dict(
                copy.deepcopy(judge), useRestriction="qwen2-audio-per-take-judge", status="candidate",
            )
        self.assertFalse(any("use restriction" in e for e in self._errors(research_only)))

    def test_retired_judges_stay_out_of_every_qc_path(self) -> None:
        root = self._repository_copy()
        self.assertEqual(validate_repository(root), [])
        (root / "scripts").mkdir(exist_ok=True)
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

    def test_a_legacy_contract_naming_a_retired_guardrail_is_frozen(self) -> None:
        root = self._repository_copy()
        frozen = "config/delivery-prompt-remediation-contract.json"
        path = root / frozen
        path.write_bytes(path.read_bytes() + b"\n")
        self.assertIn(
            f"judge quality.utmosv2@1: frozen contract {frozen} changed; a digest-bound legacy contract "
            "is never edited", validate_repository(root),
        )
        shutil.copyfile(REPO / frozen, path)

        def unregistered_field(registry):
            registry["judges"]["quality.utmosv2@1"]["legacyIdentifiers"]["frozenContracts"][0]["fields"] = [
                "acceptance.maximumMedianSpeakerSimilarityRegression"]
        registry = copy.deepcopy(self.registry)
        unregistered_field(registry)
        self.assertTrue(any("is not a retired guardrail it carries" in e
                            for e in validate_repository(root, registry)))

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

    def test_the_load_gate_refuses_what_may_not_load(self) -> None:
        pins = self.registry["judges"][WHISPER]["pins"]
        judge = require_loadable(WHISPER, pins["repository"], pins["revision"], registry=self.registry)
        self.assertIs(require_executable(WHISPER, judge), judge)
        with self.assertRaisesRegex(JudgeRegistryError, "not registered"):
            require_loadable("asr.unregistered@1", pins["repository"], pins["revision"], registry=self.registry)
        for status in ("retired", "quarantined"):
            registry = copy.deepcopy(self.registry)
            registry["judges"][WHISPER]["status"] = status
            with self.assertRaisesRegex(JudgeRegistryError, status):
                require_loadable(WHISPER, pins["repository"], pins["revision"], registry=registry)
        registry = copy.deepcopy(self.registry)
        registry["judges"][WHISPER]["license"].pop("tier")
        with self.assertRaisesRegex(JudgeRegistryError, "license tier"):
            require_loadable(WHISPER, pins["repository"], pins["revision"], registry=registry)
        # The repository actually loaded is checked, however the loader reaches it.
        for model in ("distil-whisper/distil-small.en", "torchaudio.pipelines.MMS_FA",
                      "MahmoudAshraf/mms-300m-1130-forced-aligner", "moonshine-ai/moonshine-tiny-ja"):
            with self.subTest(model=model), self.assertRaisesRegex(JudgeRegistryError, "is excluded"):
                require_loadable(WHISPER, model, pins["revision"], registry=self.registry)
        with self.assertRaisesRegex(JudgeRegistryError, "package lightning-whisper-mlx is excluded"):
            require_loadable(WHISPER, pins["repository"], pins["revision"],
                             packages=["mlx", "lightning-whisper-mlx"], registry=self.registry)
        with self.assertRaisesRegex(JudgeRegistryError, "another model or revision"):
            require_loadable(WHISPER, pins["repository"], "1" * 40, registry=self.registry)
        with self.assertRaisesRegex(JudgeRegistryError, "another model or revision"):
            require_loadable(WHISPER, "openai/whisper-small", pins["revision"], registry=self.registry)
        # A variant suffix names a file set inside the pinned repository.
        sensevoice = self.registry["judges"]["compact.sensevoice-small-q8@1"]["pins"]
        require_loadable("compact.sensevoice-small-q8@1", sensevoice["repository"] + ":q8",
                         sensevoice["revision"], registry=self.registry)
        # English Moonshine is MIT and not excluded; the legacy non-English models are.
        with self.assertRaisesRegex(JudgeRegistryError, "another model or revision"):
            require_loadable(WHISPER, "moonshine-ai/moonshine-tiny", pins["revision"], registry=self.registry)


def _hub_snapshot(root: Path, files: dict[str, bytes], *, large: set[str], revision: str) -> Path:
    """A Hugging Face cache layout: blobs named by content address, snapshot symlinks."""
    blobs = root / "blobs"
    snapshot = root / "snapshots" / revision
    blobs.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        address = _address(content, large=name in large)
        (blobs / address).write_bytes(content)
        link = snapshot / name
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(Path("../" * (name.count("/") + 2)) / "blobs" / address)
    return snapshot


def _address(content: bytes, *, large: bool) -> str:
    if large:
        return hashlib.sha256(content).hexdigest()
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def _tree_pins(files: dict[str, bytes], *, large: set[str]) -> dict[str, dict]:
    """What the Hub tree metadata records: the LFS SHA-256 or the git blob ID, and the size."""
    return {
        name: {("lfsSHA256" if name in large else "gitBlobID"): _address(content, large=name in large),
               "size": len(content)}
        for name, content in files.items()
    }


class HubSnapshotVerificationTests(unittest.TestCase):
    REVISION = "a" * 40
    FILES = {
        ".gitattributes": b"*.ckpt filter=lfs\n",
        "hyperparams.yaml": b"pretrainer: fixture\n",
        "embedding_model.ckpt": b"fixture embedding weights",
        "nested/label_encoder.txt": b"'id10001' => 0\n",
    }
    LARGE = {"embedding_model.ckpt"}

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.snapshot = _hub_snapshot(self.root, self.FILES, large=self.LARGE, revision=self.REVISION)
        self.pins = _tree_pins(self.FILES, large=self.LARGE)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_a_snapshot_matching_its_tree_pins_verifies_and_reports_file_digests(self) -> None:
        digests = verify_hub_snapshot(self.snapshot, self.pins, revision=self.REVISION)
        self.assertEqual(digests, {name: hashlib.sha256(content).hexdigest()
                                   for name, content in self.FILES.items()})
        # A plain copy is judged by its bytes, not by how the cache linked it.
        copied = self.snapshot / "hyperparams.yaml"
        copied.unlink()
        copied.write_bytes(self.FILES["hyperparams.yaml"])
        self.assertEqual(verify_hub_snapshot(self.snapshot, self.pins, revision=self.REVISION), digests)

    def test_altered_extra_missing_or_misplaced_files_refuse(self) -> None:
        blob = (self.snapshot / "embedding_model.ckpt").resolve()
        original = blob.read_bytes()
        blob.write_bytes(b"tampered")
        with self.assertRaisesRegex(JudgeRegistryError, "differs from its registry pin"):
            verify_hub_snapshot(self.snapshot, self.pins, revision=self.REVISION)
        # Same size, different bytes: the content pin still refuses.
        blob.write_bytes(original[:-1] + b"!")
        with self.assertRaisesRegex(JudgeRegistryError, "differs from its registry pin"):
            verify_hub_snapshot(self.snapshot, self.pins, revision=self.REVISION)
        blob.write_bytes(original)
        # A blob named by its own content cannot vouch for itself.
        (self.snapshot / "hyperparams.yaml").resolve().write_bytes(b"pretrainer: swapped\n")
        with self.assertRaisesRegex(JudgeRegistryError, "hyperparams.yaml differs"):
            verify_hub_snapshot(self.snapshot, self.pins, revision=self.REVISION)
        (self.snapshot / "hyperparams.yaml").resolve().write_bytes(self.FILES["hyperparams.yaml"])
        (self.snapshot / "extra.bin").write_bytes(b"unpinned")
        with self.assertRaisesRegex(JudgeRegistryError, "unpinned files: extra.bin"):
            verify_hub_snapshot(self.snapshot, self.pins, revision=self.REVISION)
        (self.snapshot / "extra.bin").unlink()
        with self.assertRaisesRegex(JudgeRegistryError, "lacks pinned files: classifier.ckpt"):
            verify_hub_snapshot(self.snapshot, {**self.pins, "classifier.ckpt": {"lfsSHA256": "0" * 64}},
                                revision=self.REVISION)
        with self.assertRaisesRegex(JudgeRegistryError, "not the pinned revision"):
            verify_hub_snapshot(self.snapshot, self.pins, revision="b" * 40)
        with self.assertRaisesRegex(JudgeRegistryError, "pins no snapshot files"):
            verify_hub_snapshot(self.snapshot, {}, revision=self.REVISION)
        with self.assertRaisesRegex(JudgeRegistryError, "not in the local cache"):
            verify_hub_snapshot(self.root / "absent", self.pins, revision=self.REVISION)

    def test_a_fabricated_ecapa_snapshot_fails_against_the_registry_pins(self) -> None:
        registry = load_registry()
        pins = registry["judges"][clone_speaker_similarity.ECAPA_JUDGE_ID]["pins"]
        self.assertEqual((pins["repository"], pins["revision"]),
                         (clone_speaker_similarity.ECAPA_SOURCE, clone_speaker_similarity.ECAPA_REVISION))
        # Every pinned name, fabricated bytes, cached under the pinned revision.
        fabricated = {name: b"fabricated " + name.encode() for name in pins["files"]}
        snapshot = _hub_snapshot(self.root / "fabricated", fabricated, large=set(),
                                 revision=clone_speaker_similarity.ECAPA_REVISION)
        with self.assertRaisesRegex(RuntimeError, "failed verification.*differs from its registry pin"):
            clone_speaker_similarity.verify_ecapa_snapshot(str(snapshot))

    def test_the_ecapa_loader_verifies_its_registered_snapshot(self) -> None:
        registry = load_registry()
        judge = registry["judges"][clone_speaker_similarity.ECAPA_JUDGE_ID]
        judge["pins"]["files"] = self.pins
        snapshot = _hub_snapshot(self.root / "pinned", self.FILES, large=self.LARGE,
                                 revision=clone_speaker_similarity.ECAPA_REVISION)
        with mock.patch("audio_qc_judges.load_registry", return_value=registry):
            digests = clone_speaker_similarity.verify_ecapa_snapshot(str(snapshot))
            self.assertEqual(set(digests), set(self.FILES))
            (snapshot / "hyperparams.yaml").resolve().write_bytes(b"pretrainer: swapped\n")
            with self.assertRaisesRegex(RuntimeError, "failed verification"):
                clone_speaker_similarity.verify_ecapa_snapshot(str(snapshot))

    def test_a_blocked_or_repinned_judge_refuses_its_snapshot(self) -> None:
        registry = load_registry()
        pins = registry["judges"][ECAPA]["pins"]
        with self.assertRaisesRegex(JudgeRegistryError, "another model or revision"):
            verify_judge_snapshot(ECAPA, self.snapshot, repository=pins["repository"],
                                  revision="1" * 40, registry=registry)
        registry["judges"][ECAPA]["status"] = "quarantined"
        with self.assertRaisesRegex(JudgeRegistryError, "quarantined"):
            verify_judge_snapshot(ECAPA, self.snapshot, repository=pins["repository"],
                                  revision=pins["revision"], registry=registry)
        with self.assertRaisesRegex(JudgeRegistryError, "not registered"):
            verify_judge_snapshot("speaker.unknown@1", self.snapshot, repository="x", revision="y",
                                  registry=registry)
        with self.assertRaisesRegex(JudgeRegistryError, "not pinned by snapshot"):
            whisper = registry["judges"][WHISPER]["pins"]
            verify_judge_snapshot(WHISPER, self.snapshot, repository=whisper["repository"],
                                  revision=whisper["revision"], registry=registry)


if __name__ == "__main__":
    unittest.main()
