// Prompt assembly of the Qwen3-TTS runtime: the generation inputs for Built-in Voice,
// Voice Design and Voice Cloning, and the chat-template text rules.
// Moved out of Qwen3TTS.swift unchanged (RF-46).

import CryptoKit
import Foundation
import Hub
import HuggingFace
@preconcurrency import MLX
import MLXAudioCore
@preconcurrency import MLXLMCommon
import MLXNN
import os
import Tokenizers

/// The clone target's text where it follows the reference transcript (A-11).
enum Qwen3ICLTargetText {
    /// The tokenizer is byte-level BPE with `add_prefix_space: false`, and the
    /// clone layout joins the reference transcript's tokens and the target's
    /// with no separator, as upstream does. Without a leading space a target's
    /// first word loses its word-boundary marker and glues to the transcript;
    /// short French first words (such as "Ce") were dropped, so Vocello puts
    /// exactly one space before the target (idempotent). With
    /// `onlyBeforeSpacedScripts` (production since 2026-11-12, A-11) a target
    /// whose first letter is Han or kana gets none, as upstream's join gives
    /// it: those scripts mark no word boundary with spaces. Digits and punctuation before the first letter do
    /// not decide ("3个苹果" joins, "2024 report" keeps its space).
    static func boundaryMarked(_ text: String, onlyBeforeSpacedScripts: Bool) -> String {
        let target = text.drop(while: { $0.isWhitespace })
        if onlyBeforeSpacedScripts,
           let first = target.first(where: { $0.isLetter }),
           isUnspacedScript(first) {
            return String(target)
        }
        return " " + target
    }

    /// Han (its unified ideographs with every extension, the compatibility
    /// ideographs and 々 〆 〇) and kana (with the halfwidth forms).
    static func isUnspacedScript(_ character: Character) -> Bool {
        guard let scalar = character.unicodeScalars.first else {
            return false
        }
        switch scalar.value {
        case 0x3040 ... 0x30FF, 0x31F0 ... 0x31FF, 0xFF66 ... 0xFF9F,
             0x3005 ... 0x3007, 0x3400 ... 0x4DBF, 0x4E00 ... 0x9FFF, 0xF900 ... 0xFAFF,
             0x20000 ... 0x323AF, 0x2F800 ... 0x2FA1F:
            return true
        default:
            return false
        }
    }
}

extension Qwen3TTSModel {
    // MARK: - Prepare generation inputs

    func prepareICLGenerationInputs(
        text: String,
        refAudio: MLXArray,
        refText: String,
        speakerEmbedding: MLXArray?,
        language: String
    ) throws -> (
        inputEmbeds: MLXArray,
        trailingTextHidden: MLXArray,
        ttsPadEmbed: MLXArray,
        refCodes: MLXArray,
        targetTokenCount: Int
    ) {
        let refAudioForEncoder = try Qwen3TTSReferenceAudio.encoderInput(
            refAudio, trailingSilenceSamples: referenceTrailingSilenceSamples)
        guard let speechTokenizer else {
            throw AudioGenerationError.modelNotInitialized("Speech tokenizer not loaded")
        }
        let refCodes = try speechTokenizer.encode(refAudioForEncoder) // [1, num_code_groups, ref_time]
        return try prepareICLGenerationInputs(
            text: text,
            refCodes: refCodes,
            refText: refText,
            speakerEmbedding: speakerEmbedding,
            language: language
        )
    }

