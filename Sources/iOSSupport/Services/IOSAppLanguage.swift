import Foundation
import Observation

/// UI-only identifiers. Deliberately unrelated to Qwen3SupportedLanguage and generation requests.
enum IOSUILanguage: String, CaseIterable, Sendable {
    case english = "en", french = "fr", spanish = "es", german = "de", italian = "it"
    case portuguese = "pt-BR", chinese = "zh-Hans", japanese = "ja", korean = "ko", russian = "ru"

    var nativeName: String {
        switch self {
        case .english: "English"
        case .french: "Français"
        case .spanish: "Español"
        case .german: "Deutsch"
        case .italian: "Italiano"
        case .portuguese: "Português (Brasil)"
        case .chinese: "简体中文"
        case .japanese: "日本語"
        case .korean: "한국어"
        case .russian: "Русский"
        }
    }
}

/// One app-lifetime owner. Changing copy never changes root identity or runtime ownership.
@MainActor @Observable
final class IOSAppLanguage {
    static let shared = IOSAppLanguage()
    static let preferenceKey = "vocello.ios.interfaceLanguage"
    static let system = "system"

    private let defaults: UserDefaults
    private let bundle: Bundle
    private let preferredLanguages: () -> [String]
    let availableLanguages: [IOSUILanguage]
    private(set) var selection: String
    private(set) var resolvedLanguage: String
    private(set) var localization: VocelloLocalization

    init(defaults: UserDefaults = .standard, bundle: Bundle = .main,
         preferredLanguages: @escaping () -> [String] = { Locale.preferredLanguages }) {
        self.defaults = defaults
        self.bundle = bundle
        self.preferredLanguages = preferredLanguages
        let available = IOSUILanguage.allCases.filter { bundle.localizations.contains($0.rawValue) }
        availableLanguages = available
        let stored = defaults.string(forKey: Self.preferenceKey) ?? Self.system
        let initial = available.contains(where: { $0.rawValue == stored }) ? stored : Self.system
        selection = initial
        let resolved = Self.resolve(selection: initial, available: available, preferred: preferredLanguages())
        resolvedLanguage = resolved
        localization = VocelloLocalization(bundle: bundle, language: resolved)
    }

    func select(_ identifier: String) {
        let next = availableLanguages.contains(where: { $0.rawValue == identifier }) ? identifier : Self.system
        guard next != selection else { return }
        selection = next
        if next == Self.system { defaults.removeObject(forKey: Self.preferenceKey) }
        else { defaults.set(next, forKey: Self.preferenceKey) }
        refreshSystemLanguage()
    }

    func refreshSystemLanguage() {
        let resolved = Self.resolve(selection: selection, available: availableLanguages, preferred: preferredLanguages())
        guard resolved != resolvedLanguage else { return }
        resolvedLanguage = resolved
        localization = VocelloLocalization(bundle: bundle, language: resolved)
    }

    var interfaceLocale: Locale {
        var components = Locale.Components(locale: .current)
        let selected = Locale.Language.Components(identifier: resolvedLanguage)
        // Region belongs to formatting preferences, not the interface-language choice.
        components.languageComponents.languageCode = selected.languageCode
        components.languageComponents.script = selected.script
        return Locale(components: components)
    }
    var presentation: VocelloPresentationText { VocelloPresentationText(localization: localization) }

    func localized(localized key: String, defaultValue: String? = nil, comment: StaticString? = nil) -> String {
        localization.string(localized: key, defaultValue: defaultValue, comment: comment)
    }

    static func resolve(selection: String, available: [IOSUILanguage], preferred: [String]) -> String {
        let identifiers = available.map(\.rawValue)
        if identifiers.contains(selection) { return selection }
        return Bundle.preferredLocalizations(from: identifiers, forPreferences: preferred).first ?? "en"
    }
}
