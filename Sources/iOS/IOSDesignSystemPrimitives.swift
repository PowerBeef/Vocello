import SwiftUI
import UIKit
import QwenVoiceCore

// Primitives introduced by the May 2026 Vocello iOS redesign reference.
// Lives alongside `IOSShellPrimitives.swift`; that file holds the
// older chrome (cards, badges, status strips). This one holds the new
// shared building blocks used by the unified Studio, the Player sheet, the
// Voices tab, and the bottom-sheet family.
//
// Token sources:
// - design_references/Vocello iOS/tokens.css (--radius-*, --space-*, --ease-out)
// - design_references/Vocello Design System/colors_and_type.css (colors,
//   shadows, surface ramp, stroke values)

// MARK: - Mode backdrop

/// Warm mode-tinted wash behind the Studio + Player sheet. Anchored to
/// the top of the container; fades to clear by mid-screen. Mirrors
/// `.vc-mode-backdrop` (`design_references/Vocello iOS/app.css:36-48`),
/// including the CSS `mix-blend-mode: plus-lighter` semantics via
/// `.blendMode(.plusLighter)`.
/// Forwards to the shared `VocelloModeBackdrop`; macOS draws the same wash
/// behind its Studio screens. The recipe moved unchanged, so this type keeps
/// its name, its intensity cases and its Reduce Transparency source.
struct IOSModeBackdrop: View {
    let tint: Color
    let intensity: VocelloModeBackdrop.Intensity

    @Environment(\.iosReduceTransparencyEnabled) private var reduceTransparency

    typealias Intensity = VocelloModeBackdrop.Intensity

    init(tint: Color, intensity: VocelloModeBackdrop.Intensity = .warm) {
        self.tint = tint
        self.intensity = intensity
    }

    var body: some View {
        VocelloModeBackdrop(
            tint: tint,
            intensity: intensity,
            reduceTransparency: reduceTransparency
        )
    }
}

// MARK: - Waveform bars

/// The shared FNV-1a visual seed hash
/// (`Sources/SharedSupport/Views/VocelloStableVisualHash.swift`, UIF-02).
typealias IOSStableVisualHash = VocelloStableVisualHash

/// Static or playback-driven waveform bars. Deterministic heights from a
/// seed so repeated renders match. Used by mini-waveform thumbnails
/// (History rows), the inline player in Studio, and the full Player sheet.
///
/// Per `design_references/Vocello iOS/chrome.jsx` MiniWaveform / PlayerWaveform.
struct IOSWaveformBars: View {
    enum Style: Equatable {
        case mini
        case player
        case big

        var minimumAmplitude: Double {
            switch self {
            case .mini: return 0.16
            case .player: return 0.12
            case .big: return 0.15
            }
        }

        var maximumAmplitude: Double {
            switch self {
            case .mini: return 0.95
            case .player: return 0.96
            case .big: return 0.95
            }
        }

        var spacing: CGFloat {
            switch self {
            case .mini: return 1.5
            case .player: return 2.0
            case .big: return 3.5
            }
        }

        var cornerRadius: CGFloat {
            switch self {
            case .mini: return 1.0
            case .player: return 1.5
            case .big: return 2.5
            }
        }

        var minimumBarWidth: CGFloat {
            switch self {
            case .mini, .player: return 2.0
            case .big: return 3.0
            }
        }
    }

    /// Which streaming band a bar belongs to. With `bufferedProgress == nil` only
    /// `.played`/`.tail` occur (the buffered band is empty), so rendering is identical
    /// to the pre-streaming two-band waveform.
    private enum Band { case played, buffered, tail }

    let seed: Int
    let barCount: Int
    let tint: Color
    let progress: Double
    let isAnimating: Bool
    let unplayedColor: Color?
    let style: Style
    /// Absolute generated fraction (0…1) for the live streaming preview: bars between
    /// `progress` (playhead) and `bufferedProgress` render as "generated, not yet played",
    /// and bars beyond it are the not-yet-generated tail (animated when streaming). `nil`
    /// (the default) means "not streaming" → pixel-identical to the prior two-band render.
    let bufferedProgress: Double?

    @Environment(\.iosReduceTransparencyEnabled) private var reduceTransparency

    init(
        seed: Int,
        barCount: Int = 24,
        tint: Color,
        progress: Double = 1.0,
        isAnimating: Bool = false,
        unplayedColor: Color? = nil,
        style: Style = .mini,
        bufferedProgress: Double? = nil
    ) {
        self.seed = seed
        self.barCount = barCount
        self.tint = tint
        self.progress = progress
        self.isAnimating = isAnimating
        self.unplayedColor = unplayedColor
        self.style = style
        self.bufferedProgress = bufferedProgress
    }

