---
status: active
owner: release-qa
reviewed: 2026-11-26
summary: App Store listing draft for Vocello for iPhone 3.2.0 (en-US), reconciled from the 2026-11-01/10 App Store Connect 3.0.0 entry against the shipped attn hybrid baseline (retained unchanged for 3.2 under RF-70) and RF-73 App Store readiness safeguards. Pushing remaining updates to App Store Connect needs a separate explicit request.
sourceOfTruth:
  - config/public-product-facts.json
  - Sources/Resources/qwenvoice_contract.json
  - Sources/Resources/Localizable.xcstrings
  - Sources/Resources/qwenvoice_production_model_catalog.json
  - config/support-contact.json
  - docs/releases/v3.1.0.md
  - docs/reference/content-rights-review.md
---
# App Store listing: Vocello for iPhone 3.2.0 (en-US)

**Status: 3.2.0 target draft reconciled with `main`'s shipped `attn` hybrid baseline (`RF-70` closed keeping `artifactVersion` `2026.11.13.1` unchanged). On 2026-11-25, authorized App Store Connect prep applied Age Rating `13+`, `147` territories (app and export IAP), and the Privacy Policy URL; the version record still holds the 2026-11-10 `3.0.0` entry until an explicit 3.2.0 metadata update request.**
On 2026-11-01 (ASR-05), at the maintainer's request, the subtitle "Local AI voice studio", the
promotional text, description, keywords and marketing URL, and the App Review contact and notes were
entered in App Store Connect on version 3.0.0 and read back byte-identical. On 2026-11-02 (iPhone 15
Pro floor), 2026-11-04 (App Review readiness audit, archived in git history,
Safeguards paragraph), and 2026-11-10 (RF-41 download confirmation and RF-42 iPad refusal on build 30),
the listing and review notes were updated and read back byte-identical. By the maintainer's 2026-11-21
decision there is no iPhone 3.0 or 3.1 App Store release and no more 3.1 TestFlight builds: iPhone
submits directly as **3.2.0** after Pack B (`RF-68`, `RF-69`), Pack C (`RF-70`), and `RF-73` land.
`RF-70` closed keeping `main`'s `artifactVersion` `2026.11.13.1` hybrid model byte counts and
storage headroom unchanged for 3.2. Any change to App Store Connect requires a separate, explicit
maintainer request; keep this file and [`ios-appstore-submission.md`](ios-appstore-submission.md) in
step with live App Store Connect state.

The copy follows `website/PRODUCT.md`:
- it says local, not on-device;
- it uses sentence case;
- it has no em dashes, hype or first-person plural.

Every claim below traces to a source listed above. Counts in parentheses are Apple's limits
(UTF-8 bytes for App Review notes; characters for store-listing fields).

## App information

| Field | Value | Notes |
|---|---|---|
| Name (30) | Vocello | Already set; unchanged (7). |
| Subtitle (30) | Local AI voice studio | 21. Alternatives: "Text to speech, made locally" (28), "Private AI text to speech" (25). |
| Privacy Policy URL | https://vocello.vercel.app/privacy/ | Matches the website canonical URL and in-app Settings link. |
| Terms of Use URL | https://vocello.vercel.app/terms/ | Linked from onboarding, inline cloning consent, Export Purchase, and Settings → Privacy & Permissions. |
| Age Rating | 13+ (applied 2026-11-25) | Raised from 4+ and verified via readback in App Store Connect on 2026-11-25 (`RF-62`/`RF-73`); Nov 16 descriptors `Shared Location = No` and `Dating and Relationships = No` remain pending web-portal completion. |
| Territories | 147 of 175 (applied 2026-11-25) | Applied and verified via readback on both app and export IAP: excludes the 27 EU territories (`BKL-41`) and China Mainland (`CN`, `RF-73`), keeping South Korea (`KR`) enabled. |

## Version 3.2.0

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

- Vocello requires an iPhone 15 Pro or later, or an eligible Apple silicon or A17 Pro iPad with 8 GB+ memory (in portrait compatibility mode). Generation is fastest on the newest devices; on an iPhone 15 Pro, a take can take longer to generate than it lasts, so the live preview may pause while it catches up. That is normal, and the finished take plays without pauses. Each voice mode uses its own model of about 2.2 GB, downloaded once over Wi-Fi, or over cellular data if you allow it in Settings; keep at least 5 GB free while a model installs.
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
Vocello 3.2 runs on a local engine shared with the Mac app with one improved model per mode. Built-in Voice and Voice Design takes read the whole script before they speak, every generated take is marked as AI-generated, a take's seed can be pinned from History, the interface is available in ten languages, and imported Clone references are reviewed before they are saved.
```

## App Review notes (4000)

For App Review Information → Notes (limit: **4,000 UTF-8 bytes**). No demo account is needed. The
download requirement is spelled out so the app is not judged non-functional under Guideline 2.1.

```text
Vocello generates speech locally on your device. It ships with no bundled model weights to keep the app small and needs no account or login.

Please review on an iPhone 15 Pro or later, or an eligible Apple silicon or A17 Pro iPad (8 GB+ RAM, portrait compatibility mode). Unsupported devices show a localized unsupported-device screen. Demo video (RF-66: onboarding, model install, take, Mic/Speech prompts, cloning consent, IAP) is in App Review Information → Attachment (backup: [URL]).

