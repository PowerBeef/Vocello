import Foundation
import MLX
import MLXAudioMark

/// First-party audio-marking surface (EU AI Act Article 50, CP-2).
///
/// Product code reaches AudioSeal only through this facade API: it loads the
/// fused wm16 generator, embeds the fixed Vocello payload with the
/// exact-streaming windowed embedder, and drops the generator before
/// returning (load-and-drop keeps the take lifecycle's peak footprint
/// unchanged). The pass runs on the GPU inside an MLX error scope (see
/// `markedPCM`).
public enum VocelloQwen3AudioMarking {
    /// The fixed 16-bit payload every published Vocello WAV carries
    /// (deterministic embedding and detector-side attribution).
    public static var payload: UInt16 { AudioSealGenerator.messagePayload }

    /// The mark's frame, in samples. A detector reads the mark on this grid,
    /// counted from the first sample of the file it is given. Audio that is
    /// cropped or joined after marking must keep every marked sample at a
    /// position that is a whole number of frames from where it was marked:
    /// off the grid the reference detector reads a weaker mark and a wrong
    /// payload (measured 2026-11-11, RF-44).
    public static var frameSampleCount: Int { AudioSealGenerator.totalStride }

    /// Embeds the watermark into 24 kHz mono PCM and returns the marked
    /// samples. The generator is constructed and released inside the call.
    ///
    /// Runs on the default (GPU) device deliberately: the pass executes only
    /// after the post-take cache trim, when the generation working set has
    /// been released, and the windowed embedder's workspace is one window
    /// per window size class, recycled through the allocator cache and
    /// cleared when the pass ends — MLX's CPU conv path measured near 1× realtime
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
        // An MLX error (for example a failed Metal allocation) throws a typed
        // `VocelloQwen3RuntimeFailure` instead of reaching `fatalError`.
        return try VocelloQwen3MLXErrorScope().capture {
            try autoreleasepool {
                let generator = try AudioSealGenerator(weightsURL: weightsURL)
                return try generator.watermark(pcm: pcm)
            }
        }
    }
}
