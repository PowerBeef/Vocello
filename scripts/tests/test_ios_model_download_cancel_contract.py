#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "Sources/iOS/IOSModelDownloadCoordinator.swift"
VIEW_MODEL = REPO_ROOT / "Sources/iOS/IOSModelInstallerViewModel.swift"
DOWNLOADER = REPO_ROOT / "Sources/QwenVoiceCore/HuggingFaceDownloader.swift"


class IOSModelDownloadCancelContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.view_model = VIEW_MODEL.read_text(encoding="utf-8")
        cls.downloader = DOWNLOADER.read_text(encoding="utf-8")
        cls.cancel_body = cls.source.split(
            "func cancel(modelID: String) async -> Bool {", 1
        )[1].split("\n    func delete(model:", 1)[0]
        cls.restore_body = cls.source.split(
            "func restoreInFlightDownloadsIfNeeded() async {", 1
        )[1].split("\n    func resumeBackgroundEventsIfNeeded", 1)[0]
        cls.progress_body = cls.source.split(
            "private func handleProgress(", 1
        )[1].split("\n    private func resolveFiles", 1)[0]
        cls.persist_progress_body = cls.source.split(
            "private func persistProgressIfNeeded(", 1
        )[1].split("\n    private func recordVerifiedFile", 1)[0]
        cls.run_download_body = cls.source.split(
            "private func runDownload(", 1
        )[1].split("\n    private func makeSharedDownloader", 1)[0]
        cls.cancel_view_model_body = cls.view_model.split(
            "func cancel(_ model: TTSModel) {", 1
        )[1].split("\n    func delete(_ model:", 1)[0]

    def test_active_cancel_is_durable_before_task_cancellation(self) -> None:
        barrier = self.cancel_body.index("cancellationBarriers.insert(modelID)")
        persisted = self.cancel_body.index(
            "persistCancellationStatus(modelID: modelID, status: .cancelRequested)"
        )
        task_cancelled = self.cancel_body.index("await downloader.cancel()")
        self.assertLess(barrier, persisted)
        self.assertLess(persisted, task_cancelled)

    def test_staging_is_removed_only_after_durable_tombstone(self) -> None:
        tombstone = self.cancel_body.rindex(
            "persistCancellationStatus(modelID: modelID, status: .deleted)"
        )
        staging_removed = self.cancel_body.rindex(
            "fileManager.removeItem(at: active.stagingRoot)"
        )
        published_deleted = self.cancel_body.rindex(
            "publishTerminal(modelID: modelID, phase: .deleted)"
        )
        self.assertLess(tombstone, staging_removed)
        self.assertLess(tombstone, published_deleted)

    def test_late_atomic_install_is_rolled_back_before_tombstone(self) -> None:
        task_finished = self.cancel_body.rindex("await active.task.value")
        rollback = self.cancel_body.rindex("rollbackRacedInstallationIfNeeded(active)")
        tombstone = self.cancel_body.rindex(
            "persistCancellationStatus(modelID: modelID, status: .deleted)"
        )
        self.assertLess(task_finished, rollback)
        self.assertLess(rollback, tombstone)
        rollback_body = self.source.split(
            "private func rollbackRacedInstallationIfNeeded(", 1
        )[1].split("\n    private func reconcileInstalledAfterCancellationCleanupFailure", 1)[0]
        self.assertIn("!active.targetWasAvailableAtStart", rollback_body)
        self.assertIn(
            "SharedModelComponentStore(modelsRoot: AppPaths.modelsDir).deleteModel(",
            rollback_body,
        )
        self.assertIn("modelFolder: active.targetDir.lastPathComponent", rollback_body)

    def test_failed_install_rollback_reconciles_ledger_before_visible_success(self) -> None:
        rollback_failure = self.cancel_body.index(
            "reconcileInstalledAfterCancellationCleanupFailure(active)"
        )
        tombstone = self.cancel_body.rindex(
            "persistCancellationStatus(modelID: modelID, status: .deleted)"
        )
        self.assertLess(rollback_failure, tombstone)

        reconcile_body = self.source.split(
            "private func reconcileInstalledAfterCancellationCleanupFailure(", 1
        )[1].split("\n    /// A completion can win", 1)[0]
        persisted = reconcile_body.index("try persistLedgerUpdate(modelID: active.modelID)")
        status = reconcile_body.index("request.status = .installed")
        bytes_recorded = reconcile_body.index(
            "request.receivedBytes = max(request.receivedBytes, active.totalBytes)"
        )
        visible_success = reconcile_body.index("phase: .installed")
        self.assertLess(persisted, status)
        self.assertLess(status, bytes_recorded)
        self.assertLess(bytes_recorded, visible_success)
        self.assertIn('classification: "cancellation-install-reconcile"', reconcile_body)
        self.assertIn("phase: .failed", reconcile_body)
        self.assertIn(
            "CancellationInstallReconciliationError.privacySafeMessage",
            reconcile_body,
        )

    def test_durability_failure_surfaces_without_claiming_deleted(self) -> None:
        self.assertIn("publishCancellationPersistenceFailure(modelID: modelID)", self.cancel_body)
        self.assertIn("return false", self.cancel_body)
        self.assertNotIn("markLedgerTerminal(modelID: modelID", self.cancel_body)

    def test_restore_handles_cancelled_records_before_queueing(self) -> None:
        cancelled = self.restore_body.index(
            "request.status == .cancelRequested || request.status == .deleted"
        )
        queued = self.restore_body.index("ledger.requests[index].status = .queued")
        self.assertLess(cancelled, queued)
        self.assertIn("continue", self.restore_body[cancelled:queued])

    def test_progress_cannot_weaken_durable_cancellation(self) -> None:
        self.assertIn(
            "!cancellationBarriers.contains(active.modelID)",
            self.progress_body,
        )
        self.assertIn("guard persistProgressIfNeeded(", self.progress_body)
        self.assertIn(
            "guard !cancellationBarriers.contains(modelID) else { return false }",
            self.persist_progress_body,
        )
        self.assertIn("durableStatus != .cancelRequested", self.persist_progress_body)
        self.assertIn("durableStatus != .deleted", self.persist_progress_body)
        self.assertEqual(
            self.run_download_body.count("!cancellationBarriers.contains(model.id)"),
            3,
        )

    def test_failed_initial_cancel_keeps_active_generation_recoverable(self) -> None:
        active_guard = self.cancel_body.index("guard let active = inflight[modelID]")
        failure = self.cancel_body.index(
            "recoverableGeneration: active.operationGeneration",
            active_guard,
        )
        cancellation = self.cancel_body.index("await downloader.cancel()", active_guard)
        self.assertLess(failure, cancellation)

    def test_no_op_cancel_reconciles_without_optimistic_cancelling_state(self) -> None:
        self.assertIn("reconcileNoOpCancellation(modelID: modelID)", self.cancel_body)
        self.assertNotIn("states[model.id] = .cancelling", self.cancel_view_model_body)
        reconcile_body = self.source.split(
            "private func reconcileNoOpCancellation(modelID: String) {", 1
        )[1].split("\n    private func updateRequest", 1)[0]
        self.assertIn("phase: .installed", reconcile_body)
        self.assertIn("phase: .deleted", reconcile_body)
        self.assertIn("publishFailed(", reconcile_body)

    def test_shared_downloader_rechecks_late_cancellation_at_terminal_boundaries(self) -> None:
        terminal_body = self.downloader.split(
            "try await downloadAllFiles(", 1
        )[1].split("\n        } catch {", 1)[0]
        download_finished = terminal_body.index(")\n            try await throwIfCancellationRequested()")
        verifying = terminal_body.index("await state.setPhase(.verifying)")
        verified = terminal_body.index("try await verifyDownloadedFilesUsingReceipts(")
        manifest = terminal_body.index("try persistInstalledIntegrityManifest(")
        installing = terminal_body.index("await state.setPhase(.installing)")
        atomic_install = terminal_body.index("try installStagedRepository(")
        self.assertLess(download_finished, verifying)
        self.assertLess(verifying, verified)
        self.assertLess(verified, manifest)
        self.assertLess(manifest, installing)
        self.assertLess(installing, atomic_install)
        self.assertEqual(terminal_body.count("try await throwIfCancellationRequested()"), 6)


if __name__ == "__main__":
    unittest.main()
