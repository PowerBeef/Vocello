#!/usr/bin/env python3
"""AQ-06 panel qualification (audit P8): canary set, determinism, flips, records and promotion.

No model runs. The session test drives `run_session` with fixture judges under
the real supervisor and admission: a deterministic judge (D0), one whose
scores wobble below a tolerance (D1) and one whose transcript changes between
runs (D2). It proves that both runs are separate sessions with their own
caches, that the records carry digests and metrics only and validate, that the
flip analysis names the flipped takes, and that `promote` moves exactly the
passing candidates to shadow, and only from committed records, leaving every
other byte of the registry alone.
"""

from __future__ import annotations

import copy
import datetime as dt
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
from lib.qc_pipeline import qualification as q  # noqa: E402
import test_audio_qc_judges as registry_tests  # noqa: E402
from test_audio_qc_panel_orchestration import (  # noqa: E402
    AUDIOBOX,
    CAMPPLUS,
    CANONICAL_HOST,
    HOST,
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


class SessionTests(PanelFixture):
    """Both runs, the analysis, publication and promotion, end to end with fixture judges.

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
        session_dir, _summary = self._session()
        repository = self.root / "repository"
        repository.mkdir()
        copier = registry_tests.JudgeRegistryTests("_repository_copy")
        copier.registry, copier.root = self.registry, repository
        copier._repository_copy()
        for relative in ("scripts/lib/qc_pipeline/panel_engines.py", "scripts/lib/qc_pipeline/panel_jobs.py",
                         "scripts/independent_asr_worker.py", "scripts/audio_qc_worker.py"):
            (repository / relative).parent.mkdir(parents=True, exist_ok=True)
            (repository / relative).write_bytes((REPO / relative).read_bytes())
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
