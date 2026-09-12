"""One JSON read/write/digest toolkit for every script.

Until 2026-09-12 the scripts carried sixteen `load_json`, twelve `canonical_bytes`,
twelve `atomic_json` and twenty-one file-digest definitions under five names.
They differed only in options that this module exposes as keywords: whether a
canonical encoding escapes non-ASCII, ends with a newline or allows NaN, whether
an atomic write creates the parent directory or fsyncs it, which exception a
failed read raises and how much of the path that exception may show.

Persisted digests depend on the exact bytes, so callers pass the options that
reproduce their historical encoding; the defaults are the most common one
(compact, ASCII, no newline, no NaN for canonical bytes; indent 2 plus newline
for files).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable


class JSONReadError(ValueError):
    """A JSON file could not be read or does not have the expected shape."""


def _shown(path: Path, redact: str) -> str:
    return path.name if redact in ("name", "type") else str(path)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(
    path: Path,
    *,
    error: type[Exception] = JSONReadError,
    require_object: bool = True,
    reject_duplicate_keys: bool = False,
    redact: str = "path",
) -> Any:
    """Read a JSON file, raising `error` with a bounded message on failure.

    `redact` controls how much of the path a message may contain: "path" (the
    full path), "name" (the file name only) or "type" (the file name and the
    exception type only, for surfaces that must not echo host details).
    """
    shown = _shown(path, redact)
    try:
        text = path.read_text(encoding="utf-8")
        value = json.loads(text, object_pairs_hook=_reject_duplicate_keys if reject_duplicate_keys else None)
    except (OSError, ValueError) as failure:
        detail = type(failure).__name__ if redact == "type" else str(failure)
        raise error(f"cannot read JSON {shown}: {detail}") from failure
    if require_object and not isinstance(value, dict):
        raise error(f"{shown} must contain a JSON object")
    return value


def canonical_bytes(
    value: Any, *, ascii: bool = True, newline: bool = False, allow_nan: bool = False,
) -> bytes:
    """Compact, key-sorted JSON bytes: the input of every content digest."""
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=ascii, allow_nan=allow_nan,
    )
    return (encoded + "\n" if newline else encoded).encode("utf-8")


def pretty_bytes(value: Any, *, ascii: bool = True, allow_nan: bool = True) -> bytes:
    """Indent-2, key-sorted JSON bytes ending in a newline: the tracked-file shape."""
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=ascii, allow_nan=allow_nan) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(value: Any, **options: Any) -> str:
    """Digest of `canonical_bytes(value, **options)`."""
    return sha256_bytes(canonical_bytes(value, **options))


def sha256_file(path: Path, *, error: type[Exception] | None = None) -> str:
    """Streaming SHA-256 of a file (1 MiB blocks); `error` wraps an OSError when given."""
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as failure:
        if error is None:
            raise
        raise error(f"cannot hash {path}: {failure}") from failure
    return digest.hexdigest()


def utc_now(*, whole_seconds: bool = True) -> str:
    """ISO-8601 UTC timestamp with a Z suffix, truncated to seconds by default."""
    now = datetime.now(timezone.utc)
    if whole_seconds:
        now = now.replace(microsecond=0)
    return now.isoformat().replace("+00:00", "Z")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(
    path: Path, data: bytes, *, mkdir: bool = True, fsync_dir: bool = False, prefix: str | None = None,
) -> None:
    """Write `data` to a temporary sibling, fsync it, then rename over `path`."""
    path = Path(path)
    if mkdir:
        path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=prefix or f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if fsync_dir:
            _fsync_directory(path.parent)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def atomic_json(
    path: Path, value: Any, *, ascii: bool = True, allow_nan: bool = True,
    mkdir: bool = True, fsync_dir: bool = False,
    encoder: Callable[[Any], bytes] | None = None,
) -> None:
    """Atomically write `value` as indent-2 sorted JSON (or through `encoder`)."""
    data = encoder(value) if encoder is not None else pretty_bytes(value, ascii=ascii, allow_nan=allow_nan)
    atomic_write_bytes(path, data, mkdir=mkdir, fsync_dir=fsync_dir)