    func prepareICLGenerationInputs(
        text: String,
        refCodes: MLXArray,
        refText: String,
        speakerEmbedding: MLXArray?,
        language: String
    ) throws -> (
        inputEmbeds: MLXArray,
        trailingTextHidden: MLXArray,
        ttsPadEmbed: MLXArray,
        refCodes: MLXArray,
        targetTokenCount: Int
    ) {
        guard let tokenizer, let talkerConfig = config.talkerConfig else {
            throw AudioGenerationError.modelNotInitialized("Tokenizer/config not loaded")
        }

        // Reference text and target text tokenization
        let text = Qwen3ChatTemplateText.preparedForTemplate(text)
        let refText = Qwen3ChatTemplateText.preparedForTemplate(refText)
        let targetTokenCount = tokenizer.encode(text: text).count
        let refChatText = "<|im_start|>assistant\n\(refText)<|im_end|>\n"
        let refIds = MLXArray(tokenizer.encode(text: refChatText).map { Int32($0) }).reshaped(1, -1)
        let refCount = refIds.dim(1)
        let refStart = min(3, refCount)
        let refEnd = max(refStart, refCount - 2)
        let refTextIds = refIds[0..., refStart ..< refEnd]

        let boundaryMarkedText = Qwen3ICLTargetText.boundaryMarked(
            text,
            onlyBeforeSpacedScripts: iclTargetSpaceOnlyBeforeSpacedScripts
        )
        let targetChatText = "<|im_start|>assistant\n\(boundaryMarkedText)<|im_end|>\n<|im_start|>assistant\n"
        let targetIds = MLXArray(tokenizer.encode(text: targetChatText).map { Int32($0) }).reshaped(1, -1)
        let targetCount = targetIds.dim(1)
        let targetStart = min(3, targetCount)
        let targetEnd = max(targetStart, targetCount - 5)
        let targetTextIds = targetIds[0..., targetStart ..< targetEnd]

        // TTS special tokens
        let ttsTokens = MLXArray(
            [Int32(config.ttsBosTokenId), Int32(config.ttsEosTokenId), Int32(config.ttsPadTokenId)]
        ).reshaped(1, 3)
        let ttsEmbeds = talker.textProjection(try talker.embedText(ttsTokens))
        let ttsBosEmbed = ttsEmbeds[0..., 0 ..< 1, 0...]
        let ttsEosEmbed = ttsEmbeds[0..., 1 ..< 2, 0...]
        let ttsPadEmbed = ttsEmbeds[0..., 2 ..< 3, 0...]

        // Build text embeddings for ref+target
        let combinedTextIds = concatenated([refTextIds, targetTextIds], axis: 1)
        var textEmbed = talker.textProjection(try talker.embedText(combinedTextIds))
        textEmbed = concatenated([textEmbed, ttsEosEmbed], axis: 1)
        let textLen = textEmbed.dim(1)

        // Build codec embeddings from reference codes: codec_bos + sum of all codebook embeddings
        let firstCbCodes = refCodes[0..., 0, 0...]
        var refCodecEmbed = talker.getInputEmbeddings()(firstCbCodes)
        if talkerConfig.numCodeGroups > 1 {
            for i in 0 ..< (talkerConfig.numCodeGroups - 1) {
                let codeIdx = i + 1
                if codeIdx >= refCodes.dim(1) { break }
                let cbCodes = refCodes[0..., codeIdx, 0...]
                refCodecEmbed = refCodecEmbed + talker.codePredictor.codecEmbedding[i](cbCodes)
            }
        }

        let codecBosEmbed = talker.getInputEmbeddings()(
            MLXArray([Int32(talkerConfig.codecBosId)]).reshaped(1, 1)
        )
        let codecEmbedIcl = concatenated([codecBosEmbed, refCodecEmbed], axis: 1)

        // Non-streaming overlay of text and codec contexts
        let codecPadEmbed = talker.getInputEmbeddings()(MLXArray([Int32(talkerConfig.codecPadId)]).reshaped(1, 1))
        let textWithCodecPad = textEmbed + broadcast(
            codecPadEmbed,
            to: [1, textLen, codecPadEmbed.dim(-1)]
        )
        let codecWithTextPad = codecEmbedIcl + broadcast(
            ttsPadEmbed,
            to: [1, codecEmbedIcl.dim(1), ttsPadEmbed.dim(-1)]
        )

        let iclInputEmbed = concatenated([textWithCodecPad, codecWithTextPad], axis: 1)
        let trailingTextHidden = ttsPadEmbed

        // Language ID
        var languageId: Int?
        if language.lowercased() != "auto", let langMap = talkerConfig.codecLanguageId {
            languageId = langMap[language.lowercased()]
        }

        let codecPrefill: [Int32] = if let langId = languageId {
            [
                Int32(talkerConfig.codecThinkId),
                Int32(talkerConfig.codecThinkBosId),
                Int32(langId),
                Int32(talkerConfig.codecThinkEosId)
            ]
        } else {
            [
                Int32(talkerConfig.codecNothinkId),
                Int32(talkerConfig.codecThinkBosId),
                Int32(talkerConfig.codecThinkEosId)
            ]
        }

        var codecPrefixEmbed = talker.getInputEmbeddings()(MLXArray(codecPrefill).reshaped(1, -1))
        let codecPrefixSuffix = talker.getInputEmbeddings()(
            MLXArray([Int32(talkerConfig.codecPadId), Int32(talkerConfig.codecBosId)]).reshaped(1, 2)
        )
        if let speakerEmbedding {
            let canonicalSpeakerEmbedding = try Qwen3TTSVoiceClonePrompt.validateSpeakerEmbedding(
                speakerEmbedding,
                expectedDimension: talkerConfig.hiddenSize,
                allowOfficialVectorShape: true
            )
            let speakerEmbed = canonicalSpeakerEmbedding
                .asType(codecPrefixEmbed.dtype)
                .reshaped(1, 1, talkerConfig.hiddenSize)
            codecPrefixEmbed = concatenated([codecPrefixEmbed, speakerEmbed, codecPrefixSuffix], axis: 1)
        } else {
            codecPrefixEmbed = concatenated([codecPrefixEmbed, codecPrefixSuffix], axis: 1)
        }

        // Role embedding
        let roleEmbed = talker.textProjection(try talker.embedText(targetIds[0..., 0 ..< 3]))

        // Build prefix: text side overlayed with codec prefix
        let padCount = codecPrefixEmbed.dim(1) - 2
        let padEmbeds = broadcast(ttsPadEmbed, to: [1, padCount, ttsPadEmbed.dim(-1)])
        var combinedPrefix = concatenated([padEmbeds, ttsBosEmbed], axis: 1)
        combinedPrefix = combinedPrefix + codecPrefixEmbed[0..., 0 ..< (codecPrefixEmbed.dim(1) - 1), 0...]

        // Full input embedding
        let inputEmbeds = concatenated([roleEmbed, combinedPrefix, iclInputEmbed], axis: 1)

        return (inputEmbeds, trailingTextHidden, ttsPadEmbed, refCodes, targetTokenCount)
    }

