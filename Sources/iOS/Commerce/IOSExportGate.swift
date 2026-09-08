import Observation
import SwiftUI
import UIKit

/// Owns a single, immutable export selection. Purchase completion does not
/// silently export anything: the user closes the sheet and requests export again.
@MainActor @Observable
final class IOSExportGate {
    struct Presentation: Identifiable {
        let id = UUID()
        let urls: [URL]? // nil presents the purchase sheet, not an activity sheet.
    }
    var presentation: Presentation?
    private var requestID = UUID()

    func share(urls: [URL], provenance: [IOSExportProvenance]) {
        guard !urls.isEmpty, urls.count == provenance.count else { return }
        perform(provenance: provenance) { [weak self] in
            self?.presentation = Presentation(urls: urls)
        }
    }

    func perform(provenance: [IOSExportProvenance], action: @escaping @MainActor () -> Void) {
        guard !provenance.isEmpty else { return }
        let id = UUID()
        requestID = id
        if IOSExportAccessPolicy.permits(provenance, unlocked: false) {
            action()
            return
        }
        Task { [weak self] in
            let store = IOSExportCommerce.shared
            await store.refresh()
            guard let self, self.requestID == id else { return }
            if store.permits(provenance) { action() }
            else { self.presentation = Presentation(urls: nil) }
        }
    }
}

extension View {
    func iosExportPresentation(_ gate: IOSExportGate) -> some View {
        modifier(IOSExportPresentationModifier(gate: gate))
    }
}

private struct IOSExportPresentationModifier: ViewModifier {
    @Bindable var gate: IOSExportGate
    func body(content: Content) -> some View {
        content.sheet(item: $gate.presentation) { presentation in
            if let urls = presentation.urls {
                IOSExportActivitySheet(urls: urls)
            } else {
                IOSExportPurchaseSheet()
            }
        }
    }
}

private struct IOSExportActivitySheet: UIViewControllerRepresentable {
    let urls: [URL]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: urls, applicationActivities: nil)
    }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}

struct IOSExportPurchaseSheet: View {
    private let store = IOSExportCommerce.shared
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text(VocelloPresentationText.exportUnlockDetail)
                        .fixedSize(horizontal: false, vertical: true)
                    if store.access == .unlocked {
                        Label(VocelloPresentationText.exportUnlocked, systemImage: "checkmark.seal")
                            .accessibilityIdentifier("exportPurchase_unlocked")
                        Text(VocelloPresentationText.exportRetryAfterPurchase)
                    } else if let product = store.product {
                        Button(VocelloPresentationText.exportBuy(product.displayPrice)) {
                            Task { await store.purchase() }
                        }
                        .buttonStyle(.borderedProminent)
                        .frame(minHeight: 44)
                        .disabled(store.operation != .idle || store.access == .checking)
                        .accessibilityIdentifier("exportPurchase_buy")
                    } else {
                        Text(VocelloPresentationText.exportProductUnavailable)
                        Button(VocelloPresentationText.exportReloadProduct) {
                            Task { await store.loadProduct() }
                        }
                        .frame(minHeight: 44)
                        .disabled(store.operation != .idle)
                        .accessibilityIdentifier("exportPurchase_reload")
                    }
                    if store.operation != .idle || store.access == .checking {
                        ProgressView(VocelloPresentationText.exportChecking)
                            .accessibilityIdentifier("exportPurchase_progress")
                    }
                    if let notice = store.notice {
                        Text(VocelloPresentationText.exportPurchaseNotice(notice))
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("exportPurchase_status")
                    }
                    Button(VocelloPresentationText.exportRestore) {
                        Task { await store.restore() }
                    }
                    .frame(minHeight: 44)
                    .disabled(store.operation != .idle)
                    .accessibilityIdentifier("exportPurchase_restore")
                    Link(VocelloPresentationText.exportPrivacy,
                         destination: URL(string: "https://vocello.vercel.app/privacy")!)
                        .frame(minHeight: 44)
                        .accessibilityIdentifier("exportPurchase_privacy")
                    Link(VocelloPresentationText.exportSupport,
                         destination: URL(string: "https://vocello.vercel.app/support/")!)
                        .frame(minHeight: 44)
                        .accessibilityIdentifier("exportPurchase_support")
                }
                .padding()
            }
            .navigationTitle(VocelloPresentationText.exportUnlockTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(VocelloPresentationText.exportClose) { dismiss() }
                        .accessibilityIdentifier("exportPurchase_close")
                }
            }
        }
        .task {
            await store.refresh()
            await store.loadProduct()
        }
    }
}
