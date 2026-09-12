import Foundation
import QwenVoiceCore

/// `vocello deliveries` — list the built-in delivery presets (emotion x intensity)
/// and the natural-language instruction each one sends to the model. Static +
/// instant (no engine boot), reading `EmotionPreset` (the single source of truth).
///
/// This is the roster the delivery harness reads (`--shipped-only --json`) and a
/// way to discover the `bench --delivery <id>` cell ids. Delivery adherence is
/// measured by `vocello bench --delivery` plus `scripts/bench_delivery_prosody.py`,
/// which pairs each instructed take with its same-seed neutral take and compares
/// their acoustics; adherence is judged by acoustics, not by an external model ear.
enum DeliveriesCommand {
    struct DeliveryJSON: Encodable {
        let id: String          // "<preset>.<intensity>"
        let preset: String
        let intensity: String
        let label: String
        let instruction: String
    }

    @MainActor
    static func run(_ argv: [String]) async throws {
        var argv = argv
        if let first = argv.first?.lowercased(), first == "list" || first == "ls" { argv.removeFirst() }
        let args = Args(argv)
        if args.flag("help") { printHelp(); return }
        CLIOutput.configure(args)

        var rows: [DeliveryJSON] = []
        if args.flag("shipped-only") {
            // One row per product-visible preset, including instructed
            // Neutral, at the exact tier fresh selections ship. This is the
            // machine-readable roster used by the autonomous speaker matrix;
            // it must not duplicate the tier policy in Python.
            for preset in EmotionPreset.all {
                let intensity = preset.shippedIntensity
                let instr = preset.instruction(for: intensity)
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                guard !instr.isEmpty else { continue }
                rows.append(DeliveryJSON(
                    id: "\(preset.id).\(intensity.rpcValue)",
                    preset: preset.id,
                    intensity: intensity.rpcValue,
                    label: preset.label,
                    instruction: instr))
            }
        } else {
            for preset in EmotionPreset.all where preset.id != "neutral" {
                for intensity in EmotionIntensity.allCases {
                    let instr = preset.instruction(for: intensity)
                        .trimmingCharacters(in: .whitespacesAndNewlines)
                    if instr.isEmpty { continue }
                    rows.append(DeliveryJSON(
                        id: "\(preset.id).\(intensity.rpcValue)",
                        preset: preset.id,
                        intensity: intensity.rpcValue,
                        label: preset.label,
                        instruction: instr))
                }
            }
        }

        if args.flag("json") { emitJSON(rows); return }
        for r in rows { print("\(r.id)\t\(r.instruction)") }
        note("ids are the `bench --delivery <id>` cells; measure adherence objectively with `vocello bench --delivery <ids>`")
    }

    static func printHelp() {
        print("""
        vocello deliveries — list built-in delivery presets (emotion x intensity) + instruction text

        Usage:
          vocello deliveries [--json]

        Each row is `<preset>.<intensity>` and the natural-language instruction the
        model receives. These ids are the `bench --delivery <id>` cells. Reference-free
        delivery adherence is measured objectively from the audio (F0 / rate / duration)
        by `vocello bench --delivery <ids>` and scripts/bench_delivery_prosody.py.

        Options:
          --json           emit JSON instead of a table
          --shipped-only   emit one row for each of the eight product presets,
                           including Neutral, at its shipped tier
        """)
    }
}
