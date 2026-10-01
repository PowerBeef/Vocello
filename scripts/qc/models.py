"""The QC v2 model registry (`config/qc/models.json`): load, validate, fetch, verify.

A model has one main `source`, optional `dependencies` (`[{name, source}]`, for
example the SSL encoder a MOS model builds on) and optional `code` pinned by
commit. Every file is pinned by size and SHA-256:

| host             | pins                                   | lands in                              |
|------------------|----------------------------------------|---------------------------------------|
| `huggingface`    | `repo`, 40-hex `revision`, `files`     | `models/<id>/` (a dependency: `models/<id>/deps/<name>/`) |
| `github-release` | `files` each with its own `url`        | as above                              |
| `github-raw`     | `repo`, 40-hex `revision`, `files`     | as above (`code`: `models/<id>/code/`) |
| `github-archive` | one `url`, `sha256`, `bytes` (`code`)  | extracted into `models/<id>/code/`    |

Downloads are HTTPS only and follow redirects only to the source's own hosts.
Each file streams to a `.part` file, is checked for size and digest, then moves
into place under `build/cache/qc/models/`. Files already present are verified and
skipped; `seed_dirs` lets a fetch hard-link (or copy) a file with the same digest
from another local cache instead of downloading it. Standard library only.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Iterator

from qc.store import LANGUAGES, Layout, read_json, write_json_atomic

SCHEMA_VERSION = 1
KINDS = ("asr", "align", "phones", "g2p", "pitch", "speaker", "mos", "aesthetics", "llm", "runtime")
RUNTIMES = ("mlx", "onnx", "torch", "llamacpp")
ROLES = ("primary", "fallback", "alternate")
FILE_HOSTS = ("huggingface", "github-release", "github-raw")
CODE_HOSTS = ("github-raw", "github-archive")

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
RUNNER_RE = re.compile(r"^qc\.runners\.[a-z][a-z0-9_]*$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")

HF_BASE = "https://huggingface.co"
RAW_BASE = "https://raw.githubusercontent.com"
HOST_ALLOWLIST = {
    "huggingface": ("huggingface.co", "hf.co"),
    # GitHub serves release assets from these hosts after the github.com redirect.
    "github-release": ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"),
    "github-raw": ("raw.githubusercontent.com",),
    "github-archive": ("codeload.github.com", "github.com"),
}
CODE_RECEIPT = ".qc-code.json"
DISK_MARGIN_BYTES = 2 * 1024**3
CHUNK = 1 << 20


class RegistryError(ValueError):
    """`config/qc/models.json` violates the registry schema."""


class FetchError(RuntimeError):
    """A download was refused or did not match its pin."""


# --- registry -------------------------------------------------------------

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RegistryError(message)


def _relative(path: str, label: str) -> None:
    _require(isinstance(path, str) and bool(path) and not PurePosixPath(path).is_absolute() and "\\" not in path
             and all(part not in ("", ".", "..") for part in path.split("/")), f"{label}: bad path {path!r}")


def _digest_pin(pin: Any, label: str) -> None:
    _require(isinstance(pin, dict), f"{label} must be an object")
    _require(isinstance(pin.get("sha256"), str) and bool(SHA256_RE.fullmatch(pin["sha256"])),
             f"{label}.sha256 must be 64 lowercase hex characters")
    size = pin.get("bytes")
    _require(isinstance(size, int) and not isinstance(size, bool) and size >= 0,
             f"{label}.bytes must be a non-negative integer")


def _https_url(url: Any, host: str, label: str) -> None:
    _require(isinstance(url, str) and url.startswith("https://"), f"{label}.url must be an https URL")
    _require(host_allowed(urllib.parse.urlsplit(url).hostname, HOST_ALLOWLIST[host]),
             f"{label}.url is not on an allowed {host} host")


def validate_source(source: Any, label: str, *, hosts: tuple[str, ...] = FILE_HOSTS) -> None:
    _require(isinstance(source, dict), f"{label} must be an object")
    host = source.get("host")
    _require(host in hosts, f"{label}: host must be one of {', '.join(hosts)}, got {host!r}")
    if host == "github-archive":
        _digest_pin(source, label)
        _https_url(source.get("url"), host, label)
        return
    if host in ("huggingface", "github-raw"):
        _require(isinstance(source.get("repo"), str) and bool(REPO_RE.fullmatch(source["repo"])),
                 f"{label}: repo must be <owner>/<name>")
        _require(isinstance(source.get("revision"), str) and bool(REVISION_RE.fullmatch(source["revision"])),
                 f"{label}: revision must be a 40-hex commit")
    files = source.get("files")
    _require(isinstance(files, dict) and bool(files), f"{label}: files must be a non-empty object")
    for path, pin in files.items():
        _relative(path, f"{label} file")
        _digest_pin(pin, f"{label} file {path}")
        if host == "github-release":
            _https_url(pin.get("url"), host, f"{label} file {path}")


def validate_model(model: Any, index: int) -> None:
    label = f"models[{index}]"
    _require(isinstance(model, dict), f"{label} must be an object")
    model_id = model.get("id")
    _require(isinstance(model_id, str) and bool(ID_RE.fullmatch(model_id)), f"{label}.id is invalid: {model_id!r}")
    label = f"model {model_id}"
    _require(model.get("kind") in KINDS, f"{label}: unknown kind {model.get('kind')!r}")
    _require(model.get("runtime") in RUNTIMES, f"{label}: unknown runtime {model.get('runtime')!r}")
    _require(model.get("role", "primary") in ROLES, f"{label}: role must be one of {', '.join(ROLES)}")
    runner = model.get("runner")
    if model["kind"] == "runtime":
        _require(runner is None, f"{label}: a runtime artifact has no runner")
    else:
        _require(isinstance(runner, str) and bool(RUNNER_RE.fullmatch(runner)),
                 f"{label}: runner must be a qc.runners.<name> module, got {runner!r}")
        memory = model.get("memoryGB")
        _require(isinstance(memory, (int, float)) and not isinstance(memory, bool) and memory > 0,
                 f"{label}: memoryGB must be a positive number")
    license_name = model.get("license")
    _require(isinstance(license_name, str) and bool(license_name.strip()), f"{label}: license must be non-empty")
    _require(isinstance(model.get("notice", ""), str), f"{label}: notice must be a string")
    version = model.get("version")
    _require(isinstance(version, int) and not isinstance(version, bool) and version >= 1,
             f"{label}: version must be a positive integer")
    languages = model.get("languages", "any")
    _require(languages == "any" or (
        isinstance(languages, list) and languages and all(item in LANGUAGES for item in languages)
        and len(set(languages)) == len(languages)
    ), f"{label}: languages must be \"any\" or a list of repository language names")
    _require(isinstance(model.get("options", {}), dict), f"{label}: options must be an object")
    if "timeoutSeconds" in model:
        timeout = model["timeoutSeconds"]
        _require(isinstance(timeout, (int, float)) and timeout > 0, f"{label}: timeoutSeconds must be positive")
    validate_source(model.get("source"), f"{label} source")
    names: set[str] = set()
    dependencies = model.get("dependencies", [])
    _require(isinstance(dependencies, list), f"{label}: dependencies must be an array")
    for position, dependency in enumerate(dependencies):
        _require(isinstance(dependency, dict), f"{label} dependencies[{position}] must be an object")
        name = dependency.get("name")
        _require(isinstance(name, str) and bool(NAME_RE.fullmatch(name)) and name not in names,
                 f"{label} dependencies[{position}]: name must be unique and lowercase")
        names.add(name)
        validate_source(dependency.get("source"), f"{label} dependency {name}")
    if "code" in model:
        validate_source(model["code"], f"{label} code", hosts=CODE_HOSTS)


def validate_registry(document: Any) -> list[dict[str, Any]]:
    _require(isinstance(document, dict), "the registry must be a JSON object")
    _require(document.get("schemaVersion") == SCHEMA_VERSION, "unsupported registry schemaVersion")
    models = document.get("models")
    _require(isinstance(models, list), "models must be an array")
    seen: set[str] = set()
    for index, model in enumerate(models):
        validate_model(model, index)
        _require(model["id"] not in seen, f"duplicate model id: {model['id']}")
        seen.add(model["id"])
    return models


def load_registry(layout: Layout = Layout()) -> list[dict[str, Any]]:
    """The validated models, or an empty list when no registry exists yet."""

    if not layout.registry.is_file():
        return []
    return validate_registry(read_json(layout.registry))


def find_model(models: Iterable[dict[str, Any]], model_id: str) -> dict[str, Any]:
    for model in models:
        if model["id"] == model_id:
            return model
    raise KeyError(f"unknown model id: {model_id}")


def runner_source(layout: Layout, model: dict[str, Any]) -> Path:
    """The source file of a `qc.runners.<name>` (or any dotted) runner module."""

    return layout.scripts.joinpath(*model["runner"].split(".")).with_suffix(".py")


# --- the files a model needs ------------------------------------------------

@dataclass(frozen=True)
class PinnedFile:
    model: str
    source: dict[str, Any]
    path: str  # repository path inside the source
    pin: dict[str, Any]
    destination: Path
    label: str  # model-relative display path

    @property
    def host(self) -> str:
        return self.source["host"]


def model_files(layout: Layout, model: dict[str, Any]) -> Iterator[PinnedFile]:
    """Every pinned file of a model: main source, dependencies, code (an archive counts once)."""

    root = layout.model_dir(model["id"])
    yield from _source_files(model["id"], model["source"], root, "")
    for dependency in model.get("dependencies", []):
        yield from _source_files(model["id"], dependency["source"], root / "deps" / dependency["name"],
                                 f"deps/{dependency['name']}/")
    code = model.get("code")
    if code and code["host"] == "github-archive":
        pin = {"sha256": code["sha256"], "bytes": code["bytes"], "url": code["url"]}
        yield PinnedFile(model["id"], code, "code.tar.gz", pin, root / "code.tar.gz", "code.tar.gz")
    elif code:
        yield from _source_files(model["id"], code, root / "code", "code/")


def _source_files(model_id: str, source: dict[str, Any], root: Path, prefix: str) -> Iterator[PinnedFile]:
    for path, pin in sorted(source["files"].items()):
        yield PinnedFile(model_id, source, path, pin, root.joinpath(*path.split("/")), prefix + path)


def file_url(item: PinnedFile, *, hf_base: str = HF_BASE, raw_base: str = RAW_BASE) -> str:
    source = item.source
    if source["host"] == "huggingface":
        return f"{hf_base}/{source['repo']}/resolve/{source['revision']}/{urllib.parse.quote(item.path)}"
    if source["host"] == "github-raw":
        return f"{raw_base}/{source['repo']}/{source['revision']}/{urllib.parse.quote(item.path)}"
    return item.pin["url"]


def pins_digest(model: dict[str, Any]) -> dict[str, Any]:
    """Every pin of a model, for the runner identity."""

    return {
        "source": {path: pin["sha256"] for path, pin in sorted(model["source"]["files"].items())},
        "dependencies": {dependency["name"]: {path: pin["sha256"] for path, pin in
                                              sorted(dependency["source"]["files"].items())}
                         for dependency in model.get("dependencies", [])},
        "code": (model["code"].get("sha256") or {path: pin["sha256"] for path, pin in
                                                 sorted(model["code"].get("files", {}).items())})
        if model.get("code") else None,
    }


# --- verify ---------------------------------------------------------------

def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_status(path: Path, pin: dict[str, Any]) -> str:
    """`ok`, `missing`, `size-mismatch` or `digest-mismatch` (re-hashes the file)."""

    if not path.is_file():
        return "missing"
    if path.stat().st_size != pin["bytes"]:
        return "size-mismatch"
    if _file_digest(path) != pin["sha256"]:
        return "digest-mismatch"
    return "ok"


def code_extracted(layout: Layout, model: dict[str, Any]) -> bool:
    code = model.get("code")
    if not code or code["host"] != "github-archive":
        return True
    try:
        return read_json(layout.model_dir(model["id"]) / "code" / CODE_RECEIPT).get("sha256") == code["sha256"]
    except (OSError, ValueError):
        return False


def verify_models(layout: Layout, models: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per pinned file: model, path, bytes and status."""

    rows = []
    for model in models:
        for item in model_files(layout, model):
            rows.append({"model": model["id"], "path": item.label, "bytes": item.pin["bytes"],
                         "status": file_status(item.destination, item.pin)})
        if not code_extracted(layout, model):
            rows.append({"model": model["id"], "path": "code/", "bytes": 0, "status": "not-extracted"})
    return rows


