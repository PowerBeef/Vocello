import SwiftUI
import UIKit

// Reusable scroll refinements for the bottom-sheet pickers: a property-only bounce
// disabler and a subtle, auto-fading custom scroll indicator. Built as View modifiers
// so any sheet (Language now; Voice / Delivery later) can adopt them.
//
// Why UIKit at all: pure SwiftUI cannot disable rubber-band on *overflowing* content
// (`.scrollBounceBehavior(.basedOnSize)` only suppresses bounce when the content fits).
// Mirrors the existing IOSBriefTextEditor / IOSFlexibleTextEditor UIKit bridges.

// MARK: - Bounce disabler

/// Clear, non-interactive probe placed *inside* the scroll content (via `.background`).
/// It walks up to the enclosing `UIScrollView` and turns off bounce. It only sets
/// properties — it never touches `.delegate`, which SwiftUI owns (hijacking it breaks
/// scrolling).
private final class IOSScrollBounceProbeView: UIView {
    override func didMoveToWindow() {
        super.didMoveToWindow()
        disableBounce()
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        disableBounce()
    }

    private func disableBounce() {
        var ancestor: UIView? = superview
        while let view = ancestor {
            if let scrollView = view as? UIScrollView {
                scrollView.bounces = false
                scrollView.alwaysBounceVertical = false
                scrollView.alwaysBounceHorizontal = false
                break
            }
            ancestor = view.superview
        }
    }
}

private struct IOSScrollBounceDisabler: UIViewRepresentable {
    func makeUIView(context: Context) -> IOSScrollBounceProbeView {
        let view = IOSScrollBounceProbeView()
        view.backgroundColor = .clear
        view.isUserInteractionEnabled = false
        return view
    }

    func updateUIView(_ uiView: IOSScrollBounceProbeView, context: Context) {}
}

// MARK: - Subtle custom scroll indicator

private struct IOSScrollMetrics: Equatable {
    var offsetY: CGFloat = 0
    var contentHeight: CGFloat = 0
    var viewportHeight: CGFloat = 0
}

/// A thin translucent thumb pinned over the scroll viewport's trailing edge. It tracks
/// scroll position, appears while scrolling, and fades out ~1s after scrolling stops.
/// No track and no glass — neutral white so it reads as part of the dark sheet. Geometry
/// comes from `.onScrollGeometryChange` (delegate-free), so SwiftUI keeps its scroll
/// delegate.
private struct IOSSubtleScrollIndicator: ViewModifier {
    /// Deadline holder outside SwiftUI state (IUI-5 P7): scroll geometry
    /// events arrive per frame while scrolling, and the previous
    /// implementation cancelled + spawned a fresh hide `Task` per event.
    /// Mutating this box does not invalidate the view; one task per
    /// visibility burst sleeps until the extending deadline passes. (Like
    /// the task it replaces, that task is not cancelled on view teardown —
    /// it dies ≤1 s later writing into detached state, which is inert.)
    @MainActor
    private final class HideScheduler {
        var lastEvent: ContinuousClock.Instant = .now
        var task: Task<Void, Never>?
    }

    @Environment(\.iosReduceMotionEnabled) private var reduceMotion

    @State private var metrics = IOSScrollMetrics()
    @State private var isVisible = false
    @State private var scheduler = HideScheduler()

    func body(content: Content) -> some View {
        content
            .onScrollGeometryChange(for: IOSScrollMetrics.self) { geometry in
                IOSScrollMetrics(
                    offsetY: geometry.contentOffset.y,
                    contentHeight: geometry.contentSize.height,
                    viewportHeight: geometry.containerSize.height
                )
            } action: { _, newValue in
                metrics = newValue
                flash()
            }
            .overlay { thumb }
    }

