import Foundation

enum AppLaunchIssue: String, Equatable, Sendable {
    case invalidContract
    case engineBootstrapFailed

    var summary: String {
        switch self {
        case .invalidContract:
            return MacInterfaceText.startupInvalidContract
        case .engineBootstrapFailed:
            return MacInterfaceText.startupEngineBootstrapFailed
        }
    }
}

struct AppLaunchDiagnosticsSnapshot: Equatable, Sendable {
    let issue: AppLaunchIssue
    let manifestPath: String?
    let bundlePath: String
    let resourcesPath: String?
    let underlyingError: String

    var diagnosticsText: String {
        [
            issue.summary,
            "Manifest path: \(manifestPath ?? "not found")",
            "Bundle path: \(bundlePath)",
            "Resources path: \(resourcesPath ?? "not found")",
            "Details: \(underlyingError)",
        ]
        .joined(separator: "\n")
    }
}

enum AppLaunchPreflight {
    static var shouldShowDiagnostics: Bool {
        shouldShowDiagnostics(
            bundlePath: Bundle.main.bundlePath
        )
    }

    static func shouldShowDiagnostics(bundlePath: String) -> Bool {
        guard !bundlePath.contains("/DerivedData/") else { return false }
        return true
    }

    static func run() -> AppLaunchDiagnosticsSnapshot? {
        guard shouldShowDiagnostics else { return nil }

        let manifestPath = TTSContract.manifestURL?.path ?? TTSContract.loadError?.manifestPath
        let bundlePath = Bundle.main.bundlePath
        let resourcesPath = Bundle.main.resourceURL?.path

        if let loadError = TTSContract.loadError {
            return AppLaunchDiagnosticsSnapshot(
                issue: .invalidContract,
                manifestPath: manifestPath,
                bundlePath: bundlePath,
                resourcesPath: resourcesPath,
                underlyingError: "\(loadError.summary)\n\n\(loadError.details)"
            )
        }

        return nil
    }
}
