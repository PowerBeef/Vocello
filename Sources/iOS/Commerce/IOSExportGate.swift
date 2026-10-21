import Foundation
import Observation
// The gate's decision logic is Foundation-only so the macOS logic-test bundle
// compiles and runs it (PA-19); the presentation below is iPhone UI.
#if canImport(UIKit)
import SwiftUI
import UIKit
#endif

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
    private let commerce: @MainActor () -> IOSExportPurchaseState

    /// `commerce` is a test seam (PA-19); the app always consults the one
    /// StoreKit owner, `IOSExportCommerce.shared`.
    init(commerce: @escaping @MainActor () -> IOSExportPurchaseState = { IOSExportCommerce.shared }) {
        self.commerce = commerce
    }

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
        let commerce = self.commerce
        Task { [weak self] in
            let store = commerce()
            await store.refresh()
            guard let self, self.requestID == id else { return }
            if store.permits(provenance) { action() }
            else { self.presentation = Presentation(urls: nil) }
        }
    }
}

#if canImport(UIKit)
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

/// The export unlock. It speaks onboarding's welcome language (the warm mode
/// backdrop, a gradient hero tile, a large title, benefit rows and the shared
/// glass CTA), so the app's one purchase looks like the rest of the app. The
/// actions pin to the bottom; at accessibility text sizes they scroll with the
/// content instead of covering it.
struct IOSExportPurchaseSheet: View {
    private let store = IOSExportCommerce.shared
    @Environment(\.dismiss) private var dismiss
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private static let privacyURL = URL(string: "https://vocello.vercel.app/privacy")!
    private static let supportURL = URL(string: "https://vocello.vercel.app/support/")!

    private var text: VocelloPresentationText { IOSAppLanguage.shared.presentation }
    private var isBusy: Bool { store.operation != .idle || store.access == .checking }
    private var pinsActions: Bool { !dynamicTypeSize.isAccessibilitySize }

    var body: some View {
        ZStack {
            IOSModeBackdrop(tint: Theme.Brand.gold, intensity: .warm)

            VStack(spacing: 0) {
                topBar
                IOSScrollView(bottomFadeHeight: Theme.Spacing.xxl) {
                    VStack(spacing: 0) {
                        hero
                        benefits
                            .padding(.top, Theme.Spacing.xxxl)
                        if !pinsActions {
                            actions
                                .padding(.top, Theme.Spacing.xxxl)
                        }
                        footer
                            .padding(.top, Theme.Spacing.xxxl)
                    }
                    .padding(.horizontal, Theme.Spacing.xxl)
                    .padding(.bottom, Theme.Spacing.xxl)
                }
                if pinsActions {
                    actions
                        .padding(.horizontal, Theme.Spacing.xxl)
                        .padding(.top, Theme.Spacing.md)
                        .padding(.bottom, Theme.Spacing.sm)
                }
            }
        }
        .preferredColorScheme(.dark)
        .presentationCornerRadius(28)
        .iosAppAnimation(Theme.Motion.easeOut, value: store.access)
        .iosAppAnimation(Theme.Motion.stateChange, value: store.notice)
        .iosAppAnimation(Theme.Motion.stateChange, value: isBusy)
        .task {
            await store.refresh()
            await store.loadProduct()
        }
        // A12-04: a purchase or restore outcome appears below the buttons,
        // away from VoiceOver focus; say it once when it changes.
        .onChange(of: store.notice) { _, notice in
            guard let notice else { return }
            StudioGenerationAnnouncer.post(
                IOSAppLanguage.shared.presentation.exportPurchaseNotice(notice, access: store.access)
            )
        }
    }

    // MARK: - Header

    private var topBar: some View {
        HStack {
            Spacer()
            Button {
                dismiss()
            } label: {
                IOSPlayerIconButtonChrome(symbol: "xmark", size: 36, symbolSize: 14)
                    .frame(width: Theme.HitTarget.minimum, height: Theme.HitTarget.minimum)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(text.exportClose)
            .accessibilityIdentifier("exportPurchase_close")
        }
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.top, Theme.Spacing.md)
    }

    private var hero: some View {
        VStack(spacing: 0) {
            // Design's lavender into Clone's terracotta: the two modes this unlocks.
            IOSOnboardingIcon(
                symbol: store.access == .unlocked ? "checkmark" : "square.and.arrow.up",
                colors: [Theme.Brand.modeDesign, Theme.Brand.modeClone]
            )
            .accessibilityHidden(true)
            .padding(.bottom, 28)

            Text(text.exportUnlockTitle)
                .iosScaledFont(size: 30, weight: .bold, relativeTo: .largeTitle)
                .tracking(-0.6)
                .foregroundStyle(Theme.Text.primary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)

            Text(text.exportBenefit)
                .iosScaledFont(size: 17, relativeTo: .body)
                .foregroundStyle(Theme.Text.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 320)
                .padding(.top, Theme.Spacing.snug)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, Theme.Spacing.sm)
    }

