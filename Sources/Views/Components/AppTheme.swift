import AppKit
import SwiftUI

/// Generation performance gate (benchmarks/OPTIMIZATION.md §K): Liquid Glass's
/// continuous compositor work costs ~23% engine RTF on the 8 GB tier while a
/// window showing glass is visible (measured 1.37 with glass vs 1.84 with the
/// solid-fill fallback during generation). While a generation is active the
/// glass surfaces fall back to the same solid-fill design Reduce Transparency
/// uses; glass returns when the engine goes idle.
private struct GenerationPerformanceGateKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    var generationPerformanceGate: Bool {
        get { self[GenerationPerformanceGateKey.self] }
        set { self[GenerationPerformanceGateKey.self] = newValue }
    }
}

enum AppTheme {
    enum UIProfile: String {
        case liquid
    }

    // QW_UI_LIQUID is always set (project.yml) and .liquid is the only profile —
    // the enum + conditional survive as the seam for a future non-liquid profile,
    // but there is deliberately NO behavioral fork today (2026-07-02 review).
    static let uiProfile: UIProfile = .liquid

    static let vocelloGold = Color(red: 0.93, green: 0.80, blue: 0.54)
    static let accent = vocelloGold
    static let inlinePreviewProgressTint = Color(red: 0.93, green: 0.80, blue: 0.54)
    static let statusProgressTint = Color(red: 0.93, green: 0.80, blue: 0.54)
    static let smokedGlassTint = Color(white: 0.15, opacity: 0.6)
    // Vocello mode palette (mirrors Sources/iOS/IOSShellPrimitives.swift:IOSBrandTheme).
    // The app is dark-only (appearance pinned in QwenVoiceApplicationDelegate),
    // matching the iOS brand values exactly.
    static let customVoice = Color(red: 0.93, green: 0.80, blue: 0.54)   // warm golden — Vocello primary
    static let voiceDesign = Color(red: 0.75, green: 0.67, blue: 0.86)   // lavender purple
    static let voiceCloning = Color(red: 0.86, green: 0.66, blue: 0.53)  // warm terracotta
    // Library + Settings continue to resolve to the primary accent (golden) so
    // non-generation surfaces read as one coherent app chrome.
    static let history = accent
    static let voices = accent
    static let models = accent
    static let preferences = accent

    static let canvasBackground = Color(red: 0.086, green: 0.094, blue: 0.118)
    static let stageFill = Color(red: 0.110, green: 0.118, blue: 0.150)
    static let stageStroke = Color.white.opacity(0.10)
    // Dark-glass panel fills: panels are VISIBLY darker than the canvas
    // background so glass refraction + 3D depth carry the "looking
    // through smoked glass into a recess" look.
    static let cardFill = Color(red: 0.050, green: 0.055, blue: 0.072)
    static let cardStroke = Color.white.opacity(0.15)
    static let inlineFill = Color(red: 0.068, green: 0.075, blue: 0.095)
    static let inlineStroke = Color.white.opacity(0.12)
    static let fieldFill = Color(red: 0.165, green: 0.172, blue: 0.214)
    static let fieldStroke = Color.white.opacity(0.10)
    static let railBackground = Color(red: 0.090, green: 0.098, blue: 0.122)
    static let railStroke = Color.white.opacity(0.08)
    static let stageGlow = Color.white.opacity(0.05)
    static let sidebarSelectionFill = Color.white.opacity(0.05)
    static let sidebarSelectionStroke = accent.opacity(0.26)
    static let sidebarHoverFill = Color.white.opacity(0.03)
    static let sidebarHoverStroke = Color.white.opacity(0.08)

    static var windowTitlebarSeparatorStyle: NSTitlebarSeparatorStyle {
        #if QW_UI_LIQUID
        return .none
        #else
        return .automatic
        #endif
    }
    static var splitDividerStyle: NSSplitView.DividerStyle { .thin }
    static var legacyDividerBlendInset: CGFloat { 0 }
    static var legacyDividerBlendAlpha: CGFloat { 0 }
    static var legacyDividerEdgeAlpha: CGFloat { 0 }

