@preconcurrency import Combine
import QwenVoiceCore
import Foundation
import OSLog

enum EngineTransportError: LocalizedError, Equatable, Sendable {
    case interrupted
    case invalidated
    case timedOut(commandName: String)
    case staleOrMismatchedReply(id: UUID)
    case invalidReply

    var errorDescription: String? {
        switch self {
        case .interrupted:
            return "The engine service connection was interrupted."
        case .invalidated:
            return "The engine service connection was invalidated."
        case .timedOut(let commandName):
            return "The engine service request timed out while running \(commandName)."
        case .staleOrMismatchedReply(let id):
            return "The engine service returned a stale or mismatched reply for request \(id.uuidString)."
        case .invalidReply:
            return "The engine service returned an invalid reply."
        }
    }
}

struct XPCNativeEngineTransportHandlers: Sendable {
    let onEventData: @Sendable (Data) -> Void
    let onRemoteError: @Sendable (Error) -> Void
    let onInterrupted: @Sendable () -> Void
    let onInvalidated: @Sendable () -> Void
}

protocol XPCNativeEngineTransporting: AnyObject, Sendable {
    func resume()
    func invalidate()
    func perform(_ payload: Data, reply: @escaping @Sendable (Data) -> Void)
}

typealias XPCNativeEngineTransportFactory = @Sendable (XPCNativeEngineTransportHandlers) -> any XPCNativeEngineTransporting
typealias XPCNativeEngineTimeoutResolver = @Sendable (EngineCommand) -> Duration?

private final class PendingRequestBox: @unchecked Sendable {
    let commandName: String
    let resume: @Sendable (Result<EngineReply, Error>) -> Void
    var timeoutTask: Task<Void, Never>?

    init(
        commandName: String,
        resume: @escaping @Sendable (Result<EngineReply, Error>) -> Void
    ) {
        self.commandName = commandName
        self.resume = resume
    }
}

private final class XPCNativeEngineClientEventSink: NSObject, QwenVoiceEngineClientEventXPCProtocol {
    private let onEvent: @Sendable (Data) -> Void

    init(onEvent: @escaping @Sendable (Data) -> Void) {
        self.onEvent = onEvent
    }

    func handleEvent(_ payload: Data) {
        onEvent(payload)
    }
}

private final class XPCServiceTransport: NSObject, XPCNativeEngineTransporting, @unchecked Sendable {
    private let connection: NSXPCConnection
    private let eventSink: XPCNativeEngineClientEventSink
    private let handlers: XPCNativeEngineTransportHandlers

    init(handlers: XPCNativeEngineTransportHandlers) {
        self.handlers = handlers

        let sink = XPCNativeEngineClientEventSink(onEvent: handlers.onEventData)
        self.eventSink = sink
        let connection = NSXPCConnection(serviceName: QwenVoiceEngineServiceBundleIdentifier)
        connection.setCodeSigningRequirement(
            EngineServiceTrustPolicy.serviceRequirementForCurrentBundle()
        )
        connection.remoteObjectInterface = NSXPCInterface(with: QwenVoiceEngineServiceXPCProtocol.self)
        connection.exportedInterface = NSXPCInterface(with: QwenVoiceEngineClientEventXPCProtocol.self)
        connection.exportedObject = sink
        self.connection = connection

        super.init()

        connection.interruptionHandler = { [handlers] in
            handlers.onInterrupted()
        }
        connection.invalidationHandler = { [handlers] in
            handlers.onInvalidated()
        }
    }

    func resume() {
        connection.resume()
    }

    func invalidate() {
        connection.invalidate()
    }

    func perform(_ payload: Data, reply: @escaping @Sendable (Data) -> Void) {
        let rawProxy = connection.remoteObjectProxyWithErrorHandler { [handlers] error in
            handlers.onRemoteError(error)
        }
        guard let proxy = rawProxy as? QwenVoiceEngineServiceXPCProtocol else {
            let mismatch = NSError(
                domain: "com.qwenvoice.xpc",
                code: -1,
                userInfo: [
                    NSLocalizedDescriptionKey:
                        "Remote XPC proxy does not conform to QwenVoiceEngineServiceXPCProtocol",
                ]
            )
            handlers.onRemoteError(mismatch)
            reply(Data())
            return
        }
        proxy.perform(payload, withReply: reply)
    }
}

