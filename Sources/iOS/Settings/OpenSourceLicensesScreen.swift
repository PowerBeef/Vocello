import SwiftUI

private struct IOSAttributionManifest: Decodable {
    struct License: Decodable, Identifiable {
        let id: String
        let text: String
    }

    struct Component: Decodable, Identifiable {
        let id: String
        let displayName: String
        let version: String
        let revision: String?
        let sourceURL: String
        let licenseID: String
        let copyrightNotice: String?
        let notice: String?
        let origins: String?
        let licenseTextOverride: String?
    }

    struct ModelArtifact: Decodable, Identifiable {
        let id: String
        let displayName: String
        let variantID: String
        let repo: String
        let revision: String
        let modelCardSHA256: String
        let licenseID: String
        let baseRepo: String
        let baseRevision: String
        let sourceURL: String
    }

    let licenses: [License]
    let components: [Component]
    let modelArtifacts: [ModelArtifact]

    static func load() throws -> Self {
        guard let url = Bundle.main.url(forResource: "third_party_attributions", withExtension: "json") else {
            throw CocoaError(.fileNoSuchFile)
        }
        return try JSONDecoder().decode(Self.self, from: Data(contentsOf: url))
    }
}

/// Offline software and model attribution browser generated from exact repository resolutions.
struct OpenSourceLicensesScreen: View {
    @Environment(\.iosDockHeight) private var dockHeight
    @Environment(\.dismiss) private var dismiss

    private let manifest: IOSAttributionManifest?
    private let loadError: String?

    init() {
        do {
            manifest = try IOSAttributionManifest.load()
            loadError = nil
        } catch {
            manifest = nil
            loadError = IOSAppLanguage.shared.localized(localized: "vocello.licenses.unavailable")
        }
    }

    var body: some View {
        IOSScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                compactHeader

                Text(IOSAppLanguage.shared.localized(localized: "vocello.licenses.introduction"))
                    .font(.caption)
                    .foregroundStyle(Theme.Text.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 4)

                if let manifest {
                    IOSSettingsSection(title: IOSAppLanguage.shared.localized(localized: "vocello.licenses.software")) {
                        ForEach(Array(manifest.components.enumerated()), id: \.element.id) { index, component in
                            NavigationLink {
                                IOSAttributionDetailScreen(
                                    title: component.displayName,
                                    subtitle: component.version,
                                    sourceURL: component.sourceURL,
                                    licenseID: component.licenseID,
                                    copyrightNotice: component.copyrightNotice,
                                    notice: component.notice,
                                    origins: component.origins,
                                    licenseText: component.licenseTextOverride
                                        ?? manifest.licenses.first(where: { $0.id == component.licenseID })?.text
                                        ?? ""
                                )
                            } label: {
                                IOSSettingsNavigationRow(
                                    symbol: "shippingbox",
                                    title: component.displayName,
                                    subtitle: component.version,
                                    value: component.licenseID
                                )
                            }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("iosAttributionRow_\(component.id)")
                            .accessibilityLabel(component.displayName)
                            .accessibilityValue("\(component.version), \(component.licenseID)")
                            .accessibilityHint(IOSAppLanguage.shared.localized(localized: "vocello.licenses.detail_hint"))

                            if index < manifest.components.count - 1 {
                                IOSSettingsDivider()
                            }
                        }
                    }

                    IOSSettingsSection(title: IOSAppLanguage.shared.localized(localized: "vocello.licenses.models")) {
                        ForEach(Array(manifest.modelArtifacts.enumerated()), id: \.element.id) { index, model in
                            NavigationLink {
                                IOSAttributionDetailScreen(
                                    title: model.displayName,
                                    subtitle: "\(model.variantID) · \(model.revision.prefix(12))",
                                    sourceURL: model.sourceURL,
                                    licenseID: model.licenseID,
                                    copyrightNotice: nil,
                                    notice: "Model card SHA-256: \(model.modelCardSHA256)\n\nBase: \(model.baseRepo) @ \(model.baseRevision)",
                                    origins: nil,
                                    licenseText: manifest.licenses.first(where: { $0.id == model.licenseID })?.text ?? ""
                                )
                            } label: {
                                IOSSettingsNavigationRow(
                                    symbol: "waveform",
                                    title: model.displayName,
                                    subtitle: model.variantID.capitalized,
                                    value: model.licenseID
                                )
                            }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("iosModelAttributionRow_\(model.id)")
                            .accessibilityLabel(model.displayName)
                            .accessibilityValue("\(model.variantID), \(model.licenseID)")
                            .accessibilityHint(IOSAppLanguage.shared.localized(localized: "vocello.licenses.detail_hint"))

                            if index < manifest.modelArtifacts.count - 1 {
                                IOSSettingsDivider()
                            }
                        }
                    }
                } else if let loadError {
                    Text(loadError)
                        .font(.body)
                        .foregroundStyle(Theme.Status.critical)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(12)
                        .accessibilityIdentifier("iosAttributionLoadError")
                }
            }
            .padding(.horizontal, Theme.Spacing.lg)
            .padding(.top, Theme.Spacing.sm)
            .padding(.bottom, max(IOSStudioShellMetrics.dockFadeHeight, dockHeight) + Theme.Spacing.lg)
        }
        .background(Theme.Surface.canvas.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
    }

    private var compactHeader: some View {
        HStack(spacing: 8) {
            Button { dismiss() } label: {
                Image(systemName: "chevron.left")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(Theme.Text.primary)
                    .frame(width: 44, height: 44)
                    .background(Theme.Surface.panelMuted, in: Circle())
                    .overlay { Circle().stroke(Theme.Surface.panelStroke, lineWidth: 0.5) }
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(IOSSettingsText.backAbout)
            .accessibilityIdentifier("iosSettings_openSourceBackButton")

            Text(IOSAppLanguage.shared.localized(localized: "vocello.settings.open_source_licenses"))
                .font(.headline)
                .foregroundStyle(Theme.Text.primary)
                .accessibilityAddTraits(.isHeader)
                .accessibilityIdentifier("screen_openSourceLicenses")

            Spacer(minLength: 0)
        }
        .frame(minHeight: 44)
    }
}