    /// Per the May 2026 audit (Batch 4 — colorize): the emotion palette
    /// no longer reaches for raw fully-saturated system colors (which
    /// fought the warm-golden Vocello chrome). Each emotion sits in the
    /// same midtone OKLCH-ish neighborhood, distinguishable through hue
    /// but unified in chroma + lightness so an emotion chip never feels
    /// like a sticker on the panel.
    static func emotionColor(for emotionID: String) -> Color {
        switch emotionID {
        case "neutral":
            return .secondary
        case "happy":
            return Color(red: 0.95, green: 0.78, blue: 0.30)  // warm gold-yellow
        case "sad":
            return Color(red: 0.55, green: 0.62, blue: 0.78)  // muted slate-blue
        case "angry":
            return Color(red: 0.78, green: 0.32, blue: 0.20)  // deep rust
        case "fearful":
            return Color(red: 0.62, green: 0.50, blue: 0.78)  // quiet violet
        case "surprised":
            return Color(red: 0.38, green: 0.72, blue: 0.72)  // bright teal
        case "whisper":
            return Color(red: 0.62, green: 0.62, blue: 0.66)  // cool gray
        case "calm":
            return Color(red: 0.62, green: 0.74, blue: 0.62)  // sage
        case "narrator":
            return Color(red: 0.72, green: 0.58, blue: 0.42)  // warm tan
        case "news":
            return Color(red: 0.40, green: 0.56, blue: 0.74)  // steel blue
        default:
            return accent
        }
    }

    static func sidebarColor(for item: SidebarItem) -> Color {
        switch item {
        case .customVoice: return customVoice
        case .voiceDesign: return voiceDesign
        case .voiceCloning: return voiceCloning
        case .history: return history
        case .voices: return voices
        case .settings: return preferences
        }
    }

    static func modeColor(for mode: String) -> Color {
        switch mode {
        case GenerationMode.custom.rawValue: return customVoice
        case GenerationMode.design.rawValue: return voiceDesign
        case GenerationMode.clone.rawValue: return voiceCloning
        default: return accent
        }
    }

    static func modeColor(for mode: GenerationMode) -> Color {
        switch mode {
        case .custom: return customVoice
        case .design: return voiceDesign
        case .clone: return voiceCloning
        }
    }

    /// Canonical per-mode SF Symbol, matching the sidebar's mode icons —
    /// keep Settings rows, sidebar items, and any future mode chips on the
    /// same glyphs (`c196f11` analog from iOS).
    static func modeGlyph(for mode: GenerationMode) -> String {
        switch mode {
        case .custom: return "person.wave.2"
        case .design: return "text.bubble"
        case .clone: return "waveform.badge.plus"
        }
    }

    static func accentWash(_ color: Color) -> Color {
        color.opacity(0.20)
    }

    static func accentGlassTint(_ color: Color) -> Color {
        color.opacity(0.88)
    }

    /// Subtle mode-aware tint for big Liquid-Glass surfaces (Configuration
    /// panel, Script panel, cards). Weaker alpha than `accentGlassTint` so
    /// the panels read as softly Vocello-colored without overpowering the
    /// content inside them.
    static func surfaceGlassTint(_ color: Color) -> Color {
        color.opacity(0.14)
    }

    static func accentStroke(_ color: Color) -> Color {
        color.opacity(0.34)
    }

    static let surfaceStrokeOpacity: Double = 0.16

    static let surfaceStrokeWidth: CGFloat = 0.75

    static let waveformGradient = LinearGradient(
        colors: [accent.opacity(0.45), accent],
        startPoint: .leading,
        endPoint: .trailing
    )

    static func waveformColor(at position: Double) -> Color {
        let progress = max(0, min(1, position))
        return accent.opacity(0.45 + (progress * 0.45))
    }
}

