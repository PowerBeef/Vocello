---
status: active
owner: release-qa
reviewed: 2026-11-10
summary: App Store listing for Vocello for iPhone 3.0.0 (en-US), entered in App Store Connect on 2026-11-01 at the maintainer's request. It covers the subtitle, promotional text, description, keywords, What's New, URLs and the App Review notes. Further changes to App Store Connect need a separate request.
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

**Status: entered in App Store Connect on 2026-11-01 (ASR-05).** At the maintainer's request, the
subtitle "Local AI voice studio", the promotional text, description, keywords and marketing URL, and
the App Review contact and notes were written as drafted below and read back byte-identical. What's
New is not offered on a first App Store version and stays empty. On 2026-11-02, after the iPhone 15
Pro farm runs and the decision to keep it as the floor, the description and the review notes gained
the speed and live-preview sentences below, written and read back the same way. On 2026-11-04, after the
[App Review readiness audit](../audits/2026-11-04-app-review-readiness.md), the notes' last paragraph
became the Safeguards paragraph below, answering Guideline 1.2's AI content wording, 4.2.3(ii) and
cloning consent. The same day every claim here was checked against the app, and the promotional text and
review-notes steps 2, 3 and 5 were tightened; all of it was written and read back the same way. On
2026-11-10, with the decision to keep refusing iPad (RF-42), the notes gained a paragraph asking for
review on an iPhone 15 Pro or later, and step 2 and the Safeguards paragraph gained the download
confirmation that build 30 shows (RF-41). The notes are 3,802 of 4,000 characters and read back
byte-identical. They describe build 30, the candidate that will be submitted: at the maintainer's
request it replaced build 29 on version 3.0.0 on 2026-11-10, read back. Any later change to App
Store Connect is a separate, explicit request; keep this file and App Store Connect in step.

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
Hear your script in a built-in voice, a voice you describe, or a clone of a voice you own or have permission to use. Every take is generated locally on your iPhone.
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

- Vocello requires an iPhone 15 Pro or later. Generation is fastest on the newest iPhones; on an iPhone 15 Pro, a take can take longer to generate than it lasts, so the live preview may pause while it catches up. That is normal, and the finished take plays without pauses. Each voice mode uses its own model of about 2 GB, downloaded once over Wi-Fi, or over cellular data if you allow it in Settings; keep at least 4.5 GB free while a model installs.
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

Please review on an iPhone 15 Pro or later. Recent iPad models meet the same hardware capability, so the app installs on them, but Vocello does not run on iPad: it shows an unsupported-device message there.

1. On first launch, go through the three onboarding pages.
2. Open Settings → Models & Files → Voice Models and tap Install for the mode you want to review, then Download in the confirmation that shows the download's size. Built-in Voice is 2,049,696,897 bytes, Voice Design 2,049,696,404 bytes and Voice Cloning 2,073,713,977 bytes; one model is enough for its mode. Downloads use Wi-Fi unless the Download over cellular switch on that screen is turned on. Each one needs at least 4.5 GB of free space and can take several minutes. Progress shows the exact bytes downloaded, and the final verification and installation show as an indeterminate finishing step. A download can be cancelled and restarted, and one interrupted in the background is picked up after relaunch. Once a model shows Ready, its mode works without a network connection.
3. In Studio, type a short line, choose a speaker where the mode has one, and tap Generate. Voice Design also needs a voice description first: tap the speech-bubble chip marked + above Generate and describe the voice, for example "a warm, deep narrator". Generate stays dimmed until the description and the line are both filled. Speed depends on the iPhone: on iPhone 17 Pro a take generates in about half its own length, while on the oldest supported model, iPhone 15 Pro, it takes about one and a half to a little over two times as long as the audio it produces. While generating, the live preview starts playing early; on slower iPhones it may pause while generation catches up, then continue. This is expected behavior, not a hang. The finished take plays without pauses and is saved to History.
4. Voice Cloning needs the switch "I own or have permission to clone the voices I use" in Settings → Privacy & Permissions. Its reference is recorded with the microphone or imported from an audio file the user has rights to. Microphone and Speech Recognition are requested only to record a reference and transcribe it locally.
5. In-app purchase: Design & Clone Export (non-consumable) unlocks exporting Voice Design and Voice Cloning audio through the share sheet. Generation, listening, History and Built-in Voice export are free. Open it from Settings → Design & Clone Export, or by exporting a Voice Design or Voice Cloning take; Restore Purchases is on the same sheet.

