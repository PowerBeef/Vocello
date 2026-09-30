#!/usr/bin/env python3
"""Render the audio QC reference tree, docs/reference/audio-qc/ (AQ-09, audit section 3.7).

Pages:

- `README.md`: the index. Hand-written pipeline and procedure; generated judge,
  detector, lane and verdict tables.
- `qualification-policy.md`: the threshold-change authority, rendered from
  `config/audio-qc-qualification-policy.json`.
- `judges/<id>.md`, one per judge of `config/audio-qc-judges.json` (`@N` is
  spelled `-vN`, as the canary records are): what it measures, provenance,
  pins, execution and resources, its canary, and the detectors that consume it
  with their qualification.
- `detectors/<id>.md`, one per detector of `config/audio-qc-detectors.json`:
  its definition, the lanes it gates, its plan and its calibration records.
- `meta-evaluation-report.md`, generated only: the accuracy report across
  detectors from the committed records under `benchmarks/audio-qc-calibration/`
  ("not qualified" without one), the lane gates of
  `config/audio-qc-lane-gates.json` and the judges' canaries.
- `corpora.md`: the pinned corpora of the next qualification round, rendered
  from `config/audio-qc-corpora.json`: per group its sources and bytes, and per
  source its pins, license, attribution, languages, labels and caveats.

Facts appear only inside generated blocks, which this script owns:

    <!-- BEGIN GENERATED audio-qc-docs:<block> (...) -->
    ...
    <!-- END GENERATED audio-qc-docs:<block> -->

Text outside them is hand-written and kept. A missing page is created with its
title and blocks, a missing block is appended, and a block its page does not
have is removed. A judge or detector page without a registry entry is an error
for a person to resolve, since its prose may belong to a successor.

    python3 scripts/audio_qc_docs.py regen           rewrite what is stale
    python3 scripts/audio_qc_docs.py regen --check   fail when anything is stale

`scripts/dev.sh regen` runs it; the contract gate runs `regen --check`.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import sys
from typing import Any, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import audio_qc_detector_calibration as calibration  # noqa: E402
from lib.qc_qualification import detectors as registry_lib, thresholds  # noqa: E402

DOCS = PurePosixPath("docs/reference/audio-qc")
LANE_GATES = "config/audio-qc-lane-gates.json"
CORPORA = "config/audio-qc-corpora.json"
PREREGISTRATIONS = "config/audio-qc-preregistrations"
STALE_MESSAGE = "audio-qc docs are stale"
BEGIN = ("<!-- BEGIN GENERATED audio-qc-docs:{name} (scripts/audio_qc_docs.py regen; "
         "edit its sources, not this block) -->")
END = "<!-- END GENERATED audio-qc-docs:{name} -->"
BLOCK = re.compile(r"<!-- BEGIN GENERATED audio-qc-docs:(?P<name>[a-z0-9-]+) [^\n]*-->\n(?P<body>.*?)"
                   r"<!-- END GENERATED audio-qc-docs:(?P=name) -->\n?", re.S)
MARKER = "GENERATED audio-qc-docs:"
# Audit section 5.7.
CLASS_NAMES = {"A": "signal", "B": "content", "C": "boundary", "D": "language", "E": "identity", "F": "prosody",
               "G": "quality", "H": "delivery", "I": "introspection", "J": "long form"}
LEVEL_ORDER = ("warn", "fail")
NOT_QUALIFIED = ("**Not qualified.** No committed calibration record qualifies it: its measurements compose as "
                 "`uncalibrated` and it gates no lane.")


class DocsError(ValueError):
    """A registry or page the generator cannot render or splice."""


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #

def page_name(identifier: str) -> str:
    """A judge's or detector's page: its id with `@N` spelled `-vN`."""
    name, version = identifier.rsplit("@", 1)
    return f"{name}-v{version}.md"


def judge_page(identifier: str) -> PurePosixPath:
    return DOCS / "judges" / page_name(identifier)


def detector_page(identifier: str) -> PurePosixPath:
    return DOCS / "detectors" / page_name(identifier)


def link(page: PurePosixPath, target: str | PurePosixPath, text: str) -> str:
    return f"[{text}]({posixpath.relpath(str(target), str(page.parent))})"


def cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def number(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def compact(value: Any) -> str:
    """A flat mapping as `key=value` pairs; anything else as compact JSON."""
    if isinstance(value, Mapping) and all(not isinstance(item, (Mapping, list)) for item in value.values()):
        return ", ".join(f"{key}={json.dumps(item, ensure_ascii=False)}" for key, item in value.items())
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def rest(mapping: Mapping[str, Any], known: Iterable[str]) -> list[str]:
    """The fields of a registry object the page does not lay out, one bullet each, so none goes unshown."""
    return [f"- `{key}`: {value if isinstance(value, str) else compact(value)}"
            for key, value in mapping.items() if key not in set(known)]


def gib(value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "-"
    return f"{value / 2 ** 30:.2f} GiB"


def short(digest: Any) -> str:
    return f"`{digest[:16]}`" if isinstance(digest, str) and digest else "-"


def fraction(rate: Any, bound: str | None = "upper") -> str:
    """`k/n (rate)` with the named one-sided bound, or `-` when nothing was counted."""
    if not isinstance(rate, Mapping) or not rate.get("units"):
        return "-"
    text = f"{rate['events']}/{rate['units']} ({rate['events'] / rate['units']:.3f})"
    if bound and isinstance(rate.get(bound), (int, float)):
        text += f", {bound} {rate[bound]:.3f}"
    return text


def sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def names(values: Iterable[Any]) -> str:
    listed = [str(value) for value in values]
    return ", ".join(listed) if listed else "-"


def table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(cell(value) for value in row) + " |" for row in rows]
    return lines


def class_label(entry: Mapping[str, Any]) -> str:
    name = CLASS_NAMES.get(entry.get("class"))
    return f"{entry.get('class')} ({name})" if name else number(entry.get("class"))


def component_reads(component: Mapping[str, Any]) -> str:
    what = component.get("field") or component.get("metric") or component.get("measure")
    text = f"{component.get('source')} `{what}`"
    return f"absolute {text}" if component.get("transform") == "absolute" else text


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #

def load_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DocsError(f"{what} {path.name} is unreadable: {error}") from error


@dataclass
class Record:
    path: str
    data: dict | None
    problems: list[str]

    @property
    def usable(self) -> bool:
        return self.data is not None and not self.problems


@dataclass
class Qualification:
    """One detector's plan, ledger entry and calibration records as the tree holds them."""
    plan: thresholds.PreRegistration | None
    plan_problem: str | None
    ledger: dict | None
    records: list[Record] = field(default_factory=list)
    # Plans at a fail point beside the warn plan: (point, plan, its ledger entry).
    fail_plans: list[tuple[str, thresholds.PreRegistration, dict | None]] = field(default_factory=list)

    def best(self) -> Record | None:
        """The usable qualified record at the strictest level, if any."""
        qualified = [record for record in self.records if record.usable and record.data["verdict"] == "qualified"]
        return max(qualified, key=lambda record: (LEVEL_ORDER.index(record.data["level"])
                                                  if record.data["level"] in LEVEL_ORDER else -1, record.path),
                   default=None)

    def verdict(self) -> str:
        best = self.best()
        if best is not None:
            return f"qualified ({best.data['level']})"
        if any(record.usable for record in self.records):
            return "refused"
        return "not qualified"

    def plan_state(self) -> str:
        if self.plan is None:
            state = "unreadable plan" if self.plan_problem else "no plan"
        elif self.ledger is None:
            state = "planned, not confirmed"
        else:
            state = f"confirmed ({self.ledger.get('status', '-')})"
        for point, _, ledger in self.fail_plans:
            state += f"; {point} " + ("planned" if ledger is None else f"confirmed ({ledger.get('status', '-')})")
        return state


