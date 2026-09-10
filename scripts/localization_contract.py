#!/usr/bin/env python3
"""Validate Vocello's String Catalog, typed presentation, and literal baseline."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import plistlib
from pathlib import Path
import re
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG = Path("Sources/Resources/Localizable.xcstrings")
BASELINE = Path("config/localization-unlocalized-baseline.json")
PRESENTATION_SOURCE = Path("Sources/SharedSupport/Services/VocelloPresentationText.swift")
UI_TEST_SOURCE = Path("Tests/VocelloiOSUITests/VocelloiOSSmokeUITests.swift")
MAC_UI_TEST_SOURCE = Path("Tests/VocelloMacUITests/VocelloMacSmokeUITests.swift")
SCAN_ROOTS = (Path("Sources/iOS"), Path("Sources/Views"), Path("Sources/SharedSupport"))
ALLOWED_CALLS = {
    "Text", "Button", "Label", "Toggle", "Picker", "Section", "GroupBox", "Link",
    "navigationTitle", "alert", "confirmationDialog", "accessibilityLabel", "accessibilityHint",
}
CALL_PATTERN = re.compile(
    r"\b(?P<call>Text|Button|Label|Toggle|Picker|Section|GroupBox|Link|navigationTitle|"
    r"alert|confirmationDialog|accessibilityLabel|accessibilityHint)\s*\(\s*"
    r'"(?P<literal>(?:\\.|[^"\\])*)"',
    re.MULTILINE,
)
REQUIRED_SETTINGS = (
    "LOCALIZATION_PREFERS_STRING_CATALOGS",
    "STRING_CATALOG_GENERATE_SYMBOLS",
    "SWIFT_EMIT_LOC_STRINGS",
)
REQUIRED_KEYS = {
    "vocello.error.cancellation_not_finished",
    "vocello.error.cloning_consent_required",
    "vocello.error.install_model",
    "vocello.error.long_form_planning_failed",
    "vocello.error.reference_audio_required",
    "vocello.history.export_recovery_files",
    "vocello.history.long_form_recovery_detail",
    "vocello.history.recovery_export_failure",
    "vocello.long_form.segment_history_failed",
    "vocello.models.ready_count",
    "vocello.status.checking_downloaded_files",
    "vocello.status.generation_failed",
    "vocello.status.making_model_available_offline",
    "vocello.status.ready",
}
REQUIRED_PLURAL_KEYS = {
    "vocello.models.ready_count",
    "vocello.history.recovery_export_failure",
}
REQUIRED_LOCALES = ("en", "fr")
# UI identifiers, deliberately separate from the model's spoken-language enum.
SUPPORTED_UI_LOCALES = {"en", "fr", "es", "de", "it", "pt-BR", "zh-Hans", "ja", "ko", "ru"}
FORMAT_ARGUMENT = re.compile(
    r"%(?:(?P<position>[1-9][0-9]*)\$)?(?P<type>@|lld|llu|ld|lu|d|u|f|g|s)"
)


def _format_arguments(value: str) -> Counter[tuple[int, str]]:
    """Compare argument identity/type while allowing positional reordering."""
    arguments: Counter[tuple[int, str]] = Counter()
    for ordinal, match in enumerate(FORMAT_ARGUMENT.finditer(value.replace("%%", "")), 1):
        arguments[(int(match.group("position") or ordinal), match.group("type"))] += 1
    return arguments


def _translation_units(payload: dict[str, Any], label: str) -> dict[str, str]:
    variations = payload.get("variations", {})
    if not isinstance(variations, dict):
        raise ContractError(f"{label} has malformed variations")
    plural = variations.get("plural")
    variants = plural if isinstance(plural, dict) else {"value": payload}
    if plural is not None and (not isinstance(plural, dict) or not {"one", "other"} <= plural.keys()):
        raise ContractError(f"{label} requires plural one and other")
    result = {}
    for category, variant in variants.items():
        unit = variant.get("stringUnit", {}) if isinstance(variant, dict) else {}
        value = unit.get("value") if isinstance(unit, dict) else None
        if not isinstance(value, str) or not value.strip() or unit.get("state") != "translated":
            raise ContractError(f"{label} requires a non-empty translated {category}")
        result[category] = value
    return result


def _validate_translations(entry: dict[str, Any], key: str, locales=REQUIRED_LOCALES) -> None:
    localizations = entry["localizations"]
    unknown = set(localizations) - SUPPORTED_UI_LOCALES
    if unknown:
        raise ContractError(f"{key} has unsupported UI locales: {sorted(unknown)}")
    english = _translation_units(localizations["en"], f"{key} en")
    for locale in set(locales) | set(localizations):
        payload = localizations.get(locale)
        if not isinstance(payload, dict):
            raise ContractError(f"{key} missing required localization {locale}")
        translated = _translation_units(payload, f"{key} {locale}")
        if ("value" in english) != ("value" in translated):
            raise ContractError(f"{key} {locale} must preserve plural structure")
        for category, value in translated.items():
            original = english.get(category, english.get("other", ""))
            if _format_arguments(original) != _format_arguments(value):
                raise ContractError(f"{key} {locale} {category} format arguments differ from English")


def _validate_permission_catalog(root: Path) -> None:
    path = Path("Sources/iOS/InfoPlist.xcstrings")
    catalog = _read_json(root, path)
    info = plistlib.loads(_read_text(root, Path("Sources/iOS/Info.plist")).encode())
    required = {"NSMicrophoneUsageDescription", "NSSpeechRecognitionUsageDescription"}
    if catalog.get("sourceLanguage") != "en" or catalog.get("version") != "1.0":
        raise ContractError("permission catalog must use English source and version 1.0")
    if set(catalog.get("strings", {})) != required:
        raise ContractError("permission catalog must contain exactly the two declared purpose strings")
    for key, entry in catalog["strings"].items():
        _validate_translations(entry, key, _bundled_catalog_locales(_read_json(root, CATALOG)))
        if entry["localizations"]["en"]["stringUnit"]["value"] != info[key]:
            raise ContractError(f"{key} must preserve the Info.plist purpose string")
    body = _target_body(_read_text(root, Path("project.yml")), "VocelloiOS")
    if "- path: Sources/iOS/InfoPlist.xcstrings\n        buildPhase: resources" not in body:
        raise ContractError("VocelloiOS must explicitly bundle the permission catalog")


class ContractError(ValueError):
    """Raised when localization governance is incomplete or inconsistent."""


def _read_text(root: Path, relative: Path) -> str:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ContractError(f"required localization surface is missing: {relative}") from error


def _read_json(root: Path, relative: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_text(root, relative))
    except json.JSONDecodeError as error:
        raise ContractError(f"invalid JSON in {relative}: {error}") from error
    if not isinstance(value, dict):
        raise ContractError(f"{relative} must contain a JSON object")
    return value


def _target_body(manifest: str, target_name: str) -> str:
    header = re.compile(rf"^  {re.escape(target_name)}:[ \t]*$", re.MULTILINE)
    matches = list(header.finditer(manifest))
    target_bodies: list[str] = []
    for match in matches:
        start = match.end()
        next_header = re.search(r"^  [A-Za-z0-9_.-]+:[ \t]*$", manifest[start:], re.MULTILINE)
        end = start + next_header.start() if next_header else len(manifest)
        body = manifest[start:end]
        if re.search(r"^    type:[ \t]*", body, re.MULTILINE):
            target_bodies.append(body)
    if len(target_bodies) != 1:
        raise ContractError(
            f"project.yml must define target {target_name} exactly once "
            f"(found {len(target_bodies)})"
        )
    return target_bodies[0]


def _validate_manifest(root: Path) -> None:
    manifest = _read_text(root, Path("project.yml"))
    for setting in REQUIRED_SETTINGS:
        matches = re.findall(rf"^[ \t]+{setting}:[ \t]*YES[ \t]*$", manifest, re.MULTILINE)
        if len(matches) != 1:
            raise ContractError(f"project.yml must set {setting}: YES exactly once")

    catalog_entry = "- path: Sources/Resources/Localizable.xcstrings"
    ios_body = _target_body(manifest, "VocelloiOS")
    if ios_body.count(catalog_entry) != 1 or "buildPhase: resources" not in ios_body:
        raise ContractError("VocelloiOS must bundle Localizable.xcstrings as a sources resource")
    for target in ("VocelloCLI", "QwenVoiceEngineService"):
        if catalog_entry in _target_body(manifest, target):
            raise ContractError(f"Localizable.xcstrings must not be attached to {target}")


def _english_payload(entry: dict[str, Any], key: str) -> dict[str, Any]:
    localizations = entry.get("localizations")
    if not isinstance(localizations, dict) or not isinstance(localizations.get("en"), dict):
        raise ContractError(f"catalog key {key} is missing its English localization")
    return localizations["en"]


def _bundled_catalog_locales(catalog: dict[str, Any]) -> set[str]:
    locales = set(REQUIRED_LOCALES)
    for entry in catalog.get("strings", {}).values():
        if isinstance(entry, dict):
            locales.update(entry.get("localizations", {}))
    return locales


def _validate_catalog(root: Path) -> None:
    catalog = _read_json(root, CATALOG)
    if catalog.get("sourceLanguage") != "en" or catalog.get("version") != "1.0":
        raise ContractError("Localizable.xcstrings must use sourceLanguage en and version 1.0")
    strings = catalog.get("strings")
    if not isinstance(strings, dict):
        raise ContractError("Localizable.xcstrings strings must be an object")
    missing = sorted(REQUIRED_KEYS - strings.keys())
    if missing:
        raise ContractError(f"Localizable.xcstrings is missing required keys: {missing}")

    for key, raw_entry in strings.items():
        if not isinstance(raw_entry, dict):
            raise ContractError(f"catalog key {key} must be an object")
        if raw_entry.get("extractionState") != "manual":
            continue
        comment = raw_entry.get("comment")
        if not isinstance(comment, str) or not comment.strip():
            raise ContractError(f"manual catalog key {key} requires translator context")
        english = _english_payload(raw_entry, key)
        variations = english.get("variations", {})
        if not isinstance(variations, dict):
            raise ContractError(f"catalog key {key} has malformed English variations")
        if key in REQUIRED_PLURAL_KEYS or "plural" in variations:
            plural = variations.get("plural", {})
            if not isinstance(plural, dict):
                raise ContractError(f"{key} requires English plural categories")
            for category in ("one", "other"):
                variant = plural.get(category, {})
                unit = variant.get("stringUnit", {}) if isinstance(variant, dict) else {}
                value = unit.get("value") if isinstance(unit, dict) else None
                if not isinstance(value, str) or not value.strip():
                    raise ContractError(f"{key} requires non-empty English plural {category}")
        else:
            value = english.get("stringUnit", {}).get("value")
            if not isinstance(value, str) or not value.strip():
                raise ContractError(f"catalog key {key} requires a non-empty English value")
        _validate_translations(raw_entry, key, _bundled_catalog_locales(catalog))


def _validate_typed_presentation(root: Path) -> None:
    source = _read_text(root, PRESENTATION_SOURCE)
    for key in sorted(REQUIRED_KEYS):
        if f'localized: "{key}"' not in source:
            raise ContractError(f"typed presentation source does not reference {key}")

    expected_uses = {
        Path("Sources/iOS/IOSGenerationModeViews.swift"): (
            "IOSAppLanguage.shared.presentation.installModel",
            "IOSAppLanguage.shared.presentation.longFormPlanningFailed",
            "IOSAppLanguage.shared.presentation.cloningConsentRequired",
            "IOSAppLanguage.shared.presentation.referenceAudioRequired",
        ),
        Path("Sources/iOS/Studio/StudioGenerationCoordinator.swift"): (
            "IOSAppLanguage.shared.presentation.cancellationCouldNotFinish",
        ),
        Path("Sources/iOS/IOSSettingsViews.swift"): (
            "IOSAppLanguage.shared.presentation.status(.ready)",
        ),
        Path("Sources/iOSSupport/Services/IOSModelProgressPresentation.swift"): (
            "VocelloPresentationText.status(.checkingDownloadedFiles)",
            "VocelloPresentationText.status(.makingModelAvailableOffline)",
        ),
    }
    for path, needles in expected_uses.items():
        text = _read_text(root, path)
        for needle in needles:
            if needle not in text:
                raise ContractError(f"{path} must use typed presentation value {needle}")


def scan_unlocalized_literals(root: Path) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str, str]] = Counter()
    for scan_root in SCAN_ROOTS:
        absolute_root = root / scan_root
        if not absolute_root.is_dir():
            raise ContractError(f"localization scan root is missing: {scan_root}")
        for path in sorted(absolute_root.rglob("*.swift")):
            relative = path.relative_to(root).as_posix()
            text = path.read_text(encoding="utf-8")
            for match in CALL_PATTERN.finditer(text):
                literal = match.group("literal")
                digest = hashlib.sha256(literal.encode("utf-8")).hexdigest()
                counts[(relative, match.group("call"), digest)] += 1
    return [
        {"path": path, "call": call, "literalSha256": digest, "count": count}
        for (path, call, digest), count in sorted(counts.items())
    ]


def _baseline_document(root: Path) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "scope": [path.as_posix() for path in SCAN_ROOTS],
        "scanner": "swift-direct-presentation-literals-v1",
        "records": scan_unlocalized_literals(root),
    }


def write_snapshot(root: Path, output: Path) -> None:
    destination = output if output.is_absolute() else root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_baseline_document(root), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def _record_identity(record: Any, label: str) -> tuple[tuple[str, str, str], int]:
    if not isinstance(record, dict):
        raise ContractError(f"{label} record must be an object")
    path = record.get("path")
    call = record.get("call")
    digest = record.get("literalSha256")
    count = record.get("count")
    if not isinstance(path, str) or path.startswith("/") or ".." in Path(path).parts:
        raise ContractError(f"{label} record has an invalid repository-relative path")
    if call not in ALLOWED_CALLS:
        raise ContractError(f"{label} record has an invalid presentation call")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ContractError(f"{label} record has an invalid literal digest")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ContractError(f"{label} record has an invalid count")
    return (path, call, digest), count


def _validate_literal_baseline(root: Path) -> int:
    baseline = _read_json(root, BASELINE)
    if baseline.get("schemaVersion") != 1:
        raise ContractError("localization literal baseline schemaVersion must be 1")
    if baseline.get("scope") != [path.as_posix() for path in SCAN_ROOTS]:
        raise ContractError("localization literal baseline scope does not match the scanner")
    if baseline.get("scanner") != "swift-direct-presentation-literals-v1":
        raise ContractError("localization literal baseline scanner identity is unsupported")
    raw_records = baseline.get("records")
    if not isinstance(raw_records, list):
        raise ContractError("localization literal baseline records must be an array")

    allowed: dict[tuple[str, str, str], int] = {}
    for record in raw_records:
        identity, count = _record_identity(record, "baseline")
        if identity in allowed:
            raise ContractError("localization literal baseline contains a duplicate identity")
        allowed[identity] = count

    current = scan_unlocalized_literals(root)
    additions: list[str] = []
    for record in current:
        identity, count = _record_identity(record, "current")
        allowed_count = allowed.get(identity, 0)
        if count > allowed_count:
            additions.append(f"{identity[0]} {identity[1]} (+{count - allowed_count})")
    if additions:
        joined = ", ".join(additions[:12])
        raise ContractError(
            "new direct user-facing literals must use typed localization or be deliberately "
            f"baselined after review: {joined}"
        )
    return sum(record["count"] for record in current)


def _validate_pseudo_localization(root: Path) -> None:
    text = _read_text(root, UI_TEST_SOURCE)
    required = (
        "UICTContentSizeCategoryAccessibilityXXXL",
        "-NSDoubleLocalizedStrings",
        "-NSShowNonLocalizedStrings",
        "Pseudo-AX-XXXL",
    )
    for value in required:
        if value not in text:
            raise ContractError(f"physical-device pseudo-localization walk is missing {value}")
    mac_text = _read_text(root, MAC_UI_TEST_SOURCE)
    for value in ("-NSDoubleLocalizedStrings", "-NSShowNonLocalizedStrings"):
        if value not in mac_text:
            raise ContractError(f"macOS pseudo-localization smoke is missing {value}")


def validate(root: Path) -> int:
    _validate_manifest(root)
    _validate_catalog(root)
    _validate_permission_catalog(root)
    _validate_typed_presentation(root)
    _validate_pseudo_localization(root)
    return _validate_literal_baseline(root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--output", type=Path, default=BASELINE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "snapshot":
            write_snapshot(root, args.output)
            print(f"Localization literal baseline: WROTE {args.output}")
            return 0
        literal_count = validate(root)
    except ContractError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Localization contract: PASS ({literal_count} direct literals baselined)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
