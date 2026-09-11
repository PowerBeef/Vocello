import SwiftUI
import QwenVoiceCore

/// UI language is independent of model-facing language, prompts, and raw identities.
@MainActor enum IOSInterfaceText {
    static var seed: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.seed", defaultValue: "Seed",
               comment: "iOS interface guidance only; never substituted into model input.")
    }
    static var unpinSeed: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.unpinSeed", defaultValue: "Unpin — new seed each take",
               comment: "iOS interface guidance only; never substituted into model input.")
    }
    static var keepPinned: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.keepPinned", defaultValue: "Keep pinned",
               comment: "iOS interface guidance only; never substituted into model input.")
    }
    static var stopGenerating: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.stopGenerating", defaultValue: "Stop generating",
               comment: "iOS interface guidance only; never substituted into model input.")
    }
    static var unusualPacing: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.unusualPacing", defaultValue: "Unusual pacing detected",
               comment: "iOS interface guidance only; never substituted into model input.")
    }
    static var reviewTake: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.reviewTake", defaultValue: "Review this take or generate it again.",
               comment: "iOS interface guidance only; never substituted into model input.")
    }
    static var timingAdvisory: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.timingAdvisory", defaultValue: "Timing requests aren’t honored — the voice can’t target a duration, so this may distort pacing instead.",
               comment: "iOS interface guidance only; never substituted into model input.")
    }
    static var tonePlaceholderCalm: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.tonePlaceholderCalm", defaultValue: "e.g. A calm narrator, warm and measured",
               comment: "iOS interface guidance only; never substituted into model input.")
    }
    static var tonePlaceholderNews: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.tonePlaceholderNews", defaultValue: "e.g. An energetic news anchor, bright and fast",
               comment: "iOS interface guidance only; never substituted into model input.")
    }
    static var tonePlaceholderWhisper: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.tonePlaceholderWhisper", defaultValue: "e.g. Whispered, close-mic and breathy",
               comment: "iOS interface guidance only; never substituted into model input.")
    }
    static var tonePlaceholderGentle: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.tonePlaceholderGentle", defaultValue: "e.g. Gentle, serious, and reassuring",
               comment: "iOS interface guidance only; never substituted into model input.")
    }
    static var toneExampleCalm: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.toneExampleCalm", defaultValue: "A calm narrator, warm and measured.",
               comment: "iOS interface guidance only; never substituted into model input.")
    }
    static var toneExampleNews: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.toneExampleNews", defaultValue: "An energetic news anchor, bright and fast.",
               comment: "iOS interface guidance only; never substituted into model input.")
    }
    static var toneExampleWhisper: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.toneExampleWhisper", defaultValue: "A whispered, close-mic and breathy tone.",
               comment: "iOS interface guidance only; never substituted into model input.")
    }
    static var toneExampleGentle: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.toneExampleGentle", defaultValue: "Gentle, serious, and reassuring.",
               comment: "iOS interface guidance only; never substituted into model input.")
    }
    static var english: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.english", defaultValue: "English",
               comment: "iOS display-only english; preserve model IDs, prompt text and warning policy.")
    }
    static var chinese: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.chinese", defaultValue: "Chinese",
               comment: "iOS display-only chinese; preserve model IDs, prompt text and warning policy.")
    }
    static var french: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.french", defaultValue: "French",
               comment: "iOS display-only french; preserve model IDs, prompt text and warning policy.")
    }
    static var german: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.german", defaultValue: "German",
               comment: "iOS display-only german; preserve model IDs, prompt text and warning policy.")
    }
    static var spanish: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.spanish", defaultValue: "Spanish",
               comment: "iOS display-only spanish; preserve model IDs, prompt text and warning policy.")
    }
    static var italian: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.italian", defaultValue: "Italian",
               comment: "iOS display-only italian; preserve model IDs, prompt text and warning policy.")
    }
    static var portuguese: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.portuguese", defaultValue: "Portuguese",
               comment: "iOS display-only portuguese; preserve model IDs, prompt text and warning policy.")
    }
    static var russian: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.russian", defaultValue: "Russian",
               comment: "iOS display-only russian; preserve model IDs, prompt text and warning policy.")
    }
    static var japanese: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.japanese", defaultValue: "Japanese",
               comment: "iOS display-only japanese; preserve model IDs, prompt text and warning policy.")
    }
    static var korean: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.korean", defaultValue: "Korean",
               comment: "iOS display-only korean; preserve model IDs, prompt text and warning policy.")
    }
    static var auto: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.auto", defaultValue: "Auto",
               comment: "iOS display-only auto; preserve model IDs, prompt text and warning policy.")
    }
    static var british: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.british", defaultValue: "British",
               comment: "iOS display-only british; preserve model IDs, prompt text and warning policy.")
    }
    static var neutral: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.neutral", defaultValue: "Neutral",
               comment: "iOS display-only neutral; preserve model IDs, prompt text and warning policy.")
    }
    static var happy: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.happy", defaultValue: "Happy",
               comment: "iOS display-only happy; preserve model IDs, prompt text and warning policy.")
    }
    static var sad: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.sad", defaultValue: "Sad",
               comment: "iOS display-only sad; preserve model IDs, prompt text and warning policy.")
    }
    static var angry: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.angry", defaultValue: "Angry",
               comment: "iOS display-only angry; preserve model IDs, prompt text and warning policy.")
    }
    static var fearful: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.fearful", defaultValue: "Fearful",
               comment: "iOS display-only fearful; preserve model IDs, prompt text and warning policy.")
    }
    static var surprised: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.surprised", defaultValue: "Surprised",
               comment: "iOS display-only surprised; preserve model IDs, prompt text and warning policy.")
    }
    static var whisper: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.whisper", defaultValue: "Whisper",
               comment: "iOS display-only whisper; preserve model IDs, prompt text and warning policy.")
    }
    static var calm: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.calm", defaultValue: "Calm",
               comment: "iOS display-only calm; preserve model IDs, prompt text and warning policy.")
    }
    static var normal: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.normal", defaultValue: "Normal",
               comment: "iOS display-only normal; preserve model IDs, prompt text and warning policy.")
    }
    static var strong: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.strong", defaultValue: "Strong",
               comment: "iOS display-only strong; preserve model IDs, prompt text and warning policy.")
    }
    static var qualityShort: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.qualityShort", defaultValue: "Reference is shorter than recommended (under 10 seconds).",
               comment: "iOS display-only qualityShort; preserve model IDs, prompt text and warning policy.")
    }
    static var qualityLong: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.qualityLong", defaultValue: "Reference is longer than recommended (over 30 seconds).",
               comment: "iOS display-only qualityLong; preserve model IDs, prompt text and warning policy.")
    }
    static var qualityExcessive: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.qualityExcessive", defaultValue: "Reference exceeds the 60 second maximum supported for cloning.",
               comment: "iOS display-only qualityExcessive; preserve model IDs, prompt text and warning policy.")
    }
    static var qualityUnreadable: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.qualityUnreadable", defaultValue: "Reference audio could not be read.",
               comment: "iOS display-only qualityUnreadable; preserve model IDs, prompt text and warning policy.")
    }
    static var qualityIntro: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.qualityIntro", defaultValue: "Voice cloning works best with 10–20 seconds of clean speech.",
               comment: "iOS display-only qualityIntro; preserve model IDs, prompt text and warning policy.")
    }
    static var qualityHard: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.qualityHard", defaultValue: "Pick a clip that is 60 seconds or shorter to use it for cloning.",
               comment: "iOS display-only qualityHard; preserve model IDs, prompt text and warning policy.")
    }
    static var qualitySoft: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.qualitySoft", defaultValue: "Clones from references outside this range still work, but may sound less consistent.",
               comment: "iOS display-only qualitySoft; preserve model IDs, prompt text and warning policy.")
    }

    static func languageName(_ value: Qwen3SupportedLanguage) -> String {
        switch value {
        case .english: return english
        case .chinese: return chinese
        case .french: return french
        case .german: return german
        case .spanish: return spanish
        case .italian: return italian
        case .portuguese: return portuguese
        case .russian: return russian
        case .japanese: return japanese
        case .korean: return korean
        case .auto: return auto
        }
    }

    static func presetName(_ id: String, fallback: String? = nil) -> String {
        switch id {
        case "neutral": return neutral
        case "happy": return happy
        case "sad": return sad
        case "angry": return angry
        case "fearful": return fearful
        case "surprised": return surprised
        case "whisper": return whisper
        case "calm": return calm
        default: return fallback ?? neutral
        }
    }

    static func qualitySummary(_ tokens: [String]) -> String {
        let lines = tokens.compactMap { token -> String? in
            switch token {
            case "reference_duration_short": return qualityShort
            case "reference_duration_long": return qualityLong
            case "reference_duration_excessive": return qualityExcessive
            case "reference_quality_unreadable": return qualityUnreadable
            default: return nil
            }
        }
        guard !lines.isEmpty else { return qualityIntro }
        let trailer = PreparedVoiceQualityWarning.isHardBlocking(tokens) ? qualityHard : qualitySoft
        return qualityIntro + "\n\n" + lines.map { "• \($0)" }.joined(separator: "\n") + "\n\n" + trailer
    }
    static func deleteAllHistory(_ count: Int) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.deleteAllHistory", defaultValue: "This permanently deletes all %1$lld history entries and their audio files.",
                   comment: "iOS complete message: deleteAllHistory. Substitutions retain original user content and numeric values."), count)
    }
    static func clearAllHistory(_ count: Int) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.clearAllHistory", defaultValue: "This removes all %1$lld history entries. The generated audio files stay on the device.",
                   comment: "iOS complete message: clearAllHistory. Substitutions retain original user content and numeric values."), count)
    }
    static func queuedTakes(_ count: Int) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.queuedTakes", defaultValue: "%1$lld takes remain safely queued and available to retry or export.",
                   comment: "iOS complete message: queuedTakes. Substitutions retain original user content and numeric values."), count)
    }
    static func segmentCount(_ count: Int) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.segmentCount", defaultValue: "%1$lld segments",
                   comment: "iOS complete message: segmentCount. Substitutions retain original user content and numeric values."), count)
    }
    static func pinSeed(_ seed: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.pinSeed", defaultValue: "Pin seed %1$@ for new takes",
                   comment: "iOS complete message: pinSeed. Substitutions retain original user content and numeric values."), seed)
    }
    static func voiceBank(_ delivery: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.voiceBank", defaultValue: "Voice bank · %1$@",
                   comment: "iOS complete message: voiceBank. Substitutions retain original user content and numeric values."), delivery)
    }
    static func deletingVoice(_ name: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.deletingVoice", defaultValue: "Deleting %1$@",
                   comment: "iOS complete message: deletingVoice. Substitutions retain original user content and numeric values."), name)
    }
    static func actionsForVoice(_ name: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.actionsForVoice", defaultValue: "Actions for %1$@",
                   comment: "iOS complete message: actionsForVoice. Substitutions retain original user content and numeric values."), name)
    }
    static func deleteVoicePermanent(_ name: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.deleteVoicePermanent", defaultValue: "Delete \"%1$@\" from this iPhone? This cannot be undone.",
                   comment: "iOS complete message: deleteVoicePermanent. Substitutions retain original user content and numeric values."), name)
    }
    static func deleteVoiceBase(_ name: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.deleteVoiceBase", defaultValue: "Delete \"%1$@\"? Its voice-bank variants will remain as individual saved voices.",
                   comment: "iOS complete message: deleteVoiceBase. Substitutions retain original user content and numeric values."), name)
    }
    static func deleteVoiceVariant(_ name: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.deleteVoiceVariant", defaultValue: "Delete \"%1$@\"? The rest of this voice bank will remain available.",
                   comment: "iOS complete message: deleteVoiceVariant. Substitutions retain original user content and numeric values."), name)
    }
    static func duplicateVoice(_ name: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.duplicateVoice", defaultValue: "A saved voice named %1$@ already exists. Choose another name.",
                   comment: "iOS complete message: duplicateVoice. Substitutions retain original user content and numeric values."), name)
    }
    static func savedNamedVoice(_ name: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.savedNamedVoice", defaultValue: "Saved “%1$@”",
                   comment: "iOS complete message: savedNamedVoice. Substitutions retain original user content and numeric values."), name)
    }
    static func tooManySegments(_ count: Int, maximum: Int) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.tooManySegments", defaultValue: "This script plans %1$lld segments; the maximum is %2$lld. Split the text and try again.",
                   comment: "iOS complete message: tooManySegments. Substitutions retain original user content and numeric values."), count, maximum)
    }
    static func transcriptLoadFailed(_ name: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.transcriptLoadFailed", defaultValue: "Couldn’t load the saved transcript for \"%1$@\". Cloning can still use the audio.",
                   comment: "iOS complete message: transcriptLoadFailed. Substitutions retain original user content and numeric values."), name)
    }
    static func justNowMode(_ mode: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.justNowMode", defaultValue: "Just now · %1$@",
                   comment: "iOS complete message: justNowMode. Substitutions retain original user content and numeric values."), mode)
    }
    static func languageAuto(_ name: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.languageAuto", defaultValue: "%1$@ (Auto)",
                   comment: "iOS complete message: languageAuto. Substitutions retain original user content and numeric values."), name)
    }
    static func languagePath(_ name: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.languagePath", defaultValue: "Use Qwen3’s %1$@ path.",
                   comment: "iOS complete message: languagePath. Substitutions retain original user content and numeric values."), name)
    }
    static func voiceBankDetail(_ name: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.voiceBankDetail", defaultValue: "%1$@ is a voice bank: the same voice with curated emotion references. Each delivery clones its measured reference clip.",
                   comment: "iOS complete message: voiceBankDetail. Substitutions retain original user content and numeric values."), name)
    }
    static func freesStorage(_ size: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.freesStorage", defaultValue: "Frees %1$@. You can reinstall later from Settings.",
                   comment: "iOS complete message: freesStorage. Substitutions retain original user content and numeric values."), size)
    }
    static func segmentChoice(_ number: Int, text: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.segmentChoice", defaultValue: "Segment %1$lld: %2$@",
                   comment: "iOS complete message: segmentChoice. Substitutions retain original user content and numeric values."), number, text)
    }
    static var customDeliveryEmpty: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.customDeliveryEmpty", defaultValue: "Custom delivery…",
               comment: "iOS interface: Custom delivery…. Presentation only.")
    }
    static var customDelivery: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.customDelivery", defaultValue: "Custom delivery",
               comment: "iOS interface: Custom delivery. Presentation only.")
    }
    static var customPlaceholder: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.customPlaceholder", defaultValue: "Describe the delivery or emotion (optional)",
               comment: "iOS interface: Describe the delivery or emotion (optional). Presentation only.")
    }
    static var customOnly: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.customOnly", defaultValue: "Custom only",
               comment: "iOS interface: Custom only. Presentation only.")
    }
    static var customInput: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.customInput", defaultValue: "Custom delivery input",
               comment: "iOS interface: Custom delivery input. Presentation only.")
    }
    static var customInputDisabled: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.customInputDisabled", defaultValue: "Select Custom delivery to edit this field",
               comment: "iOS interface: Select Custom delivery to edit this field. Presentation only.")
    }
    static var builtInMeta: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.builtInMeta", defaultValue: "Built-in voice",
               comment: "iOS interface: Built-in voice. Presentation only.")
    }
    static var designedMeta: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.designedMeta", defaultValue: "Designed voice",
               comment: "iOS interface: Designed voice. Presentation only.")
    }
    static var longForm: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.longForm", defaultValue: "Long-form",
               comment: "iOS interface: Long-form. Presentation only.")
    }
    static var resumeProject: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.resumeProject", defaultValue: "Resume project",
               comment: "iOS interface: Resume project. Presentation only.")
    }
    static var describeVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.describeVoice", defaultValue: "Describe the voice",
               comment: "iOS interface: Describe the voice. Presentation only.")
    }
    static var saveGeneratedVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.saveGeneratedVoice", defaultValue: "Save Generated Voice",
               comment: "iOS interface: Save Generated Voice. Presentation only.")
    }
    static var referenceRange: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.referenceRange", defaultValue: "Reference outside recommended range",
               comment: "iOS interface: Reference outside recommended range. Presentation only.")
    }
    static var saveVoiceFailed: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.saveVoiceFailed", defaultValue: "Couldn't save voice",
               comment: "iOS interface: Couldn't save voice. Presentation only.")
    }
    static var nowInVoices: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.nowInVoices", defaultValue: "Now in your voices.",
               comment: "iOS interface: Now in your voices.. Presentation only.")
    }
    static var useClone: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.useClone", defaultValue: "Use in Clone",
               comment: "iOS interface: Use in Clone. Presentation only.")
    }
    static var recordedClip: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.recordedClip", defaultValue: "Recorded clip",
               comment: "iOS interface: Recorded clip. Presentation only.")
    }
    static var chooseReference: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.chooseReference", defaultValue: "Choose reference",
               comment: "iOS interface: Choose reference. Presentation only.")
    }
    static var chooseReferenceDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.chooseReferenceDetail", defaultValue: "Choose a saved voice or record a reference clip on this iPhone.",
               comment: "iOS interface: Choose a saved voice or record a reference clip on this iPhone.. Presentation only.")
    }
    static var loadingVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.loadingVoice", defaultValue: "Loading the selected voice.",
               comment: "iOS interface: Loading the selected voice.. Presentation only.")
    }
    static var preparingReference: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.preparingReference", defaultValue: "Preparing the reference audio.",
               comment: "iOS interface: Preparing the reference audio.. Presentation only.")
    }
    static var cloneMeta: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.cloneMeta", defaultValue: "Voice cloning",
               comment: "iOS interface: Voice cloning. Presentation only.")
    }
    static var cloneLoading: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.cloneLoading", defaultValue: "Voice cloning · Loading voice",
               comment: "iOS interface: Voice cloning · Loading voice. Presentation only.")
    }
    static var clonePreparing: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.clonePreparing", defaultValue: "Voice cloning · Preparing reference",
               comment: "iOS interface: Voice cloning · Preparing reference. Presentation only.")
    }
    static var cloneReady: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.cloneReady", defaultValue: "Voice cloning · Reference ready",
               comment: "iOS interface: Voice cloning · Reference ready. Presentation only.")
    }
    static var cloneOnGenerate: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.cloneOnGenerate", defaultValue: "Voice cloning · Prepares on generate",
               comment: "iOS interface: Voice cloning · Prepares on generate. Presentation only.")
    }
    static var cloneSelected: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.cloneSelected", defaultValue: "Voice cloning · Reference selected",
               comment: "iOS interface: Voice cloning · Reference selected. Presentation only.")
    }
    static var reference: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.reference", defaultValue: "Reference",
               comment: "iOS interface: Reference. Presentation only.")
    }
    static var descriptionLabel: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.descriptionLabel", defaultValue: "Description",
               comment: "iOS interface: Description. Presentation only.")
    }
    static var describeWanted: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.describeWanted", defaultValue: "Describe the voice you want",
               comment: "iOS interface: Describe the voice you want. Presentation only.")
    }
    static var speakerLabel: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.speakerLabel", defaultValue: "Speaker",
               comment: "iOS interface: Speaker. Presentation only.")
    }
    static var promptLabel: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.promptLabel", defaultValue: "Prompt",
               comment: "iOS interface: Prompt. Presentation only.")
    }
    static var missingDescriptor: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.missingDescriptor", defaultValue: "Missing model descriptor.",
               comment: "iOS interface: Missing model descriptor.. Presentation only.")
    }
    static var modelUnavailable: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.modelUnavailable", defaultValue: "This model is not available on iPhone yet, and the local files are incomplete.",
               comment: "iOS interface: This model is not available on iPhone yet, and the local files are incomplete.. Presentation only.")
    }
    static var deliveryUnavailable: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.deliveryUnavailable", defaultValue: "Model delivery is unavailable in this runtime.",
               comment: "iOS interface: Model delivery is unavailable in this runtime.. Presentation only.")
    }
    static var deliveryFailed: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.deliveryFailed", defaultValue: "Model delivery failed.",
               comment: "iOS interface: Model delivery failed.. Presentation only.")
    }
    static var deleteTakeQuestion: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.deleteTakeQuestion", defaultValue: "Delete this take?",
               comment: "iOS interface: Delete this take?. Presentation only.")
    }
    static var download: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.download", defaultValue: "Download",
               comment: "iOS interface: Download. Presentation only.")
    }
    static var distinctDeliveries: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.distinctDeliveries", defaultValue: "Distinct deliveries",
               comment: "iOS interface: Distinct deliveries. Presentation only.")
    }
    static var directionalHints: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.directionalHints", defaultValue: "Directional hints",
               comment: "iOS interface: Directional hints. Presentation only.")
    }
    static var recommended: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.recommended", defaultValue: "Recommended",
               comment: "iOS interface: Recommended. Presentation only.")
    }
    static var allLanguages: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.allLanguages", defaultValue: "All languages",
               comment: "iOS interface: All languages. Presentation only.")
    }
    static var allVoices: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.allVoices", defaultValue: "All voices",
               comment: "iOS interface: All voices. Presentation only.")
    }
    static var savedVoices: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.savedVoices", defaultValue: "Saved voices",
               comment: "iOS interface: Saved voices. Presentation only.")
    }
    static var inferLanguage: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.inferLanguage", defaultValue: "Infer from script or transcript.",
               comment: "iOS interface: Infer from script or transcript.. Presentation only.")
    }
    static var detectedText: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.detectedText", defaultValue: "Detected from your text.",
               comment: "iOS interface: Detected from your text.. Presentation only.")
    }
    static var captureSample: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.captureSample", defaultValue: "Capture a 10-20 second sample on this iPhone.",
               comment: "iOS interface: Capture a 10-20 second sample on this iPhone.. Presentation only.")
    }
    static var saveThisVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.saveThisVoice", defaultValue: "Save this voice",
               comment: "iOS interface: Save this voice. Presentation only.")
    }
    static var importVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.importVoice", defaultValue: "Import voice",
               comment: "iOS interface: Import voice. Presentation only.")
    }
    static var regenerateSegment: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.regenerateSegment", defaultValue: "Regenerate segment",
               comment: "iOS interface: Regenerate segment. Presentation only.")
    }
    static var regenerateSegmentTitle: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.regenerateSegmentTitle", defaultValue: "Regenerate a segment",
               comment: "iOS interface: Regenerate a segment. Presentation only.")
    }
    static var scriptLabel: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.scriptLabel", defaultValue: "Script",
               comment: "iOS interface: Script. Presentation only.")
    }
    static var scriptHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.scriptHint", defaultValue: "Enter or paste the text to generate.",
               comment: "iOS interface: Enter or paste the text to generate.. Presentation only.")
    }
    static var clearSearch: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.clearSearch", defaultValue: "Clear search",
               comment: "iOS interface: Clear search. Presentation only.")
    }
    static var unsupportedDevice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.unsupportedDevice", defaultValue: "Unsupported Device",
               comment: "iOS interface: Unsupported Device. Presentation only.")
    }
    static var initializationFailed: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.initializationFailed", defaultValue: "App Initialization Failed",
               comment: "iOS interface: App Initialization Failed. Presentation only.")
    }
    static var cancel: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.cancel", defaultValue: "Cancel",
               comment: "iOS interface: Cancel. Presentation only; never use as a model prompt or stored identity.")
    }
    static var close: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.close", defaultValue: "Close",
               comment: "iOS interface: Close. Presentation only; never use as a model prompt or stored identity.")
    }
    static var confirm: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.confirm", defaultValue: "Confirm",
               comment: "iOS interface: Confirm. Presentation only; never use as a model prompt or stored identity.")
    }
    static var retry: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.retry", defaultValue: "Retry",
               comment: "iOS interface: Retry. Presentation only; never use as a model prompt or stored identity.")
    }
    static var deleteAction: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.deleteAction", defaultValue: "Delete",
               comment: "iOS interface: Delete. Presentation only; never use as a model prompt or stored identity.")
    }
    static var dismiss: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.dismiss", defaultValue: "Dismiss",
               comment: "iOS interface: Dismiss. Presentation only; never use as a model prompt or stored identity.")
    }
    static var save: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.save", defaultValue: "Save",
               comment: "iOS interface: Save. Presentation only; never use as a model prompt or stored identity.")
    }
    static var share: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.share", defaultValue: "Share",
               comment: "iOS interface: Share. Presentation only; never use as a model prompt or stored identity.")
    }
    static var play: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.play", defaultValue: "Play",
               comment: "iOS interface: Play. Presentation only; never use as a model prompt or stored identity.")
    }
    static var pause: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.pause", defaultValue: "Pause",
               comment: "iOS interface: Pause. Presentation only; never use as a model prompt or stored identity.")
    }
    static var moreActions: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.moreActions", defaultValue: "More actions",
               comment: "iOS interface: More actions. Presentation only; never use as a model prompt or stored identity.")
    }
    static var playbackPosition: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.playbackPosition", defaultValue: "Playback position",
               comment: "iOS interface: Playback position. Presentation only; never use as a model prompt or stored identity.")
    }
    static var transcript: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.transcript", defaultValue: "Transcript",
               comment: "iOS interface: Transcript. Presentation only; never use as a model prompt or stored identity.")
    }
    static var all: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.all", defaultValue: "All",
               comment: "iOS interface: All. Presentation only; never use as a model prompt or stored identity.")
    }
    static var saved: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.saved", defaultValue: "Saved",
               comment: "iOS interface: Saved. Presentation only; never use as a model prompt or stored identity.")
    }
    static var today: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.today", defaultValue: "Today",
               comment: "iOS interface: Today. Presentation only; never use as a model prompt or stored identity.")
    }
    static var yesterday: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.yesterday", defaultValue: "Yesterday",
               comment: "iOS interface: Yesterday. Presentation only; never use as a model prompt or stored identity.")
    }
    static var previous7: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.previous7", defaultValue: "Previous 7 Days",
               comment: "iOS interface: Previous 7 Days. Presentation only; never use as a model prompt or stored identity.")
    }
    static var previous30: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.previous30", defaultValue: "Previous 30 Days",
               comment: "iOS interface: Previous 30 Days. Presentation only; never use as a model prompt or stored identity.")
    }
    static var earlier: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.earlier", defaultValue: "Earlier",
               comment: "iOS interface: Earlier. Presentation only; never use as a model prompt or stored identity.")
    }
    static var historySearch: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.historySearch", defaultValue: "Search transcript or voice",
               comment: "iOS interface: Search transcript or voice. Presentation only; never use as a model prompt or stored identity.")
    }
    static var clearKeepFiles: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.clearKeepFiles", defaultValue: "Clear History (Keep Audio Files)…",
               comment: "iOS interface: Clear History (Keep Audio Files)…. Presentation only; never use as a model prompt or stored identity.")
    }
    static var clearDeleteFiles: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.clearDeleteFiles", defaultValue: "Clear History and Delete Audio…",
               comment: "iOS interface: Clear History and Delete Audio…. Presentation only; never use as a model prompt or stored identity.")
    }
    static var clearHistoryLower: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.clearHistoryLower", defaultValue: "Clear history",
               comment: "iOS interface: Clear history. Presentation only; never use as a model prompt or stored identity.")
    }
    static var historyLoadFailed: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.historyLoadFailed", defaultValue: "Couldn't load history",
               comment: "iOS interface: Couldn't load history. Presentation only; never use as a model prompt or stored identity.")
    }
    static var historyLoadDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.historyLoadDetail", defaultValue: "Something went wrong reading your history. Tap Retry below.",
               comment: "iOS interface: Something went wrong reading your history. Tap Retry below.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var noTakes: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.noTakes", defaultValue: "No takes yet",
               comment: "iOS interface: No takes yet. Presentation only; never use as a model prompt or stored identity.")
    }
    static var noTakesDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.noTakesDetail", defaultValue: "Generated audio shows up here once you create a voice or line.",
               comment: "iOS interface: Generated audio shows up here once you create a voice or line.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var noMatches: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.noMatches", defaultValue: "No matches",
               comment: "iOS interface: No matches. Presentation only; never use as a model prompt or stored identity.")
    }
    static var noMatchesDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.noMatchesDetail", defaultValue: "Nothing matches this filter or search. Try widening it.",
               comment: "iOS interface: Nothing matches this filter or search. Try widening it.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var clearDeleteQuestion: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.clearDeleteQuestion", defaultValue: "Clear History and Delete Audio?",
               comment: "iOS interface: Clear History and Delete Audio?. Presentation only; never use as a model prompt or stored identity.")
    }
    static var deleteEverything: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.deleteEverything", defaultValue: "Delete Everything",
               comment: "iOS interface: Delete Everything. Presentation only; never use as a model prompt or stored identity.")
    }
    static var clearQuestion: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.clearQuestion", defaultValue: "Clear History?",
               comment: "iOS interface: Clear History?. Presentation only; never use as a model prompt or stored identity.")
    }
    static var clearHistory: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.clearHistory", defaultValue: "Clear History",
               comment: "iOS interface: Clear History. Presentation only; never use as a model prompt or stored identity.")
    }
    static var historyWaiting: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.historyWaiting", defaultValue: "Finished audio is waiting for History",
               comment: "iOS interface: Finished audio is waiting for History. Presentation only; never use as a model prompt or stored identity.")
    }
    static var historyRecoveryProblem: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.historyRecoveryProblem", defaultValue: "Vocello preserved the recovery record but could not verify or commit it. Retry before clearing History.",
               comment: "iOS interface: Vocello preserved the recovery record but could not verify or commit it. Retry before clearing History.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var saveAudio: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.saveAudio", defaultValue: "Save audio",
               comment: "iOS interface: Save audio. Presentation only; never use as a model prompt or stored identity.")
    }
    static var deleteAudioDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.deleteAudioDetail", defaultValue: "This permanently removes the generated audio and its history entry.",
               comment: "iOS interface: This permanently removes the generated audio and its history entry.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var microphoneDenied: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.microphoneDenied", defaultValue: "Microphone access denied",
               comment: "iOS interface: Microphone access denied. Presentation only; never use as a model prompt or stored identity.")
    }
    static var microphoneDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.microphoneDetail", defaultValue: "Vocello needs the microphone to record reference clips. Enable it in Settings to continue.",
               comment: "iOS interface: Vocello needs the microphone to record reference clips. Enable it in Settings to continue.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var recordGuidance: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.recordGuidance", defaultValue: "Read 10-20 s of clean, natural speech. Quiet room. One voice.",
               comment: "iOS interface: Read 10-20 s of clean, natural speech. Quiet room. One voice.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var recording: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.recording", defaultValue: "Recording",
               comment: "iOS interface: Recording. Presentation only; never use as a model prompt or stored identity.")
    }
    static var captured: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.captured", defaultValue: "Captured",
               comment: "iOS interface: Captured. Presentation only; never use as a model prompt or stored identity.")
    }
    static var referenceClip: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.referenceClip", defaultValue: "Reference clip",
               comment: "iOS interface: Reference clip. Presentation only; never use as a model prompt or stored identity.")
    }
    static var recordInterrupted: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.recordInterrupted", defaultValue: "Recording was interrupted. The clip up to that point was kept.",
               comment: "iOS interface: Recording was interrupted. The clip up to that point was kept.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var recordBegin: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.recordBegin", defaultValue: "Tap Record to begin.",
               comment: "iOS interface: Tap Record to begin.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var recordMinimum: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.recordMinimum", defaultValue: "Keep recording. 10 second minimum.",
               comment: "iOS interface: Keep recording. 10 second minimum.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var recordEnough: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.recordEnough", defaultValue: "Sounds good. Tap stop when ready.",
               comment: "iOS interface: Sounds good. Tap stop when ready.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var recordMaximum: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.recordMaximum", defaultValue: "Over 20 seconds. Stop now.",
               comment: "iOS interface: Over 20 seconds. Stop now.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var stop: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.stop", defaultValue: "Stop",
               comment: "iOS interface: Stop. Presentation only; never use as a model prompt or stored identity.")
    }
    static var retake: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.retake", defaultValue: "Retake",
               comment: "iOS interface: Retake. Presentation only; never use as a model prompt or stored identity.")
    }
    static var useClip: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.useClip", defaultValue: "Use this clip",
               comment: "iOS interface: Use this clip. Presentation only; never use as a model prompt or stored identity.")
    }
    static var need10: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.need10", defaultValue: "Need 10 s",
               comment: "iOS interface: Need 10 s. Presentation only; never use as a model prompt or stored identity.")
    }
    static var record: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.record", defaultValue: "Record",
               comment: "iOS interface: Record. Presentation only; never use as a model prompt or stored identity.")
    }
    static var keepVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.keepVoice", defaultValue: "Keep voice",
               comment: "iOS interface: Keep voice. Presentation only; never use as a model prompt or stored identity.")
    }
    static var discardRecord: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.discardRecord", defaultValue: "Discard and re-record",
               comment: "iOS interface: Discard and re-record. Presentation only; never use as a model prompt or stored identity.")
    }
    static var discardImport: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.discardImport", defaultValue: "Discard imported voice",
               comment: "iOS interface: Discard imported voice. Presentation only; never use as a model prompt or stored identity.")
    }
    static var playRecording: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.playRecording", defaultValue: "Play recording",
               comment: "iOS interface: Play recording. Presentation only; never use as a model prompt or stored identity.")
    }
    static var shortClip: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.shortClip", defaultValue: "A bit short",
               comment: "iOS interface: A bit short. Presentation only; never use as a model prompt or stored identity.")
    }
    static var goodLength: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.goodLength", defaultValue: "Good length",
               comment: "iOS interface: Good length. Presentation only; never use as a model prompt or stored identity.")
    }
    static var longClip: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.longClip", defaultValue: "A bit long",
               comment: "iOS interface: A bit long. Presentation only; never use as a model prompt or stored identity.")
    }
    static var voiceName: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.voiceName", defaultValue: "Name",
               comment: "iOS interface: Name. Presentation only; never use as a model prompt or stored identity.")
    }
    static var nameVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.nameVoice", defaultValue: "Name this voice",
               comment: "iOS interface: Name this voice. Presentation only; never use as a model prompt or stored identity.")
    }
    static var whatYouSaid: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.whatYouSaid", defaultValue: "What you said",
               comment: "iOS interface: What you said. Presentation only; never use as a model prompt or stored identity.")
    }
    static var transcriptCaption: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.transcriptCaption", defaultValue: "Auto-transcribed. With it, clones carry this clip's pacing and emotion; without it, identity only.",
               comment: "iOS interface: Auto-transcribed. With it, clones carry this clip's pacing and emotion; without it, identity only.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var transcriptPlaceholder: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.transcriptPlaceholder", defaultValue: "What you said in the recording",
               comment: "iOS interface: What you said in the recording. Presentation only; never use as a model prompt or stored identity.")
    }
    static var saveVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.saveVoice", defaultValue: "Save voice",
               comment: "iOS interface: Save voice. Presentation only; never use as a model prompt or stored identity.")
    }
    static var savedVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.savedVoice", defaultValue: "Saved voice",
               comment: "iOS interface: Saved voice. Presentation only; never use as a model prompt or stored identity.")
    }
    static var voicePreview: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.voicePreview", defaultValue: "Voice preview",
               comment: "iOS interface: Voice preview. Presentation only; never use as a model prompt or stored identity.")
    }
    static var dismissClip: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.dismissClip", defaultValue: "Dismiss this clip?",
               comment: "iOS interface: Dismiss this clip?. Presentation only; never use as a model prompt or stored identity.")
    }
    static var saveAsVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.saveAsVoice", defaultValue: "Save as voice",
               comment: "iOS interface: Save as voice. Presentation only; never use as a model prompt or stored identity.")
    }
    static var generateAgain: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.generateAgain", defaultValue: "Generate again",
               comment: "iOS interface: Generate again. Presentation only; never use as a model prompt or stored identity.")
    }
    static var generateAgainLabel: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.generateAgainLabel", defaultValue: "Generate this take again",
               comment: "iOS interface: Generate this take again. Presentation only; never use as a model prompt or stored identity.")
    }
    static var generateAgainHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.generateAgainHint", defaultValue: "Starts a new generation using the visible Studio settings",
               comment: "iOS interface: Starts a new generation using the visible Studio settings. Presentation only; never use as a model prompt or stored identity.")
    }
    static var streamingPreview: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.streamingPreview", defaultValue: "Streaming preview",
               comment: "iOS interface: Streaming preview. Presentation only; never use as a model prompt or stored identity.")
    }
    static var cancelGeneration: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.cancelGeneration", defaultValue: "Cancel generation",
               comment: "iOS interface: Cancel generation. Presentation only; never use as a model prompt or stored identity.")
    }
    static var preparingPreview: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.preparingPreview", defaultValue: "Preparing preview",
               comment: "iOS interface: Preparing preview. Presentation only; never use as a model prompt or stored identity.")
    }
    static var previewProgress: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.previewProgress", defaultValue: "Preview playback progress",
               comment: "iOS interface: Preview playback progress. Presentation only; never use as a model prompt or stored identity.")
    }
    static var liveProgress: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.liveProgress", defaultValue: "Live preview progress",
               comment: "iOS interface: Live preview progress. Presentation only; never use as a model prompt or stored identity.")
    }
    static var clonedReference: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.clonedReference", defaultValue: "Cloned reference",
               comment: "iOS interface: Cloned reference. Presentation only; never use as a model prompt or stored identity.")
    }
    static var searchVoices: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.searchVoices", defaultValue: "Search voices",
               comment: "iOS interface: Search voices. Presentation only; never use as a model prompt or stored identity.")
    }
    static var yourVoices: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.yourVoices", defaultValue: "Your saved voices",
               comment: "iOS interface: Your saved voices. Presentation only; never use as a model prompt or stored identity.")
    }
    static var builtInSpeakers: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.builtInSpeakers", defaultValue: "Built-in speakers",
               comment: "iOS interface: Built-in speakers. Presentation only; never use as a model prompt or stored identity.")
    }
    static var nothingMatches: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.nothingMatches", defaultValue: "Nothing matches",
               comment: "iOS interface: Nothing matches. Presentation only; never use as a model prompt or stored identity.")
    }
    static var voiceSearchDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.voiceSearchDetail", defaultValue: "Try a different search term or switch the filter back to All.",
               comment: "iOS interface: Try a different search term or switch the filter back to All.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var importFailed: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.importFailed", defaultValue: "Couldn't import audio",
               comment: "iOS interface: Couldn't import audio. Presentation only; never use as a model prompt or stored identity.")
    }
    static var importFailedDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.importFailedDetail", defaultValue: "Choose another audio file and try again.",
               comment: "iOS interface: Choose another audio file and try again.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var deleteVoiceQuestion: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.deleteVoiceQuestion", defaultValue: "Delete saved voice?",
               comment: "iOS interface: Delete saved voice?. Presentation only; never use as a model prompt or stored identity.")
    }
    static var deleteFailed: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.deleteFailed", defaultValue: "Delete failed",
               comment: "iOS interface: Delete failed. Presentation only; never use as a model prompt or stored identity.")
    }
    static var deleteFailedDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.deleteFailedDetail", defaultValue: "The saved voice was not removed. Try again.",
               comment: "iOS interface: The saved voice was not removed. Try again.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var saveNewVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.saveNewVoice", defaultValue: "Save a new voice",
               comment: "iOS interface: Save a new voice. Presentation only; never use as a model prompt or stored identity.")
    }
    static var recordVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.recordVoice", defaultValue: "Record voice",
               comment: "iOS interface: Record voice. Presentation only; never use as a model prompt or stored identity.")
    }
    static var captureDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.captureDetail", defaultValue: "Capture a 10-20 second reference clip on this iPhone.",
               comment: "iOS interface: Capture a 10-20 second reference clip on this iPhone.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var stopPreview: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.stopPreview", defaultValue: "Stop preview",
               comment: "iOS interface: Stop preview. Presentation only; never use as a model prompt or stored identity.")
    }
    static var previewVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.previewVoice", defaultValue: "Preview voice",
               comment: "iOS interface: Preview voice. Presentation only; never use as a model prompt or stored identity.")
    }
    static var deleteVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.deleteVoice", defaultValue: "Delete voice",
               comment: "iOS interface: Delete voice. Presentation only; never use as a model prompt or stored identity.")
    }
    static var waitDelete: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.waitDelete", defaultValue: "Wait for generation to finish before deleting this voice.",
               comment: "iOS interface: Wait for generation to finish before deleting this voice.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var voiceActionsHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.voiceActionsHint", defaultValue: "Opens actions for this saved voice.",
               comment: "iOS interface: Opens actions for this saved voice.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var waitCurrentDelete: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.waitCurrentDelete", defaultValue: "Wait for the current generation to finish before deleting this voice.",
               comment: "iOS interface: Wait for the current generation to finish before deleting this voice.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var voiceBrief: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.voiceBrief", defaultValue: "Voice brief",
               comment: "iOS interface: Voice brief. Presentation only; never use as a model prompt or stored identity.")
    }
    static var briefGuidance: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.briefGuidance", defaultValue: "Describe the voice. Combine character, age, accent, and texture.",
               comment: "iOS interface: Describe the voice. Combine character, age, accent, and texture.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var briefPlaceholder: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.briefPlaceholder", defaultValue: "A warm, deep narrator with a subtle British accent.",
               comment: "iOS interface: A warm, deep narrator with a subtle British accent.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var startingPoints: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.startingPoints", defaultValue: "Starting points",
               comment: "iOS interface: Starting points. Presentation only; never use as a model prompt or stored identity.")
    }
    static var customTone: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.customTone", defaultValue: "Custom tone",
               comment: "iOS interface: Custom tone. Presentation only; never use as a model prompt or stored identity.")
    }
    static var delivery: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.delivery", defaultValue: "Delivery",
               comment: "iOS interface: Delivery. Presentation only; never use as a model prompt or stored identity.")
    }
    static var useCustomTone: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.useCustomTone", defaultValue: "Use a custom tone instead",
               comment: "iOS interface: Use a custom tone instead. Presentation only; never use as a model prompt or stored identity.")
    }
    static var toneGuidance: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.toneGuidance", defaultValue: "Be specific: combine emotion, pace, pitch, and timbre.",
               comment: "iOS interface: Be specific: combine emotion, pace, pitch, and timbre.. Presentation only; never use as a model prompt or stored identity.")
    }
    static var examples: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.examples", defaultValue: "Examples",
               comment: "iOS interface: Examples. Presentation only; never use as a model prompt or stored identity.")
    }
    static var language: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.language", defaultValue: "Language",
               comment: "iOS interface: Language. Presentation only; never use as a model prompt or stored identity.")
    }
    static var voice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.voice", defaultValue: "Voice",
               comment: "iOS interface: Voice. Presentation only; never use as a model prompt or stored identity.")
    }
    static var recordNewClip: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.recordNewClip", defaultValue: "Record new clip",
               comment: "iOS interface: Record new clip. Presentation only; never use as a model prompt or stored identity.")
    }
    static var deleteModelQuestion: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.deleteModelQuestion", defaultValue: "Delete model?",
               comment: "iOS interface: Delete model?. Presentation only; never use as a model prompt or stored identity.")
    }
    static var deleteModel: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.deleteModel", defaultValue: "Delete model",
               comment: "iOS interface: Delete model. Presentation only; never use as a model prompt or stored identity.")
    }
    static var neutralHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.neutralHint", defaultValue: "Default, even pacing",
               comment: "iOS interface: Default, even pacing. Presentation only; never use as a model prompt or stored identity.")
    }
    static var happyHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.happyHint", defaultValue: "Bright lift; can read as surprise",
               comment: "iOS interface: Bright lift; can read as surprise. Presentation only; never use as a model prompt or stored identity.")
    }
    static var sadHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.sadHint", defaultValue: "Quiet, slower, somber",
               comment: "iOS interface: Quiet, slower, somber. Presentation only; never use as a model prompt or stored identity.")
    }
    static var angryHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.angryHint", defaultValue: "Hard, driving push",
               comment: "iOS interface: Hard, driving push. Presentation only; never use as a model prompt or stored identity.")
    }
    static var fearfulHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.fearfulHint", defaultValue: "Soft, unsteady; can read as sad",
               comment: "iOS interface: Soft, unsteady; can read as sad. Presentation only; never use as a model prompt or stored identity.")
    }
    static var surprisedHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.surprisedHint", defaultValue: "Pitch jumps, quick catches",
               comment: "iOS interface: Pitch jumps, quick catches. Presentation only; never use as a model prompt or stored identity.")
    }
    static var whisperHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.whisperHint", defaultValue: "Soft, close-mic breath",
               comment: "iOS interface: Soft, close-mic breath. Presentation only; never use as a model prompt or stored identity.")
    }
    static var calmHint: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.calmHint", defaultValue: "Slower, reassuring",
               comment: "iOS interface: Slower, reassuring. Presentation only; never use as a model prompt or stored identity.")
    }
    static var tabStudio: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.tabStudio", defaultValue: "Studio",
               comment: "Bottom navigation tab for generation.")
    }
    static var tabVoices: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.tabVoices", defaultValue: "Voices",
               comment: "Bottom navigation tab for saved voices.")
    }
    static var tabHistory: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.tabHistory", defaultValue: "History",
               comment: "Bottom navigation tab for generated clips.")
    }
    static var tabSettings: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.tabSettings", defaultValue: "Settings",
               comment: "Bottom navigation tab for app settings.")
    }
    static var modeBuiltIn: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.modeBuiltIn", defaultValue: "Built-in",
               comment: "Compact Studio selector for built-in voices; presentation only.")
    }
    static var modeDesign: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.modeDesign", defaultValue: "Design",
               comment: "Compact Studio selector for voice design; presentation only.")
    }
    static var modeClone: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.modeClone", defaultValue: "Clone",
               comment: "Compact Studio selector for voice cloning; presentation only.")
    }
    static var skip: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.skip", defaultValue: "Skip",
               comment: "Dismiss informational onboarding without installing a model.")
    }
    static var getStarted: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.getStarted", defaultValue: "Get started",
               comment: "First onboarding page action.")
    }
    static var continueAction: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.continueAction", defaultValue: "Continue",
               comment: "Advance to the next informational onboarding page.")
    }
    static var openStudio: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.openStudio", defaultValue: "Open Studio",
               comment: "Finish onboarding and open Studio.")
    }
    static var welcomeDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.welcomeDetail", defaultValue: "Studio-quality voice generation. Runs entirely on this iPhone.",
               comment: "Onboarding welcome description.")
    }
    static var onDeviceBenefit: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.onDeviceBenefit", defaultValue: "Nothing leaves your device",
               comment: "Onboarding statement about local voice generation; not model downloads.")
    }
    static var speedBenefit: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.speedBenefit", defaultValue: "Generation in seconds",
               comment: "Existing onboarding generation benefit, not a timing guarantee.")
    }
    static var modesBenefit: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.modesBenefit", defaultValue: "Clone, design, or pick a voice",
               comment: "Onboarding overview of three generation modes.")
    }
    static var installBuiltIn: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.installBuiltIn", defaultValue: "Install Built-in Voice",
               comment: "Onboarding installation heading; this page does not initiate a download.")
    }
    static var installDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.installDetail", defaultValue: "Download the 4-bit Speed model to start generating. Voice Design and Voice Cloning each have their own model; install them later in Settings.",
               comment: "Onboarding explanation of separately downloaded models; Speed is the model-tier name.")
    }
    static var builtInDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.builtInDetail", defaultValue: "Built-in speakers and delivery presets.",
               comment: "Onboarding built-in mode explanation.")
    }
    static var designDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.designDetail", defaultValue: "Describe a voice in natural language.",
               comment: "Onboarding design mode explanation, never submitted as a generation prompt.")
    }
    static var cloneDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.cloneDetail", defaultValue: "Use a 10-20 s reference clip you own.",
               comment: "Onboarding clone mode reference guidance.")
    }
    static var onboardingReady: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.onboardingReady", defaultValue: "You're ready",
               comment: "Onboarding completion heading, not an installed-model status.")
    }
    static var onboardingReadyDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.onboardingReadyDetail", defaultValue: "Download a voice model in Settings, then type a script, pick a voice, generate. Your audio stays here.",
               comment: "Final onboarding page explains that model installation is still required.")
    }
    static var installFirstVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.installFirstVoice", defaultValue: "Install your first voice",
               comment: "First-run model installation card heading.")
    }
    static var firstVoiceDetail: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.firstVoiceDetail", defaultValue: "Open Settings to download a Built-in Voice, Voice Design, or Voice Cloning model. Every package runs on-device.",
               comment: "First-run model installation card guidance.")
    }
    static var openSettings: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.openSettings", defaultValue: "Open Settings",
               comment: "First-run navigation to Settings.")
    }
    static var scriptPlaceholder: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.scriptPlaceholder", defaultValue: "Type or paste your script.",
               comment: "Empty Built-in composer placeholder, never actual script text.")
    }
    static var designPlaceholder: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.designPlaceholder", defaultValue: "Type the lines you want this designed voice to say.",
               comment: "Empty Design composer placeholder, never actual script text.")
    }
    static var clonePlaceholder: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.clonePlaceholder", defaultValue: "Type the new text. The reference voice will speak it.",
               comment: "Empty Clone composer placeholder, never actual script text.")
    }
    static var clearScript: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.clearScript", defaultValue: "Clear",
               comment: "Clear the editable Studio script.")
    }
    static var generate: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.generate", defaultValue: "Generate",
               comment: "Start speech generation.")
    }
    static var generating: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.generating", defaultValue: "Generating",
               comment: "Active Studio generation heading.")
    }
    static var tryAgain: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.tryAgain", defaultValue: "Try again.",
               comment: "Fallback Studio failure guidance.")
    }
    static var renderingAudio: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.renderingAudio", defaultValue: "Rendering audio…",
               comment: "Built-in generation progress message.")
    }
    static var designingVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.designingVoice", defaultValue: "Designing voice…",
               comment: "Design generation progress message.")
    }
    static var cloningVoice: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.cloningVoice", defaultValue: "Cloning voice…",
               comment: "Clone generation progress message.")
    }
    static var justNow: String {
        IOSAppLanguage.shared.localized(localized: "vocello.ui.justNow", defaultValue: "Just now",
               comment: "Relative time for the newly completed Studio take.")
    }

    static func page(_ current: Int, of total: Int) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.page", defaultValue: "Page %1$lld of %2$lld",
                   comment: "VoiceOver onboarding page position and total."), current, total)
    }

    static func installModel(_ name: String) -> String {
        IOSAppLanguage.shared.format(IOSAppLanguage.shared.localized(localized: "vocello.ui.installModel", defaultValue: "Install %1$@",
                   comment: "Studio install button; substitution is the localized model display name."), name)
    }
}

enum IOSAppTab: String, CaseIterable, Identifiable {
    case studio
    case voices
    case history
    case settings

    var id: String { rawValue }
}

enum IOSGenerationSection: String, CaseIterable, Identifiable {
    case custom
    case design
    case clone

    var id: String { rawValue }

    var mode: GenerationMode {
        switch self {
        case .custom: return .custom
        case .design: return .design
        case .clone: return .clone
        }
    }

    @MainActor var title: String {
        IOSSettingsText.modeName(mode)
    }

    @MainActor var compactTitle: String {
        // Mode segmented uses the mode name (per design_references/Vocello iOS/
        // chrome.jsx ModeSegmented). The longer action-oriented labels live on
        // the setup-chip pattern; the segmented control itself stays terse.
        switch self {
        case .custom:
            return IOSInterfaceText.modeBuiltIn
        case .design:
            return IOSInterfaceText.modeDesign
        case .clone:
            return IOSInterfaceText.modeClone
        }
    }
}
