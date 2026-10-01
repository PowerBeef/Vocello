"""QC v2 core: the model registry, fetch and verify, the runner host, the cache and takes I/O."""

from __future__ import annotations

import fcntl
import hashlib
import http.server
import importlib.util
import io
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from qc import models, runtime, store  # noqa: E402
from qc.store import Layout  # noqa: E402

PAYLOAD = b"vocello qc fixture weights\n" * 64
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()
REVISION = "0123456789abcdef0123456789abcdef01234567"


def model_entry(**overrides):
    entry = {
        "id": "asr.fixture", "kind": "asr", "runner": "qc.runners.fake", "runtime": "onnx",
        "source": {"host": "huggingface", "repo": "example/fixture", "revision": REVISION,
                   "files": {"weights/model.bin": {"sha256": PAYLOAD_SHA, "bytes": len(PAYLOAD)}}},
        "license": "Apache-2.0", "notice": "", "memoryGB": 1.0, "languages": "any", "version": 1,
    }
    entry.update(overrides)
    return entry


def registry(*entries):
    return {"schemaVersion": 1, "models": list(entries)}


def make_tar(members):
    """A gzip tarball: name -> bytes (a file), None (a directory) or ("symlink", target)."""

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, value in members.items():
            info = tarfile.TarInfo(name.rstrip("/"))
            if value is None:
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                bundle.addfile(info)
            elif isinstance(value, tuple):
                info.type = tarfile.SYMTYPE
                info.linkname = value[1]
                bundle.addfile(info)
            else:
                info.size = len(value)
                info.mode = 0o755 if value.startswith(b"#!") else 0o644
                bundle.addfile(info, io.BytesIO(value))
    return buffer.getvalue()


class RegistryTests(unittest.TestCase):
    def test_valid_registry_loads(self):
        github = model_entry(id="runtime.llamacpp", kind="runtime", runner=None, runtime="llamacpp", source={
            "host": "github-release",
            "files": {"llama.zip": {"url": "https://github.com/example/llama/releases/download/b1/llama.zip",
                                    "sha256": PAYLOAD_SHA, "bytes": 10}}})
        loaded = models.validate_registry(registry(model_entry(), github,
                                                   model_entry(id="pitch.fixture", languages=["french", "english"])))
        self.assertEqual([entry["id"] for entry in loaded], ["asr.fixture", "runtime.llamacpp", "pitch.fixture"])

    def test_registry_violations_are_refused(self):
        cases = {
            "duplicate": registry(model_entry(), model_entry()),
            "kind": registry(model_entry(kind="vibes")),
            "runtime": registry(model_entry(runtime="tensorflow")),
            "revision": registry(model_entry(source=dict(model_entry()["source"], revision="main"))),
            "sha": registry(model_entry(source=dict(model_entry()["source"],
                                                    files={"a.bin": {"sha256": "abc", "bytes": 1}}))),
            "bytes": registry(model_entry(source=dict(model_entry()["source"],
                                                      files={"a.bin": {"sha256": PAYLOAD_SHA, "bytes": -1}}))),
            "path": registry(model_entry(source=dict(model_entry()["source"],
                                                     files={"../escape.bin": {"sha256": PAYLOAD_SHA, "bytes": 1}}))),
            "license": registry(model_entry(license=" ")),
            "runner": registry(model_entry(runner="os.system")),
            "language": registry(model_entry(languages=["klingon"])),
            "github-host": registry(model_entry(source={"host": "github-release", "files": {
                "x.zip": {"url": "https://example.com/x.zip", "sha256": PAYLOAD_SHA, "bytes": 1}}})),
            "schema": {"schemaVersion": 2, "models": []},
        }
        for name, document in cases.items():
            with self.subTest(name), self.assertRaises(models.RegistryError):
                models.validate_registry(document)

    def test_missing_registry_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(models.load_registry(Layout(Path(directory))), [])

    def test_urls_are_pinned_to_the_revision(self):
        entry = model_entry(source=dict(model_entry()["source"], files={
            "weights/model file.bin": {"sha256": PAYLOAD_SHA, "bytes": 1}}))
        entry["code"] = {"host": "github-raw", "repo": "example/code", "revision": REVISION,
                         "files": {"src/net.py": {"sha256": PAYLOAD_SHA, "bytes": 1}}}
        main, code = list(models.model_files(Layout(), entry))
        self.assertEqual(models.file_url(main),
                         f"https://huggingface.co/example/fixture/resolve/{REVISION}/weights/model%20file.bin")
        self.assertEqual(models.file_url(code),
                         f"https://raw.githubusercontent.com/example/code/{REVISION}/src/net.py")
        self.assertEqual(code.destination, Layout().model_dir("asr.fixture") / "code/src/net.py")

    def test_dependencies_and_code_archives_validate(self):
        entry = model_entry(dependencies=[{"name": "ssl-base", "source": dict(model_entry()["source"])}],
                            code={"host": "github-archive", "sha256": PAYLOAD_SHA, "bytes": 10,
                                  "url": f"https://codeload.github.com/example/code/tar.gz/{REVISION}"})
        models.validate_registry(registry(entry))
        for bad in ({"host": "github-archive", "sha256": PAYLOAD_SHA, "bytes": 10, "url": "https://example.com/x.tgz"},
                    {"host": "huggingface", "repo": "a/b", "revision": REVISION,
                     "files": {"x": {"sha256": PAYLOAD_SHA, "bytes": 1}}}):
            with self.subTest(bad), self.assertRaises(models.RegistryError):
                models.validate_registry(registry(dict(entry, code=bad)))
        duplicate = [{"name": "a", "source": entry["source"]}, {"name": "a", "source": entry["source"]}]
        with self.assertRaises(models.RegistryError):
            models.validate_registry(registry(dict(entry, dependencies=duplicate)))