    var body: some View {
        // Only `.big` consumes `phase` (see amplitude(at:phase:)); `.mini`/`.player`
        // render identical frames every tick, so animating them is pure churn. Gate the
        // per-frame TimelineView to `.big` and cap it to ~24fps (vsync-aligned). The
        // generating dock + recording overlay (.mini) and history thumbnails (.player)
        // fall through to a single static draw — pixel-identical, zero per-frame cost.
        // `.big` always animates when asked; `.player` animates ONLY while streaming
        // (a tail breathing on the not-yet-generated bars). `.mini` + the static
        // `bufferedProgress == nil` `.player` fall through to one static draw — zero per-frame cost.
        if isAnimating && (style == .big || (style == .player && bufferedProgress != nil)) {
            TimelineView(.animation(minimumInterval: 1.0 / 24.0)) { context in
                bars(phase: context.date.timeIntervalSinceReferenceDate)
            }
        } else {
            bars(phase: 0)
        }
    }

    private func bars(phase: TimeInterval) -> some View {
        GeometryReader { geo in
            let spacing = style.spacing
            let totalSpacing = spacing * CGFloat(barCount - 1)
            let fittedBarWidth = (geo.size.width - totalSpacing) / CGFloat(barCount)
            let barWidth = resolvedBarWidth(fitted: fittedBarWidth)
            let playhead = min(max(progress, 0), 1)
            let buffered = max(playhead, min(bufferedProgress ?? playhead, 1))
            let playheadIndex = Int((Double(barCount) * playhead).rounded())
            let bufferedIndex = Int((Double(barCount) * buffered).rounded())
            let tailAnimated = isAnimating && style == .player && bufferedProgress != nil
            let showsPlayhead = bufferedProgress != nil && style == .player

            ZStack(alignment: .leading) {
                HStack(alignment: .center, spacing: spacing) {
                    ForEach(0..<barCount, id: \.self) { i in
                        let band: Band = i < playheadIndex ? .played : (i < bufferedIndex ? .buffered : .tail)
                        let amp = amplitude(at: i, phase: phase)
                        let height = max(2, geo.size.height * CGFloat(amp))
                        RoundedRectangle(cornerRadius: style.cornerRadius, style: .continuous)
                            .fill(fillStyle(band: band))
                            .opacity(renderOpacity(at: i, band: band, amplitude: amp, phase: phase, tailAnimated: tailAnimated))
                            .frame(width: barWidth, height: height)
                    }
                }
                .frame(width: geo.size.width, height: geo.size.height, alignment: .center)

                // Streaming-only playhead: marks the playback position and crisply separates the
                // bright "played" tier from the dimmer "generated-ahead" tier.
                if showsPlayhead {
                    playheadMarker(height: geo.size.height)
                        .offset(x: playhead * geo.size.width - playheadMarkerWidth / 2)
                }
            }
        }
    }

    private var playheadMarkerWidth: CGFloat { 2.5 }

    private func playheadMarker(height: CGFloat) -> some View {
        Capsule(style: .continuous)
            .fill(Color.white.opacity(0.92))
            .frame(width: playheadMarkerWidth, height: height)
            .shadow(color: reduceTransparency ? .clear : tint.opacity(0.6), radius: 3)
    }

    private func resolvedBarWidth(fitted: CGFloat) -> CGFloat {
        if style == .mini {
            return style.minimumBarWidth
        }
        return max(style.minimumBarWidth, fitted)
    }

    // A gentle traveling wave used to softly shimmer the not-yet-generated tail while streaming.
    private func tailWave(_ index: Int, phase: TimeInterval) -> Double {
        sin(phase * 2.2 + Double(index) * 0.55)
    }

    private func renderOpacity(at index: Int, band: Band, amplitude: Double, phase: TimeInterval, tailAnimated: Bool) -> Double {
        // Streaming tail reads as faint/incoming (a soft shimmer when animating); the completed
        // card's unplayed tail keeps its prior 0.55 via `opacity(band:)`.
        if band == .tail, bufferedProgress != nil {
            return tailAnimated ? 0.30 + 0.10 * tailWave(index, phase: phase) : 0.30
        }
        return opacity(band: band, amplitude: amplitude)
    }

