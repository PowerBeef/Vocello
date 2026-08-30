import Combine
import Foundation
import OSLog
import QwenVoiceCore
import QwenVoiceEngineSupport

private final class EngineReplyHandlerBox: @unchecked Sendable {
    let reply: (Data) -> Void

    init(reply: @escaping (Data) -> Void) {
        self.reply = reply
    }
}

/// Serializes diagnostic JSONL appends so concurrent detached Tasks don't
/// interleave partial lines or race on file-handle creation.
private actor DiagnosticEventRecorder {
    func append(line: String, to url: URL) {
        guard TelemetryGate.resolvedEnabled else { return }
        let diagnosticsDirectory = url.deletingLastPathComponent()
        do {
            try FileManager.default.createDirectory(at: diagnosticsDirectory, withIntermediateDirectories: true)
            if FileManager.default.fileExists(atPath: url.path) {
                let handle = try FileHandle(forWritingTo: url)
                defer { try? handle.close() }
                try handle.seekToEnd()
                if let encoded = line.data(using: .utf8) {
                    try handle.write(contentsOf: encoded)
                }
            } else {
                try line.write(to: url, atomically: true, encoding: .utf8)
            }
        } catch {
            diagnosticEventLogger.error("Failed to record diagnostic event: \(error.localizedDescription, privacy: .public)")
        }
    }
}

private let diagnosticEventRecorder = DiagnosticEventRecorder()
private let diagnosticEventLogger = Logger(
    subsystem: "com.qwenvoice.app",
    category: "DiagnosticEventRecorder"
)

/// Bridges request acceptance on the XPC command task to the detached event
/// drain without blocking either path. Entries are consumed by the first chunk
/// for that generation, so the map remains bounded even across long sessions.
private final class EngineServiceRequestTimingRegistry: @unchecked Sendable {
    private let lock = NSLock()
    private var acceptedUptimeByGeneration: [UUID: Double] = [:]

    func recordAcceptance(for generationID: UUID) {
        lock.lock()
        if acceptedUptimeByGeneration.count >= 64,
           let oldest = acceptedUptimeByGeneration.min(by: { $0.value < $1.value })?.key {
            acceptedUptimeByGeneration.removeValue(forKey: oldest)
        }
        acceptedUptimeByGeneration[generationID] = ProcessInfo.processInfo.systemUptime
        lock.unlock()
    }

    func consumeAcceptance(for generationID: UUID) -> Double? {
        lock.lock()
        defer { lock.unlock() }
        return acceptedUptimeByGeneration.removeValue(forKey: generationID)
    }

    func discard(_ generationID: UUID?) {
        guard let generationID else { return }
        lock.lock()
        acceptedUptimeByGeneration.removeValue(forKey: generationID)
        lock.unlock()
    }
}

@MainActor
private final class RuntimeContext: @unchecked Sendable {
    let appSupportDirectory: URL
    let engine: MLXTTSEngine
    var cancellables: Set<AnyCancellable> = []
    var lastPublishedEvent: GenerationEvent?
    var lastPublishedSnapshot: TTSEngineSnapshot?
    let requestTimings = EngineServiceRequestTimingRegistry()
    /// One scoped forwarder for the currently active generation. The service
    /// admits only one generation at a time, so replacing this task cannot
    /// cross streams between requests.
    var eventForwardingTask: Task<Void, Never>?

    init(appSupportDirectory: URL, engine: MLXTTSEngine) {
        self.appSupportDirectory = appSupportDirectory
        self.engine = engine
    }
}

final class EngineServiceHost: NSObject, NSXPCListenerDelegate, QwenVoiceEngineServiceXPCProtocol, @unchecked Sendable {
    static let shared = EngineServiceHost()

    private struct ActiveSession {
        let id: UUID
        let eventSink: QwenVoiceEngineClientEventXPCProtocol
    }

    private static let logger = Logger(
        subsystem: "com.qwenvoice.app",
        category: "EngineServiceHost"
    )

