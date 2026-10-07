import Foundation
@testable import QwenVoiceCore
import XCTest

final class GenerationPlanShadowMapperTests: XCTestCase {
    func testCustomMappingUsesResolvedCurrentPromptAndPolicies() throws {
        let inputs = makeInputs(mode: .custom)
        let projection = try GenerationPlanShadowMapper.project(
            inputs,
            shipping: try shippingSnapshot(from: inputs)
        )

        XCTAssertTrue(projection.comparison.matches)
        XCTAssertEqual(projection.plan.core.mode, .custom)
        XCTAssertEqual(projection.plan.core.language, "english")
        XCTAssertEqual(projection.plan.core.modelFacingText, "Private generation text.")
        XCTAssertEqual(
            projection.plan.core.conditioning,
            .custom(
                speakerID: "aiden",
                deliveryInstruction: "Warm and confident. Native English pronunciation with clear English diction and natural stress."
            )
        )
        XCTAssertEqual(projection.plan.core.sampling.effectiveSeed, 42)
        XCTAssertEqual(projection.plan.core.memory.tier, .floor8GBMac)
        XCTAssertEqual(projection.plan.core.memory.retentionPolicy, .retainUntilIdle)
    }

    func testDesignMappingUsesResolvedInstructionNotUnresolvedDescription() throws {
        let inputs = makeInputs(mode: .design)
        let projection = try GenerationPlanShadowMapper.project(
            inputs,
            shipping: try shippingSnapshot(from: inputs)
        )

        XCTAssertTrue(projection.comparison.matches)
        XCTAssertEqual(
            projection.plan.core.conditioning,
            .design(
                voiceDescription: "Voice character: A bright narrator. Delivery: Intense but controlled. Native English pronunciation with clear English diction and natural stress."
            )
        )
    }

    func testCloneMappingBindsResolvedConditioningDigest() throws {
        let inputs = makeInputs(mode: .clone)
        let projection = try GenerationPlanShadowMapper.project(
            inputs,
            shipping: try shippingSnapshot(from: inputs)
        )

        XCTAssertTrue(projection.comparison.matches)
        XCTAssertEqual(
            projection.plan.core.conditioning,
            .clone(conditioningDigest: String(repeating: "c", count: 64))
        )
        XCTAssertEqual(projection.plan.core.language, "english")
    }

    func testCloneRequiresDigestAndOtherModesRejectIt() throws {
        var clone = makeInputs(mode: .clone)
        clone = replacingCloneDigest(in: clone, with: nil)
        XCTAssertThrowsError(try GenerationPlanShadowMapper.makePlan(clone)) { error in
            XCTAssertEqual(
                error as? GenerationPlanShadowMappingError,
                .missingCloneConditioningDigest
            )
        }

        var custom = makeInputs(mode: .custom)
        custom = replacingCloneDigest(in: custom, with: "unexpected")
        XCTAssertThrowsError(try GenerationPlanShadowMapper.makePlan(custom)) { error in
            XCTAssertEqual(
                error as? GenerationPlanShadowMappingError,
                .unexpectedCloneConditioningDigest
            )
        }
    }

    func testDependencyInvalidationRemainsLocalToChangedPolicy() throws {
        let baseline = try GenerationPlanShadowMapper.makePlan(makeInputs(mode: .custom))

        let changedOutput = try GenerationPlanShadowMapper.makePlan(
            makeInputs(mode: .custom, outputPath: "/private/alternate.wav")
        )
        assertOnlyChanged(
            baseline.dependencyIdentities,
            changedOutput.dependencyIdentities,
            keyPath: \.output
        )

        let changedSampling = try GenerationPlanShadowMapper.makePlan(
            makeInputs(mode: .custom, effectiveSeed: 43)
        )
        assertOnlyChanged(
            baseline.dependencyIdentities,
            changedSampling.dependencyIdentities,
            keyPath: \.sampling
        )

        let changedMemory = try GenerationPlanShadowMapper.makePlan(
            makeInputs(mode: .custom, memoryCadence: 75)
        )
        assertOnlyChanged(
            baseline.dependencyIdentities,
            changedMemory.dependencyIdentities,
            keyPath: \.memory
        )
    }

