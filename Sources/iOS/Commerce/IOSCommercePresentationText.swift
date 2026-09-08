import Foundation

/// iOS-only purchase copy; live prices always come from StoreKit.
extension VocelloPresentationText {
    static var exportPrivacy: String {
        String(localized: "vocello.export.privacy", defaultValue: "Privacy Policy",
               comment: "Opens the published Vocello privacy policy.")
    }
    static var exportSupport: String {
        String(localized: "vocello.export.support", defaultValue: "Help & Support",
               comment: "Opens the published Vocello support contact page.")
    }
    static var exportUnlockTitle: String {
        String(localized: "vocello.export.unlock_title", defaultValue: "Design & Clone Export",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportUnlockDetail: String {
        String(localized: "vocello.export.unlock_detail", defaultValue: "Generate, listen, and keep every take in History for free. Built-in exports are free. A one-time purchase unlocks sharing and saving Voice Design and Voice Clone audio outside Vocello on iOS.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportUnlocked: String {
        String(localized: "vocello.export.unlocked", defaultValue: "Export unlocked",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportRetryAfterPurchase: String {
        String(localized: "vocello.export.retry_export", defaultValue: "Close this sheet and choose Share or Download again to export your selected clip.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportProductUnavailable: String {
        String(localized: "vocello.export.unavailable", defaultValue: "The purchase is currently unavailable. Your audio stays in Vocello. You can try again or restore an existing purchase.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportReloadProduct: String {
        String(localized: "vocello.export.reload", defaultValue: "Try Again",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportChecking: String {
        String(localized: "vocello.export.checking", defaultValue: "Checking purchase…",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportRestore: String {
        String(localized: "vocello.export.restore", defaultValue: "Restore Purchases",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportClose: String {
        String(localized: "vocello.export.close", defaultValue: "Done",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportViewOptions: String {
        String(localized: "vocello.export.view_options", defaultValue: "View options",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportOptionsHint: String {
        String(localized: "vocello.export.options_hint", defaultValue: "Opens export purchase options and Restore Purchases",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportFolderDetail: String {
        String(localized: "vocello.export.folder_detail", defaultValue: "All clips stay in History. An optional Files folder also receives new Built-in clips; Design and Clone copies require the export unlock. If purchase access is still being checked, export those clips manually from History afterward.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportNoticePending: String {
        String(localized: "vocello.export.pending", defaultValue: "Purchase pending approval. You can continue generating and listening.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportNoticeCancelled: String {
        String(localized: "vocello.export.cancelled", defaultValue: "Purchase cancelled. No export access was changed.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportNoticeFailed: String {
        String(localized: "vocello.export.failed", defaultValue: "The App Store operation could not complete. Try again. Your clips remain in History.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportNoticeUnverified: String {
        String(localized: "vocello.export.unverified", defaultValue: "The purchase could not be verified. Try Restore Purchases or contact support.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportNoticeRestored: String {
        String(localized: "vocello.export.restored", defaultValue: "Your export purchase has been restored.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static var exportNoticeNotOwned: String {
        String(localized: "vocello.export.not_owned", defaultValue: "No export purchase was found for this Apple Account.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    static func exportBuy(_ price: String) -> String {
        String.localizedStringWithFormat(String(localized: "vocello.export.buy",
            defaultValue: "Unlock exports — %@", comment: "One-time purchase; substitution is the App Store localized price."), price)
    }

    static func exportPurchaseNotice(_ notice: IOSExportPurchaseState.Notice) -> String {
        switch notice {
        case .pending: exportNoticePending
        case .cancelled: exportNoticeCancelled
        case .failed: exportNoticeFailed
        case .unavailable: exportProductUnavailable
        case .unverified: exportNoticeUnverified
        case .restored: exportNoticeRestored
        case .notOwned: exportNoticeNotOwned
        }
    }
}
