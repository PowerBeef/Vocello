---
status: active
owner: release-qa
reviewed: 2026-10-24
summary: Draft App Store listing for Vocello for iPhone 3.0.0 (en-US), awaiting the maintainer's review. It covers the subtitle, promotional text, description, keywords, What's New, URLs and the App Review notes. Nothing here is written to App Store Connect without a separate request.
sourceOfTruth:
  - config/public-product-facts.json
  - Sources/Resources/qwenvoice_contract.json
  - Sources/Resources/Localizable.xcstrings
  - Sources/Resources/qwenvoice_production_model_catalog.json
  - config/support-contact.json
  - docs/releases/v3.0.0.md
  - docs/reference/content-rights-review.md
---
# App Store listing: Vocello for iPhone 3.0.0 (en-US)

**Status: draft for the maintainer's review (ASR-05).** Writing any field to App Store Connect is a
separate, explicit request. After approval, `asc metadata` can apply the app-information and
version fields from canonical files (`asc metadata init`, then `validate`, `plan` and `apply`); the
App Review notes are entered with the review details.

The copy follows `website/PRODUCT.md`:
- it says local, not on-device;
- it uses sentence case;
- it has no em dashes, hype or first-person plural.

Every claim below traces to a source listed above. Counts in parentheses are characters against
Apple's limit.

## App information

| Field | Value | Notes |
|---|---|---|
| Name (30) | Vocello | Already set; unchanged (7). |
| Subtitle (30) | Local AI voice studio | 21. Alternatives: "Text to speech, made locally" (28), "Private AI text to speech" (25). |
| Privacy Policy URL | https://vocello.vercel.app/privacy | Already set; matches the runbook. |

## Version 3.0.0

### Promotional text (170)

```text
Hear your script in a built-in voice, a voice you describe, or one cloned from a clip you own. Every take is generated locally on your iPhone.
```

### Description (4000)

```text
Vocello turns your scripts into speech, and the work happens on your iPhone. There is no account, no cloud service and no usage meter: once a voice model is installed, every take is generated locally.

Three ways to make a voice

- Built-in Voice: nine speakers, with English, Chinese, Japanese and Korean natives. Pick a delivery such as Neutral, Calm, Whisper or Sad, or describe in your own words how a line should sound.
- Voice Design: describe a voice in plain words, such as "a warm, deep narrator with a subtle British accent," and Vocello shapes a new voice around it. Save the ones you like and use them in any script.
- Voice Cloning: record a short clip, or import a WAV, MP3, AIFF or M4A file, of a voice you own or have permission to use. Vocello follows that reference voice. Add the clip's words, or transcribe them locally, for the strongest clone.

Long scripts and many languages

- Keep typing past the single-take limit and your script becomes a long-form project. Regenerate any one segment without redoing the rest.
- Generate speech in English, Chinese, Japanese, Korean, German, French, Russian, Portuguese, Spanish and Italian. The interface is available in ten languages too, chosen separately from the speech language.

Keep, reuse and share

- Every take lands in History with its settings and the seed it used. Pin a seed to reproduce a take, or leave it unpinned for a fresh one each time.
- Saved Voices keep your designed and cloned voices ready for the next script.
- Share or save a take through the share sheet.

Private by design

- Vocello never sends your scripts, voice descriptions, recordings or generated audio anywhere. They leave your iPhone only when you export them, or in your own iPhone backups. Vocello collects no data.
- Every generated take carries an inaudible watermark and a provenance note that mark it as AI-generated. If you publish audio of a cloned real voice, disclose that it is AI-generated.

Before you start

- Vocello requires an iPhone 15 Pro or later. Each voice mode uses its own model of about 2 GB, downloaded once over Wi-Fi; keep at least 4.5 GB free while a model installs.
- Generation, listening, History and Saved Voices are free in every mode, and so is exporting Built-in Voice takes. One optional in-app purchase, Design & Clone Export, unlocks exporting Voice Design and Voice Cloning audio.
- Takes come from an AI model and can contain mistakes, such as a missing word or a delivery that misses the request. Vocello rejects takes that fail its audio check instead of saving them; generate again for a different take.
```

