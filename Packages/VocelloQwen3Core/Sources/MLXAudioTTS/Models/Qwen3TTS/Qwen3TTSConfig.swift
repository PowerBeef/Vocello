import Foundation
import MLXLMCommon

private enum StringOrBool: Codable, Sendable {
    case string(String)
    case bool(Bool)

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let stringValue = try? container.decode(String.self) {
            self = .string(stringValue)
            return
        }
        if let boolValue = try? container.decode(Bool.self) {
            self = .bool(boolValue)
            return
        }
        throw DecodingError.typeMismatch(
            StringOrBool.self,
            DecodingError.Context(
                codingPath: decoder.codingPath,
                debugDescription: "Expected a string or bool value."
            )
        )
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        }
    }

    var stringValue: String? {
        switch self {
        case .string(let value):
            return value
        case .bool:
            return nil
        }
    }
}

// MARK: - Code Predictor Config

public struct Qwen3TTSTalkerCodePredictorConfig: Codable, Sendable {
    var vocabSize: Int
    var hiddenSize: Int
    var intermediateSize: Int
    var numHiddenLayers: Int
    var numAttentionHeads: Int
    var numKeyValueHeads: Int
    var headDim: Int
    var hiddenAct: String
    var maxPositionEmbeddings: Int
    var rmsNormEps: Float
    var ropeTheta: Float
    var ropeScaling: [String: StringOrNumber]?
    var attentionBias: Bool
    var slidingWindow: Int?
    var layerTypes: [String]?
    var attentionDropout: Float
    var numCodeGroups: Int

    enum CodingKeys: String, CodingKey {
        case vocabSize = "vocab_size"
        case hiddenSize = "hidden_size"
        case intermediateSize = "intermediate_size"
        case numHiddenLayers = "num_hidden_layers"
        case numAttentionHeads = "num_attention_heads"
        case numKeyValueHeads = "num_key_value_heads"
        case headDim = "head_dim"
        case hiddenAct = "hidden_act"
        case maxPositionEmbeddings = "max_position_embeddings"
        case rmsNormEps = "rms_norm_eps"
        case ropeTheta = "rope_theta"
        case ropeScaling = "rope_scaling"
        case attentionBias = "attention_bias"
        case slidingWindow = "sliding_window"
        case layerTypes = "layer_types"
        case attentionDropout = "attention_dropout"
        case numCodeGroups = "num_code_groups"
    }

    public init(from decoder: Swift.Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        vocabSize = try c.decodeIfPresent(Int.self, forKey: .vocabSize) ?? 2048
        hiddenSize = try c.decodeIfPresent(Int.self, forKey: .hiddenSize) ?? 1024
        intermediateSize = try c.decodeIfPresent(Int.self, forKey: .intermediateSize) ?? 3072
        numHiddenLayers = try c.decodeIfPresent(Int.self, forKey: .numHiddenLayers) ?? 5
        numAttentionHeads = try c.decodeIfPresent(Int.self, forKey: .numAttentionHeads) ?? 16
        numKeyValueHeads = try c.decodeIfPresent(Int.self, forKey: .numKeyValueHeads) ?? 8
        headDim = try c.decodeIfPresent(Int.self, forKey: .headDim) ?? 128
        hiddenAct = try c.decodeIfPresent(String.self, forKey: .hiddenAct) ?? "silu"
        maxPositionEmbeddings = try c.decodeIfPresent(Int.self, forKey: .maxPositionEmbeddings) ?? 65536
        rmsNormEps = try c.decodeIfPresent(Float.self, forKey: .rmsNormEps) ?? 1e-6
        ropeTheta = try c.decodeIfPresent(Float.self, forKey: .ropeTheta) ?? 1_000_000
        ropeScaling = try c.decodeIfPresent([String: StringOrNumber].self, forKey: .ropeScaling)
        attentionBias = try c.decodeIfPresent(Bool.self, forKey: .attentionBias) ?? false
        slidingWindow = try c.decodeIfPresent(Int.self, forKey: .slidingWindow)
        layerTypes = try c.decodeIfPresent([String].self, forKey: .layerTypes)
        attentionDropout = try c.decodeIfPresent(Float.self, forKey: .attentionDropout) ?? 0
        numCodeGroups = try c.decodeIfPresent(Int.self, forKey: .numCodeGroups) ?? 16
    }
}