actor XPCNativeEngineCoordinator {
    private struct ActiveConnection {
        let id: UUID
        let transport: any XPCNativeEngineTransporting
    }

    private enum BestEffortDeduplicationIdentity: Hashable, Sendable {
        case ensureModelLoaded(modelID: String)
        case runtimePrewarm(GenerationSemantics.PrewarmIdentity)
        case interactivePrefetch(
            identity: GenerationSemantics.PrewarmIdentity,
            customPrewarmDepth: String?
        )

        var diagnosticKey: String {
            switch self {
            case .ensureModelLoaded(let modelID):
                "ensure-model-v1-\(modelID)"
            case .runtimePrewarm(let identity):
                "runtime-prewarm-\(identity.digest)"
            case .interactivePrefetch(let identity, let customPrewarmDepth):
                "interactive-prefetch-\(identity.digest)-\(customPrewarmDepth ?? "default")"
            }
        }
    }

    private static let logger = Logger(
        subsystem: "com.qwenvoice.app",
        category: "XPCNativeEngineClient"
    )
    private static let signposter = OSSignposter(
        subsystem: "com.qwenvoice.app",
        category: "xpc"
    )

    private let onSnapshot: @Sendable (TTSEngineSnapshot) -> Void
    private let onChunk: @Sendable (GenerationEvent) -> Void
    private let transportFactory: XPCNativeEngineTransportFactory
    private let timeoutResolver: XPCNativeEngineTimeoutResolver

    private var activeConnection: ActiveConnection?
    private var didInitializeCurrentConnection = false
    private var initializedAppSupportDirectory: URL?
    private var pendingRequests: [UUID: PendingRequestBox] = [:]
    private var inFlightBestEffortKeys: Set<BestEffortDeduplicationIdentity> = []
    private var pendingFireAndForgetTasks: [UUID: Task<Void, Never>] = [:]
    private let reconnectDelays: [Duration]
    private var reconnectAttempt = 0
    private var reconnectTask: Task<Void, Never>?
    /// Set while a `shutdownWhenIdle` retirement is in flight so the
    /// resulting connection drop is treated as expected — no error UI,
    /// no auto-reconnect; the next command lazily relaunches the service.
    private var expectedRetirement = false

    var pendingRequestCount: Int { pendingRequests.count }

    init(
        onSnapshot: @escaping @Sendable (TTSEngineSnapshot) -> Void,
        onChunk: @escaping @Sendable (GenerationEvent) -> Void,
        transportFactory: @escaping XPCNativeEngineTransportFactory = { handlers in
            XPCServiceTransport(handlers: handlers)
        },
        timeoutResolver: @escaping XPCNativeEngineTimeoutResolver = { command in
            command.transportTimeout
        },
        reconnectDelays: [Duration] = [.milliseconds(250), .seconds(1)]
    ) {
        self.onSnapshot = onSnapshot
        self.onChunk = onChunk
        self.transportFactory = transportFactory
        self.timeoutResolver = timeoutResolver
        self.reconnectDelays = reconnectDelays
    }

    func initialize(appSupportDirectory: URL) async throws {
        initializedAppSupportDirectory = appSupportDirectory
        _ = try await send(.initialize(
            appSupportDirectoryPath: appSupportDirectory.path,
            telemetryMode: TelemetryGate.appProcessIntendedMode.rawValue,
            forcedMemoryClass: NativeDeviceClassGate.appProcessForcedClassRawValue
        ))
    }

    func send(_ command: EngineCommand) async throws -> EngineReply {
        cancelReconnectTaskIfNeeded()
        return try await send(command, cancelsReconnectTask: false)
    }

    private func send(_ command: EngineCommand, cancelsReconnectTask: Bool) async throws -> EngineReply {
        if cancelsReconnectTask {
            cancelReconnectTaskIfNeeded()
        }
        let transport = ensureConnection()
        switch command {
        case .initialize(let path, _, _):
            initializedAppSupportDirectory = URL(fileURLWithPath: path)
            let reply = try await perform(transport: transport, command: command)
            applyReplySideEffects(reply)
            didInitializeCurrentConnection = true
            return reply
        default:
            if !didInitializeCurrentConnection, let initializedAppSupportDirectory {
                let initializationReply = try await perform(
                    transport: transport,
                    command: .initialize(
                        appSupportDirectoryPath: initializedAppSupportDirectory.path,
                        telemetryMode: TelemetryGate.appProcessIntendedMode.rawValue,
                        forcedMemoryClass: NativeDeviceClassGate.appProcessForcedClassRawValue
                    )
                )
                applyReplySideEffects(initializationReply)
                didInitializeCurrentConnection = true
            }
            let reply = try await perform(transport: transport, command: command)
            applyReplySideEffects(reply)
            return reply
        }
    }

    func fireAndForget(_ command: EngineCommand) {
        let deduplicationKey = bestEffortDeduplicationKey(for: command)
        if let deduplicationKey {
            guard inFlightBestEffortKeys.insert(deduplicationKey).inserted else {
                Self.logger.debug(
                    "Skipping duplicate best-effort command '\(command.transportName, privacy: .public)' with key \(deduplicationKey.diagnosticKey, privacy: .public)."
                )
                return
            }
        }

        let taskID = UUID()
        let task = Task { [weak self, command, deduplicationKey] in
            guard let self else { return }
            await self.performBestEffort(
                command,
                taskID: taskID,
                deduplicationKey: deduplicationKey
            )
        }
        pendingFireAndForgetTasks[taskID] = task
    }

    private func performBestEffort(
        _ command: EngineCommand,
        taskID: UUID,
        deduplicationKey: BestEffortDeduplicationIdentity?
    ) async {
        defer {
            if let deduplicationKey {
                inFlightBestEffortKeys.remove(deduplicationKey)
            }
            pendingFireAndForgetTasks.removeValue(forKey: taskID)
        }
        do {
            _ = try await send(command)
        } catch is CancellationError {
            // Transport was invalidated/replaced; the command was best-effort.
        } catch {
            Self.logger.error(
                "Best-effort command '\(command.transportName, privacy: .public)' failed: \(error.localizedDescription, privacy: .public)"
            )
        }
    }

    private func cancelAllFireAndForgetTasks() {
        let tasks = pendingFireAndForgetTasks.values
        pendingFireAndForgetTasks.removeAll()
        for task in tasks {
            task.cancel()
        }
    }

    func handleEventData(_ data: Data, from connectionID: UUID) {
        guard isCurrentConnection(connectionID) else {
            Self.logger.debug(
                "Ignoring engine event from stale connection \(connectionID.uuidString, privacy: .public)."
            )
            return
        }

        do {
            let event = try EngineServiceCodec.decode(EngineEventEnvelope.self, from: data)
            switch event {
            case .snapshot(let snapshot):
                onSnapshot(snapshot)
            case .generationChunk(let generationEvent):
                onChunk(generationEvent)
            }
        } catch {
            Self.logger.error("Unreadable engine event payload: \(error.localizedDescription, privacy: .public)")
            handleDisconnect(
                connectionID: connectionID,
                transportError: .invalidReply,
                message: "The engine service sent an unreadable event: \(error.localizedDescription)"
            )
        }
    }

    func handleRemoteError(_ error: Error, from connectionID: UUID) {
        handleDisconnect(
            connectionID: connectionID,
            transportError: .invalidated,
            message: error.localizedDescription
        )
    }

    func handleConnectionInterrupted(for connectionID: UUID) {
        handleDisconnect(
            connectionID: connectionID,
            transportError: .interrupted,
            message: EngineTransportError.interrupted.localizedDescription
        )
    }

    func handleConnectionInvalidated(for connectionID: UUID) {
        handleDisconnect(
            connectionID: connectionID,
            transportError: .invalidated,
            message: EngineTransportError.invalidated.localizedDescription
        )
    }

    private func ensureConnection() -> ActiveConnection {
        if let activeConnection {
            return activeConnection
        }

        let connectionID = UUID()
        let handlers = XPCNativeEngineTransportHandlers(
            onEventData: { [weak self] payload in
                Task {
                    await self?.handleEventData(payload, from: connectionID)
                }
            },
            onRemoteError: { [weak self] error in
                Task {
                    await self?.handleRemoteError(error, from: connectionID)
                }
            },
            onInterrupted: { [weak self] in
                Task {
                    await self?.handleConnectionInterrupted(for: connectionID)
                }
            },
            onInvalidated: { [weak self] in
                Task {
                    await self?.handleConnectionInvalidated(for: connectionID)
                }
            }
        )

        let transport = transportFactory(handlers)
        transport.resume()
        let connection = ActiveConnection(id: connectionID, transport: transport)
        activeConnection = connection
        didInitializeCurrentConnection = false
        return connection
    }

    private func perform(
        transport: ActiveConnection,
        command: EngineCommand
    ) async throws -> EngineReply {
        let signpostState = Self.signposter.beginInterval("XPC Engine Command")
        defer {
            Self.signposter.endInterval("XPC Engine Command", signpostState)
        }
        let requestEnvelope = EngineRequestEnvelope(id: UUID(), command: command)
        let payload = try EngineServiceCodec.encode(requestEnvelope)

        Self.signposter.emitEvent("XPC Engine Command Sent")
        Self.logger.debug("Sending engine command '\(command.transportName, privacy: .public)' with id \(requestEnvelope.id.uuidString, privacy: .public)")

        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                guard !Task.isCancelled else {
                    continuation.resume(throwing: CancellationError())
                    return
                }

                let pendingRequest = PendingRequestBox(
                    commandName: command.transportName,
                    resume: { result in
                        continuation.resume(with: result)
                    }
                )
                if let timeout = timeoutResolver(command) {
                    pendingRequest.timeoutTask = Task { [requestID = requestEnvelope.id] in
                        do {
                            try await Task.sleep(for: timeout)
                        } catch {
                            return
                        }
                        await self.handleTimeout(for: requestID)
                    }
                }
                pendingRequests[requestEnvelope.id] = pendingRequest

                transport.transport.perform(payload) { [weak self] replyData in
                    Task {
                        Self.signposter.emitEvent("XPC Engine Reply Received")
                        await self?.handleReplyData(replyData, from: transport.id)
                    }
                }
            }
        } onCancel: {
            Task { await self.cancelPendingRequest(id: requestEnvelope.id, command: command) }
        }
    }

    private func cancelPendingRequest(id requestID: UUID, command: EngineCommand) {
        guard let pendingRequest = pendingRequests.removeValue(forKey: requestID) else { return }
        pendingRequest.timeoutTask?.cancel()
        Self.logger.debug(
            "Cancelled engine-service command '\(pendingRequest.commandName, privacy: .public)' with id \(requestID.uuidString, privacy: .public)"
        )
        pendingRequest.resume(.failure(CancellationError()))
        if let cleanupCommand = cancellationCleanupCommand(for: command) {
            fireAndForget(cleanupCommand)
        }
    }

    private func cancellationCleanupCommand(for command: EngineCommand) -> EngineCommand? {
        switch command {
        case .generate:
            return .cancelActiveGeneration
        case .ensureCloneReferencePrimed:
            return .cancelClonePreparationIfNeeded
        default:
            return nil
        }
    }

    private func handleReplyData(_ data: Data, from connectionID: UUID) {
        guard isCurrentConnection(connectionID) else {
            Self.logger.debug(
                "Ignoring engine reply from stale connection \(connectionID.uuidString, privacy: .public)."
            )
            return
        }

        let envelope: EngineReplyEnvelope
        do {
            envelope = try EngineServiceCodec.decode(EngineReplyEnvelope.self, from: data)
        } catch {
            Self.logger.error("Unreadable engine reply payload: \(error.localizedDescription, privacy: .public)")
            handleDisconnect(
                connectionID: connectionID,
                transportError: .invalidReply,
                message: EngineTransportError.invalidReply.localizedDescription
            )
            return
        }

        guard let pendingRequest = pendingRequests.removeValue(forKey: envelope.id) else {
            let transportError = EngineTransportError.staleOrMismatchedReply(id: envelope.id)
            Self.logger.warning("\(transportError.localizedDescription, privacy: .public)")
            return
        }

        pendingRequest.timeoutTask?.cancel()

        if case .failure(let error) = envelope.reply {
            pendingRequest.resume(.failure(error))
        } else {
            pendingRequest.resume(.success(envelope.reply))
        }
    }

    private func handleTimeout(for requestID: UUID) {
        guard let pendingRequest = pendingRequests.removeValue(forKey: requestID) else { return }
        pendingRequest.timeoutTask?.cancel()
        let error = EngineTransportError.timedOut(commandName: pendingRequest.commandName)
        Self.logger.error("\(error.localizedDescription, privacy: .public)")
        pendingRequest.resume(.failure(error))
        if pendingRequest.commandName == "generate" {
            fireAndForget(.cancelActiveGeneration)
        }
    }

    private func handleDisconnect(
        connectionID: UUID,
        transportError: EngineTransportError,
        message: String?,
        allowsRecovery: Bool = true
    ) {
        guard let connectionToInvalidate = disconnectCurrentConnectionIfNeeded(connectionID: connectionID) else {
            Self.logger.debug(
                "Ignoring disconnect cleanup from stale connection \(connectionID.uuidString, privacy: .public)."
            )
            return
        }
        connectionToInvalidate.invalidate()
        didInitializeCurrentConnection = false
        inFlightBestEffortKeys.removeAll()
        cancelAllFireAndForgetTasks()

        let pendingRequestBoxes = pendingRequests.values
        pendingRequests.removeAll()
        let pendingCommandNames = pendingRequestBoxes.map(\.commandName).joined(separator: ",")
        let visibleMessage = message ?? transportError.localizedDescription
        let canRecover = allowsRecovery
            && isRecoverableDisconnect(transportError)
            && initializedAppSupportDirectory != nil
            && !reconnectDelays.isEmpty

        Self.logger.error(
            "Disconnect cleanup: \(visibleMessage, privacy: .public); pending=\(pendingRequestBoxes.count, privacy: .public); commands=\(pendingCommandNames, privacy: .public); recoveryScheduled=\(canRecover, privacy: .public)."
        )

        for pendingRequest in pendingRequestBoxes {
            pendingRequest.timeoutTask?.cancel()
            pendingRequest.resume(.failure(transportError))
        }

        if expectedRetirement {
            // Retirement-to-reclaim: the service exit was requested by us.
            // Publish a clean idle snapshot (honest-by-behavior: any next
            // command lazily reconnects + auto-initializes) and skip both
            // the "Reconnecting…" state and the reconnect attempt — a
            // reconnect would relaunch the service and defeat the reclaim.
            expectedRetirement = false
            Self.logger.info("Engine service retired (expected exit); lazy relaunch on next use.")
            publishRetiredSnapshot()
        } else if canRecover {
            publishRecoveringSnapshot()
            scheduleReconnect()
        } else {
            publishUnavailableSnapshot(message: visibleMessage)
        }
    }

    /// Retirement-to-reclaim (constrained Macs): ask the idle service to
    /// exit so the OS reclaims everything model unload can't (MLX heap
    /// fragmentation, Metal shader caches). Returns false when the service
    /// refused (busy) or requests are in flight; true when retired (or
    /// there was no live connection to retire).
    func retireServiceIfIdle() async -> Bool {
        guard pendingRequests.isEmpty, reconnectTask == nil else { return false }
        guard activeConnection != nil else { return true }
        expectedRetirement = true
        do {
            _ = try await send(.shutdownWhenIdle)
            return true
        } catch is EngineTransportError {
            // The 250 ms exit grace can race the reply — the drop is the
            // retirement succeeding; handleDisconnect consumed the flag.
            return true
        } catch {
            // Remote refusal (a generation grabbed the engine between our
            // check and the service's) or another remote error.
            expectedRetirement = false
            return false
        }
    }

    private func isCurrentConnection(_ connectionID: UUID) -> Bool {
        activeConnection?.id == connectionID
    }

    private func disconnectCurrentConnectionIfNeeded(connectionID: UUID) -> (any XPCNativeEngineTransporting)? {
        guard activeConnection?.id == connectionID else { return nil }
        let transport = activeConnection?.transport
        activeConnection = nil
        return transport
    }

    private func applyReplySideEffects(_ reply: EngineReply) {
        guard case .snapshot(let snapshot) = reply else { return }
        onSnapshot(snapshot)
    }

    private func isRecoverableDisconnect(_ error: EngineTransportError) -> Bool {
        switch error {
        case .interrupted, .invalidated:
            true
        case .timedOut, .staleOrMismatchedReply, .invalidReply:
            false
        }
    }

    private func publishRetiredSnapshot() {
        onSnapshot(
            TTSEngineSnapshot(
                isReady: true,
                loadState: .idle,
                clonePreparationState: .idle,
                visibleErrorMessage: nil
            )
        )
    }

    private func publishRecoveringSnapshot() {
        onSnapshot(
            TTSEngineSnapshot(
                isReady: false,
                loadState: .starting,
                clonePreparationState: .idle,
                visibleErrorMessage: "Reconnecting engine…"
            )
        )
    }

    private func publishUnavailableSnapshot(message: String) {
        onSnapshot(
            TTSEngineSnapshot(
                isReady: false,
                loadState: .failed(message: message),
                clonePreparationState: .idle,
                visibleErrorMessage: message
            )
        )
    }

    private func cancelReconnectTaskIfNeeded() {
        reconnectTask?.cancel()
        reconnectTask = nil
        reconnectAttempt = 0
    }

    private func scheduleReconnect() {
        reconnectTask?.cancel()
        reconnectAttempt += 1

        let attempt = reconnectAttempt
        guard attempt <= reconnectDelays.count,
              let initializedAppSupportDirectory else {
            reconnectTask = nil
            publishUnavailableSnapshot(
                message: "Engine unavailable. Try generating again to reconnect the engine."
            )
            return
        }

        let delay = reconnectDelays[attempt - 1]
        reconnectTask = Task { [attempt, initializedAppSupportDirectory] in
            do {
                try await Task.sleep(for: delay)
            } catch {
                return
            }
            await self.performReconnectAttempt(
                attempt: attempt,
                appSupportDirectory: initializedAppSupportDirectory
            )
        }
    }

    private func performReconnectAttempt(attempt: Int, appSupportDirectory: URL) async {
        guard reconnectAttempt == attempt else { return }

        do {
            _ = try await send(
                .initialize(
                    appSupportDirectoryPath: appSupportDirectory.path,
                    telemetryMode: TelemetryGate.appProcessIntendedMode.rawValue,
                    forcedMemoryClass: NativeDeviceClassGate.appProcessForcedClassRawValue
                ),
                cancelsReconnectTask: false
            )
            _ = try await send(.ping, cancelsReconnectTask: false)
            reconnectTask = nil
            reconnectAttempt = 0
            Self.logger.notice(
                "Engine service reconnect attempt \(attempt, privacy: .public) completed."
            )
        } catch {
            guard reconnectAttempt == attempt else { return }
            Self.logger.error(
                "Engine service reconnect attempt \(attempt, privacy: .public) failed: \(error.localizedDescription, privacy: .public)."
            )
            scheduleReconnect()
        }
    }

    private func bestEffortDeduplicationKey(
        for command: EngineCommand
    ) -> BestEffortDeduplicationIdentity? {
        switch command {
        case .ensureModelLoadedIfNeeded(let id):
            .ensureModelLoaded(modelID: id)
        case .prewarmModelIfNeeded(let request):
            // Use the runtime-aligned key. The runtime intentionally treats
            // `.custom` prewarm as model-level (see
            // GenerationSemantics.swift `prewarmIdentityKey(modelID:mode:...)`
            // — keeps the hot model state stable across UI draft churn). The
            // request-form `prewarmIdentityKey(for:)` would dedupe at
            // speaker+instruction level, leaking one XPC round-trip per
            // draft edit that the runtime will just no-op on.
            .runtimePrewarm(Self.runtimeAlignedPrewarmIdentity(for: request))
        case .prefetchInteractiveReadinessIfNeeded(let request, let customPrewarmDepth):
            .interactivePrefetch(
                identity: GenerationSemantics.prewarmIdentity(for: request),
                customPrewarmDepth: customPrewarmDepth
            )
        default:
            nil
        }
    }

    /// Mirrors `NativeEngineRuntime.prewarmIdentityKey(for:)` so the client
    /// dedupes prewarm commands using the same key the runtime uses to
    /// decide whether to do the work. Without this alignment the client
    /// would dispatch one prewarm XPC call per speaker/instruction change
    /// for `.custom` requests; the runtime would treat the model as
    /// already-prewarmed and no-op on each one.
    private static func runtimeAlignedPrewarmIdentity(
        for request: GenerationRequest
    ) -> GenerationSemantics.PrewarmIdentity {
        switch request.payload {
        case .custom:
            return GenerationSemantics.prewarmIdentity(
                modelID: request.modelID,
                mode: request.mode
            )
        case .design:
            return GenerationSemantics.prewarmIdentity(
                modelID: request.modelID,
                mode: request.mode
            )
        case .clone(let reference):
            return GenerationSemantics.prewarmIdentity(
                modelID: request.modelID,
                mode: request.mode,
                refAudio: reference.audioPath,
                refText: reference.transcript
            )
        }
    }
}

