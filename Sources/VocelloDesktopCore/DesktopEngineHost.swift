import Foundation
import QwenVoiceCore

/// The engine host the Mac app uses (`MacEngineBootstrap`): the shared
/// `TTSEngineStore` over the in-process engine with the Mac memory budget, so a
/// CLI take gets the app's support check, consent admission, busy refusal,
/// memory admission, critical-pressure guard and post-take trims. Consent is
/// the invocation's (`--confirm-consent`, or a request's `confirmConsent`),
/// never the app's Settings acknowledgment.
@MainActor
public final class DesktopEngineHost {
    private let store: TTSEngineStore
    private var consent: VoiceCloningConsentPolicy

    public init(
        engine: MLXTTSEngine,
        consent: VoiceCloningConsentPolicy,
        deviceClass: NativeDeviceMemoryClass = NativeMemoryPolicyResolver.deviceClass()
    ) {
        self.consent = consent
        weak var host: DesktopEngineHost?
        store = TTSEngineStore(
            backend: AnyTTSEngineBackend(
                engine: engine,
                supportsSavedVoiceMutation: true,
                supportsModelManagementMutation: true,
                supportedModes: [.custom, .design, .clone],
                voiceCloningConsent: { host?.consent ?? consent }
            ),
            memoryBudgetPolicy: MacMemoryBudgetPolicy.policy(for: deviceClass)
        )
        host = self
    }

    /// Initializes the engine through the store, as the app does, so the store
    /// holds its first memory context before admitting any take.
    public func initialize(appSupportDirectory: URL) async throws {
        try await store.initialize(appSupportDirectory: appSupportDirectory)
    }

    /// The consent the next request is admitted under (one host serves many requests).
    public func setConsent(_ policy: VoiceCloningConsentPolicy) {
        consent = policy
    }

    public func loadModel(id: String) async throws {
        try await store.loadModel(id: id)
    }

    public func generate(_ request: GenerationRequest) async throws -> GenerationResult {
        try await store.generate(request)
    }

    public func cancelActiveGeneration(reason: GenerationCancellationReason) async throws {
        try await store.cancelActiveGeneration(reason: reason)
    }
}
