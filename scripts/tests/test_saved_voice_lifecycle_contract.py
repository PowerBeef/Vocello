#!/usr/bin/env python3
"""Tests for the transactional saved-voice lifecycle contract."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import saved_voice_lifecycle_contract  # noqa: E402


class SavedVoiceLifecycleContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for relative in (
            "Sources/QwenVoiceCore/TTSEngine.swift",
            "Sources/QwenVoiceCore/SemanticTypes.swift",
            "Sources/QwenVoiceCore/PreparedVoiceRepository.swift",
            "Sources/QwenVoiceCore/MLXTTSEngine.swift",
            "Sources/QwenVoiceEngineSupport/EngineServiceIPC.swift",
            "Sources/iOS/Voices/IOSRecordVoiceSheet.swift",
            "Sources/iOS/IOSGenerationInputControls.swift",
            "Sources/iOS/IOSGenerationModeViews.swift",
            "Sources/iOS/App/RootView.swift",
            "Sources/iOS/Sheets/IOSBottomSheets.swift",
            "Sources/SharedSupport/Services/ReferenceTranscriptionReviewState.swift",
            "Sources/Views/Library/SavedVoiceSheet.swift",
            "Sources/iOS/IOSVoicesView.swift",
            "Tests/VocelloiOSUITests/VocelloiOSSavedVoiceLifecycleUITests.swift",
            "scripts/ui_test.sh",
        ):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_current_repository_passes(self) -> None:
        saved_voice_lifecycle_contract.validate(self.root)

    def test_direct_interactive_enrollment_fails(self) -> None:
        path = self.root / "Sources/iOS/Voices/IOSRecordVoiceSheet.swift"
        path.write_text(path.read_text(encoding="utf-8") + "\nenrollPreparedVoice(\n", encoding="utf-8")
        with self.assertRaisesRegex(saved_voice_lifecycle_contract.ContractError, "bypasses"):
            saved_voice_lifecycle_contract.validate(self.root)

    def test_missing_discard_path_fails(self) -> None:
        path = self.root / "Sources/Views/Library/SavedVoiceSheet.swift"
        text = path.read_text(encoding="utf-8").replace(
            "discardPreparedVoiceCandidate(id:",
            "discardCandidateRemoved(id:",
        )
        path.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(saved_voice_lifecycle_contract.ContractError, "missing"):
            saved_voice_lifecycle_contract.validate(self.root)

    def test_private_candidate_path_exposure_fails(self) -> None:
        path = self.root / "Sources/QwenVoiceCore/SemanticTypes.swift"
        text = path.read_text(encoding="utf-8").replace(
            "public let name: String\n    public let hasTranscript",
            "public let name: String\n    public let audioPath: String\n    public let hasTranscript",
            1,
        )
        path.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(saved_voice_lifecycle_contract.ContractError, "staged path"):
            saved_voice_lifecycle_contract.validate(self.root)

    def test_missing_ios_delete_cleanup_fails(self) -> None:
        path = self.root / "Sources/iOS/IOSVoicesView.swift"
        text = path.read_text(encoding="utf-8").replace(
            "appModel.voiceCloningDraft.clearReference()",
            "appModel.voiceCloningDraft.referenceWasNotCleared()",
        )
        path.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(saved_voice_lifecycle_contract.ContractError, "iOS saved-voice deletion"):
            saved_voice_lifecycle_contract.validate(self.root)

    def test_missing_ios_device_lane_fails(self) -> None:
        path = self.root / "scripts/ui_test.sh"
        text = path.read_text(encoding="utf-8").replace(
            '"saved-voice-lifecycle"',
            '"saved-voice-lifecycle-removed"',
        )
        path.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(saved_voice_lifecycle_contract.ContractError, "XCUITest lane"):
            saved_voice_lifecycle_contract.validate(self.root)

    def test_missing_direct_clone_import_surface_fails(self) -> None:
        path = self.root / "Sources/iOS/Sheets/IOSBottomSheets.swift"
        text = path.read_text(encoding="utf-8").replace(
            '"referenceClip_importAudioFile"',
            '"referenceClip_importWasRemoved"',
        )
        path.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(saved_voice_lifecycle_contract.ContractError, "direct Clone import"):
            saved_voice_lifecycle_contract.validate(self.root)

    def test_missing_transcription_save_gate_fails(self) -> None:
        path = self.root / "Sources/iOS/Voices/IOSRecordVoiceSheet.swift"
        text = path.read_text(encoding="utf-8").replace(
            "transcriptionReview.allowsSave(transcript: transcript)",
            "transcriptionReview.allowsUnsafeSave(transcript: transcript)",
        )
        path.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(saved_voice_lifecycle_contract.ContractError, "transcription review enrollment"):
            saved_voice_lifecycle_contract.validate(self.root)

    def test_missing_typed_transcription_evidence_fails(self) -> None:
        path = self.root / "Sources/iOS/Voices/IOSRecordVoiceSheet.swift"
        text = path.read_text(encoding="utf-8").replace(
            "VoiceClipTranscriber.enrollmentResult(url: url)",
            "VoiceClipTranscriber.transcribe(url: url)",
        )
        path.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(saved_voice_lifecycle_contract.ContractError, "transcription review enrollment"):
            saved_voice_lifecycle_contract.validate(self.root)


if __name__ == "__main__":
    unittest.main()
