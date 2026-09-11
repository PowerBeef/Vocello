import Foundation

/// iOS-only purchase copy; live prices always come from StoreKit.
extension VocelloPresentationText {
    var exportRootSummary: String {
        localization.string(localized: "vocello.export.root_summary", defaultValue: "One-time export unlock",
               comment: "iOS export purchase presentation; never substitute a fixed price or imply generation is paid.")
    }
    var exportBenefit: String {
        localization.string(localized: "vocello.export.benefit", defaultValue: "Save and share audio created with Voice Design and Voice Clone.",
               comment: "iOS export purchase presentation; never substitute a fixed price or imply generation is paid.")
    }
    var exportFreeDetail: String {
        localization.string(localized: "vocello.export.free_detail", defaultValue: "Generation, listening, and History are free in every mode. Built-in voice exports are free too.",
               comment: "iOS export purchase presentation; never substitute a fixed price or imply generation is paid.")
    }
    var exportOneTime: String {
        localization.string(localized: "vocello.export.one_time", defaultValue: "One-time purchase. No subscription.",
               comment: "iOS export purchase presentation; never substitute a fixed price or imply generation is paid.")
    }
    var exportThanks: String {
        localization.string(localized: "vocello.export.thanks", defaultValue: "Thank you for supporting Vocello. Your purchase helps fund its continued development and future independent projects.",
               comment: "iOS export purchase presentation; never substitute a fixed price or imply generation is paid.")
    }
    var exportPrivacy: String {
        localization.string(localized: "vocello.export.privacy", defaultValue: "Privacy Policy",
               comment: "Opens the published Vocello privacy policy.")
    }
    var exportSupport: String {
        localization.string(localized: "vocello.export.support", defaultValue: "Help & Support",
               comment: "Opens the published Vocello support contact page.")
    }
    var exportUnlockTitle: String {
        localization.string(localized: "vocello.export.unlock_title", defaultValue: "Design & Clone Export",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportUnlockDetail: String {
        localization.string(localized: "vocello.export.unlock_detail", defaultValue: "Generate, listen, and keep every take in History for free. Built-in exports are free. A one-time purchase unlocks sharing and saving Voice Design and Voice Clone audio outside Vocello on iOS.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportUnlocked: String {
        localization.string(localized: "vocello.export.unlocked", defaultValue: "Export unlocked",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportRetryAfterPurchase: String {
        localization.string(localized: "vocello.export.retry_export", defaultValue: "Close this sheet and choose Share or Download again to export your selected clip.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportProductUnavailable: String {
        localization.string(localized: "vocello.export.unavailable", defaultValue: "The purchase is currently unavailable. Your audio stays in Vocello. You can try again or restore an existing purchase.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportReloadProduct: String {
        localization.string(localized: "vocello.export.reload", defaultValue: "Try Again",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportOwnedProductUnavailable: String {
        localization.string(localized: "vocello.export.owned_unavailable", defaultValue: "Purchase information is currently unavailable. Your export unlock is still active; you can save and share audio in every mode.",
               comment: "Product information failed to load, but the existing verified export entitlement remains active. Do not imply exports are blocked.")
    }

    var exportChecking: String {
        localization.string(localized: "vocello.export.checking", defaultValue: "Checking purchase…",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportRestore: String {
        localization.string(localized: "vocello.export.restore", defaultValue: "Restore Purchases",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportClose: String {
        localization.string(localized: "vocello.export.close", defaultValue: "Done",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportViewOptions: String {
        localization.string(localized: "vocello.export.view_options", defaultValue: "View options",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportOptionsHint: String {
        localization.string(localized: "vocello.export.options_hint", defaultValue: "Opens export purchase options and Restore Purchases",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportFolderDetail: String {
        localization.string(localized: "vocello.export.folder_detail", defaultValue: "All clips stay in History. An optional Files folder also receives new Built-in clips; Design and Clone copies require the export unlock. If purchase access is still being checked, export those clips manually from History afterward.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportNoticePending: String {
        localization.string(localized: "vocello.export.pending", defaultValue: "Purchase pending approval. You can continue generating and listening.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportNoticeCancelled: String {
        localization.string(localized: "vocello.export.cancelled", defaultValue: "Purchase cancelled. No export access was changed.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportNoticeFailed: String {
        localization.string(localized: "vocello.export.failed", defaultValue: "The App Store operation could not complete. Try again. Your clips remain in History.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportNoticeUnverified: String {
        localization.string(localized: "vocello.export.unverified", defaultValue: "The purchase could not be verified. Try Restore Purchases or contact support.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportNoticeRestored: String {
        localization.string(localized: "vocello.export.restored", defaultValue: "Your export purchase has been restored.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    var exportNoticeNotOwned: String {
        localization.string(localized: "vocello.export.not_owned", defaultValue: "No export purchase was found for this Apple Account.",
               comment: "iOS non-consumable export purchase; generation and internal playback remain free.")
    }

    func exportBuy(_ price: String) -> String {
        localization.format(localization.string(localized: "vocello.export.buy",
            defaultValue: "Unlock exports — %@", comment: "One-time purchase; substitution is the App Store localized price."), price)
    }

    func exportPurchaseNotice(_ notice: IOSExportPurchaseState.Notice,
                                     access: IOSExportPurchaseState.Access) -> String {
        switch notice {
        case .pending: exportNoticePending
        case .cancelled: exportNoticeCancelled
        case .failed: exportNoticeFailed
        case .unavailable: access == .unlocked ? exportOwnedProductUnavailable : exportProductUnavailable
        case .unverified: exportNoticeUnverified
        case .restored: exportNoticeRestored
        case .notOwned: exportNoticeNotOwned
        }
    }
}

// Default-locale callers retain their existing interface.
extension VocelloPresentationText {
    static var exportRootSummary: String { Self().exportRootSummary }
    static var exportBenefit: String { Self().exportBenefit }
    static var exportFreeDetail: String { Self().exportFreeDetail }
    static var exportOneTime: String { Self().exportOneTime }
    static var exportThanks: String { Self().exportThanks }
    static var exportPrivacy: String { Self().exportPrivacy }
    static var exportSupport: String { Self().exportSupport }
    static var exportUnlockTitle: String { Self().exportUnlockTitle }
    static var exportUnlockDetail: String { Self().exportUnlockDetail }
    static var exportUnlocked: String { Self().exportUnlocked }
    static var exportRetryAfterPurchase: String { Self().exportRetryAfterPurchase }
    static var exportProductUnavailable: String { Self().exportProductUnavailable }
    static var exportReloadProduct: String { Self().exportReloadProduct }
    static var exportOwnedProductUnavailable: String { Self().exportOwnedProductUnavailable }
    static var exportChecking: String { Self().exportChecking }
    static var exportRestore: String { Self().exportRestore }
    static var exportClose: String { Self().exportClose }
    static var exportViewOptions: String { Self().exportViewOptions }
    static var exportOptionsHint: String { Self().exportOptionsHint }
    static var exportFolderDetail: String { Self().exportFolderDetail }
    static var exportNoticePending: String { Self().exportNoticePending }
    static var exportNoticeCancelled: String { Self().exportNoticeCancelled }
    static var exportNoticeFailed: String { Self().exportNoticeFailed }
    static var exportNoticeUnverified: String { Self().exportNoticeUnverified }
    static var exportNoticeRestored: String { Self().exportNoticeRestored }
    static var exportNoticeNotOwned: String { Self().exportNoticeNotOwned }
    static func exportBuy(_ price: String) -> String { Self().exportBuy(price) }
    static func exportPurchaseNotice(_ notice: IOSExportPurchaseState.Notice,
                                     access: IOSExportPurchaseState.Access) -> String { Self().exportPurchaseNotice(notice, access: access) }
}
