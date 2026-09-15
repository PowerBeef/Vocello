import SwiftUI

extension View {
    /// Every macOS animation routes through here so Reduce Motion (read live
    /// by `AppLaunchConfiguration`) disables the lot; imperative changes use
    /// `AppLaunchConfiguration.performAnimated`.
    func appAnimation<Value: Equatable>(_ animation: Animation?, value: Value) -> some View {
        self.animation(AppLaunchConfiguration.current.animation(animation), value: value)
    }

    /// Visible keyboard-focus indicator in the active mode's accent color
    /// (2026-08 UI review, W1-C). The system blue ring stays suppressed; it
    /// painted a stray selection halo on first appearance under Full Keyboard
    /// Access, but suppression alone left controls with no focus indication
    /// at all (WCAG 2.4.7). This modifier keeps the suppression and draws a
    /// 2 pt accent ring only while the control actually has focus.
    func vocelloFocusRing(_ color: Color, radius: CGFloat = 8) -> some View {
        modifier(VocelloFocusRing(color: color, radius: radius))
    }
}

private struct VocelloFocusRing: ViewModifier {
    let color: Color
    let radius: CGFloat
    @FocusState private var isFocused: Bool

    func body(content: Content) -> some View {
        content
            .focused($isFocused)
            .focusEffectDisabled()
            .overlay {
                if isFocused {
                    RoundedRectangle(cornerRadius: radius + 2, style: .continuous)
                        .strokeBorder(color.opacity(0.85), lineWidth: 2)
                        .padding(-3)
                        .allowsHitTesting(false)
                }
            }
            .appAnimation(MacTheme.Motion.stateChange, value: isFocused)
    }
}
