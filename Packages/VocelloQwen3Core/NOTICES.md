# Third-party notices

## mlx-audio-swift

Vocello Qwen3 Core contains source derived from `mlx-audio-swift` by Prince Canuma and contributors.
That source is licensed under the MIT License. The complete license text is preserved in
[`LICENSE`](LICENSE), including its copyright notice and warranty disclaimer.

## Package dependencies

This source package references MLX Swift, MLX Swift LM, Swift Hugging Face and Swift Transformers as
external SwiftPM dependencies (exact pins in `Package.swift`). Their source is not copied into this directory. Their licenses and notices are
provided by their respective upstream distributions and resolved package checkouts.

## Models

Qwen3-TTS model weights are downloaded separately and are not distributed in this source tree.
Model repository identity, immutable revisions, and required artifacts are governed by the root
[`qwenvoice_contract.json`](../../Sources/Resources/qwenvoice_contract.json).
