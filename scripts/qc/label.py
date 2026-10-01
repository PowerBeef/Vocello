"""The maintainer's labels: sample a batch, serve the listening page, export a summary.

`sample` draws a batch from qc-takes runs: per language, 60% a stratified
systematic sample of every take (language x mode x cell x voice) and 40% a
simple random sample of the enrichment list, with each take's inclusion
probability recorded. Script families split 60/40 into train and held-out by a
fixed hash, so a script keeps its side in every batch. About 10% of the takes
come back later in the order under a second token, for intra-rater agreement.

`serve` runs one local page on 127.0.0.1: one take at a time, opaque tokens
only (never a path, mode, voice, score or enrichment reason), and appends each
label to `build/private/qc/labels/<batch>.jsonl`; the latest line per token wins.
"""

from __future__ import annotations

import http.server
import json
import math
import random
import re
import socketserver
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from qc import store
from qc.store import Layout

BATCH_SCHEMA = "vocello.qc.batch/1"
TOKEN_RE = re.compile(r"^[0-9a-f]{16}$")
BATCH_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DEFAULT_SIZE = 96
DEFAULT_LANGUAGES = ("french", "english")
ENRICH_FRACTION = 0.4
TRAIN_FRACTION = 0.6
MAX_BODY = 64 * 1024


# --- protocol -----------------------------------------------------------------

def load_protocol(layout: Layout = Layout()) -> dict[str, Any]:
    protocol = store.read_json(layout.protocol)
    ids = [item["id"] for item in protocol["classes"]]
    if len(ids) != len(set(ids)) or protocol["severities"][0] != "none":
        raise ValueError("config/qc/protocol.json: duplicate classes or severities not led by none")
    return protocol


def class_ids(protocol: dict[str, Any], *, acoustic_only: bool = False) -> list[str]:
    return [item["id"] for item in protocol["classes"] if not (acoustic_only and item.get("linguistic"))]


# --- sampling -----------------------------------------------------------------

def split_for_family(family: str) -> str:
    """`train` or `heldout`, fixed per script family across every batch."""

    bucket = int(store.sha256_text(f"vocello.qc.split/1:{family}")[:8], 16) / 2**32
    return "train" if bucket < TRAIN_FRACTION else "heldout"


def stratum(take: dict[str, Any]) -> str:
    return "|".join(str(take.get(key)) for key in ("language", "mode", "cell", "voice"))


def label_token(batch: str, seed: int, take_token: str, copy: int) -> str:
    return store.sha256_text(f"vocello.qc.label/1:{batch}:{seed}:{take_token}:{copy}")[:16]


def load_enrichment(path: Path | str | None, sources_by_run: dict[str, str]) -> dict[tuple[str | None, str], dict[str, Any]]:
    """Enrichment entries keyed by (source or None for every run, takeID).

    Accepts `{"<runTag>:<takeID>": {"run": "<run dir>", "takeID": ..., "reasons": [...]}}`,
    a list of such objects, or `{"<takeID>": "<reason>"}`. `"certain": true`
    includes a take with probability 1.
    """

    if not path:
        return {}
    document = store.read_json(path)
    entries: list[dict[str, Any]] = []
    if isinstance(document, dict) and isinstance(document.get("takes"), list):
        document = document["takes"]
    if isinstance(document, list):
        entries = [dict(item) for item in document]
    elif isinstance(document, dict):
        for key, value in document.items():
            if isinstance(value, dict):
                entry = dict(value)
                entry.setdefault("takeID", key.split(":", 1)[-1])
            else:
                entry = {"takeID": key, "reasons": value if isinstance(value, list) else [value]}
            entries.append(entry)
    result: dict[tuple[str | None, str], dict[str, Any]] = {}
    for entry in entries:
        reasons = entry.get("reasons", entry.get("reason", []))
        reasons = [reasons] if isinstance(reasons, str) else list(reasons)
        source = None
        if entry.get("run"):
            source = _resolve_source(str(entry["run"]), sources_by_run)
            if source is None:
                continue
        key = (source, entry["takeID"])
        merged = result.setdefault(key, {"reasons": [], "certain": False})
        merged["reasons"].extend(reason for reason in reasons if reason not in merged["reasons"])
        merged["certain"] = merged["certain"] or bool(entry.get("certain"))
    return result