    func testStrictComparisonReportsNestedAndSourceDriftByFieldOnly() throws {
        let inputs = makeInputs(mode: .custom)
        let baseline = try GenerationPlanShadowMapper.makePlan(inputs)
        let changedCore = CoreGenerationPlan(
            generationID: baseline.core.generationID,
            mode: baseline.core.mode,
            modelFacingText: baseline.core.modelFacingText,
            language: "french",
            model: baseline.core.model,
            conditioning: baseline.core.conditioning,
            sampling: Qwen3SamplingPolicy(
                algorithmVersion: baseline.core.sampling.algorithmVersion,
                effectiveSeed: baseline.core.sampling.effectiveSeed,
                talker: SamplingStage(
                    temperature: 0.75,
                    topP: baseline.core.sampling.talker.topP,
                    topK: baseline.core.sampling.talker.topK,
                    minP: baseline.core.sampling.talker.minP
                ),
                subtalker: baseline.core.sampling.subtalker,
                repetitionPenalty: baseline.core.sampling.repetitionPenalty,
                maximumCodecTokens: baseline.core.sampling.maximumCodecTokens
            ),
            chunking: baseline.core.chunking,
            memory: baseline.core.memory
        )
        let changedPlan = ProductGenerationPlan(
            originalText: baseline.originalText,
            spokenText: baseline.spokenText,
            core: changedCore,
            output: baseline.output,
            quality: baseline.quality
        )

        let comparison = GenerationPlanShadowMapper.compare(
            changedPlan,
            against: inputs,
            shipping: try shippingSnapshot(from: inputs)
        )
        XCTAssertFalse(comparison.matches)
        XCTAssertEqual(
            Set(comparison.drifts.map(\.field)),
            [.language, .talkerTemperature]
        )

        let encoded = try JSONEncoder().encode(comparison)
        let text = try XCTUnwrap(String(data: encoded, encoding: .utf8))
        XCTAssertFalse(text.contains("Private generation text"))
        XCTAssertFalse(text.contains("Warm and confident"))
        XCTAssertFalse(text.contains("/private/output.wav"))
        XCTAssertTrue(text.contains("core.language"))
    }

    func testSourceCoherenceDetectsRequestAndResolvedIdentityMismatch() throws {
        let base = makeInputs(mode: .custom)
        let mismatchedModel = CoreModelIdentity(
            modelID: "wrong_model",
            repository: base.modelIdentity.repository,
            revision: base.modelIdentity.revision,
            artifactVersion: base.modelIdentity.artifactVersion,
            integrityManifestDigest: base.modelIdentity.integrityManifestDigest,
            runtimeProfileSignature: base.modelIdentity.runtimeProfileSignature
        )
        let inputs = GenerationPlanShadowInputs(
            request: base.request,
            resolvedGenerationID: base.resolvedGenerationID,
            modelIdentity: mismatchedModel,
            modelCapabilities: base.modelCapabilities,
            nativeMemoryPolicy: base.nativeMemoryPolicy,
            talkerKVGeneratedWindow: base.talkerKVGeneratedWindow,
            chunkPolicy: base.chunkPolicy,
            samplingPolicy: base.samplingPolicy,
            outputPolicy: ProductOutputPlan(
                destinationPath: "/private/wrong.wav",
                shouldStream: false,
                batchIndex: nil,
                batchTotal: nil,
                publicationPolicyVersion: 1
            ),
            qualityPolicy: base.qualityPolicy
        )

        let projection = try GenerationPlanShadowMapper.project(
            inputs,
            shipping: try shippingSnapshot(from: inputs)
        )
        XCTAssertEqual(
            Set(projection.comparison.drifts.map(\.field)),
            [.requestModelID, .requestOutputPath, .requestShouldStream]
        )
    }

