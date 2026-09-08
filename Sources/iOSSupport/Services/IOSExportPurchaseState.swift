import Foundation
import Observation

struct IOSExportProduct: Equatable, Sendable {
    let id: String
    let displayPrice: String
}

struct IOSExportTransaction: Equatable, Sendable {
    let id: UInt64
    let productID: String
    let verified: Bool
    let nonConsumable: Bool
    let revoked: Bool

    var grantsUnlock: Bool {
        verified && nonConsumable && !revoked && productID == IOSExportAccessPolicy.productID
    }
}

enum IOSExportPurchaseResult: Sendable {
    case success(IOSExportTransaction)
    case cancelled
    case pending
}

@MainActor
protocol IOSExportPurchaseClient: AnyObject {
    func product() async throws -> IOSExportProduct?
    func currentEntitlements() async -> [IOSExportTransaction]
    func purchase() async throws -> IOSExportPurchaseResult
    func sync() async throws
    func finish(_ transaction: IOSExportTransaction) async
    func observe(_ receive: @escaping @MainActor (IOSExportTransaction) async -> Void) async
}

/// One app-lifetime owner, with an injectable StoreKit boundary for deterministic
/// tests. Entitlements are rebuilt from verified StoreKit data, never preferences.
@MainActor @Observable
final class IOSExportPurchaseState {
    enum Access: Equatable { case checking, locked, unlocked }
    enum Operation: Equatable { case idle, loading, purchasing, restoring }
    enum Notice: Equatable { case pending, cancelled, failed, unavailable, unverified, restored, notOwned }

    private(set) var access: Access = .checking
    private(set) var operation: Operation = .idle
    private(set) var product: IOSExportProduct?
    private(set) var notice: Notice?
    private let client: any IOSExportPurchaseClient
    private var revision = 0
    private var refreshRevision = 0
    @ObservationIgnored private var ownedTransactions: Set<UInt64> = []
    @ObservationIgnored private var revokedTransactions: Set<UInt64> = []
    @ObservationIgnored private var listener: Task<Void, Never>?

    init(client: any IOSExportPurchaseClient) { self.client = client }
    deinit { listener?.cancel() }

    func start() {
        guard listener == nil else { return }
        let client = client
        listener = Task { [weak self] in
            await client.observe { [weak self] transaction in
                await self?.receive(transaction)
            }
        }
    }

    func refresh() async {
        start()
        refreshRevision += 1
        let requestRevision = refreshRevision
        let observedRevision = revision
        let transactions = await client.currentEntitlements()
        guard !Task.isCancelled, requestRevision == refreshRevision,
              observedRevision == revision else { return }
        ownedTransactions = Set(transactions.filter {
            $0.grantsUnlock && !revokedTransactions.contains($0.id)
        }.map(\.id))
        access = ownedTransactions.isEmpty ? .locked : .unlocked
    }

    func loadProduct() async {
        guard operation == .idle else { return }
        operation = .loading
        defer { operation = .idle }
        do {
            let value = try await client.product()
            product = value?.id == IOSExportAccessPolicy.productID ? value : nil
            notice = product == nil ? .unavailable : nil
        } catch { product = nil; notice = .unavailable }
    }

    func purchase() async {
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

    func restore() async {
        guard operation == .idle else { return }
        operation = .restoring
        notice = nil
        defer { operation = .idle }
        do {
            // Only an explicit Restore action may prompt for an Apple Account.
            try await client.sync()
            await refresh()
            notice = access == .unlocked ? .restored : .notOwned
        } catch { notice = .failed }
    }

    func permits(_ items: [IOSExportProvenance]) -> Bool {
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