def _resolve_source(run: str, sources_by_run: dict[str, str]) -> str | None:
    candidate = Path(run)
    if candidate.exists() and str(candidate.resolve()) in sources_by_run:
        return sources_by_run[str(candidate.resolve())]
    for run_dir, source in sources_by_run.items():
        if run in (source, Path(run_dir).name) or Path(run).name in (source, Path(run_dir).name):
            return source
    return None


def _source_of(take: dict[str, Any], sources_by_token: dict[str, str]) -> str:
    return sources_by_token[take["token"]]


def _systematic(population: list[dict[str, Any]], count: int, rng: random.Random) -> list[dict[str, Any]]:
    """Equal-probability systematic sample over a stratum-sorted list (implicitly stratified)."""

    if count <= 0:
        return []
    if count >= len(population):
        return list(population)
    by_stratum: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for take in population:
        by_stratum[stratum(take)].append(take)
    ordered: list[dict[str, Any]] = []
    for key in sorted(by_stratum):
        members = sorted(by_stratum[key], key=lambda take: take["token"])
        rng.shuffle(members)
        ordered.extend(members)
    interval = len(ordered) / count
    start = rng.uniform(0, interval)
    return [ordered[min(len(ordered) - 1, math.floor(start + index * interval))] for index in range(count)]