// MARK: - Speaker Encoder Config

public struct Qwen3TTSSpeakerEncoderConfig: Codable, Sendable {
    var melDim: Int
    var encDim: Int
    var encChannels: [Int]
    var encKernelSizes: [Int]
    var encDilations: [Int]
    var encAttentionChannels: Int
    var encRes2netScale: Int
    var encSeChannels: Int
    var sampleRate: Int

    enum CodingKeys: String, CodingKey {
        case melDim = "mel_dim"
        case encDim = "enc_dim"
        case encChannels = "enc_channels"
        case encKernelSizes = "enc_kernel_sizes"
        case encDilations = "enc_dilations"
        case encAttentionChannels = "enc_attention_channels"
        case encRes2netScale = "enc_res2net_scale"
        case encSeChannels = "enc_se_channels"
        case sampleRate = "sample_rate"
    }

    public init(from decoder: Swift.Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        melDim = try c.decodeIfPresent(Int.self, forKey: .melDim) ?? 128
        encDim = try c.decodeIfPresent(Int.self, forKey: .encDim) ?? 1024
        encChannels = try c.decodeIfPresent([Int].self, forKey: .encChannels) ?? [512, 512, 512, 512, 1536]
        encKernelSizes = try c.decodeIfPresent([Int].self, forKey: .encKernelSizes) ?? [5, 3, 3, 3, 1]
        encDilations = try c.decodeIfPresent([Int].self, forKey: .encDilations) ?? [1, 2, 3, 4, 1]
        encAttentionChannels = try c.decodeIfPresent(Int.self, forKey: .encAttentionChannels) ?? 128
        encRes2netScale = try c.decodeIfPresent(Int.self, forKey: .encRes2netScale) ?? 8
        encSeChannels = try c.decodeIfPresent(Int.self, forKey: .encSeChannels) ?? 128
        sampleRate = try c.decodeIfPresent(Int.self, forKey: .sampleRate) ?? 24000
    }

    public init() {
        melDim = 128
        encDim = 1024
        encChannels = [512, 512, 512, 512, 1536]
        encKernelSizes = [5, 3, 3, 3, 1]
        encDilations = [1, 2, 3, 4, 1]
        encAttentionChannels = 128
        encRes2netScale = 8
        encSeChannels = 128
        sampleRate = 24000
    }
}

// MARK: - Talker Config

public struct Qwen3TTSTalkerConfig: Codable, Sendable {
    var codePredictorConfig: Qwen3TTSTalkerCodePredictorConfig?
    var vocabSize: Int
    var hiddenSize: Int
    var intermediateSize: Int
    var numHiddenLayers: Int
    var numAttentionHeads: Int
    var numKeyValueHeads: Int
    var headDim: Int
    var hiddenAct: String
    var maxPositionEmbeddings: Int
    var rmsNormEps: Float
    var ropeTheta: Float
    var ropeScaling: [String: StringOrNumber]?
    var attentionBias: Bool
    var slidingWindow: Int?
    var attentionDropout: Float
    var numCodeGroups: Int
    var textHiddenSize: Int
    var textVocabSize: Int
    var codecEosTokenId: Int
    var codecThinkId: Int
    var codecNothinkId: Int
    var codecThinkBosId: Int
    var codecThinkEosId: Int
    var codecPadId: Int
    var codecBosId: Int
    var codecLanguageId: [String: Int]?
    var spkId: [String: [Int]]?
    var spkIsDialect: [String: String]?

    enum CodingKeys: String, CodingKey {
        case codePredictorConfig = "code_predictor_config"
        case vocabSize = "vocab_size"
        case hiddenSize = "hidden_size"
        case intermediateSize = "intermediate_size"
        case numHiddenLayers = "num_hidden_layers"
        case numAttentionHeads = "num_attention_heads"
        case numKeyValueHeads = "num_key_value_heads"
        case headDim = "head_dim"
        case hiddenAct = "hidden_act"
        case maxPositionEmbeddings = "max_position_embeddings"
        case rmsNormEps = "rms_norm_eps"
        case ropeTheta = "rope_theta"
        case ropeScaling = "rope_scaling"
        case attentionBias = "attention_bias"
        case slidingWindow = "sliding_window"
        case attentionDropout = "attention_dropout"
        case numCodeGroups = "num_code_groups"
        case textHiddenSize = "text_hidden_size"
        case textVocabSize = "text_vocab_size"
        case codecEosTokenId = "codec_eos_token_id"
        case codecThinkId = "codec_think_id"
        case codecNothinkId = "codec_nothink_id"
        case codecThinkBosId = "codec_think_bos_id"
        case codecThinkEosId = "codec_think_eos_id"
        case codecPadId = "codec_pad_id"
        case codecBosId = "codec_bos_id"
        case codecLanguageId = "codec_language_id"
        case spkId = "spk_id"
        case spkIsDialect = "spk_is_dialect"
    }

