"""Chat confirmations: the maintainer hears a few flagged takes and answers usable or unusable.

`qc.py confirm next --run <generated run>` picks up to `--n` (5) takes the run flagged, with any
detector that has a class (the advisory loudness flag alone never sends a take). It leaves out
human controls, every clone take (mode `clone`, or a take with a reference clip: corpus-voice
clones are internal-only and are never sent) and every take already answered in a confirm batch.
It prefers `--languages` (French and English) and spreads over detectors: round-robin by
detector, the highest score first. It writes a `kind: "confirm"` label batch
(`build/private/qc/batches/<name>.json`), copies each WAV to
`build/private/qc/confirm/<name>/<k>.wav` under a neutral name, and lists, per take, the file, the
language and the script, never a detector, score or voice: the maintainer judges blind.

`qc.py confirm record --batch <name> --answers "1=x,2=u,3=?"` writes the answers as label lines
(`labels/<name>.jsonl`), validated as the listening page's are: `x` (unusable) is objectionable,
`u` (usable) acceptable and `?` uncertain. The rater is the protocol's, `playedFraction` 1.0 (the
maintainer attests hearing each take in full), and `--classes "1=devoiced:severe,pause:moderate"`
optionally ticks classes. These labels measure the precision of the human-reference thresholds
(`qc.calibrate.evaluate`); the supervised fit reads them like queue labels, never as a sample.
"""

from __future__ import annotations

import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from qc import label, store
from qc.controls import CONTROLS_LANE
from qc.store import Layout

CONFIRM_KIND = "confirm"
DEFAULT_N = 5
DEFAULT_LANGUAGES = ("french", "english")
NAME_PREFIX = "confirm-"
ANSWERS = {"x": "objectionable", "unusable": "objectionable", "u": "acceptable", "usable": "acceptable",
           "?": "uncertain"}


class ConfirmError(ValueError):
    """The run, the batch or the answers cannot support a confirmation."""


def confirm_directory(layout: Layout, name: str) -> Path:
    return layout.private / "confirm" / name


def is_clone(take: dict[str, Any]) -> bool:
    """A clone take: mode `clone`, or any take carrying a reference clip."""

    return take.get("mode") == "clone" or bool(take.get("reference"))


def confirmed_takes(layout: Layout) -> set[str]:
    """The takes any rater has answered in a confirm batch."""

    answered: set[str] = set()
    for name in label.batch_names(layout):
        batch = label.load_batch(layout, name)
        if batch.get("kind") != CONFIRM_KIND:
            continue
        tokens = {row.get("token") for row in store.read_jsonl(label.labels_path(layout, name)) if isinstance(row, dict)}
        answered.update(item["takeToken"] for item in batch["items"] if item["token"] in tokens)
    return answered


def _default_name(layout: Layout) -> str:
    numbers = [int(name[len(NAME_PREFIX):]) for name in label.batch_names(layout)
               if name.startswith(NAME_PREFIX) and name[len(NAME_PREFIX):].isdigit()]
    return f"{NAME_PREFIX}{max(numbers, default=0) + 1:03d}"


def _round_robin(group: list[dict[str, Any]], count: int, taken: set[str]) -> list[dict[str, Any]]:
    """Up to `count` candidates, one detector at a time in turn, each detector's highest score first."""

    queues: dict[str, list[tuple[float, str, dict[str, Any]]]] = {}
    for candidate in group:
        for flag in candidate["flags"]:
            queues.setdefault(flag["detector"], []).append((float(flag.get("score") or 0.0), candidate["token"],
                                                            candidate))
    for queue in queues.values():
        queue.sort(key=lambda item: (-item[0], item[1]))
    picked: list[dict[str, Any]] = []
    while len(picked) < count and any(queues.values()):
        for detector in sorted(queues):
            queue = queues[detector]
            while queue and queue[0][1] in taken:
                queue.pop(0)
            if queue and len(picked) < count:
                _, token, candidate = queue.pop(0)
                picked.append(candidate)
                taken.add(token)
    return picked