@dataclass
class Sources:
    root: Path
    judges: dict
    detectors: dict
    policy: dict
    gates: dict
    corpora: dict
    qualifications: dict[str, Qualification] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> "Sources":
        root = Path(root)
        sources = cls(root, load_json(root / calibration.JUDGES, "the judge registry"),
                      load_json(root / calibration.REGISTRY, "the detector registry"),
                      load_json(root / calibration.POLICY, "the qualification policy"),
                      load_json(root / LANE_GATES, "the lane gates"),
                      load_json(root / CORPORA, "the corpora registry"))
        if not isinstance(sources.judges.get("judges"), Mapping) \
                or not isinstance(sources.detectors.get("detectors"), list):
            raise DocsError("the judge registry maps its judges and the detector registry lists its detectors")
        if not isinstance(sources.corpora.get("sources"), Mapping) \
                or not isinstance(sources.corpora.get("groups"), Mapping):
            raise DocsError("the corpora registry maps its sources and groups")
        for entry in sources.detector_entries():
            sources.qualifications[entry["id"]] = sources._qualification(entry)
        return sources

    def judge_entries(self) -> dict[str, dict]:
        entries = dict(self.judges["judges"])
        if any("@" not in identifier or not isinstance(entry, Mapping) for identifier, entry in entries.items()):
            raise DocsError("every judge is an id@version mapped to its entry")
        return entries

    def detector_entries(self) -> list[dict]:
        entries = [entry for entry in self.detectors["detectors"] if isinstance(entry, Mapping)]
        if len(entries) != len(self.detectors["detectors"]) \
                or any(not isinstance(entry.get("id"), str) or "@" not in entry["id"] for entry in entries):
            raise DocsError("every detector is an entry with an id@version")
        return entries

    def _qualification(self, entry: Mapping[str, Any]) -> Qualification:
        directory = self.root / PREREGISTRATIONS
        plan = problem = ledger = None
        try:
            plan = thresholds.PreRegistrationStore(directory, naming="detector").load(entry["id"])
        except (thresholds.PreRegistrationError, ValueError, KeyError, TypeError) as error:
            problem = str(error)
        if plan is not None:
            try:
                ledger = thresholds.ConfirmationLedger(directory).outcome(plan.digest())
            except (OSError, json.JSONDecodeError):
                ledger = {"status": "unreadable"}
        fail_plans = []
        for point in calibration.SUPPORTED_OPERATING_POINTS[1:]:
            try:
                other = thresholds.PreRegistrationStore(directory, naming="detector").load(entry["id"], point)
                outcome = thresholds.ConfirmationLedger(directory).outcome(other.digest()) if other else None
            except (thresholds.PreRegistrationError, ValueError, KeyError, TypeError, OSError) as error:
                problem = problem or f"{point}: {error}"
                continue
            if other is not None:
                fail_plans.append((point, other, outcome))
        records = []
        record_directory = self.root / calibration.RECORDS / entry["id"]
        current = registry_lib.definition_digest(entry)
        for path in sorted(record_directory.glob("record-*.json")) if record_directory.is_dir() else ():
            relative = path.relative_to(self.root).as_posix()
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                records.append(Record(relative, None, ["unreadable"]))
                continue
            problems = calibration.record_errors(data)
            if not problems and data["detector"] != entry["id"]:
                problems.append(f"the record is of {data['detector']}")
            if not problems and data["detectorDefinitionSHA256"] != current:
                problems.append("it confirmed an earlier definition (A7)")
            records.append(Record(relative, data if isinstance(data, dict) else None, problems))
        return Qualification(plan, problem, ledger, records, fail_plans)

    def consumers(self, judge: str) -> list[tuple[dict, list[str], list[str]]]:
        """The detectors that read a judge, each with the languages and what it reads there."""
        found = []
        for entry in self.detector_entries():
            languages: list[str] = []
            reads: list[str] = []
            for group in (entry.get("score") or {}).get("groups") or ():
                components = [component for component in group.get("components") or ()
                              if registry_lib.component_judge(component) == judge]
                required = judge in (group.get("requiresComplete") or ())
                if not components and not required:
                    continue
                languages += [language for language in group.get("languages") or () if language not in languages]
                for what in [component_reads(component) for component in components] \
                        + (["must complete"] if required else []):
                    if what not in reads:
                        reads.append(what)
            if languages:
                found.append((entry, languages, reads))
        return found

    def lane_gates(self, detector: str) -> list[tuple[str, str]]:
        return [(lane, str(gate.get("level"))) for lane, spec in (self.gates.get("lanes") or {}).items()
                for gate in (spec.get("gates") or ()) if gate.get("detector") == detector]


# --------------------------------------------------------------------------- #
# Judge pages
# --------------------------------------------------------------------------- #

JUDGE_FIELDS = frozenset({
    "role", "kind", "status", "calibration", "voting", "family", "ships", "legacyIdentifiers", "pins", "license",
    "tierBAcceptance", "licenseDecision", "independence", "identity", "execution", "resources", "determinismClass",
    "expectedDeterminismClass", "canary", "panel", "decodeOptions", "preprocessing", "configuration",
    "acquisition", "retirement", "plannedRetirement", "votingGate",
})


def _file_rows(files: Mapping[str, Any]) -> list[list[str]]:
    rows = []
    for name, pin in sorted(files.items()):
        if not isinstance(pin, Mapping):
            rows.append([f"`{name}`", "-", f"SHA-256 {short(pin)}"])
        elif pin.get("lfsSHA256"):
            rows.append([f"`{name}`", number(pin.get("size")), f"LFS SHA-256 {short(pin['lfsSHA256'])}"])
        elif pin.get("sha256"):
            rows.append([f"`{name}`", number(pin.get("size")), f"SHA-256 {short(pin['sha256'])}"])
        else:
            rows.append([f"`{name}`", number(pin.get("size")), f"git blob {short(pin.get('gitBlobID'))}"])
    return rows


def _resources_line(resources: Mapping[str, Any]) -> str:
    ceiling = resources.get("ceilingBytes")
    if ceiling is None:
        admitted = f"{gib(resources.get('provisionalCeilingBytes'))} (provisional)"
    else:
        admitted = gib(ceiling)
        if resources.get("ceilingStatus"):
            admitted += f" ({resources['ceilingStatus']})"
        if resources.get("ceilingSession"):
            admitted += f", measured in session {resources['ceilingSession']}"
    return (f"- Resources: canonical-host peak {gib(resources.get('canonicalHostPeakBytes'))}; admission ceiling "
            f"{admitted}; policy: {resources.get('ceilingPolicy', '-')}.")


