# Voice preview samples

This directory holds short per-voice WAV samples played by the iOS
Voice Picker sheet when the user taps a row's preview button.
`IOSVoicePreviewPlayer` (`Sources/iOS/Sheets/IOSVoicePreviewPlayer.swift`)
loads `Bundle.main.url(forResource: voiceID, withExtension: "wav",
subdirectory: "voice-previews")`.

## Required files

One WAV per speaker id from `Sources/Resources/qwenvoice_contract.json`:

- `aiden.wav` — English, male
- `ryan.wav` — English, male
- `vivian.wav` — Chinese, female
- `serena.wav` — Chinese, female
- `uncle_fu.wav` — Chinese, male
- `dylan.wav` — Chinese, male
- `eric.wav` — Chinese, male
- `ono_anna.wav` — Japanese, female
- `sohee.wav` — Korean, female

`IOSVoicePreviewPlayer` matches on `voiceID`, so each speaker id listed in
the contract needs a same-named WAV in this directory.

## Format

- 24 kHz mono Int16 PCM (the engine's canonical format —
  `Qwen3TTSRuntimeProfile.canonicalSampleRate`)
- A few seconds of audio
- `afinfo {file}.wav` to verify before commit

## Generation recipe

These samples are already bundled. Replacing them is an explicit asset-generation/rights task,
not part of ordinary documentation or app builds. Use the repository XCUITest/macOS generation
route in **Built-in Voice** mode (internal mode id `custom`) with the approved catalog and recorded
seed/model identity. That route runs through `scripts/ui_test.sh`, which is consent-bound: it starts
only on the maintainer's explicit request (CLAUDE.md), never as part of ordinary documentation or
build work. The project has only a Release configuration; internal diagnostics are a
separate compile capability and runtime gate, not a Debug configuration.

Privacy-safe example scripts for an explicitly approved replacement:

| Speaker | Mode | Delivery | Prompt |
|---|---|---|---|
| aiden, ryan | Custom | Neutral | `Hello, this is a sample of my voice.` |
| vivian, serena, uncle_fu, dylan, eric | Custom | Neutral | `你好，这是我的声音预览样本。` |
| ono_anna | Custom | Neutral | `こんにちは、これは私の声のプレビューサンプルです。` |
| sohee | Custom | Neutral | `안녕하세요, 이것은 제 목소리 미리보기 샘플입니다。` |

Export the accepted WAV through the visible player or use the exact output recorded by the
authorized generator. Diagnostic outputs may use the isolated QwenVoice-Debug support root;
that directory name does not imply an Xcode Debug configuration. Validate PCM/QC and obtain the
required provenance/rights decision under `docs/reference/content-rights-review.md` before replacing
a bundled asset. Stage only the intended speaker file:

```bash
cp <verified-export.wav> \
   Sources/Resources/voice-previews/aiden.wav
```

XcodeGen's `buildPhase: resources` rule in `project.yml` for the
`VocelloiOS` target's `voice-previews` path picks the WAVs up
automatically on the next `scripts/regenerate_project.sh`.

Verify bundled resource membership and the real picker preview after any approved replacement.
Presence in the bundle is not a qualified content-rights decision.