public final class XPCNativeEngineClient: MacTTSEngine, @unchecked Sendable {
    private let snapshotSubject: CurrentValueSubject<TTSEngineSnapshot, Never>
    private let coordinator: XPCNativeEngineCoordinator

    public convenience init() {
        self.init(onChunk: { event in
            GenerationChunkBroker.publish(event)
        })
    }

    convenience init(onChunk: @escaping @Sendable (GenerationEvent) -> Void) {
        self.init(
            transportFactory: { handlers in
                XPCServiceTransport(handlers: handlers)
            },
            timeoutResolver: { command in
                command.transportTimeout
            },
            onChunk: onChunk
        )
    }

    init(
        transportFactory: @escaping XPCNativeEngineTransportFactory,
        timeoutResolver: @escaping XPCNativeEngineTimeoutResolver = { command in
            command.transportTimeout
        },
        onChunk: @escaping @Sendable (GenerationEvent) -> Void = { event in
            GenerationChunkBroker.publish(event)
        },
        reconnectDelays: [Duration] = [.milliseconds(250), .seconds(1)]
    ) {
        let initialSnapshot = TTSEngineSnapshot(
            isReady: false,
            loadState: .idle,
            clonePreparationState: .idle,
            visibleErrorMessage: nil
        )
        self.snapshotSubject = CurrentValueSubject(initialSnapshot)
        self.coordinator = XPCNativeEngineCoordinator(
            onSnapshot: { [snapshotSubject] snapshot in
                snapshotSubject.send(snapshot)
            },
            onChunk: onChunk,
            transportFactory: transportFactory,
            timeoutResolver: timeoutResolver,
            reconnectDelays: reconnectDelays
        )
    }

