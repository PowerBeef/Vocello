// swift-tools-version:6.1
import PackageDescription

// Vocello-specialized fork: Qwen3-TTS only (2026-06-09).
// The upstream multi-model targets (STT/STS/VAD/LID/G2P/UI/Tools and the
// non-Mimi codec families) were deleted — restorable from upstream
// (Blaizzy/mlx-audio-swift @ fcbd04d) or git history. MLXAudioCodecs remains
// as the home of the Mimi transformer/conv/quantization primitives the
// Qwen3 speech tokenizer builds on.
let package = Package(
    name: "MLXAudio",
    platforms: [.macOS(.v14), .iOS(.v17)],
    products: [
        // Stable first-party boundary consumed by Vocello product targets. The
        // MLXAudio* products remain available for source compatibility and as
        // implementation modules behind this facade.
        .library(name: "VocelloQwen3Core", targets: ["VocelloQwen3Core"]),

        // Core foundation library
        .library(name: "MLXAudioCore", targets: ["MLXAudioCore"]),

        // Audio codec primitives (Mimi subset used by Qwen3-TTS)
        .library(name: "MLXAudioCodecs", targets: ["MLXAudioCodecs"]),

        // Text-to-Speech (Qwen3-TTS)
        .library(name: "MLXAudioTTS", targets: ["MLXAudioTTS"]),
    ],
    dependencies: [
        .package(url: "https://github.com/ml-explore/mlx-swift.git", exact: "0.31.6"),
        .package(url: "https://github.com/ml-explore/mlx-swift-lm.git", exact: "3.31.4"),
        .package(url: "https://github.com/huggingface/swift-huggingface.git", exact: "0.9.0"),
        // mlx-swift-lm 3.x dropped its swift-transformers dependency; the app now brings the
        // concrete Hub/Tokenizers implementation. Pinned to the exact version the 2.30.6 graph
        // resolved so tokenizer behavior stays identical across the pin-bump A/B.
        .package(url: "https://github.com/huggingface/swift-transformers.git", exact: "1.3.3")
    ],
    targets: [
        // MARK: - VocelloQwen3Core
        .target(
            name: "VocelloQwen3Core",
            dependencies: [
                "MLXAudioCore",
                "MLXAudioTTS",
                .product(name: "MLX", package: "mlx-swift"),
                .product(name: "MLXLMCommon", package: "mlx-swift-lm"),
                .product(name: "HuggingFace", package: "swift-huggingface"),
            ],
            path: "Sources/VocelloQwen3Core"
        ),

        // MARK: - MLXAudioCore
        .target(
            name: "MLXAudioCore",
            dependencies: [
                .product(name: "MLX", package: "mlx-swift"),
                .product(name: "MLXRandom", package: "mlx-swift"),
                .product(name: "MLXNN", package: "mlx-swift"),
                .product(name: "HuggingFace", package: "swift-huggingface"),
            ],
            path: "Sources/MLXAudioCore",
            swiftSettings: [
                .unsafeFlags(["-Xfrontend", "-warn-concurrency"], .when(configuration: .debug))
            ]
        ),

        // MARK: - MLXAudioCodecs
        .target(
            name: "MLXAudioCodecs",
            dependencies: [
                "MLXAudioCore",
                .product(name: "MLX", package: "mlx-swift"),
                .product(name: "MLXFast", package: "mlx-swift"),
                .product(name: "MLXNN", package: "mlx-swift"),
                .product(name: "MLXLMCommon", package: "mlx-swift-lm"),
                .product(name: "HuggingFace", package: "swift-huggingface"),
            ],
            path: "Sources/MLXAudioCodecs"
        ),

        // MARK: - MLXAudioTTS
        .target(
            name: "MLXAudioTTS",
            dependencies: [
                "MLXAudioCore",
                "MLXAudioCodecs",
                .product(name: "MLX", package: "mlx-swift"),
                .product(name: "MLXFast", package: "mlx-swift"),
                .product(name: "MLXNN", package: "mlx-swift"),
                .product(name: "MLXLMCommon", package: "mlx-swift-lm"),
                .product(name: "HuggingFace", package: "swift-huggingface"),
                .product(name: "Transformers", package: "swift-transformers"),
            ],
            path: "Sources/MLXAudioTTS"
        ),

        // Curated deterministic coverage for the owned Qwen3 runtime. Keep this
        // target narrow; do not re-import upstream's broad multi-model test tree.
        .testTarget(
            name: "Qwen3RuntimeTests",
            dependencies: [
                "VocelloQwen3Core",
                "MLXAudioCore",
                "MLXAudioCodecs",
                "MLXAudioTTS",
                .product(name: "MLX", package: "mlx-swift"),
                .product(name: "MLXLMCommon", package: "mlx-swift-lm"),
            ],
            path: "Tests/Qwen3RuntimeTests"
        ),
    ]
)
