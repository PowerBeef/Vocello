#!/usr/bin/env python3
"""The Parquet side of `scripts/audio_qc_corpora.py extract`: runs inside the pinned corpora-parquet runtime.

The system interpreter has no pyarrow and no FLAC or Opus decoder, so the
corpora tool writes a job file and runs this worker with the runtime's own
interpreter (`config/audio-qc-runtimes/corpora-parquet.txt`, built by
`python3 scripts/audio_qc_corpora.py runtime`), offline:

    <runtime>/bin/python3 scripts/audio_qc_corpora_worker.py <job.json>

The job names the verified Parquet shards, the source's column map and output
rate, and where to write. For each row the worker reads the audio cell (the
Hugging Face `Audio` struct, its `bytes` and `path`), decodes it (a RIFF/WAVE
cell with `lib.corpus_clips`, anything else with soundfile), writes the clip
as mono PCM16 through the shared `ClipSink`, and keeps the row's raw labels
(the columns the job names); the corpora tool maps and joins them. A row
whose audio cannot be decoded is listed as skipped with its reason; a shard
without a column the job names fails the job. The results file is written
last, so a failed job leaves none.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import sys
from typing import Any, Callable, Iterable, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib import corpus_clips as clips  # noqa: E402

JOB_KIND = "audio-qc-corpora-parquet-job"
RESULT_KIND = "audio-qc-corpora-parquet-result"
SCHEMA_VERSION = 1
BATCH_ROWS = 16
AUDIO_PATH = "@audio-path"
ROW_INDEX = "@row"


class WorkerError(RuntimeError):
    """The job cannot run: a malformed job, a missing column or an unreadable shard."""


def _log(message: str) -> None:
    print(f"audio-qc-corpora-worker: {message}", file=sys.stderr, flush=True)


def decode_other(data: bytes) -> tuple[Any, int, dict[str, Any]]:
    """A non-WAV audio cell (FLAC, Ogg Opus or Vorbis, MP3) through soundfile's bundled libsndfile."""
    import soundfile

    try:
        with soundfile.SoundFile(io.BytesIO(data)) as handle:
            rate, channels = int(handle.samplerate), int(handle.channels)
            subtype, container = str(handle.subtype), str(handle.format)
            if subtype == "PCM_16":
                frames, scale = handle.read(dtype="int16", always_2d=True), float(clips.PCM16_FULL_SCALE)
            else:
                frames, scale = handle.read(dtype="float64", always_2d=True), 1.0
    except (RuntimeError, ValueError, TypeError) as error:
        raise clips.CorpusAudioError(f"soundfile cannot decode it ({type(error).__name__})") from None
    if len(frames) == 0:
        raise clips.CorpusAudioError("it holds no sample")
    return frames, rate, {"sourceFormat": f"{container}-{subtype}".lower(), "sourceRate": rate,
                          "sourceChannels": channels, "scale": scale}


def clip_audio(data: bytes, *, output_rate: int,
               decode: Callable[[bytes], tuple[Any, int, dict[str, Any]]] = decode_other) -> tuple[bytes, dict]:
    """A cell's clip: a WAV through `lib.corpus_clips` (soundfile only for a WAV codec it does not read, such as
    ADPCM), anything else through soundfile."""
    if clips.is_wav(data):
        try:
            return clips.clip_from_wav(data, output_rate=output_rate)
        except clips.CorpusAudioError as error:
            try:
                frames, rate, source = decode(data)
            except clips.CorpusAudioError:
                raise error from None
    else:
        frames, rate, source = decode(data)
    return clips.clip_from_samples(frames, rate, scale=source["scale"], output_rate=output_rate, source=source)


def _audio_cell(value: Any) -> tuple[bytes | None, str | None]:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value), None
    if isinstance(value, Mapping):
        data = value.get("bytes")
        path = value.get("path")
        return (bytes(data) if isinstance(data, (bytes, bytearray)) else None,
                path if isinstance(path, str) and path else None)
    return None, None


def row_identity(row: Mapping[str, Any], spec: Mapping[str, Any], shard: str, index: int,
                 audio_path: str | None) -> str:
    """The corpus's own id of a row: a column, the audio cell's file stem, or the shard and row index."""
    column = (spec.get("columns") or {}).get("id")
    if column == AUDIO_PATH and audio_path:
        return PurePosixPath(audio_path).stem
    if column not in (None, AUDIO_PATH, ROW_INDEX):
        value = clips.label_text(row.get(column))
        if value is not None:
            return value
    return f"{PurePosixPath(shard).stem}-{index}"


