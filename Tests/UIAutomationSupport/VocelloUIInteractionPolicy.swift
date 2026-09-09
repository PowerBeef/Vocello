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
