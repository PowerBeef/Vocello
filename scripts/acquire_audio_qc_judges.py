#!/usr/bin/env python3
"""Acquire the audio QC judge panel (AQ-06): pinned snapshots, hash-locked runtimes, receipts.

The maintainer runs this: a model or package download is a maintainer-run
action, and nothing else in the repository downloads a judge. Everything it
fetches is pinned in `config/audio-qc-judges.json`:

- **Snapshots.** A judge's pinned files at its pinned revision land in
  `<model root>/<judge directory>/<revision>/`: from Hugging Face
  (`huggingface.co/<repo>/resolve/<revision>/<path>`) or, for a GitHub-sourced
  snapshot, from `raw.githubusercontent.com/<repo>/<commit>/<path>`. Each file
  streams into `<judge directory>/.partial/`, resumes where it stopped (an HTTP
  range request) and moves into the snapshot only once its size and every
  digest its pin records (the LFS or content SHA-256, the git blob ID of a small
  file) match. A mismatch deletes the partial file and fails; a checksum is
  never inferred, a file already in the snapshot that does not match its pin is
  refused, not replaced, and a path that resolves outside the model root is
  refused before anything is written.
- **Transport.** Every download is https, and a redirect is followed only to
  https on huggingface.co, `*.hf.co`, `*.huggingface.co`, github.com and its
  release and raw content hosts; anything else refuses the download.
- **Disk.** Before anything is fetched, the whole selection must fit: its
  remaining model bytes, each runtime still to build at the documented install
  estimate (its wheel bytes x 3.5) and the interpreter, plus a 2 GiB margin.
- **Interpreter.** The python-build-standalone archive is verified by SHA-256
  (downloaded only if absent) and extracted into its own directory; an
  extracted interpreter is reused only while every file matches the archive.
- **Runtimes.** Each runtime family's venv is built from its committed hash lock
  with `pip install --isolated --require-hashes --no-deps --only-binary :all:`
  and `PIP_CONFIG_FILE=/dev/null`, so no pip configuration file is read (the
  few sdist-only packages a lock names are built without isolation from their
  hash-pinned sdists, after the lock's own setuptools). Its installed
  distributions must then equal the lock exactly, every installed file must
  match the SHA-256 its distribution's RECORD lists, and an offline import
  probe must pass. A venv is reused only while all of that still holds.
- **Native runtime.** The SenseVoice llama.cpp archive and binary are verified
  by SHA-256; an existing verified copy is reused.
- **Receipts.** Each judge gets `<judge directory>/receipt.json`, written last:
  every verified file's SHA-256, the lock and interpreter digests and the
  registry entry's digest, with names relative to the model root only.

Quarantined and retired judges, and the panel judges listed in
`acquisitionBlocked`, are never fetched; `plan` names each with its reason.
After a fetch everything is offline: `verify` re-checks every receipt without
the network (snapshots, the interpreter archive and its extracted files, and
every venv file against its RECORD), and each worker verifies its snapshot
before it loads.

Commands:
  plan    the selected judges, bytes and destinations (reads the registry and
          the model root; no network)
  fetch   download, build and verify the selected judges (--judge ID ...,
          --stage N or --all)
  verify  re-verify offline (default: every judge with a receipt)
"""

from __future__ import annotations

import argparse
import base64
import csv
from dataclasses import dataclass
import datetime as dt
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Any, Callable, Iterable, Sequence
import urllib.error
import urllib.parse
import urllib.request

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audio_qc_judges import (  # noqa: E402
    BLOCKED_STATUSES,
    DEFAULT_SNAPSHOT_SOURCE,
    JudgeRegistryError,
    canonical_package,
    host_profile,
    require_loadable,
    require_runnable,
    runtime_lock,
    safe_file_key,
    snapshot_file_digest,
    validate_registry,
    verify_judge_snapshot,
)

REPO = SCRIPT_DIR.parent
REGISTRY_PATH = REPO / "config/audio-qc-judges.json"
WORKER = SCRIPT_DIR / "audio_qc_worker.py"
RECEIPT_SCHEMA = "vocello.audioqc.judge-receipt/1"
RUNTIME_RECEIPT_SCHEMA = "vocello.audioqc.runtime-receipt/1"
INTERPRETER_RECEIPT_SCHEMA = "vocello.audioqc.interpreter-receipt/1"
RECEIPT_NAME = "receipt.json"
RUNTIME_RECEIPT_NAME = "vocello-runtime-receipt.json"
# Written first into every directory this tool builds, so it only ever
# replaces a directory it created itself.
OWNED_MARKER = ".vocello-audio-qc-owned"
PARTIAL_DIRECTORY = ".partial"
HUB = "https://huggingface.co"
GITHUB_RAW = "https://raw.githubusercontent.com"
PYPI_INDEX = "https://pypi.org/simple"
USER_AGENT = "vocello-audio-qc-acquisition/1"
# The hosts a download or any redirect of it may reach, over https only: the Hub
# and its CDNs, the GitHub release hosts of the interpreter and the SenseVoice
# runtime, and raw.githubusercontent.com for a GitHub-sourced snapshot.
DOWNLOAD_HOSTS = frozenset({
    "huggingface.co", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com",
    "raw.githubusercontent.com",
})
DOWNLOAD_HOST_SUFFIXES = (".hf.co", ".huggingface.co")
# Loads never reach a hub; a runtime that tries fails instead.
OFFLINE_ENVIRONMENT = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
                       "PYTHONNOUSERSITE": "1"}
# pip's own distribution; the venv module installs it, the lock does not pin it.
VENV_BASELINE = frozenset({"pip"})
BOOTSTRAP_BUILD_PACKAGES = ("setuptools",)
CHUNK_BYTES = 1 << 20
DOWNLOAD_ATTEMPTS = 6
DOWNLOAD_TIMEOUT_SECONDS = 120.0
FREE_SPACE_MARGIN_BYTES = 2 * 1024 ** 3
# The documented install estimate (docs/reference/audio-qc-engineering.md): about 1.19 GB of wheels
# install to about 3-4 GB, so a runtime is budgeted at its wheel bytes x 3.5, the interpreter likewise.
INSTALLED_BYTES_PER_DOWNLOADED_BYTE = 3.5
TRANSIENT_HTTP = frozenset({408, 425, 429, 500, 502, 503, 504})
LIST_DISTRIBUTIONS = (
    "import json\nfrom importlib import metadata\n"
    "print(json.dumps(sorted({(d.metadata['Name'], d.version) for d in metadata.distributions()})))"
)
IMPORT_PROBE = "import importlib, sys\nfor name in sys.argv[1:]:\n    importlib.import_module(name)\n"