    public init(from decoder: Swift.Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        codePredictorConfig = try c.decodeIfPresent(Qwen3TTSTalkerCodePredictorConfig.self, forKey: .codePredictorConfig)
        vocabSize = try c.decodeIfPresent(Int.self, forKey: .vocabSize) ?? 3072
        hiddenSize = try c.decodeIfPresent(Int.self, forKey: .hiddenSize) ?? 1024
        intermediateSize = try c.decodeIfPresent(Int.self, forKey: .intermediateSize) ?? 3072
        numHiddenLayers = try c.decodeIfPresent(Int.self, forKey: .numHiddenLayers) ?? 28
        numAttentionHeads = try c.decodeIfPresent(Int.self, forKey: .numAttentionHeads) ?? 16
        numKeyValueHeads = try c.decodeIfPresent(Int.self, forKey: .numKeyValueHeads) ?? 8
        headDim = try c.decodeIfPresent(Int.self, forKey: .headDim) ?? 128
        hiddenAct = try c.decodeIfPresent(String.self, forKey: .hiddenAct) ?? "silu"
        maxPositionEmbeddings = try c.decodeIfPresent(Int.self, forKey: .maxPositionEmbeddings) ?? 32768
        rmsNormEps = try c.decodeIfPresent(Float.self, forKey: .rmsNormEps) ?? 1e-6
        ropeTheta = try c.decodeIfPresent(Float.self, forKey: .ropeTheta) ?? 1_000_000
        ropeScaling = try c.decodeIfPresent([String: StringOrNumber].self, forKey: .ropeScaling)
        attentionBias = try c.decodeIfPresent(Bool.self, forKey: .attentionBias) ?? false
        slidingWindow = try c.decodeIfPresent(Int.self, forKey: .slidingWindow)
        attentionDropout = try c.decodeIfPresent(Float.self, forKey: .attentionDropout) ?? 0
        numCodeGroups = try c.decodeIfPresent(Int.self, forKey: .numCodeGroups) ?? 16
        textHiddenSize = try c.decodeIfPresent(Int.self, forKey: .textHiddenSize) ?? 2048
        textVocabSize = try c.decodeIfPresent(Int.self, forKey: .textVocabSize) ?? 151936
        codecEosTokenId = try c.decodeIfPresent(Int.self, forKey: .codecEosTokenId) ?? 2150
        codecThinkId = try c.decodeIfPresent(Int.self, forKey: .codecThinkId) ?? 2154
        codecNothinkId = try c.decodeIfPresent(Int.self, forKey: .codecNothinkId) ?? 2155
        codecThinkBosId = try c.decodeIfPresent(Int.self, forKey: .codecThinkBosId) ?? 2156
        codecThinkEosId = try c.decodeIfPresent(Int.self, forKey: .codecThinkEosId) ?? 2157
        codecPadId = try c.decodeIfPresent(Int.self, forKey: .codecPadId) ?? 2148
        codecBosId = try c.decodeIfPresent(Int.self, forKey: .codecBosId) ?? 2149
        codecLanguageId = try c.decodeIfPresent([String: Int].self, forKey: .codecLanguageId)
        do {
            spkId = try c.decodeIfPresent([String: [Int]].self, forKey: .spkId)
        } catch DecodingError.typeMismatch {
            let scalarSpeakerIDs = try c.decodeIfPresent([String: Int].self, forKey: .spkId)
            spkId = scalarSpeakerIDs?.mapValues { [$0] }
        }
        let dialectValues = try c.decodeIfPresent([String: StringOrBool].self, forKey: .spkIsDialect)
        spkIsDialect = dialectValues?.compactMapValues(\.stringValue)
    }

