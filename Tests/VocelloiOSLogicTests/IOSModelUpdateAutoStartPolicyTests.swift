import Foundation
import QwenVoiceCore
import XCTest

/// RF-59: the iPhone asks once before the model update downloads (Guideline 4.2.3(ii)), then
/// resumes it on its own; it never restarts what the user stopped or a failure waiting for Retry.
final class IOSModelUpdateAutoStartPolicyTests: XCTestCase {
    private typealias Policy = IOSModelUpdateAutoStartPolicy
    private let gigabyte: Int64 = 1_000_000_000

    private func candidate(
        _ id: String, bytes: Int64 = 2_000_000_000, paused: Bool = false, active: Bool = false, failed: Bool = false
    ) -> Policy.Candidate {
        Policy.Candidate(modelID: id, estimatedBytes: bytes, paused: paused, active: active, failed: failed)
    }

    private func decide(
        _ candidates: [Policy.Candidate], consented: Bool = false, lowDataMode: Bool = false,
        available: Int64? = 100_000_000_000, earlier: Bool = true
    ) -> Policy.Decision {
        Policy.decide(
            candidates: candidates, consented: consented, lowDataMode: lowDataMode,
            availableBytes: available, holdsEarlierModels: earlier
        )
    }

    func testTheFirstLaunchAsksOnceForEveryModelWithTheirTotalSize() {
        XCTAssertEqual(
            decide([candidate("pro_custom"), candidate("pro_clone", bytes: 2_200_000_000)]),
            .ask(modelIDs: ["pro_custom", "pro_clone"], totalBytes: 4_200_000_000, makesRoomFirst: false)
        )
    }

    func testAfterConsentALaunchResumesWithoutAsking() {
        XCTAssertEqual(
            decide([candidate("pro_custom"), candidate("pro_design")], consented: true),
            .start(modelIDs: ["pro_custom", "pro_design"])
        )
    }

    func testStoppedFailedAndRunningModelsAreLeftAlone() {
        let candidates = [
            candidate("pro_custom", paused: true),
            candidate("pro_design", failed: true),
            candidate("pro_clone", active: true),
        ]
        XCTAssertEqual(decide(candidates), .none)
        XCTAssertEqual(decide(candidates, consented: true), .none)
        XCTAssertEqual(
            decide(candidates + [candidate("pro_extra")], consented: true), .start(modelIDs: ["pro_extra"])
        )
    }

    func testNothingStartsUnderLowDataModeOrWithNothingToUpdate() {
        XCTAssertEqual(decide([candidate("pro_custom")], consented: true, lowDataMode: true), .none)
        XCTAssertEqual(decide([candidate("pro_custom")], lowDataMode: true), .none)
        XCTAssertEqual(decide([]), .none)
    }

    /// The first download needs room for itself twice over; when the phone lacks it and earlier
    /// models are still on disk, the prompt says they go first.
    func testANearlyFullPhoneMakesRoomFirstOnlyWhenEarlierModelsCanFreeIt() {
        let model = candidate("pro_custom", bytes: 2 * gigabyte)
        let needed = IOSModelDeliverySupport.minimumFreeBytes(forFetching: 2 * gigabyte)
        XCTAssertEqual(needed, 4 * gigabyte)
        XCTAssertEqual(
            decide([model], available: needed - 1),
            .ask(modelIDs: ["pro_custom"], totalBytes: 2 * gigabyte, makesRoomFirst: true)
        )
        XCTAssertEqual(
            decide([model], available: needed),
            .ask(modelIDs: ["pro_custom"], totalBytes: 2 * gigabyte, makesRoomFirst: false)
        )
        XCTAssertEqual(
            decide([model], available: needed - 1, earlier: false),
            .ask(modelIDs: ["pro_custom"], totalBytes: 2 * gigabyte, makesRoomFirst: false),
            "nothing to remove: the delivery's own space check speaks"
        )
        XCTAssertEqual(
            decide([model], available: nil),
            .ask(modelIDs: ["pro_custom"], totalBytes: 2 * gigabyte, makesRoomFirst: false)
        )
    }

