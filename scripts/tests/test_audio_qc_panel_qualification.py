#!/usr/bin/env python3
"""AQ-06 panel qualification (audit P8): canary set, determinism, flips, records and promotion.

No model runs. The session test drives `run_session` with fixture judges under
the real supervisor and admission: a deterministic judge (D0), one whose
scores wobble below a tolerance (D1) and one whose transcript changes between
runs (D2). It proves that both runs are separate sessions with their own
caches, that the records carry digests and metrics only and validate, that the
flip analysis names the flipped takes, and that `promote` moves exactly the
passing candidates to shadow, and only from committed records, leaving every
other byte of the registry alone. The recalibration tests run a full-cohort
session over the promoted fixture panel under the measurement ceiling and prove
that `recalibrate` raises only shadow ceilings, keeps their history, and
refuses what it must; they never read the live registry's ceilings.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import audio_qc_panel_qualification as cli  # noqa: E402
from audio_qc_judges import (  # noqa: E402
    acquisition_entry_digest,
    load_registry,
    validate_registry,
    validate_repository,
)
from acquire_audio_qc_judges import entry_digest, receipt_current  # noqa: E402
from delivery_resource_supervisor import HostSnapshot, run_supervised  # noqa: E402
from lib.qc_pipeline import qualification as q  # noqa: E402
from lib.qc_pipeline.admission import judge_admission  # noqa: E402
import test_audio_qc_judges as registry_tests  # noqa: E402
from test_audio_qc_panel_orchestration import (  # noqa: E402
    AUDIOBOX,
    CAMPPLUS,
    CANONICAL_HOST,
    HOST,
    MIB,
    PARAKEET,
    PYIN,
    SCRIPTS,
    WHISPER_LARGE,
    PanelFixture,
    quiet_supervisor,
)

REPO = Path(__file__).resolve().parents[2]


def envelope(**overrides) -> dict:
    value = {"kind": "delivery-analyzer-resource-envelope", "qualificationFailures": [], "qualified": True,
             "hostProfileID": CANONICAL_HOST, "peakRSSBytes": 300, "peakPhysicalFootprintBytes": 500,
             "wallSeconds": 1.5, "swapDeltaBytes": 0, "sessionID": "session-a"}
    value.update(overrides)
    return value


def worker(*envelopes: dict, retry: bool = False, **overrides) -> dict:
    launches = [{"launch": index, "retry": retry and index > 1, "completed": True, "protocolError": False,
                 "resourceEnvelope": item} for index, item in enumerate(envelopes, start=1)]
    return {"judge": PYIN, "launches": launches, "rowsAccepted": 3, "rowsAdopted": 0, "rowsUnavailable": {},
            "modelLoadSeconds": 1.25, "warmupSeconds": 0.5, "threads": 1, **overrides}


class CanarySetTests(unittest.TestCase):
    def test_the_committed_canary_set_renders_to_its_golden_digests(self) -> None:
        spec = q.load_canary_set()
        self.assertEqual(q.canary_set_errors(spec), [])
        with tempfile.TemporaryDirectory() as temporary:
            takes = q.materialize_canary_set(spec, Path(temporary))
        self.assertEqual(len(takes), len(spec["takes"]))
        languages = {take["language"] for take in takes}
        # Every language-scoped panel judge sees at least one canary take.
        self.assertTrue({"english", "chinese", "japanese", "korean", "french", "german"} <= languages)
        self.assertEqual(sum(1 for take in takes if "referenceAudioPath" in take), 3)
        self.assertTrue(all(take["referenceText"] for take in takes if take["id"].split("-")[1] in
                            ("modal", "breathy", "high", "quiet", "long")))
        broken = copy.deepcopy(spec)
        broken["takes"][0]["pcmSHA256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(q.QualificationError, "golden"):
            q.materialize_canary_set(broken, Path(temporary))


class AnalysisTests(unittest.TestCase):
    def test_determinism_classes(self) -> None:
        row = {"transcript": "a b", "scores": [0.25, 0.5], "voiced": [True, False], "count": 3}
        self.assertEqual(q.determinism([(row, copy.deepcopy(row))])["class"], "D0")
        wobble = {**row, "scores": [0.25, 0.5000001]}
        measured = q.determinism([(row, row), (row, wobble)])
        self.assertEqual((measured["class"], measured["rowsBitExact"], measured["numericDifferences"]), ("D1", 1, 1))
        self.assertAlmostEqual(measured["maxAbsoluteDifference"], 1e-7, places=12)
        for changed in ({**row, "transcript": "a c"}, {**row, "voiced": [True, True]}, {**row, "count": 4},
                        {**row, "scores": [0.25]}, {**row, "extra": 1}):
            self.assertEqual(q.determinism([(row, changed)])["class"], "D2", changed)
        self.assertEqual(q.determinism([])["class"], "unmeasured")

    def test_a_clean_run_needs_qualified_envelopes_on_the_canonical_host_and_no_retry(self) -> None:
        clean = q.run_resources(worker(envelope(), envelope(peakRSSBytes=900, peakPhysicalFootprintBytes=None)),
                                canonical_host=CANONICAL_HOST)
        self.assertEqual((clean["clean"], clean["peakBytes"], clean["peakRSSBytes"], clean["launches"],
                          clean["wallSeconds"], clean["threads"]), (True, 900, 900, 2, 3.0, 1))
        for report, failure in (
            (worker(envelope(qualificationFailures=["post-exit-memory-recovery-unqualified"])),
             "post-exit-memory-recovery-unqualified"),
            (worker(envelope(hostProfileID="mac-mini-m2-8gb")), "host-not-canonical"),
            (worker(envelope(), envelope(), retry=True), "retried"),
            (worker(envelope(), rowsUnavailable={"row": "crash"}), "rows-unavailable"),
            (worker(), "not-launched"),
            (None, "not-launched"),
        ):
            summary = q.run_resources(report, canonical_host=CANONICAL_HOST)
            self.assertFalse(summary["clean"], failure)
            self.assertIn(failure, summary["failures"])

    def test_the_flip_analysis_names_each_flipped_take_and_skips_canaries(self) -> None:
        def record(take_id: str, small: dict, large: dict, *, role=None, language="english") -> dict:
            return {"take": {"takeID": take_id, "language": language, "role": role, "expectedOutcome": "pass"},
                    "measurements": [{"judge": q.BASELINE_RECOGNIZER, "status": "complete", "metrics": small},
                                     {"judge": q.CANDIDATE_RECOGNIZER, "status": "complete", "metrics": large}]}

        good = {"errorRate": 0.02, "detectedLanguage": "english"}
        records = [
            record("same", good, good),
            record("accuracy", good, {"errorRate": 0.4, "detectedLanguage": "english"}),
            record("language", {"errorRate": 0.02, "detectedLanguage": "french"}, good),
            record("no-script", {"detectedLanguage": "english"}, {"detectedLanguage": "english"}),
            record("canary-x", good, {"errorRate": 0.9, "detectedLanguage": "german"}, role=q.CANARY_ROLE),
        ]
        analysis = q.flip_analysis(records)
        self.assertEqual((analysis["accuracy"]["compared"], analysis["accuracy"]["flips"],
                          analysis["accuracy"]["passToFail"]), (3, 1, 1))
        self.assertEqual((analysis["language"]["compared"], analysis["language"]["flips"],
                          analysis["language"]["failToPass"], analysis["language"]["fraction"]), (4, 1, 1, 0.25))
        self.assertEqual(q.flipped_ids(analysis), {"language": ["language"], "accuracy": ["accuracy"]})
        self.assertEqual(analysis["accuracy"]["flipped"][0]["candidateErrorRate"], 0.4)


class RegistryEditTests(unittest.TestCase):
    def test_only_the_promoted_values_change(self) -> None:
        text = (REPO / "config/audio-qc-judges.json").read_text(encoding="utf-8")
        edits = {("judges", PYIN, "status"): "warn", ("judges", PYIN, "canary"): {"record": "a", "sha256": "b"}}
        live = json.loads(text)["judges"][PYIN]
        for (_judges, _judge, key), value in edits.items():
            self.assertNotEqual(live[key], value, "each edit changes a live value")
        updated = q.replace_json_values(text, edits)
        before, after = text.splitlines(), updated.splitlines()
        self.assertEqual(len(before), len(after))
        changed = [index for index, (old, new) in enumerate(zip(before, after)) if old != new]
        self.assertEqual(len(changed), 2)
        self.assertEqual(json.loads(updated)["judges"][PYIN]["canary"], {"record": "a", "sha256": "b"})
        with self.assertRaisesRegex(q.QualificationError, "no judges.pitch.pyin@1.missing"):
            q.replace_json_values(text, {("judges", PYIN, "missing"): 1})

    def test_the_acquisition_digest_ignores_qualification_state_and_old_receipts_stay_current(self) -> None:
        registry = registry_tests.unpromoted_registry()
        judge = registry["judges"][PARAKEET]
        promoted = {**judge, "status": "shadow", "determinismClass": "D1", "canary": {"record": "x"},
                    "resources": {**judge["resources"], "canonicalHostPeakBytes": 5}}
        self.assertEqual(acquisition_entry_digest(promoted), acquisition_entry_digest(judge))
        rethreaded = copy.deepcopy(judge)
        rethreaded["execution"]["threads"] = 4
        self.assertNotEqual(acquisition_entry_digest(rethreaded), acquisition_entry_digest(judge))
        self.assertTrue(receipt_current({"registryEntrySHA256": acquisition_entry_digest(judge)}, promoted))
        # A receipt from before P8 (the whole entry) is current until the entry changes, promotion aside.
        self.assertTrue(receipt_current({"registryEntrySHA256": entry_digest(judge)}, judge))
        self.assertFalse(receipt_current({"registryEntrySHA256": entry_digest(judge)}, rethreaded))
        # The live promotion kept every pre-promotion receipt current.
        live = load_registry()["judges"][PARAKEET]
        self.assertEqual(live["status"], "shadow")
        self.assertEqual(acquisition_entry_digest(live), acquisition_entry_digest(judge))
        self.assertTrue(receipt_current({"registryEntrySHA256": entry_digest(judge)}, live))
        text = registry_tests.unpromoted_registry_text()
        record = {"identityComponents": {"registryEntrySHA256": acquisition_entry_digest(judge)},
                  "resources": {"canonicalHostPeakBytes": 3 * 1024**3,
                                "admissionCeilingBytes": q.admission_ceiling(3 * 1024**3)},
                  "determinism": {"class": "D1"},
                  "outputIdentity": "a" * 64, "session": {"id": "20260928-0123abcd", "date": "2026-09-28"}}
        edits, _skipped = q.promotion_edits(registry, {"judges": {PARAKEET: {"passed": True}}}, {PARAKEET: record},
                                            record_paths={PARAKEET: "benchmarks/x.json"},
                                            record_digests={PARAKEET: "b" * 64})
        shadow = json.loads(q.replace_json_values(text, edits))["judges"][PARAKEET]
        self.assertEqual(shadow["status"], "shadow")
        self.assertEqual((shadow["resources"]["ceilingStatus"], shadow["resources"]["ceilingBytes"],
                          shadow["resources"]["ceilingSession"]),
                         ("calibrated", q.admission_ceiling(3 * 1024**3), "20260928-0123abcd"))
        self.assertTrue(receipt_current({"registryEntrySHA256": entry_digest(judge)}, shadow))


class QualificationFixture(PanelFixture):
    """A qualification session over fixture judges and a minimal repository to publish it in; no test of its own.

    Qualification and promotion act on candidates, so the session runs on the
    un-promoted registry, whatever the live registry has since promoted.
    """

    def setUp(self) -> None:
        super().setUp()
        self.registry = registry_tests.unpromoted_registry()

    def _judges(self, counter: Path) -> list:
        english = self.audio("speech-en", 180)
        self.speech_audio = english
        pcm = self.pcm(english)
        small = {pcm: self.whisper_answer(SCRIPTS["english"], "en", english)}
        large = {pcm: {**self.whisper_answer("Nothing like the script", "fr", english)}}
        default = {"transcript": "la la", "language": "en", "detectedLanguage": "en",
                   "detectedLanguageProbability": 0.5, "expectedLanguageProbability": 0.5,
                   "segments": [{"start": 0.0, "end": 1.0, "noSpeechProb": 0.5, "avgLogprob": -1.0}]}
        small_judge = self.whisper_small(small)
        small_judge = type(small_judge)(**{**small_judge.__dict__,
                                           "engine_config": {"table": small, "default": default}})
        return [
            small_judge,
            self.panel_judge(WHISPER_LARGE, table=large, default=default),
            self.panel_judge(PARAKEET, default={"transcript": "the quiet garden"}, counterFile=str(counter),
                             perturb="transcript"),
            self.panel_judge(AUDIOBOX, default={"CE": 5.0, "CU": 5.5, "PC": 2.0, "PQ": 6.0},
                             counterFile=str(counter) + "-audiobox", perturb="float"),
            self.panel_judge(PYIN, default={"hopSeconds": 0.01, "f0Hz": [200.0, 201.0], "voiced": [True, True]}),
            self.panel_judge(CAMPPLUS, embedFromDigest=True),
        ]

    def _session(self) -> tuple[Path, dict]:
        judges = self._judges(self.root / "launches")
        speech = self.manifest([self.take("speech-en", self.speech_audio, "english")], run_id="speech")
        panel = [WHISPER_LARGE, PARAKEET, AUDIOBOX, PYIN, CAMPPLUS]
        session_dir, manifest = cli.start_session(self.root / "sessions", speech=speech, panel=panel,
                                                  legacy=[q.BASELINE_RECOGNIZER], today=dt.date(2026, 9, 28))
        cli.run_session(registry=self.registry, manifest=manifest, judges=judges, resampler="polyphase-kaiser5-v2",
                        session_dir=session_dir, supervisor=quiet_supervisor, lock_root=self.root / "locks",
                        preflight=lambda: {"loadAverage1M": 1.0, "busy": False}, host=HOST,
                        host_profile_id=CANONICAL_HOST)
        return session_dir, cli.analyze_session(session_dir, registry=self.registry)

    def _repository(self) -> Path:
        """A minimal repository holding the un-promoted registry and the panel's worker sources."""
        repository = self.root / "repository"
        repository.mkdir()
        copier = registry_tests.JudgeRegistryTests("_repository_copy")
        copier.registry, copier.root = self.registry, repository
        copier._repository_copy()
        for relative in ("scripts/lib/qc_pipeline/panel_engines.py", "scripts/lib/qc_pipeline/panel_jobs.py",
                         "scripts/independent_asr_worker.py", "scripts/audio_qc_worker.py"):
            (repository / relative).parent.mkdir(parents=True, exist_ok=True)
            (repository / relative).write_bytes((REPO / relative).read_bytes())
        return repository