    /// Encodes a failure-shaped reply that preserves the original request id
    /// so the client can match it to the pending request and resolve the
    /// in-flight continuation. The previous implementation used a static
    /// pre-encoded constant with a random `UUID()`, which the client silently
    /// dropped (no pending request matched the id) — leaving long-timeout
    /// `.generate` calls hung
    /// indefinitely whenever response encoding failed (e.g., a non-finite
    /// numeric metadata field made it into the payload).
    private static func encodeFailureFallback(for requestID: UUID, underlyingError: Error) -> Data {
        let fallback = EngineReplyEnvelope(
            id: requestID,
            reply: .failure(
                RemoteErrorPayload(
                    message: "The engine service failed to encode its reply: \(underlyingError.localizedDescription)"
                )
            )
        )
        do {
            return try EngineServiceCodec.encode(fallback)
        } catch {
            EngineServiceHost.logger.fault(
                "Failed to encode engine-service failure fallback for id \(requestID.uuidString, privacy: .public): \(error.localizedDescription, privacy: .public)"
            )
            // Degenerate path: even a minimal failure envelope failed to
            // encode. Returning empty Data forces the client into its
            // `invalidReply` disconnect handler, which is preferable to
            // silently dropping the reply because the id doesn't match.
            return Data()
        }
    }

    /// Synchronous-only lock wrapper. `NSLock.lock()`/`unlock()` are marked
    /// `noasync` in recent SDKs, so the host uses this for short critical
    /// sections that are accessed from both sync and async call sites.
    private final class SynchronousLock {
        private let lock = NSLock()
        func withLock<T>(_ body: () -> T) -> T {
            lock.lock()
            defer { lock.unlock() }
            return body()
        }
    }

    private let sessionLock = SynchronousLock()
    private let activeGenerationCoordinator = ServiceActiveGenerationCoordinator()
    private var activeSession: ActiveSession?
    private var runtimeContext: RuntimeContext?
    private var droppedEncodeEventCount = 0

    func listener(_ listener: NSXPCListener, shouldAcceptNewConnection newConnection: NSXPCConnection) -> Bool {
        let sessionID = UUID()
        newConnection.setCodeSigningRequirement(
            EngineServiceTrustPolicy.clientRequirementForCurrentBundle()
        )
        newConnection.exportedInterface = NSXPCInterface(with: QwenVoiceEngineServiceXPCProtocol.self)
        newConnection.exportedObject = self
        newConnection.remoteObjectInterface = NSXPCInterface(with: QwenVoiceEngineClientEventXPCProtocol.self)
        let eventSink = newConnection.remoteObjectProxyWithErrorHandler { [weak self] error in
            self?.handleSessionEnded(
                sessionID: sessionID,
                message: "Event sink remote error: \(error.localizedDescription)"
            )
        } as? QwenVoiceEngineClientEventXPCProtocol
        guard let eventSink else {
            Self.logger.error("Failed to create event sink for new engine-service session.")
            return false
        }
        activateSession(id: sessionID, eventSink: eventSink)
        newConnection.invalidationHandler = { [weak self] in
            self?.handleSessionEnded(
                sessionID: sessionID,
                message: "Engine-service session invalidated."
            )
        }
        newConnection.interruptionHandler = { [weak self] in
            self?.handleSessionEnded(
                sessionID: sessionID,
                message: "Engine-service session interrupted."
            )
        }
        newConnection.resume()
        Task { @MainActor [weak self] in
            guard let self, let runtimeContext = self.runtimeContext else { return }
            self.publish(.snapshot(Self.snapshot(for: runtimeContext.engine)), toSessionID: sessionID)
        }
        return true
    }

    func perform(_ payload: Data, withReply reply: @escaping (Data) -> Void) {
        let replyHandler = EngineReplyHandlerBox(reply: reply)
        let capturedSessionID = sessionLock.withLock { activeSession?.id }
        Task.detached(priority: .userInitiated) { [weak self, payload] in
            guard let self else { return }
            // Explicit process-level importance for the span of every command.
            // The XPC reply for `.generate` stays open across the whole
            // generation, but the implicit transaction boost does not confer
            // interactive darwin scheduling for the service's GPU work: the
            // 2026-07-23 characterization measured the identical -O engine at
            // RTF 1.81 in an interactive-class process vs 0.97 forced to
            // background class and ~0.75 in this service. This assertion is
            // the documented counter to that decay; it releases at reply.
            let processActivity = ProcessInfo.processInfo.beginActivity(
                options: [.userInitiated, .latencyCritical],
                reason: "vocello-engine-command"
            )
            defer { ProcessInfo.processInfo.endActivity(processActivity) }
            let response = await self.handleCommandPayload(payload)
            let encodedResponse: Data
            do {
                encodedResponse = try EngineServiceCodec.encode(response)
            } catch {
                Self.logger.error(
                    "Failed to encode engine-service reply (id \(response.id.uuidString, privacy: .public)): \(error.localizedDescription, privacy: .public)"
                )
                encodedResponse = Self.encodeFailureFallback(
                    for: response.id,
                    underlyingError: error
                )
            }
            let sessionStillActive = self.sessionLock.withLock {
                self.activeSession?.id == capturedSessionID
            }
            guard sessionStillActive else {
                Self.logger.debug("Dropping engine-service reply for a session that is no longer active.")
                return
            }
            replyHandler.reply(encodedResponse)
        }
    }

