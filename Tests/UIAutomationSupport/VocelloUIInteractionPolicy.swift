import Foundation

/// Visibility and actionability are different claims. Layout checks always require
/// the whole frame. An explicitly selected oversized control may be activated only
/// when its central 44-point band is safely inside the viewport (plus XCUI hittability).
enum VocelloUIRevealRequirement {
    case fullVisibility, navigation

    func requiredFrame(_ frame: CGRect, visible: CGRect) -> CGRect {
        guard self == .navigation, frame.height > visible.height else { return frame }
        return CGRect(x: frame.minX, y: frame.midY - 22, width: frame.width, height: 44)
    }

    func satisfied(by frame: CGRect, visible: CGRect) -> Bool {
        guard Self.valid(frame), Self.valid(visible) else { return false }
        return visible.contains(requiredFrame(frame, visible: visible))
    }

    static func valid(_ frame: CGRect) -> Bool {
        !frame.isEmpty && !frame.isNull && !frame.isInfinite
            && [frame.minX, frame.minY, frame.maxX, frame.maxY].allSatisfy(\.isFinite)
    }

    static func viewport(window: CGRect, statusBar: CGRect?, dock: CGRect) -> CGRect? {
        guard valid(window), valid(dock), window.intersects(dock) else { return nil }
        let top = statusBar.flatMap { valid($0) ? max(window.minY, $0.maxY) : nil } ?? window.minY
        let bottom = dock.minY - 4
        guard bottom > top else { return nil }
        return CGRect(x: window.minX, y: top, width: window.width, height: bottom - top)
    }
}

/// Test-only bounded search. Geometry comes from the current accessibility snapshot,
/// not coordinates to tap or assumptions about the retained scroll position.
struct VocelloUIRevealSearch {
    enum Swipe { case up, down }
    private(set) var attempts = 0
    let preferred: Swipe
    private var previousFrame: CGRect?
    private var previousDirection: Swipe?
    private var stationarySamples = 0
    private var stepLimit: CGFloat = 120

    init(preferred: Swipe) {
        self.preferred = preferred
    }

    /// Desired content movement (negative Y reveals content below), used to
    /// choose a small touch anchor. This is not a pointer event or a promise of
    /// exact UIKit displacement; every touch must be followed by a fresh snapshot.
    mutating func nextScroll(target: CGRect?, visible: CGRect) -> CGFloat? {
        guard VocelloUIRevealRequirement.valid(visible) else { return nil }
        let validTarget = target.flatMap { VocelloUIRevealRequirement.valid($0) ? $0 : nil }
        if let frame = validTarget {
            guard frame.height <= visible.height, frame.width <= visible.width,
                  frame.minX >= visible.minX, frame.maxX <= visible.maxX,
                  !visible.contains(frame) else { return nil }
            if let previousFrame, abs(frame.minY - previousFrame.minY) < 0.5,
               abs(frame.height - previousFrame.height) < 0.5 {
                stationarySamples += 1
            } else {
                stationarySamples = 0
            }
            guard stationarySamples < 3 else { return nil }
        }
        previousFrame = validTarget
        guard let direction = next(target: validTarget, visible: visible) else { return nil }
        if let previousDirection, direction != previousDirection {
            stepLimit = max(4, stepLimit / 2)
        }
        previousDirection = direction
        let distance: CGFloat
        if let frame = validTarget {
            let gap = direction == .up ? frame.maxY - visible.maxY : visible.minY - frame.minY
            // Aim inside the fitting interval instead of balancing on its edge.
            distance = gap + min(8, (visible.height - frame.height) / 2)
        } else {
            distance = stepLimit
        }
        let magnitude = min(distance, stepLimit, visible.height / 4)
        guard magnitude.isFinite, magnitude > 0 else { return nil }
        return direction == .up ? -magnitude : magnitude
    }

    mutating func next(target: CGRect?, visible: CGRect) -> Swipe? {
        guard attempts < 20 else { return nil }
        attempts += 1
        if let target, VocelloUIRevealRequirement.valid(target) {
            if target.minY < visible.minY { return .down }
            if target.maxY > visible.maxY { return .up }
        }
        // Some virtualized/offscreen elements expose no usable frame. Search both
        // directions within one fixed budget; never repeat an entire test attempt.
        return attempts <= 10 ? preferred : (preferred == .up ? .down : .up)
    }
}

/// A native element swipe chooses its own endpoints. Only use a small, completely
/// visible descendant of the owning scroll view, so neither endpoint starts on the
/// dock or outside the window. Never swipe the oversized row/window as a fallback.
enum VocelloUITouchScrollAnchor {
    static func index(frames: [CGRect], visible: CGRect, desiredDelta: CGFloat) -> Int? {
        guard VocelloUIRevealRequirement.valid(visible), desiredDelta.isFinite,
              desiredDelta != 0 else { return nil }
        let safe = visible.insetBy(dx: 4, dy: 8)
        let maximumHeight = min(120, max(24, abs(desiredDelta) * 2))
        return frames.indices.filter { index in
            let frame = frames[index]
            return VocelloUIRevealRequirement.valid(frame) && safe.contains(frame)
                && frame.width >= 44 && frame.height >= 12 && frame.height <= maximumHeight
        }.sorted { lhs, rhs in
            // Largest permitted anchor advances efficiently; ties stay deterministic.
            if frames[lhs].height != frames[rhs].height { return frames[lhs].height > frames[rhs].height }
            return lhs < rhs
        }.first
    }
}

/// Each restoration dimension must be observed, not inferred from process exit.
struct VocelloUIPurchaseRestoration: Codable {
    enum Outcome: String, Codable {
        case restored, notRequired, skippedBackground, baselineMissing, failed

        var satisfied: Bool { self == .restored || self == .notRequired }
    }
    var transactionsCleared = false
    var tab: Outcome = .notRequired
    var historyFilter: Outcome = .notRequired
    var appStopped = false

    var complete: Bool {
        transactionsCleared && tab.satisfied && historyFilter.satisfied && appStopped
    }
}