def sample_batch(
    manifests: list[dict[str, Any]],
    *,
    name: str,
    size: int = DEFAULT_SIZE,
    languages: Iterable[str] = DEFAULT_LANGUAGES,
    enrichment: dict[tuple[str | None, str], dict[str, Any]] | None = None,
    blind: float = 0.1,
    seed: int = 0,
) -> dict[str, Any]:
    if not BATCH_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid batch name: {name!r}")
    languages = [store.normalize_language(language) for language in languages]
    enrichment = enrichment or {}
    rng = random.Random(seed)
    sources_by_token: dict[str, str] = {}
    takes: list[dict[str, Any]] = []
    for manifest in manifests:
        for take in manifest["takes"]:
            if take["token"] not in sources_by_token:
                sources_by_token[take["token"]] = manifest["source"]
                takes.append(take)

    def enrichment_for(take: dict[str, Any]) -> dict[str, Any] | None:
        return (enrichment.get((_source_of(take, sources_by_token), take["takeID"]))
                or enrichment.get((None, take["takeID"])))

    selected: dict[str, dict[str, Any]] = {}
    for index, language in enumerate(languages):
        quota = size // len(languages) + (1 if index < size % len(languages) else 0)
        population = sorted((take for take in takes if take.get("language") == language), key=lambda t: t["token"])
        if not population:
            continue
        enriched = [take for take in population if enrichment_for(take)]
        certain = [take for take in enriched if enrichment_for(take)["certain"]]
        optional = [take for take in enriched if not enrichment_for(take)["certain"]]
        enrich_count = max(len(certain), min(round(ENRICH_FRACTION * quota), len(enriched)))
        draw = min(len(optional), enrich_count - len(certain))
        enrich_pick = certain + (rng.sample(optional, draw) if draw > 0 else [])
        uniform_count = max(0, quota - enrich_count)
        uniform_pick = _systematic(population, uniform_count, rng)
        p_uniform = min(1.0, uniform_count / len(population))
        p_enrich = draw / len(optional) if optional else 0.0
        enrich_tokens = {take["token"] for take in enrich_pick}
        for take in uniform_pick + enrich_pick:
            if take["token"] in selected:
                continue
            info = enrichment_for(take)
            if info and info["certain"]:
                probability = 1.0
            elif info:
                probability = 1 - (1 - p_uniform) * (1 - p_enrich)
            else:
                probability = p_uniform
            selected[take["token"]] = {
                "take": take, "inclusionProbability": round(probability, 6),
                "enriched": take["token"] in enrich_tokens, "reasons": list(info["reasons"]) if info else [],
            }

    primaries = sorted(selected.values(), key=lambda item: item["take"]["token"])
    rng.shuffle(primaries)
    order: list[dict[str, Any]] = []
    for entry in primaries:
        take = entry["take"]
        order.append({
            "token": label_token(name, seed, take["token"], 0), "takeToken": take["token"], "repeatOf": None,
            "split": split_for_family(str(take.get("family") or take["takeID"])),
            "inclusionProbability": entry["inclusionProbability"], "stratum": stratum(take),
            "enriched": entry["enriched"], "reasons": entry["reasons"],
        })
    repeat_count = round(blind * len(order))
    if repeat_count:
        eligible = order[: max(1, math.ceil(len(order) * 0.75))]
        gap = max(5, len(order) // 4)
        for original in rng.sample(eligible, min(repeat_count, len(eligible))):
            position = order.index(original)
            low = min(position + gap, len(order))
            repeat = dict(original, token=label_token(name, seed, original["takeToken"], 1),
                          repeatOf=original["token"])
            order.insert(rng.randint(low, len(order)), repeat)
    for position, item in enumerate(order):
        item["order"] = position
    return {
        "schema": BATCH_SCHEMA, "batch": name, "kind": "sample", "createdAt": utc_now(),
        "params": {"size": size, "languages": languages, "blind": blind, "seed": seed,
                   "enrichFraction": ENRICH_FRACTION, "trainFraction": TRAIN_FRACTION,
                   "sources": sorted({manifest["source"] for manifest in manifests})},
        "items": order,
        "takes": {entry["take"]["token"]: entry["take"] for entry in primaries},
    }


def batch_path(layout: Layout, name: str) -> Path:
    if not BATCH_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid batch name: {name!r}")
    return layout.batches / f"{name}.json"


def labels_path(layout: Layout, name: str) -> Path:
    if not BATCH_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid batch name: {name!r}")
    return layout.labels / f"{name}.jsonl"


def write_batch(layout: Layout, batch: dict[str, Any], *, overwrite: bool = False) -> Path:
    path = batch_path(layout, batch["batch"])
    if path.exists() and not overwrite:
        raise FileExistsError(f"batch {batch['batch']} exists; choose another name")
    store.write_json_atomic(path, batch)
    return path


def load_batch(layout: Layout, name: str) -> dict[str, Any]:
    batch = store.read_json(batch_path(layout, name))
    if batch.get("schema") != BATCH_SCHEMA:
        raise ValueError(f"not a {BATCH_SCHEMA} file: {name}")
    return batch


def sample_command(layout: Layout, runs: list[str], *, name: str, size: int, languages: list[str],
                   enrich_file: str | None, blind: float, seed: int, overwrite: bool = False) -> dict[str, Any]:
    manifests = []
    sources_by_run: dict[str, str] = {}
    for run in runs:
        manifest = store.load_takes(run)
        manifests.append(manifest)
        sources_by_run[str(Path(run).resolve())] = manifest["source"]
    enrichment = load_enrichment(enrich_file, sources_by_run)
    batch = sample_batch(manifests, name=name, size=size, languages=languages, enrichment=enrichment,
                         blind=blind, seed=seed)
    write_batch(layout, batch, overwrite=overwrite)
    return summarize_batch(batch)


def summarize_batch(batch: dict[str, Any]) -> dict[str, Any]:
    items = batch["items"]
    takes = batch["takes"]
    return {
        "batch": batch["batch"], "items": len(items),
        "takes": sum(1 for item in items if item["repeatOf"] is None),
        "repeats": sum(1 for item in items if item["repeatOf"] is not None),
        "enriched": sum(1 for item in items if item["repeatOf"] is None and item["enriched"]),
        "languages": dict(Counter(takes[item["takeToken"]]["language"] for item in items if item["repeatOf"] is None)),
        "splits": dict(Counter(item["split"] for item in items if item["repeatOf"] is None)),
    }


# --- labels ---------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def latest_labels(layout: Layout, name: str) -> dict[str, dict[str, Any]]:
    """The latest label line per token (re-labelling appends; the last line wins)."""

    latest: dict[str, dict[str, Any]] = {}
    for row in store.read_jsonl(labels_path(layout, name)):
        if isinstance(row, dict) and row.get("token"):
            latest[row["token"]] = row
    return latest


def validate_label(payload: Any, *, protocol: dict[str, Any], acoustic_only: bool) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("the label must be an object")
    verdict = payload.get("verdict")
    if verdict not in protocol["verdicts"]:
        raise ValueError("a verdict is required")
    allowed = set(class_ids(protocol, acoustic_only=acoustic_only))
    classes_in = payload.get("classes") or {}
    if not isinstance(classes_in, dict):
        raise ValueError("classes must be an object")
    classes: dict[str, dict[str, Any]] = {}
    for class_id, value in classes_in.items():
        if class_id not in allowed:
            raise ValueError(f"unknown class: {class_id}")
        if not isinstance(value, dict) or value.get("severity") not in protocol["severities"]:
            raise ValueError(f"{class_id}: a severity is required")
        if value["severity"] == "none":
            continue
        times = []
        for key in ("start", "end"):
            moment = value.get(key)
            if moment is not None and (not isinstance(moment, (int, float)) or isinstance(moment, bool)
                                       or moment < 0 or not math.isfinite(moment)):
                raise ValueError(f"{class_id}: {key} must be a non-negative number of seconds")
            times.append(None if moment is None else round(float(moment), 3))
        start, end = times
        if start is not None and end is not None and end < start:
            start, end = end, start
        classes[class_id] = {"severity": value["severity"], "start": start, "end": end}
    return {"classes": classes, "verdict": verdict}


def defect_present(label: dict[str, Any], class_id: str | None = None) -> bool:
    classes = label.get("classes") or {}
    if class_id is None:
        return any(value.get("severity", "none") != "none" for value in classes.values())
    return classes.get(class_id, {}).get("severity", "none") != "none"


def cohen_kappa(pairs: list[tuple[Any, Any]]) -> float | None:
    """Cohen's kappa of paired ratings; None when undefined (no pairs or no variation)."""

    if not pairs:
        return None
    count = len(pairs)
    observed = sum(1 for left, right in pairs if left == right) / count
    left_counts = Counter(left for left, _ in pairs)
    right_counts = Counter(right for _, right in pairs)
    expected = sum(left_counts[key] * right_counts.get(key, 0) for key in left_counts) / count**2
    if expected >= 1:
        return None
    return round((observed - expected) / (1 - expected), 4)


def export_summary(layout: Layout, name: str) -> dict[str, Any]:
    batch = load_batch(layout, name)
    protocol = load_protocol(layout)
    labels = latest_labels(layout, name)
    takes = batch["takes"]
    primaries = [item for item in batch["items"] if item["repeatOf"] is None]
    verdicts: Counter[str] = Counter()
    classes: dict[str, Counter[str]] = {class_id: Counter() for class_id in class_ids(protocol)}
    by_language: dict[str, dict[str, Any]] = {}
    labelled = 0
    for item in primaries:
        label = labels.get(item["token"])
        if not label:
            continue
        labelled += 1
        language = takes[item["takeToken"]].get("language") or "unknown"
        bucket = by_language.setdefault(language, {"labelled": 0, "verdicts": Counter(), "classes": Counter()})
        bucket["labelled"] += 1
        verdicts[label["verdict"]] += 1
        bucket["verdicts"][label["verdict"]] += 1
        for class_id, value in (label.get("classes") or {}).items():
            classes.setdefault(class_id, Counter())[value["severity"]] += 1
            bucket["classes"][class_id] += 1
    agreement = repeat_agreement(batch, labels, protocol)
    return {
        "batch": name, "items": len(batch["items"]), "takes": len(primaries), "labelled": labelled,
        "verdicts": dict(verdicts),
        "classes": {class_id: dict(counts) for class_id, counts in classes.items()},
        "languages": {language: {"labelled": value["labelled"], "verdicts": dict(value["verdicts"]),
                                 "classes": dict(value["classes"])} for language, value in sorted(by_language.items())},
        "intraRater": agreement,
    }


def repeat_agreement(batch: dict[str, Any], labels: dict[str, dict[str, Any]], protocol: dict[str, Any]) -> dict[str, Any]:
    pairs = []
    for item in batch["items"]:
        if item["repeatOf"] and item["token"] in labels and item["repeatOf"] in labels:
            pairs.append((labels[item["repeatOf"]], labels[item["token"]]))
    per_class = {}
    for class_id in class_ids(protocol):
        per_class[class_id] = cohen_kappa([(defect_present(a, class_id), defect_present(b, class_id)) for a, b in pairs])
    return {
        "pairs": len(pairs),
        "verdictKappa": cohen_kappa([(a["verdict"], b["verdict"]) for a, b in pairs]),
        "anyDefectKappa": cohen_kappa([(defect_present(a), defect_present(b)) for a, b in pairs]),
        "verdictAgreement": round(sum(a["verdict"] == b["verdict"] for a, b in pairs) / len(pairs), 4) if pairs else None,
        "classKappa": per_class,
    }


def labelled_takes(layout: Layout, name: str) -> list[dict[str, Any]]:
    """Each labelled primary item of a batch with its take and latest label (fit and eval read these)."""

    batch = load_batch(layout, name)
    labels = latest_labels(layout, name)
    rows = []
    for item in batch["items"]:
        if item["repeatOf"] is None and item["token"] in labels:
            rows.append({"item": item, "take": batch["takes"][item["takeToken"]], "label": labels[item["token"]]})
    return rows


# --- serve ------------------------------------------------------------------------

class LabelServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, layout: Layout, batch: dict[str, Any], *, port: int = 8765,
                 acoustic_only_languages: Iterable[str] = ()) -> None:
        self.layout = layout
        self.batch = batch
        self.protocol = load_protocol(layout)
        self.acoustic_only = {store.normalize_language(language) for language in acoustic_only_languages}
        self.items = {item["token"]: item for item in batch["items"]}
        self.labels_file = labels_path(layout, batch["batch"])
        self.write_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), LabelHandler)

    def server_bind(self) -> None:
        # HTTPServer.server_bind resolves the host name (socket.getfqdn), which can
        # stall for half a minute on a Mac; the page needs only the bound address.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def take_for(self, token: str) -> dict[str, Any] | None:
        if not TOKEN_RE.fullmatch(token) or token not in self.items:
            return None
        return self.batch["takes"].get(self.items[token]["takeToken"])

    def item_view(self, item: dict[str, Any]) -> dict[str, Any]:
        take = self.batch["takes"][item["takeToken"]]
        language = take.get("language") or "unknown"
        acoustic_only = language in self.acoustic_only
        return {"token": item["token"], "language": language, "acousticOnly": acoustic_only,
                "text": None if acoustic_only else take.get("text"), "hasReference": bool(take.get("reference"))}

    def state(self) -> dict[str, Any]:
        labels = latest_labels(self.layout, self.batch["batch"])
        views = [self.item_view(item) for item in self.batch["items"]]
        return {
            "batch": self.batch["batch"], "total": len(views), "items": views,
            "classes": [{"id": c["id"], "label": c["label"], "linguistic": bool(c.get("linguistic"))}
                        for c in self.protocol["classes"]],
            "severities": [s for s in self.protocol["severities"] if s != "none"],
            "verdicts": self.protocol["verdicts"],
            "labels": {token: {"classes": row.get("classes", {}), "verdict": row.get("verdict")}
                       for token, row in labels.items() if token in self.items},
        }

    def save(self, payload: Any) -> int:
        if not isinstance(payload, dict) or not isinstance(payload.get("token"), str):
            raise ValueError("a token is required")
        token = payload["token"]
        if self.take_for(token) is None:
            raise ValueError("unknown token")
        acoustic_only = self.item_view(self.items[token])["acousticOnly"]
        label = validate_label(payload, protocol=self.protocol, acoustic_only=acoustic_only)
        row = {"token": token, "batch": self.batch["batch"], "rater": self.protocol.get("rater", "maintainer"),
               "classes": label["classes"], "verdict": label["verdict"], "acousticOnly": acoustic_only,
               "labelledAt": utc_now()}
        with self.write_lock:
            store.append_jsonl(self.labels_file, row)
            return len(latest_labels(self.layout, self.batch["batch"]))


