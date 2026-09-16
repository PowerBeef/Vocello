import AppKit
import SwiftUI

/// The desktop script editor: an `NSTextView` bridge (the counterpart of the
/// iOS `IOSFlexibleTextEditor`) with a drawn placeholder, focus reporting
/// and the `ScriptTextState` echo guard against native/external edit races.
/// The identifier defaults to the composer's `textInput_textEditor`; the
/// batch sheet and the Voice Design brief pass their own.
struct MacScriptTextEditor: NSViewRepresentable {
    @Binding var text: String
    let placeholder: String
    let font: NSFont
    @Binding var isFocused: Bool
    /// Letter spacing, matched to the iOS composer's `-0.22` at 22 pt. Zero
    /// for the brief and batch editors, which use the system default.
    var tracking: CGFloat = 0
    var accessibilityIdentifier: String = "textInput_textEditor"
    var textColor: NSColor = MacTheme.textPrimaryNSColor
    var placeholderColor: NSColor = MacTheme.textTertiaryNSColor
    /// Height reported when the layout asks for the ideal size; callers bound
    /// the editor with `frame(minHeight:maxHeight:)` around it.
    var idealHeight: CGFloat = 120
    /// Laid-out height of the text plus the vertical insets, for a caller that
    /// sizes the editor to its content (the Studio composer). Written only
    /// when it moves by more than half a point, on the next run-loop turn, so
    /// measuring never re-enters the layout pass that asked for it.
    var contentHeight: Binding<CGFloat>? = nil