    var mropeSection: [Int]? {
        guard let scaling = ropeScaling,
              let value = scaling["mrope_section"] else { return nil }
        return value.asInts()
    }
}

// MARK: - Tokenizer Decoder Config

public struct Qwen3TTSTokenizerDecoderConfig: Codable, Sendable {
    var attentionBias: Bool
    var attentionDropout: Float
    var latentDim: Int
    var codebookDim: Int
    var codebookSize: Int
    var decoderDim: Int
    var hiddenAct: String
    var hiddenSize: Int
    var intermediateSize: Int
    var layerScaleInitialScale: Float
    var maxPositionEmbeddings: Int
    var headDim: Int
    var numAttentionHeads: Int
    var numHiddenLayers: Int
    var numKeyValueHeads: Int
    var numQuantizers: Int
    var numSemanticQuantizers: Int
    var rmsNormEps: Float
    var ropeTheta: Float
    var semanticCodebookSize: Int
    var slidingWindow: Int
    var upsampleRates: [Int]
    var upsamplingRatios: [Int]
    var vectorQuantizationHiddenDimension: Int

    enum CodingKeys: String, CodingKey {
        case attentionBias = "attention_bias"
        case attentionDropout = "attention_dropout"
        case latentDim = "latent_dim"
        case codebookDim = "codebook_dim"
        case codebookSize = "codebook_size"
        case decoderDim = "decoder_dim"
        case hiddenAct = "hidden_act"
        case hiddenSize = "hidden_size"
        case intermediateSize = "intermediate_size"
        case layerScaleInitialScale = "layer_scale_initial_scale"
        case maxPositionEmbeddings = "max_position_embeddings"
        case headDim = "head_dim"
        case numAttentionHeads = "num_attention_heads"
        case numHiddenLayers = "num_hidden_layers"
        case numKeyValueHeads = "num_key_value_heads"
        case numQuantizers = "num_quantizers"
        case numSemanticQuantizers = "num_semantic_quantizers"
        case rmsNormEps = "rms_norm_eps"
        case ropeTheta = "rope_theta"
        case semanticCodebookSize = "semantic_codebook_size"
        case slidingWindow = "sliding_window"
        case upsampleRates = "upsample_rates"
        case upsamplingRatios = "upsampling_ratios"
        case vectorQuantizationHiddenDimension = "vector_quantization_hidden_dimension"
    }

    public init(from decoder: Swift.Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        attentionBias = try c.decodeIfPresent(Bool.self, forKey: .attentionBias) ?? false
        attentionDropout = try c.decodeIfPresent(Float.self, forKey: .attentionDropout) ?? 0
        latentDim = try c.decodeIfPresent(Int.self, forKey: .latentDim) ?? 1024
        codebookDim = try c.decodeIfPresent(Int.self, forKey: .codebookDim) ?? 512
        codebookSize = try c.decodeIfPresent(Int.self, forKey: .codebookSize) ?? 2048
        decoderDim = try c.decodeIfPresent(Int.self, forKey: .decoderDim) ?? 1536
        hiddenAct = try c.decodeIfPresent(String.self, forKey: .hiddenAct) ?? "silu"
        hiddenSize = try c.decodeIfPresent(Int.self, forKey: .hiddenSize) ?? 512
        intermediateSize = try c.decodeIfPresent(Int.self, forKey: .intermediateSize) ?? 1024
        layerScaleInitialScale = try c.decodeIfPresent(Float.self, forKey: .layerScaleInitialScale) ?? 0.01
        maxPositionEmbeddings = try c.decodeIfPresent(Int.self, forKey: .maxPositionEmbeddings) ?? 8000
        headDim = try c.decodeIfPresent(Int.self, forKey: .headDim) ?? 64
        numAttentionHeads = try c.decodeIfPresent(Int.self, forKey: .numAttentionHeads) ?? 16
        numHiddenLayers = try c.decodeIfPresent(Int.self, forKey: .numHiddenLayers) ?? 8
        numKeyValueHeads = try c.decodeIfPresent(Int.self, forKey: .numKeyValueHeads) ?? 16
        numQuantizers = try c.decodeIfPresent(Int.self, forKey: .numQuantizers) ?? 16
        numSemanticQuantizers = try c.decodeIfPresent(Int.self, forKey: .numSemanticQuantizers) ?? 1
        rmsNormEps = try c.decodeIfPresent(Float.self, forKey: .rmsNormEps) ?? 1e-5
        ropeTheta = try c.decodeIfPresent(Float.self, forKey: .ropeTheta) ?? 10000
        semanticCodebookSize = try c.decodeIfPresent(Int.self, forKey: .semanticCodebookSize) ?? 4096
        slidingWindow = try c.decodeIfPresent(Int.self, forKey: .slidingWindow) ?? 72
        upsampleRates = try c.decodeIfPresent([Int].self, forKey: .upsampleRates) ?? [8, 5, 4, 3]
        upsamplingRatios = try c.decodeIfPresent([Int].self, forKey: .upsamplingRatios) ?? [2, 2]
        vectorQuantizationHiddenDimension = try c.decodeIfPresent(Int.self, forKey: .vectorQuantizationHiddenDimension) ?? 512
    }
}