    /// Review of 2026-11-14, item 7: the launch reads a failure the ledger kept from an earlier
    /// launch, so that update does not restart; the user's Retry resumes the mode in the ledger,
    /// and the next launch starts it again.
    func testAKeptFailureDoesNotRestartAtLaunchButRetryDoes() {
        func plan(failure: String?, paused: Bool = false) -> ModelUpdatePlan {
            ModelUpdatePlan(entries: [
                .clone: .init(
                    mode: .clone, retiredFolders: ["Qwen3-TTS-12Hz-1.7B-Base-4bit"], detectedAtUTC: "2026-11-14T00:00:00Z",
                    paused: paused, lastFailure: failure
                ),
            ])
        }
        func launch(
            _ plan: ModelUpdatePlan, pausedThisSession: Bool = false, transferring: Bool = false,
            failedThisSession: Bool = false
        ) -> Policy.Decision {
            decide([
                Policy.Candidate(
                    modelID: "pro_clone", estimatedBytes: 2 * gigabyte, mode: .clone, plan: plan,
                    pausedThisSession: pausedThisSession, transferring: transferring, failedThisSession: failedThisSession
                ),
            ], consented: true)
        }
        let kept = plan(failure: ModelUpdateFailure.network.rawValue)
        XCTAssertEqual(launch(kept), .none, "a failure from an earlier launch waits for Retry")
        XCTAssertEqual(kept.changeBeforeUpdating(.clone), .resume(.clone), "Retry resumes it first")
        XCTAssertEqual(launch(plan(failure: nil)), .start(modelIDs: ["pro_clone"]), "after Retry, a launch starts it")
        XCTAssertEqual(launch(plan(failure: nil), failedThisSession: true), .none)
        XCTAssertEqual(launch(plan(failure: nil, paused: true)), .none)
        XCTAssertEqual(launch(plan(failure: nil), pausedThisSession: true), .none)
        XCTAssertEqual(launch(plan(failure: nil), transferring: true), .none)
        XCTAssertEqual(
            plan(failure: nil).changeAfterFailure(.clone, .space), .recordFailure(.clone, .space),
            "a failed transfer is recorded for the next launch"
        )
    }

    /// A download that failed for want of space would fail again on Retry while the earlier models
    /// stay: the next launch asks to remove them first, even after consent; Later stops it.
    func testASpaceFailureAsksToMakeRoomFirst() {
        func candidate(failure: ModelUpdateFailure?, paused: Bool = false) -> Policy.Candidate {
            let plan = ModelUpdatePlan(entries: [
                .clone: .init(
                    mode: .clone, retiredFolders: ["Qwen3-TTS-12Hz-1.7B-Base-4bit"], detectedAtUTC: "2026-11-14T00:00:00Z",
                    paused: paused, lastFailure: failure?.rawValue
                ),
            ])
            return Policy.Candidate(
                modelID: "pro_clone", estimatedBytes: 2 * gigabyte, mode: .clone, plan: plan,
                pausedThisSession: false, transferring: false, failedThisSession: false
            )
        }
        let makeRoom = Policy.Decision.ask(modelIDs: ["pro_clone"], totalBytes: 2 * gigabyte, makesRoomFirst: true)
        XCTAssertEqual(decide([candidate(failure: .space)], consented: true), makeRoom)
        XCTAssertEqual(decide([candidate(failure: .space)]), makeRoom)
        XCTAssertEqual(
            decide([candidate(failure: .space), self.candidate("pro_custom")], consented: true),
            .ask(modelIDs: ["pro_custom", "pro_clone"], totalBytes: 4 * gigabyte, makesRoomFirst: true)
        )
        XCTAssertEqual(decide([candidate(failure: .space)], earlier: false), .none, "nothing left to remove")
        XCTAssertEqual(decide([candidate(failure: .space, paused: true)]), .none, "Later stopped it")
        XCTAssertEqual(decide([candidate(failure: .space)], lowDataMode: true), .none)
        XCTAssertEqual(decide([candidate(failure: .network)], consented: true), .none, "another failure waits for Retry")
    }

