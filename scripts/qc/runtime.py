"""Runtimes and the runner host: pinned venvs, one model subprocess at a time.

`setup_runtime` builds `build/cache/qc/runtimes/<name>` (mlx, onnx, torch) as a
venv of the pinned interpreter and installs `config/qc/runtimes/<name>.txt`.
The llama.cpp release is unpacked into `runtimes/llamacpp`; its runner uses the
onnx venv's python.

`run_runner` sends the takes a model has not scored yet to its runner:

    <runtime python> -m qc.runners.<name> --job <job.json>

with `PYTHONPATH=scripts` and the repository root as the working directory. It
samples the peak RSS of the runner's process tree every 0.5 s, enforces a
timeout, and returns every take's result from the content-addressed cache.
Only one `qc.py` run holds `build/cache/qc/run.lock` at a time.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator

from qc import store
from qc.models import (
    FetchError, code_extracted, file_status, model_files, pins_digest, runner_source, safe_extract_tar,
)
from qc.store import Layout

VENV_RUNTIMES = ("mlx", "onnx", "torch")
RUNTIMES = VENV_RUNTIMES + ("llamacpp",)
RECEIPT = "qc-runtime.json"
RECEIPT_SCHEMA = "vocello.qc.runtime/1"
# The standalone CPython the v1 harness pinned (cpython-3.14.4+20260414). Setup
# copies it under build/cache/qc/runtimes/python, so the v2 venvs never depend on
# the v1 cache that the cleanup removes.
LEGACY_INTERPRETER = "build/cache/delivery-analysis/external-models/audio-qc-python-3.14.4"
SAMPLE_SECONDS = 0.5

# name[extras]==version, an https direct reference, or a git URL pinned to a full commit.
REQUIREMENT_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?"
    r"(==[A-Za-z0-9.+!_-]+| @ https://\S+| @ git\+https://\S+@[0-9a-f]{40})(\s*;.*)?$"
)
ALLOWED_OPTIONS = ("--index-url", "--extra-index-url", "--find-links", "--only-binary", "--no-binary", "--pre")


class RuntimeSetupError(RuntimeError):
    """A runtime could not be built or does not match its pins."""


class RunnerError(RuntimeError):
    """A runner could not start."""


class LockBusy(RuntimeError):
    """Another qc.py run holds the run lock."""


# --- interpreter and requirements -------------------------------------------

def interpreter_root(layout: Layout) -> Path:
    return layout.runtimes / "python"


def find_base_python(layout: Layout, *, copy_legacy: bool = True) -> tuple[Path, str]:
    """The interpreter the venvs are built from, and its identity.

    In order: v2's own copy of the pinned standalone interpreter; the v1
    harness's pinned copy, copied into v2's root first; the current python3.
    """

    own = interpreter_root(layout)
    executable = own / "python/bin/python3"
    receipt = own / "receipt.json"
    if executable.is_file():
        identity = "unknown"
        if receipt.is_file():
            identity = store.read_json(receipt).get("id", "unknown")
        return executable, identity
    legacy = layout.root / LEGACY_INTERPRETER
    if copy_legacy and (legacy / "python/bin/python3").is_file():
        identity = "unknown"
        if (legacy / "receipt.json").is_file():
            identity = store.read_json(legacy / "receipt.json").get("id", "unknown")
        staging = own.with_name("python.staging")
        shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(legacy / "python", staging / "python", symlinks=True)
        store.write_json_atomic(staging / "receipt.json", {"id": identity, "copiedFrom": LEGACY_INTERPRETER})
        own.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, own)
        return executable, identity
    return Path(sys.executable), f"system-python-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def parse_requirements(text: str) -> list[str]:
    """The requirement lines of a runtime file; every package must be pinned."""

    lines = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            if not line.split("=", 1)[0].split(" ", 1)[0] in ALLOWED_OPTIONS:
                raise RuntimeSetupError(f"line {number}: option not allowed: {line}")
        elif not REQUIREMENT_RE.fullmatch(line):
            raise RuntimeSetupError(f"line {number}: not pinned with == or an https direct reference: {line}")
        lines.append(line)
    return lines


def pinned_versions(lines: list[str]) -> dict[str, str]:
    pins = {}
    for line in lines:
        if line.startswith("-") or "==" not in line:
            continue
        name, version = line.split(";", 1)[0].split("==", 1)
        name = re.sub(r"\[.*\]", "", name)
        pins[canonical_package(name)] = version.strip()
    return pins


def canonical_package(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower().strip()


def runtime_dir(layout: Layout, runtime: str) -> Path:
    return layout.runtimes / runtime


def runtime_python(layout: Layout, runtime: str) -> Path:
    """The python a runtime's runners use (llama.cpp runners use the onnx venv)."""

    if runtime == "llamacpp":
        runtime = "onnx"
    return runtime_dir(layout, runtime) / "bin/python3"


