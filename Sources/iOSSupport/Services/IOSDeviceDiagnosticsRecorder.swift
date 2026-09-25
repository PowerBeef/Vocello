import Foundation
import QwenVoiceCore
#if canImport(UIKit)
import UIKit
#endif

@MainActor
final class IOSDeviceDiagnosticsRecorder {
    private struct Target {
        let name: String
        let directory: URL
        let manifestURL: URL
        let memoryContextsURL: URL
        let nativeEventsURL: URL
    }

    private let runID: String
    private let targets: [Target]
    private let encoder: JSONEncoder
    private let dateFormatter = ISO8601DateFormatter()
    private var preparedTargets: Set<String> = []

    private init(runID: String, diagnosticsDirectories: [(name: String, url: URL)]) {
        self.runID = runID
        self.targets = diagnosticsDirectories.map { entry in
            Target(
                name: entry.name,
                directory: entry.url,
                manifestURL: entry.url.appendingPathComponent("manifest.json", isDirectory: false),
                memoryContextsURL: entry.url.appendingPathComponent("memory-contexts.jsonl", isDirectory: false),
                nativeEventsURL: entry.url.appendingPathComponent("native-events.jsonl", isDirectory: false)
            )
        }
        self.encoder = JSONEncoder()
        self.encoder.outputFormatting = [.sortedKeys]
    }

    /// Host identity for the manifest. UIKit's `UIDevice` on iOS; on macOS
    /// (where the same recorder runs for the in-process engine) Foundation's
    /// process information.
    private static var hostDescriptor: (model: String, systemName: String, systemVersion: String) {
        #if canImport(UIKit)
        return (UIDevice.current.model, UIDevice.current.systemName, UIDevice.current.systemVersion)
        #else
        let version = ProcessInfo.processInfo.operatingSystemVersion
        return ("Mac", "macOS", "\(version.majorVersion).\(version.minorVersion).\(version.patchVersion)")
        #endif
    }

    static func makeIfEnabled(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        appSupportDirectory: URL = AppPaths.appSupportDir,
        cachesDirectory: URL? = FileManager.default.urls(
            for: .cachesDirectory,
            in: .userDomainMask
        ).first
    ) -> IOSDeviceDiagnosticsRecorder? {
        guard NativeTelemetryMode.current(environment: environment) != .off else {
            return nil
        }
        guard let runID = environment["QVOICE_IOS_DEVICE_RUN_ID"]?
            .trimmingCharacters(in: .whitespacesAndNewlines),
              !runID.isEmpty else {
            return nil
        }

        let safeRunID = runID.map { character -> Character in
            if character.isLetter || character.isNumber || character == "-" || character == "_" {
                return character
            }
            return "_"
        }
        .reduce(into: "") { $0.append($1) }

        let directory = appSupportDirectory
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent(safeRunID, isDirectory: true)
        var directories = [(name: "app-group", url: directory)]
        if let cachesDirectory {
            let mirrorDirectory = cachesDirectory
                .appendingPathComponent("Vocello", isDirectory: true)
                .appendingPathComponent("diagnostics", isDirectory: true)
                .appendingPathComponent(safeRunID, isDirectory: true)
            directories.append((name: "app-container-cache", url: mirrorDirectory))
        }
        return IOSDeviceDiagnosticsRecorder(runID: safeRunID, diagnosticsDirectories: directories)
    }

    func recordMemoryContext(
        _ context: IOSMemoryContext,
        event: String,
        previousBand: IOSMemoryPressureBand? = nil
    ) {
        append(
            MemoryContextDiagnosticRecord(
                event: event,
                recordedAt: dateFormatter.string(from: Date()),
                processUptimeSeconds: ProcessInfo.processInfo.systemUptime,
                runID: runID,
                reason: context.reason,
                source: context.source,
                pressureBand: context.pressureBand,
                aggregatePressureBand: context.aggregatePressureBand,
                previousPressureBand: previousBand,
                worstProcessRole: context.worstProcessRole,
                trimLevel: nil,
                message: nil,
                context: context
            )
        )
    }

