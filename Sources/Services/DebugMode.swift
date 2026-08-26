import Foundation
import QwenVoiceCore

/// App-target view of the process-local runtime debug gate. Behavior-changing
/// overrides require an internal diagnostics build plus an explicit
/// `QWENVOICE_DEBUG` launch opt-in; distributed builds have no such capability.
enum DebugMode {
    static let isEnabled = RuntimeDebugGate.isEnabled()
}