    @MainActor
    private func handleCommandPayload(_ payload: Data) async -> EngineReplyEnvelope {
        do {
            let request = try EngineServiceCodec.decode(EngineRequestEnvelope.self, from: payload)
            do {
                return EngineReplyEnvelope(
                    id: request.id,
                    reply: try await perform(request.command)
                )
            } catch {
                return EngineReplyEnvelope(
                    id: request.id,
                    reply: .failure(RemoteErrorPayload.make(for: error))
                )
            }
        } catch {
            Self.logger.error("Failed to decode engine request envelope: \(error.localizedDescription, privacy: .public)")
            return EngineReplyEnvelope(
                id: UUID(),
                reply: .failure(RemoteErrorPayload.make(for: error))
            )
        }
    }

    @MainActor
    private func perform(_ command: EngineCommand) async throws -> EngineReply {
        switch command {
        case .initialize(let appSupportDirectoryPath, let telemetryMode, let forcedMemoryClass):
            // The app process resolves the telemetry MODE (env + the persisted 7-tap
            // gesture flag, neither of which crosses the process boundary) and reports
            // it here. One-way latch — enables durable telemetry in this engine-service
            // process, and carries `verbose` so the raw-sample sidecar can fire.
            TelemetryGate.applyHandshakeMode(NativeTelemetryMode(rawValue: telemetryMode) ?? .off)
            // Benchmark tier override (env doesn't cross to this process either) —
            // forces the constrained-tier code paths so memory pressure is measurable.
            NativeDeviceClassGate.applyHandshakeForcedClass(forcedMemoryClass)
            let runtimeContext = try makeOrReuseRuntimeContext(
                appSupportDirectory: URL(fileURLWithPath: appSupportDirectoryPath, isDirectory: true)
            )
            try await runtimeContext.engine.initialize(appSupportDirectory: runtimeContext.appSupportDirectory)
            return .snapshot(Self.snapshot(for: runtimeContext.engine))
        case .ping:
            _ = try await requireRuntimeContext().engine.ping()
            return .capabilities(.macOSXPCDefault)
        case .loadModel(let id):
            try await requireRuntimeContext().engine.loadModel(id: id)
            return .void
        case .unloadModel:
            try await requireRuntimeContext().engine.unloadModel()
            return .void
        case .ensureModelLoadedIfNeeded(let id):
            try await requireRuntimeContext().engine.ensureModelLoadedIfNeeded(id: id)
            return .void
        case .prewarmModelIfNeeded(let request):
            try await requireRuntimeContext().engine.prewarmModelIfNeeded(for: request)
            return .void
        case .prefetchInteractiveReadinessIfNeeded(let request, let customPrewarmDepth):
            let diagnostics = try await requireRuntimeContext().engine.prefetchInteractiveReadinessIfNeeded(
                for: request,
                customPrewarmDepth: customPrewarmDepth
            )
                ?? InteractivePrefetchDiagnostics(
                    timingsMS: [:],
                    booleanFlags: [:],
                    requestKey: nil
                )
            return .interactivePrefetchDiagnostics(diagnostics)
        case .ensureCloneReferencePrimed(let modelID, let reference):
            try await requireRuntimeContext().engine.ensureCloneReferencePrimed(
                modelID: modelID,
                reference: reference
            )
            return .void
        case .cancelClonePreparationIfNeeded:
            try await requireRuntimeContext().engine.cancelClonePreparationIfNeeded()
            return .void
        case .generate(let request):
            let runtimeContext = try requireRuntimeContext()
            let request = request.generationID == nil
                ? request.withGenerationID(UUID())
                : request
            let requestGenerationID = request.generationID!
            let generationCoordinator = activeGenerationCoordinator
            // Reserve before touching timing, transport, or model work. A
            // rejected second request therefore cannot cancel the accepted
            // request's forwarder or start a task that reaches the engine.
            let reservation = try await generationCoordinator.reserve()
            let generationTask = Task { @MainActor in
                guard await generationCoordinator.waitUntilOpen(reservation) else {
                    throw CancellationError()
                }
                // Enter the engine even when cancellation arrived after bind:
                // its generation-scoped router must begin and publish the
                // accepted request's normal cancellation terminal so the
                // already-installed event forwarder can drain and retire.
                return try await runtimeContext.engine.generate(request)
            }

            let mayOpen: Bool
            do {
                mayOpen = try await generationCoordinator.bind(
                    reservation,
                    cancel: { generationTask.cancel() },
                    waitForTermination: { _ = await generationTask.result }
                )
            } catch {
                generationTask.cancel()
                await generationCoordinator.abort(reservation)
                _ = await generationTask.result
                throw error
            }
            guard mayOpen else {
                generationTask.cancel()
                _ = await generationTask.result
                await generationCoordinator.finish(reservation)
                throw CancellationError()
            }

            runtimeContext.requestTimings.recordAcceptance(for: requestGenerationID)
            let eventForwardingTask = startEventForwarding(
                generationID: requestGenerationID,
                runtimeContext: runtimeContext
            )
            runtimeContext.eventForwardingTask = eventForwardingTask
            var didOpen = false
            do {
                try await generationCoordinator.open(reservation)
                didOpen = true
                let result = try await generationTask.value
                await eventForwardingTask.value
                runtimeContext.eventForwardingTask = nil
                await generationCoordinator.finish(reservation)
                return .generationResult(result)
            } catch {
                runtimeContext.requestTimings.discard(requestGenerationID)
                generationTask.cancel()
                _ = await generationTask.result
                if didOpen {
                    await eventForwardingTask.value
                } else {
                    eventForwardingTask.cancel()
                    await eventForwardingTask.value
                }
                runtimeContext.eventForwardingTask = nil
                await generationCoordinator.finish(reservation)
                throw error
            }
        case .cancelActiveGeneration:
            let runtimeContext = try requireRuntimeContext()
            try await runtimeContext.engine.cancelActiveGeneration(reason: .user)
            await activeGenerationCoordinator.cancelCurrent()
            runtimeContext.engine.clearGenerationActivity()
            return .void
        case .listPreparedVoices:
            return .preparedVoices(try await requireRuntimeContext().engine.listPreparedVoices())
        case .preparePreparedVoiceCandidate(let name, let audioPath, let transcript, let replacingVoiceID):
            return .preparedVoiceCandidate(
                try await requireRuntimeContext().engine.preparePreparedVoiceCandidate(
                    name: name,
                    audioPath: audioPath,
                    transcript: transcript,
                    replacingVoiceID: replacingVoiceID
                )
            )
        case .preparePreparedVoiceCandidateV2(
            let name,
            let audioPath,
            let transcript,
            let enrollmentMetadata,
            let replacingVoiceID
        ):
            return .preparedVoiceCandidate(
                try await requireRuntimeContext().engine.preparePreparedVoiceCandidate(
                    name: name,
                    audioPath: audioPath,
                    transcript: transcript,
                    replacingVoiceID: replacingVoiceID,
                    enrollmentMetadata: enrollmentMetadata
                )
            )
        case .commitPreparedVoiceCandidate(let id):
            return .preparedVoice(
                try await requireRuntimeContext().engine.commitPreparedVoiceCandidate(id: id)
            )
        case .discardPreparedVoiceCandidate(let id):
            try await requireRuntimeContext().engine.discardPreparedVoiceCandidate(id: id)
            return .void
        case .enrollPreparedVoice(let name, let audioPath, let transcript):
            return .preparedVoice(
                try await requireRuntimeContext().engine.enrollPreparedVoice(
                    name: name,
                    audioPath: audioPath,
                    transcript: transcript
                )
            )
        case .deletePreparedVoice(let id):
            try await requireRuntimeContext().engine.deletePreparedVoice(id: id)
            return .void
        case .clearGenerationActivity:
            try requireRuntimeContext().engine.clearGenerationActivity()
            return .void
        case .clearVisibleError:
            try requireRuntimeContext().engine.clearVisibleError()
            return .void
        case .shutdownWhenIdle:
            // Retirement-to-reclaim: exiting is the only way to return MLX
            // heap fragmentation + Metal shader caches to the OS. Refuse
            // while generating; the client treats the exit as expected and
            // relaunches lazily on the next command.
            guard await !activeGenerationCoordinator.hasActive else {
                throw TTSEngineError.generationFailed(
                    "Engine is busy; retirement refused."
                )
            }
            if let runtimeContext {
                try? await runtimeContext.engine.unloadModel()
            }
            // Grace period so the `.void` reply flushes over the wire
            // before the process dies.
            DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(250)) {
                exit(0)
            }
            return .void
        }
    }

    @MainActor
    private func makeOrReuseRuntimeContext(appSupportDirectory: URL) throws -> RuntimeContext {
        if let runtimeContext,
           runtimeContext.appSupportDirectory.standardizedFileURL == appSupportDirectory.standardizedFileURL {
            return runtimeContext
        }

        let manifestURL = try Self.locateManifestURL()
        let registry = try ContractBackedModelRegistry(manifestURL: manifestURL)
            .expandedForPlatform(
                .macOS,
                deviceClass: NativeMemoryPolicyResolver.deviceClass(),
                includeBaseAliases: true
            )
        // Skip the dedicated custom-prewarm step on floor8GBMac to
        // match the iOS in-process engine's policy (which has done this
        // since launch). The prewarm cost
        // moves into the generation proper rather than running upfront,
        // and on a memory-constrained Mac that's the right trade:
        // model load completes faster, peak RSS at startup is lower,
        // and steady-state warm-medium RTF is essentially unaffected
        // (the prewarm work happens once at first generation anyway).
        // mid16GBMac and higher keep `.eager` — there's no benefit
        // to deferring on machines with headroom.
        let customPrewarmPolicy: NativeCustomPrewarmPolicy =
            NativeMemoryPolicyResolver.deviceClass() == .floor8GBMac
                ? .skipDedicatedCustomPrewarm
                : .eager
        let runtime = try NativeRuntimeFactory.make(
            registry: registry,
            paths: .rooted(at: appSupportDirectory),
            storeVersionSeed: Self.storeVersionSeed(),
            customPrewarmPolicy: customPrewarmPolicy
        )
        let runtimeContext = RuntimeContext(
            appSupportDirectory: appSupportDirectory,
            engine: runtime.engine
        )

        // Snapshot publishing — `loadState`, `clonePreparationState`,
        // `visibleErrorMessage` changes need to flow over XPC so the
        // client's UI bindings stay live. Chunk delivery is handled by
        // the AsyncStream below; this sink suppresses unchanged snapshots
        // produced by chunk-only `latestEvent` updates.
        runtime.engine.objectWillChange
            .sink { [weak self, weak runtimeContext] _ in
                Task { @MainActor [weak self, weak runtimeContext] in
                    guard let self, let runtimeContext else { return }
                    let snapshot = Self.snapshot(for: runtimeContext.engine)
                    guard runtimeContext.lastPublishedSnapshot != snapshot else { return }
                    runtimeContext.lastPublishedSnapshot = snapshot
                    self.publish(.snapshot(snapshot))
                }
            }
            .store(in: &runtimeContext.cancellables)

        // Cancel a prior context's generation-scoped forwarder before replacing
        // the runtime. A new one is created only when `.generate` is accepted.
        self.runtimeContext?.eventForwardingTask?.cancel()

        self.runtimeContext = runtimeContext
        return runtimeContext
    }

    @MainActor
    private func startEventForwarding(
        generationID: UUID,
        runtimeContext: RuntimeContext
    ) -> Task<Void, Never> {
        let appSupportDirectory = runtimeContext.appSupportDirectory
        let eventStream = runtimeContext.engine.events(for: generationID)
        return Task.detached(priority: .utility) { [weak self, weak runtimeContext, appSupportDirectory, eventStream] in
            var expectedChunkSequence: UInt64 = 0
            var transport = EngineServiceTransportAccumulator()

            for await event in eventStream {
                guard let self, let runtimeContext else { return }
                if case .chunk(let chunk) = event,
                   let sequence = chunk.chunkSequence {
                    if sequence > expectedChunkSequence + 1 {
                        let expected = expectedChunkSequence + 1
                        Task.detached(priority: .background) {
                            Self.recordChunkSequenceGap(
                                expected: expected,
                                received: sequence,
                                appSupportDirectory: appSupportDirectory
                            )
                        }
                    }
                    expectedChunkSequence = max(expectedChunkSequence, sequence)
                }

                let requestAcceptedUptime: Double?
                if case .chunk(let chunk) = event,
                   chunk.generationID == generationID,
                   transport.snapshot.generationID == nil {
                    requestAcceptedUptime = runtimeContext.requestTimings.consumeAcceptance(
                        for: generationID
                    )
                } else {
                    requestAcceptedUptime = nil
                }
                if let record = transport.observe(
                    event: event,
                    requestAcceptedUptime: requestAcceptedUptime
                ) {
                    Task.detached(priority: .background) {
                        await GenerationTelemetryJSONLSink.shared.write(
                            record: record,
                            appSupportDirectory: appSupportDirectory,
                            subdirectory: "engine-service"
                        )
                    }
                }
                self.publish(.generationChunk(event))
                let stripped = event.withoutPreviewAudioPayload()
                await MainActor.run {
                    runtimeContext.lastPublishedEvent = stripped
                }
            }
        }
    }

    @MainActor
    private func requireRuntimeContext() throws -> RuntimeContext {
        guard let runtimeContext else {
            throw MLXTTSEngineError.notInitialized
        }
        return runtimeContext
    }

    private func activateSession(id: UUID, eventSink: QwenVoiceEngineClientEventXPCProtocol) {
        let previousSessionID = sessionLock.withLock {
            let previous = activeSession?.id
            activeSession = ActiveSession(id: id, eventSink: eventSink)
            return previous
        }

        if let previousSessionID, previousSessionID != id {
            Self.logger.notice(
                "Replacing active engine-service session \(previousSessionID.uuidString, privacy: .public) with \(id.uuidString, privacy: .public)."
            )
        } else {
            Self.logger.debug("Activated engine-service session \(id.uuidString, privacy: .public).")
        }
    }

    private func handleSessionEnded(sessionID: UUID, message: String) {
        guard clearActiveSessionIfNeeded(sessionID: sessionID) else {
            Self.logger.debug(
                "Ignoring disconnect from stale engine-service session \(sessionID.uuidString, privacy: .public)."
            )
            return
        }

        Self.logger.error("\(message, privacy: .public)")
        Task { @MainActor [weak self] in
            guard let self else { return }

            // If another session has already activated (even if it reuses the
            // same RuntimeContext/engine), this cleanup belongs to a stale
            // session and must not mutate engine state. Capture this under
            // sessionLock before touching runtimeContext.
            let anotherSessionActive = self.sessionLock.withLock { self.activeSession != nil }
            guard !anotherSessionActive else {
                Self.logger.debug(
                    "Skipping stale session cleanup because a new session is already active."
                )
                return
            }

            // Capture the runtime context that was active when this session
            // ended. Re-reading `self.runtimeContext` later in this Task is
            // unsafe: another session may have already replaced it (the host
            // is `EngineServiceHost.shared`, a process-wide singleton across
            // every test in the test bundle). Without this capture-and-
            // identity-check, a stale cleanup Task from session A nils out
            // the active runtime context of session B mid-`initialize`,
            // causing the next call from B's client to throw
            // `MLXTTSEngineError.notInitialized`. See the May 2026 fix
            // commit for the full timeline (Tier 4.4).
            let contextAtSessionEnd = self.runtimeContext
            try? await contextAtSessionEnd?.engine.cancelActiveGeneration(reason: .shutdown)
            await self.activeGenerationCoordinator.cancelCurrent()
            guard self.isStillTerminatingSession(sessionID) else { return }
            await contextAtSessionEnd?.engine.cancelClonePreparationIfNeeded()
            contextAtSessionEnd?.engine.clearGenerationActivity()
            guard self.isStillTerminatingSession(sessionID) else { return }
            try? await contextAtSessionEnd?.engine.unloadModel()
            guard self.isStillTerminatingSession(sessionID) else { return }
            // Only clear the host's runtime-context slot if the context that
            // ended is STILL the active one — otherwise a newer session has
            // already taken it over and we must not clobber its state.
            if self.runtimeContext === contextAtSessionEnd {
                self.runtimeContext = nil
            }
        }
    }

    /// True while this ended session's cleanup may still safely run: either no session has
    /// reactivated (`activeSession == nil`, the normal case after `clearActiveSessionIfNeeded`),
    /// or the still-active session is this same one. A DIFFERENT active session means a newer
    /// session took over mid-cleanup, so this stale cleanup must abort and not clobber its state.
    private func isStillTerminatingSession(_ sessionID: UUID) -> Bool {
        self.sessionLock.withLock {
            self.activeSession == nil || self.activeSession?.id == sessionID
        }
    }

    @discardableResult
    private func clearActiveSessionIfNeeded(sessionID: UUID) -> Bool {
        sessionLock.withLock {
            guard activeSession?.id == sessionID else { return false }
            activeSession = nil
            return true
        }
    }

    private func publish(_ event: EngineEventEnvelope, toSessionID: UUID? = nil) {
        let eventSink: QwenVoiceEngineClientEventXPCProtocol? = sessionLock.withLock {
            if let toSessionID {
                return activeSession?.id == toSessionID ? activeSession?.eventSink : nil
            } else {
                return activeSession?.eventSink
            }
        }

        guard let eventSink else { return }
        do {
            let payload = try EngineServiceCodec.encode(event)
            eventSink.handleEvent(payload)
        } catch {
            let droppedCount = sessionLock.withLock {
                droppedEncodeEventCount += 1
                return droppedEncodeEventCount
            }
            let diagnosticsDirectory = runtimeContext?.appSupportDirectory

            Self.logger.error(
                "Failed to encode engine-service event payload (droppedCount=\(droppedCount, privacy: .public)): \(error.localizedDescription, privacy: .public)"
            )
            Self.recordDroppedEncodeEvent(
                error: error,
                droppedCount: droppedCount,
                appSupportDirectory: diagnosticsDirectory
            )
        }
    }

    private static func recordChunkSequenceGap(
        expected: UInt64,
        received: UInt64,
        appSupportDirectory: URL
    ) {
        let diagnosticsDirectory = appSupportDirectory
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent("engine-service", isDirectory: true)
        let url = diagnosticsDirectory.appendingPathComponent("native-events.jsonl", isDirectory: false)
        let record: [String: String] = [
            "event": "engine_service_chunk_gap",
            "recordedAt": ISO8601DateFormatter().string(from: Date()),
            "expectedSequence": String(expected),
            "receivedSequence": String(received),
            "gap": String(received > expected ? received - expected : 0),
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: record),
              var line = String(data: data, encoding: .utf8) else {
            return
        }
        line.append("\n")
        Task.detached(priority: .background) {
            await diagnosticEventRecorder.append(line: line, to: url)
        }
    }

    private static func recordDroppedEncodeEvent(
        error: Error,
        droppedCount: Int,
        appSupportDirectory: URL?
    ) {
        guard let appSupportDirectory else { return }
        let diagnosticsDirectory = appSupportDirectory
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent("engine-service", isDirectory: true)
        let url = diagnosticsDirectory.appendingPathComponent("native-events.jsonl", isDirectory: false)
        let record: [String: String] = [
            "event": "engine_service_encode_dropped",
            "recordedAt": ISO8601DateFormatter().string(from: Date()),
            "droppedCount": String(droppedCount),
            "message": error.localizedDescription,
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: record),
              var line = String(data: data, encoding: .utf8) else {
            return
        }
        line.append("\n")
        Task.detached(priority: .background) {
            await diagnosticEventRecorder.append(line: line, to: url)
        }
    }

    @MainActor
    private static func snapshot(for engine: MLXTTSEngine) -> TTSEngineSnapshot {
        TTSEngineSnapshot(
            isReady: engine.isReady,
            loadState: engine.loadState,
            clonePreparationState: engine.clonePreparationState,
            visibleErrorMessage: engine.visibleErrorMessage
        )
    }

    private static func locateManifestURL() throws -> URL {
        let bundles = [Bundle.main] + Bundle.allBundles + Bundle.allFrameworks
        for bundle in bundles {
            if let url = bundle.url(forResource: "qwenvoice_contract", withExtension: "json") {
                return url
            }
        }
        throw DocumentIOError.missingSource("qwenvoice_contract.json")
    }

    private static func storeVersionSeed(bundle: Bundle = .main) -> String {
        let bundleIdentifier = bundle.bundleIdentifier ?? "com.qwenvoice.app.engine-service"
        let marketingVersion = bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
        let buildVersion = bundle.object(forInfoDictionaryKey: kCFBundleVersionKey as String) as? String ?? "0"
        return "\(bundleIdentifier)|\(marketingVersion)|\(buildVersion)"
    }
}
