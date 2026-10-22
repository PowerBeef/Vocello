import Foundation
import QwenVoiceCore

/// RF-28: removing an installed model as the app's model manager removes one
/// (`ModelManagerViewModel.delete`): its staging first, then the model through
/// the shared component store, which also reclaims shared files no other model
/// uses. This process holds no engine, so the only risk is another one: the
/// caller says whether one runs (the app, or another vocello), and then nothing
/// is removed.
public enum DesktopModelRemoval {
    public enum Refusal: Error, Equatable, Sendable {
        case notInstalled
        /// Another engine runs and may have the model loaded.
        case engineRunning
    }

    public static func remove(
        _ descriptor: ModelDescriptor, modelsDirectory: URL, otherEngineRunning: Bool
    ) throws {
        let modelDirectory = descriptor.installDirectory(in: modelsDirectory)
        guard FileManager.default.fileExists(atPath: modelDirectory.path) else { throw Refusal.notInstalled }
        guard !otherEngineRunning else { throw Refusal.engineRunning }
        // Staging first: its reuse pins would otherwise keep the blobs the removal releases.
        HuggingFaceDownloader.discardStaging(forTargetDirectory: modelDirectory)
        try SharedModelComponentStore(modelsRoot: modelsDirectory).deleteModel(
            modelFolder: modelDirectory.lastPathComponent, reclamation: .immediate
        )
    }
}