def judge_facts(sources: Sources, identifier: str, judge: Mapping[str, Any]) -> str:
    page = judge_page(identifier)
    statuses = sources.judges.get("statuses") or {}
    tiers = sources.judges.get("tiers") or {}
    execution = judge.get("execution") or {}
    license_ = judge.get("license") or {}
    pins = judge.get("pins") or {}
    status = judge.get("status")
    determinism = number(judge.get("determinismClass"))
    if judge.get("expectedDeterminismClass"):
        determinism += f" (expected {judge['expectedDeterminismClass']})"
    stage = "-" if execution.get("stage") is None else f"{execution['stage']} ({execution.get('lane', '-')})"
    lines = [f"Registry entry `{identifier}` in {link(page, calibration.JUDGES, calibration.JUDGES)}.", "",
             f"**Measures.** {judge.get('role', '-')}", ""]
    lines += table(["Status", "Calibration", "Kind", "Family", "Votes", "Ships", "Stage", "Determinism"],
                   [[f"`{status}`", number(judge.get("calibration")), number(judge.get("kind")),
                     number(judge.get("family")), number(judge.get("voting")), number(judge.get("ships")),
                     stage, determinism]])
    lines += ["", f"`{status}`: {statuses.get(status, 'not a registry status.')}"]
    panel = judge.get("panel") or {}
    if panel.get("languages"):
        roles = "; ".join(f"{role}: {names(values)}" for role, values in panel["languages"].items())
        lines += ["", f"**Languages.** {roles}."]
    if panel.get("audit"):
        lines += ["", f"**Audit section.** {panel['audit']}."]
    if panel.get("scopeNote"):
        lines += ["", f"**Scope.** {panel['scopeNote']}"]
    if judge.get("votingGate"):
        gate = judge["votingGate"]
        lines += ["", f"**Voting gate ({gate.get('status', '-')}).** {gate.get('requires', '-')}"]
    for key, title in (("retirement", "Retired"), ("plannedRetirement", "Planned retirement")):
        value = judge.get(key)
        if isinstance(value, Mapping) and value:
            lines += ["", f"**{title}.**", ""] + rest(value, ())
        elif value:
            lines += ["", f"**{title}.** {compact(value)}"]

    tier = license_.get("tier")
    lines += ["", "## Provenance", "",
              f"- License tier **{number(tier)}** ({number(license_.get('trainingDataRisk'))}): "
              f"{tiers.get(tier, 'not a registry tier.')} Commercial use compatible: "
              f"{number(license_.get('commercialUseCompatible'))}."]
    for key, title in (("weights", "Weights"), ("code", "Code"), ("trainingData", "Training data"),
                       ("tierBasis", "Tier basis")):
        if license_.get(key):
            lines.append(f"- {title}: {license_[key]}")
    if license_.get("notices"):
        lines.append(f"- Notices: {names(license_['notices'])}")
    lines += rest(license_, ("tier", "trainingDataRisk", "commercialUseCompatible", "weights", "code",
                             "trainingData", "tierBasis", "notices", "sources"))
    if judge.get("tierBAcceptance"):
        accepted = judge["tierBAcceptance"]
        lines.append(f"- Tier-B acceptance: decision {accepted.get('decision')} ({accepted.get('date')}), "
                     f"scope `{accepted.get('scope')}`.")
    if judge.get("licenseDecision"):
        decision = judge["licenseDecision"]
        lines.append(f"- License decision ({decision.get('date')}, {decision.get('item')}): "
                     f"{decision.get('decision')}")
        if decision.get("attribution"):
            lines.append(f"- Attribution: {decision['attribution']}")
    independence = judge.get("independence") or {}
    if independence:
        lines.append(f"- Independence: vendor {independence.get('vendor', '-')}; architecture "
                     f"{independence.get('architecture', '-')}; training data "
                     f"{independence.get('trainingData', '-')}; label lineage "
                     f"{independence.get('labelLineage', '-')}; correlated with the generator's lab: "
                     f"{number(independence.get('generatorLabCorrelated'))}.")
        if independence.get("correlationNotes"):
            lines.append(f"- Correlation: {independence['correlationNotes']}")
        lines += rest(independence, ("vendor", "architecture", "trainingData", "labelLineage",
                                     "generatorLabCorrelated", "correlationNotes"))
    if license_.get("sources"):
        lines.append(f"- Sources: {names(f'<{source}>' for source in license_['sources'])}")

    lines += ["", "## Pins", ""]
    if pins.get("repository"):
        lines.append(f"- `{pins['repository']}` at revision `{pins.get('revision', '-')}`.")
    if pins.get("framework"):
        lines.append(f"- Framework: {pins['framework']}.")
    lines.append(f"- Digest status: `{pins.get('digestStatus', '-')}`.")
    if pins.get("verification"):
        lines.append(f"- Verification: {pins['verification']}")
    if isinstance(pins.get("runtime"), Mapping) and pins["runtime"]:
        runtime = names(f"{name} {version}" for name, version in sorted(pins["runtime"].items()))
        lines.append(f"- Runtime: {runtime}.")
    if pins.get("executionRegistry"):
        lines.append(f"- Execution registry: `{pins['executionRegistry']}`.")
    lines += rest(pins, ("repository", "revision", "framework", "digestStatus", "verification", "runtime",
                         "executionRegistry", "files"))
    if isinstance(pins.get("files"), Mapping) and pins["files"]:
        lines += [""] + table(["File", "Bytes", "Digest"], _file_rows(pins["files"]))

    lines += ["", "## Execution", ""]
    if execution:
        parts = [f"Stage {execution.get('stage', '-')}", f"lane {execution.get('lane', '-')}"]
        parts += [f"{key} {execution[key]}" for key in ("engine", "device") if key in execution]
        if "threads" in execution:
            threads = f"threads {execution['threads']}"
            parts.append(f"{threads} ({execution['threadsStatus']})" if execution.get("threadsStatus") else threads)
        if "batchSize" in execution:
            parts.append(f"batch size {execution['batchSize']}")
        parts.append("orchestrated" if execution.get("orchestrated") else "not orchestrated")
        if execution.get("worker"):
            parts.append(f"worker `{execution['worker']}`")
        lines.append(f"- {'; '.join(parts)}.")
        for key, title in (("threadControl", "Thread control"), ("note", "Note")):
            if execution.get(key):
                lines.append(f"- {title}: {execution[key]}")
        lines += rest(execution, ("stage", "lane", "engine", "device", "threads", "threadsStatus", "batchSize",
                                  "orchestrated", "worker", "threadControl", "note"))
    for key, title in (("decodeOptions", "Decode options"), ("preprocessing", "Preprocessing"),
                       ("configuration", "Configuration"), ("acquisition", "Acquisition")):
        if judge.get(key):
            lines.append(f"- {title}: {compact(judge[key])}")
    resources = judge.get("resources") or {}
    if resources:
        lines.append(_resources_line(resources))
        if resources.get("ceilingBasis"):
            lines.append(f"- Ceiling basis: {resources['ceilingBasis']}")
        lines += rest(resources, ("provisionalCeilingBytes", "ceilingStatus", "ceilingBasis", "ceilingPolicy",
                                  "canonicalHostPeakBytes", "ceilingBytes", "ceilingSession"))
    identity = judge.get("identity") or {}
    if identity:
        lines.append(f"- Output identity: {names(identity.get('output') or ())}. Envelope identity: "
                     f"{names(identity.get('envelope') or ())}.")
    legacy = judge.get("legacyIdentifiers") or {}
    if legacy:
        listed = "; ".join(f"{key}: {names(values)}" for key, values in legacy.items())
        lines.append(f"- Legacy identifiers: {listed}.")
    others = sorted(set(judge) - JUDGE_FIELDS)
    if others:
        lines += ["", "## Other registry fields", ""] + [f"- `{key}`: {compact(judge[key])}" for key in others]
    return "\n".join(lines)


def canary_lines(sources: Sources, page: PurePosixPath, canary: Any) -> list[str]:
    if not isinstance(canary, Mapping):
        return ["- No canary record."]
    path = canary.get("record")
    lines = [f"- Canary record: {link(page, path, path) if path else '-'} ({canary.get('date', '-')}), output "
             f"identity {short(canary.get('outputIdentity'))}."]
    file = sources.root / path if isinstance(path, str) else None
    if file is None or not file.is_file():
        return lines + ["- The canary record file is missing from the tree."]
    record = load_json(file, "the canary record")
    determinism = record.get("determinism") or {}
    resources = record.get("resources") or {}
    qualification = record.get("qualification") or {}
    session = record.get("session") or {}
    lines.append(f"- Canary qualification passed: {number(qualification.get('passed'))}; determinism "
                 f"{determinism.get('class', '-')} over {number(determinism.get('rowsCompared'))} rows "
                 f"({number(determinism.get('rowsBitExact'))} bit-exact, "
                 f"{number(determinism.get('discreteMismatches'))} discrete mismatches); peak "
                 f"{gib(resources.get('canonicalHostPeakBytes'))} on {session.get('hostProfileID', '-')} "
                 f"(session {session.get('id', '-')}).")
    return lines