class AcquisitionError(RuntimeError):
    """A pin, a download, a build or a verification failed; nothing unverified is kept."""


Opener = Callable[[urllib.request.Request, float], Any]
Runner = Callable[..., subprocess.CompletedProcess]


def allowed_download_url(url: str) -> bool:
    """An https URL on one of the download hosts, with no credentials and the default port."""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.password or port not in (None, 443):
        return False
    return host in DOWNLOAD_HOSTS or host.endswith(DOWNLOAD_HOST_SUFFIXES)


def _described(url: str) -> str:
    """A URL's scheme and host only (a CDN redirect carries a signed query)."""
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme or '?'}://{parts.hostname or '?'}"


class PinnedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to https on the download hosts; https to http or any other host refuses."""

    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any,
                         newurl: str) -> urllib.request.Request | None:
        if not allowed_download_url(newurl):
            raise AcquisitionError(f"a download was redirected to {_described(newurl)}, which is not an allowed "
                                   "https download host; nothing is fetched from it")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(PinnedRedirectHandler)


def _open(request: urllib.request.Request, timeout: float) -> Any:
    if not allowed_download_url(request.full_url):
        raise AcquisitionError(f"{_described(request.full_url)} is not an allowed https download host")
    return _OPENER.open(request, timeout=timeout)


def _run(argv: Sequence[str], *, env: dict[str, str] | None = None, capture: bool = False,
         cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), env=env, cwd=cwd, check=False, text=True,
                          capture_output=capture)


def _log(message: str) -> None:
    print(f"audio-qc-acquire: {message}", file=sys.stderr, flush=True)


def default_model_root() -> Path:
    cache = os.environ.get("QVOICE_DELIVERY_ANALYSIS_CACHE")
    return (Path(cache) if cache else REPO / "build/cache/delivery-analysis") / "external-models"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def entry_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _remove_owned(path: Path) -> None:
    """Remove a directory this tool built (it holds the owned marker); refuse anything else."""
    if not path.exists():
        return
    if not (path / OWNED_MARKER).is_file():
        raise AcquisitionError(f"{path.name} exists but was not built by this tool; move it aside and fetch again")
    shutil.rmtree(path)


# --------------------------------------------------------------------------- #
# Registry and selection
# --------------------------------------------------------------------------- #

def load_valid_registry(path: Path = REGISTRY_PATH, *, root: Path = REPO) -> dict[str, Any]:
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AcquisitionError(f"cannot read the judge registry: {error}") from None
    errors = validate_registry(registry, root=root)
    if errors:
        raise AcquisitionError("the judge registry is invalid: " + "; ".join(errors[:3]))
    return registry


@dataclass(frozen=True)
class Target:
    judge_id: str
    judge: dict[str, Any]
    directory: str
    stage: int
    runtime: str

    @property
    def blocked_reason(self) -> str | None:
        status = self.judge.get("status")
        if status not in BLOCKED_STATUSES:
            return None
        detail = (self.judge.get("quarantine") or self.judge.get("retirement") or {}).get("reason")
        return f"{status}: {detail}" if detail else str(status)

    @property
    def files(self) -> dict[str, dict[str, Any]]:
        return dict((self.judge.get("pins") or {}).get("files") or {})

    @property
    def repository(self) -> str | None:
        return (self.judge.get("pins") or {}).get("repository")

    @property
    def revision(self) -> str | None:
        return (self.judge.get("pins") or {}).get("revision")

    @property
    def source(self) -> str:
        return str((self.judge.get("pins") or {}).get("source", DEFAULT_SNAPSHOT_SOURCE))

    def file_url(self, name: str) -> str:
        """Where one pinned file downloads from: its Hub revision or its GitHub commit."""
        if self.source == "github":
            return github_raw_url(str(self.repository), str(self.revision), name)
        return hub_url(str(self.repository), str(self.revision), name)

    @property
    def bytes(self) -> int:
        return sum(int(pin.get("size", 0)) for pin in self.files.values())

    def snapshot(self, root: Path) -> Path | None:
        return root / self.directory / self.revision if self.revision else None


def targets(registry: dict[str, Any]) -> list[Target]:
    found = []
    for judge_id, judge in (registry.get("judges") or {}).items():
        spec = judge.get("acquisition")
        if isinstance(spec, dict):
            found.append(Target(judge_id, judge, spec["directory"], int(spec["stage"]), spec["runtime"]))
    return sorted(found, key=lambda target: (target.stage, target.judge_id))


def select(registry: dict[str, Any], *, judges: Sequence[str] = (), stage: int | None = None,
           everything: bool = False) -> list[Target]:
    available = {target.judge_id: target for target in targets(registry)}
    blocked = {entry["judge"]: entry for entry in registry.get("acquisitionBlocked") or []}
    if judges:
        chosen = []
        for judge_id in judges:
            if judge_id in blocked:
                raise AcquisitionError(f"{judge_id} is blocked: {blocked[judge_id]['reason']}")
            if judge_id not in available:
                raise AcquisitionError(f"{judge_id} is not a panel judge with an acquisition entry")
            if available[judge_id].blocked_reason:
                raise AcquisitionError(f"{judge_id} is {available[judge_id].blocked_reason}")
            chosen.append(available[judge_id])
        return chosen
    if stage is not None:
        return [target for target in available.values() if target.stage == stage]
    return list(available.values()) if everything else []


# --------------------------------------------------------------------------- #
# Downloads
# --------------------------------------------------------------------------- #

def hub_url(repository: str, revision: str, path: str) -> str:
    return f"{HUB}/{repository}/resolve/{revision}/{urllib.parse.quote(path)}"


def github_raw_url(repository: str, commit: str, path: str) -> str:
    return f"{GITHUB_RAW}/{repository}/{commit}/{urllib.parse.quote(path)}"


def _status(response: Any) -> int:
    return int(getattr(response, "status", None) or response.getcode())


def download(url: str, part: Path, *, size: int, opener: Opener = _open,
             attempts: int = DOWNLOAD_ATTEMPTS, sleep: Callable[[float], None] = time.sleep) -> None:
    """Fill `part` with `size` bytes from `url`, resuming across attempts (HTTP ranges)."""
    part.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, attempts + 1):
        have = part.stat().st_size if part.exists() else 0
        if have > size:
            part.unlink()
            have = 0
        if have == size:
            return
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with opener(urllib.request.Request(url, headers=headers), DOWNLOAD_TIMEOUT_SECONDS) as response:
                status = _status(response)
                if status == 206:
                    content_range = str(response.headers.get("Content-Range", ""))
                    if not content_range.startswith(f"bytes {have}-"):
                        raise AcquisitionError(f"the server resumed {part.name} at the wrong offset")
                    mode = "ab"
                elif status == 200:
                    mode = "wb"  # the server ignored the range: start over
                else:
                    raise AcquisitionError(f"unexpected HTTP status {status} for {part.name}")
                with part.open(mode) as handle:
                    for block in iter(lambda: response.read(CHUNK_BYTES), b""):
                        handle.write(block)
                        if handle.tell() > size:
                            break
                    handle.flush()
                    os.fsync(handle.fileno())
        except urllib.error.HTTPError as error:
            if error.code not in TRANSIENT_HTTP:
                raise AcquisitionError(f"HTTP {error.code} for {part.name}; nothing is retried") from None
            if attempt == attempts:
                raise AcquisitionError(f"HTTP {error.code} for {part.name} after {attempts} attempts") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException, TimeoutError) as error:
            if attempt == attempts:
                raise AcquisitionError(f"{part.name} could not be downloaded: {type(error).__name__}") from None
        else:
            if part.stat().st_size == size:
                return
            if part.stat().st_size > size:
                part.unlink()
        sleep(min(60.0, 5.0 * attempt))
    raise AcquisitionError(f"{part.name} is incomplete after {attempts} attempts")


def fetch_pinned_file(url: str, final: Path, part: Path, pin: dict[str, Any], *, opener: Opener = _open,
                      sleep: Callable[[float], None] = time.sleep) -> str:
    """One pinned file into its final place, verified; returns its SHA-256."""
    if final.exists():
        digest = snapshot_file_digest(final, pin)
        if digest is None:
            raise AcquisitionError(f"{final.name} is present but differs from its pin; remove it and fetch again")
        return digest
    size = pin.get("size")
    if type(size) is not int:
        raise AcquisitionError(f"{final.name} has no pinned size; a download is never unbounded")
    download(url, part, size=size, opener=opener, sleep=sleep)
    digest = snapshot_file_digest(part, pin)
    if digest is None:
        part.unlink(missing_ok=True)
        raise AcquisitionError(f"{final.name} does not match its registry pin; the download was discarded")
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(part, final)
    return digest


def fetch_archive(url: str, archive: Path, sha256: str, size: int, *, opener: Opener = _open,
                  sleep: Callable[[float], None] = time.sleep) -> None:
    """A pinned archive: an existing copy must match; an absent one is downloaded and verified."""
    if archive.exists():
        if _sha256(archive) != sha256:
            raise AcquisitionError(f"{archive.name} is present but differs from its pinned SHA-256")
        return
    part = archive.parent / PARTIAL_DIRECTORY / f"{archive.name}.part"
    download(url, part, size=size, opener=opener, sleep=sleep)
    if _sha256(part) != sha256:
        part.unlink(missing_ok=True)
        raise AcquisitionError(f"{archive.name} does not match its pinned SHA-256; the download was discarded")
    os.replace(part, archive)
    _prune_partial(archive.parent)


def _prune_partial(directory: Path) -> None:
    partial = directory / PARTIAL_DIRECTORY
    for path in sorted(partial.rglob("*"), reverse=True) if partial.is_dir() else []:
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    if partial.is_dir() and not any(partial.iterdir()):
        partial.rmdir()


def _inside(root: Path, path: Path) -> bool:
    """Whether `path`, every link in it resolved, stays inside `root`."""
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return False


def snapshot_paths(root: Path, target: Target) -> dict[str, tuple[Path, Path]]:
    """Each pinned file's final and partial path, refused unless both resolve inside the model root."""
    snapshot = target.snapshot(root)
    if snapshot is None:
        return {}
    partial = root / target.directory / PARTIAL_DIRECTORY / str(target.revision)
    paths = {}
    for name in sorted(target.files):
        if not safe_file_key(name):
            raise AcquisitionError(f"{target.judge_id}: {name!r} is not a safe relative file key")
        final, part = snapshot / name, partial / f"{name}.part"
        if not (_inside(root, final) and _inside(root, part)):
            raise AcquisitionError(f"{target.judge_id}: {name} resolves outside the model root; nothing is written")
        paths[name] = (final, part)
    return paths