    func testIndependentShippingSnapshotDetectsProjectionDrift() throws {
        let inputs = makeInputs(mode: .custom)
        let baseline = try shippingSnapshot(from: inputs)
        let shipping = GenerationShippingResolutionSnapshot(
            originalText: baseline.originalText,
            spokenText: baseline.spokenText,
            generationID: baseline.generationID,
            mode: baseline.mode,
            modelFacingText: baseline.modelFacingText,
            language: "french",
            model: baseline.model,
            conditioning: baseline.conditioning,
            sampling: baseline.sampling,
            chunking: baseline.chunking,
            memory: baseline.memory,
            output: baseline.output,
            quality: baseline.quality
        )

        let projection = try GenerationPlanShadowMapper.project(
            inputs,
            shipping: shipping
        )
        XCTAssertEqual(projection.comparison.drifts.map(\.field), [.language])
    }

    private func makeInputs(
        mode: GenerationMode,
        outputPath: String = "/private/output.wav",
        effectiveSeed: UInt64 = 42,
        memoryCadence: Int = 50
    ) -> GenerationPlanShadowInputs {
        let generationID = UUID(uuidString: "01234567-89AB-CDEF-0123-456789ABCDEF")!
        let modelID: String
        let payload: GenerationRequest.Payload
        let cloneDigest: String?
        switch mode {
        case .custom:
            modelID = "pro_custom_speed"
            payload = .custom(speakerID: " aiden ", deliveryStyle: "Warm and confident")
            cloneDigest = nil
        case .design:
            modelID = "pro_design_speed"
            payload = .design(
                voiceDescription: "A bright narrator",
                deliveryStyle: "Intense but controlled"
            )
            cloneDigest = nil
        case .clone:
            modelID = "pro_clone_speed"
            payload = .clone(
                reference: CloneReference(
                    audioPath: "/private/reference.wav",
                    transcript: "Private English reference transcript.",
                    preparedVoiceID: "private-voice"
                )
            )
            cloneDigest = String(repeating: "c", count: 64)
        }
        let request = GenerationRequest(
            mode: mode,
            modelID: modelID,
            text: "Private generation text.",
            outputPath: outputPath,
            shouldStream: true,
            streamingInterval: 0.6,
            languageHint: "english",
            payload: payload,
            generationID: generationID,
            seed: effectiveSeed,
            variation: .expressive
        )
        let stage = SamplingStage(temperature: 0.9, topP: 1, topK: 50, minP: 0)
        return GenerationPlanShadowInputs(
            request: request,
            resolvedGenerationID: generationID,
            modelIdentity: CoreModelIdentity(
                modelID: modelID,
                repository: "mlx-community/\(modelID)",
                revision: String(repeating: "a", count: 40),
                artifactVersion: "artifact-v1",
                integrityManifestDigest: String(repeating: "b", count: 64),
                runtimeProfileSignature: "runtime-profile"
            ),
            modelCapabilities: capabilities(for: mode),
            nativeMemoryPolicy: NativeMemoryPolicy(
                name: "floor-test",
                deviceClass: .floor8GBMac,
                cacheLimitBytes: 256 * 1_024 * 1_024,
                clearCacheAfterGeneration: true,
                clearMLXCacheOnStreamChunkEmit: true,
                mlxTokenMemoryClearCadence: memoryCadence,
                unloadAfterIdleSeconds: 120
            ),
            talkerKVGeneratedWindow: 512,
            chunkPolicy: .currentConstrainedTierDefault(for: mode),
            samplingPolicy: Qwen3SamplingPolicy(
                algorithmVersion: 2,
                effectiveSeed: effectiveSeed,
                talker: stage,
                subtalker: stage,
                repetitionPenalty: 1.05,
                maximumCodecTokens: 2_048
            ),
            outputPolicy: ProductOutputPlan(
                destinationPath: outputPath,
                shouldStream: true,
                batchIndex: nil,
                batchTotal: nil,
                publicationPolicyVersion: 1
            ),
            qualityPolicy: ProductQualityPolicy(
                reviewPolicyID: "fast",
                algorithmVersion: 3
            ),
            cloneConditioningDigest: cloneDigest,
            resolvedCloneTranscript: mode == .clone
                ? "Private English reference transcript."
                : nil
        )
    }