    /// `message` is code-owned copy or a failure's `DiagnosticPrivacy` summary, never
    /// error text; it is redacted again before it is written (AUD-08).
    func recordAction(
        event: String,
        reason: String,
        context: IOSMemoryContext?,
        trimLevel: NativeMemoryTrimLevel? = nil,
        message: String? = nil
    ) {
        let recordedMessage = message.map { DiagnosticPrivacy.redactedText($0) }
        append(
            MemoryContextDiagnosticRecord(
                event: event,
                recordedAt: dateFormatter.string(from: Date()),
                processUptimeSeconds: ProcessInfo.processInfo.systemUptime,
                runID: runID,
                reason: reason,
                source: context?.source,
                pressureBand: context?.pressureBand,
                aggregatePressureBand: context?.aggregatePressureBand,
                previousPressureBand: nil,
                worstProcessRole: context?.worstProcessRole,
                trimLevel: trimLevel,
                message: recordedMessage,
                context: context
            )
        )
    }

    private func append(_ record: MemoryContextDiagnosticRecord) {
        do {
            var data = try encoder.encode(record)
            data.append(0x0A)
            var firstError: Error?
            for target in targets {
                do {
                    try prepareFilesIfNeeded(for: target)
                    try append(data, to: target.memoryContextsURL)
                } catch {
                    firstError = firstError ?? error
                }
            }
            if let firstError {
                throw firstError
            }
            mirrorNativeEventsToAppContainerCacheIfNeeded()
        } catch {
            if TelemetryGate.resolvedEnabled {
                print("[IOSDeviceDiagnosticsRecorder] Could not write diagnostics: \(DiagnosticPrivacy.summary(of: error))")
            }
        }
    }

    private func append(_ data: Data, to url: URL) throws {
        if FileManager.default.fileExists(atPath: url.path) {
            let handle = try FileHandle(forWritingTo: url)
            defer { try? handle.close() }
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
        } else {
            try data.write(to: url, options: .atomic)
        }
    }

    private func prepareFilesIfNeeded(for target: Target) throws {
        guard !preparedTargets.contains(target.name) else { return }
        try FileManager.default.createDirectory(
            at: target.directory,
            withIntermediateDirectories: true
        )
        let manifest = DeviceDiagnosticsManifest(
            runID: runID,
            createdAt: dateFormatter.string(from: Date()),
            bundleIdentifier: Bundle.main.bundleIdentifier ?? "unknown",
            marketingVersion: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String,
            buildVersion: Bundle.main.object(forInfoDictionaryKey: kCFBundleVersionKey as String) as? String,
            deviceModel: Self.hostDescriptor.model,
            systemName: Self.hostDescriptor.systemName,
            systemVersion: Self.hostDescriptor.systemVersion,
            memoryContextsPath: target.memoryContextsURL.lastPathComponent,
            nativeEventsPath: target.nativeEventsURL.lastPathComponent
        )
        let data = try encoder.encode(manifest)
        try data.write(to: target.manifestURL, options: .atomic)
        preparedTargets.insert(target.name)
    }

    private func mirrorNativeEventsToAppContainerCacheIfNeeded() {
        guard let appGroupTarget = targets.first(where: { $0.name == "app-group" }),
              FileManager.default.fileExists(atPath: appGroupTarget.nativeEventsURL.path) else {
            return
        }
        for target in targets where target.name != appGroupTarget.name {
            do {
                try FileManager.default.createDirectory(
                    at: target.directory,
                    withIntermediateDirectories: true
                )
                if FileManager.default.fileExists(atPath: target.nativeEventsURL.path) {
                    try FileManager.default.removeItem(at: target.nativeEventsURL)
                }
                try FileManager.default.copyItem(
                    at: appGroupTarget.nativeEventsURL,
                    to: target.nativeEventsURL
                )
            } catch {
                if TelemetryGate.resolvedEnabled {
                    print("[IOSDeviceDiagnosticsRecorder] Could not mirror native events: \(DiagnosticPrivacy.summary(of: error))")
                }
            }
        }
    }
}