class LabelHandler(http.server.BaseHTTPRequestHandler):
    server: LabelServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 (stdlib signature)
        return  # no request log: URLs carry tokens only, but keep the terminal quiet

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, value: Any) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _not_found(self) -> None:
        self._json(404, {"error": "not found"})

    def do_HEAD(self) -> None:  # noqa: N802 (stdlib API)
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802 (stdlib API)
        if not self._host_ok():
            self._json(403, {"error": "forbidden host"})
            return
        path = urlsplit(self.path).path
        if path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8",
                       {"Content-Security-Policy": "default-src 'self'; script-src 'unsafe-inline'; "
                                                   "style-src 'unsafe-inline'; media-src 'self'"})
            return
        if path == "/api/state":
            self._json(200, self.server.state())
            return
        if path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return
        parts = path.strip("/").split("/")
        if len(parts) == 2 and parts[0] in ("audio", "reference"):
            take = self.server.take_for(parts[1])
            if take is None:
                self._not_found()
                return
            source = take.get("audio") if parts[0] == "audio" else take.get("reference")
            if not source or not Path(source).is_file():
                self._not_found()
                return
            self._stream(Path(source))
            return
        self._not_found()

    def _stream(self, path: Path) -> None:
        size = path.stat().st_size
        start, end = 0, size - 1
        status = 200
        header = self.headers.get("Range")
        if header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
            if not match or (not match.group(1) and not match.group(2)):
                self._send(416, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
                return
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
            else:
                start = max(0, size - int(match.group(2)))
            end = min(end, size - 1)
            if start > end:
                self._send(416, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
                return
            status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(1 << 16, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)

    def do_POST(self) -> None:  # noqa: N802 (stdlib API)
        if not self._host_ok():
            self._json(403, {"error": "forbidden host"})
            return
        if urlsplit(self.path).path != "/api/label":
            self._not_found()
            return
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            self._json(415, {"error": "application/json required"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length <= 0 or length > MAX_BODY:
            self._json(413, {"error": "bad body length"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
            labelled = self.server.save(payload)
        except (ValueError, json.JSONDecodeError) as error:
            self._json(400, {"error": str(error)})
            return
        self._json(200, {"ok": True, "labelled": labelled})


def serve(layout: Layout, name: str, *, port: int = 8765, acoustic_only_languages: Iterable[str] = ()) -> None:
    server = LabelServer(layout, load_batch(layout, name), port=port, acoustic_only_languages=acoustic_only_languages)
    host, bound = server.server_address[:2]
    print(f"qc label: batch {name}, {len(server.items)} items: http://{host}:{bound}/ (Ctrl-C stops)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vocello QC labels</title>
<style>
:root{--bg:#fafaf8;--fg:#1d1d1b;--muted:#6b6b66;--line:#dcdcd6;--accent:#2d5bd7;--ok:#1f7a3a;--bad:#b3261e;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ececea;--muted:#a3a39d;--line:#34342f;--accent:#7fa2ff;--ok:#6fd28c;--bad:#ff8a80;--card:#1f1f1d}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,system-ui,sans-serif}
main{max-width:760px;margin:0 auto;padding:16px}
header{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:12px}
h1{font-size:17px;margin:0}.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:12px}
audio{width:100%}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px}
button{font:inherit;padding:6px 12px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
button.on{border-color:var(--accent);color:var(--accent)}button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.script{font-size:18px;margin:6px 0 0}.cls{display:grid;grid-template-columns:28px 1fr auto;gap:6px;align-items:center;padding:6px 0;border-top:1px solid var(--line)}
.cls:first-child{border-top:0}.cls .key{color:var(--muted);font-size:12px;text-align:center}.cls .detail{grid-column:2/4;display:none;gap:10px;flex-wrap:wrap;align-items:center}
.cls.checked .detail{display:flex}.sev label{margin-right:8px}.verdicts label{margin-right:16px}
.saved{color:var(--ok)}.error{color:var(--bad)}kbd{font:12px ui-monospace,monospace;border:1px solid var(--line);border-radius:4px;padding:0 4px}
</style></head><body><main>
<header><h1>Vocello QC labels <span class="muted" id="batch"></span></h1><div><span id="progress"></span> <span class="muted" id="eta"></span></div></header>
<div class="card">
  <div class="row" style="justify-content:space-between;margin-top:0"><strong id="position"></strong><span class="muted" id="language"></span></div>
  <audio id="take" controls preload="auto"></audio>
  <div class="row"><button id="loop">Loop</button><button id="slow">0.5&times;</button><button id="replay">Replay</button><span class="muted" id="status"></span></div>
  <p class="script" id="script"></p>
  <div id="refbox" style="display:none;margin-top:10px"><div class="muted">Reference clip</div><audio id="ref" controls preload="none"></audio></div>
</div>
<div class="card" id="classes"></div>
<div class="card verdicts" id="verdicts"></div>
<div class="row"><button id="prev">&larr; Previous</button><button id="next">Next &rarr;</button><button id="unlabelled">Next unlabelled</button><button class="primary" id="save">Save &amp; next (Enter)</button><span id="message"></span></div>
<p class="muted" style="font-size:13px"><kbd>Space</kbd> play/pause &middot; <kbd>a</kbd> acceptable, save &amp; next &middot; <kbd>o</kbd> objectionable &middot; <kbd>u</kbd> uncertain &middot; <kbd>1</kbd>&ndash;<kbd>0</kbd> toggle a class &middot; <kbd>Enter</kbd> save &amp; next &middot; <kbd>l</kbd> loop &middot; <kbd>s</kbd> 0.5&times; &middot; <kbd>&larr;</kbd>/<kbd>&rarr;</kbd> previous/next</p>
</main>
<script>
"use strict";
const $ = (id) => document.getElementById(id);
let state = null, index = 0, draft = null, shownAt = Date.now(), durations = [];
const audio = $("take"), ref = $("ref");

function visibleClasses(item){ return state.classes.filter(c => !(item.acousticOnly && c.linguistic)); }
function labelledCount(){ return Object.keys(state.labels).length; }
function fmtTime(s){ if(!isFinite(s)) return ""; const m = Math.round(s/60); return m < 1 ? "under a minute left" : `about ${m} min left`; }

function updateProgress(){
  const done = labelledCount(), total = state.total;
  $("progress").textContent = `${done} / ${total} labelled`;
  const recent = durations.slice(-20);
  const per = recent.length ? recent.reduce((a,b)=>a+b,0)/recent.length : 15;
  $("eta").textContent = done >= total ? "done" : fmtTime((total - done) * per);
}

function render(){
  const item = state.items[index];
  const saved = state.labels[item.token];
  draft = saved ? JSON.parse(JSON.stringify(saved)) : {classes:{}, verdict:null};
  $("position").textContent = `Take ${index + 1} of ${state.total}`;
  $("language").textContent = item.language + (item.acousticOnly ? " (acoustic only)" : "");
  $("script").textContent = item.acousticOnly ? "" : (item.text || "");
  $("status").textContent = saved ? "labelled" : "";
  $("status").className = saved ? "saved" : "muted";
  audio.src = `/audio/${item.token}`;
  audio.playbackRate = $("slow").classList.contains("on") ? 0.5 : 1;
  audio.loop = $("loop").classList.contains("on");
  $("refbox").style.display = item.hasReference ? "" : "none";
  ref.removeAttribute("src");
  if (item.hasReference) ref.src = `/reference/${item.token}`;
  const box = $("classes"); box.innerHTML = "";
  visibleClasses(item).forEach((c, i) => {
    const key = i < 9 ? String(i + 1) : (i === 9 ? "0" : "");
    const entry = draft.classes[c.id];
    const div = document.createElement("div");
    div.className = "cls" + (entry ? " checked" : ""); div.dataset.id = c.id;
    div.innerHTML = `<span class="key">${key}</span><label><input type="checkbox" ${entry ? "checked" : ""}> ${c.label}</label><span></span>
      <div class="detail"><span class="sev">${state.severities.map(s => `<label><input type="radio" name="sev-${c.id}" value="${s}" ${entry && entry.severity === s ? "checked" : ""}> ${s}</label>`).join("")}</span>
      <button data-mark="start">Start at playhead</button><button data-mark="end">End at playhead</button><span class="muted times"></span></div>`;
    div.querySelector("input[type=checkbox]").addEventListener("change", (e) => toggleClass(c.id, e.target.checked));
    div.querySelectorAll(".sev input").forEach(r => r.addEventListener("change", () => { ensure(c.id).severity = r.value; }));
    div.querySelectorAll("button[data-mark]").forEach(b => b.addEventListener("click", () => mark(c.id, b.dataset.mark)));
    box.appendChild(div); showTimes(c.id);
  });
  $("verdicts").innerHTML = "<strong>Overall</strong> " + state.verdicts.map(v =>
    `<label><input type="radio" name="verdict" value="${v}" ${draft.verdict === v ? "checked" : ""}> ${v}</label>`).join("");
  document.querySelectorAll("input[name=verdict]").forEach(r => r.addEventListener("change", () => { draft.verdict = r.value; }));
  $("message").textContent = "";
  updateProgress();
  shownAt = Date.now();
  audio.play().catch(() => { $("status").textContent = "press Space to play"; });
}

function ensure(id){ if(!draft.classes[id]) draft.classes[id] = {severity:"moderate", start:null, end:null}; return draft.classes[id]; }
function toggleClass(id, on){
  const div = document.querySelector(`.cls[data-id="${id}"]`);
  if (on) { ensure(id); } else { delete draft.classes[id]; }
  div.classList.toggle("checked", on);
  div.querySelector("input[type=checkbox]").checked = on;
  div.querySelectorAll(".sev input").forEach(r => { r.checked = on && draft.classes[id].severity === r.value; });
  showTimes(id);
}
function mark(id, which){ ensure(id)[which] = Math.round(audio.currentTime * 1000) / 1000; toggleClass(id, true); }
function showTimes(id){
  const div = document.querySelector(`.cls[data-id="${id}"]`); if (!div) return;
  const e = draft.classes[id];
  div.querySelector(".times").textContent = e && (e.start !== null || e.end !== null) ? `${e.start ?? "?"} s to ${e.end ?? "?"} s` : "";
}
function setVerdict(v){ draft.verdict = v; document.querySelectorAll("input[name=verdict]").forEach(r => { r.checked = r.value === v; }); }

async function save(){
  const item = state.items[index];
  if (!draft.verdict) { $("message").textContent = "choose an overall verdict"; $("message").className = "error"; return false; }
  const body = {token: item.token, verdict: draft.verdict, classes: draft.classes};
  const res = await fetch("/api/label", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
  const out = await res.json();
  if (!res.ok) { $("message").textContent = out.error || "not saved"; $("message").className = "error"; return false; }
  state.labels[item.token] = {classes: JSON.parse(JSON.stringify(draft.classes)), verdict: draft.verdict};
  durations.push(Math.min(120, (Date.now() - shownAt) / 1000));
  return true;
}
async function saveNext(){ if (await save()) go(index + 1); }
function go(i){ if (i < 0 || i >= state.total) { updateProgress(); return; } audio.pause(); ref.pause(); index = i; render(); }
function nextUnlabelled(){
  for (let k = 1; k <= state.total; k++) { const i = (index + k) % state.total; if (!state.labels[state.items[i].token]) { go(i); return; } }
}

$("loop").onclick = () => { $("loop").classList.toggle("on"); audio.loop = $("loop").classList.contains("on"); };
$("slow").onclick = () => { $("slow").classList.toggle("on"); audio.playbackRate = $("slow").classList.contains("on") ? 0.5 : 1; };
$("replay").onclick = () => { audio.currentTime = 0; audio.play(); };
$("prev").onclick = () => go(index - 1);
$("next").onclick = () => go(index + 1);
$("unlabelled").onclick = nextUnlabelled;
$("save").onclick = saveNext;
audio.addEventListener("loadedmetadata", () => { audio.playbackRate = $("slow").classList.contains("on") ? 0.5 : 1; });

document.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const item = state && state.items[index]; if (!item) return;
  const k = e.key;
  if (k === " ") { e.preventDefault(); if (audio.paused) audio.play(); else audio.pause(); }
  else if (k === "Enter") { e.preventDefault(); saveNext(); }
  else if (k === "a") { setVerdict("acceptable"); saveNext(); }
  else if (k === "o") setVerdict("objectionable");
  else if (k === "u") setVerdict("uncertain");
  else if (k === "l") $("loop").click();
  else if (k === "s") $("slow").click();
  else if (k === "ArrowLeft") go(index - 1);
  else if (k === "ArrowRight") go(index + 1);
  else if (/^[0-9]$/.test(k)) {
    const n = k === "0" ? 9 : Number(k) - 1;
    const c = visibleClasses(item)[n];
    if (c) toggleClass(c.id, !draft.classes[c.id]);
  }
});

fetch("/api/state").then(r => r.json()).then(s => {
  state = s; $("batch").textContent = s.batch;
  const first = s.items.findIndex(it => !s.labels[it.token]);
  index = first < 0 ? 0 : first; render();
});
</script></body></html>
"""
