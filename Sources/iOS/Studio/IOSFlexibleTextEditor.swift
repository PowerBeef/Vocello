import SwiftUI
import UIKit

/// Multi-line text editor that **actually** honors
/// `.frame(maxHeight: .infinity)` from a SwiftUI parent.
///
/// SwiftUI's stock `TextEditor` ignores its preferred-height instruction
/// from parents and reports an intrinsic size that doesn't compose with
/// `.layoutPriority(1)` cleanly — it claims the canvas's entire vertical
/// budget regardless of sibling layout priority, which is what blocked
/// the Studio composer's `flex: 1` design (audit item B.3, see
/// `/tmp/ui-audit-26-05-21/UI-AUDIT.md`). This wrapper bridges a
/// `UITextView` and overrides `intrinsicContentSize.height` to
/// `UIView.noIntrinsicMetric` so SwiftUI's preferred-size pipeline
/// drives the height end-to-end.
///
/// API mirrors what `IOSStudioCanvas.composerPad` previously read from
/// `TextEditor`: a `text` binding, an `font` + `textColor` pair, a
/// `tintColor` for the cursor, an `isFocused` binding for the
/// keyboard, and an optional `onChange(_:)` callback for character-cap
/// enforcement at the parent level.
struct IOSFlexibleTextEditor: UIViewRepresentable {
    @Binding var text: String
    var font: UIFont
    var textColor: UIColor
    var tintColor: UIColor
    var isFocused: Binding<Bool>?

    func makeUIView(context: Context) -> NoIntrinsicHeightTextView {
        let view = NoIntrinsicHeightTextView()
        view.accessibilityIdentifier = "textInput_textEditor"
        view.accessibilityLabel = "Script"
        view.accessibilityHint = "Enter or paste the text to generate."
        view.delegate = context.coordinator
        view.backgroundColor = .clear
        view.font = font
        view.adjustsFontForContentSizeCategory = true
        view.textColor = textColor
        view.tintColor = tintColor
        // Match SwiftUI TextEditor's default content insets so the
        // caret + first-line text align with the placeholder Text view
        // overlaid by the parent ZStack in IOSStudioCanvas.
        view.textContainerInset = UIEdgeInsets(top: 8, left: 0, bottom: 8, right: 0)
        view.textContainer.lineFragmentPadding = 0
        view.isScrollEnabled = true
        view.alwaysBounceVertical = false
        view.showsVerticalScrollIndicator = true
        view.autocorrectionType = .default
        view.autocapitalizationType = .sentences
        view.smartQuotesType = .yes
        view.smartDashesType = .yes
        // The Return key doubles as "Done": it's labelled accordingly and dismisses
        // the keyboard (handled in `shouldChangeTextIn` below) rather than inserting a
        // newline. Multi-line scripts still work via PASTE (the placeholder says "Type
        // or paste your script") — a pasted "\n" is part of a larger replacement and
        // isn't intercepted; only a lone Return keypress dismisses.
        view.returnKeyType = .done
        // No `inputAccessoryView` (a UIKit accessory bar docks at the screen bottom
        // when there's no on-screen keyboard). The dismiss affordances are the Return
        // ("Done") key above and the tap-outside window recognizer in the Coordinator;
        // both end-editing, which the `isFocused` binding mirrors.
        return view
    }