    private func fillStyle(band: Band) -> AnyShapeStyle {
        switch band {
        case .played, .buffered:
            let bottomOpacity: Double = style == .big ? 0.60 : 0.70
            return AnyShapeStyle(
                LinearGradient(
                    colors: [
                        tint,
                        tint.opacity(bottomOpacity),
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
            )
        case .tail:
            return AnyShapeStyle(unplayedColor ?? Color.white.opacity(style == .big ? 0.14 : 0.18))
        }
    }

    private func opacity(band: Band, amplitude: Double) -> Double {
        switch style {
        case .mini:
            return 0.4 + amplitude * 0.5
        case .player:
            switch band {
            case .played: return 1.0
            case .buffered: return 0.50   // generated, ahead of the playhead — a clear step below played
            case .tail: return 0.55       // completed-card unplayed tail (streaming tail is dimmer via renderOpacity)
            }
        case .big:
            return band == .played ? 1.0 : 0.65
        }
    }

    private func amplitude(at index: Int, phase: TimeInterval) -> Double {
        let i = Double(index)
        let base: Double
        switch style {
        case .mini:
            let raw = sin((Double(seed) * 13 + i * 7.31) * 1.3) * 0.4 + 0.5
            base = abs(raw) + Double(index % 5) * 0.08
        case .player:
            let raw = sin((Double(seed) * 11 + i * 6.7) * 1.6) * 0.45 + 0.5
            base = abs(raw)
        case .big:
            let raw = sin(i * 6.7) * 0.45 + 0.5
            if isAnimating {
                let waveSeed = phase * 18
                let pulse = 1
                    + sin((waveSeed * 0.5 + i * 0.7)) * 0.18
                    + sin((waveSeed * 0.3 + i * 1.4)) * 0.10
                base = abs(raw) * pulse
            } else {
                base = abs(raw)
            }
        }
        return max(style.minimumAmplitude, min(style.maximumAmplitude, base))
    }
}

/// Fixed-size history-row waveform thumbnail; the body lives in the shared
/// `VocelloStaticWaveformThumbnail` (UIF-02).
typealias IOSStaticWaveformThumbnail = VocelloStaticWaveformThumbnail

/// Circular icon chrome for the player and row controls; the body lives in
/// the shared `VocelloIconButtonChrome` (UIF-02) with the phone's 40 / 16 pt
/// defaults.
typealias IOSPlayerIconButtonChrome = VocelloIconButtonChrome

// MARK: - Voice avatar

/// Circular gradient avatar for built-in or saved voices; the body lives in
/// the shared `VocelloVoiceAvatar` (UIF-02).
typealias IOSVoiceAvatar = VocelloVoiceAvatar

// MARK: - Mode dot

/// 6×6 colored dot used in History row meta + filter chips; the body lives in
/// the shared `VocelloModeDot` (UIF-02).
typealias IOSModeDot = VocelloModeDot

// MARK: - Bottom sheet

enum IOSBottomSheetChrome {
    static let background = Color(red: 20 / 255, green: 22 / 255, blue: 30 / 255).opacity(0.92)
    static let cornerRadius: CGFloat = 22
    static let voicePickerHeight: CGFloat = 430
    static let deliveryPickerHeight: CGFloat = 470
    static let referenceClipHeight: CGFloat = 430
    static let modelInstallHeight: CGFloat = 430

    /// Height for the expanded selector pickers (voice / delivery / language / reference):
    /// the sheet rises to just BELOW the Studio mode selector (Custom/Design/Clone), leaving
    /// it + the status bar visible above for a balanced look (still tap-to-dismiss).
    /// `screenHeight` is the FULL window height (from the bottom-panel overlay's GeometryReader,
    /// which ignores the safe area), so the subtracted value is the sheet-top y. 116 ≈ top safe
    /// inset (~59) + the selector's 6pt top pad + 44pt rail + ~7pt gap. Clamped so it never
    /// collapses. (Tuned for the 17 Pro; ~12pt looser on notch devices.)
    static func expandedHeight(forScreenHeight screenHeight: CGFloat) -> CGFloat {
        max(440, screenHeight - 116)
    }
}

enum IOSBottomSheetPresentationStyle {
    case system
    case edgeToEdge(bottomSafeAreaInset: CGFloat, height: CGFloat? = nil)
}

struct IOSBottomSheetSurface<Content: View>: View {
    let title: String
    let tint: Color
    let presentation: IOSBottomSheetPresentationStyle
    let onDismiss: (() -> Void)?
    let headerLeading: AnyView?
    let headerTrailing: AnyView?
    let content: Content

    init(
        title: String,
        tint: Color = Theme.Brand.gold,
        presentation: IOSBottomSheetPresentationStyle = .system,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.tint = tint
        self.presentation = presentation
        self.onDismiss = onDismiss
        self.headerLeading = nil
        self.headerTrailing = nil
        self.content = content()
    }

    init<Trailing: View>(
        title: String,
        tint: Color = Theme.Brand.gold,
        presentation: IOSBottomSheetPresentationStyle = .system,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder headerTrailing: () -> Trailing,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.tint = tint
        self.presentation = presentation
        self.onDismiss = onDismiss
        self.headerLeading = nil
        self.headerTrailing = AnyView(headerTrailing())
        self.content = content()
    }

    init<Leading: View, Trailing: View>(
        title: String,
        tint: Color = Theme.Brand.gold,
        presentation: IOSBottomSheetPresentationStyle = .system,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder headerLeading: () -> Leading,
        @ViewBuilder headerTrailing: () -> Trailing,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.tint = tint
        self.presentation = presentation
        self.onDismiss = onDismiss
        self.headerLeading = AnyView(headerLeading())
        self.headerTrailing = AnyView(headerTrailing())
        self.content = content()
    }

    var body: some View {
        switch presentation {
        case .system:
            if headerLeading != nil || headerTrailing != nil {
                IOSBottomSheet(
                    title: title,
                    tint: tint,
                    onDismiss: onDismiss,
                    headerLeading: { headerLeading },
                    headerTrailing: { headerTrailing }
                ) {
                    content
                }
            } else if let headerTrailing {
                IOSBottomSheet(title: title, tint: tint, onDismiss: onDismiss, headerTrailing: { headerTrailing }) {
                    content
                }
            } else {
                IOSBottomSheet(title: title, tint: tint, onDismiss: onDismiss) {
                    content
                }
            }
        case .edgeToEdge(let bottomSafeAreaInset, let height):
            if headerLeading != nil || headerTrailing != nil {
                IOSBottomEdgeSheet(
                    title: title,
                    tint: tint,
                    bottomSafeAreaInset: bottomSafeAreaInset,
                    height: height,
                    onDismiss: { onDismiss?() },
                    headerLeading: { headerLeading },
                    headerTrailing: { headerTrailing }
                ) {
                    content
                }
            } else if let headerTrailing {
                IOSBottomEdgeSheet(
                    title: title,
                    tint: tint,
                    bottomSafeAreaInset: bottomSafeAreaInset,
                    height: height,
                    onDismiss: { onDismiss?() },
                    headerTrailing: { headerTrailing }
                ) {
                    content
                }
            } else {
                IOSBottomEdgeSheet(
                    title: title,
                    tint: tint,
                    bottomSafeAreaInset: bottomSafeAreaInset,
                    height: height,
                    onDismiss: { onDismiss?() }
                ) {
                    content
                }
            }
        }
    }
}

struct IOSTopRoundedRectangle: InsettableShape {
    var cornerRadius: CGFloat
    var insetAmount: CGFloat = 0

    func path(in rect: CGRect) -> Path {
        let rect = rect.insetBy(dx: insetAmount, dy: insetAmount)
        let radius = min(cornerRadius, rect.width / 2, rect.height / 2)

        var path = Path()
        path.move(to: CGPoint(x: rect.minX, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX, y: rect.minY + radius))
        path.addQuadCurve(
            to: CGPoint(x: rect.minX + radius, y: rect.minY),
            control: CGPoint(x: rect.minX, y: rect.minY)
        )
        path.addLine(to: CGPoint(x: rect.maxX - radius, y: rect.minY))
        path.addQuadCurve(
            to: CGPoint(x: rect.maxX, y: rect.minY + radius),
            control: CGPoint(x: rect.maxX, y: rect.minY)
        )
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY))
        path.closeSubpath()
        return path
    }