    private func replacingCloneDigest(
        in inputs: GenerationPlanShadowInputs,
        with digest: String?
    ) -> GenerationPlanShadowInputs {
        GenerationPlanShadowInputs(
            request: inputs.request,
            resolvedGenerationID: inputs.resolvedGenerationID,
            resolvedSpokenText: inputs.resolvedSpokenText,
            modelIdentity: inputs.modelIdentity,
            modelCapabilities: inputs.modelCapabilities,
            nativeMemoryPolicy: inputs.nativeMemoryPolicy,
            talkerKVGeneratedWindow: inputs.talkerKVGeneratedWindow,
            chunkPolicy: inputs.chunkPolicy,
            samplingPolicy: inputs.samplingPolicy,
            outputPolicy: inputs.outputPolicy,
            qualityPolicy: inputs.qualityPolicy,
            cloneConditioningDigest: digest,
            resolvedCloneTranscript: inputs.resolvedCloneTranscript
        )
    }

    private func shippingSnapshot(
        from inputs: GenerationPlanShadowInputs
    ) throws -> GenerationShippingResolutionSnapshot {
        let plan = try GenerationPlanShadowMapper.makePlan(inputs)
        return GenerationShippingResolutionSnapshot(
            originalText: plan.originalText,
            spokenText: plan.spokenText,
            generationID: plan.core.generationID,
            mode: plan.core.mode,
            modelFacingText: plan.core.modelFacingText,
            language: plan.core.language,
            model: plan.core.model,
            conditioning: plan.core.conditioning,
            sampling: plan.core.sampling,
            chunking: plan.core.chunking,
            memory: plan.core.memory,
            output: plan.output,
            quality: plan.quality
        )
    }

    private func capabilities(for mode: GenerationMode) -> Qwen3TTSModelCapabilities {
        Qwen3TTSModelCapabilities(
            modelSize: .pro1b7,
            familyType: {
                switch mode {
                case .custom: .customVoice
                case .design: .voiceDesign
                case .clone: .baseClone
                }
            }(),
            supportsInstructionControl: mode != .clone,
            supportsVoiceClone: mode == .clone,
            supportsXVectorOnlyClone: mode == .clone,
            requiresSpeakerEncoder: mode == .clone,
            tokenizerProfile: Qwen3TTSTokenizerProfile(
                name: "qwen3",
                sampleRateHz: 24_000,
                frameRateHz: 12.5,
                decoderQuantizers: 16,
                encoderValidQuantizers: 8,
                encoderConfiguredQuantizers: 8,
                codebookSize: 2_048,
                semanticCodebookSize: 4_096
            ),
            generationDefaults: Qwen3TTSGenerationDefaultsProfile(
                checkpointMaxNewTokens: nil,
                wrapperFallbackMaxNewTokens: 2_048,
                appPolicyMaxNewTokens: 2_048,
                temperature: 0.9,
                topP: 1,
                topK: 50,
                doSample: true,
                repetitionPenalty: 1.05,
                source: .appPolicy
            ),
            artifactAvailability: .publicArtifact
        )
    }

    private func assertOnlyChanged(
        _ baseline: GenerationPlanDependencyIdentities,
        _ changed: GenerationPlanDependencyIdentities,
        keyPath: KeyPath<GenerationPlanDependencyIdentities, String>,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertNotEqual(baseline[keyPath: keyPath], changed[keyPath: keyPath], file: file, line: line)
        XCTAssertNotEqual(baseline.complete, changed.complete, file: file, line: line)
        let all: [KeyPath<GenerationPlanDependencyIdentities, String>] = [
            \.modelPreparation, \.conditioning, \.sampling, \.chunking,
            \.memory, \.output, \.quality,
        ]
        for candidate in all where candidate != keyPath {
            XCTAssertEqual(
                baseline[keyPath: candidate],
                changed[keyPath: candidate],
                file: file,
                line: line
            )
        }
    }
}
