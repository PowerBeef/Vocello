#!/usr/bin/env python3
"""The data steps of scripts/ui_test.sh, as tested functions behind one command line.

The UI runner used to carry these as inline `python3 -` heredocs, which tests could reach
only by cutting the Python out of the shell text. Each subcommand behaves exactly as the
inline code did:

    script-file PATH                  refuse a startup-parity script that is not 1...2000
                                      non-NUL UTF-8 characters
    matrix MODES LENGTHS WARM         refuse a benchmark matrix outside custom,design,clone x
                                      short,medium,long or a warm count below 1
    run-metadata OUT ARG...           write run.json atomically (the 19 values after OUT, in
                                      the order `write_run_metadata` passes them)
    export-attachments RESULT OUT     export an xcresult's attachments in its own process
                                      group, bounded at 60 s, retiring the group on any exit
    long-form-summary WALL OUT DIR [SUPPORT]
                                      the macOS long-form project summary, its per-segment
                                      memory trend and the retained per-generation logs
                                      (SUPPORT: the app's debug support tree)
    virtual-mic [PATH]                the recording journey's synthetic microphone WAV

Refusals print `error: ...` to stderr and exit 1. Only the standard library: the runner
uses whichever `python3` is on PATH.
"""
from __future__ import annotations

import glob
import json
import math
import os
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from types import FrameType
from typing import Any

MODES = {"custom", "design", "clone"}
LENGTHS = {"short", "medium", "long"}
VIRTUAL_MIC = "/tmp/vocello-ui-virtual-mic.wav"
DEBUG_SUPPORT = "~/Library/Application Support/QwenVoice-Debug"
# The values `write_run_metadata` passes after the output path, in order.
RUN_METADATA_FIELDS: tuple[str, ...] = (
    "platform", "lane", "run_id", "modes", "lengths", "warm", "label", "started_at", "finished_at",
    "status", "exit_code", "audit_source_id", "control_scenario", "control_resume",
    "control_resume_run_ids", "control_resume_take_start", "control_take_limit",
    "candidate_evidence", "scenario",
)


class Refusal(Exception):
    """An invalid lane argument; the message is printed as the runner's error."""


def check_script_file(data: bytes) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Refusal("error: --script-file must be UTF-8") from None
    if not text.strip() or "\x00" in text or not 1 <= len(text) <= 2000:
        raise Refusal("error: --script-file must contain 1...2000 non-NUL characters")


def check_matrix(modes_argument: str, lengths_argument: str, warm_argument: str) -> None:
    modes = [value.strip() for value in modes_argument.split(",") if value.strip()]
    lengths = [value.strip() for value in lengths_argument.split(",") if value.strip()]
    try:
        warm = int(warm_argument)
    except ValueError:
        raise Refusal("error: --warm must be an integer") from None
    if not modes or len(modes) != len(set(modes)) or set(modes) - MODES:
        raise Refusal("error: --modes must be a unique subset of custom,design,clone")
    if not lengths or len(lengths) != len(set(lengths)) or set(lengths) - LENGTHS:
        raise Refusal("error: --lengths must be a unique subset of short,medium,long")
    if warm < 1:
        raise Refusal("error: --warm must be at least 1")


def _focus(payload: dict[str, Any], scenario: str, evidence_class: str, modes: list[str]) -> None:
    payload["scenario"] = scenario
    payload["evidenceClass"] = evidence_class
    payload["modes"] = modes
    payload["lengths"] = []
    payload["warm"] = 0