    func updateUIView(_ view: NoIntrinsicHeightTextView, context: Context) {
        if view.accessibilityIdentifier != "textInput_textEditor" {
            view.accessibilityIdentifier = "textInput_textEditor"
        }
        if view.accessibilityLabel != "Script" {
            view.accessibilityLabel = "Script"
        }
        if view.accessibilityHint != "Enter or paste the text to generate." {
            view.accessibilityHint = "Enter or paste the text to generate."
        }
        if view.text != text {
            view.text = text
        }
        if view.font != font {
            view.font = font
        }
        if view.textColor != textColor {
            view.textColor = textColor
        }
        if view.tintColor != tintColor {
            view.tintColor = tintColor
        }

        if let isFocused {
            // Reflect the SwiftUI focus binding into UIKit. Guard the
            // call so we don't fight UIKit's own focus events.
            if isFocused.wrappedValue, !view.isFirstResponder {
                DispatchQueue.main.async { view.becomeFirstResponder() }
            } else if !isFocused.wrappedValue, view.isFirstResponder {
                DispatchQueue.main.async { view.resignFirstResponder() }
            }
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    final class Coordinator: NSObject, UITextViewDelegate, UIGestureRecognizerDelegate {
        var parent: IOSFlexibleTextEditor
        private weak var managedTextView: UITextView?
        private weak var dismissTap: UITapGestureRecognizer?

        init(_ parent: IOSFlexibleTextEditor) {
            self.parent = parent
        }

        func textViewDidChange(_ textView: UITextView) {
            // Avoid a feedback loop if the binding update triggers
            // updateUIView with the same text.
            if parent.text != textView.text {
                parent.text = textView.text
            }
        }

        // Return ("Done") key dismisses instead of inserting a newline. A lone Return
        // arrives as replacement text "\n"; a multi-line PASTE arrives as a larger
        // string and is inserted normally, so pasted scripts keep their line breaks.
        func textView(
            _ textView: UITextView,
            shouldChangeTextIn range: NSRange,
            replacementText text: String
        ) -> Bool {
            if text == "\n" {
                textView.resignFirstResponder()
                return false
            }
            return true
        }

        func textViewDidBeginEditing(_ textView: UITextView) {
            parent.isFocused?.wrappedValue = true
            installDismissTap(for: textView)
        }

        func textViewDidEndEditing(_ textView: UITextView) {
            parent.isFocused?.wrappedValue = false
            removeDismissTap()
        }

        // MARK: - Tap-outside-to-dismiss
        //
        // The keyboard OVERLAYS the bottom controls, and the full-height composer
        // fills the visible area — so a SwiftUI background tap-catcher would have
        // almost no surface. Instead, while editing, a window-level tap recognizer
        // dismisses the keyboard when the user taps anywhere OUTSIDE the text view
        // (the mode header, around the composer, or a now-covered control). It
        // doesn't swallow those taps (`cancelsTouchesInView = false`), so tapping a
        // control still triggers it; taps inside the text view keep placing the
        // caret. The "Done" bar remains the primary, always-visible affordance.

        private func installDismissTap(for textView: UITextView) {
            guard dismissTap == nil, let window = textView.window else { return }
            let tap = UITapGestureRecognizer(target: self, action: #selector(handleDismissTap(_:)))
            tap.cancelsTouchesInView = false
            tap.delegate = self
            window.addGestureRecognizer(tap)
            dismissTap = tap
            managedTextView = textView
        }

        private func removeDismissTap() {
            if let tap = dismissTap {
                tap.view?.removeGestureRecognizer(tap)
            }
            dismissTap = nil
            managedTextView = nil
        }

        @objc private func handleDismissTap(_ recognizer: UITapGestureRecognizer) {
            guard let textView = managedTextView, textView.isFirstResponder else { return }
            let point = recognizer.location(in: textView)
            // Taps inside the editor keep editing (caret); only outside dismisses.
            if !textView.bounds.contains(point) {
                textView.resignFirstResponder()
            }
        }

        // Don't block any other gesture (buttons, scrolling, the text view's own taps).
        func gestureRecognizer(
            _ gestureRecognizer: UIGestureRecognizer,
            shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer
        ) -> Bool {
            true
        }
    }
}

/// UITextView subclass that opts out of supplying an intrinsic height
/// to Auto Layout, so SwiftUI's `.frame(maxHeight:)` (including
/// `.infinity`) drives the height. Width still uses Auto Layout's
/// usual content-hugging behavior.
final class NoIntrinsicHeightTextView: UITextView {
    override var intrinsicContentSize: CGSize {
        CGSize(width: UIView.noIntrinsicMetric, height: UIView.noIntrinsicMetric)
    }
}
