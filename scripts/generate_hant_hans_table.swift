// Derives the Traditional-to-Simplified Chinese fold table of text normalization v3 (AQ-02 P2b)
// from ICU's `Hant-Hans` transform, which Foundation's `StringTransform` exposes on macOS.
//
// The committed table is a reviewed snapshot and is never regenerated routinely: ICU's data
// moves with the OS, and a table that changes moves what every Chinese language verdict
// measures. A new table is a new versioned file (`hant-hans-v2.txt`), a new manifest beside it
// and a new text normalization version in `scripts/lib/language_metrics.py`. Run it on macOS:
//
//   xcrun swiftc -O scripts/generate_hant_hans_table.swift -o <scratch>/generate-hant-hans
//   <scratch>/generate-hant-hans <scratch>/hant-hans-v2.txt
//
// Each code point of the CJK ranges below is transformed alone, and a mapping is kept when the
// result is exactly one scalar that differs from the input. The table is then closed so the fold
// is idempotent (no target is itself a source, so folding both sides of a comparison meets in
// one spelling): a chain is followed to its end, and a cycle folds to its lowest code point
// (ICU 78 maps U+82CE and U+82E7 to each other). The summary names every entry the closure
// changed, for the manifest.
import CryptoKit
import Foundation

let ranges: [ClosedRange<UInt32>] = [
    0x3400 ... 0x4DBF, // CJK Unified Ideographs Extension A
    0x4E00 ... 0x9FFF, // CJK Unified Ideographs
    0xF900 ... 0xFAFF, // CJK Compatibility Ideographs
    0x20000 ... 0x2A6DF, // CJK Unified Ideographs Extension B
]

guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write(Data("usage: generate-hant-hans <output.txt>\n".utf8))
    exit(2)
}

let transform = StringTransform("Hant-Hans")
var raw: [UInt32: UInt32] = [:]
for range in ranges {
    for value in range {
        guard let scalar = Unicode.Scalar(value) else { continue }
        let text = String(scalar)
        guard let folded = text.applyingTransform(transform, reverse: false), folded != text else { continue }
        let scalars = Array(folded.unicodeScalars)
        if scalars.count == 1 {
            raw[value] = scalars[0].value
        }
    }
}

/// Where `start` folds once the table is closed: the end of its chain, or the lowest code point
/// of the cycle the chain enters.
func terminal(_ start: UInt32) -> UInt32 {
    var path: [UInt32] = [start]
    var current = start
    while let next = raw[current] {
        if let index = path.firstIndex(of: next) {
            return path[index...].min() ?? next
        }
        path.append(next)
        current = next
    }
    return current
}

func hex(_ value: UInt32) -> String {
    String(value, radix: 16, uppercase: true)
}

var lines: [String] = []
var changes: [String] = []
for source in raw.keys.sorted() {
    let target = terminal(source)
    if target != raw[source] {
        changes.append("\(hex(source)): ICU \(hex(raw[source] ?? source)), folded \(target == source ? "none" : hex(target))")
    }
    if target != source {
        lines.append("\(hex(source)) \(hex(target))")
    }
}

let table = Data(lines.map { $0 + "\n" }.joined().utf8)
do {
    try table.write(to: URL(fileURLWithPath: CommandLine.arguments[1]), options: .atomic)
} catch {
    FileHandle.standardError.write(Data("error: cannot write the table: \(error)\n".utf8))
    exit(1)
}
let digest = SHA256.hash(data: table).map { String(format: "%02x", $0) }.joined()
print("ICU Hant-Hans single-scalar mappings: \(raw.count)")
print("closed table entries: \(lines.count)")
for change in changes {
    print("closure: \(change)")
}
print("sha256: \(digest)")
