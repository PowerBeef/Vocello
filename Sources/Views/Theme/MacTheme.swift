import AppKit
import QwenVoiceCore
import SwiftUI

/// The macOS face of the shared `VocelloTheme` tokens (plan
/// `macos-ios-convergence-2026-09`): the new shell and screens read colors,
/// radii, spacing and motion from here, so the two apps share one palette. The
/// legacy `AppTheme` survives only under the screens that are still to be
/// replaced and forwards its brand colors to the same tokens.
enum MacTheme {
    typealias Brand = VocelloTheme.Brand
    typealias Surface = VocelloTheme.Surface
    typealias Text = VocelloTheme.Text
    typealias Status = VocelloTheme.Status
    typealias Radius = VocelloTheme.Radius
    typealias Spacing = VocelloTheme.Spacing
    typealias Motion = VocelloTheme.Motion

    static let accent = VocelloTheme.Brand.gold

    /// Dock accents of the iOS `TabDock` for the destinations that are not a
    /// generation mode: dusty rose for History, dusty blue for Saved Voices,
    /// cool slate for Settings.
    static let historyTint = Color(red: 0.749, green: 0.627, blue: 0.671)
    static let voicesTint = Color(red: 0.541, green: 0.690, blue: 0.784)
    static let settingsTint = Color(red: 0.631, green: 0.659, blue: 0.722)

    static let textMutedNSColor = NSColor(red: 0.62, green: 0.60, blue: 0.55, alpha: 1)

    static func tint(for item: SidebarItem) -> Color {
        switch item {
        case .customVoice: Brand.modeCustom
        case .voiceDesign: Brand.modeDesign
        case .voiceCloning: Brand.modeClone
        case .history: historyTint
        case .voices: voicesTint
        case .settings: settingsTint
        }
    }

    /// Canonical per-mode SF Symbol shared by the sidebar, the Settings model
    /// rows and every future mode chip.
    static func modeGlyph(for mode: GenerationMode) -> String {
        switch mode {
        case .custom: "person.wave.2"
        case .design: "text.bubble"
        case .clone: "waveform.badge.plus"
        }
    }

    static func glassTint(_ tint: Color? = nil, intensity: Double = 1.0) -> Color {
        VocelloTheme.glassTint(tint, intensity: intensity)
    }

    /// Full-height canvas behind the sidebar and the detail pane: the iOS
    /// screen backdrop, top to bottom.
    static var canvasGradient: LinearGradient {
        LinearGradient(
            colors: [Surface.canvas, Surface.canvasBottom],
            startPoint: .top,
            endPoint: .bottom
        )
    }
}
