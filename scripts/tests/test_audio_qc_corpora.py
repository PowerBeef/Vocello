#!/usr/bin/env python3
"""AQ-07 corpora: the pinned registry, its fetch, receipts and extraction, and the FLEURS reserve cohorts.

No network and no corpus data. The committed registry is validated as the
contract gate validates it; everything else runs on synthetic sources built in
a temporary directory (WAVs, a zip, a tar.gz, pins of their own bytes) served
through a fake opener. Parquet extraction runs the worker's row logic through a
fake worker (the system interpreter has no pyarrow).
"""

from __future__ import annotations

from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tarfile
import tempfile
from types import SimpleNamespace
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


def snapshot(root: Path) -> dict[str, bytes]:
    """Every plain file under `root` (links not followed) by its relative path, with its bytes."""
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file() and not path.is_symlink()}


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
                         (9037, 28_964_969_758))
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
        pins = [pin for pin in corpora.source_pins(self.registry, "crema-d") if pin.role == "audio"]
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

    def test_mls_and_crema_d_take_speaker_gender_from_blob_pinned_metadata(self) -> None:
        mls = self.registry["sources"]["mls"]
        metadata = [pin for pin in corpora.source_pins(self.registry, "mls") if pin.role == "metadata"]
        # One metainfo.txt per language, pinned by git blob SHA-1 and labelling that language's clips only.
        self.assertEqual([(pin.path, pin.language, pin.kind) for pin in metadata],
                         [(f"data/mls_{language}/metainfo.txt", language, "gitBlobSHA1")
                          for language in mls["languages"]])
        self.assertEqual([(table["file"], table["joinOn"], table["fields"], table.get("header"))
                          for table in mls["extract"]["metadata"]],
                         [(pin.path, "speaker", {"gender": 1}, True) for pin in metadata])
        crema = self.registry["sources"]["crema-d"]
        [demographics] = [pin for pin in corpora.source_pins(self.registry, "crema-d") if pin.role == "metadata"]
        self.assertEqual((demographics.path, demographics.kind), ("VideoDemographics.csv", "gitBlobSHA1"))
        self.assertEqual(corpora.file_url(crema, demographics),
                         f"https://raw.githubusercontent.com/{crema['repository']}/{crema['revision']}"
                         "/VideoDemographics.csv")
        # Only the Sex column is ever read: never age, race or ethnicity.
        self.assertEqual([table["fields"] for table in crema["extract"]["metadata"]], [{"gender": "Sex"}])
        for source in ("mls", "crema-d", "aishell3-subset", "emozionalmente"):
            self.assertTrue(self.registry["sources"][source]["labels"]["gender"], source)
        for source in ("libritts-r", "zeroth-korean"):
            entry_ = self.registry["sources"][source]
            self.assertIsNone(entry_["labels"]["gender"], source)
            self.assertTrue(any(caveat.startswith("No speaker gender") for caveat in entry_["caveats"]), source)

    def test_metadata_pins_are_read_scoped_and_hosted_as_declared(self) -> None:
        for change, expected in (
                (lambda r: r["sources"]["mls"]["extract"]["metadata"].pop(), "no extract.metadata table reads it"),
                (lambda r: r["sources"]["mls"]["files"][-1].update(language="english"), "names a language only"),
                (lambda r: r["sources"]["mls"]["files"][0].update(path="german/dev.arrow"), ".parquet shards"),
                (lambda r: r["sources"]["crema-d"]["files"][0].pop("role"), "is a metadata file"),
                (lambda r: r["sources"]["crema-d"]["extract"]["metadata"][0].update(header=True), "header"),
                (lambda r: r["sources"]["crema-d"]["extract"]["metadata"][0].update(file="Other.csv"),
                 "not a pinned metadata file")):
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
        self.assertEqual(value["downloadBytes"], 28_964_969_758)
        self.assertEqual(value["missingBytes"], 28_964_969_758 + value["n1TSVBytes"])
        self.assertEqual(set(value["groups"]), set(corpora.GROUPS))
        # The per-speaker caps of MLS, Zeroth-Korean and LibriTTS-R keep the extraction near 13.6 GB (34 GB uncapped).
        self.assertGreater(value["extractTotalBytes"], 10e9)
        self.assertLess(value["extractTotalBytes"], 20e9)
        self.assertTrue(value["runtime"]["needed"])
        self.assertFalse(value["runtime"]["built"])


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #

