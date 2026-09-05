import SwiftUI
import QwenVoiceCore

/// Bottom glass dock from `design_references/Vocello iOS/chrome.jsx`
/// (`TabDock`). Custom view rather than `TabView` because the native
/// TabView doesn't ship the mode-tinted accent rail behavior the design
/// uses on Studio.
///
/// Selection lives on `AppModel.tab`. The Studio tab takes the
/// currently-selected mode color; the other tabs use their reference
/// dock accents from `design_references/Vocello iOS/chrome.jsx`.
struct TabDock: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private var dockTint: Color {
        appModel.tab.dockAccent(studioMode: appModel.studioMode.mode)
    }

    // Tabs stay ENABLED during generation (relaxed 2026-07-02, maintainer decision):
    // generation state lives on AppModel's per-mode coordinators and the engine task,
    // so browsing History/Settings mid-take is safe — returning to Studio shows the
    // live/completed card. The old lock made Settings unreachable for the whole take.

    var body: some View {
        VStack(spacing: 0) {
            Group {
                if dynamicTypeSize.isAccessibilitySize {
                    LazyVGrid(
                        columns: [GridItem(.flexible()), GridItem(.flexible())],
                        spacing: 2
                    ) {
                        tabButtons(horizontalLayout: true)
                    }
                } else {
                    HStack(spacing: 2) {
                        tabButtons(horizontalLayout: false)
                    }
                }
            }
            .padding(6)
            .frame(maxWidth: .infinity)
            .background { TabDockRailBackground(tint: dockTint) }
            .sensoryFeedback(.selection, trigger: appModel.tab)
            .padding(.horizontal, 14)
            .padding(.top, 6)
            .padding(.bottom, 24)
        }
        .background(
            LinearGradient(
                colors: [
                    Theme.Surface.canvasBottom.opacity(0),
                    Theme.Surface.canvasBottom.opacity(0.88),
                    Theme.Surface.canvasBottom
                ],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea(edges: .bottom)
        )
    }

    @ViewBuilder
    private func tabButtons(horizontalLayout: Bool) -> some View {
        ForEach(IOSAppTab.allCases) { tab in
            TabDockButton(
                tab: tab,
                isSelected: appModel.tab == tab,
                isDisabled: false,
                horizontalLayout: horizontalLayout,
                action: { select(tab) }
            )
        }
    }

    private func select(_ tab: IOSAppTab) {
        guard appModel.tab != tab else { return }
        IOSAccessibleAnimation.perform(Theme.Motion.stateChange) {
            appModel.tab = tab
        }
    }
}

// MARK: - Single dock button

private struct TabDockButton: View {
    let tab: IOSAppTab
    let isSelected: Bool
    let isDisabled: Bool
    let horizontalLayout: Bool
    let action: () -> Void

    @Environment(AppModel.self) private var appModel

    private var accentTint: Color {
        tab.dockAccent(studioMode: appModel.studioMode.mode)
    }

    var body: some View {
        Button(action: action) {
            Group {
                if horizontalLayout {
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 8) {
                            tabIcon
                            // Evaluate the real title width, not an ellipsized fit.
                            tabTitle.fixedSize(horizontal: true, vertical: false)
                        }
                        VStack(spacing: 4) {
                            tabIcon
                            tabTitle
                        }
                    }
                } else {
                    VStack(spacing: 4) {
                        tabIcon
                        tabTitle
                    }
                }
            }
            .foregroundStyle(isSelected ? accentTint : Color.white.opacity(0.46))
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 4)
            .padding(.top, 9)
            .padding(.bottom, 7)
            .background {
                if isSelected {
                    TabDockSelectionBackground(tint: accentTint)
                }
            }
        }
        .buttonStyle(.plain)
        // Apply the expansion to the control itself, not only its label. Otherwise SwiftUI can
        // expose the intrinsic text width as the accessibility frame even though the HStack's
        // visual selection background spans a much larger area.
        .frame(maxWidth: .infinity, minHeight: 44)
        .contentShape(Rectangle())
        .disabled(isDisabled)
        .opacity(isDisabled ? 0.42 : 1)
        .accessibilityIdentifier("rootTab_\(tab.rawValue)")
        .accessibilityAddTraits(isSelected ? [.isSelected, .isButton] : [.isButton])
    }

    private var tabIcon: some View {
        Image(systemName: tab.systemImage)
            .font(.system(size: 22, weight: .semibold))
    }

    private var tabTitle: some View {
        Text(tab.title)
            .font(.caption2.weight(.semibold))
            .tracking(0.05)
            .lineLimit(horizontalLayout ? nil : 1)
            .fixedSize(horizontal: false, vertical: true)
            .multilineTextAlignment(.center)
    }
}