    func inset(by amount: CGFloat) -> IOSTopRoundedRectangle {
        var copy = self
        copy.insetAmount += amount
        return copy
    }
}

struct IOSBottomEdgeSheet<Content: View>: View {
    let title: String
    let tint: Color
    let bottomSafeAreaInset: CGFloat
    let height: CGFloat?
    let onDismiss: () -> Void
    let headerLeading: AnyView?
    let headerTrailing: AnyView?
    let content: Content

    init(
        title: String,
        tint: Color = Theme.Brand.gold,
        bottomSafeAreaInset: CGFloat,
        height: CGFloat? = nil,
        onDismiss: @escaping () -> Void,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.tint = tint
        self.bottomSafeAreaInset = bottomSafeAreaInset
        self.height = height
        self.onDismiss = onDismiss
        self.headerLeading = nil
        self.headerTrailing = nil
        self.content = content()
    }

    init<Trailing: View>(
        title: String,
        tint: Color = Theme.Brand.gold,
        bottomSafeAreaInset: CGFloat,
        height: CGFloat? = nil,
        onDismiss: @escaping () -> Void,
        @ViewBuilder headerTrailing: () -> Trailing,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.tint = tint
        self.bottomSafeAreaInset = bottomSafeAreaInset
        self.height = height
        self.onDismiss = onDismiss
        self.headerLeading = nil
        self.headerTrailing = AnyView(headerTrailing())
        self.content = content()
    }

