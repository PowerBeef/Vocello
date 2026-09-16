import SwiftUI

/// A quiet white-on-dark card with a hairline, for grouped content that does
/// not need glass: 12 pt padding, 8 pt content spacing, the shared card
/// radius. The iOS `IOSSurfaceCard` body, moved unchanged (UIF-02); the macOS
/// `MacSurfaceCard` twin is gone. `tint` is accepted for API compatibility
/// with the iOS call sites and is not used by the chrome (as on the phone).
struct VocelloSurfaceCard<Content: View>: View {
    let tint: Color?
    let content: Content

    init(tint: Color? = nil, @ViewBuilder content: () -> Content) {
        self.tint = tint
        self.content = content()
    }

    var body: some View {
        let shape = VocelloShape.card()

        VStack(alignment: .leading, spacing: contentSpacing) {
            content
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background { shape.fill(Color.white.opacity(0.04)) }
        .overlay { shape.stroke(Color.white.opacity(0.08), lineWidth: 0.5) }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var contentSpacing: CGFloat { 8 }
}
