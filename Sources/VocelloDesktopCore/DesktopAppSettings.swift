import CoreFoundation
import Foundation
import QwenVoiceCore

/// The Mac app's settings as the CLI reads them: the `com.qwenvoice.app`
/// preferences domain (`com.qwenvoice.app.debug` in a debug session), read
/// through CFPreferences because `UserDefaults.standard` in the CLI is the
/// CLI's own domain. `set` writes what the app's Settings write (RF-28); the
/// app reads each value when it needs it, and preferences stay coherent across
/// processes. Consent and the interface language are reported but never
/// settable from the CLI.
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

    /// Why a setting was not set.
    public enum SetError: Error, Equatable, Sendable {
        case unknownSetting(String)
        case notSettable(String)
        case invalidValue(name: String, value: String, accepted: String)
        case writeFailed(String)
    }

    public let domain: String
    private let read: @Sendable (String) -> Any?
    /// Stores a value (nil removes the key) and makes it visible to other processes.
    private let write: @Sendable (String, Any?) -> Bool
    /// The release domain, where the app keeps the interface language even in
    /// a debug session (`IOSAppLanguage` writes `UserDefaults.standard`).
    private let readRelease: @Sendable (String) -> Any?

    public init(debug: Bool = RuntimeDebugGate.isEnabled()) {
        let domain = debug ? Self.debugDomain : Self.releaseDomain
        let release = Self.releaseDomain
        self.init(
            domain: domain,
            read: { CFPreferencesCopyAppValue($0 as CFString, domain as CFString) as Any? },
            readRelease: { CFPreferencesCopyAppValue($0 as CFString, release as CFString) as Any? },
            write: { key, value in
                let stored: CFPropertyList? = value.map { $0 as AnyObject }
                CFPreferencesSetAppValue(key as CFString, stored, domain as CFString)
                return CFPreferencesAppSynchronize(domain as CFString)
            }
        )
    }

    /// A store over any key-value source (tests); `readRelease` defaults to `read`,
    /// and without `write` nothing is settable.
    public init(
        domain: String, read: @escaping @Sendable (String) -> Any?,
        readRelease: (@Sendable (String) -> Any?)? = nil,
        write: (@Sendable (String, Any?) -> Bool)? = nil
    ) {
        self.domain = domain
        self.read = read
        self.readRelease = readRelease ?? read
        self.write = write ?? { _, _ in false }
    }

    /// Sets the setting `name` from its CLI spelling, as the app's Settings store
    /// it, and returns its new entry. `output-folder` takes an existing folder or
    /// `default`; `variant.<mode>` takes `speed`, `quality` or `automatic`.
    public func set(_ name: String, to raw: String) throws -> Entry {
        let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        let stored: Any?
        switch name {
        case "autoplay", "prefer-lower-memory":
            guard let flag = Self.flag(value) else {
                throw SetError.invalidValue(name: name, value: raw, accepted: "true | false")
            }
            stored = flag
        case "output-folder":
            if value.lowercased() == "default" {
                stored = nil
            } else {
                let folder = URL(fileURLWithPath: (value as NSString).expandingTildeInPath).standardizedFileURL
                var isDirectory: ObjCBool = false
                guard !value.isEmpty, unsafe FileManager.default.fileExists(atPath: folder.path, isDirectory: &isDirectory),
                      isDirectory.boolValue else {
                    throw SetError.invalidValue(name: name, value: raw, accepted: "an existing folder | default")
                }
                stored = folder.path
            }
        case "variation":
            guard let variation = Qwen3SamplingVariation(rawValue: value.lowercased()) else {
                throw SetError.invalidValue(name: name, value: raw, accepted: "expressive | balanced | consistent")
            }
            stored = variation.rawValue
        case "variant.custom", "variant.design", "variant.clone":
            switch value.lowercased() {
            case "automatic", "auto": stored = nil
            case "speed", "fast": stored = ModelVariantKind.speed.rawValue
            case "quality", "hq": stored = ModelVariantKind.quality.rawValue
            default: throw SetError.invalidValue(name: name, value: raw, accepted: "speed | quality | automatic")
            }
        case "interface-language":
            throw SetError.notSettable(name)
        default:
            throw SetError.unknownSetting(name)
        }
        guard write(Self.key(for: name), stored) else { throw SetError.writeFailed(name) }
        guard let entry = entry(name) else { throw SetError.unknownSetting(name) }
        return entry
    }

    private static func key(for name: String) -> String {
        switch name {
        case "autoplay": MacAppSettingsKeys.autoPlay
        case "output-folder": MacAppSettingsKeys.outputDirectory
        case "variation": MacAppSettingsKeys.generationVariation
        case "prefer-lower-memory": MacAppSettingsKeys.preferSpeedEverywhere
        default: MacAppSettingsKeys.variantPreference(for: GenerationMode(rawValue: String(name.dropFirst("variant.".count))) ?? .custom)
        }
    }

    private static func flag(_ value: String) -> Bool? {
        switch value.lowercased() {
        case "true", "on", "yes", "1": true
        case "false", "off", "no", "0": false
        default: nil
        }
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
            let stored = explicitVariantID(for: mode).flatMap { ModelVariantKind(rawValue: $0)?.rawValue }
            return Entry(name: name, value: stored ?? "automatic", isDefault: stored == nil, settable: true)
        case "interface-language":
            let stored = readRelease(Self.interfaceLanguageKey) as? String
            return Entry(name: name, value: stored ?? "system", isDefault: stored == nil, settable: false)
        default:
            return nil
        }
    }

    /// The app's explicit per-mode variant choice, nil when automatic. As in the
    /// app (`MacModelVariantPreferences`), any non-empty stored id counts; the
    /// resolution skips one the mode does not have.
    public func explicitVariantID(for mode: GenerationMode) -> String? {
        guard let stored = (read(MacAppSettingsKeys.variantPreference(for: mode)) as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines), !stored.isEmpty else { return nil }
        return stored
    }

    /// The app's "Prefer lower-memory models" setting.
    public var prefersLowerMemory: Bool { boolValue(read(MacAppSettingsKeys.preferSpeedEverywhere)) ?? false }

    /// The app's sampling variation.
    public var variation: Qwen3SamplingVariation {
        (read(MacAppSettingsKeys.generationVariation) as? String).flatMap(Qwen3SamplingVariation.init(rawValue:)) ?? .expressive
    }

    private func bool(_ name: String, key: String, default fallback: Bool) -> Entry {
        let stored = boolValue(read(key))
        return Entry(name: name, value: String(stored ?? fallback), isDefault: stored == nil, settable: true)
    }

    /// A stored Boolean as `UserDefaults.bool(forKey:)` reads it: a Boolean, a number or a string.
    private func boolValue(_ value: Any?) -> Bool? {
        switch value {
        case let bool as Bool: return bool
        case let number as NSNumber: return number.boolValue
        case let string as String: return (string as NSString).boolValue
        default: return nil
        }
    }
}
