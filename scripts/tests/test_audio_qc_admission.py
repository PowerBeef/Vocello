#!/usr/bin/env python3
"""The budgeted admission semaphore and the recovery-rule switch (AQ-05, decision 9a)."""

from __future__ import annotations

import copy
import fcntl
import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio_qc_judges import JudgeRegistryError, load_registry  # noqa: E402
from delivery_resource_supervisor import (  # noqa: E402
    CANDIDATE_RECOVERY_RULE,
    HOST_LOCK_NAME,
    WHOLE_HOST_RECOVERY_RULE,
    HostSnapshot,
    ProcessSample,
    ResourceSupervisorError,
    process_start_identity,
    recovery_report,
    run_supervised,
)
from lib.qc_pipeline import admission as admission_module  # noqa: E402
from lib.qc_pipeline.workers import WorkerSpec, run_persistent_worker  # noqa: E402
from lib.qc_pipeline.admission import (  # noqa: E402
    AdmissionPolicy,
    AdmissionRefused,
    AdmissionTimeout,
    HostAdmission,
    HostBusy,
    JudgeAdmission,
    admission_decision,
    judge_admission,
)

GIB = 1024**3
MIB = 1024**2
WHISPER = "asr.whisper-small@1"
SENSEVOICE = "compact.sensevoice-small-q8@1"


def _policy(*, budget: int = 10 * GIB, cap: int | None = 1) -> AdmissionPolicy:
    return AdmissionPolicy(budget_bytes=budget, lane_limits={"gpu": 1, "cpu": 2, "dsp": 4},
                           orchestrator_reservation_bytes=GIB // 2,
                           recovery_rule=WHOLE_HOST_RECOVERY_RULE if cap else CANDIDATE_RECOVERY_RULE,
                           worker_cap=cap)



