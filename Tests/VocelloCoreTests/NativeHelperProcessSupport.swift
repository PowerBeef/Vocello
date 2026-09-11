import Darwin
import Foundation
import XCTest

/// Launches a helper XCTest case in a separate native process, and names the one
/// environment in which that cannot work.
///
/// Two suites exercise real cross-process boundaries (CLI signal supervision, the
/// prepared-voice store lock) by running one of their own test methods in a child
/// `xctest`. Under the ThreadSanitizer lane (`scripts/macos_test.sh tsan`) every child
/// spawned from the instrumented parent aborts at load in `VerifyInterceptorsWorking`,
/// whether the insertion variable is inherited, re-injected explicitly, or removed so the
/// runtime's own `posix_spawn` propagation applies (all three were tried on 2026-09-11
/// with Xcode 26.6; the same child launched from an uninstrumented parent runs cleanly).
/// The parent then times out and, before this helper existed, an unguarded assertion
/// crashed the bundle so most of the suite never ran. These two-process tests therefore
/// skip under the sanitizer and remain covered by the ordinary lane on every checkpoint;
/// `config/tsan-policy.json` records the exclusion.
enum NativeHelperProcess {
    static func xctest(running testIdentifier: String, in bundle: Bundle) -> Process {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/xcrun")
        process.arguments = ["xctest", "-XCTest", testIdentifier, bundle.bundleURL.path]
        process.environment = ProcessInfo.processInfo.environment
        return process
    }

    /// Skip a helper-process test when the ThreadSanitizer runtime is loaded into this process.
    static func skipUnderThreadSanitizer(file: StaticString = #filePath, line: UInt = #line) throws {
        if let runtime = loadedSanitizerRuntimePath() {
            throw XCTSkip(
                "helper xctest children cannot start from a ThreadSanitizer-instrumented parent "
                + "(VerifyInterceptorsWorking abort; runtime \(runtime)); covered by the non-sanitized lane",
                file: file, line: line)
        }
    }

    /// Path of the ThreadSanitizer runtime if it is loaded into this process.
    static func loadedSanitizerRuntimePath() -> String? {
        for index in 0..<_dyld_image_count() {
            guard let raw = _dyld_get_image_name(index) else { continue }
            let name = String(cString: raw)
            if name.contains("libclang_rt.tsan") { return name }
        }
        return nil
    }
}