    private var benefits: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
            IOSOnboardingBenefitRow(symbol: "checkmark", title: text.exportFreeDetail, detail: nil)
            IOSOnboardingBenefitRow(symbol: "infinity", title: text.exportOneTime, detail: nil)
        }
        // The fixed column widens to the page at accessibility sizes, as in onboarding.
        .frame(width: pinsActions ? 300 : nil, alignment: .leading)
        .frame(maxWidth: .infinity)
    }

    // MARK: - Actions

    private var actions: some View {
        VStack(spacing: Theme.Spacing.sm) {
            if store.access == .unlocked {
                unlockedCard
            } else if let product = store.product {
                IOSPrimaryCTAButton(
                    title: text.exportBuy(product.displayPrice),
                    symbol: "lock.open.fill",
                    tint: Theme.Brand.gold,
                    isEnabled: !isBusy
                ) {
                    IOSHaptics.impact(.medium)
                    Task { await store.purchase() }
                }
                .accessibilityIdentifier("exportPurchase_buy")
            } else {
                unavailable
            }
            if isBusy {
                HStack(spacing: Theme.Spacing.sm) {
                    ProgressView()
                        .controlSize(.small)
                        .tint(Theme.Text.secondary)
                    Text(text.exportChecking)
                        .font(.subheadline)
                        .foregroundStyle(Theme.Text.secondary)
                }
                .padding(.top, Theme.Spacing.xs)
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("exportPurchase_progress")
            }
            if let notice = store.notice {
                Text(text.exportPurchaseNotice(notice, access: store.access))
                    .font(.subheadline)
                    .foregroundStyle(Theme.Text.secondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, Theme.Spacing.xs)
                    .accessibilityIdentifier("exportPurchase_status")
            }
            Button {
                Task { await store.restore() }
            } label: {
                Text(text.exportRestore)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.Brand.gold)
                    .frame(maxWidth: .infinity, minHeight: Theme.HitTarget.minimum)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(store.operation != .idle)
            .opacity(store.operation != .idle ? Theme.Opacity.disabled : 1)
            .accessibilityIdentifier("exportPurchase_restore")
        }
    }

    private var unlockedCard: some View {
        VStack(spacing: Theme.Spacing.xs) {
            Label {
                Text(text.exportUnlocked)
                    .foregroundStyle(Theme.Text.primary)
            } icon: {
                Image(systemName: "checkmark.seal.fill")
                    .foregroundStyle(Theme.Brand.gold)
            }
            .font(.headline)
            .accessibilityIdentifier("exportPurchase_unlocked")

            Text(text.exportRetryAfterPurchase)
                .font(.subheadline)
                .foregroundStyle(Theme.Text.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity)
        .padding(Theme.Spacing.lg)
        .background {
            RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                .fill(Theme.accentSurface(Theme.Brand.gold))
        }
        .overlay {
            RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                .stroke(Theme.accentStroke(Theme.Brand.gold), lineWidth: Theme.Stroke.hairline)
        }
    }

    private var unavailable: some View {
        VStack(spacing: Theme.Spacing.md) {
            Text(text.exportProductUnavailable)
                .font(.subheadline)
                .foregroundStyle(Theme.Text.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            Button {
                Task { await store.loadProduct() }
            } label: {
                Text(text.exportReloadProduct)
                    .font(.headline)
                    .foregroundStyle(Theme.Text.primary)
                    .frame(maxWidth: .infinity, minHeight: 50)
                    .contentShape(Capsule())
            }
            .buttonStyle(.plain)
            .iosGatedGlass(tint: Theme.glassTint(), in: Capsule(), interactive: true, gatedFill: Theme.Surface.panel)
            .disabled(store.operation != .idle)
            .opacity(store.operation != .idle ? Theme.Opacity.disabled : 1)
            .accessibilityIdentifier("exportPurchase_reload")
        }
    }

    // MARK: - Footer

    private var footer: some View {
        VStack(spacing: Theme.Spacing.xs) {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: Theme.Spacing.md) {
                    privacyLink
                    Circle()
                        .fill(Theme.Text.tertiary)
                        .frame(width: 3, height: 3)
                        .accessibilityHidden(true)
                    supportLink
                }
                VStack(spacing: 0) {
                    privacyLink
                    supportLink
                }
            }
            Text(text.exportThanks)
                .font(.footnote)
                .foregroundStyle(Theme.Text.tertiary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 320)
        }
        .frame(maxWidth: .infinity)
    }

    private var privacyLink: some View {
        Link(text.exportPrivacy, destination: Self.privacyURL)
            .font(.footnote.weight(.medium))
            .foregroundStyle(Theme.Text.secondary)
            .frame(minHeight: Theme.HitTarget.minimum)
            .accessibilityIdentifier("exportPurchase_privacy")
    }

    private var supportLink: some View {
        Link(text.exportSupport, destination: Self.supportURL)
            .font(.footnote.weight(.medium))
            .foregroundStyle(Theme.Text.secondary)
            .frame(minHeight: Theme.HitTarget.minimum)
            .accessibilityIdentifier("exportPurchase_support")
    }
}
#endif