// MARK: - Speech Tokenizer Encoder Config

public struct Qwen3TTSTokenizerEncoderConfig: Codable, Sendable {
    var frameRate: Float
    var attentionBias: Bool
    var attentionDropout: Float
    var audioChannels: Int
    var codebookDim: Int
    var codebookSize: Int
    var compress: Int
    var dilationGrowthRate: Int
    var headDim: Int
    var hiddenAct: String
    var hiddenSize: Int
    var intermediateSize: Int
    var kernelSize: Int
    var lastKernelSize: Int
    var layerScaleInitialScale: Float
    var maxPositionEmbeddings: Int
    var normEps: Float
    var numAttentionHeads: Int
    var numFilters: Int
    var numHiddenLayers: Int
    var numKeyValueHeads: Int
    var numQuantizers: Int
    var numResidualLayers: Int
    var numSemanticQuantizers: Int
    var residualKernelSize: Int
    var ropeTheta: Float
    var samplingRate: Int
    var slidingWindow: Int
    var upsamplingRatios: [Int]
    var useCausalConv: Bool
    var useConvShortcut: Bool
    var vectorQuantizationHiddenDimension: Int

    enum CodingKeys: String, CodingKey {
        case frameRate = "frame_rate"
        case attentionBias = "attention_bias"
        case attentionDropout = "attention_dropout"
        case audioChannels = "audio_channels"
        case codebookDim = "codebook_dim"
        case codebookSize = "codebook_size"
        case compress
        case dilationGrowthRate = "dilation_growth_rate"
        case headDim = "head_dim"
        case hiddenAct = "hidden_act"
        case hiddenSize = "hidden_size"
        case intermediateSize = "intermediate_size"
        case kernelSize = "kernel_size"
        case lastKernelSize = "last_kernel_size"
        case layerScaleInitialScale = "layer_scale_initial_scale"
        case maxPositionEmbeddings = "max_position_embeddings"
        case normEps = "norm_eps"
        case numAttentionHeads = "num_attention_heads"
        case numFilters = "num_filters"
        case numHiddenLayers = "num_hidden_layers"
        case numKeyValueHeads = "num_key_value_heads"
        case numQuantizers = "num_quantizers"
        case numResidualLayers = "num_residual_layers"
        case numSemanticQuantizers = "num_semantic_quantizers"
        case residualKernelSize = "residual_kernel_size"
        case ropeTheta = "rope_theta"
        case samplingRate = "sampling_rate"
        case slidingWindow = "sliding_window"
        case upsamplingRatios = "upsampling_ratios"
        case useCausalConv = "use_causal_conv"
        case useConvShortcut = "use_conv_shortcut"
        case vectorQuantizationHiddenDimension = "vector_quantization_hidden_dimension"
    }

