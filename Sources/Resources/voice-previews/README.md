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

For each speaker, generate one sample via the macOS Vocello.app (Debug
build) in **Built-in Voice** mode (internal mode id `custom`):

| Speaker | Mode | Delivery | Prompt |
|---|---|---|---|
| aiden, ryan | Custom | Neutral | `Hello, this is a sample of my voice.` |
| vivian, serena, uncle_fu, dylan, eric | Custom | Neutral | `你好，这是我的声音预览样本。` |
| ono_anna | Custom | Neutral | `こんにちは、これは私の声のプレビューサンプルです。` |
| sohee | Custom | Neutral | `안녕하세요, 이것은 제 목소리 미리보기 샘플입니다。` |

After each generation, find the WAV in
`~/Library/Application Support/QwenVoice-Debug/outputs/` (Debug builds)
or via the inline player's Save / right-click context menu, then rename
and copy:

```bash
cp ~/.../outputs/{generated}.wav \
   Sources/Resources/voice-previews/aiden.wav
```

XcodeGen's `buildPhase: resources` rule in `project.yml` for the
`VocelloiOS` target's `voice-previews` path picks the WAVs up
automatically on the next `scripts/regenerate_project.sh`.

When the WAVs land, the voice picker's per-row play button will Just Work.
Until then, taps no-op (the player logs a Debug warning).
