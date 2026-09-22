import AppKit
import QwenVoiceCore
import SwiftUI

/// The native Voice Design brief popover: a multi-line editor with the shared
/// starting points in a menu, the helper line and the character count,
/// clamped to `VoiceDesignBriefCatalog.descriptionLimit`. The field keeps
/// `voiceDesign_voiceDescriptionField` on the genuine editor after the chip opens it.
struct MacVoiceBriefEditor: View {
    @Binding var text: String
    let tint: Color
    let contentLanguage: Qwen3SupportedLanguage

    @State private var isEditorFocused = false

    private var isAtLimit: Bool {
        text.count >= VoiceDesignBriefCatalog.descriptionLimit
    }

    var body: some View {
        let shape = VocelloShape.input()

        VStack(alignment: .leading, spacing: MacTheme.Spacing.sm) {
            HStack(alignment: .firstTextBaseline) {
                Text(MacInterfaceText.designVoiceBriefLabel)
                    .macType(.eyebrow)
                    .textCase(.uppercase)
                    .foregroundStyle(MacTheme.Text.secondary)

                Spacer(minLength: MacTheme.Spacing.sm)

                startingPointsMenu
            }

            MacScriptTextEditor(
                text: $text,
                placeholder: VoiceDesignBriefCatalog.placeholder(in: contentLanguage),
                font: .systemFont(ofSize: MacType.style(.body).size, weight: .medium),
                isFocused: $isEditorFocused,
                accessibilityIdentifier: "voiceDesign_voiceDescriptionField",
                accessibilityLabel: MacInterfaceText.designVoiceBriefLabel,
                idealHeight: 160
            )
            .frame(height: 160)
            .padding(.horizontal, MacTheme.Spacing.sm)
            .padding(.vertical, MacTheme.Spacing.tight)
            .background { shape.fill(MacTheme.Surface.field) }
            .overlay {
                shape.stroke(
                    isEditorFocused ? tint.opacity(0.40) : MacTheme.Surface.fieldStroke,
                    lineWidth: VocelloTheme.Stroke.hairline
                )
            }
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
                    .macType(.caption)
                    .foregroundStyle(MacTheme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                Spacer(minLength: MacTheme.Spacing.sm)

                Text(verbatim: "\(text.count)/\(VoiceDesignBriefCatalog.descriptionLimit)")
                    .macType(.counter)
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
            ForEach(Array(VoiceDesignBriefCatalog.startingPoints(in: contentLanguage).enumerated()), id: \.offset) { index, starter in
                Button(starterItemLabel(for: starter)) {
                    text = starter
                }
                .accessibilityLabel(MacInterfaceText.briefStartingPointAccessibility(starter))
                .accessibilityIdentifier("voiceDesign_briefStarter_\(index)")
            }
        } label: {
            HStack(spacing: MacTheme.Spacing.tight) {
                Image(systemName: "sparkles")
                    .font(.system(size: MacControl.badge.glyph, weight: .semibold))
                Text(MacInterfaceText.briefStartingPoints)
                    .macType(.badge)
                    .lineLimit(1)
                Image(systemName: "chevron.down")
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundStyle(tint.opacity(0.7))
            }
            .foregroundStyle(MacTheme.Text.primary)
            .padding(.horizontal, MacTheme.Spacing.snug)
            .macControlHeight(.badge)
            .background { VocelloShape.pill().fill(tint.opacity(0.14)) }
            .overlay { VocelloShape.pill().stroke(tint.opacity(0.30), lineWidth: VocelloTheme.Stroke.hairline) }
            .contentShape(VocelloShape.pill())
            .accessibilityElement(children: .ignore)
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .menuIndicator(.hidden)
        .tint(tint)
        .accessibilityLabel(MacInterfaceText.briefStartingPoints)
        .accessibilityIdentifier("voiceDesign_briefStarters")
    }

    /// Bound menu width by characters, including scripts without word spaces.
    /// The full starter remains the accessibility label and inserted text.
    private func starterItemLabel(for starter: String) -> String {
        let prefix = String(starter.prefix(55))
        return prefix.count < starter.count ? prefix + "…" : prefix
    }
}
