import AVFoundation
import CryptoKit
import Foundation
import QwenVoiceCore
import Speech
import UIKit

/// Headless, non-UI on-device diagnostics runner — the iOS analog of `vocello bench`.
///
/// Fires **only** when one of its purpose-specific diagnostics environment variables is present
/// and non-empty, so it ships completely inert (a normal user launch never sets one).
/// `scripts/ios_device.sh bench` sets the generation spec — together with `QWENVOICE_DEBUG=1` (lights
/// up `TelemetryGate`, so the engine appends its decode/RTF/audioQC row to
/// `diagnostics/engine/generations.jsonl`) and `QVOICE_IOS_DEVICE_RUN_ID=<runID>`
/// (tags the run) — launches the app over `devicectl`, polls for the completion
/// sentinel, then pulls the App-Group `diagnostics/` tree and runs the summarizer.
///
/// Spec format (the env value): `<mode>:<variant>:<text>`, e.g.
/// `custom:speed:Hello from Vocello on device`. `mode ∈ custom|design|clone`,
/// `variant ∈ speed|quality` (iPhone resolves speed-only regardless), and the text is
/// everything after the second `:` (so it may itself contain colons). Forgiving:
/// a bare `1`/`on`/`true`/`yes`, a bare mode, or a partial spec all fall back to
/// sensible defaults.
///
/// Optional companion env `QVOICE_IOS_DEVICE_DIAGNOSTICS_LANGUAGE` sets the UI language picker
/// equivalent (`english`, `french`, `auto`, …) on the generation request. Omitted
/// behaves like Auto. `scripts/ios_device.sh lang-bench` sets it per matrix cell.
/// `QVOICE_IOS_DEVICE_DIAGNOSTICS_SEED=<UInt64>` pins the MLX sampling stream for
/// predeclared diagnostic cohorts; an invalid value fails before generation.
/// `QVOICE_IOS_DEVICE_DIAGNOSTICS_VARIATION=expressive|balanced|consistent`
/// explicitly pins the sampling policy; otherwise the current iOS preference applies.
///
/// Clone diagnostics additionally require `QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID`
/// to identify the exact prepared voice. They never select an arbitrary saved voice or
/// substitute a bundled speaker preview.
///
/// When `QVOICE_IOS_DEVICE_DIAGNOSTICS_VERIFY_OUTPUT=1`, after a successful generation the runner
/// transcribes the output WAV in-process (Speech) and stamps `outputVerification`
/// on the diagnostics sentinel for `scripts/check_language_output.py`. The completed
/// run also mirrors only its exact WAV as `output.wav`, with bounded sample metadata
/// and a SHA-256 digest in the sentinel; raw prompts and absolute paths are omitted.
///
/// The runner drives the same in-process `TTSEngineStore.generate(_:)` the UI uses —
/// no UI interaction — then writes `diagnostics/<runID>/device-diagnostics-done.json`. It never
/// calls `exit()`; the app stays up so the script can pull the diagnostics container.
@MainActor
enum IOSDeviceDiagnosticsRunner {
    private static let environmentKey = "QVOICE_IOS_DEVICE_DIAGNOSTICS_SPEC"
    private static let memoryQualificationEnvironmentKey =
        "QVOICE_IOS_DEVICE_MEMORY_QUALIFICATION_SPEC"
    private static let cloneConditioningAcceptanceEnvironmentKey =
        "QVOICE_IOS_DEVICE_CLONE_CONDITIONING_ACCEPTANCE"
    private static let expectedCloneAudioSHA256EnvironmentKey =
        "QVOICE_IOS_DEVICE_DIAGNOSTICS_EXPECTED_CLONE_AUDIO_SHA256"
    private static let expectedCloneTranscriptSHA256EnvironmentKey =
        "QVOICE_IOS_DEVICE_DIAGNOSTICS_EXPECTED_CLONE_TRANSCRIPT_SHA256"
    private static let speechAssetLocalesEnvironmentKey =
        "QVOICE_IOS_SPEECH_ASSET_LOCALES"
    private static let runIDKey = "QVOICE_IOS_DEVICE_RUN_ID"
    private static let languageEnvKey = "QVOICE_IOS_DEVICE_DIAGNOSTICS_LANGUAGE"
    private static let verifyOutputEnvKey = "QVOICE_IOS_DEVICE_DIAGNOSTICS_VERIFY_OUTPUT"
    private static let cloneVoiceIDEnvKey = "QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID"
    private static let seedEnvKey = "QVOICE_IOS_DEVICE_DIAGNOSTICS_SEED"
    private static let variationEnvKey = "QVOICE_IOS_DEVICE_DIAGNOSTICS_VARIATION"
    private static let customSpeakerEnvKey = "QVOICE_IOS_DEVICE_DIAGNOSTICS_CUSTOM_SPEAKER"
    private static let designInstructionEnvKey = "QVOICE_IOS_DEVICE_DIAGNOSTICS_DESIGN_INSTRUCTION"

    /// Default benchmark sentence — long enough to exercise streaming chunking,
    /// free of any personal/sensitive content.
    private static let defaultText =
        "Vocello on-device diagnostics check. The quick brown fox jumps over the lazy dog, "
        + "then pauses, takes a breath, and reads one more sentence aloud."
    /// Default Voice Design brief when a `design` run supplies only text.
    private static let defaultVoiceBrief =
        "A warm, friendly narrator with a calm, measured pace."

    struct Spec {
        var mode: GenerationMode
        var variant: ModelVariantKind
        var text: String
    }

    /// True when the launch environment requested a diagnostic generation.
    static var isRequested: Bool {
        var keys = [
            environmentKey,
            memoryQualificationEnvironmentKey,
            speechAssetLocalesEnvironmentKey,
        ]
        #if QVOICE_DEVICE_DIAGNOSTICS
        keys.append(cloneConditioningAcceptanceEnvironmentKey)
        #endif
        return keys.contains { key in
            guard let raw = ProcessInfo.processInfo.environment[key]?
                .trimmingCharacters(in: .whitespacesAndNewlines) else { return false }
            return !raw.isEmpty
        }
    }

    /// Kick off the diagnostic generation if requested. Safe to call once after engine init;
    /// no-op when `QVOICE_IOS_DEVICE_DIAGNOSTICS_SPEC` is unset. Runs detached on the MainActor so it
    /// doesn't block app startup.
    static func runIfRequested(engine: TTSEngineStore) {
        guard isRequested else { return }
        #if QVOICE_DEVICE_DIAGNOSTICS
        // Crash-capture lane verification: deliberately fault so MetricKit captures the
        // crash and the `scripts/ios_device.sh crashes --test` flow can symbolicate it
        // against the preserved build dSYM. This code is absent from ordinary builds.
        if ProcessInfo.processInfo.environment["QVOICE_IOS_DEVICE_DIAGNOSTICS_CRASH_TEST"] == "1" {
            print("[device-diagnostics] deliberate crash requested for the capture/symbolication lane")
            fatalError("QVOICE_IOS_DEVICE_DIAGNOSTICS_CRASH_TEST: deliberate diagnostics crash")
        }
        if trimmedEnvironmentValue(cloneConditioningAcceptanceEnvironmentKey) == "1" {
            IOSInterruptionRecorder.shared.start()
            Task { @MainActor in
                await runCloneConditioningAcceptance(engine: engine)
            }
            return
        }
        #endif
        if let rawLocales = trimmedEnvironmentValue(speechAssetLocalesEnvironmentKey) {
            Task { @MainActor in
                await runSpeechAssetBootstrap(rawLocales: rawLocales)
            }
            return
        }
        if let rawMemorySpec = trimmedEnvironmentValue(memoryQualificationEnvironmentKey) {
            IOSInterruptionRecorder.shared.start()
            Task { @MainActor in
                await runMemoryQualification(rawSpec: rawMemorySpec, engine: engine)
            }
            return
        }
        let spec = parseSpec(ProcessInfo.processInfo.environment[environmentKey] ?? "")
        let uiLanguageHint = trimmedEnvironmentValue(languageEnvKey)
        // Record calls + lifecycle transitions for the sentinel so a doomed run
        // self-reports its cause ("call arrived at t=42s"). Diagnostics-only → inert
        // on user launches.
        IOSInterruptionRecorder.shared.start()
        Task { @MainActor in
            await run(spec: spec, uiLanguageHint: uiLanguageHint, engine: engine)
        }
    }

    // MARK: - Spec parsing

    static func parseSpec(_ raw: String) -> Spec {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        var spec = Spec(mode: .custom, variant: .speed, text: defaultText)
        guard !["", "1", "on", "true", "yes"].contains(trimmed.lowercased()) else {
            return spec
        }
        let parts = trimmed
            .split(separator: ":", maxSplits: 2, omittingEmptySubsequences: false)
            .map(String.init)
        if let first = parts.first, let mode = GenerationMode(rawValue: first.lowercased()) {
            spec.mode = mode
        }
        if parts.count >= 2 {
            switch parts[1].lowercased() {
            case "quality", "hq": spec.variant = .quality
            case "speed", "fast", "": spec.variant = .speed
            default: break
            }
        }
        if parts.count >= 3, !parts[2].isEmpty {
            spec.text = parts[2]
        }
        return spec
    }

    // MARK: - Speech assets

