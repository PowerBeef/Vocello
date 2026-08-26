#!/usr/bin/env python3
"""Deterministic contract gate for the shipped delivery-instruction copy.

Delivery quality itself needs audio, models, and seeds, so it can never be an
ordinary CI gate. But several ways the copy can be *wrong* are pure text
properties, checkable in milliseconds with nothing loaded -- and until now
nothing checked them. The defect that motivated this gate was exactly that
shape: three presets received 76 characters of English-diction boilerplate on
their ``strong`` tier and not their ``normal`` tier, so the two tiers differed
by unrelated text as well as by emotional wording, confounding every
normal-versus-strong comparison run over them. Every deterministic gate passed
throughout.

The gate also pins every canonical cell digest and validates each versioned localized variant,
its source constant, supported language pair, speaker-metadata authority, dual-match routing,
verbatim custom-text fallback, and hard-safety matrix identity.

Four semantic-text checks follow, in two severities.

Hard failures -- indefensible whatever the right delivery copy turns out to be:

* ``diction-append-parity``  both intensity tiers of one preset must reach the
  same English-diction append decision. The append says nothing about
  intensity, so letting it vary across tiers injects a confound into the one
  comparison the tier exists to support.
* ``repeated-intensifier``   ``very very`` style repetition. The one part of the
  old house style that upstream's own examples support: single intensifiers are
  fine (``Very happy.``), repetition adds nothing.

Acknowledged findings -- real conflicts whose *resolution* is unknown, so the
gate enumerates them rather than forcing a blind edit:

* ``tier-direction-inversion``  a preset asks for opposite directions on the
  same scalar axis across its tiers (angry: "a lower clipped tone" at normal,
  "heated raised pitch" at strong). As an intensity ladder that is incoherent
  -- strong should push normal's axes harder, not invert them.
* ``expectation-conflict``      the copy states a direction that contradicts the
  same preset's delivery expectation in the versioned prosody profile.

The second pair is reported against ``config/delivery-instruction-contract.json``.
A finding in that file is a known-open issue and passes; a finding that is not
fails; an acknowledgement matching no current finding also fails, so the list
cannot rot. Crucially the gate never asserts that the copy must *conform* to an
expectation: those expectations were seeded before the project had any
voice-quality measurement, so a conformance gate would fit copy to an
unvalidated target. It reports that the two disagree and that one of them is
wrong, without presuming which.

Usage:
    python3 scripts/check_delivery_instructions.py [--root DIR] [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

PRESET_SOURCE = "Sources/QwenVoiceCore/EmotionPreset.swift"
SEMANTICS_SOURCE = "Sources/QwenVoiceCore/GenerationSemantics.swift"
CONTRACT_PATH = "config/delivery-instruction-contract.json"
SPEAKER_CONTRACT_PATH = "Sources/Resources/qwenvoice_contract.json"
SUPPORTED_INSTRUCTION_LANGUAGES = {"english", "mandarin"}

# Multi-word phrases only, so incidental words ("wide swings between low and
# high") cannot register a direction. A tier that states no direction on an axis
# is silent, never neutral -- inversion needs both tiers to speak and disagree.
AXIS_PHRASES = {
    "pitch": {
        1: [
            "raised pitch", "higher pitch", "lifted pitch", "high pitch",
            "high-pitched", "pitch rising", "rising pitch", "pitch leaps",
            "upward pitch", "high-mid pitch", "pitch up",
        ],
        -1: [
            "lower pitch", "lowered pitch", "low pitch", "lower clipped",
            "low settled pitch", "downward inflection", "deeper pitch",
            "lower tone", "lowered tone",
        ],
    },
    "rate": {
        1: ["fast", "quick", "racing", "brisk", "rapid", "accelerat", "driving pace"],
        -1: ["slow", "unhurried", "measured pacing", "deliberate pace", "very slow"],
    },
    "volume": {
        1: ["louder", "loud ", "projected volume", "strong projected", "raised volume"],
        -1: ["quiet", "hushed", "barely voiced", "softly", "soft and"],
    },
}

# Delivery-expectation features that state a direction on one of the axes above.
# Variation and composite features (pitch_variation_delta_hz, arousal_score)
# describe spread or a blend, not a level, so no copy phrase maps onto them.
EXPECTATION_AXIS = {"pitch_shift_semitones": "pitch"}

INTENSIFIERS = ["very", "really", "extremely", "so", "super"]


class ContractError(RuntimeError):
    """Raised when the sources or the contract file cannot be read as expected."""


def _swift_string_constants(source: str) -> dict[str, str]:
    """Every `static let NAME = "literal"` in a Swift source."""
    pattern = re.compile(
        r'static\s+let\s+(\w+)\s*=\s*\n?\s*"((?:[^"\\]|\\.)*)"'
    )
    return {name: _unescape(body) for name, body in pattern.findall(source)}


def _unescape(body: str) -> str:
    return body.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n")


_PRESET_RE = re.compile(
    r'id:\s*"(?P<id>[a-z]+)".*?'
    r'\.normal:\s*(?P<normal>EmotionPreset\.\w+|"(?:[^"\\]|\\.)*").*?'
    r'\.strong:\s*(?P<strong>EmotionPreset\.\w+|"(?:[^"\\]|\\.)*")',
    re.S,
)


def load_presets(root: pathlib.Path) -> dict[str, dict[str, str]]:
    """Parse the shipped presets as {preset_id: {tier: instruction}}."""
    path = root / PRESET_SOURCE
    if not path.exists():
        raise ContractError(f"missing preset source: {PRESET_SOURCE}")
    source = path.read_text(encoding="utf-8")
    constants = _swift_string_constants(source)

    def resolve(raw: str, preset_id: str, tier: str) -> str:
        if raw.startswith("EmotionPreset."):
            name = raw.split(".", 1)[1]
            if name not in constants:
                raise ContractError(
                    f"{preset_id}.{tier} references unknown constant '{name}'"
                )
            return constants[name]
        return _unescape(raw[1:-1])

    presets: dict[str, dict[str, str]] = {}
    for match in _PRESET_RE.finditer(source):
        preset_id = match.group("id")
        presets[preset_id] = {
            tier: resolve(match.group(tier), preset_id, tier)
            for tier in ("normal", "strong")
        }
    if not presets:
        raise ContractError(
            f"parsed zero presets from {PRESET_SOURCE}; the gate must not pass vacuously"
        )
    return presets


PRESET_WIDE_SET = "presetInstructionsSuppressingDictionReinforcement"


def load_diction_rule(root: pathlib.Path) -> tuple[str, list[str], bool]:
    """The reinforcement sentence, its suppression tokens, and how they resolve.

    ``preset_wide`` is True when ``englishDictionReinforcedInstruction`` consults
    the preset-wide suppression set, which is what keeps a preset's two tiers on
    the same append decision. Deleting that consult silently reintroduces the
    per-tier asymmetry this gate exists to prevent, so it is read from the code
    rather than assumed.
    """
    path = root / SEMANTICS_SOURCE
    if not path.exists():
        raise ContractError(f"missing semantics source: {SEMANTICS_SOURCE}")
    source = path.read_text(encoding="utf-8")
    constants = _swift_string_constants(source)
    reinforcement = constants.get("englishDictionReinforcement")
    if not reinforcement:
        raise ContractError(
            "englishDictionReinforcement not found; the gate would silently stop checking"
        )
    block = re.search(
        r"dictionTokens\s*=\s*\[(.*?)\]", source, re.S
    )
    if not block:
        raise ContractError("dictionTokens list not found in GenerationSemantics")
    tokens = re.findall(r'"([^"]+)"', block.group(1))
    if not tokens:
        raise ContractError("dictionTokens list parsed empty")

    body = re.search(
        r"func\s+englishDictionReinforcedInstruction\b.*?\n    \}",
        source,
        re.S,
    )
    if not body:
        raise ContractError("englishDictionReinforcedInstruction body not found")
    preset_wide = PRESET_WIDE_SET in body.group(0)
    return reinforcement, tokens, preset_wide


def appends_reinforcement(instruction: str, tokens: list[str]) -> bool:
    lowered = instruction.lower()
    return not any(token in lowered for token in tokens)


def effective_append_decisions(
    tiers: dict[str, str], tokens: list[str], preset_wide: bool
) -> dict[str, bool]:
    """What each tier actually ships, under the rule the code implements today."""
    per_string = {
        tier: appends_reinforcement(text, tokens) for tier, text in tiers.items()
    }
    if preset_wide and not all(per_string.values()):
        # One tier asks for clarity, so the whole preset suppresses.
        return {tier: False for tier in per_string}
    return per_string


def axis_direction(instruction: str, axis: str) -> int | None:
    """+1, -1, or None when the instruction states no direction on this axis."""
    lowered = instruction.lower()
    directions = {
        sign for sign, phrases in AXIS_PHRASES[axis].items()
        if any(phrase in lowered for phrase in phrases)
    }
    if len(directions) != 1:
        # Silent, or self-conflicting within one string; the latter is reported
        # by the inversion check only when the *tiers* disagree.
        return None
    return directions.pop()


def repeated_intensifier(instruction: str) -> str | None:
    lowered = instruction.lower()
    for word in INTENSIFIERS:
        if re.search(rf"\b{word}\s*,?\s+{word}\b", lowered):
            return word
    return None


def find_findings(presets, diction_tokens, expectations, preset_wide=True) -> list[dict]:
    """Every current finding, hard and acknowledged alike."""
    findings: list[dict] = []
    for preset_id in sorted(presets):
        tiers = presets[preset_id]

        decisions = effective_append_decisions(tiers, diction_tokens, preset_wide)
        if len(set(decisions.values())) > 1:
            appended = sorted(t for t, v in decisions.items() if v)
            suppressed = sorted(t for t, v in decisions.items() if not v)
            findings.append({
                "check": "diction-append-parity",
                "severity": "error",
                "preset": preset_id,
                "detail": (
                    f"tier(s) {', '.join(appended)} receive the English diction append and "
                    f"{', '.join(suppressed)} do not, so the tiers differ by boilerplate "
                    "as well as by emotional wording"
                ),
            })

        for tier, text in sorted(tiers.items()):
            word = repeated_intensifier(text)
            if word:
                findings.append({
                    "check": "repeated-intensifier",
                    "severity": "error",
                    "preset": preset_id,
                    "tier": tier,
                    "detail": f"repeated intensifier '{word}'; repetition adds nothing",
                })

        for axis in sorted(AXIS_PHRASES):
            normal = axis_direction(tiers["normal"], axis)
            strong = axis_direction(tiers["strong"], axis)
            if normal is not None and strong is not None and normal != strong:
                findings.append({
                    "check": "tier-direction-inversion",
                    "severity": "acknowledged",
                    "preset": preset_id,
                    "axis": axis,
                    "detail": (
                        f"{axis} direction inverts across tiers "
                        f"(normal {normal:+d}, strong {strong:+d}); strong should push "
                        "normal's axes harder, not reverse them"
                    ),
                })

        for feature, axis in sorted(EXPECTATION_AXIS.items()):
            spec = expectations.get(preset_id, {}).get(feature)
            if not spec:
                continue
            expected = spec["direction"]
            for tier, text in sorted(tiers.items()):
                stated = axis_direction(text, axis)
                if stated is not None and stated != expected:
                    findings.append({
                        "check": "expectation-conflict",
                        "severity": "acknowledged",
                        "preset": preset_id,
                        "tier": tier,
                        "axis": axis,
                        "detail": (
                            f"copy states {axis} {stated:+d} but the {spec['tier']} "
                            f"expectation '{feature}' is {expected:+d}; one of them is "
                            "wrong and the gate does not presume which"
                        ),
                    })
    return findings


def finding_key(finding: dict) -> str:
    parts = [finding["check"], finding["preset"]]
    for extra in ("tier", "axis"):
        if extra in finding:
            parts.append(finding[extra])
    return "/".join(parts)


def load_contract(root: pathlib.Path) -> dict:
    path = root / CONTRACT_PATH
    if not path.exists():
        raise ContractError(f"missing contract: {CONTRACT_PATH}")
    with path.open(encoding="utf-8") as handle:
        contract = json.load(handle)
    if not isinstance(contract, dict):
        raise ContractError(f"{CONTRACT_PATH} must be a JSON object")
    if contract.get("schemaVersion") != 2:
        raise ContractError(f"{CONTRACT_PATH}.schemaVersion must be 2")
    acknowledged = contract.get("acknowledgedFindings")
    if not isinstance(acknowledged, list):
        raise ContractError(f"{CONTRACT_PATH}.acknowledgedFindings must be a list")
    for entry in acknowledged:
        missing = {"key", "why", "opened", "resolveWith"} - set(entry)
        if missing:
            raise ContractError(
                f"{CONTRACT_PATH} entry {entry.get('key', '?')} missing {sorted(missing)}"
            )
    return contract


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_versioned_instructions(
    root: pathlib.Path,
    contract: dict,
    presets: dict[str, dict[str, str]],
) -> dict:
    """Validate exact cell digests and every registered localized variant."""
    expected_cells = {
        f"{preset_id}.{tier}": instruction
        for preset_id, tiers in presets.items()
        for tier, instruction in tiers.items()
    }
    digests = contract.get("canonicalInstructionDigests")
    if not isinstance(digests, dict) or set(digests) != set(expected_cells):
        raise ContractError(
            f"{CONTRACT_PATH}.canonicalInstructionDigests must exactly cover all delivery cells"
        )
    for cell_id, instruction in expected_cells.items():
        expected_digest = _sha256(instruction)
        if digests.get(cell_id) != expected_digest:
            raise ContractError(
                f"{CONTRACT_PATH} digest drift for {cell_id}: expected {expected_digest}"
            )

    source_path = root / PRESET_SOURCE
    source_constants = _swift_string_constants(source_path.read_text(encoding="utf-8"))
    variants = contract.get("localizedInstructionVariants")
    if not isinstance(variants, list) or not variants:
        raise ContractError(f"{CONTRACT_PATH}.localizedInstructionVariants must be non-empty")
    identities: set[tuple[str, str]] = set()
    for variant in variants:
        if not isinstance(variant, dict):
            raise ContractError("localized instruction variant must be an object")
        version = variant.get("version")
        cell_id = variant.get("cellID")
        if not isinstance(version, str) or not version or cell_id not in expected_cells:
            raise ContractError("localized instruction variant has invalid version or cellID")
        identity = (version, cell_id)
        if identity in identities:
            raise ContractError(f"duplicate localized instruction variant {version}/{cell_id}")
        identities.add(identity)

        languages = variant.get("languages")
        if not isinstance(languages, list):
            raise ContractError(f"{version}/{cell_id} languages must be a list")
        language_ids = [entry.get("id") for entry in languages if isinstance(entry, dict)]
        if len(language_ids) != len(languages) or len(language_ids) != len(set(language_ids)):
            raise ContractError(f"{version}/{cell_id} has duplicate or malformed languages")
        unsupported = set(language_ids) - SUPPORTED_INSTRUCTION_LANGUAGES
        if unsupported:
            raise ContractError(
                f"{version}/{cell_id} has unsupported instruction language(s): {sorted(unsupported)}"
            )
        missing = SUPPORTED_INSTRUCTION_LANGUAGES - set(language_ids)
        if missing:
            raise ContractError(
                f"{version}/{cell_id} is missing translation(s): {sorted(missing)}"
            )
        resolved: dict[str, str] = {}
        for entry in languages:
            constant = entry.get("sourceConstant")
            if not isinstance(constant, str) or constant not in source_constants:
                raise ContractError(
                    f"{version}/{cell_id}/{entry.get('id')} references unknown source constant"
                )
            instruction = source_constants[constant]
            if entry.get("digest") != _sha256(instruction):
                raise ContractError(
                    f"{version}/{cell_id}/{entry.get('id')} digest does not match source"
                )
            resolved[entry["id"]] = instruction
        if resolved["english"] != expected_cells[cell_id]:
            raise ContractError(
                f"{version}/{cell_id} English variant must equal the canonical shipped cell"
            )

        routing = variant.get("routing")
        exact_routing = {
            "mode": "custom",
            "requiresNativeLanguage": "Chinese",
            "requiresOutputLanguage": "chinese",
            "speakerMetadataSource": SPEAKER_CONTRACT_PATH,
            "fallbackLanguage": "english",
            "customTextBehavior": "verbatim",
        }
        if routing != exact_routing:
            raise ContractError(f"{version}/{cell_id} dual-match routing contract drifted")

    speaker_contract = root / SPEAKER_CONTRACT_PATH
    try:
        speaker_payload = json.loads(speaker_contract.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"could not load {SPEAKER_CONTRACT_PATH}: {error}") from error
    groups = speaker_payload.get("speakers")
    metadata = speaker_payload.get("speakerMetadata")
    if not isinstance(groups, dict) or not isinstance(metadata, dict):
        raise ContractError(f"{SPEAKER_CONTRACT_PATH} is missing speaker metadata")
    roster = [speaker for members in groups.values() for speaker in members]
    if len(roster) != len(set(roster)) or set(roster) != set(metadata):
        raise ContractError("speaker-language routing requires unique metadata for every speaker")
    if not any(
        str(row.get("nativeLanguage", "")).lower() == "chinese"
        for row in metadata.values()
    ):
        raise ContractError("speaker contract has no registered Chinese-native speaker")

    safety = contract.get("safetyMatrix")
    if not isinstance(safety, dict):
        raise ContractError(f"{CONTRACT_PATH}.safetyMatrix must be an object")
    required_safety = {
        "runner": "scripts/angry_bilingual_safety_matrix.py",
        "tests": "scripts/tests/test_angry_bilingual_safety_matrix.py",
        "fixedSeeds": [32060826, 32060827, 32060828, 32060829],
        "requiredTakeCount": 36,
        "authority": "hard-failure-and-routing-safety-only",
    }
    if safety != required_safety:
        raise ContractError(f"{CONTRACT_PATH}.safetyMatrix drifted")
    for path_key in ("runner", "tests"):
        if not (root / safety[path_key]).is_file():
            raise ContractError(f"missing safety-matrix surface: {safety[path_key]}")
    return {"canonicalCells": len(expected_cells), "localizedVariants": len(variants)}


def evaluate(root: pathlib.Path) -> dict:
    sys.path.insert(0, str(root / "scripts"))
    import prosody_profile

    expectations = prosody_profile.BUILTIN_PROFILE["delivery_expectations"]["presets"]
    presets = load_presets(root)
    _, diction_tokens, preset_wide = load_diction_rule(root)
    findings = find_findings(presets, diction_tokens, expectations, preset_wide)

    contract = load_contract(root)
    versioned = validate_versioned_instructions(root, contract, presets)
    acknowledged = {entry["key"]: entry for entry in contract["acknowledgedFindings"]}
    current = {finding_key(f): f for f in findings}

    errors = [f for f in findings if f["severity"] == "error"]
    unacknowledged = [
        f for f in findings
        if f["severity"] == "acknowledged" and finding_key(f) not in acknowledged
    ]
    stale = sorted(set(acknowledged) - set(current))

    return {
        "presets": len(presets),
        "findings": findings,
        "errors": errors,
        "unacknowledged": unacknowledged,
        "staleAcknowledgements": stale,
        "acknowledged": [f for f in findings if finding_key(f) in acknowledged],
        "versionedInstructions": versioned,
        "ok": not errors and not unacknowledged and not stale,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(REPO_ROOT), help="repository root")
    parser.add_argument("--json", action="store_true", help="emit the full report as JSON")
    args = parser.parse_args(argv)

    try:
        report = evaluate(pathlib.Path(args.root).resolve())
    except ContractError as error:
        print(f"delivery-instruction contract error: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1

    for finding in report["errors"] + report["unacknowledged"]:
        label = "error" if finding["severity"] == "error" else "unacknowledged"
        print(
            f"delivery-instruction {label}: {finding_key(finding)} -- {finding['detail']}",
            file=sys.stderr,
        )
    for key in report["staleAcknowledgements"]:
        print(
            f"delivery-instruction stale acknowledgement: {key} no longer occurs; "
            f"remove it from {CONTRACT_PATH}",
            file=sys.stderr,
        )

    if not report["ok"]:
        if report["unacknowledged"]:
            print(
                f"\nA new conflict must be fixed or acknowledged in {CONTRACT_PATH} "
                "with a reason and a way to resolve it.",
                file=sys.stderr,
            )
        return 1

    known = len(report["acknowledged"])
    suffix = f", {known} acknowledged open finding(s)" if known else ""
    variants = report["versionedInstructions"]["localizedVariants"]
    print(
        f"Delivery instruction contract: PASS ({report['presets']} presets, "
        f"{variants} localized variant(s){suffix})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
