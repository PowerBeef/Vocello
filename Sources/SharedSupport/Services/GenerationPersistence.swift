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

    /// Hands off playback synchronously, durably queues the finished take,
    /// then schedules its idempotent SQLite commit off the main actor. The
    /// outbox intent exists before this method returns, so a process exit or
    /// database failure cannot silently orphan a published WAV.
    ///
    /// Behavior change from May 2026: persistence errors that occur
    /// AFTER playback handoff are no longer thrown — they're logged via
    /// `print()` only when runtime diagnostics are enabled. Rationale: the user
    /// already heard their
    /// audio play. A persistence failure means the generation won't
    /// appear in History, which is a quiet non-blocking failure that
    /// doesn't affect the immediate UX. Surfacing it via a thrown error
    /// previously caused an alert that landed AFTER playback was already
    /// running, confusing users who weren't sure what failed.
    ///
    /// UI win: the synchronous DB save (5-30ms blocking on @MainActor)
    /// is gone. UI rendering of the just-completed generation is no
    /// longer hitched by the SQLite write.
    static func persistAndAutoplay(
        _ generation: Generation,
        result: PersistenceGenerationResult,
        text: String,
        audioPlayer: AudioPlayerViewModel,
        caller: String
    ) {
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

        schedulePersistence(generation, caller: caller)
    }

    /// Schedules only the SQLite save + history-event broadcast. iOS
    /// Studio uses this when the generated output is owned by the inline
    /// player instead of the global now-playing model.
    static func persist(
        _ generation: Generation,
        caller: String
    ) {
        AppPerformanceSignposts.emit("Final File Ready")
        schedulePersistence(generation, caller: caller)
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

    private static func schedulePersistence(
        _ generation: Generation,
        caller: String
    ) {
        let entry: GenerationHistoryOutboxEntry
        do {
            entry = try GenerationHistoryRecovery.enqueue(generation)
        } catch {
            if TelemetryGate.resolvedEnabled {
                print("[Performance][\(caller)] history_outbox_enqueue_failed")
            }
            announceRecoveryStateChanged()
            return
        }

        // The task is deliberately unstructured because persistence must
        // outlive the initiating view. Unlike the retired Task.detached route,
        // it preserves task-local provenance while explicitly leaving
        // MainActor; durability and retry are owned by the outbox.
        Task { @concurrent in
            let saveStart = DispatchTime.now().uptimeNanoseconds
            let savedGeneration: Generation
            do {
                savedGeneration = try await GenerationHistoryRecovery.coordinator.commit(entry)
            } catch {
                if TelemetryGate.resolvedEnabled {
                    print("[Performance][\(caller)] db_save_deferred_to_history_outbox")
                }
                await MainActor.run { announceRecoveryStateChanged() }
                return
            }
            let saveMS = elapsedMs(since: saveStart)
            if TelemetryGate.resolvedEnabled {
                print("[Performance][\(caller)] db_save_wall_ms=\(saveMS) (off-main)")
            }
            await MainActor.run {
                let notificationStart = DispatchTime.now().uptimeNanoseconds
                #if canImport(QwenVoiceNative)
                GenerationLibraryEvents.shared.announceGenerationAppended(savedGeneration)
                #else
                NotificationCenter.default.post(name: .generationSaved, object: nil)
                #endif
                if TelemetryGate.resolvedEnabled {
                    print("[Performance][\(caller)] history_notification_wall_ms=\(elapsedMs(since: notificationStart))")
                }
                announceRecoveryStateChanged()
            }
        }
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
