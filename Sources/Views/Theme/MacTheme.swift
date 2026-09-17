import AppKit
import QwenVoiceCore
import SwiftUI

/// The macOS face of the shared `VocelloTheme` tokens (plan
/// `macos-ios-convergence-2026-09`): the shell, the screens and the sheets
/// read colors, radii, spacing and motion from here, so the two apps share one
/// palette. It is the only macOS theme namespace; the legacy `AppTheme` left
/// with the last legacy screen (CONV-22).
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

    /// AppKit twins of the shared text tokens, for the `NSTextView` bridges.
    /// The composer used `.labelColor` and drifted a shade off every other
    /// label on the screen.
    static let textPrimaryNSColor = NSColor(red: 0.95, green: 0.94, blue: 0.92, alpha: 1)
    static let textTertiaryNSColor = NSColor(red: 0.62, green: 0.60, blue: 0.55, alpha: 1)
    static let textMutedNSColor = textTertiaryNSColor

    static func tint(for mode: GenerationMode) -> Color {
        switch mode {
        case .custom: Brand.modeCustom
        case .design: Brand.modeDesign
        case .clone: Brand.modeClone
        }
    }

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

    /// Delivery preset tint of the Studio delivery chip; `fallback` (the mode
    /// tint) covers Neutral, Custom and unknown ids. Always paired with the
    /// preset's label, never the only signal.
    static func emotionColor(for presetID: String?, fallback: Color) -> Color {
        switch presetID {
        case "happy": Color(red: 0.95, green: 0.78, blue: 0.30)
        case "sad": Color(red: 0.55, green: 0.62, blue: 0.78)
        case "angry": Color(red: 0.78, green: 0.32, blue: 0.20)
        case "fearful": Color(red: 0.62, green: 0.50, blue: 0.78)
        case "surprised": Color(red: 0.38, green: 0.72, blue: 0.72)
        case "whisper": Color(red: 0.62, green: 0.62, blue: 0.66)
        case "calm": Color(red: 0.62, green: 0.74, blue: 0.62)
        case "narrator": Color(red: 0.72, green: 0.58, blue: 0.42)
        case "news": Color(red: 0.40, green: 0.56, blue: 0.74)
        default: fallback
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

/// The window's backdrop: the shared mode wash, tinted by the selected
/// destination. The split view's sidebar column draws its own material over
/// any window background, so each column paints the wash itself as its slice
/// of one window-sized surface: the phone's recipe untouched at the window's
/// size, shifted by the column's origin and clipped to the column, so the two
/// slices compose into one. Reduce Transparency is macOS's own environment key.
struct MacModeBackdrop: View {
    enum Column {
        case sidebar
        case detail
    }

    let tint: Color
    var intensity: VocelloModeBackdrop.Intensity = .whisper
    var column: Column? = nil

    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.vocelloWindowSize) private var windowSize

    var body: some View {
        GeometryReader { proxy in
            if let column, let windowSize, windowSize.width > proxy.size.width {
                let originX: CGFloat = column == .sidebar ? 0 : windowSize.width - proxy.size.width
                let surfaceHeight = max(windowSize.height, proxy.size.height)
                VocelloModeBackdrop(tint: tint, intensity: intensity, reduceTransparency: reduceTransparency)
                    .frame(width: windowSize.width, height: surfaceHeight)
                    .offset(x: -originX)
                    .frame(width: proxy.size.width, height: proxy.size.height, alignment: .topLeading)
                    .clipped()
            } else {
                VocelloModeBackdrop(tint: tint, intensity: intensity, reduceTransparency: reduceTransparency)
            }
        }
    }
}

/// Size of the main window's content, published by `ContentView` so the
/// split view's columns can draw one continuous backdrop.
private struct VocelloWindowSizeKey: EnvironmentKey {
    static let defaultValue: CGSize? = nil
}

/// Whether the sidebar column is on screen, published by `ContentView`.
///
/// It matters because the sidebar footer holds the only playback transport for
/// a finished take (maintainer decision 2026-09-16). macOS gives the user a
/// toolbar control and a menu command to collapse that column, and nothing
/// stopped it taking the transport with it — so a completed take could be left
/// with no way to play it except through History.
private struct VocelloSidebarVisibleKey: EnvironmentKey {
    static let defaultValue = true
}

extension EnvironmentValues {
    var vocelloWindowSize: CGSize? {
        get { self[VocelloWindowSizeKey.self] }
        set { self[VocelloWindowSizeKey.self] = newValue }
    }

    var vocelloSidebarIsVisible: Bool {
        get { self[VocelloSidebarVisibleKey.self] }
        set { self[VocelloSidebarVisibleKey.self] = newValue }
    }
}
