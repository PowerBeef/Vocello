import SwiftUI

/// Small mode-colored dot (6 pt by default) used beside History row metadata
/// and inside filter chips; always paired with a textual cue, never the only
/// signal. The iOS `IOSModeDot` body, moved unchanged (UIF-02); the macOS
/// `MacModeDot` twin is gone.
struct VocelloModeDot: View {
    let tint: Color
    let diameter: CGFloat

    init(tint: Color, diameter: CGFloat = 6) {
        self.tint = tint
        self.diameter = diameter
    }

    var body: some View {
        Circle()
            .fill(tint)
            .frame(width: diameter, height: diameter)
    }
}
