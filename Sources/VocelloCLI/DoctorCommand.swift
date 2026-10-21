import Foundation
import QwenVoiceCore
import VocelloCLICore

/// `vocello doctor`: a read-only check of what the CLI needs, with no engine
/// boot: the data folder, the bundled contract and catalog, installed models,
/// the memory tier and free disk. A missing trust anchor is a configuration
/// error (exit 78); anything else is a warning the result names.
enum DoctorCommand {
    struct Check: Encodable, Sendable {
        let name: String
        /// ok, warn or fail.
        let status: String
        let message: String
    }

    struct Report: Encodable, Sendable {
        let vocelloVersion: String
        let build: String
        let macOSVersion: String
        let physicalMemoryBytes: String
        let memoryClass: String
        let dataDirectory: String
        let installedModels: [String]
        let modelCount: Int
        let freeDiskBytes: String?
        let checks: [Check]
    }

    @MainActor
    static func run(_ args: Args) async throws {
        let dataDirectory = CLIPaths.dataDirectory(override: args.string("data-dir"))
        var checks: [Check] = []
        var installed: [String] = []
        var modelCount = 0

        let fileManager = FileManager.default
        var isDirectory: ObjCBool = false
        if unsafe fileManager.fileExists(atPath: dataDirectory.path, isDirectory: &isDirectory), isDirectory.boolValue {
            checks.append(Check(name: "data-directory", status: "ok", message: "the shared data folder exists"))
        } else {
            checks.append(Check(
                name: "data-directory", status: "warn",
                message: "no data folder yet; it is created by the first install or take"
            ))
        }

        let contractFound: Bool
        do {
            let context = try CLIRuntime.bootstrapRegistryOnly(
                dataDirectory: dataDirectory,
                manifestOverride: args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) }
            )
            contractFound = true
            modelCount = context.registry.models.count
            installed = context.registry.models.compactMap { model in
                if case .available = context.registry.availability(forModelID: model.id, in: context.modelsDirectory) {
                    return model.id
                }
                return nil
            }
            checks.append(Check(name: "contract", status: "ok", message: "the model contract loads"))
            checks.append(Check(
                name: "models", status: installed.isEmpty ? "warn" : "ok",
                message: installed.isEmpty
                    ? "no model is installed; install one with `vocello models install <id>`"
                    : "\(installed.count) of \(modelCount) models installed"
            ))
        } catch {
            contractFound = false
            checks.append(Check(name: "contract", status: "fail", message: CLIFailure.classify(error).message))
        }

        let catalogFound = (try? CLIRuntime.locateProductionCatalogURL())
            .flatMap { try? ProductionModelCatalog(contentsOf: $0) } != nil
        checks.append(Check(
            name: "catalog", status: catalogFound ? "ok" : "fail",
            message: catalogFound ? "the authenticated model catalog loads" : "the authenticated model catalog is missing or invalid"
        ))

        let memoryClass = NativeMemoryPolicyResolver.deviceClass()
        checks.append(Check(
            name: "memory", status: memoryClass == .floor8GBMac ? "warn" : "ok",
            message: memoryClass == .floor8GBMac
                ? "an 8 GB Mac: prefer --variant speed and quit other apps for long takes"
                : "memory tier \(memoryClass.rawValue)"
        ))

        let probe = fileManager.fileExists(atPath: dataDirectory.path)
            ? dataDirectory : URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)
        let free = (try? probe.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey]))?
            .volumeAvailableCapacityForImportantUsage
        if let free {
            let low = free < 8 * 1_073_741_824
            checks.append(Check(
                name: "disk", status: low ? "warn" : "ok",
                message: low ? "less than 8 GB free; a model install needs up to 4 GB" : "\(humanBytes(free)) free"
            ))
        }

        let report = Report(
            vocelloVersion: vocelloCLIVersion, build: vocelloCLIBuild,
            macOSVersion: ProcessInfo.processInfo.operatingSystemVersionString,
            physicalMemoryBytes: String(ProcessInfo.processInfo.physicalMemory),
            memoryClass: memoryClass.rawValue, dataDirectory: dataDirectory.path,
            installedModels: installed, modelCount: modelCount, freeDiskBytes: free.map { String($0) },
            checks: checks
        )
        if CLIPresenter.isMachine {
            if contractFound && catalogFound {
                CLIPresenter.succeed(report)
            } else {
                CLIPresenter.recordPartialResult(report)
            }
        } else {
            print("vocello \(vocelloCLIVersion) (\(vocelloCLIBuild)) · \(report.macOSVersion) · \(memoryClass.rawValue)")
            print("data: \(dataDirectory.path)")
            for check in checks {
                let mark = check.status == "ok" ? "✓" : check.status == "warn" ? "!" : "✗"
                print("\(mark) \(check.name)\t\(check.message)")
            }
        }
        if !(contractFound && catalogFound) {
            throw CLIError(.configError, "the CLI's model contract or catalog is unusable", hint: "reinstall the CLI")
        }
    }
}
