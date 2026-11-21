import Foundation
import Observation

public struct IOSExportProduct: Equatable, Sendable {
    public let id: String
    public let displayPrice: String

    public init(id: String, displayPrice: String) {
        self.id = id
        self.displayPrice = displayPrice
    }
}

public struct IOSExportTransaction: Equatable, Sendable {
    public let id: UInt64
    public let productID: String
    public let verified: Bool
    public let nonConsumable: Bool
    public let revoked: Bool

    public init(
        id: UInt64,
        productID: String,
        verified: Bool,
        nonConsumable: Bool,
        revoked: Bool
    ) {
        self.id = id
        self.productID = productID
        self.verified = verified
        self.nonConsumable = nonConsumable
        self.revoked = revoked
    }

    public var grantsUnlock: Bool {
        verified && nonConsumable && !revoked && productID == IOSExportAccessPolicy.productID
    }
}

public enum IOSExportPurchaseResult: Sendable {
    case success(IOSExportTransaction)
    case cancelled
    case pending
}

/// Restore's App Store sync: completed, or the Apple Account prompt the user
/// dismissed (A4-02). Every other outcome is a thrown failure.
public enum IOSExportSyncResult: Sendable {
    case synced
    case cancelled
}

@MainActor
public protocol IOSExportPurchaseClient: AnyObject {
    func product() async throws -> IOSExportProduct?
    func currentEntitlements() async -> [IOSExportTransaction]
    func purchase() async throws -> IOSExportPurchaseResult
    func sync() async throws -> IOSExportSyncResult
    func finish(_ transaction: IOSExportTransaction) async
    func observe(_ receive: @escaping @MainActor (IOSExportTransaction) async -> Void) async
}

/// One app-lifetime owner, with an injectable StoreKit boundary for deterministic
/// tests. Entitlements are rebuilt from verified StoreKit data, never preferences.
@MainActor @Observable
public final class IOSExportPurchaseState {
    public enum Access: Equatable, Sendable { case checking, locked, unlocked }
    public enum Operation: Equatable, Sendable { case idle, loading, purchasing, restoring }
    public enum Notice: Equatable, Sendable { case pending, cancelled, failed, unavailable, unverified, restored, notOwned, restoreCancelled }

    public private(set) var access: Access = .checking
    public private(set) var operation: Operation = .idle
    public private(set) var product: IOSExportProduct?
    public private(set) var notice: Notice?
    private let client: any IOSExportPurchaseClient
    private var revision = 0
    /// IOS-19: one entitlement scan runs at a time and every `refresh()` joins
    /// it. A caller that arrived after the running scan began waits for it and
    /// then for one more scan, shared by every such caller, so no caller
    /// returns with the value an older or superseded scan left behind.
    @ObservationIgnored private var scanTask: Task<Void, Never>?
    @ObservationIgnored private var requestedScans = 0
    @ObservationIgnored private var coveredScans = 0
    @ObservationIgnored private var ownedTransactions: Set<UInt64> = []
    @ObservationIgnored private var revokedTransactions: Set<UInt64> = []
    @ObservationIgnored private var listener: Task<Void, Never>?

    public init(client: any IOSExportPurchaseClient) { self.client = client }
    deinit { listener?.cancel() }

    public func start() {
        guard listener == nil else { return }
        let client = client
        listener = Task { [weak self] in
            await client.observe { [weak self] transaction in
                await self?.receive(transaction)
            }
        }
    }

    /// Returns once a scan that began after this call has settled `access`
    /// (or a newer transaction decided it), so the caller acts on current state.
    public func refresh() async {
        start()
        requestedScans += 1
        let request = requestedScans
        while coveredScans < request, !Task.isCancelled {
            if let scanTask {
                await scanTask.value
            } else {
                let task = Task { await self.scanEntitlements() }
                scanTask = task
                await task.value
            }
        }
    }

    private func scanEntitlements() async {
        let covers = requestedScans
        let observedRevision = revision
        defer {
            coveredScans = max(coveredScans, covers)
            scanTask = nil
        }
        let transactions = await client.currentEntitlements()
        // A transaction received meanwhile is newer than this scan and already
        // decided access; the older snapshot cannot undo it.
        guard observedRevision == revision else { return }
        ownedTransactions = Set(transactions.filter {
            $0.grantsUnlock && !revokedTransactions.contains($0.id)
        }.map(\.id))
        access = ownedTransactions.isEmpty ? .locked : .unlocked
    }

    public func loadProduct() async {
        guard operation == .idle else { return }
        operation = .loading
        defer { operation = .idle }
        do {
            let value = try await client.product()
            product = value?.id == IOSExportAccessPolicy.productID ? value : nil
            notice = product == nil ? .unavailable : nil
        } catch { product = nil; notice = .unavailable }
    }

    public func purchase() async {
        guard operation == .idle, product?.id == IOSExportAccessPolicy.productID else { return }
        operation = .purchasing
        notice = nil
        defer { operation = .idle }
        do {
            switch try await client.purchase() {
            case .success(let transaction): await receive(transaction)
            case .cancelled: notice = .cancelled
            case .pending: notice = .pending
            }
        } catch { notice = .failed }
    }

    public func restore() async {
        guard operation == .idle else { return }
        operation = .restoring
        notice = nil
        defer { operation = .idle }
        do {
            // Only an explicit Restore action may prompt for an Apple Account.
            // Dismissing that prompt is the user's choice, not an App Store
            // failure, and leaves access as it was (A4-02).
            guard try await client.sync() == .synced else {
                notice = .restoreCancelled
                return
            }
            await refresh()
            notice = access == .unlocked ? .restored : .notOwned
        } catch { notice = .failed }
    }

    public func permits(_ items: [IOSExportProvenance]) -> Bool {
        IOSExportAccessPolicy.permits(items, unlocked: access == .unlocked)
    }

    private func receive(_ transaction: IOSExportTransaction) async {
        guard transaction.productID == IOSExportAccessPolicy.productID else { return }
        guard transaction.verified, transaction.nonConsumable else {
            notice = .unverified
            return
        }
        revision += 1 // An older entitlement scan cannot undo this update.
        if transaction.revoked {
            revokedTransactions.insert(transaction.id)
            ownedTransactions.remove(transaction.id)
        } else if !revokedTransactions.contains(transaction.id) {
            ownedTransactions.insert(transaction.id)
        }
        // A delayed success for a refunded transaction cannot re-grant access;
        // refunding an older purchase cannot revoke a distinct valid purchase.
        access = ownedTransactions.isEmpty ? .locked : .unlocked
        notice = nil
        await client.finish(transaction)
    }
}
