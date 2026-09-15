import SwiftUI
import AppKit

struct TextInputView: View {
    @Binding var text: String

    var isGenerating: Bool
    var placeholder: String = MacInterfaceText.textInputPlaceholder
    var buttonColor: Color = AppTheme.customVoice
    var batchAction: (() -> Void)? = nil
    var batchDisabled: Bool = true
    var generateDisabled: Bool = false
    var isEmbedded: Bool = false
    var usesFlexibleEmbeddedHeight: Bool = false
    var onGenerate: () -> Void
    var onCancel: (() -> Void)? = nil
    /// DP-15 seed control: non-nil binding exposes the pin state. While a
    /// seed is pinned every take reproduces it; unpinning returns to a
    /// fresh seed per take. Pinning happens from a History row's
    /// "Pin seed" action; this chip is the visible state + the unpin.
    var pinnedSeed: Binding<UInt64?>? = nil

    @State private var isEditorFocused = false
    /// W1-E: scales the seed chip's fixed micro-glyph sizes with the
    /// system text-size setting (base ×1 keeps today's default rendering).
    @ScaledMetric(relativeTo: .caption) private var glyphScale: CGFloat = 1

    private var isTextEmptyForGeneration: Bool {
        text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        VStack(alignment: .leading, spacing: isEmbedded ? LayoutConstants.composerEmbeddedSpacing : 12) {
            editor
            actionRow
        }
        .frame(maxHeight: usesFlexibleEmbeddedHeight ? .infinity : nil, alignment: .topLeading)
        .background(shortcutBridge)
    }

    private var editor: some View {
        MacScriptTextEditor(
            text: $text,
            placeholder: placeholder,
            font: .systemFont(ofSize: NSFont.systemFontSize),
            isFocused: $isEditorFocused
        )
        .padding(isEmbedded ? LayoutConstants.composerEmbeddedEditorInset : 8)
        .frame(
            maxWidth: .infinity,
            minHeight: isEmbedded ? LayoutConstants.composerEmbeddedMinHeight : 160,
            maxHeight: usesFlexibleEmbeddedHeight && isEmbedded ? .infinity : LayoutConstants.textEditorMaxHeight,
            alignment: .topLeading
        )
        .glassTextField(
            radius: 10,
            strokeColor: isEditorFocused ? buttonColor.opacity(0.24) : AppTheme.fieldStroke
        )
        .frame(maxHeight: usesFlexibleEmbeddedHeight ? .infinity : nil, alignment: .topLeading)
    }

    private var actionRow: some View {
        HStack(alignment: .center, spacing: isEmbedded ? 10 : 12) {
            // Plain HStack, deliberately not a ControlGroup: on macOS 26 the
            // group collapses its children into one compact capsule and
            // silently discards prominence, tint, label, and width — the
            // Generate CTA shipped as an unlabeled icon sliver (2026-08-06
            // critique, P1-A).
            HStack(spacing: 8) {
                if let batchAction {
                    Button(MacInterfaceText.textInputBatch) {
                        batchAction()
                    }
                    .buttonStyle(.bordered)
                    .disabled(batchDisabled)
                    .accessibilityIdentifier("textInput_batchButton")
                }

                if isGenerating, let onCancel {
                    Button {
                        onCancel()
                    } label: {
                        Label(MacInterfaceText.cancel, systemImage: "stop.fill")
                            .frame(minWidth: 100)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.red)
                    .accessibilityIdentifier("textInput_cancelButton")
                } else {
                    Button {
                        onGenerate()
                    } label: {
                        Label(MacInterfaceText.textInputGenerate, systemImage: "waveform")
                            .frame(minWidth: 100)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(buttonColor)
                    .disabled(isTextEmptyForGeneration || isGenerating || generateDisabled)
                    .accessibilityIdentifier("textInput_generateButton")
                }
            }

            if let pinnedSeed, let seedValue = pinnedSeed.wrappedValue {
                seedPinChip(binding: pinnedSeed, seedValue: seedValue)
            }

            Spacer(minLength: 0)

            characterCount
        }
    }

    /// Compact pinned-seed indicator + unpin. Icon pairs with the label
    /// (no color-only signal); the seed value itself is the identity a
    /// user may want to note down or re-pin later from History.
    private func seedPinChip(binding: Binding<UInt64?>, seedValue: UInt64) -> some View {
        HStack(spacing: 5) {
            Image(systemName: "pin.fill")
                .font(.system(size: 9 * glyphScale))
                .foregroundStyle(buttonColor)
            Text(MacInterfaceText.textInputSeed(String(seedValue)))
                .font(.footnote.monospacedDigit())
                .foregroundStyle(.secondary)
                .lineLimit(1)
            Button {
                binding.wrappedValue = nil
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .font(.system(size: 11 * glyphScale))
                    .foregroundStyle(AppTheme.textMuted)
            }
            .buttonStyle(.plain)
            .help(MacInterfaceText.textInputUnpinHelp)
            .accessibilityLabel(MacInterfaceText.textInputUnpinSeed)
            .accessibilityIdentifier("textInput_seedUnpin")
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(Capsule().fill(buttonColor.opacity(0.10)))
        .help(MacInterfaceText.textInputSeedPinnedHelp(String(seedValue)))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("textInput_seedPinChip")
    }

    /// Pairs the character count with an icon when the script crosses
    /// the 500-char "long" threshold. Color-only signal (the prior
    /// orange-tint-on-overflow) violated WCAG 1.4.1; the icon +
    /// accessibility label give non-color-perceiving users the same
    /// information.
    private var characterCount: some View {
        let count = text.count
        let isLong = count > 500
        let baseLabel = MacInterfaceText.textInputCharacterCount(String(count))
        return HStack(spacing: 6) {
            if isLong {
                Image(systemName: "exclamationmark.circle.fill")
                    .font(.footnote)
                    .foregroundStyle(.orange)
                    .accessibilityHidden(true)
            }
            Text(baseLabel)
                .font(.footnote.monospacedDigit())
                .foregroundStyle(isLong ? .orange : .secondary)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(isLong ? "\(baseLabel), long script" : baseLabel)
        .accessibilityIdentifier("textInput_charCount")
    }

    private var shortcutBridge: some View {
        Button("", action: onGenerate)
            .keyboardShortcut(.return, modifiers: .command)
            .opacity(0.001)
            .disabled(isTextEmptyForGeneration || isGenerating || generateDisabled)
            .accessibilityHidden(true)
    }
}
