import Foundation
@preconcurrency import MLX
import MLXAudioCore

/// The talker's text embedding, read by row from the checkpoint file (RF-47).
///
/// The table is 151,936 rows and about a quarter of a Speed checkpoint
/// (315 MB of 1,272 MB), while a take reads a few hundred of its rows, once,
/// to build its prompt. Loaded as a parameter the whole table stays resident
/// for as long as the model does. This reader keeps the file open instead and
/// reads the rows a prompt names, so the table never enters the process's
/// memory.
///
/// The result is the embedding layer's result bit for bit: the layer gathers
/// the rows of the packed weights, scales and biases and dequantizes them,
/// and this reads the same rows from the same bytes and dequantizes them with
/// the same call. The fixed-seed PCM digests are the arbiter, and the unit
/// tests pin bit equality on a small table.
///
/// The reader assumes what the weights in memory already assume: the file a
/// model was loaded from is never rewritten in place. Installed artifacts are
/// activated atomically as complete directories and shared as hard links, so
/// a replacement is a new file; an open handle keeps the old one's data
/// readable after it is unlinked, and a model removed while it is loaded
/// keeps generating until it is unloaded. The handle's seek-then-read cursor
/// is not atomic: like every MLX value of the model, the reader is used only
/// by the model's single operation owner.
final class Qwen3TextEmbeddingRows {
    /// The quantization recipe the checkpoint's config declares for the table.
    struct Quantization: Equatable {
        let groupSize: Int
        let bits: Int
    }

    /// One tensor of the file: where its bytes start and how a row is laid out.
    private struct Tensor {
        let fileOffset: UInt64
        let rows: Int
        let columns: Int
        let dtype: DType

        var rowBytes: Int { columns * dtype.size }
    }

    private enum Layout {
        case affine(weight: Tensor, scales: Tensor, biases: Tensor, quantization: Quantization)
        case plain(weight: Tensor)
    }

    private let file: FileHandle
    private let layout: Layout
    let rowCount: Int
    let dimensions: Int

    private init(file: FileHandle, layout: Layout, rowCount: Int, dimensions: Int) {
        self.file = file
        self.layout = layout
        self.rowCount = rowCount
        self.dimensions = dimensions
    }

    deinit {
        try? file.close()
    }

    /// Opens the table named `tensorPrefix` in `weightsFile`.
    ///
    /// Returns nil, leaving the caller to load the table as a parameter, when
    /// the file does not hold it in a layout this reader knows: no such
    /// tensor, a shape other than `rowCount` by `dimensions`, a dtype it does
    /// not map, or packed weights without the recipe to unpack them. A file
    /// that cannot be opened, whose header is malformed, or that ends before
    /// the table does throws `modelNotInitialized`.
    static func open(
        weightsFile: URL,
        tensorPrefix: String,
        rowCount: Int,
        dimensions: Int,
        quantization: Quantization?
    ) throws -> Qwen3TextEmbeddingRows? {
        // Fixed messages: a Foundation error would carry the model's path.
        let unreadable = AudioGenerationError.modelNotInitialized(
            "The model weights file could not be read."
        )
        let malformed = AudioGenerationError.modelNotInitialized(
            "The model weights file has a malformed safetensors header."
        )
        guard let file = try? FileHandle(forReadingFrom: weightsFile) else { throw unreadable }
        var keepOpen = false
        defer { if !keepOpen { try? file.close() } }

        // safetensors: an 8-byte little-endian header length, a JSON header,
        // then the tensors' bytes at offsets relative to the header's end.
        guard let fileSize = try? file.seekToEnd(), (try? file.seek(toOffset: 0)) != nil,
              let lengthBytes = try? file.read(upToCount: 8)
        else { throw unreadable }
        guard lengthBytes.count == 8 else { throw malformed }
        let headerLength = lengthBytes.enumerated().reduce(UInt64(0)) { partial, byte in
            partial | (UInt64(byte.element) << (8 * UInt64(byte.offset)))
        }
        // The format caps the header at 100 MB.
        guard headerLength > 0, headerLength <= 100_000_000, 8 + headerLength <= fileSize,
              let headerBytes = try? file.read(upToCount: Int(headerLength)),
              headerBytes.count == Int(headerLength),
              let header = (try? JSONSerialization.jsonObject(with: headerBytes)) as? [String: Any]
        else { throw malformed }
        let dataStart = 8 + headerLength

        // A tensor whose bytes run past the end of the file is a truncated
        // checkpoint: the load fails here rather than every later take.
        var truncated = false
        func tensor(_ suffix: String) -> Tensor? {
            guard let entry = header["\(tensorPrefix).\(suffix)"] as? [String: Any],
                  let dtypeName = entry["dtype"] as? String,
                  let dtype = Self.dtype(named: dtypeName),
                  let shape = entry["shape"] as? [Int], shape.count == 2,
                  let offsets = entry["data_offsets"] as? [Int], offsets.count == 2,
                  shape[0] > 0, shape[1] > 0, offsets[0] >= 0, offsets[1] >= offsets[0]
            else { return nil }
            // Overflow-checked: the header is input, not a trusted value.
            let (cells, cellsOverflow) = shape[0].multipliedReportingOverflow(by: shape[1])
            let (byteCount, bytesOverflow) = cells.multipliedReportingOverflow(by: dtype.size)
            guard !cellsOverflow, !bytesOverflow, offsets[1] - offsets[0] == byteCount else { return nil }
            let (end, endOverflow) = dataStart.addingReportingOverflow(UInt64(offsets[1]))
            guard !endOverflow, end <= fileSize else {
                truncated = true
                return nil
            }
            return Tensor(
                fileOffset: dataStart + UInt64(offsets[0]),
                rows: shape[0], columns: shape[1], dtype: dtype
            )
        }

        let truncatedFile = AudioGenerationError.modelNotInitialized(
            "The model weights file is shorter than its header declares."
        )
        guard let weight = tensor("weight") else {
            if truncated { throw truncatedFile }
            return nil
        }
        guard weight.rows == rowCount else { return nil }
        let layout: Layout
        if header["\(tensorPrefix).scales"] != nil {
            guard let quantization,
                  quantization.groupSize > 0, quantization.bits > 0,
                  weight.dtype == .uint32,
                  weight.columns * 32 == dimensions * quantization.bits,
                  dimensions % quantization.groupSize == 0,
                  let scales = tensor("scales"), let biases = tensor("biases"),
                  !truncated,
                  scales.rows == rowCount, biases.rows == rowCount,
                  scales.columns == dimensions / quantization.groupSize,
                  biases.columns == scales.columns,
                  scales.dtype == biases.dtype, scales.dtype != .uint32
            else {
                if truncated { throw truncatedFile }
                return nil
            }
            layout = .affine(weight: weight, scales: scales, biases: biases, quantization: quantization)
        } else {
            guard weight.columns == dimensions, weight.dtype != .uint32 else { return nil }
            layout = .plain(weight: weight)
        }
        keepOpen = true
        return Qwen3TextEmbeddingRows(file: file, layout: layout, rowCount: rowCount, dimensions: dimensions)
    }