def judge_accuracy(sources: Sources, identifier: str, judge: Mapping[str, Any]) -> str:
    page = judge_page(identifier)
    lines = ["## Canary and accuracy", ""] + canary_lines(sources, page, judge.get("canary"))
    consumers = sources.consumers(identifier)
    if not consumers:
        return "\n".join(lines + ["", "**UNQUALIFIED.** No registered detector consumes this judge, so no "
                                      "accuracy is claimed for it."])
    lines += ["", "Its accuracy is claimed only through the detectors that consume it:", ""]
    lines += table(["Detector", "Class", "Languages", "Reads", "Qualification"],
                   [[link(page, detector_page(entry["id"]), f"`{entry['id']}`"), class_label(entry),
                     names(languages), names(reads), sources.qualifications[entry["id"]].verdict()]
                    for entry, languages, reads in consumers])
    if all(sources.qualifications[entry["id"]].best() is None for entry, _, _ in consumers):
        lines += ["", "**UNQUALIFIED.** No committed calibration record qualifies a detector that consumes this "
                      "judge, so every verdict built on it composes as `uncalibrated`."]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Detector pages
# --------------------------------------------------------------------------- #

DETECTOR_FIELDS = frozenset({
    "id", "class", "stage", "measures", "score", "direction", "strata", "scope", "targets", "shams", "populations",
    "limitations", "risks",
})


def _catalog(sources: Sources, name: str, codes: Iterable[str]) -> list[str]:
    catalog = sources.detectors.get(name) or {}
    return [f"- `{code}`: {catalog.get(code, 'not in the registry catalog.')}" for code in codes]


def detector_definition(sources: Sources, entry: Mapping[str, Any]) -> str:
    page = detector_page(entry["id"])
    score = entry.get("score") or {}
    strata = entry.get("strata")
    scope = entry.get("scope") or {}
    lines = [f"Registry entry `{entry['id']}` in {link(page, calibration.REGISTRY, calibration.REGISTRY)}; "
             f"definition digest {short(registry_lib.definition_digest(entry))} (a plan binds it, so any change "
             "is a new version, A7).", "",
             f"**Measures.** {entry.get('measures', '-')}", ""]
    lines += table(["Class", "Stage", "Direction", "Combination", "Unit", "Thresholds"],
                   [[class_label(entry), number(entry.get("stage")), number(entry.get("direction")),
                     number(score.get("combination")), number(score.get("unit")),
                     f"per {strata['by']}" if isinstance(strata, Mapping) else "pooled"]])
    if isinstance(strata, Mapping) and strata.get("reason"):
        lines += ["", f"**Strata.** {strata['reason']}"]
    lines += ["", "**Score components.**", ""]
    rows = []
    for group in score.get("groups") or ():
        parts = []
        for component in group.get("components") or ():
            judge = registry_lib.component_judge(component)
            parts.append(f"{link(page, judge_page(judge), f'`{judge}`')} {component_reads(component)}")
        required = [link(page, judge_page(judge), f"`{judge}`") for judge in group.get("requiresComplete") or ()]
        rows.append([names(group.get("languages") or ()), "; ".join(parts) or "-", names(required)])
    lines += table(["Languages", "Components", "Requires complete"], rows)
    lines += ["", f"**Scope.** {names(scope.get('languages') or ())}."]
    reasons = sources.detectors.get("exclusionReasons") or {}
    for exclusion in scope.get("exclusions") or ():
        lines.append(f"Excludes {exclusion.get('language')}: {reasons.get(exclusion.get('reason'), exclusion)}")
    if scope.get("modes") is not None:
        lines.append(f"Modes: {names(scope['modes'])}.")
    shams = {(sham.get("injectorID"), sham.get("mechanism")) for sham in entry.get("shams") or ()}
    lines += ["", "**Positives and shams.**", ""]
    lines += table(["Injector", "Severities", "Mechanism", "Matched sham"],
                   [[f"`{target.get('injectorID')}`", names(target.get("severities") or ()),
                     number(target.get("mechanism")),
                     number((target.get("injectorID"), target.get("mechanism")) in shams)]
                    for target in entry.get("targets") or ()])
    roles = (sources.detectors.get("roleSets") or {}).get(entry.get("populations")) or {}
    if roles:
        described = []
        for role in registry_lib.ROLE_KEYS:
            value = roles.get(role)
            if isinstance(value, Mapping):
                corpus = f", {value['corpus']}" if value.get("corpus") else ""
                described.append(f"{role} {value.get('population')} ({value.get('cohort')}{corpus})")
            elif value:
                described.append(f"{role} {names(value)}")
        lines += ["", f"**Populations** (role set `{entry.get('populations')}`): {'; '.join(described)}."]
    if entry.get("limitations"):
        lines += ["", "**Limitations.**", ""] + _catalog(sources, "limitations", entry["limitations"])
    if entry.get("risks"):
        lines += ["", "**Risks.**", ""] + _catalog(sources, "risks", entry["risks"])
    gates = sources.lane_gates(entry["id"])
    lanes = names(f"{lane} at {level}" for lane, level in gates) if gates else "none"
    lines += ["", f"**Lanes it gates** ({link(page, LANE_GATES, LANE_GATES)}): {lanes}."]
    others = sorted(set(entry) - DETECTOR_FIELDS)
    if others:
        lines += ["", "**Other registry fields.**", ""] + [f"- `{key}`: {compact(entry[key])}" for key in others]
    return "\n".join(lines)


def plan_lines(page: PurePosixPath, entry: Mapping[str, Any], qualification: Qualification) -> list[str]:
    plan = qualification.plan
    if plan is None:
        if qualification.plan_problem:
            return [f"**Plan.** Unreadable: {qualification.plan_problem}"]
        return ["**Plan.** None committed under "
                f"{link(page, PREREGISTRATIONS, PREREGISTRATIONS + '/')}."]
    path = f"{PREREGISTRATIONS}/{entry['id']}.json"
    cohorts = plan.split_dict()

    def cohort(role: str) -> str:
        value = cohorts.get(role) or {}
        return f"{value.get('kind', '-')} ({value.get('source', '-')}, manifest {short(value.get('manifestDigest'))})"

    lines = [f"**Plan.** {link(page, path, path)}: digest {short(plan.digest())}, rule {plan.rule}, alpha "
             f"{number(plan.alpha)}, confidence {number(plan.confidence)}, operating point "
             f"{plan.binding('operatingPoint') or '-'}, population {plan.population}; injector catalog "
             f"{plan.binding('injectorCatalogVersion') or '-'}, classes {plan.binding('injectionClasses') or '-'}, "
             f"{plan.binding('injectionSamplePerCell') or '-'} per cell."]
    if "calibration" in cohorts:
        lines.append(f"Calibration cohort {cohort('calibration')}; confirmation cohort {cohort('confirmation')}.")
    ledger = qualification.ledger
    if ledger is None:
        lines += ["", "**Confirmation.** Not run: no ledger entry."]
    else:
        reasons = f" ({names(ledger.get('reasons') or ())})" if ledger.get("reasons") else ""
        lines += ["", f"**Confirmation.** Ledger entry {ledger.get('status', '-')}{reasons}."]
    for point, other, outcome in qualification.fail_plans:
        other_path = f"{PREREGISTRATIONS}/{entry['id']}.{point}.json"
        split = other.split_dict()
        n3 = other.binding("n3CohortDigest")
        lines += ["", f"**Plan ({point}).** {link(page, other_path, other_path)}: digest {short(other.digest())}, "
                      f"alpha {number(other.alpha)}; calibration manifest "
                      f"{short((split.get('calibration') or {}).get('manifestDigest'))}, confirmation manifest "
                      f"{short((split.get('confirmation') or {}).get('manifestDigest'))}, N3 bound manifest "
                      f"{short(n3)}; injector catalog {other.binding('injectorCatalogVersion') or '-'}, classes "
                      f"{other.binding('injectionClasses') or '-'}. "
                      + ("Not confirmed: no ledger entry." if outcome is None else
                         f"Ledger entry {outcome.get('status', '-')}"
                         + (f" ({names(outcome.get('reasons') or ())})" if outcome.get("reasons") else "") + ".")]
    return lines


