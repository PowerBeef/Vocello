"""Read the vocello CLI's machine output, from today's binary and from one that speaks the v1 contract.

Today's binary prints bare per-command JSON under `--json`: an object (`generate`, `batch`,
`batch --long-form`, the schemaVersion 2 rows of a stopped batch) or an array (`speakers list`,
`modes`, `deliveries`, `voices list`, `models list|status`). A v1 binary prints one envelope
(`config/cli-contract/v1/envelope.schema.json`) whose `result` holds the same objects, with the
list commands' arrays under a key (`{"speakers": [...]}`), or, in `--output-format ndjson`, event
records that end in a `result` record carrying the envelope. This module reads all of them, so a
caller works against either binary:

- `read_result(stdout)` returns what the command produced: the envelope's `result` on success, the
  bare value of today's binary otherwise. A failure raises `VocelloCLIError` (code, exit code,
  message, detail, and the partial `result` of a stopped batch).
- `rows(payload, key)` returns a list command's rows from the bare array or the wrapped object.
- `read_batch(stdout)` returns a batch's payload whether or not every item completed: today's
  BatchJSON or LongFormBatchJSON on success, the schemaVersion 2 rows when the batch stopped (in
  the envelope's `result` of a v1 binary), with `error` set in the second case.
- `read_ndjson(stdout)` returns the event records and the final envelope (None when the stream was
  cut short). Records of a type this module does not know are kept, never rejected.

Old batch row codes are mapped to their v1 names (`published_output_missing` becomes
`output_missing`), so callers see one vocabulary from both binaries. Nothing here runs the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import functools
import json
from pathlib import Path
from typing import Any, Mapping

REPO = Path(__file__).resolve().parents[2]
ERROR_CODES = REPO / "config" / "cli-contract" / "v1" / "error-codes.json"
ENVELOPE_KEYS = frozenset({"schemaVersion", "ok", "command", "requestID", "result", "error", "warnings", "meta"})
# Batch row codes of the CLI before the v1 contract, and their v1 names.
ERROR_CODE_ALIASES: Mapping[str, str] = {"published_output_missing": "output_missing"}
# A stopped batch of today's binary reports the code of the row that stopped it when the v1
# contract gives that stop its own code; any other stop is batch_incomplete.
_STOP_CODES = frozenset({"cancelled", "memory_pressure", "engine_busy"})


class VocelloCLIOutputError(ValueError):
    """The CLI's stdout holds no output this module can read."""