    init<Leading: View, Trailing: View>(
        title: String,
        tint: Color = Theme.Brand.gold,
        bottomSafeAreaInset: CGFloat,
        height: CGFloat? = nil,
        onDismiss: @escaping () -> Void,
        @ViewBuilder headerLeading: () -> Leading,
        @ViewBuilder headerTrailing: () -> Trailing,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.tint = tint
        self.bottomSafeAreaInset = bottomSafeAreaInset
        self.height = height
        self.onDismiss = onDismiss
        self.headerLeading = AnyView(headerLeading())
        self.headerTrailing = AnyView(headerTrailing())
        self.content = content()
    }

    var body: some View {
        let shape = IOSTopRoundedRectangle(cornerRadius: IOSBottomSheetChrome.cornerRadius)
        let panel = VStack(spacing: 0) {
            // D8: the grabber advertises drag-dismiss, so the grabber +
            // header zone honors it (a committed downward drag or flick).
            // The gesture stays off the content, whose scroll must win.
            VStack(spacing: 0) {
                grabber
                    .padding(.top, 8)

                header
                    .padding(.horizontal, 20)
                    .padding(.top, 12)
                    .padding(.bottom, 10)
            }
            .contentShape(Rectangle())
            .gesture(dismissDragGesture)

            content
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.bottom, resolvedBottomSafeAreaInset)
        .frame(
            maxWidth: .infinity,
            minHeight: height,
            idealHeight: height,
            maxHeight: height,
            alignment: .top
        )

        // Gate decision shared with every other glass surface (IUI-5 D10a);
        // the gated branch paints this panel's solid backing via gatedFill.
        panel.iosGatedGlass(
            tint: Theme.glassTint(tint, intensity: 0.45),
            in: shape,
            gatedFill: Color(red: 20 / 255, green: 22 / 255, blue: 30 / 255)
        )
        .clipShape(shape)
        .overlay {
            shape
                .stroke(Color.white.opacity(0.12), lineWidth: 0.5)
                .allowsHitTesting(false)
        }
        .overlay {
            shape
                .inset(by: 0.7)
                .stroke(Color.white.opacity(0.07), lineWidth: 0.55)
                .allowsHitTesting(false)
        }
        .shadow(color: Color.black.opacity(0.34), radius: 30, x: 0, y: -10)
    }

    private var grabber: some View {
        Capsule(style: .continuous)
            .fill(Color.white.opacity(0.20))
            .frame(width: 36, height: 5)
    }

    private var dismissDragGesture: some Gesture {
        DragGesture(minimumDistance: 12)
            .onEnded { value in
                if value.translation.height > 48 || value.predictedEndTranslation.height > 120 {
                    onDismiss()
                }
            }
    }

    private var resolvedBottomSafeAreaInset: CGFloat {
        max(bottomSafeAreaInset, 34)
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 12) {
            if let headerLeading {
                headerLeading
            }

            Text(title)
                .iosScaledFont(size: 22, weight: .bold, relativeTo: .title2)
                .tracking(-0.44)
                .foregroundStyle(Theme.Text.primary)
                .frame(maxWidth: .infinity, alignment: .leading)

            if let headerTrailing {
                headerTrailing
            } else {
                Button {
                    onDismiss()
                } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 18, weight: .regular))
                        .foregroundStyle(Theme.Text.primary)
                        .frame(width: 40, height: 40)
                        .background {
                            Circle()
                                .fill(Color.white.opacity(0.06))
                        }
                        .overlay {
                            Circle()
                                .stroke(Color.white.opacity(0.10), lineWidth: 0.5)
                        }
                }
                .buttonStyle(.plain)
                .accessibilityLabel(IOSInterfaceText.close)
                .accessibilityIdentifier("bottomSheet_close")
            }
        }
    }
}

