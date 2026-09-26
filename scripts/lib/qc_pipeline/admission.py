"""Budgeted admission after the generator exits (audit section 3.4, decision 9a).

The host-wide single-analyzer flock is replaced, for the orchestrator's
workers, by a semaphore over memory:

- **One host-wide root.** The host lock (`delivery-analysis-supervisor.lock`)
  and the ledger live under `delivery_resource_supervisor.host_analysis_lock_root()`
  (`hostAnalysisLock` in `config/build-output-policy.json`, under
  `~/Library/Caches/Vocello/`), which no checkout, worktree or analysis cache
  root changes: every generator, standalone analyzer and orchestrator on the
  host contends on the same lock and spends the same budget.
- **Generator exclusion is unchanged.** The generator and every standalone
  analyzer take the host lock exclusively. An orchestrator run takes it
  *shared* for its whole duration and every worker it launches inherits that
  descriptor, so no evaluator runs beside a resident generator, no generator
  starts beside an evaluator, and a run on a busy host refuses to start
  (`HostBusy`).
- **Admission is budgeted.** A worker is admitted only while the registry
  ceilings of every admitted worker plus the orchestrators' own reservations
  stay within `admission.budgetBytes` of `config/audio-qc-judges.json`
  (about 10 GiB on the M6, est.), with at most `lanes.gpu` (1) MLX worker and
  `lanes.cpu` (2) CPU workers at once. A judge's ceiling is its measured
  canonical-host peak x 1.2 once measured (AQ-06), else its provisional
  ceiling; a judge with neither, or a ceiling the budget can never hold, is
  refused outright. The supervisor then enforces that same ceiling live on
  the child's whole process group (the worker and every command it runs), so
  the budget is a bound, not an estimate.
- **The recovery rule sets the host-wide worker cap.** While the whole-host
  post-exit recovery rule binds, one worker's drop in host free memory cannot
  be told apart from another's allocation, so at most
  `recoveryRule.workerCapWhileWholeHostBinding` (1) supervised worker runs at
  a time, and an orchestrator's in-process L0 and Stage 1 DSP take a slot of
  that cap too (`RunAdmission.stage1`): an admitted worker's envelope is then
  serial (`SERIAL_SCOPE`). Once the child-attributed rule is binding (the
  registry switch, flipped only on the committed M6 evidence it names), the
  lane limits alone apply.
- **The registry gate runs at load.** `AdmissionPolicy.from_registry` runs the
  registry's admission validator, so a local flip of the switch without its
  committed evidence is refused rather than taking effect.

The ledger (`audio-qc-admission.json`, guarded by `audio-qc-admission.lock`)
records each ticket's owner and child by PID and process start time, so a
reused PID never pins a stale entry. An entry whose owner and child have both
exited is purged; a live child keeps its budget reserved even when its
orchestrator died, and a ticket released while its child still lives keeps its
entry until the child is gone.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Callable, Iterator, Mapping
import uuid

from delivery_resource_supervisor import (
    HOST_LOCK_NAME as SUPERVISOR_HOST_LOCK_NAME,
    SERIAL_ADMISSION_SCOPE,
    host_analysis_lock_root,
    process_start_identity,
)

LEDGER_SCHEMA = "vocello.audioqc.admission-ledger/1"
LEDGER_NAME = "audio-qc-admission.json"
LEDGER_LOCK_NAME = "audio-qc-admission.lock"
# The supervisor's host lock (`delivery_resource_supervisor.HOST_LOCK_NAME`).
HOST_LOCK_NAME = SUPERVISOR_HOST_LOCK_NAME
POLICY = "budgeted-admission-after-generator-exit"
WORKER_LANES = ("gpu", "cpu", "dsp")
ORCHESTRATOR_LANE = "orchestrator"
WHOLE_HOST_RECOVERY_RULE = "whole-host-free-percent-v1"
CANDIDATE_RECOVERY_RULE = "attributed-post-exit-recovery-v2"
# The orchestrator's in-process L0 canonicalization and Stage 1 DSP: a slot in
# the dsp lane (and under the worker cap), its memory inside the reservation.
STAGE1_SLOT = "stage1.in-process"
SERIAL_SCOPE = SERIAL_ADMISSION_SCOPE
DEFAULT_POLL_SECONDS = 0.25
DEFAULT_WAIT_SECONDS = 3600.0
BLOCKED_STATUSES = frozenset({"retired", "quarantined"})


class AdmissionError(RuntimeError):
    """Admission is impossible, refused or failed closed."""


class HostBusy(AdmissionError):
    """A generator or an exclusive analyzer holds the host lock."""


class AdmissionRefused(AdmissionError):
    """The request can never be admitted under this policy."""


class AdmissionTimeout(AdmissionError):
    """The request was admissible in principle but never fit before the deadline."""


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


@dataclass(frozen=True)
class AdmissionPolicy:
    budget_bytes: int
    lane_limits: Mapping[str, int]
    orchestrator_reservation_bytes: int
    recovery_rule: str
    # Host-wide supervised-worker cap; None when only the lane limits apply.
    worker_cap: int | None

    @classmethod
    def from_registry(cls, registry: Mapping[str, Any], *, root: Path | None = None) -> "AdmissionPolicy":
        """The policy a registry declares, after its admission validator passes.

        A registry whose admission block fails `audio_qc_judges.admission_errors`
        is refused here, so a switch flipped without its committed evidence
        never takes effect.
        """
        from audio_qc_judges import REPO as REGISTRY_ROOT, admission_errors

        errors = admission_errors(dict(registry), root=root or REGISTRY_ROOT)
        if errors:
            raise AdmissionError("the judge registry's admission block is invalid: " + "; ".join(errors[:3]))
        admission = registry.get("admission")
        if not isinstance(admission, Mapping) or admission.get("policy") != POLICY:
            raise AdmissionError(f"the judge registry declares no {POLICY} policy")
        budget = admission.get("budgetBytes")
        reservation = admission.get("orchestratorReservationBytes")
        lanes = admission.get("lanes")
        if not _positive_int(budget) or not _positive_int(reservation) or reservation >= budget:
            raise AdmissionError("the admission budget and orchestrator reservation must be positive bytes")
        if not isinstance(lanes, Mapping) or set(lanes) != set(WORKER_LANES):
            raise AdmissionError("admission lanes must be gpu, cpu and dsp")
        limits: dict[str, int] = {}
        for lane in WORKER_LANES:
            limit = lanes[lane].get("maximumConcurrent") if isinstance(lanes[lane], Mapping) else None
            if not _positive_int(limit):
                raise AdmissionError(f"admission lane {lane} needs a positive maximumConcurrent")
            limits[lane] = limit
        recovery = admission.get("recoveryRule")
        if not isinstance(recovery, Mapping) or not isinstance(recovery.get("candidateBinding"), bool):
            raise AdmissionError("admission must record the recovery-rule switch")
        binding = recovery["candidateBinding"]
        cap = recovery.get("workerCapWhileWholeHostBinding")
        if not binding and not _positive_int(cap):
            raise AdmissionError("the whole-host recovery rule needs a positive host-wide worker cap")
        return cls(
            budget_bytes=budget, lane_limits=limits, orchestrator_reservation_bytes=reservation,
            recovery_rule=CANDIDATE_RECOVERY_RULE if binding else WHOLE_HOST_RECOVERY_RULE,
            worker_cap=None if binding else cap,
        )

    def report(self) -> dict[str, Any]:
        return {
            "policy": POLICY,
            "budgetBytes": self.budget_bytes,
            "laneLimits": dict(self.lane_limits),
            "orchestratorReservationBytes": self.orchestrator_reservation_bytes,
            "recoveryRule": self.recovery_rule,
            "workerCap": self.worker_cap,
            "serialScope": SERIAL_SCOPE,
        }


@dataclass(frozen=True)
class JudgeAdmission:
    judge_id: str
    lane: str
    ceiling_bytes: int
    ceiling_basis: str
    threads: int
    engine: str

    def report(self) -> dict[str, Any]:
        return {
            "judge": self.judge_id, "lane": self.lane, "ceilingBytes": self.ceiling_bytes,
            "ceilingBasis": self.ceiling_basis, "threads": self.threads, "engine": self.engine,
        }


def judge_ceiling(judge: Mapping[str, Any]) -> tuple[int, str]:
    """A judge's admission ceiling: measured peak x 1.2, else the provisional ceiling."""
    resources = judge.get("resources") if isinstance(judge.get("resources"), Mapping) else {}
    measured = resources.get("canonicalHostPeakBytes")
    if _positive_int(measured):
        # Exact integer ceil(peak x 1.2), the registry validator's arithmetic.
        return -(-measured * 12 // 10), "measured-canonical-host-peak-x1.2"
    provisional = resources.get("provisionalCeilingBytes")
    if _positive_int(provisional):
        return provisional, "provisional"
    raise AdmissionRefused("the judge has neither a measured nor a provisional memory ceiling")


def judge_admission(registry: Mapping[str, Any], judge_id: str) -> JudgeAdmission:
    """What one orchestrated worker judge is admitted as, from the registry."""
    judge = (registry.get("judges") or {}).get(judge_id)
    if not isinstance(judge, Mapping):
        raise AdmissionRefused(f"audio QC judge {judge_id} is not registered")
    if judge.get("status") in BLOCKED_STATUSES:
        raise AdmissionRefused(f"audio QC judge {judge_id} is {judge.get('status')}; it may not run")
    execution = judge.get("execution")
    if (not isinstance(execution, Mapping) or execution.get("orchestrated") is not True
            or execution.get("lane") not in WORKER_LANES):
        raise AdmissionRefused(f"audio QC judge {judge_id} is not an orchestrated worker judge")
    threads = execution.get("threads")
    if not _positive_int(threads):
        raise AdmissionRefused(f"audio QC judge {judge_id} declares no thread count")
    try:
        ceiling, basis = judge_ceiling(judge)
    except AdmissionRefused as error:
        raise AdmissionRefused(f"audio QC judge {judge_id}: {error}") from None
    return JudgeAdmission(judge_id, str(execution["lane"]), ceiling, basis, threads, str(execution.get("engine")))


def admission_decision(policy: AdmissionPolicy, entries: list[Mapping[str, Any]], lane: str,
                       ceiling_bytes: int, *, slot_only: bool = False) -> tuple[str, str | None]:
    """`admit`, `wait` or `refuse` for one request against the live ledger (pure).

    A `slot_only` request (the orchestrator's in-process Stage 1) reserves no
    bytes beyond its orchestrator's reservation but takes a lane slot and a
    slot of the host-wide worker cap.
    """
    if lane != ORCHESTRATOR_LANE and lane not in policy.lane_limits:
        return "refuse", "unknown-lane"
    if slot_only:
        if lane == ORCHESTRATOR_LANE or ceiling_bytes != 0:
            return "refuse", "ceiling-invalid"
    else:
        if not _positive_int(ceiling_bytes):
            return "refuse", "ceiling-invalid"
        floor = 0 if lane == ORCHESTRATOR_LANE else policy.orchestrator_reservation_bytes
        if ceiling_bytes + floor > policy.budget_bytes:
            return "refuse", "ceiling-exceeds-budget"
        reserved = sum(int(entry.get("ceilingBytes", 0)) for entry in entries)
        if reserved + ceiling_bytes > policy.budget_bytes:
            return "wait", "budget-exhausted"
    if lane == ORCHESTRATOR_LANE:
        return "admit", None
    if sum(1 for entry in entries if entry.get("lane") == lane) >= policy.lane_limits[lane]:
        return "wait", "lane-full"
    workers = sum(1 for entry in entries if entry.get("lane") in WORKER_LANES)
    if policy.worker_cap is not None and workers >= policy.worker_cap:
        return "wait", "worker-cap"
    return "admit", None


def pid_alive(pid: Any) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class _Ledger:
    def __init__(self, root: Path, alive: Callable[[Any], bool],
                 started: Callable[[int], str | None]) -> None:
        self.path = root / LEDGER_NAME
        self.lock_path = root / LEDGER_LOCK_NAME
        self.alive = alive
        self.started = started
        self.thread_lock = threading.Lock()

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AdmissionError(
                f"the admission ledger is unreadable ({type(error).__name__}); remove {LEDGER_NAME} "
                "only when no audio QC worker runs"
            ) from None
        entries = payload.get("tickets") if isinstance(payload, dict) and payload.get("schema") == LEDGER_SCHEMA else None
        if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
            raise AdmissionError("the admission ledger has an unknown schema")
        return entries

    def _write(self, entries: list[dict[str, Any]]) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{LEDGER_NAME}-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({"schema": LEDGER_SCHEMA, "tickets": entries}, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)

    def instance_alive(self, pid: Any, started: Any) -> bool:
        """The recorded process instance still runs: its PID is live and names the same process."""
        if not self.alive(pid):
            return False
        if not isinstance(started, str):
            return True  # an entry from before start times were recorded
        try:
            current = self.started(pid)
        except ProcessLookupError:
            return False
        except PermissionError:
            return False  # the PID now names another user's process
        return current is None or current == started

    def _live(self, entry: Mapping[str, Any]) -> bool:
        return bool(self.instance_alive(entry.get("ownerPID"), entry.get("ownerStarted"))
                    or self.instance_alive(entry.get("childPID"), entry.get("childStarted")))

    @contextlib.contextmanager
    def locked(self) -> Iterator[list[dict[str, Any]]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.thread_lock, self.lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                entries = [entry for entry in self._read() if self._live(entry)]
                yield entries
                self._write(entries)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def snapshot(self) -> list[dict[str, Any]]:
        with self.locked() as entries:
            return [dict(entry) for entry in entries]


def _start_identity(started: Callable[[int], str | None], pid: int) -> str | None:
    try:
        return started(pid)
    except (ProcessLookupError, PermissionError):
        return None


class AdmissionTicket:
    """One admitted worker (or an orchestrator's own reservation, or a Stage 1 slot)."""

    def __init__(self, host: "HostAdmission", entry: dict[str, Any], *, host_fd: int,
                 wait_seconds: float, reserved_bytes: int, workers: int) -> None:
        self._host = host
        self._entry = entry
        self._host_fd = host_fd
        self._released = False
        self.ticket_id: str = entry["ticketID"]
        self.judge_id: str = entry["judge"]
        self.lane: str = entry["lane"]
        self.ceiling_bytes: int = entry["ceilingBytes"]
        self.session_id: str | None = entry.get("sessionID")
        self.child_pid: int | None = None
        self.wait_seconds = wait_seconds
        self.reserved_bytes_at_admission = reserved_bytes
        self.workers_at_admission = workers

    def host_lock_fd(self) -> int:
        if self._released:
            raise AdmissionError("the admission ticket was released")
        return self._host_fd

    def bind_child(self, pid: int) -> None:
        """Record the worker's PID and start so its budget outlives a dead orchestrator."""
        self.child_pid = pid
        started = _start_identity(self._host.ledger.started, pid)
        with self._host.ledger.locked() as entries:
            for entry in entries:
                if entry.get("ticketID") == self.ticket_id:
                    entry["childPID"] = pid
                    entry["childStarted"] = started

    def release(self) -> None:
        """Return the budget, but never while the bound child still runs.

        A child that survived its supervision (an unconfirmed exit) keeps its
        entry, with the owner cleared, until the ledger sees it gone.
        """
        if self._released:
            return
        self._released = True
        ledger = self._host.ledger
        with ledger.locked() as entries:
            kept = []
            for entry in entries:
                if entry.get("ticketID") != self.ticket_id:
                    kept.append(entry)
                elif ledger.instance_alive(entry.get("childPID"), entry.get("childStarted")):
                    entry["ownerPID"] = None
                    entry["ownerStarted"] = None
                    kept.append(entry)
            entries[:] = kept

    def report(self) -> dict[str, Any]:
        policy = self._host.policy
        return {
            "ticketID": self.ticket_id,
            "judge": self.judge_id,
            "lane": self.lane,
            "ceilingBytes": self.ceiling_bytes,
            "budgetBytes": policy.budget_bytes,
            "reservedBytesAtAdmission": self.reserved_bytes_at_admission,
            "workersAtAdmission": self.workers_at_admission,
            "workerCap": policy.worker_cap,
            "serialScope": SERIAL_SCOPE,
            "laneLimit": policy.lane_limits.get(self.lane),
            "recoveryRule": policy.recovery_rule,
            "sessionID": self.session_id,
            "waitSeconds": round(self.wait_seconds, 3),
        }

    def __enter__(self) -> "AdmissionTicket":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.release()


class RunAdmission:
    """One orchestrator run: the shared host lock, its session and its own reservation."""

    def __init__(self, host: "HostAdmission", host_fd: int, reservation: AdmissionTicket,
                 session_id: str) -> None:
        self.host = host
        self.host_fd = host_fd
        self.reservation = reservation
        self.session_id = session_id

    @property
    def policy(self) -> AdmissionPolicy:
        return self.host.policy

    def admit(self, judge: JudgeAdmission) -> AdmissionTicket:
        return self.host._admit(judge.lane, judge.judge_id, judge.ceiling_bytes, self.host_fd,
                                session_id=self.session_id)

    @contextlib.contextmanager
    def stage1(self) -> Iterator[AdmissionTicket]:
        """Hold a dsp slot (under the host-wide worker cap) for in-process L0 and Stage 1."""
        ticket = self.host._admit("dsp", STAGE1_SLOT, 0, self.host_fd, session_id=self.session_id,
                                  slot_only=True)
        try:
            yield ticket
        finally:
            ticket.release()


class HostAdmission:
    def __init__(self, lock_root: Path | None, policy: AdmissionPolicy, *,
                 poll_seconds: float = DEFAULT_POLL_SECONDS, wait_seconds: float = DEFAULT_WAIT_SECONDS,
                 alive: Callable[[Any], bool] = pid_alive,
                 started: Callable[[int], str | None] = process_start_identity,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        # The host-wide root unless a test names its own.
        self.lock_root = lock_root if lock_root is not None else host_analysis_lock_root()
        self.policy = policy
        self.poll_seconds = poll_seconds
        self.wait_seconds = wait_seconds
        self.clock = clock
        self.sleep = sleep
        self.ledger = _Ledger(self.lock_root, alive, started)

    def _admit(self, lane: str, judge_id: str, ceiling_bytes: int, host_fd: int, *,
               session_id: str | None = None, slot_only: bool = False) -> AdmissionTicket:
        started = self.clock()
        deadline = started + self.wait_seconds
        owner = os.getpid()
        owner_started = _start_identity(self.ledger.started, owner)
        while True:
            with self.ledger.locked() as entries:
                verdict, reason = admission_decision(self.policy, entries, lane, ceiling_bytes,
                                                     slot_only=slot_only)
                if verdict == "admit":
                    reserved = sum(int(entry.get("ceilingBytes", 0)) for entry in entries) + ceiling_bytes
                    workers = sum(1 for entry in entries if entry.get("lane") in WORKER_LANES)
                    entry = {
                        "ticketID": uuid.uuid4().hex, "judge": judge_id, "lane": lane,
                        "ceilingBytes": ceiling_bytes, "slotOnly": slot_only,
                        "ownerPID": owner, "ownerStarted": owner_started,
                        "childPID": None, "childStarted": None, "sessionID": session_id,
                        "admittedAtEpochSeconds": round(time.time(), 3),
                    }
                    entries.append(entry)
                    return AdmissionTicket(self, dict(entry), host_fd=host_fd,
                                           wait_seconds=self.clock() - started,
                                           reserved_bytes=reserved, workers=workers)
                if verdict == "refuse":
                    raise AdmissionRefused(f"{judge_id} ({lane}, {ceiling_bytes} bytes) is never admissible: {reason}")
            if self.clock() >= deadline:
                raise AdmissionTimeout(f"{judge_id} was not admitted within {self.wait_seconds:g} s: {reason}")
            self.sleep(self.poll_seconds)

    @contextlib.contextmanager
    def run(self) -> Iterator[RunAdmission]:
        """Hold the host lock shared for one orchestrator run; refuse a busy host."""
        self.lock_root.mkdir(parents=True, exist_ok=True)
        with (self.lock_root / HOST_LOCK_NAME).open("a+b") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                raise HostBusy(
                    "a generator or an exclusive analyzer holds the host lock; "
                    "the orchestrator refuses to start on a busy host"
                ) from None
            session_id = uuid.uuid4().hex
            reservation = self._admit(
                ORCHESTRATOR_LANE, "orchestrator", self.policy.orchestrator_reservation_bytes, handle.fileno(),
                session_id=session_id,
            )
            try:
                yield RunAdmission(self, handle.fileno(), reservation, session_id)
            finally:
                reservation.release()

    def status(self) -> dict[str, Any]:
        entries = self.ledger.snapshot()
        return {
            **self.policy.report(),
            "reservedBytes": sum(int(entry.get("ceilingBytes", 0)) for entry in entries),
            "tickets": [
                {key: entry.get(key) for key in ("judge", "lane", "ceilingBytes")} for entry in entries
            ],
        }