# --- setup and verify -------------------------------------------------------

Runner = Callable[..., subprocess.CompletedProcess]


def setup_runtime(layout: Layout, runtime: str, *, run: Runner = subprocess.run,
                  log: Callable[[str], None] = lambda message: print(message, file=sys.stderr)) -> dict[str, Any]:
    if runtime == "llamacpp":
        return setup_llamacpp(layout, log=log)
    if runtime not in VENV_RUNTIMES:
        raise RuntimeSetupError(f"unknown runtime: {runtime}")
    requirements = layout.runtime_requirements / f"{runtime}.txt"
    text = requirements.read_text(encoding="utf-8")
    lines = parse_requirements(text)
    if not lines:
        raise RuntimeSetupError(f"config/qc/runtimes/{runtime}.txt pins no package yet")
    base, identity = find_base_python(layout)
    venv = runtime_dir(layout, runtime)
    if not (venv / "bin/python3").is_file():
        log(f"qc runtimes: creating the {runtime} venv from {identity}")
        run([str(base), "-m", "venv", str(venv)], check=True)
    log(f"qc runtimes: installing {len(lines)} pinned requirements into {runtime}")
    run([str(venv / "bin/python3"), "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
         "-r", str(requirements)], check=True)
    receipt = {"schema": RECEIPT_SCHEMA, "runtime": runtime, "interpreter": identity,
               "requirementsSHA256": store.sha256_text(text), "createdAt": utc_now()}
    store.write_json_atomic(venv / RECEIPT, receipt)
    return receipt


def verify_runtime(layout: Layout, runtime: str, *, run: Runner = subprocess.run) -> list[str]:
    """Problems with a runtime, empty when it matches its pins."""

    if runtime == "llamacpp":
        return verify_llamacpp(layout)
    venv = runtime_dir(layout, runtime)
    python = venv / "bin/python3"
    if not python.is_file():
        return [f"{runtime}: no venv (run qc.py runtimes setup --runtime {runtime})"]
    requirements = layout.runtime_requirements / f"{runtime}.txt"
    text = requirements.read_text(encoding="utf-8")
    problems = []
    try:
        receipt = store.read_json(venv / RECEIPT)
    except (OSError, ValueError):
        return [f"{runtime}: no setup receipt (re-run setup)"]
    if receipt.get("requirementsSHA256") != store.sha256_text(text):
        problems.append(f"{runtime}: the requirements changed since setup (re-run setup)")
    listing = run([str(python), "-m", "pip", "list", "--format=json", "--disable-pip-version-check"],
                  check=False, capture_output=True, text=True)
    if listing.returncode != 0:
        return problems + [f"{runtime}: pip list failed"]
    installed = {canonical_package(item["name"]): item["version"] for item in json.loads(listing.stdout)}
    for name, version in sorted(pinned_versions(parse_requirements(text)).items()):
        if installed.get(name) != version:
            problems.append(f"{runtime}: {name} is {installed.get(name, 'missing')}, pinned {version}")
    return problems