    public var snapshot: TTSEngineSnapshot {
        snapshotSubject.value
    }

    public var snapshotPublisher: AnyPublisher<TTSEngineSnapshot, Never> {
        snapshotSubject.eraseToAnyPublisher()
    }

    var pendingRequestCount: Int {
        get async { await coordinator.pendingRequestCount }
    }

    public func initialize(appSupportDirectory: URL) async throws {
        try await coordinator.initialize(appSupportDirectory: appSupportDirectory)
    }

    public func ping() async throws -> Bool {
        let reply = try await coordinator.send(.ping)
        switch reply {
        case .bool(let value):
            return value
        case .capabilities:
            return true
        default:
            throw EngineTransportError.invalidReply
        }
    }

    public func loadModel(id: String) async throws {
        _ = try await coordinator.send(.loadModel(id: id))
    }

    public func unloadModel() async throws {
        _ = try await coordinator.send(.unloadModel)
    }

    public func retireServiceIfIdle() async -> Bool {
        await coordinator.retireServiceIfIdle()
    }

    public func ensureModelLoadedIfNeeded(id: String) async {
        await coordinator.fireAndForget(.ensureModelLoadedIfNeeded(id: id))
    }

    public func prewarmModelIfNeeded(for request: GenerationRequest) async {
        await coordinator.fireAndForget(.prewarmModelIfNeeded(request: request))
    }

