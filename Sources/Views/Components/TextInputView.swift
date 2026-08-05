import SwiftUI
import AppKit

struct TextInputView: View {
    @Binding var text: String

    var isGenerating: Bool
    var placeholder: String = "Type or paste your script"
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
        ScriptTextEditor(
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
            ControlGroup {
                if let batchAction {
                    Button("Batch") {
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
                        Label("Cancel", systemImage: "stop.fill")
                            .frame(minWidth: 100)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.red)
                    .accessibilityIdentifier("textInput_cancelButton")
                } else {
                    Button {
                        onGenerate()
                    } label: {
                        Label("Generate", systemImage: "waveform")
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
            Text("Seed \(String(seedValue))")
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
            .help("Unpin — new seed each take")
            .accessibilityLabel("Unpin seed")
            .accessibilityIdentifier("textInput_seedUnpin")
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(Capsule().fill(buttonColor.opacity(0.10)))
        .help("Takes reproduce pinned seed \(String(seedValue)) with identical settings")
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("textInput_seedPinChip")
    }

    /// Pairs the character count with an icon when the script crosses
    /// the 500-char "long" threshold. Color-only signal (the prior
    /// orange-tint-on-overflow) violated WCAG 1.4.1; the icon +
    /// accessibility label give non-color-perceiving users the same
    /// information.
    private var characterCount: some View {
        let isLong = text.count > 500
        let baseLabel = "\(text.count) characters"
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

// MARK: - Native NSTextView wrapper

struct ScriptTextEditor: NSViewRepresentable {
    @Binding var text: String
    let placeholder: String
    let font: NSFont
    @Binding var isFocused: Bool
    var accessibilityIdentifier: String = "textInput_textEditor"

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    func makeNSView(context: Context) -> NSScrollView {
        let scrollView = NSScrollView()
        let textView = PlaceholderTextView()

        textView.font = font
        textView.textColor = .labelColor
        textView.backgroundColor = .clear
        textView.drawsBackground = false
        textView.isRichText = false
        textView.allowsUndo = true
        textView.isAutomaticQuoteSubstitutionEnabled = false
        textView.isAutomaticDashSubstitutionEnabled = false
        textView.isAutomaticTextReplacementEnabled = false
        textView.textContainerInset = NSSize(width: 0, height: 4)
        textView.textContainer?.lineFragmentPadding = 4
        textView.delegate = context.coordinator
        textView.string = text
        textView.placeholderString = placeholder
        textView.identifier = NSUserInterfaceItemIdentifier(accessibilityIdentifier)
        textView.setAccessibilityIdentifier(accessibilityIdentifier)
        textView.setAccessibilityEnabled(true)
        textView.onFocusChange = { focused in
            DispatchQueue.main.async { isFocused = focused }
        }

        scrollView.hasVerticalScroller = true
        scrollView.scrollerStyle = .overlay
        scrollView.autohidesScrollers = true
        scrollView.drawsBackground = false
        scrollView.borderType = .noBorder
        scrollView.documentView = textView

        textView.minSize = NSSize(width: 0, height: 0)
        textView.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.autoresizingMask = [.width]
        textView.textContainer?.widthTracksTextView = true

        return scrollView
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        guard let textView = scrollView.documentView as? PlaceholderTextView else { return }
        if textView.identifier?.rawValue != accessibilityIdentifier {
            textView.identifier = NSUserInterfaceItemIdentifier(accessibilityIdentifier)
            textView.setAccessibilityIdentifier(accessibilityIdentifier)
        }
        if textView.string != text {
            let selectedRanges = textView.selectedRanges
            textView.string = text
            textView.selectedRanges = selectedRanges
        }
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: ScriptTextEditor

        init(_ parent: ScriptTextEditor) {
            self.parent = parent
        }

        func textDidChange(_ notification: Notification) {
            guard let textView = notification.object as? NSTextView else { return }
            parent.text = textView.string
        }
    }
}

final class PlaceholderTextView: NSTextView {
    var placeholderString: String = ""
    var onFocusChange: ((Bool) -> Void)?

    override var acceptsFirstResponder: Bool { true }

    override func becomeFirstResponder() -> Bool {
        let result = super.becomeFirstResponder()
        if result { onFocusChange?(true) }
        return result
    }

    override func resignFirstResponder() -> Bool {
        let result = super.resignFirstResponder()
        if result { onFocusChange?(false) }
        return result
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)

        if string.isEmpty, let font = self.font {
            let attrs: [NSAttributedString.Key: Any] = [
                .foregroundColor: AppTheme.textMutedNSColor,
                .font: font
            ]
            let inset = textContainerInset
            let padding = textContainer?.lineFragmentPadding ?? 0
            let rect = NSRect(
                x: inset.width + padding,
                y: inset.height,
                width: bounds.width - (inset.width + padding) * 2,
                height: bounds.height - inset.height * 2
            )
            placeholderString.draw(in: rect, withAttributes: attrs)
        }
    }
}