def fetch_snapshot(root: Path, target: Target, *, opener: Opener = _open,
                   sleep: Callable[[float], None] = time.sleep) -> dict[str, str]:
    snapshot = target.snapshot(root)
    if snapshot is None or not target.files:
        return {}
    root.mkdir(parents=True, exist_ok=True)
    paths = snapshot_paths(root, target)
    remaining = sum(int(target.files[name]["size"]) for name, (final, _part) in paths.items() if not final.exists())
    free = shutil.disk_usage(root).free
    if remaining + FREE_SPACE_MARGIN_BYTES > free:
        raise AcquisitionError(
            f"{target.judge_id} needs {remaining / 1e9:.2f} GB plus a 2 GiB margin; {free / 1e9:.2f} GB is free"
        )
    digests = {}
    for name, (final, part) in paths.items():
        pin = target.files[name]
        _log(f"{target.judge_id}: {name} ({int(pin['size']) / 1e6:.1f} MB)")
        digests[name] = fetch_pinned_file(target.file_url(name), final, part, pin, opener=opener, sleep=sleep)
    _prune_partial(root / target.directory)
    return digests


# --------------------------------------------------------------------------- #
# Interpreter, venvs and the native runtime
# --------------------------------------------------------------------------- #

def interpreter_python(root: Path, spec: dict[str, Any]) -> Path:
    return root / spec["directory"] / spec["executable"]


def _stream_sha256(stream: Any) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(CHUNK_BYTES), b""):
        digest.update(block)
    return digest.hexdigest()


def _compiled(name: str) -> bool:
    """Bytecode Python may rewrite in place; never compared, only counted."""
    return "__pycache__" in PurePosixPath(name).parts