    private let simulatedAvailableBytesKey = "QVOICE_IOS_SIMULATED_AVAILABLE_BYTES"
    private let seedRetiredModelsKey = "QVOICE_IOS_SEED_RETIRED_MODELS"

    func testSimulatedAvailableBytesRespectsRuntimeDebugGateAndValidatesInput() {
        #if !(os(iOS) && !VOCELLO_INTERNAL_DIAGNOSTICS)
        XCTAssertEqual(simulatedAvailableBytesKey, Policy.simulatedAvailableBytesKey)
        #endif
        let systemBytes: Int64 = 50 * gigabyte
        let overrideBytes: Int64 = 500_000_000

        // Unset or gate off always returns the system value.
        XCTAssertEqual(
            Policy.resolvedAvailableBytes(systemAvailableBytes: systemBytes, environment: [:]),
            systemBytes
        )
        XCTAssertEqual(
            Policy.resolvedAvailableBytes(
                systemAvailableBytes: systemBytes,
                environment: [simulatedAvailableBytesKey: "\(overrideBytes)"]
            ),
            systemBytes,
            "Without QWENVOICE_DEBUG=1 the override must remain inert"
        )

        // With internalDiagnosticsAvailable == false (distribution builds), override stays inert.
        let armed = [
            "QWENVOICE_DEBUG": "1",
            simulatedAvailableBytesKey: " \(overrideBytes) ",
        ]
        XCTAssertEqual(
            Policy.resolvedAvailableBytes(
                systemAvailableBytes: systemBytes,
                environment: armed,
                internalDiagnosticsAvailable: false
            ),
            systemBytes
        )

        if RuntimeDebugGate.internalDiagnosticsAvailable {
            XCTAssertEqual(
                Policy.resolvedAvailableBytes(systemAvailableBytes: systemBytes, environment: armed),
                overrideBytes
            )
            XCTAssertEqual(
                decide(
                    [candidate("pro_custom", bytes: 2 * gigabyte)],
                    available: Policy.resolvedAvailableBytes(systemAvailableBytes: systemBytes, environment: armed)
                ),
                .ask(modelIDs: ["pro_custom"], totalBytes: 2 * gigabyte, makesRoomFirst: true)
            )
        } else {
            XCTAssertEqual(
                Policy.resolvedAvailableBytes(systemAvailableBytes: systemBytes, environment: armed),
                systemBytes
            )
        }
        for invalid in ["-1", "not-a-number", ""] {
            XCTAssertEqual(
                Policy.resolvedAvailableBytes(
                    systemAvailableBytes: systemBytes,
                    environment: ["QWENVOICE_DEBUG": "1", simulatedAvailableBytesKey: invalid]
                ),
                systemBytes,
                "Invalid override \(invalid) must fall back to system free space"
            )
        }
    }

