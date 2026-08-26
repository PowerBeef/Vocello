import XCTest

final class StudioGenerationAttemptAuthorityTests: XCTestCase {
    private let first = StudioGenerationAttemptToken(
        rawValue: UUID(uuidString: "00000000-0000-0000-0000-000000000001")!
    )
    private let second = StudioGenerationAttemptToken(
        rawValue: UUID(uuidString: "00000000-0000-0000-0000-000000000002")!
    )

    func testStartRejectsOverlappingAttempt() {
        var authority = StudioGenerationAttemptAuthority()

        XCTAssertEqual(authority.begin(token: first), first)
        XCTAssertNil(authority.begin(token: second))
        XCTAssertTrue(authority.isRunning(first))
        XCTAssertFalse(authority.isCurrent(second))
    }

    func testStaleTerminalCannotClearNewAttempt() {
        var authority = StudioGenerationAttemptAuthority()

        XCTAssertEqual(authority.begin(token: first), first)
        XCTAssertTrue(authority.finishGeneration(first))
        XCTAssertEqual(authority.begin(token: second), second)

        XCTAssertFalse(authority.finishGeneration(first))
        XCTAssertTrue(authority.isRunning(second))
        XCTAssertEqual(authority.currentToken, second)
    }

    func testCancellationOwnsTerminalUntilBarrierCompletes() {
        var authority = StudioGenerationAttemptAuthority()

        XCTAssertEqual(authority.begin(token: first), first)
        XCTAssertTrue(authority.requestCancellation(first))
        XCTAssertFalse(authority.requestCancellation(first))
        XCTAssertTrue(authority.isCancelling(first))
        XCTAssertFalse(authority.finishGeneration(first))
        XCTAssertNil(authority.begin(token: second))

        XCTAssertTrue(authority.completeCancellation(first))
        XCTAssertNil(authority.currentToken)
        XCTAssertEqual(authority.begin(token: second), second)
    }

    func testCancellationFailureIsTerminalOnlyForMatchingAttempt() {
        var authority = StudioGenerationAttemptAuthority()

        XCTAssertEqual(authority.begin(token: first), first)
        XCTAssertTrue(authority.requestCancellation(first))
        XCTAssertFalse(authority.failCancellation(second))
        XCTAssertTrue(authority.isCancelling(first))
        XCTAssertTrue(authority.failCancellation(first))
        XCTAssertNil(authority.currentToken)
    }

    func testRapidCancelRestartRejectsEveryStaleCallback() {
        var authority = StudioGenerationAttemptAuthority()

        XCTAssertEqual(authority.begin(token: first), first)
        XCTAssertTrue(authority.requestCancellation(first))
        XCTAssertTrue(authority.completeCancellation(first))
        XCTAssertEqual(authority.begin(token: second), second)

        XCTAssertFalse(authority.completeCancellation(first))
        XCTAssertFalse(authority.failCancellation(first))
        XCTAssertFalse(authority.finishGeneration(first))
        XCTAssertTrue(authority.isRunning(second))
        XCTAssertTrue(authority.finishGeneration(second))
    }
}
