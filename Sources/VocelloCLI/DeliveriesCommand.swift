import Foundation
import QwenVoiceCore
import VocelloCLICore

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
    struct DeliveryJSON: Encodable, Sendable {
        let id: String          // "<preset>.<intensity>"
        let preset: String
        let intensity: String
        let label: String
        let instruction: String
    }

    struct Rows: Encodable, Sendable {
        let deliveries: [DeliveryJSON]
    }

    @MainActor
    static func run(_ args: Args) async throws {
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

        if CLIPresenter.isMachine {
            CLIPresenter.succeed(Rows(deliveries: rows))
            return
        }
        for r in rows { print("\(r.id)\t\(r.instruction)") }
        note("ids are the `bench --delivery <id>` cells; measure adherence objectively with `vocello bench --delivery <ids>`")
    }
}