class FixtureServer:
    """A local HTTP server: path -> (status, headers, body)."""

    def __init__(self):
        self.routes = {}
        routes = self.routes

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_GET(self):
                status, headers, body = routes.get(self.path, (404, {}, b""))
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        class Server(http.server.ThreadingHTTPServer):
            def server_bind(self):  # skip the host-name lookup (seconds on a Mac)
                socketserver.TCPServer.server_bind(self)
                self.server_name, self.server_port = self.server_address[:2]

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.layout = Layout(Path(self.directory.name))
        self.server = FixtureServer()
        self.base = f"http://127.0.0.1:{self.server.port}"
        self.environment = mock.patch.dict(os.environ, {"no_proxy": "*", "NO_PROXY": "*"})
        self.environment.start()
        self.logs = []

    def tearDown(self):
        self.environment.stop()
        self.server.close()
        self.directory.cleanup()

    def fetcher(self, **overrides):
        local = ("127.0.0.1",)
        options = dict(layout=self.layout, hf_base=self.base, raw_base=f"{self.base}/raw", allow_http=True,
                       allowlist={host: local for host in models.HOST_ALLOWLIST}, token=None, log=self.logs.append)
        options.update(overrides)
        return models.Fetcher(**options)

    def route(self, path, body=PAYLOAD, status=200, headers=None):
        self.server.routes[f"/example/fixture/resolve/{REVISION}/{path}"] = (status, headers or {}, body)

    def destination(self):
        return self.layout.model_dir("asr.fixture") / "weights/model.bin"

    def test_downloads_verifies_and_then_skips(self):
        self.route("weights/model.bin")
        summary = self.fetcher().fetch([model_entry()])
        self.assertEqual(summary["downloaded"], 1)
        self.assertEqual(self.destination().read_bytes(), PAYLOAD)
        self.assertTrue(any(str(len(PAYLOAD)) in line for line in self.logs))
        self.assertEqual(self.fetcher().fetch([model_entry()])["downloaded"], 0)
        rows = models.verify_models(self.layout, [model_entry()])
        self.assertEqual([row["status"] for row in rows], ["ok"])

    def test_digest_mismatch_is_refused_and_leaves_nothing(self):
        self.route("weights/model.bin", body=b"x" * len(PAYLOAD))
        with self.assertRaisesRegex(models.FetchError, "SHA-256 mismatch"):
            self.fetcher().fetch([model_entry()])
        self.assertFalse(self.destination().exists())
        self.assertFalse(self.destination().with_name("model.bin.part").exists())

    def test_size_overrun_is_refused(self):
        self.route("weights/model.bin", body=PAYLOAD + b"extra")
        with self.assertRaises(models.FetchError):
            self.fetcher().fetch([model_entry()])
        self.assertFalse(self.destination().exists())

    def test_redirect_to_a_disallowed_host_is_refused(self):
        self.route("weights/model.bin", status=302,
                   headers={"Location": f"http://localhost:{self.server.port}/elsewhere/model.bin"})
        self.server.routes["/elsewhere/model.bin"] = (200, {}, PAYLOAD)
        with self.assertRaisesRegex(models.FetchError, "not allowed"):
            self.fetcher().fetch([model_entry()])
        self.assertFalse(self.destination().exists())

    def test_redirect_within_allowed_hosts_is_followed(self):
        self.route("weights/model.bin", status=302, headers={"Location": "/cdn/model.bin"})
        self.server.routes["/cdn/model.bin"] = (200, {}, PAYLOAD)
        self.fetcher().fetch([model_entry()])
        self.assertEqual(self.destination().read_bytes(), PAYLOAD)

    def test_plain_http_is_refused_by_default(self):
        self.route("weights/model.bin")
        with self.assertRaisesRegex(models.FetchError, "not https"):
            self.fetcher(allow_http=False).fetch([model_entry()])

    def test_production_host_rules(self):
        hosts = models.HOST_ALLOWLIST
        self.assertTrue(models.host_allowed("cas-bridge.xethub.hf.co", hosts["huggingface"]))
        self.assertTrue(models.host_allowed("huggingface.co", hosts["huggingface"]))
        self.assertFalse(models.host_allowed("huggingface.co.evil.example", hosts["huggingface"]))
        self.assertFalse(models.host_allowed("evilhf.co", hosts["huggingface"]))
        self.assertTrue(models.host_allowed("objects.githubusercontent.com", hosts["github-release"]))
        self.assertFalse(models.host_allowed("raw.githubusercontent.com", hosts["github-release"]))
        self.assertTrue(models.host_allowed("codeload.github.com", hosts["github-archive"]))
        self.assertFalse(models.host_allowed("huggingface.co", hosts["github-raw"]))

    def test_dependencies_and_raw_code_land_in_their_directories(self):
        dependency_payload = b"encoder weights"
        code_payload = b"print('net')\n"
        entry = model_entry(
            dependencies=[{"name": "ssl-base", "source": {
                "host": "huggingface", "repo": "example/ssl", "revision": REVISION,
                "files": {"model.bin": {"sha256": hashlib.sha256(dependency_payload).hexdigest(),
                                        "bytes": len(dependency_payload)}}}}],
            code={"host": "github-raw", "repo": "example/code", "revision": REVISION,
                  "files": {"src/net.py": {"sha256": hashlib.sha256(code_payload).hexdigest(),
                                           "bytes": len(code_payload)}}})
        self.route("weights/model.bin")
        self.server.routes[f"/example/ssl/resolve/{REVISION}/model.bin"] = (200, {}, dependency_payload)
        self.server.routes[f"/raw/example/code/{REVISION}/src/net.py"] = (200, {}, code_payload)
        self.assertEqual(self.fetcher().fetch([entry])["downloaded"], 3)
        root = self.layout.model_dir("asr.fixture")
        self.assertEqual((root / "deps/ssl-base/model.bin").read_bytes(), dependency_payload)
        self.assertEqual((root / "code/src/net.py").read_bytes(), code_payload)
        self.assertEqual({row["status"] for row in models.verify_models(self.layout, [entry])}, {"ok"})

    def test_code_archives_are_extracted_safely(self):
        archive = make_tar({"repo-abc/": None, "repo-abc/pkg/net.py": b"x = 1\n", "repo-abc/run.sh": b"#!/bin/sh\n"})
        entry = model_entry(code={"host": "github-archive", "sha256": hashlib.sha256(archive).hexdigest(),
                                  "bytes": len(archive), "url": f"{self.base}/codeload/archive.tar.gz"})
        self.route("weights/model.bin")
        self.server.routes["/codeload/archive.tar.gz"] = (200, {}, archive)
        self.fetcher().fetch([entry])
        code = self.layout.model_dir("asr.fixture") / "code"
        self.assertEqual((code / "pkg/net.py").read_text(), "x = 1\n")
        self.assertTrue(models.code_extracted(self.layout, entry))
        self.assertEqual({row["status"] for row in models.verify_models(self.layout, [entry])}, {"ok"})

        for name, members in {"parent": {"repo/../escape.py": b"x"}, "absolute": {"/etc/passwd": b"x"},
                              "link": {"repo/": None, "repo/link": ("symlink", "../../outside")}}.items():
            with self.subTest(name):
                bad = Path(self.directory.name) / f"{name}.tar.gz"
                bad.write_bytes(make_tar(members))
                with self.assertRaises(models.FetchError):
                    models.safe_extract_tar(bad, Path(self.directory.name) / f"out-{name}", strip_components=1)

    def test_seed_directory_links_matching_files_instead_of_downloading(self):
        seed = Path(self.directory.name) / "old-cache/snapshot"
        seed.mkdir(parents=True)
        (seed / "renamed.bin").write_bytes(PAYLOAD)
        (seed / "same-size.bin").write_bytes(b"z" * len(PAYLOAD))
        summary = self.fetcher(seed_dirs=(seed.parent,)).fetch([model_entry()])  # the server has no route
        self.assertEqual((summary["seeded"], summary["downloaded"]), (1, 0))
        self.assertEqual(self.destination().read_bytes(), PAYLOAD)
        self.assertEqual(self.destination().stat().st_ino, (seed / "renamed.bin").stat().st_ino)

    def test_refuses_when_disk_is_short(self):
        self.route("weights/model.bin")
        usage = shutil._ntuple_diskusage(10**12, 10**12 - 1024, 1024)
        with mock.patch.object(models.shutil, "disk_usage", return_value=usage):
            with self.assertRaisesRegex(models.FetchError, "2 GB margin"):
                self.fetcher().fetch([model_entry()])

    def test_verify_reports_missing_and_mismatched_files(self):
        self.assertEqual(models.verify_models(self.layout, [model_entry()])[0]["status"], "missing")
        self.destination().parent.mkdir(parents=True)
        self.destination().write_bytes(b"y" * len(PAYLOAD))
        self.assertEqual(models.verify_models(self.layout, [model_entry()])[0]["status"], "digest-mismatch")