class TransportTests(unittest.TestCase):
    def test_only_https_on_the_corpora_hosts_is_allowed(self) -> None:
        for url in ("https://huggingface.co/datasets/a/b/resolve/x/y", "https://cas-bridge.xethub.hf.co/x",
                    "https://us.aws.cdn.hf.co/x", "https://media.githubusercontent.com/media/a/b/c/d",
                    "https://raw.githubusercontent.com/a/b/c/d", "https://zenodo.org/api/records/1/files/x/content"):
            self.assertTrue(corpora.allowed_url(url), url)
        for url in ("http://huggingface.co/x", "http://raw.githubusercontent.com/a/b/c/d",
                    "https://raw.githubusercontent.com.example.org/a", "https://gist.githubusercontent.com/a/b",
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
        # raw.githubusercontent.com serves only blob-pinned metadata requested directly: never a redirect target.
        self.assertFalse(corpora.allowed_url("https://raw.githubusercontent.com/a/b/c/d", raw=False))
        with self.assertRaisesRegex(corpora.CorporaError, "not an allowed corpora host"):
            handler.redirect_request(request, None, 302, "Found", {}, "https://raw.githubusercontent.com/a/b/c/d")

    def test_each_host_kind_downloads_from_its_pinned_place(self) -> None:
        hub = entry([], {"format": "parquet"})
        lfs = entry([], {"format": "wav-files"}, host="media.githubusercontent.com")
        zen = entry([], {"format": "zip"}, host="zenodo.org", record="42", version="1.0")
        del zen["repository"], zen["revision"]
        self.assertEqual(url_of(hub, "data/a b.parquet"),
                         f"https://huggingface.co/datasets/owner/corpus/resolve/{REVISION}/data/a%20b.parquet")
        self.assertEqual(url_of(lfs, "AudioWAV/x.wav"),
                         f"https://media.githubusercontent.com/media/owner/corpus/{REVISION}/AudioWAV/x.wav")
        # A GitHub source's plain git file (not LFS content) comes from raw, at the same pinned commit.
        self.assertEqual(url_of(lfs, "Video Demographics.csv", "gitBlobSHA1"),
                         f"https://raw.githubusercontent.com/owner/corpus/{REVISION}/Video%20Demographics.csv")
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

    def test_a_github_metadata_file_downloads_from_raw_and_is_bound_to_its_git_blob(self) -> None:
        demographics = b"ActorID,Sex\n1001,Male\n"
        audio = self.lfs_files["AudioWAV/0.wav"]
        source = entry([sha256_pin("AudioWAV/0.wav", audio),
                        {"path": "VideoDemographics.csv", "size": len(demographics),
                         "gitBlobSHA1": n1.git_blob_sha1(demographics), "role": "metadata"}],
                       {"format": "wav-files"}, host="media.githubusercontent.com")
        registry = registry_of(crema=source)
        raw = url_of(source, "VideoDemographics.csv", "gitBlobSHA1")
        host = FakeHost({url_of(source, "AudioWAV/0.wav"): audio, raw: demographics})
        report = quiet(corpora.fetch, registry, ["crema"], root=self.root, opener=host, sleep=lambda _seconds: None)
        self.assertEqual(report[0]["fetched"], 2)
        self.assertIn(raw, {url for url, _range in host.requests})
        self.assertTrue(raw.startswith("https://raw.githubusercontent.com/"))
        tampered = FakeHost({url_of(source, "AudioWAV/0.wav"): audio, raw: demographics.replace(b"Male", b"Mole")})
        with self.assertRaisesRegex(corpora.CorporaError, "does not match its pinned size and digest"):
            quiet(corpora.fetch, registry, ["crema"], root=self.tmp / "other", opener=tampered,
                  sleep=lambda _seconds: None, jobs=1)
        self.assertFalse((corpora.source_directory(registry, "crema", self.tmp / "other")
                          / "VideoDemographics.csv").exists())

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

    def test_a_pinned_demographics_file_adds_only_gender_to_wav_files(self) -> None:
        files = {"AudioWAV/1001_DFA_ANG_XX.wav": pcm16(1600, 16000),
                 "AudioWAV/1002_IEO_HAP_HI.wav": pcm16(1700, 16000, 330.0),
                 "AudioWAV/1003_IEO_SAD_LO.wav": pcm16(1800, 16000, 440.0)}
        demographics = ("ActorID,Age,Sex,Race,Ethnicity\n"
                        "1001,AgeSentinel,Male,RaceSentinel,EthnicitySentinel\n"
                        "1002,AgeSentinel,Female,RaceSentinel,EthnicitySentinel\n").encode()
        spec = {"format": "wav-files", "outputRate": 16000,
                "members": ("^AudioWAV/(?P<id>(?P<speaker>[0-9]{4})_(?P<textID>[A-Z]{3})_(?P<emotion>[A-Z]{3})_"
                            "(?P<intensity>[A-Z]{2}))\\.wav$"),
                "maps": {"gender": {"Female": "female", "Male": "male"}},
                "metadata": [{"file": "VideoDemographics.csv", "format": "csv", "keyColumn": "ActorID",
                              "keyNormalize": "int", "joinOn": "speaker", "fields": {"gender": "Sex"}}]}
        pins = [sha256_pin(path, data) for path, data in files.items()]
        pins.append({"path": "VideoDemographics.csv", "size": len(demographics),
                     "gitBlobSHA1": n1.git_blob_sha1(demographics), "role": "metadata"})
        registry = registry_of(crema=entry(pins, spec, host="media.githubusercontent.com"))
        self.assertEqual(corpora._extract_issues("crema", registry["sources"]["crema"],
                                                 corpora.source_pins(registry, "crema")), [])
        directory = self.place(registry, "crema", files)
        with self.assertRaisesRegex(corpora.CorporaError, "VideoDemographics.csv is not fetched"):
            self.extract(registry, "crema")
        (directory / "VideoDemographics.csv").write_bytes(demographics.replace(b"Male", b"Mole"))
        with self.assertRaisesRegex(corpora.CorporaError, "does not match its pinned gitBlobSHA1"):
            self.extract(registry, "crema")
        (directory / "VideoDemographics.csv").write_bytes(demographics)
        self.extract(registry, "crema")
        manifest = self.manifest(registry, "crema")
        clip = {record["sourceID"]: record for record in manifest["clips"]}
        self.assertEqual([clip[name]["gender"] for name in sorted(clip)], ["male", "female", None])
        self.assertEqual(manifest["metadata"]["VideoDemographics.csv"], {"rows": 2, "unjoinedClips": 1})
        text = json.dumps(manifest)
        for sentinel in ("AgeSentinel", "RaceSentinel", "EthnicitySentinel"):
            self.assertNotIn(sentinel, text)
        receipt = json.loads((directory / corpora.RECEIPT_NAME).read_text())
        self.assertIn("VideoDemographics.csv", receipt["files"])

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

    def test_a_per_speaker_cap_keeps_each_speakers_lowest_ranked_ids_across_shards(self) -> None:
        def row(identity: str, speaker: str | None) -> dict:
            return {"id": identity, "speaker_id": speaker, "transcript": "Hallo.", "total": 5,
                    "audio": {"bytes": pcm16(1600, 16000), "path": None}}

        rows = {"german/dev-0.parquet": [row("a1", "1"), row("a2", "1"), row("b1", "2"), row("x", None)],
                "french/dev-0.parquet": [row("a3", "1"), row("c1", "3")]}
        job = {"extract": {"columns": {"id": "id", "speaker": "speaker_id"}, "perSpeaker": 1, "capSeed": "seed"},
               "files": [{"path": path, "shard": path, "language": path.split("/")[0]} for path in rows]}

        def reader(path, needed):
            self.assertEqual(sorted(needed), ["id", "speaker_id"])
            return [{name: item[name] for name in needed} for item in rows[str(path)]]

        keep = worker.speaker_cap(job, reader)
        rank = {identity: hashlib.sha256(f"seed\0german\0{identity}".encode()).hexdigest() for identity in ("a1", "a2")}
        german_one = ("german/dev-0.parquet", 0 if rank["a1"] < rank["a2"] else 1)
        # One id per (language, speaker): speaker 1 once in German and once in French; no speaker, no row.
        self.assertEqual(keep, {german_one, ("german/dev-0.parquet", 2), ("french/dev-0.parquet", 0),
                                ("french/dev-0.parquet", 1)})
        self.assertIsNone(worker.speaker_cap({"extract": {}, "files": []}, reader))

    def test_per_language_metadata_files_join_gender_by_speaker_within_their_language(self) -> None:
        header = " SPEAKER   |   GENDER   | PARTITION  |  MINUTES   |  BOOK ID   |  TITLE  |  CHAPTER\n"
        german = (header + "  1  |  F  | dev | 10.0 | 100 | Ein Buch | 1\n  1  |  F  | dev | 12.0 | 101 | Zwei | 2\n"
                  "  2  |  F  | dev | 5.0 | 102 | Buch | 1\n  2  |  M  | dev | 5.0 | 103 | Buch | 2\n").encode()
        french = (header + "  1  |  M  | dev | 10.0 | 200 | Un livre | 1\n  9  |  F  | dev | 8.0 | 201 | Livre | 1\n"
                  ).encode()
        metadata = {"data/mls_german/metainfo.txt": german, "data/mls_french/metainfo.txt": french}
        source = self.registry["sources"]["mls"]
        source["files"] += [{"path": path, "size": len(data), "gitBlobSHA1": n1.git_blob_sha1(data),
                             "role": "metadata", "language": path.split("/")[1].removeprefix("mls_")}
                            for path, data in metadata.items()]
        source["extract"]["metadata"] = [{"file": path, "format": "pipe", "header": True, "keyColumn": 0,
                                          "keyNormalize": "int", "joinOn": "speaker", "fields": {"gender": 1}}
                                         for path in metadata]
        source["extract"]["maps"] = {"gender": {"F": "female", "M": "male"}}
        self.assertEqual(corpora._extract_issues("mls", source, corpora.source_pins(self.registry, "mls")), [])
        self.place(self.registry, "mls", metadata)

        def row(identity: str, speaker: str, frequency: float) -> dict:
            return {"id": identity, "speaker_id": speaker, "transcript": "Hallo.", "total": 5,
                    "audio": {"bytes": pcm16(1600, 16000, frequency), "path": None}}

        # The worker reads only the shards: a metadata file in its job would have no rows here.
        rows = {"german/dev-0.parquet": [row("1_1_1", "1", 200.0), row("2_1_1", "2", 300.0),
                                         row("7_1_1", "7", 400.0)],
                "french/dev-0.parquet": [row("9_1_1", "9", 500.0), row("1_1_2", "0001", 600.0)]}
        quiet(corpora.extract_source, self.registry, "mls", root=self.root, worker=self.fake_worker(rows))
        manifest = json.loads((self.directory / corpora.EXTRACTED_DIRECTORY / corpora.MANIFEST_NAME).read_text())
        gender = {record["clipID"]: record["gender"] for record in manifest["clips"]}
        # German speaker 1 is female in German; the French table's speaker 1 (male) labels French clips only.
        # German speaker 2's rows disagree, so it keeps no gender; speaker 7 is in no table.
        self.assertEqual(gender, {"mls-de-1_1_1": "female", "mls-de-2_1_1": None, "mls-de-7_1_1": None,
                                  "mls-fr-9_1_1": "female", "mls-fr-1_1_2": "male"})
        self.assertEqual(manifest["metadata"], {
            "data/mls_german/metainfo.txt": {"rows": 2, "unjoinedClips": 1, "conflictingKeys": 1},
            "data/mls_french/metainfo.txt": {"rows": 2, "unjoinedClips": 0}})
        self.assertEqual(manifest["counts"]["byGender"], {"female": 2, "male": 1, "unknown": 2})
        (self.directory / corpora.EXTRACTED_DIRECTORY / corpora.MANIFEST_NAME).unlink()
        (self.directory / "data/mls_german/metainfo.txt").unlink()
        with self.assertRaisesRegex(corpora.CorporaError, "data/mls_german/metainfo.txt is not fetched"):
            quiet(corpora.extract_source, self.registry, "mls", root=self.root, worker=self.fake_worker(rows))

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
# Pruning the downloads of a complete extraction
# --------------------------------------------------------------------------- #

class PruneTests(Fixture):
    """`prune-archives`: only the pinned downloads of a complete, verified extraction go, each marked in its
    receipt, and `fetch` restores them; any refusal removes nothing."""

    WHEN = "2026-09-30T12:00:00Z"

    def setUp(self) -> None:
        super().setUp()
        self.archive = zip_bytes({"emoUERJ/m01a01.wav": pcm16(1600, 24000),
                                  "emoUERJ/w02h03.wav": pcm16(1700, 24000, 330.0)})
        emo = entry([{"path": "set.zip", "size": len(self.archive), "md5": hashlib.md5(self.archive).hexdigest()}],
                    {"format": "zip", "outputRate": 24000,
                     "members": "^emoUERJ/(?P<id>(?P<speaker>[mw][0-9]{2})[ahns][0-9]{2})\\.wav$"},
                    host="zenodo.org", record="7", version="1", languages=["portuguese"])
        del emo["repository"], emo["revision"]
        self.wavs = {"AudioWAV/1001_DFA_ANG_XX.wav": pcm16(1600, 16000),
                     "AudioWAV/1002_IEO_HAP_HI.wav": pcm16(1700, 16000, 330.0)}
        self.demographics = b"ActorID,Sex\n1001,Male\n1002,Female\n"
        pins = [sha256_pin(path, data) for path, data in self.wavs.items()]
        pins.append({"path": "VideoDemographics.csv", "size": len(self.demographics),
                     "gitBlobSHA1": n1.git_blob_sha1(self.demographics), "role": "metadata"})
        crema = entry(pins, {"format": "wav-files", "outputRate": 16000,
                             "members": "^AudioWAV/(?P<id>(?P<speaker>[0-9]{4})_[A-Z]{3}_[A-Z]{3}_[A-Z]{2})\\.wav$",
                             "maps": {"gender": {"Female": "female", "Male": "male"}},
                             "metadata": [{"file": "VideoDemographics.csv", "format": "csv", "keyColumn": "ActorID",
                                           "keyNormalize": "int", "joinOn": "speaker", "fields": {"gender": "Sex"}}]},
                      host="media.githubusercontent.com")
        self.registry = registry_of(emo=emo, crema=crema)
        self.emo = self.place(self.registry, "emo", {"set.zip": self.archive})
        self.crema = self.place(self.registry, "crema", {**self.wavs, "VideoDemographics.csv": self.demographics})
        for source in ("emo", "crema"):
            quiet(corpora.extract_source, self.registry, source, root=self.root)
        self.receipts = {f"emo/zenodo-7/{corpora.RECEIPT_NAME}", f"crema/{REVISION}/{corpora.RECEIPT_NAME}"}

    def prune(self, sources=("emo", "crema"), **kwargs) -> dict:
        return quiet(corpora.prune_archives, self.registry, list(sources), root=self.root, now=lambda: self.WHEN,
                     **kwargs)

    def receipt(self, directory: Path) -> dict:
        return json.loads((directory / corpora.RECEIPT_NAME).read_text())["files"]

    def test_a_dry_run_lists_the_downloads_and_their_bytes_and_removes_nothing(self) -> None:
        before = snapshot(self.root)
        value = self.prune(dry_run=True)
        self.assertEqual(snapshot(self.root), before)
        rows = {row["source"]: row for row in value["sources"]}
        self.assertEqual([item["path"] for item in rows["emo"]["files"]], ["set.zip"])
        self.assertEqual([item["path"] for item in rows["crema"]["files"]], sorted(self.wavs))
        self.assertEqual(value["reclaimBytes"], len(self.archive) + sum(len(data) for data in self.wavs.values()))
        self.assertIsNone(value["prunedAt"])
        output = io.StringIO()
        with redirect_stdout(output):
            corpora._print_prune(value)
        self.assertIn("would remove emo/zenodo-7/set.zip", output.getvalue())
        self.assertIn(f"Would reclaim {value['reclaimBytes']} bytes", output.getvalue())

    def test_only_pinned_downloads_go_and_the_receipt_marks_each_one_pruned(self) -> None:
        (self.emo / "other.zip").write_bytes(b"a file no pin names")
        (self.crema / "AudioWAV" / "stray.wav").write_bytes(b"a file no pin names")
        before = snapshot(self.root)
        value = self.prune()
        after = snapshot(self.root)
        self.assertEqual(set(before) - set(after),
                         {"emo/zenodo-7/set.zip", *(f"crema/{REVISION}/{path}" for path in self.wavs)})
        # Extractions, manifests, metadata and unpinned files stay byte for byte; only the receipts change.
        self.assertEqual({path: data for path, data in after.items() if path not in self.receipts},
                         {path: before[path] for path in after if path not in self.receipts})
        self.assertEqual(value["prunedAt"], self.WHEN)
        self.assertEqual(value["reclaimBytes"], len(self.archive) + sum(len(data) for data in self.wavs.values()))
        archive = self.receipt(self.emo)["set.zip"]
        self.assertEqual((archive["prunedAt"], archive["size"], archive["md5"], archive["sha256"]),
                         (self.WHEN, len(self.archive), hashlib.md5(self.archive).hexdigest(),
                          hashlib.sha256(self.archive).hexdigest()))
        crema = self.receipt(self.crema)
        self.assertEqual({path for path, item in crema.items() if "prunedAt" in item}, set(self.wavs))
        self.assertTrue((self.crema / "VideoDemographics.csv").is_file())
        for source in ("emo", "crema"):
            self.assertEqual(corpora.prune_blockers(self.registry, source, root=self.root), [])
        again = self.prune()
        self.assertEqual(again["reclaimBytes"], 0)
        self.assertEqual({row["source"]: row["alreadyPruned"] for row in again["sources"]}, {"emo": 1, "crema": 2})

    def test_verify_reports_a_pruned_file_plan_counts_it_missing_and_fetch_restores_it(self) -> None:
        self.prune(sources=("emo",))
        results = quiet(corpora.verify, self.registry, ["emo"], root=self.root)
        self.assertEqual((results[0]["status"], results[0]["prunedFiles"], results[0]["problems"]), ("PASS", 1, []))
        self.assertIn("`fetch` restores them", results[0]["notes"][0])
        with mock.patch.object(corpora, "runtime_spec", return_value={
                "venv": "none", "lockSHA256": "x", "downloadBytes": 1, "packages": 1}):
            row = corpora.plan(self.registry, ["emo"], root=self.root, model_root=self.tmp)["sources"][0]
        self.assertEqual((row["presentBytes"], row["missingBytes"], row["prunedFiles"], row["prunedBytes"],
                          row["extracted"]), (0, len(self.archive), 1, len(self.archive), True))
        host = FakeHost({url_of(self.registry["sources"]["emo"], "set.zip", "md5"): self.archive})
        report = quiet(corpora.fetch, self.registry, ["emo"], root=self.root, opener=host, sleep=lambda _seconds: None)
        self.assertEqual(report[0]["fetched"], 1)
        self.assertEqual((self.emo / "set.zip").read_bytes(), self.archive)
        self.assertNotIn("prunedAt", self.receipt(self.emo)["set.zip"])
        results = quiet(corpora.verify, self.registry, ["emo"], root=self.root)
        self.assertEqual((results[0]["status"], results[0]["verifiedFiles"], results[0]["prunedFiles"]),
                         ("PASS", 1, 0))

    def test_a_pruned_md5_file_fetched_again_must_match_its_recorded_sha256(self) -> None:
        self.prune(sources=("emo",))
        path = self.emo / corpora.RECEIPT_NAME
        receipt = json.loads(path.read_text())
        receipt["files"]["set.zip"]["sha256"] = "0" * 64
        path.write_text(json.dumps(receipt))
        host = FakeHost({url_of(self.registry["sources"]["emo"], "set.zip", "md5"): self.archive})
        with self.assertRaisesRegex(corpora.CorporaError, "does not match its pinned size and digest"):
            quiet(corpora.fetch, self.registry, ["emo"], root=self.root, opener=host, sleep=lambda _seconds: None)
        self.assertFalse((self.emo / "set.zip").exists())

    def test_a_missing_or_stale_extraction_refuses_and_removes_nothing(self) -> None:
        shutil.rmtree(self.emo / corpora.EXTRACTED_DIRECTORY)
        before = snapshot(self.root)
        with self.assertRaisesRegex(corpora.CorporaError, "removed nothing:\n  emo: its extraction is not complete "
                                                          "and current \\(not extracted\\); run `extract --source "
                                                          "emo` first"):
            self.prune()
        self.assertEqual(snapshot(self.root), before)
        quiet(corpora.extract_source, self.registry, "emo", root=self.root)
        manifest = json.loads((self.crema / corpora.EXTRACTED_DIRECTORY / corpora.MANIFEST_NAME).read_text())
        wav = self.crema / corpora.EXTRACTED_DIRECTORY / manifest["clips"][0]["wavPath"]
        data = bytearray(wav.read_bytes())
        data[-1] ^= 1  # same size: only the deep check (every WAV hashed) sees it
        wav.write_bytes(bytes(data))
        before = snapshot(self.root)
        with self.assertRaisesRegex(corpora.CorporaError, "crema: its extraction is not complete and current "
                                                          "\\(.* differs from its manifest\\)"):
            self.prune()
        self.assertEqual(snapshot(self.root), before)
        self.registry["sources"]["emo"]["extract"]["outputRate"] = 16000
        with self.assertRaisesRegex(corpora.CorporaError, "emo: .*extracted from other pins or another extraction "
                                                          "spec"):
            self.prune(sources=("emo",))
        self.assertEqual(snapshot(self.root), before)

    def test_a_file_that_differs_from_its_pin_refuses_every_source(self) -> None:
        path = self.crema / "AudioWAV/1002_IEO_HAP_HI.wav"
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(bytes(data))
        before = snapshot(self.root)
        with self.assertRaisesRegex(corpora.CorporaError, "removed nothing:\n  crema: AudioWAV/1002_IEO_HAP_HI.wav "
                                                          "does not match its pinned sha256"):
            self.prune()
        self.assertEqual(snapshot(self.root), before)  # the verified zip of the other source stays too

    def test_a_symbolic_link_anywhere_on_the_path_refuses(self) -> None:
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "set.zip").write_bytes(self.archive)
        (self.emo / "set.zip").unlink()
        (self.emo / "set.zip").symlink_to(outside / "set.zip")
        with self.assertRaisesRegex(corpora.CorporaError, "set.zip: emo/zenodo-7/set.zip is a symbolic link"):
            self.prune(sources=("emo",))
        self.assertEqual((outside / "set.zip").read_bytes(), self.archive)
        audio = self.crema / "AudioWAV"
        audio.rename(outside / "AudioWAV")
        audio.symlink_to(outside / "AudioWAV", target_is_directory=True)
        with self.assertRaisesRegex(corpora.CorporaError, f"crema/{REVISION}/AudioWAV is a symbolic link"):
            self.prune(sources=("crema",))
        self.assertEqual(sorted(path.name for path in (outside / "AudioWAV").iterdir()),
                         sorted(Path(path).name for path in self.wavs))
        for name in ("extracted/manifest.json", corpora.RECEIPT_NAME, ".staging-extracted/x.wav"):
            with self.assertRaisesRegex(corpora.CorporaError, "names an extraction, a receipt or a manifest"):
                corpora.prune_path(self.root, self.emo, corpora.Pin(name, 1, "sha256", "0" * 64))
        linked_root = self.tmp / "linked-root"
        linked_root.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(corpora.CorporaError, "cache root is missing or a symbolic link"):
            quiet(corpora.prune_archives, self.registry, ["emo"], root=linked_root, dry_run=True)

    def test_an_extract_after_a_prune_refuses_until_fetch_restores_the_download(self) -> None:
        self.prune(sources=("emo",))
        self.assertEqual(quiet(corpora.extract_source, self.registry, "emo", root=self.root)["status"], "present")
        (self.emo / corpora.EXTRACTED_DIRECTORY / corpora.MANIFEST_NAME).unlink()
        with self.assertRaisesRegex(corpora.CorporaError, "emo: 1 pinned files \\(set.zip first\\) were pruned after "
                                                          "a verified extraction.*fetch --source emo"):
            quiet(corpora.extract_source, self.registry, "emo", root=self.root)
        results = quiet(corpora.verify, self.registry, ["emo"], root=self.root)
        self.assertEqual(results[0]["status"], "FAIL")
        self.assertIn("its downloads were pruned: run `fetch --source emo`, then `extract --source emo`",
                      results[0]["problems"])
        with self.assertRaisesRegex(corpora.CorporaError, "run `fetch --source emo`, then `extract --source emo`"):
            self.prune(sources=("emo",))

    def test_the_command_takes_explicit_sources_and_reports_a_refusal(self) -> None:
        self.root.mkdir(exist_ok=True)
        errors = io.StringIO()
        with mock.patch.dict(os.environ, {n1.CACHE_ENV: str(self.root)}), redirect_stderr(errors), \
                redirect_stdout(io.StringIO()):
            status = corpora.main(["prune-archives", "--source", "emodb", "--dry-run"])
        self.assertEqual(status, 1)
        self.assertIn("emodb: its extraction is not complete and current (not extracted)", errors.getvalue())
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            corpora.main(["prune-archives", "--dry-run"])


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
            # FLEURS reads one FLoRes sentence in every language: French reads English's 501, 503 and 505.
            ("french", "train"): [
                fleurs_row(501, "60001.wav", "La pluie tombe doucement sur le jardin."),
                fleurs_row(503, "60002.wav", "Le vent souffle fort ce matin."),
                fleurs_row(505, "60003.wav", "Nous marchons vers la gare."),
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

        def pick(train, shared, **kwargs):
            values = {"cohorts": 2, "per_language": 3, "seed": "s", **kwargs}
            return corpora.reserve_allocation(train, shared_ids=shared, **values)

        english = pick({"english": rows}, {"english": {101, 201}})["english"]
        self.assertEqual(english, pick({"english": list(reversed(rows))}, {"english": {101, 201}})["english"])
        sentences = [{row.sentence_id for row in cohort} for cohort in english]
        self.assertFalse(sentences[0] & sentences[1])
        chosen = {row.file for cohort in english for row in cohort}
        self.assertFalse(chosen & {"50001.wav", "50004.wav"})
        self.assertTrue(all(len(cohort) <= 3 for cohort in english))
        self.assertEqual(sum(len(cohort) for cohort in english), 6)
        others = {tuple(tuple(row.file for row in cohort) for cohort in pick({"english": rows}, {"english": {101}},
                                                                             seed=seed)["english"])
                  for seed in ("a", "b", "c", "d", "e")}
        self.assertGreater(len(others), 1)
        # Seven eligible recordings cannot fill three cohorts of three: the shortfall stays visible.
        short = pick({"english": rows}, {"english": set()}, cohorts=3)["english"]
        self.assertLess(min(len(cohort) for cohort in short), 3)

    def test_a_sentence_joins_one_cohort_in_every_language(self) -> None:
        """Rule v2: the allocation is global. Ten sentences, each read twice in each of three languages (one
        language's reading of sentence 7 shares dev, another's of sentence 8 has a digit), fill two cohorts of
        four recordings per language with no sentence in both, whatever the input order."""
        texts = {"english": "The river runs past the old mill.", "french": "La rivière passe devant le moulin.",
                 "german": "Der Fluss fließt an der Mühle vorbei."}
        train = {language: [n1.Row(sentence, f"{index}{sentence:02d}{take}.wav",
                                   "There were 3 boats." if (language, sentence) == ("german", 8) else text,
                                   1600, "female")
                            for sentence in range(1, 11) for take in range(2)]
                 for index, (language, text) in enumerate(texts.items(), 1)}
        shared = {"english": {7}, "french": set(), "german": set()}
        allocation = corpora.reserve_allocation(train, shared_ids=shared, cohorts=2, per_language=4, seed="g")
        reordered = corpora.reserve_allocation({language: list(reversed(rows)) for language, rows in
                                                reversed(list(train.items()))},
                                               shared_ids=shared, cohorts=2, per_language=4, seed="g")
        self.assertEqual(allocation, {language: reordered[language] for language in allocation})
        owner: dict[int, set[int]] = {}
        for language, cohorts in allocation.items():
            self.assertEqual([len(rows) for rows in cohorts], [4, 4], language)
            for index, rows in enumerate(cohorts):
                for row in rows:
                    owner.setdefault(row.sentence_id, set()).add(index)
        self.assertTrue(all(len(indexes) == 1 for indexes in owner.values()), owner)
        self.assertNotIn(7, {row.sentence_id for rows in allocation["english"] for row in rows})
        self.assertNotIn(8, {row.sentence_id for rows in allocation["german"] for row in rows})
        # The pool is three sentences short of a third cohort in each language: it falls short, never padded.
        three = corpora.reserve_allocation(train, shared_ids=shared, cohorts=3, per_language=8, seed="g")
        self.assertTrue(all(sum(len(rows) for rows in cohorts) <= 20 for cohorts in three.values()))
        self.assertLess(min(len(rows) for cohorts in three.values() for rows in cohorts), 8)
        scripts = [{row.sentence_id for cohorts in three.values() for row in cohorts[index]} for index in range(3)]
        self.assertFalse(scripts[0] & scripts[1] or scripts[0] & scripts[2] or scripts[1] & scripts[2])

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

    def prune(self, **kwargs) -> dict:
        with mock.patch.object(n1, "sources_digest", return_value="d" * 64):
            return quiet(corpora.prune_archives, self.registry, ["fleurs-train"], root=self.root,
                         n1_sources=self.n1_sources, now=lambda: "2026-09-30T12:00:00Z", **kwargs)

    def test_prune_removes_only_the_train_archives_once_every_reserve_cohort_verifies(self) -> None:
        with self.assertRaisesRegex(corpora.CorporaError, "removed nothing(.|\n)*cohort 1 is not extracted"):
            self.prune(dry_run=True)
        report = self.extract()
        receipt_path = f"fleurs/{REVISION}/{corpora.RECEIPT_NAME}"
        before = snapshot(self.root)
        archives = [f"data/{n1.FLEURS_CONFIGS[language]}/audio/train.tar.gz" for language in self.LANGUAGES]
        dry = self.prune(dry_run=True)
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual([item["path"] for item in dry["sources"][0]["files"]], archives)
        self.assertEqual(dry["reclaimBytes"], sum(len(self.train[path]) for path in archives))
        value = self.prune()
        self.assertEqual(value["reclaimBytes"], dry["reclaimBytes"])
        after = snapshot(self.root)
        # Only the train archives go: the train TSVs, the N1 dev and test files, the reserve recordings and cohorts
        # stay byte for byte; the receipt marks each archive pruned.
        self.assertEqual(set(before) - set(after), {f"fleurs/{REVISION}/{path}" for path in archives})
        self.assertEqual({path: data for path, data in after.items() if path != receipt_path},
                         {path: before[path] for path in after if path != receipt_path})
        self.assertTrue(all(f"fleurs/{REVISION}/{path}" in after for path in self.n1_files))
        receipt = json.loads((self.root / receipt_path).read_text())["files"]
        self.assertEqual({path for path, item in receipt.items() if "prunedAt" in item}, set(archives))
        # The reserve's receipts let `extract` skip the pruned archives, and `verify` reports them as pruned.
        again = self.extract()
        self.assertEqual([item["counts"] for item in again["cohorts"]], [item["counts"] for item in report["cohorts"]])
        with mock.patch.object(n1, "sources_digest", return_value="d" * 64):
            results = quiet(corpora.verify, self.registry, ["fleurs-train"], root=self.root,
                            n1_sources=self.n1_sources)
        self.assertEqual((results[0]["status"], results[0]["prunedFiles"]), ("PASS", 2))
        # Recordings that no longer match their receipt need the archive again: extract and prune both say fetch.
        french = self.corpus / corpora.RESERVE_DIRECTORY / report["samplingDigest"][:12] / \
            corpora.EXTRACTED_DIRECTORY / n1.FLEURS_CONFIGS["french"]
        next(french.glob("*.wav")).unlink()  # the cohort's hard link keeps the cohort itself whole
        with self.assertRaisesRegex(corpora.CorporaError, "was pruned after a verified reserve extraction.*"
                                                          "fetch --group fleurs-train"):
            self.extract()
        with self.assertRaisesRegex(corpora.CorporaError, "french reserve recordings do not match their extraction "
                                                          "receipt\\); run `fetch --source fleurs-train`"):
            self.prune(dry_run=True)


    def test_verify_names_a_reserve_of_an_earlier_rule(self) -> None:
        self.extract()
        earlier = self.corpus / corpora.RESERVE_DIRECTORY / "0123456789ab" / "cohort-1" / corpora.MANIFEST_NAME
        earlier.parent.mkdir(parents=True)
        earlier.write_text(json.dumps({"reserve": {"cohort": 1, "version": "audio-qc-fleurs-reserve-v1"}}))
        with mock.patch.object(n1, "sources_digest", return_value="d" * 64):
            results = quiet(corpora.verify, self.registry, ["fleurs-train"], root=self.root,
                            n1_sources=self.n1_sources)
        self.assertEqual(results[0]["status"], "PASS")
        self.assertEqual(len(results[0]["notes"]), 1)
        self.assertIn("reserve/0123456789ab holds cohorts sampled by audio-qc-fleurs-reserve-v1",
                      results[0]["notes"][0])
        self.assertIn("reserve-disjoint --reserve 0123456789ab", results[0]["notes"][0])


TOKENIZER = "e" * 64


def fake_roundtrip(run: Path, plan: dict) -> Path:
    """What the codec round trip writes for a plan: `<id>.wav` (24 kHz) and `<id>.codes.bin` beside its result."""
    out = run / "roundtrip"
    out.mkdir(parents=True, exist_ok=True)
    items = []
    for index, item in enumerate(plan["items"]):
        audio = pcm16(item["inputSampleCount"], 24_000, 300.0 + index)
        (out / f"{item['id']}.wav").write_bytes(audio)
        codes = b"VQCT" + item["id"].encode()
        (out / f"{item['id']}.codes.bin").write_bytes(codes)
        items.append({"id": item["id"], "inputSHA256": item["inputWAVSHA256"], "status": "complete",
                      "inputSampleCount": item["inputSampleCount"], "outputPath": f"{item['id']}.wav",
                      "outputSHA256": hashlib.sha256(audio).hexdigest(), "outputSampleCount": item["inputSampleCount"],
                      "clampedSampleCount": 0, "frameCount": 7, "codebookCount": 16,
                      "codesPath": f"{item['id']}.codes.bin", "codesSHA256": hashlib.sha256(codes).hexdigest()})
    result = {"schemaVersion": 1, "kind": n2.RESULT_KIND, "runID": "codec-roundtrip-x",
              "jobSHA256": plan["job"]["sha256"], "modelID": "pro_clone_speed", "modelRevision": REVISION,
              "tokenizerSHA256": TOKENIZER, "encoderInput": n2.ENCODER_INPUT, "decodeSemantics": n2.DECODE_SEMANTICS,
              "outputFormat": n2.OUTPUT_FORMAT, "sampleRate": n2.CODEC_RATE, "status": "complete",
              "modelLoadCount": 1, "items": items}
    path = out / "codec-roundtrip-result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    return path


class ReserveDisjointTests(Fixture):
    """`reserve-disjoint`: rule v1 cohorts sharing sentences across languages become script-disjoint subsets,
    their qc-n2 runs' matching takes a derived N2 manifest each, with every source untouched and every validator
    the N2 tooling, the calibration set and the detector driver apply passing."""

    # (cohort, language, sentence, file): rule v1 put sentence 501 in cohort 1 in English and cohort 2 in French.
    RECORDINGS = [
        (1, "english", 501, "50001.wav"), (1, "english", 502, "50002.wav"), (1, "french", 503, "60001.wav"),
        (1, "french", 504, "60002.wav"), (1, "english", 505, "50003.wav"), (1, "french", 506, "60003.wav"),
        (2, "french", 501, "60004.wav"), (2, "english", 503, "50004.wav"), (2, "english", 507, "50005.wav"),
        (2, "french", 508, "60005.wav"), (2, "english", 506, "50006.wav"), (2, "french", 509, "60006.wav"),
        (3, "english", 504, "50007.wav"), (3, "french", 505, "60007.wav"), (3, "english", 510, "50008.wav"),
        (3, "french", 511, "60008.wav"),
    ]
    TEXTS = {"english": "A small boat drifts across the quiet lake.",
             "french": "Le petit bateau glisse sur le lac tranquille."}
    SAMPLING = "f" * 64

    def setUp(self) -> None:
        super().setUp()
        self.registry = corpora.load_registry()
        self.reserve = corpora.source_directory(self.registry, "fleurs-train", self.root) / \
            corpora.RESERVE_DIRECTORY / self.SAMPLING[:12]
        sources = self.tmp / "extracted"
        sources.mkdir()
        cohorts: dict[int, list[dict]] = {}
        for index, (cohort, language, sentence, file) in enumerate(self.RECORDINGS):
            data = pcm16(1600 + 160 * index, 16_000, 200.0 + 10 * index)
            (sources / file).write_bytes(data)
            cohorts.setdefault(cohort, []).append({
                "row": n1.Row(sentence, file, self.TEXTS[language], 1600 + 160 * index, "female"),
                "language": language, "config": n1.FLEURS_CONFIGS[language], "source": sources / file,
                "digest": hashlib.sha256(data).hexdigest()})
        self.paths = {}
        with mock.patch.object(n1, "sources_digest", return_value="d" * 64):
            for cohort, members in cohorts.items():
                self.paths[cohort] = self.reserve / f"cohort-{cohort}" / corpora.MANIFEST_NAME
                corpora.write_reserve_manifest({"revision": REVISION}, members, output=self.paths[cohort],
                                               cohort=cohort, digest=self.SAMPLING,
                                               spec={"cohorts": 3, "perLanguage": 6, "seed": "s"}, identity="e" * 64)
        self.runs = {cohort: self.resynthesize(cohort) for cohort in (1, 2)}

    def resynthesize(self, cohort: int) -> Path:
        """A qc-n2 run of a reserve cohort: plan, round trip, manifest, as the lane writes them."""
        run = self.tmp / "artifacts" / f"qc-n2-run-{cohort}"
        quiet(n2.build_plan, n1_manifest=self.paths[cohort], out_dir=run, run_id=f"mac-qc-n2-{cohort}")
        n2.build_manifest(plan_path=run / n2.PLAN_NAME, result_path=fake_roundtrip(run, json.loads(
            (run / n2.PLAN_NAME).read_text())), output=run / corpora.N2_MANIFEST_NAME)
        return run

    def derive(self, cohorts=(1, 2), **kwargs) -> dict:
        values = {"reserve": self.SAMPLING[:12], "cohorts": cohorts, "n2_runs": self.runs, "root": self.root, **kwargs}
        return corpora.derive_disjoint_cohorts(self.registry, "fleurs-train", **values)

    def owner(self, script: str, cohorts=(1, 2)) -> int:
        reading = [cohort for cohort in cohorts
                   if any(take["scriptID"] == script for take in self.source(cohort)["takes"])]
        return corpora.disjoint_owner(script, reading, seed=corpora.DISJOINT_SEED)

    def source(self, cohort: int) -> dict:
        return json.loads(self.paths[cohort].read_text())

    def test_derivation_keeps_each_shared_script_in_one_cohort_and_every_source_untouched(self) -> None:
        before = snapshot(self.tmp)
        dry = self.derive(dry_run=True)
        self.assertEqual(snapshot(self.tmp), before)
        self.assertEqual((dry["status"], dry["sharedScripts"]), ("dry-run", 3))
        self.assertEqual(dry["sourceOverlaps"]["1-2"], {"scripts": 3, "families": 0, "speakers": 0})
        self.assertEqual(dry["overlaps"]["1-2"], {"scripts": 0, "families": 0, "speakers": 0})
        report = self.derive()
        self.assertEqual({path: data for path, data in snapshot(self.tmp).items() if path in before}, before)
        self.assertEqual({key: value for key, value in report.items() if key != "status"},
                         {key: value for key, value in dry.items() if key != "status"})
        derived = {}
        for item in report["derived"]:
            cohort, path = item["cohort"], Path(item["manifest"])
            self.assertEqual(path.parent.parent, self.reserve / corpora.DISJOINT_DIRECTORY /
                             report["derivationDigest"][:12])
            manifest = json.loads(path.read_text())
            source = self.source(cohort)
            derived[cohort] = manifest
            self.assertEqual(n1.manifest_digest_issues(manifest), [])
            kept = [take for take in source["takes"] if self.owner(take["scriptID"]) == cohort]
            self.assertEqual(manifest["takes"], kept)
            self.assertEqual(manifest["counts"], n1.cohort_counts(kept))
            self.assertEqual({key: manifest[key] for key in ("split", "fleursSplit", "reserve")},
                             {key: source[key] for key in ("split", "fleursSplit", "reserve")})
            self.assertEqual({key: manifest["derivedFrom"][key] for key in
                              ("version", "rule", "seed", "cohorts", "manifestDigest", "manifestSHA256", "takes")},
                             {"version": corpora.DISJOINT_VERSION, "rule": corpora.DISJOINT_RULE,
                              "seed": corpora.DISJOINT_SEED, "cohorts": [1, 2],
                              "manifestDigest": source["manifestDigest"],
                              "manifestSHA256": hashlib.sha256(self.paths[cohort].read_bytes()).hexdigest(),
                              "takes": len(source["takes"])})
            for take in kept:
                self.assertEqual(hashlib.sha256((path.parent / take["wavPath"]).read_bytes()).hexdigest(),
                                 take["wavSHA256"])
            eligible, count = n2.eligible_recordings(manifest)
            self.assertEqual(len(eligible), count)
        scripts = [{take["scriptID"] for take in derived[cohort]["takes"]} for cohort in (1, 2)]
        self.assertFalse(scripts[0] & scripts[1])
        self.assertEqual(sum(len(value["takes"]) for value in derived.values()), 12 - 3)
        # Deriving again is a no-op; another seed writes its own directory.
        self.assertEqual(self.derive(), report)
        other = self.derive(seed="another-seed")
        self.assertNotEqual(other["output"], report["output"])

    def test_derived_n2_manifests_pass_the_n2_calibration_set_and_driver_checks(self) -> None:
        import audio_qc_calibration_set as calibration_set
        import audio_qc_detector_calibration as calibration
        from lib.qc_qualification import thresholds

        report = self.derive()
        cohorts = {}
        for item in report["derived"]:
            cohort, n1_path, n2_path = item["cohort"], Path(item["manifest"]), Path(item["n2"]["manifest"])
            run = self.runs[cohort]
            self.assertEqual(n2_path.parent.name, f"{run.name}-disjoint-{report['derivationDigest'][:12]}")
            manifest = json.loads(n2_path.read_text())
            source = json.loads((run / corpora.N2_MANIFEST_NAME).read_text())
            kept = {take["takeID"] for take in json.loads(n1_path.read_text())["takes"]}
            self.assertEqual(manifest["takes"], [take for take in source["takes"] if take["n1TakeID"] in kept])
            self.assertEqual(manifest["n1ManifestSHA256"], hashlib.sha256(n1_path.read_bytes()).hexdigest())
            self.assertEqual((manifest["derivedFrom"]["manifestDigest"], manifest["derivedFrom"]["n1ManifestSHA256"],
                              manifest["runID"], manifest["planDigest"]),
                             (source["manifestDigest"], source["n1ManifestSHA256"], source["runID"],
                              source["planDigest"]))
            plan = json.loads((run / n2.PLAN_NAME).read_text())
            for checked in (n2.validate_manifest(manifest, manifest_dir=n2_path.parent),
                            n2.validate_manifest(manifest, manifest_dir=n2_path.parent, plan=plan)):
                self.assertEqual(checked["status"], "PASS", checked["errors"])
            self.assertEqual(n2.manifest_digest_issues(manifest), [])
            calibration_set.load_takes(n2_path)
            cohort_value = calibration.load_cohort(n2_path)
            self.assertEqual(calibration.resolve_cohort(cohort_value, n1_path), f"reserve-{cohort}")
            cohorts[cohort] = cohort_value
            # A derived manifest whose takes leave plan order is refused against its plan.
            shuffled = {**manifest, "takes": list(reversed(manifest["takes"]))}
            shuffled["manifestDigest"] = n2.self_digest(shuffled, "manifestDigest")
            checked = n2.validate_manifest(shuffled, manifest_dir=n2_path.parent, plan=plan)
            self.assertIn("the derived manifest's takes are not items of its plan in plan order", checked["errors"])
        # The driver's declared split (FLEURS: family and script) holds on the derived cohorts, not the sources.
        split = SimpleNamespace(cohorts=SimpleNamespace(disjoint_by=calibration.FLEURS_RULE.disjoint_by))
        thresholds.check_cohort_disjointness(split, calibration._triples(cohorts[1]), calibration._triples(cohorts[2]))
        sources = {cohort: calibration.load_cohort(run / corpora.N2_MANIFEST_NAME) for cohort, run in self.runs.items()}
        with self.assertRaisesRegex(thresholds.PreRegistrationError, "the cohorts share 3 script value"):
            thresholds.check_cohort_disjointness(split, calibration._triples(sources[1]),
                                                 calibration._triples(sources[2]))

    def test_three_cohorts_and_a_cohort_without_a_run(self) -> None:
        report = self.derive(cohorts=(1, 2, 3))
        self.assertEqual([("n2" in item) for item in report["derived"]], [True, True, False])
        scripts = [{take["scriptID"] for take in json.loads(Path(item["manifest"]).read_text())["takes"]}
                   for item in report["derived"]]
        self.assertFalse(scripts[0] & scripts[1] or scripts[0] & scripts[2] or scripts[1] & scripts[2])
        self.assertEqual(report["sharedScripts"], 5)
        self.assertNotEqual(report["derivationDigest"], self.derive(dry_run=True)["derivationDigest"])

    def test_refusals(self) -> None:
        with self.assertRaisesRegex(corpora.CorporaError, "two or more reserve cohorts"):
            self.derive(cohorts=(1,))
        with self.assertRaisesRegex(corpora.CorporaError, "outside"):
            self.derive(n2_runs={3: self.runs[1]})
        # A run of another cohort resynthesized another N1 manifest.
        with self.assertRaisesRegex(n2.N2Error, "does not derive from the N1 manifest this run resynthesized"):
            self.derive(n2_runs={1: self.runs[2]}, dry_run=True)
        # A tampered source run fails its own validation first.
        wav = next((self.runs[1] / "roundtrip").glob("*.wav"))
        original = wav.read_bytes()
        wav.write_bytes(original[:-2] + b"\x01\x00")
        with self.assertRaisesRegex(n2.N2Error, "the source N2 manifest does not validate"):
            self.derive(dry_run=True)
        wav.write_bytes(original)
        # Never over another derivation's manifest.
        output = self.tmp / "derived"
        self.derive(output=output, n2_runs={})
        (output / "cohort-1" / corpora.MANIFEST_NAME).write_text("{}")
        with self.assertRaisesRegex(corpora.CorporaError, "already holds another manifest"):
            self.derive(output=output, n2_runs={})
        # A derived cohort is never a source.
        derived = self.tmp / "derived-once"
        self.derive(output=derived, n2_runs={})
        with self.assertRaisesRegex(corpora.CorporaError, "itself derived"):
            self.derive(reserve=str(derived), n2_runs={}, dry_run=True)

    def test_command_line(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = corpora.main(["reserve-disjoint", "--reserve", str(self.reserve), "--cohorts", "1,2",
                                 "--n2", f"1={self.runs[1]}", "--n2", f"2={self.runs[2] / corpora.N2_MANIFEST_NAME}",
                                 "--dry-run"])
        self.assertEqual(code, 0)
        value = json.loads(out.getvalue())
        self.assertEqual(value["status"], "dry-run")
        self.assertEqual([item["n2"]["takes"] for item in value["derived"]],
                         [item["recordings"] for item in value["derived"]])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            corpora.main(["reserve-disjoint", "--reserve", str(self.reserve), "--cohorts", "1"])


class LabelledCohortTests(Fixture):
    """speechocean762's extraction as the N1 cohorts of language.nativeness@1's natural positives: split by
    speaker, every utterance with its speaker, scores and text, read by the N2 plan and the detector driver."""

    SPEAKERS = 12

    def setUp(self) -> None:
        super().setUp()
        self.registry = corpora.load_registry()
        self.extracted = corpora.source_directory(self.registry, "speechocean762", self.root) / \
            corpora.EXTRACTED_DIRECTORY

    def extract(self, *, per_speaker: int = 5) -> dict:
        """A synthetic extraction: per speaker, utterances scored 3 (severe), 6 (moderate) and 8 (outside), one of
        the first speaker's with an empty transcript and one with no score."""
        sink = clips.ClipSink(self.extracted / "wav")
        for speaker in range(self.SPEAKERS):
            for index in range(per_speaker):
                source_id = f"{speaker:04d}{index:04d}"
                data = pcm16(1600 + 16 * index + speaker, 16_000, 200.0 + speaker)
                clip, info = clips.clip_from_wav(data, output_rate=16_000)
                accuracy = (3, 6, 8)[index % 3]
                text = "" if (speaker, index) == (0, 3) else "MARK IS GOING TO SEE ELEPHANT"
                scores = {"accuracy": None if (speaker, index) == (0, 4) else accuracy, "completeness": 10,
                          "fluency": 7, "prosodic": 7, "total": accuracy}
                labels = {"language": "english", "split": "train" if speaker % 2 else "test", "sourceID": source_id,
                          "speaker": f"{speaker:04d}", "gender": "female", "accent": "mandarin-l1",
                          "scores": scores, "text": text}
                sink.add(clips.clip_id("speechocean762", source_id), clip, info, labels, origin=f"row#{source_id}",
                         source_sha256=hashlib.sha256(data).hexdigest())
        manifest = corpora.build_manifest(self.registry, "speechocean762", sink.clips, sink.skipped, metadata={},
                                          members={})
        (self.extracted / corpora.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    def build(self, split: str, **options) -> dict:
        return corpora.labelled_cohort(self.registry, "speechocean762", split=split, root=self.root, **options)

    def test_a_missing_extraction_is_refused_with_the_commands_to_run(self) -> None:
        with self.assertRaisesRegex(corpora.CorporaError, "not extracted.*fetch --source speechocean762"):
            self.build("confirmation")
        with self.assertRaisesRegex(corpora.CorporaError, "no labelled cohort rule"):
            corpora.labelled_cohort(self.registry, "crema-d", split="confirmation", root=self.root)

    def test_the_splits_share_no_speaker_and_keep_every_label(self) -> None:
        self.extract()
        confirmation, calibration = self.build("confirmation"), self.build("calibration")
        speakers = [{take["speaker"] for take in manifest["takes"]} for manifest in (confirmation, calibration)]
        self.assertFalse(speakers[0] & speakers[1])
        self.assertEqual(len(speakers[0] | speakers[1]), self.SPEAKERS)
        self.assertEqual(confirmation["speakerSplit"]["speakers"], {"calibration": 6, "confirmation": 6})
        for manifest, split in ((confirmation, "confirmation"), (calibration, "calibration")):
            self.assertEqual(n1.manifest_digest_issues(manifest), [])
            self.assertEqual((manifest["kind"], manifest["split"], manifest["corpus"], manifest.get("fleursSplit")),
                             (n1.MANIFEST_KIND, split, "speechocean762", None))
            eligible, count = n2.eligible_recordings(manifest)
            self.assertEqual(count, 30)
            directory = corpora.cohort_path(self.registry, "speechocean762", split=split, share=0.5,
                                            root=self.root).parent
            for take in manifest["takes"]:
                self.assertEqual(hashlib.sha256((directory / take["wavPath"]).read_bytes()).hexdigest(),
                                 take["wavSHA256"])
                self.assertEqual((take["population"], take["language"], take["accent"]), ("N1", "english",
                                                                                          "mandarin-l1"))
        takes = {take["recording"]["sourceID"]: take for take in
                 [*confirmation["takes"], *calibration["takes"]]}
        self.assertEqual(takes["00000003"]["ineligibleReasons"], ["emptyText"])
        self.assertEqual(takes["00000004"]["ineligibleReasons"], ["noLabel"])
        self.assertEqual(takes["00010000"]["scores"]["accuracy"], 3)
        # One sentence read by every speaker is one script.
        self.assertEqual(len({take["scriptID"] for take in takes.values() if take["text"]}), 1)
        # The counts follow the label rule of the role set language.nativeness@1 names (4 or less severe, 5-6
        # moderate), over each split's eligible utterances.
        counts = confirmation["labels"]["bySplit"]
        self.assertEqual(counts, calibration["labels"]["bySplit"])
        self.assertEqual(sum(counts["confirmation"].values()) + sum(counts["calibration"].values()), 58)
        # Two severe utterances per speaker, less the first speaker's with an empty transcript.
        self.assertEqual(sum(value["severe"] for value in counts.values()), 23)
        self.assertEqual(confirmation["labels"]["field"], "scores.accuracy")
        summary = corpora.labelled_summary(confirmation, Path("manifest.json"))
        self.assertIn("below the warn floor of 60", summary["warning"])
        # A rebuild writes the same manifest; another share into the same directory is refused.
        self.assertEqual(self.build("confirmation")["manifestDigest"], confirmation["manifestDigest"])
        output = corpora.cohort_path(self.registry, "speechocean762", split="confirmation", share=0.5, root=self.root)
        with self.assertRaisesRegex(corpora.CorporaError, "already holds another cohort"):
            self.build("confirmation", share=0.25, output=output)
        wider = self.build("confirmation", share=0.75)
        self.assertEqual(wider["speakerSplit"]["speakers"], {"calibration": 3, "confirmation": 9})
        self.assertTrue(speakers[0] <= {take["speaker"] for take in wider["takes"]})

    def test_the_detector_driver_reads_the_split_speakers_and_labels(self) -> None:
        import audio_qc_detector_calibration as calibration
        from lib.qc_qualification import detectors as registry_lib

        self.extract()
        manifest = self.build("confirmation")
        n1_path = corpora.cohort_path(self.registry, "speechocean762", split="confirmation", share=0.5, root=self.root)
        takes = [{"takeID": f"{take['takeID']}--n2", "n1TakeID": take["takeID"], "population": "N2",
                  "family": take["family"], "scriptID": take["scriptID"], "language": take["language"],
                  "textSHA256": take["textSHA256"], "wavSHA256": hashlib.sha256(take["takeID"].encode()).hexdigest(),
                  "eligible": True} for take in manifest["takes"] if take["eligible"]]
        n2_manifest = {"kind": n2.MANIFEST_KIND, "schemaVersion": 1, "runID": "n2-accent",
                       "n1ManifestSHA256": hashlib.sha256(n1_path.read_bytes()).hexdigest(), "takes": takes}
        n2_manifest["manifestDigest"] = corpora.jsonio.sha256_json(n2_manifest, ascii=False)
        n2_path = self.tmp / "n2-manifest.json"
        n2_path.write_text(json.dumps(n2_manifest), encoding="utf-8")
        registry = json.loads(corpora.DETECTOR_REGISTRY_PATH.read_text(encoding="utf-8"))
        entry = registry_lib.detector_entry(registry, "language.nativeness@1")
        natural = calibration.load_natural_positives(entry, registry_lib.role_set(registry, entry), n2_path, n1_path)
        self.assertEqual((natural["split"], natural["cohort"]["corpus"]), ("confirmation", "speechocean762"))
        # The target declares the severe cell: the moderate and outside utterances are outside the rule.
        counts = manifest["labels"]["bySplit"]["confirmation"]
        self.assertEqual((len(natural["severities"]), natural["outsideRule"]),
                         (counts["severe"], counts["moderate"] + counts["outside"]))
        self.assertEqual(len({take["speaker"] for take in natural["cohort"]["takes"].values()}), 6)
        policy = json.loads(corpora.POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(calibration.natural_label_problems(policy, entry, natural), [])


class SpeakerCohortTests(Fixture):
    """The class E speaker cohort over synthetic extractions of the four sources it reads: speaker- and
    script-disjoint splits, the eligibility rules, one reference clip per take, and the N1 shape the N2 plan
    and the detector driver read."""

    SECONDS = 4.5

    def setUp(self) -> None:
        super().setUp()
        self.registry = corpora.load_registry()

    def extract(self, source: str, rows: list[tuple]) -> dict:
        """rows: (language, speaker, text, seconds, gender); one clip each, a tone of its own frequency."""
        rate = self.registry["sources"][source]["extract"]["outputRate"]
        directory = corpora.source_directory(self.registry, source, self.root) / corpora.EXTRACTED_DIRECTORY
        sink = clips.ClipSink(directory / "wav")
        for index, (language, speaker, text, seconds, gender) in enumerate(rows):
            source_id = f"{speaker}_{index:04d}"
            data = pcm16(int(seconds * rate), rate, 120.0 + 3.0 * index)
            clip, info = clips.clip_from_wav(data, output_rate=rate)
            labels = {"language": language, "split": "test", "sourceID": source_id, "speaker": speaker,
                      "gender": gender, "text": text}
            sink.add(clips.clip_id(source, source_id), clip, info, labels, origin=f"row#{index}",
                     source_sha256=hashlib.sha256(data).hexdigest())
        manifest = corpora.build_manifest(self.registry, source, sink.clips, sink.skipped, metadata={}, members={})
        (directory / corpora.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    def readings(self, language: str, speakers: int, per_speaker: int, *, gendered: bool = True,
                 prefix: str | None = None) -> list[tuple]:
        prefix = prefix or language[:2]
        return [(language, f"{prefix}{speaker}", f"{language} {speaker} reads sentence {reading}.", self.SECONDS,
                 ("female", "male")[speaker % 2] if gendered else None)
                for speaker in range(speakers) for reading in range(per_speaker)]

    def extract_all(self) -> None:
        english = self.readings("english", 6, 3, gendered=False)
        english += [("english", "en0", "too short", 2.0, None), ("english", "en1", "", self.SECONDS, None),
                    # One speaker reads one sentence twice: no reference with another script.
                    ("english", "en9", "once again", self.SECONDS, None),
                    ("english", "en9", "Once  again", self.SECONDS, None)]
        self.extract("libritts-r", english)
        # A reader of German and French is one speaker, whose split follows the language it reads most.
        mls = self.readings("german", 6, 3) + self.readings("french", 6, 3)
        mls += [("german", "multi", f"multi reads {index}", self.SECONDS, "female") for index in range(3)]
        mls += [("french", "multi", "multi lit une phrase", self.SECONDS, "female")]
        self.extract("mls", mls)
        # One speaker reads 12 sentences: the cap keeps 10.
        self.extract("aishell3-subset", self.readings("chinese", 6, 3)
                     + [("chinese", "zh-many", f"zh many {index}", self.SECONDS, "female") for index in range(12)])
        # Every Korean speaker reads the same three sentences and two of its own: a script lives in one split.
        self.extract("zeroth-korean", [("korean", f"ko{speaker}", text, self.SECONDS, None) for speaker in range(8)
                                       for text in (*(f"korean sentence {reading}" for reading in range(3)),
                                                    f"ko{speaker} alone 1", f"ko{speaker} alone 2")])

    def build(self, split: str, **options) -> dict:
        return corpora.speaker_cohort(self.registry, split=split, root=self.root, **options)

    def test_a_missing_extraction_is_refused_with_the_commands_to_run(self) -> None:
        with self.assertRaisesRegex(corpora.CorporaError, "aishell3-subset is not extracted.*extract --source"):
            self.build("confirmation")

    def test_the_splits_share_no_speaker_or_script_and_every_take_names_a_reference(self) -> None:
        self.extract_all()
        confirmation, calibration = self.build("confirmation"), self.build("calibration")
        for manifest, split in ((confirmation, "confirmation"), (calibration, "calibration")):
            self.assertEqual(n1.manifest_digest_issues(manifest), [])
            self.assertEqual((manifest["kind"], manifest["split"], manifest["corpus"], manifest.get("fleursSplit")),
                             (n1.MANIFEST_KIND, split, corpora.SPEAKER_CORPUS, None))
            eligible, _count = n2.eligible_recordings(manifest)
            self.assertTrue(eligible)
            directory = corpora.speaker_cohort_path(self.registry, split=split, share=0.5, root=self.root).parent
            by_id = {take["takeID"]: take for take in manifest["takes"]}
            for take in manifest["takes"]:
                self.assertEqual(hashlib.sha256((directory / take["wavPath"]).read_bytes()).hexdigest(),
                                 take["wavSHA256"])
                self.assertRegex(take["speaker"], r"^[a-z0-9-]+:[0-9a-f]{16}$")
                if not take["eligible"]:
                    self.assertNotIn("reference", take)
                    continue
                reference = by_id[take["reference"]["takeID"]]
                self.assertTrue(reference["eligible"])
                self.assertEqual(reference["speaker"], take["speaker"])
                self.assertNotEqual(reference["scriptID"], take["scriptID"])
                self.assertEqual((take["reference"]["wavPath"], take["reference"]["wavSHA256"]),
                                 (reference["wavPath"], reference["wavSHA256"]))
                # A speaker's takes cycle: never a mutual pair when three or more read distinct scripts.
                mine = [other["scriptID"] for other in manifest["takes"] if other["eligible"]
                        and other["speaker"] == take["speaker"]]
                if len(mine) > 2 and len(set(mine)) == len(mine):
                    self.assertNotEqual(reference["reference"]["takeID"], take["takeID"])
        takes = {split: [take for take in manifest["takes"] if take["eligible"]]
                 for split, manifest in (("confirmation", confirmation), ("calibration", calibration))}
        for key in ("speaker", "scriptID", "family"):
            shared = {take[key] for take in takes["confirmation"]} & {take[key] for take in takes["calibration"]}
            self.assertFalse(shared, key)
        every = [*confirmation["takes"], *calibration["takes"]]
        reasons = Counter(reason for take in every for reason in take["ineligibleReasons"])
        self.assertEqual((reasons["duration"], reasons["emptyText"], reasons["speakerCap"], reasons["noReference"]),
                         (1, 1, 2, 2))
        # Korean: each shared sentence stays in one split, so the other split's readings of it are out.
        korean = [take for take in every if take["language"] == "korean"]
        self.assertTrue(any("sharedScript" in take["ineligibleReasons"] for take in korean))
        self.assertTrue(all(take["ineligibleReasons"] in ([], ["sharedScript"]) for take in korean))
        # The German and French reader is one speaker in one split.
        multi = {take["language"]: take for take in every if take["recording"]["sourceID"].startswith("multi_")}
        self.assertEqual(len({take["speaker"] for take in multi.values()}), 1)
        self.assertEqual(sum(1 for split in takes.values() if any(take["speaker"] == multi["german"]["speaker"]
                                                                  for take in split)), 1)
        # Gender where the corpus labels it, never a guess; English and Korean carry none.
        self.assertEqual({take["gender"] for take in every if take["language"] in ("english", "korean")}, {None})
        self.assertEqual({take["gender"] for take in every if take["language"] == "german"}, {"female", "male"})
        self.assertEqual(confirmation["byLanguage"], calibration["byLanguage"])
        self.assertEqual(set(confirmation["byLanguage"]["confirmation"]),
                         {"english", "german", "french", "chinese", "korean"})
        summary = corpora.speaker_summary(confirmation, Path("manifest.json"))
        self.assertIn("below the warn floors", summary["warning"])
        self.assertEqual(summary["speakers"], confirmation["speakerSplit"]["speakers"])
        # A rebuild writes the same manifest; the default directory is named by what the cohort is drawn from.
        self.assertEqual(self.build("confirmation")["manifestDigest"], confirmation["manifestDigest"])
        self.assertEqual(confirmation["speakerSplit"]["samplingSHA256"], calibration["speakerSplit"]["samplingSHA256"])
        output = corpora.speaker_cohort_path(self.registry, split="confirmation", share=0.5, root=self.root)
        self.assertEqual(output.parts[-5], corpora.SPEAKER_COHORT_DIRECTORY)
        with self.assertRaisesRegex(corpora.CorporaError, "already holds another cohort"):
            self.build("confirmation", share=0.25, output=output)

    def test_the_detector_driver_reads_the_corpus_the_role_set_names(self) -> None:
        import audio_qc_detector_calibration as calibration

        self.extract_all()
        manifest = self.build("calibration")
        path = corpora.speaker_cohort_path(self.registry, split="calibration", share=0.5, root=self.root)
        cohort = calibration.load_cohort(path)
        self.assertEqual(calibration.resolve_cohort(cohort, None), "calibration")
        self.assertEqual(cohort["corpus"], corpora.SPEAKER_CORPUS)
        registry = json.loads(corpora.DETECTOR_REGISTRY_PATH.read_text(encoding="utf-8"))
        roles = registry["roleSets"][corpora.SPEAKER_ROLE_SET]
        self.assertEqual((roles["fit"]["corpus"], roles["confirmNegatives"]["corpus"]),
                         (f"{corpora.SPEAKER_CORPUS}-calibration", f"{corpora.SPEAKER_CORPUS}-confirmation"))
        # Speakers are digests of the corpus and the (already anonymized) label.
        self.assertEqual(len({take["speaker"] for take in cohort["takes"].values()}),
                         len({take["speaker"] for take in manifest["takes"] if take["eligible"]}))
        referenced = [take for take in cohort["takes"].values() if take["referenceSHA256"]]
        self.assertEqual(len(referenced), len(cohort["takes"]))
        # Every excluded language has a reason, and the in-scope languages are the ones a corpus covers.
        self.assertEqual(set(corpora.SPEAKER_SOURCES) | set(corpora.SPEAKER_EXCLUDED_LANGUAGES),
                         set(corpora.lm.PRODUCT_LANGUAGES))
        for detector in ("identity.clone-similarity@1", "identity.window-drift@1", "identity.onset-drift@1"):
            entry = next(item for item in registry["detectors"] if item["id"] == detector)
            self.assertEqual(sorted(entry["scope"]["languages"]), sorted(corpora.SPEAKER_SOURCES))
            self.assertEqual({item["language"] for item in entry["scope"]["exclusions"]},
                             set(corpora.SPEAKER_EXCLUDED_LANGUAGES))

    def test_the_selection_on_its_own_counts_both_splits_without_writing(self) -> None:
        self.extract_all()
        extractions = corpora.speaker_extractions(self.registry, root=self.root)
        splits = corpora.speaker_selection({source: manifest for source, (_directory, manifest)
                                            in extractions.items()}, share=0.5)
        wider = corpora.speaker_selection({source: manifest for source, (_directory, manifest)
                                           in extractions.items()}, share=0.75)
        self.assertGreater(sum(take["eligible"] for take in wider["confirmation"]),
                           sum(take["eligible"] for take in splits["confirmation"]))
        with self.assertRaisesRegex(corpora.CorporaError, "strictly between"):
            corpora.speaker_selection({}, share=1.0)
        self.assertFalse(corpora.speaker_cohort_path(self.registry, split="calibration", share=0.5,
                                                     root=self.root).exists())


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
