import Foundation

/// Immutable presentation context. Never used to resolve a generation language or price.
struct VocelloLocalization: Sendable {
    let bundle: Bundle
    let language: String?
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
    }

    func string(localized key: String, defaultValue: String? = nil, comment: StaticString? = nil) -> String {
        // Selecting a locale on Text does not change Foundation's bundle lookup.
        // Resolve the compiled localization once per context, not once per rendered label.
        return lookupBundle.localizedString(forKey: key, value: defaultValue, table: nil)
    }
}
