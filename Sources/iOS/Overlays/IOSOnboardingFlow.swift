import SwiftUI

/// Full-screen first-run onboarding from the iOS design reference
/// (design_references/Vocello iOS/screens.jsx Onboarding). Three pages:
/// Welcome → Install pointer → Open Studio. Informational only; the actual
/// model install happens later in Settings via the model row
/// controls so onboarding stays focused on framing.
///
/// Wired in QVoiceiOSRootView as a `.fullScreenCover` gated on
/// `IOSAppDefaults.hasCompletedOnboarding`.
struct IOSOnboardingFlow: View {
    @Binding var isPresented: Bool

    @State private var page: Int = 0
    @Environment(\.iosReduceMotionEnabled) private var reduceMotion

    private let totalPages = 3

    var body: some View {
        ZStack {
            IOSModeBackdrop(tint: Theme.Brand.gold, intensity: .warm)

            VStack(spacing: 0) {
                topBar
                pages
                pagination
                ctaButton
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 40)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .preferredColorScheme(.dark)
        .interactiveDismissDisabled(true)
    }

    // MARK: - Top bar

    private var topBar: some View {
        HStack {
            IOSProductTitleLockup(title: Theme.Branding.productName)

            Spacer()

            if page < totalPages - 1 {
                Button("Skip") {
                    complete()
                }
                .font(.subheadline.weight(.medium))
                .foregroundStyle(Theme.Text.secondary)
                .buttonStyle(.plain)
                .accessibilityIdentifier("onboarding_skip")
            }
        }
        .frame(height: 44)
        .padding(.top, 12)
    }

    // MARK: - Pages

    @ViewBuilder
    private var pages: some View {
        Group {
            switch page {
            case 0:
                IOSOnboardingWelcomePage()
            case 1:
                IOSOnboardingInstallPage()
            default:
                IOSOnboardingReadyPage()
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        .transition(.opacity)
        .iosAppAnimation(Theme.Motion.easeOut, value: page)
    }

    // MARK: - Pagination dots

    private var pagination: some View {
        HStack(spacing: 8) {
            ForEach(0..<totalPages, id: \.self) { i in
                Capsule(style: .continuous)
                    .fill(i == page ? Theme.Brand.gold : Theme.Text.tertiary.opacity(0.4))
                    .frame(width: i == page ? 20 : 6, height: 6)
                    .iosAppAnimation(Theme.Motion.stateChange, value: page)
            }
        }
        .padding(.bottom, 24)
        .accessibilityElement()
        .accessibilityLabel("Page \(page + 1) of \(totalPages)")
    }

    // MARK: - CTA

    private var ctaButton: some View {
        IOSPrimaryCTAButton(
            title: ctaTitle,
            tint: Theme.Brand.gold,
            isEnabled: true,
            action: handleCTA
        )
        .accessibilityIdentifier("onboarding_cta")
    }

    private var ctaTitle: String {
        switch page {
        case 0: return "Get started"
        case 1: return "Continue"
        default: return "Open Studio"
        }
    }

    private func handleCTA() {
        IOSHaptics.impact(.light)
        if page < totalPages - 1 {
            IOSAccessibleAnimation.perform(Theme.Motion.easeOut) {
                page += 1
            }
        } else {
            complete()
        }
    }

    private func complete() {
        IOSAppDefaults.hasCompletedOnboarding = true
        IOSHaptics.success()
        IOSAccessibleAnimation.perform(Theme.Motion.sheetSlideUp) {
            isPresented = false
        }
    }
}

// MARK: - Page 1: Welcome

private struct IOSOnboardingWelcomePage: View {
    var body: some View {
        VStack(spacing: 0) {
            IOSOnboardingIcon(symbol: "sparkles", colors: [Theme.Brand.gold, Theme.Brand.modeClone])
                .padding(.bottom, 32)

            Text("Vocello")
                .iosScaledFont(size: 36, weight: .bold, relativeTo: .largeTitle)
                .tracking(-0.90)
                .foregroundStyle(Theme.Text.primary)
                .multilineTextAlignment(.center)

            Text("Studio-quality voice generation. Runs entirely on this iPhone.")
                .iosScaledFont(size: 17, relativeTo: .body)
                .foregroundStyle(Theme.Text.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 320)
                .padding(.top, 14)

            VStack(alignment: .leading, spacing: 12) {
                IOSOnboardingBenefitRow(
                    symbol: "lock.shield",
                    title: "Nothing leaves your device",
                    detail: nil
                )
                IOSOnboardingBenefitRow(
                    symbol: "bolt.fill",
                    title: "Generation in seconds",
                    detail: nil
                )
                IOSOnboardingBenefitRow(
                    symbol: "waveform.path.ecg",
                    title: "Clone, design, or pick a voice",
                    detail: nil
                )
            }
            .frame(width: 280, alignment: .leading)
            .padding(.top, 32)
        }
        .frame(maxWidth: .infinity, alignment: .center)
    }
}

// MARK: - Page 2: Install

private struct IOSOnboardingInstallPage: View {
    var body: some View {
        VStack(spacing: 0) {
            IOSOnboardingIcon(symbol: "arrow.down.circle.fill", colors: [Theme.Brand.modeDesign, Theme.Brand.gold])
                .padding(.bottom, 32)

            Text("Install Built-in Voice")
                .iosScaledFont(size: 36, weight: .bold, relativeTo: .largeTitle)
                .tracking(-0.90)
                .foregroundStyle(Theme.Text.primary)
                .multilineTextAlignment(.center)

            Text("Download the 4-bit Speed model to start generating. Voice Design and Voice Cloning each have their own model; install them later in Settings.")
                .iosScaledFont(size: 17, relativeTo: .body)
                .foregroundStyle(Theme.Text.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 320)
                .padding(.top, 14)

            VStack(alignment: .leading, spacing: 14) {
                IOSOnboardingModelHint(
                    tint: Theme.Brand.modeCustom,
                    name: "Built-in Voice",
                    detail: "Built-in speakers and delivery presets."
                )
                IOSOnboardingModelHint(
                    tint: Theme.Brand.modeDesign,
                    name: "Voice Design",
                    detail: "Describe a voice in natural language."
                )
                IOSOnboardingModelHint(
                    tint: Theme.Brand.modeClone,
                    name: "Voice Cloning",
                    detail: "Use a 10-20 s reference clip you own."
                )
            }
            .frame(width: 300, alignment: .leading)
            .padding(.top, 32)
        }
        .frame(maxWidth: .infinity, alignment: .center)
    }
}

// MARK: - Page 3: Ready

private struct IOSOnboardingReadyPage: View {
    var body: some View {
        VStack(spacing: 0) {
            IOSOnboardingIcon(symbol: "checkmark.circle.fill", colors: [Theme.Brand.modeClone, Theme.Brand.modeDesign])
                .padding(.bottom, 32)

            Text("You're ready")
                .iosScaledFont(size: 36, weight: .bold, relativeTo: .largeTitle)
                .tracking(-0.90)
                .foregroundStyle(Theme.Text.primary)
                .multilineTextAlignment(.center)

            // Design pick D2: onboarding finishes before any model exists on
            // a fresh install — the closing copy names that first real step
            // instead of implying generation already works.
            Text("Download a voice model in Settings, then type a script, pick a voice, generate. Your audio stays here.")
                .iosScaledFont(size: 17, relativeTo: .body)
                .foregroundStyle(Theme.Text.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 320)
                .padding(.top, 14)

            HStack(spacing: 12) {
                ForEach(0..<3, id: \.self) { i in
                    let tint: Color = {
                        switch i {
                        case 0: return Theme.Brand.modeCustom
                        case 1: return Theme.Brand.modeDesign
                        default: return Theme.Brand.modeClone
                        }
                    }()
                    IOSWaveformBars(
                        seed: 42 + i,
                        barCount: 18,
                        tint: tint,
                        progress: 1.0,
                        isAnimating: false
                    )
                    .frame(height: 64)
                    .padding(12)
                    .background {
                        RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                            .fill(Theme.Surface.glassSurfaceMuted.opacity(0.5))
                    }
                    .overlay {
                        RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                            .stroke(tint.opacity(0.32), lineWidth: 0.9)
                    }
                }
            }
            .padding(.top, 32)
        }
        .frame(maxWidth: .infinity, alignment: .center)
    }
}

// MARK: - Reusable rows

private struct IOSOnboardingIcon: View {
    let symbol: String
    let colors: [Color]

    var body: some View {
        RoundedRectangle(cornerRadius: 24, style: .continuous)
            .fill(
                LinearGradient(
                    colors: colors,
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
            )
            .frame(width: 96, height: 96)
            .overlay {
                Image(systemName: symbol)
                    .font(.system(size: 48, weight: .semibold))
                    .foregroundStyle(Color(red: 13 / 255, green: 14 / 255, blue: 18 / 255))
            }
            .shadow(color: Theme.Brand.gold.opacity(0.30), radius: 18, x: 0, y: 12)
    }
}

private struct IOSOnboardingBenefitRow: View {
    let symbol: String
    let title: String
    let detail: String?

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            ZStack {
                Circle()
                    .fill(Theme.Brand.gold.opacity(0.18))
                Image(systemName: symbol)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(Theme.Brand.gold)
            }
            .frame(width: 38, height: 38)

            VStack(alignment: .leading, spacing: 2) {
                // D7: benefit titles carry the row (every current row is
                // title-only) — secondary ink made the list read as fine
                // print next to the page headline.
                Text(title)
                    .iosScaledFont(size: 14, weight: .medium, relativeTo: .footnote)
                    .foregroundStyle(Theme.Text.primary)
                if let detail {
                    Text(detail)
                        .font(.subheadline)
                        .foregroundStyle(Theme.Text.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }
}

private struct IOSOnboardingModelHint: View {
    let tint: Color
    let name: String
    let detail: String

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Circle()
                .fill(tint.opacity(0.6))
                .frame(width: 10, height: 10)
                .padding(.top, 6)

            VStack(alignment: .leading, spacing: 2) {
                Text(name)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.Text.primary)
                Text(detail)
                    .font(.subheadline)
                    .foregroundStyle(Theme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