def fetch_size(models: Iterable[dict[str, Any]]) -> int:
    layout = Layout()
    return sum(item.pin["bytes"] for model in models for item in model_files(layout, model))


# --- safe extraction ------------------------------------------------------

def safe_extract_tar(archive: Path, destination: Path, *, strip_components: int = 0,
                     allow_symlinks: bool = False) -> None:
    """Extract regular files and directories only: no absolute paths, no `..`, no hard links,
    no devices; symbolic links only when allowed and only to targets inside `destination`."""

    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive, "r:*") as bundle:
        for member in bundle.getmembers():
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or ".." in pure.parts or "\\" in member.name:
                raise FetchError(f"unsafe archive member: {member.name}")
            parts = [part for part in pure.parts if part != "."][strip_components:]
            if not parts:
                continue
            target = destination.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                assert source is not None
                with source, target.open("wb") as handle:
                    shutil.copyfileobj(source, handle)
                os.chmod(target, 0o755 if member.mode & 0o111 else 0o644)
            elif member.issym() and allow_symlinks:
                link = PurePosixPath(member.linkname)
                resolved = (target.parent / member.linkname).resolve()
                if link.is_absolute() or not (resolved == root or root in resolved.parents):
                    raise FetchError(f"archive link escapes the destination: {member.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_symlink() or target.exists():
                    target.unlink()
                os.symlink(member.linkname, target)
            else:
                raise FetchError(f"archive member type not allowed: {member.name}")


def extract_code(layout: Layout, model: dict[str, Any]) -> None:
    """Unpack a model's verified `github-archive` code into `models/<id>/code/` (top directory stripped)."""

    code = model["code"]
    root = layout.model_dir(model["id"])
    archive = root / "code.tar.gz"
    if file_status(archive, {"sha256": code["sha256"], "bytes": code["bytes"]}) != "ok":
        raise FetchError(f"{model['id']}: code archive is missing or unverified")
    staging = root / "code.staging"
    shutil.rmtree(staging, ignore_errors=True)
    safe_extract_tar(archive, staging, strip_components=1)
    write_json_atomic(staging / CODE_RECEIPT, {"sha256": code["sha256"], "url": code["url"]})
    shutil.rmtree(root / "code", ignore_errors=True)
    os.replace(staging, root / "code")


# --- fetch ----------------------------------------------------------------

def host_allowed(host: str | None, allowed: Iterable[str]) -> bool:
    if not host:
        return False
    host = host.lower().rstrip(".")
    return any(host == item or host.endswith("." + item) for item in allowed)


def check_url(url: str, allowed_hosts: Iterable[str], *, allow_http: bool = False, what: str = "download") -> None:
    parts = urllib.parse.urlsplit(url)
    schemes = ("https", "http") if allow_http else ("https",)
    if parts.scheme not in schemes:
        raise FetchError(f"{what} refused: {parts.scheme or 'no'} scheme is not https")
    if not host_allowed(parts.hostname, allowed_hosts):
        raise FetchError(f"{what} refused: host {parts.hostname!r} is not allowed")


class _GuardedRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: tuple[str, ...], allow_http: bool) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts
        self.allow_http = allow_http

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802 (urllib API)
        target = urllib.parse.urljoin(req.full_url, newurl)
        check_url(target, self.allowed_hosts, allow_http=self.allow_http, what="redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class SeedIndex:
    """Local files by size, hashed on demand, to reuse a pinned file instead of downloading it."""

    def __init__(self, roots: Iterable[Path], exclude: Path | None = None) -> None:
        self.by_size: dict[int, list[Path]] = {}
        self.digests: dict[Path, str] = {}
        excluded = exclude.resolve() if exclude and exclude.exists() else None
        for root in roots:
            for directory, subdirectories, files in os.walk(root):
                current = Path(directory)
                if excluded and (current.resolve() == excluded or excluded in current.resolve().parents):
                    subdirectories[:] = []
                    continue
                for name in files:
                    if name.endswith(".part"):
                        continue
                    path = current / name
                    try:
                        info = path.stat()
                    except OSError:
                        continue
                    if stat.S_ISREG(info.st_mode):
                        self.by_size.setdefault(info.st_size, []).append(path.resolve())

    def find(self, pin: dict[str, Any]) -> Path | None:
        for candidate in self.by_size.get(pin["bytes"], []):
            if candidate not in self.digests:
                try:
                    self.digests[candidate] = _file_digest(candidate)
                except OSError:
                    continue
            if self.digests[candidate] == pin["sha256"]:
                return candidate
        return None


@dataclass
class Fetcher:
    """Downloads pinned files. Tests point the bases at a local server with `allow_http`."""

    layout: Layout = Layout()
    hf_base: str = HF_BASE
    raw_base: str = RAW_BASE
    allowlist: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(HOST_ALLOWLIST))
    allow_http: bool = False
    seed_dirs: tuple[Path, ...] = ()
    token: str | None = field(default_factory=lambda: os.environ.get("HF_TOKEN") or None)
    timeout: float = 60.0
    log: Callable[[str], None] = lambda message: print(message, file=sys.stderr)

    def fetch(self, models: Iterable[dict[str, Any]]) -> dict[str, int]:
        models = list(models)
        items = [item for model in models for item in model_files(self.layout, model)]
        needed = [item for item in items if file_status(item.destination, item.pin) != "ok"]
        seeded = 0
        if needed and self.seed_dirs:
            index = SeedIndex(self.seed_dirs, exclude=self.layout.models)
            remaining = []
            for item in needed:
                found = index.find(item.pin)
                if found is None:
                    remaining.append(item)
                else:
                    self._seed(item, found)
                    seeded += 1
            needed = remaining
        total = sum(item.pin["bytes"] for item in needed)
        self.log(f"qc fetch: {len(items)} files, {len(items) - len(needed) - seeded} already verified, "
                 f"{seeded} seeded locally, {len(needed)} to download: {total} bytes ({total / 1024**3:.2f} GB)")
        if needed:
            free = shutil.disk_usage(_existing_ancestor(self.layout.models)).free
            if free < total + DISK_MARGIN_BYTES:
                raise FetchError(f"refused: {free} bytes free, the download needs {total} bytes plus a 2 GB margin")
        for item in needed:
            self.download(item)
        for model in models:
            if model.get("code", {}).get("host") == "github-archive" and not code_extracted(self.layout, model):
                extract_code(self.layout, model)
        return {"files": len(items), "downloaded": len(needed), "seeded": seeded, "bytes": total}

    def _seed(self, item: PinnedFile, found: Path) -> None:
        destination = item.destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        partial.unlink(missing_ok=True)
        try:
            os.link(found, partial)
            how = "linked"
        except OSError:
            shutil.copyfile(found, partial)
            how = "copied"
        if file_status(partial, item.pin) != "ok":
            partial.unlink(missing_ok=True)
            raise FetchError(f"{item.model}/{item.label}: the seed changed while it was reused")
        os.replace(partial, destination)
        self.log(f"qc fetch: {item.model}/{item.label} {how} from the seed directory")

    def _opener(self, allowed: tuple[str, ...]) -> urllib.request.OpenerDirector:
        return urllib.request.build_opener(_GuardedRedirects(allowed, self.allow_http))

    def download(self, item: PinnedFile) -> None:
        allowed = self.allowlist[item.host]
        url = file_url(item, hf_base=self.hf_base, raw_base=self.raw_base)
        check_url(url, allowed, allow_http=self.allow_http)
        request = urllib.request.Request(url, headers={"User-Agent": "vocello-qc/1"})
        if self.token and item.host == "huggingface":
            # Unredirected: the token never follows a redirect to a CDN host.
            request.add_unredirected_header("Authorization", f"Bearer {self.token}")
        destination = item.destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        digest = hashlib.sha256()
        received = 0
        expected = item.pin["bytes"]
        self.log(f"qc fetch: {item.model}/{item.label} ({expected} bytes)")
        try:
            with self._opener(allowed).open(request, timeout=self.timeout) as response:
                check_url(response.geturl(), allowed, allow_http=self.allow_http, what="response")
                with partial.open("wb") as handle:
                    while True:
                        chunk = response.read(CHUNK)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > expected:
                            raise FetchError(f"{item.model}/{item.label}: more bytes than the pinned {expected}")
                        digest.update(chunk)
                        handle.write(chunk)
            if received != expected:
                raise FetchError(f"{item.model}/{item.label}: received {received} bytes, pinned {expected}")
            if digest.hexdigest() != item.pin["sha256"]:
                raise FetchError(f"{item.model}/{item.label}: SHA-256 mismatch, refused")
            os.replace(partial, destination)
        except urllib.error.URLError as error:
            partial.unlink(missing_ok=True)
            raise FetchError(f"{item.model}/{item.label}: download failed: {getattr(error, 'reason', error)}") from None
        except BaseException:
            partial.unlink(missing_ok=True)
            raise


def _existing_ancestor(path: Path) -> Path:
    while not path.exists():
        path = path.parent
    return path
