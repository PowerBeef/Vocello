import SwiftUI
import AppKit

/// Multi-line Voice Design brief editor — the macOS counterpart of the iOS
/// `IOSVoiceDesignBriefSheet`, inline instead of a sheet: a ~3–4 line
/// `TextEditor` with a live character counter (clamped to
/// `VoiceDesignBriefCatalog.descriptionLimit`) and a compact "Starting
/// points" menu in the caption row, drawn from the shared catalog. (The
/// starters were previously a 4-row chip grid that inflated the Voice Design
/// panel past the viewport at the default window size; the menu keeps the
/// mode's layout in line with Custom Voice / Voice Cloning and the card
/// height stable between empty and typed states.)
struct VoiceBriefEditor: View {
    @Binding var text: String
    var accentColor: Color = AppTheme.voiceDesign
    var accessibilityIdentifier: String = "voiceDesign_voiceDescriptionField"
    @State private var isEditorFocused = false

    private var trimmedIsEmpty: Bool {
        text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var isAtLimit: Bool {
        text.count >= VoiceDesignBriefCatalog.descriptionLimit
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ZStack(alignment: .topLeading) {
                ScriptTextEditor(
                    text: $text,
                    placeholder: "",
                    font: .systemFont(ofSize: NSFont.systemFontSize),
                    isFocused: $isEditorFocused,
                    accessibilityIdentifier: accessibilityIdentifier
                )
                    // min 52 (~2 body lines + insets; the editor scrolls
                    // internally beyond maxHeight) keeps the whole Voice
                    // Design panel scroll-free at the default 720×560
                    // window — the old 72/120 frame overflowed the viewport
                    // and forced a canvas scrollbar.
                    .frame(minHeight: 52, maxHeight: 80)
                    .padding(.horizontal, 4)
                    .padding(.vertical, 2)

                if trimmedIsEmpty {
                    Text(VoiceDesignBriefCatalog.placeholder)
                        .font(.body)
                        .foregroundStyle(AppTheme.textMuted)
                        .padding(.horizontal, 9)
                        .padding(.vertical, 10)
                        .allowsHitTesting(false)
                }
            }
            .padding(.horizontal, 4)
            .glassTextField(radius: 10)
            .onChange(of: text) { _, newValue in
                // UX bound only — no model cap exists for the open-weights
                // VoiceDesign model (see VoiceDesignBriefCatalog).
                let limit = VoiceDesignBriefCatalog.descriptionLimit
                if newValue.count > limit {
                    text = String(newValue.prefix(limit))
                }
            }

            HStack(alignment: .firstTextBaseline) {
                Text("Combine character, age, accent, and texture.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Spacer(minLength: 8)

                startingPointsMenu

                Text("\(text.count)/\(VoiceDesignBriefCatalog.descriptionLimit)")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(isAtLimit ? accentColor : Color.secondary)
                    .accessibilityIdentifier("voiceDesign_briefCharCount")
            }
        }
    }

    /// Compact starters menu (always enabled — selecting replaces the brief,
    /// so starters can be swapped after typing too). Items show a readable
    /// head of each sentence; the full starter lands in the editor where it
    /// can be read and edited.
    private var startingPointsMenu: some View {
        Menu {
            ForEach(Array(VoiceDesignBriefCatalog.startingPoints.enumerated()), id: \.offset) { index, starter in
                Button(starterItemLabel(for: starter)) {
                    text = starter
                }
                .accessibilityLabel("Starting point: \(starter)")
                .accessibilityIdentifier("voiceDesign_briefStarter_\(index)")
            }
        } label: {
            // Single concatenated Text so the bordered button style cannot
            // reorder a decomposable label (same pattern as QwenLanguagePicker).
            (Text("Starting points  ")
                + Text(Image(systemName: "chevron.up.chevron.down"))
                    .font(.caption2.weight(.semibold))
                    .foregroundColor(.secondary))
                .font(.caption)
                .lineLimit(1)
        }
        .menuStyle(.button)
        .buttonStyle(.bordered)
        .menuIndicator(.hidden)
        .controlSize(.small)
        .tint(accentColor)
        .accessibilityIdentifier("voiceDesign_briefStarters")
    }

    /// Menu items show the first words of each starter; the full sentence
    /// would run the menu several hundred points wide.
    private func starterItemLabel(for starter: String) -> String {
        let words = starter.split(separator: " ").prefix(8)
        return words.joined(separator: " ") + "…"
    }
}
