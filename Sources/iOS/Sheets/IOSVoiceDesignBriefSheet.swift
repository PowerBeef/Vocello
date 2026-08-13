import SwiftUI
import UIKit

/// Bottom sheet that lets the user edit the Voice Design brief, replacing
/// the legacy inline `IOSVoiceDesignSetupCard` editor. Multi-line text
/// editor + reference starter rows. Caller binds to the brief string;
/// tapping a starter fills it and dismisses the sheet.
///
/// Per design_references/Vocello iOS/sheets.jsx (DesignBriefSheet pattern).
struct IOSVoiceDesignBriefSheet: View {
    @Binding var voiceDescription: String
    let tint: Color
    var presentation: IOSBottomSheetPresentationStyle = .system
    var onDismiss: (() -> Void)?

    @Environment(\.dismiss) private var dismiss
    // Plain @State (not @FocusState): the brief uses a UITextView wrapper (IOSBriefTextEditor)
    // that bridges focus through this Bool via its begin/end-editing delegate.
    @State private var isFocused = false

    // Research-aligned starter briefs, sourced from the shared catalog so the iOS sheet and
    // the macOS inline editor stay in lockstep.
    private let startingPoints = VoiceDesignBriefCatalog.startingPoints

    private var isBriefEmpty: Bool {
        voiceDescription.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        IOSBottomSheetSurface(
            title: "Voice brief",
            tint: tint,
            presentation: presentation,
            onDismiss: onDismiss,
            headerTrailing: {
                Button {
                    isFocused = false
                    closeSheet()
                } label: {
                    Text("Confirm")
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(IOSAppTheme.textPrimary)
                        .padding(.horizontal, 18)
                        .frame(height: 40)
                        .background {
                            Capsule(style: .continuous)
                                .fill(tint.opacity(0.18))
                        }
                        .overlay {
                            Capsule(style: .continuous)
                                .stroke(tint.opacity(0.35), lineWidth: 0.8)
                        }
                }
                .buttonStyle(.plain)
                .disabled(isBriefEmpty)
                .opacity(isBriefEmpty ? 0.5 : 1.0)
                .accessibilityIdentifier("voiceBrief_confirm")
            }
        ) {
            VStack(alignment: .leading, spacing: 0) {
                Text("Describe the voice. Combine character, age, accent, and texture.")
                    .iosScaledFont(size: 14, weight: .regular, relativeTo: .footnote)
                    .lineSpacing(1)
                    .foregroundStyle(IOSAppTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 20)
                    .padding(.bottom, 16)

                ZStack(alignment: .topLeading) {
                    IOSBriefTextEditor(
                        text: $voiceDescription,
                        isFocused: $isFocused,
                        tintColor: UIColor(tint)
                    )

                    if voiceDescription.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        Text("A warm, deep narrator with a subtle British accent.")
                            .font(.system(size: 16, weight: .medium))
                            .foregroundStyle(IOSAppTheme.textTertiary)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 18)
                            .allowsHitTesting(false)
                    }
                }
                // ~7 lines tall — proportionate to the 500-char brief without dominating the
                // sheet; the TextEditor scrolls when the description runs longer.
                .frame(height: 160)
                .background {
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(Color.white.opacity(0.04))
                }
                .overlay {
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .stroke(isFocused ? tint.opacity(0.40) : tint.opacity(0.22), lineWidth: 0.5)
                }
                .padding(.horizontal, 20)
                .onChange(of: voiceDescription) { _, newValue in
                    // Clamp the voice DESCRIPTION to its own limit (decoupled from the
                    // spoken-script limit). No model cap exists for the open-weights VoiceDesign
                    // model; this is a UX bound that keeps briefs concise.
                    let limit = IOSGenerationTextLimitPolicy.descriptionLimit
                    if newValue.count > limit {
                        voiceDescription = String(newValue.prefix(limit))
                    }
                }

                HStack {
                    Spacer(minLength: 0)
                    Text("\(voiceDescription.count)/\(IOSGenerationTextLimitPolicy.descriptionLimit)")
                        .iosScaledFont(size: 12, weight: .medium, monospacedDigit: true, relativeTo: .caption)
                        .foregroundStyle(
                            voiceDescription.count >= IOSGenerationTextLimitPolicy.descriptionLimit
                                ? tint
                                : IOSAppTheme.textTertiary
                        )
                        .accessibilityIdentifier("voiceBrief_charCount")
                }
                .padding(.horizontal, 20)
                .padding(.top, 6)
                .padding(.bottom, 18)

                Text("Starting points".uppercased())
                    .iosScaledFont(size: 11, weight: .semibold, relativeTo: .caption2)
                    .tracking(0.88)
                    .foregroundStyle(IOSAppTheme.textSecondary)
                    .padding(.horizontal, 20)
                    .padding(.bottom, 10)

                VStack(spacing: 8) {
                    ForEach(Array(startingPoints.enumerated()), id: \.element) { index, startingPoint in
                        Button {
                            voiceDescription = startingPoint
                            IOSHaptics.selection()
                            closeSheet()
                        } label: {
                            Text(startingPoint)
                                .iosScaledFont(size: 14, weight: .regular, relativeTo: .footnote)
                                .lineSpacing(1)
                                .foregroundStyle(IOSAppTheme.textPrimary)
                                .lineLimit(2)
                                .multilineTextAlignment(.leading)
                                .fixedSize(horizontal: false, vertical: true)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.horizontal, 14)
                                .padding(.vertical, 12)
                                .background {
                                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                                        .fill(Color.white.opacity(0.03))
                                }
                                .overlay {
                                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                                        .stroke(Color.white.opacity(0.08), lineWidth: 0.5)
                                }
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("voiceBrief_starter_\(index)")
                    }
                }
                .padding(.horizontal, 20)
            }
            .padding(.bottom, 24)
        }
    }

    private func closeSheet() {
        onDismiss?()
        dismiss()
    }
}

