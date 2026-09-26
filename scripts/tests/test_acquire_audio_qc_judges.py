#!/usr/bin/env python3
"""Judge panel acquisition (AQ-06): pinned, resumable, verified downloads, hash-locked runtimes, offline verify.

No test reaches the network: a fake hub serves fixture bytes by URL, and a fake
runner stands in for `python -m venv`, pip and the import probe, writing a
site-packages tree whose RECORD files list each installed file's SHA-256.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import acquire_audio_qc_judges as acquire  # noqa: E402
from audio_qc_judges import load_registry, runtime_lock  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CAMPPLUS = "speaker.campplus-voxceleb@1"
PYIN = "pitch.pyin@1"
SENSEVOICE = "asr.sensevoice-small-f16@1"
RESNET = "speaker.resnet293-voxceleb@1"
DNSMOS = "quality.dnsmos-p835@1"
SITE_PACKAGES = "lib/python3.14/site-packages"


def _blob_id(content: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def _pin(content: bytes, *, large: bool) -> dict:
    key = "lfsSHA256" if large else "gitBlobID"
    value = hashlib.sha256(content).hexdigest() if large else _blob_id(content)
    return {key: value, "size": len(content)}


def _tarball(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o755
            bundle.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, status: int, payload: bytes, start: int, total: int, cut: int | None) -> None:
        self.status = status
        self.headers = {"Content-Range": f"bytes {start}-{total - 1}/{total}"} if status == 206 else {}
        self._payload = payload
        self._position = 0
        self._cut = cut

    def read(self, size: int) -> bytes:
        if self._cut is not None and self._position >= self._cut:
            raise ConnectionResetError("fixture drop")
        end = self._position + size
        if self._cut is not None:
            end = min(end, self._cut)
        block = self._payload[self._position:end]
        self._position += len(block)
        return block

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_exc) -> None:
        return None


class FakeHub:
    """Serves fixture bytes by URL; can drop a transfer, ignore ranges, fail or go offline."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)
        self.requests: list[tuple[str, str | None]] = []
        self.cut: dict[str, int] = {}
        self.errors: dict[str, int] = {}
        self.ignore_range = False
        self.offline = False

    def __call__(self, request, timeout):
        url = request.full_url
        self.requests.append((url, request.get_header("Range")))
        if self.offline:
            raise AssertionError("the network was used")
        if url in self.errors:
            raise urllib.error.HTTPError(url, self.errors[url], "fixture", {}, None)
        body = self.files[url]
        header = request.get_header("Range")
        start, status = 0, 200
        if header and not self.ignore_range:
            start, status = int(header.split("=")[1].rstrip("-")), 206
        return FakeResponse(status, body[start:], start, len(body), self.cut.pop(url, None))


