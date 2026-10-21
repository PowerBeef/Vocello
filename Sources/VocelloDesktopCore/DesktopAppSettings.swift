import CoreFoundation
import Foundation
import QwenVoiceCore

/// The Mac app's settings as the CLI reads them: the `com.qwenvoice.app`
/// preferences domain (`com.qwenvoice.app.debug` in a debug session), read
/// through CFPreferences because `UserDefaults.standard` in the CLI is the
/// CLI's own domain. Read-only here; consent and the interface language are
/// reported but never settable from the CLI.
public struct DesktopAppSettings: Sendable {
    /// One setting: its CLI name, the app's preference key and its value.
    public struct Entry: Encodable, Sendable, Equatable {
        public let name: String
        public let value: String
        /// The value is the app's default because the app never stored one.
        public let isDefault: Bool
        public let settable: Bool
    }

    public static let releaseDomain = "com.qwenvoice.app"
    /// `IOSAppLanguage.preferenceKey`, which both apps write (iPhone-compiled, so not shared by path here).
    public static let interfaceLanguageKey = "vocello.ios.interfaceLanguage"
    public static let debugDomain = "com.qwenvoice.app.debug"

    public let domain: String
    private let read: @Sendable (String) -> Any?

    public init(debug: Bool = RuntimeDebugGate.isEnabled()) {
        let domain = debug ? Self.debugDomain : Self.releaseDomain
        self.init(domain: domain) { key in
            CFPreferencesCopyAppValue(key as CFString, domain as CFString) as Any?
        }
    }

    /// A reader over any key-value source (tests).
    public init(domain: String, read: @escaping @Sendable (String) -> Any?) {
        self.domain = domain
        self.read = read
    }

    /// The CLI names, in display order.
    public static let names = [
        "autoplay", "output-folder", "variation", "prefer-lower-memory",
        "variant.custom", "variant.design", "variant.clone", "interface-language",
    ]

    public func all() -> [Entry] { Self.names.compactMap(entry) }

    public func entry(_ name: String) -> Entry? {
        switch name {
        case "autoplay":
            return bool(name, key: MacAppSettingsKeys.autoPlay, default: true)
        case "output-folder":
            let stored = (read(MacAppSettingsKeys.outputDirectory) as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            let isDefault = stored?.isEmpty ?? true
            return Entry(name: name, value: isDefault ? "default" : stored!, isDefault: isDefault, settable: true)
        case "variation":
            let stored = (read(MacAppSettingsKeys.generationVariation) as? String).flatMap { Qwen3SamplingVariation(rawValue: $0)?.rawValue }
            return Entry(name: name, value: stored ?? Qwen3SamplingVariation.expressive.rawValue, isDefault: stored == nil, settable: true)
        case "prefer-lower-memory":
            return bool(name, key: MacAppSettingsKeys.preferSpeedEverywhere, default: false)
        case "variant.custom", "variant.design", "variant.clone":
            let mode = GenerationMode(rawValue: String(name.dropFirst("variant.".count))) ?? .custom
            let stored = explicitVariantID(for: mode)
            return Entry(name: name, value: stored ?? "automatic", isDefault: stored == nil, settable: true)
        case "interface-language":
            let stored = read(Self.interfaceLanguageKey) as? String
            return Entry(name: name, value: stored ?? "system", isDefault: stored == nil, settable: false)
        default:
            return nil
        }
    }

    /// The app's explicit per-mode variant choice (`speed`, `quality`), nil when automatic.
    public func explicitVariantID(for mode: GenerationMode) -> String? {
        (read(MacAppSettingsKeys.variantPreference(for: mode)) as? String).flatMap {
            ModelVariantKind(rawValue: $0) == nil ? nil : $0
        }
    }

    /// The app's "Prefer lower-memory models" setting.
    public var prefersLowerMemory: Bool { (read(MacAppSettingsKeys.preferSpeedEverywhere) as? Bool) ?? false }

    /// The app's sampling variation.
    public var variation: Qwen3SamplingVariation {
        (read(MacAppSettingsKeys.generationVariation) as? String).flatMap(Qwen3SamplingVariation.init(rawValue:)) ?? .expressive
    }

    private func bool(_ name: String, key: String, default fallback: Bool) -> Entry {
        let stored = read(key) as? Bool
        return Entry(name: name, value: String(stored ?? fallback), isDefault: stored == nil, settable: true)
    }
}