FAKE_RUNNER = '''
import argparse, json, os, sys, time
from qc import store

parser = argparse.ArgumentParser()
parser.add_argument("--job", required=True)
job = json.load(open(parser.parse_args().job))
options = job["options"]
if options.get("sleep"):
    time.sleep(options["sleep"])
ballast = bytearray(8 * 1024 * 1024)
for take in job["takes"]:
    if take["token"] == options.get("skipToken"):
        continue
    print(f"take {take['token']}", flush=True)
    store.write_result(job["outputDir"], model=job["model"], runner_sha=job["runnerSHA256"],
                       audio_sha=take["audioSHA256"], variant=take["variantKey"], duration_seconds=1.0,
                       outputs={"text": open(take["audio"], "rb").read().decode(), "language": take["language"],
                                "cwd": os.getcwd(), "modelDir": job["modelDir"]})
time.sleep(options.get("linger", 0.7))
sys.exit(options.get("exitCode", 0))
'''


class RunnerHostTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.layout = Layout(self.root)
        package = self.root / "scripts/qc"
        (package / "runners").mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "runners/__init__.py").write_text("")
        shutil.copyfile(SCRIPTS / "qc/store.py", package / "store.py")
        (package / "runners/fake.py").write_text(FAKE_RUNNER)
        weights = self.layout.model_dir("asr.fixture") / "weights/model.bin"
        weights.parent.mkdir(parents=True)
        weights.write_bytes(PAYLOAD)
        self.takes = []
        for index, language in enumerate(("french", "english", "german")):
            audio = self.root / f"audio/take{index}.wav"
            audio.parent.mkdir(exist_ok=True)
            audio.write_text(f"take {index}")
            self.takes.append({"token": f"{index:016x}", "audio": str(audio), "language": language,
                               "text": f"script {index}", "reference": None})
        self.lines = []

    def tearDown(self):
        self.directory.cleanup()

    def run_model(self, model=None, takes=None, options=None, **kwargs):
        return runtime.run_runner(model or model_entry(), takes or self.takes, options, layout=self.layout,
                                  python=sys.executable, echo=self.lines.append, **kwargs)

    def runs_logged(self, model_id="asr.fixture"):
        return store.read_jsonl(self.layout.results_dir(model_id) / "runs.jsonl")

    def test_runs_pending_takes_then_serves_them_from_the_cache(self):
        report = self.run_model()
        self.assertEqual((report.ran, report.cached, report.exit_code, report.timed_out), (3, 0, 0, False))
        self.assertEqual(report.failed, [])
        first = report.results[self.takes[0]["token"]]["outputs"]
        self.assertEqual(first["text"], "take 0")
        self.assertEqual(Path(first["cwd"]).resolve(), self.root.resolve())
        self.assertEqual(Path(first["modelDir"]), self.layout.model_dir("asr.fixture").resolve())
        self.assertGreater(report.peak_rss_bytes, 8 * 1024 * 1024)
        self.assertTrue(any("take" in line for line in self.lines))
        self.assertEqual(list(self.layout.jobs.glob("*")), [])  # a successful job leaves no private residue
        logged = self.runs_logged()
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0]["peakRSSBytes"], report.peak_rss_bytes)

        again = self.run_model()
        self.assertEqual((again.ran, again.cached), (0, 3))
        self.assertEqual(len(self.runs_logged()), 1)  # no subprocess for a fully cached run

    def test_runner_identity_change_reruns(self):
        self.run_model()
        bumped = self.run_model(model_entry(version=2))
        self.assertEqual((bumped.ran, bumped.cached), (3, 0))
        source = self.root / "scripts/qc/runners/fake.py"
        source.write_text(source.read_text() + "\n# changed\n")
        self.assertEqual(self.run_model(model_entry(version=2)).ran, 3)
        identity = runtime.runner_identity(self.layout, model_entry())
        with_dependency = model_entry(dependencies=[{"name": "ssl", "source": model_entry()["source"]}])
        self.assertNotEqual(runtime.runner_identity(self.layout, with_dependency), identity)
        # A shared helper (the LLM prompts live in runners/_llama.py) or qc/pitch.py changes it too.
        (self.root / "scripts/qc/runners/_kit.py").write_text("PROMPT = 'v1'\n")
        with_helper = runtime.runner_identity(self.layout, model_entry())
        self.assertNotEqual(with_helper, identity)
        (self.root / "scripts/qc/pitch.py").write_text("# pitch helpers\n")
        with_pitch = runtime.runner_identity(self.layout, model_entry())
        self.assertNotEqual(with_pitch, with_helper)
        # Imported shared modules count, whatever their name (the fake runner imports qc.store).
        store_copy = self.root / "scripts/qc/store.py"
        store_copy.write_text(store_copy.read_text() + "\n# changed\n")
        self.assertNotEqual(runtime.runner_identity(self.layout, model_entry()), with_pitch)
        sources = {path.name for path in runtime.runner_sources(self.layout, model_entry())}
        self.assertEqual(sources, {"_kit.py", "fake.py", "pitch.py", "store.py"})

    def test_variant_models_key_results_by_text_language_and_reference(self):
        aligner = model_entry(id="align.fixture", kind="align")
        weights = self.layout.model_dir("align.fixture") / "weights/model.bin"
        weights.parent.mkdir(parents=True)
        weights.write_bytes(PAYLOAD)
        report = self.run_model(aligner)
        self.assertEqual(report.ran, 3)
        take = self.takes[0]
        digest = store.audio_sha256(take["audio"])
        key = store.variant_key(take["text"], take["language"], None)
        self.assertTrue(store.result_path(self.layout, "align.fixture", digest, key).is_file())
        changed = [dict(take, text="another script")] + self.takes[1:]
        rerun = self.run_model(aligner, changed)
        self.assertEqual((rerun.ran, rerun.cached), (1, 2))

    def test_unsupported_languages_are_skipped(self):
        report = self.run_model(model_entry(languages=["french", "english"]))
        self.assertEqual((report.ran, report.skipped), (2, 1))

    def test_missing_results_and_failures_are_reported(self):
        report = self.run_model(options={"skipToken": self.takes[1]["token"], "exitCode": 1})
        self.assertEqual(report.exit_code, 1)
        self.assertEqual(report.failed, [self.takes[1]["token"]])
        self.assertEqual(report.results[self.takes[1]["token"]], {"error": "no-result"})
        self.assertEqual(len(list(self.layout.jobs.glob("*.json"))), 1)  # kept for debugging

    def test_timeout_kills_the_runner(self):
        report = self.run_model(options={"sleep": 30}, timeout=1.5)
        self.assertTrue(report.timed_out)
        self.assertLess(report.seconds, 15)
        self.assertEqual({result["error"] for result in report.results.values()}, {"timeout"})

    def test_refuses_while_another_run_holds_the_lock(self):
        self.layout.cache.mkdir(parents=True, exist_ok=True)
        with open(self.layout.run_lock, "a+") as other:
            fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(runtime.LockBusy):
                self.run_model()
        self.assertEqual(self.run_model().ran, 3)

    def test_missing_model_files_or_runtime_refuse_to_start(self):
        shutil.rmtree(self.layout.models)
        with self.assertRaisesRegex(runtime.RunnerError, "models fetch"):
            self.run_model()
        with self.assertRaisesRegex(runtime.RunnerError, "runtimes setup"):
            runtime.run_runner(model_entry(), self.takes, layout=self.layout, echo=self.lines.append)

    def test_llamacpp_runners_use_the_onnx_venv(self):
        self.assertEqual(runtime.runtime_python(self.layout, "llamacpp"),
                         self.layout.runtimes / "onnx/bin/python3")


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.layout = Layout(Path(self.directory.name))

    def tearDown(self):
        self.directory.cleanup()

    def test_round_trip_and_staleness(self):
        digest = "a" * 64
        output = self.layout.results_dir("m")
        store.write_result(output, model="m", runner_sha="r1", audio_sha=digest, variant=None,
                           duration_seconds=2.0, outputs={"mos": 3.9})
        self.assertEqual(store.read_result(self.layout, "m", digest, None, "r1")["outputs"], {"mos": 3.9})
        self.assertIsNone(store.read_result(self.layout, "m", digest, None, "r2"))
        self.assertIsNone(store.read_result(self.layout, "m", digest, "abcd", "r1"))
        self.assertIsNone(store.read_result(self.layout, "other", digest, None, "r1"))
        self.assertEqual([path.name for path in output.iterdir()], [f"{digest}.json"])  # no temp files left

    def test_error_results_and_variants(self):
        digest = "b" * 64
        key = store.variant_key("bonjour", "french", None)
        self.assertEqual(len(key), 16)
        self.assertNotEqual(key, store.variant_key("bonjour", "english", None))
        store.write_result(self.layout.results_dir("m"), model="m", runner_sha="r", audio_sha=digest,
                           variant=key, duration_seconds=None, error="decode-failed")
        self.assertEqual(store.read_result(self.layout, "m", digest, key, "r")["error"], "decode-failed")
        with self.assertRaises(ValueError):
            store.write_result(self.layout.results_dir("m"), model="m", runner_sha="r", audio_sha=digest,
                               variant=None, duration_seconds=None)

    def test_audio_digest_is_the_file_bytes(self):
        path = Path(self.directory.name) / "x.wav"
        path.write_bytes(b"RIFF....")
        self.assertEqual(store.audio_sha256(path), hashlib.sha256(b"RIFF....").hexdigest())

    def test_take_variants_follow_the_model_kind(self):
        take = {"text": "t", "language": "french", "referenceSHA256": None}
        self.assertIsNone(store.take_variant({"kind": "asr"}, take))
        self.assertEqual(store.take_variant({"kind": "align"}, take), store.variant_key("t", "french", None))
        self.assertIsNone(store.take_variant({"kind": "align", "variant": False}, take))