def interpreter_check(root: Path, spec: dict[str, Any]) -> tuple[list[str], dict[str, int]]:
    """The interpreter archive re-hashed against its pin, and every extracted file against the archive.

    Returns the problems (empty when the interpreter may run) and the counts:
    files compared, and bytecode files skipped (Python may rewrite them).
    """
    counts = {"interpreterFiles": 0, "interpreterBytecodeSkipped": 0}
    archive = root / spec["archiveDirectory"] / spec["archive"]
    if not archive.is_file() or _sha256(archive) != spec["sha256"]:
        return ["the interpreter archive is missing or differs from its pinned SHA-256"], counts
    directory = root / spec["directory"]
    receipt = _read_json(directory / RECEIPT_NAME) or {}
    if receipt.get("schema") != INTERPRETER_RECEIPT_SCHEMA or receipt.get("archiveSHA256") != spec["sha256"] \
            or not interpreter_python(root, spec).is_file():
        return ["the pinned interpreter is not extracted from its pinned archive"], counts
    changed: list[str] = []
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle:
            if not member.isfile():
                continue
            name = member.name.removeprefix("./").lstrip("/")
            if _compiled(name):
                counts["interpreterBytecodeSkipped"] += 1
                continue
            counts["interpreterFiles"] += 1
            path = directory / name
            source = bundle.extractfile(member)
            expected = _stream_sha256(source) if source is not None else ""
            if path.is_symlink() or not path.is_file() or _sha256(path) != expected:
                changed.append(name)
    if changed:
        return [f"{len(changed)} extracted interpreter files differ from the pinned archive "
                f"(first: {changed[0]})"], counts
    return [], counts


def ensure_interpreter(root: Path, spec: dict[str, Any], *, opener: Opener = _open,
                       sleep: Callable[[float], None] = time.sleep) -> Path:
    """The pinned standalone interpreter, extracted from its verified archive into its own directory.

    An existing extraction is reused only while every file still matches the archive.
    """
    archive = root / spec["archiveDirectory"] / spec["archive"]
    fetch_archive(spec["url"], archive, spec["sha256"], spec["size"], opener=opener, sleep=sleep)
    target = root / spec["directory"]
    python = interpreter_python(root, spec)
    problems, _counts = interpreter_check(root, spec)
    if not problems:
        return python
    if (target / RECEIPT_NAME).exists():
        _log(f"re-extracting the interpreter: {problems[0]}")
    _remove_owned(target)
    staging = root / f".{spec['directory']}.staging"
    _remove_owned(staging)
    staging.mkdir(parents=True)
    (staging / OWNED_MARKER).write_text("audio QC interpreter\n", encoding="utf-8")
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(staging, filter="data")
    _atomic_json(staging / RECEIPT_NAME, {"schema": INTERPRETER_RECEIPT_SCHEMA, "id": spec["id"],
                                          "archiveSHA256": spec["sha256"]})
    os.replace(staging, target)
    if not python.is_file():
        raise AcquisitionError("the extracted interpreter has no executable at its pinned path")
    return python


def build_environment() -> dict[str, str]:
    """A clean environment for venv, pip and probes: no user site and no pip configuration file at all.

    `PIP_CONFIG_FILE=/dev/null` makes pip skip every configuration file (global,
    user and site), which `--isolated` alone does not.
    """
    keep = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR")
    return {**{name: os.environ[name] for name in keep if name in os.environ}, **OFFLINE_ENVIRONMENT,
            "PIP_CONFIG_FILE": os.devnull}


