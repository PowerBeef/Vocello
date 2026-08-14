import SwiftUI

struct IOSFirstRunOnboardingCard: View {
    @Binding var selectedTab: IOSAppTab

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "sparkles")
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(Theme.Brand.gold)
                Text("Install your first voice")
                    .font(IOSTypeStyle.cardTitle.font)
                    .foregroundStyle(Theme.Text.primary)
            }

            Text("Open Settings to download a Custom Voice, Voice Design, or Voice Cloning model. Every package runs on-device.")
                .font(IOSTypeStyle.body.font)
                .foregroundStyle(Theme.Text.secondary)
                .fixedSize(horizontal: false, vertical: true)

            Button {
                IOSHaptics.selection()
                selectedTab = .settings
            } label: {
                Label("Open Settings", systemImage: "arrow.right.circle.fill")
                    .font(.callout.weight(.semibold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 10)
            }
            .buttonStyle(.borderedProminent)
            .tint(Theme.Brand.gold)
            .accessibilityIdentifier("onboarding_openSettings")
        }
        .padding(16)
        // Neutral surface — gold appears on the CTA only. Mirrors macOS
        // "warm without volume" pattern (PRODUCT.md design principle 5).
        .iosSubtleGlassSurface(
            in: RoundedRectangle(cornerRadius: 16, style: .continuous),
            tint: nil
        )
        .accessibilityIdentifier("onboarding_firstRunCard")
    }
}