    public func prefetchInteractiveReadinessIfNeeded(
        for request: GenerationRequest
    ) async -> InteractivePrefetchDiagnostics? {
        await prefetchInteractiveReadinessIfNeeded(for: request, customPrewarmDepth: nil)
    }

    public func prefetchInteractiveReadinessIfNeeded(
        for request: GenerationRequest,
        customPrewarmDepth: String?
    ) async -> InteractivePrefetchDiagnostics? {
        do {
            let reply = try await coordinator.send(
                .prefetchInteractiveReadinessIfNeeded(
                    request: request,
                    customPrewarmDepth: customPrewarmDepth
                )
            )
            guard case .interactivePrefetchDiagnostics(let diagnostics) = reply else {
                throw EngineTransportError.invalidReply
            }
            return diagnostics
        } catch {
            return nil
        }
    }

    public func ensureCloneReferencePrimed(modelID: String, reference: CloneReference) async throws {
        _ = try await coordinator.send(.ensureCloneReferencePrimed(modelID: modelID, reference: reference))
    }

    public func cancelClonePreparationIfNeeded() async {
        await coordinator.fireAndForget(.cancelClonePreparationIfNeeded)
    }

    public func generate(_ request: GenerationRequest) async throws -> GenerationResult {
        do {
            let reply = try await coordinator.send(.generate(request: request))
            guard case .generationResult(let result) = reply else {
                throw EngineTransportError.invalidReply
            }
            return result
        } catch {
            throw Self.remappedTransportError(error)
        }
    }