### Keywords (100)

`text to speech,tts,narrator,narration,voiceover,clone,audiobook,podcast,read aloud,multilingual` (95)

The keywords avoid words the name and subtitle already index (Vocello, local, AI, voice, studio),
and they name no third-party brand: the content-rights review allows the Qwen and Hugging Face
names only descriptively.

### URLs

| Field | Value |
|---|---|
| Support URL | https://vocello.vercel.app/support/ (already set; matches `config/support-contact.json`) |
| Marketing URL | https://vocello.vercel.app |

### What's New (4000)

App Store Connect may not offer this field on an app's first App Store version. If it does:

```text
Vocello 3.0 runs on a new engine shared with the Mac app. Built-in Voice and Voice Design takes now read the whole script before they speak, every generated take is marked as AI-generated, a take's seed can be pinned from History, the interface is available in ten languages, and imported Clone references are reviewed before they are saved.
```

## App Review notes (4000)

For App Review Information → Notes. No demo account is needed. The download requirement is
spelled out so the app is not judged non-functional under Guideline 2.1.

```text
Vocello generates speech locally on the iPhone. It ships with no bundled model weights, to keep the app small, and needs no account or login.

1. On first launch, go through the three onboarding pages.
2. Open Settings → Models & Files → Voice Models and tap Download for the mode you want to review. Built-in Voice is 2,049,696,897 bytes, Voice Design 2,049,696,404 bytes and Voice Cloning 2,073,713,977 bytes; one model is enough for its mode. Downloads use Wi-Fi only and need at least 4.5 GB of free space before each one, and they can take several minutes. Progress shows the exact bytes downloaded, and the final verification and installation show as an indeterminate finishing step. A download can be cancelled and restarted, and one interrupted in the background is picked up after relaunch. Once a model shows Ready, its mode works without a network connection.
3. In Studio, type a short line, choose a speaker where the mode has one, and tap Generate.
4. Voice Cloning needs the switch "I own or have permission to clone the voices I use" in Settings → Privacy & Permissions. Its reference is recorded with the microphone or imported from an audio file the user has rights to. Microphone and Speech Recognition are requested only to record a reference and transcribe it locally.
5. In-app purchase: Design & Clone Export (non-consumable) unlocks exporting Voice Design and Voice Cloning audio through the share sheet. Generation, listening, History and Built-in Voice export are free. Restore Purchases is in Settings → Design & Clone Export.

Every generated take carries an inaudible watermark and provenance metadata marking it as AI-generated. If a pinned model host is temporarily unavailable, retry later on stable Wi-Fi or use the Support link in Settings; Vocello never substitutes a different model artifact.
```

Before pasting, recheck the three byte counts against the candidate's catalog, and close ASR-09's
fresh North America download proof (see [`ios-appstore-submission.md`](ios-appstore-submission.md)
§2 for the storage and region reasoning).

## Choices for the maintainer

- **Subtitle:** one of the three above, or your own.
- **Naming the model:** the description does not mention Qwen3-TTS. A descriptive line such as
  "Vocello runs the open-source Qwen3-TTS models with Apple's MLX" could be added once ASR-04's
  confirmation 12 (Qwen and Hugging Face names used only descriptively) is recorded.
- **Speaker names:** none appear here; ASR-04's confirmation 13 covers presenting them in the app.
- **The purchase line:** it describes Design & Clone Export as offered, which holds only once
  RF-02's Paid Apps agreement is accepted and the product is submitted with the version.
- **The limitations paragraph:** kept short, in line with the release notes' known limitations.

## Not drafted here

- Screenshots: ASR-05 takes them from the signed candidate on the iPhone, as one 6.9-inch set (or
  the 6.5-inch fallback). See [`ios-appstore-submission.md`](ios-appstore-submission.md) §3.
- Category, age rating and the copyright line.
- Other localizations. The listing is en-US only so far; the export purchase already has en-US,
  fr-CA and fr-FR names and descriptions.
