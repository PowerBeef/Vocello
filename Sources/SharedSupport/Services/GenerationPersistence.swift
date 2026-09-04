import Foundation

#if canImport(QwenVoiceCore)
import QwenVoiceCore
#endif

#if canImport(QwenVoiceNative)
import QwenVoiceNative
#endif

#if canImport(QwenVoiceNative)
typealias PersistenceGenerationResult = QwenVoiceNative.GenerationResult
#elseif canImport(QwenVoiceCore)
typealias PersistenceGenerationResult = QwenVoiceCore.GenerationResult
#endif

/// Shared generation persistence and autoplay logic used by all three generation views.
@MainActor
enum GenerationPersistence {

    /// Playback is handed off before any storage work. A typed result separates
    /// successful synthesis from History acceptance; failed enqueue is visibly
    /// recoverable during this app session and never claimed crash-safe. GRDB
    /// commits off MainActor through the existing coordinator and writer queue.
    @discardableResult
    static func persistAndAutoplay(
        _ generation: Generation,
        result: PersistenceGenerationResult,
        text: String,
        audioPlayer: AudioPlayerViewModel,
        caller: String
    ) async -> GenerationHistoryPersistenceOutcome {
        emitClonePromptMetricsIfNeeded(result: result, caller: caller)
        AppPerformanceSignposts.emit("Final File Ready")

        if result.usedStreaming {
            audioPlayer.completeStreamingPreview(
                result: result,
                title: String(text.prefix(40)),
                shouldAutoPlay: AudioService.shouldAutoPlay
            )
        } else {
            let autoplayStart = DispatchTime.now().uptimeNanoseconds
            audioPlayer.playFile(
                result.audioPath,
                title: String(text.prefix(40)),
                isAutoplay: AudioService.shouldAutoPlay,
                presentationContext: .generatePreview
            )
            if TelemetryGate.resolvedEnabled {
                print("[Performance][\(caller)] autoplay_start_wall_ms=\(elapsedMs(since: autoplayStart))")
            }
        }

        return await saveToHistory(generation, caller: caller)
    }

    /// Performs only the SQLite save + history-event broadcast. iOS
    /// Studio uses this when the generated output is owned by the inline
    /// player instead of the global now-playing model.
    @discardableResult
    static func persist(
        _ generation: Generation,
        caller: String
    ) async -> GenerationHistoryPersistenceOutcome {
        AppPerformanceSignposts.emit("Final File Ready")
        return await saveToHistory(generation, caller: caller)
    }

    private static func emitClonePromptMetricsIfNeeded(
        result: PersistenceGenerationResult,
        caller: String
    ) {
        let timings = result.diagnosticTimingsMS
        let booleans = result.diagnosticBooleanFlags
        let strings = result.diagnosticStringFlags
        let hasCloneMetrics = timings.keys.contains { $0.hasPrefix("clone_prompt_") }
            || booleans.keys.contains { $0.hasPrefix("clone_prompt_") || $0 == "clone_transcript_backed" }
            || strings.keys.contains { $0.hasPrefix("clone_") }
        guard hasCloneMetrics else { return }

        var fields: [String] = ["caller=\(caller)"]
        for key in [
            "clone_prompt_artifact_load",
            "clone_prompt_build",
            "clone_prompt_resolve",
            "prime_clone_reference",
        ] {
            if let value = timings[key] {
                fields.append("\(key)_ms=\(value)")
            }
        }
        for key in [
            "clone_prompt_artifact_hit",
            "clone_prompt_memory_hit",
            "clone_prompt_built",
            "clone_transcript_backed",
            "clone_reference_was_primed",
            "clone_conditioning_reused",
        ] {
            if let value = booleans[key] {
                fields.append("\(key)=\(value ? "true" : "false")")
            }
        }
        for key in [
            "clone_transcript_mode",
            "clone_prompt_artifact_scope",
        ] {
            if let value = strings[key], !value.isEmpty {
                fields.append("\(key)=\(value)")
            }
        }
        AppPerformanceSignposts.emit("Clone Prompt Metrics", message: fields.joined(separator: " "))
    }

    private static func saveToHistory(
        _ generation: Generation,
        caller: String
    ) async -> GenerationHistoryPersistenceOutcome {
        // Durable intent exists before this suspension. Cancellation, view
        // teardown, or database failure cannot discard the pending record.
        let saveStart = DispatchTime.now().uptimeNanoseconds
        let outcome = await GenerationHistoryRecovery.unqueued.persist(
            generation,
            enqueue: { try GenerationHistoryRecovery.enqueue($0) },
            commit: { try await GenerationHistoryRecovery.coordinator.commit($0) },
            onSaved: { savedGeneration in
                #if canImport(QwenVoiceNative)
                GenerationLibraryEvents.shared.announceGenerationAppended(savedGeneration)
                #else
                NotificationCenter.default.post(name: .generationSaved, object: nil)
                #endif
            }
        )
        let saveMS = elapsedMs(since: saveStart)
        if TelemetryGate.resolvedEnabled {
            print("[Performance][\(caller)] history_save_outcome=\(outcome) wall_ms=\(saveMS)")
        }
        announceRecoveryStateChanged()
        return outcome
    }

    private static func announceRecoveryStateChanged() {
        NotificationCenter.default.post(name: .generationHistoryRecoveryChanged, object: nil)
    }

    nonisolated private static func elapsedMs(since start: UInt64) -> Int {
        Int((DispatchTime.now().uptimeNanoseconds - start) / 1_000_000)
    }
}

extension Notification.Name {
    static let generationHistoryRecoveryChanged = Notification.Name("generationHistoryRecoveryChanged")
}