def pick(candidates: list[dict[str, Any]], n: int, languages: Iterable[str]) -> list[dict[str, Any]]:
    """The takes to send: the preferred languages first, then the others, each round-robin by detector."""

    preferred = set(languages)
    first = [candidate for candidate in candidates if candidate["language"] in preferred]
    rest = [candidate for candidate in candidates if candidate["language"] not in preferred]
    taken: set[str] = set()
    chosen = _round_robin(first, n, taken)
    if len(chosen) < n:
        chosen += _round_robin(rest, n - len(chosen), taken)
    return chosen


def next_batch(layout: Layout, run_id: str, *, n: int = DEFAULT_N, languages: Iterable[str] = DEFAULT_LANGUAGES,
               name: str | None = None) -> dict[str, Any]:
    """Write the next confirm batch from a generated run's flags and copy its WAVs under neutral
    names; return what the maintainer is shown: per take its number, file, language and script."""

    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ConfirmError("--n must be at least 1")
    directory = layout.runs / run_id
    if not run_id or Path(run_id).name != run_id or not (directory / "flags.json").is_file() \
            or not (directory / "takes.json").is_file():
        raise ConfirmError(f"run {run_id} has no flags.json and takes.json under build/private/qc/runs")
    flags = store.read_json(directory / "flags.json")
    if flags.get("lane") == CONTROLS_LANE:
        raise ConfirmError(f"run {run_id} is a {CONTROLS_LANE} run: human recordings are never sent for confirmation")
    preferred = [store.normalize_language(language) for language in languages]
    takes = {take["token"]: take for take in store.read_json(directory / "takes.json").get("takes", [])}
    answered = confirmed_takes(layout)
    candidates = []
    for entry in flags.get("takes", []):
        take = takes.get(entry["token"])
        if take is None or entry.get("control") or take.get("control") or is_clone(take) or entry["token"] in answered:
            continue
        flagged = [flag for flag in entry.get("flags") or [] if flag.get("class")]
        if not flagged or not take.get("audio") or not Path(take["audio"]).is_file():
            continue
        candidates.append({"token": entry["token"], "language": take.get("language"), "flags": flagged, "take": take})
    chosen = pick(candidates, n, preferred)
    if not chosen:
        raise ConfirmError(f"run {run_id} flagged no take that can be sent (controls, clones and answered takes "
                           "are never sent)")
    name = name or _default_name(layout)
    if label.batch_path(layout, name).exists():
        raise FileExistsError(f"batch {name} exists; choose another name")
    folder = confirm_directory(layout, name)
    folder.mkdir(parents=True, exist_ok=True)
    items, listing = [], []
    for position, candidate in enumerate(chosen):
        take = candidate["take"]
        target = folder / f"{position + 1}.wav"
        shutil.copyfile(take["audio"], target)
        items.append({
            "token": label.label_token(name, 0, take["token"], 0), "takeToken": take["token"], "repeatOf": None,
            "split": label.split_for_family(str(take.get("family") or take.get("takeID") or take["token"])),
            "inclusionProbability": None, "stratum": label.stratum(take), "enriched": True,
            "reasons": sorted({flag["detector"] for flag in candidate["flags"]}), "order": position,
        })
        listing.append({"k": position + 1, "path": str(target), "language": take.get("language"),
                        "text": " ".join(str(take.get("text") or "").split())})
    label.write_batch(layout, {
        "schema": label.BATCH_SCHEMA, "batch": name, "kind": CONFIRM_KIND, "createdAt": label.utc_now(),
        "params": {"run": run_id, "n": n, "languages": preferred}, "items": items,
        "takes": {item["takeToken"]: takes[item["takeToken"]] for item in items},
    })
    return {"batch": name, "takes": listing}


def next_lines(result: dict[str, Any]) -> list[str]:
    """What the maintainer sees: blind (no detector, score, voice or take id)."""

    name = result["batch"]
    lines = [f"qc confirm: batch {name}, {len(result['takes'])} takes. Listen to each in full, then answer "
             "per take: x unusable, u usable, ? unsure (for example 1=x,2=u,3=?)."]
    for take in result["takes"]:
        lines.append(f"{take['k']}. {take['path']}")
        lines.append(f"   {take['language']}: {take['text']}")
    lines.append(f"qc confirm: record them with: python3 scripts/qc.py confirm record --batch {name} "
                 '--answers "1=x,2=u,3=?"')
    return lines