private struct NativeSurfaceStyle: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.generationPerformanceGate) private var performanceGate
    @Environment(\.cardGlassTint) private var cardGlassTint

    let padding: CGFloat
    let radius: CGFloat
    let fill: Color

    func body(content: Content) -> some View {
        #if QW_UI_LIQUID
        if #available(macOS 26, *), !reduceTransparency, !performanceGate {
            let resolvedTint: Color = cardGlassTint.map {
                AppTheme.surfaceGlassTint($0)
            } ?? AppTheme.smokedGlassTint
            let resolvedStroke: Color = cardGlassTint.map {
                AppTheme.accentStroke($0).opacity(0.55)
            } ?? AppTheme.cardStroke.opacity(AppTheme.surfaceStrokeOpacity)
            let depthIntensity: Double = cardGlassTint == nil ? 1.0 : 1.15
            content
                .padding(padding)
                .background(
                    RoundedRectangle(cornerRadius: radius, style: .continuous)
                        .fill(fill)
                        .overlay(
                            RoundedRectangle(cornerRadius: radius, style: .continuous)
                                .strokeBorder(
                                    resolvedStroke,
                                    lineWidth: AppTheme.surfaceStrokeWidth
                                )
                        )
                )
                .glassEffect(.regular.tint(resolvedTint), in: .rect(cornerRadius: radius))
                .glass3DDepth(radius: radius, intensity: depthIntensity)
        } else {
            legacyBody(content: content)
        }
        #else
        legacyBody(content: content)
        #endif
    }

    private func legacyBody(content: Content) -> some View {
        content
            .padding(padding)
            .background(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .fill(fill)
            )
            .overlay(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .stroke(
                        AppTheme.cardStroke.opacity(0.20),
                        lineWidth: 0.5
                    )
            )
    }
}

private struct StudioChipStyle: ViewModifier {
    let isSelected: Bool
    let color: Color

    // Per the May 2026 audit (Batch 2 — quieter): chips no longer
    // use Liquid Glass + 3D depth. Glass is reserved for cards /
    // panels / the primary CTA so the chrome around them reads
    // quieter and the cards feel more substantial. Single flat code
    // path for both Liquid + legacy builds.
    func body(content: Content) -> some View {
        content
            .font(.subheadline.weight(.semibold))
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .foregroundStyle(isSelected ? color : .primary)
            .background(
                Capsule(style: .continuous)
                    .fill(
                        isSelected
                            ? AppTheme.accentWash(color)
                            : AppTheme.inlineFill
                    )
            )
            .overlay(
                Capsule(style: .continuous)
                    .stroke(
                        isSelected
                            ? color.opacity(0.32)
                            : AppTheme.cardStroke.opacity(0.20),
                        lineWidth: isSelected ? 1 : 0.75
                    )
            )
            .appAnimation(.easeInOut(duration: 0.15), value: isSelected)
    }
}

extension View {
    func studioCard(
        padding: CGFloat = LayoutConstants.cardPadding,
        radius: CGFloat = LayoutConstants.cardRadius
    ) -> some View {
        modifier(NativeSurfaceStyle(padding: padding, radius: radius, fill: AppTheme.cardFill))
    }

    func glassCard() -> some View {
        studioCard(padding: LayoutConstants.glassCardPadding, radius: LayoutConstants.cardRadius)
    }

    func stageCard() -> some View {
        modifier(NativeSurfaceStyle(padding: 0, radius: LayoutConstants.stageRadius, fill: AppTheme.stageFill))
    }

    func inlinePanel(padding: CGFloat = 14, radius: CGFloat = 16) -> some View {
        modifier(NativeSurfaceStyle(padding: padding, radius: radius, fill: AppTheme.inlineFill))
    }

    func appAnimation<Value: Equatable>(_ animation: Animation?, value: Value) -> some View {
        self.animation(AppLaunchConfiguration.current.animation(animation), value: value)
    }

    func studioChip(isSelected: Bool, color: Color) -> some View {
        modifier(StudioChipStyle(isSelected: isSelected, color: color))
    }

    func chipStyle(isSelected: Bool, color: Color) -> some View {
        modifier(StudioChipStyle(isSelected: isSelected, color: color))
    }

    func voiceChoiceChip(isSelected: Bool, color: Color) -> some View {
        modifier(StudioChipStyle(isSelected: isSelected, color: color))
    }
}

private struct ToolbarRowStyle: ViewModifier {
    let label: String

