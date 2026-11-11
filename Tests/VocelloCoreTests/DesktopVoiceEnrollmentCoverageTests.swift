import Foundation
import QwenVoiceCore
import XCTest
@testable import VocelloDesktopCore

/// G-01 on the command line: recognition that leaves part of the clip
/// unspoken is refused and nothing is saved. The recognizer is injected, so
/// no Speech permission is involved.
///
/// The recognition types are the desktop core's own (it compiles the shared
/// transcriber by path), hence the module-qualified names.
final class DesktopVoiceEnrollmentCoverageTests: XCTestCase {
    private typealias Transcriber = VocelloDesktopCore.VoiceClipTranscriber
    private static let contract = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
    private static let words = "The lighthouse keeper climbed the stairs again, counting each step aloud."

    @MainActor
    private func host() async throws -> (host: DesktopEngineHost, engine: MLXTTSEngine, root: URL) {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("DesktopVoiceEnrollmentCoverage-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        let registry = try ContractBackedModelRegistry(manifestURL: Self.contract)
            .expandedForPlatform(.macOS, deviceClass: .mid16GBMac, includeBaseAliases: true)
        let components = try NativeRuntimeFactory.make(
            registry: registry, paths: .rooted(at: root), storeVersionSeed: "rf51-coverage-fixture"
        )
        let host = DesktopEngineHost(
            engine: components.engine, consent: VoiceCloningConsentPolicy(isConsentRecorded: true), deviceClass: .mid16GBMac
        )
        try await host.initialize(appSupportDirectory: root)
        return (host, components.engine, root)
    }

    /// Ten seconds of a 220 Hz tone as a 16-bit mono PCM WAV at 24 kHz.
    private func clip(in root: URL) throws -> String {
        let url = root.appendingPathComponent("reference.wav")
        let samples: [Int16] = (0 ..< 10 * 24_000).map { frame in
            Int16((sin(2 * Double.pi * 220 * Double(frame) / 24_000) * 8_000).rounded())
        }
        var data = Data()
        func append<T: FixedWidthInteger>(_ value: T) {
            for shift in stride(from: 0, to: T.bitWidth, by: 8) { data.append(UInt8(truncatingIfNeeded: value >> shift)) }
        }
        data.append(contentsOf: Array("RIFF".utf8)); append(UInt32(36 + samples.count * 2))
        data.append(contentsOf: Array("WAVEfmt ".utf8)); append(UInt32(16)); append(UInt16(1)); append(UInt16(1))
        append(UInt32(24_000)); append(UInt32(48_000)); append(UInt16(2)); append(UInt16(16))
        data.append(contentsOf: Array("data".utf8)); append(UInt32(samples.count * 2))
        samples.forEach { append($0) }
        try data.write(to: url)
        return url.path
    }

    @MainActor
    func testARecognizedTranscriptThatDoesNotCoverTheClipIsRefused() async throws {
        let (host, engine, root) = try await host()
        defer { engine.stop() }
        let clip = try clip(in: root)
        let words = Self.words
        func enroll(
            _ name: String, _ coverage: Transcriber.TranscriptCoverage
        ) async throws -> DesktopVoiceEnrollment.Result {
            try await host.enrollVoice(
                DesktopVoiceEnrollment.Request(
                    name: name, audioPath: clip, transcript: nil, audioOnly: false, transcription: .always,
                    language: nil, onWarnings: .fail, replacingVoiceID: nil, source: .clip),
                recognize: { @concurrent _ in
                    Transcriber.EnrollmentResult(
                        text: words, language: .english,
                        evidence: .init(
                            schemaVersion: Transcriber.EnrollmentEvidence.currentSchemaVersion,
                            algorithmVersion: Transcriber.EnrollmentEvidence.currentAlgorithmVersion,
                            authorizationStatus: .authorized, outcome: .success, attempts: [],
                            bestLanguage: "english", bestLanguageScore: 1, bestTranscriptConfidence: 1),
                        coverage: coverage)
                })
        }
        for coverage in [Transcriber.TranscriptCoverage.partial, .unknown] {
            do {
                _ = try await enroll("Partial", coverage)
                XCTFail("A transcript with \(coverage) coverage was saved")
            } catch {
                XCTAssertEqual(error as? DesktopVoiceEnrollment.Failure, .transcriptIncomplete)
            }
        }
        let afterRefusals = try await engine.listPreparedVoices()
        XCTAssertTrue(afterRefusals.isEmpty, "A refused transcript leaves no voice behind")

        let saved = try await enroll("Whole", .whole)
        XCTAssertEqual(saved.outcome, .saved)
        XCTAssertEqual(saved.transcriptSource, "automatic")
    }
}