private struct TabDockRailBackground: View {
    let tint: Color
    @Environment(\.iosReduceTransparencyEnabled) private var reduceTransparency

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 28, style: .continuous)
        let fill = Color(red: 16 / 255, green: 18 / 255, blue: 26 / 255)
            .opacity(reduceTransparency ? 1.0 : 0.98)

        shape
            .fill(fill)
            .overlay {
                shape.stroke(Color.white.opacity(0.10), lineWidth: 0.5)
            }
            .overlay(alignment: .top) {
                shape
                    .stroke(Color.white.opacity(0.05), lineWidth: 0.6)
                    .mask(
                        LinearGradient(
                            colors: [.white, .clear],
                            startPoint: .top,
                            endPoint: .center
                        )
                    )
            }
            .shadow(color: .black.opacity(0.40), radius: 18, x: 0, y: 14)
            .overlay {
                shape.stroke(tint.opacity(0.04), lineWidth: 0.5)
            }
    }
}

// MARK: - Selected pill background

/// Active-tab background pill.
///
/// R2 (2026-05-21): rewritten to match `app.css` `.vc-tab-btn-pill` +
/// the per-tab tint formula in `chrome.jsx`:
///
///   background:  color-mix(tint 12 %, rgba(255,255,255,0.02))
///   border:      0.5pt color-mix(tint 38 %, transparent)
///   inset hi:    rgba(255,255,255,0.08) from top
///   shadow:      0 2 6 / rgba(0,0,0,0.25)
///
/// The earlier version stacked a full Liquid-Glass tinted surface on
/// top of a neutral glass fill and crowned it with a `tint @ 0.42`
/// stroke — vivid enough that even the silver-tinted Voices /
/// Settings tabs read as cool blue badges. The new recipe pulls the
/// pill back to a quiet hue-tinted glass.
private struct TabDockSelectionBackground: View {
    let tint: Color
    @Environment(\.iosReduceTransparencyEnabled) private var reduceTransparency

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 22, style: .continuous)

        // Background: 12 % tint over a near-transparent white film so
        // the hue reads but the surface stays glassy on the dock.
        let baseFill = shape
            .fill(Color.white.opacity(0.02))
            .overlay {
                shape.fill(tint.opacity(0.12))
            }

        // Stroke: 38 % tint outline. Half-point hairline.
        let stroke = shape
            .stroke(tint.opacity(0.38), lineWidth: 0.5)

        // Inset white highlight from the top edge, masked by a
        // top-down gradient so it reads as a 1-pixel light source.
        let insetHighlight = shape
            .stroke(Color.white.opacity(0.08), lineWidth: 0.5)
            .mask(
                LinearGradient(
                    colors: [.white, .clear],
                    startPoint: .top,
                    endPoint: .center
                )
            )

        baseFill
            .overlay { stroke }
            .overlay { insetHighlight }
            .shadow(color: .black.opacity(reduceTransparency ? 0 : 0.25), radius: 3, x: 0, y: 2)
    }
}

// MARK: - IOSAppTab presentation helpers

extension IOSAppTab {
    func dockAccent(studioMode: GenerationMode) -> Color {
        switch self {
        case .studio:
            return Theme.Brand.modeColor(studioMode)
        case .voices:
            // #8AB0C8 — soft dusty blue in the reference dock.
            return Color(red: 0.541, green: 0.690, blue: 0.784)
        case .history:
            // #BFA0AB — muted dusty rose in the reference dock.
            return Color(red: 0.749, green: 0.627, blue: 0.671)
        case .settings:
            // #A1A8B8 — cool slate neutral in the reference dock.
            return Color(red: 0.631, green: 0.659, blue: 0.722)
        }
    }

    var title: String {
        switch self {
        case .studio: return "Studio"
        case .voices: return "Voices"
        case .history: return "History"
        case .settings: return "Settings"
        }
    }

    var systemImage: String {
        // R2 (2026-05-21): SF Symbols closest to the design glyphs in
        // `design_references/Vocello iOS/icons.jsx`:
        //   IconStudio   = 5 rounded bars rising to a peak  → "waveform"
        //                  (was "waveform.badge.mic" which carries a mic
        //                  badge and reads as recording, not composing)
        //   IconVoices   = two stylized speaker silhouettes → "person.2.fill"
        //                  (was "person.wave.2.fill" which adds a sound wave
        //                  the design doesn't carry)
        //   IconHistory  = clock with rewind hint           → "clock.arrow.circlepath"
        //   IconSettings = 6-tooth gear with inner circle   → "gearshape"
        switch self {
        case .studio: return "waveform"
        case .voices: return "person.2.fill"
        case .history: return "clock.arrow.circlepath"
        case .settings: return "gearshape"
        }
    }
}

// `IOSGenerationSection.mode` already exists in `IOSRootNavigationModels.swift`;
// no extension needed here.