def _llamacpp_artifacts(layout: Layout) -> list[tuple[dict[str, Any], str, dict[str, Any]]]:
    from qc.models import load_registry

    artifacts = []
    for model in load_registry(layout):
        if model["kind"] == "runtime" and model["runtime"] == "llamacpp":
            for path, pin in sorted(model["source"]["files"].items()):
                artifacts.append((model, path, pin))
    return artifacts


def _safe_member(name: str) -> bool:
    pure = PurePosixPath(name)
    return bool(name) and not pure.is_absolute() and ".." not in pure.parts


def setup_llamacpp(layout: Layout, *, log: Callable[[str], None]) -> dict[str, Any]:
    artifacts = _llamacpp_artifacts(layout)
    if not artifacts:
        raise RuntimeSetupError("the registry pins no llama.cpp release (kind runtime, runtime llamacpp)")
    target = runtime_dir(layout, "llamacpp")
    staging = target.with_name("llamacpp.staging")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    unpacked = {}
    for model, path, pin in artifacts:
        archive = layout.model_dir(model["id"]) / path
        if file_status(archive, pin) != "ok":
            raise RuntimeSetupError(f"{model['id']}/{path} is missing or unverified (run qc.py models fetch)")
        log(f"qc runtimes: unpacking {model['id']}/{path}")
        if path.endswith(".zip"):
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.infolist():
                    if not _safe_member(member.filename):
                        raise RuntimeSetupError(f"unsafe archive member: {member.filename}")
                    bundle.extract(member, staging)
                    mode = (member.external_attr >> 16) & 0o777
                    if mode and not member.is_dir():
                        os.chmod(staging / member.filename, mode)
        elif path.endswith((".tar.gz", ".tgz")):
            try:
                safe_extract_tar(archive, staging, allow_symlinks=True)
            except FetchError as error:
                raise RuntimeSetupError(str(error)) from None
        else:
            shutil.copy2(archive, staging / PurePosixPath(path).name)
        unpacked[f"{model['id']}/{path}"] = pin["sha256"]
    receipt = {"schema": RECEIPT_SCHEMA, "runtime": "llamacpp", "artifacts": unpacked, "createdAt": utc_now()}
    store.write_json_atomic(staging / RECEIPT, receipt)
    shutil.rmtree(target, ignore_errors=True)
    os.replace(staging, target)
    return receipt


def verify_llamacpp(layout: Layout) -> list[str]:
    target = runtime_dir(layout, "llamacpp")
    try:
        receipt = store.read_json(target / RECEIPT)
    except (OSError, ValueError):
        return ["llamacpp: not unpacked (run qc.py runtimes setup --runtime llamacpp)"]
    expected = {f"{model['id']}/{path}": pin["sha256"] for model, path, pin in _llamacpp_artifacts(layout)}
    problems = []
    if receipt.get("artifacts") != expected:
        problems.append("llamacpp: the pinned release changed since setup (re-run setup)")
    if not (runtime_python(layout, "llamacpp")).is_file():
        problems.append("llamacpp: its runner needs the onnx venv (run qc.py runtimes setup --runtime onnx)")
    return problems


# --- the run lock -----------------------------------------------------------

_HELD: dict[str, list[Any]] = {}