def _running(pid: int) -> bool:
    """A process with this PID still exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True

class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class AdmissionPolicyTests(unittest.TestCase):
    def test_the_registry_policy_is_budgeted_and_serial_until_the_switch(self) -> None:
        policy = AdmissionPolicy.from_registry(load_registry())
        self.assertEqual(policy.budget_bytes, 10 * GIB)
        self.assertEqual(dict(policy.lane_limits), {"gpu": 1, "cpu": 2, "dsp": 4})
        self.assertEqual(policy.recovery_rule, WHOLE_HOST_RECOVERY_RULE)
        # While the whole-host recovery rule binds, one worker at a time host-wide.
        self.assertEqual(policy.worker_cap, 1)
        # A local flip without its committed evidence never takes effect: the
        # registry's admission gate runs when the policy loads.
        registry = copy.deepcopy(load_registry())
        registry["admission"]["recoveryRule"]["candidateBinding"] = True
        with self.assertRaisesRegex(admission_module.AdmissionError, "recovery reports"):
            AdmissionPolicy.from_registry(registry)
        with tempfile.TemporaryDirectory() as temporary:
            flipped_path = Path(temporary) / "audio-qc-judges.json"
            flipped_path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaisesRegex(JudgeRegistryError, "may not load"):
                load_registry(flipped_path)

    def test_a_judge_is_admitted_at_its_registry_ceiling(self) -> None:
        registry = load_registry()
        whisper = judge_admission(registry, WHISPER)
        self.assertEqual((whisper.lane, whisper.ceiling_bytes, whisper.threads, whisper.engine),
                         ("gpu", 2684354560, 2, "whisper-mlx"))
        self.assertEqual(whisper.ceiling_basis, "provisional")
        sensevoice = judge_admission(registry, SENSEVOICE)
        self.assertEqual((sensevoice.lane, sensevoice.ceiling_bytes), ("cpu", 5 * GIB))
        measured = copy.deepcopy(registry)
        measured["judges"][WHISPER]["resources"]["canonicalHostPeakBytes"] = 1_000_000_001
        admitted = judge_admission(measured, WHISPER)
        self.assertEqual((admitted.ceiling_bytes, admitted.ceiling_basis),
                         (1_200_000_002, "measured-canonical-host-peak-x1.2"))
        for judge_id, reason in (("compact.distilhubert@1", "retired"), ("fastqc@8", "not an orchestrated worker"),
                                 ("prosody@3", "neither a measured nor a provisional"),
                                 ("asr.unregistered@1", "not registered")):
            with self.subTest(judge=judge_id), self.assertRaisesRegex(AdmissionRefused, reason):
                judge_admission(registry, judge_id)

    def test_admission_decisions_follow_budget_lanes_and_cap(self) -> None:
        uncapped = _policy(cap=None)
        gpu = {"lane": "gpu", "ceilingBytes": 3 * GIB}
        cpu = {"lane": "cpu", "ceilingBytes": 2 * GIB}
        self.assertEqual(admission_decision(uncapped, [], "gpu", 3 * GIB), ("admit", None))
        self.assertEqual(admission_decision(uncapped, [gpu], "gpu", 3 * GIB), ("wait", "lane-full"))
        self.assertEqual(admission_decision(uncapped, [gpu], "cpu", 2 * GIB), ("admit", None))
        self.assertEqual(admission_decision(uncapped, [gpu, cpu], "cpu", 2 * GIB), ("admit", None))
        self.assertEqual(admission_decision(uncapped, [gpu, cpu, cpu], "cpu", GIB), ("wait", "lane-full"))
        self.assertEqual(admission_decision(uncapped, [gpu, {"lane": "cpu", "ceilingBytes": 6 * GIB}], "cpu", 2 * GIB),
                         ("wait", "budget-exhausted"))
        self.assertEqual(admission_decision(uncapped, [], "cpu", 10 * GIB), ("refuse", "ceiling-exceeds-budget"))
        self.assertEqual(admission_decision(uncapped, [], "tpu", GIB), ("refuse", "unknown-lane"))
        # Serial until the child-attributed rule binds: one worker host-wide.
        capped = _policy(cap=1)
        self.assertEqual(admission_decision(capped, [gpu], "cpu", GIB), ("wait", "worker-cap"))
        # An orchestrator's own reservation is budget only, never a worker slot.
        orchestrator = {"lane": "orchestrator", "ceilingBytes": GIB // 2}
        self.assertEqual(admission_decision(capped, [orchestrator], "gpu", 3 * GIB), ("admit", None))


class HostAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clock = FakeClock()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _host(self, policy: AdmissionPolicy, **kwargs) -> HostAdmission:
        return HostAdmission(self.root, policy, clock=self.clock, sleep=self.clock.sleep,
                             poll_seconds=1.0, wait_seconds=kwargs.pop("wait_seconds", 5.0), **kwargs)

    @staticmethod
    def _judge(lane: str, ceiling: int, judge_id: str = "asr.fixture@1") -> JudgeAdmission:
        return JudgeAdmission(judge_id, lane, ceiling, "provisional", 2, "fixture")

    def test_a_generator_excludes_the_run_and_the_run_excludes_a_generator(self) -> None:
        self.assertEqual(admission_module.HOST_LOCK_NAME, HOST_LOCK_NAME)
        host = self._host(_policy())
        with (self.root / HOST_LOCK_NAME).open("a+b") as generator:
            fcntl.flock(generator.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(HostBusy, "busy host"):
                with host.run():
                    pass
        with host.run():
            # Another orchestrator shares the host; a generator or a standalone
            # analyzer (the exclusive supervisor path) cannot start.
            with self._host(_policy()).run():
                pass
            with self.assertRaisesRegex(ResourceSupervisorError, "already active"):
                run_supervised([sys.executable, "-c", "print('generator')"], lock_root=self.root,
                               snapshotter=lambda: HostSnapshot(50.0, 0, False), rss_sampler=lambda _pid: MIB)
            with (self.root / HOST_LOCK_NAME).open("a+b") as generator, self.assertRaises(BlockingIOError):
                fcntl.flock(generator.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        # After the run, the exclusive path works again.
        result = run_supervised([sys.executable, "-c", "print('ok')"], lock_root=self.root,
                                snapshotter=lambda: HostSnapshot(50.0, 0, False), rss_sampler=lambda _pid: MIB)
        self.assertEqual(result.report["exclusion"], "host-exclusive-lock")

    def test_the_budget_lanes_and_worker_cap_are_enforced_across_orchestrators(self) -> None:
        uncapped = self._host(_policy(cap=None))
        with uncapped.run() as first, self._host(_policy(cap=None)).run() as second:
            gpu = first.admit(self._judge("gpu", 3 * GIB))
            with self.assertRaisesRegex(AdmissionTimeout, "lane-full"):
                second.admit(self._judge("gpu", 3 * GIB))
            cpu = [second.admit(self._judge("cpu", GIB)), first.admit(self._judge("cpu", GIB))]
            with self.assertRaisesRegex(AdmissionTimeout, "lane-full"):
                first.admit(self._judge("cpu", GIB))
            status = uncapped.status()
            self.assertEqual(status["reservedBytes"], 3 * GIB + 2 * GIB + 2 * (GIB // 2))
            gpu.release()
            again = second.admit(self._judge("gpu", 3 * GIB))
            self.assertEqual(again.report()["workersAtAdmission"], 2)
            for ticket in cpu + [again]:
                ticket.release()
            with self.assertRaisesRegex(AdmissionRefused, "ceiling-exceeds-budget"):
                first.admit(self._judge("cpu", 10 * GIB))
        capped = self._host(_policy(cap=1))
        with capped.run() as run:
            ticket = run.admit(self._judge("gpu", GIB))
            self.assertEqual(ticket.report()["workerCap"], 1)
            with self.assertRaisesRegex(AdmissionTimeout, "worker-cap"):
                run.admit(self._judge("cpu", GIB))
            ticket.release()
            run.admit(self._judge("cpu", GIB)).release()
        self.assertEqual(capped.status()["tickets"], [])

    def test_waiting_admission_proceeds_when_a_worker_releases(self) -> None:
        host = HostAdmission(self.root, _policy(cap=None), poll_seconds=0.01, wait_seconds=5.0)
        with host.run() as run:
            held = run.admit(self._judge("gpu", GIB))
            admitted = []
            waiter = threading.Thread(target=lambda: admitted.append(run.admit(self._judge("gpu", GIB))))
            waiter.start()
            threading.Timer(0.1, held.release).start()
            waiter.join(timeout=5)
            self.assertEqual(len(admitted), 1)
            self.assertGreater(admitted[0].wait_seconds, 0.0)
            admitted[0].release()

    def test_dead_owners_are_purged_but_a_live_child_keeps_its_budget(self) -> None:
        alive = {1001: False, 1002: False, 1003: True}
        host = self._host(_policy(budget=4 * GIB, cap=None),
                          alive=lambda pid: alive.get(pid, pid is not None and pid > 0 and pid not in alive))
        self.root.mkdir(exist_ok=True)
        ledger = {"schema": admission_module.LEDGER_SCHEMA, "tickets": [
            {"ticketID": "dead", "judge": "asr.fixture@1", "lane": "gpu", "ceilingBytes": 3 * GIB,
             "ownerPID": 1001, "childPID": None},
            {"ticketID": "orphan", "judge": "asr.fixture@1", "lane": "cpu", "ceilingBytes": 2 * GIB,
             "ownerPID": 1002, "childPID": 1003},
        ]}
        (self.root / admission_module.LEDGER_NAME).write_text(json.dumps(ledger), encoding="utf-8")
        with host.run() as run:
            # The dead gpu entry is gone; the orphaned child's 2 GiB still count.
            status = host.status()
            self.assertEqual([ticket["lane"] for ticket in status["tickets"]], ["cpu", "orchestrator"])
            with self.assertRaisesRegex(AdmissionTimeout, "budget-exhausted"):
                run.admit(self._judge("gpu", 2 * GIB))
            ticket = run.admit(self._judge("gpu", GIB))
            ticket.bind_child(4242)
            recorded = {entry["ticketID"]: entry for entry in host.ledger.snapshot()}
            self.assertEqual(recorded[ticket.ticket_id]["childPID"], 4242)
            ticket.release()

    def test_a_corrupt_ledger_fails_closed(self) -> None:
        self.root.mkdir(exist_ok=True)
        (self.root / admission_module.LEDGER_NAME).write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(admission_module.AdmissionError, "unreadable"):
            with self._host(_policy()).run():
                pass


class LedgerIdentityTests(unittest.TestCase):
    """PID reuse, released tickets with live children and the Stage 1 slot."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.children: list[subprocess.Popen] = []

    def tearDown(self) -> None:
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
        self.temporary.cleanup()

    def _sleeper(self) -> subprocess.Popen:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.children.append(child)
        return child

    def test_a_reused_pid_never_pins_a_stale_entry(self) -> None:
        me = os.getpid()
        ledger = {"schema": admission_module.LEDGER_SCHEMA, "tickets": [
            # This PID is live, but it named another process when the entry was written.
            {"ticketID": "reused", "judge": "asr.fixture@1", "lane": "gpu", "ceilingBytes": 3 * GIB,
             "ownerPID": me, "ownerStarted": "mach-abs:1", "childPID": me, "childStarted": "proc-ticks:1"},
            {"ticketID": "mine", "judge": "asr.fixture@1", "lane": "cpu", "ceilingBytes": GIB,
             "ownerPID": me, "ownerStarted": process_start_identity(me), "childPID": None, "childStarted": None},
        ]}
        (self.root / admission_module.LEDGER_NAME).write_text(json.dumps(ledger), encoding="utf-8")
        host = HostAdmission(self.root, _policy(cap=None))
        self.assertEqual([entry["ticketID"] for entry in host.ledger.snapshot()], ["mine"])

    def test_a_released_ticket_keeps_its_budget_while_its_child_lives(self) -> None:
        host = HostAdmission(self.root, _policy(cap=None))
        with host.run() as run:
            ticket = run.admit(JudgeAdmission("asr.fixture@1", "gpu", 3 * GIB, "provisional", 2, "fixture"))
            child = self._sleeper()
            ticket.bind_child(child.pid)
            ticket.release()
            entries = {entry["ticketID"]: entry for entry in host.ledger.snapshot()}
            # The child outlived its supervision: its budget stays reserved, owner cleared.
            self.assertIsNone(entries[ticket.ticket_id]["ownerPID"])
            self.assertEqual(entries[ticket.ticket_id]["childStarted"], process_start_identity(child.pid))
            self.assertEqual(host.status()["reservedBytes"], 3 * GIB + GIB // 2)
            child.kill()
            child.wait(timeout=5)
            self.assertNotIn(ticket.ticket_id, {entry["ticketID"] for entry in host.ledger.snapshot()})

    def test_stage1_takes_a_slot_of_the_one_worker_cap(self) -> None:
        clock = FakeClock()
        first = HostAdmission(self.root, _policy(cap=1), clock=clock, sleep=clock.sleep,
                              poll_seconds=1.0, wait_seconds=3.0)
        second = HostAdmission(self.root, _policy(cap=1), clock=clock, sleep=clock.sleep,
                               poll_seconds=1.0, wait_seconds=3.0)
        judge = JudgeAdmission("asr.fixture@1", "gpu", GIB, "provisional", 2, "fixture")
        with first.run() as one, second.run() as two:
            worker = one.admit(judge)
            # Another orchestrator's in-process L0 and Stage 1 wait for the one worker...
            with self.assertRaisesRegex(AdmissionTimeout, "worker-cap"):
                with two.stage1():
                    pass
            self.assertEqual(worker.report()["serialScope"], "workers-and-stage1")
            worker.release()
            with two.stage1() as slot:
                # ...and a worker waits for them, so its envelope is serial.
                self.assertEqual((slot.lane, slot.ceiling_bytes), ("dsp", 0))
                with self.assertRaisesRegex(AdmissionTimeout, "worker-cap"):
                    one.admit(judge)
            one.admit(judge).release()
        # Once the child-attributed rule binds, Stage 1 only fills dsp lane slots.
        uncapped = HostAdmission(self.root, _policy(cap=None))
        with uncapped.run() as run, run.stage1(), run.stage1():
            run.admit(judge).release()


class SupervisedAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_an_admitted_child_runs_under_the_shared_lock_within_its_ceiling(self) -> None:
        host = HostAdmission(self.root, _policy())
        with host.run() as run:
            ticket = run.admit(JudgeAdmission("asr.fixture@1", "gpu", GIB, "provisional", 2, "fixture"))
            with self.assertRaisesRegex(ResourceSupervisorError, "exceed its admitted ceiling"):
                run_supervised([sys.executable, "-c", "print(1)"], lock_root=self.root, admission=ticket,
                               maximum_rss_bytes=2 * GIB, maximum_physical_footprint_bytes=GIB)
            result = run_supervised(
                [sys.executable, "-c", "import time; print('admitted'); time.sleep(.1)"],
                lock_root=self.root, admission=ticket, maximum_rss_bytes=GIB, maximum_physical_footprint_bytes=GIB,
                snapshotter=lambda: HostSnapshot(50.0, 0, False), rss_sampler=lambda _pid: 12 * MIB,
            )
            self.assertTrue(result.report["qualified"])
            self.assertEqual(result.report["exclusion"], "budgeted-admission")
            self.assertEqual(result.report["admission"]["judge"], "asr.fixture@1")
            self.assertEqual(result.report["bindingRecoveryRule"], WHOLE_HOST_RECOVERY_RULE)
            children = {entry["ticketID"]: entry.get("childPID") for entry in host.ledger.snapshot()}
            self.assertIsInstance(children[ticket.ticket_id], int)
            ticket.release()
            with self.assertRaisesRegex(Exception, "released"):
                run_supervised([sys.executable, "-c", "print(1)"], lock_root=self.root, admission=ticket,
                               maximum_rss_bytes=GIB, maximum_physical_footprint_bytes=GIB)


    def test_a_failed_ledger_write_never_leaves_the_worker_running(self) -> None:
        """Binding the child happens inside the supervision's try: a full disk still reaps it."""
        host = HostAdmission(self.root, _policy())
        judge = JudgeAdmission("asr.fixture@1", "gpu", GIB, "provisional", 2, "fixture")
        children: list[int] = []
        released: list[bool] = []
        release = admission_module.AdmissionTicket.release

        def full_disk(ticket, pid):
            children.append(pid)
            raise OSError(errno.ENOSPC, "No space left on device")

        def release_after_exit(ticket):
            if ticket.lane == "gpu":
                released.append(not _running(children[-1]))
            release(ticket)

        try:
            with mock.patch.object(admission_module.AdmissionTicket, "bind_child", full_disk), \
                    mock.patch.object(admission_module.AdmissionTicket, "release", release_after_exit), \
                    host.run() as run:
                started = time.monotonic()
                ticket = run.admit(judge)
                with self.assertRaises(OSError):
                    run_supervised([sys.executable, "-c", "import time; time.sleep(30)"], lock_root=self.root,
                                   admission=ticket, maximum_rss_bytes=GIB, maximum_physical_footprint_bytes=GIB,
                                   snapshotter=lambda: HostSnapshot(50.0, 0, False), rss_sampler=lambda _pid: MIB)
                self.assertLess(time.monotonic() - started, 10.0)
                ticket.release()
                self.assertFalse(_running(children[0]), "the worker outlived its supervision")
                # Through the persistent-worker runner: the ticket is released only after the child is gone.
                spec = WorkerSpec(judge_id="asr.fixture@1", engine="fixture",
                                  command=(sys.executable, "-c", "import time; time.sleep(30)"), threads=2,
                                  lane="gpu", ceiling_bytes=GIB)
                with self.assertRaises(OSError):
                    run_persistent_worker(spec, [{"id": "row-0", "pcmPath": "unused"}], workdir=self.root / "work",
                                          lock_root=self.root, run_admission=run, judge_admission=judge,
                                          supervisor=lambda command, **kwargs: run_supervised(
                                              command, snapshotter=lambda: HostSnapshot(50.0, 0, False),
                                              rss_sampler=lambda _pid: MIB, **kwargs))
                self.assertEqual(released, [True, True])
            self.assertEqual(host.status()["tickets"], [])
        finally:
            for pid in children:
                if _running(pid):
                    os.killpg(pid, signal.SIGKILL)
                    os.waitpid(pid, 0)


class RecoverySwitchTests(unittest.TestCase):
    """The child-attributed rule is the binding candidate behind the registry switch."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _run(self, rule: str, before: HostSnapshot, after: HostSnapshot, *, child: int) -> dict:
        snapshots = iter((before, after))
        return run_supervised(
            [sys.executable, "-c", "import time; time.sleep(.1)"],
            lock_root=self.root, snapshotter=lambda: next(snapshots),
            process_sampler=lambda _pid: ProcessSample(64 * MIB, 128 * MIB, child),
            measure_physical_footprint=True, maximum_physical_footprint_bytes=8 * GIB,
            recovery_timeout_seconds=0, recovery_rule=rule,
        ).report

    def test_the_default_keeps_the_whole_host_rule_binding(self) -> None:
        report = self._run(WHOLE_HOST_RECOVERY_RULE, HostSnapshot(60.0, 0, False, 1, 16 * GIB),
                           HostSnapshot(40.0, 0, False, 1, 16 * GIB), child=GIB)
        self.assertFalse(report["qualified"])
        self.assertIn("post-exit-memory-recovery-unqualified", report["qualificationFailures"])
        self.assertFalse(report["candidateRecoveryRule"]["binding"])
        self.assertEqual(report["wholeHostRecoveryFailures"], ["post-exit-memory-recovery-unqualified"])

    def test_the_switched_rule_frees_a_concurrent_allocator_and_still_fails_the_child(self) -> None:
        concurrent = self._run(CANDIDATE_RECOVERY_RULE, HostSnapshot(60.0, 0, False, 1, 16 * GIB),
                               HostSnapshot(40.0, 0, False, 1, 16 * GIB), child=GIB)
        self.assertTrue(concurrent["qualified"], concurrent["qualificationFailures"])
        self.assertTrue(concurrent["candidateRecoveryRule"]["binding"])
        self.assertEqual(concurrent["bindingRecoveryRule"], CANDIDATE_RECOVERY_RULE)
        # The whole-host outcome is still recorded for the recovery report.
        self.assertEqual(concurrent["wholeHostRecoveryFailures"], ["post-exit-memory-recovery-unqualified"])
        child = self._run(CANDIDATE_RECOVERY_RULE, HostSnapshot(60.0, 0, False, 1, 16 * GIB),
                          HostSnapshot(40.0, 0, False, 1, 16 * GIB), child=4 * GIB)
        self.assertFalse(child["qualified"])
        self.assertEqual(child["qualificationFailures"], ["post-exit-recovery-attributed-to-child"])
        pressured = self._run(CANDIDATE_RECOVERY_RULE, HostSnapshot(60.0, 0, False, 1, 16 * GIB),
                              HostSnapshot(58.0, 0, False, 2, 16 * GIB), child=GIB)
        self.assertEqual(pressured["qualificationFailures"], ["kernel-pressure-not-normal"])
        with self.assertRaisesRegex(ResourceSupervisorError, "unknown recovery rule"):
            self._run("lenient", HostSnapshot(60.0, 0, False), HostSnapshot(60.0, 0, False), child=GIB)
        # The report reads the whole-host outcome whichever rule was binding.
        summary = recovery_report([concurrent, child])
        self.assertEqual(summary["bindingRecoveryFailures"], 2)
        self.assertEqual(summary["candidateWouldQualifyBindingFailure"], 1)
        # Both ran under the exclusive lock, so both count as serial: a serial
        # drop the candidate blames on another allocator is the misattribution
        # the promotion evidence must rule out.
        self.assertEqual(summary["serialEnvelopes"], 2)
        self.assertEqual(summary["serialCandidateWouldQualifyBindingFailure"], 1)
        self.assertEqual(summary["unattributed"], 0)


if __name__ == "__main__":
    unittest.main()
