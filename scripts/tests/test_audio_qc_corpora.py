#!/usr/bin/env python3
"""AQ-07 corpora: the pinned registry, its fetch, receipts and extraction, and the FLEURS reserve cohorts.

No network and no corpus data. The committed registry is validated as the
contract gate validates it; everything else runs on synthetic sources built in
a temporary directory (WAVs, a zip, a tar.gz, pins of their own bytes) served
through a fake opener. Parquet extraction runs the worker's row logic through a
fake worker (the system interpreter has no pyarrow).
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.request
import wave
import zipfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_corpora as corpora  # noqa: E402
import audio_qc_corpora_worker as worker  # noqa: E402
import audio_qc_n1_corpus as n1  # noqa: E402
import audio_qc_n2_resynthesis as n2  # noqa: E402
from lib import corpus_clips as clips  # noqa: E402

REVISION = "0123456789abcdef0123456789abcdef01234567"
LICENSE = {"id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/",
           "source": "https://example.org/corpus"}
NO_LABELS = {label: None for label in corpora.LABELS}


def quiet(function, *args, **kwargs):
    with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
        return function(*args, **kwargs)


def tone(samples: int, rate: int, frequency: float = 220.0, amplitude: float = 0.3) -> np.ndarray:
    time = np.arange(samples) / rate
    return amplitude * np.sin(2.0 * np.pi * frequency * time)


def wav(values: np.ndarray, rate: int, *, width: int = 2, floating: bool = False, extensible: bool = False,
        declared: int | None = None) -> bytes:
    """A handmade RIFF/WAVE file: integer PCM of any width, IEEE float, plain or extensible."""
    frames = values if values.ndim == 2 else values[:, None]
    channels = frames.shape[1]
    if floating:
        payload, tag = frames.astype("<f4" if width == 4 else "<f8").tobytes(), 3
    else:
        full = {1: 127, 2: 32767, 3: 8388607, 4: 2147483647}[width]
        ints = np.clip(np.rint(frames * full), -full, full).astype(np.int64)
        if width == 1:
            payload = (ints + 128).astype(np.uint8).tobytes()
        elif width == 3:
            payload = ints.astype("<i4").view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
        else:
            payload = ints.astype("<i2" if width == 2 else "<i4").tobytes()
        tag = 1
    align = channels * width
    if extensible:
        fmt = (struct.pack("<HHIIHH", 0xFFFE, channels, rate, rate * align, align, 8 * width)
               + struct.pack("<HHI", 22, 8 * width, 0) + struct.pack("<H", tag) + bytes(14))
    else:
        fmt = struct.pack("<HHIIHH", tag, channels, rate, rate * align, align, 8 * width)
    size = len(payload) if declared is None else declared
    body = b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", size) + payload
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body


def pcm16(samples: int, rate: int, frequency: float = 220.0) -> bytes:
    return wav(tone(samples, rate, frequency), rate)


def read_pcm16(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as reader:
        assert reader.getnchannels() == 1 and reader.getsampwidth() == 2
        return np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2"), reader.getframerate()


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, data in members.items():
            bundle.writestr(name, data)
    return buffer.getvalue()


def tar_gz(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            bundle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def sha256_pin(path: str, data: bytes, **extra) -> dict:
    return {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), **extra}


def entry(files: list[dict], extract: dict, **overrides) -> dict:
    value = {
        "title": "Synthetic corpus", "group": "speaker", "alsoIn": [], "host": "huggingface.co",
        "repository": "owner/corpus", "revision": REVISION, "languages": ["english"], "license": LICENSE,
        "attribution": "A synthetic corpus built by the test, attributed to nobody in particular.",
        "caveats": [], "labels": dict(NO_LABELS), "files": files,
        "extract": {"estimatedBytes": 1, "estimateBasis": "test", "outputRate": 16000, **extract},
    }
    value.update(overrides)
    value["totals"] = {"files": len(files), "bytes": sum(file["size"] for file in files)}
    return value


def registry_of(**sources) -> dict:
    return {"sources": sources}


def url_of(source_entry: dict, path: str, kind: str = "sha256") -> str:
    pin = corpora.Pin(path, 1, kind, "0" * {"sha256": 64, "md5": 32, "gitBlobSHA1": 40}[kind])
    return corpora.file_url(source_entry, pin)


class FakeResponse:
    def __init__(self, status: int, payload: bytes, start: int, total: int) -> None:
        self.status = status
        self.headers = {"Content-Range": f"bytes {start}-{total - 1}/{total}"} if status == 206 else {}
        self._payload = payload
        self._position = 0

    def read(self, size: int = -1) -> bytes:
        end = len(self._payload) if size < 0 else self._position + size
        block = self._payload[self._position:end]
        self._position += len(block)
        return block

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_details) -> None:
        return None


class FakeHost:
    """Serves bytes by URL; honours a range request unless told to ignore it."""

    def __init__(self, files: dict[str, bytes], *, ignore_range: bool = False) -> None:
        self.files = files
        self.ignore_range = ignore_range
        self.requests: list[tuple[str, str | None]] = []
        self.offline = False

    def __call__(self, request, timeout):
        self.requests.append((request.full_url, request.get_header("Range")))
        if self.offline:
            raise AssertionError("the network was used")
        if request.full_url not in self.files:
            raise urllib.error.HTTPError(request.full_url, 404, "fixture", {}, None)
        body = self.files[request.full_url]
        header = request.get_header("Range")
        if header and not self.ignore_range:
            start = int(header.split("=")[1].rstrip("-"))
            return FakeResponse(206, body[start:], start, len(body))
        return FakeResponse(200, body, 0, len(body))


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)
        self.root = self.tmp / "cache"
        margin = mock.patch.object(corpora, "FREE_SPACE_MARGIN_BYTES", 0)
        margin.start()
        self.addCleanup(margin.stop)
        n1_margin = mock.patch.object(n1, "FREE_SPACE_MARGIN_BYTES", 0)
        n1_margin.start()
        self.addCleanup(n1_margin.stop)

    def place(self, registry: dict, source: str, files: dict[str, bytes]) -> Path:
        directory = corpora.source_directory(registry, source, self.root)
        for path, data in files.items():
            (directory / path).parent.mkdir(parents=True, exist_ok=True)
            (directory / path).write_bytes(data)
        return directory


# --------------------------------------------------------------------------- #
# The committed registry
# --------------------------------------------------------------------------- #

class CommittedRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = corpora.load_registry()
        self.n1_sources = n1.load_sources()

    def issues(self, registry: dict) -> list[str]:
        return corpora.registry_issues(registry, n1_sources=self.n1_sources)

    def test_the_committed_registry_validates_in_its_canonical_encoding(self) -> None:
        self.assertEqual(self.issues(self.registry), [])
        self.assertEqual(corpora.encode_registry(self.registry), corpora.REGISTRY_PATH.read_bytes())
        self.assertEqual(quiet(corpora.main, ["validate"]), 0)
        self.assertEqual((self.registry["totals"]["files"], self.registry["totals"]["bytes"]),
                         (9031, 28_962_323_872))
        self.assertEqual(set(self.registry["sources"]), {
            "fleurs-train", "crema-d", "libritts-r", "mls", "zeroth-korean", "aishell3-subset", "emozionalmente",
            "thorsten-emotional", "emodb", "jvnv", "emouerj", "resd", "speechocean762"})
        self.assertEqual(self.registry["hosts"], list(corpora.ALLOWED_HOSTS))

    def test_the_lean_set_selects_every_group_and_shared_sources_join_the_emotion_group(self) -> None:
        self.assertEqual(len(corpora.select(self.registry, sets=["lean"])), 13)
        emotion = corpora.select(self.registry, groups=["emotion"])
        self.assertTrue({"crema-d", "emozionalmente", "thorsten-emotional", "jvnv"} <= set(emotion))
        self.assertEqual(corpora.select(self.registry, sources=["emodb"]), ["emodb"])
        with self.assertRaisesRegex(corpora.CorporaError, "unknown sources"):
            corpora.select(self.registry, sources=["common-voice"])

    def test_every_host_pins_the_digest_it_publishes(self) -> None:
        for source in self.registry["sources"]:
            entry = self.registry["sources"][source]
            kinds = {pin.kind for pin in corpora.source_pins(self.registry, source)}
            self.assertLessEqual(kinds, set(corpora.PIN_KINDS[corpora.host_kind(entry)]), source)
        broken = copy.deepcopy(self.registry)
        file = broken["sources"]["emodb"]["files"][0]
        file["sha256"] = "a" * 64
        del file["md5"]
        self.assertTrue(any("emodb" in issue and "pinned by sha256" in issue for issue in self.issues(broken)))
        broken = copy.deepcopy(self.registry)
        file = broken["sources"]["jvnv"]["files"][0]
        file["md5"] = "a" * 32
        del file["sha256"]
        self.assertTrue(any("jvnv" in issue and "pinned by md5" in issue for issue in self.issues(broken)))

    def test_a_host_outside_the_allow_list_is_refused(self) -> None:
        broken = copy.deepcopy(self.registry)
        broken["sources"]["crema-d"]["host"] = "raw.githubusercontent.com"
        self.assertTrue(any("crema-d: host is one of" in issue for issue in self.issues(broken)))
        broken = copy.deepcopy(self.registry)
        broken["hosts"].append("example.org")
        self.assertTrue(any("hosts must be exactly" in issue for issue in self.issues(broken)))

    def test_the_sidecar_pin_files_are_bound_by_their_digest_and_counts(self) -> None:
        broken = copy.deepcopy(self.registry)
        broken["sources"]["crema-d"]["pinFile"]["sha256"] = "0" * 64
        self.assertTrue(any("does not match its recorded SHA-256" in issue for issue in self.issues(broken)))
        broken = copy.deepcopy(self.registry)
        broken["sources"]["aishell3-subset"]["pinFile"]["files"] += 1
        self.assertTrue(any("pinFile records" in issue for issue in self.issues(broken)))
        pins = corpora.source_pins(self.registry, "crema-d")
        self.assertEqual((len(pins), sum(pin.size for pin in pins)), (7442, 605_899_936))
        subset = corpora.source_pins(self.registry, "aishell3-subset")
        self.assertEqual(sum(1 for pin in subset if pin.role == "audio"), 76 * 20)

    def test_labels_licenses_rates_and_totals_are_checked(self) -> None:
        for change, expected in (
                (lambda r: r["sources"]["jvnv"]["extract"].update(outputRate=22050), "outputRate"),
                (lambda r: r["sources"]["resd"]["labels"].pop("accent"), "labels names"),
                (lambda r: r["sources"]["mls"]["license"].update(url="http://example.org"), "license holds"),
                (lambda r: r["sources"]["emodb"]["totals"].update(bytes=1), "emodb: totals"),
                (lambda r: r["sources"]["jvnv"]["extract"]["maps"]["emotion"].update(anger="furious"),
                 "maps only to"),
                (lambda r: r["sources"]["crema-d"]["extract"].update(members="(?P<nope>x)"), "unknown groups"),
                (lambda r: r["sources"]["mls"]["files"][0].pop("language"), "names each audio file's language"),
                (lambda r: r["sources"]["libritts-r"].update(revision="main"), "full 40-character commit")):
            broken = copy.deepcopy(self.registry)
            change(broken)
            self.assertTrue(any(expected in issue for issue in self.issues(broken)), expected)

    def test_the_parquet_runtime_lock_is_bound_and_names_its_readers(self) -> None:
        broken = copy.deepcopy(self.registry)
        broken["parquetRuntime"]["lockSHA256"] = "0" * 64
        self.assertTrue(any("does not match its recorded SHA-256" in issue for issue in self.issues(broken)))
        broken = copy.deepcopy(self.registry)
        broken["parquetRuntime"]["packages"] = 5
        self.assertTrue(any("its lock pins 6" in issue for issue in self.issues(broken)))
        view = corpora.runtime_view(self.registry, {"sha256": "x"})
        spec = view["acquisition"]["runtimes"][corpora.RUNTIME_FAMILY]
        self.assertEqual(spec["lock"], "config/audio-qc-runtimes/corpora-parquet.txt")
        self.assertNotIn("family", spec)

    def test_the_fleurs_reserve_reads_the_n1_revision_and_pins(self) -> None:
        broken = copy.deepcopy(self.registry)
        broken["sources"]["fleurs-train"]["revision"] = "f" * 40
        self.assertTrue(any("N1 revision" in issue for issue in self.issues(broken)))
        pins = corpora.source_pins(self.registry, "fleurs-train")
        self.assertEqual(len(pins), 20)
        self.assertEqual(sum(pin.size for pin in pins), 15_576_912_602)

    def test_plan_reads_no_network_and_totals_the_lean_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            value = corpora.plan(self.registry, corpora.select(self.registry, sets=["lean"]), root=Path(directory),
                                 model_root=Path(directory), n1_sources=self.n1_sources)
        self.assertEqual(value["downloadBytes"], 28_962_323_872)
        self.assertEqual(value["missingBytes"], 28_962_323_872 + value["n1TSVBytes"])
        self.assertEqual(set(value["groups"]), set(corpora.GROUPS))
        self.assertGreater(value["extractTotalBytes"], 30e9)
        self.assertTrue(value["runtime"]["needed"])
        self.assertFalse(value["runtime"]["built"])


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #

class TransportTests(unittest.TestCase):
    def test_only_https_on_the_corpora_hosts_is_allowed(self) -> None:
        for url in ("https://huggingface.co/datasets/a/b/resolve/x/y", "https://cas-bridge.xethub.hf.co/x",
                    "https://us.aws.cdn.hf.co/x", "https://media.githubusercontent.com/media/a/b/c/d",
                    "https://zenodo.org/api/records/1/files/x/content"):
            self.assertTrue(corpora.allowed_url(url), url)
        for url in ("http://huggingface.co/x", "https://raw.githubusercontent.com/a/b/c/d",
                    "https://github.com/a/b", "https://example.org/x", "https://user:secret@zenodo.org/x",
                    "https://zenodo.org:8443/x", "https://zenodo.org.example.org/x", "ftp://zenodo.org/x"):
            self.assertFalse(corpora.allowed_url(url), url)

    def test_a_redirect_off_the_hosts_is_refused(self) -> None:
        handler = corpora.CorporaRedirectHandler()
        request = urllib.request.Request("https://zenodo.org/api/records/1/files/x/content")
        with self.assertRaisesRegex(corpora.CorporaError, "not an allowed corpora host"):
            handler.redirect_request(request, None, 302, "Found", {}, "https://bucket.s3.amazonaws.com/x")
        with self.assertRaisesRegex(corpora.CorporaError, "not an allowed corpora host"):
            corpora._open(urllib.request.Request("https://example.org/x"), 1.0)

    def test_each_host_kind_downloads_from_its_pinned_place(self) -> None:
        hub = entry([], {"format": "parquet"})
        lfs = entry([], {"format": "wav-files"}, host="media.githubusercontent.com")
        zen = entry([], {"format": "zip"}, host="zenodo.org", record="42", version="1.0")
        del zen["repository"], zen["revision"]
        self.assertEqual(url_of(hub, "data/a b.parquet"),
                         f"https://huggingface.co/datasets/owner/corpus/resolve/{REVISION}/data/a%20b.parquet")
        self.assertEqual(url_of(lfs, "AudioWAV/x.wav"),
                         f"https://media.githubusercontent.com/media/owner/corpus/{REVISION}/AudioWAV/x.wav")
        self.assertEqual(url_of(zen, "set.zip", "md5"), "https://zenodo.org/api/records/42/files/set.zip/content")


# --------------------------------------------------------------------------- #
# Fetch and receipts
# --------------------------------------------------------------------------- #

class FetchTests(Fixture):
    def setUp(self) -> None:
        super().setUp()
        self.blob = b"speaker\tgender\nA\tfemale\n"
        self.shard = bytes(range(256)) * 400
        self.archive = zip_bytes({"set/a.wav": pcm16(1600, 16000)})
        self.lfs_files = {f"AudioWAV/{index}.wav": pcm16(800 + index, 16000) for index in range(5)}
        hub = entry([sha256_pin("data/train.parquet", self.shard),
                     {"path": "meta.txt", "size": len(self.blob), "gitBlobSHA1": n1.git_blob_sha1(self.blob),
                      "role": "metadata"}], {"format": "parquet"})
        lfs = entry([sha256_pin(path, data) for path, data in self.lfs_files.items()], {"format": "wav-files"},
                    host="media.githubusercontent.com")
        zen = entry([{"path": "set.zip", "size": len(self.archive),
                      "md5": hashlib.md5(self.archive).hexdigest()}], {"format": "zip"}, host="zenodo.org",
                    record="42", version="1.0")
        del zen["repository"], zen["revision"]
        self.registry = registry_of(hub=hub, lfs=lfs, zen=zen)
        files = {url_of(hub, "data/train.parquet"): self.shard, url_of(hub, "meta.txt", "gitBlobSHA1"): self.blob,
                 url_of(zen, "set.zip", "md5"): self.archive}
        files.update({url_of(lfs, path): data for path, data in self.lfs_files.items()})
        self.host = FakeHost(files)

    def fetch(self, sources=("hub", "lfs", "zen"), host=None, **kwargs):
        return quiet(corpora.fetch, self.registry, list(sources), root=self.root, opener=host or self.host,
                     sleep=lambda _seconds: None, **kwargs)

    def test_fetch_verifies_every_pin_kind_and_a_second_run_uses_no_network(self) -> None:
        report = self.fetch(jobs=3)
        self.assertEqual([item["fetched"] for item in report], [2, 5, 1])
        zen = corpora.source_directory(self.registry, "zen", self.root)
        self.assertEqual((zen / "set.zip").read_bytes(), self.archive)
        receipt = json.loads((zen / corpora.RECEIPT_NAME).read_text())
        self.assertEqual(receipt["files"]["set.zip"]["sha256"], hashlib.sha256(self.archive).hexdigest())
        self.assertEqual(receipt["files"]["set.zip"]["md5"], hashlib.md5(self.archive).hexdigest())
        self.host.offline = True
        report = self.fetch()
        self.assertEqual([item["present"] for item in report], [2, 5, 1])
        self.assertEqual(quiet(corpora.verify, self.registry, ["hub", "lfs", "zen"], root=self.root)[0]["status"],
                         "FAIL")  # nothing is extracted yet

    def test_an_md5_pinned_file_is_bound_to_its_recorded_sha256_on_later_runs(self) -> None:
        self.fetch(sources=("zen",))
        zen = corpora.source_directory(self.registry, "zen", self.root)
        receipt_path = zen / corpora.RECEIPT_NAME
        receipt = json.loads(receipt_path.read_text())
        receipt["files"]["set.zip"]["sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(receipt))
        self.host.offline = True
        with self.assertRaisesRegex(corpora.CorporaError, "recorded on its first verified fetch"):
            self.fetch(sources=("zen",))
        results = quiet(corpora.verify, self.registry, ["zen"], root=self.root)
        self.assertTrue(any("first verified fetch" in problem for problem in results[0]["problems"]))

    def test_an_interrupted_download_resumes_or_restarts_where_the_host_ignores_ranges(self) -> None:
        hub = corpora.source_directory(self.registry, "hub", self.root)
        part = hub / corpora.PARTIAL_DIRECTORY / "data/train.parquet.part"
        part.parent.mkdir(parents=True)
        part.write_bytes(self.shard[:1000])
        self.fetch(sources=("hub",))
        self.assertIn((url_of(self.registry["sources"]["hub"], "data/train.parquet"), "bytes=1000-"),
                      self.host.requests)
        self.assertEqual((hub / "data/train.parquet").read_bytes(), self.shard)
        self.assertFalse((hub / corpora.PARTIAL_DIRECTORY).exists())
        zen = corpora.source_directory(self.registry, "zen", self.root)
        part = zen / corpora.PARTIAL_DIRECTORY / "set.zip.part"
        part.parent.mkdir(parents=True)
        part.write_bytes(self.archive[:100])
        ignoring = FakeHost(self.host.files, ignore_range=True)
        self.fetch(sources=("zen",), host=ignoring)
        self.assertEqual((zen / "set.zip").read_bytes(), self.archive)

    def test_a_mismatch_is_refused_and_nothing_unverified_is_kept(self) -> None:
        address = url_of(self.registry["sources"]["hub"], "meta.txt", "gitBlobSHA1")
        tampered = FakeHost({**self.host.files, address: self.blob.replace(b"female", b"f3male")})
        with self.assertRaisesRegex(corpora.CorporaError, "does not match its pinned size and digest"):
            self.fetch(sources=("hub",), host=tampered)
        hub = corpora.source_directory(self.registry, "hub", self.root)
        self.assertFalse((hub / "meta.txt").exists())
        self.assertFalse((hub / corpora.PARTIAL_DIRECTORY / "meta.txt.part").exists())
        (hub / "meta.txt").write_bytes(self.blob.upper())
        with self.assertRaisesRegex(corpora.CorporaError, "meta.txt holds|does not match its pinned"):
            self.fetch(sources=("hub",))
        self.assertEqual((hub / "meta.txt").read_bytes(), self.blob.upper())

    def test_the_whole_selection_must_fit_before_anything_is_fetched(self) -> None:
        with mock.patch.object(corpora, "FREE_SPACE_MARGIN_BYTES", 10 ** 18):
            with self.assertRaisesRegex(corpora.CorporaError, "plus a 2 GiB margin"):
                self.fetch()
        self.assertEqual(self.host.requests, [])

    def test_a_parallel_failure_keeps_the_verified_files_in_the_receipt(self) -> None:
        broken = dict(self.host.files)
        broken[url_of(self.registry["sources"]["lfs"], "AudioWAV/3.wav")] = \
            b"RIFF" + b"x" * (len(self.lfs_files["AudioWAV/3.wav"]) - 4)
        with self.assertRaises(corpora.CorporaError):
            self.fetch(sources=("lfs",), host=FakeHost(broken), jobs=2)
        lfs = corpora.source_directory(self.registry, "lfs", self.root)
        receipt = json.loads((lfs / corpora.RECEIPT_NAME).read_text())
        self.assertNotIn("AudioWAV/3.wav", receipt["files"])
        self.assertTrue(set(receipt["files"]) <= set(self.lfs_files))
        self.assertFalse((lfs / "AudioWAV/3.wav").exists())

    def test_plan_reports_present_and_missing_bytes_without_the_network(self) -> None:
        self.fetch(sources=("zen",))
        self.host.offline = True
        with mock.patch.object(corpora, "runtime_spec", return_value={
                "venv": "none", "lockSHA256": "x", "downloadBytes": 1, "packages": 1}):
            value = corpora.plan(self.registry, ["hub", "zen"], root=self.root, model_root=self.tmp)
        rows = {row["source"]: row for row in value["sources"]}
        self.assertEqual(rows["zen"]["missingBytes"], 0)
        self.assertEqual(rows["hub"]["missingBytes"], len(self.shard) + len(self.blob))
        self.assertTrue(value["runtime"]["needed"])


# --------------------------------------------------------------------------- #
# Audio conversion
# --------------------------------------------------------------------------- #

class ClipAudioTests(unittest.TestCase):
    def test_every_integer_and_float_width_decodes_to_the_same_mono_pcm16(self) -> None:
        values = tone(1600, 16000)
        reference, _ = clips.clip_from_wav(wav(values, 16000), output_rate=16000)
        expected = np.frombuffer(reference[44:], dtype="<i2").astype(int)
        for width, floating, extensible in ((1, False, False), (3, False, False), (4, False, True),
                                            (4, True, False), (8, True, True), (3, False, True)):
            data, info = clips.clip_from_wav(wav(values, 16000, width=width, floating=floating,
                                                 extensible=extensible), output_rate=16000)
            got = np.frombuffer(data[44:], dtype="<i2").astype(int)
            tolerance = 300 if width == 1 else 1
            self.assertLessEqual(int(np.max(np.abs(got - expected))), tolerance, (width, floating, extensible))
            self.assertFalse(info["resampled"])

    def test_a_mono_pcm16_clip_at_its_rate_keeps_its_samples_exactly(self) -> None:
        source = pcm16(4000, 24000)
        data, info = clips.clip_from_wav(source, output_rate=24000)
        self.assertEqual(data[44:], source[44:])
        self.assertEqual((info["samples"], info["sourceFormat"], info["clippedSamples"]), (4000, "wav-pcm16", 0))

    def test_channels_are_averaged_and_other_rates_resampled_with_clipping_counted(self) -> None:
        left, right = tone(4410, 44100, 300.0, 0.5), tone(4410, 44100, 300.0, 0.1)
        data, info = clips.clip_from_wav(wav(np.stack([left, right], axis=1), 44100, width=3), output_rate=24000)
        pcm = np.frombuffer(data[44:], dtype="<i2")
        self.assertEqual((info["sourceChannels"], info["sourceRate"], info["sampleRate"]), (2, 44100, 24000))
        self.assertTrue(info["resampled"])
        self.assertAlmostEqual(len(pcm), 2400, delta=1)
        self.assertAlmostEqual(float(np.max(np.abs(pcm))) / 32767, 0.3, delta=0.02)
        loud = wav(np.full(800, 1.5), 16000, width=4, floating=True)
        _data, info = clips.clip_from_wav(loud, output_rate=16000)
        self.assertEqual(info["clippedSamples"], 800)

    def test_a_streamed_wav_with_an_oversized_data_chunk_is_read_and_marked(self) -> None:
        data, info = clips.clip_from_wav(wav(tone(1000, 16000), 16000, declared=0xFFFFFFF0), output_rate=16000)
        self.assertTrue(info["dataChunkTruncated"])
        self.assertEqual(info["samples"], 1000)

    def test_unusable_audio_is_refused_with_a_reason(self) -> None:
        for data, reason in ((b"not a wav at all", "not a RIFF/WAVE"),
                             (wav(np.zeros(0), 16000), "no sample"),
                             (wav(np.array([0.1, np.nan]), 16000, width=4, floating=True), "non-finite")):
            with self.assertRaisesRegex(clips.CorpusAudioError, reason):
                clips.clip_from_wav(data, output_rate=16000)
        with self.assertRaisesRegex(clips.CorpusAudioError, "output rate"):
            clips.clip_from_wav(pcm16(100, 16000), output_rate=22050)

    def test_labels_and_ids_are_normalized_never_guessed(self) -> None:
        self.assertEqual(clips.clip_id("mls", "de", "10087 10388/000.1"), "mls-de-10087_10388_000.1")
        self.assertEqual([clips.gender(value) for value in ("M", "female", "w", "other", None)],
                         ["male", "female", "female", None, None])
        self.assertEqual(clips.emotion("ANG", {"ANG": "angry"}), ("ANG", "angry"))
        self.assertEqual(clips.emotion("drunk", {"ANG": "angry"}), ("drunk", None))


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #

class ExtractTests(Fixture):
    def extract(self, registry: dict, source: str, **kwargs) -> dict:
        return quiet(corpora.extract_source, registry, source, root=self.root, **kwargs)

    def manifest(self, registry: dict, source: str) -> dict:
        directory = corpora.source_directory(registry, source, self.root) / corpora.EXTRACTED_DIRECTORY
        return json.loads((directory / corpora.MANIFEST_NAME).read_text())

    def zip_source(self, files: dict[str, bytes], **extract) -> dict:
        archive = zip_bytes(files)
        spec = {"format": "zip", "outputRate": 24000, "ignore": ["^__MACOSX/", "(^|/)\\._"],
                "members": ("^emoUERJ/(?P<id>(?P<speaker>(?P<gender>[mw])[0-9]{2})(?P<emotion>[ahns])[0-9]{2})"
                            "\\.wav$"),
                "maps": {"emotion": {"a": "angry", "h": "happy", "n": "neutral", "s": "sad"}}, **extract}
        value = entry([{"path": "set.zip", "size": len(archive), "md5": hashlib.md5(archive).hexdigest()}], spec,
                      host="zenodo.org", record="7", version="1", languages=["portuguese"])
        del value["repository"], value["revision"]
        registry = registry_of(emo=value)
        self.place(registry, "emo", {"set.zip": archive})
        return registry

    def test_a_zip_is_decoded_labelled_resampled_and_deduplicated(self) -> None:
        stereo = wav(np.stack([tone(4800, 48000), tone(4800, 48000, 330.0)], axis=1), 48000, width=3)
        same = pcm16(2400, 24000, 180.0)
        registry = self.zip_source({
            "emoUERJ/m01a01.wav": stereo, "emoUERJ/w02h03.wav": same, "emoUERJ/w02h04.wav": same,
            "emoUERJ/m01s02.wav": b"RIFF broken", "emoUERJ/README.txt": b"readme",
            "__MACOSX/emoUERJ/._m01a01.wav": b"apple double",
        })
        report = self.extract(registry, "emo")
        self.assertEqual(report["status"], "extracted")
        manifest = self.manifest(registry, "emo")
        self.assertEqual(corpora.manifest_issues(manifest), [])
        clip = {record["sourceID"]: record for record in manifest["clips"]}
        self.assertEqual(set(clip), {"m01a01", "w02h03"})
        self.assertEqual((clip["m01a01"]["speaker"], clip["m01a01"]["gender"], clip["m01a01"]["emotion"],
                          clip["m01a01"]["emotionCanonical"], clip["m01a01"]["language"]),
                         ("m01", "male", "a", "angry", "portuguese"))
        self.assertEqual((clip["w02h03"]["gender"], clip["w02h03"]["emotionCanonical"]), ("female", "happy"))
        self.assertEqual((clip["m01a01"]["source"]["sampleRate"], clip["m01a01"]["sampleRate"]), (48000, 24000))
        self.assertTrue(clip["m01a01"]["resampled"])
        self.assertEqual([item["origin"] for item in clip["w02h03"]["duplicates"]], ["emoUERJ/w02h04.wav"])
        self.assertEqual([item["origin"] for item in manifest["skipped"]], ["emoUERJ/m01s02.wav"])
        self.assertEqual(manifest["members"], {"otherMembers": 1, "ignored": 1})
        directory = corpora.source_directory(registry, "emo", self.root) / corpora.EXTRACTED_DIRECTORY
        pcm, rate = read_pcm16(directory / clip["m01a01"]["wavPath"])
        self.assertEqual((rate, len(pcm)), (24000, 2400))
        self.assertEqual(self.extract(registry, "emo")["status"], "present")
        (directory / clip["w02h03"]["wavPath"]).write_bytes(pcm16(10, 24000))
        self.assertTrue(corpora.extraction_problems(directory))
        self.assertEqual(self.extract(registry, "emo")["status"], "extracted")

    def test_metadata_tables_join_speaker_text_emotion_and_gender(self) -> None:
        samples = "file_name,actor,sentence,emotion_expressed\n111.wav,ana,Una frase.,joy\n222.wav,bob,Altra.,drunk\n"
        users = "username,gender,age\nana,female,30\nbob,male,40\n"
        registry = self.zip_source(
            {"emozionalmente/audio/111.wav": pcm16(1600, 16000), "emozionalmente/audio/222.wav": pcm16(1700, 16000),
             "emozionalmente/audio/333.wav": pcm16(1800, 16000),
             "emozionalmente/metadata/samples.csv": samples.encode(),
             "emozionalmente/metadata/users.csv": users.encode()},
            outputRate=16000, members="^emozionalmente/audio/(?P<id>[0-9]+)\\.wav$",
            metadata=[{"member": "emozionalmente/metadata/samples.csv", "format": "csv", "keyColumn": "file_name",
                       "keyNormalize": "stem", "joinOn": "sourceID",
                       "fields": {"speaker": "actor", "text": "sentence", "emotion": "emotion_expressed"}},
                      {"member": "emozionalmente/metadata/users.csv", "format": "csv", "keyColumn": "username",
                       "joinOn": "speaker", "fields": {"gender": "gender"}}],
            maps={"emotion": {"joy": "happy"}})
        self.extract(registry, "emo")
        manifest = self.manifest(registry, "emo")
        clip = {record["sourceID"]: record for record in manifest["clips"]}
        self.assertEqual((clip["111"]["speaker"], clip["111"]["gender"], clip["111"]["text"],
                          clip["111"]["emotion"], clip["111"]["emotionCanonical"]),
                         ("ana", "female", "Una frase.", "joy", "happy"))
        self.assertEqual((clip["222"]["emotion"], clip["222"]["emotionCanonical"]), ("drunk", None))
        self.assertIsNone(clip["333"]["speaker"])
        self.assertEqual(manifest["metadata"]["emozionalmente/metadata/samples.csv"], {"rows": 2, "unjoinedClips": 1})
        bad = self.zip_source({"emozionalmente/audio/111.wav": pcm16(1600, 16000),
                               "emozionalmente/metadata/samples.csv": b"name,actor\n"},
                              outputRate=16000, members="^emozionalmente/audio/(?P<id>[0-9]+)\\.wav$",
                              metadata=[{"member": "emozionalmente/metadata/samples.csv", "format": "csv",
                                         "keyColumn": "file_name", "joinOn": "sourceID",
                                         "fields": {"speaker": "actor"}}])
        with self.assertRaisesRegex(corpora.CorporaError, "has no column file_name"):
            self.extract(bad, "emo")

    def test_an_optional_table_that_is_missing_costs_its_labels_not_the_corpus(self) -> None:
        table = {"member": "emoUERJ/speakers.csv", "format": "csv", "keyColumn": "speaker", "joinOn": "speaker",
                 "fields": {"gender": "gender"}}
        registry = self.zip_source({"emoUERJ/m01a01.wav": pcm16(1600, 24000)},
                                   metadata=[{**table, "optional": True}])
        self.extract(registry, "emo")
        manifest = self.manifest(registry, "emo")
        self.assertEqual(manifest["metadata"]["emoUERJ/speakers.csv"]["unjoinedClips"], 1)
        self.assertIn("is missing", manifest["metadata"]["emoUERJ/speakers.csv"]["problem"])
        required = self.zip_source({"emoUERJ/m01a01.wav": pcm16(1600, 24000)}, metadata=[table])
        with self.assertRaisesRegex(corpora.CorporaError, "emoUERJ/speakers.csv is missing"):
            self.extract(required, "emo")

    def test_a_tar_with_its_metadata_last_labels_every_style_and_the_constant_speaker(self) -> None:
        first, second = "0" * 31 + "a", "0" * 31 + "b"
        archive = tar_gz({
            f"thorsten-emotional_v02/amused/{first}.wav": pcm16(2205, 22050),
            f"thorsten-emotional_v02/drunk/{first}.wav": pcm16(2205, 22050, 300.0),
            f"thorsten-emotional_v02/neutral/{second}.wav": pcm16(2205, 22050, 400.0),
            "thorsten-emotional_v02/thorsten-emotional-metadata.csv": f"{first}|Erster Satz.\n{second}|Zweiter.\n"
                                                                      .encode(),
        })
        spec = {"format": "tar.gz", "outputRate": 24000, "idTemplate": "{emotion}-{textID}",
                "members": "^thorsten-emotional_v02/(?P<emotion>[a-z]+)/(?P<textID>[0-9a-f]{32})\\.wav$",
                "metadata": [{"member": "thorsten-emotional_v02/thorsten-emotional-metadata.csv", "format": "pipe",
                              "keyColumn": 0, "joinOn": "textID", "fields": {"text": 1}}],
                "maps": {"emotion": {"amused": "happy", "neutral": "neutral"}},
                "constants": {"speaker": "thorsten", "gender": "male"}}
        value = entry([{"path": "t.tgz", "size": len(archive), "md5": hashlib.md5(archive).hexdigest()}], spec,
                      host="zenodo.org", record="5", version="2.0", languages=["german"])
        del value["repository"], value["revision"]
        registry = registry_of(thorsten=value)
        self.place(registry, "thorsten", {"t.tgz": archive})
        self.extract(registry, "thorsten")
        clip = {record["clipID"]: record for record in self.manifest(registry, "thorsten")["clips"]}
        self.assertEqual(set(clip), {f"thorsten-amused-{first}", f"thorsten-drunk-{first}",
                                     f"thorsten-neutral-{second}"})
        amused = clip[f"thorsten-amused-{first}"]
        self.assertEqual((amused["speaker"], amused["gender"], amused["text"], amused["emotionCanonical"],
                          amused["sampleRate"], amused["samples"]),
                         ("thorsten", "male", "Erster Satz.", "happy", 24000, 2400))
        self.assertIsNone(clip[f"thorsten-drunk-{first}"]["emotionCanonical"])

    def test_pinned_wav_files_are_checked_one_by_one_and_labelled_from_their_names(self) -> None:
        files = {"AudioWAV/1001_DFA_ANG_XX.wav": pcm16(1600, 16000),
                 "AudioWAV/1002_IEO_HAP_HI.wav": pcm16(1700, 16000, 330.0)}
        spec = {"format": "wav-files", "outputRate": 16000,
                "members": ("^AudioWAV/(?P<id>(?P<speaker>[0-9]{4})_(?P<textID>[A-Z]{3})_(?P<emotion>[A-Z]{3})_"
                            "(?P<intensity>[A-Z]{2}))\\.wav$"),
                "maps": {"emotion": {"ANG": "angry", "HAP": "happy"}, "intensity": {"HI": "high",
                                                                                    "XX": "unspecified"}}}
        registry = registry_of(crema=entry([sha256_pin(path, data) for path, data in files.items()], spec,
                                           host="media.githubusercontent.com"))
        directory = self.place(registry, "crema", files)
        self.extract(registry, "crema")
        clip = {record["sourceID"]: record for record in self.manifest(registry, "crema")["clips"]}
        self.assertEqual((clip["1001_DFA_ANG_XX"]["speaker"], clip["1001_DFA_ANG_XX"]["textID"],
                          clip["1001_DFA_ANG_XX"]["emotionCanonical"], clip["1001_DFA_ANG_XX"]["intensity"]),
                         ("1001", "DFA", "angry", "unspecified"))
        receipt = json.loads((directory / corpora.RECEIPT_NAME).read_text())
        self.assertEqual(set(receipt["files"]), set(files))
        (directory / "AudioWAV/1002_IEO_HAP_HI.wav").write_bytes(pcm16(1700, 16000, 331.0))
        (directory / corpora.EXTRACTED_DIRECTORY / corpora.MANIFEST_NAME).unlink()
        with self.assertRaisesRegex(corpora.CorporaError, "does not match its pinned sha256"):
            self.extract(registry, "crema")
        self.assertFalse((directory / f".staging-{corpora.EXTRACTED_DIRECTORY}").exists())

    def test_an_unsafe_member_or_an_unnamed_wav_refuses_the_archive_and_keeps_nothing(self) -> None:
        for members, reason in (({"emoUERJ/m01a01.wav": pcm16(100, 24000), "../evil.wav": b"x"}, "unsafe path"),
                                ({"emoUERJ/m01a01.wav": pcm16(100, 24000), "emoUERJ/extra/m01a02.wav": b"x"},
                                 "member pattern does not name")):
            registry = self.zip_source(members)
            with self.assertRaisesRegex(corpora.CorporaError, reason):
                self.extract(registry, "emo")
            directory = corpora.source_directory(registry, "emo", self.root)
            self.assertFalse((directory / corpora.EXTRACTED_DIRECTORY).exists())
            self.assertFalse((directory / f".staging-{corpora.EXTRACTED_DIRECTORY}").exists())

    def test_an_unfetched_or_repinned_archive_is_refused_before_extraction(self) -> None:
        registry = self.zip_source({"emoUERJ/m01a01.wav": pcm16(100, 24000)})
        registry["sources"]["emo"]["files"][0]["md5"] = "0" * 32
        with self.assertRaisesRegex(corpora.CorporaError, "does not match its pinned md5"):
            self.extract(registry, "emo")


class ParquetTests(Fixture):
    def setUp(self) -> None:
        super().setUp()
        self.shards = {"german/dev-0.parquet": b"PAR1 german dev", "french/dev-0.parquet": b"PAR1 french dev"}
        spec = {"format": "parquet", "outputRate": 16000, "audioColumn": "audio",
                "columns": {"id": "id", "speaker": "speaker_id", "text": "transcript"}, "scores": ["total"],
                "constants": {"accent": "native"}}
        files = [sha256_pin(path, data, language=path.split("/")[0], split="dev")
                 for path, data in self.shards.items()]
        self.registry = registry_of(mls=entry(files, spec, languages=["german", "french"]))
        self.directory = self.place(self.registry, "mls", self.shards)

    def fake_worker(self, rows_by_shard: dict[str, list[dict]]):
        def decode(data: bytes):
            if not data.startswith(b"FLAC"):
                raise clips.CorpusAudioError("soundfile cannot decode it (LibsndfileError)")
            return np.full((800, 1), 0.25), 8000, {"sourceFormat": "flac-pcm_16", "sourceRate": 8000,
                                                   "sourceChannels": 1, "scale": 1.0}

        def runner(job_path: Path, _job) -> None:
            job = json.loads(job_path.read_text())
            result = worker.run_job(job, reader=lambda path, needed: rows_by_shard[
                str(Path(path).relative_to(self.directory))], decode=decode)
            Path(job["results"]).write_text(json.dumps(result))
        return runner

    def test_parquet_rows_become_clips_through_the_worker(self) -> None:
        rows = {
            "german/dev-0.parquet": [
                {"id": "1_2_3", "speaker_id": "1", "transcript": "Hallo Welt.", "total": 8,
                 "audio": {"bytes": pcm16(1600, 16000), "path": "1_2_3.flac"}},
                {"id": "1_2_4", "speaker_id": "1", "transcript": "Noch einmal.", "total": 7,
                 "audio": {"bytes": b"FLAC fake", "path": "1_2_4.flac"}},
                {"id": "1_2_5", "speaker_id": "1", "transcript": "Kaputt.", "total": 1,
                 "audio": {"bytes": b"OggS broken", "path": None}},
                {"id": "1_2_6", "speaker_id": "1", "transcript": "Leer.", "total": 1, "audio": None},
            ],
            "french/dev-0.parquet": [
                {"id": "1_2_3", "speaker_id": "9", "transcript": "Bonjour.", "total": 9,
                 "audio": {"bytes": pcm16(1600, 16000, 440.0), "path": None}},
            ],
        }
        report = quiet(corpora.extract_source, self.registry, "mls", root=self.root, worker=self.fake_worker(rows))
        self.assertEqual(report["status"], "extracted")
        directory = self.directory / corpora.EXTRACTED_DIRECTORY
        manifest = json.loads((directory / corpora.MANIFEST_NAME).read_text())
        self.assertEqual(corpora.extraction_problems(directory, corpora.extraction_identity(self.registry, "mls")), [])
        clip = {record["clipID"]: record for record in manifest["clips"]}
        self.assertEqual(set(clip), {"mls-de-1_2_3", "mls-de-1_2_4", "mls-fr-1_2_3"})
        self.assertEqual((clip["mls-de-1_2_3"]["speaker"], clip["mls-de-1_2_3"]["text"],
                          clip["mls-de-1_2_3"]["scores"], clip["mls-de-1_2_3"]["accent"],
                          clip["mls-de-1_2_3"]["language"]), ("1", "Hallo Welt.", {"total": 8}, "native", "german"))
        self.assertEqual((clip["mls-de-1_2_4"]["source"]["format"], clip["mls-de-1_2_4"]["sampleRate"],
                          clip["mls-de-1_2_4"]["samples"]), ("flac-pcm_16", 16000, 1600))
        self.assertEqual(sorted(item["reason"] for item in manifest["skipped"]),
                         ["soundfile cannot decode it (LibsndfileError)", "the row has no audio bytes"])
        self.assertEqual(manifest["members"], {"rows": 5})
        self.assertFalse((directory / corpora.JOB_NAME).exists() or (directory / corpora.RESULTS_NAME).exists())

    def test_a_worker_that_writes_no_result_leaves_nothing(self) -> None:
        with self.assertRaisesRegex(corpora.CorporaError, "wrote no readable result"):
            quiet(corpora.extract_source, self.registry, "mls", root=self.root, worker=lambda path, job: None)
        self.assertFalse((self.directory / corpora.EXTRACTED_DIRECTORY).exists())

    def test_a_wav_codec_the_parser_does_not_read_falls_back_to_soundfile(self) -> None:
        adpcm = bytearray(pcm16(800, 16000))
        adpcm[20:22] = struct.pack("<H", 2)  # WAVE_FORMAT_ADPCM
        calls = []

        def decode(data: bytes):
            calls.append(len(data))
            return np.full((400, 1), 0.1), 8000, {"sourceFormat": "wav-ms_adpcm", "sourceRate": 8000,
                                                  "sourceChannels": 1, "scale": 1.0}

        _data, info = worker.clip_audio(bytes(adpcm), output_rate=16000, decode=decode)
        self.assertEqual((calls, info["sourceFormat"], info["samples"]), ([len(adpcm)], "wav-ms_adpcm", 800))

        def refuse(data: bytes):
            raise clips.CorpusAudioError("soundfile cannot decode it (LibsndfileError)")

        with self.assertRaisesRegex(clips.CorpusAudioError, "neither integer PCM nor IEEE float"):
            worker.clip_audio(bytes(adpcm), output_rate=16000, decode=refuse)

    def test_the_row_id_falls_back_from_the_audio_path_to_the_shard_row(self) -> None:
        spec = {"columns": {"id": "@audio-path"}}
        self.assertEqual(worker.row_identity({}, spec, "data/test-0.parquet", 4, "F1_anger_01.wav"),
                         "F1_anger_01")
        self.assertEqual(worker.row_identity({}, spec, "data/test-0.parquet", 4, None), "test-0-4")
        self.assertEqual(worker.needed_columns({"audioColumn": "speech", "columns": {"id": "name", "x": "@row"},
                                                "scores": ["total"]}), ["name", "speech", "total"])


# --------------------------------------------------------------------------- #
# FLEURS reserve cohorts
# --------------------------------------------------------------------------- #

def fleurs_row(sentence: int, file: str, text: str, samples: int = 1600, gender: str = "FEMALE") -> tuple:
    return sentence, file, text, samples, gender


def tsv(rows) -> bytes:
    return "".join("\t".join((str(sentence), file, text, text.lower(), "x", str(samples), gender)) + "\n"
                   for sentence, file, text, samples, gender in rows).encode()


class ReserveTests(Fixture):
    LANGUAGES = ("english", "french")

    def setUp(self) -> None:
        super().setUp()
        self.rows = {
            ("english", "dev"): [fleurs_row(101, "10001.wav", "The quiet river runs past the mill.")],
            ("english", "test"): [fleurs_row(201, "20001.wav", "Birds sing softly in the morning light.")],
            ("french", "dev"): [fleurs_row(301, "30001.wav", "Le petit chat dort sur la fenêtre.")],
            ("french", "test"): [fleurs_row(401, "40001.wav", "Nous avons marché le long de la rivière.")],
            ("english", "train"): [
                fleurs_row(101, "50001.wav", "The quiet river runs past the mill."),  # shared with dev
                fleurs_row(501, "50002.wav", "A small boat drifts across the lake."),
                fleurs_row(501, "50003.wav", "A small boat drifts across the lake."),
                fleurs_row(502, "50004.wav", "There were 3 boats on the lake."),  # a digit: ineligible
                fleurs_row(503, "50005.wav", "The wind carries the smell of rain."),
                fleurs_row(504, "50006.wav", "Old roads wind slowly through the hills."),
                fleurs_row(504, "50007.wav", "Old roads wind slowly through the hills."),
                fleurs_row(505, "50008.wav", "Warm bread waits on the kitchen table."),
                fleurs_row(506, "50009.wav", "Children laugh as the snow begins to fall."),
            ],
            ("french", "train"): [
                fleurs_row(601, "60001.wav", "La pluie tombe doucement sur le jardin."),
                fleurs_row(602, "60002.wav", "Le vent souffle fort ce matin."),
                fleurs_row(603, "60003.wav", "Nous marchons vers la gare."),
            ],
        }
        self.n1_files: dict[str, bytes] = {}
        n1_languages = []
        for language in self.LANGUAGES:
            config = n1.FLEURS_CONFIGS[language]
            splits = []
            for split, role in n1.SPLIT_ROLES.items():
                data = tsv(self.rows[(language, split)])
                archive = tar_gz({f"{split}/{row[1]}": pcm16(row[3], 16000) for row in self.rows[(language, split)]})
                self.n1_files[f"data/{config}/{split}.tsv"] = data
                self.n1_files[f"data/{config}/audio/{split}.tar.gz"] = archive
                splits.append({"split": split, "role": role,
                               "tsv": {"path": f"data/{config}/{split}.tsv", "size": len(data),
                                       "gitBlobSHA1": n1.git_blob_sha1(data)},
                               "archive": {"path": f"data/{config}/audio/{split}.tar.gz", "size": len(archive),
                                           "sha256": hashlib.sha256(archive).hexdigest()}})
            n1_languages.append({"language": language, "config": config, "splits": splits})
        self.n1_sources = {"revision": REVISION, "dataset": n1.DATASET, "languages": n1_languages,
                           "attribution": n1.ATTRIBUTION}
        self.train: dict[str, bytes] = {}
        files = []
        for language in self.LANGUAGES:
            config = n1.FLEURS_CONFIGS[language]
            rows = self.rows[(language, "train")]
            members = {f"train/{row[1]}": pcm16(row[3], 16000, 200.0 + index) for index, row in enumerate(rows)}
            if language == "english":
                members["train/99999.wav"] = pcm16(1600, 16000)  # a member the TSV does not list
            self.train[f"data/{config}/train.tsv"] = tsv(rows)
            self.train[f"data/{config}/audio/train.tar.gz"] = tar_gz(members)
            data = self.train[f"data/{config}/train.tsv"]
            files += [{"path": f"data/{config}/train.tsv", "size": len(data), "gitBlobSHA1": n1.git_blob_sha1(data)},
                      sha256_pin(f"data/{config}/audio/train.tar.gz", self.train[f"data/{config}/audio/train.tar.gz"])]
        self.registry = registry_of(**{"fleurs-train": entry(
            files, {"format": "fleurs-reserve", "cohorts": 2, "perLanguage": 3, "seed": "test-seed"},
            group="fleurs-train", repository="google/fleurs", languages=list(self.LANGUAGES))})
        self.corpus = self.place(self.registry, "fleurs-train", {**self.n1_files, **self.train})

    def extract(self) -> dict:
        with mock.patch.object(n1, "sources_digest", return_value="d" * 64):
            return quiet(corpora.extract_fleurs_reserve, self.registry, "fleurs-train", root=self.root,
                         n1_sources=self.n1_sources)

    def test_the_selection_is_seeded_stratified_disjoint_and_eligible_only(self) -> None:
        rows = n1.parse_tsv(tsv(self.rows[("english", "train")]), "t")
        pick = corpora.reserve_selection(rows, language="english", shared_ids={101, 201}, cohorts=2,
                                         per_language=3, seed="s")
        self.assertEqual(pick, corpora.reserve_selection(list(reversed(rows)), language="english",
                                                         shared_ids={101, 201}, cohorts=2, per_language=3, seed="s"))
        sentences = [{row.sentence_id for row in cohort} for cohort in pick]
        self.assertFalse(sentences[0] & sentences[1])
        chosen = {row.file for cohort in pick for row in cohort}
        self.assertFalse(chosen & {"50001.wav", "50004.wav"})
        self.assertTrue(all(len(cohort) <= 3 for cohort in pick))
        self.assertEqual(sum(len(cohort) for cohort in pick), 6)
        others = {tuple(tuple(row.file for row in cohort) for cohort in corpora.reserve_selection(
            rows, language="english", shared_ids={101}, cohorts=2, per_language=3, seed=seed))
            for seed in ("a", "b", "c", "d", "e")}
        self.assertGreater(len(others), 1)
        short = corpora.reserve_selection(rows, language="english", shared_ids=set(), cohorts=3, per_language=3,
                                          seed="s")
        self.assertLess(len(short[2]), 3)

    def test_reserve_cohorts_are_n1_manifests_the_n2_and_calibration_tools_accept(self) -> None:
        report = self.extract()
        self.assertEqual([item["cohort"] for item in report["cohorts"]], [1, 2])
        manifests = [json.loads(Path(item["manifest"]).read_text()) for item in report["cohorts"]]
        files_seen: set[str] = set()
        sentences_seen: set[int] = set()
        for index, manifest in enumerate(manifests, 1):
            self.assertEqual(n1.manifest_digest_issues(manifest), [])
            self.assertEqual((manifest["kind"], manifest["split"], manifest["fleursSplit"]),
                             (n1.MANIFEST_KIND, f"reserve-{index}", "train"))
            eligible, count = n2.eligible_recordings(manifest)
            self.assertEqual(len(eligible), count)
            files = {take["recording"]["file"] for take in manifest["takes"]}
            sentences = {take["recording"]["sentenceID"] for take in manifest["takes"]}
            self.assertFalse(files & files_seen)
            self.assertFalse(sentences & sentences_seen)
            self.assertFalse(sentences & {101, 201, 301, 401})
            files_seen |= files
            sentences_seen |= sentences
            for take in manifest["takes"]:
                path = Path(report["cohorts"][index - 1]["manifest"]).parent / take["wavPath"]
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), take["wavSHA256"])
        reserve = self.corpus / corpora.RESERVE_DIRECTORY / report["samplingDigest"][:12]
        extracted = sorted(path.name for path in (reserve / corpora.EXTRACTED_DIRECTORY / "en_us").glob("*.wav"))
        self.assertEqual(set(extracted), {file for file in files_seen if file.startswith("5")})
        receipt = json.loads((reserve / corpora.EXTRACTED_DIRECTORY / "en_us" / n1.RECEIPT_NAME).read_text())
        self.assertEqual(receipt["members"]["unlisted"], 1)
        again = self.extract()
        self.assertEqual(again["samplingDigest"], report["samplingDigest"])
        digests = [json.loads(Path(item["manifest"]).read_text())["manifestDigest"] for item in again["cohorts"]]
        self.assertEqual(digests, [manifest["manifestDigest"] for manifest in manifests])
        with mock.patch.object(n1, "sources_digest", return_value="d" * 64):
            self.assertEqual(corpora.reserve_problems(self.registry, "fleurs-train", root=self.root,
                                                      n1_sources=self.n1_sources), [])

    def test_a_kept_recording_missing_from_the_archive_refuses_the_language(self) -> None:
        config = n1.FLEURS_CONFIGS["french"]
        rows = self.rows[("french", "train")]
        archive = tar_gz({f"train/{row[1]}": pcm16(row[3], 16000) for row in rows[:1]})
        self.train[f"data/{config}/audio/train.tar.gz"] = archive
        pins = self.registry["sources"]["fleurs-train"]["files"]
        pins[:] = [pin if pin["path"] != f"data/{config}/audio/train.tar.gz"
                   else sha256_pin(pin["path"], archive) for pin in pins]
        (self.corpus / f"data/{config}/audio/train.tar.gz").write_bytes(archive)
        with self.assertRaisesRegex(n1.N1Error, "kept recordings are not in the archive"):
            self.extract()


class RuntimeWiringTests(unittest.TestCase):
    def test_the_runtime_is_built_by_the_judge_acquisition_builder_from_the_registry_view(self) -> None:
        registry = corpora.load_registry()
        interpreter = {"id": "cpython", "sha256": "a" * 64}
        with mock.patch.object(corpora.acquire, "load_valid_registry",
                               return_value={"acquisition": {"interpreter": interpreter}}), \
                mock.patch.object(corpora.acquire, "ensure_interpreter", return_value=Path("/python")) as build, \
                mock.patch.object(corpora.acquire, "ensure_runtime", return_value=Path("/venv/bin/python3")) as venv:
            self.assertEqual(corpora.ensure_runtime(registry, model_root=Path("/models")), Path("/venv/bin/python3"))
        self.assertEqual(build.call_args.args, (Path("/models"), interpreter))
        root, view, family, python = venv.call_args.args
        self.assertEqual((root, family, python), (Path("/models"), corpora.RUNTIME_FAMILY, Path("/python")))
        spec = view["acquisition"]["runtimes"][family]
        self.assertEqual((spec["lock"], spec["venv"]), ("config/audio-qc-runtimes/corpora-parquet.txt",
                                                        "audio-qc-runtime-corpora-parquet-py314"))
        self.assertEqual(view["acquisition"]["interpreter"], interpreter)

    def test_selection_flags_take_several_values(self) -> None:
        with mock.patch.object(corpora, "plan", return_value={}) as planned, \
                mock.patch.object(corpora, "_print_plan"):
            self.assertEqual(corpora.main(["plan", "--group", "emotion", "accent", "--source", "mls"]), 0)
        self.assertEqual(set(planned.call_args.args[1]),
                         set(corpora.select(corpora.load_registry(), groups=["emotion", "accent"], sources=["mls"])))


class WorkerJobTests(unittest.TestCase):
    def test_a_job_of_another_kind_is_refused(self) -> None:
        with self.assertRaisesRegex(worker.WorkerError, "is not an audio-qc-corpora-parquet-job"):
            worker.run_job({"kind": "something"})


if __name__ == "__main__":
    unittest.main()
