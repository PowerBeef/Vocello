<div align="center">

<picture>
  <source media="(max-width: 700px)" srcset="docs/readme/hero-narrow.png">
  <img src="docs/readme/hero.png" width="100%" alt="Vocello: premium voice studio, proven performance, private by design. Write a script, pick or describe a voice, and generate speech locally on your Mac and iPhone. The Mac Studio shows a Built-in Voice take ready to play beside the iPhone app, under the three mode pills: Built-in Voice in gold, Voice Design in lavender, Voice Cloning in terracotta.">
</picture>

<br>

<a href="https://github.com/PowerBeef/Vocello/releases/download/v3.0.0/Vocello-macos26.dmg"><img src="docs/readme/download-mac.svg" height="56" alt="Download Vocello 3.0.0 for macOS 26 or newer"></a>&nbsp;&nbsp;<a href="https://github.com/PowerBeef/Vocello/releases/download/v3.0.0/Vocello-macos26-cli.pkg"><img src="docs/readme/install-cli.svg" height="56" alt="Download the Vocello 3.0.0 command-line installer for macOS 26 or newer"></a>&nbsp;&nbsp;<a href="https://testflight.apple.com/join/Cvp6yCv7"><img src="docs/readme/join-iphone-beta.svg" height="56" alt="Join the Vocello iPhone beta on TestFlight"></a>

<br>