private struct IOSAttributionDetailScreen: View {
    @Environment(\.iosDockHeight) private var dockHeight
    @Environment(\.dismiss) private var dismiss

    let title: String
    let subtitle: String
    let sourceURL: String
    let licenseID: String
    let copyrightNotice: String?
    let notice: String?
    let origins: String?
    let licenseText: String

    var body: some View {
        IOSScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                header

                Text(subtitle)
                    .font(.caption.monospaced())
                    .foregroundStyle(Theme.Text.secondary)

                if let url = URL(string: sourceURL) {
                    Link(destination: url) {
                        Label(IOSAppLanguage.shared.localized(localized: "vocello.licenses.view_source"), systemImage: "arrow.up.right.square")
                            .font(.subheadline.weight(.semibold))
                            .frame(minHeight: 44)
                    }
                    .accessibilityIdentifier("iosAttributionSourceLink")
                }

                if let copyrightNotice, !copyrightNotice.isEmpty {
                    detailSection(title: IOSAppLanguage.shared.localized(localized: "vocello.licenses.copyright"), body: copyrightNotice)
                }
                if let notice, !notice.isEmpty {
                    detailSection(title: IOSAppLanguage.shared.localized(localized: "vocello.licenses.notices"), body: notice)
                }
                if let origins, !origins.isEmpty {
                    detailSection(title: IOSAppLanguage.shared.localized(localized: "vocello.licenses.origins"), body: origins)
                }
                detailSection(title: "\(licenseID) \(IOSAppLanguage.shared.localized(localized: "vocello.licenses.license"))", body: licenseText)
            }
            .padding(.horizontal, Theme.Spacing.lg)
            .padding(.top, Theme.Spacing.sm)
            .padding(.bottom, max(IOSStudioShellMetrics.dockFadeHeight, dockHeight) + Theme.Spacing.lg)
        }
        .background(Theme.Surface.canvas.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
    }

    private var header: some View {
        HStack(spacing: 8) {
            Button { dismiss() } label: {
                Image(systemName: "chevron.left")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(Theme.Text.primary)
                    .frame(width: 44, height: 44)
                    .background(Theme.Surface.panelMuted, in: Circle())
                    .overlay { Circle().stroke(Theme.Surface.panelStroke, lineWidth: 0.5) }
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(IOSAppLanguage.shared.localized(localized: "vocello.licenses.back"))
            .accessibilityIdentifier("iosAttributionDetailBackButton")

            Text(title)
                .font(.headline)
                .foregroundStyle(Theme.Text.primary)
                .lineLimit(2)
                .accessibilityAddTraits(.isHeader)

            Spacer(minLength: 0)
        }
        .frame(minHeight: 44)
    }

    private func detailSection(title: String, body: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.headline)
                .foregroundStyle(Theme.Text.primary)
                .accessibilityAddTraits(.isHeader)
            Text(body)
                .font(.footnote.monospaced())
                .foregroundStyle(Theme.Text.secondary)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color.white.opacity(0.04))
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
    }
}