def write_qc_takes_run(root: Path) -> Path:
    """A miniature qc-takes run: two generated takes (one clone) and one rejected take."""

    run = root / "qc-takes-fixture"
    (run / "wav").mkdir(parents=True)
    (run / "references").mkdir()
    (run / "batches").mkdir()
    (run / "wav/fr-0101--dylan.wav").write_bytes(b"dylan")
    (run / "wav/fr-0101--clone-refabc.wav").write_bytes(b"clone")
    (run / "references/refabc.wav").write_bytes(b"reference")
    takes = [
        {"takeID": "fr-0101--dylan", "status": "generated", "wavPath": "wav/fr-0101--dylan.wav",
         "wavSHA256": hashlib.sha256(b"dylan").hexdigest(), "language": "french", "text": "Bonjour à tous.",
         "mode": "custom", "voice": {"id": "dylan", "kind": "builtin"}, "cell": "cross-lingual",
         "reference": None, "finishReason": "eos", "seed": 7, "family": "fr-0101:dylan:7",
         "scriptID": "fr-0101", "batchID": "calibration-french-dylan"},
        {"takeID": "fr-0101--clone-refabc", "status": "generated", "wavPath": "wav/fr-0101--clone-refabc.wav",
         "wavSHA256": None, "language": "french", "text": "Bonjour à tous.", "mode": "clone",
         "voice": {"kind": "clone", "referenceKey": "refabc"}, "cell": "clone",
         "reference": {"wavPath": "references/refabc.wav", "wavSHA256": hashlib.sha256(b"reference").hexdigest()},
         "finishReason": "eos", "seed": 9, "scriptID": "fr-0101", "batchID": "calibration-clone-french-clone-refabc"},
        {"takeID": "fr-0102--design-calm", "status": "rejected", "wavPath": None, "wavSHA256": None,
         "language": "french", "text": "Salut.", "mode": "design",
         "voice": {"kind": "design", "briefID": "calm"}, "cell": "standard", "reference": None,
         "finishReason": None, "seed": 3, "scriptID": "fr-0102", "batchID": "calibration-french-design-calm"},
    ]
    (run / "takes-manifest.json").write_text(json.dumps({"runID": "mac-qc-takes-fixture", "takes": takes}))
    separator = "\x1f"
    rows = [
        separator.join(["calibration-french-dylan", "custom", "speed", "expressive", "7", "dylan", "", "1",
                        "lines.txt", "", "", ""]),
        separator.join(["calibration-clone-french-clone-refabc", "clone", "speed", "expressive", "9", "", "", "1",
                        "lines.txt", "references/refabc.wav", "Le transcript de la référence.", ""]),
    ]
    (run / "batches/index.tsv").write_text("\n".join(rows) + "\n")
    return run