[![Release 3.0.0](https://img.shields.io/badge/release-3.0.0-EDCC8A?style=flat-square&labelColor=1C1E26)](https://github.com/PowerBeef/Vocello/releases/tag/v3.0.0) [![macOS 26+](https://img.shields.io/badge/macOS-26%2B-EDCC8A?style=flat-square&logo=apple&logoColor=F5F6F8&labelColor=1C1E26)](#get-vocello) [![iPhone beta](https://img.shields.io/badge/iPhone-TestFlight%20beta-BFAADB?style=flat-square&logo=apple&logoColor=F5F6F8&labelColor=1C1E26)](https://testflight.apple.com/join/Cvp6yCv7) [![Swift 6 and MLX](https://img.shields.io/badge/Swift%206-MLX-DBA887?style=flat-square&logo=swift&logoColor=F5F6F8&labelColor=1C1E26)](#for-developers) [![MIT license](https://img.shields.io/badge/license-MIT-8C8F9B?style=flat-square&labelColor=1C1E26)](LICENSE)

**[Features](#three-ways-to-make-a-voice)** · **[Get Vocello](#get-vocello)** · **[Command line](#command-line-and-ai-agents)** · **[For developers](#for-developers)**

</div>

<br>

Vocello is a voice studio for your Mac and iPhone. Write a script, pick one of nine voices or describe a new one, and Vocello speaks it with the Qwen3-TTS model running on your own Apple Silicon. A command line brings the same engine to scripts and AI agents.

<table>
<tr>
<td width="56" valign="top"><img src="docs/readme/icons/private.svg" width="40" height="40" alt=""></td>
<td><b>Private by design.</b> No account, no credits and no cloud. Generation runs locally once a model is installed, and your scripts, recordings, voices and takes stay on your Mac or iPhone unless you export them.</td>
</tr>
<tr>
<td valign="top"><img src="docs/readme/icons/fast.svg" width="40" height="40" alt=""></td>
<td><b>Fast.</b> On a Mac mini M6 with the Speed models, a minute of speech generates in under 20 seconds once the model is loaded, and long scripts start playing while the rest is still being made.</td>
</tr>
<tr>
<td valign="top"><img src="docs/readme/icons/native.svg" width="40" height="40" alt=""></td>
<td><b>Native.</b> Built in Swift on Apple's MLX, with no Python and no server, for the Mac, the iPhone and Terminal.</td>
</tr>
</table>

## Three ways to make a voice

<picture>
  <source media="(max-width: 700px)" srcset="docs/readme/modes-narrow.png">
  <img src="docs/readme/modes.png" width="100%" alt="Three cards, each edged in its mode's color. Built-in Voice, gold: nine speakers and ten languages, with the delivery you choose. Voice Design, lavender: describe a voice in your own words, then keep the ones you like. Voice Cloning, terracotta: a new voice from a short clip you have permission to use.">
</picture>

- **Built-in Voice.** Nine speakers in ten languages, with a delivery preset or a few words about how it should sound.
- **Voice Design.** Describe a voice ("a warm, clear narrator"), hear it, and save the ones you like to use again.
- **Voice Cloning.** Record or import a clip of a voice you own or have permission to use. Voice Cloning follows the reference voice, so the clip sets its character, and it waits for your consent in Settings.

## Made for real projects

- **Long scripts.** Paste a whole chapter: Vocello plans it into segments that play one after another while the rest generates, then joins them into one file.
- **Ten languages.** Chinese, English, Japanese, Korean, German, French, Russian, Portuguese, Spanish and Italian, detected from your script. The interface comes in ten languages too, set apart from the speech language.
- **Your library.** Saved voices, and a searchable History of every take. Pin a take's seed from History to make it again with the same settings.
- **Marked as AI-generated.** From 3.0, every take Vocello generates carries an inaudible AudioSeal watermark and a note naming the model and mode. Reference clips you record or import are never marked.
- **Up to date by itself.** The Mac app is signed and notarized, and installs signed updates from **Vocello > Check for Updates**.

## Performance

<picture>
  <source media="(max-width: 700px)" srcset="docs/readme/performance-narrow.png">
  <img src="docs/readme/performance.png" width="100%" alt="Speed: a real-time factor of 0.26 to 0.32, warm, in all three modes on a Mac mini M6 with 16 GB and the Speed models, which is 3.1 to 3.8 times real time. Peak memory: about 3 GB, flat as scripts grow, against about 8 GB before streaming, on an 8 GB Mac mini M2. Long-form drift: memory ended 1.1 percent below its start across a 12-segment project with 10.4 minutes of audio, on the same M2.">
</picture>

The speed figures come from a Vocello 3.0 development build on the benchmark Mac. [Performance, measured](#performance-measured) shows them by mode and explains how they were taken.

## Get Vocello

**On a Mac:** [download Vocello](https://github.com/PowerBeef/Vocello/releases/download/v3.0.0/Vocello-macos26.dmg), drag it to Applications, then install a voice model from **Settings > Models & Files**.<br>
**On iPhone:** [join the public beta on TestFlight](https://testflight.apple.com/join/Cvp6yCv7). The beta runs Vocello 3.0, on the same engine as the Mac app, and the App Store release follows.<br>
**In Terminal:** see [Command line and AI agents](#command-line-and-ai-agents).

| Platform | Requirements | Models |
| --- | --- | --- |
| Mac | macOS 26.0 or newer, Apple Silicon, 8 GB RAM (16 GB or more for Quality and long projects) | Speed (4-bit) and Quality (8-bit) |
| Command line | macOS 26.0 or newer, Apple Silicon | Shared with the Mac app |
| iPhone | iPhone 15 Pro or newer, iOS 26.0 or newer | Speed (4-bit) |

Models download once from Hugging Face and are never bundled. Speed uses less memory and suits 8 GB Macs; Quality is a Mac option for 16 GB or more. → [What's new in 3.0.0](docs/releases/v3.0.0.md) · [All releases](https://github.com/PowerBeef/Vocello/releases)

<details>
<summary><b>Upgrading, and older Macs</b></summary>

<br>

To upgrade from Vocello 2.x, install the new DMG by hand once: 2.x has no updater, and from 3.0 the app updates itself. History, saved voices and settings carry over, and the model manager offers an update for each model installed with 2.x. Vocello was called QwenVoice before 2.2.0, and old repository links redirect here. Macs on macOS 15 can use the legacy [QwenVoice 1.2.3](https://github.com/PowerBeef/Vocello/releases/tag/v1.2.3).

</details>

> [!NOTE]
> Take quality is not verified by human listening. Automated checks catch gross failures only (silence, a cut-off take, missing words, the wrong language), so a take can still carry a subtle defect, such as a swallowed syllable or a delivery that misses the requested style. Generate again for a different take. The [release notes](docs/releases/v3.0.0.md#evidence-and-limitations) list the known limitations.

## Command line and AI agents

`vocello` brings the Mac app's features to Terminal, sharing its models, saved voices and settings: every mode, long scripts, saved voices, models and History, with JSON output for scripts and an MCP server for AI agents.

Install it with the signed [installer package](https://github.com/PowerBeef/Vocello/releases/download/v3.0.0/Vocello-macos26-cli.pkg), which asks for an administrator password, then, from a new Terminal window, check it, install the Built-in Voice Speed model (about 2 GB) and play a first take:

```sh
vocello --version
vocello models install pro_custom_speed
vocello custom --variant speed --text "The train left at dawn." --play
```

To let Claude Code generate speech with Vocello through the installer package's link:

```sh
claude mcp add --scope user vocello -- /usr/local/bin/vocello mcp
```

→ [CLI reference](docs/reference/cli.md): the folder install, updates, removal, the JSON contract and other MCP clients.

<br>

---

## For developers

Vocello is a working reference for running a 1.7B-parameter text-to-speech model natively on Apple Silicon: Swift 6 with strict concurrency, a first-party MLX runtime, audio that streams with bounded memory, and a measurement discipline that ties every performance claim to a record.

### How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/charts/architecture-dark.svg">
  <img alt="Architecture diagram: the SwiftUI app hosts the engine in the same process, which drives the owned VocelloQwen3Core runtime (an engine actor owning each session, the Qwen3-TTS talker and code predictor, the Mimi decoder) on MLX and Metal; PCM audio streams back chunk by chunk." src="docs/charts/architecture-light.svg">
</picture>

One engine serves the Mac app, the iPhone app and the `vocello` command line. Every request takes one path from conditioning to a verified 24 kHz mono WAV: an engine actor owns the session, the Qwen3-TTS talker and code predictor sample codec frames, the Mimi decoder turns them into audio, and PCM streams back chunk by chunk to the player, a limiter, an atomic WAV writer and a quality check. → [Architecture](docs/ARCHITECTURE.md)

### Engineering highlights

<table>
<tr>
<td width="56" valign="top"><img src="docs/readme/icons/runtime.svg" width="40" height="40" alt=""></td>
<td><b>An owned runtime, not a Python wrapper.</b> <a href="Packages/VocelloQwen3Core/README.md"><code>VocelloQwen3Core</code></a> is derived from mlx-audio-swift v0.1.2 and narrowed to what Vocello ships: about 36,000 of its 49,000 upstream lines removed, every remaining file tracked with its change, and a facade that keeps raw MLX types out of the apps.</td>
</tr>
<tr>
<td valign="top"><img src="docs/readme/icons/streaming.svg" width="40" height="40" alt=""></td>
<td><b>Streaming that doesn't grow.</b> Audio crosses an actor-owned, frame-bounded channel that never drops audio and suspends the producer instead of buffering. Streaming took the peak of the same take from about 8 GB to about 3 GB, flat with script length.</td>
</tr>
<tr>
<td valign="top"><img src="docs/readme/icons/launches.svg" width="40" height="40" alt=""></td>
<td><b>Launch-bound, not compute-bound.</b> Fusing the code predictor's rotary embedding removed about 600 kernel launches per frame (+26% warm), and compiling the per-frame predictor pass added +8 to 11% with byte-identical output.</td>
</tr>
<tr>
<td valign="top"><img src="docs/readme/icons/reproducible.svg" width="40" height="40" alt=""></td>
<td><b>Reproducible by construction.</b> Every request carries its own seed and sampler state. Cancellation is typed and awaited, so a cancelled take never reaches History, and MLX errors arrive as typed failures instead of aborting the process.</td>
</tr>
<tr>
<td valign="top"><img src="docs/readme/icons/proof.svg" width="40" height="40" alt=""></td>
<td><b>Proof before merge.</b> Fixed-seed byte identity gates every scheduling change, regressions stay on record with their numbers, and published benchmark records are pass-only and privacy-allowlisted.</td>
</tr>
<tr>
<td valign="top"><img src="docs/readme/icons/device.svg" width="40" height="40" alt=""></td>
<td><b>Tested on real hardware.</b> UI tests drive the native Mac app and a paired iPhone, never a Simulator, and every take passes a byte-bound audio check before it is saved.</td>
</tr>
</table>

→ [Optimization ledger](benchmarks/OPTIMIZATION.md) · [Testing runbook](docs/reference/testing-runbook.md) · [MLX guide](docs/reference/mlx-guide.md)

### Performance, measured

Warm real-time factor (seconds of generation per second of audio, lower is faster) by mode and script length on the Mac mini M6 (16 GB), pooled from the most recent canonical records of one build (record `74f026be`, a Vocello 3.0 development build measured on October 7, 2026, before the release's newer MLX, full-precision sampling and whole-script reading):

<!-- rtf-chart:start (generated by scripts/generate_readme_charts.py) -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/charts/rtf-by-mode-dark.svg">
  <img alt="Grouped bar chart: warm real-time factor of the Speed models by script length, lower is faster: Built-in Voice 0.27 to 0.31, Voice Design 0.26 to 0.31, Voice Cloning 0.27 to 0.32. Every bar sits below the real-time line at 1.0." src="docs/charts/rtf-by-mode-light.svg">
</picture>
<!-- rtf-chart:end -->

<details>
<summary><b>How these were measured</b></summary>

<br>

The speed figures pool warm takes of the Speed models from the canonical benchmark host. No benchmark record of the released 3.0.0 is published yet, so they are not a measurement of 3.0.0 itself. The 8 GB Mac mini M2 is the support floor: its records (the last canonical one, `379db820`, measured warm RTF 0.53 to 0.82) form an earlier series that is never compared with the M6's. The memory figures come from that M2: streaming took the peak of the same take from about 8 GB to about 3 GB (`benchmarks/OPTIMIZATION.md` §F.1), and a 12-segment long-form project (smoke run `8f15c1fd`) ended 1.1% below its starting footprint. The charts regenerate from the named records with `scripts/generate_readme_charts.py`.

→ [Benchmark history](benchmarks/HISTORY.md) · [Benchmarking method](docs/reference/telemetry-and-benchmarking.md)

</details>

### Build from source

You need full Xcode (the CI version is pinned in `config/toolchain.json`) on an Apple Silicon Mac with macOS 26 or newer, plus the pinned xcodegen, ripgrep and Python packages; [New Mac setup](docs/reference/development-workflow.md#new-mac-setup) walks through it.

```sh
git clone https://github.com/PowerBeef/Vocello.git
cd Vocello
./scripts/regenerate_project.sh
./scripts/build.sh build
```

`project.yml` generates the Xcode project, and the repository scripts are the build and test interface: `scripts/dev.sh check` runs the lint, contracts and tests your changes touch, and `scripts/dev.sh ci` runs what CI runs. `./scripts/build.sh cli` builds a development `vocello` at `build/vocello`. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md); coding agents also read [`CLAUDE.md`](CLAUDE.md).

<details>
<summary><b>Project layout</b></summary>

<br>

```text
Sources/                 the apps and the engine
  QwenVoiceApp.swift       macOS app (Views/, ViewModels/, Services/)
  iOS/                     iPhone app
  QwenVoiceCore/           engine host: runtime factory, generation, model delivery
  VocelloCLI/              the vocello command line
Packages/VocelloQwen3Core/ the owned Qwen3-TTS runtime on MLX, with its own tests
Tests/                   unit and iPhone logic tests, Mac and iPhone UI tests
scripts/                 build, test, benchmark and release lanes, and the README art
config/                  machine-readable contracts: models, privacy, release, roadmap
benchmarks/              published benchmark records and the optimization ledger
website/                 vocello.vercel.app (React and Vite)
docs/                    architecture, references, audits, release notes
```

</details>

<details>
<summary><b>Design system</b></summary>

<br>

Dark-first, warm neutrals on a charcoal canvas, and one accent per mode. Liquid Glass stays on chrome and falls back to solid surfaces under Reduce Transparency and while audio generates. The tokens live in the app's theme and in [`website/src/tokens.css`](website/src/tokens.css), and `scripts/readme_art/render.sh` draws this page's art from them.

| Token | Color | Use |
| --- | --- | --- |
| Gold | ![#EDCC8A](https://img.shields.io/badge/-EDCC8A-EDCC8A?style=flat-square) | Built-in Voice, the brand accent |
| Lavender | ![#BFAADB](https://img.shields.io/badge/-BFAADB-BFAADB?style=flat-square) | Voice Design |
| Terracotta | ![#DBA887](https://img.shields.io/badge/-DBA887-DBA887?style=flat-square) | Voice Cloning |
| Charcoal | ![#16181E](https://img.shields.io/badge/-16181E-16181E?style=flat-square) | The canvas |
| Text | ![#F5F6F8](https://img.shields.io/badge/-F5F6F8-F5F6F8?style=flat-square) | Primary text |

</details>

### Documentation

| | |
| --- | --- |
| [Architecture](docs/ARCHITECTURE.md) | Ownership, the life of a take, the engine's invariants |
| [Development setup](docs/reference/development-workflow.md#new-mac-setup) | A new Mac, from clone to first build |
| [Testing runbook](docs/reference/testing-runbook.md) | Which lane proves what, on the Mac and on a paired iPhone |
| [Benchmarking](docs/reference/telemetry-and-benchmarking.md) | The protocol behind every published number |
| [Privacy and storage](docs/reference/privacy-storage.md) | What is stored where, and how it is deleted |
| [CLI reference](docs/reference/cli.md) | Every `vocello` command, the machine contract and the MCP server |
| [Release notes](docs/releases/) | What changed in each release, and its known limitations |
| [Roadmap](docs/ROADMAP.md) | What is in flight and what follows |

## License and acknowledgements

Vocello is available under the [MIT License](LICENSE). It builds on [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS), [MLX](https://github.com/ml-explore/mlx), [mlx-audio-swift](https://github.com/Blaizzy/mlx-audio-swift) and [GRDB.swift](https://github.com/groue/GRDB.swift). Third-party models and assets keep their own terms; see the [third-party attributions](Sources/Resources/third_party_attributions.json) and the runtime's [notices](Packages/VocelloQwen3Core/NOTICES.md).

<br>

<div align="center">
<img src="docs/readme/icon.png" width="56" alt="The Vocello app icon">
<br>
<sub>Vocello · a private voice studio for your Mac and iPhone</sub>
</div>
