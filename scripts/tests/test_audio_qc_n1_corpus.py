#!/usr/bin/env python3
"""AQ-07 N1: pinned FLEURS acquisition, safe extraction, cohort manifests and their consumers.

No network and no FLEURS data. Every corpus here is synthetic: TSVs and
tar.gz archives of generated 16 kHz WAVs built in a temporary directory and
pinned by their own sizes and digests, served through a fake opener. One test
validates the committed sources file (`config/audio-qc-n1-sources.json`), as
the contract gate does.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.error
import urllib.request
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import acquire_audio_qc_judges as acquire  # noqa: E402
import audio_qc_calibration_set as m2  # noqa: E402
import audio_qc_n1_corpus as n1  # noqa: E402
import audio_qc_orchestrator as orchestrator  # noqa: E402
from lib.qc_qualification import pcm, recordings  # noqa: E402

REVISION = "0123456789abcdef0123456789abcdef01234567"
LANGUAGES = ("english", "french")
RATE = 16_000
# (FLoRes sentence id, file, raw transcription, samples, gender) per language and FLEURS split.
ROWS = {
    ("english", "dev"): [
        (101, "10001.wav", "The quiet river runs past the old mill.", 40_000, "MALE"),
        (102, "10002.wav", "There were 3 boats on the lake that morning.", 36_000, "FEMALE"),
        (103, "10003.wav", "Yesterday we met Robin at the market.", 34_000, "FEMALE"),
        (104, "10004.wav", "The same sentence is read in both splits.", 38_000, "OTHER"),
    ],
    ("english", "test"): [
        (104, "20001.wav", "The same sentence is read in both splits.", 37_000, "MALE"),
        (201, "20002.wav", "Birds sing softly in the early morning light.", 39_000, "MALE"),
    ],
    ("french", "dev"): [
        (301, "30001.wav", "Le petit chat dort sur le rebord de la fenêtre.", 41_000, "FEMALE"),
    ],
    ("french", "test"): [
        (401, "40001.wav", "Nous avons marché le long de la rivière.", 35_000, "MALE"),
    ],
}


def quiet(function, *args, **kwargs):
    with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
        return function(*args, **kwargs)


def tone(samples: int, frequency: float) -> np.ndarray:
    time = np.arange(samples) / RATE
    envelope = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(samples) / max(samples - 1, 1))
    return 0.3 * envelope * (np.sin(2.0 * np.pi * frequency * time) + 0.3 * np.sin(2.0 * np.pi * 3.1 * frequency * time))


def wav_bytes(samples: int, *, frequency: float = 180.0, rate: int = RATE, channels: int = 1) -> bytes:
    values = np.clip(np.round(tone(samples, frequency) * 32767.0), -32768, 32767).astype("<i2")
    if channels == 2:
        values = np.repeat(values, 2)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(values.tobytes())
    return buffer.getvalue()


def tsv_bytes(rows) -> bytes:
    lines = []
    for sentence, file, text, samples, gender in rows:
        normalized = text.lower().rstrip(".")
        lines.append("\t".join((str(sentence), file, text, normalized, "|".join(normalized.split()), str(samples),
                                gender)))
    return ("\n".join(lines) + "\n").encode("utf-8")


def tar_gz(members) -> bytes:
    """Members are (name, data) regular files, or TarInfo objects added as they are."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for member in members:
            if isinstance(member, tarfile.TarInfo):
                bundle.addfile(member)
                continue
            name, data = member
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            bundle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def directory_member(name: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    return info


def split_members(language: str, split: str) -> list:
    return [directory_member(split), *[(f"{split}/{file}", wav_bytes(samples, frequency=150.0 + 10 * index))
                                       for index, (_s, file, _t, samples, _g) in enumerate(ROWS[(language, split)])]]


def corpus_files(overrides: dict | None = None) -> dict[str, bytes]:
    files = {}
    for language in LANGUAGES:
        config = n1.FLEURS_CONFIGS[language]
        for split in n1.SPLIT_ROLES:
            files[f"data/{config}/{split}.tsv"] = tsv_bytes(ROWS[(language, split)])
            files[f"data/{config}/audio/{split}.tar.gz"] = tar_gz(split_members(language, split))
    files.update(overrides or {})
    return files


def make_sources(files: dict[str, bytes]) -> dict:
    languages = []
    total = 0
    for language in LANGUAGES:
        config = n1.FLEURS_CONFIGS[language]
        splits = []
        for split, role in n1.SPLIT_ROLES.items():
            tsv, archive = f"data/{config}/{split}.tsv", f"data/{config}/audio/{split}.tar.gz"
            splits.append({"split": split, "role": role,
                           "tsv": {"path": tsv, "size": len(files[tsv]), "gitBlobSHA1": n1.git_blob_sha1(files[tsv])},
                           "archive": {"path": archive, "size": len(files[archive]),
                                       "sha256": hashlib.sha256(files[archive]).hexdigest()}})
            total += len(files[tsv]) + len(files[archive])
        languages.append({"language": language, "config": config, "splits": splits})
    return {
        "schemaVersion": n1.SCHEMA_VERSION, "kind": n1.SOURCES_KIND, "description": n1.DESCRIPTION,
        "population": n1.POPULATION, "dataset": n1.DATASET, "revision": REVISION, "host": n1.HUB_HOST,
        "license": n1.LICENSE, "attribution": n1.ATTRIBUTION, "sampleRate": n1.SAMPLE_RATE,
        "tsvColumns": list(n1.TSV_COLUMNS), "disjointness": n1.DISJOINTNESS, "limitations": n1.LIMITATIONS,
        "languages": languages, "totals": {"files": 4 * len(LANGUAGES), "bytes": total},
    }


def url(path: str) -> str:
    return f"https://huggingface.co/datasets/google/fleurs/resolve/{REVISION}/{path}"


class FakeResponse:
    def __init__(self, status: int, payload: bytes, start: int, total: int, cut: int | None) -> None:
        self.status = status
        self.headers = {"Content-Range": f"bytes {start}-{total - 1}/{total}"} if status == 206 else {}
        self._payload = payload
        self._position = 0
        self._cut = cut

    def read(self, size: int = -1) -> bytes:
        if self._cut is not None and self._position >= self._cut:
            raise ConnectionResetError("fixture drop")
        end = len(self._payload) if size < 0 else self._position + size
        if self._cut is not None:
            end = min(end, self._cut)
        block = self._payload[self._position:end]
        self._position += len(block)
        return block

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_details) -> None:
        return None


