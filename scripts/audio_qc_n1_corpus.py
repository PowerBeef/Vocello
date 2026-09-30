#!/usr/bin/env python3
"""FLEURS human recordings as the AQ-07 N1 population: pinned acquisition, safe extraction, cohort manifests.

Population N1 of the audio QC audit (sections 5.1 and 5.3) is human originals
with verified text; N2 is their codec resyntheses. FLEURS (Conneau et al.
2022, CC BY 4.0) is the N1 source for all ten product languages. The
committed sources file (`config/audio-qc-n1-sources.json`) holds only pins,
license and attribution: the dataset revision and, per language and split,
each file's path, size and pin (the LFS SHA-256 of an audio archive, the git
blob SHA-1 of a TSV). No FLEURS audio or transcript is ever committed.

- **Splits.** FLEURS `dev` is the calibration cohort and `test` the
  confirmation cohort. They read disjoint FLoRes sentence sets, so the split is
  disjoint by script (and by family: each recording is its own family and lies
  in one split). FLEURS publishes no speaker ids, so speaker disjointness
  cannot be verified: a declared limitation (A5 asks for all three).
- **Transport.** Every file downloads from
  `https://huggingface.co/datasets/google/fleurs/resolve/<revision>/<path>`;
  a redirect is followed only to https on the Hub or its CDNs
  (`acquire_audio_qc_judges.allowed_download_url`, narrowed to the Hub hosts).
  Each file streams into `.partial/<path>.part`, resumes where it stopped (an
  HTTP range request), and moves into place only once its size and pin match;
  a mismatch deletes the partial file. A file already in place is re-verified
  and skipped, or refused if it differs from its pin.
- **Extraction.** An archive is read as a stream and only regular-file members
  named `<digits>.wav` that its TSV lists are written, by file name only. All
  of them must sit in one directory whose last part is the split (`dev/`, or a
  prefixed `<...>/dev/`), and a directory entry must lie on that directory's
  path. Links, absolute paths, `..`, device files, unexpected names or
  directories, duplicates and a member count other than the TSV's row count
  are refused, and so is any WAV that is not mono PCM16 at 16 kHz with the
  TSV's sample count. Each language's extraction is staged and moved into
  place whole, with a receipt of every WAV's SHA-256.
- **Manifest.** One untracked `audio-qc-n1-cohort` manifest per split, in the
  take shape the calibration tools read: per recording its takeID
  (`n1-<code>-<stem>`), its own family, `scriptID` `flores-<sentence id>`,
  language, raw transcription as `text`, WAV path (hard-linked, or copied,
  next to the manifest), digest, duration and gender, with eligibility flags:
  `language_metrics.script_lint_issues` (FLEURS spells digits and symbols) and
  the script pool's per-text proper-name rule. Ineligible recordings stay
  listed with their reasons; the consumers skip them.

Commands:
  plan      the files, sizes, destination and state (no network)
  fetch     download and verify the pinned files [--languages ...]; maintainer-run
  extract   extract and verify the fetched archives [--languages ...]
  manifest  --split calibration|confirmation --output <path> [--languages ...]
  validate  check the committed sources file (no network); in the contract gate
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tarfile
import time
from typing import Any, Callable, Collection, Mapping, Sequence
import urllib.parse
import urllib.request
import wave
import zlib

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import acquire_audio_qc_judges as acquire  # noqa: E402
from audio_qc_calibration_takes import self_digest  # noqa: E402
from audio_qc_judges import snapshot_file_digest  # noqa: E402
from audio_qc_script_pool import names_proper_noun  # noqa: E402
from lib import jsonio  # noqa: E402
from lib import language_metrics as lm  # noqa: E402

REPO = SCRIPT_DIR.parent
SOURCES_PATH = REPO / "config" / "audio-qc-n1-sources.json"
CACHE_ENV = "QVOICE_AUDIO_QC_CORPORA_CACHE"
CACHE_SUBDIRECTORY = "fleurs"

SCHEMA_VERSION = 1
SOURCES_KIND = "audio-qc-n1-sources"
MANIFEST_KIND = "audio-qc-n1-cohort"
RECEIPT_KIND = "audio-qc-n1-extraction"
EXTRACTOR = "audio-qc-n1-extract-v2"  # v2: FLEURS float WAVs are written as PCM16 (`decode_wav`)
ELIGIBILITY_VERSION = "audio-qc-n1-eligibility-v1"
POPULATION = "N1"
DATASET = "google/fleurs"
HUB_HOST = "huggingface.co"
LICENSE = "CC-BY-4.0"
SAMPLE_RATE = 16_000
DESCRIPTION = (
    "AQ-07 population N1 (human originals with verified text): FLEURS read speech in the product's ten "
    "languages, pinned at one dataset revision. Only pins, license and attribution are committed; "
    "scripts/audio_qc_n1_corpus.py fetches, extracts and writes the untracked cohort manifests."
)
ATTRIBUTION = (
    "FLEURS (Few-shot Learning Evaluation of Universal Representations of Speech; Conneau et al., 2022, "
    "arXiv:2205.12446), released by Google as the Hugging Face dataset google/fleurs under the Creative "
    "Commons Attribution 4.0 International license (CC BY 4.0). Vocello's audio QC tooling downloads the "
    "pinned files into an untracked local cache for detector qualification; no FLEURS audio or transcript "
    "is redistributed or committed."
)
TSV_COLUMNS = ("floresSentenceID", "file", "rawTranscription", "normalizedTranscription", "characters",
               "samples", "gender")
SPLIT_ROLES = {"dev": "calibration", "test": "confirmation"}
ROLE_SPLITS = {role: split for split, role in SPLIT_ROLES.items()}
DISJOINTNESS = {
    "requirement": "A5 and thresholdDerivation.split: calibration and confirmation cohorts disjoint by family, "
                   "speaker and script",
    "family": "holds: each recording is its own family and lies in one split",
    "script": "holds by the FLoRes split: dev and test read disjoint FLoRes sentence sets, and manifest marks "
              "any sentence id found in both splits ineligible (sharedScript)",
    "speaker": "unverifiable: FLEURS publishes no speaker ids (see limitations)",
}
LIMITATIONS = [{
    "id": "fleurs-no-speaker-ids",
    "statement": (
        "FLEURS publishes no speaker ids; its TSVs give only a gender per recording. Speaker disjointness "
        "between the dev (calibration) and test (confirmation) splits therefore cannot be verified, and "
        "neither can a speaker count. It is a declared limitation of N1: family and script disjointness "
        "hold, speaker disjointness is assumed, not shown."
    ),
}]
# The FLEURS config of each product language (`lm.PRODUCT_LANGUAGES`).
FLEURS_CONFIGS: dict[str, str] = {
    "english": "en_us",
    "french": "fr_fr",
    "german": "de_de",
    "spanish": "es_419",
    "italian": "it_it",
    "portuguese": "pt_br",
    "russian": "ru_ru",
    "chinese": "cmn_hans_cn",
    "japanese": "ja_jp",
    "korean": "ko_kr",
}
GENDERS = {"MALE": "male", "FEMALE": "female", "OTHER": "other"}
SHA256 = re.compile(r"[0-9a-f]{64}")
SHA1 = re.compile(r"[0-9a-f]{40}")
DIGITS = re.compile(r"[0-9]+", re.ASCII)
WAV_NAME = re.compile(r"[0-9]+\.wav", re.ASCII)
# The Hub keeps files above 10 MB in LFS, so a git blob pin above it is never genuine.
GIT_BLOB_MAX_BYTES = 10_000_000
MAX_ARCHIVE_BYTES = 8 * 1024 ** 3
MAX_MEMBER_BYTES = 64 * 1024 * 1024
WAV_HEADER_BYTES = 44
PROGRESS_STEP_BYTES = 64 * 1024 * 1024
FREE_SPACE_MARGIN_BYTES = acquire.FREE_SPACE_MARGIN_BYTES
PARTIAL_DIRECTORY = ".partial"
EXTRACTED_DIRECTORY = "extracted"
RECEIPT_NAME = "receipt.json"
ELIGIBILITY_RULES = [
    "text: the raw transcription is not empty (emptyText)",
    "script lint: language_metrics.script_lint_issues(text, language) is empty (scriptLint:<code>)",
    "no proper names where letter case marks them: audio_qc_script_pool.names_proper_noun(text, language), "
    "the per-text part of the script pool's rule (properName)",
    "script disjointness: the recording's FLoRes sentence id is not also read in the other split (sharedScript)",
]

Opener = Callable[[urllib.request.Request, float], Any]


class N1Error(RuntimeError):
    """A pin, a download, an archive or a manifest failed; nothing unverified is kept."""


def _log(message: str) -> None:
    print(f"audio-qc-n1: {message}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #

def load_sources(path: Path = SOURCES_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise N1Error(f"{path.name} cannot be read: {type(error).__name__}") from None
    if not isinstance(value, dict):
        raise N1Error(f"{path.name} is not a JSON object")
    return value


def sources_digest(sources: Mapping[str, Any]) -> str:
    return jsonio.sha256_json(sources, ascii=False)


def encode_sources(sources: Mapping[str, Any]) -> bytes:
    return jsonio.pretty_bytes(sources, ascii=False, allow_nan=False)


def _pin_issue(pin: Any, *, path: str, kind: str) -> str | None:
    """Why one file pin is unusable: a TSV pins its git blob SHA-1, an archive its LFS SHA-256."""
    key, pattern = ("gitBlobSHA1", SHA1) if kind == "tsv" else ("sha256", SHA256)
    if not isinstance(pin, dict) or set(pin) != {"path", "size", key}:
        return f"{path}: a {kind} pin holds exactly path, size and {key}"
    size = pin["size"]
    limit = GIT_BLOB_MAX_BYTES if kind == "tsv" else MAX_ARCHIVE_BYTES
    if pin["path"] != path:
        return f"{path}: the {kind} pin names {pin['path']!r}"
    if type(size) is not int or not 0 < size <= limit:
        return f"{path}: size must be a positive integer of at most {limit} bytes"
    if not isinstance(pin[key], str) or pattern.fullmatch(pin[key]) is None:
        return f"{path}: {key} is malformed"
    return None


def sources_issues(sources: Any, languages: Sequence[str] = lm.PRODUCT_LANGUAGES) -> list[str]:
    """Why the sources file may not pin N1 (empty when it may). Reads no network and no file."""
    if not isinstance(sources, dict):
        return ["sources: not an object"]
    issues = []
    expected = {
        "schemaVersion": SCHEMA_VERSION, "kind": SOURCES_KIND, "description": DESCRIPTION,
        "population": POPULATION, "dataset": DATASET, "host": HUB_HOST, "license": LICENSE,
        "attribution": ATTRIBUTION, "sampleRate": SAMPLE_RATE, "tsvColumns": list(TSV_COLUMNS),
        "disjointness": DISJOINTNESS, "limitations": LIMITATIONS,
    }
    for key, value in expected.items():
        if sources.get(key) != value:
            issues.append(f"sources: {key} differs from the script's")
    keys = {*expected, "revision", "languages", "totals"}
    if set(sources) != keys:
        issues.append(f"sources: fields must be {', '.join(sorted(keys))}")
    if not (isinstance(sources.get("revision"), str) and SHA1.fullmatch(sources["revision"])):
        issues.append("sources: revision must be a full 40-character commit")
    entries = sources.get("languages")
    if not isinstance(entries, list):
        return issues + ["sources: languages must be a list"]
    if [entry.get("language") if isinstance(entry, dict) else None for entry in entries] != list(languages):
        issues.append(f"sources: languages must be {', '.join(languages)} in that order")
    files = 0
    total = 0
    paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"language", "config", "splits"}:
            issues.append("sources: a language entry holds exactly language, config and splits")
            continue
        language, config = entry["language"], entry["config"]
        if FLEURS_CONFIGS.get(language) != config:
            issues.append(f"sources: {language} must read the FLEURS config {FLEURS_CONFIGS.get(language)}")
            continue
        splits = entry["splits"]
        if not isinstance(splits, list) or [split.get("split") if isinstance(split, dict) else None
                                            for split in splits] != list(SPLIT_ROLES):
            issues.append(f"sources: {language} must list the splits {', '.join(SPLIT_ROLES)} in that order")
            continue
        for split in splits:
            name = split["split"]
            if set(split) != {"split", "role", "tsv", "archive"} or split.get("role") != SPLIT_ROLES[name]:
                issues.append(f"sources: {language} {name} holds split, role {SPLIT_ROLES[name]}, tsv and archive")
                continue
            for kind, path in (("tsv", f"data/{config}/{name}.tsv"),
                               ("archive", f"data/{config}/audio/{name}.tar.gz")):
                if (problem := _pin_issue(split[kind], path=path, kind=kind)) is not None:
                    issues.append(f"sources: {problem}")
                    continue
                if path in paths:
                    issues.append(f"sources: {path} is pinned twice")
                paths.add(path)
                files += 1
                total += split[kind]["size"]
    if sources.get("totals") != {"files": files, "bytes": total}:
        issues.append(f"sources: totals must be {{files: {files}, bytes: {total}}}")
    if files != 4 * len(languages):
        issues.append(f"sources: {files} files pinned, expected {4 * len(languages)}")
    return issues


def language_entry(sources: Mapping[str, Any], language: str) -> dict[str, Any]:
    for entry in sources["languages"]:
        if entry["language"] == language:
            return entry
    raise N1Error(f"the sources file pins no {language}")


def split_entry(entry: Mapping[str, Any], split: str) -> dict[str, Any]:
    return next(item for item in entry["splits"] if item["split"] == split)


def _languages(sources: Mapping[str, Any], requested: Sequence[str] | None) -> list[str]:
    pinned = [entry["language"] for entry in sources["languages"]]
    if not requested:
        return pinned
    unknown = [language for language in requested if language not in pinned]
    if unknown:
        raise N1Error(f"not pinned languages: {', '.join(unknown)} (choose from {', '.join(pinned)})")
    return [language for language in pinned if language in requested]


def pinned_files(sources: Mapping[str, Any], languages: Sequence[str] | None = None,
                 kinds: Sequence[str] = ("tsv", "archive")) -> list[dict[str, Any]]:
    """Every pinned file of the selected languages: per language its TSVs, then its archives."""
    files = []
    for language in _languages(sources, languages):
        entry = language_entry(sources, language)
        for kind in kinds:
            for split in entry["splits"]:
                files.append({"language": language, "config": entry["config"], "split": split["split"],
                              "role": split["role"], "kind": kind, **split[kind]})
    return files


def cache_root() -> Path:
    override = os.environ.get(CACHE_ENV)
    return (Path(override) if override else REPO / "build" / "cache" / "audio-qc-corpora") / CACHE_SUBDIRECTORY


def corpus_root(sources: Mapping[str, Any], root: Path | None = None) -> Path:
    return (root or cache_root()) / sources["revision"]


def _judge_pin(pin: Mapping[str, Any]) -> dict[str, Any]:
    """The pin as the judge snapshot verifier reads it: an LFS SHA-256 or a git blob ID, and the size."""
    if "sha256" in pin:
        return {"size": pin["size"], "lfsSHA256": pin["sha256"]}
    return {"size": pin["size"], "gitBlobID": pin["gitBlobSHA1"]}


def verified_file(path: Path, pin: Mapping[str, Any]) -> bool:
    """The file's size and pin (LFS SHA-256 or git blob SHA-1) match; a link never does."""
    return not path.is_symlink() and snapshot_file_digest(path, _judge_pin(pin)) is not None