/// Reusable bottom sheet container. Drag-to-dismiss via a grabber. Uses the
/// system `.presentationDetents` when presented as a sheet, but the visual
/// chrome (glass surface, grabber, title) is provided here so the look is
/// consistent across pickers.
///
/// Caller wraps in `.sheet(isPresented:)` modifier; this view supplies the
/// content. For drag-to-dismiss the system sheet already handles it.
struct IOSBottomSheet<Content: View>: View {
    let title: String
    let tint: Color
    let onDismiss: (() -> Void)?
    let headerLeading: AnyView?
    let headerTrailing: AnyView?
    let content: Content

    @Environment(\.dismiss) private var dismiss

    init(
        title: String,
        tint: Color = Theme.Brand.gold,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.tint = tint
        self.onDismiss = onDismiss
        self.headerLeading = nil
        self.headerTrailing = nil
        self.content = content()
    }

    init<Trailing: View>(
        title: String,
        tint: Color = Theme.Brand.gold,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder headerTrailing: () -> Trailing,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.tint = tint
        self.onDismiss = onDismiss
        self.headerLeading = nil
        self.headerTrailing = AnyView(headerTrailing())
        self.content = content()
    }

    init<Leading: View, Trailing: View>(
        title: String,
        tint: Color = Theme.Brand.gold,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder headerLeading: () -> Leading,
        @ViewBuilder headerTrailing: () -> Trailing,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.tint = tint
        self.onDismiss = onDismiss
        self.headerLeading = AnyView(headerLeading())
        self.headerTrailing = AnyView(headerTrailing())
        self.content = content()
    }

    var body: some View {
        VStack(spacing: 0) {
            grabber
                .padding(.top, 8)

            header
                .padding(.horizontal, 20)
                .padding(.top, 12)
                .padding(.bottom, 10)

            content
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background {
            IOSBottomSheetChrome.background
                .ignoresSafeArea()
        }
        // R3 G.0 (2026-05-21): the per-sheet `IOSModeBackdrop` was a
        // whisper-intensity radial wash that added a hue to every
        // bottom sheet. Design's `.vc-sheet { background: rgba(20,22,
        // 30,0.92) + blur 32 }` is flat translucent dark with no
        // tint — the sheets read cleaner that way and the dock above
        // already carries the mode hue.
    }

    private var grabber: some View {
        // 36 × 5 pt per app.css `.vc-sheet-grabber`.
        Capsule(style: .continuous)
            .fill(Color.white.opacity(0.20))
            .frame(width: 36, height: 5)
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 12) {
            if let headerLeading {
                headerLeading
            }

            Text(title)
                .iosScaledFont(size: 22, weight: .bold, relativeTo: .title2)
                .tracking(-0.44)
                .foregroundStyle(Theme.Text.primary)
                .frame(maxWidth: .infinity, alignment: .leading)

            if let headerTrailing {
                headerTrailing
            } else {
                Button {
                    onDismiss?()
                    dismiss()
                } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 18, weight: .regular))
                        .foregroundStyle(Theme.Text.primary)
                        .frame(width: 40, height: 40)
                        .background {
                            Circle()
                                .fill(Color.white.opacity(0.06))
                        }
                        .overlay {
                            Circle()
                                .stroke(Color.white.opacity(0.10), lineWidth: 0.5)
                        }
                }
                .accessibilityLabel(IOSInterfaceText.close)
                .accessibilityIdentifier("bottomSheet_close")
            }
        }
    }
}

// MARK: - Setup chip

/// Studio selector pill. Keeps the orb's lit-tint styling (tint gradient fill,
/// glass strokes, soft tint glow) but in a full-width capsule showing the SF
/// Symbol on the left + a two-letter UPPERCASE abbreviation of the current
/// selection on the right (e.g. `person.fill` + "AI"). The 2-or-3 pills are
/// equal-width and fill the setup row so they span the Generate button's width
/// (see `IOSStudioCanvas.setupRow`). The full value + category ("Voice: Aiden")
/// live in the VoiceOver label and the picker that tapping opens.
///
/// DP-15 pinned-seed chip: visible only while a seed is pinned, in which
/// case every take reproduces that seed with identical settings. Tapping
/// offers the unpin (back to a fresh seed per take). Pinning itself happens
/// from a History row's "Pin seed" action — this chip owns no other state.
struct IOSSeedPinChip: View {
    @Binding var pinnedSeed: UInt64?
    let tint: Color

    @State private var isConfirmingUnpin = false