def _record_digest(path: Path) -> str:
    """A file's SHA-256 as a wheel RECORD writes it: urlsafe base64 without padding."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    return base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode("ascii")


def venv_record_check(venv: Path) -> tuple[list[str], dict[str, int]]:
    """Every installed file of a venv against the SHA-256 its distribution's RECORD lists.

    RECORD entries without a hash (RECORD itself, and anything written after
    the install) are skipped and counted. A missing, changed or linked file, a
    distribution without a RECORD and an entry that points outside the venv are
    problems. Returns the problems and the counts.
    """
    counts = {"distributions": 0, "runtimeFiles": 0, "unhashedRecordEntries": 0}
    sites = sorted(venv.glob("lib/python*/site-packages"))
    if len(sites) != 1:
        return ["the venv has no single site-packages directory"], counts
    site = sites[0]
    base = os.path.normpath(venv)
    changed: list[str] = []
    missing: list[str] = []
    problems: list[str] = []
    for dist in sorted(site.glob("*.dist-info")):
        counts["distributions"] += 1
        record = dist / "RECORD"
        if record.is_symlink() or not record.is_file():
            problems.append(f"{dist.name} has no RECORD")
            continue
        try:
            rows = list(csv.reader(record.read_text(encoding="utf-8").splitlines()))
        except (OSError, UnicodeDecodeError, csv.Error):
            problems.append(f"{dist.name} has an unreadable RECORD")
            continue
        for row in rows:
            if not row or not row[0]:
                continue
            relative, recorded = row[0], (row[1] if len(row) > 1 else "")
            if not recorded:
                counts["unhashedRecordEntries"] += 1
                continue
            location = os.path.normpath(os.path.join(site, relative))
            if not location.startswith(base + os.sep):
                problems.append(f"{dist.name} records a path outside the venv")
                continue
            algorithm, _, expected = recorded.partition("=")
            path = Path(location)
            if algorithm != "sha256":
                problems.append(f"{dist.name} records {relative} with {algorithm or 'no'} hash, not sha256")
            elif path.is_symlink() or not path.is_file():
                missing.append(relative)
            elif _record_digest(path) != expected:
                changed.append(relative)
            else:
                counts["runtimeFiles"] += 1
    if changed:
        problems.append(f"{len(changed)} installed files differ from their RECORD (first: {changed[0]})")
    if missing:
        problems.append(f"{len(missing)} recorded files are missing (first: {missing[0]})")
    return problems, counts


def installed_distributions(python: Path, *, runner: Runner = _run) -> dict[str, str]:
    result = runner([str(python), "-c", LIST_DISTRIBUTIONS], env=build_environment(), capture=True)
    if result.returncode != 0:
        raise AcquisitionError(f"cannot list the distributions of {python.parent.parent.name}")
    try:
        pairs = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise AcquisitionError("the distribution listing is not JSON") from None
    return {canonical_package(str(name)): str(version) for name, version in pairs}


def lock_differences(installed: dict[str, str], lock: dict[str, dict[str, Any]]) -> list[str]:
    """What stands between an installed venv and its lock (empty when they are equal)."""
    problems = []
    for name, entry in sorted(lock.items()):
        if installed.get(name) != entry["version"]:
            problems.append(f"{name} is {installed.get(name, 'missing')}, the lock pins {entry['version']}")
    extra = sorted(set(installed) - set(lock) - VENV_BASELINE)
    if extra:
        problems.append("unlocked distributions are installed: " + ", ".join(extra))
    return problems


def import_probe(python: Path, modules: Iterable[str], *, runner: Runner = _run) -> None:
    with tempfile.TemporaryDirectory(prefix="vocello-audio-qc-probe-") as scratch:
        result = runner([str(python), "-c", IMPORT_PROBE, *modules], env=build_environment(), capture=True,
                        cwd=Path(scratch))
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-1:] or ["no error text"]
        raise AcquisitionError(f"the import probe failed in {python.parent.parent.name}: {tail[0][:200]}")


def ensure_runtime(root: Path, registry: dict[str, Any], family: str, interpreter: Path, *,
                   runner: Runner = _run, repository: Path = REPO) -> Path:
    """A runtime family's venv, built from its hash lock and proven equal to it.

    An existing venv is reused only while its receipt names the current lock and
    interpreter, its distributions equal the lock and every installed file
    matches its RECORD; otherwise it is rebuilt.
    """
    acquisition = registry["acquisition"]
    spec = acquisition["runtimes"][family]
    lock = runtime_lock(registry, family, root=repository)
    lock_path = repository / spec["lock"]
    venv = root / spec["venv"]
    python = venv / "bin/python3"
    interpreter_sha = acquisition["interpreter"]["sha256"]
    receipt = _read_json(venv / RUNTIME_RECEIPT_NAME)
    if receipt and receipt.get("schema") == RUNTIME_RECEIPT_SCHEMA and receipt.get("lockSHA256") == spec["lockSHA256"] \
            and receipt.get("interpreterSHA256") == interpreter_sha and python.is_file() \
            and not lock_differences(installed_distributions(python, runner=runner), lock):
        problems, _counts = venv_record_check(venv)
        if not problems:
            return python
        _log(f"rebuilding the {family} runtime: {problems[0]}")
    _remove_owned(venv)
    _log(f"building the {family} runtime ({len(lock)} locked packages)")
    result = runner([str(interpreter), "-m", "venv", str(venv)], env=build_environment())
    if result.returncode != 0:
        raise AcquisitionError(f"the {family} venv could not be created")
    (venv / OWNED_MARKER).write_text(f"audio QC runtime {family}\n", encoding="utf-8")
    pip = [str(python), "-m", "pip", "install", "--isolated", "--no-input", "--disable-pip-version-check",
           "--no-cache-dir", "--index-url", PYPI_INDEX, "--require-hashes", "--no-deps"]
    # pip reaches PyPI (the one networked step); `--isolated` ignores user configuration and
    # PIP_* variables, and PIP_CONFIG_FILE=/dev/null (build_environment) every configuration file.
    environment = build_environment()
    builds = [canonical_package(name) for name in spec.get("sourceBuilds") or []]
    if builds:
        bootstrap = [name for name in BOOTSTRAP_BUILD_PACKAGES if name in lock]
        if len(bootstrap) != len(BOOTSTRAP_BUILD_PACKAGES):
            raise AcquisitionError(f"the {family} lock builds sdists but pins no setuptools")
        subset = venv / "bootstrap-requirements.txt"
        subset.write_text("".join(
            f"{name}=={lock[name]['version']} " + " ".join(f"--hash=sha256:{digest}" for digest in lock[name]["hashes"])
            + "\n" for name in bootstrap), encoding="utf-8")
        steps = [
            [*pip, "--only-binary", ":all:", "-r", str(subset)],
            [*pip, "--only-binary", ":all:", "--no-binary", ",".join(builds), "--no-build-isolation",
             "-r", str(lock_path)],
        ]
    else:
        steps = [[*pip, "--only-binary", ":all:", "-r", str(lock_path)]]
    for step in steps:
        if runner(step, env=environment).returncode != 0:
            raise AcquisitionError(f"pip could not install the {family} lock; the venv stays unverified")
    problems = lock_differences(installed_distributions(python, runner=runner), lock)
    if problems:
        raise AcquisitionError(f"the {family} venv differs from its lock: " + "; ".join(problems[:3]))
    problems, _counts = venv_record_check(venv)
    if problems:
        raise AcquisitionError(f"the {family} venv differs from its RECORDs: " + "; ".join(problems[:3]))
    import_probe(python, spec["importProbe"], runner=runner)
    _atomic_json(venv / RUNTIME_RECEIPT_NAME, {
        "schema": RUNTIME_RECEIPT_SCHEMA, "family": family, "lockSHA256": spec["lockSHA256"],
        "interpreterSHA256": interpreter_sha, "packages": len(lock),
    })
    return python


def ensure_artifact(root: Path, registry: dict[str, Any], artifact_id: str, *, opener: Opener = _open,
                    sleep: Callable[[float], None] = time.sleep) -> dict[str, Path]:
    """A pinned native runtime archive and the members it runs, each verified by SHA-256."""
    spec = registry["acquisition"]["artifacts"][artifact_id]
    directory = root / spec["directory"]
    archive = directory / spec["archive"]
    fetch_archive(spec["url"], archive, spec["sha256"], spec["size"], opener=opener, sleep=sleep)
    members = {}
    for member, digest in spec["members"].items():
        path = directory / "extracted" / member
        if path.exists():
            if _sha256(path) != digest:
                raise AcquisitionError(f"{member} is present but differs from its pinned SHA-256")
            members[member] = path
            continue
        with tarfile.open(archive, "r:gz") as bundle:
            names = {name.removeprefix("./"): name for name in bundle.getnames()}
            info = bundle.getmember(names[member]) if member in names else None
            if info is None or not info.isfile():
                raise AcquisitionError(f"the pinned archive holds no file {member}")
            source = bundle.extractfile(info)
            path.parent.mkdir(parents=True, exist_ok=True)
            part = path.with_name(f".{path.name}.part")
            with part.open("wb") as handle:
                shutil.copyfileobj(source, handle, CHUNK_BYTES)
                handle.flush()
                os.fsync(handle.fileno())
        if _sha256(part) != digest:
            part.unlink(missing_ok=True)
            raise AcquisitionError(f"{member} extracted from the archive does not match its pinned SHA-256")
        part.chmod(0o755)
        os.replace(part, path)
        members[member] = path
    return members


# --------------------------------------------------------------------------- #
# Fetch, receipts and verification
# --------------------------------------------------------------------------- #

def _lock_packages(registry: dict[str, Any], family: str, repository: Path) -> list[str]:
    spec = registry["acquisition"]["runtimes"][family]
    return list(runtime_lock(registry, family, root=repository)) if spec.get("kind") == "venv" else []


def _gate(registry: dict[str, Any], target: Target, repository: Path) -> None:
    """The registry's own load gate, before anything is downloaded for a judge."""
    packages = _lock_packages(registry, target.runtime, repository)
    if target.judge.get("kind") == "neural":
        require_loadable(target.judge_id, str(target.repository), str(target.revision), packages=packages,
                         registry=registry)
    else:
        require_runnable(target.judge_id, packages=packages, registry=registry)