class SessionTests(QualificationFixture):
    """Both runs, the analysis, publication and promotion, end to end with fixture judges."""

    def test_two_runs_measure_resources_determinism_and_flips_into_valid_records(self) -> None:
        session_dir, summary = self._session()
        judges = summary["judges"]
        self.assertEqual({judge: (entry["passed"], entry["determinismClass"]) for judge, entry in judges.items()}, {
            WHISPER_LARGE: (True, "D0"), PARAKEET: (False, "D2"), AUDIOBOX: (True, "D1"),
            PYIN: (True, "D0"), CAMPPLUS: (True, "D0"),
        })
        self.assertIn("determinism-d2", judges[PARAKEET]["reasons"])
        records = session_dir / "records"
        audiobox = json.loads((records / "judges" / q.record_file_name(AUDIOBOX)).read_text(encoding="utf-8"))
        self.assertEqual(q.validate_canary_record(audiobox), [])
        self.assertAlmostEqual(audiobox["determinism"]["maxAbsoluteDifference"], 1e-7, places=12)
        self.assertEqual([run["clean"] for run in audiobox["runs"]], [True, True])
        # The peak is every launch's largest measurement: the sampled footprint (48 MiB here), the
        # reaped ru_maxrss and the child-attributed peak, over both runs.
        launches = [launch for run in audiobox["runs"] for launch in run["launchEnvelopes"]]
        peak = max(48 * 1024**2, *(launch["waitMaxRSSBytes"] or 0 for launch in launches))
        self.assertEqual(audiobox["resources"]["canonicalHostPeakBytes"], peak)
        self.assertEqual(audiobox["resources"]["admissionCeilingBytes"], -(-peak * 12 // 10))
        self.assertEqual({launch["childPeakBytes"] for launch in launches}, {48 * 1024**2})
        self.assertEqual({launch["peakPhysicalFootprintBytes"] for launch in launches}, {48 * 1024**2})
        # Qualification measures a provisional judge under the budget, not its estimate.
        budget = self.registry["admission"]["budgetBytes"] - self.registry["admission"]["orchestratorReservationBytes"]
        self.assertEqual({(launch["ceilingBytes"], launch["ceilingBasis"]) for launch in launches},
                         {(budget, "qualification-measurement-budget")})
        self.assertEqual(len(audiobox["resources"]["runPeakBytes"]), 2)
        session = json.loads((records / "session.json").read_text(encoding="utf-8"))
        self.assertEqual(session["judges"][AUDIOBOX]["runPeakBytes"], audiobox["resources"]["runPeakBytes"])
        self.assertEqual(session["judges"][AUDIOBOX]["admissionCeilingBytes"], -(-peak * 12 // 10))
        # The private diagnostics name each launch's codes, peaks and stderr; they stay out of the records.
        diagnostics = json.loads((session_dir / "diagnostics.json").read_text(encoding="utf-8"))
        parakeet = diagnostics["judges"][PARAKEET]
        self.assertEqual(parakeet["verdict"]["reasons"], judges[PARAKEET]["reasons"])
        launch = parakeet["runs"][0]["launches"][0]
        self.assertEqual((launch["hostCondition"], launch["failures"], launch["ceilingBasis"]),
                         (False, [], "qualification-measurement-budget"))
        self.assertIsInstance(launch["stderrTail"], str)
        self.assertEqual(diagnostics["judges"][q.BASELINE_RECOGNIZER]["verdict"], {"legacy": True})
        # The legacy whisper-small judge has no ceilingStatus: it keeps its provisional ceiling.
        small = diagnostics["judges"][q.BASELINE_RECOGNIZER]["runs"][0]["launches"][0]
        self.assertEqual(small["ceilingBasis"], "provisional")
        # Two runs are two orchestrator sessions, each with its own recovery report.
        sessions = [set(run["sessionIDs"]) for run in summary["runs"]]
        self.assertTrue(sessions[0] and sessions[1] and not sessions[0] & sessions[1])
        for index in (1, 2):
            report = json.loads((records / f"recovery-report-run-{index}.json").read_text(encoding="utf-8"))
            self.assertEqual(q.validate_recovery_report(report), [])
            self.assertEqual(report["overlapPossibleEnvelopes"], 0)
        # The D2 judge's record stays private.
        self.assertFalse((records / "judges" / q.record_file_name(PARAKEET)).exists())
        self.assertTrue((session_dir / "failed-judges" / q.record_file_name(PARAKEET)).exists())
        flip = json.loads((records / "flip-analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(q.validate_flip_record(flip), [])
        self.assertEqual((flip["accuracy"]["flipped"][0]["takeID"], flip["language"]["flipped"][0]["takeID"]),
                         ("speech-en", "speech-en"))
        self.assertTrue(flip["run2Consistent"])
        for path in records.rglob("*.json"):
            text = path.read_text(encoding="utf-8")
            self.assertEqual(q.validate_record_file(path), [], path.name)
            self.assertNotIn(SCRIPTS["english"], text)
            self.assertNotIn(str(self.root), text, "no private path in a record")

    def test_promotion_moves_passing_candidates_to_shadow_from_committed_records_only(self) -> None:
        session_dir, summary = self._session()
        # A judge that did not pass names why (CI once saw whisper-large-v3 fail here, not locally).
        diagnostics = json.loads((session_dir / "diagnostics.json").read_text(encoding="utf-8"))
        for judge in (WHISPER_LARGE, AUDIOBOX, PYIN, CAMPPLUS):
            entry = diagnostics["judges"].get(judge) or {}
            self.assertTrue(summary["judges"][judge]["passed"], json.dumps({
                "reasons": summary["judges"][judge].get("reasons"), "verdict": entry.get("verdict"),
                "launches": [[{key: launch.get(key) for key in ("failures", "hostCondition", "unavailableReason",
                                                                "ceilingBasis")} for launch in run.get("launches", [])]
                             for run in entry.get("runs", [])]}, default=str)[:4000])
        repository = self._repository()
        records_root = repository / "benchmarks/audio-qc-qualification"
        published = cli.publish(session_dir, records_root)
        self.assertEqual(q.validate_records(records_root), [])
        with self.assertRaisesRegex(cli.QualificationRunError, "published once"):
            cli.publish(session_dir, records_root)
        registry_path = repository / "config/audio-qc-judges.json"
        original = registry_path.read_text(encoding="utf-8")
        registry_tests._git(repository, "init", "-q")
        registry_tests._git(repository, "add", "-A", "--", "config", "benchmarks/hardware-profiles.json", "scripts")
        registry_tests._git(repository, "commit", "-qm", "fixture repository")
        with self.assertRaisesRegex(cli.QualificationRunError, "commit the session's records"):
            cli.promote(published, root=repository)
        registry_tests._git(repository, "add", "--", "benchmarks/audio-qc-qualification")
        registry_tests._git(repository, "commit", "-qm", "qualification records")
        dry = cli.promote(published, root=repository, dry_run=True)
        self.assertEqual(registry_path.read_text(encoding="utf-8"), original)
        self.assertEqual(dry["promoted"], sorted([WHISPER_LARGE, AUDIOBOX, PYIN, CAMPPLUS]), dry)
        self.assertEqual(dry["skipped"], {PARAKEET: "did-not-pass"})
        # The recovery rule stays report-only: two runs of five judges do not cover every worker.
        with self.assertRaisesRegex(cli.QualificationRunError, "would not validate"):
            cli.promote(published, root=repository, bind_recovery_rule=True)
        self.assertEqual(registry_path.read_text(encoding="utf-8"), original)
        result = cli.promote(published, root=repository)
        self.assertTrue(result["written"])
        promoted = json.loads(registry_path.read_text(encoding="utf-8"))
        audiobox = promoted["judges"][AUDIOBOX]
        self.assertEqual((audiobox["status"], audiobox["determinismClass"], audiobox["resources"]["ceilingStatus"]),
                         ("shadow", "D1", "calibrated"))
        record = json.loads((published / "judges" / q.record_file_name(AUDIOBOX)).read_text(encoding="utf-8"))
        self.assertEqual(audiobox["resources"]["canonicalHostPeakBytes"], record["resources"]["canonicalHostPeakBytes"])
        self.assertEqual(audiobox["resources"]["ceilingBytes"], record["resources"]["admissionCeilingBytes"])
        self.assertEqual(audiobox["resources"]["ceilingSession"], published.name)
        # Normal runs admit a calibrated judge at its calibrated ceiling.
        self.assertEqual(cli.orchestrator.judge_admission(promoted, AUDIOBOX, measurement=True).ceiling_bytes,
                         record["resources"]["admissionCeilingBytes"])
        self.assertEqual(audiobox["canary"]["record"],
                         f"benchmarks/audio-qc-qualification/{published.name}/judges/{q.record_file_name(AUDIOBOX)}")
        self.assertEqual(promoted["judges"][PARAKEET]["status"], "candidate")
        changed = [line for old, line in zip(original.splitlines(), registry_path.read_text().splitlines())
                   if old != line]
        self.assertEqual(len(changed), 4 * 4, "status, determinism class, resources and canary per judge")
        self.assertEqual(validate_repository(repository, promoted), [])
        # A second promotion changes nothing: the judges are no longer candidates.
        self.assertEqual(cli.promote(published, root=repository)["promoted"], [])

        # Registry integrity: a shadow panel judge cites a current, committed canary record.
        def errors(mutate) -> list[str]:
            registry = copy.deepcopy(promoted)
            mutate(registry["judges"][AUDIOBOX])
            return [error for error in validate_registry(registry, root=repository) if AUDIOBOX in error]

        self.assertEqual(errors(lambda judge: None), [])
        self.assertTrue(any("cites its canary record" in error for error in errors(
            lambda judge: judge.update(canary=None))))
        self.assertTrue(any("registry entry changed" in error for error in errors(
            lambda judge: judge["execution"].update(threads=3))))
        self.assertTrue(any("D0 or D1" in error for error in errors(lambda judge: judge.update(determinismClass="D2"))))
        self.assertTrue(any("canonicalHostPeakBytes" in error for error in errors(
            lambda judge: judge["resources"].update(canonicalHostPeakBytes=1))))
        # A calibrated ceiling is the one its committed canary record measured, in the session it names.
        self.assertTrue(any("peak x 1.2" in error for error in errors(
            lambda judge: judge["resources"].update(ceilingBytes=judge["resources"]["ceilingBytes"] + 1))))
        self.assertTrue(any("names session" in error for error in errors(
            lambda judge: judge["resources"].update(ceilingSession="20260101-00000000"))))
        self.assertTrue(any("names the qualification session" in error for error in errors(
            lambda judge: judge["resources"].update(ceilingSession=None))))
        self.assertTrue(any("cites the committed canary record" in error for error in errors(
            lambda judge: judge.update(status="candidate", canary=None, determinismClass="unmeasured"))))
        self.assertTrue(any("only a calibrated ceiling" in error for error in errors(
            lambda judge: judge["resources"].update(ceilingStatus="provisional"))))
        self.assertTrue(any("ceilingStatus is" in error for error in errors(
            lambda judge: judge["resources"].update(ceilingStatus="measured"))))
        self.assertTrue(any("determinismClass is one of" in error for error in errors(
            lambda judge: judge.update(status="candidate", determinismClass="bitwise"))))
        # A warn judge's canary must also match today's worker sources.
        worker = repository / "scripts/lib/qc_pipeline/panel_engines.py"
        worker.write_text(worker.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        self.assertTrue(any("judge canary is required" in error for error in errors(
            lambda judge: judge.update(status="warn"))))
        self.assertEqual(errors(lambda judge: None), [], "a shadow judge keeps its canary across worker edits")


GIB = 1024**3
CANARY_SESSION = "20260928-89abcdef"
RECALIBRATION_SESSION = "20260929-0123abcd"
# The recalibration fixture's workers outgrow the footprint (48 MiB) their canary session measured.
COHORT_FOOTPRINT = 256 * MIB


def cohort_supervisor(command, **kwargs):
    """The canonical fixture host, with workers whose footprint a full cohort grows past their canary ceiling."""
    result = run_supervised(command, snapshotter=lambda: HostSnapshot(50.0, 0, False),
                            rss_sampler=lambda _pid: 32 * MIB, physical_footprint_sampler=lambda _pid: COHORT_FOOTPRINT,
                            **kwargs)
    result.report["hostProfileID"] = CANONICAL_HOST
    return result


def output_identity(judge_id: str) -> str:
    return hashlib.sha256(judge_id.encode("utf-8")).hexdigest()


def shadow_registry() -> dict:
    """The un-promoted registry with PYIN and Audiobox shadow at fixed canary ceilings (never the live ones)."""
    registry = registry_tests.unpromoted_registry()
    for judge_id, peak in ((PYIN, 400 * MIB), (AUDIOBOX, 2 * GIB)):
        judge = registry["judges"][judge_id]
        judge.update(status="shadow", determinismClass="D0",
                     canary={"record": f"benchmarks/audio-qc-qualification/{CANARY_SESSION}/judges/x.json",
                             "sha256": "b" * 64, "outputIdentity": output_identity(judge_id), "date": "2026-09-28"})
        judge["resources"].update(ceilingStatus="calibrated", canonicalHostPeakBytes=peak,
                                  ceilingBytes=q.admission_ceiling(peak), ceilingSession=CANARY_SESSION)
    return registry


def ceiling_record(registry: dict, judge_id: str, *, peak: int, session: str = RECALIBRATION_SESSION,
                   host: str = CANONICAL_HOST, failures: tuple[str, ...] = (), identity: str | None = None,
                   budget_bytes: int | None = None) -> dict:
    judge = registry["judges"][judge_id]
    resources = q.run_resources(worker(envelope(peakRSSBytes=peak, hostProfileID=host,
                                                qualificationFailures=list(failures))),
                                canonical_host=CANONICAL_HOST)
    run = {"resources": resources, "raw": {"t": {"f0Hz": [1.0]}},
           "measurements": {"t": {"status": "complete", "metrics": {"f0MedianHz": 1.0}}}}
    return q.ceiling_analysis(
        judge_id, runs=[run, copy.deepcopy(run)],
        identity={"outputIdentity": identity or output_identity(judge_id),
                  "components": {"registryEntrySHA256": acquisition_entry_digest(judge), "workerSourceSHA256": {},
                                 "threads": 1, "hostProfile": HOST}},
        takes=[{"takeID": "t", "language": "english", "audioSHA256": "c" * 64, "canonicalPCMSHA256": "d" * 64}],
        session={"id": session, "date": q.session_date(session), "hostProfileID": host},
        canary_set={"sha256": "e" * 64, "takes": 1}, registry_sha256="f" * 64,
        budget_bytes=budget_bytes or registry["admission"]["budgetBytes"],
        reservation_bytes=registry["admission"]["orchestratorReservationBytes"],
    )


def recalibration_session(records: dict, *, session: str = RECALIBRATION_SESSION,
                          host: str = CANONICAL_HOST) -> dict:
    return {"schema": q.SESSION_SCHEMA, "purpose": q.RECALIBRATION_PURPOSE,
            "session": {"id": session, "date": q.session_date(session), "hostProfileID": host},
            "judges": {judge_id: {"passed": record["recalibration"]["passed"],
                                  "record": f"judges/{q.record_file_name(judge_id)}"}
                       for judge_id, record in records.items()}}


class RecalibrationEditTests(unittest.TestCase):
    """`recalibration_edits` over fixed fixture ceilings: which judges move, which refuse, and why."""

    def setUp(self) -> None:
        self.registry = shadow_registry()

    def _edits(self, records: dict, **options) -> tuple[dict, dict, dict]:
        session = recalibration_session(records, **{key: options.pop(key) for key in ("session", "host")
                                                    if key in options})
        return q.recalibration_edits(self.registry, session, records, canonical_host=CANONICAL_HOST, **options)

    def test_a_larger_full_cohort_peak_raises_the_ceiling_and_keeps_the_history(self) -> None:
        records = {PYIN: ceiling_record(self.registry, PYIN, peak=600 * MIB),
                   AUDIOBOX: ceiling_record(self.registry, AUDIOBOX, peak=3 * GIB)}
        self.assertEqual([q.validate_ceiling_record(record) for record in records.values()], [[], []])
        before = copy.deepcopy(self.registry)
        edits, changed, refused = self._edits(records)
        self.assertEqual(refused, {})
        self.assertEqual(set(edits), {("judges", PYIN, "resources"), ("judges", AUDIOBOX, "resources")},
                         "only resources change: status, identity and canary never do")
        pyin = edits[("judges", PYIN, "resources")]
        self.assertEqual((pyin["canonicalHostPeakBytes"], pyin["ceilingBytes"], pyin["ceilingSession"],
                          pyin["ceilingStatus"]),
                         (600 * MIB, q.admission_ceiling(600 * MIB), RECALIBRATION_SESSION, "calibrated"))
        self.assertEqual(pyin["ceilingHistory"], [{"ceilingSession": CANARY_SESSION, "date": "2026-09-28",
                                                   "canonicalHostPeakBytes": 400 * MIB,
                                                   "ceilingBytes": q.admission_ceiling(400 * MIB)}])
        self.assertEqual(pyin["provisionalCeilingBytes"], before["judges"][PYIN]["resources"]["provisionalCeilingBytes"])
        self.assertEqual(changed[AUDIOBOX]["fromBytes"], q.admission_ceiling(2 * GIB))
        self.assertEqual(changed[AUDIOBOX]["toBytes"], q.admission_ceiling(3 * GIB))
        self.assertEqual(self.registry, before, "the edits are computed, never applied in place")
        # A second recalibration appends to the history, oldest first.
        self.registry["judges"][PYIN]["resources"] = pyin
        later = "20261003-00c0ffee"
        edits, _changed, refused = self._edits({PYIN: ceiling_record(self.registry, PYIN, peak=700 * MIB,
                                                                     session=later)}, session=later)
        self.assertEqual(refused, {})
        history = edits[("judges", PYIN, "resources")]["ceilingHistory"]
        self.assertEqual([item["ceilingSession"] for item in history], [CANARY_SESSION, RECALIBRATION_SESSION])
        # The same session never recalibrates twice.
        _edits, _changed, refused = self._edits({PYIN: ceiling_record(self.registry, PYIN, peak=600 * MIB)})
        self.assertEqual(refused, {PYIN: "already-recalibrated"})

    def test_unclean_off_host_over_budget_candidate_and_foreign_runs_are_refused(self) -> None:
        cases = {
            "run-1-not-clean": ceiling_record(self.registry, PYIN, peak=600 * MIB,
                                              failures=("post-exit-memory-recovery-unqualified",)),
            "not-canonical-host": ceiling_record(self.registry, PYIN, peak=600 * MIB, host="mac-mini-m2-8gb"),
            "identity-mismatch": ceiling_record(self.registry, PYIN, peak=600 * MIB, identity="9" * 64),
            # The record already fails the session's budget.
            "ceiling-exceeds-budget": ceiling_record(self.registry, PYIN, peak=9 * GIB),
        }
        for reason, record in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(q.validate_ceiling_record(record), [])
                edits, _changed, refused = self._edits({PYIN: record})
                self.assertEqual(edits, {})
                self.assertTrue(refused[PYIN].startswith(reason), refused)
        # A session measured off the canonical host is refused even when its envelopes claim it.
        _edits, _changed, refused = self._edits({PYIN: ceiling_record(self.registry, PYIN, peak=600 * MIB)},
                                                host="mac-mini-m2-8gb")
        self.assertEqual(refused, {PYIN: "not-canonical-host"})
        # A record that fit a larger session budget still refuses against the registry's own budget.
        roomy = ceiling_record(self.registry, PYIN, peak=9 * GIB, budget_bytes=64 * GIB)
        self.assertTrue(roomy["recalibration"]["passed"])
        self.assertEqual(self._edits({PYIN: roomy})[2], {PYIN: "ceiling-exceeds-budget"})
        # A candidate is qualified by `promote`, never recalibrated.
        self.registry["judges"][PYIN].update(status="candidate")
        self.assertEqual(self._edits({PYIN: ceiling_record(self.registry, PYIN, peak=600 * MIB)})[2],
                         {PYIN: "status-candidate"})
        # A judge whose registry entry changed since its canary measured another output.
        self.registry = shadow_registry()
        record = ceiling_record(self.registry, PYIN, peak=600 * MIB)
        self.registry["judges"][PYIN]["execution"]["threads"] += 1
        self.assertEqual(self._edits({PYIN: record})[2], {PYIN: "identity-mismatch"})
        # A qualification session never recalibrates.
        session = {**recalibration_session({PYIN: record}), "purpose": q.QUALIFICATION_PURPOSE}
        with self.assertRaisesRegex(q.QualificationError, "ceiling-recalibration session"):
            q.recalibration_edits(self.registry, session, {PYIN: record}, canonical_host=CANONICAL_HOST)

    def test_a_lower_ceiling_needs_allow_lower(self) -> None:
        records = {PYIN: ceiling_record(self.registry, PYIN, peak=300 * MIB)}
        edits, _changed, refused = self._edits(records)
        self.assertEqual((edits, refused), ({}, {PYIN: "would-lower-ceiling"}))
        edits, changed, refused = self._edits(records, allow_lower=True)
        self.assertEqual(refused, {})
        self.assertEqual(edits[("judges", PYIN, "resources")]["ceilingBytes"], q.admission_ceiling(300 * MIB))
        self.assertLess(changed[PYIN]["toBytes"], changed[PYIN]["fromBytes"])

    def test_a_recalibration_admits_every_judge_at_the_measurement_ceiling(self) -> None:
        budget = self.registry["admission"]["budgetBytes"] - self.registry["admission"]["orchestratorReservationBytes"]
        calibrated = judge_admission(self.registry, PYIN, measurement=True)
        self.assertEqual((calibrated.ceiling_bytes, calibrated.ceiling_basis),
                         (q.admission_ceiling(400 * MIB), "calibrated-canonical-host-peak-x1.2"))
        for judge_id in (PYIN, PARAKEET, q.BASELINE_RECOGNIZER):
            admitted = judge_admission(self.registry, judge_id, measurement=True, recalibration=True)
            self.assertEqual((admitted.ceiling_bytes, admitted.ceiling_basis),
                             (budget, "recalibration-measurement-budget"), judge_id)

    def test_a_ceiling_record_keeps_digests_and_counts_not_take_rows(self) -> None:
        record = ceiling_record(self.registry, PYIN, peak=600 * MIB)
        self.assertEqual(record["takes"]["rows"], 1)
        self.assertEqual(q.validate_ceiling_record(record), [])
        for mutate, expected in (
            (lambda value: value["takes"].update(rows=0), "takes counts"),
            (lambda value: value.update(takes=[{"metrics": {}}]), "takes counts"),
            (lambda value: value["recalibration"].update(passed=False), "passes exactly when"),
            (lambda value: value["runs"][0].update(clean=False, failures=["retried"]), "passing recalibration"),
            (lambda value: value.update(qualification={"passed": True, "reasons": []}), "exactly"),
            (lambda value: value["takes"].update(transcript="hello there"), "takes counts"),
        ):
            changed = copy.deepcopy(record)
            mutate(changed)
            problems = q.validate_ceiling_record(changed)
            self.assertTrue(any(expected in problem for problem in problems), (expected, problems))


class RecalibrationSessionTests(QualificationFixture):
    """A promoted fixture panel, then a full-cohort recalibration session, its records and `recalibrate`."""

    def _promoted(self) -> tuple[Path, Path, dict]:
        session_dir, _summary = self._session()
        repository = self._repository()
        published = cli.publish(session_dir, repository / "benchmarks/audio-qc-qualification")
        registry_tests._git(repository, "init", "-q")
        registry_tests._git(repository, "add", "-A", "--", "config", "benchmarks", "scripts")
        registry_tests._git(repository, "commit", "-qm", "fixture repository and qualification records")
        cli.promote(published, root=repository)
        registry_tests._git(repository, "commit", "-qam", "promotion")
        registry = json.loads((repository / "config/audio-qc-judges.json").read_text(encoding="utf-8"))
        return repository, published, registry

    def test_a_full_cohort_session_raises_shadow_ceilings_with_their_history(self) -> None:
        repository, qualification, promoted = self._promoted()
        panel = [PYIN, CAMPPLUS, AUDIOBOX]
        self.assertEqual({promoted["judges"][judge]["status"] for judge in panel}, {"shadow"})
        judges = [judge for judge in self._judges(self.root / "cohort-launches") if judge.judge_id in panel]
        cohort = [self.take(f"cohort-{index}", self.audio(f"cohort-{index}", 300 + 40 * index), "english")
                  for index in range(3)]
        speech = self.manifest(cohort, run_id="cohort")
        with self.assertRaisesRegex(cli.QualificationRunError, "full-cohort manifest"):
            cli.start_session(self.root / "recalibrations", speech=None, panel=panel, legacy=[],
                              purpose=q.RECALIBRATION_PURPOSE)
        session_dir, manifest = cli.start_session(self.root / "recalibrations", speech=speech, panel=panel, legacy=[],
                                                  today=dt.date(2026, 9, 29), purpose=q.RECALIBRATION_PURPOSE)
        cli.run_session(registry=promoted, manifest=manifest, judges=judges, resampler="polyphase-kaiser5-v2",
                        session_dir=session_dir, supervisor=cohort_supervisor, lock_root=self.root / "locks",
                        preflight=lambda: {"loadAverage1M": 1.0, "busy": False}, host=HOST,
                        host_profile_id=CANONICAL_HOST)
        summary = cli.analyze_session(session_dir, registry=promoted)
        self.assertEqual((summary["purpose"], summary["flipAnalysis"]), (q.RECALIBRATION_PURPOSE, None))
        self.assertEqual({judge: entry["passed"] for judge, entry in summary["judges"].items()},
                         dict.fromkeys(panel, True))
        records = session_dir / "records"
        budget = promoted["admission"]["budgetBytes"] - promoted["admission"]["orchestratorReservationBytes"]
        for judge_id in panel:
            record = json.loads((records / "judges" / q.record_file_name(judge_id)).read_text(encoding="utf-8"))
            self.assertEqual(q.validate_ceiling_record(record), [])
            self.assertEqual(record["outputIdentity"], promoted["judges"][judge_id]["canary"]["outputIdentity"])
            self.assertEqual(record["takes"]["rows"], len(manifest["takes"]))
            # A calibrated judge runs under the measurement ceiling, not its canary ceiling.
            launches = [launch for run in record["runs"] for launch in run["launchEnvelopes"]]
            self.assertEqual({(launch["ceilingBytes"], launch["ceilingBasis"]) for launch in launches},
                             {(budget, "recalibration-measurement-budget")})
            self.assertGreaterEqual(record["resources"]["canonicalHostPeakBytes"], COHORT_FOOTPRINT)
        for path in records.rglob("*.json"):
            self.assertEqual(q.validate_record_file(path), [], path.name)
            self.assertNotIn(str(self.root), path.read_text(encoding="utf-8"), "no private path in a record")
        records_root = repository / "benchmarks/audio-qc-qualification"
        published = cli.publish(session_dir, records_root)
        self.assertEqual(q.validate_records(records_root), [])
        registry_path = repository / "config/audio-qc-judges.json"
        original = registry_path.read_text(encoding="utf-8")
        with self.assertRaisesRegex(cli.QualificationRunError, "commit the session's records"):
            cli.recalibrate(published, root=repository)
        with self.assertRaisesRegex(cli.QualificationRunError, "not a ceiling-recalibration session"):
            cli.recalibrate(qualification, root=repository)
        with self.assertRaisesRegex(cli.QualificationRunError, "only a qualification session promotes"):
            cli.promote(published, root=repository)
        registry_tests._git(repository, "add", "--", "benchmarks/audio-qc-qualification")
        registry_tests._git(repository, "commit", "-qm", "recalibration records")
        dry = cli.recalibrate(published, root=repository, dry_run=True)
        self.assertEqual(registry_path.read_text(encoding="utf-8"), original, "a dry run writes nothing")
        self.assertEqual((sorted(dry["recalibrated"]), dry["refused"], dry["written"]), (sorted(panel), {}, False))
        result = cli.recalibrate(published, root=repository)
        self.assertTrue(result["written"])
        updated = json.loads(registry_path.read_text(encoding="utf-8"))
        for judge_id in panel:
            before, after = promoted["judges"][judge_id], updated["judges"][judge_id]
            record = json.loads((published / "judges" / q.record_file_name(judge_id)).read_text(encoding="utf-8"))
            resources = after["resources"]
            self.assertEqual((resources["canonicalHostPeakBytes"], resources["ceilingBytes"],
                              resources["ceilingSession"]),
                             (record["resources"]["canonicalHostPeakBytes"],
                              record["resources"]["admissionCeilingBytes"], published.name))
            self.assertGreater(resources["ceilingBytes"], before["resources"]["ceilingBytes"])
            self.assertEqual(resources["ceilingHistory"], [{
                "ceilingSession": qualification.name, "date": "2026-09-28",
                "canonicalHostPeakBytes": before["resources"]["canonicalHostPeakBytes"],
                "ceilingBytes": before["resources"]["ceilingBytes"]}])
            self.assertEqual({key: value for key, value in after.items() if key != "resources"},
                             {key: value for key, value in before.items() if key != "resources"},
                             "status, identity, class and canary never change")
            # Every later run admits the judge at its full-cohort ceiling.
            self.assertEqual(judge_admission(updated, judge_id, measurement=True).ceiling_bytes,
                             resources["ceilingBytes"])
        self.assertEqual(validate_repository(repository, updated), [])
        self.assertEqual(updated["judges"][WHISPER_LARGE], promoted["judges"][WHISPER_LARGE],
                         "a judge the session did not measure keeps its ceiling")
        again = cli.recalibrate(published, root=repository)
        self.assertEqual((again["written"], set(again["refused"].values())), (False, {"already-recalibrated"}))

        # Registry integrity: a recalibrated ceiling is its committed ceiling record's, with its history.
        def errors(mutate) -> list[str]:
            registry = copy.deepcopy(updated)
            mutate(registry["judges"][PYIN]["resources"])
            return [error for error in validate_registry(registry, root=repository) if PYIN in error]

        def history(**changes):
            return lambda resources: resources["ceilingHistory"][0].update(**changes)

        self.assertEqual(errors(lambda resources: None), [])
        self.assertTrue(any("no ceilingHistory" in error for error in errors(
            lambda resources: resources.pop("ceilingHistory"))))
        self.assertTrue(any("recalibration record measured" in error for error in errors(
            lambda resources: resources.update(canonicalHostPeakBytes=resources["canonicalHostPeakBytes"] + 10,
                                               ceilingBytes=q.admission_ceiling(
                                                   resources["canonicalHostPeakBytes"] + 10)))))
        self.assertTrue(any("peak x 1.2" in error for error in errors(
            history(ceilingBytes=promoted["judges"][PYIN]["resources"]["ceilingBytes"] + 1))))
        self.assertTrue(any("its date is its session's" in error for error in errors(history(date="2026-09-30"))))
        self.assertTrue(any("records exactly" in error for error in errors(history(note="lowered"))))
        self.assertTrue(any("not a published session" in error for error in errors(
            history(ceilingSession="20260101-00000000", date="2026-01-01"))))
        self.assertTrue(any("distinct earlier sessions" in error for error in errors(
            lambda resources: resources["ceilingHistory"].append(copy.deepcopy(resources["ceilingHistory"][0])))))
        self.assertTrue(any("not a published session" in error for error in errors(
            lambda resources: resources.update(ceilingSession="20261001-00000000"))))
        self.assertTrue(any("records no ceilingHistory" in error for error in errors(
            lambda resources: resources.update(ceilingSession=qualification.name, **{
                key: promoted["judges"][PYIN]["resources"][key]
                for key in ("canonicalHostPeakBytes", "ceilingBytes")}))))
        self.assertTrue(any("only a calibrated ceiling" in error for error in errors(
            lambda resources: resources.update(ceilingStatus="provisional", ceilingBytes=None,
                                               ceilingSession=None))))
        # The ceiling record behind a recalibrated ceiling must stay committed as it is.
        record_path = published / "judges" / q.record_file_name(PYIN)
        record_path.write_text(record_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.assertTrue(any("differs from its committed version" in error for error in errors(lambda resources: None)))


class RecordValidationTests(unittest.TestCase):
    def test_a_record_carrying_text_or_an_inconsistent_verdict_is_refused(self) -> None:
        record = q.judge_analysis(
            PYIN, runs=[{"resources": q.run_resources(worker(envelope()), canonical_host=CANONICAL_HOST),
                         "raw": {"t": {"f0Hz": [1.0]}}, "measurements": {"t": {"status": "complete",
                                                                                 "metrics": {"f0MedianHz": 1.0}}}}] * 2,
            identity={"outputIdentity": "a" * 64,
                      "components": {"registryEntrySHA256": "b" * 64, "workerSourceSHA256": {}, "threads": 1,
                                     "hostProfile": HOST}},
            takes=[{"takeID": "t", "language": "english", "audioSHA256": "c" * 64, "canonicalPCMSHA256": "d" * 64}],
            session={"id": "20260928-0123abcd", "date": "2026-09-28", "hostProfileID": CANONICAL_HOST},
            canary_set={"sha256": "e" * 64, "takes": 1}, registry_sha256="f" * 64,
            budget_bytes=10 * 1024**3, reservation_bytes=512 * 1024**2,
        )
        self.assertEqual(q.validate_canary_record(record), [])
        self.assertTrue(record["qualification"]["passed"])
        leaked = copy.deepcopy(record)
        leaked["takes"][0]["metrics"]["transcript"] = "hello"
        self.assertTrue(any("transcript" in error for error in q.validate_canary_record(leaked)))
        spaced = copy.deepcopy(record)
        spaced["takes"][0]["metrics"]["language"] = "a sentence with spaces"
        self.assertTrue(q.validate_canary_record(spaced))
        dishonest = copy.deepcopy(record)
        dishonest["determinism"]["class"] = "D2"
        self.assertTrue(any("passing qualification" in error for error in q.validate_canary_record(dishonest)))

    def test_the_committed_records_validate(self) -> None:
        completed = subprocess.run([sys.executable, str(REPO / "scripts/audio_qc_panel_qualification.py"), "validate"],
                                   capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
