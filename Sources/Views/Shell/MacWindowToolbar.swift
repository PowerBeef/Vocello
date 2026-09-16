import AppKit
import QwenVoiceCore
import SwiftUI

/// Window-toolbar controls of the current destination: History sort, clear
/// and search, and the Saved Voices enroll button. Desktop-only chrome the
/// iOS screens keep inline; the identifiers are the lane contract. The
/// controls observe `MacAppModel` themselves so a keystroke in the search
/// field re-renders the field and the History screen, never the shell.
struct MacWindowToolbar: ToolbarContent {
    let selectedItem: SidebarItem?

    var body: some ToolbarContent {
        // The toolbar is attached to the detail column and no title fills the
        // bar any more, so a flexible spacer keeps the controls at the trailing
        // edge of the column's section.
        ToolbarSpacer(.flexible, placement: .primaryAction)

        // One ToolbarItem (HStack): separate items pick up enough inter-item
        // padding that the search field overflows at the minimum window width
        // (regressing the smoke test's `history_searchField` assertion).
        if selectedItem == .history {
            ToolbarItem(placement: .primaryAction) {
                MacHistoryToolbarControls()
            }
        }

        if selectedItem == .voices {
            ToolbarItem(placement: .primaryAction) {
                MacVoicesToolbarControls()
            }
        }

        // The Studio screens carry no title row — the sidebar names the mode,
        // as the phone's capsule does — so the desktop's Speed/Quality switch
        // lives in the window chrome with the other per-destination controls.
        if let mode = selectedItem?.generationMode, let prefix = selectedItem?.accessibilityPrefix {
            ToolbarItem(placement: .primaryAction) {
                MacStudioToolbarControls(mode: mode, accessibilityPrefix: prefix)
            }
        }
    }
}

private struct MacStudioToolbarControls: View {
    @Environment(MacAppModel.self) private var appModel

    let mode: GenerationMode
    let accessibilityPrefix: String

    var body: some View {
        MacGenerationVariantSelector(
            mode: mode,
            tint: MacTheme.tint(for: mode),
            accessibilityPrefix: accessibilityPrefix,
            isDisabled: appModel.coordinator(for: mode).isGenerating,
            showsLabel: false
        )
    }
}

private struct MacHistoryToolbarControls: View {
    @Environment(MacAppModel.self) private var appModel

    var body: some View {
        @Bindable var appModel = appModel
        HStack(spacing: 10) {
            Menu {
                Picker(MacInterfaceText.historySortPicker, selection: $appModel.historySortOrder) {
                    ForEach(HistorySortOrder.allCases) { order in
                        Text(order.label).tag(order)
                    }
                }
            } label: {
                Image(systemName: "arrow.up.arrow.down.circle")
            }
            .accessibilityLabel(MacInterfaceText.historySortAccessibility)
            .accessibilityIdentifier("history_sortPicker")

            Menu {
                Button(MacInterfaceText.historyClearKeepFiles) {
                    appModel.historyClearRequest = HistoryClearRequest(scope: .keepFiles)
                }
                .accessibilityIdentifier("history_clearKeepFiles")
                Button(MacInterfaceText.historyClearDeleteFiles, role: .destructive) {
                    appModel.historyClearRequest = HistoryClearRequest(scope: .deleteFiles)
                }
                .accessibilityIdentifier("history_clearDeleteFiles")
            } label: {
                Image(systemName: "trash.circle")
            }
            .accessibilityLabel(MacInterfaceText.historyClearAccessibility)
            .accessibilityIdentifier("history_clearMenu")

            MacToolbarSearchField(
                text: $appModel.historySearchText,
                placeholder: MacInterfaceText.sidebarSearchHistory,
                accessibilityIdentifier: "history_searchField"
            )
            // Fixed width on purpose: flexible or generous frames push the
            // trailing toolbar group into the overflow chevron at compact
            // window widths (smoke-verified 2026-08-06). 170 is just enough
            // to unclip the placeholder.
            .frame(width: 170)
        }
    }
}

private struct MacVoicesToolbarControls: View {
    @Environment(MacAppModel.self) private var appModel

    var body: some View {
        Button(MacInterfaceText.voicesAddVoiceSampleAction) {
            appModel.voicesEnrollRequestID = UUID()
        }
        .buttonStyle(.borderedProminent)
        .tint(MacTheme.accent)
        .accessibilityIdentifier("voices_enrollButton")
    }
}

private struct MacToolbarSearchField: NSViewRepresentable {
    @Binding var text: String
    let placeholder: String
    let accessibilityIdentifier: String

    func makeCoordinator() -> Coordinator {
        Coordinator(text: $text)
    }

    func makeNSView(context: Context) -> NSSearchField {
        let field = NSSearchField(frame: .zero)
        field.target = context.coordinator
        field.action = #selector(Coordinator.didActivateSearch(_:))
        field.delegate = context.coordinator
        field.sendsSearchStringImmediately = true
        field.sendsWholeSearchString = false
        configure(field)
        return field
    }

    func updateNSView(_ nsView: NSSearchField, context: Context) {
        context.coordinator.text = $text
        if nsView.stringValue != text {
            nsView.stringValue = text
        }
        configure(nsView)
    }

    private func configure(_ field: NSSearchField) {
        field.placeholderString = placeholder
        field.identifier = NSUserInterfaceItemIdentifier(accessibilityIdentifier)
        field.setAccessibilityIdentifier(accessibilityIdentifier)
        field.setAccessibilityLabel(placeholder)
    }

    @MainActor final class Coordinator: NSObject, NSSearchFieldDelegate {
        var text: Binding<String>

        init(text: Binding<String>) {
            self.text = text
        }

        @objc
        func didActivateSearch(_ sender: NSSearchField) {
            text.wrappedValue = sender.stringValue
        }

        func controlTextDidChange(_ notification: Notification) {
            guard let field = notification.object as? NSSearchField else { return }
            text.wrappedValue = field.stringValue
        }
    }
}
