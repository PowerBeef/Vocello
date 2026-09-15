import SwiftUI

/// The iOS surface card (`IOSSurfaceCard`): a quiet white-on-dark card with a
/// hairline, used for grouped content that does not need glass.
struct MacSurfaceCard<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: MacTheme.Radius.card, style: .continuous)

        VStack(alignment: .leading, spacing: MacTheme.Spacing.sm) {
            content
        }
        .padding(MacTheme.Spacing.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background { shape.fill(Color.white.opacity(0.04)) }
        .overlay { shape.stroke(Color.white.opacity(0.08), lineWidth: 0.5) }
    }
}
