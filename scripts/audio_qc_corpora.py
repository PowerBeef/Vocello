#!/usr/bin/env python3
"""Pinned corpora for the next audio QC qualification round (AQ-07): registry, fetch, verify, extract.

The maintainer runs the downloads (a dataset download is a maintainer-run
action). The lean set is 28.96 GB to download and about 13.6 GB of WAVs once
extracted (the per-speaker caps of MLS, Zeroth-Korean and LibriTTS-R; about
34 GB uncapped); `plan` prints the exact download bytes, the extraction
estimate and the free space before anything is written:

    python3 scripts/audio_qc_corpora.py plan --set lean
    python3 scripts/audio_qc_corpora.py runtime
    python3 scripts/audio_qc_corpora.py fetch --set lean && python3 scripts/audio_qc_corpora.py extract --set lean
    python3 scripts/audio_qc_corpora.py verify --set lean

`config/audio-qc-corpora.json` is the registry: four groups (`fleurs-train`,
the N1 reserve cohorts; `speaker`, class E; `emotion`, class H; `accent`, class
D), and per source its host, repository and revision (or Zenodo record and
version), license with its official source, attribution, caveats, languages,
the labels it carries and every file pinned by size and digest: the LFS SHA-256
of a Hugging Face or GitHub LFS file, the git blob SHA-1 of a small Hub file
or of a plain git metadata file of a GitHub commit, or the publisher's MD5 of
a Zenodo file (the maintainer accepted MD5 plus the exact size there). The
7,442 CREMA-D WAV pins and the AISHELL-3 subset sit in
sidecar TSVs under `config/audio-qc-corpora/`, bound to the registry by their
SHA-256. Only pins, licenses and attributions are committed; audio,
transcripts and manifests stay untracked under `build/cache/audio-qc-corpora`
(`config/build-output-policy.json`, `QVOICE_AUDIO_QC_CORPORA_CACHE`).

- **Transport.** https only, on huggingface.co and its CDNs (`*.hf.co`,
  `*.huggingface.co`), media.githubusercontent.com (GitHub LFS content),
  raw.githubusercontent.com (a GitHub source's plain git metadata files, read
  at its pinned commit and pinned by git blob SHA-1) and zenodo.org; a
  redirect anywhere else refuses the download. Each file streams
  into `.partial/<path>.part`, resumes with an HTTP range request where the
  host honours one (a host that answers 200 starts over), and moves into place
  only once its size and pin match; a mismatch deletes the partial file. A
  file already in place is re-verified and skipped, or refused if it differs.
  The whole selection must fit, with a 2 GiB margin, before anything is
  fetched. Sources of many small files download on `--jobs` threads.
- **Receipts.** `<source>/corpora-fetch-receipt.json` records every verified
  file's SHA-256. For an MD5-pinned file that SHA-256 is computed on its first
  verified fetch and every later run checks the file against both the MD5 and
  the recorded SHA-256.
- **Runtime.** Parquet shards are read, and their FLAC or Opus audio decoded,
  by `scripts/audio_qc_corpora_worker.py` inside the pinned corpora-parquet
  runtime (`config/audio-qc-runtimes/corpora-parquet.txt`: pyarrow and
  soundfile), which `runtime` builds with the judge acquisition's own venv
  builder and standalone interpreter (`acquire_audio_qc_judges.py`) under
  `build/cache/delivery-analysis/external-models`. The system interpreter needs
  neither.
- **Extraction.** Every clip becomes mono PCM16 WAV at its source's output
  rate, 16 or 24 kHz (`scripts/lib/corpus_clips.py`: channels averaged, other
  rates resampled with the Kaiser-5 polyphase design the calibration tools
  use), in `<source>/extracted/wav/`, with `extracted/manifest.json`
  (`audio-qc-corpus`): per clip its id, language, split, speaker, gender,
  emotion (the corpus's label and its canonical name), accent, pronunciation
  scores and text where the corpus has them, duration, rate and digests of the
  written WAV and of the source audio. Labels come from the member names (a
  registry pattern), the Parquet columns the registry names, and metadata
  tables (archive members, or pinned metadata files beside WAV files or
  Parquet shards) joined by key after decoding; a pinned file that names its
  language labels that language's clips only, and a key whose rows disagree on
  a label keeps none (MLS speaker gender, CREMA-D actor sex: only the declared
  columns are kept). Identical PCM is one clip with its duplicates listed; a
  clip that cannot be decoded is listed under `skipped` with its reason, never
  silently dropped; an unsafe archive member, or a WAV the source's pattern
  does not name, refuses the archive. The extraction is staged and moved into
  place whole, and kept while its manifest and WAVs still match.
- **FLEURS reserve.** The FLEURS train split (same revision as the N1 pins in
  `config/audio-qc-n1-sources.json`, whose dev and test TSVs are fetched with
  it) is not unpacked whole: a seeded, language-stratified sample of eligible
  recordings forms `cohorts` disjoint reserve cohorts of `perLanguage`
  recordings each (the registry's `fleurs-train` entry, `RESERVE_RULE`),
  disjoint by FLoRes sentence id from each other and from dev and test. Only
  the sampled members are decoded (`audio_qc_n1_corpus.extract_members`), and
  each cohort is an `audio-qc-n1-cohort` manifest in the take shape the N2 and
  calibration tools read, under `fleurs/<revision>/reserve/<sampling digest>/`.

Commands:
  plan      bytes to download and to extract per group and source, and the free space (no network)
  runtime   build the pinned Parquet runtime (maintainer-run; reaches PyPI and the interpreter release)
  fetch     download and verify (--set, --group or --source; maintainer-run)
  extract   decode to the untracked per-source manifests and the FLEURS reserve cohorts
  verify    re-verify downloads, receipts, runtime and extractions offline
  validate  check the committed registry and its sidecars (no network); in the contract gate
  resolve-subset  the AISHELL-3 subset pins from a Hub tree listing, by the registry's seeded rule
"""

from __future__ import annotations

import argparse
from collections import Counter
import concurrent.futures
import csv
from dataclasses import dataclass
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import string
import subprocess
import sys
import tarfile
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence
import urllib.parse
import urllib.request
import zipfile
import zlib

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import acquire_audio_qc_judges as acquire  # noqa: E402
import audio_qc_n1_corpus as n1  # noqa: E402
from audio_qc_calibration_takes import self_digest  # noqa: E402
from audio_qc_judges import JudgeRegistryError, runtime_lock  # noqa: E402
from lib import corpus_clips as clips  # noqa: E402
from lib import jsonio  # noqa: E402
from lib import language_metrics as lm  # noqa: E402

REPO = SCRIPT_DIR.parent
REGISTRY_PATH = REPO / "config" / "audio-qc-corpora.json"
PIN_DIRECTORY = "config/audio-qc-corpora"
WORKER = SCRIPT_DIR / "audio_qc_corpora_worker.py"

SCHEMA_VERSION = 1
REGISTRY_KIND = "audio-qc-corpora"
RECEIPT_KIND = "audio-qc-corpora-fetch"
MANIFEST_KIND = "audio-qc-corpus"
RESERVE_RECEIPT_KIND = "audio-qc-corpora-fleurs-reserve-extraction"
EXTRACTOR = "audio-qc-corpora-extract-v1"
RESERVE_VERSION = "audio-qc-fleurs-reserve-v1"
RECEIPT_NAME = "corpora-fetch-receipt.json"
MANIFEST_NAME = "manifest.json"
EXTRACTED_DIRECTORY = "extracted"
RESERVE_DIRECTORY = "reserve"
PARTIAL_DIRECTORY = ".partial"
JOB_NAME = "worker-job.json"
RESULTS_NAME = "worker-results.json"

GROUPS: dict[str, str] = {"fleurs-train": "N1", "speaker": "E", "emotion": "H", "accent": "D"}
SETS = ("lean",)
HOSTS: dict[str, str] = {"huggingface.co": "hub", "media.githubusercontent.com": "github-lfs",
                         "zenodo.org": "zenodo"}
# A GitHub source's plain git files (not LFS content) are served only here, each read at the source's pinned
# commit and pinned by its git blob SHA-1.
GITHUB_RAW_HOST = "raw.githubusercontent.com"
TRANSPORT_HOSTS = frozenset({*HOSTS, GITHUB_RAW_HOST})
HOST_SUFFIXES = (".hf.co", ".huggingface.co")
ALLOWED_HOSTS = ("huggingface.co", "*.hf.co", "*.huggingface.co", "media.githubusercontent.com", GITHUB_RAW_HOST,
                 "zenodo.org")
PIN_KINDS: dict[str, tuple[str, ...]] = {"hub": ("sha256", "gitBlobSHA1"), "github-lfs": ("sha256", "gitBlobSHA1"),
                                         "zenodo": ("md5",)}
PIN_PATTERNS = {"sha256": re.compile(r"[0-9a-f]{64}"), "gitBlobSHA1": re.compile(r"[0-9a-f]{40}"),
                "md5": re.compile(r"[0-9a-f]{32}")}
FORMATS = ("fleurs-reserve", "wav-files", "zip", "tar.gz", "parquet")
LABELS = ("speaker", "gender", "emotion", "accent", "pronunciationScores", "text")
MEMBER_GROUPS = frozenset({"id", "speaker", "gender", "emotion", "intensity", "textID", "take"})
PARQUET_COLUMNS = frozenset({"id", "speaker", "gender", "emotion", "text"})
METADATA_FORMATS = ("csv", "pipe", "whitespace", "aishell3-content")
JOIN_FIELDS = ("sourceID", "speaker", "textID")
JOIN_LABELS = frozenset({"speaker", "gender", "emotion", "text", "accent", "textID"})
KEY_NORMALIZERS = ("stem", "int")
MAP_LABELS = frozenset({"emotion", "gender", "intensity"})
CONSTANT_LABELS = frozenset({"language", "speaker", "gender", "accent"})
SOURCE_FIELDS = frozenset({"title", "group", "alsoIn", "host", "repository", "revision", "record", "version",
                           "languages", "license", "attribution", "caveats", "labels", "extract", "files",
                           "pinFile", "subset", "totals"})
RUNTIME_FAMILY = "corpora-parquet"
SAFE_PATH = re.compile(r"[A-Za-z0-9._@+=,-]+(/[A-Za-z0-9._@+=,-]+)*")
SOURCE_ID = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
SHA1 = re.compile(r"[0-9a-f]{40}")
GIT_BLOB_MAX_BYTES = n1.GIT_BLOB_MAX_BYTES
MAX_FILE_BYTES = 8 * 1024 ** 3
MAX_MEMBER_BYTES = 64 * 1024 * 1024
FREE_SPACE_MARGIN_BYTES = acquire.FREE_SPACE_MARGIN_BYTES
PROGRESS_STEP_BYTES = n1.PROGRESS_STEP_BYTES
DEFAULT_JOBS = 4
RECEIPT_EVERY_FILES = 250
CHUNK_BYTES = 1 << 20
RESERVE_RULE = (
    "Per language, the train recordings the N1 manifest would mark eligible (audio_qc_n1_corpus eligibility, "
    "a FLoRes sentence id also read in dev or test counting as shared), grouped by FLoRes sentence id. The "
    "sentences in ascending order of SHA-256(seed NUL language NUL sentence id), and each sentence's recordings "
    "in ascending order of SHA-256(seed NUL language NUL file), fill cohort 1 up to perLanguage recordings, "
    "then cohort 2, and so on; a sentence belongs to one cohort only (its recordings past a full cohort stay "
    "unused), so the cohorts are disjoint by sentence from each other and from dev and test."
)

Opener = Callable[[urllib.request.Request, float], Any]
WorkerRunner = Callable[[Path, Mapping[str, Any]], None]


class CorporaError(RuntimeError):
    """A registry, pin, download, archive or extraction failed; nothing unverified is kept."""


