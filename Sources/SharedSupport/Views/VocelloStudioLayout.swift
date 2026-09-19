import SwiftUI

/// The iOS Studio composition, shared by both apps. The writing surface receives
/// the remaining height; setup and the stateful dock keep their natural sizes.
/// Platform adapters supply their editor, safe-area clearances and dock actions.
struct VocelloStudioLayout<Composer: View, Setup: View, Dock: View>: View {
    @ViewBuilder var composer: () -> Composer
    @ViewBuilder var setup: () -> Setup
    @ViewBuilder var dock: () -> Dock

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            composer()
                .frame(maxHeight: .infinity)
                .layoutPriority(1)
            setup()
                .layoutPriority(2)
            dock()
                .layoutPriority(3)
        }
    }
}