def _source_digest() -> str:
    return _sha256(Path(__file__).resolve())


def _installed_estimate(download_bytes: int) -> int:
    return int(download_bytes * INSTALLED_BYTES_PER_DOWNLOADED_BYTE)


def disk_requirement(root: Path, registry: dict[str, Any], selected: Sequence[Target]) -> dict[str, int]:
    """What a fetch of the selection still needs on disk, before it starts (no network).

    The remaining model bytes; each runtime family whose receipt does not name
    its current lock and interpreter, at the documented install estimate (its
    wheel bytes x 3.5); the interpreter archive and its extraction when absent;
    a native runtime archive when absent; and the 2 GiB margin.
    """
    acquisition = registry["acquisition"]
    runnable = [target for target in selected if not target.blocked_reason]
    models = 0
    for target in runnable:
        snapshot = target.snapshot(root)
        models += sum(int(pin.get("size", 0)) for name, pin in target.files.items()
                      if snapshot is None or not (snapshot / name).exists())
    interpreter_spec = acquisition["interpreter"]
    interpreter = 0
    runtimes = 0
    families = sorted({target.runtime for target in runnable})
    if families:
        if not (root / interpreter_spec["archiveDirectory"] / interpreter_spec["archive"]).exists():
            interpreter += int(interpreter_spec["size"])
        receipt = _read_json(root / interpreter_spec["directory"] / RECEIPT_NAME) or {}
        if receipt.get("archiveSHA256") != interpreter_spec["sha256"]:
            interpreter += _installed_estimate(int(interpreter_spec["size"]))
    for family in families:
        spec = acquisition["runtimes"][family]
        if spec.get("kind") == "venv":
            receipt = _read_json(root / spec["venv"] / RUNTIME_RECEIPT_NAME) or {}
            if receipt.get("lockSHA256") != spec["lockSHA256"] \
                    or receipt.get("interpreterSHA256") != interpreter_spec["sha256"]:
                runtimes += _installed_estimate(int(spec.get("downloadBytes") or 0))
        else:
            artifact = acquisition["artifacts"][spec["artifact"]]
            if not (root / artifact["directory"] / artifact["archive"]).exists():
                runtimes += 2 * int(artifact["size"])
    total = models + interpreter + runtimes + FREE_SPACE_MARGIN_BYTES
    return {"modelBytes": models, "interpreterBytes": interpreter, "runtimeInstallBytes": runtimes,
            "marginBytes": FREE_SPACE_MARGIN_BYTES, "totalBytes": total}


def require_free_space(root: Path, registry: dict[str, Any], selected: Sequence[Target]) -> dict[str, int]:
    """Refuse a fetch whose whole selection, runtimes included, does not fit on the model root's volume."""
    needed = disk_requirement(root, registry, selected)
    root.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(root).free
    if needed["totalBytes"] > free:
        raise AcquisitionError(
            f"the selection needs {needed['totalBytes'] / 1e9:.2f} GB ({needed['modelBytes'] / 1e9:.2f} GB of "
            f"models, about {needed['runtimeInstallBytes'] / 1e9:.2f} GB of runtimes, "
            f"{needed['interpreterBytes'] / 1e9:.2f} GB of interpreter and a 2 GiB margin); "
            f"{free / 1e9:.2f} GB is free, so nothing was fetched"
        )
    return needed


def fetch(root: Path, registry: dict[str, Any], selected: Sequence[Target], *, opener: Opener = _open,
          runner: Runner = _run, repository: Path = REPO, sleep: Callable[[float], None] = time.sleep,
          ) -> dict[str, Any]:
    report: dict[str, Any] = {"fetched": [], "skipped": []}
    runnable = []
    for target in selected:
        if target.blocked_reason:
            report["skipped"].append({"judge": target.judge_id, "reason": target.blocked_reason})
            continue
        _gate(registry, target, repository)
        runnable.append(target)
    if runnable:
        report["disk"] = require_free_space(root, registry, runnable)
    acquisition = registry["acquisition"]
    interpreter: Path | None = None
    runtimes: dict[str, dict[str, Any]] = {}
    for target in runnable:
        digests = fetch_snapshot(root, target, opener=opener, sleep=sleep)
        family = target.runtime
        spec = acquisition["runtimes"][family]
        if family not in runtimes:
            if interpreter is None:
                interpreter = ensure_interpreter(root, acquisition["interpreter"], opener=opener, sleep=sleep)
            if spec["kind"] == "venv":
                ensure_runtime(root, registry, family, interpreter, runner=runner, repository=repository)
                runtimes[family] = {"family": family, "kind": "venv", "lockSHA256": spec["lockSHA256"],
                                    "venv": spec["venv"], "interpreterSHA256": acquisition["interpreter"]["sha256"],
                                    "packages": spec["packages"]}
            else:
                artifact = acquisition["artifacts"][spec["artifact"]]
                ensure_artifact(root, registry, spec["artifact"], opener=opener, sleep=sleep)
                runtimes[family] = {"family": family, "kind": "native", "artifact": spec["artifact"],
                                    "archiveSHA256": artifact["sha256"],
                                    "binary": f"{artifact['directory']}/extracted/{spec['binary']}",
                                    "binarySHA256": artifact["members"][spec["binary"]],
                                    "interpreterSHA256": acquisition["interpreter"]["sha256"]}
        if target.files:
            verified = verify_judge_snapshot(
                target.judge_id, target.snapshot(root), repository=str(target.repository),
                revision=str(target.revision), packages=_lock_packages(registry, family, repository),
                registry=registry,
            )
            if verified != digests:
                raise AcquisitionError(f"{target.judge_id}: the snapshot changed while it was being verified")
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "judge": target.judge_id,
            "registryEntrySHA256": entry_digest(target.judge),
            "repository": target.repository,
            "revision": target.revision,
            "snapshot": f"{target.directory}/{target.revision}" if target.files else None,
            "files": {name: {"sha256": digest, "size": target.files[name]["size"]}
                      for name, digest in sorted(digests.items())},
            "runtime": runtimes[family],
            "acquisitionSourceSHA256": _source_digest(),
            "hostProfile": host_profile(),
            "fetchedOn": dt.date.today().isoformat(),
        }
        _atomic_json(root / target.directory / RECEIPT_NAME, receipt)
        report["fetched"].append({"judge": target.judge_id, "bytes": target.bytes, "runtime": family})
        _log(f"{target.judge_id}: fetched and verified")
    return report