    func prepareVoiceCloneInputs(
        text: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt,
        language: String
    ) throws -> (
        inputEmbeds: MLXArray,
        trailingTextHidden: MLXArray,
        ttsPadEmbed: MLXArray,
        refCodes: MLXArray?,
        targetTokenCount: Int
    ) {
        if voiceClonePrompt.iclMode {
            guard let refCodes = voiceClonePrompt.refCodes,
                  let refText = voiceClonePrompt.refText,
                  !refText.isEmpty else {
                throw AudioGenerationError.modelNotInitialized(
                    "Qwen3 clone prompt in ICL mode is missing required reference codes or transcript."
                )
            }
            let prepared = try prepareICLGenerationInputs(
                text: text,
                refCodes: refCodes,
                refText: refText,
                speakerEmbedding: voiceClonePrompt.speakerEmbedding,
                language: language
            )
            return (
                prepared.inputEmbeds,
                prepared.trailingTextHidden,
                prepared.ttsPadEmbed,
                prepared.refCodes,
                prepared.targetTokenCount
            )
        }

        let prepared = try prepareVoiceCloneFromSpeakerOnly(
            text: text,
            language: language,
            voiceClonePrompt: voiceClonePrompt
        )
        return (
            prepared.inputEmbeds,
            prepared.trailingTextHidden,
            prepared.ttsPadEmbed,
            nil,
            prepared.targetTokenCount
        )
    }

    private func prepareVoiceCloneFromSpeakerOnly(
        text: String,
        language: String,
        voiceClonePrompt: Qwen3TTSVoiceClonePrompt
    ) throws -> (
        inputEmbeds: MLXArray,
        trailingTextHidden: MLXArray,
        ttsPadEmbed: MLXArray,
        prefixCacheHit: Bool,
        targetTokenCount: Int
    ) {
        guard let speakerEmbedding = voiceClonePrompt.speakerEmbedding else {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen3 speaker-only clone prompt is missing a speaker embedding."
            )
        }

