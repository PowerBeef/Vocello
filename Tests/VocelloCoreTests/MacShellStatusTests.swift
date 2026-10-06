import Foundation
import QwenVoiceCore
import XCTest

/// A14-04: the sidebar footer status over the engine snapshot. The engine keeps
/// a visible error until a later operation succeeds or the user dismisses it,
/// so a busy engine (a retry's cold start, a running take, a model load) shows
/// its own activity, and the error returns only once the engine is idle again.
@MainActor
final class MacShellStatusTests: XCTestCase {
    private let staleError = "The previous take failed."

    private func snapshot(
        _ loadState: EngineLoadState,
        isReady: Bool = true,
        visibleErrorMessage: String? = nil
    ) -> TTSEngineSnapshot {
        TTSEngineSnapshot(
            isReady: isReady,
            loadState: loadState,
            clonePreparationState: .idle,
            visibleErrorMessage: visibleErrorMessage
        )
    }

    private func resolve(_ snapshot: TTSEngineSnapshot, inline: Bool = false) -> MacShellStatus {
        MacShellStatusPresentation.resolve(snapshot: snapshot, prefersInlinePresentation: inline)
    }

    func testARunningRetryShowsItsActivityOverTheStaleError() {
        // A user take makes the engine not ready while it runs.
        let status = resolve(snapshot(
            .running(modelID: "pro_custom", label: nil, fraction: 0.25),
            isReady: false,
            visibleErrorMessage: staleError
        ))
        XCTAssertEqual(status, .running(MacShellActivity(
            label: MacInterfaceText.activityGeneratingAudio,
            fraction: 0.25,
            presentation: .standaloneCard
        )))
    }

    func testAModelLoadShowsItsOwnProgressNotTheStaleErrorAsItsTitle() {
        XCTAssertEqual(
            resolve(snapshot(.starting, isReady: true, visibleErrorMessage: staleError), inline: true),
            .running(MacShellActivity(
                label: MacInterfaceText.activityPreparingModel,
                fraction: nil,
                presentation: .inlinePlayer
            ))
        )
        XCTAssertEqual(
            resolve(snapshot(.starting, isReady: false, visibleErrorMessage: staleError)),
            .starting
        )
    }

    func testTheErrorShowsWhileTheEngineIsIdleOrFailed() {
        XCTAssertEqual(
            resolve(snapshot(.loaded(modelID: "pro_custom"), visibleErrorMessage: staleError)),
            .error(staleError),
            "A cancelled retry leaves the undismissed error on screen"
        )
        XCTAssertEqual(resolve(snapshot(.idle, visibleErrorMessage: staleError)), .error(staleError))
        XCTAssertEqual(resolve(snapshot(.idle, isReady: false, visibleErrorMessage: staleError)), .crashed(staleError))
        XCTAssertEqual(resolve(snapshot(.failed(message: "Load failed."))), .error("Load failed."))
        XCTAssertEqual(resolve(snapshot(.failed(message: "Load failed."), isReady: false)), .crashed("Load failed."))
    }

    func testAnIdleEngineWithoutAnErrorIsStandbyOrIdle() {
        XCTAssertEqual(resolve(snapshot(.idle)), .standby)
        XCTAssertEqual(resolve(snapshot(.idle, visibleErrorMessage: "  \n")), .standby)
        XCTAssertEqual(resolve(snapshot(.loaded(modelID: "pro_custom"))), .idle)
        XCTAssertEqual(resolve(snapshot(.idle, isReady: false)), .starting)
    }
}