    func body(content: Content) -> some View {
        HStack(alignment: .center, spacing: 10) {
            Text(label.uppercased())
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
                .frame(width: 52, alignment: .leading)
            content
        }
    }
}

private struct GlassBadgeStyle: ViewModifier {
    let tint: Color?

    // Per the May 2026 audit (Batch 2 — quieter): badges no longer
    // use Liquid Glass. A flat capsule fill + subtle stroke reads
    // quieter against the cards / panels that DO use glass. Tinted
    // badges (e.g. mode capsules in History rows) keep a subtle
    // tint-washed fill so they remain identity-coherent.
    func body(content: Content) -> some View {
        content
            .background(
                Capsule(style: .continuous)
                    .fill(badgeFill)
            )
            .overlay(
                Capsule(style: .continuous)
                    .stroke(badgeStroke, lineWidth: 0.5)
            )
    }

    private var badgeFill: Color {
        if let tint {
            return tint.opacity(0.16)
        }
        return AppTheme.inlineFill
    }

    private var badgeStroke: Color {
        if let tint {
            return tint.opacity(0.30)
        }
        return AppTheme.inlineStroke.opacity(0.30)
    }
}

private struct GlassTextFieldStyle: ViewModifier {
    let radius: CGFloat
    let strokeColor: Color?

    // Per the May 2026 audit (Batch 2 — quieter): text fields no
    // longer use Liquid Glass. A flat rounded fill + a focus-aware
    // stroke (passed in by the caller via `strokeColor`) reads
    // calmer and lets the surrounding cards carry the depth.
    func body(content: Content) -> some View {
        content
            .background(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .fill(AppTheme.fieldFill)
            )
            .overlay(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .stroke(
                        (strokeColor ?? AppTheme.fieldStroke).opacity(0.45),
                        lineWidth: 0.5
                    )
            )
    }
}

private struct Glass3DDepthStyle: ViewModifier {
    let radius: CGFloat
    let intensity: Double

    func body(content: Content) -> some View {
        #if QW_UI_LIQUID
        if #available(macOS 26, *) {
            let topOpacity = 0.12 * intensity
            let midOpacity = 0.02 * intensity
            let shadowOpacity = 0.20 * intensity

            content
                .overlay {
                    RoundedRectangle(cornerRadius: radius, style: .continuous)
                        .strokeBorder(
                            LinearGradient(
                                colors: [
                                    .white.opacity(topOpacity),
                                    .white.opacity(midOpacity),
                                    .clear,
                                ],
                                startPoint: .top,
                                endPoint: .bottom
                            ),
                            lineWidth: 0.75
                        )
                }
                .shadow(color: .black.opacity(shadowOpacity), radius: 2.0, y: 2.0)
        } else {
            content
        }
        #else
        content
        #endif
    }
}

struct SectionHeaderStyle: ViewModifier {
    func body(content: Content) -> some View {
        content
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(.secondary)
    }
}

struct GlowingGradientButtonStyle: ButtonStyle {
    let baseColor: Color
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.generationPerformanceGate) private var performanceGate

    func makeBody(configuration: Configuration) -> some View {
        #if QW_UI_LIQUID
        if #available(macOS 26, *), !reduceTransparency, !performanceGate {
            configuration.label
                .font(.body.weight(.semibold))
                .foregroundStyle(.white)
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .glassEffect(.regular.tint(baseColor), in: .rect(cornerRadius: 8))
                .opacity(configuration.isPressed ? 0.75 : 1.0)
                .appAnimation(.easeInOut(duration: 0.15), value: configuration.isPressed)
        } else {
            legacyBody(configuration: configuration)
        }
        #else
        legacyBody(configuration: configuration)
        #endif
    }

    private func legacyBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.semibold))
            .foregroundStyle(.white)
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(baseColor.opacity(configuration.isPressed ? 0.75 : 0.95))
            )
            .appAnimation(.easeInOut(duration: 0.15), value: configuration.isPressed)
    }
}

