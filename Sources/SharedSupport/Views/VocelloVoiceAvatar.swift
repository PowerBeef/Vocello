import SwiftUI

/// Circular gradient avatar for built-in or saved voices. Hue derived from
/// the voice id so the same voice renders the same gradient everywhere.
///
/// Per `design_references/Vocello iOS/chrome.jsx` VoiceAvatar. The iOS
/// `IOSVoiceAvatar` body, moved unchanged (UIF-02); the macOS
/// `MacVoiceAvatar` twin is gone. `isDecorative` is the one desktop
/// difference: the Mac rows hide the avatar from accessibility because the
/// row's name label already speaks the voice; the phone leaves it exposed.
struct VocelloVoiceAvatar: View {
    let seed: String
    let initials: String
    let diameter: CGFloat
    let isDecorative: Bool

    init(seed: String, initials: String, diameter: CGFloat = 44, isDecorative: Bool = false) {
        self.seed = seed
        let parts = initials.split(separator: " ")
        if parts.count >= 2 {
            self.initials = parts.prefix(2).map { String($0.prefix(1)) }.joined().uppercased()
        } else {
            self.initials = String(initials.prefix(1)).uppercased()
        }
        self.diameter = diameter
        self.isDecorative = isDecorative
    }

    var body: some View {
        if isDecorative {
            avatar.accessibilityHidden(true)
        } else {
            avatar
        }
    }

    private var avatar: some View {
        let hue = hueForSeed(seed)
        let topColor = Color(hue: hue, saturation: 0.45, brightness: 0.78)
        let bottomColor = Color(hue: hue, saturation: 0.55, brightness: 0.52)

        return ZStack {
            Circle()
                .fill(
                    LinearGradient(
                        colors: [topColor, bottomColor],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
            Circle()
                .stroke(Color.white.opacity(0.10), lineWidth: 0.75)
            Text(initials)
                .font(.system(size: diameter * 0.36, weight: .semibold, design: .rounded))
                .foregroundStyle(VocelloTheme.Text.primary)
        }
        .frame(width: diameter, height: diameter)
    }

    private func hueForSeed(_ seed: String) -> Double {
        VocelloStableVisualHash.normalized(seed)
    }
}
