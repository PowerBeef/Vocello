#!/usr/bin/env python3
"""One persistent worker per judge per run: protocol, crash isolation, timeouts and engines (AQ-05)."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_worker  # noqa: E402
from delivery_resource_supervisor import HostSnapshot, SupervisedResult, run_supervised  # noqa: E402
from lib.qc_pipeline.admission import AdmissionPolicy, HostAdmission, JudgeAdmission  # noqa: E402
from lib.qc_pipeline.workers import (  # noqa: E402
    WorkerProtocolError,
    WorkerSpec,
    parse_worker_stream,
    run_persistent_worker,
)

FIXTURE_WORKER = Path(__file__).resolve().parent / "fixtures/audio_qc_fixture_worker.py"
GIB = 1024**3
MIB = 1024**2


def quiet_supervisor(command, **kwargs):
    """The real supervisor on a host whose memory probes read clean."""
    return run_supervised(command, snapshotter=lambda: HostSnapshot(50.0, 0, False),
                          rss_sampler=lambda _pid: 32 * MIB, **kwargs)


class WorkerStreamTests(unittest.TestCase):
    def test_complete_lines_are_parsed_and_a_torn_line_is_ignored(self) -> None:
        stream = (b'{"kind": "ready", "engine": "fixture", "threads": 2}\n'
                  b'{"kind": "row", "id": "a", "result": {"x": 1}}\n'
                  b'{"kind": "row-error", "id": "b", "reason": "analysis-failed", "childMaxRSSBytes": 9}\n'
                  b'{"kind": "row", "id": "c", "res')
        parsed = parse_worker_stream(stream, ["a", "b", "c"])
        self.assertEqual(parsed.rows, {"a": {"x": 1}})
        self.assertEqual(parsed.row_errors, {"b": "analysis-failed"})
        self.assertEqual(parsed.child_peaks, {"b": 9})
        self.assertFalse(parsed.done)
        self.assertEqual(parsed.ready["threads"], 2)
        for bad in (b'{"kind": "row", "id": "z", "result": {}}\n', b'[1]\n',
                    b'{"kind": "row", "id": "a", "result": {}}\n{"kind": "row", "id": "a", "result": {}}\n',
                    b'{"kind": "row", "id": "a", "result": 3}\n'):
            with self.subTest(bad=bad), self.assertRaises(WorkerProtocolError):
                parse_worker_stream(bad, ["a"])

    def test_the_worker_refuses_a_thread_count_its_environment_does_not_fix(self) -> None:
        job = {"kind": audio_qc_worker.JOB_KIND, "protocol": audio_qc_worker.PROTOCOL, "threads": 2,
               "engine": "fixture", "engineConfig": {}, "rows": [{"id": "a", "pcmPath": "x"}]}
        with self.assertRaisesRegex(audio_qc_worker.WorkerJobError, "thread environment"):
            audio_qc_worker.validate_job(job, {"OMP_NUM_THREADS": "8"})
        environment = audio_qc_worker.thread_environment(2)
        self.assertIs(audio_qc_worker.validate_job(job, environment), job)
        self.assertEqual(environment["VECLIB_MAXIMUM_THREADS"], "2")
        with self.assertRaisesRegex(audio_qc_worker.WorkerJobError, "unique"):
            audio_qc_worker.validate_job({**job, "rows": [{"id": "a"}, {"id": "a"}]}, environment)

    def test_the_whisper_engine_loads_once_and_streams_every_row(self) -> None:
        loads = []

        class FakeRecognizer:
            def __init__(self, model_dir, decode, *, warmup_language=None):
                loads.append((model_dir.name, decode, warmup_language))
                self.model_load_seconds, self.warmup_seconds = 1.5, 0.5

            def recognize(self, audio, language):
                return {"transcript": f"{len(audio)} samples", "language": language, "detectedLanguage": language,
                        "segments": [], "decodedSampleCount": len(audio), "sampleRateHz": 16000, "wallSeconds": 0.1}

        with tempfile.TemporaryDirectory() as temporary:
            rows = []
            for index in range(3):
                pcm = Path(temporary) / f"{index}.pcm"
                pcm.write_bytes(b"\x00\x01" * (100 + index))
                rows.append({"id": f"row-{index}", "pcmPath": str(pcm), "language": "fr"})
            rows.append({"id": "missing", "pcmPath": str(Path(temporary) / "absent.pcm"), "language": "fr"})
            job = {"kind": audio_qc_worker.JOB_KIND, "protocol": audio_qc_worker.PROTOCOL, "threads": 2,
                   "engine": "whisper-mlx", "engineConfig": {"weights": str(Path(temporary) / "model/weights.npz"),
                                                             "decodeOptions": {"temperature": 0.0}},
                   "rows": rows}
            emitted = []
            with mock.patch("independent_asr_worker.Recognizer", FakeRecognizer):
                audio_qc_worker.run(job, emit=emitted.append, environment=audio_qc_worker.thread_environment(2))
        self.assertEqual(loads, [("model", {"temperature": 0.0}, "fr")])
        self.assertEqual([item["kind"] for item in emitted], ["ready", "row", "row", "row", "row-error", "done"])
        self.assertEqual(emitted[0]["modelLoadSeconds"], 1.5)
        self.assertEqual(emitted[2]["result"]["decodedSampleCount"], 101)


class PersistentWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.rows = self._clips(4)
        self.policy = AdmissionPolicy(budget_bytes=10 * GIB, lane_limits={"gpu": 1, "cpu": 2, "dsp": 4},
                                      orchestrator_reservation_bytes=GIB // 2,
                                      recovery_rule="whole-host-free-percent-v1", worker_cap=1)
        self.judge = JudgeAdmission("asr.fixture@1", "gpu", GIB, "provisional", 2, "fixture")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _clips(self, count: int) -> list[dict]:
        self.table = getattr(self, "table", {})
        rows = []
        for index in range(count):
            pcm = self.root / f"clip-{index}.pcm"
            pcm.write_bytes(bytes([index + 1]) * 3200)
            digest = hashlib.sha256(pcm.read_bytes()).hexdigest()
            self.table[digest] = {"transcript": f"clip {index}", "detectedLanguage": "en"}
            rows.append({"id": f"row-{index}", "pcmPath": str(pcm), "language": "en", "digest": digest})
        return rows

    def _spec(self, *, row_timeout: float = 60.0, startup: float = 60.0, **config) -> WorkerSpec:
        return WorkerSpec(judge_id="asr.fixture@1", engine="fixture", command=(sys.executable, str(FIXTURE_WORKER)),
                          threads=2, lane="gpu", ceiling_bytes=GIB,
                          engine_config={"table": self.table, **config},
                          row_timeout_seconds=row_timeout, startup_seconds=startup)

    def _run(self, spec: WorkerSpec, *, supervisor=quiet_supervisor, rows=None, adopt=None):
        host = HostAdmission(self.root / "locks", self.policy)
        with host.run() as run:
            outcome = run_persistent_worker(
                spec, [{key: row[key] for key in ("id", "pcmPath", "language")} for row in rows or self.rows],
                workdir=self.root / "work", lock_root=self.root / "locks", run_admission=run,
                judge_admission=self.judge, supervisor=supervisor, adopt=adopt,
            )
        self.assertEqual(host.status()["tickets"], [])
        return outcome

    def test_every_row_runs_in_one_admitted_worker(self) -> None:
        outcome = self._run(self._spec())
        self.assertEqual(len(outcome.launches), 1)
        self.assertEqual(sorted(outcome.results), [row["id"] for row in self.rows])
        self.assertEqual(outcome.results["row-2"]["transcript"], "clip 2")
        self.assertEqual(outcome.unavailable, {})
        envelope = outcome.launches[0]["resourceEnvelope"]
        self.assertTrue(envelope["qualified"])
        self.assertEqual(envelope["exclusion"], "budgeted-admission")
        self.assertEqual(envelope["admission"]["judge"], "asr.fixture@1")
        self.assertEqual(envelope["maximumAllowedRSSBytes"], GIB)
        self.assertEqual(outcome.ready["threads"], 2)

    def test_a_crash_keeps_emitted_rows_and_isolates_the_row_in_flight(self) -> None:
        marker = self.root / "crashed"
        outcome = self._run(self._spec(crashOnce=self.rows[2]["digest"], crashMarker=str(marker)))
        self.assertTrue(marker.exists())
        # The job, then the row in flight alone, then the rest.
        self.assertEqual([launch["kind"] for launch in outcome.launches], ["job", "isolated", "remainder"])
        self.assertEqual([launch["rows"] for launch in outcome.launches], [4, 1, 1])
        self.assertEqual([launch["rowsAccepted"] for launch in outcome.launches], [2, 1, 1])
        self.assertIn("nonzero-exit", outcome.launches[0]["resourceEnvelope"]["qualificationFailures"])
        self.assertEqual(sorted(outcome.results), [row["id"] for row in self.rows])
        self.assertEqual(outcome.row_launch, {"row-0": 1, "row-1": 1, "row-2": 2, "row-3": 3})

    def test_one_bad_row_of_eight_never_costs_the_other_seven(self) -> None:
        rows = self._clips(8)
        bad = rows[3]
        outcome = self._run(self._spec(crashAlways=bad["digest"]), rows=rows)
        self.assertEqual(outcome.unavailable, {bad["id"]: "crash"})
        self.assertEqual(sorted(outcome.results), sorted(row["id"] for row in rows if row is not bad))
        # Nothing is counted twice or dropped: every row ends exactly once.
        self.assertFalse(set(outcome.results) & set(outcome.unavailable))
        self.assertEqual(set(outcome.results) | set(outcome.unavailable), {row["id"] for row in rows})
        self.assertEqual([(launch["kind"], launch["rows"], launch["rowsAccepted"]) for launch in outcome.launches],
                         [("job", 8, 3), ("isolated", 1, 0), ("remainder", 4, 4)])
        self.assertEqual({outcome.row_launch[row["id"]] for row in rows[4:]}, {3})

    def test_a_row_that_crashes_twice_is_unavailable_and_nothing_else_is_lost(self) -> None:
        outcome = self._run(self._spec(crashAlways=self.rows[1]["digest"], rowError=self.rows[3]["digest"]))
        self.assertEqual(len(outcome.launches), 3)
        self.assertEqual(sorted(outcome.results), ["row-0", "row-2"])
        # Only the row that crashed two workers is unavailable as a crash; the
        # engine's own row error stays what the engine said.
        self.assertEqual(outcome.unavailable, {"row-1": "crash", "row-3": "analysis-failed"})

    def test_an_engine_error_is_unavailable_without_a_retry(self) -> None:
        outcome = self._run(self._spec(rowError=self.rows[3]["digest"]))
        self.assertEqual(len(outcome.launches), 1)
        self.assertEqual(outcome.unavailable, {"row-3": "analysis-failed"})
        self.assertEqual(len(outcome.results), 3)

    def test_a_failed_host_condition_accepts_nothing_and_never_retries(self) -> None:
        def recovery_failed(command, **kwargs):
            result = quiet_supervisor(command, **kwargs)
            report = dict(result.report, qualified=False,
                          qualificationFailures=["post-exit-memory-recovery-unqualified"])
            return SupervisedResult(report, result.stdout, result.stderr)

        outcome = self._run(self._spec(), supervisor=recovery_failed)
        self.assertEqual(len(outcome.launches), 1)
        self.assertEqual(outcome.results, {})
        self.assertEqual(set(outcome.unavailable.values()), {"envelope-breach"})

    def test_a_worker_without_its_thread_environment_never_emits(self) -> None:
        def stripped(command, **kwargs):
            environment = dict(kwargs.pop("environment"))
            environment["OMP_NUM_THREADS"] = "7"
            return quiet_supervisor(command, environment=environment, **kwargs)

        # It never becomes ready, so no row was in flight: one retry of the
        # whole job, then every row is unavailable.
        outcome = self._run(self._spec(), supervisor=stripped)
        self.assertEqual([launch["kind"] for launch in outcome.launches], ["job", "retry"])
        self.assertEqual(set(outcome.unavailable.values()), {"crash"})

    def test_the_timeout_scales_with_the_rows_and_honours_the_per_row_budget(self) -> None:
        rows = self._clips(8)
        timeouts = []

        def recording(command, **kwargs):
            timeouts.append(kwargs["timeout_seconds"])
            return quiet_supervisor(command, **kwargs)

        # Eight rows of 0.3 s each outlast any single row's budget (1 s) plus
        # the start-up allowance, but not the job's scaled one.
        outcome = self._run(self._spec(row_timeout=1.0, startup=1.5, sleepPerRow=0.3), rows=rows,
                            supervisor=recording)
        self.assertEqual(timeouts, [1.5 + 8 * 1.0])
        self.assertEqual(outcome.launches[0]["timeoutSeconds"], 9.5)
        self.assertEqual(len(outcome.results), 8)
        self.assertEqual(outcome.unavailable, {})

    def test_a_row_that_hangs_times_out_alone(self) -> None:
        hung = self.rows[1]
        outcome = self._run(self._spec(row_timeout=0.5, startup=1.0, hangOn=hung["digest"]))
        self.assertEqual(outcome.unavailable, {hung["id"]: "timeout"})
        self.assertEqual(sorted(outcome.results), ["row-0", "row-2", "row-3"])
        self.assertEqual([(launch["kind"], launch["timeoutSeconds"]) for launch in outcome.launches],
                         [("job", 3.0), ("isolated", 1.5), ("remainder", 2.0)])

    def test_timing_rides_beside_the_result_and_adopted_rows_launch_nothing(self) -> None:
        outcome = self._run(self._spec(measureWall=True))
        for identity, result in outcome.results.items():
            self.assertNotIn("wallSeconds", result)
            self.assertGreaterEqual(outcome.timings[identity], 0.0)
        stored = {row["id"]: {"transcript": "stored by another run"} for row in self.rows[:3]}
        checked = []

        def adopt(batch):
            checked.append([row["id"] for row in batch])
            return {row["id"]: stored[row["id"]] for row in batch if row["id"] in stored}

        adopted = self._run(self._spec(), adopt=adopt)
        # Re-checked after admission; only the row nobody stored launches.
        self.assertEqual(checked[0], [row["id"] for row in self.rows])
        self.assertEqual(adopted.adopted, stored)
        self.assertEqual(sorted(adopted.results), ["row-3"])
        self.assertEqual(adopted.launches[0]["rows"], 1)
        everything = self._run(self._spec(), adopt=lambda batch: {row["id"]: {"x": 1} for row in batch},
                               supervisor=lambda *args, **kwargs: self.fail("an adopted job launched a worker"))
        self.assertEqual((everything.launches, len(everything.adopted)), ([], 4))

    def test_the_native_engine_reaps_each_invocation_and_reports_its_peak(self) -> None:
        binary = self.root / "fake_sensevoice.py"
        binary.write_text(
            "import sys, wave\n"
            "path = sys.argv[sys.argv.index('-a') + 1]\n"
            "with wave.open(path, 'rb') as reader:\n"
            "    assert reader.getframerate() == 16000\n"
            "    frames = reader.getnframes()\n"
            "print(f'<|en|><|NEUTRAL|><|Speech|><|withitn|>{frames} frames')\n",
            encoding="utf-8",
        )
        spec = WorkerSpec(judge_id="compact.fixture@1", engine="native-command",
                          command=(sys.executable, str(audio_qc_worker.__file__)), threads=2, lane="cpu",
                          ceiling_bytes=GIB, engine_config={
                              "command": [sys.executable, str(binary), "-a", "{audio}", "--keep-tags"],
                              "ceilingBytes": GIB}, row_timeout_seconds=60)
        outcome = run_persistent_worker(
            spec, [{"id": row["id"], "pcmPath": row["pcmPath"]} for row in self.rows],
            workdir=self.root / "work", lock_root=self.root / "locks", supervisor=quiet_supervisor,
        )
        self.assertEqual(len(outcome.launches), 1)
        self.assertEqual(outcome.results["row-0"]["stdout"].strip(), "<|en|><|NEUTRAL|><|Speech|><|withitn|>1600 frames")
        self.assertNotIn("wallSeconds", outcome.results["row-0"])
        self.assertGreater(outcome.launches[0]["descendantPeakRSSBytes"], 0)
        # Without an admission ticket the worker holds the host lock exclusively.
        self.assertEqual(outcome.launches[0]["resourceEnvelope"]["exclusion"], "host-exclusive-lock")
        # A per-invocation peak above the ceiling makes that row unavailable.
        tight = WorkerSpec(**{**spec.__dict__, "ceiling_bytes": 1024,
                              "engine_config": {**spec.engine_config, "ceilingBytes": 1024}})
        breached = run_persistent_worker(
            tight, [{"id": "row-0", "pcmPath": self.rows[0]["pcmPath"]}], workdir=self.root / "tight",
            lock_root=self.root / "locks",
            supervisor=lambda command, **kwargs: quiet_supervisor(
                command, **{**kwargs, "maximum_rss_bytes": GIB, "maximum_physical_footprint_bytes": GIB}),
        )
        self.assertEqual(breached.unavailable, {"row-0": "envelope-breach"})

    def test_the_ceiling_binds_a_native_binary_live_not_after_it_exits(self) -> None:
        """The supervisor samples the worker's process group: a binary above the ceiling is stopped."""
        binary = self.root / "greedy_binary.py"
        binary.write_text(
            "import time\n"
            "hoard = bytearray(96 * 1024 * 1024)\n"
            "for index in range(0, len(hoard), 4096):\n"
            "    hoard[index] = 1\n"
            "time.sleep(20)\n"
            "print('<|en|><|NEUTRAL|><|Speech|><|withitn|>late')\n",
            encoding="utf-8",
        )
        ceiling = 64 * MIB
        spec = WorkerSpec(judge_id="compact.fixture@1", engine="native-command",
                          command=(sys.executable, str(audio_qc_worker.__file__)), threads=2, lane="cpu",
                          ceiling_bytes=ceiling, engine_config={
                              "command": [sys.executable, str(binary), "{audio}"], "ceilingBytes": ceiling},
                          row_timeout_seconds=60, startup_seconds=60)

        def real_probes(command, **kwargs):
            # The real in-process group probe; only host memory reads clean.
            return run_supervised(command, snapshotter=lambda: HostSnapshot(50.0, 0, False), **kwargs)

        started = time.monotonic()
        outcome = run_persistent_worker(
            spec, [{"id": "row-0", "pcmPath": self.rows[0]["pcmPath"]}], workdir=self.root / "greedy",
            lock_root=self.root / "locks", supervisor=real_probes,
        )
        elapsed = time.monotonic() - started
        first = outcome.launches[0]["resourceEnvelope"]
        self.assertTrue(first["resourceLimitTerminated"], first["qualificationFailures"])
        self.assertIn("resource-limit-termination", first["qualificationFailures"])
        self.assertGreater(first["peakRSSBytes"], ceiling)
        self.assertGreaterEqual(first["maximumSampledProcessCount"], 2)
        self.assertEqual(first["sampledProcessScope"], "process-group")
        # Stopped live twice (the job, then the row alone), long before the binary's 20 s.
        self.assertEqual(outcome.unavailable, {"row-0": "envelope-breach"})
        self.assertLess(elapsed, 15.0)


if __name__ == "__main__":
    unittest.main()
