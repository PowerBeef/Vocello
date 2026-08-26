#!/usr/bin/env python3
"""Correlate physical-iPhone model-delivery, UI, and progress-rendering evidence.

The checker is local-only and fail-closed on malformed/cross-run evidence. A diagnose run may
produce a correctly classified product failure (MD-3) while still proving the harness itself is
complete; acceptance requires a clean diagnosis.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import math
import pathlib
import re
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


OBSERVATION_PREFIX = "VOCELLO_MODEL_OBSERVATION="
PASS_SCENARIOS = {"acceptance", "queue", "recover", "soak"}
REQUIRED_PROGRESS_MILESTONES = {"transfer-1", "transfer-25", "transfer-50", "transfer-75", "transfer-95"}


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_observations(log_path: pathlib.Path) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    if not log_path.is_file():
        return observations
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if OBSERVATION_PREFIX not in line:
            continue
        encoded = line.rsplit(OBSERVATION_PREFIX, 1)[1].strip()
        try:
            value = json.loads(base64.b64decode(encoded, validate=True))
        except (ValueError, binascii.Error, json.JSONDecodeError) as error:
            raise SystemExit(f"malformed model-management UI observation: {error}") from error
        if value.get("schemaVersion") != 1:
            raise SystemExit("unsupported model-management UI observation schema")
        observations.append(value)
    return observations


def xcodebuild_failed(log_path: pathlib.Path) -> bool:
    if not log_path.is_file():
        return False
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return "** TEST FAILED **" in text or bool(
        re.search(r"Executed\s+\d+\s+tests?,\s+with\s+[1-9]\d*\s+failures?", text)
    )


def read_trace(root: pathlib.Path, run_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted(root.glob("**/trace/event-*.json")):
        value = load_json(path)
        validate_trace_event(value, path, run_id)
        value["_artifact"] = str(path.relative_to(root))
        events.append(value)
    for path in sorted(root.glob("**/trace/**/*.jsonl")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise SystemExit(
                    f"malformed delivery trace journal {path}:{line_number}: {error}"
                ) from error
            validate_trace_event(value, path, run_id)
            value["_artifact"] = f"{path.relative_to(root)}#{line_number}"
            events.append(value)
    events.sort(key=lambda row: (row.get("capturedAtUTC", ""), row.get("processInstanceID", ""), row.get("sequence", 0)))
    return events


def validate_trace_event(value: Any, path: pathlib.Path, run_id: str) -> None:
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise SystemExit(f"unsupported delivery trace schema in {path}")
    if value.get("runID") != run_id:
        raise SystemExit(
            f"cross-run delivery trace contamination: {path.name} belongs to "
            f"{value.get('runID')!r}, expected {run_id!r}"
        )


def partition_prior_trace_events(root: pathlib.Path, run_id: str) -> dict[str, int]:
    """Move older retained-run events out of the active trace input without discarding them.

    A failed physical-device run deliberately leaves one bounded support root for the next
    diagnostic. The pull therefore contains prior journal files by design. Keep those files in the
    host artifact for comparison, but ensure the current run's validator sees one run identity.
    `read_trace` remains fail-closed if a mismatched event is left in the active trace directory.
    """
    trace_root = root / "trace"
    prior_root = root / "prior-traces"
    current = prior = 0
    for path in sorted(trace_root.glob("event-*.json")):
        value = load_json(path)
        if value.get("schemaVersion") != 1:
            raise SystemExit(f"unsupported delivery trace schema in {path}")
        event_run_id = value.get("runID")
        if event_run_id == run_id:
            current += 1
            continue
        safe_run_id = re.sub(r"[^A-Za-z0-9._-]+", "-", str(event_run_id or "unknown"))[:96]
        destination = prior_root / safe_run_id / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        path.replace(destination)
        prior += 1
    for path in sorted(trace_root.glob("**/*.jsonl")):
        rows = []
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise SystemExit(
                    f"malformed delivery trace journal {path}:{line_number}: {error}"
                ) from error
            if not isinstance(value, dict) or value.get("schemaVersion") != 1:
                raise SystemExit(f"unsupported delivery trace schema in {path}")
            rows.append(value)
        run_ids = {row.get("runID") for row in rows}
        if run_ids == {run_id}:
            current += len(rows)
            continue
        if len(run_ids) != 1:
            raise SystemExit(f"mixed-run delivery trace journal: {path}")
        event_run_id = next(iter(run_ids), None)
        safe_run_id = re.sub(r"[^A-Za-z0-9._-]+", "-", str(event_run_id or "unknown"))[:96]
        destination = prior_root / safe_run_id / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        path.replace(destination)
        prior += len(rows)
    return {"currentEventCount": current, "priorEventCount": prior}


def missing_progress_milestones(
    observations: Iterable[dict[str, Any]],
    scenario: str,
) -> list[str]:
    if scenario not in {"diagnose", "acceptance"}:
        return []
    captured = {
        observation.get("milestone")
        for observation in observations
        if observation.get("modelID") == "pro_custom"
    }
    return sorted(REQUIRED_PROGRESS_MILESTONES - captured)


def invalid_progress_milestone_ranges(
    observations: Iterable[dict[str, Any]],
    scenario: str,
) -> list[str]:
    """Reject a nominal late-transfer checkpoint that is not genuinely near 95%.

    Exact durable catalog-byte updates may jump from an incomplete sample to completion. The UI
    harness therefore captures the first real sample in the five-point band below 95%; it never
    manufactures a percentage or leaves a full determinate bar on screen during finalization.
    """
    if scenario not in {"diagnose", "acceptance"}:
        return []
    invalid: list[str] = []
    for observation in observations:
        if observation.get("modelID") != "pro_custom" or observation.get("milestone") != "transfer-95":
            continue
        fraction = observation.get("expectedFraction")
        if not isinstance(fraction, (int, float)) or not math.isfinite(fraction) or not 0.90 <= fraction < 1:
            invalid.append("transfer-95")
    return sorted(set(invalid))


def attachment_map(attachments: pathlib.Path) -> dict[str, pathlib.Path]:
    manifest = attachments / "manifest.json"
    if not manifest.is_file():
        return {}
    result: dict[str, pathlib.Path] = {}
    value = load_json(manifest)
    tests = value if isinstance(value, list) else value.get("tests", [])
    for test in tests:
        for attachment in test.get("attachments", []):
            name = attachment.get("suggestedHumanReadableName")
            exported = attachment.get("exportedFileName")
            if name and exported:
                path = attachments / exported
                result[name] = path
                # Xcode 26 decorates explicit XCTAttachment names during export with an
                # occurrence counter and UUID. UI observations intentionally record the stable
                # source name, so also expose that canonical key without weakening exact-name
                # lookup for ordinary attachments.
                canonical = re.sub(
                    r"_\d+_[0-9A-Fa-f-]{36}(?:\.[A-Za-z0-9]+)?$",
                    "",
                    name,
                )
                result.setdefault(canonical, path)
    return result


def png_pixels(path: pathlib.Path) -> tuple[int, int, list[tuple[int, int, int]]]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    position = 8
    width = height = color_type = bit_depth = 0
    compressed = bytearray()
    while position + 12 <= len(data):
        length = struct.unpack(">I", data[position : position + 4])[0]
        kind = data[position + 4 : position + 8]
        payload = data[position + 8 : position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, _ = struct.unpack(">IIBBBBB", payload)
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
    channels = {2: 3, 6: 4}.get(color_type)
    if bit_depth != 8 or channels is None or width <= 0 or height <= 0:
        raise ValueError("unsupported PNG format")
    raw = zlib.decompress(bytes(compressed))
    stride = width * channels
    previous = bytearray(stride)
    offset = 0
    pixels: list[tuple[int, int, int]] = []
    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        scan = bytearray(raw[offset : offset + stride])
        offset += stride
        for index in range(stride):
            left = scan[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                scan[index] = (scan[index] + left) & 0xFF
            elif filter_type == 2:
                scan[index] = (scan[index] + up) & 0xFF
            elif filter_type == 3:
                scan[index] = (scan[index] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                estimate = left + up - upper_left
                pa, pb, pc = abs(estimate - left), abs(estimate - up), abs(estimate - upper_left)
                predictor = left if pa <= pb and pa <= pc else (up if pb <= pc else upper_left)
                scan[index] = (scan[index] + predictor) & 0xFF
            elif filter_type != 0:
                raise ValueError("unsupported PNG filter")
        for index in range(0, stride, channels):
            pixels.append((scan[index], scan[index + 1], scan[index + 2]))
        previous = scan
    return width, height, pixels


def relative_luminance(rgb: tuple[float, float, float]) -> float:
    def channel(value: float) -> float:
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    one, two = relative_luminance(first), relative_luminance(second)
    return (max(one, two) + 0.05) / (min(one, two) + 0.05)


def average(values: Iterable[tuple[int, int, int]]) -> tuple[float, float, float]:
    values = list(values)
    if not values:
        return (0, 0, 0)
    return tuple(sum(pixel[index] for pixel in values) / len(values) for index in range(3))


def color_distance(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    return math.sqrt(sum((first[index] - second[index]) ** 2 for index in range(3)))


def analyze_bar(path: pathlib.Path, reported_fraction: float) -> dict[str, Any]:
    width, height, pixels = png_pixels(path)
    # Inspect the capsule's central band. Averaging its full height makes the rounded leading
    # cap look like background in the first columns and previously measured every real bar as
    # zero-width. The reported fraction is used only to choose samples that are safely inside the
    # expected fill and track; the transition itself is independently measured from pixels.
    first_row = height // 3
    last_row = max(first_row + 1, height - height // 3)
    columns = [
        average(pixels[row * width + column] for row in range(first_row, last_row))
        for column in range(width)
    ]
    inset = min(max(1, height // 2), max(1, width // 20))
    # The central band is fully inside the capsule, so only discard one edge pixel when
    # sampling the trailing track. Reusing the full cap-radius inset here made a truthful 99%
    # bar sample the fill immediately before its narrow remaining track and falsely report
    # 1:1 contrast. Keep the larger leading inset for the rounded-cap anchor check below.
    edge_guard = 1
    sample_limit = max(2, width // 20)
    fill_sample_width = max(2, min(sample_limit, int(max(reported_fraction, 0.01) * width / 2)))
    track_sample_width = max(2, min(sample_limit, int(max(1 - reported_fraction, 0.01) * width / 2)))
    fill_color = average(columns[inset : min(width, inset + fill_sample_width)])
    track_end = max(inset + 1, width - edge_guard)
    track_color = average(columns[max(inset, track_end - track_sample_width) : track_end])
    separation = color_distance(fill_color, track_color)
    sustain = max(2, height // 4)
    endpoint = width - edge_guard
    for column in range(inset, width - edge_guard):
        stop = min(width - edge_guard, column + sustain)
        if stop - column < sustain:
            break
        if all(
            color_distance(columns[index], track_color)
            < color_distance(columns[index], fill_color)
            for index in range(column, stop)
        ):
            endpoint = column
            break
    measured = endpoint / width
    ratio = contrast_ratio(fill_color, track_color)
    fill_chroma = max(fill_color) - min(fill_color)
    track_chroma = max(track_color) - min(track_color)
    leading_edge_anchored = (
        endpoint > inset
        and separation >= 12
        and fill_chroma > track_chroma + 5
        and color_distance(columns[inset], fill_color)
        < color_distance(columns[inset], track_color)
    )
    return {
        "image": str(path),
        "width": width,
        "height": height,
        "reportedFraction": reported_fraction,
        "measuredFillFraction": measured,
        "fractionDelta": abs(measured - reported_fraction),
        "leadingEdgeAnchored": leading_edge_anchored,
        "finiteAndUnclipped": width > 0 and height > 0 and 0 <= measured <= 1,
        "contrastRatio": ratio,
        "passesFractionTolerance": leading_edge_anchored and abs(measured - reported_fraction) <= 0.05,
        "passesContrast": ratio >= 3.0,
    }


def write_png(path: pathlib.Path, width: int, height: int, pixels: list[tuple[int, int, int]]) -> None:
    raw = bytearray()
    for row in range(height):
        raw.append(0)
        for red, green, blue in pixels[row * width : (row + 1) * width]:
            raw.extend((red, green, blue))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def resized(path: pathlib.Path, maximum_width: int, maximum_height: int) -> tuple[int, int, list[tuple[int, int, int]]]:
    width, height, pixels = png_pixels(path)
    scale = min(maximum_width / width, maximum_height / height, 1.0)
    target_width = max(1, int(width * scale))
    target_height = max(1, int(height * scale))
    result: list[tuple[int, int, int]] = []
    for y in range(target_height):
        source_y = min(height - 1, int(y / scale))
        for x in range(target_width):
            source_x = min(width - 1, int(x / scale))
            result.append(pixels[source_y * width + source_x])
    return target_width, target_height, result


def make_contact_sheet(
    observations: list[dict[str, Any]],
    attachments: dict[str, pathlib.Path],
    destination: pathlib.Path,
) -> bool:
    rows: list[tuple[tuple[int, int, list[tuple[int, int, int]]] | None, tuple[int, int, list[tuple[int, int, int]]] | None]] = []
    for observation in observations:
        row_path = attachments.get(observation.get("rowScreenshot", ""))
        progress_path = attachments.get(observation.get("progressScreenshot", ""))
        try:
            row_image = resized(row_path, 520, 180) if row_path and row_path.is_file() else None
            progress_image = resized(progress_path, 300, 80) if progress_path and progress_path.is_file() else None
        except (OSError, ValueError, zlib.error):
            continue
        if row_image or progress_image:
            rows.append((row_image, progress_image))
    if not rows:
        return False
    padding = 12
    canvas_width = 860
    heights = [max(row[0][1] if row[0] else 0, row[1][1] if row[1] else 0, 44) + padding for row in rows]
    canvas_height = padding + sum(heights)
    canvas = [(20, 21, 29)] * (canvas_width * canvas_height)

    def paste(image: tuple[int, int, list[tuple[int, int, int]]], origin_x: int, origin_y: int) -> None:
        width, height, pixels = image
        for y in range(height):
            start = (origin_y + y) * canvas_width + origin_x
            canvas[start : start + width] = pixels[y * width : (y + 1) * width]

    y = padding
    for row_image, progress_image in rows:
        if row_image:
            paste(row_image, padding, y)
        if progress_image:
            paste(progress_image, 548, y)
        y += max(row_image[1] if row_image else 0, progress_image[1] if progress_image else 0, 44) + padding
    write_png(destination, canvas_width, canvas_height, canvas)
    return True


@dataclass
class Finding:
    code: str
    subsystem: str
    message: str
    last_consistent: dict[str, Any] | None = None
    first_divergent: dict[str, Any] | None = None

    def json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "subsystem": self.subsystem,
            "message": self.message,
            "lastConsistentEvent": self.last_consistent,
            "firstDivergentEvent": self.first_divergent,
        }


def diagnose(
    events: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    *,
    test_execution_failed: bool = False,
) -> list[Finding]:
    findings: list[Finding] = []
    if not events:
        return [Finding("missing-trace", "harness", "No correlated delivery trace was collected.")]
    missing_observations = not observations

    sequences_by_process: dict[str, list[int]] = {}
    for event in events:
        sequences_by_process.setdefault(event.get("processInstanceID", "unknown"), []).append(int(event.get("sequence", 0)))
    for process, sequences in sequences_by_process.items():
        ordered = sorted(sequences)
        if ordered != list(range(ordered[0], ordered[-1] + 1)):
            findings.append(Finding("trace-sequence-gap", "harness", f"Trace process {process[:8]} has missing or duplicate sequence numbers."))

    progress_by_request: dict[tuple[str, str], tuple[int, int]] = {}
    for event in events:
        if event.get("event") != "progress":
            continue
        model_id = event.get("modelID")
        request_id = event.get("logicalRequestID")
        durable, total = event.get("durableBytes"), event.get("totalBytes")
        if model_id and request_id and isinstance(durable, int) and isinstance(total, int) and total > 0:
            key = (model_id, request_id)
            previous = progress_by_request.get(key)
            if durable > total:
                findings.append(Finding("bytes-exceed-total", "downloader", f"{model_id} durable bytes exceed catalog bytes.", previous and {"durableBytes": previous[0], "totalBytes": previous[1]}, event))
            clean_retry_reset = (
                previous
                and durable < previous[0]
                and event.get("phase") == "retrying"
                and event.get("errorClassification")
                in {"integrity", "range-response", "chunk-assembly"}
            )
            if previous and durable < previous[0] and not clean_retry_reset:
                findings.append(Finding("progress-regressed", "downloader", f"{model_id} durable progress regressed.", {"durableBytes": previous[0], "totalBytes": previous[1]}, event))
            progress_by_request[key] = (
                durable if clean_retry_reset else max(durable, previous[0] if previous else 0),
                total,
            )

    task_events: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for event in events:
        process = event.get("processInstanceID")
        task_id = event.get("taskID")
        if process and isinstance(task_id, int):
            task_events.setdefault((process, task_id), []).append(event)
    for task_history in task_events.values():
        terminal = next((row for row in task_history if row.get("event") == "task-completed"), None)
        landed = next((row for row in task_history if row.get("event") == "chunk-landed"), None)
        if terminal and not landed:
            findings.append(Finding(
                "urlsession-completion-not-staged",
                "url-session-bridge",
                "A successful URLSession task completed without a staged download callback.",
                task_history[-2] if len(task_history) > 1 else None,
                terminal,
            ))

    for index, failure in enumerate(events):
        if failure.get("event") != "request-failed":
            continue
        message = str(failure.get("errorMessage") or "")
        model_id = failure.get("modelID", "unknown")
        prior = next((
            candidate for candidate in reversed(events[:index])
            if candidate.get("modelID") == failure.get("modelID")
        ), None)
        if "failed integrity checks" in message.lower():
            findings.append(Finding(
                "downloaded-file-integrity-rejected",
                "file-verification",
                f"{model_id} completed transfer but its staged file was rejected by integrity validation.",
                prior,
                failure,
            ))
        else:
            findings.append(Finding(
                "download-request-failed",
                "downloader",
                f"{model_id} ended with a typed downloader failure before installation.",
                prior,
                failure,
            ))

    for index, queued in enumerate(events):
        if queued.get("event") != "request-queued" or not queued.get("modelID"):
            continue
        queued_bytes = queued.get("durableBytes")
        following_snapshot = next((
            event for event in events[index + 1 :]
            if event.get("modelID") == queued.get("modelID")
            and event.get("event") == "snapshot-published"
            and event.get("phase") == "queued"
        ), None)
        if following_snapshot is not None and following_snapshot.get("durableBytes") != queued_bytes:
            findings.append(Finding(
                "queued-ledger-progress-mismatch",
                "coordinator",
                f"{queued.get('modelID')} queued with {queued_bytes} durable bytes but its first snapshot reported "
                f"{following_snapshot.get('durableBytes')}.",
                queued,
                following_snapshot,
            ))

    for model_id in {event.get("modelID") for event in events if event.get("modelID")}:
        model_events = [event for event in events if event.get("modelID") == model_id]
        last = model_events[-1]
        saturated_heartbeats = [
            event for event in model_events
            if event.get("event") == "heartbeat"
            and event.get("phase") in {"downloading", "retrying"}
            and isinstance(event.get("durableBytes"), int)
            and isinstance(event.get("totalBytes"), int)
            and event["totalBytes"] > 0
            and event["durableBytes"] >= event["totalBytes"]
            and event.get("targetAvailable") is not True
            and (event.get("taskCount") or 0) > 0
        ]
        if len(saturated_heartbeats) >= 2:
            first_time = datetime.fromisoformat(
                saturated_heartbeats[0]["capturedAtUTC"].replace("Z", "+00:00")
            )
            last_time = datetime.fromisoformat(
                saturated_heartbeats[-1]["capturedAtUTC"].replace("Z", "+00:00")
            )
            if (last_time - first_time).total_seconds() >= 300:
                findings.append(Finding(
                    "saturated-progress-with-live-task",
                    "progress-accounting",
                    f"{model_id} remained at the catalog total with a live transfer task for at least 300 seconds.",
                    saturated_heartbeats[0],
                    saturated_heartbeats[-1],
                ))
        if (
            last.get("expectedFileCount")
            and last.get("expectedFileCount") == last.get("verifiedFileCount")
            and last.get("ledgerStatus") in {"downloading", "verifying", "installing"}
            and not any(event.get("event") == "atomic-publication-completed" for event in model_events)
        ):
            findings.append(Finding(
                "verified-files-not-finalized",
                "download-finalization",
                f"{model_id} verified every expected file but never reached atomic publication.",
                next((event for event in reversed(model_events) if event.get("event") in {"file-verified", "progress"}), None),
                last,
            ))
        published = next((event for event in model_events if event.get("event") == "atomic-publication-completed"), None)
        installed_ledger = next((
            event for event in reversed(model_events)
            if event.get("ledgerStatus") == "installed"
            and event.get("event") in {"write", "snapshot-published", "atomic-publication-completed"}
        ), None)
        if published and not installed_ledger:
            findings.append(Finding("publication-without-installed-ledger", "ledger", f"{model_id} was published without an installed ledger.", published, model_events[-1]))
        model_observations = [obs for obs in observations if obs.get("modelID") == model_id]
        if installed_ledger and model_observations:
            installed_at = installed_ledger.get("capturedAtUTC", "")
            post_install_observations = [
                obs for obs in model_observations
                if obs.get("capturedAtUTC", "") >= installed_at
            ]
            ready = any(
                obs.get("status") == "Ready" or "Delete" in obs.get("actions", [])
                for obs in post_install_observations
            )
            if post_install_observations and not ready:
                findings.append(Finding(
                    "installed-not-ready-in-ui",
                    "view-model",
                    f"{model_id} is installed durably but a later UI observation never exposed Ready.",
                    installed_ledger,
                    post_install_observations[-1],
                ))
            elif not post_install_observations:
                findings.append(Finding(
                    "missing-post-install-ui-observation",
                    "harness",
                    f"{model_id} installed durably, but no later UI observation was collected.",
                    installed_ledger,
                    model_events[-1],
                ))
        delete = next((event for event in reversed(model_events) if event.get("event") == "delete-completed"), None)
        if delete and (delete.get("targetAvailable") is True or delete.get("stagingFileCount", 0) > 0 or delete.get("ledgerStatus") not in {None, "deleted"}):
            findings.append(Finding("false-delete-success", "deletion", f"{model_id} reported deletion before storage and ledger converged.", None, delete))

        claimed_index = next(
            (index for index in range(len(model_events) - 1, -1, -1)
             if model_events[index].get("event") == "parked-completion-claimed"),
            None,
        )
        if claimed_index is not None and not any(
            event.get("event") in {"file-verified", "atomic-publication-completed", "request-failed"}
            for event in model_events[claimed_index + 1 :]
        ):
            findings.append(Finding(
                "claimed-completion-not-resumed",
                "continuation-bridge",
                f"{model_id} claimed a parked completion but emitted no downstream verification or terminal event.",
                model_events[claimed_index],
                model_events[-1],
            ))

    previous_fraction: dict[str, float] = {}
    previous_raw: dict[str, int] = {}
    for observation in observations:
        model_id = observation.get("modelID", "unknown")
        expected = observation.get("expectedFraction")
        accessible = observation.get("accessibilityFraction")
        prior_fraction = previous_fraction.get(model_id)
        prior_raw = previous_raw.get(model_id)
        if isinstance(expected, (int, float)) and isinstance(accessible, (int, float)):
            if abs(expected - accessible) > 0.01:
                findings.append(Finding("accessibility-progress-disagrees", "progress-presentation", f"{model_id} byte and accessibility fractions disagree.", None, observation))
            if prior_fraction is not None and accessible + 1e-6 < prior_fraction:
                findings.append(Finding("ui-progress-regressed", "progress-presentation", f"{model_id} visible progress regressed.", None, observation))
        raw, total = observation.get("rawBytes"), observation.get("totalBytes")
        if isinstance(raw, int) and isinstance(accessible, (int, float)):
            if prior_raw is not None and prior_fraction is not None:
                if raw > prior_raw and accessible <= prior_fraction + 1e-6:
                    findings.append(Finding("ui-frozen-while-bytes-advance", "progress-presentation", f"{model_id} bytes advanced while the visible fraction stayed fixed.", None, observation))
                if raw == prior_raw and accessible > prior_fraction + 1e-6:
                    findings.append(Finding("ui-moved-without-bytes", "progress-presentation", f"{model_id} visible progress advanced without durable byte movement.", None, observation))
            previous_raw[model_id] = max(raw, prior_raw if prior_raw is not None else raw)
            previous_fraction[model_id] = max(accessible, prior_fraction if prior_fraction is not None else accessible)
        if isinstance(accessible, (int, float)) and accessible >= 0.999 and isinstance(raw, int) and isinstance(total, int) and raw < total:
            findings.append(Finding("premature-full-bar", "progress-presentation", f"{model_id} showed a full bar before transfer completion.", None, observation))
    if missing_observations:
        findings.append(Finding(
            "missing-ui-observations",
            "harness",
            "No structured model-row or progress observation was collected.",
        ))
    if test_execution_failed:
        findings.append(Finding(
            "xcuitest-failed",
            "harness",
            "The physical-device XCUITest execution failed; its diagnostic output cannot be summarized as PASS.",
        ))
    return findings


def timeline_markdown(events: list[dict[str, Any]], observations: list[dict[str, Any]], findings: list[Finding]) -> str:
    lines = ["# Model-management timeline", "", "| Time | Process/sequence | Layer | Event | Model | Phase | Bytes | Ledger |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for event in events:
        byte_text = ""
        if event.get("durableBytes") is not None:
            byte_text = f"{event.get('durableBytes')}/{event.get('totalBytes', '?')}"
        lines.append(
            f"| {event.get('capturedAtUTC', '')} | {event.get('processInstanceID', '')[:8]}/{event.get('sequence', '')} "
            f"| {event.get('layer', '')} | {event.get('event', '')} | {event.get('modelID', '')} "
            f"| {event.get('phase', '')} | {byte_text} | {event.get('ledgerStatus', '')} |"
        )
    lines += ["", "## UI observations", ""]
    for observation in observations:
        lines.append(f"- {observation.get('capturedAtUTC')}: {observation.get('modelID')} `{observation.get('milestone')}` — {observation.get('visibleText') or observation.get('status')}")
    lines += ["", "## Diagnosis", ""]
    lines.extend(f"- `{finding.code}` ({finding.subsystem}): {finding.message}" for finding in findings)
    if not findings:
        lines.append("- No inconsistency detected.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=pathlib.Path)
    parser.add_argument("--diagnostics", type=pathlib.Path)
    parser.add_argument("--xcodebuild-log", type=pathlib.Path)
    parser.add_argument("--attachments", type=pathlib.Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--scenario", choices=["diagnose", "queue", "acceptance", "soak", "recover"])
    parser.add_argument("--partition-prior-traces", action="store_true")
    args = parser.parse_args()

    if args.partition_prior_traces:
        if args.diagnostics is None:
            parser.error("--partition-prior-traces requires --diagnostics")
        print(json.dumps(partition_prior_trace_events(args.diagnostics, args.run_id), sort_keys=True))
        return 0
    if args.artifact_dir is None or args.scenario is None:
        parser.error("diagnosis requires --artifact-dir and --scenario")

    artifact_dir = args.artifact_dir
    artifact_dir.mkdir(parents=True, exist_ok=True)
    diagnostics = args.diagnostics or artifact_dir / "model-download-diagnostics"
    xcodebuild_log = args.xcodebuild_log or artifact_dir / "xcodebuild.log"
    observations = read_observations(xcodebuild_log)
    events = read_trace(diagnostics, args.run_id)
    findings = diagnose(
        events,
        observations,
        test_execution_failed=xcodebuild_failed(xcodebuild_log),
    )

    attachments = attachment_map(args.attachments or artifact_dir / "attachments")
    visual_rows: list[dict[str, Any]] = []
    visual_findings: list[Finding] = []
    for observation in observations:
        screenshot = observation.get("progressScreenshot")
        expected_fraction = observation.get("expectedFraction")
        accessibility_fraction = observation.get("accessibilityFraction")
        reference_fraction = (
            expected_fraction
            if isinstance(expected_fraction, (int, float))
            else accessibility_fraction
        )
        if not screenshot or not isinstance(reference_fraction, (int, float)):
            continue
        path = attachments.get(screenshot)
        if path is None or not path.is_file():
            visual_rows.append({"screenshot": screenshot, "status": "missing"})
            visual_findings.append(Finding("missing-progress-screenshot", "visual-evidence", f"Missing exported progress screenshot {screenshot}."))
            continue
        try:
            measurement = analyze_bar(path, reference_fraction)
        except (OSError, ValueError, zlib.error) as error:
            measurement = {"screenshot": screenshot, "status": "unreadable", "error": str(error)}
            visual_findings.append(Finding("unreadable-progress-screenshot", "visual-evidence", f"Could not analyze {screenshot}: {error}"))
        else:
            measurement["screenshot"] = screenshot
            measurement["modelID"] = observation.get("modelID")
            measurement["milestone"] = observation.get("milestone")
            measurement["expectedFraction"] = expected_fraction
            measurement["accessibilityFraction"] = accessibility_fraction
            if not measurement["passesFractionTolerance"]:
                visual_findings.append(Finding("rendered-fill-disagrees", "progress-rendering", f"{screenshot} differs from the reported fraction by more than five points."))
            if not measurement["passesContrast"]:
                visual_findings.append(Finding("progress-contrast-low", "progress-rendering", f"{screenshot} has under 3:1 fill/track contrast."))
            if (
                isinstance(expected_fraction, (int, float))
                and expected_fraction < 1
                and measurement["measuredFillFraction"] >= 0.995
            ):
                visual_findings.append(Finding(
                    "rendered-premature-full-bar",
                    "progress-rendering",
                    f"{screenshot} appears full before the durable byte transfer completed.",
                ))
        visual_rows.append(measurement)
    missing_milestones = missing_progress_milestones(observations, args.scenario)
    if missing_milestones:
        visual_findings.append(Finding(
            "missing-progress-milestones",
            "visual-evidence",
            "Missing required Custom progress observations: " + ", ".join(missing_milestones),
        ))
    invalid_milestones = invalid_progress_milestone_ranges(observations, args.scenario)
    if invalid_milestones:
        visual_findings.append(Finding(
            "progress-milestone-out-of-range",
            "visual-evidence",
            "Progress observations were captured outside their real-byte milestone band: "
            + ", ".join(invalid_milestones),
        ))
    sizes = {(row.get("width"), row.get("height")) for row in visual_rows if row.get("width")}
    if len(sizes) > 1:
        visual_findings.append(Finding("progress-frame-unstable", "progress-rendering", "Progress screenshot dimensions changed across transfer samples."))
    previous_rendered: dict[str, float] = {}
    for row in visual_rows:
        model_id = row.get("modelID")
        measured = row.get("measuredFillFraction")
        if not model_id or not isinstance(measured, (int, float)):
            continue
        if measured + 0.01 < previous_rendered.get(model_id, 0):
            visual_findings.append(Finding(
                "rendered-fill-regressed",
                "progress-rendering",
                f"{model_id} rendered fill moved backward across captured milestones.",
            ))
        previous_rendered[model_id] = max(measured, previous_rendered.get(model_id, 0))
    findings.extend(visual_findings)
    contact_sheet_created = make_contact_sheet(
        observations,
        attachments,
        artifact_dir / "model-management-contact-sheet.png",
    )

    diagnosis = {
        "schemaVersion": 1,
        "runID": args.run_id,
        "scenario": args.scenario,
        "capturedAtUTC": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "eventCount": len(events),
        "observationCount": len(observations),
        "result": "passed" if not findings else "diagnosedFailure",
        "firstInconsistentLayer": findings[0].subsystem if findings else None,
        "findings": [finding.json() for finding in findings],
    }
    write_json(artifact_dir / "model-management-diagnosis.json", diagnosis)
    write_json(artifact_dir / "model-management-summary.json", {
        "schemaVersion": 1,
        "runID": args.run_id,
        "scenario": args.scenario,
        "result": diagnosis["result"],
        "eventCount": len(events),
        "observationCount": len(observations),
        "findingCodes": [finding.code for finding in findings],
    })
    latest_filesystem_state: dict[str, dict[str, Any]] = {}
    for event in events:
        model_id = event.get("modelID")
        if not model_id or not any(
            event.get(field) is not None
            for field in ("stagingFileCount", "stagingBytes", "targetAvailable", "taskCount", "ledgerStatus")
        ):
            continue
        latest_filesystem_state[model_id] = {
            "capturedAtUTC": event.get("capturedAtUTC"),
            "stagingFileCount": event.get("stagingFileCount"),
            "stagingBytes": event.get("stagingBytes"),
            "targetAvailable": event.get("targetAvailable"),
            "activeTaskCount": event.get("taskCount"),
            "ledgerStatus": event.get("ledgerStatus"),
            "sourceEvent": event.get("event"),
            "sourceArtifact": event.get("_artifact"),
        }
    write_json(artifact_dir / "model-management-filesystem-inventory.json", {
        "schemaVersion": 1,
        "runID": args.run_id,
        "privacyBoundary": "Counts, sizes, terminal availability, and relative trace references only.",
        "models": latest_filesystem_state,
    })
    write_json(artifact_dir / "progress-visual-summary.json", {
        "schemaVersion": 1,
        "runID": args.run_id,
        "measurements": visual_rows,
        "findingCodes": [finding.code for finding in visual_findings],
        "contactSheet": "model-management-contact-sheet.png" if contact_sheet_created else None,
    })
    (artifact_dir / "model-management-timeline.md").write_text(
        timeline_markdown(events, observations, findings), encoding="utf-8"
    )

    # A diagnostic scenario succeeds as a harness run when it captured enough evidence to assign
    # the failure. Acceptance-like scenarios fail closed on every diagnosed inconsistency.
    if args.scenario == "diagnose":
        return 0 if events and observations else 1
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