    public init(from decoder: Swift.Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        frameRate = try c.decodeIfPresent(Float.self, forKey: .frameRate) ?? 12.5
        attentionBias = try c.decodeIfPresent(Bool.self, forKey: .attentionBias) ?? false
        attentionDropout = try c.decodeIfPresent(Float.self, forKey: .attentionDropout) ?? 0
        audioChannels = try c.decodeIfPresent(Int.self, forKey: .audioChannels) ?? 1
        codebookDim = try c.decodeIfPresent(Int.self, forKey: .codebookDim) ?? 256
        codebookSize = try c.decodeIfPresent(Int.self, forKey: .codebookSize) ?? 2048
        compress = try c.decodeIfPresent(Int.self, forKey: .compress) ?? 2
        dilationGrowthRate = try c.decodeIfPresent(Int.self, forKey: .dilationGrowthRate) ?? 2
        headDim = try c.decodeIfPresent(Int.self, forKey: .headDim) ?? 64
        hiddenAct = try c.decodeIfPresent(String.self, forKey: .hiddenAct) ?? "gelu"
        hiddenSize = try c.decodeIfPresent(Int.self, forKey: .hiddenSize) ?? 512
        intermediateSize = try c.decodeIfPresent(Int.self, forKey: .intermediateSize) ?? 2048
        kernelSize = try c.decodeIfPresent(Int.self, forKey: .kernelSize) ?? 7
        lastKernelSize = try c.decodeIfPresent(Int.self, forKey: .lastKernelSize) ?? 3
        layerScaleInitialScale = try c.decodeIfPresent(Float.self, forKey: .layerScaleInitialScale) ?? 0.01
        maxPositionEmbeddings = try c.decodeIfPresent(Int.self, forKey: .maxPositionEmbeddings) ?? 8000
        normEps = try c.decodeIfPresent(Float.self, forKey: .normEps) ?? 1e-5
        numAttentionHeads = try c.decodeIfPresent(Int.self, forKey: .numAttentionHeads) ?? 8
        numFilters = try c.decodeIfPresent(Int.self, forKey: .numFilters) ?? 64
        numHiddenLayers = try c.decodeIfPresent(Int.self, forKey: .numHiddenLayers) ?? 8
        numKeyValueHeads = try c.decodeIfPresent(Int.self, forKey: .numKeyValueHeads) ?? 8
        numQuantizers = try c.decodeIfPresent(Int.self, forKey: .numQuantizers) ?? 32
        numResidualLayers = try c.decodeIfPresent(Int.self, forKey: .numResidualLayers) ?? 1
        numSemanticQuantizers = try c.decodeIfPresent(Int.self, forKey: .numSemanticQuantizers) ?? 1
        residualKernelSize = try c.decodeIfPresent(Int.self, forKey: .residualKernelSize) ?? 3
        ropeTheta = try c.decodeIfPresent(Float.self, forKey: .ropeTheta) ?? 10000
        samplingRate = try c.decodeIfPresent(Int.self, forKey: .samplingRate) ?? 24000
        slidingWindow = try c.decodeIfPresent(Int.self, forKey: .slidingWindow) ?? 250
        upsamplingRatios = try c.decodeIfPresent([Int].self, forKey: .upsamplingRatios) ?? [8, 6, 5, 4]
        useCausalConv = try c.decodeIfPresent(Bool.self, forKey: .useCausalConv) ?? true
        useConvShortcut = try c.decodeIfPresent(Bool.self, forKey: .useConvShortcut) ?? false
        vectorQuantizationHiddenDimension = try c.decodeIfPresent(Int.self, forKey: .vectorQuantizationHiddenDimension) ?? 256
    }
}

// MARK: - Tokenizer Config (wrapper)

public struct Qwen3TTSTokenizerConfig: Codable, Sendable {
    var encoderConfig: Qwen3TTSTokenizerEncoderConfig?
    var decoderConfig: Qwen3TTSTokenizerDecoderConfig?
    var encoderValidNumQuantizers: Int
    var inputSampleRate: Int
    var outputSampleRate: Int
    var decodeUpsampleRate: Int
    var encodeDownsampleRate: Int

    enum CodingKeys: String, CodingKey {
        case encoderConfig = "encoder_config"
        case decoderConfig = "decoder_config"
        case encoderValidNumQuantizers = "encoder_valid_num_quantizers"
        case inputSampleRate = "input_sample_rate"
        case outputSampleRate = "output_sample_rate"
        case decodeUpsampleRate = "decode_upsample_rate"
        case encodeDownsampleRate = "encode_downsample_rate"
    }