/// Multi-line brief editor backed by a `UITextView` with **scroll bounce disabled** — SwiftUI's
/// `TextEditor` rubber-bands at the top/bottom (and `.scrollBounceBehavior(.basedOnSize)` only
/// suppresses it while the text fits). `bounces = false` removes the elastic overscroll entirely
/// while still scrolling once the brief overflows the box. Focus is bridged to a `Bool` binding
/// (drives the box's focus stroke); `Return` inserts a newline as in the stock editor.
private struct IOSBriefTextEditor: UIViewRepresentable {
    @Binding var text: String
    var isFocused: Binding<Bool>
    var tintColor: UIColor

    func makeUIView(context: Context) -> UITextView {
        let view = UITextView()
        view.delegate = context.coordinator
        view.accessibilityIdentifier = "voiceBrief_editor"
        view.backgroundColor = .clear
        view.font = .systemFont(ofSize: 16, weight: .medium)
        view.textColor = IOSAppTheme.textPrimaryUIColor
        view.tintColor = tintColor
        view.isScrollEnabled = true
        view.bounces = false               // no rubber-band, even when the brief overflows
        view.alwaysBounceVertical = false
        view.showsVerticalScrollIndicator = true
        // Aligns the caret/first line with the placeholder Text overlaid by the parent ZStack
        // (which uses 16pt horizontal / 18pt vertical padding).
        view.textContainerInset = UIEdgeInsets(top: 18, left: 16, bottom: 12, right: 16)
        view.textContainer.lineFragmentPadding = 0
        view.autocapitalizationType = .sentences
        view.autocorrectionType = .default
        view.smartQuotesType = .yes
        view.smartDashesType = .yes
        return view
    }

    func updateUIView(_ view: UITextView, context: Context) {
        if view.text != text { view.text = text }
        if view.tintColor != tintColor { view.tintColor = tintColor }
        if isFocused.wrappedValue, !view.isFirstResponder {
            DispatchQueue.main.async { view.becomeFirstResponder() }
        } else if !isFocused.wrappedValue, view.isFirstResponder {
            DispatchQueue.main.async { view.resignFirstResponder() }
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject, UITextViewDelegate {
        var parent: IOSBriefTextEditor
        init(_ parent: IOSBriefTextEditor) { self.parent = parent }

        func textViewDidChange(_ textView: UITextView) {
            if parent.text != textView.text { parent.text = textView.text }
        }
        func textViewDidBeginEditing(_ textView: UITextView) { parent.isFocused.wrappedValue = true }
        func textViewDidEndEditing(_ textView: UITextView) { parent.isFocused.wrappedValue = false }
    }
}