def _take_number(key: str, count: int) -> int:
    key = key.strip()
    if not re.fullmatch(r"[0-9]+", key) or not 1 <= int(key) <= count:
        raise ConfirmError(f"unknown take {key!r}: the batch has takes 1 to {count}")
    return int(key)


def _parts(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;]", text) if part.strip()]


def parse_answers(text: str, count: int) -> dict[int, str]:
    """`1=x,2=u,3=?` to verdicts by take number (1 to `count`)."""

    answers: dict[int, str] = {}
    for part in _parts(text or ""):
        key, separator, value = part.partition("=")
        if not separator:
            raise ConfirmError(f"an answer is <take>=<x|u|?>, not {part!r}")
        number = _take_number(key, count)
        verdict = ANSWERS.get(value.strip().lower())
        if verdict is None:
            raise ConfirmError(f"take {number}: answer x (unusable), u (usable) or ? (unsure), not {value.strip()!r}")
        if number in answers:
            raise ConfirmError(f"take {number} is answered twice")
        answers[number] = verdict
    if not answers:
        raise ConfirmError("no answers given")
    return answers


def parse_classes(text: str, count: int) -> dict[int, dict[str, dict[str, Any]]]:
    """`1=devoiced:severe,pause:moderate,3=stutter:mild` to ticked classes by take number."""

    classes: dict[int, dict[str, dict[str, Any]]] = {}
    current: int | None = None
    for part in _parts(text or ""):
        if "=" in part:
            key, _, part = part.partition("=")
            current = _take_number(key, count)
        if current is None:
            raise ConfirmError(f"classes start with their take, as in 1=devoiced:severe, not {part!r}")
        class_id, separator, severity = (piece.strip() for piece in part.partition(":"))
        if not separator or not class_id or not severity:
            raise ConfirmError(f"a class is <class>:<severity>, not {part!r}")
        bucket = classes.setdefault(current, {})
        if class_id in bucket:
            raise ConfirmError(f"take {current}: {class_id} is given twice")
        bucket[class_id] = {"severity": severity.lower(), "start": None, "end": None}
    return classes


def record(layout: Layout, name: str, answers: str, *, classes: str | None = None,
           rater: str | None = None) -> dict[str, Any]:
    """Append the maintainer's answers to a confirm batch's labels; every answer is validated
    before any is written."""

    batch = label.load_batch(layout, name)
    if batch.get("kind") != CONFIRM_KIND:
        raise ConfirmError(f"batch {name} is a {batch.get('kind')} batch, not a confirm batch")
    protocol = label.load_protocol(layout)
    rater = rater or label.default_rater(layout)
    if not label.BATCH_NAME_RE.fullmatch(rater):
        raise ConfirmError(f"invalid rater id: {rater!r}")
    items = sorted((item for item in batch["items"] if item["repeatOf"] is None), key=lambda item: item["order"])
    verdicts = parse_answers(answers, len(items))
    ticks = parse_classes(classes, len(items)) if classes else {}
    stray = sorted(set(ticks) - set(verdicts))
    if stray:
        raise ConfirmError(f"classes for take {', '.join(map(str, stray))}, which has no answer")
    digest = label.protocol_digest(protocol)
    rows = []
    for number, verdict in sorted(verdicts.items()):
        try:
            checked = label.validate_label({"verdict": verdict, "playedFraction": 1.0, "classes": ticks.get(number, {})},
                                           protocol=protocol, acoustic_only=False)
        except ValueError as error:
            raise ConfirmError(f"take {number}: {error}") from None
        rows.append({"token": items[number - 1]["token"], "batch": name, "rater": rater,
                     "classes": checked["classes"], "verdict": checked["verdict"], "acousticOnly": False,
                     "playedFraction": checked["playedFraction"], "protocolSHA256": digest,
                     "labelledAt": label.utc_now()})
    path = label.labels_path(layout, name)
    for row in rows:
        store.append_jsonl(path, row)
    answered = label.latest_labels(layout, name, rater)
    return {"batch": name, "recorded": len(rows), "verdicts": dict(Counter(row["verdict"] for row in rows)),
            "takes": len(items), "unanswered": sum(1 for item in items if item["token"] not in answered)}