    /// Explicit physical-device bootstrap for the on-device Speech assets used by the language
    /// output gate. This path is independent from generation and never runs during a normal app
    /// launch. `AssetInventory` automatically reserves resolved locale assets when it creates the
    /// combined installation request; this code never releases unrelated reservations.
    private static func runSpeechAssetBootstrap(rawLocales: String) async {
        let idleTimerWasDisabled = UIApplication.shared.isIdleTimerDisabled
        UIApplication.shared.isIdleTimerDisabled = true
        defer {
            UIApplication.shared.isIdleTimerDisabled = idleTimerWasDisabled
        }

        let runID = safeRunID(from: trimmedEnvironmentValue(runIDKey)) ?? "ios-speech-assets"
        let startedAt = ISO8601DateFormatter().string(from: Date())
        let requestedIdentifiers = speechAssetLocaleIdentifiers(from: rawLocales)
        var result = SpeechAssetBootstrapResult(
            runID: runID,
            startedAt: startedAt,
            requestedLocaleIdentifiers: requestedIdentifiers
        )
        var prepared: [PreparedSpeechAssetModule] = []
        var failureCode: SpeechAssetFailureCode?

        do {
            guard !requestedIdentifiers.isEmpty else {
                throw SpeechAssetBootstrapError(.invalidLocaleList)
            }

            let reservedBefore = await AssetInventory.reservedLocales
            let installedBefore = await DictationTranscriber.installedLocales
            result.maximumReservedLocales = AssetInventory.maximumReservedLocales
            result.reservedLocaleCountBefore = reservedBefore.count
            result.installedLocaleCountBefore = installedBefore.count

            for requestedIdentifier in requestedIdentifiers {
                let requestedLocale = Locale(identifier: requestedIdentifier)
                guard let resolvedLocale = await DictationTranscriber.supportedLocale(
                    equivalentTo: requestedLocale
                ) else {
                    result.locales.append(SpeechAssetLocaleResult(
                        requestedIdentifier: requestedIdentifier
                    ))
                    failureCode = .unsupportedLocale
                    continue
                }

                let module = DictationTranscriber(
                    locale: resolvedLocale,
                    preset: .shortDictation
                )
                let statusBefore = await AssetInventory.status(forModules: [module])
                let resolvedIdentifier = resolvedLocale.identifier
                result.locales.append(SpeechAssetLocaleResult(
                    requestedIdentifier: requestedIdentifier,
                    resolvedIdentifier: resolvedIdentifier,
                    moduleSelectedIdentifiers: module.selectedLocales.map(\.identifier),
                    statusBefore: speechAssetStatusLabel(statusBefore),
                    reservedBefore: containsEquivalentLocale(
                        resolvedLocale,
                        in: reservedBefore
                    ),
                    installedLocalePresentBefore: containsEquivalentLocale(
                        resolvedLocale,
                        in: installedBefore
                    )
                ))
                prepared.append(PreparedSpeechAssetModule(
                    recordIndex: result.locales.count - 1,
                    resolvedLocale: resolvedLocale,
                    module: module
                ))
            }

            guard failureCode == nil, prepared.count == requestedIdentifiers.count else {
                throw SpeechAssetBootstrapError(failureCode ?? .unsupportedLocale)
            }

            let modules: [any SpeechModule] = prepared.map(\.module)
            result.aggregateStatusBefore = speechAssetStatusLabel(
                await AssetInventory.status(forModules: modules)
            )
            if let installationRequest = try await AssetInventory.assetInstallationRequest(
                supporting: modules
            ) {
                result.installationRequestCreated = true
                result.installationAttempted = true
                try await installationRequest.downloadAndInstall()
            }

        } catch let error as SpeechAssetBootstrapError {
            failureCode = error.code
        } catch {
            let nsError = error as NSError
            result.failureDomain = boundedSpeechAssetFailureDomain(nsError.domain)
            result.failureCodeValue = nsError.code
            failureCode = result.installationAttempted ? .downloadFailed : .installationRequestFailed
        }

        // Always re-read the device after the installation attempt. Apple can throw while a
        // system-managed retry continues, and partial installs must remain visible to the caller.
        let assetInventoryReady = await finalizeSpeechAssetBootstrapResult(
            &result,
            prepared: prepared
        )
        result.assetInventoryReady = assetInventoryReady
        if assetInventoryReady, result.vocelloLegacyReady == true {
            result.status = "pass"
            result.failureCode = nil
            result.failureDomain = nil
            result.failureCodeValue = nil
        } else {
            result.status = "failed"
            if failureCode == nil {
                failureCode = assetInventoryReady
                    ? .legacyRecognizerNotReady
                    : .postInstallationVerificationFailed
            }
            result.failureCode = (failureCode ?? .unknown).rawValue
        }
        result.finishedAt = ISO8601DateFormatter().string(from: Date())
        writeSpeechAssetSentinel(result, runID: runID)
    }

    private static func finalizeSpeechAssetBootstrapResult(
        _ result: inout SpeechAssetBootstrapResult,
        prepared: [PreparedSpeechAssetModule]
    ) async -> Bool {
        guard !prepared.isEmpty,
              prepared.count == result.requestedLocaleIdentifiers.count else {
            return false
        }

        let modules: [any SpeechModule] = prepared.map(\.module)
        let reservedAfter = await AssetInventory.reservedLocales
        let installedAfter = await DictationTranscriber.installedLocales
        let aggregateStatusAfter = await AssetInventory.status(forModules: modules)
        var perModuleStatuses: [AssetInventory.Status] = []
        perModuleStatuses.reserveCapacity(prepared.count)
        for preparedModule in prepared {
            perModuleStatuses.append(
                await AssetInventory.status(forModules: [preparedModule.module])
            )
        }

        result.reservedLocaleCountAfter = reservedAfter.count
        result.installedLocaleCountAfter = installedAfter.count
        result.aggregateStatusAfter = speechAssetStatusLabel(aggregateStatusAfter)

        // SFSpeechRecognizer is not Sendable. All AssetInventory awaits above are complete before
        // fresh recognizers are created and read on this @MainActor task.
        let vocelloSelections = VoiceClipTranscriber.liveSelectedCapabilities()
        var allInstalled = aggregateStatusAfter == .installed
        for (preparedModule, statusAfter) in zip(prepared, perModuleStatuses) {
            let installedLocalePresent = containsEquivalentLocale(
                preparedModule.resolvedLocale,
                in: installedAfter
            )
            let reserved = containsEquivalentLocale(
                preparedModule.resolvedLocale,
                in: reservedAfter
            )
            let legacyExact = VoiceClipTranscriber.liveRecognizerObservation(
                for: preparedModule.resolvedLocale
            )
            let vocelloSelection = vocelloSelections.first {
                $0.language == legacyExact.language
            }
            let vocelloReady = vocelloSelection?.isAvailable == true
                && vocelloSelection?.supportsOnDeviceRecognition == true

            result.locales[preparedModule.recordIndex].statusAfter =
                speechAssetStatusLabel(statusAfter)
            result.locales[preparedModule.recordIndex].reservedAfter = reserved
            result.locales[preparedModule.recordIndex].installedLocalePresentAfter =
                installedLocalePresent
            result.locales[preparedModule.recordIndex].legacyRecognizerIdentifier =
                legacyExact.recognizerIdentifier
            result.locales[preparedModule.recordIndex].legacyRecognizerAvailable =
                legacyExact.isAvailable
            result.locales[preparedModule.recordIndex].legacySupportsOnDeviceRecognition =
                legacyExact.supportsOnDeviceRecognition
            result.locales[preparedModule.recordIndex].vocelloSelectedLegacyIdentifier =
                vocelloSelection?.identifier
            result.locales[preparedModule.recordIndex].vocelloSelectedLegacyAvailable =
                vocelloSelection?.isAvailable
            result.locales[preparedModule.recordIndex]
                .vocelloSelectedLegacySupportsOnDeviceRecognition =
                vocelloSelection?.supportsOnDeviceRecognition
            result.locales[preparedModule.recordIndex].vocelloLegacyReady = vocelloReady

            allInstalled = allInstalled
                && statusAfter == .installed
                && installedLocalePresent
        }
        result.vocelloLegacyReady = result.locales.allSatisfy {
            $0.vocelloLegacyReady == true
        }
        return allInstalled
    }

    private static func speechAssetLocaleIdentifiers(from raw: String) -> [String] {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !["1", "on", "true", "yes"].contains(trimmed.lowercased()) else {
            return ["de_DE", "es_419", "ja_JP", "zh_CN"]
        }
        var seen: Set<String> = []
        return trimmed.split(separator: ",").compactMap { component in
            let identifier = component.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !identifier.isEmpty,
                  identifier.count <= 32,
                  identifier.unicodeScalars.allSatisfy({ scalar in
                      CharacterSet.alphanumerics.contains(scalar)
                          || scalar == "_"
                          || scalar == "-"
                  }) else {
                return nil
            }
            let key = normalizedLocaleIdentifier(identifier)
            return seen.insert(key).inserted ? identifier : nil
        }
    }

    private static func containsEquivalentLocale(_ locale: Locale, in locales: [Locale]) -> Bool {
        let expected = normalizedLocaleIdentifier(locale.identifier)
        return locales.contains {
            normalizedLocaleIdentifier($0.identifier) == expected
        }
    }

    private static func normalizedLocaleIdentifier(_ identifier: String) -> String {
        identifier.replacingOccurrences(of: "-", with: "_").lowercased()
    }

    private static func speechAssetStatusLabel(_ status: AssetInventory.Status) -> String {
        switch status {
        case .unsupported: "unsupported"
        case .supported: "supported"
        case .downloading: "downloading"
        case .installed: "installed"
        @unknown default: "unknown"
        }
    }

