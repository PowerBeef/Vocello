import QwenVoiceCore
import SwiftUI

/// RF-59: the model update that follows an app update from an earlier Vocello, above every tab
/// while it runs, then a note of the space the earlier models freed, dismissed with a tap. The rows
/// in Settings > Voice Models carry each model's own progress and its Cancel.
struct IOSModelUpdateBanner: View {
    @Environment(IOSModelInstallerViewModel.self) private var modelInstaller

    var body: some View {
        if let freedBytes = modelInstaller.modelUpdateCompletion {
            Button {
                modelInstaller.dismissModelUpdateCompletion()
            } label: {
                IOSInfoBanner(
                    title: IOSSettingsText.modelUpdateDoneTitle,
                    message: freedBytes > 0
                        ? IOSSettingsText.modelUpdateDoneMessage(IOSSettingsFormatters.fileSize(freedBytes))
                        : IOSSettingsText.modelUpdatePromptReason,
                    symbolName: "checkmark.circle.fill",
                    tint: Theme.Status.healthy
                )
            }
            .buttonStyle(.plain)
            .accessibilityHint(IOSInterfaceText.engineToastDismissHint)
            .accessibilityIdentifier("iosModelUpdateBanner_done")
            .modifier(BannerPlacement())
        } else if let progress = modelInstaller.modelUpdateProgress {
            IOSInfoBanner(
                title: IOSSettingsText.modelUpdateBannerTitle,
                message: IOSSettingsText.modelUpdateBannerProgress(String(progress.completed), String(progress.total)),
                symbolName: "arrow.triangle.2.circlepath.circle.fill"
            )
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("iosModelUpdateBanner")
            .modifier(BannerPlacement())
        }
    }
}

private struct BannerPlacement: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(.horizontal, Theme.Spacing.lg)
            .padding(.top, Theme.Spacing.xs)
    }
}