    func testSeedRetiredModelsRequiresIsolatedRootAndContractAllowlistAndIsIdempotent() throws {
        #if !(os(iOS) && !VOCELLO_INTERNAL_DIAGNOSTICS)
        XCTAssertEqual(seedRetiredModelsKey, Policy.seedRetiredModelsKey)
        #endif
        let tempRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("IOSModelUpdateSeed-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: tempRoot, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: tempRoot) }

        let allowed: Set<String> = [
            "Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit",
            "Qwen3-TTS-12Hz-1.7B-Base-4bit",
        ]

        // Refuses without isolated QVOICE_APP_SUPPORT_DIR, without QWENVOICE_DEBUG,
        // without internalDiagnosticsAvailable, or with malformed/absolute QVOICE_APP_SUPPORT_DIR.
        for badSupport in [nil, "", ".", "..", "../escape", "a/b", "/tmp/canonical"] {
            var env = [
                "QWENVOICE_DEBUG": "1",
                seedRetiredModelsKey: "reset:Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit",
            ]
            if let badSupport {
                env["QVOICE_APP_SUPPORT_DIR"] = badSupport
            }
            XCTAssertEqual(
                Policy.seedRetiredModelsIfConfigured(
                    modelsDirectory: tempRoot,
                    allowedRetiredFolders: allowed,
                    environment: env
                ),
                .none,
                "Must refuse support root \(String(describing: badSupport))"
            )
        }
        XCTAssertEqual(
            Policy.seedRetiredModelsIfConfigured(
                modelsDirectory: tempRoot,
                allowedRetiredFolders: allowed,
                environment: [
                    "QVOICE_APP_SUPPORT_DIR": "upgrade-test",
                    seedRetiredModelsKey: "Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit",
                ]
            ),
            .none
        )
        XCTAssertEqual(
            Policy.seedRetiredModelsIfConfigured(
                modelsDirectory: tempRoot,
                allowedRetiredFolders: allowed,
                environment: [
                    "QWENVOICE_DEBUG": "1",
                    "QVOICE_APP_SUPPORT_DIR": "upgrade-test",
                    seedRetiredModelsKey: "Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit",
                ],
                internalDiagnosticsAvailable: false
            ),
            .none
        )

        guard RuntimeDebugGate.internalDiagnosticsAvailable else { return }

        // Rejects unknown and path-traversal entries while seeding allowed folders with a
        // schema-valid ModelAssetIntegrityManifest recognized by ModelUpdateLedger.
        let seeded = Policy.seedRetiredModelsIfConfigured(
            modelsDirectory: tempRoot,
            allowedRetiredFolders: allowed,
            environment: [
                "QWENVOICE_DEBUG": "1",
                "QVOICE_APP_SUPPORT_DIR": "upgrade-test",
                seedRetiredModelsKey: "../escape,unknown-folder,Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit",
            ]
        )
        XCTAssertEqual(
            seeded,
            Policy.SeedResult(didResetLedger: false, seededFolders: ["Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit"])
        )
        XCTAssertTrue(seeded.shouldClearConsent)
        let manifestURL = tempRoot.appendingPathComponent(
            "Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit/\(ModelAssetIntegrityManifest.filename)"
        )
        let decoded = try JSONDecoder().decode(ModelAssetIntegrityManifest.self, from: Data(contentsOf: manifestURL))
        XCTAssertEqual(decoded.targetFolder, "Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit")
        XCTAssertEqual(decoded.files.map(\.path), ["model.safetensors"])
        XCTAssertTrue(
            ModelUpdateLedger.holdsEarlierInstall("Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit", in: tempRoot),
            "Seeded retired folder must satisfy real ModelUpdateLedger.holdsEarlierInstall"
        )

        // Once a model-update ledger exists, subsequent launches never re-seed,
        // and `reset:` with only invalid folders must leave the existing ledger untouched.
        let ledgerURL = tempRoot.appendingPathComponent(".qwenvoice-model-update.json")
        try Data("{}".utf8).write(to: ledgerURL)
        XCTAssertEqual(
            Policy.seedRetiredModelsIfConfigured(
                modelsDirectory: tempRoot,
                allowedRetiredFolders: allowed,
                environment: [
                    "QWENVOICE_DEBUG": "1",
                    "QVOICE_APP_SUPPORT_DIR": "upgrade-test",
                    seedRetiredModelsKey: "reset:../escape,unknown-folder",
                ]
            ),
            .none
        )
        XCTAssertTrue(FileManager.default.fileExists(atPath: ledgerURL.path), "Invalid reset must not delete ledger")

        let secondPass = Policy.seedRetiredModelsIfConfigured(
            modelsDirectory: tempRoot,
            allowedRetiredFolders: allowed,
            environment: [
                "QWENVOICE_DEBUG": "1",
                "QVOICE_APP_SUPPORT_DIR": "upgrade-test",
                seedRetiredModelsKey: "Qwen3-TTS-12Hz-1.7B-Base-4bit",
            ]
        )
        XCTAssertEqual(secondPass, .none)
        XCTAssertFalse(
            FileManager.default.fileExists(
                atPath: tempRoot.appendingPathComponent("Qwen3-TTS-12Hz-1.7B-Base-4bit").path
            )
        )

        // Explicit `reset:` on an ALREADY-EXISTING retired folder clears the ledger AND reports
        // `shouldClearConsent == true` even when no new folder had to be written.
        let resetExisting = Policy.seedRetiredModelsIfConfigured(
            modelsDirectory: tempRoot,
            allowedRetiredFolders: allowed,
            environment: [
                "QWENVOICE_DEBUG": "1",
                "QVOICE_APP_SUPPORT_DIR": "upgrade-test",
                seedRetiredModelsKey: "reset:Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit",
            ]
        )
        XCTAssertEqual(resetExisting, Policy.SeedResult(didResetLedger: true, seededFolders: []))
        XCTAssertTrue(resetExisting.shouldClearConsent)
        XCTAssertFalse(FileManager.default.fileExists(atPath: ledgerURL.path))
    }

    func testResolvedModelUpdateConsentKeyIsolatesFromCanonicalDefaults() {
        let canonical = IOSAppDefaults.modelUpdateConsentKey
        XCTAssertEqual(IOSAppDefaults.resolvedModelUpdateConsentKey(environment: [:]), canonical)
        XCTAssertEqual(
            IOSAppDefaults.resolvedModelUpdateConsentKey(environment: [
                "QVOICE_APP_SUPPORT_DIR": "model-upgrade-acceptance",
            ]),
            canonical,
            "Without QWENVOICE_DEBUG=1 the consent key must stay canonical"
        )
        for unsafeRoot in ["", ".", "..", "../escape", "a/b", "/tmp/canonical"] {
            XCTAssertEqual(
                IOSAppDefaults.resolvedModelUpdateConsentKey(environment: [
                    "QWENVOICE_DEBUG": "1",
                    "QVOICE_APP_SUPPORT_DIR": unsafeRoot,
                ]),
                canonical,
                "Unsafe support root \(unsafeRoot) must not create an isolated consent key"
            )
        }
        let isolatedKey = IOSAppDefaults.resolvedModelUpdateConsentKey(environment: [
            "QWENVOICE_DEBUG": "1",
            "QVOICE_APP_SUPPORT_DIR": "model-upgrade-acceptance",
        ])
        if RuntimeDebugGate.internalDiagnosticsAvailable {
            XCTAssertEqual(isolatedKey, "\(canonical).isolated.model-upgrade-acceptance")
            XCTAssertNotEqual(isolatedKey, canonical)
        } else {
            XCTAssertEqual(isolatedKey, canonical)
        }
    }

    /// RB-12: subtracting verified 682 MB shared tokenizer bytes avoids triggering destructive
    /// `makesRoomFirst` when the volume has room for the actual remaining bytes (~1.57 GB -> 3.14 GB).
    func testSubtractingVerifiedSharedBytesAvoidsUnnecessaryMakeRoom() {
        let fullArtifact: Int64 = 2_250_000_000
        let sharedTokenizer: Int64 = 682_000_000
        let effective = Policy.effectiveDownloadBytes(
            estimatedBytes: fullArtifact,
            reusableSharedBytes: sharedTokenizer
        )
        XCTAssertEqual(effective, fullArtifact - sharedTokenizer)
        XCTAssertEqual(Policy.effectiveDownloadBytes(estimatedBytes: 100, reusableSharedBytes: 500), 0)

        let availableBytes: Int64 = 3_500_000_000
        XCTAssertEqual(
            decide([candidate("pro_custom", bytes: fullArtifact)], available: availableBytes),
            .ask(modelIDs: ["pro_custom"], totalBytes: fullArtifact, makesRoomFirst: true),
            "overcounting the 682 MB shared tokenizer forces destructive Make Room at 3.5 GB free"
        )
        XCTAssertEqual(
            decide([candidate("pro_custom", bytes: effective)], available: availableBytes),
            .ask(modelIDs: ["pro_custom"], totalBytes: effective, makesRoomFirst: false),
            "subtracting verified shared bytes keeps earlier models intact until the new model verifies"
        )
    }

    /// RB-12: iOS mirrors macOS `afterMakingRoom`, refusing to start doomed downloads when
    /// `removeRetiredFoldersBeforeUpdate()` removed nothing.
    func testAfterMakingRoomRefusesToStartWhenNothingWasRemoved() {
        XCTAssertEqual(
            Policy.afterMakingRoom(RetiredModelReclamation(removed: [], failed: ["old": "locked"])),
            .roomNotMade
        )
        XCTAssertEqual(
            Policy.afterMakingRoom(RetiredModelReclamation(removed: ["old"], failed: [:])),
            .startUpdate
        )
    }

    /// RB-06 / RF-59: on a real 3.0 -> 3.1 upgrade, `restoreInFlightDownloadsIfNeeded()` marks the
    /// prior 3.0 `.installed` ledger entry as `.failed` (`artifactIsCurrent: false`). Checking
    /// `isCurrentArtifactFailed` against the 3.1 artifact version returns `false` so the RF-59
    /// one-time Update prompt is still shown (and a real 3.1 `.failed` entry still suppresses it).
    func testSupersededEarlierArtifactFailureInLedgerDoesNotSuppressUpgradePrompt() {
        var earlierInstalled = IOSModelDownloadLedger.Request(
            logicalRequestID: "req-3-0",
            modelID: "pro_custom",
            artifactVersion: "v3.0.0",
            repo: "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit",
            revision: String(repeating: "a", count: 40),
            targetFolder: "Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit",
            expectedFiles: ["model.safetensors"],
            verifiedFiles: [],
            retryCount: 0,
            receivedBytes: 2_000_000_000,
            totalBytes: 2_000_000_000,
            status: .installed
        )
        XCTAssertEqual(
            earlierInstalled.restoreAction(artifactIsCurrent: false, targetIsInstalled: false),
            .markFailed
        )
        earlierInstalled.status = .failed
        let ledgerAfterUpgradeRestore = IOSModelDownloadLedger(requests: [earlierInstalled])
        let plan = ModelUpdatePlan(entries: [
            .custom: .init(
                mode: .custom,
                retiredFolders: ["Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit"],
                detectedAtUTC: "2026-11-21T00:00:00Z",
                paused: false
            ),
        ])

        let upgradeCandidate = Policy.Candidate(
            modelID: "pro_custom",
            estimatedBytes: 2_000_000_000,
            mode: .custom,
            plan: plan,
            pausedThisSession: false,
            transferring: false,
            failedThisSession: ledgerAfterUpgradeRestore.isCurrentArtifactFailed(
                modelID: "pro_custom",
                artifactVersion: "v3.1.0"
            )
        )
        XCTAssertFalse(upgradeCandidate.failed)
        XCTAssertEqual(
            decide([upgradeCandidate], consented: false),
            .ask(modelIDs: ["pro_custom"], totalBytes: 2_000_000_000, makesRoomFirst: false),
            "3.0 -> 3.1 upgrade must still present the RF-59 Update prompt"
        )

        let currentFailed = IOSModelDownloadLedger.Request(
            logicalRequestID: "req-3-1",
            modelID: "pro_custom",
            artifactVersion: "v3.1.0",
            repo: "patricedery/Qwen3-TTS-12Hz-1.7B-CustomVoice-Hybrid",
            revision: String(repeating: "b", count: 40),
            targetFolder: "Qwen3-TTS-12Hz-1.7B-CustomVoice-Hybrid",
            expectedFiles: ["model.safetensors"],
            verifiedFiles: [],
            retryCount: 1,
            receivedBytes: 500_000_000,
            totalBytes: 2_000_000_000,
            status: .failed
        )
        let currentFailedLedger = IOSModelDownloadLedger(requests: [currentFailed])
        let failedCurrentCandidate = Policy.Candidate(
            modelID: "pro_custom",
            estimatedBytes: 2_000_000_000,
            mode: .custom,
            plan: plan,
            pausedThisSession: false,
            transferring: false,
            failedThisSession: currentFailedLedger.isCurrentArtifactFailed(
                modelID: "pro_custom",
                artifactVersion: "v3.1.0"
            )
        )
        XCTAssertTrue(failedCurrentCandidate.failed)
        XCTAssertEqual(
            decide([failedCurrentCandidate], consented: true),
            .none,
            "a genuine 3.1 failure waits for explicit Retry (NET-1)"
        )
    }
}