    private static func boundedSpeechAssetFailureDomain(_ value: String) -> String? {
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "._-"))
        let bounded = String(value.unicodeScalars.filter { allowed.contains($0) }.prefix(96))
        return bounded.isEmpty ? nil : bounded
    }

    // MARK: - Run

    private static func run(spec: Spec, uiLanguageHint: String?, engine: TTSEngineStore) async {
        let runID = safeRunID(from: ProcessInfo.processInfo.environment[runIDKey]) ?? "device-diagnostics"
        let generationID = UUID()
        let startedAt = Date()
        print(
            "[device-diagnostics] start mode=\(spec.mode.rawValue) variant=\(spec.variant.rawValue) "
            + "runID=\(runID) lang=\(uiLanguageHint ?? "auto") chars=\(spec.text.count)"
        )

        // Device/bundle fields read here (MainActor) — UIDevice is MainActor-isolated,
        // so they cannot be struct property defaults under Swift 6 strict concurrency.
        let device = UIDevice.current
        var record = SentinelRecord(
            runID: runID,
            generationID: generationID.uuidString,
            mode: spec.mode.rawValue,
            variant: spec.variant.rawValue,
            promptCharacters: spec.text.count,
            startedAt: ISO8601DateFormatter().string(from: startedAt),
            uiLanguageHint: uiLanguageHint,
            requestedLanguageHint: uiLanguageHint ?? Qwen3SupportedLanguage.auto.rawValue,
            languageHintSource: languageHintSource(for: uiLanguageHint),
            deviceModel: device.model,
            systemName: device.systemName,
            systemVersion: device.systemVersion,
            bundleVersion: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String,
            buildVersion: Bundle.main.object(forInfoDictionaryKey: kCFBundleVersionKey as String) as? String
        )
        var appTimelineSubmitted = false

        do {
            guard let model = ModelDescriptor.model(for: spec.mode) else {
                throw DiagnosticsError("no model in the contract for mode '\(spec.mode.rawValue)'")
            }
            record.modelID = model.id
            record.modelName = model.name

            let payload = try await buildPayload(spec: spec, engine: engine)
            if case .custom(let speakerID, _) = payload {
                record.customSpeakerID = speakerID
            }
            record.fixtureDigest = try fixtureDigest(for: payload)
            let seed = try diagnosticsSeed()
            let variation = try diagnosticsVariation()
            record.seed = seed
            record.samplingVariation = (variation ?? .expressive).rawValue
            let loadedModelID = engine.loadState.currentModelID
            record.preGenerationModelID = loadedModelID
            record.preGenerationWarmState = loadedModelID == model.id ? "warm" : "cold"

            // Do not explicitly load or prime here. `engine.generate` enters the native
            // per-generation telemetry session before model load, prewarm, and clone
            // conditioning. Preloading from this runner would hide the cold model-loading
            // peak and clone preparation from the benchmark's clock and sampler.

            let outputPath = makeOutputPath(runID: runID, model: model)
            let request = GenerationRequest(
                mode: spec.mode,
                modelID: model.id,
                text: spec.text,
                outputPath: outputPath,
                shouldStream: true,
                streamingInterval: GenerationSemantics.appStreamingInterval,
                languageHint: uiLanguageHint,
                payload: payload,
                generationID: generationID,
                seed: seed,
                variation: variation
            )
            guard let capabilities = model.qwen3Capabilities else {
                throw DiagnosticsError("model '\(model.id)' has no declared Qwen3 prompt capabilities")
            }
            let prompt = GenerationSemantics.qwen3PromptAssembly(
                for: request,
                capabilities: capabilities
            )
            record.resolvedLanguageHint = prompt.language
            record.resolvedPromptAssemblyDigest = try digest(prompt)
            record.promptDigestScope = spec.mode == .clone
                ? "request_without_resolved_clone_transcript"
                : "resolved"

            print("[device-diagnostics] generating… resolvedLanguage=\(record.resolvedLanguageHint ?? "?")")
            // Headless diagnostics still execute in the production app process. Record the real
            // submit/completion lifecycle so iOS benchmark evidence proves both app and engine
            // ownership. Do not synthesize player milestones: this lane never schedules playback.
            await AppGenerationTimeline.shared.recordSubmitted(
                id: generationID,
                mode: spec.mode.rawValue
            )
            appTimelineSubmitted = true
            let t0 = Date()
            let result = try await engine.generate(request)
            await AppGenerationTimeline.shared.recordCompleted(
                id: generationID,
                mode: spec.mode.rawValue,
                usedStreaming: true,
                finishReason: result.finishReason?.rawValue,
                summary: result.telemetrySummary
            )
            appTimelineSubmitted = false
            let wall = Date().timeIntervalSince(t0)
            let rtf = wall > 0 ? result.durationSeconds / wall : 0

            record.status = "ok"
            record.durationSeconds = result.durationSeconds
            record.wallSeconds = wall
            record.realtimeFactor = rtf
            record.finishReason = result.finishReason?.rawValue
            print(String(
                format: "[device-diagnostics] ✓ %.2fs audio · rtf=%.2f · finish=%@",
                result.durationSeconds, rtf, result.finishReason?.rawValue ?? "?"
            ))

            if shouldVerifyOutput,
               let resolvedHint = record.resolvedLanguageHint,
               let expectedLanguage = resolvedLanguageHint(for: resolvedHint) {
                let verification = await GenerationOutputVerifier.verify(
                    audioURL: URL(fileURLWithPath: result.audioPath),
                    expectedScript: spec.text,
                    expectedLanguage: expectedLanguage
                )
                record.outputVerification = verification
                print(
                    "[device-diagnostics] output verify pass=\(verification.pass) "
                    + "lang=\(verification.languagePass) wer=\(verification.wordErrorRate.map { String(format: "%.2f", $0) } ?? "unavailable") "
                    + "score=\(String(format: "%.2f", verification.languageMatchScore))"
                )
            }

            let audioURL = URL(fileURLWithPath: result.audioPath)
            let outputEvidence = try makeOutputEvidence(for: audioURL)
            try mirrorOutputToPullableDiagnostics(audioURL, runID: runID)
            record.outputEvidence = outputEvidence
            if let verification = record.outputVerification {
                record.languageASRGate = verification.languageASRGateResult(
                    evidenceDigest: outputEvidence.sha256
                )
            }
        } catch is CancellationError {
            if appTimelineSubmitted {
                await AppGenerationTimeline.shared.recordFailed(
                    id: generationID,
                    finishReason: .cancelled
                )
            }
            record.status = "error"
            record.error = "cancelled"
            print("[device-diagnostics] ✗ cancelled")
        } catch {
            if appTimelineSubmitted {
                await AppGenerationTimeline.shared.recordFailed(id: generationID)
            }
            record.status = "error"
            record.error = error.localizedDescription
            print("[device-diagnostics] ✗ \(error.localizedDescription)")
        }

        record.finishedAt = ISO8601DateFormatter().string(from: Date())
        let interruptions = IOSInterruptionRecorder.shared.snapshot()
        if !interruptions.isEmpty {
            record.interruptions = interruptions
            if record.status == "ok" {
                record.status = "error"
                record.error = "diagnostic run was interrupted (\(interruptions.count) event(s))"
            }
        }
        writeSentinel(record, runID: runID)
    }

    #if QVOICE_DEVICE_DIAGNOSTICS
    /// Two-take, local-only proof that the owned Qwen runtime keeps transcript-backed and
    /// x-vector-only clone conditioning semantically distinct on the same physical-device
    /// process. The canonical saved voice is read but never modified. The audio-only take uses
    /// a purpose-owned copy with no transcript sidecar and removes that copy before PASS.
    private static func runCloneConditioningAcceptance(engine: TTSEngineStore) async {
        let runID = safeRunID(from: trimmedEnvironmentValue(runIDKey))
            ?? "clone-conditioning-acceptance"
        let scratchDirectory = cloneConditioningScratchDirectory()
        var failureCode = CloneConditioningAcceptanceFailureCode.invalidEnvironment
        var completedTakeCount = 0
        var failedTakeIndex: Int?
        let startedAt = ISO8601DateFormatter().string(from: Date())
        defer { BenchRunContext.clearCurrentTakeFile() }

        do {
            guard NativeTelemetryMode.current() == .verbose, TelemetryGate.resolvedEnabled else {
                throw DiagnosticsError("clone-conditioning acceptance requires verbose telemetry")
            }
            guard let voiceID = trimmedEnvironmentValue(cloneVoiceIDEnvKey),
                  let expectedAudioSHA256 = validatedSHA256EnvironmentValue(
                    expectedCloneAudioSHA256EnvironmentKey
                  ),
                  let expectedTranscriptSHA256 = validatedSHA256EnvironmentValue(
                    expectedCloneTranscriptSHA256EnvironmentKey
                  ) else {
                throw DiagnosticsError("clone-conditioning acceptance fixture identity is incomplete")
            }
            guard let model = ModelDescriptor.model(for: .clone),
                  let capabilities = model.qwen3Capabilities,
                  capabilities.supportsXVectorOnlyClone else {
                failureCode = .runtimeCapabilityUnavailable
                throw DiagnosticsError("the active clone model does not support x-vector-only conditioning")
            }

            failureCode = .fixtureUnavailable
            let voices = try await engine.listPreparedVoices()
            guard let voice = voices.first(where: { $0.id == voiceID }),
                  let transcript = try voice.loadTranscript(),
                  !transcript.isEmpty else {
                throw DiagnosticsError("the exact transcript-backed clone fixture is unavailable")
            }
            let sourceAudioURL = URL(fileURLWithPath: voice.audioPath)
            guard try sha256Hex(for: sourceAudioURL) == expectedAudioSHA256,
                  sha256Hex(forText: transcript) == expectedTranscriptSHA256 else {
                failureCode = .fixtureIdentityMismatch
                throw DiagnosticsError("the clone fixture digest does not match the acceptance contract")
            }

            failureCode = .scratchPreparationFailed
            let fileManager = FileManager.default
            try? fileManager.removeItem(at: scratchDirectory)
            try fileManager.createDirectory(at: scratchDirectory, withIntermediateDirectories: true)
            let scratchAudioURL = scratchDirectory.appendingPathComponent(
                "reference.wav",
                isDirectory: false
            )
            try copyAtomically(sourceAudioURL, to: scratchAudioURL)
            let scratchTranscriptURL = scratchAudioURL
                .deletingPathExtension()
                .appendingPathExtension("txt")
            try? fileManager.removeItem(at: scratchTranscriptURL)
            guard try sha256Hex(for: scratchAudioURL) == expectedAudioSHA256,
                  !fileManager.fileExists(atPath: scratchTranscriptURL.path) else {
                throw DiagnosticsError("the audio-only scratch fixture is not exact")
            }

            let plans = [
                CloneConditioningAcceptancePlan(
                    takeIndex: 1,
                    cell: "clone/speed/conditioning/transcript-backed",
                    expectedConditioningMode: "transcript_backed",
                    expectedTranscriptMode: "inline",
                    expectedArtifactScope: "saved_voice",
                    expectedTranscriptBacked: true,
                    expectedXVectorOnly: false,
                    reference: CloneReference(
                        audioPath: sourceAudioURL.path,
                        transcript: transcript,
                        preparedVoiceID: voice.id
                    )
                ),
                CloneConditioningAcceptancePlan(
                    takeIndex: 2,
                    cell: "clone/speed/conditioning/x-vector-only",
                    expectedConditioningMode: "x_vector_only",
                    expectedTranscriptMode: "none",
                    expectedArtifactScope: "transient_reference",
                    expectedTranscriptBacked: false,
                    expectedXVectorOnly: true,
                    reference: CloneReference(
                        audioPath: scratchAudioURL.path,
                        transcript: nil,
                        preparedVoiceID: nil
                    )
                ),
            ]
            var takeResults: [CloneConditioningAcceptanceTakeResult] = []
            let seed: UInt64 = 19_790_615

            print("[clone-conditioning] start runID=\(runID) takes=2")
            for plan in plans {
                failedTakeIndex = plan.takeIndex
                let actualWarmState = engine.loadState.currentModelID == model.id ? "warm" : "cold"
                failureCode = .takeIdentityUnavailable
                try BenchRunContext.writeCurrentTakeFile(
                    takeIndex: plan.takeIndex,
                    cell: plan.cell,
                    intendedWarmState: actualWarmState
                )
                let generationID = UUID()
                let outputFileName = String(
                    format: "take-%02d-%@.wav",
                    plan.takeIndex,
                    plan.expectedConditioningMode
                )
                let outputPath = makeCloneConditioningOutputPath(
                    scratchDirectory: scratchDirectory,
                    outputFileName: outputFileName
                )
                let request = GenerationRequest(
                    mode: .clone,
                    modelID: model.id,
                    text: defaultText,
                    outputPath: outputPath,
                    shouldStream: true,
                    streamingInterval: GenerationSemantics.appStreamingInterval,
                    languageHint: Qwen3SupportedLanguage.english.rawValue,
                    payload: .clone(reference: plan.reference),
                    generationID: generationID,
                    seed: seed,
                    variation: .consistent
                )
                let promptAssemblyDigest = try digest(
                    GenerationSemantics.qwen3PromptAssembly(for: request, capabilities: capabilities)
                )

                var appTimelineSubmitted = false
                do {
                    failureCode = .generationFailed
                    await AppGenerationTimeline.shared.recordSubmitted(
                        id: generationID,
                        mode: GenerationMode.clone.rawValue
                    )
                    appTimelineSubmitted = true
                    let generationStartedAt = Date()
                    let result = try await engine.generate(request)
                    await AppGenerationTimeline.shared.recordCompleted(
                        id: generationID,
                        mode: GenerationMode.clone.rawValue,
                        usedStreaming: result.usedStreaming,
                        finishReason: result.finishReason?.rawValue,
                        summary: result.telemetrySummary
                    )
                    appTimelineSubmitted = false
                    IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
                        generationID: generationID
                    )

                    failureCode = .conditioningContractFailed
                    let booleans = result.diagnosticBooleanFlags
                    let strings = result.diagnosticStringFlags
                    let promptMaterialized = booleans["clone_prompt_artifact_hit"] == true
                        || booleans["clone_prompt_memory_hit"] == true
                        || booleans["clone_prompt_built"] == true
                    guard booleans["clone_transcript_backed"] == plan.expectedTranscriptBacked,
                          booleans["clone_x_vector_only"] == plan.expectedXVectorOnly,
                          booleans["clone_optimized_handler_used"] == true,
                          strings["clone_conditioning_mode"] == plan.expectedConditioningMode,
                          strings["clone_transcript_mode"] == plan.expectedTranscriptMode,
                          strings["clone_prompt_artifact_scope"] == plan.expectedArtifactScope,
                          strings["qwen3_supports_x_vector_only_clone"] == "true",
                          promptMaterialized else {
                        throw DiagnosticsError("the runtime clone-conditioning flags are inconsistent")
                    }

                    let audioURL = URL(fileURLWithPath: result.audioPath)
                    failureCode = .outputValidationFailed
                    let outputEvidence = try makeOutputEvidence(
                        for: audioURL,
                        artifactRelativePath: "outputs/\(outputFileName)"
                    )
                    let outputVerification = await GenerationOutputVerifier.verify(
                        audioURL: audioURL,
                        expectedScript: defaultText,
                        expectedLanguage: .english
                    )
                    guard outputVerification.pass else {
                        throw DiagnosticsError("clone-conditioning output verification failed")
                    }

                    failureCode = .telemetryValidationFailed
                    _ = try requireQualificationTelemetry(
                        generationID: generationID,
                        expectedMode: .clone,
                        expectedModelID: model.id,
                        expectedCell: plan.cell,
                        expectedTakeIndex: plan.takeIndex
                    )
                    failureCode = .outputMirrorFailed
                    _ = try mirrorQualificationOutput(
                        audioURL,
                        runID: runID,
                        outputFileName: outputFileName
                    )
                    IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
                        generationID: generationID
                    )

                    takeResults.append(
                        CloneConditioningAcceptanceTakeResult(
                            takeIndex: plan.takeIndex,
                            generationID: generationID.uuidString,
                            cell: plan.cell,
                            mode: GenerationMode.clone.rawValue,
                            modelID: model.id,
                            conditioningMode: strings["clone_conditioning_mode"] ?? "",
                            transcriptMode: strings["clone_transcript_mode"] ?? "",
                            promptArtifactScope: strings["clone_prompt_artifact_scope"] ?? "",
                            transcriptBacked: booleans["clone_transcript_backed"] == true,
                            xVectorOnly: booleans["clone_x_vector_only"] == true,
                            supportsXVectorOnlyClone: true,
                            optimizedHandlerUsed: booleans["clone_optimized_handler_used"] == true,
                            promptMaterialized: promptMaterialized,
                            conditioningReused: booleans["clone_conditioning_reused"] == true,
                            preparedCloneCacheHit: booleans["prepared_clone_cache_hit"] == true,
                            referenceAudioSHA256: expectedAudioSHA256,
                            promptAssemblySHA256: promptAssemblyDigest,
                            wallSeconds: Date().timeIntervalSince(generationStartedAt),
                            outputFileName: outputFileName,
                            outputEvidence: outputEvidence,
                            outputVerification: outputVerification
                        )
                    )
                    completedTakeCount = takeResults.count
                    failedTakeIndex = nil
                    print(
                        "[clone-conditioning] take \(plan.takeIndex)/2 "
                        + "\(plan.expectedConditioningMode) PASS"
                    )
                } catch {
                    if appTimelineSubmitted {
                        await AppGenerationTimeline.shared.recordFailed(id: generationID)
                    }
                    throw error
                }
            }

            failureCode = .conditioningContractFailed
            guard takeResults.count == 2,
                  takeResults[0].promptAssemblySHA256 != takeResults[1].promptAssemblySHA256 else {
                throw DiagnosticsError("clone-conditioning prompt identities were not distinct")
            }
            failureCode = .interrupted
            let interruptions = IOSInterruptionRecorder.shared.snapshot()
            guard interruptions.isEmpty else {
                throw DiagnosticsError("clone-conditioning acceptance was interrupted")
            }
            failureCode = .scratchCleanupFailed
            try fileManager.removeItem(at: scratchDirectory)
            guard !fileManager.fileExists(atPath: scratchDirectory.path) else {
                throw DiagnosticsError("clone-conditioning scratch cleanup was incomplete")
            }

            let terminal = CloneConditioningAcceptanceResult(
                runID: runID,
                startedAt: startedAt,
                finishedAt: ISO8601DateFormatter().string(from: Date()),
                seed: seed,
                samplingVariation: Qwen3SamplingVariation.consistent.rawValue,
                voiceIDDigest: sha256Hex(forText: voice.id),
                referenceAudioSHA256: expectedAudioSHA256,
                referenceTranscriptSHA256: expectedTranscriptSHA256,
                scratchCleanupVerified: true,
                takes: takeResults
            )
            failureCode = .resultWriteFailed
            try writeCloneConditioningResult(terminal, runID: runID)
            print("[clone-conditioning] PASS runID=\(runID)")
        } catch {
            try? FileManager.default.removeItem(at: scratchDirectory)
            let failure = CloneConditioningAcceptanceFailure(
                runID: runID,
                failedAt: ISO8601DateFormatter().string(from: Date()),
                failureCode: failureCode.rawValue,
                completedTakeCount: completedTakeCount,
                expectedTakeCount: 2,
                failedTakeIndex: failedTakeIndex
            )
            try? writeCloneConditioningFailure(failure, runID: runID)
            print(
                "[clone-conditioning] FAIL code=\(failureCode.rawValue) "
                + "completed=\(completedTakeCount)/2"
            )
        }
    }
    #endif

    /// Executes the canonical retained-memory plan in one app/engine process.
    /// `memory-qualification-result.json` remains the only PASS barrier. A failed
    /// run writes a separate bounded status marker so the host can stop polling;
    /// that marker is never accepted by history publication.
    private static func runMemoryQualification(rawSpec: String, engine: TTSEngineStore) async {
        let environmentRunID = safeRunID(from: trimmedEnvironmentValue(runIDKey))
        var failureCode = IOSMemoryQualificationFailureCode.invalidPlan
        var completedTakeCount = 0
        var activeTake: IOSMemoryQualificationTake?
        do {
            let plan = try IOSMemoryQualificationSpec.decodeAndValidate(rawSpec)
            failureCode = .runIdentityMismatch
            guard safeRunID(from: trimmedEnvironmentValue(runIDKey)) == plan.runID else {
                throw DiagnosticsError("memory qualification runID does not match the launch environment")
            }
            failureCode = .telemetryUnavailable
            guard NativeTelemetryMode.current() == .verbose, TelemetryGate.resolvedEnabled else {
                throw DiagnosticsError("memory qualification requires verbose native telemetry")
            }
            failureCode = .cloneVoiceUnavailable
            guard trimmedEnvironmentValue(cloneVoiceIDEnvKey) != nil else {
                throw DiagnosticsError(
                    "memory qualification requires \(cloneVoiceIDEnvKey) with an exact saved voice ID"
                )
            }
            failureCode = .corpusUnavailable
            guard let text = BenchMatrixSpec.text(for: plan.length) else {
                throw DiagnosticsError("memory qualification corpus is missing \(plan.length)")
            }

            let startedAt = ISO8601DateFormatter().string(from: Date())
            var takeResults: [MemoryQualificationTakeResult] = []
            var fixtureDigests: [String: String] = [:]
            defer { BenchRunContext.clearCurrentTakeFile() }

            print("[device-memory] start runID=\(plan.runID) takes=\(plan.takes.count)")
            for plannedTake in plan.takes {
                activeTake = plannedTake
                failureCode = .modeUnavailable
                guard let mode = GenerationMode(rawValue: plannedTake.mode),
                      let model = ModelDescriptor.model(for: mode) else {
                    throw DiagnosticsError("memory qualification mode/model is unavailable")
                }
                failureCode = .fixtureUnavailable
                let payload = try await buildPayload(
                    spec: Spec(mode: mode, variant: .speed, text: text),
                    engine: engine
                )
                if let digest = try fixtureDigest(for: payload) {
                    fixtureDigests[mode.rawValue] = digest
                }

                let actualWarmState = engine.loadState.currentModelID == model.id ? "warm" : "cold"
                failureCode = .takeIdentityUnavailable
                try BenchRunContext.writeCurrentTakeFile(
                    takeIndex: plannedTake.takeIndex,
                    cell: plannedTake.cell,
                    intendedWarmState: actualWarmState
                )

                let generationID = UUID()
                let outputFileName = String(
                    format: "take-%02d-%@-speed-medium-retained-%d.wav",
                    plannedTake.takeIndex,
                    plannedTake.mode,
                    plannedTake.repetition
                )
                let outputPath = makeQualificationOutputPath(
                    runID: plan.runID,
                    model: model,
                    outputFileName: outputFileName
                )
                let request = GenerationRequest(
                    mode: mode,
                    modelID: model.id,
                    text: text,
                    outputPath: outputPath,
                    shouldStream: true,
                    streamingInterval: GenerationSemantics.appStreamingInterval,
                    languageHint: nil,
                    payload: payload,
                    generationID: generationID,
                    seed: plan.seed,
                    variation: nil
                )

                var appTimelineSubmitted = false
                do {
                    failureCode = .generationFailed
                    await AppGenerationTimeline.shared.recordSubmitted(
                        id: generationID,
                        mode: mode.rawValue
                    )
                    appTimelineSubmitted = true
                    let started = Date()
                    let result = try await engine.generate(request)
                    await AppGenerationTimeline.shared.recordCompleted(
                        id: generationID,
                        mode: mode.rawValue,
                        usedStreaming: result.usedStreaming,
                        finishReason: result.finishReason?.rawValue,
                        summary: result.telemetrySummary
                    )
                    appTimelineSubmitted = false

                    // Export the exact just-completed rows before validating them. A
                    // fail-closed qualification must still preserve the row and raw
                    // sample sidecar that explain which contract check rejected it.
                    IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
                        generationID: generationID
                    )

                    let audioURL = URL(fileURLWithPath: result.audioPath)
                    failureCode = .outputValidationFailed
                    _ = try makeOutputEvidence(for: audioURL)
                    failureCode = .telemetryValidationFailed
                    let engineRecord: GenerationTelemetryRecord
                    do {
                        engineRecord = try requireQualificationTelemetry(
                            generationID: generationID,
                            expectedMode: mode,
                            expectedModelID: model.id,
                            expectedCell: plannedTake.cell,
                            expectedTakeIndex: plannedTake.takeIndex
                        )
                    } catch let validationError as QualificationTelemetryValidationError {
                        failureCode = validationError.failureCode
                        throw validationError
                    }
                    failureCode = .outputMirrorFailed
                    let pullableOutput = try mirrorQualificationOutput(
                        audioURL,
                        runID: plan.runID,
                        outputFileName: outputFileName
                    )
                    guard pullableOutput.lastPathComponent == outputFileName else {
                        throw DiagnosticsError("memory qualification output mirror identity changed")
                    }
                    IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(
                        generationID: generationID
                    )

                    let wallSeconds = Date().timeIntervalSince(started)
                    takeResults.append(
                        MemoryQualificationTakeResult(
                            takeIndex: plannedTake.takeIndex,
                            generationID: generationID.uuidString,
                            cell: plannedTake.cell,
                            mode: mode.rawValue,
                            modelID: model.id,
                            variant: plan.variant,
                            length: plan.length,
                            warmState: engineRecord.warmState?.rawValue ?? actualWarmState,
                            repetition: plannedTake.repetition,
                            audioSeconds: result.durationSeconds,
                            wallSeconds: wallSeconds,
                            firstChunkMS: engineRecord.stageMarks.first(where: {
                                $0.stage == "firstChunk"
                            }).map { Double($0.tMS) },
                            outputFileName: outputFileName,
                            environment: qualificationEnvironment(from: engineRecord.summary)
                        )
                    )
                    completedTakeCount = takeResults.count
                    activeTake = nil
                    print(
                        "[device-memory] take \(plannedTake.takeIndex)/9 "
                        + "\(plannedTake.cell) \(actualWarmState) PASS"
                    )
                } catch {
                    if appTimelineSubmitted {
                        await AppGenerationTimeline.shared.recordFailed(id: generationID)
                    }
                    throw error
                }
            }

            failureCode = .interrupted
            let interruptions = IOSInterruptionRecorder.shared.snapshot()
            guard interruptions.isEmpty else {
                throw DiagnosticsError(
                    "memory qualification was interrupted (\(interruptions.count) event(s))"
                )
            }
            failureCode = .incompletePlan
            guard takeResults.count == plan.takes.count else {
                throw DiagnosticsError("memory qualification did not complete all planned takes")
            }

            let terminal = MemoryQualificationResult(
                runID: plan.runID,
                label: plan.runID,
                startedAt: startedAt,
                finishedAt: ISO8601DateFormatter().string(from: Date()),
                telemetryMode: "verbose",
                seed: plan.seed,
                streaming: true,
                fixtureDigests: fixtureDigests,
                memoryQualification: MemoryQualificationDeclaration(
                    policyID: plan.policyID,
                    modeOrder: plan.modes,
                    variant: plan.variant,
                    length: plan.length,
                    repetitionsPerMode: plan.repetitionsPerMode,
                    expectedTakeCount: plan.takes.count
                ),
                takes: takeResults
            )
            failureCode = .resultWriteFailed
            try writeMemoryQualificationSentinel(terminal, runID: plan.runID)
            print("[device-memory] PASS runID=\(plan.runID)")
        } catch {
            // Preserve already-written per-generation telemetry and outputs. The
            // allowlisted marker lets the host terminate promptly, while absence of
            // the PASS sentinel keeps history publication fail-closed.
            if let environmentRunID {
                let failure = IOSMemoryQualificationFailureStatus(
                    runID: environmentRunID,
                    failedAt: ISO8601DateFormatter().string(from: Date()),
                    failureCode: failureCode,
                    completedTakeCount: completedTakeCount,
                    failedTakeIndex: activeTake?.takeIndex,
                    failedCell: activeTake?.cell
                )
                do {
                    try writeMemoryQualificationFailureMarker(failure, runID: environmentRunID)
                } catch {
                    print(
                        "[device-memory] failure marker unavailable "
                        + "code=\(failureCode.rawValue)"
                    )
                }
            }
            print(
                "[device-memory] FAIL code=\(failureCode.rawValue) "
                + "completed=\(completedTakeCount)/9"
            )
        }
    }

    @MainActor
    private static func buildPayload(
        spec: Spec,
        engine: TTSEngineStore
    ) async throws -> GenerationRequest.Payload {
        switch spec.mode {
        case .custom:
            let speakerID = trimmedEnvironmentValue(customSpeakerEnvKey)
                ?? ModelDescriptor.defaultSpeaker
            guard speakerID.unicodeScalars.allSatisfy({
                CharacterSet.lowercaseLetters.contains($0)
                    || CharacterSet.decimalDigits.contains($0)
                    || $0 == "_"
            }), speakerID.count <= 32 else {
                throw DiagnosticsError("\(customSpeakerEnvKey) contains an invalid speaker identifier")
            }
            return .custom(
                speakerID: speakerID,
                deliveryStyle: nil
            )
        case .design:
            let instruction = trimmedEnvironmentValue(designInstructionEnvKey)
                ?? defaultVoiceBrief
            guard instruction.count <= 240 else {
                throw DiagnosticsError("\(designInstructionEnvKey) exceeds 240 characters")
            }
            return .design(
                voiceDescription: instruction,
                deliveryStyle: nil
            )
        case .clone:
            guard let requestedVoiceID = trimmedEnvironmentValue(cloneVoiceIDEnvKey) else {
                throw DiagnosticsError(
                    "clone diagnostics require \(cloneVoiceIDEnvKey) to identify an exact saved voice"
                )
            }
            let voices = try await engine.listPreparedVoices()
            guard let voice = voices.first(where: { $0.id == requestedVoiceID }) else {
                let availableIDs = voices.map(\.id).sorted().joined(separator: ", ")
                throw DiagnosticsError(
                    "saved clone voice '\(requestedVoiceID)' was not found"
                    + (availableIDs.isEmpty ? "; no saved voices are installed" : "; available IDs: \(availableIDs)")
                )
            }
            return .clone(
                reference: CloneReference(
                    audioPath: voice.audioPath,
                    transcript: nil,
                    preparedVoiceID: voice.id
                )
            )
        }
    }

    private static func trimmedEnvironmentValue(_ key: String) -> String? {
        guard let raw = ProcessInfo.processInfo.environment[key]?
            .trimmingCharacters(in: .whitespacesAndNewlines),
              !raw.isEmpty else {
            return nil
        }
        return raw
    }

    private static func diagnosticsSeed() throws -> UInt64? {
        guard let raw = trimmedEnvironmentValue(seedEnvKey) else { return nil }
        guard let seed = UInt64(raw) else {
            throw DiagnosticsError("\(seedEnvKey) must be an unsigned 64-bit integer")
        }
        return seed
    }

    private static func diagnosticsVariation() throws -> Qwen3SamplingVariation? {
        guard let raw = trimmedEnvironmentValue(variationEnvKey) else {
            return IOSGenerationVariationPreference.requestValue()
        }
        guard let variation = Qwen3SamplingVariation(rawValue: raw.lowercased()) else {
            throw DiagnosticsError(
                "\(variationEnvKey) must be expressive, balanced, or consistent"
            )
        }
        return variation == .expressive ? nil : variation
    }

    private static func languageHintSource(for requestedHint: String?) -> String {
        guard let requestedHint,
              Qwen3SupportedLanguage.normalized(requestedHint) != .auto else {
            return "auto"
        }
        return "explicit"
    }

    private static func digest<T: Encodable>(_ value: T) throws -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(value)
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    /// Privacy-safe identity for the exact non-text fixture used by a diagnostic
    /// generation. The sentinel exposes only the digest—never the App Group path,
    /// saved-voice name, transcript, or design description.
    private static func fixtureDigest(for payload: GenerationRequest.Payload) throws -> String? {
        switch payload {
        case .custom:
            return nil
        case .design(let voiceDescription, _):
            return SHA256.hash(data: Data(voiceDescription.utf8))
                .map { String(format: "%02x", $0) }
                .joined()
        case .clone(let reference):
            let url = URL(fileURLWithPath: reference.audioPath)
            guard let stream = InputStream(url: url) else {
                throw DiagnosticsError("could not open the resolved clone reference for identity hashing")
            }
            stream.open()
            defer { stream.close() }
            var hasher = SHA256()
            var buffer = [UInt8](repeating: 0, count: 64 * 1024)
            while stream.hasBytesAvailable {
                let count = stream.read(&buffer, maxLength: buffer.count)
                if count < 0 {
                    throw stream.streamError
                        ?? DiagnosticsError("could not read the resolved clone reference for identity hashing")
                }
                if count == 0 { break }
                hasher.update(data: Data(buffer[..<count]))
            }
            return hasher.finalize().map { String(format: "%02x", $0) }.joined()
        }
    }

    private static var shouldVerifyOutput: Bool {
        ProcessInfo.processInfo.environment[verifyOutputEnvKey] == "1"
    }

    private static func resolvedLanguageHint(for rawHint: String) -> Qwen3SupportedLanguage? {
        let normalized = Qwen3SupportedLanguage.normalized(rawHint)
        return normalized == .auto ? nil : normalized
    }

    // MARK: - Paths & sentinel

    private static func requireQualificationTelemetry(
        generationID: UUID,
        expectedMode: GenerationMode,
        expectedModelID: String,
        expectedCell: String,
        expectedTakeIndex: Int
    ) throws -> GenerationTelemetryRecord {
        let engineDirectory = AppPaths.appSupportDir
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent("engine", isDirectory: true)
        let rowsURL = engineDirectory.appendingPathComponent("generations.jsonl", isDirectory: false)
        guard let text = try? String(contentsOf: rowsURL, encoding: .utf8) else {
            throw QualificationTelemetryValidationError.telemetryUnavailable
        }
        let decoder = JSONDecoder()
        let matches = text.split(separator: "\n").compactMap { line -> GenerationTelemetryRecord? in
            guard line.contains(generationID.uuidString),
                  let data = line.data(using: .utf8),
                  let row = try? decoder.decode(GenerationTelemetryRecord.self, from: data),
                  row.generationID == generationID.uuidString else {
                return nil
            }
            return row
        }
        guard matches.count == 1, let row = matches.first else {
            throw QualificationTelemetryValidationError.rowCountInvalid
        }
        guard row.schemaVersion >= 8,
              row.mode == expectedMode.rawValue,
              row.modelID == expectedModelID,
              row.usedStreaming == true else {
            throw QualificationTelemetryValidationError.identityInvalid
        }
        let acceptedFinishReasons = Set(["eos", "max_tokens", "maxTokens", "completed"])
        guard row.finishReason.map(acceptedFinishReasons.contains) == true else {
            throw QualificationTelemetryValidationError.finishInvalid
        }
        guard row.notes["benchRunID"] == trimmedEnvironmentValue(runIDKey),
              row.notes["benchCell"] == expectedCell,
              row.notes["benchTakeIndex"] == String(expectedTakeIndex) else {
            throw QualificationTelemetryValidationError.runIdentityInvalid
        }
        guard row.outputMetrics?.readableWAV == true,
              row.outputMetrics?.atomicallyPublished == true,
              let audioQC = row.audioQC,
              audioQC.verdict != .fail,
              audioQC.instabilityVerdict != .fail,
              audioQC.writtenOutputVerdict != .fail else {
            throw QualificationTelemetryValidationError.outputInvalid
        }
        guard let summary = row.summary,
              let coverage = summary.captureCoverage,
              coverage.totalSampleCount == summary.sampleCount,
              coverage.memoryCoverageRatio >= 0.95,
              coverage.processResourceCaptureSucceeded,
              let boundaries = summary.boundaryCoverage,
              boundaries.missingBoundaryNames.isEmpty,
              summary.memoryAtStart != nil,
              summary.memoryAtEnd != nil,
              summary.memoryAtPeakPhysFootprint != nil,
              let memoryMetrics = row.memoryMetrics,
              memoryMetrics.captureCoverage == coverage,
              memoryMetrics.boundaryCoverage == boundaries,
              memoryMetrics.mlxStageCount > 0 else {
            throw QualificationTelemetryValidationError.memoryEvidenceIncomplete
        }

        let samplesURL = engineDirectory.appendingPathComponent(
            "samples-\(generationID.uuidString).jsonl",
            isDirectory: false
        )
        guard let samplesText = try? String(contentsOf: samplesURL, encoding: .utf8) else {
            throw QualificationTelemetryValidationError.sampleSidecarUnavailable
        }
        let sampleLines = samplesText.split(separator: "\n")
        let samples: [TelemetrySample]
        do {
            samples = try sampleLines.map { line in
                guard let data = line.data(using: .utf8) else {
                    throw QualificationTelemetryValidationError.sampleSidecarInvalid
                }
                return try decoder.decode(TelemetrySample.self, from: data)
            }
        } catch let validationError as QualificationTelemetryValidationError {
            throw validationError
        } catch {
            throw QualificationTelemetryValidationError.sampleSidecarInvalid
        }
        guard samples.count == summary.sampleCount,
              samples.first?.kind == .start,
              samples.last?.kind == .stop else {
            throw QualificationTelemetryValidationError.sampleSidecarInvalid
        }
        let observedBoundaries = Set(samples.compactMap(\.boundary))
        guard observedBoundaries.contains("first_chunk"),
              observedBoundaries.contains("final_audio_materialized") else {
            throw QualificationTelemetryValidationError.boundaryIncomplete
        }
        return row
    }

    private enum QualificationTelemetryValidationError: LocalizedError {
        case telemetryUnavailable
        case rowCountInvalid
        case identityInvalid
        case finishInvalid
        case runIdentityInvalid
        case outputInvalid
        case memoryEvidenceIncomplete
        case sampleSidecarUnavailable
        case sampleSidecarInvalid
        case boundaryIncomplete

        var failureCode: IOSMemoryQualificationFailureCode {
            switch self {
            case .telemetryUnavailable: .telemetryUnavailable
            case .rowCountInvalid: .telemetryRowCountInvalid
            case .identityInvalid: .telemetryIdentityInvalid
            case .finishInvalid: .telemetryFinishInvalid
            case .runIdentityInvalid: .telemetryRunIdentityInvalid
            case .outputInvalid: .telemetryOutputInvalid
            case .memoryEvidenceIncomplete: .telemetryMemoryEvidenceIncomplete
            case .sampleSidecarUnavailable: .telemetrySampleSidecarUnavailable
            case .sampleSidecarInvalid: .telemetrySampleSidecarInvalid
            case .boundaryIncomplete: .telemetryBoundaryIncomplete
            }
        }

        var errorDescription: String? {
            switch self {
            case .telemetryUnavailable:
                "memory qualification engine telemetry is unavailable"
            case .rowCountInvalid:
                "memory qualification expected exactly one engine telemetry row"
            case .identityInvalid:
                "memory qualification engine telemetry identity is incomplete"
            case .finishInvalid:
                "memory qualification generation did not finish successfully"
            case .runIdentityInvalid:
                "memory qualification telemetry lost ordered run/take identity"
            case .outputInvalid:
                "memory qualification output or audio QC proof failed"
            case .memoryEvidenceIncomplete:
                "memory qualification summary lacks complete v8 memory evidence"
            case .sampleSidecarUnavailable:
                "memory qualification verbose sample sidecar is unavailable"
            case .sampleSidecarInvalid:
                "memory qualification sample sidecar count, lifetime, or encoding is invalid"
            case .boundaryIncomplete:
                "memory qualification streaming/output boundaries are incomplete"
            }
        }
    }

    private static func qualificationEnvironment(
        from summary: TelemetrySummary?
    ) -> MemoryQualificationTakeEnvironment {
        if let environment = summary?.runEnvironment {
            return MemoryQualificationTakeEnvironment(
                loadAverage1Minute: environment.loadAverage1Minute,
                freeStorageBytes: environment.freeStorageBytes,
                uptimeSeconds: environment.uptimeSeconds,
                lowPowerModeEnabled: environment.lowPowerModeEnabled,
                thermalState: environment.thermalState
            )
        }
        let processInfo = ProcessInfo.processInfo
        return MemoryQualificationTakeEnvironment(
            loadAverage1Minute: nil,
            freeStorageBytes: nil,
            uptimeSeconds: processInfo.systemUptime,
            lowPowerModeEnabled: processInfo.isLowPowerModeEnabled,
            thermalState: thermalStateLabel(processInfo.thermalState)
        )
    }

    private static func thermalStateLabel(_ state: ProcessInfo.ThermalState) -> String {
        switch state {
        case .nominal: "nominal"
        case .fair: "fair"
        case .serious: "serious"
        case .critical: "critical"
        @unknown default: "unknown"
        }
    }

    #if QVOICE_DEVICE_DIAGNOSTICS
    private static func cloneConditioningScratchDirectory() -> URL {
        AppPaths.appSupportDir
            .appendingPathComponent("cache", isDirectory: true)
            .appendingPathComponent("clone-conditioning-acceptance", isDirectory: true)
    }

    private static func validatedSHA256EnvironmentValue(_ key: String) -> String? {
        guard let value = trimmedEnvironmentValue(key), value.count == 64,
              value.unicodeScalars.allSatisfy({ scalar in
                  CharacterSet(charactersIn: "0123456789abcdef").contains(scalar)
              }) else {
            return nil
        }
        return value
    }

    private static func sha256Hex(forText text: String) -> String {
        SHA256.hash(data: Data(text.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }

    private static func makeCloneConditioningOutputPath(
        scratchDirectory: URL,
        outputFileName: String
    ) -> String {
        let directory = scratchDirectory.appendingPathComponent("outputs", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory.appendingPathComponent(outputFileName, isDirectory: false).path
    }
    #endif

    private static func makeQualificationOutputPath(
        runID: String,
        model: ModelDescriptor,
        outputFileName: String
    ) -> String {
        let directory = AppPaths.outputsDir
            .appendingPathComponent(model.outputSubfolder, isDirectory: true)
            .appendingPathComponent("memory-qualification", isDirectory: true)
            .appendingPathComponent(runID, isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory.appendingPathComponent(outputFileName, isDirectory: false).path
    }

    @discardableResult
    private static func mirrorQualificationOutput(
        _ source: URL,
        runID: String,
        outputFileName: String
    ) throws -> URL {
        guard let pullableRoot = IOSPullableDiagnosticsMirror.pullableRoot else {
            throw DiagnosticsError("pullable diagnostics directory is unavailable")
        }
        let destination = pullableRoot
            .appendingPathComponent(runID, isDirectory: true)
            .appendingPathComponent("outputs", isDirectory: true)
            .appendingPathComponent(outputFileName, isDirectory: false)
        try copyAtomically(source, to: destination)
        return destination
    }

    private static func writeMemoryQualificationSentinel(
        _ record: MemoryQualificationResult,
        runID: String
    ) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(record)
        let relativeName = "memory-qualification-result.json"

        let appGroupURL = AppPaths.appSupportDir
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent(runID, isDirectory: true)
            .appendingPathComponent(relativeName, isDirectory: false)
        try FileManager.default.createDirectory(
            at: appGroupURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try data.write(to: appGroupURL, options: .atomic)

        guard let pullableRoot = IOSPullableDiagnosticsMirror.pullableRoot else {
            throw DiagnosticsError("pullable diagnostics directory is unavailable")
        }
        let pullableURL = pullableRoot
            .appendingPathComponent(runID, isDirectory: true)
            .appendingPathComponent(relativeName, isDirectory: false)
        try FileManager.default.createDirectory(
            at: pullableURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        // This is deliberately the final write observed by the shell poller.
        try data.write(to: pullableURL, options: .atomic)
    }

    private static func writeMemoryQualificationFailureMarker(
        _ record: IOSMemoryQualificationFailureStatus,
        runID: String
    ) throws {
        try record.validate()
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(record)
        guard data.count <= IOSMemoryQualificationFailureStatus.maximumEncodedBytes else {
            throw DiagnosticsError("memory qualification failure marker exceeded its bound")
        }
        let relativeName = "memory-qualification-failure.json"

        let appGroupURL = AppPaths.appSupportDir
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent(runID, isDirectory: true)
            .appendingPathComponent(relativeName, isDirectory: false)
        try FileManager.default.createDirectory(
            at: appGroupURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try data.write(to: appGroupURL, options: .atomic)

        guard let pullableRoot = IOSPullableDiagnosticsMirror.pullableRoot else {
            throw DiagnosticsError("pullable diagnostics directory is unavailable")
        }
        let pullableURL = pullableRoot
            .appendingPathComponent(runID, isDirectory: true)
            .appendingPathComponent(relativeName, isDirectory: false)
        try FileManager.default.createDirectory(
            at: pullableURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        // This terminal marker is written only on failure and can never be
        // mistaken for the successful result file by the host.
        try data.write(to: pullableURL, options: .atomic)
    }

    #if QVOICE_DEVICE_DIAGNOSTICS
    private static func writeCloneConditioningResult(
        _ record: CloneConditioningAcceptanceResult,
        runID: String
    ) throws {
        try writeCloneConditioningRecord(
            record,
            relativeName: "clone-conditioning-result.json",
            runID: runID,
            maximumEncodedBytes: 256 * 1024
        )
    }

    private static func writeCloneConditioningFailure(
        _ record: CloneConditioningAcceptanceFailure,
        runID: String
    ) throws {
        try writeCloneConditioningRecord(
            record,
            relativeName: "clone-conditioning-failure.json",
            runID: runID,
            maximumEncodedBytes: 4096
        )
    }

    private static func writeCloneConditioningRecord<T: Encodable>(
        _ record: T,
        relativeName: String,
        runID: String,
        maximumEncodedBytes: Int
    ) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(record)
        guard data.count <= maximumEncodedBytes else {
            throw DiagnosticsError("clone-conditioning terminal record exceeded its size bound")
        }
        let destinations: [URL] = [
            AppPaths.appSupportDir
                .appendingPathComponent("diagnostics", isDirectory: true)
                .appendingPathComponent(runID, isDirectory: true)
                .appendingPathComponent(relativeName, isDirectory: false),
            IOSPullableDiagnosticsMirror.pullableRoot?
                .appendingPathComponent(runID, isDirectory: true)
                .appendingPathComponent(relativeName, isDirectory: false),
        ].compactMap { $0 }
        guard destinations.count == 2 else {
            throw DiagnosticsError("pullable diagnostics directory is unavailable")
        }
        for destination in destinations {
            try FileManager.default.createDirectory(
                at: destination.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try data.write(to: destination, options: .atomic)
        }
    }
    #endif

    private static func makeOutputEvidence(
        for url: URL,
        artifactRelativePath: String = "output.wav"
    ) throws -> OutputEvidence {
        let file = try AVAudioFile(forReading: url)
        let frameCount = Int64(file.length)
        let sampleRate = file.fileFormat.sampleRate
        let channelCount = Int(file.fileFormat.channelCount)
        guard frameCount > 0, sampleRate > 0, channelCount > 0 else {
            throw DiagnosticsError("generated WAV has invalid sample metadata")
        }
        let values = try url.resourceValues(forKeys: [.fileSizeKey])
        guard let fileSize = values.fileSize, fileSize > 0 else {
            throw DiagnosticsError("generated WAV has no readable file size")
        }
        return OutputEvidence(
            artifactRelativePath: artifactRelativePath,
            sha256: try sha256Hex(for: url),
            byteCount: Int64(fileSize),
            durationSeconds: Double(frameCount) / sampleRate,
            sampleRate: sampleRate,
            channelCount: channelCount,
            frameCount: frameCount
        )
    }

    private static func sha256Hex(for url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while true {
            let chunk = try handle.read(upToCount: 1_048_576) ?? Data()
            if chunk.isEmpty { break }
            hasher.update(data: chunk)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private static func mirrorOutputToPullableDiagnostics(_ source: URL, runID: String) throws {
        guard let pullableRoot = IOSPullableDiagnosticsMirror.pullableRoot else {
            throw DiagnosticsError("pullable diagnostics directory is unavailable")
        }
        try copyAtomically(
            source,
            to: pullableRoot.appendingPathComponent(runID, isDirectory: true)
                .appendingPathComponent("output.wav", isDirectory: false)
        )
    }

    private static func copyAtomically(_ source: URL, to destination: URL) throws {
        let fileManager = FileManager.default
        let directory = destination.deletingLastPathComponent()
        try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        let temporary = directory.appendingPathComponent(".output-\(UUID().uuidString).tmp")
        defer { try? fileManager.removeItem(at: temporary) }
        try fileManager.copyItem(at: source, to: temporary)
        if fileManager.fileExists(atPath: destination.path) {
            try fileManager.removeItem(at: destination)
        }
        try fileManager.moveItem(at: temporary, to: destination)
    }

    private static func makeOutputPath(runID: String, model: ModelDescriptor) -> String {
        let dir = AppPaths.outputsDir
            .appendingPathComponent(model.outputSubfolder, isDirectory: true)
            .appendingPathComponent("device-diagnostics", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("\(runID).wav", isDirectory: false).path
    }

    private static func writeSpeechAssetSentinel(
        _ record: SpeechAssetBootstrapResult,
        runID: String
    ) {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        guard let data = try? encoder.encode(record) else {
            print("[speech-assets] could not encode completion evidence")
            return
        }
        let fileName = "speech-assets-done.json"
        let appGroupURL = AppPaths.appSupportDir
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent(runID, isDirectory: true)
            .appendingPathComponent(fileName, isDirectory: false)
        writeData(data, to: appGroupURL, label: "speech assets (app-group)")

        guard let pullableRoot = IOSPullableDiagnosticsMirror.pullableRoot else { return }
        let pullableURL = pullableRoot
            .appendingPathComponent(runID, isDirectory: true)
            .appendingPathComponent(fileName, isDirectory: false)
        // This is the final write observed by the host poller.
        writeData(data, to: pullableURL, label: "speech assets (pullable)")
    }

    private static func writeSentinel(_ record: SentinelRecord, runID: String) {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = (try? encoder.encode(record)) ?? Data()

        // 1) Canonical: the App-Group diagnostics dir, where the engine also writes its
        //    telemetry (`diagnostics/engine/generations.jsonl`).
        let groupRunDir = AppPaths.appSupportDir
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent(runID, isDirectory: true)
        writeData(data, to: groupRunDir.appendingPathComponent("device-diagnostics-done.json", isDirectory: false),
                  label: "sentinel (app-group)")

        // 2) Pullable mirror in the app's OWN container. devicectl `copy from
        //    --domain-type appDataContainer` CAN pull this, but it CANNOT pull the
        //    App-Group container (confirmed: any source there fails with a bogus
        //    "File paths cannot contain '..'"). scripts/ios_device.sh pulls
        //    `Library/Caches/Vocello/diagnostics` from appDataContainer, so the bench
        //    needs the sentinel + the engine telemetry here too.
        guard let pullableRoot = IOSPullableDiagnosticsMirror.pullableRoot else { return }
        // Publish the exact generation telemetry before the pullable sentinel: the
        // sentinel is the completion barrier observed by the shell poller.
        IOSPullableDiagnosticsMirror.syncGenerationTelemetry(
            generationID: record.generationID,
            from: AppPaths.appSupportDir.appendingPathComponent("diagnostics", isDirectory: true),
            into: pullableRoot
        )
        writeData(data, to: pullableRoot.appendingPathComponent(runID, isDirectory: true)
                    .appendingPathComponent("device-diagnostics-done.json", isDirectory: false),
                  label: "sentinel (pullable)")
    }

    private static func writeData(_ data: Data, to url: URL, label: String) {
        do {
            try FileManager.default.createDirectory(
                at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: url, options: .atomic)
            print("[device-diagnostics] \(label) → \(url.path)")
        } catch {
            print("[device-diagnostics] could not write \(label): \(error.localizedDescription)")
        }
    }

    /// Mirror `IOSDeviceDiagnosticsRecorder` / `MLXTTSEngine` run-ID sanitization so
    /// the sentinel lands in the same `diagnostics/<runID>/` directory.
    private static func safeRunID(from rawValue: String?) -> String? {
        guard let trimmed = rawValue?.trimmingCharacters(in: .whitespacesAndNewlines),
              !trimmed.isEmpty else { return nil }
        let safe = trimmed.map { character -> Character in
            if character.isLetter || character.isNumber || character == "-" || character == "_" {
                return character
            }
            return "_"
        }
        return String(safe)
    }

    private struct DiagnosticsError: LocalizedError {
        let message: String
        init(_ message: String) { self.message = message }
        var errorDescription: String? { message }
    }

    private struct MemoryQualificationTakeEnvironment: Codable {
        let loadAverage1Minute: Double?
        let freeStorageBytes: UInt64?
        let uptimeSeconds: Double
        let lowPowerModeEnabled: Bool
        let thermalState: String
    }

    private struct MemoryQualificationTakeResult: Codable {
        let takeIndex: Int
        let generationID: String
        let cell: String
        let mode: String
        let modelID: String
        let variant: String
        let length: String
        let warmState: String
        let repetition: Int
        let audioSeconds: Double
        let wallSeconds: Double
        let firstChunkMS: Double?
        let outputFileName: String
        let environment: MemoryQualificationTakeEnvironment
    }

    private struct MemoryQualificationDeclaration: Codable {
        let policyID: String
        let modeOrder: [String]
        let variant: String
        let length: String
        let repetitionsPerMode: Int
        let expectedTakeCount: Int
    }

    private struct MemoryQualificationResult: Codable {
        var schemaVersion = 1
        var status = "pass"
        let runID: String
        let label: String
        let startedAt: String
        let finishedAt: String
        let telemetryMode: String
        let seed: UInt64
        let streaming: Bool
        let fixtureDigests: [String: String]
        let memoryQualification: MemoryQualificationDeclaration
        let takes: [MemoryQualificationTakeResult]
    }

    #if QVOICE_DEVICE_DIAGNOSTICS
    private struct CloneConditioningAcceptancePlan {
        let takeIndex: Int
        let cell: String
        let expectedConditioningMode: String
        let expectedTranscriptMode: String
        let expectedArtifactScope: String
        let expectedTranscriptBacked: Bool
        let expectedXVectorOnly: Bool
        let reference: CloneReference
    }

    private struct CloneConditioningAcceptanceTakeResult: Codable {
        let takeIndex: Int
        let generationID: String
        let cell: String
        let mode: String
        let modelID: String
        let conditioningMode: String
        let transcriptMode: String
        let promptArtifactScope: String
        let transcriptBacked: Bool
        let xVectorOnly: Bool
        let supportsXVectorOnlyClone: Bool
        let optimizedHandlerUsed: Bool
        let promptMaterialized: Bool
        let conditioningReused: Bool
        let preparedCloneCacheHit: Bool
        let referenceAudioSHA256: String
        let promptAssemblySHA256: String
        let wallSeconds: Double
        let outputFileName: String
        let outputEvidence: OutputEvidence
        let outputVerification: GenerationOutputVerifier.Result
    }

    private struct CloneConditioningAcceptanceResult: Codable {
        var schemaVersion = 1
        var status = "pass"
        let runID: String
        let startedAt: String
        let finishedAt: String
        let seed: UInt64
        let samplingVariation: String
        let voiceIDDigest: String
        let referenceAudioSHA256: String
        let referenceTranscriptSHA256: String
        let scratchCleanupVerified: Bool
        let takes: [CloneConditioningAcceptanceTakeResult]
    }

    private struct CloneConditioningAcceptanceFailure: Codable {
        var schemaVersion = 1
        var status = "failed"
        let runID: String
        let failedAt: String
        let failureCode: String
        let completedTakeCount: Int
        let expectedTakeCount: Int
        let failedTakeIndex: Int?
    }

    private enum CloneConditioningAcceptanceFailureCode: String {
        case invalidEnvironment = "invalid_environment"
        case runtimeCapabilityUnavailable = "runtime_capability_unavailable"
        case fixtureUnavailable = "fixture_unavailable"
        case fixtureIdentityMismatch = "fixture_identity_mismatch"
        case scratchPreparationFailed = "scratch_preparation_failed"
        case takeIdentityUnavailable = "take_identity_unavailable"
        case generationFailed = "generation_failed"
        case conditioningContractFailed = "conditioning_contract_failed"
        case outputValidationFailed = "output_validation_failed"
        case telemetryValidationFailed = "telemetry_validation_failed"
        case outputMirrorFailed = "output_mirror_failed"
        case interrupted
        case scratchCleanupFailed = "scratch_cleanup_failed"
        case resultWriteFailed = "result_write_failed"
    }
    #endif

    private struct PreparedSpeechAssetModule {
        let recordIndex: Int
        let resolvedLocale: Locale
        let module: DictationTranscriber
    }

    private enum SpeechAssetFailureCode: String {
        case invalidLocaleList = "invalid_locale_list"
        case unsupportedLocale = "unsupported_locale"
        case installationRequestFailed = "installation_request_failed"
        case downloadFailed = "download_failed"
        case postInstallationVerificationFailed = "post_installation_verification_failed"
        case legacyRecognizerNotReady = "legacy_recognizer_not_ready"
        case unknown
    }

    private struct SpeechAssetBootstrapError: Error {
        let code: SpeechAssetFailureCode

        init(_ code: SpeechAssetFailureCode) {
            self.code = code
        }
    }

    private struct SpeechAssetBootstrapResult: Codable {
        var schemaVersion = 1
        let runID: String
        let startedAt: String
        var finishedAt: String?
        var status = "failed"
        let requestedLocaleIdentifiers: [String]
        var maximumReservedLocales: Int?
        var reservedLocaleCountBefore: Int?
        var reservedLocaleCountAfter: Int?
        var installedLocaleCountBefore: Int?
        var installedLocaleCountAfter: Int?
        var aggregateStatusBefore: String?
        var aggregateStatusAfter: String?
        var installationRequestCreated = false
        var installationAttempted = false
        var assetInventoryReady: Bool?
        var vocelloLegacyReady: Bool?
        var failureCode: String?
        var failureDomain: String?
        var failureCodeValue: Int?
        var locales: [SpeechAssetLocaleResult] = []
    }

    private struct SpeechAssetLocaleResult: Codable {
        let requestedIdentifier: String
        var resolvedIdentifier: String?
        var moduleSelectedIdentifiers: [String] = []
        var statusBefore: String?
        var statusAfter: String?
        var reservedBefore: Bool?
        var reservedAfter: Bool?
        var installedLocalePresentBefore: Bool?
        var installedLocalePresentAfter: Bool?
        var legacyRecognizerIdentifier: String?
        var legacyRecognizerAvailable: Bool?
        var legacySupportsOnDeviceRecognition: Bool?
        var vocelloSelectedLegacyIdentifier: String?
        var vocelloSelectedLegacyAvailable: Bool?
        var vocelloSelectedLegacySupportsOnDeviceRecognition: Bool?
        var vocelloLegacyReady: Bool?
    }

    private struct SentinelRecord: Codable {
        // `var` (not `let`) for the defaulted fields: a `let` with an initial value is
        // skipped by Codable decode (warning) and, for the device fields, a default
        // expression touching MainActor `UIDevice` would be evaluated in the nonisolated
        // synthesized init (Swift 6 error). So defaults stay literal/`var`, and device/
        // bundle fields are passed in from the @MainActor call site.
        var schemaVersion = 2
        let runID: String
        let generationID: String
        let mode: String
        let variant: String
        let promptCharacters: Int
        let startedAt: String
        var finishedAt: String?
        var status = "error"
        var uiLanguageHint: String?
        var requestedLanguageHint: String
        var languageHintSource: String
        var resolvedLanguageHint: String?
        var resolvedPromptAssemblyDigest: String?
        var promptDigestScope: String?
        var seed: UInt64?
        var samplingVariation: String?
        var preGenerationModelID: String?
        var preGenerationWarmState: String?
        var modelID: String?
        var modelName: String?
        var customSpeakerID: String?
        var fixtureDigest: String?
        var outputEvidence: OutputEvidence?
        var durationSeconds: Double?
        var wallSeconds: Double?
        var realtimeFactor: Double?
        var finishReason: String?
        var error: String?
        var outputVerification: GenerationOutputVerifier.Result?
        /// Typed `languageASR` quality-registry gate derived from
        /// `outputVerification` — per-take evidence for standard/canonical
        /// depth composition (Stage 3), mirroring the prosody sidecar pattern.
        var languageASRGate: GenerationQualityGateResult?
        /// Calls + lifecycle transitions observed during the run (see
        /// `IOSInterruptionRecorder`) — explains doomed runs. Omitted when clean.
        var interruptions: [IOSInterruptionRecorder.Event]?
        let deviceModel: String
        let systemName: String
        let systemVersion: String
        let bundleVersion: String?
        let buildVersion: String?
    }

    private struct OutputEvidence: Codable {
        let artifactRelativePath: String
        let sha256: String
        let byteCount: Int64
        let durationSeconds: Double
        let sampleRate: Double
        let channelCount: Int
        let frameCount: Int64
    }
}
