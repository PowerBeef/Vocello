import Foundation
import QwenVoiceCore
import XCTest

final class ClonePrimingAndWarmLanguageTests: XCTestCase {
    func testSuccessfulPrimeSuppressesOnlyTheSameReferenceIntent() {
        var intent = CloneProactivePrimingIntent()
        XCTAssertTrue(intent.shouldPrime(key: "first"))
        intent.recordPrime(key: "first", preparationState: .primed(key: "first"))

        XCTAssertFalse(intent.shouldPrime(key: "first"), "an idle unload must stay unloaded")
        XCTAssertTrue(intent.shouldPrime(key: "changed-reference"))
        intent.reset()
        XCTAssertTrue(intent.shouldPrime(key: "first"), "re-entering Clone starts a fresh intent")
    }

    func testUnfinishedOrMismatchedPrimeCanBeRetried() {
        var intent = CloneProactivePrimingIntent()
        let states: [ClonePreparationState] = [
            .idle, .preparing(key: "first"), .failed(key: "first", message: nil), .primed(key: "other"),
        ]
        XCTAssertTrue(intent.shouldPrime(key: "first"))
        for state in states {
            intent.recordPrime(key: "first", preparationState: state)
            XCTAssertTrue(intent.shouldPrime(key: "first"))
            XCTAssertNil(intent.primedKey)
        }
    }

    func testChangedIntentRejectsAStalePrimeCompletionAndCanReturnToTheOldReference() {
        var intent = CloneProactivePrimingIntent()
        XCTAssertTrue(intent.shouldPrime(key: "first"))
        intent.recordPrime(key: "first", preparationState: .primed(key: "first"))
        XCTAssertTrue(intent.shouldPrime(key: "second"))
        intent.recordPrime(key: "first", preparationState: .primed(key: "first"))
        XCTAssertNil(intent.primedKey, "the old task no longer owns the current reference intent")
        intent.recordPrime(key: "second", preparationState: .failed(key: "second", message: nil))
        XCTAssertTrue(intent.shouldPrime(key: "first"), "returning to an earlier clip is fresh intent")
    }

    @MainActor
    func testAnAutoFrenchBuiltInVoiceWarmIsKeyedLikeItsTake() throws {
        let script = "Bonjour à tous, je vous présente aujourd'hui le nouveau programme de la saison prochaine."
        let take = MacStudioGenerationRequestFactory.customVoice(
            modelID: "pro_custom",
            text: script,
            outputPath: "/tmp/p01-05.wav",
            language: .auto,
            speakerID: "aiden",
            deliveryStyle: nil,
            deliveryInstructionCellID: nil,
            seed: nil,
            variation: nil
        )
        func warm(languageHint: String) throws -> GenerationRequest {
            let decision = warmupCoordinator().warmupDecision(for: .init(
                mode: .custom,
                modelID: "pro_custom",
                isModelAvailable: true,
                identity: .custom(
                    speakerID: "aiden",
                    deliveryStyle: nil,
                    deliveryInstructionCellID: nil,
                    languageHint: languageHint
                ),
                deviceClass: .mid16GBMac
            ))
            guard case .prefetchInteractiveReadiness(let request) = decision else {
                XCTFail("the warm decision is not a prefetch: \(decision)")
                throw CocoaError(.coderInvalidValue)
            }
            return request
        }

        let resolved = MacWarmLanguageResolution.takeLanguageHint(mode: .custom, selectedLanguage: .auto, script: script)
        XCTAssertEqual(resolved, "french")
        XCTAssertEqual(
            GenerationSemantics.prewarmIdentity(for: try warm(languageHint: resolved)),
            GenerationSemantics.prewarmIdentity(for: take)
        )
        XCTAssertNotEqual(
            GenerationSemantics.prewarmIdentity(for: try warm(languageHint: "auto")),
            GenerationSemantics.prewarmIdentity(for: take),
            "the warm Auto resolved from the English warm text"
        )
    }

    @MainActor
    func testAnAutoFrenchVoiceDesignWarmIsKeyedLikeItsTake() throws {
        let script = "Bonjour à tous, je vous présente aujourd'hui le nouveau programme de la saison prochaine."
        let brief = "Une narratrice chaleureuse et posée."
        let take = MacStudioGenerationRequestFactory.voiceDesign(
            modelID: "pro_design",
            text: script,
            outputPath: "/tmp/p12-07.wav",
            language: .auto,
            voiceDescription: brief,
            deliveryStyle: "",
            seed: nil,
            variation: nil
        )
        let resolved = MacWarmLanguageResolution.takeLanguageHint(mode: .design, selectedLanguage: .auto, script: script)
        let decision = warmupCoordinator().warmupDecision(for: .init(
            mode: .design,
            modelID: "pro_design",
            isModelAvailable: true,
            identity: .design(
                brief: brief,
                deliveryStyle: "",
                bucket: GenerationSemantics.designWarmBucket(for: script),
                languageHint: resolved
            ),
            deviceClass: .mid16GBMac
        ))
        guard case .prefetchInteractiveReadiness(let warm) = decision else {
            return XCTFail("the warm decision is not a prefetch: \(decision)")
        }
        XCTAssertEqual(
            GenerationSemantics.designConditioningIdentity(for: warm),
            GenerationSemantics.designConditioningIdentity(for: take)
        )
    }

    @MainActor
    private func warmupCoordinator() -> MacGenerationWarmupCoordinator {
        MacGenerationWarmupCoordinator(
            admissionPolicy: MacWarmupAdmissionPolicy(mode: .off, deviceClass: .mid16GBMac)
        )
    }

    func testAnExplicitLanguageWarmsAsSelected() {
        XCTAssertEqual(
            MacWarmLanguageResolution.takeLanguageHint(mode: .custom, selectedLanguage: .german, script: "Bonjour à tous."),
            "german"
        )
        XCTAssertEqual(
            MacWarmLanguageResolution.takeLanguageHint(mode: .custom, selectedLanguage: .auto, script: ""),
            GenerationSemantics.canonicalCustomWarmLanguage
        )
    }
}