def process_rows(rows: Iterable[Mapping[str, Any]], *, job: Mapping[str, Any], file: Mapping[str, Any],
                 sink: clips.ClipSink, decode: Callable[[bytes], tuple[Any, int, dict[str, Any]]] = decode_other,
                 ) -> int:
    """Write every row of one shard through the sink; returns the rows read."""
    spec = job["extract"]
    columns = spec.get("columns") or {}
    audio_column = spec["audioColumn"]
    count = 0
    for index, row in enumerate(rows):
        count += 1
        origin = f"{file['shard']}#{index}"
        data, audio_path = _audio_cell(row.get(audio_column))
        if data is None:
            sink.skip(origin, "the row has no audio bytes")
            continue
        identity = row_identity(row, spec, file["shard"], index, audio_path)
        labels: dict[str, Any] = {"language": file["language"], "split": file.get("split"), "sourceID": identity}
        for label in ("speaker", "gender", "emotion", "text"):
            if columns.get(label):
                labels[label] = clips.label_text(row.get(columns[label]))
        if spec.get("scores"):
            labels["scores"] = {name: row.get(name) for name in spec["scores"]}
        try:
            wav, info = clip_audio(data, output_rate=job["outputRate"], decode=decode)
            identifier = clips.clip_id(job["source"], *([file["idPrefix"]] if file.get("idPrefix") else []),
                                       identity)
        except clips.CorpusAudioError as error:
            sink.skip(origin, str(error))
            continue
        sink.add(identifier, wav, info, labels, origin=origin, source_sha256=hashlib.sha256(data).hexdigest())
    return count


def parquet_rows(path: Path, needed: Iterable[str]) -> Iterable[dict[str, Any]]:
    """Rows of one Parquet shard, only the named columns, a few at a time (pyarrow)."""
    import pyarrow.parquet as parquet

    handle = parquet.ParquetFile(str(path))
    names = set(handle.schema_arrow.names)
    missing = sorted(set(needed) - names)
    if missing:
        raise WorkerError(f"{path.name} has no column {', '.join(missing)}; its columns are "
                          f"{', '.join(sorted(names))}")
    for batch in handle.iter_batches(batch_size=BATCH_ROWS, columns=sorted(set(needed))):
        yield from batch.to_pylist()


def needed_columns(spec: Mapping[str, Any]) -> list[str]:
    columns = [spec["audioColumn"]]
    columns += [name for name in (spec.get("columns") or {}).values() if name and not name.startswith("@")]
    columns += list(spec.get("scores") or ())
    return sorted(set(columns))


def run_job(job: Mapping[str, Any], *,
            reader: Callable[[Path, Iterable[str]], Iterable[Mapping[str, Any]]] = parquet_rows,
            decode: Callable[[bytes], tuple[Any, int, dict[str, Any]]] = decode_other) -> dict[str, Any]:
    if not isinstance(job, Mapping) or job.get("kind") != JOB_KIND or job.get("schemaVersion") != SCHEMA_VERSION:
        raise WorkerError(f"the job is not an {JOB_KIND} schema {SCHEMA_VERSION} file")
    sink = clips.ClipSink(Path(job["wavDirectory"]))
    shards = []
    for file in job["files"]:
        _log(f"{job['source']}: reading {file['shard']}")
        rows = process_rows(reader(Path(file["path"]), needed_columns(job["extract"])), job=job, file=file,
                            sink=sink, decode=decode)
        shards.append({"shard": file["shard"], "rows": rows})
        _log(f"{job['source']}: {file['shard']}: {rows} rows; {len(sink.clips)} clips so far")
    return {"schemaVersion": SCHEMA_VERSION, "kind": RESULT_KIND, "source": job["source"], "shards": shards,
            **sink.result()}


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        print("usage: audio_qc_corpora_worker.py <job.json>", file=sys.stderr)
        return 2
    try:
        job = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
        result = run_job(job)
        output = Path(job["results"])
        temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(temporary, output)
    except (WorkerError, OSError, KeyError, TypeError, ValueError) as error:
        print(f"audio-qc-corpora-worker: FAIL\n{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