class FakeHub:
    """Serves fixture bytes by URL; can drop a transfer or go offline."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = {url(path): data for path, data in files.items()}
        self.requests: list[tuple[str, str | None]] = []
        self.cut: dict[str, int] = {}
        self.offline = False

    def __call__(self, request, timeout):
        self.requests.append((request.full_url, request.get_header("Range")))
        if self.offline:
            raise AssertionError("the network was used")
        if request.full_url not in self.files:
            raise urllib.error.HTTPError(request.full_url, 404, "fixture", {}, None)
        body = self.files[request.full_url]
        header = request.get_header("Range")
        start, status = (int(header.split("=")[1].rstrip("-")), 206) if header else (0, 200)
        return FakeResponse(status, body[start:], start, len(body), self.cut.pop(request.full_url, None))


class CorpusFixture(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)
        self.root = self.tmp / "cache"
        margin = mock.patch.object(n1, "FREE_SPACE_MARGIN_BYTES", 0)
        margin.start()
        self.addCleanup(margin.stop)
        self.files = corpus_files()
        self.sources = make_sources(self.files)
        self.corpus = self.root / REVISION

    def place(self, files: dict[str, bytes] | None = None) -> None:
        for path, data in (files or self.files).items():
            (self.corpus / path).parent.mkdir(parents=True, exist_ok=True)
            (self.corpus / path).write_bytes(data)

    def extracted(self) -> None:
        self.place()
        quiet(n1.extract, self.sources, root=self.root)


# --------------------------------------------------------------------------- #
# Sources and pins
# --------------------------------------------------------------------------- #

class SourcesTests(unittest.TestCase):
    def test_the_committed_sources_file_validates(self) -> None:
        sources = n1.load_sources()
        self.assertEqual(n1.sources_issues(sources), [])
        self.assertEqual(n1.encode_sources(sources), n1.SOURCES_PATH.read_bytes())
        self.assertEqual(sources["totals"], {"files": 40, "bytes": 6_740_907_612})
        self.assertEqual((sources["dataset"], sources["license"]), ("google/fleurs", "CC-BY-4.0"))
        self.assertEqual([entry["config"] for entry in sources["languages"]],
                         ["en_us", "fr_fr", "de_de", "es_419", "it_it", "pt_br", "ru_ru", "cmn_hans_cn", "ja_jp",
                          "ko_kr"])
        self.assertIn("no speaker ids", sources["limitations"][0]["statement"])
        self.assertIn("unverifiable", sources["disjointness"]["speaker"])
        for text in ("Conneau et al., 2022", "arXiv:2205.12446", "Google", "CC BY 4.0", "no FLEURS audio or transcript"):
            self.assertIn(text, sources["attribution"])
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(n1.main(["validate"]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "PASS")

    def test_validate_refuses_a_wrong_shape_pin_or_license(self) -> None:
        committed = n1.load_sources()
        mutations = {
            "license": lambda s: s.update(license="CC-BY-SA-4.0"),
            "languages must be": lambda s: s["languages"].pop(),
            "sha256 is malformed": lambda s: s["languages"][0]["splits"][0]["archive"].update(sha256="0" * 63),
            "exactly path, size and gitBlobSHA1": lambda s: s["languages"][0]["splits"][0]["tsv"].update(sha256="0" * 64),
            "holds split, role calibration": lambda s: s["languages"][1]["splits"][0].update(role="confirmation"),
            "totals must be": lambda s: s["totals"].update(bytes=1),
            "revision must be": lambda s: s.update(revision="main"),
            "the archive pin names": lambda s: s["languages"][2]["splits"][1]["archive"].update(path="data/x/audio/test.tar.gz"),
            "limitations differs": lambda s: s.update(limitations=[]),
            "FLEURS config": lambda s: s["languages"][0].update(config="en_gb"),
        }
        for expected, mutate in mutations.items():
            with self.subTest(expected=expected):
                sources = copy.deepcopy(committed)
                mutate(sources)
                issues = n1.sources_issues(sources)
                self.assertTrue(any(expected in issue for issue in issues), issues)

    def test_both_pin_kinds_verify_the_bytes_including_the_git_blob_id(self) -> None:
        # `git hash-object` of "hello\n".
        self.assertEqual(n1.git_blob_sha1(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tsv, archive = root / "dev.tsv", root / "dev.tar.gz"
            tsv.write_bytes(b"1\t1.wav\tA text.\ta text\ta|text\t16000\tMALE\n")
            archive.write_bytes(b"\x1f\x8b archive bytes")
            tsv_pin = {"path": "dev.tsv", "size": tsv.stat().st_size, "gitBlobSHA1": n1.git_blob_sha1(tsv.read_bytes())}
            archive_pin = {"path": "dev.tar.gz", "size": archive.stat().st_size,
                           "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
            self.assertTrue(n1.verified_file(tsv, tsv_pin))
            self.assertTrue(n1.verified_file(archive, archive_pin))
            # A plain SHA-1 of the content is not the blob id.
            self.assertFalse(n1.verified_file(tsv, {**tsv_pin, "gitBlobSHA1": hashlib.sha1(tsv.read_bytes()).hexdigest()}))
            self.assertFalse(n1.verified_file(archive, {**archive_pin, "size": archive_pin["size"] + 1}))
            tsv.write_bytes(tsv.read_bytes().replace(b"MALE", b"MALF"))
            self.assertFalse(n1.verified_file(tsv, tsv_pin))
            archive.write_bytes(archive.read_bytes()[:-1] + b"X")
            self.assertFalse(n1.verified_file(archive, archive_pin))
            link = root / "link.tar.gz"
            archive.write_bytes(b"\x1f\x8b archive bytes")
            link.symlink_to(archive)
            self.assertFalse(n1.verified_file(link, archive_pin))

    def test_the_synthetic_sources_follow_the_committed_shape(self) -> None:
        self.assertEqual(n1.sources_issues(make_sources(corpus_files()), LANGUAGES), [])


# --------------------------------------------------------------------------- #
# Transport and fetch
# --------------------------------------------------------------------------- #

class TransportTests(unittest.TestCase):
    def test_only_https_on_the_hub_and_its_cdns_is_allowed(self) -> None:
        for allowed in ("https://huggingface.co/datasets/google/fleurs/resolve/abc/data/x", "https://cdn-lfs.hf.co/x",
                        "https://cas-bridge.xethub.hf.co/xet?sig=1", "https://us.gcp.cdn.huggingface.co/x"):
            with self.subTest(url=allowed):
                self.assertTrue(n1.allowed_hub_url(allowed))
        for refused in ("http://huggingface.co/x", "https://github.com/x", "https://objects.githubusercontent.com/x",
                        "https://raw.githubusercontent.com/x", "https://evil.example/x",
                        "https://huggingface.co.evil.example/x", "https://user:secret@huggingface.co/x",
                        "https://huggingface.co:8443/x", "file:///etc/passwd"):
            with self.subTest(url=refused):
                self.assertFalse(n1.allowed_hub_url(refused))

    def test_a_redirect_is_followed_only_to_the_hub_cdn(self) -> None:
        handler = n1.HubRedirectHandler()
        request = urllib.request.Request(url("data/en_us/audio/dev.tar.gz"), headers={"Range": "bytes=10-"})
        followed = handler.redirect_request(request, None, 302, "Found", {}, "https://cdn-lfs.hf.co/x?signed=1")
        self.assertEqual(followed.full_url, "https://cdn-lfs.hf.co/x?signed=1")
        self.assertEqual(followed.get_header("Range"), "bytes=10-")
        for target in ("http://cdn-lfs.hf.co/x", "https://github.com/x?token=secret", "https://mirror.example/x"):
            with self.subTest(target=target), self.assertRaisesRegex(n1.N1Error, "redirected") as caught:
                handler.redirect_request(request, None, 302, "Found", {}, target)
            self.assertNotIn("secret", str(caught.exception))
        self.assertTrue(any(isinstance(item, n1.HubRedirectHandler) for item in n1._OPENER.handlers))

    def test_a_url_off_the_hub_is_refused_before_any_connection(self) -> None:
        with mock.patch.object(n1._OPENER, "open", side_effect=AssertionError("connected")):
            with self.assertRaisesRegex(n1.N1Error, "not a Hugging Face Hub https host"):
                n1._open(urllib.request.Request("https://github.com/x"), 1.0)

    def test_every_file_downloads_from_the_pinned_revision(self) -> None:
        sources = make_sources(corpus_files())
        self.assertEqual(n1.file_url(sources, "data/en_us/dev.tsv"), url("data/en_us/dev.tsv"))


class FetchTests(CorpusFixture):
    def fetch(self, hub: FakeHub, **options) -> list[dict]:
        return quiet(n1.fetch, self.sources, root=self.root, opener=hub, sleep=lambda _seconds: None, **options)

    def test_fetch_verifies_every_file_and_skips_what_is_already_verified(self) -> None:
        hub = FakeHub(self.files)
        stderr = io.StringIO()
        with mock.patch.object(n1, "PROGRESS_STEP_BYTES", 4096), redirect_stderr(stderr):
            report = n1.fetch(self.sources, root=self.root, opener=hub, sleep=lambda _seconds: None)
        self.assertEqual({item["status"] for item in report}, {"fetched"})
        self.assertEqual([item["path"] for item in report][:4],
                         ["data/en_us/dev.tsv", "data/en_us/test.tsv", "data/en_us/audio/dev.tar.gz",
                          "data/en_us/audio/test.tar.gz"])
        for path, data in self.files.items():
            self.assertEqual((self.corpus / path).read_bytes(), data)
        self.assertFalse((self.corpus / n1.PARTIAL_DIRECTORY).exists())
        self.assertIn(" MB", stderr.getvalue())
        self.assertRegex(stderr.getvalue(), r"data/en_us/audio/dev\.tar\.gz: \d+\.\d / \d+\.\d MB")
        hub.offline = True
        again = self.fetch(hub)
        self.assertEqual({item["status"] for item in again}, {"present"})
        self.assertEqual(len(hub.requests), len(self.files))

    def test_a_language_selection_fetches_only_its_files(self) -> None:
        hub = FakeHub(self.files)
        report = self.fetch(hub, languages=["french"])
        self.assertEqual({item["path"].split("/")[1] for item in report}, {"fr_fr"})
        self.assertFalse((self.corpus / "data/en_us").exists())

    def test_an_interrupted_download_resumes_from_its_part_file(self) -> None:
        path = "data/en_us/audio/dev.tar.gz"
        part = self.corpus / n1.PARTIAL_DIRECTORY / f"{path}.part"
        part.parent.mkdir(parents=True)
        part.write_bytes(self.files[path][:1000])
        hub = FakeHub(self.files)
        hub.cut[url(path)] = 500  # the resumed transfer drops again after 500 more bytes
        self.fetch(hub, languages=["english"])
        ranges = [header for address, header in hub.requests if address == url(path)]
        self.assertEqual(ranges, ["bytes=1000-", "bytes=1500-"])
        self.assertEqual((self.corpus / path).read_bytes(), self.files[path])
        self.assertFalse(part.exists())

    def test_a_digest_or_size_mismatch_is_refused_and_nothing_unverified_is_kept(self) -> None:
        path = "data/en_us/dev.tsv"
        tampered = bytearray(self.files[path])
        tampered[5] ^= 0x01
        hub = FakeHub({**self.files, path: bytes(tampered)})
        with self.assertRaisesRegex(n1.N1Error, "does not match its pinned size and digest"):
            self.fetch(hub, languages=["english"])
        self.assertFalse((self.corpus / path).exists())
        self.assertFalse((self.corpus / n1.PARTIAL_DIRECTORY / f"{path}.part").exists())
        longer = FakeHub({**self.files, path: self.files[path] + b"extra"})
        with self.assertRaisesRegex(acquire.AcquisitionError, "incomplete"):
            self.fetch(longer, languages=["english"])
        self.assertFalse((self.corpus / path).exists())

    def test_a_present_file_that_differs_from_its_pin_is_refused_not_replaced(self) -> None:
        path = "data/fr_fr/test.tsv"
        (self.corpus / path).parent.mkdir(parents=True)
        (self.corpus / path).write_bytes(b"not the pinned file\n")
        with self.assertRaisesRegex(n1.N1Error, "present but differs from its pin"):
            self.fetch(FakeHub(self.files), languages=["french"])
        self.assertEqual((self.corpus / path).read_bytes(), b"not the pinned file\n")

    def test_the_whole_selection_must_fit_before_anything_is_fetched(self) -> None:
        hub = FakeHub(self.files)
        with mock.patch.object(n1.shutil, "disk_usage", return_value=SimpleNamespace(total=2, used=1, free=1)):
            with self.assertRaisesRegex(n1.N1Error, "nothing was written"):
                self.fetch(hub)
        self.assertEqual(hub.requests, [])

    def test_plan_reads_no_network_and_reports_the_state(self) -> None:
        self.place({"data/en_us/dev.tsv": self.files["data/en_us/dev.tsv"]})
        value = n1.plan(self.sources, root=self.root)
        states = {row["path"]: row["state"] for row in value["files"]}
        self.assertEqual(states["data/en_us/dev.tsv"], "present")
        self.assertEqual(states["data/en_us/test.tsv"], "absent")
        self.assertEqual(value["totalBytes"], self.sources["totals"]["bytes"])

    def test_the_committed_plan_totals_6_74_gb(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(n1.main(["plan", "--json"]), 0)
        value = json.loads(stdout.getvalue())
        self.assertEqual((len(value["files"]), value["totalBytes"]), (40, 6_740_907_612))


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #

class ExtractTests(CorpusFixture):
    def test_extraction_writes_checked_wavs_and_a_receipt_and_is_kept_while_it_matches(self) -> None:
        self.place()
        report = quiet(n1.extract, self.sources, root=self.root)
        self.assertEqual([item["status"] for item in report], ["extracted", "extracted"])
        self.assertEqual(report[0]["recordings"], {"dev": 4, "test": 2})
        self.assertEqual(report[0]["sharedSentenceIDs"], 1)
        directory = self.corpus / "extracted" / "en_us"
        receipt = json.loads((directory / "receipt.json").read_text())
        self.assertEqual(receipt["kind"], "audio-qc-n1-extraction")
        self.assertEqual((receipt["splits"]["dev"]["memberDirectory"], receipt["splits"]["dev"]["recordings"]), ("dev", 4))
        self.assertEqual(receipt["pins"]["dev"]["archive"]["sha256"],
                         self.sources["languages"][0]["splits"][0]["archive"]["sha256"])
        for name, file in receipt["splits"]["dev"]["files"].items():
            self.assertEqual(hashlib.sha256((directory / "dev" / name).read_bytes()).hexdigest(), file["sha256"])
        self.assertFalse(any(path.name.startswith(".staging") for path in (self.corpus / "extracted").iterdir()))
        again = quiet(n1.extract, self.sources, root=self.root)
        self.assertEqual([item["status"] for item in again], ["present", "present"])
        (directory / "dev" / "10001.wav").write_bytes(b"tampered")
        third = quiet(n1.extract, self.sources, root=self.root, languages=["english"])
        self.assertEqual(third[0]["status"], "extracted")
        self.assertEqual(hashlib.sha256((directory / "dev" / "10001.wav").read_bytes()).hexdigest(),
                         receipt["splits"]["dev"]["files"]["10001.wav"]["sha256"])

    def test_an_unfetched_or_repinned_archive_is_refused(self) -> None:
        with self.assertRaisesRegex(n1.N1Error, "run `fetch` first"):
            quiet(n1.extract, self.sources, root=self.root)
        self.place()
        (self.corpus / "data/fr_fr/audio/test.tar.gz").write_bytes(b"other bytes")
        with self.assertRaisesRegex(n1.N1Error, "differs from its pin"):
            quiet(n1.extract, self.sources, root=self.root, languages=["french"])

    def _refused(self, members, expected: str, rows=None) -> None:
        archive = self.tmp / "bad.tar.gz"
        archive.write_bytes(tar_gz(members))
        destination = self.tmp / "out" / "dev"
        shutil.rmtree(destination.parent, ignore_errors=True)
        with self.assertRaisesRegex(n1.N1Error, expected):
            n1.extract_split(archive, {"path": "data/en_us/audio/dev.tar.gz"}, "dev",
                             rows or n1.parse_tsv(tsv_bytes(ROWS[("english", "dev")]), "dev.tsv"), destination)

    def test_unsafe_or_unexpected_members_are_refused(self) -> None:
        good = split_members("english", "dev")
        link = tarfile.TarInfo("dev/10001.wav")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        hard = tarfile.TarInfo("dev/10002.wav")
        hard.type, hard.linkname = tarfile.LNKTYPE, "dev/10001.wav"
        device = tarfile.TarInfo("dev/10003.wav")
        device.type = tarfile.CHRTYPE
        cases = [
            ("is a link", [link, *good[1:]]),
            ("is a link", [*good[:2], hard]),
            ("device file", [*good[:2], device]),
            (r"'\.\.' path part", [*good, ("dev/../10005.wav", b"x")]),
            ("absolute or unsafe path", [("/dev/10001.wav", b"x"), *good]),
            ("is not listed in its TSV", [*good, ("dev/99999.wav", wav_bytes(1000))]),
            (r"is not named dev/<digits>\.wav", [*good, ("dev/readme.txt", b"hello")]),
            (r"is not named dev/<digits>\.wav", [*good, ("test/10001.wav", b"x")]),
            (r"is not named dev/<digits>\.wav", [*good, ("10005.wav", b"x")]),
            ("is not in dev/ with the archive's first recording", [*good, ("other/dev/10005.wav", b"x")]),
            ("is a directory off the recordings' path dev/", [*good, directory_member("dev/nested")]),
            ("is a directory off the recordings' path dev/", [directory_member("test"), *good]),
            ("appears twice", [*good, good[1]]),
        ]
        for index, (expected, members) in enumerate(cases):
            with self.subTest(index=index, expected=expected):
                self._refused(members, expected)

    def test_a_root_entry_or_a_path_prefix_before_the_split_directory_is_accepted(self) -> None:
        rows = n1.parse_tsv(tsv_bytes(ROWS[("english", "dev")]), "dev.tsv")
        good = split_members("english", "dev")
        prefix = "home/fleurs/en_us/audio"
        prefixed = [directory_member("."), *[directory_member("/".join(prefix.split("/")[:depth]))
                                             for depth in range(1, 5)],
                    directory_member(f"{prefix}/dev"),
                    *[(f"{prefix}/{name}", data) for name, data in good[1:]]]
        for label, members, directory in (("rooted", [directory_member("."), *good], "dev"),
                                          ("prefixed", prefixed, f"{prefix}/dev")):
            with self.subTest(label=label):
                archive = self.tmp / f"{label}.tar.gz"
                archive.write_bytes(tar_gz(members))
                member_directory, files = n1.extract_split(archive, {"path": "dev.tar.gz"}, "dev", rows,
                                                           self.tmp / label)
                self.assertEqual(member_directory, directory)
                self.assertEqual(sorted(files), ["10001.wav", "10002.wav", "10003.wav", "10004.wav"])
                self.assertEqual(sorted(path.name for path in (self.tmp / label).iterdir()), sorted(files))

    def test_a_wav_that_is_not_mono_pcm16_at_16_khz_with_its_sample_count_is_refused(self) -> None:
        good = split_members("english", "dev")
        rows = ROWS[("english", "dev")]
        cases = {
            "24000 Hz, not 16000 Hz": ("dev/10001.wav", wav_bytes(rows[0][3], rate=24_000)),
            "not mono PCM16": ("dev/10001.wav", wav_bytes(rows[0][3], channels=2)),
            "its TSV row says 40000": ("dev/10001.wav", wav_bytes(rows[0][3] - 1)),
            "not a readable PCM WAV": ("dev/10001.wav", b"RIFF not really a wave file"),
        }
        for expected, replacement in cases.items():
            with self.subTest(expected=expected):
                self._refused([good[0], replacement, *good[2:]], expected)

    def test_a_member_count_other_than_the_tsv_rows_is_refused(self) -> None:
        self._refused(split_members("english", "dev")[:-1], "holds 3 recordings, its TSV lists 4")

    def test_a_refused_archive_leaves_nothing_behind(self) -> None:
        bad = tar_gz([*split_members("english", "dev"), ("dev/99999.wav", wav_bytes(1000))])
        files = corpus_files({"data/en_us/audio/dev.tar.gz": bad})
        sources = make_sources(files)
        self.place(files)
        with self.assertRaisesRegex(n1.N1Error, "not listed in its TSV"):
            quiet(n1.extract, sources, root=self.root, languages=["english"])
        self.assertEqual(list((self.corpus / "extracted").iterdir()), [])

    def test_a_malformed_tsv_is_refused(self) -> None:
        for data, expected in ((b"1\t1.wav\tText.\n", "has 3 columns"),
                               (b"1\t1.wav\tA.\ta\ta\t100\tMAN\n", "malformed"),
                               (b"1\t../1.wav\tA.\ta\ta\t100\tMALE\n", "malformed"),
                               (b"1\t1.wav\tA.\ta\ta\t100\tMALE\n1\t1.wav\tB.\tb\tb\t100\tMALE\n", "twice"),
                               (b"", "no recording")):
            with self.subTest(expected=expected), self.assertRaisesRegex(n1.N1Error, expected):
                n1.parse_tsv(data, "dev.tsv")


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #

class ManifestTests(CorpusFixture):
    def build(self, output: Path, split: str = "calibration", **options) -> dict:
        return quiet(n1.build_manifest, self.sources, split=split, output=output, root=self.root, **options)

    def test_the_manifest_lists_every_recording_with_its_eligibility(self) -> None:
        self.extracted()
        output = self.tmp / "run" / "n1-calibration.json"
        manifest = self.build(output)
        self.assertEqual(n1.manifest_digest_issues(json.loads(output.read_text())), [])
        self.assertEqual((manifest["kind"], manifest["population"], manifest["split"], manifest["fleursSplit"]),
                         ("audio-qc-n1-cohort", "N1", "calibration", "dev"))
        self.assertEqual((manifest["revision"], manifest["sourcesDigest"]), (REVISION, n1.sources_digest(self.sources)))
        self.assertEqual(manifest["license"], "CC-BY-4.0")
        takes = {take["takeID"]: take for take in manifest["takes"]}
        self.assertEqual(list(takes), ["n1-en-10001", "n1-en-10002", "n1-en-10003", "n1-en-10004", "n1-fr-30001"])
        first = takes["n1-en-10001"]
        self.assertEqual({key: first[key] for key in ("family", "scriptID", "language", "text", "gender", "population",
                                                      "status", "wavPath", "eligible", "ineligibleReasons")},
                         {"family": "n1-en-10001", "scriptID": "flores-101", "language": "english",
                          "text": "The quiet river runs past the old mill.", "gender": "male", "population": "N1",
                          "status": "generated", "wavPath": "wav/n1-en-10001.wav", "eligible": True,
                          "ineligibleReasons": []})
        self.assertEqual(first["durationSeconds"], 2.5)
        self.assertEqual(first["recording"], {"dataset": "google/fleurs", "config": "en_us", "split": "dev",
                                              "file": "10001.wav", "sentenceID": 101, "samples": 40_000,
                                              "sampleRate": 16_000})
        self.assertEqual(first["wavSHA256"], hashlib.sha256((output.parent / first["wavPath"]).read_bytes()).hexdigest())
        self.assertEqual(first["textSHA256"], hashlib.sha256(first["text"].encode()).hexdigest())
        self.assertEqual(takes["n1-en-10002"]["ineligibleReasons"], ["scriptLint:digit"])
        self.assertEqual(takes["n1-en-10002"]["scriptLintIssues"], ["digit"])
        self.assertEqual(takes["n1-en-10003"]["ineligibleReasons"], ["properName"])
        self.assertTrue(takes["n1-en-10003"]["properName"])
        self.assertEqual(takes["n1-en-10004"]["ineligibleReasons"], ["sharedScript"])
        self.assertTrue(takes["n1-fr-30001"]["eligible"])
        self.assertEqual(manifest["counts"], {
            "recordings": 5, "eligible": 2, "ineligible": 3,
            "byLanguage": {"english": {"recordings": 4, "eligible": 1}, "french": {"recordings": 1, "eligible": 1}},
            "ineligibleReasons": {"properName": 1, "scriptLint:digit": 1, "sharedScript": 1}})
        self.assertEqual(manifest["limitations"], n1.LIMITATIONS)

    def test_the_manifest_is_deterministic_and_its_wavs_are_placed_once(self) -> None:
        self.extracted()
        first = self.tmp / "one" / "n1.json"
        self.build(first)
        before = first.read_bytes()
        self.build(first)
        self.assertEqual(first.read_bytes(), before)
        second = self.tmp / "two" / "n1.json"
        self.build(second)
        self.assertEqual(second.read_bytes(), before)
        confirmation = self.build(self.tmp / "one" / "n1-confirmation.json", split="confirmation")
        self.assertEqual(confirmation["fleursSplit"], "test")
        self.assertEqual([take["takeID"] for take in confirmation["takes"]], ["n1-en-20001", "n1-en-20002", "n1-fr-40001"])
        self.assertEqual(confirmation["takes"][0]["ineligibleReasons"], ["sharedScript"])
        self.assertEqual(first.read_bytes(), before)

    def test_a_missing_or_changed_extraction_is_refused(self) -> None:
        with self.assertRaisesRegex(n1.N1Error, "run `fetch` and `extract` first"):
            self.build(self.tmp / "run" / "n1.json")
        self.extracted()
        (self.corpus / "extracted" / "fr_fr" / "dev" / "30001.wav").write_bytes(b"changed")
        with self.assertRaisesRegex(n1.N1Error, "differs from its extraction receipt"):
            self.build(self.tmp / "run" / "n1.json", languages=["french"])

    def test_a_placed_wav_with_other_content_is_never_overwritten(self) -> None:
        self.extracted()
        output = self.tmp / "run" / "n1.json"
        (output.parent / "wav").mkdir(parents=True)
        (output.parent / "wav" / "n1-fr-30001.wav").write_bytes(b"someone else's file")
        with self.assertRaisesRegex(n1.N1Error, "already exists with other content"):
            self.build(output, languages=["french"])
        self.assertEqual((output.parent / "wav" / "n1-fr-30001.wav").read_bytes(), b"someone else's file")

    def test_a_tampered_manifest_fails_its_digest(self) -> None:
        self.extracted()
        manifest = self.build(self.tmp / "run" / "n1.json")
        manifest["takes"][1]["eligible"] = True
        self.assertEqual(n1.manifest_digest_issues(manifest), ["the N1 manifest digest does not match its content"])


# --------------------------------------------------------------------------- #
# Consumers: the orchestrator and the calibration set
# --------------------------------------------------------------------------- #

class BridgeTests(CorpusFixture):
    def setUp(self) -> None:
        super().setUp()
        self.extracted()
        self.path = self.tmp / "run" / "n1-calibration.json"
        self.manifest = quiet(n1.build_manifest, self.sources, split="calibration", output=self.path, root=self.root)

    def test_the_orchestrator_takes_only_eligible_recordings_and_counts_the_rest(self) -> None:
        value = orchestrator.manifest_from_calibration_takes(self.manifest, source_sha256="e" * 64,
                                                             base_dir=self.path.parent)
        orchestrator.validate_manifest(value)
        self.assertEqual([take["id"] for take in value["takes"]], ["n1-en-10001", "n1-fr-30001"])
        self.assertEqual(value["source"], {"kind": "audio-qc-n1-cohort", "sha256": "e" * 64, "skippedTakes": 3})
        english = value["takes"][0]
        self.assertEqual((english["language"], english["referenceText"], english["expectedOutcome"]),
                         ("english", "The quiet river runs past the old mill.", "pass"))
        self.assertEqual(Path(english["audioPath"]), (self.path.parent / "wav/n1-en-10001.wav").resolve())
        output = self.tmp / "orchestrator-manifest.json"
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(orchestrator.main(["manifest", "--from-calibration-takes", str(self.path),
                                                "--output", str(output)]), 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"lane": "language-bench", "takes": 2, "skipped": 3})
        tampered = copy.deepcopy(self.manifest)
        tampered["takes"][1]["eligible"] = True
        with self.assertRaisesRegex(orchestrator.OrchestratorError, "digest"):
            orchestrator.manifest_from_calibration_takes(tampered, source_sha256="e" * 64, base_dir=self.path.parent)

    def test_the_recording_adapter_resamples_n1_to_the_engine_rate(self) -> None:
        wav = self.path.parent / "wav" / "n1-en-10001.wav"
        with self.assertRaisesRegex(recordings.RecordingError, "16000 Hz, not 24000 Hz"):
            recordings.load_recording(wav, take_id="x", family="x", stratum="x")
        fixture, _digest = recordings.load_recording(wav, take_id="x", family="x", stratum="N1/english",
                                                     source_rate=16_000)
        self.assertEqual((fixture.sample_rate, fixture.samples.size), (24_000, 60_000))
        again, _ = recordings.load_recording(wav, take_id="x", family="x", stratum="N1/english", source_rate=16_000)
        self.assertEqual(again.digest, fixture.digest)
        self.assertEqual(recordings.resampling_recipe(24_000), None)
        with self.assertRaises(recordings.RecordingError):
            recordings.resampling_recipe(44_100)

    def test_t1_injections_target_eligible_n1_recordings_and_replay(self) -> None:
        manifest, _ = m2.load_takes(self.path)
        self.assertEqual([take["takeID"] for take in m2.generated_takes(manifest)], ["n1-en-10001", "n1-fr-30001"])
        self.assertEqual(m2.stratum(m2.generated_takes(manifest)[0]), "N1/english")
        output = self.tmp / "set"
        summary = quiet(m2.run_inject, self.path, output, catalog_seed=7, classes=("A",), jobs=1)
        self.assertEqual(summary["sourceManifest"]["kind"], "audio-qc-n1-cohort")
        self.assertEqual((summary["counts"]["generatedTakes"], summary["counts"]["ineligibleTakes"],
                          summary["counts"]["missingTakes"]), (2, 3, 0))
        self.assertTrue(summary["entries"])
        for entry in summary["entries"]:
            self.assertEqual(entry["injection"]["sourceResampling"], recordings.resampling_recipe(16_000))
            self.assertIn(entry["sourceTakeID"], ("n1-en-10001", "n1-fr-30001"))
            self.assertNotIn("text", entry)
            with wave.open(str(output / entry["wavPath"]), "rb") as reader:
                self.assertEqual(reader.getframerate(), 24_000)
        sham = next(entry for entry in summary["entries"]
                    if entry["injection"]["injectorID"] == "SIG-LEVEL" and entry["injection"]["severity"] == "sham")
        source, _ = recordings.load_recording(self.path.parent / "wav" / f"{sham['sourceTakeID']}.wav", take_id="x",
                                              family="x", stratum="x", source_rate=16_000)
        self.assertEqual(sham["injection"]["sourcePCMSHA256"], source.digest)
        self.assertEqual(sham["injection"]["outputPCMSHA256"], pcm.pcm_digest(source.samples))
        result = quiet(m2.run_verify, output / "injection-set.json", self.path, jobs=1)
        self.assertTrue(result["verified"], result["failures"][:3])
        injection_set = json.loads((output / "injection-set.json").read_text())
        injection_set["entries"][0]["injection"]["sourceResampling"] = None
        (output / "injection-set.json").write_text(json.dumps(injection_set))
        result = quiet(m2.run_verify, output / "injection-set.json", self.path, jobs=1)
        self.assertIn("source resampling differs", " ".join(reason for _, reason in result["failures"]))
        with self.assertRaisesRegex(m2.CalibrationError, "does not score an N1 cohort"):
            quiet(m2.run_score, self.path, output / "injection-set.json", self.tmp / "score", jobs=1)

    def test_a_tampered_n1_manifest_is_refused_by_the_calibration_set(self) -> None:
        tampered = copy.deepcopy(self.manifest)
        tampered["takes"][0]["text"] = "Changed after the manifest was sealed."
        path = self.path.parent / "tampered.json"
        path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaisesRegex(m2.CalibrationError, "digest"):
            m2.load_takes(path)


if __name__ == "__main__":
    unittest.main()