    var body: some View {
        if let seedValue = pinnedSeed {
            IOSStudioSetupChip(
                eyebrow: IOSInterfaceText.seed,
                value: String(seedValue),
                abbreviation: "PN",
                leadingSymbol: "pin.fill",
                tint: tint,
                accessibilityID: "studioChip_seedPin",
                action: { isConfirmingUnpin = true }
            )
            .confirmationDialog(
                "Seed \(String(seedValue)) is pinned — every take reproduces it with the same settings.",
                isPresented: $isConfirmingUnpin,
                titleVisibility: .visible
            ) {
                Button(IOSInterfaceText.unpinSeed) {
                    IOSHaptics.selection()
                    pinnedSeed = nil
                }
                Button(IOSInterfaceText.keepPinned, role: .cancel) {}
            }
        }
    }
}

/// Uses the app's tinted language via `IOSSetupChipPill`. `IOSVoiceAvatar` is
/// no longer used here (the voice slot is a symbol pill like the others).
struct IOSStudioSetupChip: View {
    /// Shared avatar diameter — voice avatars elsewhere align to this.
    static let iconDiameter: CGFloat = 54
    /// Pill height for the selector row.
    static let pillHeight: CGFloat = 46

    let eyebrow: String        // category — VoiceOver label only, not rendered
    let value: String          // full value — VoiceOver label only, not rendered
    let abbreviation: String   // rendered 2-letter (UPPERCASE) badge
    let leadingSymbol: String
    let tint: Color
    let isPlaceholder: Bool
    let accessibilityID: String?
    let action: () -> Void

    init(
        eyebrow: String,
        value: String,
        abbreviation: String,
        leadingSymbol: String,
        tint: Color = Theme.Brand.gold,
        isPlaceholder: Bool = false,
        accessibilityID: String? = nil,
        action: @escaping () -> Void
    ) {
        self.eyebrow = eyebrow
        self.value = value
        self.abbreviation = abbreviation
        self.leadingSymbol = leadingSymbol
        self.tint = tint
        self.isPlaceholder = isPlaceholder
        self.accessibilityID = accessibilityID
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            IOSSetupChipPill(
                symbol: leadingSymbol,
                abbreviation: abbreviation,
                tint: tint,
                isPlaceholder: isPlaceholder
            )
            // Placeholder (unset reference / brief) reads dimmer. The pill
            // expands to fill its equal share of the row (see setupRow).
            .opacity(isPlaceholder ? 0.55 : 1)
            .frame(maxWidth: .infinity)
            .contentShape(Capsule(style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(eyebrow): \(value)")
        .accessibilityAddTraits(.isButton)
        .iosAccessibilityIdentifier(accessibilityID)
    }
}

/// Premium "lit tinted" pill used by the Studio setup chips: the shared
/// `VocelloSetupChipPill` chrome (UIF-02) with the phone's label — an SF
/// Symbol + a two-letter abbreviation, or a "+" for an unset slot. Honors
/// Reduce Transparency through the iOS environment key.
struct IOSSetupChipPill: View {
    let symbol: String
    let abbreviation: String
    let tint: Color
    var isPlaceholder: Bool = false
    var height: CGFloat = IOSStudioSetupChip.pillHeight

    @Environment(\.iosReduceTransparencyEnabled) private var reduceTransparency

    var body: some View {
        VocelloSetupChipPill(
            symbol: symbol,
            tint: tint,
            height: height,
            reduceTransparency: reduceTransparency
        ) {
            if isPlaceholder {
                // Unset slot: a "+" add affordance instead of a value abbreviation.
                Image(systemName: "plus")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Theme.Text.primary)
            } else {
                Text(abbreviation)
                    .font(.subheadline.weight(.semibold))
                    .tracking(0.5)
                    // Tint remains in the capsule fill, stroke, and glow. Repeating the
                    // same hue as foreground can fall below 3:1 on the brightest part of
                    // the translucent gradient (for example the Built-in "AI" chip).
                    .foregroundStyle(Theme.Text.primary)
                    .lineLimit(1)
            }
        }
    }
}

// MARK: - Filter chip row

/// Horizontal row of selectable filter chips. Used by Voices, History, and
/// Settings to filter content.
struct IOSFilterChipRow<Option: Hashable & Identifiable>: View {
    let options: [Option]
    @Binding var selection: Option
    let tint: Color
    let label: (Option) -> String
    let leading: ((Option) -> AnyView)?
    let accessibilityIdentifier: ((Option) -> String)?