1. Onboarding: Page 3 notes local AI speech, AudioSeal watermarking, and links to Privacy Policy and Terms of Use.
2. Models: open Settings → Models & Files → Voice Models, tap Install for one mode, then Download in the size confirmation. Exact sizes: Built-in 2,225,870,484 B, Design 2,225,869,991 B, Cloning 2,249,887,307 B (one suffices for its mode). Downloads use Wi-Fi (or opt-in cellular), need >=5 GB free, verify SHA-256 before activation, and cancel/resume across launches. Once Ready, generation works offline.
3. Studio: enter a short line, pick a voice, and tap Generate. For Voice Design, tap the Voice Brief chip (or inline setup prompt) and enter e.g. "a warm, deep narrator". iPhone 17 Pro generates faster than real time; iPhone 15 Pro runs ~1.5x-2x audio length so live preview may pause while catching up while the saved take plays smoothly.
4. Voice Cloning: the first Record, Import, Save, or Generate shows a one-time inline permission sheet confirming voice ownership/permission with a Terms of Use link. The toggle also lives in Settings → Privacy & Permissions and can be revoked anytime without deleting saved voices or history. Microphone and Speech Recognition are used locally only.
5. In-app purchase: Design & Clone Export (non-consumable) unlocks exporting Voice Design and Voice Cloning audio via the share sheet (with one-tap Export Now after unlocking from a take). Generation, listening, History, Saved Voices, and Built-in Voice export are free. Reach it via Settings → Design & Clone Export or tapping Share on a Design/Clone take; Restore Purchases is on the same sheet.

Safeguards, privacy (5.1.2(i)), and rights (4.1/5.2). Single-user local tool with no accounts, cloud backend, feed, or third-party AI APIs: Hugging Face serves immutable static weights verified by bundled SHA-256 digests; zero scripts, voice descriptions, recordings, transcripts, or generated audio leave the device unless exported or backed up by iOS. Regional scope: 147 territories (EU-27 and China Mainland excluded at launch), identical behavior everywhere. Shipping builds compile out all internal diagnostics and QVOICE_*/QWENVOICE_* env reads (2.5.19). Voice Design descriptions and Built-in delivery instructions requesting celebrity imitation or impersonation are refused across all 10 languages; spoken scripts stay unfiltered as a private local editor. Every generated WAV carries a mandatory inaudible AudioSeal watermark (fixed non-identifying payload) and WAV LIST/INFO provenance inspectable with open-source AudioSeal tools (external transcoding after export may degrade it), disclosed in Settings → Privacy & Permissions with Privacy Policy and Terms of Use (https://vocello.vercel.app/terms/). Settings → About links Help & Support (https://vocello.vercel.app/support/), Report an Issue (https://vocello.vercel.app/support/#report, zero automatic upload), and Open Source & Licenses. Ownership (4.1/5.2): the Apple Developer account holder is the sole author and owner of Vocello for Mac (github.com/PowerBeef/Vocello), vocello.vercel.app, and the pinned PowerBeef02 Hugging Face repos. Third-party content: Qwen3-TTS (Apache-2.0), Meta AudioSeal (MIT), original artwork, and generated previews. If revisions are needed, please list all findings together so every item can be resolved in one pass.
```

Before pasting, recheck the three byte counts against the candidate's catalog, and close ASR-09's
fresh North America download proof (see [`ios-appstore-submission.md`](ios-appstore-submission.md)
§2 for the storage and region reasoning).

## Export purchase: Design & Clone Export

Entered in App Store Connect on 2026-11-10 at the maintainer's request and read back:

- **Availability:** applied and verified via readback on 2026-11-25 at **147 territories** on both
  the app and the export purchase (`RF-73`: China Mainland `CN` excluded alongside the 27 EU
  territories, keeping South Korea `KR` enabled). When the EU territories return (`BKL-41`), add
  them to the purchase too.
- **Review note (4000):** updated for 3.2.0 Share label and one-tap Export Now.

```text
Design & Clone Export is a one-time, non-consumable purchase. It unlocks exporting audio made with Voice Design and Voice Cloning through the share sheet. Generation, listening, History, Saved Voices and exporting Built-in Voice takes are free and need no purchase.

To reach it: open Settings → Design & Clone Export. It also appears when you tap Share on a Voice Design or Voice Cloning take (after unlocking, tap Export Now to open the share sheet). To make such a take, install the Voice Design model first (Settings → Models & Files → Voice Models → Install, then Download; about 2.2 GB), then in Studio choose Voice Design, describe a voice, type a line and tap Generate.

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
- The copyright line (entered during the explicit 3.2.0 App Store Connect metadata update). Category
  (Productivity / Utilities) was set under RF-02 (2026-10-12 / 2026-11-04) and age rating was raised
  to `13+` on 2026-11-25 (`RF-62`/`RF-73`; Nov 16 `Shared Location` and `Dating and Relationships`
  descriptors remain pending web-portal completion).
- Other localizations. The listing is en-US only so far; the export purchase already has en-US,
  fr-CA and fr-FR names and descriptions.