@contextmanager
def run_lock(layout: Layout) -> Iterator[None]:
    """Hold `build/cache/qc/run.lock` (re-entrant within this process); refuse when busy."""

    key = str(layout.run_lock)
    if key in _HELD:
        _HELD[key][1] += 1
        try:
            yield
        finally:
            _HELD[key][1] -= 1
        return
    layout.cache.mkdir(parents=True, exist_ok=True)
    handle = open(layout.run_lock, "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise LockBusy("another qc.py run holds build/cache/qc/run.lock") from None
    _HELD[key] = [handle, 1]
    try:
        yield
    finally:
        del _HELD[key]
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


# --- peak RSS ---------------------------------------------------------------

def tree_rss_bytes(root_pid: int) -> int:
    """Resident memory of a process and all its descendants, from `ps`."""

    try:
        listing = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,rss="], capture_output=True, text=True,
                                 check=False, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return 0
    children: dict[int, list[int]] = {}
    rss: dict[int, int] = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            continue
        pid, ppid, kilobytes = (int(part) for part in parts)
        rss[pid] = kilobytes
        children.setdefault(ppid, []).append(pid)
    total, stack, seen = 0, [root_pid], set()
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        total += rss.get(pid, 0)
        stack.extend(children.get(pid, []))
    return total * 1024


# --- the runner host ----------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def runner_identity(layout: Layout, model: dict[str, Any]) -> str:
    """`runnerSHA256`: the digest of the runner source, the model version and every pin.

    Any change to the runner file, the registry `version` or a pinned model,
    dependency or code file gives a new identity, so cached results of the old
    one are re-run.
    """

    source = runner_source(layout, model)
    if not source.is_file():
        raise RunnerError(f"{model['id']}: runner source is missing ({model['runner']})")
    payload = store.canonical_json({
        "pins": pins_digest(model),
        "runner": hashlib.sha256(source.read_bytes()).hexdigest(),
        "version": model["version"],
    })
    return store.sha256_text(payload)


@dataclass
class RunnerReport:
    model: str
    runner_sha: str
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    ran: int = 0
    cached: int = 0
    skipped: int = 0
    peak_rss_bytes: int = 0
    seconds: float = 0.0
    exit_code: int | None = None
    timed_out: bool = False

    @property
    def failed(self) -> list[str]:
        return sorted(token for token, result in self.results.items() if "error" in result)


def default_timeout(model: dict[str, Any], pending: int) -> float:
    if "timeoutSeconds" in model:
        return float(model["timeoutSeconds"])
    return 120.0 + 60.0 * pending


def _supported(model: dict[str, Any], take: dict[str, Any]) -> bool:
    languages = model.get("languages", "any")
    return languages == "any" or take.get("language") in languages


def _job_take(take: dict[str, Any], variant: str | None) -> dict[str, Any]:
    return {
        "token": take["token"], "audio": str(Path(take["audio"]).resolve()), "audioSHA256": take["audioSHA256"],
        "language": take.get("language"), "text": take.get("text"),
        "reference": str(Path(take["reference"]).resolve()) if take.get("reference") else None,
        "referenceSHA256": take.get("referenceSHA256"), "variantKey": variant,
    }


def _complete_digests(take: dict[str, Any]) -> dict[str, Any]:
    take = dict(take)
    if not take.get("audioSHA256"):
        take["audioSHA256"] = store.audio_sha256(take["audio"])
    if take.get("reference") and not take.get("referenceSHA256"):
        take["referenceSHA256"] = store.audio_sha256(take["reference"])
    return take


def run_runner(
    model: dict[str, Any],
    takes: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
    *,
    layout: Layout = Layout(),
    python: Path | str | None = None,
    timeout: float | None = None,
    echo: Callable[[str], None] | None = None,
) -> RunnerReport:
    """Score `takes` with one model, reusing cached results; one model at a time."""

    if model.get("kind") in ("runtime", "g2p"):
        raise RunnerError(f"{model['id']}: kind {model['kind']} has no audio runner")
    echo = echo or (lambda line: print(line, file=sys.stderr, flush=True))
    runner_sha = runner_identity(layout, model)
    report = RunnerReport(model=model["id"], runner_sha=runner_sha)
    retry_errors = bool((options or {}).get("retryErrors"))
    pending: list[tuple[dict[str, Any], str | None]] = []
    for take in takes:
        if not _supported(model, take):
            report.skipped += 1
            continue
        take = _complete_digests(take)
        variant = store.take_variant(model, take)
        cached = store.read_result(layout, model["id"], take["audioSHA256"], variant, runner_sha)
        if cached is not None and not (retry_errors and "error" in cached):
            report.results[take["token"]] = cached
            report.cached += 1
        else:
            pending.append((take, variant))
    if not pending:
        return report

    python = Path(python) if python else runtime_python(layout, model["runtime"])
    if not python.is_file():
        raise RunnerError(f"{model['id']}: runtime {model['runtime']} is not set up "
                          f"(run qc.py runtimes setup --runtime {model['runtime']})")
    model_dir = layout.model_dir(model["id"])
    for item in model_files(layout, model):
        if not item.destination.is_file() or item.destination.stat().st_size != item.pin["bytes"]:
            raise RunnerError(f"{model['id']}: model file {item.label} is missing "
                              f"(run qc.py models fetch --model {model['id']})")
    if not code_extracted(layout, model):
        raise RunnerError(f"{model['id']}: its code is not extracted (run qc.py models fetch --model {model['id']})")

    job_options = dict(model.get("options", {}))
    job_options.update({key: value for key, value in (options or {}).items() if key != "retryErrors"})
    if model["runtime"] == "llamacpp":
        job_options.setdefault("llamacppDir", str(runtime_dir(layout, "llamacpp").resolve()))
    output_dir = layout.results_dir(model["id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    job = {
        "model": model["id"], "modelDir": str(model_dir.resolve()), "outputDir": str(output_dir.resolve()),
        "runnerSHA256": runner_sha, "options": job_options,
        "takes": [_job_take(take, variant) for take, variant in pending],
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    job_path = layout.jobs / f"{model['id']}-{stamp}-{os.getpid()}.json"
    log_path = job_path.with_suffix(".log")
    store.write_json_atomic(job_path, job)
    limit = timeout if timeout is not None else default_timeout(model, len(pending))

    with run_lock(layout):
        environment = dict(os.environ)
        environment.update({"PYTHONPATH": str(layout.scripts.resolve()), "PYTHONUNBUFFERED": "1",
                            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        environment.pop("VIRTUAL_ENV", None)
        started = time.monotonic()
        echo(f"qc run: {model['id']}: {len(pending)} takes to score, {report.cached} cached")
        with log_path.open("w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                [str(python), "-m", model["runner"], "--job", str(job_path.resolve())],
                cwd=layout.root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, errors="replace", start_new_session=True,
            )
            pump = threading.Thread(target=_pump, args=(process.stdout, log_file, model["id"], echo), daemon=True)
            pump.start()
            while True:
                report.peak_rss_bytes = max(report.peak_rss_bytes, tree_rss_bytes(process.pid))
                try:
                    process.wait(timeout=SAMPLE_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if time.monotonic() - started > limit:
                    report.timed_out = True
                    _terminate(process)
                    break
            pump.join(timeout=5)
        report.exit_code = process.returncode
        report.seconds = round(time.monotonic() - started, 3)

    for take, variant in pending:
        result = store.read_result(layout, model["id"], take["audioSHA256"], variant, runner_sha)
        if result is None:
            result = {"error": "timeout" if report.timed_out else "no-result"}
        else:
            report.ran += 1
        report.results[take["token"]] = result
    store.append_jsonl(output_dir / "runs.jsonl", {
        "model": model["id"], "runnerSHA256": runner_sha, "takes": len(pending), "scored": report.ran,
        "peakRSSBytes": report.peak_rss_bytes, "memoryGB": model.get("memoryGB"), "seconds": report.seconds,
        "exitCode": report.exit_code, "timedOut": report.timed_out, "at": utc_now(),
    })
    if report.exit_code == 0 and not report.timed_out:
        job_path.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
    else:
        echo(f"qc run: {model['id']}: runner exited {report.exit_code}{' (timeout)' if report.timed_out else ''}; "
             f"its job and log are kept under build/private/qc/jobs")
    return report


def _pump(stream, log_file, model_id: str, echo: Callable[[str], None]) -> None:
    for line in stream:
        log_file.write(line)
        log_file.flush()
        echo(f"[{model_id}] {line.rstrip()}")


def _terminate(process: subprocess.Popen) -> None:
    for sig, grace in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 5.0)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue
