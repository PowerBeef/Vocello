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
    /// Spoken name of the editor. Nil uses the placeholder, which is the only
    /// visible description of an empty editor; an explicit label moves the
    /// placeholder to the accessibility placeholder value instead.
    var accessibilityLabel: String? = nil
    var textColor: NSColor = MacTheme.textPrimaryNSColor
    var placeholderColor: NSColor = MacTheme.textTertiaryNSColor
    /// Height reported when the layout asks for the ideal size; callers bound
    /// the editor with `frame(minHeight:maxHeight:)` around it.
    var idealHeight: CGFloat = 120
    /// Bumped by a Clear control: the editor empties itself as an ordinary,
    /// undoable edit, so Edit > Undo (⌘Z) brings the script back (MAC-24).
    var clearRequest: Int = 0
    /// Names a Clear in the Edit menu ("Undo Clear", "Redo Clear"): the whole
    /// titles come from the catalog in the interface language.
    var clearUndoTitles: MacUndoActionTitles? = nil

    static func typingAttributes(font: NSFont, color: NSColor, tracking: CGFloat) -> [NSAttributedString.Key: Any] {
        var attributes: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: color]
        if tracking != 0 { attributes[.kern] = tracking }
        return attributes
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(self, initialText: text, clearRequest: clearRequest)
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
        applyAccessibilityDescription(to: textView)
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
        applyAccessibilityDescription(to: textView)
        context.coordinator.applyUndoTitles()
        if context.coordinator.appliedClearRequest != clearRequest {
            context.coordinator.appliedClearRequest = clearRequest
            // After this update: the edit reports back through the delegate,
            // which writes the binding, and a view update must not.
            let actionName = clearUndoTitles?.actionName
            Task { @MainActor in
                textView.clearAsUndoableEdit(actionName: actionName)
            }
        }
        if context.coordinator.textState.recordExternalEdit(text) {
            let selectedRanges = textView.selectedRanges
            textView.string = context.coordinator.textState.text
            textView.applyTracking()
            textView.selectedRanges = selectedRanges
        }
    }

    private func applyAccessibilityDescription(to textView: NSTextView) {
        let label = accessibilityLabel ?? placeholder
        if textView.accessibilityLabel() != label {
            textView.setAccessibilityLabel(label)
        }
        let placeholderValue = accessibilityLabel == nil ? nil : placeholder
        if textView.accessibilityPlaceholderValue() != placeholderValue {
            textView.setAccessibilityPlaceholderValue(placeholderValue)
        }
    }

    @MainActor
    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: MacScriptTextEditor
        var textState: ScriptTextState
        var appliedClearRequest: Int
        /// The editor's own undo stack, used when it names a Clear (MAC-24).
        let scriptUndoManager: MacScriptUndoManager

        init(_ parent: MacScriptTextEditor, initialText: String, clearRequest: Int) {
            self.parent = parent
            textState = ScriptTextState(initialText)
            appliedClearRequest = clearRequest
            scriptUndoManager = MacScriptUndoManager()
            super.init()
            applyUndoTitles()
        }

        func applyUndoTitles() {
            let titles = parent.clearUndoTitles.map { [$0] } ?? []
            if scriptUndoManager.namedActions != titles {
                scriptUndoManager.namedActions = titles
            }
        }

        func textDidChange(_ notification: Notification) {
            guard let textView = notification.object as? NSTextView else { return }
            parent.text = textState.recordNativeEdit(textView.string)
        }

        /// An editor that names a Clear keeps its own undo stack, so the Edit
        /// menu titles that action in the interface language. Any other editor
        /// answers what the text view would without a delegate: the responder
        /// chain's undo manager (the window's).
        func undoManager(for view: NSTextView) -> UndoManager? {
            parent.clearUndoTitles == nil ? view.nextResponder?.undoManager : scriptUndoManager
        }
    }
}

/// An undoable action's Edit-menu names in the interface language (MAC-24).
struct MacUndoActionTitles: Equatable {
    /// The name the edit registers (`UndoManager.setActionName`).
    let actionName: String
    /// The whole Undo menu title, such as "Undo Clear".
    let undoMenuTitle: String
    /// The whole Redo menu title, such as "Redo Clear".
    let redoMenuTitle: String
}

/// The script editor's undo manager (MAC-24). AppKit builds "Undo <action>"
/// in the system language, so an action named from the interface-language
/// catalog would read half translated; the actions this manager names take
/// their whole titles from the catalog, and every other action (typing, paste)
/// keeps AppKit's.
final class MacScriptUndoManager: UndoManager {
    var namedActions: [MacUndoActionTitles] = []

    override func undoMenuTitle(forUndoActionName actionName: String) -> String {
        namedActions.first { $0.actionName == actionName }?.undoMenuTitle
            ?? super.undoMenuTitle(forUndoActionName: actionName)
    }

    override func redoMenuTitle(forUndoActionName actionName: String) -> String {
        namedActions.first { $0.actionName == actionName }?.redoMenuTitle
            ?? super.redoMenuTitle(forUndoActionName: actionName)
    }
}

final class PlaceholderTextView: NSTextView {
    var placeholderString: String = ""
    var placeholderColor: NSColor = MacTheme.textTertiaryNSColor
    var tracking: CGFloat = 0
    var onFocusChange: ((Bool) -> Void)?

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

    /// Empties the text through the text system, which records the undo
    /// (`allowsUndo`), then keeps the caret in the editor so ⌘Z reaches it.
    /// `didChangeText()` reports the edit to the delegate like typing does.
    func clearAsUndoableEdit(actionName: String?) {
        let range = NSRange(location: 0, length: (string as NSString).length)
        guard range.length > 0, shouldChangeText(in: range, replacementString: "") else { return }
        replaceCharacters(in: range, with: "")
        didChangeText()
        if let actionName {
            undoManager?.setActionName(actionName)
        }
        window?.makeFirstResponder(self)
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
