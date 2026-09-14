import Foundation

extension IOSSavedOutputsDestination {
    /// App-target entry: the automatic folder copy consults the one verified
    /// StoreKit owner. Tests call the injectable form directly.
    @MainActor
    static func exportIfConfigured(internalAudioPath: String, generationMode: String) {
        exportIfConfigured(internalAudioPath: internalAudioPath, generationMode: generationMode) {
            IOSExportCommerce.shared.permits([$0])
        }
    }
}
