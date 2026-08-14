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

struct IOSVoiceCloningReferenceCard: View {
    let savedVoices: [Voice]
    let selectedSavedVoiceID: String?
    let referenceAudioPath: String?
    let transcriptLoadError: String?
    let setupMessage: String?
    let badgeText: String?
    let badgeTone: IOSStatusBadge.Tone?
    let onSelectSavedVoice: (String?) -> Void
    let onImportReference: () -> Void
    let onClearReference: () -> Void

    @Binding var referenceTranscript: String
    @Binding var isTranscriptExpanded: Bool

    private var referenceFilename: String? {
        referenceAudioPath.map { URL(fileURLWithPath: $0).lastPathComponent }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            IOSInlineSetupGroup {
                if !savedVoices.isEmpty || referenceAudioPath != nil {
                    ViewThatFits(in: .horizontal) {
                        HStack(alignment: .top, spacing: 12) {
                            referenceField
                            referenceActions
                        }
                        VStack(alignment: .leading, spacing: 10) {
                            referenceField
                            referenceActions
                        }
                    }
                } else {
                    referenceActions
                }

                if let referenceFilename {
                    IOSCompactSetupRow(title: "Recording") {
                        Text(referenceFilename)
                            .font(.caption)
                            .foregroundStyle(Theme.Text.secondary)
                            .lineLimit(1)
                    }
                }

                IOSInlineSetupField(title: "Transcript") {
                    Button(action: toggleTranscriptExpansion) {
                        HStack(spacing: 10) {
                            Image(systemName: isTranscriptExpanded ? "chevron.down.circle.fill" : "chevron.right.circle.fill")
                                .foregroundStyle(Theme.Brand.modeClone)

                            Text(isTranscriptExpanded ? "Hide transcript" : "Show transcript")
                                .font(.footnote.weight(.semibold))
                                .foregroundStyle(Theme.Text.primary)

                            Spacer(minLength: 0)
                        }
                    }
                    .buttonStyle(.plain)
                }

                if isTranscriptExpanded {
                    IOSMultilineTextView(
                        text: $referenceTranscript,
                        placeholder: "Add the transcript for this recording (optional)",
                        tint: Theme.Brand.modeClone,
                        isScrollEnabled: false
                    )
                    .frame(height: 72)
                    .transition(.opacity)
                }
            }

            if let transcriptLoadError {
                IOSCompactInlineNotice(
                    message: transcriptLoadError,
                    symbolName: "exclamationmark.triangle.fill",
                    tint: .orange
                )
            }

            if let message = setupMessage {
                IOSCompactInlineNotice(
                    message: message,
                    symbolName: "waveform.badge.exclamationmark",
                    tint: Theme.Brand.modeClone
                )
            }
        }
    }

    private var referenceField: some View {
        IOSInlineSetupField(title: "Source") {
            Picker("Reference source", selection: selectedVoiceBinding) {
                Text("Imported recording").tag(Optional<String>.none)
                ForEach(savedVoices) { voice in
                    Text(voice.hasTranscript ? "\(voice.name) · transcript" : "\(voice.name) · audio only")
                        .tag(Optional(voice.id))
                }
            }
            .pickerStyle(.menu)
            .tint(Theme.Brand.modeClone)
            .iosFieldChrome(tint: Theme.Brand.modeClone)
        }
    }

    private var referenceActions: some View {
        HStack(spacing: 10) {
            Button(referenceAudioPath == nil ? "Add Audio" : "Replace Audio", action: onImportReference)
                .iosAdaptiveUtilityButtonStyle(
                    compactTextProminent: true,
                    tint: Theme.Brand.modeClone
                )

            if referenceAudioPath != nil {
                Button("Remove", action: onClearReference)
                    .iosAdaptiveUtilityButtonStyle(tint: Theme.Brand.modeClone)
            }
        }
    }

    private var selectedVoiceBinding: Binding<String?> {
        Binding(
            get: { selectedSavedVoiceID },
            set: { onSelectSavedVoice($0) }
        )
    }

    private func toggleTranscriptExpansion() {
        IOSAccessibleAnimation.perform(Theme.Motion.disclosure) {
            isTranscriptExpanded.toggle()
        }
    }
}
