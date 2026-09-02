import SwiftUI
import UIKit

private struct IOSReduceMotionEnabledKey: EnvironmentKey {
    static let defaultValue = false
}

private struct IOSReduceTransparencyEnabledKey: EnvironmentKey {
    static let defaultValue = false
}

/// iOS counterpart to the macOS `generationPerformanceGate` (AppTheme.swift):
/// while a generation is active, glass surfaces render their shipped
/// solid-fill fallback so Liquid Glass compositor work cannot compete with the
/// engine. On iPhone the gate engages only on fixed-refresh (non-ProMotion)
/// displays — the measured iPhone 17 Pro evidence showed adaptive-refresh
/// panels idle static glass, but the supported iPhone 16/16 Plus/16e tier has
/// 60 Hz panels where that reasoning does not apply.
private struct IOSGenerationPerformanceGateKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    var iosReduceMotionEnabled: Bool {
        get { self[IOSReduceMotionEnabledKey.self] }
        set { self[IOSReduceMotionEnabledKey.self] = newValue }
    }

    var iosReduceTransparencyEnabled: Bool {
        get { self[IOSReduceTransparencyEnabledKey.self] }
        set { self[IOSReduceTransparencyEnabledKey.self] = newValue }
    }

    var iosGenerationPerformanceGate: Bool {
        get { self[IOSGenerationPerformanceGateKey.self] }
        set { self[IOSGenerationPerformanceGateKey.self] = newValue }
    }
}

@MainActor
enum IOSDisplayCapability {
    /// True on fixed-refresh (non-ProMotion) panels, which cannot idle below
    /// their 60 Hz cadence. Resolved from the connected window scene; before
    /// a scene attaches the performance gate stays off.
    static var isFixedRefreshDisplay: Bool {
        let sceneMaximum = UIApplication.shared.connectedScenes
            .compactMap { ($0 as? UIWindowScene)?.screen.maximumFramesPerSecond }
            .max()
        return sceneMaximum.map { $0 <= 60 } ?? false
    }
}

// iOS counterpart to the macOS `appAnimation` helper at
// Sources/Views/Components/AppTheme.swift. Honors Reduce Motion via the
// SwiftUI environment so animations are skipped when the user has the
// accessibility setting enabled. AGENTS.md requires Reduce Motion to be
// honored across the app.

extension View {
    func iosAppAnimation<Value: Equatable>(_ animation: Animation?, value: Value) -> some View {
        modifier(IOSAccessibleAnimationModifier(animation: animation, value: value))
    }

    /// Apply `accessibilityIdentifier` only when an id is provided. Lets a view
    /// take an optional id without the caller branching.
    @ViewBuilder
    func iosAccessibilityIdentifier(_ id: String?) -> some View {
        if let id {
            accessibilityIdentifier(id)
        } else {
            self
        }
    }

}

private struct IOSAccessibleAnimationModifier<Value: Equatable>: ViewModifier {
    let animation: Animation?
    let value: Value
    @Environment(\.iosReduceMotionEnabled) private var reduceMotion

    func body(content: Content) -> some View {
        content.animation(reduceMotion ? nil : animation, value: value)
    }
}

@MainActor
enum IOSAccessibleAnimation {
    static func perform<R>(_ animation: Animation?, _ block: () -> R) -> R {
        let shouldReduceMotion = UIAccessibility.isReduceMotionEnabled || IOSAppDefaults.reduceMotionEnabled
        let resolved = shouldReduceMotion ? nil : animation
        return withAnimation(resolved, block)
    }
}