    public init(from decoder: Swift.Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        encoderConfig = try c.decodeIfPresent(Qwen3TTSTokenizerEncoderConfig.self, forKey: .encoderConfig)
        decoderConfig = try c.decodeIfPresent(Qwen3TTSTokenizerDecoderConfig.self, forKey: .decoderConfig)
        encoderValidNumQuantizers = try c.decodeIfPresent(Int.self, forKey: .encoderValidNumQuantizers) ?? 16
        inputSampleRate = try c.decodeIfPresent(Int.self, forKey: .inputSampleRate) ?? 24000
        outputSampleRate = try c.decodeIfPresent(Int.self, forKey: .outputSampleRate) ?? 24000
        decodeUpsampleRate = try c.decodeIfPresent(Int.self, forKey: .decodeUpsampleRate) ?? 1920
        encodeDownsampleRate = try c.decodeIfPresent(Int.self, forKey: .encodeDownsampleRate) ?? 1920
    }

    func qwen3TTS12HzValidationFailure(includeEncoder: Bool) -> String? {
        guard inputSampleRate == 24_000, outputSampleRate == 24_000 else {
            return "expected 24 kHz speech tokenizer I/O, found input=\(inputSampleRate) output=\(outputSampleRate)"
        }
        guard decodeUpsampleRate == 1_920, encodeDownsampleRate == 1_920 else {
            return "expected 12.5 fps tokenizer stride (24_000 / 1_920), found decode=\(decodeUpsampleRate) encode=\(encodeDownsampleRate)"
        }
        guard encoderValidNumQuantizers == 16 else {
            return "expected encoder_valid_num_quantizers=16, found \(encoderValidNumQuantizers)"
        }
        guard let decoderConfig else {
            return "missing decoder_config"
        }
        guard decoderConfig.numQuantizers == 16 else {
            return "expected decoder num_quantizers=16, found \(decoderConfig.numQuantizers)"
        }
        guard decoderConfig.codebookSize == 2_048 else {
            return "expected decoder codebook_size=2048, found \(decoderConfig.codebookSize)"
        }
        guard decoderConfig.semanticCodebookSize == 4_096 else {
            return "expected decoder semantic_codebook_size=4096, found \(decoderConfig.semanticCodebookSize)"
        }
        if let encoderConfig {
            guard encoderConfig.numQuantizers == 32 else {
                return "expected encoder configured num_quantizers=32, found \(encoderConfig.numQuantizers)"
            }
            guard abs(encoderConfig.frameRate - 12.5) <= 0.001 else {
                return "expected encoder frame_rate=12.5, found \(encoderConfig.frameRate)"
            }
        } else if includeEncoder {
            return "includeEncoder=true but encoder_config is missing"
        }
        return nil
    }
}

// MARK: - Top-level Model Config

public struct Qwen3TTSModelConfig: Decodable, Sendable {
    var modelType: String
    var talkerConfig: Qwen3TTSTalkerConfig?
    var speakerEncoderConfig: Qwen3TTSSpeakerEncoderConfig
    var tokenizerConfig: Qwen3TTSTokenizerConfig?
    var quantization: BaseConfiguration.Quantization?
    var perLayerQuantization: BaseConfiguration.PerLayerQuantization?
    var tokenizerType: String
    var ttsModelSize: String
    var ttsModelType: String
    var imStartTokenId: Int
    var imEndTokenId: Int
    var ttsPadTokenId: Int
    var ttsBosTokenId: Int
    var ttsEosTokenId: Int
    var sampleRate: Int

    enum CodingKeys: String, CodingKey {
        case modelType = "model_type"
        case talkerConfig = "talker_config"
        case speakerEncoderConfig = "speaker_encoder_config"
        case tokenizerConfig = "tokenizer_config"
        case quantization
        case quantizationConfig = "quantization_config"
        case tokenizerType = "tokenizer_type"
        case ttsModelSize = "tts_model_size"
        case ttsModelType = "tts_model_type"
        case imStartTokenId = "im_start_token_id"
        case imEndTokenId = "im_end_token_id"
        case ttsPadTokenId = "tts_pad_token_id"
        case ttsBosTokenId = "tts_bos_token_id"
        case ttsEosTokenId = "tts_eos_token_id"
        case sampleRate = "sample_rate"
    }

    private struct DynamicCodingKey: CodingKey {
        let stringValue: String
        let intValue: Int?

        init(stringValue: String) {
            self.stringValue = stringValue
            self.intValue = Int(stringValue)
        }

        init(intValue: Int) {
            self.stringValue = "\(intValue)"
            self.intValue = intValue
        }
    }

