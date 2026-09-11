import Foundation

/// Immutable presentation context. Never used to resolve a generation language or price.
struct VocelloLocalization: Sendable {
    let bundle: Bundle
    let language: String?
    /// Locale used for plural rules and number substitution in formatted copy: the
    /// interface language over the user's regional formatting preferences. Never the
    /// bare process locale, which would apply English plural rules to French copy on an
    /// English-region device (or on CI).
    let locale: Locale
    private let lookupBundle: Bundle

    init(bundle: Bundle = .main, language: String? = nil) {
        self.bundle = bundle
        self.language = language
        if let language {
            let selected = bundle.path(forResource: language, ofType: "lproj").flatMap(Bundle.init(path:))
            let english = bundle.path(forResource: "en", ofType: "lproj").flatMap(Bundle.init(path:))
            lookupBundle = selected ?? english ?? bundle
        } else {
            lookupBundle = bundle
        }
        locale = Self.interfaceLocale(for: language)
    }

    /// The interface language layered over the current regional formatting preferences.
    static func interfaceLocale(for language: String?) -> Locale {
        guard let language else { return .current }
        var components = Locale.Components(locale: .current)
        let selected = Locale.Language.Components(identifier: language)
        // Region belongs to formatting preferences, not the interface-language choice.
        components.languageComponents.languageCode = selected.languageCode
        components.languageComponents.script = selected.script
        return Locale(components: components)
    }

    /// `String(format:locale:arguments:)` bound to this context's locale. Every formatted
    /// presentation string goes through here so plural categories match the copy's language.
    func format(_ format: String, _ arguments: CVarArg...) -> String {
        self.format(format, arguments: arguments)
    }

    func format(_ format: String, arguments: [CVarArg]) -> String {
        String(format: format, locale: locale, arguments: arguments)
    }

    func string(localized key: String, defaultValue: String? = nil, comment: StaticString? = nil) -> String {
        // Selecting a locale on Text does not change Foundation's bundle lookup.
        // Resolve the compiled localization once per context, not once per rendered label.
        return lookupBundle.localizedString(forKey: key, value: defaultValue, table: nil)
    }
}