class VocelloCLIError(Exception):
    """A command reported a failure; `result` is the partial outcome when there is one (a stopped batch)."""

    def __init__(self, code: str, exit_code: int | None, message: str, detail: Mapping[str, Any] | None = None,
                 *, category: str | None = None, retryable: bool = False, retry_after_ms: int | None = None,
                 hint: str | None = None, result: Any = None, command: str | None = None,
                 request_id: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.exit_code = exit_code
        self.message = message
        self.detail = dict(detail) if detail is not None else None
        self.category = category
        self.retryable = retryable
        self.retry_after_ms = retry_after_ms
        self.hint = hint
        self.result = result
        self.command = command
        self.request_id = request_id


@dataclass(frozen=True)
class BatchOutput:
    """A batch's payload, complete or stopped, with the failure that stopped it."""

    payload: dict[str, Any]
    error: VocelloCLIError | None = field(default=None)

    @property
    def complete(self) -> bool:
        return self.error is None


def canonical_error_code(code: str) -> str:
    return ERROR_CODE_ALIASES.get(code, code)


@functools.lru_cache(maxsize=1)
def error_table() -> dict[str, dict[str, Any]]:
    """The v1 error codes by code (`config/cli-contract/v1/error-codes.json`)."""
    document = json.loads(ERROR_CODES.read_text(encoding="utf-8"))
    return {row["code"]: row for row in document["errorCodes"]}


def parse_document(text: str) -> Any:
    """The JSON document on stdout: the whole text, else its last line that is a JSON object or array."""
    if not text.strip():
        raise VocelloCLIOutputError("the CLI printed nothing on stdout")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped.startswith(("{", "[")):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue
    raise VocelloCLIOutputError("the CLI's stdout holds no JSON document")


def is_envelope(value: Any) -> bool:
    return isinstance(value, dict) and ENVELOPE_KEYS <= value.keys() and isinstance(value.get("ok"), bool)


def _result_record_envelope(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict) and value.get("type") == "result" and is_envelope(value.get("data")):
        return value["data"]
    return None


def _canonical_rows(payload: Any) -> Any:
    """A copy of a batch payload whose rows carry v1 error codes."""
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return payload
    items = []
    for row in payload["items"]:
        if isinstance(row, dict) and isinstance(row.get("errorCode"), str):
            row = {**row, "errorCode": canonical_error_code(row["errorCode"])}
        items.append(row)
    return {**payload, "items": items}


def error_from_envelope(envelope: Mapping[str, Any]) -> VocelloCLIError:
    error = envelope.get("error")
    if not isinstance(error, dict) or not isinstance(error.get("code"), str):
        raise VocelloCLIOutputError("a failed envelope carries no error object")
    exit_code = error.get("exitCode")
    detail = error.get("detail")
    return VocelloCLIError(
        canonical_error_code(error["code"]), exit_code if isinstance(exit_code, int) else None,
        str(error.get("message", "")), detail if isinstance(detail, dict) else None,
        category=error.get("category") if isinstance(error.get("category"), str) else None,
        retryable=error.get("retryable") is True,
        retry_after_ms=error.get("retryAfterMs") if isinstance(error.get("retryAfterMs"), int) else None,
        hint=error.get("hint") if isinstance(error.get("hint"), str) else None,
        result=_canonical_rows(envelope.get("result")),
        command=envelope.get("command") if isinstance(envelope.get("command"), str) else None,
        request_id=envelope.get("requestID") if isinstance(envelope.get("requestID"), str) else None,
    )


def _legacy_stopped_batch(payload: Any) -> bool:
    return (isinstance(payload, dict) and payload.get("schemaVersion") == 2
            and isinstance(payload.get("items"), list) and "plannedCount" in payload)


def _legacy_batch_error(payload: dict[str, Any], exit_code: int | None) -> VocelloCLIError:
    """The v1 error a stopped batch of today's binary stands for: the stopping row's code, or batch_incomplete."""
    stop = next((row for row in payload["items"] if isinstance(row, dict)
                 and row.get("status") in ("failed", "cancelled")), None)
    row_code = canonical_error_code(stop["errorCode"]) if stop and isinstance(stop.get("errorCode"), str) else None
    code = row_code if row_code in _STOP_CODES else "batch_incomplete"
    row = error_table().get(code, {})
    detail: dict[str, Any] = {"plannedCount": payload.get("plannedCount"),
                              "completedCount": payload.get("completedCount")}
    if stop is not None:
        detail["stoppedAt"] = {"index": stop.get("index"), "status": stop.get("status"), "errorCode": row_code}
    return VocelloCLIError(
        code, exit_code if exit_code is not None else row.get("exitCode"),
        f"the batch stopped after {payload.get('completedCount')} of {payload.get('plannedCount')} items",
        detail, category=row.get("category"), retryable=row.get("retryable") is True, result=payload,
    )


def unwrap(value: Any, *, exit_code: int | None = None) -> Any:
    """What a parsed stdout document says the command produced; raises VocelloCLIError on a failure."""
    envelope = _result_record_envelope(value)
    if envelope is None and is_envelope(value):
        envelope = value
    if envelope is not None:
        if envelope["ok"]:
            return envelope.get("result")
        raise error_from_envelope(envelope)
    value = _canonical_rows(value)
    if _legacy_stopped_batch(value):
        raise _legacy_batch_error(value, exit_code)
    return value


def read_result(text: str, *, exit_code: int | None = None) -> Any:
    """The command's result from its stdout (json, or the last record of ndjson)."""
    return unwrap(parse_document(text), exit_code=exit_code)


def rows(payload: Any, key: str) -> list[Any]:
    """A list command's rows: today's bare array, or the v1 result's array under `key`."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return payload[key]
    raise VocelloCLIOutputError(f"the result holds no {key!r} list")


def read_batch(text: str, *, exit_code: int | None = None) -> BatchOutput:
    """A batch's payload from its stdout, complete or stopped; raises VocelloCLIError only when there are no rows."""
    try:
        payload = read_result(text, exit_code=exit_code)
    except VocelloCLIError as error:
        if isinstance(error.result, dict):
            return BatchOutput(error.result, error)
        raise
    if not isinstance(payload, dict):
        raise VocelloCLIOutputError("a batch prints a JSON object")
    return BatchOutput(payload)


def read_ndjson(text: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """The event records and the final envelope of an ndjson stream (None when the stream was cut short)."""
    events: list[dict[str, Any]] = []
    final: dict[str, Any] | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise VocelloCLIOutputError(f"ndjson line {number} is not JSON") from error
        if not isinstance(record, dict) or not isinstance(record.get("type"), str):
            raise VocelloCLIOutputError(f"ndjson line {number} is not an event record")
        if final is not None:
            raise VocelloCLIOutputError(f"ndjson line {number} follows the result record")
        if record["type"] == "result":
            envelope = _result_record_envelope(record)
            if envelope is None:
                raise VocelloCLIOutputError(f"ndjson line {number}: the result record carries no envelope")
            final = envelope
        else:
            events.append(record)
    return events, final