    /// RF-68 (B1.2): explicitly decodes global and per-layer quantization from
    /// `"quantization"` or `"quantization_config"` without requiring top-level
    /// `"model_type"`. Any malformed per-layer entry, wrong value type, or
    /// boolean `true` throws `DecodingError` instead of silently dropping
    /// per-layer overrides and falling back to uniform quantization.
    private static func decodePerLayerQuantization(
        from container: KeyedDecodingContainer<CodingKeys>,
        forKey key: CodingKeys
    ) throws -> (quantization: BaseConfiguration.Quantization, perLayer: BaseConfiguration.PerLayerQuantization)? {
        guard container.contains(key) else {
            return nil
        }
        if try container.decodeNil(forKey: key) {
            return nil
        }
        let globalQuant = try container.decode(BaseConfiguration.Quantization.self, forKey: key)
        let nested = try container.nestedContainer(keyedBy: DynamicCodingKey.self, forKey: key)
        var overrides: [String: BaseConfiguration.QuantizationOption] = [:]
        for layerKey in nested.allKeys {
            switch layerKey.stringValue {
            case "group_size", "bits", "mode", "quant_method", "linear_class", "quantization_mode":
                continue
            default:
                if let flag = try? nested.decode(Bool.self, forKey: layerKey) {
                    guard !flag else {
                        throw DecodingError.dataCorruptedError(
                            forKey: layerKey,
                            in: nested,
                            debugDescription: "Per-layer quantization boolean override must be false (skip), not true"
                        )
                    }
                    overrides[layerKey.stringValue] = .skip
                } else {
                    let layerQuant = try nested.decode(BaseConfiguration.Quantization.self, forKey: layerKey)
                    overrides[layerKey.stringValue] = .quantize(layerQuant)
                }
            }
        }
        return (
            globalQuant,
            BaseConfiguration.PerLayerQuantization(
                quantization: globalQuant,
                perLayerQuantization: overrides
            )
        )
    }

    public init(from decoder: Swift.Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        modelType = try c.decodeIfPresent(String.self, forKey: .modelType) ?? "qwen3_tts"
        talkerConfig = try c.decodeIfPresent(Qwen3TTSTalkerConfig.self, forKey: .talkerConfig)
        speakerEncoderConfig = try c.decodeIfPresent(Qwen3TTSSpeakerEncoderConfig.self, forKey: .speakerEncoderConfig)
            ?? Qwen3TTSSpeakerEncoderConfig()
        tokenizerConfig = try c.decodeIfPresent(Qwen3TTSTokenizerConfig.self, forKey: .tokenizerConfig)
        let primaryQuant = try Self.decodePerLayerQuantization(from: c, forKey: .quantization)
        let altQuant = try Self.decodePerLayerQuantization(from: c, forKey: .quantizationConfig)
        let resolvedQuant = primaryQuant ?? altQuant
        quantization = resolvedQuant?.quantization
        perLayerQuantization = resolvedQuant?.perLayer
        tokenizerType = try c.decodeIfPresent(String.self, forKey: .tokenizerType) ?? "qwen3_tts_tokenizer_12hz"
        ttsModelSize = try c.decodeIfPresent(String.self, forKey: .ttsModelSize) ?? "0b6"
        ttsModelType = try c.decodeIfPresent(String.self, forKey: .ttsModelType) ?? "base"
        imStartTokenId = try c.decodeIfPresent(Int.self, forKey: .imStartTokenId) ?? 151644
        imEndTokenId = try c.decodeIfPresent(Int.self, forKey: .imEndTokenId) ?? 151645
        ttsPadTokenId = try c.decodeIfPresent(Int.self, forKey: .ttsPadTokenId) ?? 151671
        ttsBosTokenId = try c.decodeIfPresent(Int.self, forKey: .ttsBosTokenId) ?? 151672
        ttsEosTokenId = try c.decodeIfPresent(Int.self, forKey: .ttsEosTokenId) ?? 151673
        sampleRate = try c.decodeIfPresent(Int.self, forKey: .sampleRate) ?? 24000
    }
}

// MARK: - StringOrNumber helper for rope_scaling

// Note: StringOrNumber is already defined in MLXLMCommon (imported by the existing Qwen3 config).
// We re-use that type here for rope_scaling parsing.
// If needed, add: import MLXLMCommon