/// No absolute path: the store root names the user's home on macOS and the App Group
/// container on iPhone (AUD-08).
private struct DeviceDiagnosticsManifest: Codable {
    let runID: String
    let createdAt: String
    let bundleIdentifier: String
    let marketingVersion: String?
    let buildVersion: String?
    let deviceModel: String
    let systemName: String
    let systemVersion: String
    let memoryContextsPath: String
    let nativeEventsPath: String
}

private struct MemoryContextDiagnosticRecord: Codable {
    let event: String
    let recordedAt: String
    let processUptimeSeconds: Double
    let runID: String
    let reason: String
    let source: String?
    let pressureBand: IOSMemoryPressureBand?
    let aggregatePressureBand: IOSMemoryPressureBand?
    let previousPressureBand: IOSMemoryPressureBand?
    let worstProcessRole: IOSMemoryProcessRole?
    let combinedResidentBytes: UInt64?
    let combinedResidentMB: Double?
    let combinedPhysFootprintBytes: UInt64?
    let combinedPhysFootprintMB: Double?
    let combinedCompressedBytes: UInt64?
    let combinedCompressedMB: Double?
    let combinedGPUAllocatedBytes: UInt64?
    let combinedGPUAllocatedMB: Double?
    let appResidentBytes: UInt64?
    let appResidentMB: Double?
    let appPhysFootprintBytes: UInt64?
    let appPhysFootprintMB: Double?
    let appAvailableHeadroomBytes: UInt64?
    let appAvailableHeadroomMB: Double?
    let appImpliedProcessLimitBytes: UInt64?
    let appImpliedProcessLimitMB: Double?
    let trimLevel: NativeMemoryTrimLevel?
    let message: String?
    let context: IOSMemoryContext?

    init(
        event: String,
        recordedAt: String,
        processUptimeSeconds: Double,
        runID: String,
        reason: String,
        source: String?,
        pressureBand: IOSMemoryPressureBand?,
        aggregatePressureBand: IOSMemoryPressureBand?,
        previousPressureBand: IOSMemoryPressureBand?,
        worstProcessRole: IOSMemoryProcessRole?,
        trimLevel: NativeMemoryTrimLevel?,
        message: String?,
        context: IOSMemoryContext?
    ) {
        let appSnapshot = context?.appSnapshot

        self.event = event
        self.recordedAt = recordedAt
        self.processUptimeSeconds = processUptimeSeconds
        self.runID = runID
        self.reason = reason
        self.source = source
        self.pressureBand = pressureBand
        self.aggregatePressureBand = aggregatePressureBand
        self.previousPressureBand = previousPressureBand
        self.worstProcessRole = worstProcessRole
        self.combinedResidentBytes = context?.combinedResidentBytes
        self.combinedResidentMB = Self.bytesToMB(context?.combinedResidentBytes)
        self.combinedPhysFootprintBytes = context?.combinedPhysFootprintBytes
        self.combinedPhysFootprintMB = Self.bytesToMB(context?.combinedPhysFootprintBytes)
        self.combinedCompressedBytes = context?.combinedCompressedBytes
        self.combinedCompressedMB = Self.bytesToMB(context?.combinedCompressedBytes)
        self.combinedGPUAllocatedBytes = context?.combinedGPUAllocatedBytes
        self.combinedGPUAllocatedMB = Self.bytesToMB(context?.combinedGPUAllocatedBytes)
        self.appResidentBytes = appSnapshot?.residentBytes
        self.appResidentMB = appSnapshot?.residentMB
        self.appPhysFootprintBytes = appSnapshot?.physFootprintBytes
        self.appPhysFootprintMB = appSnapshot?.physFootprintMB
        self.appAvailableHeadroomBytes = appSnapshot?.availableHeadroomBytes
        self.appAvailableHeadroomMB = appSnapshot?.availableHeadroomMB
        self.appImpliedProcessLimitBytes = appSnapshot?.impliedProcessLimitBytes
        self.appImpliedProcessLimitMB = appSnapshot?.impliedProcessLimitMB
        self.trimLevel = trimLevel
        self.message = message
        self.context = context
    }

    private static func bytesToMB(_ bytes: UInt64?) -> Double? {
        guard let bytes else { return nil }
        return Double(bytes) / 1_048_576
    }

}
