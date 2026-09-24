# Third-party notices

## mlx-audio-swift

Vocello Qwen3 Core contains source derived from `mlx-audio-swift` by Prince Canuma and contributors.
That source is licensed under the MIT License. The complete license text is preserved in
[`LICENSE`](LICENSE), including its copyright notice and warranty disclaimer.

## AudioSeal

The `MLXAudioMark` target is a port to MLX Swift of the AudioSeal watermark generator
(`audioseal_wm_16bits`) from [`facebookresearch/audioseal`](https://github.com/facebookresearch/audioseal)
by Meta Platforms, Inc. and affiliates. The generator weights that Vocello uses for audio marking
(`marking/audioseal_wm16_generator_fp16.safetensors`) are converted from the published AudioSeal
checkpoint to fp16; they download with each model package and are not included in this source tree.
AudioSeal's code and weights are licensed under the MIT License:

```text
MIT License

Copyright (c) Meta Platforms, Inc. and affiliates.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Package dependencies

This source package references MLX Swift, MLX Swift LM, Swift Hugging Face and Swift Transformers as
external SwiftPM dependencies (exact pins in `Package.swift`). Their source is not copied into this directory. Their licenses and notices are
provided by their respective upstream distributions and resolved package checkouts.

## Models

Qwen3-TTS model weights are downloaded separately and are not distributed in this source tree.
Model repository identity, immutable revisions, and required artifacts are governed by the root
[`qwenvoice_contract.json`](../../Sources/Resources/qwenvoice_contract.json).