    /// The thumb is confined to the overlay's *own* rendered bounds (via `GeometryReader`)
    /// rather than the scroll geometry's `containerSize` — the latter can exceed the
    /// visible viewport, which let the thumb's bottom clip off-screen at max scroll. A
    /// vertical `inset` keeps it floating clear of both edges.
    @ViewBuilder private var thumb: some View {
        GeometryReader { proxy in
            let viewport = proxy.size.height
            let content = metrics.contentHeight
            let overflow = content - viewport
            if overflow > 1, viewport > 0 {
                // Asymmetric: a larger bottom inset keeps the thumb clear of the sheet's
                // bottom rounded corner / home-indicator area at max scroll.
                let topInset: CGFloat = 6
                let bottomInset: CGFloat = 18
                let track = max(0, viewport - topInset - bottomInset)
                let thumbHeight = min(track, max(36, track * (viewport / content)))
                let progress = min(max(metrics.offsetY / overflow, 0), 1)
                let centerY = topInset + (track - thumbHeight) * progress + thumbHeight / 2
                Capsule(style: .continuous)
                    .fill(Color.white.opacity(0.28))
                    .frame(width: 3, height: thumbHeight)
                    .position(x: proxy.size.width - 5, y: centerY)
                    .opacity(isVisible ? 1 : 0)
                    .iosAppAnimation(Theme.Motion.stateChange, value: isVisible)
            }
        }
        .allowsHitTesting(false)
    }

    private func flash() {
        scheduler.lastEvent = .now
        if !isVisible {
            isVisible = true
        }
        guard scheduler.task == nil else { return }
        let scheduler = scheduler
        scheduler.task = Task { @MainActor in
            while !Task.isCancelled {
                let deadline = scheduler.lastEvent.advanced(by: .seconds(1.0))
                if ContinuousClock.now >= deadline { break }
                try? await Task.sleep(until: deadline, clock: .continuous)
            }
            scheduler.task = nil
            guard !Task.isCancelled else { return }
            isVisible = false
        }
    }
}

// MARK: - View API

extension View {
    /// Disable rubber-band/overscroll on the enclosing scroll view. Attach to a view
    /// *inside* the scroll content (e.g. the content stack) so the probe can find it.
    func iosDisableScrollBounce() -> some View {
        background(IOSScrollBounceDisabler())
    }

    /// Overlay a subtle, auto-fading custom scroll indicator. Attach to the `ScrollView`.
    func iosSubtleScrollIndicator() -> some View {
        modifier(IOSSubtleScrollIndicator())
    }
}

// MARK: - Convenience wrapper

/// iOS scroll surface with the same no-rubber-band, subtle-indicator behavior as the
/// language picker. Use this instead of raw `ScrollView` for all vertical iOS scroll
/// content so the app-wide scrolling feel stays consistent.
///
/// On full-screen shells the bottom of the scroll view fades out under the TabDock;
/// pass `bottomFadeHeight: 0` for sheets that float above the dock.
struct IOSScrollView<Content: View>: View {
    let bottomFadeHeight: CGFloat
    @ViewBuilder let content: () -> Content

    init(
        bottomFadeHeight: CGFloat = IOSStudioShellMetrics.dockFadeHeight,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.bottomFadeHeight = bottomFadeHeight
        self.content = content
    }

    var body: some View {
        ScrollView(.vertical, showsIndicators: false) {
            content()
                .iosDisableScrollBounce()
        }
        .iosSubtleScrollIndicator()
        .bottomFadeMask(height: bottomFadeHeight)
    }
}

private struct IOSScrollBottomFadeMask: ViewModifier {
    let height: CGFloat

    func body(content: Content) -> some View {
        content
            .mask {
                GeometryReader { proxy in
                    let total = proxy.size.height
                    let start = total > 0 ? max(0, (total - height) / total) : 1
                    LinearGradient(
                        stops: [
                            .init(color: .white, location: 0),
                            .init(color: .white, location: start),
                            .init(color: .clear, location: 1)
                        ],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                }
            }
    }
}

private extension View {
    @ViewBuilder
    func bottomFadeMask(height: CGFloat) -> some View {
        if height > 0 {
            modifier(IOSScrollBottomFadeMask(height: height))
        } else {
            self
        }
    }
}