def record_lines(page: PurePosixPath, record: Record, heading: str) -> list[str]:
    title = f"{heading} Record {link(page, record.path, PurePosixPath(record.path).name)}"
    if not record.usable:
        return [f"{title}: not usable ({names(record.problems)}); "
                "`scripts/audio_qc_detector_calibration.py validate` names why."]
    data = record.data
    verdict = (f"qualified at {data['level']}" if data["verdict"] == "qualified"
               else f"refused ({names(data['reasons'])})")
    threshold = data["threshold"]
    rates = data["rates"]
    lines = [f"{title}: {verdict}", "",
             f"Operating point {data['operatingPoint']}; rule {threshold.get('rule')}, alpha "
             f"{number(threshold.get('alpha'))}, thresholds per {threshold.get('strata')}; plan "
             f"{short(data['planSHA256'])}. Rates count source families with one-sided Clopper-Pearson bounds.", ""]
    far_per_language = rates.get("farPerLanguage") or {}
    per_language = far_per_language.get("languages") or {}
    values = threshold.get("values") or {}
    rows = []
    for stratum in sorted((set(values) | set(per_language)) - {registry_lib.POOLED}):
        far = per_language.get(stratum) or {}
        rows.append([stratum, number(values.get(stratum, values.get(registry_lib.POOLED))),
                     fraction(far), number(far.get("limit")), number(far.get("meets"))])
    pooled = rates.get("farPooled") or {}
    rows.append([registry_lib.POOLED, number(values.get(registry_lib.POOLED)), fraction(pooled),
                 number(pooled.get("limit")), number(pooled.get("meets"))])
    population = calibration.COHORT_KINDS.get(((data.get("cohorts") or {}).get("confirmation") or {}).get("kind"),
                                              "N2")
    lines += table(["Stratum", "Threshold", f"FAR on confirmation {population}", "Limit", "Meets"], rows)
    abstention = rates.get("cleanAbstention") or {}
    lines += ["", f"Per-language bounds at confidence {number(far_per_language.get('confidence'))} (Bonferroni "
                  f"over the languages), pooled at {number(pooled.get('confidence'))}. Clean abstention: "
                  f"{fraction(abstention)} (limit {number(abstention.get('limit'))}, meets "
                  f"{number(abstention.get('meets'))}).", ""]
    detection = [[mechanism, cellname, fraction(entry, "lower"), number(entry.get("limit")),
                  number(entry.get("meets"))]
                 for mechanism, block in sorted((rates.get("mechanisms") or {}).items())
                 for cellname, entry in sorted((block.get("cells") or {}).items())]
    lines += table(["Mechanism", "Cell", "Detected", "Limit", "Meets"], detection or [["-", "-", "-", "-", "-"]])
    lines += ["", f"Mechanisms meeting: {names(rates.get('mechanismsMeeting') or ())} (minimum "
                  f"{number(rates.get('mechanismsMin'))}).", ""]
    uninformative = (data.get("a4") or {}).get("uninformative") or {}
    lines += table(["Sham cell", "Alarms", "Overlaps N2 FAR", "Informative"],
                   [[name, fraction(sham) if sham.get("present") else "missing", number(sham.get("overlaps")),
                     "no" if name in uninformative else "yes"]
                    for name, sham in sorted((rates.get("shams") or {}).items())])
    counts = data.get("counts") or {}

    def counted(value: Mapping[str, Any] | None) -> str:
        value = value or {}
        return (f"{number(value.get('clips'))} clips, {number(value.get('families'))} families, "
                f"{number(value.get('abstainedClips'))} abstained")

    confirmation = counts.get("confirmation") or {}
    speakers = data.get("speakers") or {}
    populations = "; ".join(f"{name} {counted(value)}" for name, value in confirmation.items()) or "-"
    lines += ["", f"Counts: calibration {counted(counts.get('calibration'))}; confirmation {populations}. "
                  f"Speakers: {number(speakers.get('count'))} "
                  f"({speakers.get('claim', '-')}, unit `{speakers.get('unit', '-')}`)."]
    bound = rates.get("n3")
    if isinstance(bound, Mapping):
        lines += ["", f"N3 bound (A2): flag rate {fraction(bound)} (limit {number(bound.get('limit'))}, meets "
                      f"{number(bound.get('meets'))}) on N3 manifest "
                      f"{short(((data.get('cohorts') or {}).get('n3') or {}).get('manifestDigest'))}."]
    if data.get("phiAudit"):
        lines += [""] + table(["Consensus languages", "Judges", "Units", "Phi", "Joint failure"],
                              [[names(audit.get("languages") or ()), names(audit.get("judges") or ()),
                                number(audit.get("units")), number(audit.get("phi")),
                                fraction(audit.get("jointFailure"))]
                               for audit in data["phiAudit"]])
    informational = data.get("informational")
    if isinstance(informational, Mapping):
        bounds = names(f"pi {pi}: {number(value)}" for pi, value in (informational.get("farBound") or {}).items())
        lines += ["", f"N3 (report-only): flag rate {fraction(informational.get('flagRate'))}; FAR bound {bounds}."]
    identities = names(f"`{item.get('judge')}` {names(short(value) for value in item.get('outputIdentities') or ())}"
                       for item in data.get("judges") or ())
    lines += ["", f"Judge output identities: {identities}. Record limitations: "
                  f"{names(f'`{code}`' for code in data.get('limitations') or ())}; risks: "
                  f"{names(f'`{code}`' for code in data.get('risks') or ())}."]
    return lines


def detector_qualification(sources: Sources, entry: Mapping[str, Any]) -> str:
    page = detector_page(entry["id"])
    qualification = sources.qualifications[entry["id"]]
    lines = ["## Qualification", "", f"**Status.** {sentence(qualification.verdict())}; "
             f"{qualification.plan_state()}.", ""]
    lines += plan_lines(page, entry, qualification)
    lines.append("")
    if qualification.best() is None:
        lines += [NOT_QUALIFIED, ""]
    for record in qualification.records:
        lines += record_lines(page, record, "###") + [""]
    return "\n".join(lines).rstrip()


# --------------------------------------------------------------------------- #
# Index, policy and report
# --------------------------------------------------------------------------- #

def readme_judges(sources: Sources) -> str:
    page = DOCS / "README.md"
    rows = []
    for identifier, judge in sources.judge_entries().items():
        execution = judge.get("execution") or {}
        stage = "-" if execution.get("stage") is None else f"{execution['stage']} ({execution.get('lane', '-')})"
        rows.append([link(page, judge_page(identifier), f"`{identifier}`"), f"`{judge.get('status')}`",
                     number(judge.get("kind")), number(judge.get("family")), number(judge.get("voting")),
                     number((judge.get("license") or {}).get("tier")), stage,
                     "yes" if isinstance(judge.get("canary"), Mapping) else "no"])
    return "\n".join(table(["Judge", "Status", "Kind", "Family", "Votes", "Tier", "Stage", "Canary"], rows))


