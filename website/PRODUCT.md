# Vocello Website Product Context

## Register
Brand

## Product Purpose
Vocello is a local-first voice studio for Apple Silicon: a Mac app, the `vocello` command line for scripts and AI agents, and an iPhone app in public TestFlight. The website exists to help creators, indie developers, and Mac-native tool users understand the product quickly, trust the local generation model, hear the shape of the workflows, download the current Vocello stable release (the Mac app and the command line ship together from one tagged GitHub release), and join the iPhone TestFlight beta.

## Current release: 3.1
`docs/releases/v3.1.0.md` is the public account of this release; quote it rather than older copy.
- Models: each mode has one model, which keeps the 4-bit model's size and puts its attention layers at 8 bits. The Speed/Quality switch and the "Prefer lower-memory models" setting are gone. Each mode downloads about 2.2 GB on its own; updating all three from 3.0 downloads about 4.7 GB. After an update from 3.0 the Mac app updates the installed models on its own on an unmetered network; a banner shows the progress and Not Now stops it.
- Mac app: the engine runs inside the app; it updates itself with Sparkle (Vocello > Check for Updates, with automatic checks as a setting). macOS 26 or later, Apple Silicon, 8 GB minimum, 16 GB or more recommended for long projects. The Variation setting is retired: every take samples as the former Expressive.
- Command line: a signed, notarized installer package (`Vocello-macos26-cli.pkg`, needs an administrator password) or a copyable Vocello CLI folder (`Vocello-macos26-cli.dmg`); arm64 only. It shares the app's models, saved voices, and settings and reads History (only while the app is closed). Its takes are files and do not appear in History yet; a later update adds that (never promise a version). Options retired in 3.1 (`--variant quality`, `models use`, `models prefer-lower-memory`, `--variation balanced|consistent`) still parse and warn. `--json` and `--ndjson` give a typed machine contract, and `vocello mcp` serves AI agents over stdio. `../docs/reference/cli.md` and `../Sources/VocelloCLI` own its facts.
- iPhone timing: since 2026-10-26 the public TestFlight beta runs the iPhone app's 3.0 version. Its 3.1 version, on the same engine, has internal TestFlight candidates (`v3.1.0-ios.1` through `v3.1.0-ios.3`) under verification ahead of public TestFlight and the App Store, so 3.1's public changes are still the Mac app's and the command line's. Copy never implies the App Store has the iPhone app yet, or that the public beta runs 3.1. The published release notes keep their original timing; site copy states the current status.
- Both apps since 3.0 (the iPhone app with its 3.0 version): AudioSeal marking on generated takes only (reference clips you record or import and live preview are not marked), the interface in ten languages, a take's seed pinned from History, the distinct deliveries, the measured group (Neutral, Sad, Calm, Whisper, as the app's delivery menu orders them), beside directional hints (Happy, Angry, Fearful, Surprised), Built-in Voice and Voice Design takes that read the whole script first (long-form projects keep the previous layout), and ten speech languages.
- Limits stay visible: take quality is not verified by human listening, and automated checks catch gross failures only. The model clones a voice about as closely as the 3.0 Speed model, not as closely as Quality. The Listen samples predate 3.0 and are never presented as takes of a current version.

## Audience
- Mac users who care about privacy, local software, and native craft.
- Creators who need spoken lines without a cloud subscription or usage meter.
- Developers and AI-agent users who want speech from scripts, the terminal, or an MCP client, without a web API.
- Open-source users who want to inspect releases, model requirements, and underlying technology.

## Brand Voice
Warm, clear, confident, and human. Vocello explains local AI generation plainly. It should feel premium and private, not like a SaaS dashboard or an AI hype page.

## Copy Rules
- Say local, not offline or on-device, unless the technical distinction matters.
- Say generate, voice, script, Voice brief, Saved Voices, Generation History, and Models & Files (the Settings category in both apps; on iPhone it holds Voice Models) consistently.
- Call the CLI "the command line" or "the `vocello` command line", and show commands exactly as `../docs/reference/cli.md` gives them.
- Every copyable command block runs as written in Terminal on a fresh Mac: no `#` comments (zsh does not accept them when pasted), no placeholder files, and only models an earlier block installs. Explain the commands in the prose around the block.
- Avoid celebration copy, emoji, hype claims, and first-person plural.
- Use sentence case. Reserve all caps for tiny labels only when they are truly needed.
- Do not use em dashes in visible copy.
- Keep public model messaging on the active 1.7B surface: each mode has one model, named by its mode (the Built-in Voice model). Speed and Quality name only the 3.0 models it replaced, never the current one, though its id still ends in `_speed`. The 0.6B variant is ruled out (2026-07-02 maintainer decision: Voice Design requires 1.7B); never mention it in public copy.
- Express speed as RTF (synthesis wall time ÷ audio duration, lower is faster); "× realtime" may
  appear only as a companion figure, never as the headline number or under the RTF name.
- Do not publish third-party Vocello timing or clone-prompt performance claims unless they have been reproduced locally with the repository's maintained benchmark harness.
- Describe Voice Cloning as strongest when a Saved Voice is transcript-backed and can reuse a prepared Qwen3 clone prompt. Transcriptless or audio-only references are supported as lower-guidance fallbacks, not errors.
- For transcript auto-fill, say "transcribe locally" or "local transcription," following the local-not-on-device rule. Avoid bare "speech recognition" (too broad) and avoid naming Siri in copy (an Apple system detail; the app handles setup guidance in context).

## Strategic Principles
- Privacy is the architecture, not a badge.
- The Mac app is the hero, and the command line is its companion for scripts and agents. Product screenshots and concrete workflows should carry trust.
- The page should feel calm, polished, and Apple-native, with quiet motion and no decorative excess.
- The primary CTA follows `stableMacRelease` in `../config/public-product-facts.json` and links that tag's release page or assets, never `/releases/latest`. Use that same contract for fallback Mac requirements and the separate iPhone distribution entry point; do not hand-maintain release numbers here. While a newer version is being prepared, `candidateRelease` and `candidateOnlyClaims` in the same file name it, and a feature only the candidate ships is labeled with the candidate version wherever it appears (`scripts/public_facts_contract.py` enforces it).
- Performance claims name the hardware of the record they quote and trace to tracked records in benchmarks/HISTORY.md; never quote a number the repository cannot reproduce. The published speed (RTF) figures come from the Mac mini M6 (16 GB), the canonical benchmark host since 2026-09-22; the current chart's record is Vocello 3.1.0 build 31, compiled with Xcode 27.2, while the released app is compiled from the same source with Xcode 26.6, so copy says the release's own numbers may differ slightly and makes no speed claim beyond the record and the release notes. The published memory figures (the streaming peak and the long-form drift) come from the Mac mini M2 (8 GB), the support floor and the canonical host until then. M6 records are never compared with the M2 history.
- The site should acknowledge the QwenVoice rebrand quietly (inline "formerly QwenVoice" by the wordmark, the footer's continuation line, and the QwenVoice v1.2.3 fallback line). It is not a hero moment.
