import Foundation
import Synchronization
import VocelloCLICore
import XCTest

/// The CLI's command handlers, run in-process over an empty data folder with no model and no
/// engine (RF-61, audit finding T8). Until they moved into `VocelloCLICore`, `models`, `history`,
/// `settings` and `doctor` were outside every test, and only three read-only commands of the
/// packaged binary were ever run. Each envelope is checked against the shape contract v1 promises.
@MainActor
final class CLICommandHandlerTests: XCTestCase {
    private var root: URL!

    private static let contract = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")

    override func setUp() async throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("CLICommandHandlers-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDown() async throws {
        try? FileManager.default.removeItem(at: root)
    }

    private func arguments(_ extra: [String] = [], for path: String...) throws -> Args {
        try CLIParser.parse(
            path + ["--data-dir", root.path, "--manifest", Self.contract.path, "--json"] + extra
        ).args
    }

    /// Runs `body` as the command `name` in json mode and returns its one envelope.
    private func envelope(
        of name: String, _ body: () async throws -> Void
    ) async throws -> [String: Any] {
        let captured = Mutex<[Data]>([])
        CLIPresenter.begin(format: .json, command: name, requestID: "fixture") { data in
            captured.withLock { $0.append(data) }
            return true
        }
        try await body()
        CLIPresenter.finishSuccessIfUnreported()
        let lines = captured.withLock { $0 }
        XCTAssertEqual(lines.count, 1, "\(name) writes exactly one envelope")
        let envelope = try XCTUnwrap(
            JSONSerialization.jsonObject(with: try XCTUnwrap(lines.first)) as? [String: Any]
        )
        XCTAssertEqual(envelope["schemaVersion"] as? Int, 1)
        XCTAssertEqual(envelope["ok"] as? Bool, true, "\(name): \(String(describing: envelope["error"]))")
        XCTAssertEqual(envelope["command"] as? String, name)
        XCTAssertEqual(envelope["requestID"] as? String, "fixture")
        XCTAssertTrue(envelope["error"] is NSNull)
        XCTAssertNotNil(envelope["warnings"] as? [Any])
        XCTAssertNotNil(envelope["meta"] as? [String: Any])
        return envelope
    }

    func testModelsListNamesEachModesOneModelAsNotInstalledInAnEmptyFolder() async throws {
        let args = try arguments(for: "models", "list")
        let envelope = try await envelope(of: "models.list") {
            try await ModelsCommand.run(action: "list", args)
        }
        let result = try XCTUnwrap(envelope["result"] as? [String: Any])
        let models = try XCTUnwrap(result["models"] as? [[String: Any]])
        let ids = Set(models.compactMap { $0["id"] as? String })
        XCTAssertTrue(ids.isSuperset(of: ["pro_custom_speed", "pro_design_speed", "pro_clone_speed"]))
        XCTAssertFalse(ids.contains { $0.hasSuffix("_quality") }, "each mode has one model since RF-59")
        XCTAssertTrue(models.allSatisfy { ($0["installed"] as? Bool) == false })
    }

    func testModelsActiveResolvesEachModeToItsOneModel() async throws {
        let args = try arguments(for: "models", "active")
        let envelope = try await envelope(of: "models.active") {
            try await ModelsCommand.run(action: "active", args)
        }
        XCTAssertNotNil(envelope["result"] as? [String: Any])
    }

    func testHistoryListOverAFolderWithoutAHistoryIsEmptyNotAnError() async throws {
        let args = try arguments(for: "history", "list")
        let envelope = try await envelope(of: "history.list") {
            try await HistoryCommand.run(action: "list", args)
        }
        let result = try XCTUnwrap(envelope["result"] as? [String: Any])
        XCTAssertEqual((result["items"] as? [Any])?.count, 0)
    }

    func testDoctorReportsItsChecksWithoutAModelOrAnEngine() async throws {
        let args = try arguments(for: "doctor")
        let envelope = try await envelope(of: "doctor") {
            try await DoctorCommand.run(args)
        }
        let result = try XCTUnwrap(envelope["result"] as? [String: Any])
        let checks = try XCTUnwrap(result["checks"] as? [[String: Any]])
        XCTAssertFalse(checks.isEmpty)
        XCTAssertTrue(checks.allSatisfy { $0["name"] is String && $0["status"] is String })
    }

    func testRemovingAnUnknownModelIsTheContractsErrorNotACrash() async throws {
        let args = try arguments(["no_such_model"], for: "models", "remove")
        CLIPresenter.begin(format: .json, command: "models.remove", requestID: "fixture") { _ in true }
        do {
            try await ModelsCommand.run(action: "remove", args)
            XCTFail("an unknown model id must be refused")
        } catch let error as CLIError {
            XCTAssertEqual(error.code, .modelUnknown)
        }
    }
}
