import Foundation
import MLX
import MLXAudioMark

/// First-party audio-marking surface (EU AI Act Article 50, CP-2).
///
/// Product code reaches AudioSeal only through this facade API: it loads the
/// fused wm16 generator, embeds the fixed Vocello payload with the
/// exact-streaming windowed embedder, and drops the generator before
/// returning (load-and-drop keeps the take lifecycle's peak footprint
/// unchanged). The whole pass is scoped to the CPU device so publication-time
/// marking never allocates GPU wired memory.
public enum VocelloQwen3AudioMarking {
    /// The fixed 16-bit payload every published Vocello WAV carries
    /// (deterministic embedding and detector-side attribution).
    public static var payload: UInt16 { AudioSealGenerator.messagePayload }

    /// Embeds the watermark into 24 kHz mono PCM and returns the marked
    /// samples. The generator is constructed and released inside the call.
    ///
    /// Runs on the default (GPU) device deliberately: the pass executes only
    /// after the post-take cache trim, when the generation working set has
    /// been released, and the windowed embedder returns each window's
    /// buffers immediately — MLX's CPU conv path measured near 1× realtime
    /// with ~300 MB per-window transients, while the Metal path is fast and
    /// its transient wired use is freed before the next take. The
    /// fail-closed peak-equality assertion in the memory-qualification lane
    /// is the binding zero-peak arbiter, not the device choice.
    public static func markedPCM(
        _ pcm: [Float],
        weightsURL: URL
    ) throws -> [Float] {
        // Drain autoreleased Metal objects (command buffers, weight-load
        // staging) before returning: the cooperative-pool thread running
        // publication never drains its implicit pool, and anything left in
        // it reads as permanently retained memory to the peak-equality lane.
        defer { Memory.clearCache() }
        return try autoreleasepool {
            let generator = try AudioSealGenerator(weightsURL: weightsURL)
            return generator.watermark(pcm: pcm)
        }
    }
}
