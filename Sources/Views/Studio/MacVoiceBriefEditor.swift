import AppKit
import SwiftUI

/// The Voice Design brief, inline on the desktop (the iOS brief sheet's
/// content without the sheet): a short multi-line editor with the shared
/// starting points in a menu, the helper line and the character count,
/// clamped to `VoiceDesignBriefCatalog.descriptionLimit`. The field keeps
/// `voiceDesign_voiceDescriptionField`, which the benchmark types into
/// directly, so it never hides behind a sheet.
struct MacVoiceBriefEditor: View {
    @Binding var text: String
    let tint: Color

    @State private var isEditorFocused = false

    private var isAtLimit: Bool {
        text.count >= VoiceDesignBriefCatalog.descriptionLimit
    }

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: MacTheme.Radius.input, style: .continuous)

        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(MacInterfaceText.designVoiceBriefLabel)
                    .font(.system(size: 11, weight: .semibold))
                    .tracking(0.88)
                    .textCase(.uppercase)
                    .foregroundStyle(MacTheme.Text.secondary)

                Spacer(minLength: 8)

                startingPointsMenu
            }

            MacScriptTextEditor(
                text: $text,
                placeholder: VoiceDesignBriefCatalog.placeholder,
                font: .systemFont(ofSize: 14, weight: .medium),
                isFocused: $isEditorFocused,
                accessibilityIdentifier: "voiceDesign_voiceDescriptionField",
                idealHeight: 60
            )
            .frame(minHeight: 52, maxHeight: 72)
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background { shape.fill(MacTheme.Surface.field) }
            .overlay { shape.stroke(isEditorFocused ? tint.opacity(0.40) : MacTheme.Surface.fieldStroke, lineWidth: 0.5) }
            .onChange(of: text) { _, newValue in
                // UX bound only: no model cap exists for the open-weights
                // VoiceDesign model (see VoiceDesignBriefCatalog).
                let limit = VoiceDesignBriefCatalog.descriptionLimit
                if newValue.count > limit {
                    text = String(newValue.prefix(limit))
                }
            }

            HStack(alignment: .firstTextBaseline) {
                Text(MacInterfaceText.briefHelper)
                    .font(.caption)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .lineLimit(1)

                Spacer(minLength: 8)

                Text(verbatim: "\(text.count)/\(VoiceDesignBriefCatalog.descriptionLimit)")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(isAtLimit ? tint : MacTheme.Text.secondary)
                    .accessibilityIdentifier("voiceDesign_briefCharCount")
            }
        }
    }

    /// Starters menu (always enabled: selecting replaces the brief, so a
    /// starter can be swapped after typing too). Items show the head of each
    /// sentence; the full starter lands in the editor.
    private var startingPointsMenu: some View {
        Menu {
            ForEach(Array(VoiceDesignBriefCatalog.startingPoints.enumerated()), id: \.offset) { index, starter in
                Button(starterItemLabel(for: starter)) {
                    text = starter
                }
                .accessibilityLabel(MacInterfaceText.briefStartingPointAccessibility(starter))
                .accessibilityIdentifier("voiceDesign_briefStarter_\(index)")
            }
        } label: {
            HStack(spacing: 5) {
                Image(systemName: "sparkles")
                    .font(.system(size: 10, weight: .semibold))
                Text(MacInterfaceText.briefStartingPoints)
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
                Image(systemName: "chevron.down")
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundStyle(tint.opacity(0.7))
            }
            .foregroundStyle(MacTheme.Text.primary)
            .padding(.horizontal, 10)
            .frame(height: 24)
            .background { Capsule(style: .continuous).fill(tint.opacity(0.14)) }
            .overlay { Capsule(style: .continuous).stroke(tint.opacity(0.30), lineWidth: 0.5) }
            .contentShape(Capsule(style: .continuous))
            .accessibilityElement(children: .ignore)
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .menuIndicator(.hidden)
        .tint(tint)
        .accessibilityLabel(MacInterfaceText.briefStartingPoints)
        .accessibilityIdentifier("voiceDesign_briefStarters")
    }

    /// Menu items show the first words of each starter; the full sentence
    /// would run the menu several hundred points wide.
    private func starterItemLabel(for starter: String) -> String {
        let words = starter.split(separator: " ").prefix(8)
        return words.joined(separator: " ") + "…"
    }
}
