import StoreKit

@MainActor
enum IOSExportCommerce {
    static let shared = IOSExportPurchaseState(client: IOSStoreKitClient())
}

/// Only this adapter touches StoreKit. No server, analytics or receipt logging.
@MainActor
final class IOSStoreKitClient: IOSExportPurchaseClient {
    private var loadedProduct: Product?
    private var pending: [UInt64: StoreKit.Transaction] = [:]

    func product() async throws -> IOSExportProduct? {
        loadedProduct = try await Product.products(for: [IOSExportAccessPolicy.productID])
            .first { $0.id == IOSExportAccessPolicy.productID && $0.type == .nonConsumable }
        return loadedProduct.map { IOSExportProduct(id: $0.id, displayPrice: $0.displayPrice) }
    }

    func currentEntitlements() async -> [IOSExportTransaction] {
        var result: [IOSExportTransaction] = []
        for await verification in StoreKit.Transaction.currentEntitlements {
            if Task.isCancelled { break }
            result.append(Self.summary(verification))
        }
        return result
    }

    func purchase() async throws -> IOSExportPurchaseResult {
        guard let loadedProduct else { throw CommerceError.productUnavailable }
        switch try await loadedProduct.purchase() {
        case .success(let verification):
            retainForFinish(verification)
            return .success(Self.summary(verification))
        case .userCancelled: return .cancelled
        case .pending: return .pending
        @unknown default: throw CommerceError.unsupportedResult
        }
    }

    func sync() async throws { try await AppStore.sync() }

    func finish(_ transaction: IOSExportTransaction) async {
        guard let native = pending.removeValue(forKey: transaction.id) else { return }
        await native.finish()
    }

    func observe(_ receive: @escaping @MainActor (IOSExportTransaction) async -> Void) async {
        for await verification in StoreKit.Transaction.updates {
            guard !Task.isCancelled else { return }
            retainForFinish(verification)
            await receive(Self.summary(verification))
        }
    }

    private func retainForFinish(_ result: VerificationResult<StoreKit.Transaction>) {
        guard case .verified(let transaction) = result,
              transaction.productID == IOSExportAccessPolicy.productID,
              transaction.productType == .nonConsumable else { return }
        pending[transaction.id] = transaction
    }

    private static func summary(_ result: VerificationResult<StoreKit.Transaction>) -> IOSExportTransaction {
        let transaction: StoreKit.Transaction
        let verified: Bool
        switch result {
        case .verified(let value): transaction = value; verified = true
        case .unverified(let value, _): transaction = value; verified = false
        }
        return IOSExportTransaction(id: transaction.id, productID: transaction.productID,
            verified: verified, nonConsumable: transaction.productType == .nonConsumable,
            revoked: transaction.revocationDate != nil || transaction.isUpgraded)
    }

    private enum CommerceError: Error { case productUnavailable, unsupportedResult }
}