    public func cancelActiveGeneration() async throws {
        _ = try await coordinator.send(.cancelActiveGeneration)
    }

    public func listPreparedVoices() async throws -> [PreparedVoice] {
        let reply = try await coordinator.send(.listPreparedVoices)
        guard case .preparedVoices(let voices) = reply else {
            throw EngineTransportError.invalidReply
        }
        return voices
    }

    public func preparePreparedVoiceCandidate(
        name: String,
        audioPath: String,
        transcript: String?,
        replacingVoiceID: String?
    ) async throws -> PreparedVoiceCandidate {
        let reply = try await coordinator.send(
            .preparePreparedVoiceCandidate(
                name: name,
                audioPath: audioPath,
                transcript: transcript,
                replacingVoiceID: replacingVoiceID
            )
        )
        guard case .preparedVoiceCandidate(let candidate) = reply else {
            throw EngineTransportError.invalidReply
        }
        return candidate
    }

    public func commitPreparedVoiceCandidate(id: UUID) async throws -> PreparedVoice {
        let reply = try await coordinator.send(.commitPreparedVoiceCandidate(id: id))
        guard case .preparedVoice(let voice) = reply else {
            throw EngineTransportError.invalidReply
        }
        return voice
    }

    public func discardPreparedVoiceCandidate(id: UUID) async throws {
        _ = try await coordinator.send(.discardPreparedVoiceCandidate(id: id))
    }