struct CompactGenerateButtonStyle: ButtonStyle {
    let baseColor: Color
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.generationPerformanceGate) private var performanceGate

    func makeBody(configuration: Configuration) -> some View {
        #if QW_UI_LIQUID
        if #available(macOS 26, *), !reduceTransparency, !performanceGate {
            configuration.label
                .foregroundStyle(.white)
                .padding(12)
                .glassEffect(.regular.tint(baseColor), in: .circle)
                .opacity(configuration.isPressed ? 0.75 : 1.0)
                .appAnimation(.easeInOut(duration: 0.15), value: configuration.isPressed)
        } else {
            legacyBody(configuration: configuration)
        }
        #else
        legacyBody(configuration: configuration)
        #endif
    }

    private func legacyBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(.white)
            .padding(12)
            .background(
                Circle()
                    .fill(baseColor.opacity(configuration.isPressed ? 0.75 : 0.95))
            )
            .appAnimation(.easeInOut(duration: 0.15), value: configuration.isPressed)
    }
}

struct AuroraBackground: View {
    var body: some View {
        #if QW_UI_LIQUID
        if #available(macOS 26, *) {
            LinearGradient(
                colors: [
                    Color(red: 0.06, green: 0.07, blue: 0.09),
                    Color(red: 0.10, green: 0.11, blue: 0.13),
                ],
                startPoint: .top,
                endPoint: .bottom
            ).ignoresSafeArea()
        } else {
            AppTheme.canvasBackground.ignoresSafeArea()
        }
        #else
        AppTheme.canvasBackground.ignoresSafeArea()
        #endif
    }
}

struct EmptyStateStyle: ViewModifier {
    func body(content: Content) -> some View {
        content.foregroundStyle(.secondary)
    }
}

extension View {
    func toolbarRow(_ label: String) -> some View {
        modifier(ToolbarRowStyle(label: label))
    }

    func sectionHeader() -> some View {
        modifier(SectionHeaderStyle())
    }

    func emptyStateStyle() -> some View {
        modifier(EmptyStateStyle())
    }
}

// MARK: - Studio GroupBox Style (material-based legacy fallback)

struct StudioGroupBoxStyle: GroupBoxStyle {
    func makeBody(configuration: Configuration) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            configuration.label
            configuration.content
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(AppTheme.cardFill)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(
                    AppTheme.cardStroke.opacity(0.20),
                    lineWidth: 0.5
                )
        )
    }
}

// MARK: - Liquid Glass Convenience Extensions

#if QW_UI_LIQUID
@available(macOS 26, *)
struct GlassGroupBoxStyle: GroupBoxStyle {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.generationPerformanceGate) private var performanceGate
    @Environment(\.cardGlassTint) private var cardGlassTint

    func makeBody(configuration: Configuration) -> some View {
        if reduceTransparency || performanceGate {
            VStack(alignment: .leading, spacing: 8) {
                configuration.label
                configuration.content
            }
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(AppTheme.cardFill)
                    .overlay(
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .strokeBorder(
                                AppTheme.cardStroke.opacity(AppTheme.surfaceStrokeOpacity),
                                lineWidth: AppTheme.surfaceStrokeWidth
                            )
                    )
            )
        } else {
            let resolvedTint: Color = cardGlassTint.map {
                AppTheme.surfaceGlassTint($0)
            } ?? AppTheme.smokedGlassTint
            let resolvedStroke: Color = cardGlassTint.map {
                AppTheme.accentStroke($0).opacity(0.55)
            } ?? AppTheme.cardStroke.opacity(AppTheme.surfaceStrokeOpacity)
            let depthIntensity: Double = cardGlassTint == nil ? 1.0 : 1.15
            VStack(alignment: .leading, spacing: 8) {
                configuration.label
                configuration.content
            }
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(AppTheme.cardFill)
                    .overlay(
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .strokeBorder(
                                resolvedStroke,
                                lineWidth: AppTheme.surfaceStrokeWidth
                            )
                    )
            )
            .glassEffect(.regular.tint(resolvedTint), in: .rect(cornerRadius: 16))
            .glass3DDepth(radius: 16, intensity: depthIntensity)
        }
    }
}
#endif

