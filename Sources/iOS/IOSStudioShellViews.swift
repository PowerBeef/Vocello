import SwiftUI

/// Shared metrics for the iOS shell chrome.
enum IOSStudioShellMetrics {
    /// Height over which scroll content fades out under the glass TabDock.
    static let dockFadeHeight: CGFloat = 118
}

/// Thin per-screen body container.
///
/// History: this used to host the full iOS chrome — `IOSStudioShellCanopy`
/// rendering the "Vocello" wordmark + a memory-indicator accessory at the
/// top, and `IOSStudioRootDock` at the bottom via `safeAreaInset`. R0 of
/// the May 2026 UI audit moved both into `RootView`. The shared mode/tab
/// gradient stays here so it sits inside each `NavigationStack` and remains
/// visible behind Studio, Voices, History, and Settings content.
///
/// The cleanup pass that followed R2 also dropped the `Accessory` +
/// `BottomAccessory` generics, the canopy + dock structs, and the
/// `IOSAppTab` extension that powered the legacy dock. Anything you
/// want at the top of every Studio-style screen now lives at
/// `RootView` level; anything you want at the bottom uses the global
/// `safeAreaInset(edge: .bottom)` that hosts the new `TabDock`.
struct IOSStudioShellScreen<Content: View>: View {
    @Binding var selectedTab: IOSAppTab

    let activeTab: IOSAppTab
    let tint: Color
    let screenContent: Content

    init(
        selectedTab: Binding<IOSAppTab>,
        activeTab: IOSAppTab,
        tint: Color,
        @ViewBuilder content: () -> Content
    ) {
        self._selectedTab = selectedTab
        self.activeTab = activeTab
        self.tint = tint
        self.screenContent = content()
    }

    var body: some View {
        ZStack {
            IOSModeBackdrop(tint: tint, intensity: .warm)
                .ignoresSafeArea()

            // Phase 2 (2026-05-21): the now-playing rail + engine-lifecycle
            // toast `safeAreaInset(.bottom)` modifiers moved up to
            // `RootView`. Hosting them here gave the canvas's inner VStack
            // a tight height budget and broke any composer that asked for
            // `.frame(maxHeight: .infinity)` — the composer would gobble
            // the canvas and push the Generate CTA under the tab dock.
            // RootView now owns every bottom-inset stack-up (dock + rail
            // + toast), so each screen body gets a single clean height
            // budget it can negotiate against.
            screenContent
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .iosAppAnimation(IOSSelectionMotion.modeCrossfade, value: activeTab)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .toolbar(.hidden, for: .navigationBar)
    }
}

/// Per-screen page heading (Library, Settings, etc.).
/// Sits at the top of a screen body where the design specifies a
/// large 28-pt title in SF Pro Display.
struct IOSStudioWorkspaceHeading: View {
    let title: String

    var body: some View {
        Text(title)
            .iosScaledFont(size: 28, weight: .bold, relativeTo: .largeTitle)
            .tracking(-0.56)
            .foregroundStyle(IOSAppTheme.textPrimary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 20)
            .padding(.top, 4)
            .padding(.bottom, 12)
            .accessibilityAddTraits(.isHeader)
    }
}

/// Card-style section wrapper used on Settings + Library surfaces.
/// Wraps a section's content in a glassy rounded surface tinted by
/// the per-tab accent.
struct IOSStudioSectionGroup<Content: View>: View {
    let title: String?
    let tint: Color
    let content: Content

    init(
        title: String? = nil,
        tint: Color,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.tint = tint
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let title, !title.isEmpty {
                Text(title.uppercased())
                    .iosScaledFont(size: 11, weight: .semibold, relativeTo: .caption2)
                    .tracking(0.88)
                    .foregroundStyle(IOSAppTheme.textSecondary)
                    .padding(.horizontal, 20)
                    .padding(.top, 14)
                    .padding(.bottom, 6)
            }

            VStack(alignment: .leading, spacing: 10) {
                content
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(Color.white.opacity(0.04))
            }
            .overlay {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(Color.white.opacity(0.08), lineWidth: 0.5)
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 6)
        }
    }
}