def readme_detectors(sources: Sources) -> str:
    page = DOCS / "README.md"
    rows = []
    for entry in sources.detector_entries():
        qualification = sources.qualifications[entry["id"]]
        gates = names(f"{lane} ({level})" for lane, level in sources.lane_gates(entry["id"])) \
            if sources.lane_gates(entry["id"]) else "-"
        rows.append([link(page, detector_page(entry["id"]), f"`{entry['id']}`"), class_label(entry),
                     number(entry.get("stage")), number((entry.get("score") or {}).get("combination")),
                     qualification.plan_state(), qualification.verdict(), gates])
    return "\n".join(table(["Detector", "Class", "Stage", "Combination", "Plan", "Qualification", "Gates"], rows))


def lane_rows(sources: Sources, page: PurePosixPath) -> list[list[str]]:
    lanes = sources.gates.get("lanes") or {}
    rows = []
    for name, gating in (sources.policy.get("laneGatingSets") or {}).items():
        spec = lanes.get(name) or {}
        scope = spec.get("scope") or {}
        gates = names(f"{link(page, detector_page(gate['detector']), '`' + gate['detector'] + '`')} "
                      f"({gate.get('level')})" for gate in spec.get("gates") or ()) if spec.get("gates") else "none"
        declared = (f"{names(scope.get('languages') or ())}; modes {names(scope.get('modes') or ())}; FAR on "
                    f"{scope.get('farPopulation', '-')}") if scope else "not declared"
        rows.append([name, names(gating.get("classes") or ()) if gating.get("classes") else "-",
                     names(gating.get("stages") or ()) if gating.get("stages") else "-",
                     number(spec.get("kind")), declared, gates])
    return rows


def readme_lanes(sources: Sources) -> str:
    page = DOCS / "README.md"
    lines = [f"Classes and stages from `laneGatingSets` in {link(page, calibration.POLICY, calibration.POLICY)}; "
             f"kinds, scopes and gates from {link(page, LANE_GATES, LANE_GATES)}.", ""]
    lines += table(["Lane", "Gating classes", "Stages", "Kind", "Scope", "Gated by"], lane_rows(sources, page))
    return "\n".join(lines)


def readme_verdicts(sources: Sources) -> str:
    verdicts = sources.policy.get("verdicts") or {}
    swift = verdicts.get("swiftOutcomes") or {}
    lines = [f"Composition `{verdicts.get('composition', '-')}`; detector statuses in precedence order "
             f"{names(f'`{status}`' for status in verdicts.get('precedence') or ())}; take statuses "
             f"{names(f'`{status}`' for status in verdicts.get('takeStatuses') or ())}.", ""]
    lines += table(["Detector status", "Swift outcome"],
                   [[f"`{status}`", f"`{swift.get(status, '-')}`"]
                    for status in verdicts.get("detectorStatuses") or ()])
    return "\n".join(lines)


def policy_body(sources: Sources) -> str:
    policy = sources.policy
    page = DOCS / "qualification-policy.md"
    adoption = policy.get("adoption") or {}
    lines = [f"Rendered from {link(page, calibration.POLICY, calibration.POLICY)} (`{policy.get('policy', '-')}`, "
             f"status `{policy.get('status', '-')}`, adopted {adoption.get('date', '-')}).", ""]
    for number_, decision in sorted((adoption.get("decisions") or {}).items()):
        lines.append(f"- Decision {number_}: {decision}")
    rules = policy.get("authorityRules") or {}
    lines += ["", "### The five authority rules", "", f"Source: {rules.get('source', '-')}.", ""]
    lines += [f"{index}. {text}" for index, text in enumerate(rules.get("text") or (), 1)]
    lines += ["", "### Additions A1-A10", ""]
    lines += table(["Id", "Title", "Rule"], [[item.get("id"), item.get("title"), item.get("rule")]
                                              for item in policy.get("additions") or ()])
    lines += ["", "### Label tiers", ""]
    lines += table(["Tier", "Source", "May qualify", "May not qualify"],
                   [[item.get("id"), item.get("source"), names(item.get("mayQualify") or ()),
                     names(item.get("mayNotQualify") or ())] for item in policy.get("labelTiers") or ()])
    lines += ["", "### Populations", ""]
    lines += table(["Population", "Content"], [[item.get("id"), item.get("content")]
                                               for item in policy.get("populations") or ()])
    statistics = policy.get("statistics") or {}
    multiplicity = statistics.get("multiplicity") or {}
    lines += ["", "### Statistics", "",
              f"- Method `{statistics.get('method', '-')}` at confidence {number(statistics.get('confidence'))}; "
              f"legacy `{statistics.get('legacyMethod', '-')}` for {statistics.get('legacyScope', '-')}.",
              f"- Unit of independence: `{statistics.get('unitOfIndependence', '-')}`; "
              f"{statistics.get('familyRule', '-')}.",
              f"- Multiplicity: `{multiplicity.get('method', '-')}`; {multiplicity.get('perLanguageRule', '-')}.", ""]
    targets = statistics.get("sampleSizeTable") or []
    errors = sorted({key for row in targets for key in (row.get("clopperPearson") or {})}, key=int)
    lines += table(["Target bound"] + [f"CP, {count} errors" for count in errors] + ["Wilson, 0 errors"],
                   [[number(row.get("target"))] + [number((row.get("clopperPearson") or {}).get(count))
                                                   for count in errors]
                    + [number(row.get("wilsonTwoSidedZeroErrors"))] for row in targets])
    lines += ["", "### Operating points", ""]
    everything = policy.get("operatingPoints") or {}
    points = {name: point for name, point in everything.items() if isinstance(point, Mapping)}
    keys = []
    for point in points.values():
        keys += [key for key in point if key not in keys]
    rows = [[f"`{key}`"] + [compact(point[key]) if key in point else "-" for point in points.values()]
            for key in keys]
    lines += table(["Field"] + [f"`{name}`" for name in points], rows)
    others = [(name, value) for name, value in everything.items() if name not in points]
    if others:
        lines += [""] + [f"- `{name}`: {names(value) if isinstance(value, list) else compact(value)}"
                         for name, value in others]
    derivation = policy.get("thresholdDerivation") or {}
    lines += ["", "### Threshold derivation", ""]
    lines += [f"- `{key}`: {number(value) if not isinstance(value, (list, dict)) else compact(value)}"
              for key, value in derivation.items()]
    transitions = policy.get("statusTransitions") or {}
    lines += ["", "### Status transitions", ""]
    lines += [f"- `{key}`: {names(value) if isinstance(value, list) else number(value)}"
              for key, value in transitions.items()]
    return "\n".join(lines)


