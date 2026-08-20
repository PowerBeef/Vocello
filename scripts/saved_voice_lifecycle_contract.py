#!/usr/bin/env python3
"""Fail closed when interactive saved-voice review bypasses staging."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
INTERACTIVE_REVIEW_SOURCES = (
    "Sources/iOS/Voices/IOSRecordVoiceSheet.swift",
    "Sources/iOS/IOSGenerationModeViews.swift",
    "Sources/Views/Library/SavedVoiceSheet.swift",
)


class ContractError(ValueError):
    """Raised when the saved-voice lifecycle becomes commit-before-review."""


def _read(root: Path, relative: str) -> str:
    path = root / relative
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ContractError(f"required saved-voice surface is missing: {relative}") from error


def validate(root: Path) -> None:
    protocol = _read(root, "Sources/QwenVoiceCore/TTSEngine.swift")
    semantic_types = _read(root, "Sources/QwenVoiceCore/SemanticTypes.swift")
    repository = _read(root, "Sources/QwenVoiceCore/PreparedVoiceRepository.swift")
    ios_voices = _read(root, "Sources/iOS/IOSVoicesView.swift")
    engine = _read(root, "Sources/QwenVoiceCore/MLXTTSEngine.swift")
    wire = _read(root, "Sources/QwenVoiceEngineSupport/EngineServiceIPC.swift")
    ios_ui_test = _read(root, "Tests/VocelloiOSUITests/VocelloiOSSavedVoiceLifecycleUITests.swift")
    ui_runner = _read(root, "scripts/ui_test.sh")

    required_protocol_tokens = (
        "preparePreparedVoiceCandidate(",
        "commitPreparedVoiceCandidate(id:",
        "discardPreparedVoiceCandidate(id:",
    )
    for token in required_protocol_tokens:
        if token not in protocol:
            raise ContractError(f"TTSEngine is missing transactional lifecycle token {token!r}")

    candidate_match = re.search(
        r"public struct PreparedVoiceCandidate\b(?P<body>.*?)(?=\n}\n)",
        semantic_types,
        re.DOTALL,
    )
    if candidate_match is None:
        raise ContractError("PreparedVoiceCandidate is missing")
    if "audioPath" in candidate_match.group("body"):
        raise ContractError("PreparedVoiceCandidate must not expose its private staged path")

    for relative in INTERACTIVE_REVIEW_SOURCES:
        text = _read(root, relative)
        if "enrollPreparedVoice(" in text:
            raise ContractError(f"interactive review bypasses candidate staging: {relative}")
        for token in required_protocol_tokens:
            if token not in text:
                raise ContractError(f"interactive review is missing {token!r}: {relative}")
        if re.search(r"try\?\s+await\s+\w+\.deletePreparedVoice", text):
            raise ContractError(f"interactive deletion silently swallows failure: {relative}")

    for token in (
        'appendingPathComponent("voice-candidates"',
        'appendingPathComponent("voice-transactions"',
        "static let candidateLifetime",
        "func reconcile()",
        "CommitTransactionManifest",
        "DeleteTransactionManifest",
        "reconcileCommitTransaction(at:",
        "reconcileDeleteTransaction(at:",
        "Audio is the publication boundary",
    ):
        if token not in repository:
            raise ContractError(f"prepared-voice repository is missing {token!r}")

    for token in (
        "guard !(await activeGenerationCoordinator.hasActiveGeneration)",
        "await runtime.invalidatePreparedVoiceCaches()",
        "requirePreparedVoiceRepository().delete(id: id)",
    ):
        if token not in engine:
            raise ContractError(f"engine deletion lifecycle is missing {token!r}")

    for token in (
        "case preparePreparedVoiceCandidate(",
        "case commitPreparedVoiceCandidate(id:",
        "case discardPreparedVoiceCandidate(id:",
        "case preparedVoiceCandidate(PreparedVoiceCandidate)",
    ):
        if token not in wire:
            raise ContractError(f"XPC lifecycle contract is missing {token!r}")

    for token in (
        '"voicesRowMenu_\\(voice.id)"',
        '"voicesDelete_\\(voice.id)"',
        '"voicesDeleteConfirm_\\(voice.id)"',
        '"voicesPreview_saved_\\(voice.id)"',
        "appModel.playerSheetItem = nil",
        "appModel.voiceCloningDraft.clearReference()",
        "appModel.pendingVoiceCloningHandoff = nil",
    ):
        if token not in ios_voices:
            raise ContractError(f"iOS saved-voice deletion is missing {token!r}")

    for token in (
        "testImportPreviewHandoffAndDeleteSavedVoice",
        'element("voicesPreview_saved_\\(voiceName)")',
        'element("voicesDeleteConfirm_\\(voiceName)")',
        "studioChip_reference",
    ):
        if token not in ios_ui_test:
            raise ContractError(f"iOS saved-voice lifecycle XCUITest is missing {token!r}")
    if '"saved-voice-lifecycle"' not in ui_runner or "VocelloiOSSavedVoiceLifecycleUITests" not in ui_runner:
        raise ContractError("iOS saved-voice lifecycle XCUITest lane is missing")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate",))
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    try:
        validate(args.root.resolve())
    except ContractError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print("Saved-voice lifecycle contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