def run_metadata(values: dict[str, str], directory: Path) -> dict[str, Any]:
    """run.json's payload: the matrix as run, narrowed for focused and special lanes.

    `directory` is where run.json lives; a candidate run reads candidate-identity.json
    beside it."""
    payload: dict[str, Any] = {
        "platform": values["platform"], "lane": values["lane"], "runID": values["run_id"],
        "modes": values["modes"].split(","), "lengths": values["lengths"].split(","),
        "warm": int(values["warm"]), "label": values["label"], "status": values["status"],
        "startedAt": values["started_at"], "finishedAt": values["finished_at"] or None,
        "exitCode": int(values["exit_code"]) if values["exit_code"] else None,
        "schemaVersion": 2,
    }
    platform, lane, scenario = payload["platform"], payload["lane"], values["scenario"]
    if lane == "marketing":
        payload["evidenceClass"] = "marketing-assets"
        payload["scenario"] = scenario
        payload["warm"] = 0
        payload["lengths"] = []
    if platform == "macos" and lane == "smoke" and scenario:
        payload["scenario"] = scenario
        payload["evidenceClass"] = "focused-smoke"
        if scenario in ("design-enrollment", "clone-reference", "long-form", "line-batch"):
            mode = {"design-enrollment": "design", "clone-reference": "clone"}.get(scenario, "custom")
            _focus(payload, scenario, "focused-smoke", [mode])
        if scenario in ("long-form-recovery", "saved-voices-states"):
            _focus(payload, scenario, "focused-smoke", [])
    if platform == "ios" and lane == "smoke":
        if scenario == "foreground-exit":
            payload["scenario"] = scenario
            payload["evidenceClass"] = "focused-smoke"
        elif scenario in ("startup-retry", "record-then-play", "studio-layout"):
            _focus(payload, scenario, "focused-smoke", [])
        elif scenario == "background-warmup":
            _focus(payload, scenario, "focused-smoke", ["clone", "custom"])
        elif scenario == "long-form":
            _focus(payload, scenario, "focused-smoke", ["custom"])
        elif scenario == "update-models":
            _focus(payload, scenario, "device-maintenance", [])
    if values["audit_source_id"]:
        payload["treeFingerprint"] = values["audit_source_id"]
        payload["controlAuditScenario"] = values["control_scenario"]
        payload["controlObservationSchemaVersion"] = 2
        payload["controlEvidenceVersion"] = 2
        payload["controlTakeStart"] = int(values["control_resume_take_start"])
        payload["controlTakeLimit"] = int(values["control_take_limit"])
    if values["control_resume"]:
        payload["resumedFrom"] = values["control_resume"]
    if values["control_resume_run_ids"]:
        payload["resumeRunIDs"] = values["control_resume_run_ids"].split(",")
    if values["candidate_evidence"]:
        payload["evidenceClass"] = "preinstalled-candidate-black-box"
        payload["lane"] = "candidate-smoke"
        payload["modes"] = []
        payload["lengths"] = []
        payload["warm"] = 0
        identity = directory / "candidate-identity.json"
        if identity.is_file():
            payload["candidateIdentity"] = json.loads(identity.read_text())
    if scenario == "history-transcript":
        _focus(payload, scenario, "read-only-history-observation", [])
    return payload


def write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


class ExportInterrupted(BaseException):
    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


def _interrupted(signum: int, _frame: FrameType | None) -> None:
    raise ExportInterrupted(signum)