def report_text(sources: Sources) -> str:
    page = DOCS / "meta-evaluation-report.md"
    lines = ["# Audio QC meta-evaluation report", "",
             "<!-- Generated by scripts/audio_qc_docs.py; do not edit. Regenerate with scripts/dev.sh regen. -->",
             "",
             f"The accuracy of every registered detector, rendered from the committed calibration records under "
             f"`{calibration.RECORDS}/`, the plans and ledger under `{PREREGISTRATIONS}/`, the lane gates in "
             f"`{LANE_GATES}` and the judges' canary records. A detector without a qualified record is **not "
             "qualified**: its measurements compose as `uncalibrated` and it gates no lane. Rates count source "
             "families with one-sided Clopper-Pearson bounds.", "", "## Summary", ""]
    rows = []
    for entry in sources.detector_entries():
        qualification = sources.qualifications[entry["id"]]
        best = qualification.best()
        shown = best or next((record for record in qualification.records if record.usable), None)
        link_text = link(page, detector_page(entry["id"]), f"`{entry['id']}`")
        if shown is None:
            rows.append([link_text, class_label(entry), qualification.plan_state(), qualification.verdict()]
                        + ["-"] * 6)
            continue
        rates = shown.data["rates"]
        languages = (rates.get("farPerLanguage") or {}).get("languages") or {}
        worst = max(languages.items(), key=lambda item: (item[1].get("upper") or 0.0, item[0]), default=None)
        cells = [entry_rate for block in (rates.get("mechanisms") or {}).values()
                 for entry_rate in (block.get("cells") or {}).values()]
        weakest = min(cells, key=lambda value: value.get("lower") or 0.0, default=None)
        counts = (shown.data.get("counts") or {}).get("confirmation") or {}
        families = " / ".join(number((counts.get(key) or {}).get("families")) for key in ("N2", "P1", "S"))
        rows.append([link_text, class_label(entry), qualification.plan_state(), qualification.verdict(),
                     fraction(rates.get("farPooled")),
                     f"{worst[0]} {fraction(worst[1])}" if worst else "-",
                     fraction(weakest, "lower") if weakest else "-", fraction(rates.get("cleanAbstention")),
                     families, link(page, shown.path, PurePosixPath(shown.path).name)])
    lines += table(["Detector", "Class", "Plan", "Verdict", "N2 FAR pooled", "Worst-language FAR",
                    "Weakest detection", "Clean abstention", "Families N2 / P1 / S", "Record"], rows)
    lines += ["", "## Lane gates", ""]
    lines += table(["Lane", "Gating classes", "Stages", "Kind", "Scope", "Gated by"], lane_rows(sources, page))
    lines += ["", "## Per detector", ""]
    recorded = [entry for entry in sources.detector_entries() if sources.qualifications[entry["id"]].records]
    if not recorded:
        lines += ["No detector has a committed calibration record yet.", ""]
    for entry in recorded:
        qualification = sources.qualifications[entry["id"]]
        lines += [f"### `{entry['id']}`", "", f"{sentence(qualification.verdict())}; {qualification.plan_state()}. "
                  f"Definition: {link(page, detector_page(entry['id']), page_name(entry['id']))}.", ""]
        if qualification.best() is None:
            lines += [NOT_QUALIFIED, ""]
        for record in qualification.records:
            lines += record_lines(page, record, "####") + [""]
    lines += ["## Judge canaries", ""]
    rows = []
    for identifier, judge in sources.judge_entries().items():
        canary = judge.get("canary")
        determinism = number(judge.get("determinismClass"))
        rows.append([link(page, judge_page(identifier), f"`{identifier}`"), f"`{judge.get('status')}`",
                     link(page, canary["record"], canary.get("date", "record"))
                     if isinstance(canary, Mapping) and canary.get("record") else "none",
                     determinism, gib((judge.get("resources") or {}).get("canonicalHostPeakBytes"))])
    lines += table(["Judge", "Status", "Canary", "Determinism", "Canonical-host peak"], rows)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Corpora
# --------------------------------------------------------------------------- #

CORPORA_PAGE = DOCS / "corpora.md"
PIN_KIND_NAMES = {"sha256": "LFS SHA-256", "gitBlobSHA1": "git blob SHA-1", "md5": "Zenodo MD5"}