    static func typingAttributes(font: NSFont, color: NSColor, tracking: CGFloat) -> [NSAttributedString.Key: Any] {
        var attributes: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: color]
        if tracking != 0 { attributes[.kern] = tracking }
        return attributes
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(self, initialText: text)
    }

    func makeNSView(context: Context) -> NSScrollView {
        let scrollView = NSScrollView()
        let textView = PlaceholderTextView()

        textView.font = font
        textView.textColor = textColor
        textView.backgroundColor = .clear
        textView.drawsBackground = false
        textView.isRichText = false
        textView.allowsUndo = true
        textView.isAutomaticQuoteSubstitutionEnabled = false
        textView.isAutomaticDashSubstitutionEnabled = false
        textView.isAutomaticTextReplacementEnabled = false
        textView.textContainerInset = NSSize(width: 0, height: 8)
        textView.textContainer?.lineFragmentPadding = 0
        textView.typingAttributes = Self.typingAttributes(font: font, color: textColor, tracking: tracking)
        textView.delegate = context.coordinator
        textView.tracking = tracking
        textView.string = context.coordinator.textState.text
        textView.applyTracking()
        textView.placeholderString = placeholder
        textView.placeholderColor = placeholderColor
        textView.identifier = NSUserInterfaceItemIdentifier(accessibilityIdentifier)
        textView.setAccessibilityIdentifier(accessibilityIdentifier)
        textView.setAccessibilityEnabled(true)
        textView.onFocusChange = { focused in
            DispatchQueue.main.async { isFocused = focused }
        }
        // Width changes re-wrap the text; the text view reports its new frame
        // and the coordinator re-measures.
        textView.onWidthChange = { [weak coordinator = context.coordinator, weak textView] in
            guard let coordinator, let textView else { return }
            coordinator.reportContentHeight(of: textView)
        }
        context.coordinator.reportContentHeight(of: textView)

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

    /// The scroll view never reports its document's height: without this the
    /// vertically resizable text view's frame became the editor's size and a
    /// flexible composer inflated the whole window past its bounds.
    func sizeThatFits(_ proposal: ProposedViewSize, nsView: NSScrollView, context: Context) -> CGSize? {
        // An infinite proposal (a flexible frame asking for the ideal) must not
        // come back as an infinite size; it answers the ideal height instead.
        let width = proposal.width.flatMap { $0.isFinite ? $0 : nil } ?? 240
        let height = proposal.height.flatMap { $0.isFinite ? $0 : nil } ?? idealHeight
        return CGSize(width: width, height: height)
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        context.coordinator.parent = self
        guard let textView = scrollView.documentView as? PlaceholderTextView else { return }
        if textView.identifier?.rawValue != accessibilityIdentifier {
            textView.identifier = NSUserInterfaceItemIdentifier(accessibilityIdentifier)
            textView.setAccessibilityIdentifier(accessibilityIdentifier)
        }
        if textView.font != font || textView.tracking != tracking {
            textView.font = font
            textView.tracking = tracking
            textView.typingAttributes = Self.typingAttributes(font: font, color: textColor, tracking: tracking)
            textView.applyTracking()
        }
        if textView.placeholderString != placeholder {
            textView.placeholderString = placeholder
            textView.needsDisplay = true
        }
        if context.coordinator.textState.recordExternalEdit(text) {
            let selectedRanges = textView.selectedRanges
            textView.string = context.coordinator.textState.text
            textView.applyTracking()
            textView.selectedRanges = selectedRanges
            context.coordinator.reportContentHeight(of: textView)
        }
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: MacScriptTextEditor
        var textState: ScriptTextState
        private var lastReportedHeight: CGFloat = -1

        init(_ parent: MacScriptTextEditor, initialText: String) {
            self.parent = parent
            textState = ScriptTextState(initialText)
        }

        func textDidChange(_ notification: Notification) {
            guard let textView = notification.object as? NSTextView else { return }
            parent.text = textState.recordNativeEdit(textView.string)
            reportContentHeight(of: textView)
        }

        /// TextKit 2 first (`layoutManager` on a TextKit 2 view would drop it
        /// to the compatibility path and lose Writing Tools), TextKit 1 as
        /// the fallback. An empty document reports one line.
        func reportContentHeight(of textView: NSTextView) {
            guard let binding = parent.contentHeight else { return }
            let used: CGFloat
            if let layoutManager = textView.textLayoutManager {
                layoutManager.ensureLayout(for: layoutManager.documentRange)
                used = layoutManager.usageBoundsForTextContainer.height
            } else if let layoutManager = textView.layoutManager, let container = textView.textContainer {
                layoutManager.ensureLayout(for: container)
                used = layoutManager.usedRect(for: container).height
            } else {
                return
            }
            let lineHeight = textView.font.map { $0.ascender - $0.descender + $0.leading } ?? 0
            let height = ceil(max(used, lineHeight) + textView.textContainerInset.height * 2)
            guard abs(height - lastReportedHeight) > 0.5 else { return }
            lastReportedHeight = height
            DispatchQueue.main.async {
                if abs(binding.wrappedValue - height) > 0.5 {
                    binding.wrappedValue = height
                }
            }
        }
    }
}

final class PlaceholderTextView: NSTextView {
    var placeholderString: String = ""
    var placeholderColor: NSColor = MacTheme.textTertiaryNSColor
    var tracking: CGFloat = 0
    var onFocusChange: ((Bool) -> Void)?
    var onWidthChange: (() -> Void)?

    override func setFrameSize(_ newSize: NSSize) {
        let widthChanged = abs(newSize.width - frame.size.width) > 0.5
        super.setFrameSize(newSize)
        if widthChanged { onWidthChange?() }
    }

    /// `NSTextView` keeps typing attributes for what the user types next; text
    /// set programmatically carries the storage's own attributes, so the kern
    /// is applied to the whole string as well.
    func applyTracking() {
        guard let storage = textStorage else { return }
        let range = NSRange(location: 0, length: storage.length)
        guard range.length > 0 else { return }
        if tracking == 0 {
            storage.removeAttribute(.kern, range: range)
        } else {
            storage.addAttribute(.kern, value: tracking, range: range)
        }
    }

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
            var attrs: [NSAttributedString.Key: Any] = [
                .foregroundColor: placeholderColor,
                .font: font,
            ]
            if tracking != 0 { attrs[.kern] = tracking }
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