    init(
        options: [Option],
        selection: Binding<Option>,
        tint: Color,
        label: @escaping (Option) -> String,
        leading: ((Option) -> AnyView)? = nil,
        accessibilityIdentifier: ((Option) -> String)? = nil
    ) {
        self.options = options
        self._selection = selection
        self.tint = tint
        self.label = label
        self.leading = leading
        self.accessibilityIdentifier = accessibilityIdentifier
    }

    var body: some View {
        HStack(spacing: 8) {
            ForEach(options) { option in
                chip(for: option)
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 4)
        .padding(.bottom, 12)
    }

    private func chip(for option: Option) -> some View {
        let isSelected = option == selection

        return Button {
            IOSAccessibleAnimation.perform(Theme.Motion.stateChange) {
                selection = option
            }
            IOSHaptics.selection()
        } label: {
            HStack(spacing: 6) {
                if let leading {
                    leading(option)
                }
                Text(label(option))
                    .iosScaledFont(size: 13, weight: .semibold, relativeTo: .caption)
                    .lineLimit(1)
                    .minimumScaleFactor(0.85)
            }
            .foregroundStyle(isSelected ? Theme.Text.primary : Theme.Text.secondary)
            .frame(maxWidth: .infinity)
            .frame(minHeight: 32)
            .padding(.horizontal, 12)
            .background {
                Capsule(style: .continuous)
                    .fill(isSelected ? Color.white.opacity(0.10) : Color.white.opacity(0.03))
            }
            .overlay {
                Capsule(style: .continuous)
                    .stroke(isSelected ? Color.white.opacity(0.18) : Color.white.opacity(0.10), lineWidth: 0.5)
            }
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(accessibilityIdentifier?(option) ?? "")
        // VoiceOver must hear which filter is active — the visual state is
        // brightness-only (IUI-4 X7; the delivery preset cards' pattern).
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}

// MARK: - Search field

/// Compact search field used in Voices + History tabs. Wraps a UIKit-aware
/// SwiftUI TextField with a leading magnifier glass and trailing clear
/// button.
struct IOSSearchField: View {
    @Binding var text: String
    let placeholder: String

    @FocusState private var isFocused: Bool

    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 16, weight: .medium))
                .foregroundStyle(Theme.Text.tertiary)

            TextField(placeholder, text: $text)
                .focused($isFocused)
                .textInputAutocapitalization(.never)
                // Search filters match existing text; live autocorrection
                // rewrites the query as it's typed (reproduced on-device,
                // IUI-1). IUI-4 X1.
                .autocorrectionDisabled(true)
                .submitLabel(.search)
                .foregroundStyle(Theme.Text.primary)
                .iosScaledFont(size: 15, relativeTo: .subheadline)

            if !text.isEmpty {
                Button {
                    text = ""
                    IOSHaptics.selection()
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 16))
                        .foregroundStyle(Theme.Text.tertiary)
                        // 44 pt HIG hit target around the 16 pt glyph (IUI-4 X8).
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(IOSInterfaceText.clearSearch)
            }
        }
        .padding(.horizontal, 14)
        .frame(minHeight: 44)
        .background {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color.white.opacity(0.06))
        }
        .iosAppAnimation(Theme.Motion.stateChange, value: isFocused)
    }
}

// MARK: - Primary CTA

/// Primary CTA "glass hero" button (Studio Generate/Install, Onboarding,
/// Recording overlay, sheet Install): the shared `VocelloPrimaryCTAButton`
/// (UIF-02) at the phone's `.dock` size with `Traits.phone`, Reduce
/// Transparency from the iOS environment key and the phone's Reduce
/// Motion-aware state animation.
struct IOSPrimaryCTAButton: View {
    let title: String
    let symbol: String?
    let tint: Color
    let isEnabled: Bool
    let action: () -> Void

    @Environment(\.iosReduceTransparencyEnabled) private var reduceTransparency

    init(
        title: String,
        symbol: String? = nil,
        tint: Color,
        isEnabled: Bool = true,
        action: @escaping () -> Void
    ) {
        self.title = title
        self.symbol = symbol
        self.tint = tint
        self.isEnabled = isEnabled
        self.action = action
    }

    var body: some View {
        VocelloPrimaryCTAButton(
            title: title,
            symbol: symbol,
            tint: tint,
            isEnabled: isEnabled,
            size: .dock,
            traits: .phone,
            reduceTransparency: reduceTransparency,
            action: action
        )
        .iosAppAnimation(Theme.Motion.stateChange, value: isEnabled)
    }
}