    public func enrollPreparedVoice(name: String, audioPath: String, transcript: String?) async throws -> PreparedVoice {
        let reply = try await coordinator.send(
            .enrollPreparedVoice(name: name, audioPath: audioPath, transcript: transcript)
        )
        guard case .preparedVoice(let voice) = reply else {
            throw EngineTransportError.invalidReply
        }
        return voice
    }

    public func deletePreparedVoice(id: String) async throws {
        _ = try await coordinator.send(.deletePreparedVoice(id: id))
    }

    public func clearGenerationActivity() {
        let clearedSnapshot = TTSEngineSnapshot(
            isReady: snapshot.isReady,
            loadState: snapshot.loadState.currentModelID.map { .loaded(modelID: $0) } ?? .idle,
            clonePreparationState: snapshot.clonePreparationState,
            visibleErrorMessage: snapshot.visibleErrorMessage
        )
        snapshotSubject.send(clearedSnapshot)
        Task {
            await coordinator.fireAndForget(.clearGenerationActivity)
        }
    }

    public func clearVisibleError() {
        let clearedSnapshot = TTSEngineSnapshot(
            isReady: snapshot.isReady,
            loadState: snapshot.loadState,
            clonePreparationState: snapshot.clonePreparationState,
            visibleErrorMessage: nil
        )
        snapshotSubject.send(clearedSnapshot)
        Task {
            await coordinator.fireAndForget(.clearVisibleError)
        }
    }