def export_attachments(result: str, output: str) -> int:
    """`xcresulttool export attachments` in a new session: 124 after 60 s, 128+N on
    SIGINT or SIGTERM, else its own status. Whatever happens, the group is sent SIGTERM,
    given 2 s, then SIGKILL, so no descendant outlives the export."""
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _interrupted)
    process: subprocess.Popen[bytes] | None = None
    status = 1
    try:
        process = subprocess.Popen(["xcrun", "xcresulttool", "export", "attachments", "--path", result,
                                    "--output-path", output], start_new_session=True)
        status = process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        status = 124
    except ExportInterrupted as interruption:
        status = 128 + interruption.signum
    finally:
        # Signals can arrive while the export group is being retired. Preserve the
        # first outcome and always finish cleanup before returning it to the shell.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if process is not None:
            def stop_group(sig: int) -> None:
                assert process is not None
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    pass
            stop_group(signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            # Retire descendants even when the export parent already exited.
            stop_group(signal.SIGKILL)
            process.wait()
    return status


def _flat(obj: Any, found: dict[str, Any]) -> dict[str, Any]:
    """Every numeric leaf of a telemetry row by key, the first occurrence winning."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                _flat(value, found)
            elif isinstance(value, (int, float)) and key not in found:
                found[key] = value
    elif isinstance(obj, list):
        for value in obj:
            _flat(value, found)
    return found


def long_form_summary(wall: float, out_dir: str, support: str) -> list[str] | None:
    """The newest long-form manifest's project RTF and, when the engine rows of this run
    can be matched to its segments, the per-segment physical-footprint trend. Copies the
    compact per-generation logs into `out_dir/diagnostics`. None without a manifest."""
    outputs = os.path.join(support, "outputs", "CustomVoice")
    manifests = sorted(glob.glob(os.path.join(outputs, "long_form_manifest_*.json")), key=os.path.getmtime)
    if not manifests:
        return None
    with open(manifests[-1]) as handle:
        manifest = json.load(handle)
    assembly = manifest.get("assembly") or {}
    frames = assembly.get("outputFrameCount") or 0
    sample_rate = assembly.get("sampleRate") or 24_000
    audio = frames / sample_rate if sample_rate else 0
    segment_rows = (manifest.get("execution") or {}).get("segments", [])
    segments = len(segment_rows)
    rtf = wall / audio if audio else 0
    lines = [
        f"long-form project: {segments} segments, audio {audio:.1f}s, "
        f"wall {wall:.1f}s (plan+stream+QC+assembly), project RTF {rtf:.2f}"
    ]

    # Per-segment memory trend (local evidence only). The engine telemetry rows already
    # carry physical-footprint summaries; segments have no generationID in the manifest,
    # so match the contiguous run of engine rows whose audio durations best fit the
    # manifest's per-segment durations.
    diagnostics = os.path.join(support, "diagnostics")
    engine_log = os.path.join(diagnostics, "engine", "generations.jsonl")
    durations = [segment.get("audioDurationSeconds") or 0 for segment in segment_rows]
    if segments >= 2 and durations and os.path.isfile(engine_log):
        rows: list[dict[str, Any]] = []
        with open(engine_log) as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rows.append(_flat(json.loads(raw), {}))
                except json.JSONDecodeError:
                    continue
        audio_key = "audioSeconds"
        usable = [row for row in rows if audio_key in row]
        best: tuple[float, list[dict[str, Any]]] | None = None
        for start in range(0, max(0, len(usable) - segments) + 1):
            window = usable[start:start + segments]
            if len(window) < segments:
                break
            cost = sum(abs(row[audio_key] - duration) for row, duration in zip(window, durations))
            if best is None or cost < best[0]:
                best = (cost, window)
        # Accept the match only when durations genuinely line up (<0.75 s mean error) so
        # a stale log cannot masquerade as this run's segments.
        if best and best[0] / segments < 0.75:
            lines.append("per-segment memory (engine physical footprint, MB; matched by audio duration):")
            cumulative = 0.0
            ends: list[Any] = []
            for index, row in enumerate(best[1]):
                cumulative += row.get(audio_key, 0)
                end_mb = row.get("physFootprintEndMB")
                ends.append(end_mb)
                lines.append(
                    f"  segment {index:>2}: audio={row.get(audio_key, 0):6.1f}s "
                    f"cumulative={cumulative:7.1f}s "
                    f"start={row.get('physFootprintStartMB', float('nan')):7.1f} "
                    f"end={end_mb if end_mb is not None else float('nan'):7.1f} "
                    f"peak={row.get('physFootprintPeakMB', float('nan')):7.1f}"
                )
            known_ends = [end for end in ends if end is not None]
            if len(known_ends) >= 2:
                growth = known_ends[-1] - known_ends[0]
                lines.append(
                    f"  end-footprint growth first→last: {growth:+.1f} MB "
                    f"({100 * growth / known_ends[0]:+.2f}% of first segment end)"
                )
        else:
            lines.append(
                "per-segment memory: no contiguous engine-row window matched the "
                "manifest durations; inspect diagnostics manually"
            )

    # Retain the compact per-generation logs beside the run artifacts (sample sidecars
    # stay in the app support tree; they are bounded but large).
    kept = os.path.join(out_dir, "diagnostics")
    os.makedirs(kept, exist_ok=True)
    for layer in ("app", "engine"):
        source = os.path.join(diagnostics, layer, "generations.jsonl")
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(kept, f"{layer}-generations.jsonl"))
    merged = os.path.join(diagnostics, "generations-merged.jsonl")
    if os.path.isfile(merged):
        shutil.copy2(merged, os.path.join(kept, "generations-merged.jsonl"))
    return lines


def virtual_mic_frames(sample_rate: int = 24000, seconds: float = 12.0) -> bytes:
    """Speech-like 16-bit PCM: a 175/330 Hz tone gated into syllables and phrases."""
    data = bytearray()
    for index in range(int(sample_rate * seconds)):
        t = index / sample_rate
        syllable = abs(math.sin(2 * math.pi * 2.4 * t))
        phrase = 1.0 if math.sin(2 * math.pi * 0.22 * t) > -0.55 else 0.0
        tone = 0.7 * math.sin(2 * math.pi * 175 * t) + 0.3 * math.sin(2 * math.pi * 330 * t)
        data += struct.pack("<h", int(0.28 * tone * syllable * phrase * 32767))
    return bytes(data)


def write_virtual_mic(path: str, sample_rate: int = 24000) -> None:
    with wave.open(path, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(virtual_mic_frames(sample_rate))


# Each command's positional arity. The values are passed through untouched (a label or a
# warm count may start with a dash), so there is no option parsing.
ARITY = {
    "script-file": (1, 1), "matrix": (3, 3), "run-metadata": (1 + len(RUN_METADATA_FIELDS),) * 2,
    "export-attachments": (2, 2), "long-form-summary": (3, 4), "virtual-mic": (0, 1),
}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    command, values = (argv[0], argv[1:]) if argv else ("", [])
    if command not in ARITY or not ARITY[command][0] <= len(values) <= ARITY[command][1]:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        if command == "script-file":
            check_script_file(Path(values[0]).read_bytes())
        elif command == "matrix":
            check_matrix(*values)
    except Refusal as refusal:
        print(refusal, file=sys.stderr)
        return 1
    if command == "run-metadata":
        path = Path(values[0])
        fields: dict[str, str] = dict(zip(RUN_METADATA_FIELDS, values[1:]))
        write_json_atomically(path, run_metadata(fields, path.parent))
    elif command == "export-attachments":
        return export_attachments(values[0], values[1])
    elif command == "long-form-summary":
        support = os.path.expanduser(values[3] if len(values) == 4 else DEBUG_SUPPORT)
        lines = long_form_summary(float(values[0]), values[2], support)
        if lines is not None:
            with open(values[1], "w") as handle:
                handle.write("\n".join(lines) + "\n")
            for line in lines:
                print(f"==> {line}")
    elif command == "virtual-mic":
        write_virtual_mic(values[0] if values else VIRTUAL_MIC)
    return 0


if __name__ == "__main__":
    sys.exit(main())