def verify(root: Path, registry: dict[str, Any], selected: Sequence[Target], *, runner: Runner = _run,
           repository: Path = REPO, imports: bool = True, require: bool = True) -> list[dict[str, Any]]:
    """Re-verify each selected judge offline from its receipt.

    Each result carries its problems and the counts behind a PASS: the
    interpreter files compared with the re-hashed archive, and the venv files
    checked against their RECORDs (with the RECORD entries that carry no hash).
    """
    acquisition = registry["acquisition"]
    results = []
    probed: dict[str, tuple[list[str], dict[str, int]]] = {}
    interpreter: tuple[list[str], dict[str, int]] | None = None
    for target in selected:
        if target.blocked_reason:
            results.append({"judge": target.judge_id, "status": "BLOCKED", "problems": [target.blocked_reason]})
            continue
        receipt = _read_json(root / target.directory / RECEIPT_NAME)
        if receipt is None:
            if require:
                results.append({"judge": target.judge_id, "status": "FAIL", "problems": ["not fetched"]})
            continue
        problems: list[str] = []
        checks: dict[str, int] = {}
        if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("judge") != target.judge_id:
            problems.append("the receipt is not this judge's")
        elif receipt.get("registryEntrySHA256") != entry_digest(target.judge):
            problems.append("the registry entry changed since acquisition; fetch it again")
        family = target.runtime
        spec = acquisition["runtimes"][family]
        try:
            packages = _lock_packages(registry, family, repository)
            if target.files:
                digests = verify_judge_snapshot(
                    target.judge_id, target.snapshot(root), repository=str(target.repository),
                    revision=str(target.revision), packages=packages, registry=registry,
                )
                recorded = {name: value.get("sha256") for name, value in (receipt.get("files") or {}).items()}
                if digests != recorded:
                    problems.append("the snapshot's digests differ from its receipt")
                checks["snapshotFiles"] = len(digests)
            else:
                require_runnable(target.judge_id, packages=packages, registry=registry)
        except JudgeRegistryError as error:
            problems.append(str(error))
        runtime = receipt.get("runtime") if isinstance(receipt.get("runtime"), dict) else {}
        if spec["kind"] == "venv":
            if runtime.get("lockSHA256") != spec["lockSHA256"]:
                problems.append(f"the {family} lock changed since acquisition; fetch it again")
            if family not in probed:
                probed[family] = _verify_runtime(root, registry, family, runner=runner, repository=repository,
                                                 imports=imports)
            problems.extend(probed[family][0])
            checks.update(probed[family][1])
        else:
            artifact = acquisition["artifacts"][spec["artifact"]]
            binary = root / artifact["directory"] / "extracted" / spec["binary"]
            if not binary.is_file() or _sha256(binary) != artifact["members"][spec["binary"]]:
                problems.append(f"{spec['binary']} is missing or differs from its pinned SHA-256")
        if interpreter is None:
            interpreter = interpreter_check(root, acquisition["interpreter"])
        problems.extend(interpreter[0])
        checks.update(interpreter[1])
        results.append({"judge": target.judge_id, "status": "FAIL" if problems else "PASS", "problems": problems,
                        "checks": checks})
    return results


def _verify_runtime(root: Path, registry: dict[str, Any], family: str, *, runner: Runner, repository: Path,
                    imports: bool) -> tuple[list[str], dict[str, int]]:
    spec = registry["acquisition"]["runtimes"][family]
    venv = root / spec["venv"]
    python = venv / "bin/python3"
    receipt = _read_json(venv / RUNTIME_RECEIPT_NAME)
    if not python.is_file() or not receipt or receipt.get("lockSHA256") != spec["lockSHA256"]:
        return [f"the {family} runtime is not built from its current lock"], {}
    try:
        problems = [f"the {family} venv differs from its lock: {problem}" for problem in lock_differences(
            installed_distributions(python, runner=runner), runtime_lock(registry, family, root=repository))]
        records, counts = venv_record_check(venv)
        problems.extend(f"the {family} venv: {problem}" for problem in records)
        if not problems and imports:
            import_probe(python, spec["importProbe"], runner=runner)
    except (AcquisitionError, JudgeRegistryError) as error:
        return [str(error)], {}
    return problems, counts


# --------------------------------------------------------------------------- #
# Plan and worker launch
# --------------------------------------------------------------------------- #

def plan(root: Path, registry: dict[str, Any], selected: Sequence[Target]) -> dict[str, Any]:
    acquisition = registry["acquisition"]
    rows = []
    families: set[str] = set()
    for target in selected:
        receipt = _read_json(root / target.directory / RECEIPT_NAME)
        snapshot = target.snapshot(root)
        present = sum(1 for name in target.files if snapshot is not None and (snapshot / name).exists())
        if target.blocked_reason:
            state = "blocked"
        elif receipt and receipt.get("registryEntrySHA256") == entry_digest(target.judge):
            state = "fetched"
        elif present:
            state = "partial"
        else:
            state = "absent"
        if not target.blocked_reason:
            families.add(target.runtime)
        spec = acquisition["runtimes"][target.runtime]
        rows.append({
            "judge": target.judge_id, "status": target.judge.get("status"), "stage": target.stage,
            "repository": target.repository, "revision": target.revision, "files": len(target.files),
            "bytes": target.bytes, "destination": f"{target.directory}/{target.revision}" if target.files else None,
            "runtime": target.runtime, "venv": spec.get("venv"), "state": state,
            "blocked": target.blocked_reason,
        })
    runtime_bytes = sum(int(acquisition["runtimes"][family].get("downloadBytes") or 0) for family in families)
    runnable = [row for row in rows if not row["blocked"]]
    return {
        "modelRoot": str(root),
        "judges": rows,
        "acquisitionBlocked": [{"judge": entry["judge"], "reason": entry["reason"]}
                               for entry in registry.get("acquisitionBlocked") or []],
        "modelBytes": sum(row["bytes"] for row in runnable),
        "modelBytesByStage": {str(stage): sum(row["bytes"] for row in runnable if row["stage"] == stage)
                              for stage in sorted({row["stage"] for row in runnable})},
        "runtimeDownloadBytes": runtime_bytes,
        "interpreterBytes": acquisition["interpreter"]["size"],
        "runtimeFamilies": sorted(families),
        # What a fetch of this selection still needs free before it starts (require_free_space).
        "diskRequired": disk_requirement(root, registry, selected),
    }