def git_blob_sha1(data: bytes) -> str:
    """The git blob id of `data`: SHA-1 over `blob <size>` NUL and the bytes."""
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def _inside(root: Path, path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return False


def _require_free(root: Path, needed: int, what: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(root).free
    if needed + FREE_SPACE_MARGIN_BYTES > free:
        raise N1Error(f"{what} needs {needed / 1e9:.2f} GB plus a 2 GiB margin; {free / 1e9:.2f} GB is free, "
                      "so nothing was written")


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #

def allowed_hub_url(url: str) -> bool:
    """https on huggingface.co or a Hub CDN host (`*.hf.co`, `*.huggingface.co`), as the judge fetch allows."""
    if not acquire.allowed_download_url(url):
        return False
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host == HUB_HOST or host.endswith(acquire.DOWNLOAD_HOST_SUFFIXES)


class HubRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to https on the Hub or its CDNs; anything else refuses the download."""

    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any,
                         newurl: str) -> urllib.request.Request | None:
        if not allowed_hub_url(newurl):
            raise N1Error(f"a download was redirected to {acquire._described(newurl)}, which is not a Hugging "
                          "Face Hub https host; nothing is fetched from it")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(HubRedirectHandler)


def _open(request: urllib.request.Request, timeout: float) -> Any:
    if not allowed_hub_url(request.full_url):
        raise N1Error(f"{acquire._described(request.full_url)} is not a Hugging Face Hub https host")
    return _OPENER.open(request, timeout=timeout)


def file_url(sources: Mapping[str, Any], path: str) -> str:
    """The pinned revision's resolve URL of one dataset file; refused unless it stays on that prefix."""
    url = acquire.hub_url(f"datasets/{sources['dataset']}", sources["revision"], path)
    prefix = f"https://{HUB_HOST}/datasets/{sources['dataset']}/resolve/{sources['revision']}/"
    if not url.startswith(prefix) or not allowed_hub_url(url):
        raise N1Error(f"{path} does not resolve under {prefix}")
    return url


class _ProgressResponse:
    """A response whose reads report the file's progress in MB."""

    def __init__(self, response: Any, label: str, offset: int, total: int) -> None:
        self._response = response
        self._label = label
        self._total = total
        self._done = offset if acquire._status(response) == 206 else 0
        self._next = (self._done // PROGRESS_STEP_BYTES + 1) * PROGRESS_STEP_BYTES

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)

    def __enter__(self) -> "_ProgressResponse":
        self._response.__enter__()
        return self

    def __exit__(self, *details: Any) -> Any:
        return self._response.__exit__(*details)

    def read(self, size: int = -1) -> bytes:
        block = self._response.read(size)
        self._done += len(block)
        if self._done >= self._next:
            _log(f"  {self._label}: {self._done / 1e6:.1f} / {self._total / 1e6:.1f} MB")
            self._next = (self._done // PROGRESS_STEP_BYTES + 1) * PROGRESS_STEP_BYTES
        return block


def _with_progress(opener: Opener, label: str, total: int) -> Opener:
    def open_with_progress(request: urllib.request.Request, timeout: float) -> Any:
        header = request.get_header("Range") or ""
        offset = int(header[len("bytes="):-1]) if header.startswith("bytes=") and header.endswith("-") else 0
        return _ProgressResponse(opener(request, timeout), label, offset, total)
    return open_with_progress


def fetch(sources: Mapping[str, Any], *, root: Path | None = None, languages: Sequence[str] | None = None,
          opener: Opener = _open, sleep: Callable[[float], None] = time.sleep,
          tsv_only: bool = False) -> list[dict[str, Any]]:
    """Download every selected pinned file not already present and verified; refuse any mismatch.

    `tsv_only` fetches the transcript TSVs alone (about 6 MB), enough for the
    `yield` report before the audio is downloaded.
    """
    directory = corpus_root(sources, root)
    files = pinned_files(sources, languages, ("tsv",) if tsv_only else ("tsv", "archive"))
    for pin in files:
        final = directory / pin["path"]
        if not _inside(directory, final) or not _inside(directory, directory / PARTIAL_DIRECTORY / pin["path"]):
            raise N1Error(f"{pin['path']} resolves outside the corpus directory; nothing is written")
    remaining = sum(pin["size"] for pin in files if not (directory / pin["path"]).exists())
    _require_free(directory, remaining, f"fetching {len(files)} files")
    total = sum(pin["size"] for pin in files)
    _log(f"{DATASET} @ {sources['revision'][:12]}: {len(files)} files, {total / 1e6:.1f} MB, "
         f"{remaining / 1e6:.1f} MB still to fetch")
    report = []
    done = 0
    for index, pin in enumerate(files, 1):
        final = directory / pin["path"]
        label = f"[{index}/{len(files)}] {pin['path']}"
        if final.exists():
            if not verified_file(final, pin):
                raise N1Error(f"{pin['path']} is present but differs from its pin; remove it and fetch again")
            done += pin["size"]
            _log(f"{label}: present and verified ({pin['size'] / 1e6:.1f} MB)")
            report.append({"path": pin["path"], "status": "present", "bytes": pin["size"]})
            continue
        part = directory / PARTIAL_DIRECTORY / f"{pin['path']}.part"
        resumed = part.stat().st_size if part.exists() else 0
        _log(f"{label}: {pin['size'] / 1e6:.1f} MB" + (f", resuming at {resumed / 1e6:.1f} MB" if resumed else ""))
        acquire.download(file_url(sources, pin["path"]), part, size=pin["size"],
                         opener=_with_progress(opener, pin["path"], pin["size"]), sleep=sleep)
        if not verified_file(part, pin):
            part.unlink(missing_ok=True)
            raise N1Error(f"{pin['path']} does not match its pinned size and digest; the download was discarded")
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(part, final)
        done += pin["size"]
        _log(f"{label}: verified; {done / 1e6:.1f} / {total / 1e6:.1f} MB in place")
        report.append({"path": pin["path"], "status": "fetched", "bytes": pin["size"]})
    acquire._prune_partial(directory)
    return report


def plan(sources: Mapping[str, Any], *, root: Path | None = None,
         languages: Sequence[str] | None = None) -> dict[str, Any]:
    """The selected files, their sizes and local state (present, partial or absent), without the network."""
    directory = corpus_root(sources, root)
    rows = []
    for pin in pinned_files(sources, languages):
        final = directory / pin["path"]
        part = directory / PARTIAL_DIRECTORY / f"{pin['path']}.part"
        if final.is_file() and final.stat().st_size == pin["size"]:
            state = "present"
        elif final.exists():
            state = "differs"
        elif part.is_file():
            state = f"partial {part.stat().st_size / 1e6:.1f} MB"
        else:
            state = "absent"
        rows.append({"language": pin["language"], "config": pin["config"], "split": pin["split"],
                     "role": pin["role"], "path": pin["path"], "bytes": pin["size"], "state": state})
    total = sum(row["bytes"] for row in rows)
    return {"dataset": DATASET, "revision": sources["revision"], "license": LICENSE, "destination": str(directory),
            "files": rows, "totalBytes": total,
            "missingBytes": sum(row["bytes"] for row in rows if row["state"] != "present")}


# --------------------------------------------------------------------------- #
# TSVs and extraction
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Row:
    sentence_id: int
    file: str
    text: str
    samples: int
    gender: str


def parse_tsv(data: bytes, name: str) -> list[Row]:
    """The TSV's rows (tab-separated, no header, `TSV_COLUMNS`); any malformed row refuses the file."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise N1Error(f"{name} is not UTF-8") from None
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    rows: list[Row] = []
    seen: set[str] = set()
    for number, line in enumerate(lines, start=1):
        fields = line.removesuffix("\r").split("\t")
        if len(fields) != len(TSV_COLUMNS):
            raise N1Error(f"{name} line {number} has {len(fields)} columns, expected {len(TSV_COLUMNS)}")
        sentence, file, raw, _normalized, _characters, samples, gender = fields
        if not DIGITS.fullmatch(sentence) or not WAV_NAME.fullmatch(file) or not DIGITS.fullmatch(samples) \
                or int(samples) <= 0 or gender not in GENDERS:
            raise N1Error(f"{name} line {number} is malformed (sentence id, file name, sample count or gender)")
        if file in seen:
            raise N1Error(f"{name} lists {file} twice")
        seen.add(file)
        rows.append(Row(int(sentence), file, raw, int(samples), GENDERS[gender]))
    if not rows:
        raise N1Error(f"{name} lists no recording")
    return rows


def read_tsv(path: Path, pin: Mapping[str, Any]) -> list[Row]:
    if not verified_file(path, pin):
        raise N1Error(f"{pin['path']} is missing or differs from its pin; run `fetch` first")
    return parse_tsv(path.read_bytes(), pin["path"])


# WAV format tags: PCM, IEEE float and WAVE_FORMAT_EXTENSIBLE (whose subformat GUID starts with the tag).
WAV_PCM, WAV_FLOAT, WAV_EXTENSIBLE = 1, 3, 0xFFFE
PCM16_FULL_SCALE = 32767


def _wav_chunks(data: bytes, name: str) -> tuple[bytes, bytes]:
    """The `fmt ` and `data` chunk bodies of a RIFF/WAVE file; anything malformed refuses it."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise N1Error(f"{name} is not a RIFF/WAVE file")
    chunks: dict[bytes, bytes] = {}
    position = 12
    while position + 8 <= len(data):
        identifier, size = data[position:position + 4], struct.unpack("<I", data[position + 4:position + 8])[0]
        body = data[position + 8:position + 8 + size]
        if len(body) != size:
            raise N1Error(f"{name}: its {identifier!r} chunk is truncated")
        if identifier in chunks and identifier in (b"fmt ", b"data"):
            raise N1Error(f"{name}: its {identifier!r} chunk appears twice")
        chunks[identifier] = body
        position += 8 + size + (size & 1)
    if b"fmt " not in chunks or b"data" not in chunks:
        raise N1Error(f"{name} has no fmt or data chunk")
    return chunks[b"fmt "], chunks[b"data"]


def decode_wav(data: bytes, name: str, samples: int) -> tuple[bytes, dict[str, Any]]:
    """A recording as mono PCM16 at 16 kHz holding exactly the TSV's sample count.

    FLEURS ships its recordings as 32-bit IEEE float (format 3, with a `fact`
    chunk). Every consumer (the L0 canonicalizer, the recording adapter, the N2
    plan) reads PCM16, so a float recording is converted here, deterministically:
    each sample times 32767, rounded half to even and clipped to +-32767, with
    the clipped samples counted. A non-finite sample refuses the recording. A
    PCM16 recording is kept byte for byte. Returns the WAV to write and what the
    conversion did (`sourceFormat`, `sourceSHA256`, `clippedSamples`).
    """
    fmt, payload = _wav_chunks(data, name)
    if len(fmt) < 16:
        raise N1Error(f"{name}: its fmt chunk is too short")
    tag, channels, rate, _byte_rate, align, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag == WAV_EXTENSIBLE:
        if len(fmt) < 40:
            raise N1Error(f"{name}: its extensible fmt chunk is too short")
        tag = struct.unpack("<H", fmt[24:26])[0]
    if channels != 1:
        raise N1Error(f"{name} has {channels} channels, not mono")
    if rate != SAMPLE_RATE:
        raise N1Error(f"{name} is {rate} Hz, not {SAMPLE_RATE} Hz")
    info = {"sourceSHA256": hashlib.sha256(data).hexdigest(), "clippedSamples": 0}
    if tag == WAV_PCM and bits == 16 and align == 2:
        if len(payload) != 2 * samples:
            raise N1Error(f"{name} holds {len(payload) // 2} samples; its TSV row says {samples}")
        return data, {**info, "sourceFormat": "pcm16"}
    if tag == WAV_FLOAT and bits == 32 and align == 4:
        if len(payload) != 4 * samples:
            raise N1Error(f"{name} holds {len(payload) // 4} samples; its TSV row says {samples}")
        values = np.frombuffer(payload, dtype="<f4").astype(np.float64)
        if not np.all(np.isfinite(values)):
            raise N1Error(f"{name} holds a non-finite sample")
        scaled = np.rint(values * PCM16_FULL_SCALE)
        clipped = int(np.count_nonzero(np.abs(scaled) > PCM16_FULL_SCALE))
        pcm = np.clip(scaled, -PCM16_FULL_SCALE, PCM16_FULL_SCALE).astype("<i2")
        output = io.BytesIO()
        with wave.open(output, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(SAMPLE_RATE)
            writer.writeframes(pcm.tobytes())
        return output.getvalue(), {**info, "sourceFormat": "ieee-float32", "clippedSamples": clipped}
    raise N1Error(f"{name} is neither mono PCM16 nor 32-bit float (format {tag}, {bits} bits)")


def _refuse(archive: str, member: tarfile.TarInfo, reason: str) -> N1Error:
    return N1Error(f"{archive}: member {member.name[:120]!r} {reason}; nothing from this archive is kept")


def member_parts(member: tarfile.TarInfo, archive: str) -> list[str]:
    """A member's path parts once it is known to be a plain file or directory with a safe relative path.

    Links, device files, FIFOs, absolute paths and `.`, `..` or empty parts
    refuse the archive. The archive's own root entry (`.`) has no parts.
    """
    name = member.name
    if name.startswith("/") or "\\" in name or "\0" in name:
        raise _refuse(archive, member, "is an absolute or unsafe path")
    if member.issym() or member.islnk():
        raise _refuse(archive, member, "is a link")
    if member.ischr() or member.isblk() or member.isfifo():
        raise _refuse(archive, member, "is a device file or FIFO")
    if member.isdir() and name.rstrip("/") in (".", "./"):
        return []
    if not member.isdir() and (not member.isreg() or member.issparse()):
        raise _refuse(archive, member, "is not a regular file")
    parts = name.removeprefix("./").rstrip("/").split("/") if member.isdir() else name.removeprefix("./").split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise _refuse(archive, member, "has an empty, '.' or '..' path part")
    return parts


def extract_split(archive: Path, pin: Mapping[str, Any], split: str, rows: Sequence[Row],
                  destination: Path) -> tuple[str, dict[str, dict[str, Any]]]:
    """Write every member of a verified archive that its TSV lists, checking each WAV; refuse anything else.

    Every recording must sit in one directory, the archive's first recording's,
    whose last part is the split (`dev/`, or a prefixed `<...>/dev/`), and be
    named `<digits>.wav`; a directory entry must lie on that directory's path.
    Only the file name is written, under `destination`. Returns that member
    directory and each written file's digest, size and sample count.
    """
    member_directory, files, _counts = extract_members(archive, pin, split, rows, destination)
    return member_directory, files


def extract_members(archive: Path, pin: Mapping[str, Any], split: str, rows: Sequence[Row], destination: Path,
                    *, keep: Collection[str] | None = None,
                    ) -> tuple[str, dict[str, dict[str, Any]], dict[str, int]]:
    """`extract_split`, or with `keep` only the named recordings of a larger archive (the train reserve).

    With `keep`, every member is still checked as `extract_split` checks it
    (safe path, one split directory, `<digits>.wav`, no duplicate), but only the
    kept recordings are decoded and written; a recording its TSV does not list
    is skipped and counted instead of refused, and every kept recording must be
    in the archive. Returns the member directory, each written file's facts and
    the counts: members seen, members the TSV does not list, TSV rows without a
    member.
    """
    expected = {row.file: row for row in rows}
    strict = keep is None
    wanted = set(expected) if keep is None else set(keep)
    if not wanted <= set(expected):
        raise N1Error(f"{pin['path']}: a kept recording is not listed in its TSV")
    files: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    unlisted = 0
    directories: list[tuple[tarfile.TarInfo, str]] = []
    member_directory: str | None = None
    destination.mkdir(parents=True, exist_ok=False)
    label = pin["path"]
    try:
        with tarfile.open(archive, "r|gz") as bundle:
            for member in bundle:
                parts = member_parts(member, label)
                if member.isdir():
                    if parts:
                        directories.append((copy.copy(member), "/".join(parts)))
                    continue
                if len(parts) < 2 or parts[-2] != split or not WAV_NAME.fullmatch(parts[-1]):
                    raise _refuse(label, member, f"is not named {split}/<digits>.wav")
                directory, name = "/".join(parts[:-1]), parts[-1]
                if member_directory is None:
                    member_directory = directory
                elif directory != member_directory:
                    raise _refuse(label, member, f"is not in {member_directory}/ with the archive's first recording")
                if name not in expected and strict:
                    raise _refuse(label, member, "is not listed in its TSV")
                if name in seen:
                    raise _refuse(label, member, "appears twice")
                seen.add(name)
                if name not in expected:
                    unlisted += 1
                    continue
                if name not in wanted:
                    continue
                if member.size > MAX_MEMBER_BYTES:
                    raise _refuse(label, member, f"is larger than {MAX_MEMBER_BYTES} bytes")
                stream = bundle.extractfile(member)
                data = stream.read() if stream is not None else b""
                if len(data) != member.size:
                    raise _refuse(label, member, "is truncated")
                written, conversion = decode_wav(data, f"{label}: {name}", expected[name].samples)
                with (destination / name).open("xb") as handle:
                    handle.write(written)
                files[name] = {"sha256": hashlib.sha256(written).hexdigest(), "bytes": len(written),
                               "samples": expected[name].samples, **conversion}
    except (tarfile.TarError, EOFError, zlib.error) as error:
        raise N1Error(f"{label} is not a readable tar.gz archive ({type(error).__name__})") from None
    if strict and (len(files) != len(expected) or member_directory is None):
        raise N1Error(f"{label}: the archive holds {len(files)} recordings, its TSV lists {len(expected)}")
    if not strict and (len(files) != len(wanted) or member_directory is None):
        raise N1Error(f"{label}: {len(wanted) - len(files)} of the {len(wanted)} kept recordings are not in the "
                      "archive")
    for member, directory in directories:
        if member_directory != directory and not member_directory.startswith(f"{directory}/"):
            raise _refuse(label, member, f"is a directory off the recordings' path {member_directory}/")
    counts = {"members": len(seen), "unlisted": unlisted, "absent": len(set(expected) - seen)}
    return member_directory, dict(sorted(files.items())), counts


def extraction_directory(sources: Mapping[str, Any], config: str, root: Path | None = None) -> Path:
    return corpus_root(sources, root) / EXTRACTED_DIRECTORY / config


def _receipt_pins(sources: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION, "kind": RECEIPT_KIND, "extractor": EXTRACTOR, "dataset": DATASET,
        "revision": sources["revision"], "language": entry["language"], "config": entry["config"],
        "pins": {split["split"]: {"role": split["role"],
                                  "tsv": {"path": split["tsv"]["path"], "gitBlobSHA1": split["tsv"]["gitBlobSHA1"]},
                                  "archive": {"path": split["archive"]["path"], "sha256": split["archive"]["sha256"]}}
                 for split in entry["splits"]},
    }


def read_receipt(sources: Mapping[str, Any], entry: Mapping[str, Any], directory: Path) -> dict[str, Any] | None:
    """The extraction receipt when it names the current pins and extractor, else None."""
    try:
        receipt = json.loads((directory / RECEIPT_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(receipt, dict) or not isinstance(receipt.get("splits"), dict):
        return None
    if {key: receipt.get(key) for key in _receipt_pins(sources, entry)} != _receipt_pins(sources, entry):
        return None
    if set(receipt["splits"]) != set(SPLIT_ROLES) or not all(
            isinstance(record, dict) and isinstance(record.get("files"), dict)
            and all(isinstance(file, dict) for file in record["files"].values())
            for record in receipt["splits"].values()):
        return None
    return receipt


def _extraction_matches(receipt: Mapping[str, Any], directory: Path) -> bool:
    for split, record in receipt["splits"].items():
        for name, file in record["files"].items():
            path = directory / split / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size != file.get("bytes") \
                    or jsonio.sha256_file(path) != file.get("sha256"):
                return False
    return True


def extract(sources: Mapping[str, Any], *, root: Path | None = None,
            languages: Sequence[str] | None = None) -> list[dict[str, Any]]:
    """Extract each selected language's verified archives; an extraction whose receipt and WAVs match is kept."""
    report = []
    for language in _languages(sources, languages):
        entry = language_entry(sources, language)
        directory = extraction_directory(sources, entry["config"], root)
        receipt = read_receipt(sources, entry, directory)
        if receipt is not None and _extraction_matches(receipt, directory):
            _log(f"{language}: extraction present and verified")
            report.append({"language": language, "status": "present",
                           "recordings": {split: record.get("recordings")
                                          for split, record in receipt["splits"].items()}})
            continue
        report.append(_extract_language(sources, entry, directory, root))
    return report


def _extract_language(sources: Mapping[str, Any], entry: Mapping[str, Any], directory: Path,
                      root: Path | None) -> dict[str, Any]:
    corpus = corpus_root(sources, root)
    rows = {split["split"]: read_tsv(corpus / split["tsv"]["path"], split["tsv"]) for split in entry["splits"]}
    for split in entry["splits"]:
        archive = split["archive"]
        _log(f"{entry['language']}: verifying {archive['path']} ({archive['size'] / 1e6:.1f} MB)")
        if not verified_file(corpus / archive["path"], archive):
            raise N1Error(f"{archive['path']} is missing or differs from its pin; run `fetch` first")
    needed = sum(WAV_HEADER_BYTES + 2 * row.samples for split_rows in rows.values() for row in split_rows)
    _require_free(corpus, needed, f"extracting {entry['language']}")
    staging = directory.parent / f".staging-{entry['config']}"
    acquire._remove_owned(staging)
    staging.mkdir(parents=True)
    (staging / acquire.OWNED_MARKER).write_text(f"audio QC N1 extraction {entry['config']}\n", encoding="utf-8")
    try:
        splits = {}
        for split in entry["splits"]:
            name = split["split"]
            _log(f"{entry['language']}: extracting {split['archive']['path']}")
            member_directory, files = extract_split(corpus / split["archive"]["path"], split["archive"], name,
                                                    rows[name], staging / name)
            splits[name] = {"role": split["role"], "memberDirectory": member_directory, "recordings": len(files),
                            "samples": sum(file["samples"] for file in files.values()),
                            "sourceFormats": sorted({file["sourceFormat"] for file in files.values()}),
                            "clippedSamples": sum(file["clippedSamples"] for file in files.values()),
                            "wavBytes": sum(file["bytes"] for file in files.values()), "files": files}
        shared = ({row.sentence_id for row in rows["dev"]} & {row.sentence_id for row in rows["test"]})
        receipt = {**_receipt_pins(sources, entry), "splits": splits, "sharedSentenceIDs": len(shared)}
        jsonio.atomic_json(staging / RECEIPT_NAME, receipt, ascii=False, allow_nan=False)
        acquire._remove_owned(directory)
        os.replace(staging, directory)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    _log(f"{entry['language']}: extracted " + ", ".join(f"{name} {record['recordings']} recordings"
                                                       for name, record in splits.items()))
    return {"language": entry["language"], "status": "extracted",
            "recordings": {name: record["recordings"] for name, record in splits.items()},
            "sharedSentenceIDs": len(shared)}


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #

def ineligible_reasons(text: str, language: str, *, shared_script: bool) -> tuple[list[str], list[str], bool]:
    """(reasons, script lint codes, proper name) for one recording's raw transcription."""
    lint = lm.script_lint_issues(text, language)
    proper = names_proper_noun(text, language)
    reasons = [] if text.strip() else ["emptyText"]
    reasons += [f"scriptLint:{code}" for code in lint]
    reasons += ["properName"] if proper else []
    reasons += ["sharedScript"] if shared_script else []
    return reasons, lint, proper


def _place(source: Path, destination: Path, digest: str) -> None:
    """The verified WAV beside the manifest: a hard link, or a copy across volumes; never over other content."""
    if destination.exists() or destination.is_symlink():
        if not destination.is_symlink() and destination.is_file() and (
                os.path.samefile(source, destination) or jsonio.sha256_file(destination) == digest):
            return
        raise N1Error(f"{destination.name} already exists with other content; write the manifest to its own "
                      "directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        try:
            os.link(source, temporary)
        except OSError:
            shutil.copyfile(source, temporary)
        if jsonio.sha256_file(temporary) != digest:
            raise N1Error(f"{destination.name} changed while it was placed")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def recording_take(row: Row, *, language: str, config: str, fleurs_split: str, digest: str,
                   shared_script: bool) -> dict[str, Any]:
    """One FLEURS recording as a cohort take, in the shape every N1 manifest lists (its WAV at `wavPath`)."""
    code = lm.LANGUAGE_LOCALE_CODES[language]
    take_id = f"n1-{code}-{row.file.removesuffix('.wav')}"
    reasons, lint, proper = ineligible_reasons(row.text, language, shared_script=shared_script)
    return {
        "takeID": take_id, "family": take_id, "scriptID": f"flores-{row.sentence_id}",
        "language": language, "population": POPULATION, "status": "generated",
        "text": row.text, "textSHA256": lm.text_sha256(row.text),
        "wavPath": f"wav/{take_id}.wav", "wavSHA256": digest,
        "durationSeconds": round(row.samples / SAMPLE_RATE, 6), "gender": row.gender,
        "recording": {"dataset": DATASET, "config": config, "split": fleurs_split,
                      "file": row.file, "sentenceID": row.sentence_id, "samples": row.samples,
                      "sampleRate": SAMPLE_RATE},
        "scriptLintIssues": lint, "properName": proper,
        "eligible": not reasons, "ineligibleReasons": reasons,
    }


def build_manifest(sources: Mapping[str, Any], *, split: str, output: Path, root: Path | None = None,
                   languages: Sequence[str] | None = None) -> dict[str, Any]:
    """The N1 cohort manifest of one split (`calibration` or `confirmation`), with its WAVs beside it."""
    if split not in ROLE_SPLITS:
        raise N1Error(f"the split is one of {', '.join(ROLE_SPLITS)}")
    fleurs_split = ROLE_SPLITS[split]
    other_split = next(name for name in SPLIT_ROLES if name != fleurs_split)
    corpus = corpus_root(sources, root)
    output = output.resolve()
    wav_dir = output.parent / "wav"
    selected = _languages(sources, languages)
    takes: list[dict[str, Any]] = []
    for language in selected:
        entry = language_entry(sources, language)
        directory = extraction_directory(sources, entry["config"], root)
        receipt = read_receipt(sources, entry, directory)
        if receipt is None:
            raise N1Error(f"{language} is not extracted from the current pins; run `fetch` and `extract` first")
        pins = split_entry(entry, fleurs_split)
        rows = read_tsv(corpus / pins["tsv"]["path"], pins["tsv"])
        other = read_tsv(corpus / split_entry(entry, other_split)["tsv"]["path"],
                         split_entry(entry, other_split)["tsv"])
        other_ids = {row.sentence_id for row in other}
        files = receipt["splits"][fleurs_split]["files"]
        if set(files) != {row.file for row in rows}:
            raise N1Error(f"{language} {fleurs_split}: the extraction receipt does not list its TSV's recordings")
        _log(f"{language}: {len(rows)} {fleurs_split} recordings")
        for row in rows:
            source = directory / fleurs_split / row.file
            if source.is_symlink() or not source.is_file():
                raise N1Error(f"{language} {fleurs_split}: {row.file} is missing; run `extract` again")
            digest = jsonio.sha256_file(source)
            if digest != files[row.file]["sha256"]:
                raise N1Error(f"{language} {fleurs_split}: {row.file} differs from its extraction receipt; "
                              "run `extract` again")
            take = recording_take(row, language=language, config=entry["config"], fleurs_split=fleurs_split,
                                  digest=digest, shared_script=row.sentence_id in other_ids)
            _place(source, wav_dir / f"{take['takeID']}.wav", digest)
            takes.append(take)
    manifest: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION, "kind": MANIFEST_KIND, "population": POPULATION,
        "dataset": DATASET, "revision": sources["revision"], "sourcesDigest": sources_digest(sources),
        "license": LICENSE, "attribution": ATTRIBUTION, "split": split, "fleursSplit": fleurs_split,
        "languages": selected, "sampleRate": SAMPLE_RATE,
        "eligibility": {"version": ELIGIBILITY_VERSION, "rules": ELIGIBILITY_RULES},
        "limitations": LIMITATIONS, "counts": cohort_counts(takes), "takes": takes,
    }
    manifest["manifestDigest"] = self_digest(manifest, "manifestDigest")
    jsonio.atomic_json(output, manifest, ascii=False, allow_nan=False)
    return manifest


def eligibility_yield(sources: Mapping[str, Any], *, root: Path | None = None,
                      languages: Sequence[str] | None = None) -> dict[str, Any]:
    """Per language and cohort split, the recordings and FLoRes sentences the manifest would mark
    eligible, from the fetched TSVs alone (no audio): whether FLEURS meets the N1 and N2 minimums
    (`operatingPoints` in config/audio-qc-qualification-policy.json) before its audio is fetched."""
    corpus = corpus_root(sources, root)
    report: dict[str, Any] = {}
    for language in _languages(sources, languages):
        entry = language_entry(sources, language)
        rows = {}
        for fleurs_split in SPLIT_ROLES:
            pin = split_entry(entry, fleurs_split)["tsv"]
            path = corpus / pin["path"]
            if not path.is_file():
                raise N1Error(f"{language} {fleurs_split}: {pin['path']} is not fetched; run `fetch --tsv-only`")
            rows[fleurs_split] = read_tsv(path, pin)
        ids = {split: {row.sentence_id for row in value} for split, value in rows.items()}
        splits = {}
        for fleurs_split, value in rows.items():
            other = ids[next(name for name in SPLIT_ROLES if name != fleurs_split)]
            reasons: dict[str, int] = {}
            eligible = []
            for row in value:
                found, _lint, _proper = ineligible_reasons(row.text, language,
                                                           shared_script=row.sentence_id in other)
                for reason in {reason.split(":", 1)[0] for reason in found}:
                    reasons[reason] = reasons.get(reason, 0) + 1
                if not found:
                    eligible.append(row)
            splits[SPLIT_ROLES[fleurs_split]] = {
                "fleursSplit": fleurs_split,
                "recordings": len(value),
                "sentences": len(ids[fleurs_split]),
                "eligibleRecordings": len(eligible),
                "eligibleSentences": len({row.sentence_id for row in eligible}),
                "eligibleByGender": {gender: sum(1 for row in eligible if row.gender == gender)
                                     for gender in sorted({row.gender for row in value})},
                "ineligibleReasons": dict(sorted(reasons.items())),
            }
        report[language] = splits
    return report


def _print_yield(report: Mapping[str, Any]) -> None:
    print(f"{'language':11} {'split':12} {'recordings':>10} {'eligible':>8} {'sentences':>9} {'eligible':>8}  reasons")
    for language, splits in report.items():
        for split, value in splits.items():
            print(f"{language:11} {split:12} {value['recordings']:>10} {value['eligibleRecordings']:>8} "
                  f"{value['sentences']:>9} {value['eligibleSentences']:>8}  "
                  + ", ".join(f"{name} {count}" for name, count in value["ineligibleReasons"].items()))


def cohort_counts(takes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    reasons: dict[str, int] = {}
    by_language: dict[str, dict[str, int]] = {}
    for take in takes:
        counts = by_language.setdefault(take["language"], {"recordings": 0, "eligible": 0})
        counts["recordings"] += 1
        counts["eligible"] += int(take["eligible"])
        for reason in take["ineligibleReasons"]:
            reasons[reason] = reasons.get(reason, 0) + 1
    eligible = sum(1 for take in takes if take["eligible"])
    return {"recordings": len(takes), "eligible": eligible, "ineligible": len(takes) - eligible,
            "byLanguage": by_language, "ineligibleReasons": dict(sorted(reasons.items()))}


def manifest_digest_issues(manifest: Any) -> list[str]:
    """The cohort manifest's own structure and self digest, without its audio."""
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != SCHEMA_VERSION \
            or manifest.get("kind") != MANIFEST_KIND or manifest.get("population") != POPULATION:
        return [f"the manifest is not an {MANIFEST_KIND} schema {SCHEMA_VERSION} manifest"]
    if manifest.get("manifestDigest") != self_digest(manifest, "manifestDigest"):
        return ["the N1 manifest digest does not match its content"]
    return []


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _print_plan(value: Mapping[str, Any]) -> None:
    print(f"{value['dataset']} @ {value['revision']} ({value['license']}) -> {value['destination']}")
    for row in value["files"]:
        print(f"  {row['language']:10s} {row['config']:12s} {row['split']:4s} {row['role']:12s} "
              f"{row['path']:36s} {row['bytes'] / 1e6:9.1f} MB  {row['state']}")
    print(f"{len(value['files'])} files, {value['totalBytes'] / 1e6:.1f} MB ({value['totalBytes'] / 1e9:.2f} GB); "
          f"{value['missingBytes'] / 1e6:.1f} MB not yet present. Extraction needs about as much again for the "
          "WAVs (computed from the TSV sample counts before anything is written).")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (("plan", "the files, sizes and state (no network)"),
                       ("fetch", "download and verify the pinned files (maintainer-run)"),
                       ("extract", "extract and verify the fetched archives"),
                       ("manifest", "write an N1 cohort manifest"),
                       ("yield", "eligible recordings per language and split, from the fetched TSVs alone"),
                       ("validate", "check the committed sources file (no network)")):
        command = commands.add_parser(name, help=text)
        command.add_argument("--sources", type=Path, default=SOURCES_PATH)
        if name != "validate":
            command.add_argument("--languages", nargs="+", choices=lm.PRODUCT_LANGUAGES, metavar="LANGUAGE",
                                 help="product language ids (default: all ten)")
        if name in ("plan", "yield"):
            command.add_argument("--json", action="store_true")
        if name == "fetch":
            command.add_argument("--tsv-only", action="store_true",
                                 help="fetch only the transcript TSVs (about 6 MB), for the yield report")
        if name == "manifest":
            command.add_argument("--split", choices=tuple(ROLE_SPLITS), required=True)
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        sources = load_sources(args.sources)
        issues = sources_issues(sources)
        if not issues and encode_sources(sources) != args.sources.read_bytes():
            issues.append("sources: the file is not in the canonical encoding (indent 2, sorted keys)")
        if issues:
            raise N1Error("; ".join(issues))
        if args.command == "validate":
            print(json.dumps({"status": "PASS", "revision": sources["revision"], "files": sources["totals"]["files"],
                              "bytes": sources["totals"]["bytes"]}, sort_keys=True))
            return 0
        if args.command == "plan":
            value = plan(sources, languages=args.languages)
            if args.json:
                print(json.dumps(value, indent=2, sort_keys=True))
            else:
                _print_plan(value)
            return 0
        if args.command == "fetch":
            report = fetch(sources, languages=args.languages, tsv_only=args.tsv_only)
            print(json.dumps({"status": "PASS", "files": report}, sort_keys=True))
            return 0
        if args.command == "yield":
            value = eligibility_yield(sources, languages=args.languages)
            if args.json:
                print(json.dumps(value, indent=2, sort_keys=True))
            else:
                _print_yield(value)
            return 0
        if args.command == "extract":
            report = extract(sources, languages=args.languages)
            print(json.dumps({"status": "PASS", "languages": report}, sort_keys=True))
            return 0
        manifest = build_manifest(sources, split=args.split, output=args.output, languages=args.languages)
        print(json.dumps({"status": "PASS", "split": manifest["split"], "counts": manifest["counts"],
                          "manifestDigest": manifest["manifestDigest"]}, sort_keys=True))
        return 0
    except (N1Error, acquire.AcquisitionError, OSError) as error:
        print(f"audio-qc-n1: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