        let (prefix, cacheHit) = try buildSpeakerConditioningPrefix(
            language: language,
            speakerEmbedding: speakerEmbedding
        )
        let prepared = try prepareInputs(text: text, prefix: prefix)
        return (
            prepared.inputEmbeds,
            prepared.trailingTextHidden,
            prepared.ttsPadEmbed,
            cacheHit,
            prepared.targetTokenCount
        )
    }

    private func buildSpeakerConditioningPrefix(
        language: String,
        speakerEmbedding: MLXArray
    ) throws -> (CachedConditioningPrefix, Bool) {
        guard let tokenizer, let talkerConfig = config.talkerConfig else {
            throw AudioGenerationError.modelNotInitialized("Tokenizer/config not loaded")
        }

        let ttsTokens = MLXArray(
            [Int32(config.ttsBosTokenId), Int32(config.ttsEosTokenId), Int32(config.ttsPadTokenId)]
        ).reshaped(1, 3)
        let ttsEmbeds = talker.textProjection(try talker.embedText(ttsTokens))
        let ttsBosEmbed = ttsEmbeds[0..., 0 ..< 1, 0...]
        let ttsEosEmbed = ttsEmbeds[0..., 1 ..< 2, 0...]
        let ttsPadEmbed = ttsEmbeds[0..., 2 ..< 3, 0...]

        let languageId = resolvedLanguageIdentifier(language: language)
        let codecPrefill: [Int32] = if let languageId {
            [
                Int32(talkerConfig.codecThinkId),
                Int32(talkerConfig.codecThinkBosId),
                Int32(languageId),
                Int32(talkerConfig.codecThinkEosId),
            ]
        } else {
            [
                Int32(talkerConfig.codecNothinkId),
                Int32(talkerConfig.codecThinkBosId),
                Int32(talkerConfig.codecThinkEosId),
            ]
        }

        var codecPrefixEmbed = talker.getInputEmbeddings()(MLXArray(codecPrefill).reshaped(1, -1))
        let codecPrefixSuffix = talker.getInputEmbeddings()(
            MLXArray([Int32(talkerConfig.codecPadId), Int32(talkerConfig.codecBosId)]).reshaped(1, 2)
        )
        let canonicalSpeakerEmbedding = try Qwen3TTSVoiceClonePrompt.validateSpeakerEmbedding(
            speakerEmbedding,
            expectedDimension: talkerConfig.hiddenSize,
            allowOfficialVectorShape: true
        )
        let speakerSlot = canonicalSpeakerEmbedding
            .asType(codecPrefixEmbed.dtype)
            .reshaped(1, 1, talkerConfig.hiddenSize)
        codecPrefixEmbed = concatenated([codecPrefixEmbed, speakerSlot, codecPrefixSuffix], axis: 1)

        let assistantPrefix = "<|im_start|>assistant\n"
        let assistantTokens = tokenizer.encode(text: assistantPrefix)
        guard assistantTokens.count == 3 else {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen assistant prefix tokenization no longer matches the pinned three-token contract."
            )
        }
        let assistantPrefixIDs = MLXArray(assistantTokens.map(Int32.init)).reshaped(1, -1)
        let roleEmbed = talker.textProjection(try talker.embedText(assistantPrefixIDs))

        let padCount = codecPrefixEmbed.dim(1) - 2
        let padEmbeds = broadcast(ttsPadEmbed, to: [1, padCount, ttsPadEmbed.dim(-1)])
        var combinedEmbed = concatenated([padEmbeds, ttsBosEmbed], axis: 1)
        combinedEmbed = combinedEmbed + codecPrefixEmbed[0..., ..<(-1), 0...]

        let inputPrefixEmbeds = concatenated([roleEmbed, combinedEmbed], axis: 1)
        let codecLastEmbed = codecPrefixEmbed[0..., (-1)..., 0...]
        let prefix = CachedConditioningPrefix(
            inputPrefixEmbeds: inputPrefixEmbeds,
            codecLastEmbed: codecLastEmbed,
            ttsEosEmbed: ttsEosEmbed,
            ttsPadEmbed: ttsPadEmbed
        )
        return (prefix, false)
    }

    func extractSpeakerEmbedding(_ refAudio: MLXArray) throws -> MLXArray? {
        guard let speakerEncoder else { return nil }

        let rawAudio = try Qwen3TTSReferenceAudio.canonicalMonoBatch(refAudio)

        guard speakerEncoder.config.sampleRate == Qwen3TTSSpeakerMelFrontend.sampleRate,
              speakerEncoder.config.melDim == Qwen3TTSSpeakerMelFrontend.melBinCount else {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen speaker encoder configuration does not match the owned speaker-feature frontend."
            )
        }
        if let talkerConfig = config.talkerConfig,
           speakerEncoder.config.encDim != talkerConfig.hiddenSize {
            throw AudioGenerationError.modelNotInitialized(
                "Qwen speaker embedding dimension does not match the talker hidden size."
            )
        }

        let features = try Qwen3TTSSpeakerMelFrontend()(rawAudio)
        let embedding = speakerEncoder(features).asType(.float32)
        return try Qwen3TTSVoiceClonePrompt.validateSpeakerEmbedding(
            embedding,
            expectedDimension: speakerEncoder.config.encDim,
            allowOfficialVectorShape: true
        )
    }

    func prepareGenerationInputs(
        text: String,
        language: String,
        instruct: String?
    ) throws -> (MLXArray, MLXArray, MLXArray) {
        guard let tokenizer, let talkerConfig = config.talkerConfig else {
            throw AudioGenerationError.modelNotInitialized("Tokenizer/config not loaded")
        }

        // Tokenize text with ChatML template
        let text = Qwen3ChatTemplateText.preparedForTemplate(text)
        let chatText = "<|im_start|>assistant\n\(text)<|im_end|>\n<|im_start|>assistant\n"
        let inputIds = MLXArray(tokenizer.encode(text: chatText).map { Int32($0) }).reshaped(1, -1)

        // Get text embeddings
        let textEmbed = talker.textProjection(try talker.embedText(inputIds))
        try Self.validateChatTemplateTokenCount(textEmbed.dim(1))

        // TTS special tokens
        let ttsTokens = MLXArray(
            [Int32(config.ttsBosTokenId), Int32(config.ttsEosTokenId), Int32(config.ttsPadTokenId)]
        ).reshaped(1, 3)
        let ttsEmbeds = talker.textProjection(try talker.embedText(ttsTokens))
        let ttsBosEmbed = ttsEmbeds[0..., 0 ..< 1, 0...]
        let ttsEosEmbed = ttsEmbeds[0..., 1 ..< 2, 0...]
        let ttsPadEmbed = ttsEmbeds[0..., 2 ..< 3, 0...]

        // Language ID
        var languageId: Int?
        if language.lowercased() != "auto", let langMap = talkerConfig.codecLanguageId {
            languageId = langMap[language.lowercased()]
        }

        // Build codec prefix
        let codecPrefill: [Int32] = if let langId = languageId {
            [
                Int32(talkerConfig.codecThinkId),
                Int32(talkerConfig.codecThinkBosId),
                Int32(langId),
                Int32(talkerConfig.codecThinkEosId)
            ]
        } else {
            [
                Int32(talkerConfig.codecNothinkId),
                Int32(talkerConfig.codecThinkBosId),
                Int32(talkerConfig.codecThinkEosId)
            ]
        }

        var codecEmbed = talker.getInputEmbeddings()(MLXArray(codecPrefill).reshaped(1, -1))
        let codecEmbedSuffix = talker.getInputEmbeddings()(
            MLXArray([Int32(talkerConfig.codecPadId), Int32(talkerConfig.codecBosId)]).reshaped(1, 2)
        )
        codecEmbed = concatenated([codecEmbed, codecEmbedSuffix], axis: 1)

        // Instruct embedding
        var instructEmbed: MLXArray?
        if let instruct = instruct.map(Qwen3ChatTemplateText.preparedForTemplate), !instruct.isEmpty {
            let instructText = "<|im_start|>user\n\(instruct)<|im_end|>\n"
            let instructIds = MLXArray(tokenizer.encode(text: instructText).map { Int32($0) }).reshaped(1, -1)
            instructEmbed = talker.textProjection(try talker.embedText(instructIds))
        }

        // Role embedding (first 3 tokens: <|im_start|>assistant\n)
        let roleEmbed = textEmbed[0..., ..<3, 0...]

        // Build pad/bos prefix
        let padCount = codecEmbed.dim(1) - 2
        let padEmbeds = broadcast(ttsPadEmbed, to: [1, padCount, ttsPadEmbed.dim(-1)])
        var combinedEmbed = concatenated([padEmbeds, ttsBosEmbed], axis: 1)
        combinedEmbed = combinedEmbed + codecEmbed[0..., ..<(-1), 0...]

        // Full input embedding
        var inputEmbeds: MLXArray = if let instructEmbed {
            concatenated([instructEmbed, roleEmbed, combinedEmbed], axis: 1)
        } else {
            concatenated([roleEmbed, combinedEmbed], axis: 1)
        }

        // Add first text token (index 3) + last codec embed
        let firstTextEmbed = textEmbed[0..., 3 ..< 4, 0...] + codecEmbed[0..., (-1)..., 0...]
        inputEmbeds = concatenated([inputEmbeds, firstTextEmbed], axis: 1)

        // Trailing text (tokens 4 to -5, plus EOS)
        let trailingTextHidden = concatenated(
            [textEmbed[0..., 4 ..< (textEmbed.dim(1) - 5), 0...], ttsEosEmbed],
            axis: 1
        )

        return (inputEmbeds, trailingTextHidden, ttsPadEmbed)
    }

    /// The fewest chat-template tokens a script can produce: the
    /// `<|im_start|>assistant\n` role (3), one text token, and the
    /// `<|im_end|>\n<|im_start|>assistant\n` tail (5). Every slice of the text
    /// embedding is valid from here, so a one-token script such as "Hi"
    /// generates (DA-04 E4-01).
    static let minimumChatTemplateTokenCount = 3 + 1 + 5

    /// Refuses a script with no text token. The message names only the count,
    /// never the script, and no mode.
    static func validateChatTemplateTokenCount(_ tokenCount: Int) throws {
        guard tokenCount >= minimumChatTemplateTokenCount else {
            throw AudioGenerationError.invalidInput(
                "The script has no text to speak: it produced \(tokenCount) chat tokens, " +
                "and at least \(minimumChatTemplateTokenCount) are needed."
            )
        }
    }
}