    /// The embeddings of `ids` (any shape of integer token ids), shaped
    /// `ids.shape + [dimensions]`.
    func embed(_ ids: MLXArray) throws -> MLXArray {
        let shape = ids.shape
        // Some callers pass a lazy slice or concatenation, and this is a
        // take's first evaluation: probe it, so an MLX failure is thrown
        // instead of trapping in the readback (mlx-guide section 2.6).
        let indices = ids.asType(.int32)
        try evalForReadback(indices)
        let rows = indices.asArray(Int32.self)
        guard !rows.isEmpty else {
            throw AudioGenerationError.invalidInput("A text embedding needs at least one token.")
        }
        guard rows.allSatisfy({ $0 >= 0 && Int($0) < rowCount }) else {
            throw AudioGenerationError.invalidInput("A text token is outside the model's vocabulary.")
        }
        let embedded: MLXArray
        switch layout {
        case .affine(let weight, let scales, let biases, let quantization):
            embedded = dequantized(
                try gather(weight, rows),
                scales: try gather(scales, rows),
                biases: try gather(biases, rows),
                groupSize: quantization.groupSize,
                bits: quantization.bits,
                mode: .affine
            )
        case .plain(let weight):
            embedded = try gather(weight, rows)
        }
        return embedded.reshaped(shape + [-1])
    }

    /// The named rows of one tensor, in order, as a `[rows.count, columns]` array.
    private func gather(_ tensor: Tensor, _ rows: [Int32]) throws -> MLXArray {
        var bytes = Data(capacity: rows.count * tensor.rowBytes)
        for row in rows {
            let offset = tensor.fileOffset + UInt64(row) * UInt64(tensor.rowBytes)
            guard (try? file.seek(toOffset: offset)) != nil,
                  let chunk = try? file.read(upToCount: tensor.rowBytes),
                  chunk.count == tensor.rowBytes
            else {
                throw AudioGenerationError.generationFailed(
                    "The text embedding could not be read from the model weights file."
                )
            }
            bytes.append(chunk)
        }
        return MLXArray(bytes, [rows.count, tensor.columns], dtype: tensor.dtype)
    }

    private static func dtype(named name: String) -> DType? {
        switch name {
        case "U32": .uint32
        case "BF16": .bfloat16
        case "F16": .float16
        case "F32": .float32
        default: nil
        }
    }
}