def gb(value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "-"
    return f"{value / 1e9:.2f} GB"


def _groups(corpora: Mapping[str, Any]) -> list[str]:
    """The groups in the order the sets list them, then any other group by name."""
    listed: list[str] = []
    for value in (corpora.get("sets") or {}).values():
        listed += [group for group in value.get("groups") or () if group not in listed]
    return [group for group in listed if group in (corpora.get("groups") or {})] + sorted(
        set(corpora.get("groups") or {}) - set(listed))


def _corpus_sources(corpora: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    """The sources by group, then by id."""
    order = _groups(corpora)
    entries = corpora.get("sources") or {}
    return sorted(entries.items(), key=lambda item: (order.index(item[1].get("group"))
                                                     if item[1].get("group") in order else len(order), item[0]))


def _corpus_members(corpora: Mapping[str, Any], group: str) -> list[str]:
    """A group's sources: its own, then those shared into it (`alsoIn`), marked."""
    entries = _corpus_sources(corpora)
    own = [source for source, entry in entries if entry.get("group") == group]
    shared = [f"{source} (shared)" for source, entry in entries if group in (entry.get("alsoIn") or ())]
    return own + shared


def _files(count: Any) -> str:
    return f"{number(count)} file" + ("" if count == 1 else "s")


def _pinned_at(entry: Mapping[str, Any]) -> str:
    if entry.get("record"):
        return f"Zenodo record {entry['record']}, version {entry.get('version', '-')}"
    return f"`{entry.get('repository', '-')}` at `{str(entry.get('revision', '-'))[:12]}`"


def _pin_kinds(entry: Mapping[str, Any]) -> str:
    counts: dict[str, int] = {}
    for file in entry.get("files") or ():
        for key in PIN_KIND_NAMES:
            if key in file:
                counts[key] = counts.get(key, 0) + 1
    pin_file = entry.get("pinFile") or {}
    if pin_file:
        counts["sha256"] = counts.get("sha256", 0) + int(pin_file.get("files") or 0)
    return ", ".join(f"{count} by {PIN_KIND_NAMES[key]}" for key, count in counts.items()) or "-"


def _labels(entry: Mapping[str, Any]) -> str:
    return names(label for label, value in (entry.get("labels") or {}).items() if value)


def corpora_summary(sources: Sources) -> str:
    corpora = sources.corpora
    page = CORPORA_PAGE
    runtime = corpora.get("parquetRuntime") or {}
    lines = [f"Rendered from {link(page, CORPORA, CORPORA)} (`{corpora.get('item', '-')}`): "
             f"{corpora.get('description', '-')}", "", "**Decisions.**", ""]
    lines += [f"- {decision}" for decision in corpora.get("decisions") or ()]
    rows = []
    groups = corpora.get("groups") or {}
    for group in _groups(corpora):
        value = groups[group]
        own = [entry for entry in (corpora.get("sources") or {}).values() if entry.get("group") == group]
        rows.append([f"`{group}`", number(value.get("class")), number(value.get("title")),
                     names(_corpus_members(corpora, group)),
                     number(sum(int((entry.get("totals") or {}).get("files") or 0) for entry in own)),
                     gb(sum(int((entry.get("totals") or {}).get("bytes") or 0) for entry in own)),
                     gb(sum(int((entry.get("extract") or {}).get("estimatedBytes") or 0) for entry in own))])
    lines += ["", "**Groups.** A shared source is counted in its own group only.", ""]
    lines += table(["Group", "Class", "Title", "Sources", "Files", "Download", "Extracted (estimate)"], rows)
    lines.append("")
    for group in _groups(corpora):
        lines.append(f"- `{group}`: {groups[group].get('description', '-')}")
    totals = corpora.get("totals") or {}
    estimate = sum(int((entry.get("extract") or {}).get("estimatedBytes") or 0)
                   for entry in (corpora.get("sources") or {}).values())
    lines += ["", f"**Totals.** {number(totals.get('files'))} files, {gb(totals.get('bytes'))} to download; about "
                  f"{gb(estimate)} of mono PCM16 WAV once extracted (estimates; each extraction checks its own "
                  "need first)."]
    for name, value in (corpora.get("sets") or {}).items():
        lines.append(f"Set `{name}`: {names(f'`{group}`' for group in value.get('groups') or ())}. "
                     f"{value.get('description', '')}".rstrip())
    lines += ["", f"**Hosts.** https only, on {names(f'`{host}`' for host in corpora.get('hosts') or ())}.", "",
              f"**Parquet runtime.** `{runtime.get('family', '-')}`: "
              f"{link(page, runtime.get('lock', '-'), runtime.get('lock', '-'))}, {number(runtime.get('packages'))} "
              f"packages, about {gb(runtime.get('downloadBytes'))} of wheels, import probe "
              f"{names(f'`{module}`' for module in runtime.get('importProbe') or ())}. {runtime.get('note', '')}"
              .rstrip()]
    return "\n".join(lines)


def corpora_sources(sources: Sources) -> str:
    corpora = sources.corpora
    page = CORPORA_PAGE
    entries = _corpus_sources(corpora)
    rows = [[f"`{source}`", f"`{entry.get('group')}`" + (f" (+ {names(entry.get('alsoIn') or ())})"
                                                          if entry.get("alsoIn") else ""),
             number(entry.get("host")), names(entry.get("languages") or ()), _labels(entry),
             number((entry.get("license") or {}).get("id")), number((entry.get("totals") or {}).get("files")),
             gb((entry.get("totals") or {}).get("bytes"))]
            for source, entry in entries]
    lines = table(["Source", "Group", "Host", "Languages", "Labels", "License", "Files", "Download"], rows)
    for source, entry in entries:
        license_ = entry.get("license") or {}
        extract = entry.get("extract") or {}
        pin_file = entry.get("pinFile") or {}
        lines += ["", f"### {entry.get('title', source)} (`{source}`)", "",
                  f"- Pinned: {_pinned_at(entry)} on `{entry.get('host', '-')}`; "
                  f"{_files((entry.get('totals') or {}).get('files'))} "
                  f"({_pin_kinds(entry)}), {gb((entry.get('totals') or {}).get('bytes'))}."]
        if pin_file:
            lines.append(f"- Pin file: {link(page, pin_file.get('path', '-'), pin_file.get('path', '-'))} "
                         f"(SHA-256 {short(pin_file.get('sha256'))}).")
        lines.append(f"- License: {license_.get('id', '-')} ([text]({license_.get('url', '-')}); "
                     f"official source <{license_.get('source', '-')}>).")
        if license_.get("note"):
            lines.append(f"- License note: {license_['note']}")
        lines.append(f"- Attribution: {entry.get('attribution', '-')}")
        labels = entry.get("labels") or {}
        present = [f"{label} ({value})" for label, value in labels.items() if value]
        absent = [label for label, value in labels.items() if not value]
        lines.append(f"- Labels: {names(present)}; absent: {names(absent)}.")
        parts = [f"`{extract.get('format', '-')}`", f"written at {number(extract.get('outputRate'))} Hz",
                 f"about {gb(extract.get('estimatedBytes'))} ({extract.get('estimateBasis', '-')})"]
        if extract.get("format") == "fleurs-reserve":
            parts.append(f"{number(extract.get('cohorts'))} cohorts of {number(extract.get('perLanguage'))} "
                         f"recordings per language, seed `{extract.get('seed', '-')}`")
        lines.append(f"- Extraction: {'; '.join(parts)}.")
        if entry.get("subset"):
            lines.append(f"- Subset: {entry['subset'].get('rule', '-')} Seed `{entry['subset'].get('seed', '-')}`.")
        lines += [f"- Caveat: {caveat}" for caveat in entry.get("caveats") or ()]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Pages and splicing
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Page:
    path: PurePosixPath
    title: str
    blocks: tuple[tuple[str, str], ...]


def pages(sources: Sources) -> list[Page]:
    listed = [
        Page(DOCS / "README.md", "Audio QC reference",
             (("judges", readme_judges(sources)), ("detectors", readme_detectors(sources)),
              ("lanes", readme_lanes(sources)), ("verdicts", readme_verdicts(sources)))),
        Page(DOCS / "qualification-policy.md", "Audio QC qualification policy", (("policy", policy_body(sources)),)),
        Page(CORPORA_PAGE, "Audio QC corpora",
             (("corpora-summary", corpora_summary(sources)), ("corpora-sources", corpora_sources(sources)))),
    ]
    for identifier, judge in sources.judge_entries().items():
        listed.append(Page(judge_page(identifier), f"`{identifier}`",
                           (("facts", judge_facts(sources, identifier, judge)),
                            ("accuracy", judge_accuracy(sources, identifier, judge)))))
    for entry in sources.detector_entries():
        listed.append(Page(detector_page(entry["id"]), f"`{entry['id']}`",
                           (("definition", detector_definition(sources, entry)),
                            ("qualification", detector_qualification(sources, entry)))))
    return listed


def block_text(name: str, body: str) -> str:
    return f"{BEGIN.format(name=name)}\n{body.rstrip()}\n{END.format(name=name)}\n"


def splice(existing: str | None, page: Page) -> str:
    """The page with its generated blocks current and every hand-written line kept."""
    wanted = dict(page.blocks)
    if existing is None:
        return f"# {page.title}\n\n" + "\n".join(block_text(name, body) for name, body in page.blocks)
    found = [match.group("name") for match in BLOCK.finditer(existing)]
    duplicated = sorted({name for name in found if found.count(name) > 1})
    if duplicated:
        raise DocsError(f"{page.path}: the block {', '.join(duplicated)} appears more than once")
    if BLOCK.sub("", existing).count(MARKER):
        raise DocsError(f"{page.path}: a generated block marker has no partner")

    def replace(match: re.Match) -> str:
        name = match.group("name")
        return block_text(name, wanted[name]) if name in wanted else ""

    text = BLOCK.sub(replace, existing)
    missing = [name for name, _ in page.blocks if name not in found]
    if missing:
        text = text.rstrip("\n") + "\n\n" + "\n".join(block_text(name, wanted[name]) for name in missing)
    return text if text.endswith("\n") else text + "\n"


def render_all(root: Path = REPO) -> dict[str, str]:
    """Every page of the tree as it should read, keyed by its repository-relative path."""
    root = Path(root)
    sources = Sources.load(root)
    rendered = {}
    for page in pages(sources):
        path = root / page.path
        existing = path.read_text(encoding="utf-8") if path.is_file() else None
        rendered[str(page.path)] = splice(existing, page)
    rendered[str(DOCS / "meta-evaluation-report.md")] = report_text(sources)
    return rendered


def orphans(root: Path, rendered: Mapping[str, str]) -> list[str]:
    """Judge and detector pages whose registry entry is gone."""
    found = []
    for directory in ("judges", "detectors"):
        folder = Path(root) / DOCS / directory
        found += [path.relative_to(root).as_posix() for path in sorted(folder.glob("*.md"))
                  if path.relative_to(root).as_posix() not in rendered] if folder.is_dir() else []
    return found


def command_regen(args: argparse.Namespace) -> int:
    root = Path(args.repo_root)
    try:
        rendered = render_all(root)
    except DocsError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    stale = [path for path, text in sorted(rendered.items())
             if not (root / path).is_file() or (root / path).read_text(encoding="utf-8") != text]
    lost = orphans(root, rendered)
    for path in lost:
        print(f"error: {path} has no registry entry; move its prose to its successor's page and delete it",
              file=sys.stderr)
    if args.check:
        for path in stale:
            print(f"error: {STALE_MESSAGE}: {path}", file=sys.stderr)
        if stale:
            print(f"error: {STALE_MESSAGE}; run: python3 scripts/audio_qc_docs.py regen", file=sys.stderr)
        if stale or lost:
            return 1
        print(f"audio-qc docs: {len(rendered)} pages fresh")
        return 0
    for path in stale:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}")
        temporary.write_text(rendered[path], encoding="utf-8")
        os.replace(temporary, target)
        print(f"Rendered {path}")
    if not stale:
        print(f"audio-qc docs: {len(rendered)} pages fresh")
    return 1 if lost else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo-root", type=Path, default=REPO, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    regen = commands.add_parser("regen", help="render the generated blocks and the report")
    regen.add_argument("--check", action="store_true", help="fail when anything is stale; write nothing")
    args = parser.parse_args(argv)
    return command_regen(args)


if __name__ == "__main__":
    raise SystemExit(main())
