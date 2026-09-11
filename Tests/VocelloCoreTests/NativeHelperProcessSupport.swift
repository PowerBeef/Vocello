import Foundation
import XCTest

/// Launches a helper XCTest case in a separate native process.
///
/// Two suites exercise real cross-process boundaries (CLI signal supervision, the
/// prepared-voice store lock) by running one of their own test methods in a child
/// `xctest`. Under the ThreadSanitizer lane (`scripts/macos_test.sh tsan`) the parent is
/// started as the resolved `xctest` binary with the TSan runtime preloaded through
/// `DYLD_INSERT_LIBRARIES`; a child started through `/usr/bin/xcrun` loses that variable
/// (macOS strips it before exec), the instrumented bundle then aborts at load in
/// `VerifyInterceptorsWorking`, and the parent times out. Launching the child exactly the
/// way the lane launched the parent keeps both processes instrumented.
enum NativeHelperProcess {
    enum LaunchError: Error { case xctestNotFound }

    static func xctest(running testIdentifier: String, in bundle: Bundle) throws -> Process {
        let process = Process()
        let inserted = ProcessInfo.processInfo.environment["DYLD_INSERT_LIBRARIES"] ?? ""
        if inserted.contains("tsan") {
            process.executableURL = URL(fileURLWithPath: try resolvedXCTestPath())
            process.arguments = ["-XCTest", testIdentifier, bundle.bundleURL.path]
        } else {
            process.executableURL = URL(fileURLWithPath: "/usr/bin/xcrun")
            process.arguments = ["xctest", "-XCTest", testIdentifier, bundle.bundleURL.path]
        }
        return process
    }

    private static func resolvedXCTestPath() throws -> String {
        let find = Process()
        find.executableURL = URL(fileURLWithPath: "/usr/bin/xcrun")
        find.arguments = ["--find", "xctest"]
        let output = Pipe()
        find.standardOutput = output
        find.standardError = FileHandle.nullDevice
        try find.run()
        find.waitUntilExit()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        guard find.terminationStatus == 0,
              let path = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines),
              !path.isEmpty else {
            throw LaunchError.xctestNotFound
        }
        return path
    }
}