def _record_hash(content: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode("ascii")


def _install_distribution(venv: Path, name: str, version: str) -> None:
    """A wheel install as pip leaves it: the module, and a RECORD hashing each file (RECORD itself unhashed)."""
    site = venv / SITE_PACKAGES
    module = name.replace("-", "_")
    files = {f"{module}/__init__.py": f"# fixture {name} {version}\n".encode(),
             f"{module}-{version}.dist-info/METADATA": f"Name: {name}\nVersion: {version}\n".encode()}
    rows = []
    for relative, content in files.items():
        (site / relative).parent.mkdir(parents=True, exist_ok=True)
        (site / relative).write_bytes(content)
        rows.append(f"{relative},{_record_hash(content)},{len(content)}")
    rows.append(f"{module}-{version}.dist-info/RECORD,,")
    (site / f"{module}-{version}.dist-info/RECORD").write_text("\n".join(rows) + "\n", encoding="utf-8")


class FakeRunner:
    """`python -m venv`, pip, the distribution listing and the import probe, recorded with their environments."""

    def __init__(self, installed: dict[str, str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.environments: list[dict[str, str] | None] = []
        # Given: what the venv holds whatever pip installs. Otherwise pip installs each file it reads.
        self.fixed = installed is not None
        self.installed = installed
        self.probe_fails = False
        self.pip_fails = False

    def __call__(self, argv, *, env=None, capture=False, cwd=None):
        argv = [str(item) for item in argv]
        self.calls.append(argv)
        self.environments.append(env)
        if argv[1:3] == ["-m", "venv"]:
            python = Path(argv[3]) / "bin/python3"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!fixture\n", encoding="utf-8")
            _install_distribution(Path(argv[3]), "pip", "26.0")
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[1:4] == ["-m", "pip", "install"]:
            if "-r" in argv and not self.fixed:
                lock = argv[argv.index("-r") + 1]
                self.installed = dict(self.installed or {})
                venv = Path(argv[0]).parent.parent
                for line in Path(lock).read_text(encoding="utf-8").splitlines():
                    if "==" in line and not line.startswith("#"):
                        name, version = line.split()[0].split("==")
                        self.installed[name] = version
                        _install_distribution(venv, name, version)
            return subprocess.CompletedProcess(argv, 1 if self.pip_fails else 0, "", "")
        if argv[1] == "-c" and argv[2] == acquire.LIST_DISTRIBUTIONS:
            pairs = sorted({**(self.installed or {}), "pip": "26.0"}.items())
            return subprocess.CompletedProcess(argv, 0, json.dumps(pairs), "")
        if argv[1] == "-c" and argv[2] == acquire.IMPORT_PROBE:
            if self.probe_fails:
                return subprocess.CompletedProcess(argv, 1, "", "ModuleNotFoundError: No module named 'fixture'\n")
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(f"unexpected command {argv[:4]}")


class AcquisitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "external-models"
        self.registry = copy.deepcopy(load_registry())
        acquisition = self.registry["acquisition"]
        # The CAM++ judge, pinned to fixture bytes.
        self.content = {"README.md": b"# fixture card\n", "config.yaml": b"model: fixture\n",
                        "voxceleb_CAM++_LM.onnx": bytes(range(256)) * 300}
        judge = self.registry["judges"][CAMPPLUS]
        judge["pins"]["files"] = {name: _pin(data, large=name.endswith(".onnx")) for name, data in self.content.items()}
        self.revision = judge["pins"]["revision"]
        served = {acquire.hub_url(judge["pins"]["repository"], self.revision, name): data
                  for name, data in self.content.items()}
        # The interpreter archive, pinned to a fixture tarball.
        self.interpreter_archive = _tarball({"python/bin/python3.14": b"#!fixture interpreter\n"})
        acquisition["interpreter"].update(sha256=hashlib.sha256(self.interpreter_archive).hexdigest(),
                                          size=len(self.interpreter_archive))
        served[acquisition["interpreter"]["url"]] = self.interpreter_archive
        # The native SenseVoice runtime, pinned to a fixture tarball.
        self.binary = b"#!/bin/sh\necho fixture\n"
        native = _tarball({"./llama-funasr-sensevoice": self.binary, "./README.md": b"runtime\n"})
        artifact = acquisition["artifacts"]["sensevoice-llamacpp-runtime-v0.1.9"]
        artifact.update(sha256=hashlib.sha256(native).hexdigest(), size=len(native),
                        members={"llama-funasr-sensevoice": hashlib.sha256(self.binary).hexdigest()})
        served[artifact["url"]] = native
        # DNSMOS, a GitHub-sourced snapshot, pinned to fixture bytes at nested paths.
        self.dnsmos_content = {"DNSMOS/DNSMOS/sig_bak_ovr.onnx": b"primary" * 900,
                               "DNSMOS/DNSMOS/model_v8.onnx": b"p808" * 700}
        dnsmos = self.registry["judges"][DNSMOS]["pins"]
        dnsmos["files"] = {name: {"sha256": hashlib.sha256(data).hexdigest(), "gitBlobID": _blob_id(data),
                                  "size": len(data)} for name, data in self.dnsmos_content.items()}
        for name, data in self.dnsmos_content.items():
            served[acquire.github_raw_url(dnsmos["repository"], dnsmos["revision"], name)] = data
        # No committed judge is quarantined or blocked any more: the fixture copy holds one of each.
        resnet = self.registry["judges"][RESNET]
        resnet["status"] = "quarantined"
        resnet["quarantine"] = {"date": "2026-09-26", "reason": "fixture license question"}
        resnet["plannedExecution"] = resnet.pop("execution")
        self.registry["acquisitionBlocked"] = [{
            "id": "quality.fixture-blocked", "judge": "quality.fixture-blocked@1", "status": "blocked",
            "date": "2026-09-26", "reason": "fixture: nothing to pin", "unblock": "pin it"}]
        self.hub = FakeHub(served)
        self.lock = runtime_lock(self.registry, "onnx-cpu")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _target(self, judge_id: str) -> acquire.Target:
        return next(target for target in acquire.targets(self.registry) if target.judge_id == judge_id)

    def _fetch(self, *judges: str, runner: FakeRunner | None = None) -> dict:
        runner = runner or FakeRunner()
        return acquire.fetch(self.root, self.registry, [self._target(judge_id) for judge_id in judges],
                             opener=self.hub, runner=runner, sleep=lambda _seconds: None)

    def test_plan_names_bytes_destinations_and_blocked_judges_without_the_network(self) -> None:
        self.hub.offline = True
        value = acquire.plan(self.root, self.registry, acquire.select(self.registry, everything=True))
        rows = {row["judge"]: row for row in value["judges"]}
        self.assertEqual(rows[CAMPPLUS]["bytes"], sum(len(data) for data in self.content.values()))
        self.assertEqual(rows[CAMPPLUS]["destination"], f"wespeaker-voxceleb-campplus-lm/{self.revision}")
        self.assertEqual(rows[CAMPPLUS]["state"], "absent")
        self.assertEqual(rows[PYIN]["destination"], None)
        self.assertEqual(rows[RESNET]["state"], "blocked")
        self.assertIn("quarantined", rows[RESNET]["blocked"])
        self.assertEqual([entry["judge"] for entry in value["acquisitionBlocked"]], ["quality.fixture-blocked@1"])
        # Blocked judges never count toward what would be downloaded.
        self.assertEqual(value["modelBytes"], sum(row["bytes"] for row in rows.values() if not row["blocked"]))
        self.assertEqual(sum(value["modelBytesByStage"].values()), value["modelBytes"])
        self.assertEqual(self.hub.requests, [])

    def test_selection_refuses_what_may_not_be_fetched(self) -> None:
        with self.assertRaisesRegex(acquire.AcquisitionError, "quarantined"):
            acquire.select(self.registry, judges=[RESNET])
        with self.assertRaisesRegex(acquire.AcquisitionError, "blocked"):
            acquire.select(self.registry, judges=["quality.fixture-blocked@1"])
        with self.assertRaisesRegex(acquire.AcquisitionError, "not a panel judge"):
            acquire.select(self.registry, judges=["asr.whisper-small@1"])
        stage_two = {target.judge_id for target in acquire.select(self.registry, stage=2)}
        self.assertIn(RESNET, stage_two)
        # A stage or --all skips a quarantined judge with its reason and fetches nothing for it.
        report = acquire.fetch(self.root, self.registry, [self._target(RESNET)], opener=self.hub,
                               runner=FakeRunner(), sleep=lambda _seconds: None)
        self.assertEqual(report["fetched"], [])
        self.assertIn("quarantined", report["skipped"][0]["reason"])
        self.assertEqual(self.hub.requests, [])

    def test_fetch_verifies_every_file_builds_the_runtime_and_writes_a_relative_receipt(self) -> None:
        runner = FakeRunner()
        report = self._fetch(CAMPPLUS, runner=runner)
        self.assertEqual([item["judge"] for item in report["fetched"]], [CAMPPLUS])
        snapshot = self.root / "wespeaker-voxceleb-campplus-lm" / self.revision
        self.assertEqual({path.name for path in snapshot.iterdir()}, set(self.content))
        self.assertFalse((self.root / "wespeaker-voxceleb-campplus-lm" / ".partial").exists())
        receipt_text = (self.root / "wespeaker-voxceleb-campplus-lm/receipt.json").read_text(encoding="utf-8")
        receipt = json.loads(receipt_text)
        self.assertEqual(receipt["files"]["voxceleb_CAM++_LM.onnx"]["sha256"],
                         hashlib.sha256(self.content["voxceleb_CAM++_LM.onnx"]).hexdigest())
        self.assertEqual(receipt["runtime"]["lockSHA256"], self.registry["acquisition"]["runtimes"]["onnx-cpu"]["lockSHA256"])
        self.assertNotIn(str(self.root), receipt_text)
        self.assertNotIn(self.temporary.name, receipt_text)
        # The venv is built only from the hash lock, with no resolution and no user configuration.
        pip = next(call for call in runner.calls if call[1:4] == ["-m", "pip", "install"])
        for flag in ("--isolated", "--require-hashes", "--no-deps", "--no-cache-dir"):
            self.assertIn(flag, pip)
        self.assertEqual(pip[pip.index("--only-binary") + 1], ":all:")
        self.assertEqual(Path(pip[pip.index("-r") + 1]), REPO / "config/audio-qc-runtimes/onnx-cpu.txt")
        self.assertTrue(any(call[2] == acquire.IMPORT_PROBE for call in runner.calls if len(call) > 2))
        # Offline verification passes and never reaches the hub; a second fetch downloads nothing.
        self.hub.offline = True
        results = acquire.verify(self.root, self.registry, [self._target(CAMPPLUS)], runner=runner)
        self.assertEqual([(item["judge"], item["status"], item["problems"]) for item in results],
                         [(CAMPPLUS, "PASS", [])])
        checks = results[0]["checks"]
        # Every locked distribution plus pip: two hashed files each, RECORD itself counted as unhashed.
        self.assertEqual(checks["runtimeFiles"], 2 * (len(self.lock) + 1))
        self.assertEqual(checks["unhashedRecordEntries"], len(self.lock) + 1)
        self.assertEqual((checks["snapshotFiles"], checks["interpreterFiles"]), (3, 1))
        venvs = sum(1 for call in runner.calls if call[1:3] == ["-m", "venv"])
        again = self._fetch(CAMPPLUS, runner=runner)
        self.assertEqual([item["judge"] for item in again["fetched"]], [CAMPPLUS])
        # A verified runtime is reused, not rebuilt.
        self.assertEqual(sum(1 for call in runner.calls if call[1:3] == ["-m", "venv"]), venvs)

    def test_an_interrupted_download_resumes_from_where_it_stopped(self) -> None:
        judge = self.registry["judges"][CAMPPLUS]
        url = acquire.hub_url(judge["pins"]["repository"], self.revision, "voxceleb_CAM++_LM.onnx")
        self.hub.cut[url] = 20_000
        self._fetch(CAMPPLUS)
        ranges = [header for requested, header in self.hub.requests if requested == url]
        self.assertEqual(ranges, [None, "bytes=20000-"])
        stored = self.root / "wespeaker-voxceleb-campplus-lm" / self.revision / "voxceleb_CAM++_LM.onnx"
        self.assertEqual(stored.read_bytes(), self.content["voxceleb_CAM++_LM.onnx"])

    def test_a_server_that_ignores_the_range_restarts_the_file(self) -> None:
        judge = self.registry["judges"][CAMPPLUS]
        url = acquire.hub_url(judge["pins"]["repository"], self.revision, "voxceleb_CAM++_LM.onnx")
        self.hub.cut[url] = 10_000
        self.hub.ignore_range = True
        self._fetch(CAMPPLUS)
        stored = self.root / "wespeaker-voxceleb-campplus-lm" / self.revision / "voxceleb_CAM++_LM.onnx"
        self.assertEqual(stored.read_bytes(), self.content["voxceleb_CAM++_LM.onnx"])

    def test_a_digest_mismatch_is_refused_and_nothing_unverified_is_kept(self) -> None:
        judge = self.registry["judges"][CAMPPLUS]
        url = acquire.hub_url(judge["pins"]["repository"], self.revision, "voxceleb_CAM++_LM.onnx")
        original = self.hub.files[url]
        self.hub.files[url] = original[:-1] + b"!"  # same size, different bytes
        with self.assertRaisesRegex(acquire.AcquisitionError, "does not match its registry pin"):
            self._fetch(CAMPPLUS)
        snapshot = self.root / "wespeaker-voxceleb-campplus-lm" / self.revision
        self.assertFalse((snapshot / "voxceleb_CAM++_LM.onnx").exists())
        self.assertFalse(list((self.root / "wespeaker-voxceleb-campplus-lm").rglob("*.part")))
        self.assertFalse((self.root / "wespeaker-voxceleb-campplus-lm/receipt.json").exists())
        # A file already in the snapshot that differs from its pin is refused, never replaced.
        self.hub.files[url] = original
        snapshot.mkdir(parents=True, exist_ok=True)
        (snapshot / "voxceleb_CAM++_LM.onnx").write_bytes(b"tampered")
        with self.assertRaisesRegex(acquire.AcquisitionError, "present but differs from its pin"):
            self._fetch(CAMPPLUS)
        self.assertEqual((snapshot / "voxceleb_CAM++_LM.onnx").read_bytes(), b"tampered")

    def test_a_missing_or_gated_file_is_not_retried(self) -> None:
        judge = self.registry["judges"][CAMPPLUS]
        url = acquire.hub_url(judge["pins"]["repository"], self.revision, "config.yaml")
        self.hub.errors[url] = 401
        with self.assertRaisesRegex(acquire.AcquisitionError, "HTTP 401"):
            self._fetch(CAMPPLUS)
        self.assertEqual(sum(1 for requested, _ in self.hub.requests if requested == url), 1)

    def test_a_venv_that_differs_from_its_lock_or_fails_its_probe_is_refused(self) -> None:
        drifted = FakeRunner(installed={name: entry["version"] for name, entry in self.lock.items()})
        drifted.installed["numpy"] = "0.0.1"
        with self.assertRaisesRegex(acquire.AcquisitionError, "differs from its lock"):
            self._fetch(CAMPPLUS, runner=drifted)
        extra = FakeRunner(installed={**{name: entry["version"] for name, entry in self.lock.items()},
                                      "soynlp": "0.0.493"})
        with self.assertRaisesRegex(acquire.AcquisitionError, "unlocked distributions"):
            self._fetch(CAMPPLUS, runner=extra)
        probe = FakeRunner()
        probe.probe_fails = True
        with self.assertRaisesRegex(acquire.AcquisitionError, "import probe failed"):
            self._fetch(CAMPPLUS, runner=probe)
        self.assertFalse((self.root / "wespeaker-voxceleb-campplus-lm/receipt.json").exists())

    def test_sdist_builds_run_after_the_locked_setuptools_without_isolation(self) -> None:
        runner = FakeRunner()
        interpreter = acquire.ensure_interpreter(self.root, self.registry["acquisition"]["interpreter"],
                                                 opener=self.hub, sleep=lambda _seconds: None)
        acquire.ensure_runtime(self.root, self.registry, "funasr-torch", interpreter, runner=runner)
        pips = [call for call in runner.calls if call[1:4] == ["-m", "pip", "install"]]
        self.assertEqual(len(pips), 2)
        bootstrap = Path(pips[0][pips[0].index("-r") + 1]).read_text(encoding="utf-8")
        self.assertTrue(bootstrap.startswith("setuptools=="))
        self.assertIn("--hash=sha256:", bootstrap)
        builds = self.registry["acquisition"]["runtimes"]["funasr-torch"]["sourceBuilds"]
        self.assertEqual(pips[1][pips[1].index("--no-binary") + 1], ",".join(builds))
        self.assertIn("--no-build-isolation", pips[1])
        self.assertIn("--require-hashes", pips[1])

    def test_the_interpreter_and_native_runtime_are_verified_and_extracted_once(self) -> None:
        spec = self.registry["acquisition"]["interpreter"]
        python = acquire.ensure_interpreter(self.root, spec, opener=self.hub, sleep=lambda _seconds: None)
        self.assertEqual(python.read_bytes(), b"#!fixture interpreter\n")
        requests = len(self.hub.requests)
        self.assertEqual(acquire.ensure_interpreter(self.root, spec, opener=self.hub), python)
        self.assertEqual(len(self.hub.requests), requests)
        members = acquire.ensure_artifact(self.root, self.registry, "sensevoice-llamacpp-runtime-v0.1.9",
                                          opener=self.hub, sleep=lambda _seconds: None)
        binary = members["llama-funasr-sensevoice"]
        self.assertEqual(binary.read_bytes(), self.binary)
        self.assertTrue(binary.stat().st_mode & 0o100)
        binary.write_bytes(b"swapped")
        with self.assertRaisesRegex(acquire.AcquisitionError, "differs from its pinned SHA-256"):
            acquire.ensure_artifact(self.root, self.registry, "sensevoice-llamacpp-runtime-v0.1.9", opener=self.hub)
        # A directory this tool did not build is never removed.
        foreign = self.root / spec["directory"]
        (foreign / acquire.OWNED_MARKER).unlink()
        (foreign / acquire.RECEIPT_NAME).unlink()
        with self.assertRaisesRegex(acquire.AcquisitionError, "not built by this tool"):
            acquire.ensure_interpreter(self.root, spec, opener=self.hub)

    def test_a_tampered_or_repinned_judge_fails_offline_verification(self) -> None:
        runner = FakeRunner()
        self._fetch(CAMPPLUS, runner=runner)
        self.hub.offline = True
        snapshot = self.root / "wespeaker-voxceleb-campplus-lm" / self.revision
        (snapshot / "config.yaml").write_bytes(b"model: swapped\n")
        result = acquire.verify(self.root, self.registry, [self._target(CAMPPLUS)], runner=runner)[0]
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("differs from its registry pin" in problem for problem in result["problems"]))
        (snapshot / "config.yaml").write_bytes(self.content["config.yaml"])
        self.registry["judges"][CAMPPLUS]["execution"]["threads"] = 3
        result = acquire.verify(self.root, self.registry, [self._target(CAMPPLUS)], runner=runner)[0]
        self.assertIn("the registry entry changed since acquisition; fetch it again", result["problems"])
        missing = acquire.verify(self.root, self.registry, [self._target(PYIN)], runner=runner)
        self.assertEqual(missing[0]["problems"], ["not fetched"])
        self.assertEqual(acquire.verify(self.root, self.registry, [self._target(PYIN)], runner=runner, require=False), [])

    def test_a_weightless_judge_and_the_native_runtime_fetch_without_a_snapshot_download(self) -> None:
        self._fetch(PYIN)
        receipt = json.loads((self.root / "pitch-pyin/receipt.json").read_text(encoding="utf-8"))
        self.assertIsNone(receipt["snapshot"])
        self.assertEqual(receipt["runtime"]["family"], "librosa-dsp")
        launch = acquire.worker_launch(self.root, self.registry, PYIN)
        self.assertEqual(launch["engine"], "pyin-librosa")
        self.assertEqual(launch["command"], [str(self.root / "audio-qc-runtime-librosa-dsp-py314/bin/python3"),
                                             str(acquire.WORKER)])
        self.assertEqual(launch["engineConfig"]["configuration"], self.registry["judges"][PYIN]["configuration"])

    def test_the_worker_launch_comes_from_a_current_receipt(self) -> None:
        with self.assertRaisesRegex(acquire.AcquisitionError, "not fetched"):
            acquire.worker_launch(self.root, self.registry, CAMPPLUS)
        with self.assertRaisesRegex(acquire.AcquisitionError, "not a runnable panel judge"):
            acquire.worker_launch(self.root, self.registry, RESNET)
        self._fetch(CAMPPLUS)
        launch = acquire.worker_launch(self.root, self.registry, CAMPPLUS)
        self.assertEqual((launch["engine"], launch["lane"], launch["threads"]), ("wespeaker-onnx", "cpu", 2))
        config = launch["engineConfig"]
        self.assertEqual(config["snapshot"], str(self.root / "wespeaker-voxceleb-campplus-lm" / self.revision))
        self.assertEqual((config["judge"], config["revision"]), (CAMPPLUS, self.revision))


    # ------------------------------------------------------------------ #
    # Supply-chain hardening (AQ-06 review)
    # ------------------------------------------------------------------ #

    def test_every_venv_and_pip_step_reads_no_pip_configuration_file(self) -> None:
        runner = FakeRunner()
        self._fetch(CAMPPLUS, runner=runner)
        steps = [(call, env) for call, env in zip(runner.calls, runner.environments)
                 if call[1:3] == ["-m", "venv"] or call[1:4] == ["-m", "pip", "install"]]
        self.assertGreaterEqual(len(steps), 2)
        for call, env in steps:
            with self.subTest(step=call[1:4]):
                self.assertEqual(env["PIP_CONFIG_FILE"], os.devnull)
                self.assertNotIn("PIP_INDEX_URL", env)

    def test_a_venv_file_that_differs_from_its_record_fails_verify_and_is_rebuilt(self) -> None:
        runner = FakeRunner()
        self._fetch(CAMPPLUS, runner=runner)
        self.hub.offline = True
        venv = self.root / self.registry["acquisition"]["runtimes"]["onnx-cpu"]["venv"]
        module = venv / SITE_PACKAGES / "onnxruntime/__init__.py"
        module.write_text("import os  # swapped\n", encoding="utf-8")
        result = acquire.verify(self.root, self.registry, [self._target(CAMPPLUS)], runner=runner)[0]
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("1 installed files differ from their RECORD (first: onnxruntime/__init__.py)" in problem
                            for problem in result["problems"]), result["problems"])
        # A missing recorded file and a distribution without a RECORD are refused too.
        module.unlink()
        record = next((venv / SITE_PACKAGES).glob("numpy-*.dist-info")) / "RECORD"
        record.unlink()
        problems = acquire.venv_record_check(venv)[0]
        self.assertTrue(any("recorded files are missing" in problem for problem in problems))
        self.assertTrue(any("has no RECORD" in problem for problem in problems))
        # fetch reuses a runtime only when the full check passes: this one is rebuilt.
        venvs = sum(1 for call in runner.calls if call[1:3] == ["-m", "venv"])
        self.hub.offline = False
        self._fetch(CAMPPLUS, runner=runner)
        self.assertEqual(sum(1 for call in runner.calls if call[1:3] == ["-m", "venv"]), venvs + 1)
        result = acquire.verify(self.root, self.registry, [self._target(CAMPPLUS)], runner=runner)[0]
        self.assertEqual(result["status"], "PASS", result["problems"])

    def test_a_record_entry_outside_the_venv_is_refused(self) -> None:
        venv = self.root / "venv"
        _install_distribution(venv, "fixture", "1.0")
        record = venv / SITE_PACKAGES / "fixture-1.0.dist-info/RECORD"
        record.write_text(record.read_text(encoding="utf-8") + "../../../../outside.py,sha256=abc,3\n",
                          encoding="utf-8")
        problems, counts = acquire.venv_record_check(venv)
        self.assertIn("fixture-1.0.dist-info records a path outside the venv", problems)
        self.assertEqual((counts["runtimeFiles"], counts["unhashedRecordEntries"]), (2, 1))

    def test_the_interpreter_is_rehashed_against_its_pin_and_its_archive(self) -> None:
        runner = FakeRunner()
        self._fetch(CAMPPLUS, runner=runner)
        spec = self.registry["acquisition"]["interpreter"]
        python = acquire.interpreter_python(self.root, spec)
        python.write_bytes(b"#!swapped interpreter\n")
        result = acquire.verify(self.root, self.registry, [self._target(CAMPPLUS)], runner=runner)[0]
        self.assertIn("1 extracted interpreter files differ from the pinned archive (first: python/bin/python3.14)",
                      result["problems"])
        # fetch re-extracts an interpreter that no longer matches its archive, from the verified archive.
        acquire.ensure_interpreter(self.root, spec, opener=self.hub, sleep=lambda _seconds: None)
        self.assertEqual(python.read_bytes(), b"#!fixture interpreter\n")
        self.assertEqual(acquire.interpreter_check(self.root, spec)[0], [])
        # The archive itself is re-hashed against its pin on every verify.
        archive = self.root / spec["archiveDirectory"] / spec["archive"]
        archive.write_bytes(archive.read_bytes() + b"\0")
        result = acquire.verify(self.root, self.registry, [self._target(CAMPPLUS)], runner=runner)[0]
        self.assertIn("the interpreter archive is missing or differs from its pinned SHA-256", result["problems"])

    def test_a_symbolic_link_inside_a_panel_snapshot_fails_verify(self) -> None:
        runner = FakeRunner()
        self._fetch(CAMPPLUS, runner=runner)
        snapshot = self.root / "wespeaker-voxceleb-campplus-lm" / self.revision
        elsewhere = self.root / "elsewhere-config.yaml"
        elsewhere.write_bytes(self.content["config.yaml"])
        (snapshot / "config.yaml").unlink()
        (snapshot / "config.yaml").symlink_to(elsewhere)
        result = acquire.verify(self.root, self.registry, [self._target(CAMPPLUS)], runner=runner)[0]
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("symbolic link (config.yaml)" in problem for problem in result["problems"]))

    def test_a_snapshot_path_that_resolves_outside_the_model_root_is_refused(self) -> None:
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        judge_directory = self.root / "wespeaker-voxceleb-campplus-lm"
        judge_directory.mkdir(parents=True)
        (judge_directory / self.revision).symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(acquire.AcquisitionError, "resolves outside the model root"):
            self._fetch(CAMPPLUS)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse(any(url.startswith(acquire.HUB) for url, _range in self.hub.requests))

    def test_the_whole_selection_must_fit_before_anything_is_fetched(self) -> None:
        selection = [self._target(CAMPPLUS), self._target(PYIN)]
        needed = acquire.disk_requirement(self.root, self.registry, selection)
        runtimes = self.registry["acquisition"]["runtimes"]
        expected_runtimes = sum(int(runtimes[family]["downloadBytes"] * acquire.INSTALLED_BYTES_PER_DOWNLOADED_BYTE)
                                for family in ("onnx-cpu", "librosa-dsp"))
        self.assertEqual(needed["modelBytes"], sum(len(data) for data in self.content.values()))
        self.assertEqual(needed["runtimeInstallBytes"], expected_runtimes)
        self.assertEqual(needed["totalBytes"], needed["modelBytes"] + needed["runtimeInstallBytes"]
                         + needed["interpreterBytes"] + acquire.FREE_SPACE_MARGIN_BYTES)
        usage = shutil_usage(free=needed["totalBytes"] - 1)
        with mock.patch.object(acquire.shutil, "disk_usage", return_value=usage):
            with self.assertRaisesRegex(acquire.AcquisitionError, "nothing was fetched"):
                self._fetch(CAMPPLUS, PYIN)
        self.assertEqual(self.hub.requests, [])
        # A built runtime and a fetched snapshot no longer count toward what a fetch needs.
        self._fetch(CAMPPLUS)
        after = acquire.disk_requirement(self.root, self.registry, selection)
        self.assertEqual(after["modelBytes"], 0)
        self.assertEqual(after["runtimeInstallBytes"],
                         int(runtimes["librosa-dsp"]["downloadBytes"] * acquire.INSTALLED_BYTES_PER_DOWNLOADED_BYTE))
        self.assertEqual(after["interpreterBytes"], 0)

    def test_a_github_snapshot_downloads_from_its_pinned_commit_and_verifies(self) -> None:
        runner = FakeRunner()
        report = self._fetch(DNSMOS, runner=runner)
        self.assertEqual([item["judge"] for item in report["fetched"]], [DNSMOS])
        pins = self.registry["judges"][DNSMOS]["pins"]
        urls = {url for url, _range in self.hub.requests if "raw.githubusercontent.com" in url}
        self.assertEqual(urls, {f"https://raw.githubusercontent.com/microsoft/DNS-Challenge/{pins['revision']}/{name}"
                                for name in self.dnsmos_content})
        snapshot = self.root / "dnsmos-p835" / pins["revision"]
        for name, data in self.dnsmos_content.items():
            self.assertEqual((snapshot / name).read_bytes(), data)
        self.hub.offline = True
        result = acquire.verify(self.root, self.registry, [self._target(DNSMOS)], runner=runner)[0]
        self.assertEqual(result["status"], "PASS", result["problems"])
        # Both digests bind a GitHub file: bytes with the right blob ID but another SHA-256 are refused.
        name = "DNSMOS/DNSMOS/model_v8.onnx"
        pins["files"][name]["sha256"] = "0" * 64
        result = acquire.verify(self.root, self.registry, [self._target(DNSMOS)], runner=runner)[0]
        self.assertTrue(any(f"snapshot file {name} differs from its registry pin" in problem
                            for problem in result["problems"]))


