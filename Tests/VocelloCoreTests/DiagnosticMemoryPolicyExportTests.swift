import Foundation
import QwenVoiceCore
import XCTest

/// Operator-only bridge: standalone runtime tests consume the actual host resolver,
/// never a copied table of allocator defaults. No model or network is required.
final class DiagnosticMemoryPolicyExportTests: XCTestCase {
    func testExportResolvedHostPolicyWhenRequested() throws {
        let policy = NativeMemoryPolicyResolver.policy(mode: .custom, isBatch: false)
        XCTAssertGreaterThan(policy.cacheLimitBytes, 0)
        guard let path = ProcessInfo.processInfo.environment["VOCELLO_TEST_MEMORY_POLICY_OUTPUT"] else { return }
        let url = URL(fileURLWithPath: path)
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.path))
        guard !FileManager.default.fileExists(atPath: url.path) else { return }
        let value: [String: Any] = [
            "schemaVersion": 1, "resolver": "NativeMemoryPolicyResolver",
            "name": policy.name, "cacheLimitBytes": policy.cacheLimitBytes,
            "memoryLimitBytes": policy.memoryLimitBytes as Any? ?? NSNull(),
            "tokenMemoryClearCadence": policy.mlxTokenMemoryClearCadence,
            "clearCacheOnStreamChunkEmit": policy.clearMLXCacheOnStreamChunkEmit,
        ]
        try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]).write(to: url, options: .withoutOverwriting)
    }
}