def _log(message: str) -> None:
    print(f"audio-qc-corpora: {message}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CorporaError(f"{path.name} cannot be read: {type(error).__name__}") from None
    if not isinstance(value, dict):
        raise CorporaError(f"{path.name} is not a JSON object")
    return value


def encode_registry(registry: Mapping[str, Any]) -> bytes:
    return jsonio.pretty_bytes(registry, ascii=False, allow_nan=False)


def host_kind(entry: Mapping[str, Any]) -> str:
    return HOSTS.get(str(entry.get("host")), "")


@dataclass(frozen=True)
class Pin:
    path: str
    size: int
    kind: str
    digest: str
    role: str = "audio"
    language: str | None = None
    split: str | None = None

    def as_record(self) -> dict[str, Any]:
        return {"path": self.path, "size": self.size, self.kind: self.digest}


def _pin_from(value: Mapping[str, Any]) -> Pin:
    kind = next(key for key in PIN_PATTERNS if key in value)
    return Pin(value["path"], value["size"], kind, value[kind], value.get("role", "audio"), value.get("language"),
               value.get("split"))


_PIN_FILE_CACHE: dict[tuple[str, str], list[Pin]] = {}


def read_pin_file(spec: Mapping[str, Any], *, root: Path = REPO) -> list[Pin]:
    """A sidecar pin file (`path<TAB>size<TAB>sha256` rows under a header), verified against its SHA-256."""
    relative = str(spec.get("path"))
    key = (str(root / relative), str(spec.get("sha256")))
    if key in _PIN_FILE_CACHE:
        return _PIN_FILE_CACHE[key]
    if not relative.startswith(f"{PIN_DIRECTORY}/") or not SAFE_PATH.fullmatch(relative):
        raise CorporaError(f"the pin file {relative} is not under {PIN_DIRECTORY}/")
    try:
        data = (root / relative).read_bytes()
    except OSError:
        raise CorporaError(f"the pin file {relative} cannot be read") from None
    if hashlib.sha256(data).hexdigest() != spec.get("sha256"):
        raise CorporaError(f"the pin file {relative} does not match its recorded SHA-256")
    lines = data.decode("utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or lines[0] != "path\tsize\tsha256":
        raise CorporaError(f"the pin file {relative} does not start with its path, size, sha256 header")
    pins = []
    for number, line in enumerate(lines[1:], start=2):
        fields = line.split("\t")
        if len(fields) != 3 or not SAFE_PATH.fullmatch(fields[0]) or not fields[1].isdigit() \
                or not PIN_PATTERNS["sha256"].fullmatch(fields[2]):
            raise CorporaError(f"the pin file {relative} line {number} is malformed")
        pins.append(Pin(fields[0], int(fields[1]), "sha256", fields[2]))
    _PIN_FILE_CACHE[key] = pins
    return pins


def source_pins(registry: Mapping[str, Any], source: str, *, root: Path = REPO) -> list[Pin]:
    """Every pinned file of a source: its listed files, then its sidecar's."""
    entry = registry["sources"][source]
    pins = [_pin_from(value) for value in entry.get("files") or ()]
    if entry.get("pinFile"):
        pins += read_pin_file(entry["pinFile"], root=root)
    return pins


def _safe_relative(value: Any) -> bool:
    return isinstance(value, str) and bool(SAFE_PATH.fullmatch(value)) and not any(
        part in (".", "..") for part in value.split("/"))


def _https(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("https://") and len(value) > len("https://")


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _pattern_issues(label: str, pattern: Any, allowed: frozenset[str]) -> tuple[list[str], set[str]]:
    try:
        compiled = re.compile(pattern)
    except (re.error, TypeError):
        return [f"{label} is not a regular expression"], set()
    groups = set(compiled.groupindex)
    unknown = groups - allowed
    return ([f"{label} names unknown groups {', '.join(sorted(unknown))}"] if unknown else []), groups


def _metadata_issues(source: str, spec: Mapping[str, Any], metadata: Any, pins: Sequence[Pin],
                     languages: Sequence[str]) -> list[str]:
    issues: list[str] = []
    metadata_pins = {pin.path: pin for pin in pins if pin.role == "metadata"}
    archive = spec["format"] in ("zip", "tar.gz")
    if metadata is not None and not isinstance(metadata, list):
        return [f"{source}: extract.metadata must be a list"]
    read = {table.get("file") for table in metadata or () if isinstance(table, dict)} if not archive else set()
    for path, pin in metadata_pins.items():
        if path not in read:
            issues.append(f"{source}: the metadata file {path} is pinned but no extract.metadata table reads it")
        if pin.language is not None and (len(languages) < 2 or pin.language not in languages):
            issues.append(f"{source}: the metadata file {path} names a language only in a source of several "
                          "languages, and one of them (its rows then label that language's clips only)")
    for index, table in enumerate(metadata or ()):
        label = f"{source}: extract.metadata[{index}]"
        if not isinstance(table, dict) or table.get("format") not in METADATA_FORMATS:
            issues.append(f"{label} names a format of {', '.join(METADATA_FORMATS)}")
            continue
        where = table.get("member") if archive else table.get("file")
        if not _safe_relative(where):
            issues.append(f"{label} names its {'member' if archive else 'file'}")
        elif not archive and where not in metadata_pins:
            issues.append(f"{label}: {where} is not a pinned metadata file of the source")
        if table.get("joinOn") not in JOIN_FIELDS:
            issues.append(f"{label} joins on one of {', '.join(JOIN_FIELDS)}")
        if table.get("keyNormalize") is not None and table["keyNormalize"] not in KEY_NORMALIZERS:
            issues.append(f"{label}: keyNormalize is one of {', '.join(KEY_NORMALIZERS)}")
        fields = table.get("fields")
        if not isinstance(fields, dict) or not fields or not set(fields) <= JOIN_LABELS:
            issues.append(f"{label} maps some of {', '.join(sorted(JOIN_LABELS))} to its columns")
        if table.get("optional") not in (None, True, False):
            issues.append(f"{label}: optional is true or false")
        if table.get("header") not in (None, True, False) or (table.get("header") is not None
                                                              and table["format"] not in ("pipe", "whitespace")):
            issues.append(f"{label}: header (true or false) skips the first row of a pipe or whitespace table")
        if table["format"] == "whitespace" and not (isinstance(table.get("columns"), list) and table["columns"]):
            issues.append(f"{label}: a whitespace table names its columns")
    return issues


def _extract_issues(source: str, entry: Mapping[str, Any], pins: Sequence[Pin]) -> list[str]:
    spec = entry.get("extract")
    if not isinstance(spec, dict) or spec.get("format") not in FORMATS:
        return [f"{source}: extract.format is one of {', '.join(FORMATS)}"]
    issues = []
    if spec.get("outputRate") not in clips.OUTPUT_RATES:
        issues.append(f"{source}: extract.outputRate is one of {clips.OUTPUT_RATES}")
    if not _positive_int(spec.get("estimatedBytes")) or not isinstance(spec.get("estimateBasis"), str):
        issues.append(f"{source}: extract names its estimatedBytes and estimateBasis")
    maps = spec.get("maps") or {}
    if not isinstance(maps, dict) or not set(maps) <= MAP_LABELS or any(
            not isinstance(value, dict) or not all(isinstance(key, str) and isinstance(item, str)
                                                   for key, item in value.items()) for value in maps.values()):
        issues.append(f"{source}: extract.maps maps some of {', '.join(sorted(MAP_LABELS))} string to string")
    elif any(item not in clips.EMOTIONS for item in (maps.get("emotion") or {}).values()):
        issues.append(f"{source}: extract.maps.emotion maps only to {', '.join(clips.EMOTIONS)}")
    elif any(item not in ("male", "female") for item in (maps.get("gender") or {}).values()):
        issues.append(f"{source}: extract.maps.gender maps only to male or female")
    constants = spec.get("constants") or {}
    if not isinstance(constants, dict) or not set(constants) <= CONSTANT_LABELS \
            or not all(isinstance(value, str) and value for value in constants.values()):
        issues.append(f"{source}: extract.constants sets some of {', '.join(sorted(CONSTANT_LABELS))}")
    elif "language" in constants and constants["language"] not in (entry.get("languages") or ()):
        issues.append(f"{source}: extract.constants.language is one of the source's languages")
    prefix = spec.get("genderFromSpeakerPrefix")
    if prefix is not None and (not isinstance(prefix, dict) or not prefix or any(
            len(key) != 1 or value not in ("male", "female") for key, value in prefix.items())):
        issues.append(f"{source}: extract.genderFromSpeakerPrefix maps one-letter prefixes to male or female")
    fmt = spec["format"]
    if fmt == "fleurs-reserve":
        if not _positive_int(spec.get("cohorts")) or not _positive_int(spec.get("perLanguage")) \
                or not isinstance(spec.get("seed"), str) or not spec["seed"]:
            issues.append(f"{source}: a FLEURS reserve names its cohorts, perLanguage and seed")
        return issues
    if fmt == "parquet":
        columns = spec.get("columns")
        if not isinstance(spec.get("audioColumn"), str) or not spec["audioColumn"]:
            issues.append(f"{source}: extract.audioColumn names the audio column")
        if not isinstance(columns, dict) or not set(columns) <= PARQUET_COLUMNS \
                or not all(isinstance(value, str) and value for value in columns.values()):
            issues.append(f"{source}: extract.columns maps some of {', '.join(sorted(PARQUET_COLUMNS))} to columns")
        scores = spec.get("scores")
        if scores is not None and (not isinstance(scores, list) or not all(isinstance(name, str) for name in scores)):
            issues.append(f"{source}: extract.scores lists column names")
        if ("perSpeaker" in spec or "capSeed" in spec) and (
                not _positive_int(spec.get("perSpeaker")) or not isinstance(spec.get("capSeed"), str)
                or not spec["capSeed"] or not isinstance(columns, dict)
                or any(str(columns.get(name) or "@").startswith("@") for name in ("id", "speaker"))):
            issues.append(f"{source}: a per-speaker cap names perSpeaker and capSeed and reads id and speaker "
                          "columns")
        if not all(pin.path.endswith(".parquet") for pin in pins if pin.role == "audio"):
            issues.append(f"{source}: a Parquet source pins its .parquet shards as audio, beside the metadata files "
                          "its extract.metadata reads")
        return issues + _metadata_issues(source, spec, spec.get("metadata"), pins, entry.get("languages") or ())
    member_issues, groups = _pattern_issues(f"{source}: extract.members", spec.get("members"), MEMBER_GROUPS)
    issues += member_issues
    for pattern in spec.get("ignore") or ():
        issues += _pattern_issues(f"{source}: extract.ignore", pattern, frozenset())[0]
    template = spec.get("idTemplate")
    if template is not None:
        try:
            fields = {name for _, name, _, _ in string.Formatter().parse(template) if name}
        except (ValueError, TypeError):
            fields = {"?"}
        if not isinstance(template, str) or not fields or not fields <= groups:
            issues.append(f"{source}: extract.idTemplate formats only the member pattern's groups")
    issues += _metadata_issues(source, spec, spec.get("metadata"), pins, entry.get("languages") or ())
    audio = [pin for pin in pins if pin.role == "audio"]
    if fmt in ("zip", "tar.gz") and (len(audio) != 1 or not audio[0].path.endswith(".zip" if fmt == "zip"
                                                                                   else (".tgz", ".tar.gz"))):
        issues.append(f"{source}: a {fmt} source pins one {fmt} archive")
    if fmt == "wav-files" and not all(pin.path.lower().endswith(".wav") for pin in audio):
        issues.append(f"{source}: a wav-files source pins only .wav audio")
    return issues


def _fleurs_issues(source: str, entry: Mapping[str, Any], pins: Sequence[Pin],
                   n1_sources: Mapping[str, Any] | None) -> list[str]:
    issues = []
    if entry.get("repository") != n1.DATASET or entry.get("host") != n1.HUB_HOST:
        issues.append(f"{source}: the FLEURS reserve reads {n1.DATASET} on {n1.HUB_HOST}")
    if n1_sources is not None and entry.get("revision") != n1_sources.get("revision"):
        issues.append(f"{source}: the FLEURS reserve reads the N1 revision of config/audio-qc-n1-sources.json")
    if list(entry.get("languages") or ()) != list(lm.PRODUCT_LANGUAGES):
        issues.append(f"{source}: the FLEURS reserve covers the product languages in their order")
    expected = [path for config in n1.FLEURS_CONFIGS.values()
                for path in (f"data/{config}/train.tsv", f"data/{config}/audio/train.tar.gz")]
    if [pin.path for pin in pins] != expected:
        issues.append(f"{source}: the FLEURS reserve pins each config's train.tsv then its audio/train.tar.gz")
    for pin in pins:
        wanted = "gitBlobSHA1" if pin.path.endswith(".tsv") else "sha256"
        if pin.kind != wanted:
            issues.append(f"{source}: {pin.path} is pinned by {wanted}")
    return issues


def _file_issues(source: str, kind: str, values: Any) -> list[str]:
    if not isinstance(values, list):
        return [f"{source}: files must be a list"]
    issues = []
    for value in values:
        if not isinstance(value, dict):
            issues.append(f"{source}: every file is an object")
            continue
        present = [key for key in PIN_PATTERNS if key in value]
        allowed = {"path", "size", "role", "language", "split", *present}
        if len(present) != 1 or set(value) - allowed:
            issues.append(f"{source}: {value.get('path')!r} holds path, size, one digest and optionally role, "
                          "language and split")
            continue
        pin_kind = present[0]
        path, size = value.get("path"), value.get("size")
        if not _safe_relative(path):
            issues.append(f"{source}: {path!r} is not a safe relative path")
        if pin_kind not in PIN_KINDS.get(kind, ()):
            issues.append(f"{source}: {path} is pinned by {pin_kind}; its host pins by "
                          f"{' or '.join(PIN_KINDS.get(kind, ('nothing',)))}")
        if not PIN_PATTERNS[pin_kind].fullmatch(str(value[pin_kind])):
            issues.append(f"{source}: {path}: {pin_kind} is malformed")
        limit = GIT_BLOB_MAX_BYTES if pin_kind == "gitBlobSHA1" else MAX_FILE_BYTES
        if not _positive_int(size) or size > limit:
            issues.append(f"{source}: {path}: size must be a positive integer of at most {limit} bytes")
        if value.get("role", "audio") not in ("audio", "metadata"):
            issues.append(f"{source}: {path}: role is audio or metadata")
        elif kind == "github-lfs" and pin_kind == "gitBlobSHA1" and value.get("role") != "metadata":
            issues.append(f"{source}: {path}: a plain git file of a GitHub source ({GITHUB_RAW_HOST}) is a metadata "
                          "file; its audio is LFS content pinned by SHA-256")
        if value.get("language") is not None and value["language"] not in lm.PRODUCT_LANGUAGES:
            issues.append(f"{source}: {path}: language is a product language")
    return issues


def registry_issues(registry: Any, *, root: Path = REPO,
                    n1_sources: Mapping[str, Any] | None = None) -> list[str]:
    """Why the registry cannot pin the corpora (empty when it can). Reads no network, only the repository."""
    if not isinstance(registry, dict):
        return ["registry: not an object"]
    issues: list[str] = []
    keys = {"schemaVersion", "kind", "item", "description", "decisions", "hosts", "sets", "groups",
            "parquetRuntime", "sources", "totals"}
    if set(registry) != keys:
        issues.append(f"registry: fields must be {', '.join(sorted(keys))}")
    if registry.get("schemaVersion") != SCHEMA_VERSION or registry.get("kind") != REGISTRY_KIND:
        issues.append(f"registry: not an {REGISTRY_KIND} schema {SCHEMA_VERSION} registry")
    if registry.get("hosts") != list(ALLOWED_HOSTS):
        issues.append(f"registry: hosts must be exactly {', '.join(ALLOWED_HOSTS)}")
    if not isinstance(registry.get("decisions"), list) or not all(isinstance(item, str) and item
                                                                  for item in registry.get("decisions") or [None]):
        issues.append("registry: decisions lists the maintainer's decisions")
    groups = registry.get("groups")
    if not isinstance(groups, dict) or set(groups) != set(GROUPS) or any(
            not isinstance(value, dict) or value.get("class") != GROUPS[name]
            or not isinstance(value.get("title"), str) or not isinstance(value.get("description"), str)
            for name, value in groups.items()):
        issues.append(f"registry: groups are {', '.join(GROUPS)} with their title, class and description")
    sets = registry.get("sets")
    if not isinstance(sets, dict) or set(sets) != set(SETS) or any(
            not isinstance(value, dict) or not isinstance(value.get("groups"), list)
            or not set(value["groups"]) <= set(GROUPS) or not isinstance(value.get("description"), str)
            for value in sets.values()):
        issues.append(f"registry: sets are {', '.join(SETS)}, each naming registry groups")
    issues += runtime_issues(registry, root=root)
    sources = registry.get("sources")
    if not isinstance(sources, dict) or not sources:
        return issues + ["registry: sources must map source ids to entries"]
    totals: dict[str, dict[str, int]] = {group: {"files": 0, "bytes": 0} for group in GROUPS}
    paths_seen: set[tuple[str, str]] = set()
    for source, entry in sources.items():
        if not SOURCE_ID.fullmatch(str(source)) or not isinstance(entry, dict):
            issues.append(f"sources: {source!r} is not a lowercase id mapped to an entry")
            continue
        issues += _source_issues(source, entry, root=root, n1_sources=n1_sources)
        try:
            pins = source_pins(registry, source, root=root)
        except (CorporaError, KeyError, StopIteration, TypeError):
            continue
        for pin in pins:
            if (source, pin.path) in paths_seen:
                issues.append(f"{source}: {pin.path} is pinned twice")
            paths_seen.add((source, pin.path))
        counted = {"files": len(pins), "bytes": sum(pin.size for pin in pins)}
        if entry.get("totals") != counted:
            issues.append(f"{source}: totals must be {counted}")
        if entry.get("group") in totals:
            totals[entry["group"]]["files"] += counted["files"]
            totals[entry["group"]]["bytes"] += counted["bytes"]
    expected = {"files": sum(value["files"] for value in totals.values()),
                "bytes": sum(value["bytes"] for value in totals.values()), "groups": totals}
    if registry.get("totals") != expected:
        issues.append(f"registry: totals must be {json.dumps(expected, sort_keys=True)}")
    return issues


def _source_issues(source: str, entry: Mapping[str, Any], *, root: Path,
                   n1_sources: Mapping[str, Any] | None) -> list[str]:
    issues = []
    unknown = set(entry) - SOURCE_FIELDS
    if unknown:
        issues.append(f"{source}: unknown fields {', '.join(sorted(unknown))}")
    kind = host_kind(entry)
    if not kind:
        return issues + [f"{source}: host is one of {', '.join(HOSTS)}"]
    if kind == "zenodo":
        if not str(entry.get("record", "")).isdigit() or not isinstance(entry.get("version"), str):
            issues.append(f"{source}: a Zenodo source names its record and version")
        if "revision" in entry or "repository" in entry:
            issues.append(f"{source}: a Zenodo source is pinned by record, not by revision")
    else:
        if not isinstance(entry.get("repository"), str) or not re.fullmatch(r"[\w.-]+/[\w.-]+", entry["repository"]):
            issues.append(f"{source}: repository is owner/name")
        if not isinstance(entry.get("revision"), str) or not SHA1.fullmatch(entry["revision"]):
            issues.append(f"{source}: revision must be a full 40-character commit")
    if not isinstance(entry.get("title"), str) or not entry["title"]:
        issues.append(f"{source}: title is missing")
    group, also = entry.get("group"), entry.get("alsoIn")
    if group not in GROUPS or not isinstance(also, list) or not set(also) <= set(GROUPS) - {group} \
            or len(set(also)) != len(also):
        issues.append(f"{source}: group is one of {', '.join(GROUPS)} and alsoIn lists other groups")
    languages = entry.get("languages")
    if not isinstance(languages, list) or not languages or not set(languages) <= set(lm.PRODUCT_LANGUAGES) \
            or len(set(languages)) != len(languages):
        issues.append(f"{source}: languages lists product languages")
    license_ = entry.get("license")
    if not isinstance(license_, dict) or not isinstance(license_.get("id"), str) or not license_["id"] \
            or not _https(license_.get("url")) or not _https(license_.get("source")) \
            or set(license_) - {"id", "url", "source", "note"}:
        issues.append(f"{source}: license holds its id, the license text url and the official source url")
    if not isinstance(entry.get("attribution"), str) or len(entry["attribution"]) < 40:
        issues.append(f"{source}: attribution is missing")
    caveats = entry.get("caveats")
    if not isinstance(caveats, list) or not all(isinstance(item, str) and item for item in caveats):
        issues.append(f"{source}: caveats lists statements")
    labels = entry.get("labels")
    if not isinstance(labels, dict) or set(labels) != set(LABELS) or not all(
            value is None or (isinstance(value, str) and value) for value in labels.values()):
        issues.append(f"{source}: labels names {', '.join(LABELS)}, each described or null")
    issues += _file_issues(source, kind, entry.get("files") or [])
    pin_file = entry.get("pinFile")
    if pin_file is not None:
        if kind == "zenodo" or not isinstance(pin_file, dict) \
                or set(pin_file) != {"path", "sha256", "files", "bytes"}:
            issues.append(f"{source}: pinFile holds path, sha256, files and bytes (LFS SHA-256 pins only)")
        else:
            try:
                sidecar = read_pin_file(pin_file, root=root)
            except (CorporaError, UnicodeDecodeError) as error:
                issues.append(f"{source}: {error}")
            else:
                if pin_file["files"] != len(sidecar) or pin_file["bytes"] != sum(pin.size for pin in sidecar):
                    issues.append(f"{source}: pinFile records {len(sidecar)} files and "
                                  f"{sum(pin.size for pin in sidecar)} bytes")
    if not entry.get("files") and pin_file is None:
        issues.append(f"{source}: pins no file")
    try:
        pins = [_pin_from(value) for value in entry.get("files") or ()]
        if isinstance(pin_file, dict):
            pins += read_pin_file(pin_file, root=root)
    except (CorporaError, KeyError, StopIteration, TypeError, UnicodeDecodeError):
        return issues
    issues += _extract_issues(source, entry, pins)
    spec = entry.get("extract") or {}
    if spec.get("format") == "fleurs-reserve":
        issues += _fleurs_issues(source, entry, pins, n1_sources)
    elif isinstance(languages, list) and len(languages) > 1 and any(
            pin.language not in languages for pin in pins if pin.role == "audio"):
        issues.append(f"{source}: a source of several languages names each audio file's language")
    subset = entry.get("subset")
    if subset is not None and (not isinstance(subset, dict) or pin_file is None or not all(
            _positive_int(subset.get(key)) for key in ("minimumFiles", "perSpeaker", "speakers"))
            or not isinstance(subset.get("seed"), str) or not _safe_relative(subset.get("directory"))
            or not isinstance(subset.get("rule"), str)):
        issues.append(f"{source}: subset states its rule, directory, seed, minimumFiles, perSpeaker and speakers "
                      "beside its pin file")
    elif subset is not None:
        issues += _subset_issues(source, subset, pins)
    return issues


def _subset_issues(source: str, subset: Mapping[str, Any], pins: Sequence[Pin]) -> list[str]:
    """The resolved subset has the shape its rule promises (the rule itself needs the Hub listing)."""
    directory = subset["directory"].rstrip("/") + "/"
    speakers: Counter[str] = Counter()
    for pin in pins:
        if pin.role != "audio":
            continue
        if not pin.path.startswith(directory) or pin.path.count("/") != directory.count("/") + 1:
            return [f"{source}: {pin.path} is not one level below {directory}"]
        speakers[pin.path[len(directory):].split("/")[0]] += 1
    if len(speakers) != subset["speakers"] or set(speakers.values()) != {subset["perSpeaker"]}:
        return [f"{source}: the subset holds {len(speakers)} speakers of {sorted(set(speakers.values()))} files; "
                f"its rule says {subset['speakers']} of {subset['perSpeaker']}"]
    return []


def runtime_spec(registry: Mapping[str, Any]) -> dict[str, Any]:
    spec = registry.get("parquetRuntime")
    if not isinstance(spec, dict):
        raise CorporaError("the registry declares no parquetRuntime")
    return spec


def runtime_view(registry: Mapping[str, Any], interpreter: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The corpora runtime as a judge-registry acquisition, so the judge tool's venv builder builds it unchanged."""
    spec = {key: value for key, value in runtime_spec(registry).items() if key not in ("family", "note")}
    return {"acquisition": {"interpreter": dict(interpreter or {}), "runtimes": {RUNTIME_FAMILY: spec}}}


def runtime_issues(registry: Mapping[str, Any], *, root: Path = REPO) -> list[str]:
    spec = registry.get("parquetRuntime")
    keys = {"family", "kind", "lock", "lockSHA256", "packages", "downloadBytes", "sourceBuilds", "venv",
            "importProbe", "note"}
    if not isinstance(spec, dict) or set(spec) != keys:
        return [f"parquetRuntime: fields must be {', '.join(sorted(keys))}"]
    issues = []
    if spec["family"] != RUNTIME_FAMILY or spec["kind"] != "venv" or spec["sourceBuilds"] != []:
        issues.append(f"parquetRuntime: the {RUNTIME_FAMILY} venv family, with no source build")
    if not _safe_relative(spec["venv"]) or "/" in spec["venv"] or not _positive_int(spec["downloadBytes"]):
        issues.append("parquetRuntime: names its venv directory and its wheel bytes")
    if not isinstance(spec["importProbe"], list) or not spec["importProbe"]:
        issues.append("parquetRuntime: names the modules its import probe loads")
    try:
        lock = runtime_lock(runtime_view(registry), RUNTIME_FAMILY, root=root)
    except JudgeRegistryError as error:
        return issues + [f"parquetRuntime: {error}"]
    if spec["packages"] != len(lock):
        issues.append(f"parquetRuntime: records {spec['packages']} packages; its lock pins {len(lock)}")
    for package in ("pyarrow", "soundfile", "numpy"):
        if package not in lock:
            issues.append(f"parquetRuntime: its lock pins no {package}")
    return issues


def load_valid_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    registry = load_registry(path)
    issues = registry_issues(registry, n1_sources=_n1_sources_or_none())
    if not issues and encode_registry(registry) != path.read_bytes():
        issues.append("registry: the file is not in the canonical encoding (indent 2, sorted keys)")
    if issues:
        raise CorporaError("; ".join(issues[:5]))
    return registry


def _n1_sources_or_none() -> dict[str, Any] | None:
    try:
        sources = n1.load_sources()
    except n1.N1Error:
        return None
    return sources if not n1.sources_issues(sources) else None


def load_n1_sources() -> dict[str, Any]:
    sources = n1.load_sources()
    issues = n1.sources_issues(sources)
    if issues:
        raise CorporaError("config/audio-qc-n1-sources.json is invalid: " + "; ".join(issues[:3]))
    return sources


def select(registry: Mapping[str, Any], *, sets: Sequence[str] = (), groups: Sequence[str] = (),
           sources: Sequence[str] = ()) -> list[str]:
    """The selected sources in registry order: a set's groups, groups (a source shared through alsoIn counts),
    and sources by id."""
    wanted_groups = set(groups)
    for name in sets:
        if name not in registry["sets"]:
            raise CorporaError(f"unknown set {name} (choose from {', '.join(registry['sets'])})")
        wanted_groups |= set(registry["sets"][name]["groups"])
    unknown = sorted(set(groups) - set(GROUPS))
    if unknown:
        raise CorporaError(f"unknown groups {', '.join(unknown)} (choose from {', '.join(GROUPS)})")
    unknown = sorted(set(sources) - set(registry["sources"]))
    if unknown:
        raise CorporaError(f"unknown sources {', '.join(unknown)} (choose from {', '.join(registry['sources'])})")
    return [source for source in ordered_sources(registry)
            if source in sources or registry["sources"][source]["group"] in wanted_groups
            or set(registry["sources"][source]["alsoIn"]) & wanted_groups]


def ordered_sources(registry: Mapping[str, Any]) -> list[str]:
    """Source ids by group (`GROUPS` order), then by id: the order every command walks them in."""
    groups = list(GROUPS)
    return sorted(registry["sources"], key=lambda source: (groups.index(registry["sources"][source]["group"]),
                                                          source))


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #

def allowed_url(url: str) -> bool:
    """https with no credentials and the default port, on one of the corpora hosts or a Hub CDN."""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.password or port not in (None, 443):
        return False
    return host in TRANSPORT_HOSTS or host.endswith(HOST_SUFFIXES)


class CorporaRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to https on the corpora hosts; anything else refuses the download."""

    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any,
                         newurl: str) -> urllib.request.Request | None:
        if not allowed_url(newurl):
            raise CorporaError(f"a download was redirected to {acquire._described(newurl)}, which is not an "
                               "allowed corpora host; nothing is fetched from it")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(CorporaRedirectHandler)


def _open(request: urllib.request.Request, timeout: float) -> Any:
    if not allowed_url(request.full_url):
        raise CorporaError(f"{acquire._described(request.full_url)} is not an allowed corpora host")
    return _OPENER.open(request, timeout=timeout)


def file_url(entry: Mapping[str, Any], pin: Pin) -> str:
    """Where one pinned file downloads from: its Hub revision, its GitHub commit (LFS content from
    media.githubusercontent.com, a plain git file pinned by its blob SHA-1 from raw.githubusercontent.com) or its
    Zenodo record."""
    kind = host_kind(entry)
    quoted = urllib.parse.quote(pin.path)
    if kind == "hub":
        url = f"https://huggingface.co/datasets/{entry['repository']}/resolve/{entry['revision']}/{quoted}"
    elif kind == "github-lfs" and pin.kind == "gitBlobSHA1":
        url = f"https://{GITHUB_RAW_HOST}/{entry['repository']}/{entry['revision']}/{quoted}"
    elif kind == "github-lfs":
        url = f"https://media.githubusercontent.com/media/{entry['repository']}/{entry['revision']}/{quoted}"
    elif kind == "zenodo":
        url = f"https://zenodo.org/api/records/{entry['record']}/files/{urllib.parse.quote(pin.path, safe='')}/content"
    else:
        raise CorporaError(f"{pin.path}: its host is not a corpora host")
    if not allowed_url(url):
        raise CorporaError(f"{pin.path} does not resolve to an allowed corpora host")
    return url


# --------------------------------------------------------------------------- #
# Paths, digests and receipts
# --------------------------------------------------------------------------- #

def cache_root() -> Path:
    override = os.environ.get(n1.CACHE_ENV)
    return Path(override) if override else REPO / "build" / "cache" / "audio-qc-corpora"


def source_directory(registry: Mapping[str, Any], source: str, root: Path | None = None) -> Path:
    """Where a source's pinned files land: `fleurs/<revision>` beside the N1 files, `<source>/<revision>`, or
    `<source>/zenodo-<record>`."""
    base = root or cache_root()
    entry = registry["sources"][source]
    if entry["extract"]["format"] == "fleurs-reserve":
        return base / n1.CACHE_SUBDIRECTORY / entry["revision"]
    if host_kind(entry) == "zenodo":
        return base / source / f"zenodo-{entry['record']}"
    return base / source / entry["revision"]


def _inside(root: Path, path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return False


def file_digests(path: Path, pin: Pin) -> tuple[str, str]:
    """(SHA-256, the pin kind's own digest) of a file, in one pass."""
    sha256 = hashlib.sha256()
    other = None
    if pin.kind == "md5":
        other = hashlib.md5(usedforsecurity=False)
    elif pin.kind == "gitBlobSHA1":
        other = hashlib.sha1(usedforsecurity=False)
        other.update(b"blob " + str(path.stat().st_size).encode("ascii") + b"\0")
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            sha256.update(block)
            if other is not None:
                other.update(block)
    return sha256.hexdigest(), (other or sha256).hexdigest()


def check_file(path: Path, pin: Pin, recorded_sha256: str | None = None) -> str:
    """The file's SHA-256 once its size, its pin and any SHA-256 its receipt recorded all match."""
    if path.is_symlink() or not path.is_file():
        raise CorporaError(f"{pin.path} is missing or not a plain file")
    if path.stat().st_size != pin.size:
        raise CorporaError(f"{pin.path} holds {path.stat().st_size} bytes; its pin says {pin.size}")
    sha256, pinned = file_digests(path, pin)
    if pinned != pin.digest:
        raise CorporaError(f"{pin.path} does not match its pinned {pin.kind}")
    if recorded_sha256 is not None and sha256 != recorded_sha256:
        raise CorporaError(f"{pin.path} matches its {pin.kind} but not the SHA-256 recorded on its first verified "
                           "fetch; remove it and fetch again")
    return sha256


def check_bytes(data: bytes, pin: Pin, recorded_sha256: str | None = None) -> str:
    if len(data) != pin.size:
        raise CorporaError(f"{pin.path} holds {len(data)} bytes; its pin says {pin.size}")
    sha256 = hashlib.sha256(data).hexdigest()
    if pin.kind == "md5":
        pinned = hashlib.md5(data, usedforsecurity=False).hexdigest()
    elif pin.kind == "gitBlobSHA1":
        pinned = n1.git_blob_sha1(data)
    else:
        pinned = sha256
    if pinned != pin.digest:
        raise CorporaError(f"{pin.path} does not match its pinned {pin.kind}")
    if recorded_sha256 is not None and sha256 != recorded_sha256:
        raise CorporaError(f"{pin.path} does not match the SHA-256 recorded on its first verified fetch")
    return sha256


class Receipt:
    """`corpora-fetch-receipt.json`: each verified file's size, pin and SHA-256 (the SHA-256 of an MD5-pinned
    file is recorded on its first verified fetch and binds every later run)."""

    def __init__(self, directory: Path, source: str) -> None:
        self.path = directory / RECEIPT_NAME
        self.source = source
        self.lock = threading.Lock()
        value = None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        if not isinstance(value, dict) or value.get("kind") != RECEIPT_KIND or value.get("source") != source \
                or not isinstance(value.get("files"), dict):
            value = {"schemaVersion": SCHEMA_VERSION, "kind": RECEIPT_KIND, "source": source, "files": {}}
        self.value = value

    def recorded(self, pin: Pin) -> str | None:
        entry = self.value["files"].get(pin.path)
        if isinstance(entry, dict) and entry.get("size") == pin.size and entry.get(pin.kind) == pin.digest \
                and isinstance(entry.get("sha256"), str):
            return entry["sha256"]
        return None

    def record(self, pin: Pin, sha256: str) -> None:
        with self.lock:
            self.value["files"][pin.path] = {"size": pin.size, pin.kind: pin.digest, "sha256": sha256,
                                             "verifiedOn": dt.date.today().isoformat()}

    def write(self) -> None:
        with self.lock:
            jsonio.atomic_json(self.path, self.value, ascii=False, allow_nan=False)


def _free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def _require_free(path: Path, needed: int, what: str) -> None:
    free = _free_bytes(path)
    if needed + FREE_SPACE_MARGIN_BYTES > free:
        raise CorporaError(f"{what} needs {needed / 1e9:.2f} GB plus a 2 GiB margin; {free / 1e9:.2f} GB is free, "
                           "so nothing was written")


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #

def _paths(directory: Path, pin: Pin) -> tuple[Path, Path]:
    final = directory / pin.path
    part = directory / PARTIAL_DIRECTORY / f"{pin.path}.part"
    if not _inside(directory, final) or not _inside(directory, part):
        raise CorporaError(f"{pin.path} resolves outside its source directory; nothing is written")
    return final, part


def _fetch_one(entry: Mapping[str, Any], pin: Pin, directory: Path, receipt: Receipt, *, opener: Opener,
               sleep: Callable[[float], None]) -> str:
    final, part = _paths(directory, pin)
    if final.exists():
        receipt.record(pin, check_file(final, pin, receipt.recorded(pin)))
        return "present"
    use = n1._with_progress(opener, pin.path, pin.size) if pin.size >= PROGRESS_STEP_BYTES else opener
    if pin.size >= PROGRESS_STEP_BYTES:
        resumed = part.stat().st_size if part.exists() else 0
        _log(f"  {pin.path}: {pin.size / 1e6:.1f} MB" + (f", resuming at {resumed / 1e6:.1f} MB" if resumed else ""))
    acquire.download(file_url(entry, pin), part, size=pin.size, opener=use, sleep=sleep)
    try:
        sha256 = check_file(part, pin)
    except CorporaError:
        part.unlink(missing_ok=True)
        raise CorporaError(f"{pin.path} does not match its pinned size and digest; the download was discarded") \
            from None
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(part, final)
    receipt.record(pin, sha256)
    return "fetched"


def fetch_source(registry: Mapping[str, Any], source: str, *, root: Path | None = None, opener: Opener = _open,
                 sleep: Callable[[float], None] = time.sleep, jobs: int = DEFAULT_JOBS) -> dict[str, Any]:
    entry = registry["sources"][source]
    directory = source_directory(registry, source, root)
    pins = source_pins(registry, source)
    for pin in pins:
        _paths(directory, pin)
    directory.mkdir(parents=True, exist_ok=True)
    receipt = Receipt(directory, source)
    total = sum(pin.size for pin in pins)
    _log(f"{source}: {len(pins)} files, {total / 1e6:.1f} MB")
    counts: Counter[str] = Counter()
    stop = threading.Event()

    def one(pin: Pin) -> str:
        if stop.is_set():
            return "cancelled"
        status = _fetch_one(entry, pin, directory, receipt, opener=opener, sleep=sleep)
        with receipt.lock:
            counts[status] += 1
            done = counts["present"] + counts["fetched"]
        if pin.size >= PROGRESS_STEP_BYTES or done % RECEIPT_EVERY_FILES == 0 or done == len(pins):
            receipt.write()
            _log(f"{source}: {done}/{len(pins)} files verified")
        return status

    try:
        if jobs > 1 and len(pins) > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
                futures = [pool.submit(one, pin) for pin in pins]
                try:
                    for future in concurrent.futures.as_completed(futures):
                        future.result()
                except BaseException:
                    stop.set()
                    for future in futures:
                        future.cancel()
                    raise
        else:
            for pin in pins:
                one(pin)
    finally:
        receipt.write()
        acquire._prune_partial(directory)
    return {"source": source, "files": len(pins), "bytes": total, "fetched": counts["fetched"],
            "present": counts["present"]}


def fetch(registry: Mapping[str, Any], selected: Sequence[str], *, root: Path | None = None,
          opener: Opener = _open, sleep: Callable[[float], None] = time.sleep, jobs: int = DEFAULT_JOBS,
          n1_sources: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Download every selected pinned file not already present and verified; refuse any mismatch."""
    base = root or cache_root()
    remaining = 0
    for source in selected:
        directory = source_directory(registry, source, base)
        remaining += sum(pin.size for pin in source_pins(registry, source) if not (directory / pin.path).exists())
    reserve = [source for source in selected if registry["sources"][source]["extract"]["format"] == "fleurs-reserve"]
    if reserve:
        n1_sources = n1_sources or load_n1_sources()
        corpus = n1.corpus_root(n1_sources, base / n1.CACHE_SUBDIRECTORY)
        remaining += sum(pin["size"] for pin in n1.pinned_files(n1_sources, kinds=("tsv",))
                         if not (corpus / pin["path"]).exists())
    _require_free(base, remaining, f"fetching {len(selected)} sources")
    _log(f"{len(selected)} sources; {remaining / 1e9:.2f} GB still to fetch")
    report = []
    if reserve:
        n1.fetch(n1_sources, root=base / n1.CACHE_SUBDIRECTORY, opener=opener, sleep=sleep, tsv_only=True)
    for source in selected:
        report.append(fetch_source(registry, source, root=base, opener=opener, sleep=sleep, jobs=jobs))
    return report


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #

def _state(directory: Path, pin: Pin) -> tuple[str, int]:
    final = directory / pin.path
    part = directory / PARTIAL_DIRECTORY / f"{pin.path}.part"
    if final.is_file() and final.stat().st_size == pin.size:
        return "present", pin.size
    if final.exists():
        return "differs", 0
    if part.is_file():
        return "partial", 0
    return "absent", 0


def plan(registry: Mapping[str, Any], selected: Sequence[str], *, root: Path | None = None,
         model_root: Path | None = None, n1_sources: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Per source and group, the bytes to download and to extract, local state and free space (no network)."""
    base = root or cache_root()
    reserve = any(registry["sources"][source]["extract"]["format"] == "fleurs-reserve" for source in selected)
    if reserve:
        n1_sources = n1_sources or load_n1_sources()
    rows = []
    for source in selected:
        entry = registry["sources"][source]
        directory = source_directory(registry, source, base)
        pins = source_pins(registry, source)
        states = [_state(directory, pin) for pin in pins]
        present = sum(size for _state_name, size in states)
        extracted = _extraction_current(registry, source, base, n1_sources)
        rows.append({
            "source": source, "title": entry["title"], "group": entry["group"], "alsoIn": entry["alsoIn"],
            "license": entry["license"]["id"], "languages": entry["languages"], "files": len(pins),
            "bytes": sum(pin.size for pin in pins), "presentBytes": present,
            "missingBytes": sum(pin.size for pin in pins) - present,
            "differs": sum(1 for name, _size in states if name == "differs"),
            "extractBytes": entry["extract"]["estimatedBytes"], "extracted": extracted,
            "destination": str(directory),
        })
    extra = 0
    if reserve:
        corpus = n1.corpus_root(n1_sources, base / n1.CACHE_SUBDIRECTORY)
        extra = sum(pin["size"] for pin in n1.pinned_files(n1_sources, kinds=("tsv",))
                    if not (corpus / pin["path"]).exists())
    groups = {group: {"sources": [row["source"] for row in rows if row["group"] == group],
                      "bytes": sum(row["bytes"] for row in rows if row["group"] == group),
                      "missingBytes": sum(row["missingBytes"] for row in rows if row["group"] == group),
                      "extractBytes": sum(row["extractBytes"] for row in rows if row["group"] == group)}
              for group in GROUPS if any(row["group"] == group for row in rows)}
    download = sum(row["bytes"] for row in rows)
    missing = sum(row["missingBytes"] for row in rows) + extra
    extract_bytes = sum(row["extractBytes"] for row in rows if not row["extracted"])
    free = _free_bytes(base)
    runtime = runtime_spec(registry)
    runtime_root = model_root or acquire.default_model_root()
    receipt = acquire._read_json(runtime_root / runtime["venv"] / acquire.RUNTIME_RECEIPT_NAME) or {}
    return {
        "registry": str(REGISTRY_PATH.relative_to(REPO)), "destination": str(base), "sources": rows,
        "groups": groups, "downloadBytes": download, "missingBytes": missing, "n1TSVBytes": extra,
        "extractBytes": extract_bytes, "extractTotalBytes": sum(row["extractBytes"] for row in rows),
        "marginBytes": FREE_SPACE_MARGIN_BYTES, "freeBytes": free,
        "fetchFits": missing + FREE_SPACE_MARGIN_BYTES <= free,
        "fetchAndExtractFits": missing + extract_bytes + FREE_SPACE_MARGIN_BYTES <= free,
        "runtime": {"family": RUNTIME_FAMILY, "venv": str(runtime_root / runtime["venv"]),
                    "wheelBytes": runtime["downloadBytes"], "packages": runtime["packages"],
                    "built": receipt.get("lockSHA256") == runtime["lockSHA256"],
                    "needed": any(registry["sources"][source]["extract"]["format"] == "parquet"
                                  for source in selected)},
    }


def _gb(value: int) -> str:
    return f"{value / 1e9:.2f} GB"


def _print_plan(value: Mapping[str, Any]) -> None:
    print(f"Corpora registry {value['registry']} -> {value['destination']}")
    print(f"  {'group':12s} {'source':20s} {'files':>6s} {'download':>10s} {'present':>10s} {'extract':>10s}  "
          f"{'license':24s} languages")
    for row in value["sources"]:
        extracted = " (extracted)" if row["extracted"] else ""
        print(f"  {row['group']:12s} {row['source']:20s} {row['files']:6d} {_gb(row['bytes']):>10s} "
              f"{_gb(row['presentBytes']):>10s} {_gb(row['extractBytes']):>10s}  {row['license']:24s} "
              f"{', '.join(row['languages'])}{extracted}")
        if row["differs"]:
            print(f"    {row['differs']} files present with the wrong size; a fetch refuses them")
    for group, totals in value["groups"].items():
        print(f"  group {group}: download {_gb(totals['bytes'])} ({_gb(totals['missingBytes'])} to fetch), "
              f"extract about {_gb(totals['extractBytes'])}")
    if value["n1TSVBytes"]:
        print(f"  plus the N1 dev/test TSVs the reserve reads: {value['n1TSVBytes'] / 1e6:.1f} MB to fetch")
    runtime = value["runtime"]
    if runtime["needed"]:
        state = "built" if runtime["built"] else "not built: run `python3 scripts/audio_qc_corpora.py runtime`"
        print(f"  Parquet runtime {runtime['family']} ({runtime['packages']} packages, about "
              f"{runtime['wheelBytes'] / 1e6:.0f} MB of wheels): {state}")
    print(f"Download {_gb(value['downloadBytes'])} ({_gb(value['missingBytes'])} still to fetch, any N1 TSVs "
          f"included); extraction about "
          f"{_gb(value['extractTotalBytes'])} of WAVs ({_gb(value['extractBytes'])} not yet extracted; estimates, "
          "each extraction checks its own need first).")
    need = value["missingBytes"] + value["extractBytes"] + value["marginBytes"]
    print(f"Free {_gb(value['freeBytes'])}. fetch needs {_gb(value['missingBytes'] + value['marginBytes'])} "
          f"({'fits' if value['fetchFits'] else 'does not fit'}); fetch and extract need about {_gb(need)} "
          f"({'fits' if value['fetchAndExtractFits'] else 'does not fit'}), both with a 2 GiB margin.")


# --------------------------------------------------------------------------- #
# Runtime
# --------------------------------------------------------------------------- #

def ensure_runtime(registry: Mapping[str, Any], *, model_root: Path | None = None, opener: Any = None,
                   runner: Any = None) -> Path:
    """Build (or keep, while it still verifies) the corpora-parquet venv with the judge tool's own builder."""
    root = model_root or acquire.default_model_root()
    judges = acquire.load_valid_registry()
    view = runtime_view(registry, judges["acquisition"]["interpreter"])
    interpreter = acquire.ensure_interpreter(root, view["acquisition"]["interpreter"],
                                             **({"opener": opener} if opener else {}))
    return acquire.ensure_runtime(root, view, RUNTIME_FAMILY, interpreter, **({"runner": runner} if runner else {}))


def runtime_problems(registry: Mapping[str, Any], *, model_root: Path | None = None, runner: Any = None,
                     imports: bool = True) -> tuple[list[str], Path]:
    """What stands between the built runtime and its lock (offline); and its interpreter path."""
    root = model_root or acquire.default_model_root()
    judges = acquire.load_valid_registry()
    view = runtime_view(registry, judges["acquisition"]["interpreter"])
    problems, _counts = acquire._verify_runtime(root, view, RUNTIME_FAMILY, runner=runner or acquire._run,
                                                repository=REPO, imports=imports)
    interpreter_problems, _counts = acquire.interpreter_check(root, view["acquisition"]["interpreter"])
    return problems + interpreter_problems, root / runtime_spec(registry)["venv"] / "bin" / "python3"


def run_worker(python: Path) -> WorkerRunner:
    def runner(job_path: Path, _job: Mapping[str, Any]) -> None:
        result = subprocess.run([str(python), str(WORKER), str(job_path)], env=acquire.build_environment(),
                                cwd=str(job_path.parent), check=False)
        if result.returncode != 0:
            raise CorporaError("the Parquet worker failed (its message is above); nothing of this source is kept")
    return runner


# --------------------------------------------------------------------------- #
# Extraction: members, metadata and labels
# --------------------------------------------------------------------------- #

IGNORED = "ignored"


class Members:
    """A source's member pattern: which archive members or pinned files are its clips, and their labels."""

    def __init__(self, spec: Mapping[str, Any]) -> None:
        self.pattern = re.compile(spec["members"])
        self.ignore = [re.compile(pattern) for pattern in spec.get("ignore") or ()]
        self.template = spec.get("idTemplate")

    def match(self, name: str) -> dict[str, str] | str | None:
        """The member's labels; `IGNORED` for an ignored member, None for another non-clip member. A WAV the
        pattern does not name refuses the source."""
        if any(pattern.search(name) for pattern in self.ignore):
            return IGNORED
        match = self.pattern.fullmatch(name)
        if match is None:
            if name.lower().endswith(".wav"):
                raise CorporaError(f"{name[:120]!r} is a WAV the source's member pattern does not name; nothing is "
                                   "kept")
            return None
        groups = {key: value for key, value in match.groupdict().items() if value is not None}
        identity = self.template.format(**groups) if self.template else groups.get("id") or PurePosixPath(name).stem
        return {"sourceID": identity, **{key: value for key, value in groups.items()
                                         if key in ("speaker", "gender", "emotion", "intensity", "textID")}}

    def clip(self, name: str, counts: Counter[str]) -> dict[str, str] | None:
        """The member's labels when it is a clip; otherwise counts it as ignored or another member."""
        matched = self.match(name)
        if isinstance(matched, dict):
            return matched
        counts["ignored" if matched == IGNORED else "otherMembers"] += 1
        return None


def _normalize_key(value: Any, how: str | None) -> str | None:
    text = clips.label_text(value)
    if text is None:
        return None
    if how == "stem":
        return PurePosixPath(text).stem if text.lower().endswith(".wav") else text
    if how == "int":
        return str(int(text)) if text.isdigit() else text
    return text


PINYIN = re.compile(r"[a-z]+[1-5]?", re.ASCII)


@dataclass(frozen=True)
class MetadataTable:
    """One declared metadata table as read: its rows by normalized key (None when an optional table is missing or
    unreadable, `problem` saying why), how many keys had rows that disagree on a label (that label is dropped for
    the key, never guessed), and the one language whose clips it labels (a metadata file that names its language;
    None labels every clip)."""

    spec: Mapping[str, Any]
    rows: dict[str, dict[str, str | None]] | None
    problem: str | None = None
    conflicts: int = 0
    language: str | None = None


def _keep_row(table: dict[str, dict[str, str | None]], conflicted: set[str], key: str | None,
              values: dict[str, str | None]) -> None:
    """The first row of a key wins; a later row that gives a label another value drops that label for the key."""
    if key is None:
        return
    kept = table.setdefault(key, values)
    if kept is values:
        return
    for name, value in values.items():
        if value is not None and kept.get(name) is not None and kept[name] != value:
            kept[name] = None
            conflicted.add(key)


def parse_table(data: bytes, spec: Mapping[str, Any], label: str) -> tuple[dict[str, dict[str, str | None]], int]:
    """A metadata table keyed by its normalized key, holding only the declared fields, and the number of keys whose
    rows disagree on a field (`_keep_row`)."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CorporaError(f"{label} is not UTF-8") from None
    fields: Mapping[str, Any] = spec["fields"]
    how = spec.get("keyNormalize")
    table: dict[str, dict[str, str | None]] = {}
    conflicted: set[str] = set()
    fmt = spec["format"]
    if fmt == "csv":
        reader = csv.DictReader(io.StringIO(text))
        header = reader.fieldnames or []
        needed = [spec.get("keyColumn"), *fields.values()]
        missing = [str(name) for name in needed if name not in header]
        if missing:
            raise CorporaError(f"{label} has no column {', '.join(missing)}; its header is {', '.join(header)}")
        for row in reader:
            _keep_row(table, conflicted, _normalize_key(row.get(spec["keyColumn"]), how),
                      {name: clips.label_text(row.get(column)) for name, column in fields.items()})
        return table, len(conflicted)
    skip_header = bool(spec.get("header"))
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if skip_header:
            skip_header = False
            continue
        if fmt == "pipe":
            parts = line.split("|")
            if int(spec.get("keyColumn", 0)) >= len(parts):
                continue
            key = _normalize_key(parts[int(spec.get("keyColumn", 0))], how)
            values = {name: clips.label_text(parts[int(column)]) if int(column) < len(parts) else None
                      for name, column in fields.items()}
        elif fmt == "whitespace":
            parts = line.split()
            columns = list(spec["columns"])
            row = dict(zip(columns, parts))
            key = _normalize_key(row.get(spec.get("keyColumn", columns[0])), how)
            values = {name: clips.label_text(row.get(column)) for name, column in fields.items()}
        else:  # aishell3-content: `<utterance>.wav` then characters interleaved with their pinyin
            parts = line.split()
            key = _normalize_key(parts[0], "stem")
            rest = parts[1:]
            if rest and len(rest) % 2 == 0 and all(PINYIN.fullmatch(token) for token in rest[1::2]):
                sentence = "".join(rest[0::2])
            else:
                sentence = " ".join(rest)
            values = {name: (sentence or None) if column == "text" else None for name, column in fields.items()}
        _keep_row(table, conflicted, key, values)
    return table, len(conflicted)


def load_table(spec: Mapping[str, Any], data: bytes | None, label: str, *,
               language: str | None = None) -> MetadataTable:
    """A metadata table parsed; an optional one that is missing or unreadable is kept as its reason instead,
    so a label enrichment never costs the corpus."""
    try:
        if data is None:
            raise CorporaError(f"{label} is missing")
        rows, conflicts = parse_table(data, spec, label)
        if conflicts:
            _log(f"{label}: {conflicts} keys have rows that disagree on a label; it is dropped for them")
        return MetadataTable(spec, rows, conflicts=conflicts, language=language)
    except CorporaError as error:
        if not spec.get("optional"):
            raise
        _log(f"optional metadata not joined: {error}")
        return MetadataTable(spec, None, str(error), language=language)


def apply_metadata(records: list[dict[str, Any]], tables: Sequence[MetadataTable]) -> dict[str, Any]:
    """Join each metadata table onto the clips in registry order (a table of one language onto that language's
    clips only); returns rows, unjoined clips and any conflicting keys per table."""
    joined: dict[str, Any] = {}
    for table in tables:
        spec = table.spec
        name = spec.get("member") or spec.get("file")
        scoped = [record for record in records if table.language is None or record.get("language") == table.language]
        if table.rows is None:
            joined[name] = {"rows": 0, "unjoinedClips": len(scoped), "problem": table.problem}
            continue
        unjoined = 0
        for record in scoped:
            key = _normalize_key(record.get(spec["joinOn"]), spec.get("keyNormalize"))
            row = table.rows.get(key) if key is not None else None
            if row is None:
                unjoined += 1
                continue
            for label, value in row.items():
                if value is not None:
                    record[label] = value
        joined[name] = {"rows": len(table.rows), "unjoinedClips": unjoined,
                        **({"conflictingKeys": table.conflicts} if table.conflicts else {})}
    return joined


def finalize_labels(record: dict[str, Any], spec: Mapping[str, Any], languages: Sequence[str]) -> None:
    """Constants, then the registry's maps: the corpus's own emotion beside its canonical name, gender as
    male or female (never a guess), intensity spelled out."""
    for name, value in (spec.get("constants") or {}).items():
        if record.get(name) is None:
            record[name] = value
    maps = spec.get("maps") or {}
    record["gender"] = clips.gender(record.get("gender"), maps.get("gender"))
    prefix = spec.get("genderFromSpeakerPrefix") or {}
    if record["gender"] is None and prefix and record.get("speaker"):
        record["gender"] = prefix.get(str(record["speaker"])[:1])
    record["emotion"], record["emotionCanonical"] = clips.emotion(record.get("emotion"), maps.get("emotion"))
    if record.get("intensity") is not None:
        record["intensity"] = (maps.get("intensity") or {}).get(record["intensity"], record["intensity"])
    if record.get("language") is None and len(languages) == 1:
        record["language"] = languages[0]


# --------------------------------------------------------------------------- #
# Extraction: formats
# --------------------------------------------------------------------------- #

def _add_clip(sink: clips.ClipSink, source: str, spec: Mapping[str, Any], labels: Mapping[str, Any],
              data: bytes, origin: str) -> None:
    try:
        wav, info = clips.clip_from_wav(data, output_rate=spec["outputRate"])
        identifier = clips.clip_id(source, labels["sourceID"])
    except clips.CorpusAudioError as error:
        sink.skip(origin, str(error))
        return
    sink.add(identifier, wav, info, labels, origin=origin, source_sha256=hashlib.sha256(data).hexdigest())


def _labels(entry: Mapping[str, Any], matched: Mapping[str, str], pin: Pin | None) -> dict[str, Any]:
    language = pin.language if pin is not None and pin.language else None
    return {"language": language, "split": pin.split if pin is not None else None, **matched}


def file_tables(spec: Mapping[str, Any], pins: Sequence[Pin], directory: Path,
                receipt: Receipt) -> list[MetadataTable]:
    """The source's pinned metadata files as tables, each checked against its pin first: a file present but
    differing refuses the source, a required one not fetched too, an optional one missing is kept as its reason.
    A file that names its language labels that language's clips only."""
    tables = []
    for table in spec.get("metadata") or ():
        pin = next(pin for pin in pins if pin.path == table["file"])
        path = directory / pin.path
        data = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        if data is not None:
            receipt.record(pin, check_bytes(data, pin, receipt.recorded(pin)))
        elif not table.get("optional"):
            raise CorporaError(f"{pin.path} is not fetched; run `fetch` first")
        tables.append(load_table(table, data, pin.path, language=pin.language))
    return tables


def _extract_wav_files(source: str, entry: Mapping[str, Any], pins: Sequence[Pin], directory: Path,
                       receipt: Receipt, sink: clips.ClipSink, tables: list) -> dict[str, int]:
    spec = entry["extract"]
    members = Members(spec)
    tables += file_tables(spec, pins, directory, receipt)
    counts: Counter[str] = Counter()
    audio = [pin for pin in pins if pin.role == "audio"]
    for index, pin in enumerate(audio, 1):
        matched = members.clip(pin.path, counts)
        if matched is None:
            continue
        path = directory / pin.path
        if path.is_symlink() or not path.is_file():
            raise CorporaError(f"{pin.path} is not fetched; run `fetch` first")
        data = path.read_bytes()
        receipt.record(pin, check_bytes(data, pin, receipt.recorded(pin)))
        _add_clip(sink, source, spec, _labels(entry, matched, pin), data, pin.path)
        if index % 1000 == 0:
            _log(f"{source}: {index}/{len(audio)} files decoded")
    return dict(counts)


def _safe_zip_member(info: zipfile.ZipInfo, label: str) -> str | None:
    name = info.filename
    if name.startswith("/") or "\\" in name or "\0" in name or any(part in ("", ".", "..")
                                                                   for part in name.rstrip("/").split("/")):
        raise CorporaError(f"{label}: member {name[:120]!r} is an absolute or unsafe path; nothing is kept")
    if info.flag_bits & 0x1:
        raise CorporaError(f"{label}: member {name[:120]!r} is encrypted; nothing is kept")
    if (info.external_attr >> 16) & 0o170000 == 0o120000:
        raise CorporaError(f"{label}: member {name[:120]!r} is a link; nothing is kept")
    return None if info.is_dir() else name


def _read_capped(stream: Any, size: int, label: str, name: str) -> bytes:
    if size > MAX_MEMBER_BYTES:
        raise CorporaError(f"{label}: member {name[:120]!r} is larger than {MAX_MEMBER_BYTES} bytes; nothing is kept")
    data = stream.read(MAX_MEMBER_BYTES + 1)
    if len(data) != size:
        raise CorporaError(f"{label}: member {name[:120]!r} is truncated; nothing is kept")
    return data


def _extract_zip(source: str, entry: Mapping[str, Any], pin: Pin, path: Path, sink: clips.ClipSink,
                 tables: list) -> dict[str, int]:
    spec = entry["extract"]
    members = Members(spec)
    wanted = {table["member"]: table for table in spec.get("metadata") or ()}
    counts: Counter[str] = Counter()
    try:
        with zipfile.ZipFile(path) as bundle:
            infos = sorted(bundle.infolist(), key=lambda info: info.filename)
            names = {info.filename: info for info in infos}
            for member, table in wanted.items():
                info = names.get(member)
                data = None
                if info is not None:
                    with bundle.open(info) as stream:
                        data = _read_capped(stream, info.file_size, pin.path, member)
                tables.append(load_table(table, data, member))
            for info in infos:
                name = _safe_zip_member(info, pin.path)
                if name is None or name in wanted:
                    continue
                matched = members.clip(name, counts)
                if matched is None:
                    continue
                with bundle.open(info) as stream:
                    data = _read_capped(stream, info.file_size, pin.path, name)
                _add_clip(sink, source, spec, _labels(entry, matched, None), data, name)
    except (zipfile.BadZipFile, zlib.error, EOFError) as error:
        raise CorporaError(f"{pin.path} is not a readable zip archive ({type(error).__name__})") from None
    return dict(counts)


def _extract_tar(source: str, entry: Mapping[str, Any], pin: Pin, path: Path, sink: clips.ClipSink,
                 tables: list) -> dict[str, int]:
    spec = entry["extract"]
    members = Members(spec)
    wanted = {table["member"]: table for table in spec.get("metadata") or ()}
    found: dict[str, bytes] = {}
    counts: Counter[str] = Counter()
    try:
        with tarfile.open(path, "r|gz") as bundle:
            for member in bundle:
                parts = n1.member_parts(member, pin.path)
                if member.isdir() or not parts:
                    continue
                name = "/".join(parts)
                if name in wanted:
                    stream = bundle.extractfile(member)
                    found[name] = _read_capped(stream, member.size, pin.path, name) if stream else b""
                    continue
                matched = members.clip(name, counts)
                if matched is None:
                    continue
                stream = bundle.extractfile(member)
                data = _read_capped(stream, member.size, pin.path, name) if stream is not None else b""
                _add_clip(sink, source, spec, _labels(entry, matched, None), data, name)
    except (tarfile.TarError, EOFError, zlib.error) as error:
        raise CorporaError(f"{pin.path} is not a readable tar.gz archive ({type(error).__name__})") from None
    for member, table in wanted.items():
        tables.append(load_table(table, found.get(member), member))
    return dict(counts)


def _extract_parquet(source: str, entry: Mapping[str, Any], pins: Sequence[Pin], directory: Path, staging: Path,
                     worker: WorkerRunner) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, int]]:
    spec = entry["extract"]
    multilingual = len(entry["languages"]) > 1
    job = {
        "schemaVersion": 1, "kind": "audio-qc-corpora-parquet-job", "source": source,
        "outputRate": spec["outputRate"], "extract": spec, "wavDirectory": str(staging / "wav"),
        "results": str(staging / RESULTS_NAME),
        "files": [{"path": str(directory / pin.path), "shard": pin.path, "split": pin.split,
                   "language": pin.language or entry["languages"][0],
                   "idPrefix": lm.LANGUAGE_LOCALE_CODES[pin.language] if multilingual else None}
                  for pin in pins if pin.role == "audio"],
    }
    job_path = staging / JOB_NAME
    jsonio.atomic_json(job_path, job, ascii=False, allow_nan=False)
    worker(job_path, job)
    try:
        result = json.loads((staging / RESULTS_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise CorporaError(f"{source}: the Parquet worker wrote no readable result") from None
    finally:
        job_path.unlink(missing_ok=True)
    (staging / RESULTS_NAME).unlink(missing_ok=True)
    if not isinstance(result, dict) or result.get("kind") != "audio-qc-corpora-parquet-result" \
            or result.get("source") != source or not isinstance(result.get("clips"), list) \
            or not isinstance(result.get("skipped"), list):
        raise CorporaError(f"{source}: the Parquet worker's result is not this job's")
    for record in result["clips"]:
        path = staging / str(record.get("wavPath"))
        if record.get("wavPath") != f"wav/{record.get('clipID')}.wav" or not _inside(staging, path) \
                or path.is_symlink() or not path.is_file() or path.stat().st_size != record.get("wavBytes"):
            raise CorporaError(f"{source}: the Parquet worker's clip {record.get('clipID')} is not on disk as it "
                               "says")
    shards = {item.get("shard"): item.get("rows") for item in result.get("shards") or ()}
    counts = {"rows": sum(value for value in shards.values() if isinstance(value, int))}
    if isinstance(result.get("capKept"), int):
        counts["capKept"] = result["capKept"]
    return result["clips"], result["skipped"], counts


# --------------------------------------------------------------------------- #
# Extraction: manifests
# --------------------------------------------------------------------------- #

def extraction_identity(registry: Mapping[str, Any], source: str) -> str:
    """What an extraction is bound to: the pins, the extraction spec (its estimate aside) and the languages."""
    entry = registry["sources"][source]
    spec = {key: value for key, value in entry["extract"].items() if key not in ("estimatedBytes", "estimateBasis")}
    return jsonio.sha256_json({"extractor": EXTRACTOR, "source": source, "languages": entry["languages"],
                               "extract": spec, "files": entry.get("files") or [],
                               "pinFile": (entry.get("pinFile") or {}).get("sha256")}, ascii=False)


def manifest_counts(records: Sequence[Mapping[str, Any]], skipped: Sequence[Any]) -> dict[str, Any]:
    def tally(field: str, default: str) -> dict[str, int]:
        return dict(sorted(Counter(str(record.get(field) or default) for record in records).items()))

    return {
        "clips": len(records), "skipped": len(skipped),
        "duplicates": sum(len(record.get("duplicates") or ()) for record in records),
        "durationSeconds": round(sum(float(record["durationSeconds"]) for record in records), 3),
        "speakers": len({(record.get("language"), record["speaker"]) for record in records if record.get("speaker")}),
        "byLanguage": tally("language", "unknown"), "bySplit": tally("split", "none"),
        "byGender": tally("gender", "unknown"), "byEmotion": tally("emotion", "none"),
        "byEmotionCanonical": tally("emotionCanonical", "none"),
        "resampledClips": sum(1 for record in records if record.get("resampled")),
        "clippedSamples": sum(int(record.get("clippedSamples") or 0) for record in records),
    }


def build_manifest(registry: Mapping[str, Any], source: str, records: list[dict[str, Any]],
                   skipped: Sequence[Mapping[str, str]], *, metadata: Mapping[str, Any],
                   members: Mapping[str, int]) -> dict[str, Any]:
    entry = registry["sources"][source]
    origin = ({"record": entry["record"], "version": entry["version"]} if host_kind(entry) == "zenodo"
              else {"repository": entry["repository"], "revision": entry["revision"]})
    manifest = {
        "schemaVersion": SCHEMA_VERSION, "kind": MANIFEST_KIND, "extractor": EXTRACTOR, "source": source,
        "title": entry["title"], "groups": [entry["group"], *entry["alsoIn"]], "host": entry["host"], **origin,
        "license": entry["license"], "attribution": entry["attribution"], "caveats": entry["caveats"],
        "languages": entry["languages"], "labels": entry["labels"],
        "extractionSHA256": extraction_identity(registry, source), "sampleRate": entry["extract"]["outputRate"],
        "audio": {"format": "mono PCM16 WAV", "resampler": clips.RESAMPLER,
                  "implementation": clips.RESAMPLER_IMPLEMENTATION},
        "metadata": dict(metadata), "members": dict(members), "counts": manifest_counts(records, skipped),
        "skipped": list(skipped), "clips": records,
    }
    manifest["manifestDigest"] = self_digest(manifest, "manifestDigest")
    return manifest


def manifest_issues(manifest: Any, identity: str | None = None) -> list[str]:
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != SCHEMA_VERSION \
            or manifest.get("kind") != MANIFEST_KIND or manifest.get("extractor") != EXTRACTOR:
        return [f"the manifest is not an {MANIFEST_KIND} manifest of {EXTRACTOR}"]
    if manifest.get("manifestDigest") != self_digest(manifest, "manifestDigest"):
        return ["the manifest digest does not match its content"]
    if identity is not None and manifest.get("extractionSHA256") != identity:
        return ["the manifest was extracted from other pins or another extraction spec"]
    if not isinstance(manifest.get("clips"), list):
        return ["the manifest lists no clips"]
    return []


def extraction_problems(directory: Path, identity: str | None = None, *, deep: bool = True) -> list[str]:
    """Why an extraction directory is not current: its manifest, then every WAV's size and SHA-256."""
    try:
        manifest = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ["not extracted"]
    problems = manifest_issues(manifest, identity)
    if problems:
        return problems
    for record in manifest["clips"]:
        relative = record.get("wavPath")
        path = directory / str(relative)
        if relative != f"wav/{record.get('clipID')}.wav" or path.is_symlink() or not path.is_file() \
                or path.stat().st_size != record.get("wavBytes") \
                or (deep and jsonio.sha256_file(path) != record.get("wavSHA256")):
            return [f"{record.get('clipID')} is missing or differs from its manifest"]
    return []


def _extraction_current(registry: Mapping[str, Any], source: str, base: Path,
                        n1_sources: Mapping[str, Any] | None) -> bool:
    entry = registry["sources"][source]
    if entry["extract"]["format"] == "fleurs-reserve":
        return not reserve_problems(registry, source, root=base, n1_sources=n1_sources, deep=False)
    directory = source_directory(registry, source, base) / EXTRACTED_DIRECTORY
    return not extraction_problems(directory, extraction_identity(registry, source), deep=False)


def extract_source(registry: Mapping[str, Any], source: str, *, root: Path | None = None,
                   worker: WorkerRunner | None = None) -> dict[str, Any]:
    entry = registry["sources"][source]
    spec = entry["extract"]
    directory = source_directory(registry, source, root)
    final = directory / EXTRACTED_DIRECTORY
    identity = extraction_identity(registry, source)
    if not extraction_problems(final, identity):
        _log(f"{source}: extraction present and verified")
        manifest = json.loads((final / MANIFEST_NAME).read_text(encoding="utf-8"))
        return {"source": source, "status": "present", "counts": manifest["counts"]}
    pins = source_pins(registry, source)
    receipt = Receipt(directory, source)
    if spec["format"] != "wav-files":
        for pin in pins:
            if pin.role != "audio":
                continue  # a metadata file is checked as its table is read
            final_path = directory / pin.path
            _log(f"{source}: verifying {pin.path} ({pin.size / 1e6:.1f} MB)")
            if not final_path.exists():
                raise CorporaError(f"{source}: {pin.path} is not fetched; run `fetch` first")
            receipt.record(pin, check_file(final_path, pin, receipt.recorded(pin)))
    _require_free(directory, spec["estimatedBytes"], f"extracting {source}")
    staging = directory / f".staging-{EXTRACTED_DIRECTORY}"
    acquire._remove_owned(staging)
    staging.mkdir(parents=True)
    (staging / acquire.OWNED_MARKER).write_text(f"audio QC corpus extraction {source}\n", encoding="utf-8")
    try:
        tables: list[MetadataTable] = []
        members: dict[str, int] = {}
        if spec["format"] == "parquet":
            tables += file_tables(spec, pins, directory, receipt)
            if worker is None:
                problems, python = runtime_problems(registry)
                if problems:
                    raise CorporaError(f"the {RUNTIME_FAMILY} runtime is not ready ({problems[0]}); run "
                                       "`python3 scripts/audio_qc_corpora.py runtime` first")
                worker = run_worker(python)
            records, skipped, members = _extract_parquet(source, entry, pins, directory, staging, worker)
        else:
            sink = clips.ClipSink(staging / "wav")
            if spec["format"] == "wav-files":
                members = _extract_wav_files(source, entry, pins, directory, receipt, sink, tables)
            else:
                archive = next(pin for pin in pins if pin.role == "audio")
                _log(f"{source}: extracting {archive.path}")
                extractor = _extract_zip if spec["format"] == "zip" else _extract_tar
                members = extractor(source, entry, archive, directory / archive.path, sink, tables)
            records, skipped = sink.clips, sink.skipped
        joined = apply_metadata(records, tables)
        for record in records:
            finalize_labels(record, spec, entry["languages"])
        if not records:
            raise CorporaError(f"{source}: no clip was extracted")
        manifest = build_manifest(registry, source, records, skipped, metadata=joined, members=members)
        jsonio.atomic_json(staging / MANIFEST_NAME, manifest, ascii=False, allow_nan=False)
        acquire._remove_owned(final)
        os.replace(staging, final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        receipt.write()
    counts = manifest["counts"]
    _log(f"{source}: {counts['clips']} clips ({counts['durationSeconds'] / 3600:.1f} h), {counts['skipped']} "
         f"skipped, {counts['duplicates']} duplicates")
    return {"source": source, "status": "extracted", "counts": counts}


# --------------------------------------------------------------------------- #
# FLEURS reserve cohorts
# --------------------------------------------------------------------------- #

def _order(seed: str, language: str, value: Any) -> str:
    return hashlib.sha256(f"{seed}\0{language}\0{value}".encode("utf-8")).hexdigest()


def reserve_selection(rows: Sequence[n1.Row], *, language: str, shared_ids: set[int], cohorts: int,
                      per_language: int, seed: str) -> list[list[n1.Row]]:
    """The seeded cohorts of one language (`RESERVE_RULE`)."""
    by_sentence: dict[int, list[n1.Row]] = {}
    for row in rows:
        reasons, _lint, _proper = n1.ineligible_reasons(row.text, language,
                                                        shared_script=row.sentence_id in shared_ids)
        if not reasons:
            by_sentence.setdefault(row.sentence_id, []).append(row)
    selected: list[list[n1.Row]] = [[] for _ in range(cohorts)]
    index = 0
    for sentence in sorted(by_sentence, key=lambda value: _order(seed, language, value)):
        if index == cohorts:
            break
        recordings = sorted(by_sentence[sentence], key=lambda row: _order(seed, language, row.file))
        selected[index].extend(recordings[:per_language - len(selected[index])])
        if len(selected[index]) == per_language:
            index += 1
    return selected


def _reserve_pins(registry: Mapping[str, Any], source: str) -> dict[str, tuple[Pin, Pin]]:
    pins = {pin.path: pin for pin in source_pins(registry, source)}
    configs = {language: n1.FLEURS_CONFIGS[language] for language in registry["sources"][source]["languages"]}
    return {language: (pins[f"data/{config}/train.tsv"], pins[f"data/{config}/audio/train.tar.gz"])
            for language, config in configs.items()}


def sampling_digest(registry: Mapping[str, Any], source: str, n1_sources: Mapping[str, Any]) -> str:
    spec = registry["sources"][source]["extract"]
    pins = _reserve_pins(registry, source)
    return jsonio.sha256_json({
        "version": RESERVE_VERSION, "rule": RESERVE_RULE, "seed": spec["seed"], "cohorts": spec["cohorts"],
        "perLanguage": spec["perLanguage"], "eligibility": n1.ELIGIBILITY_VERSION,
        "n1SourcesDigest": n1.sources_digest(n1_sources),
        "train": {language: {"tsv": tsv.digest, "archive": archive.digest}
                  for language, (tsv, archive) in pins.items()},
    }, ascii=False)


def _reserve_receipt_matches(directory: Path, expected: Mapping[str, Any]) -> bool:
    try:
        receipt = json.loads((directory / n1.RECEIPT_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(receipt, dict) or {key: receipt.get(key) for key in expected} != dict(expected) \
            or not isinstance(receipt.get("files"), dict):
        return False
    for name, file in receipt["files"].items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != file.get("bytes") \
                or jsonio.sha256_file(path) != file.get("sha256"):
            return False
    return True


def extract_fleurs_reserve(registry: Mapping[str, Any], source: str, *, root: Path | None = None,
                           n1_sources: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Sample, extract and write the reserve cohorts of FLEURS train (`RESERVE_RULE`)."""
    n1_sources = n1_sources or load_n1_sources()
    spec = registry["sources"][source]["extract"]
    corpus = source_directory(registry, source, root)
    digest = sampling_digest(registry, source, n1_sources)
    reserve = corpus / RESERVE_DIRECTORY / digest[:12]
    receipt = Receipt(corpus, source)
    cohorts: list[list[dict[str, Any]]] = [[] for _ in range(spec["cohorts"])]
    shortfall: dict[str, list[int]] = {}
    try:
        for language, (tsv_pin, archive_pin) in _reserve_pins(registry, source).items():
            entry = n1.language_entry(n1_sources, language)
            config = entry["config"]
            dev, test = (n1.read_tsv(corpus / n1.split_entry(entry, name)["tsv"]["path"],
                                     n1.split_entry(entry, name)["tsv"]) for name in ("dev", "test"))
            tsv_path = corpus / tsv_pin.path
            if not tsv_path.is_file():
                raise CorporaError(f"{tsv_pin.path} is not fetched; run `fetch --group fleurs-train` first")
            data = tsv_path.read_bytes()
            receipt.record(tsv_pin, check_bytes(data, tsv_pin, receipt.recorded(tsv_pin)))
            train = n1.parse_tsv(data, tsv_pin.path)
            if {row.file for row in train} & {row.file for row in [*dev, *test]}:
                raise CorporaError(f"{tsv_pin.path} names a recording file that dev or test also names")
            selection = reserve_selection(train, language=language,
                                          shared_ids={row.sentence_id for row in [*dev, *test]},
                                          cohorts=spec["cohorts"], per_language=spec["perLanguage"],
                                          seed=spec["seed"])
            shortfall[language] = [spec["perLanguage"] - len(rows) for rows in selection]
            keep = {row.file for rows in selection for row in rows}
            extracted = reserve / EXTRACTED_DIRECTORY / config
            expected = {"schemaVersion": SCHEMA_VERSION, "kind": RESERVE_RECEIPT_KIND, "samplingDigest": digest,
                        "config": config, "tsv": tsv_pin.as_record(), "archive": archive_pin.as_record(),
                        "decoder": n1.EXTRACTOR}
            if _reserve_receipt_matches(extracted, expected):
                _log(f"{language}: reserve recordings present and verified")
                files = json.loads((extracted / n1.RECEIPT_NAME).read_text(encoding="utf-8"))["files"]
            else:
                files = _extract_reserve_language(corpus, receipt, archive_pin, train, keep, extracted, expected,
                                                  language)
            for index, rows in enumerate(selection):
                for row in rows:
                    cohorts[index].append({"row": row, "language": language, "config": config,
                                           "source": extracted / row.file, "digest": files[row.file]["sha256"]})
    finally:
        receipt.write()
    written = []
    for index, members in enumerate(cohorts, 1):
        output = reserve / f"cohort-{index}" / MANIFEST_NAME
        manifest = write_reserve_manifest(n1_sources, members, output=output, cohort=index, digest=digest,
                                          spec=spec, identity=extraction_identity(registry, source))
        written.append({"cohort": index, "manifest": str(output), "counts": manifest["counts"]})
        _log(f"reserve cohort {index}: {manifest['counts']['recordings']} recordings -> {output}")
    short = {language: values for language, values in shortfall.items() if any(values)}
    if short:
        _log("some languages could not fill every cohort (recordings short per cohort): "
             + "; ".join(f"{language} {values}" for language, values in short.items()))
    return {"source": source, "status": "extracted", "samplingDigest": digest, "cohorts": written,
            "shortfall": short}


def _extract_reserve_language(corpus: Path, receipt: Receipt, archive_pin: Pin, train: Sequence[n1.Row],
                              keep: set[str], extracted: Path, expected: Mapping[str, Any],
                              language: str) -> dict[str, dict[str, Any]]:
    if not keep:
        return {}
    archive = corpus / archive_pin.path
    _log(f"{language}: verifying {archive_pin.path} ({archive_pin.size / 1e6:.1f} MB)")
    if not archive.exists():
        raise CorporaError(f"{archive_pin.path} is not fetched; run `fetch --group fleurs-train` first")
    receipt.record(archive_pin, check_file(archive, archive_pin, receipt.recorded(archive_pin)))
    samples = {row.file: row.samples for row in train}
    _require_free(extracted.parent, sum(n1.WAV_HEADER_BYTES + 2 * samples[name] for name in keep),
                  f"extracting the {language} reserve")
    staging = extracted.parent / f".staging-{extracted.name}"
    acquire._remove_owned(staging)
    staging.mkdir(parents=True)
    (staging / acquire.OWNED_MARKER).write_text(f"audio QC FLEURS reserve {extracted.name}\n", encoding="utf-8")
    try:
        _log(f"{language}: extracting {len(keep)} of {len(train)} train recordings from {archive_pin.path}")
        member_directory, files, counts = n1.extract_members(archive, archive_pin.as_record(), "train", train,
                                                             staging / "train", keep=keep)
        for name in files:
            os.replace(staging / "train" / name, staging / name)
        (staging / "train").rmdir()
        jsonio.atomic_json(staging / n1.RECEIPT_NAME, {**expected, "memberDirectory": member_directory,
                                                       "members": counts, "files": files},
                           ascii=False, allow_nan=False)
        acquire._remove_owned(extracted)
        os.replace(staging, extracted)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return files


def write_reserve_manifest(n1_sources: Mapping[str, Any], members: Sequence[Mapping[str, Any]], *, output: Path,
                           cohort: int, digest: str, spec: Mapping[str, Any], identity: str) -> dict[str, Any]:
    """One reserve cohort as an `audio-qc-n1-cohort` manifest, its WAVs linked beside it."""
    output = output.resolve()
    takes = []
    for member in members:
        row = member["row"]
        take = n1.recording_take(row, language=member["language"], config=member["config"], fleurs_split="train",
                                 digest=member["digest"], shared_script=False)
        n1._place(member["source"], output.parent / take["wavPath"], member["digest"])
        takes.append(take)
    languages = [language for language in lm.PRODUCT_LANGUAGES if any(take["language"] == language for take in takes)]
    manifest: dict[str, Any] = {
        "schemaVersion": n1.SCHEMA_VERSION, "kind": n1.MANIFEST_KIND, "population": n1.POPULATION,
        "dataset": n1.DATASET, "revision": n1_sources["revision"], "sourcesDigest": n1.sources_digest(n1_sources),
        "license": n1.LICENSE, "attribution": n1.ATTRIBUTION, "split": f"reserve-{cohort}", "fleursSplit": "train",
        "languages": languages, "sampleRate": n1.SAMPLE_RATE,
        "eligibility": {"version": n1.ELIGIBILITY_VERSION, "rules": n1.ELIGIBILITY_RULES},
        "limitations": n1.LIMITATIONS, "counts": n1.cohort_counts(takes), "takes": takes,
        "reserve": {"cohort": cohort, "cohorts": spec["cohorts"], "perLanguage": spec["perLanguage"],
                    "seed": spec["seed"], "rule": RESERVE_RULE, "version": RESERVE_VERSION,
                    "samplingDigest": digest, "extractionSHA256": identity},
    }
    manifest["manifestDigest"] = self_digest(manifest, "manifestDigest")
    jsonio.atomic_json(output, manifest, ascii=False, allow_nan=False)
    return manifest


def reserve_problems(registry: Mapping[str, Any], source: str, *, root: Path | None = None,
                     n1_sources: Mapping[str, Any] | None = None, deep: bool = True) -> list[str]:
    """Why the current sampling's reserve cohorts are not in place: each manifest, then (deep) each WAV."""
    n1_sources = n1_sources or load_n1_sources()
    spec = registry["sources"][source]["extract"]
    digest = sampling_digest(registry, source, n1_sources)
    reserve = source_directory(registry, source, root) / RESERVE_DIRECTORY / digest[:12]
    problems = []
    for index in range(1, spec["cohorts"] + 1):
        path = reserve / f"cohort-{index}" / MANIFEST_NAME
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            problems.append(f"cohort {index} is not extracted")
            continue
        issues = n1.manifest_digest_issues(manifest)
        if issues or (manifest.get("reserve") or {}).get("samplingDigest") != digest:
            problems.append(f"cohort {index}: {issues[0] if issues else 'another sampling wrote it'}")
            continue
        for take in manifest["takes"]:
            wav = path.parent / take["wavPath"]
            if wav.is_symlink() or not wav.is_file() or (deep and jsonio.sha256_file(wav) != take["wavSHA256"]):
                problems.append(f"cohort {index}: {take['takeID']} is missing or differs from its manifest")
                break
    return problems


def extract(registry: Mapping[str, Any], selected: Sequence[str], *, root: Path | None = None,
            worker: WorkerRunner | None = None, n1_sources: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    report = []
    for source in selected:
        if registry["sources"][source]["extract"]["format"] == "fleurs-reserve":
            report.append(extract_fleurs_reserve(registry, source, root=root, n1_sources=n1_sources))
        else:
            report.append(extract_source(registry, source, root=root, worker=worker))
    return report


# --------------------------------------------------------------------------- #
# Verify
# --------------------------------------------------------------------------- #

def verify(registry: Mapping[str, Any], selected: Sequence[str], *, root: Path | None = None,
           runtime: Callable[[], list[str]] | None = None,
           n1_sources: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Offline: every selected download against its pin and receipt, every extraction against its manifest, and
    the Parquet runtime against its lock."""
    results = []
    for source in selected:
        entry = registry["sources"][source]
        directory = source_directory(registry, source, root)
        receipt = Receipt(directory, source)
        problems: list[str] = []
        absent = verified = 0
        for pin in source_pins(registry, source):
            path = directory / pin.path
            if not path.exists():
                absent += 1
                continue
            try:
                check_file(path, pin, receipt.recorded(pin))
                verified += 1
            except CorporaError as error:
                problems.append(str(error))
        if absent:
            problems.append(f"{absent} pinned files are not fetched")
        if entry["extract"]["format"] == "fleurs-reserve":
            extraction = reserve_problems(registry, source, root=root, n1_sources=n1_sources)
        else:
            extraction = extraction_problems(directory / EXTRACTED_DIRECTORY, extraction_identity(registry, source))
        problems += [f"extraction: {problem}" for problem in extraction]
        results.append({"source": source, "status": "FAIL" if problems else "PASS", "verifiedFiles": verified,
                        "problems": problems})
    if runtime is not None and any(registry["sources"][source]["extract"]["format"] == "parquet"
                                   for source in selected):
        problems = runtime()
        results.append({"source": f"runtime:{RUNTIME_FAMILY}", "status": "FAIL" if problems else "PASS",
                        "verifiedFiles": 0, "problems": problems})
    return results


# --------------------------------------------------------------------------- #
# The AISHELL-3 subset
# --------------------------------------------------------------------------- #

def resolve_subset(listing: Sequence[Mapping[str, Any]], subset: Mapping[str, Any]) -> list[Pin]:
    """The subset's pins from a Hub tree listing of its directory, by the registry's seeded rule: speakers with at
    least `minimumFiles` WAVs, each contributing the `perSpeaker` WAVs of lowest SHA-256(seed NUL path)."""
    directory = subset["directory"].rstrip("/") + "/"
    speakers: dict[str, list[Mapping[str, Any]]] = {}
    for item in listing:
        path = item.get("path")
        if item.get("type") != "file" or not isinstance(path, str) or not path.startswith(directory) \
                or not path.endswith(".wav") or path.count("/") != directory.count("/") + 1:
            continue
        speakers.setdefault(path[len(directory):].split("/")[0], []).append(item)
    pins = []
    for speaker in sorted(name for name, files in speakers.items() if len(files) >= subset["minimumFiles"]):
        ranked = sorted(speakers[speaker],
                        key=lambda item: hashlib.sha256(f"{subset['seed']}\0{item['path']}".encode()).hexdigest())
        for item in sorted(ranked[:subset["perSpeaker"]], key=lambda item: item["path"]):
            lfs = item.get("lfs") or {}
            if not PIN_PATTERNS["sha256"].fullmatch(str(lfs.get("oid", ""))) or lfs.get("size") != item.get("size"):
                raise CorporaError(f"{item['path']} carries no LFS SHA-256 in the listing")
            pins.append(Pin(item["path"], int(item["size"]), "sha256", lfs["oid"]))
    return sorted(pins, key=lambda pin: pin.path)


def pin_file_bytes(pins: Iterable[Pin]) -> bytes:
    return ("path\tsize\tsha256\n" + "".join(f"{pin.path}\t{pin.size}\t{pin.digest}\n" for pin in pins)).encode()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _selection(registry: Mapping[str, Any], args: argparse.Namespace, *, default_lean: bool) -> list[str]:
    explicit = bool(args.set or args.group or args.source)
    if not explicit and not default_lean:
        raise CorporaError(f"{args.command} needs --set, --group or --source")
    return select(registry, sets=args.set or (["lean"] if not explicit else []), groups=args.group or [],
                  sources=args.source or [])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (("plan", "bytes to download and extract, and the free space (no network)"),
                       ("runtime", "build the pinned Parquet runtime (maintainer-run)"),
                       ("fetch", "download and verify the selection (maintainer-run)"),
                       ("extract", "decode the selection to its untracked manifests"),
                       ("verify", "re-verify the selection offline"),
                       ("validate", "check the committed registry (no network)"),
                       ("resolve-subset", "the AISHELL-3 subset pins from a Hub tree listing")):
        command = commands.add_parser(name, help=text)
        if name in ("plan", "fetch", "extract", "verify"):
            command.add_argument("--set", action="extend", nargs="+", choices=SETS)
            command.add_argument("--group", action="extend", nargs="+", choices=tuple(GROUPS), metavar="GROUP")
            command.add_argument("--source", action="extend", nargs="+", metavar="SOURCE")
        if name in ("plan", "verify"):
            command.add_argument("--json", action="store_true")
        if name == "fetch":
            command.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                                 help="parallel downloads for sources of many small files (default 4)")
        if name == "resolve-subset":
            command.add_argument("--source", default="aishell3-subset")
            command.add_argument("--listing", type=Path, required=True,
                                 help="the Hub tree API listing (JSON list) of the subset directory")
            command.add_argument("--output", type=Path, help="where to write the pin TSV (default: stdout)")
    args = parser.parse_args(argv)
    try:
        if args.command == "resolve-subset":
            registry = load_registry()
            subset = registry["sources"][args.source]["subset"]
            pins = resolve_subset(json.loads(args.listing.read_text(encoding="utf-8")), subset)
            data = pin_file_bytes(pins)
            if args.output:
                args.output.write_bytes(data)
            else:
                sys.stdout.write(data.decode())
            print(json.dumps({"files": len(pins), "bytes": sum(pin.size for pin in pins),
                              "sha256": hashlib.sha256(data).hexdigest()}, sort_keys=True), file=sys.stderr)
            return 0
        registry = load_valid_registry()
        if args.command == "validate":
            print(json.dumps({"status": "PASS", "sources": len(registry["sources"]),
                              "files": registry["totals"]["files"], "bytes": registry["totals"]["bytes"]},
                             sort_keys=True))
            return 0
        if args.command == "runtime":
            python = ensure_runtime(registry)
            problems, _python = runtime_problems(registry)
            print(json.dumps({"status": "FAIL" if problems else "PASS", "python": str(python),
                              "problems": problems}, sort_keys=True))
            return 1 if problems else 0
        selected = _selection(registry, args, default_lean=args.command in ("plan", "verify"))
        if args.command == "plan":
            value = plan(registry, selected)
            if args.json:
                print(json.dumps(value, indent=2, sort_keys=True))
            else:
                _print_plan(value)
            return 0
        if args.command == "fetch":
            report = fetch(registry, selected, jobs=max(1, args.jobs))
            print(json.dumps({"status": "PASS", "sources": report}, sort_keys=True))
            return 0
        if args.command == "extract":
            report = extract(registry, selected)
            print(json.dumps({"status": "PASS", "sources": report}, sort_keys=True))
            return 0
        results = verify(registry, selected, runtime=lambda: runtime_problems(registry)[0])
        if args.json:
            print(json.dumps(results, indent=2, sort_keys=True))
        else:
            for item in results:
                detail = f": {'; '.join(item['problems'][:3])}" if item["problems"] else ""
                print(f"{item['status']:5s} {item['source']} ({item['verifiedFiles']} files verified){detail}")
        return 0 if all(item["status"] == "PASS" for item in results) else 1
    except (CorporaError, n1.N1Error, acquire.AcquisitionError, JudgeRegistryError, OSError, KeyError,
            clips.CorpusAudioError) as error:
        print(f"audio-qc-corpora: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