extension View {
    /// Wraps content in a GlassEffectContainer on liquid builds.
    @ViewBuilder
    func liquidGlassContainer(spacing: CGFloat = 8) -> some View {
        #if QW_UI_LIQUID
        if #available(macOS 26, *) {
            GlassEffectContainer(spacing: spacing) { self }
        } else { self }
        #else
        self
        #endif
    }

    /// Profile-aware background: clear for liquid, specified color for legacy.
    @ViewBuilder
    func profileBackground(_ legacyColor: Color) -> some View {
        #if QW_UI_LIQUID
        if #available(macOS 26, *) {
            self.background(AppTheme.canvasBackground)
        } else {
            self.background(legacyColor)
        }
        #else
        self.background(legacyColor)
        #endif
    }

    /// Applies profile-aware GroupBox style.
    @ViewBuilder
    func profileGroupBoxStyle() -> some View {
        #if QW_UI_LIQUID
        if #available(macOS 26, *) {
            self.groupBoxStyle(GlassGroupBoxStyle())
        } else {
            self.groupBoxStyle(StudioGroupBoxStyle())
        }
        #else
        self.groupBoxStyle(.automatic)
        #endif
    }

    /// Profile-aware glass capsule badge background.
    @ViewBuilder
    func glassBadge(tint: Color? = nil) -> some View {
        modifier(GlassBadgeStyle(tint: tint))
    }

    /// Profile-aware glass text field background with 3D depth.
    @ViewBuilder
    func glassTextField(
        radius: CGFloat = 8,
        strokeColor: Color? = nil
    ) -> some View {
        modifier(GlassTextFieldStyle(radius: radius, strokeColor: strokeColor))
    }

    /// Adds 3D depth to glass surfaces: top-edge highlight gradient + drop shadow.
    @ViewBuilder
    func glass3DDepth(radius: CGFloat = 12, intensity: Double = 1.0) -> some View {
        modifier(Glass3DDepthStyle(radius: radius, intensity: intensity))
    }

}

// MARK: - Mode-aware Liquid Glass tinting

/// Environment key injected by each generation screen (Custom Voice,
/// Voice Design, Voice Cloning) so downstream card surfaces
/// (`StudioSectionCard`, `CompactConfigurationSection`) pick up a
/// Vocello-mode-colored glass tint without every view taking an
/// explicit color parameter. A `nil` value preserves the default
/// `AppTheme.smokedGlassTint` treatment used by neutral surfaces
/// (Library, Settings, Models).
private struct CardGlassTintKey: EnvironmentKey {
    static let defaultValue: Color? = nil
}

extension EnvironmentValues {
    var cardGlassTint: Color? {
        get { self[CardGlassTintKey.self] }
        set { self[CardGlassTintKey.self] = newValue }
    }
}

extension View {
    /// Tag a subtree so every Liquid-Glass card surface underneath uses a
    /// subtle mode-colored tint (warm golden on Custom Voice, lavender
    /// purple on Voice Design, terracotta on Voice Cloning). Resolves to
    /// the neutral smoked tint when unset or when mode color is nil.
    func modeGlassTint(_ color: Color?) -> some View {
        environment(\.cardGlassTint, color)
    }

    /// Layers a subtle radial wash of the mode color at the top of the
    /// content canvas so Liquid Glass above it has something to refract —
    /// otherwise glass panels sit on a flat charcoal and the glass effect
    /// reads as a flat tint rather than a material.
    func modeCanvasBackdrop(_ color: Color?) -> some View {
        background(ModeCanvasBackdrop(color: color))
    }
}

private struct ModeCanvasBackdrop: View {
    let color: Color?

    var body: some View {
        GeometryReader { geo in
            ZStack {
                AppTheme.canvasBackground
                if let color {
                    // Top-center radial glow in mode color — strong enough
                    // to give Liquid Glass a gradient to refract, subtle
                    // enough not to fight the content.
                    RadialGradient(
                        colors: [
                            color.opacity(0.18),
                            color.opacity(0)
                        ],
                        center: .init(x: 0.5, y: -0.05),
                        startRadius: 0,
                        endRadius: max(geo.size.width, geo.size.height) * 0.75
                    )
                    .blendMode(.plusLighter)
                    .allowsHitTesting(false)
                }
            }
        }
        .ignoresSafeArea()
    }
}