def shutil_usage(*, free: int) -> SimpleNamespace:
    """A disk_usage result with the given free bytes."""
    return SimpleNamespace(total=free * 2, used=free, free=free)


class TransportTests(unittest.TestCase):
    """Downloads and every redirect stay on https and on the pinned hosts."""

    def test_only_https_on_the_download_hosts_is_allowed(self) -> None:
        for url in ("https://huggingface.co/x/y/resolve/abc/file", "https://cdn-lfs-us-1.hf.co/repos/a/b",
                    "https://cas-bridge.xethub.hf.co/xet", "https://us.gcp.cdn.huggingface.co/x",
                    "https://github.com/astral-sh/python-build-standalone/releases/download/x.tar.gz",
                    "https://objects.githubusercontent.com/github-production-release-asset/x",
                    "https://release-assets.githubusercontent.com/github-production-release-asset/x",
                    "https://raw.githubusercontent.com/microsoft/DNS-Challenge/abc/DNSMOS/x.onnx"):
            with self.subTest(url=url):
                self.assertTrue(acquire.allowed_download_url(url))
        for url in ("http://huggingface.co/x", "https://evil.example/x", "https://huggingface.co.evil.example/x",
                    "https://nothf.co/x", "https://user:secret@huggingface.co/x", "https://huggingface.co:8443/x",
                    "ftp://huggingface.co/x", "https://gist.githubusercontent.com/x", "file:///etc/passwd"):
            with self.subTest(url=url):
                self.assertFalse(acquire.allowed_download_url(url))

    def test_a_redirect_is_followed_only_to_an_allowed_https_host(self) -> None:
        handler = acquire.PinnedRedirectHandler()
        request = urllib.request.Request("https://huggingface.co/x/y/resolve/abc/model.onnx",
                                         headers={"Range": "bytes=10-"})
        followed = handler.redirect_request(request, None, 302, "Found", {}, "https://cdn-lfs.hf.co/x?signed=1")
        self.assertEqual(followed.full_url, "https://cdn-lfs.hf.co/x?signed=1")
        for target in ("http://cdn-lfs.hf.co/x", "https://mirror.example/x?token=secret"):
            with self.subTest(target=target), self.assertRaisesRegex(acquire.AcquisitionError, "redirected") as caught:
                handler.redirect_request(request, None, 302, "Found", {}, target)
            self.assertNotIn("secret", str(caught.exception))

    def test_a_download_url_off_the_allowed_hosts_is_refused_before_any_connection(self) -> None:
        with mock.patch.object(acquire._OPENER, "open", side_effect=AssertionError("connected")):
            with self.assertRaisesRegex(acquire.AcquisitionError, "not an allowed https download host"):
                acquire._open(urllib.request.Request("http://huggingface.co/x"), 1.0)
        self.assertTrue(any(isinstance(handler, acquire.PinnedRedirectHandler) for handler in acquire._OPENER.handlers))


class CommandLineTests(unittest.TestCase):
    def test_fetch_needs_an_explicit_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(acquire.main(["fetch", "--model-root", temporary]), 1)

    def test_plan_reads_the_committed_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(acquire.main(["plan", "--json", "--model-root", temporary]), 0)


if __name__ == "__main__":
    unittest.main()