def worker_launch(root: Path, registry: dict[str, Any], judge_id: str) -> dict[str, Any]:
    """How an orchestrator launches a fetched judge's worker: its interpreter, engine and configuration.

    Read from the registry and the judge's receipt; nothing is fetched. The
    worker verifies the snapshot itself before it loads.
    """
    target = next((item for item in targets(registry) if item.judge_id == judge_id), None)
    if target is None or target.blocked_reason:
        raise AcquisitionError(f"{judge_id} is not a runnable panel judge")
    receipt = _read_json(root / target.directory / RECEIPT_NAME)
    if receipt is None or receipt.get("registryEntrySHA256") != entry_digest(target.judge):
        raise AcquisitionError(f"{judge_id} is not fetched for the current registry entry")
    acquisition = registry["acquisition"]
    spec = acquisition["runtimes"][target.runtime]
    execution = target.judge["execution"]
    config: dict[str, Any] = {"judge": judge_id}
    if target.files:
        config.update(repository=target.repository, revision=target.revision, snapshot=str(target.snapshot(root)))
    for key in ("decodeOptions", "configuration", "preprocessing"):
        if key in target.judge:
            config[key] = target.judge[key]
    if spec["kind"] == "venv":
        python = root / spec["venv"] / "bin/python3"
    else:
        python = interpreter_python(root, acquisition["interpreter"])
        artifact = acquisition["artifacts"][spec["artifact"]]
        config.update(binary=str(root / artifact["directory"] / "extracted" / spec["binary"]),
                      binarySHA256=artifact["members"][spec["binary"]])
    return {"judge": judge_id, "engine": execution["engine"], "lane": execution["lane"],
            "threads": execution["threads"], "command": [str(python), str(WORKER)], "engineConfig": config}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _print_plan(value: dict[str, Any]) -> None:
    print(f"Model root: {value['modelRoot']}")
    for row in value["judges"]:
        where = row["destination"] or "(no weights)"
        note = f"  [{row['blocked']}]" if row["blocked"] else ""
        print(f"  stage {row['stage']}  {row['judge']:36s} {row['bytes'] / 1e9:7.3f} GB  {row['state']:8s} "
              f"{where}  runtime={row['runtime']}{note}")
    for entry in value["acquisitionBlocked"]:
        print(f"  blocked  {entry['judge']}: {entry['reason']}")
    stages = ", ".join(f"stage {stage} {amount / 1e9:.2f} GB" for stage, amount in value["modelBytesByStage"].items())
    print(f"Models: {value['modelBytes'] / 1e9:.2f} GB ({stages}); runtime wheels about "
          f"{value['runtimeDownloadBytes'] / 1e9:.2f} GB for {len(value['runtimeFamilies'])} families; "
          f"interpreter {value['interpreterBytes'] / 1e6:.0f} MB")
    disk = value["diskRequired"]
    print(f"A fetch of this selection needs {disk['totalBytes'] / 1e9:.2f} GB free: {disk['modelBytes'] / 1e9:.2f} GB "
          f"of models still to fetch, about {disk['runtimeInstallBytes'] / 1e9:.2f} GB of runtimes still to build, "
          f"{disk['interpreterBytes'] / 1e9:.2f} GB of interpreter and a 2 GiB margin")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "fetch", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--judge", action="append", default=[], metavar="ID")
        command.add_argument("--stage", type=int)
        command.add_argument("--all", action="store_true")
        command.add_argument("--model-root", type=Path, default=None)
        if name != "fetch":
            command.add_argument("--json", action="store_true")
        if name == "verify":
            command.add_argument("--no-import-probe", action="store_true")
    args = parser.parse_args(argv)
    root = (args.model_root or default_model_root()).resolve()
    try:
        registry = load_valid_registry()
        explicit = bool(args.judge or args.stage is not None or args.all)
        if args.command == "plan":
            value = plan(root, registry, select(registry, judges=args.judge, stage=args.stage,
                                                everything=args.all or not explicit))
            if args.json:
                print(json.dumps(value, indent=2, sort_keys=True))
            else:
                _print_plan(value)
            return 0
        if args.command == "fetch":
            if not explicit:
                raise AcquisitionError("fetch needs --judge ID, --stage N or --all")
            report = fetch(root, registry, select(registry, judges=args.judge, stage=args.stage, everything=args.all))
            results = verify(root, registry, [target for target in targets(registry)
                                              if target.judge_id in {item["judge"] for item in report["fetched"]}])
            report["verified"] = results
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if all(item["status"] == "PASS" for item in results) else 1
        results = verify(root, registry, select(registry, judges=args.judge, stage=args.stage,
                                                everything=args.all or not explicit),
                         imports=not args.no_import_probe, require=explicit)
        if args.json:
            print(json.dumps(results, indent=2, sort_keys=True))
        else:
            for item in results:
                detail = f": {'; '.join(item['problems'])}" if item["problems"] else ""
                checks = item.get("checks") or {}
                counted = (f" ({checks.get('snapshotFiles', 0)} snapshot files, {checks.get('runtimeFiles', 0)} "
                           f"runtime files against their RECORDs, {checks.get('unhashedRecordEntries', 0)} RECORD "
                           f"entries without a hash, {checks.get('interpreterFiles', 0)} interpreter files)"
                           if item["status"] == "PASS" else "")
                print(f"{item['status']:7s} {item['judge']}{counted}{detail}")
            if not results:
                print("nothing fetched yet")
        return 0 if all(item["status"] in ("PASS", "BLOCKED") for item in results) else 1
    except (AcquisitionError, JudgeRegistryError, OSError, tarfile.TarError) as error:
        print(f"audio-qc-acquire: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