/// User text in the Qwen3-TTS ChatML template (P05-02).
///
/// The script, the delivery instruction, the Voice Design brief and the clone
/// reference transcript are interpolated into `<|im_start|>…<|im_end|>` turns,
/// and the tokenizer maps every added-token literal in that text straight to
/// the token's ID. A `<tts_text_eod>` typed or pasted into a script became the
/// end-of-text embedding the prompt itself uses, and `<|im_end|>` closed the
/// turn early; on a live run such literals were spoken as noise. Every literal
/// of the model's added-token families is removed before templating, so user
/// text reaches the model only as ordinary text tokens. Text without `<` is
/// returned unchanged.
enum Qwen3ChatTemplateText {
    /// `<|…|>` (`<|im_start|>`, `<|im_end|>`, `<|endoftext|>`, the vision, box,
    /// quad, object-ref, audio and fill-in-the-middle markers), `<tts_…>`
    /// (`<tts_pad>`, `<tts_text_bos>`, `<tts_text_eod>`,
    /// `<tts_text_bos_single>`) and the `<think>`, `<tool_call>` and
    /// `<tool_response>` tags with their closing forms.
    static let controlTokenPattern =
        #"<\|[A-Za-z0-9_]+\|>|<tts_[A-Za-z0-9_]+>|</?(?:think|tool_call|tool_response)>"#

    static func neutralizingControlTokens(_ text: String) -> String {
        guard text.contains("<") else { return text }
        return text.replacingOccurrences(
            of: controlTokenPattern,
            with: " ",
            options: .regularExpression
        )
    }

    /// User text as the template takes it: composed to NFC, then cleared of
    /// control-token literals. The reference tokenizer normalizes to NFC
    /// itself (`Qwen2Tokenizer` installs `normalizers.NFC()`), and this
    /// tokenizer is built from `vocab.json` and `merges.txt` with no
    /// normalizer, so decomposed text (an accent typed as a letter and a
    /// combining mark, Hangul as jamo) used to reach the model as byte
    /// sequences the reference never produces (A-18). Text already in NFC,
    /// which is nearly all text, is returned as it was.
    static func preparedForTemplate(_ text: String) -> String {
        neutralizingControlTokens(composed(text))
    }

    static func composed(_ text: String) -> String {
        // ASCII is its own NFC form; skip the Foundation call on the common path.
        text.utf8.allSatisfy { $0 < 0x80 } ? text : text.precomposedStringWithCanonicalMapping
    }
}