class TakesTests(unittest.TestCase):
    def test_takes_from_a_qc_takes_run(self):
        with tempfile.TemporaryDirectory() as directory:
            run = write_qc_takes_run(Path(directory))
            manifest = store.takes_from_qc_takes_run(run)
            self.assertEqual(manifest["schema"], "vocello.qc.takes/1")
            self.assertEqual(manifest["source"], "mac-qc-takes-fixture")
            self.assertEqual([take["takeID"] for take in manifest["takes"]],
                             ["fr-0101--dylan", "fr-0101--clone-refabc"])
            dylan, clone = manifest["takes"]
            self.assertEqual(dylan["token"],
                             hashlib.sha256(b"mac-qc-takes-fixture" + b"fr-0101--dylan").hexdigest()[:16])
            self.assertEqual(dylan["voice"], "dylan")
            self.assertEqual(dylan["family"], "fr-0101")
            self.assertEqual((dylan["mode"], dylan["cell"], dylan["finishReason"], dylan["seed"]),
                             ("custom", "cross-lingual", "eos", 7))
            self.assertIsNone(dylan["reference"])
            self.assertEqual(clone["audioSHA256"], hashlib.sha256(b"clone").hexdigest())
            self.assertEqual(Path(clone["reference"]), run.resolve() / "references/refabc.wav")
            self.assertEqual(clone["referenceText"], "Le transcript de la référence.")
            self.assertEqual(clone["voice"], "clone-refabc")
            self.assertEqual(store.load_takes(run)["takes"], manifest["takes"])


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.layout = Layout(self.root)
        (self.layout.runtime_requirements).mkdir(parents=True)

    def tearDown(self):
        self.directory.cleanup()

    def test_requirements_must_be_pinned(self):
        lines = runtime.parse_requirements("# header\nnumpy==2.4.6\nonnxruntime==1.23.0  # inline\n"
                                           "--extra-index-url https://download.example/whl\n"
                                           f"utmosv2 @ git+https://github.com/example/utmosv2@{REVISION}\n")
        self.assertEqual(runtime.pinned_versions(lines), {"numpy": "2.4.6", "onnxruntime": "1.23.0"})
        for bad in ("numpy\n", "numpy>=2\n", "-e .\n", "--trusted-host example.com\n",
                    "utmosv2 @ git+https://github.com/example/utmosv2@main\n"):
            with self.subTest(bad), self.assertRaises(runtime.RuntimeSetupError):
                runtime.parse_requirements(bad)

    def test_base_python_copies_the_pinned_interpreter_once(self):
        legacy = self.root / runtime.LEGACY_INTERPRETER
        (legacy / "python/bin").mkdir(parents=True)
        (legacy / "python/bin/python3").write_text("#!/bin/sh\n")
        (legacy / "receipt.json").write_text(json.dumps({"id": "cpython-3.14.4+20260414"}))
        executable, identity = runtime.find_base_python(self.layout)
        self.assertEqual(executable, self.layout.runtimes / "python/python/bin/python3")
        self.assertEqual(identity, "cpython-3.14.4+20260414")
        shutil.rmtree(legacy)
        self.assertEqual(runtime.find_base_python(self.layout), (executable, identity))

    def test_base_python_falls_back_to_the_current_interpreter(self):
        executable, identity = runtime.find_base_python(self.layout)
        self.assertEqual(executable, Path(sys.executable))
        self.assertTrue(identity.startswith("system-python-"))

    def test_setup_and_verify_with_a_stubbed_pip(self):
        requirements = self.layout.runtime_requirements / "onnx.txt"
        requirements.write_text("# onnx\nnumpy==2.4.6\n")
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command[1:3] == ["-m", "venv"]:
                (Path(command[3]) / "bin").mkdir(parents=True)
                (Path(command[3]) / "bin/python3").write_text("")
            if "list" in command:
                return subprocess.CompletedProcess(command, 0, json.dumps([{"name": "NumPy", "version": "2.4.6"}]), "")
            return subprocess.CompletedProcess(command, 0, "", "")

        receipt = runtime.setup_runtime(self.layout, "onnx", run=fake_run, log=lambda message: None)
        self.assertEqual(receipt["requirementsSHA256"], store.sha256_text(requirements.read_text()))
        self.assertIn("-r", calls[-1])
        self.assertEqual(runtime.verify_runtime(self.layout, "onnx", run=fake_run), [])
        requirements.write_text("# onnx\nnumpy==2.4.7\n")
        problems = runtime.verify_runtime(self.layout, "onnx", run=fake_run)
        self.assertTrue(any("requirements changed" in problem for problem in problems))
        self.assertTrue(any("pinned 2.4.7" in problem for problem in problems))

    def test_llamacpp_release_tarball_unpacks_into_its_runtime(self):
        archive = make_tar({"build/": None, "build/bin/": None, "build/bin/llama-server": b"#!/bin/sh\n",
                            "build/bin/libllama.0.dylib": b"lib", "build/bin/libllama.dylib": ("symlink", "libllama.0.dylib")})
        name = "llama-b1-bin-macos-arm64.tar.gz"
        entry = {"id": "runtime.llamacpp", "kind": "runtime", "runner": None, "runtime": "llamacpp",
                 "source": {"host": "github-release", "files": {name: {
                     "url": f"https://github.com/example/llama/releases/download/b1/{name}",
                     "sha256": hashlib.sha256(archive).hexdigest(), "bytes": len(archive)}}},
                 "license": "MIT", "version": 1}
        self.layout.config.mkdir(parents=True, exist_ok=True)
        self.layout.registry.write_text(json.dumps(registry(entry)))
        with self.assertRaisesRegex(runtime.RuntimeSetupError, "models fetch"):
            runtime.setup_runtime(self.layout, "llamacpp", log=lambda message: None)
        (self.layout.model_dir("runtime.llamacpp")).mkdir(parents=True)
        (self.layout.model_dir("runtime.llamacpp") / name).write_bytes(archive)
        runtime.setup_runtime(self.layout, "llamacpp", log=lambda message: None)
        server = self.layout.runtimes / "llamacpp/build/bin/llama-server"
        self.assertTrue(os.access(server, os.X_OK))
        self.assertEqual(os.readlink(self.layout.runtimes / "llamacpp/build/bin/libllama.dylib"), "libllama.0.dylib")
        self.assertEqual(runtime.verify_runtime(self.layout, "llamacpp"),
                         ["llamacpp: its runner needs the onnx venv (run qc.py runtimes setup --runtime onnx)"])

    def test_setup_refuses_an_empty_requirements_file(self):
        (self.layout.runtime_requirements / "torch.txt").write_text("# header only\n")
        with self.assertRaisesRegex(runtime.RuntimeSetupError, "pins no package"):
            runtime.setup_runtime(self.layout, "torch", run=mock.Mock(), log=lambda message: None)