Safeguards. Vocello is a single-user tool that runs locally: it has no accounts, no feed, no posting and no messaging. Generated audio leaves the iPhone only when the user exports it, or in their own iPhone backups. A Voice Design description or Built-in Voice delivery instruction that explicitly requests celebrity imitation or voice impersonation is refused. The permission switch in step 4 gates clone generation and saving a cloned voice. Every generated take, including exported files, carries an inaudible watermark and provenance metadata marking it as AI-generated. The model list ships inside the app, every downloaded file is checked against a pinned SHA-256 checksum before use, and no feature is enabled remotely. Each model's download size is shown in Settings → Models & Files → Voice Models before Install is tapped, and a confirmation asks before any download starts. Contact: Settings → About → Help & Support opens https://vocello.vercel.app/support/, which lists an email address. If a pinned model host is temporarily unavailable, retry later on stable Wi-Fi; Vocello never substitutes a different model artifact.
```

Before pasting, recheck the three byte counts against the candidate's catalog, and close ASR-09's
fresh North America download proof (see [`ios-appstore-submission.md`](ios-appstore-submission.md)
§2 for the storage and region reasoning).

## Export purchase: Design & Clone Export

Entered in App Store Connect on 2026-11-10 at the maintainer's request and read back:

- **Availability:** the same 148 territories as the app, with new territories included
  automatically, as the app has it. The purchase had no availability record before. When the EU
  territories return to the app (BKL-41), add them to the purchase too.
- **Review note (4000):** read back byte-identical (689 characters).

```text
Design & Clone Export is a one-time, non-consumable purchase. It unlocks exporting audio made with Voice Design and Voice Cloning through the share sheet. Generation, listening, History and exporting Built-in Voice takes are free and need no purchase.

To reach it: open Settings → Design & Clone Export. It also appears when you tap Share or Download on a Voice Design or Voice Cloning take. To make such a take, install the Voice Design model first (Settings → Models & Files → Voice Models → Install, then Download; about 2 GB), then in Studio choose Voice Design, describe a voice, type a line and tap Generate.

Restore Purchases is on the same sheet. No account or sign-in is needed.
```

The purchase still reads `MISSING_METADATA`: its review screenshot comes from the signed candidate
on the phone (RF-12), and one account step is RF-02's.

## Choices for the maintainer

- **Subtitle:** "Local AI voice studio", chosen 2026-11-01.
- **Naming the model:** the description does not mention Qwen3-TTS. ASR-04's confirmation 12 (Qwen
  and Hugging Face names used only descriptively) is recorded since 2026-11-01, so a descriptive line
  such as "Vocello runs the open-source Qwen3-TTS models with Apple's MLX" may be added on request.
- **Speaker names:** none appear here; ASR-04's confirmation 13 (2026-11-01) covers presenting them
  in the app.
- **The purchase line:** it describes Design & Clone Export as offered, which holds only once
  RF-02's Paid Apps agreement is accepted and the product is submitted with the version.
- **The limitations paragraph:** kept short, in line with the release notes' known limitations.

## Not drafted here

- Screenshots: ASR-05 takes them from the signed candidate on the iPhone 17 Pro, as one 6.3-inch set
  (1206×2622), the iPhone size Apple's specifications require. Apple's page also still calls the
  6.5-inch size required when no 6.9-inch set is present, so the media manager settles it at upload.
  [`ios-appstore-submission.md`](ios-appstore-submission.md) §3 owns the rule.
- The copyright line. Category and age rating are already set in App Store Connect (RF-02,
  2026-10-12).
- Other localizations. The listing is en-US only so far; the export purchase already has en-US,
  fr-CA and fr-FR names and descriptions.
