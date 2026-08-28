import SwiftUI

private struct IOSCompactSetupRow<Content: View>: View {
    let title: String
    let content: Content

    init(
        title: String,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Text(title)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(Theme.Text.secondary)
                .frame(minWidth: 54, alignment: .leading)

            Spacer(minLength: 8)

            content
                .frame(maxWidth: .infinity, alignment: .trailing)
        }
    }
}

private struct IOSInlineSetupField<Content: View>: View {
    @ScaledMetric(relativeTo: .body) private var titleWidth = 96
    let title: String
    let content: Content

    init(
        title: String,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        HStack(alignment: .center, spacing: 4) {
            Text(title)
                .font(.footnote.weight(.medium))
                .foregroundStyle(Theme.Text.secondary)
                .lineLimit(1)
                .frame(width: titleWidth, alignment: .leading)

            content
                .frame(maxWidth: .infinity, alignment: .trailing)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct IOSInlineSetupGroup<Content: View>: View {
    @ScaledMetric(relativeTo: .body) private var rowSpacing = 12

    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: rowSpacing) {
            content
        }
        .padding(.vertical, 2)
    }
}

struct IOSCustomVoiceSetupCard: View {
    @Binding var selectedSpeaker: String
    @Binding var delivery: DeliveryInputState
    let setupMessage: String?
    let badgeText: String?
    let badgeTone: IOSStatusBadge.Tone?
    let modelInstallMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            IOSInlineSetupGroup {
                speakerField
                deliveryField
            }

            if let message = modelInstallMessage ?? setupMessage {
                IOSCompactInlineNotice(
                    message: message,
                    symbolName: "externaldrive.badge.exclamationmark",
                    tint: Theme.Brand.modeCustom
                )
            }
        }
    }

    private var speakerField: some View {
        IOSInlineSetupField(title: "Voice") {
            Picker("Speaker", selection: $selectedSpeaker) {
                ForEach(TTSModel.allSpeakers, id: \.self) { speaker in
                    Text(TTSModel.speakerPickerLabel(for: speaker)).tag(speaker)
                }
            }
            .pickerStyle(.menu)
            .tint(Theme.Brand.modeCustom)
            .iosSelectionFieldChrome(tint: Theme.Brand.modeCustom)
            // No fixed width — let the picker fill the IOSInlineSetupField
            // content cell so long speaker labels like "Aiden - English
            // native" render on one line. The 146pt cap was clipping them
            // mid-word.
            .frame(maxWidth: .infinity, alignment: .trailing)
            .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var deliveryField: some View {
        IOSInlineSetupField(title: "Delivery") {
            IOSDeliveryPicker(
                delivery: $delivery,
                tint: Theme.Brand.modeCustom,
                customAccessibilityIdentifier: "customVoice_customDeliveryField"
            )
        }
    }
}

struct IOSVoiceDesignSetupCard: View {
    @FocusState private var isBriefFocused: Bool
    @Binding var voiceDescription: String
    @Binding var delivery: DeliveryInputState
    let setupMessage: String?
    let badgeText: String?
    let badgeTone: IOSStatusBadge.Tone?
    let modelInstallMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            IOSInlineSetupGroup {
                briefField
                deliveryField
            }

            if let message = modelInstallMessage ?? setupMessage {
                IOSCompactInlineNotice(
                    message: message,
                    symbolName: "externaldrive.badge.exclamationmark",
                    tint: Theme.Brand.modeDesign
                )
            }
        }
    }

    private var briefField: some View {
        IOSInlineSetupField(title: "Description") {
            ZStack(alignment: .trailing) {
                TextField("Describe the voice you want", text: $voiceDescription)
                    .focused($isBriefFocused)
                    .padding(.trailing, voiceDescription.isEmpty ? 0 : 34)
                    .iosFieldChrome(isFocused: isBriefFocused, tint: Theme.Brand.modeDesign)
                    .accessibilityIdentifier("voiceDesign_voiceDescriptionField")

                if !voiceDescription.isEmpty {
                    Button(action: clearVoiceDescription) {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                    .padding(.trailing, 12)
                }
            }
        }
    }

    private var deliveryField: some View {
        IOSInlineSetupField(title: "Delivery") {
            IOSDeliveryPicker(
                delivery: $delivery,
                tint: Theme.Brand.modeDesign,
                customAccessibilityIdentifier: "voiceDesign_customDeliveryField"
            )
        }
    }

    private func clearVoiceDescription() {
        voiceDescription = ""
    }
}