class RepositoryTests(unittest.TestCase):
    def test_protocol_matches_the_contract(self):
        protocol = json.loads((ROOT / "config/qc/protocol.json").read_text())
        self.assertEqual([item["id"] for item in protocol["classes"]], [
            "stutter", "mispronunciation", "wrong-language", "cutoff", "pause", "pitch", "tonal-collapse",
            "voice-change", "artifact", "unnatural", "other"])
        self.assertEqual(protocol["severities"], ["none", "mild", "moderate", "severe"])
        self.assertEqual(protocol["verdicts"], ["acceptable", "objectionable", "uncertain"])
        self.assertEqual({item["id"] for item in protocol["classes"] if item["linguistic"]},
                         {"stutter", "mispronunciation", "wrong-language"})

    def test_checked_in_registry_is_valid(self):
        models.load_registry(Layout(ROOT))

    def test_runtime_requirement_files_parse(self):
        for name in runtime.VENV_RUNTIMES:
            with self.subTest(name):
                runtime.parse_requirements((ROOT / f"config/qc/runtimes/{name}.txt").read_text())

    def test_private_store_is_git_ignored(self):
        if shutil.which("git") is None or not (ROOT / ".git").exists():
            self.skipTest("not a git checkout")
        for path in ("build/private/qc/labels/batch.jsonl", "build/cache/qc/results/m/x.json"):
            result = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", path], check=False)
            self.assertEqual(result.returncode, 0, path)

    def test_cli_listing_and_gate_without_a_run(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / "qc.py"), "--help"], capture_output=True, text=True,
                                check=False)
        self.assertEqual(result.returncode, 0)
        for command in ("models", "runtimes", "label", "run", "gate", "queue", "fit", "eval"):
            self.assertIn(command, result.stdout)
        with tempfile.TemporaryDirectory() as directory:
            layout = Layout(Path(directory))
            layout.config.mkdir(parents=True)
            layout.registry.write_text(json.dumps(registry(model_entry())))
            spec = importlib.util.spec_from_file_location("qc_cli", SCRIPTS / "qc.py")
            cli = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cli)
            with mock.patch("sys.stdout") as stdout:
                self.assertEqual(cli.main(["models", "list", "--json"], layout=layout), 0)
            printed = "".join(call.args[0] for call in stdout.write.call_args_list)
            self.assertEqual(json.loads(printed)[0]["fetched"], False)
            with mock.patch("sys.stdout"):
                self.assertEqual(cli.main(["models", "verify"], layout=layout), 1)
            with mock.patch("sys.stderr"):
                self.assertEqual(cli.main(["gate", "--lane", "lang-bench"], layout=layout), 2)


if __name__ == "__main__":
    unittest.main()