    private static func remappedTransportError(_ error: Error) -> Error {
        guard let remoteError = error as? RemoteErrorPayload,
              remoteError.code == .cancelled else {
            return error
        }
        return CancellationError()
    }
}

private extension EngineCommand {
    var transportName: String {
        switch self {
        case .initialize:
            "initialize"
        case .ping:
            "ping"
        case .loadModel:
            "loadModel"
        case .unloadModel:
            "unloadModel"
        case .ensureModelLoadedIfNeeded:
            "ensureModelLoadedIfNeeded"
        case .prewarmModelIfNeeded:
            "prewarmModelIfNeeded"
        case .prefetchInteractiveReadinessIfNeeded:
            "prefetchInteractiveReadinessIfNeeded"
        case .ensureCloneReferencePrimed:
            "ensureCloneReferencePrimed"
        case .cancelClonePreparationIfNeeded:
            "cancelClonePreparationIfNeeded"
        case .generate:
            "generate"
        case .cancelActiveGeneration:
            "cancelActiveGeneration"
        case .listPreparedVoices:
            "listPreparedVoices"
        case .preparePreparedVoiceCandidate:
            "preparePreparedVoiceCandidate"
        case .commitPreparedVoiceCandidate:
            "commitPreparedVoiceCandidate"
        case .discardPreparedVoiceCandidate:
            "discardPreparedVoiceCandidate"
        case .enrollPreparedVoice:
            "enrollPreparedVoice"
        case .deletePreparedVoice:
            "deletePreparedVoice"
        case .clearGenerationActivity:
            "clearGenerationActivity"
        case .clearVisibleError:
            "clearVisibleError"
        case .shutdownWhenIdle:
            "shutdownWhenIdle"
        }
    }

    var transportTimeout: Duration? {
        switch self {
        case .generate:
            .seconds(600)
        case .initialize, .loadModel, .unloadModel, .ensureModelLoadedIfNeeded,
             .prewarmModelIfNeeded, .prefetchInteractiveReadinessIfNeeded, .ensureCloneReferencePrimed:
            .seconds(180)
        case .ping, .cancelClonePreparationIfNeeded, .cancelActiveGeneration,
             .listPreparedVoices, .preparePreparedVoiceCandidate,
             .commitPreparedVoiceCandidate, .discardPreparedVoiceCandidate,
             .enrollPreparedVoice, .deletePreparedVoice,
             .clearGenerationActivity, .clearVisibleError, .shutdownWhenIdle:
            .seconds(10)
        }
    }
}
