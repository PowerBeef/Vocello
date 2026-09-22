import Foundation
import QwenVoiceCore

/// Shared interpretation of engine snapshot + active model for macOS generation UI.
/// Separates engine readiness (`isReady`) from model warm-path state (`loadState`).
enum ModelWarmPathState: Equatable, Sendable {
    case engineUnavailable
    case modelCold
    case modelWarming
    case modelActivePrep
    case modelReady
    case modelMismatch
    case engineBusy
    case failed(String)
}

enum GenerationEnginePresentation {
    static func modelWarmPath(
        snapshot: TTSEngineSnapshot,
        activeModelID: String?
    ) -> ModelWarmPathState {
        guard snapshot.isReady else {
            return .engineUnavailable
        }

        let trimmedActiveID = activeModelID?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""

        switch snapshot.loadState {
        case .idle:
            return .modelCold
        case .starting:
            return .modelWarming
        case .loaded(let modelID):
            if trimmedActiveID.isEmpty || modelID == trimmedActiveID {
                return .modelReady
            }
            return .modelMismatch
        case .running(let modelID, let label, _):
            if !trimmedActiveID.isEmpty, modelID != trimmedActiveID {
                return .engineBusy
            }
            if label == EngineActivityLabels.preparingVoiceReference {
                return .modelActivePrep
            }
            return .modelActivePrep
        case .failed(let message):
            return .failed(message)
        }
    }

    /// Whether the user may start a generation (cold or warm) for the active model.
    static func allowsGenerationStart(
        snapshot: TTSEngineSnapshot,
        activeModelID: String?,
        isModelAvailable: Bool,
        hasScriptContent: Bool,
        isUserGenerating: Bool,
        hasActiveGeneration: Bool
    ) -> Bool {
        guard !isUserGenerating, !hasActiveGeneration else { return false }
        guard snapshot.isReady, isModelAvailable, hasScriptContent else { return false }

        switch modelWarmPath(snapshot: snapshot, activeModelID: activeModelID) {
        case .engineUnavailable, .engineBusy:
            return false
        case .modelCold, .modelWarming, .modelActivePrep, .modelReady, .modelMismatch, .failed:
            // A failed attempt does not disconnect the engine. A new request
            // must be able to recover after the user corrects its cause.
            return true
        }
    }

    static func coldStartDetail(deviceClass: NativeDeviceMemoryClass = NativeMemoryPolicyResolver.deviceClass()) -> String {
        switch deviceClass {
        case .floor8GBMac:
            return MacInterfaceText.engineColdStartLowMemory
        case .mid16GBMac, .highMemoryMac, .iPhonePro:
            return MacInterfaceText.engineColdStart
        }
    }
}
