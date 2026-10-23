---
status: active
owner: backend-mlx
reviewed: 2026-10-22
summary: The vocello CLI — user-facing generation surface and deterministic benchmark/test driver over the same in-process MLX engine as the app.
sourceOfTruth:
  - project.yml
  - Sources/VocelloCLI
  - scripts/build.sh
  - scripts/cli_version_contract.py
  - scripts/cli_package.py
  - scripts/release.sh
  - scripts/verify_packaged_cli.sh
---
# The `vocello` CLI

> **Install (Vocello 3.0.0):** the [v3.0.0 release](https://github.com/PowerBeef/Vocello/releases/tag/v3.0.0)
> ships `vocello` two ways, both signed with Developer ID and notarized, for Apple Silicon (arm64
> only) on macOS 26.0 or later:
>
> - **Installer package,** [`Vocello-macos26-cli.pkg`](https://github.com/PowerBeef/Vocello/releases/download/v3.0.0/Vocello-macos26-cli.pkg).
>   Open it and follow Installer, which asks for an administrator password. It puts the CLI folder at
>   `/usr/local/lib/vocello`, links `/usr/local/bin/vocello` to it and adds zsh completion in
>   `/usr/local/share/zsh/site-functions`; the shell profile is not changed. A newer package replaces
>   the previous files. `sudo sh /usr/local/lib/vocello/uninstall.sh` removes it and leaves the
>   models, saved voices and History untouched.
> - **Folder copy,** [`Vocello-macos26-cli.dmg`](https://github.com/PowerBeef/Vocello/releases/download/v3.0.0/Vocello-macos26-cli.dmg).
>   Copy the whole **Vocello CLI** folder to a folder you own, keep the executable and its resource
>   bundles together, and run it by its quoted path. Delete the folder to remove it; its
>   `uninstall.sh` is only for the installer package.
>
> Either way, the CLI uses the Mac app's models, saved voices and settings and reads its History.
> CLI takes are saved as files and do not appear in History yet; a 3.0 update adds that with the
> cross-process History lock (RF-30). AI agents connect through [`vocello mcp`](#mcp--serve-ai-agents-over-the-model-context-protocol).

`vocello` is a headless macOS command-line surface over the same in-process MLX engine the app uses.
It serves two roles:

- **User-facing generation** — synthesize speech from the terminal (Built-in Voice / Voice Design /
  Voice Cloning), one clip or many, scriptable with JSON output and stdin piping.
- **Deterministic benchmark/test driver** — drive the perf/quality matrix in-process (cold/warm
  controlled exactly via load/unload, no UI waits), aggregate run-scoped telemetry, and publish a
  privacy-safe PASS-only benchmark record when running inside this checkout.

It links the engine framework directly, like the apps, **ships no model weights and no Python**, and runs
**in place** beside its MLX metallib bundle. It shares the same on-disk model store as the app
(`~/Library/Application Support/QwenVoice/models` by default). Install weights via the app
(Settings → Models & Files) or headlessly with `vocello models install <id>` — the same
HuggingFace downloader the app uses. `generate`/`bench` fail fast if a requested model isn't
installed (`vocello models list` / `models status` show what's present). For macOS UI tests and
bench in debug context, see [`testing-runbook.md`](testing-runbook.md) "Model readiness"
(`scripts/macos_test.sh models ensure`).

## Build & run

```sh
./scripts/build.sh cli                 # build build/vocello (single config, -Onone)
./scripts/build.sh cli-optimized [args...]   # -O build for shipping-performance benchmark evidence
./scripts/build.sh cli --version       # prints the project MARKETING_VERSION
./scripts/build.sh cli generate --text "Hello." --variant speed   # build + run with args
build/vocello <command> [options]      # run the already-built binary
```

Benchmark records take `toolchain.optimization` from the executable-digest-bound build receipt
(the `<binary>.provenance.json` that `scripts/build.sh` writes beside the CLI, verified by
`scripts/publish_benchmark_history.py`), so only a `cli-optimized` binary can publish CLI benchmark
records; the -Onone `cli` build is for development and functional runs.

`build/vocello` is the public symlink to the real binary under the policy-owned
`build/cache/xcode/macos/…` (-Onone) or `build/cache/xcode/macos-optimized/…` (`cli-optimized`) product tree.
MLX and the SwiftPM resource bundles are found beside the executable as it was loaded, which through a
link is the link's folder, so a `vocello` started through any link (this one, the installer's
`/usr/local/bin/vocello`, an MCP client's configured path) first execs the real binary, keeping its
arguments, environment and process id; the adjacent MLX shader bundle (`default.metallib`) then stays
reachable from any working folder. **Do not copy only the binary**: keep the adjacent resource
bundles and catalogs. The release workflow stages a complete `Vocello CLI` folder in a separate
`<desktop-output-name>-cli.dmg`; copy the whole folder to any user-owned location and invoke the
quoted executable path. No checkout, Python, privileged install, Homebrew formula, or shell-profile
edit is needed for that payload. Model weights remain separate, explicitly installed data.

`scripts/cli_package.py` inventories the executable, source-bound catalogs, MLX shader and dependency
resources, and existing governed license/NOTICE material. It rejects missing/stale resources,
extra executable code, symlinks, digest drift, or mismatched source/version/build identity. Packaging
explicitly copies the catalogs because Xcode's tool product does not reliably emit those resource
files; any present built catalog must match the source before staging.
`verify_packaged_dmg.sh … --include-cli` also verifies the signed/stapled CLI DMG, copies its folder
to a path containing spaces, and runs model-free discovery from an unrelated working directory.
Its command-bound `cli-package-verification.json` is explicitly **not** all-mode generation,
cancellation, memory, or audio-quality acceptance. The opt-in `qualify` command supplies that
operator check against an already copied payload:

```sh
python3 scripts/cli_package.py qualify \
  --directory "/path with spaces/Vocello CLI" \
  --version 3.0.0 --build <unused-build> --commit <exact-sha> \
  --model-store "/existing/model/store" \
  --clone-reference "/test-owned/reference.wav" \
  --report build/artifacts/macos/release/cli-generation-qualification.json
```

It first revalidates every packaged byte, then runs Built-in English, French Voice Design, and
English Clone serially with fixed seeds and the Speed models. Clone uses audio-only conditioning
unless `--clone-transcript-file /path/to/reviewed.txt` supplies the actual reference transcript;
the qualifier never invents one. Each row must return the exact model,
language, output path, finite positive duration, normal EOS, RIFF/WAVE bytes, and a strict QC `pass`.
Seed and streaming fields are explicitly **requested**, not claimed observed engine receipts.
The schema-v2 qualification report also requires one two-item Built-in batch process at seed
`30000005`. It verifies the ordered batch result (read through `scripts/lib/vocello_cli_json.py`,
which takes the v1 envelope and the older bare JSON alike), distinct retained WAVs, finite matching
durations, EOS, bounded PCM integrity, and no leftover outputs/staging. Batch JSON does not expose
per-item QC receipts: this block reports engine acceptance and PCM integrity, not an invented
strict-QC or semantic verdict. Raw batch JSON, including failure rows, stays with the ignored audio.
It then interrupts
a live Built-in take (`--ndjson`) only after its `generation_started` event, requires exit 130 and a final
envelope reporting `cancelled` by SIGINT with no forced exit, rejects leftover final/staging
output without deleting it, and verifies the public unknown-command and invalid-mode exits. The isolated runtime links
only to an existing operator-provided model store; it downloads nothing. Its privacy-safe report
contains digests, sizes, timings, public identities, and verdicts—not prompts, transcripts, audio,
or absolute paths—and carries `publicationAuthority: none`. The relative `artifactDirectory`
points to retained WAVs below the report's ignored directory. Successful rows and the active stage
are written atomically before the next subprocess; failure or interruption preserves that record
and audio, with sanitized failure types. Reusing a report is refused: use a new report path for
each attempt. Timeouts terminate and await the process group before any next model can launch;
progress detection handles output without a newline. This is package execution/QC proof, not a
perceptual Clone-fidelity or multilingual accuracy claim.

RF-10 runs this check on the copied, signed candidate. Development/ad-hoc qualification can diagnose
the packaging contract but cannot substitute for Developer ID, notarization, or candidate evidence.
The existing two-argument app-only verifier remains available for historical candidates; the current
release workflow requires both DMGs.

The CLI target embeds `project.yml`'s `MARKETING_VERSION` and `CURRENT_PROJECT_VERSION` in its
Mach-O Info.plist section. `vocello --version`, `vocello version`, and `vocello -v` therefore share
the product's single version authority. `scripts/cli_version_contract.py` validates both the target
settings and the built executable; an unsupported bare `swiftc` build without embedded metadata
reports `unknown` rather than a stale numeric version.

By default the CLI uses the app's runtime data directory (`~/Library/Application Support/QwenVoice`).
A repository-built internal CLI uses `QwenVoice-Debug` when `QWENVOICE_DEBUG` is truthy;
distributed builds cannot activate that environment override. `--data-dir <path>` remains the
explicit CLI interface. `bench` defaults to the debug-isolated folder (which holds the full model
set) and forces telemetry on.

## Shell completion

`vocello completions zsh|bash|fish` prints a completion script generated from the command model
the parser runs on, so it offers exactly the commands, aliases, subcommands, options and choice
values the CLI accepts. The checked-in `scripts/completions/_vocello` is that zsh output
(`CLICommandModelGoldenTests` keeps them equal). From a checkout or an installed CLI:

```sh
mkdir -p ~/.zsh/completions
vocello completions zsh > ~/.zsh/completions/_vocello
```

Add `fpath=(~/.zsh/completions $fpath)` to `~/.zshrc` before any `compinit` call (add
`autoload -Uz compinit && compinit` after it if completion is not initialized yet), then open a new
shell. For bash, `source <(vocello completions bash)`; for fish,
`vocello completions fish > ~/.config/fish/completions/vocello.fish`.

## Command line

One declarative command model (`Sources/VocelloCLI/Core/CommandModel/VocelloCommandTree.swift`)
drives the parser, help, completions and `vocello capabilities`; its rendering is checked in as
`config/cli-contract/v1/commands.json`.

- Strict: an unknown command, subcommand or option, a missing option value, a value on a bare flag
  and an extra operand are usage errors (exit 2) with a did-you-mean hint when one is close.
- `-h`/`--help` anywhere shows that command's help; `vocello help models install` equals
  `vocello models install --help`.
- Global options work anywhere before `--`: `--output-format text|json|ndjson` (`--json`,
  `--ndjson`), `--quiet`, `--verbose`, `--no-input`, `--data-dir <dir>`, `--manifest <path>`,
  `--help`.
- `--name=value` carries a value that starts with `--`; `--` ends options.
- A command with subcommands runs its default when none is named (`vocello models` is
  `vocello models list`); options before the subcommand belong to that default.
- `vocello custom|design|clone …` runs `generate --mode <mode> …`, or `batch` when `--file` is given.

## Machine contract (v1)

Text output is for people and is not a contract. The machine formats are, under the additive-only
compatibility policy in `config/cli-contract/v1/README.md` (validated by
`scripts/cli_contract.py validate`):

- `--json`: stdout carries exactly one envelope, success or failure:
  `{schemaVersion, ok, command, requestID, result, error, warnings, meta}`. `command` is the dotted
  canonical path (`models.install`); `result` may accompany a failure (a partial batch keeps its
  rows); `error` is `{code, category, exitCode, message, retryable, retryAfterMs, hint, detail}`.
- `--ndjson`: stdout carries event records `{schemaVersion, seq, t, requestID, type,
  generationID?, data}` (`started`, `engine_booting`, `model_loading`, `generation_started`, `chunk`,
  `download_progress`, `output_published`, `generation_completed`, `warning`, …) ending in one
  `result` record whose `data` is the envelope. `progress` counts finished work: a batch's `items`, a
  line batch's `lines`, a long-form project's `segments` (with its `index` among `projects`), or
  `run`'s `requests`, each with `finished`. Running records coalesce under load and never block
  generation; terminal records are never dropped; consumers ignore unknown types. No text,
  transcript or audio ever travels in an event.
- stderr carries no CLI notes in the machine formats unless `--verbose` (the engine's own
  model-load lines still appear there until the owned package routes them).
- The machine formats and `--no-input` never prompt and never read stdin unless a flag names it
  (`--text -`, `--file -`), so a caller whose stdin never closes cannot hang a command.
- 64-bit values the CLI reports, such as `seed`, `effectiveSeed` and `longFormBaseSeed`, are decimal
  strings; an embedded engine receipt (`completionReceipt`) keeps its own numeric fields.
- `vocello capabilities --json` describes every command, option, error code, exit code, event type,
  mode, language, delivery cell and limit, plus runtime facts (data folder, memory tier, speakers,
  installed models), with no engine boot.
- `bench` is an internal tool with its own output; it refuses `--json`/`--ndjson`.

| Exit | Category | Meaning |
| --- | --- | --- |
| 0 | ok | Success. |
| 1 | failure | Generation, QC, publication, assembly, a stopped batch, a download, an integrity check or an internal error failed. |
| 2 | usage | The invocation or its input was refused before any work. |
| 66 | not_found | A named voice, speaker, model, History item or input file does not exist. |
| 69 | precondition | A model is not installed, or speech recognition is unavailable. |
| 73 | output | The output location cannot be written. |
| 74 | io | Storage is full or a file could not be read or written. |
| 75 | transient | The engine or a store is busy, memory is short or under pressure, or the network is unavailable: retry later. |
| 77 | permission | Voice-cloning consent is missing or a path is not allowed. |
| 78 | config | The configuration or a store schema is unusable. |
| 130 | cancelled | Interrupted by SIGINT. |
| 143 | cancelled | Terminated by SIGTERM. |

Signal handling is armed before any command work starts. The first SIGINT/SIGTERM cancels the owned
command and awaits its cleanup. A second signal or 30-second deadline forces exit with an explicit
stderr warning after killing any `--play` child and waiting up to 2 seconds for its reap; exit
status alone is not proof of clean cancellation. A signalled run exits `130`/`143` even when the
command also failed for another reason; its envelope then reports `cancelled` with that failure in
`detail.failure`. A closed stdout (EPIPE) stops the command the same way and exits `141`, with
nothing more reported; after a real signal it changes nothing.

## Commands

### `generate` — synthesize one clip

```sh
vocello generate --mode custom|design|clone --variant speed|quality \
                 (--text "…" | --text-file <path> | piped stdin) [--out <path>] [options]
```

| Option | Meaning |
|---|---|
| `--mode` | `custom` (default) · `design` · `clone` |
| `--variant` | `speed` (4-bit) · `quality` (8-bit); without it, the package the Mac app uses for the mode (its explicit choice, "prefer lower-memory models", or this Mac's recommendation, falling back to an installed package): `vocello models active` shows it, and the result's `variantSource` says `flag` or `app` |
| `--text` / `--text-file` | inline text or a file (`-` reads stdin); with neither, piped stdin is used in text mode (the machine formats and `--no-input` read stdin only for `-`) |
| `--speaker` | (custom) speaker id; default = contract default (see `vocello speakers list`); an empty or blank value is refused |
| `--voice-brief` | (design) plain-language voice description |
| `--voice` / `--reference` / `--transcript` | (clone) a saved voice name/id, or a reference `.wav` + optional transcript |
| `--confirm-consent` | (clone) **required**: confirms you own or have permission to clone this voice; ignored by other modes (see [Voice-cloning consent](#voice-cloning-consent)) |
| `--delivery` | optional delivery style (custom and design; refused in clone mode, which has no instruction channel) |
| `--app-delivery` | with no `--delivery`/`--delivery-cell`, send the apps' default delivery (the Neutral preset instruction) on Custom and Design, as `batch --app-delivery` does |
| `--language` | `auto` or a Qwen3 language (`chinese`, `english`, `japanese`, `korean`, `german`, `french`, `russian`, `portuguese`, `spanish`, `italian`) by name or code, a region subtag ignored (`ja-JP`, `es-MX`); omitted = Auto; any other value is refused before boot |
| `--seed` | deterministic sampling seed — the same request + seed reproduces the same take bit-for-bit |
| `--variation` | `expressive` (official sampling) · `balanced` · `consistent` — trades take-to-take liveliness for repeatability; without it, the app's Variation setting |
| `--out` | output `.wav` file (any case); a folder, a trailing `/` or another extension is refused before boot, and a missing folder is created; default → `<data>/outputs/cli/<yyyyMMdd_HHmmss>_<mode>_<generation id>.wav`, unique per run |
| `--long-form` | `auto` (default): a script longer than one take (900 characters, East Asian characters counting three) runs as a long-form project, as the apps route it · `always`: any script does · `never`: such a script is refused (`text_too_long`) |
| `--line-by-line` | one take per line, as the Mac app's line batch runs them (see below); `--out-dir <folder>` names their folder (default `<data>/outputs/cli`) |
| `--stream` | streaming synthesis at the app's 320ms cadence; reports first-chunk latency (TTFC) + chunk count (default) |
| `--no-stream` | accumulate the full result before decoding (old non-streaming behavior) |
| `--play` | play the result with `afplay` when done; a signal stops and reaps the player, and the published file stays |
| `--client-request-id` | idempotency: a repeated id with the same request replays its stored result (see `run`) |
| `--plan` | resolve the take (mode, model and its source, whether it is installed, language, seed, variation, output path) and report it without loading a model |
| `--json` / `--ndjson` | the v1 envelope (result: the take) instead of the bare path, or events ending in it |

`generate`, `batch` and `run` host the engine the way the Mac app does (`VocelloDesktopCore`'s
`DesktopEngineHost` over the app's `TTSEngineStore` with the Mac memory budget): a take passes the app's
support check, consent admission, busy refusal and memory admission, runs under its critical-pressure
guard and is followed by its post-take trims. Consent is always the invocation's or the request's,
never the app's Settings acknowledgment. `bench` keeps driving the raw engine for its measurements.

**One engine at a time on an 8 GB Mac.** A hosted engine holds a lease in one per-user folder
(`~/Library/Caches/com.qwenvoice.vocello/engine-hosts/`, a locked file that dies with its process),
whatever data folder it serves: memory belongs to the Mac. Before booting, `generate`, `batch` and
`run` read the others' leases and count the Vocello app whenever it runs. On an 8 GB Mac a second
engine is refused (`engine_busy`, exit 75); pass `--wait-for-engine` to wait for the other to exit (a
`queued` event says so once), or `--allow-concurrent-engine` to run anyway. On a larger Mac it runs,
with the warning `concurrent_engine`. Lanes that drive the CLI on an 8 GB Mac therefore need the app
closed.

Streaming is now the default for `vocello generate`. It mirrors the app's engine streaming path (same
`streamingInterval` and chunk delivery) and reports the user-perceived first-chunk latency, but it does
**not** play audio as it generates — there is no live preview player; `--play` plays the completed file.
Streaming and non-streaming are separately qualified paths; identical sampling settings do not
guarantee identical output across them. Use `--no-stream` for accumulate-then-decode behavior.

**Selecting a mode** — three equivalent ways: the shortcut subcommands `vocello custom|design|clone …`
(a `--file` makes them route to `batch`), the explicit `--mode <mode>` flag, or — when you omit `--mode`
at an interactive terminal with text output and no `--no-input` — a numbered picker. Every other run
without `--mode` defaults to `custom` (no prompt). `vocello modes` lists the modes and what each needs.

Prints the output WAV path on stdout (or, with `--json`, the envelope whose `result` carries `audioPath`, `durationSeconds`, `wallSeconds`,
`realtimeFactor` (standard RTF: `wallSeconds ÷ durationSeconds`, lower is faster, below 1.0 is faster than
real time), `realtimeSpeedup` (its inverse), `finishReason`, `mode`, `variant`, `modelID`, `seed` (the
effective seed as a decimal string: pass it back as `--seed`, with the same variant and variation, to
reproduce the take), and — when `--stream` — `firstChunkMS` and `chunks`).

**Long-form projects.** A script past one take is planned, before any model work, by the apps'
long-form planner (at most 100 segments; `--plan` reports `longForm` and `segments`) and run by the
apps' own long-form runner: Auto resolves one language over the whole script, each segment is one
streaming take at the app's cadence (with the seed derived from the base seed `--seed`, or a random
one) that must pass the engine's Fast QC and the apps' audio QC, the bounded assembler joins them, the
joined output must pass the apps' QC too, and the manifest v4 is written. A Design project without a
delivery gets the Neutral one, as the apps send it. Segment takes and the manifest stay in
`<output stem>_segments/` beside the output (`<output stem>_segments-<attempt>/` when that folder
already exists: an attempt never reuses one); the joined file replaces `--out` only once the project
passed, and never after a signal. The result adds `longForm: true`, `longFormBaseSeed` (also its `seed`), `longFormPlanDigest`,
`longFormLanguage`, `longFormManifestPath`, `longFormSegments` (each kept segment's index, boundary,
pause, seed, generation id, path, duration, finish reason and QC warnings) and `longFormAssembly`;
`finishReason` is `max_tokens` when any segment was truncated. A rejected segment or join fails with
`qc_rejected` (`detail.segment` names the segment); a stopped project keeps its completed segments and
says where (warning `long_form_segments_kept`). Projects write no History rows until the History lock
lands (RF-30). `--no-stream` does not apply to a project and is refused with one.

**Line by line.** `--line-by-line` runs the script as the Mac app's line batch does (`DesktopLineBatch`
over `MacLineBatchRequest`): one take per trimmed line that has something to speak (blank lines and
separators such as `***` are skipped), at most 100 lines, each refused before boot if it does not fit
one take; one batch seed for every line (`--seed`, or one drawn), a repeated line deriving its own;
Auto resolved once over the whole script; the Neutral delivery when none is given (Design, and Custom on
a package with instruction control); every line streamed at the app's cadence, on one model load. The
takes are `<stamp>_<mode>_<id>_<NNN>.wav` in `--out-dir`. The result is `{lineByLine: true, mode,
variant, variantSource, modelID, language, batchSeed, count, wallSeconds, items[]}`, each item `{index,
text, audioPath, durationSeconds, finishReason, seed, generationID}`. It stops at the first failed line
and then keeps every planned row, as `batch` does. `--out`, `--long-form` and `--no-stream` are
refused with it (`--long-form auto`, the default, is accepted). Unlike `batch`, whose items sample on their seed and text alone (the QC lanes resume a
batch from any item on that property), these takes follow the app.

Default output names carry the take's generation id (the JSON `generationID`), so concurrent runs
never share a file. An explicit `--out` that names an existing file is replaced atomically only by a
successful take (QC and publication passed), and a stderr note says so before boot. It never replaces
a History take's audio, as `history export` never does: History is asked, and while the app holds it a
file in a folder the app writes takes to counts as one (`outputs/cli` aside); either is refused as
`output_unavailable` (73) before boot. Failed startup,
QC, cancellation and publication preserve any previous destination. Only attempt-owned staging is
discarded. Clone rejects a reference/output alias (including symlink and hardlink aliases).
Two successful writers to the same explicit destination use last-publication-wins; use distinct
paths when both outputs must be retained. A Ctrl-C at the interactive mode picker ends the command
at once (exit 130).

### `batch` — synthesize many clips with a single model load

```sh
vocello batch --file <path|-> --mode … --variant … \
              [--speaker <id> | --voice <name> | --voice-brief "…"] [--out-dir <dir>] [options]
```

One non-empty line per clip; all clips share the same voice/mode/variant, so the engine runs them
through **one loaded model** — far faster than repeated `generate` calls. Reads stdin when `--file` is
omitted or `-` (in the machine formats only for `-`). Prints one output WAV path per line (or, with
`--json`, the envelope whose `result` is the batch summary). Also accepts
`--seed` (applied to every item — re-running the batch reproduces it, and a fixed seed steadies
cross-segment character) and `--variation`, like `generate`.

Each item is an ordinary single-take engine request. Batch index, total, progress and outcome
accounting belong to the CLI; engine-only batch fields must not be passed to `generate`.
The command uses the same request builder exercised against the real engine support policy in
`CLIExecutionTests`, including negative controls that retain the single-take rejection guard.

Batch stops at the first failure. Its envelope is then `ok: false` with `error.code`
`batch_incomplete` (or `memory_pressure`, `engine_busy`, `cancelled`), and its `result` keeps the
failure rows (`schemaVersion: 2`): every planned index/generation identity with `completed`, `failed`, `cancelled`, or
`not_attempted` status; completed paths are retained. Only a signalled cancellation makes a
row `cancelled`; a genuine failure that coincides with a signal stays `failed` and adds
`cancellationRequested: true`. A take the engine stopped on its own under memory pressure is
`failed` with `errorCode: memory_pressure` and the command exits `75`. A failed row's `errorCode` is a
contract error code (`output_missing`, `qc_rejected`, `generation_failed`, …). Failure exits nonzero. There is no automatic retry, seed substitution, or implicit resume. Batch uses Auto
language per text and non-streaming output (with `--long-form`, each line is a long-form project run
as `generate` runs one: its segments and manifest in `<project>_segments/`, its joined output
`<project>.wav`); `--language`, `--stream`, and `--out` are rejected
instead of silently ignored (use `generate` or batch `--out-dir`).

The bare `--capture-codec-trace` flag (internal-diagnostics binaries with `QWENVOICE_DEBUG=1` and
telemetry on, short-form batches only) asks the engine for each take's codec trace. Under a
registered run id (`QVOICE_MAC_BENCH_RUN_ID`) the engine keeps it beside its diagnostics as
codec-trace v1 and records its digest in the take's engine row; sampling and output are unchanged.
`scripts/macos_test.sh qc-takes` passes it.

### `run` — JSON generation requests (for agents)

```sh
vocello run --request <file|-> [--json|--ndjson]     # one request, reported as generate reports it
vocello run --requests <file|-> [--json|--ndjson]    # JSONL: one request per line, one warm engine
```

A request is a JSON object of `generate`'s options in camelCase (`mode`, `text`, `textFile`, `speaker`,
`voiceBrief`, `voice`, `reference`, `transcript`, `confirmConsent`, `delivery`, `deliveryCell`,
`appDelivery`, `language`, `seed`, `variation`, `variant`, `out`, `longForm`, `stream`), described by
`config/cli-contract/v1/generate-request.schema.json`. It becomes `generate` arguments and goes through
the same strict parser, so an unknown field, a wrong type or `text: "-"` is refused. With `--requests`
each line (lines end at `\n`) runs on the same engine; a failed request does not stop the others, and the
result lists every one (`{requests, succeeded, failed, results[]}`, each `{index, clientRequestID, ok,
replayed, result, error}`), ending `batch_incomplete` when any failed. A signal stops the run and keeps
every planned row: the request it interrupted and those it never reached are `cancelled`. A request
never reads unnamed stdin, so one without `text` or `textFile` is a usage error.

**Idempotency:** a request's `clientRequestID` (or `generate --client-request-id <id>`, which also becomes
the envelope's `requestID`) is kept with its result under `<data>/cli/requests` for seven days, named by
the id's digest and private to the user. The same id with the same request replays the stored result
(`meta.replayed: true`) instead of running again; the same id with a different request is
`idempotency_conflict` (2); the same id while another process runs it is `request_in_progress` (75). A
failed request keeps nothing, so a retry runs again. "The same request" means the same take: the text
counts by its content wherever it came from (`--text`, a file or stdin), paths count as absolute paths,
option spellings count as what they mean (`--variant fast` is `speed`), an omitted option counts as what
it resolves to at run time (the package and variation the app's settings and installed packages choose,
the default speaker),
and neither consent nor how a command reports counts, so a `generate` command line and the same `run`
request are one request, while one whose omitted setting has since resolved differently (a changed
app setting, a package installed or removed) is not. A
replay whose take no longer exists fails with `output_missing` (use a new id), and a success whose
result could not be kept carries the warning `idempotency_not_recorded`.

### `mcp` — serve AI agents over the Model Context Protocol

```sh
vocello mcp [--allow-dir <folder[:folder…]>] [--max-queue <n>] [--allow-model-install]
vocello mcp --print-config claude-code|claude-desktop [same options]   # the client's setup, then exit
vocello mcp --self-test [--json]                                       # a scripted session, no engine
claude mcp add --scope user vocello -- /usr/local/bin/vocello mcp      # what --print-config claude-code prints
```

An MCP client starts the server and speaks JSON-RPC 2.0 on its stdin and stdout, one message per line. It
serves the stateless 2026-07-28 revision (each request names it in `_meta`; `server/discover`) and the
`initialize`-era revisions 2025-11-25, 2025-06-18, 2025-03-26 and 2024-11-05; an unsupported revision in
`_meta` is answered `-32022` with the supported ones. stdout carries protocol messages only: the server
writes them to a private copy of it and points descriptor 1 at stderr, where anything else lands (the
model package's load lines, `--verbose` notes). It exits when the client closes stdin, after answering
the calls still running; a signal cancels them instead.

| Tool | Runs | |
|---|---|---|
| `get_capabilities`, `list_speakers`, `list_languages`, `list_deliveries`, `list_briefs` | `capabilities`, the catalog commands | read |
| `list_voices`, `get_voice`, `list_models`, `get_settings` | `voices list`/`show`, `models list`, `settings list` | read |
| `list_history`, `get_history_item`, `export_history_item` | `history list`/`search`/`show`/`export` | read |
| `get_status` | the server: data folder, allowed folders, engine, queue | read |
| `generate_speech` | `generate`, from a `run` request without `textFile` | engine |
| `enroll_voice`, `delete_voice` | `voices enroll`/`delete` | engine |
| `install_model` | `models install`, offered only with `--allow-model-install` | engine |

Each tool's arguments become its command's options and operands and go through the same strict parser,
and the command reports to that call only (as in json mode), so a tool can do nothing its command line
refuses. A success's `structuredContent` is the command's `result` (also given as JSON text, with each
warning as a text line); a failure is a tool error whose `structuredContent.error` is the contract's error
object. Reads run at once, beside anything else. Engine tools share one warm engine, booted by the first
one and unloaded by the engine's idle policy, and run one at a time: up to `--max-queue` (default 4) wait
in arrival order, and the next is refused with `engine_busy` (75). The engine takes its lease (and its
8 GB admission) when it first loads a model. With a `progressToken` in `_meta`, a call's events become
`notifications/progress` (chunks at most twice a second). `notifications/cancelled` stops the call
through its command's cancellation (a take through the engine's typed barrier), discards a waiting call
and answers neither.

**Paths and consent:** a path argument is absolute. Clips (`reference`, `audio`) are read from inside
`<data>/outputs` (History takes included) or a `--allow-dir` folder (several separated by `:`), and audio
(`out`) is written inside `<data>/outputs/cli` or a `--allow-dir` folder, never into the folders the app
keeps takes in. Symbolic links resolve before the check, a `..` component or a link to nothing is refused,
and a path outside is refused before anything about it is looked at, as `path_not_allowed` (77). Reads and
the engine requests share one warm engine. Cloning
and saving a voice need `confirmConsent: true` in each request, never inherited. CLI takes write no History
rows until RF-30's History lock, and `delete_history_item` arrives with it.

### `history` — read the app's History

```sh
vocello history [list] [--mode custom|design|clone] [--order newest|oldest|longest|shortest|mode] [--limit 1-500] [--json]
vocello history search <words> [--mode …] [--order …] [--limit …] [--json]
vocello history show <id> [--json]          # adds the engine's completion receipt
vocello history export <id> --out <file.wav> [--replace]
```

Reads the History the Mac app owns (`<data>/history.sqlite`) through `VocelloDesktopCore`, in one short
read-only transaction per command: it never migrates, reconciles or writes the store, and it lists takes
exactly as the app does (newest first; a long-form project's segments follow its joined row unless a
search lists matches flat; the Mac search is case-insensitive over text and voice). A store written by a
newer Vocello is refused with `history_schema_newer` (78); a busy store is `store_busy` (75). While the
app has a long-form recovery pending, project rows are withheld with a warning. The app writes History
without waiting for other readers, so until the cross-process History lock lands (RF-30) every
`history` command refuses with `store_busy` while the Vocello app is running on the same data folder;
quit the app, or point `--data-dir` elsewhere. `export` copies the take
the way the app's Save As does (complete before it replaces anything; `--replace` to overwrite).
Deleting, clearing and recovery come with the cross-process History lock (RF-30).

### `settings` — read and change the app's settings

`vocello settings [list|get <name>] [--json]` reads the Mac app's preferences (`com.qwenvoice.app`):
`autoplay`, `output-folder`, `variation`, `prefer-lower-memory`, `variant.custom|design|clone`
(`automatic` when unset) and `interface-language` (read-only). Each row says whether it is the app's
default. Voice-cloning consent is never a CLI setting.

`vocello settings set <name> <value>` changes one as the app's Settings do and reports its new row:
`autoplay` and `prefer-lower-memory` take `true` or `false` (`on`/`off`, `yes`/`no` too); `variation`
`expressive`, `balanced` or `consistent`; `output-folder` an existing folder or `default`;
`variant.<mode>` `speed`, `quality` or `automatic` (`automatic` removes the choice, `default` the folder);
turning `prefer-lower-memory` on clears every per-mode choice, as the app's toggle does. A bad
value or name is `invalid_input`; `interface-language` stays the app's. The app reads each value when
it next needs it, and a running app is told (`com.qwenvoice.shared.settingsDidChange`).

**A running app hears every change.** Each write posts a distributed notification named for its store
(`com.qwenvoice.shared.{savedVoices,models,settings}DidChange`; `SharedStoreChange` in
`Sources/DesktopShared`), and the Mac app reloads that store: its saved voices, or its model manager
(install state and package choices). The CLI writes no History until RF-30, so it posts no History
change yet.

### `briefs` — Voice Design's starting briefs

`vocello briefs [--language <l>] [--json]` lists the app's eight starting briefs by position in a
speech language (default English), with the 500-character description limit.

### `voices` — manage saved clone voices

```sh
vocello voices list [--json]
vocello voices show <name|id> [--json]   # reference, transcript, enrollment record
vocello voices banks [--json]            # Clone delivery banks: <Name> and <Name> (<Preset>)
vocello voices enroll --name <name> --audio <wav> [--transcript "…" | --audio-only] --confirm-consent
vocello voices replace <id> --audio <wav> [--transcript "…" | --audio-only] --confirm-consent
vocello voices save-take <history id> [--name <name>] [--transcript "…" | --audio-only] --confirm-consent
vocello voices delete --id <id>
```

`enroll`, `replace` and `save-take` require `--confirm-consent`; `list`, `show`, `banks` and `delete`
do not. They save a voice as the app's voice sheet does (`DesktopVoiceEnrollment`), through the hosted
engine:

- **Transcript.** `--transcript` is the clip's words; `--audio-only` saves none (the voice conditions on
  the audio alone). With neither, `--transcribe auto` (the default) recognizes the clip on this Mac only
  when Speech recognition is already allowed for the terminal, so it never prompts; `always` asks for
  it (macOS may prompt; Speech needs Siri on); `never` refuses. A transcript needs its reference
  language: detected from the words, or `--language`.
- **Quality.** A reference with quality warnings (too short, too long, unreadable) is refused
  (`qc_rejected`, the warnings in `detail`) unless `--on-warnings keep` saves it anyway or `discard`
  reports it discarded; an excessively long reference is always refused.
- **Names.** The app's rules: a name needs a letter, digit or underscore and must not match another
  saved voice, case-insensitively. `replace` keeps the voice's name unless `--name` gives a new one.
- **`save-take`** takes a Design or Clone take from History (which is read only while the app is
  closed). A Clone take's text is its transcript and its voice its suggested name; a Design take's text
  is only what was asked for, so it needs `--transcript`, recognition or `--audio-only`, and its name
  defaults to the one the app suggests from the brief. The record notes it came from Design. A Clone
  take's name defaults to "<voice> Sample", or the take's file name when it has no voice, as in the app.
- **`delete`** retries for a few seconds while another Vocello process holds the saved-voice store.
- Saved-voice writes load no model, so they take no engine lease and are not refused beside a running
  engine.

Each change tells a running app (`com.qwenvoice.shared.savedVoicesDidChange`). The result of `enroll`,
`replace` and `save-take` is `{outcome, voice, name, qualityWarnings, transcriptSource,
referenceLanguage, automaticTranscription}`.

### Voice-cloning consent

The apps record voice-cloning consent once, through the visible Settings acknowledgment. The CLI has
no Settings screen and does not read the apps' preference, so every invocation that clones or saves a
voice records consent explicitly with the bare `--confirm-consent` flag: `generate`/`batch` in clone
mode (including the `vocello clone …` shortcut), `voices enroll`, and `bench` whenever `clone` is in
`--modes` (the default matrix includes it). Without the flag the command refuses before booting the
engine, and `CLIRuntime` applies the same `VoiceCloningConsentPolicy` again at the engine call, so no
clone request or enrollment reaches the engine unconfirmed. The flag is accepted and ignored on other
runs, so scripts may pass it uniformly. Pass it only for voices you own or have permission to clone.

### `speakers` — list built-in Built-in Voice speakers

```sh
vocello speakers list [--json]
```

Lists the built-in Qwen3 speaker presets (id, display name, language; the contract default is marked)
so you don't have to guess `--speaker` ids. Read-only — doesn't boot the engine, so it returns
instantly.

### `modes` — list the generation modes

```sh
vocello modes [--json]
```

Lists the three generation modes (`custom` / `design` / `clone`) and what each needs (`--speaker` /
`--voice-brief` / `--voice` | `--reference`). Static and instant. Select a mode via the
`vocello custom|design|clone …` shortcut, `generate --mode <mode>`, or the interactive picker.

### `languages` — list the generation languages

`vocello languages [--json]` lists every language `--language` accepts with its canonical name, the
primary code it also answers to (`en`, `fr`, `ja`; a region subtag such as `ja-JP` is ignored) and
`auto`. Instant, no engine boot.

### `deliveries` — list delivery presets + instruction text

```sh
vocello deliveries [--json]
```

Lists every built-in delivery preset as a preset id and the natural-language instruction
the model receives in its canonical English form (the source of truth is `EmotionPreset`). Static
and instant. These ids are the
`bench --delivery <id>` cells, and `--shipped-only --json` is the shipped roster `scripts/voice_identity_language_reliability.py` reads.
Objective, reference-free delivery adherence (F0 / speaking-rate / duration deltas against a
same-seed neutral take) is measured by `vocello bench --delivery` with
`scripts/bench_delivery_prosody.py`; see
[`telemetry-and-benchmarking.md` §4.6](telemetry-and-benchmarking.md#46-delivery--prosody-cells).

`generate` and `batch` accept `--delivery-cell <preset>.<intensity>` for repository-owned
CustomVoice selections. That identity fails closed if its accompanying copy drifts. It also enables
the dual-match Mandarin route for `angry.normal` when both the contract-backed speaker language and
resolved output language are Chinese. Free-form `--delivery` stays verbatim. `generate --json`
reports the actual model-facing instruction language, digest, and cell identity.

### `models` — inventory and install

```sh
vocello models list [--json]
vocello models status [<id>] [--json]      # adds missing-file detail
vocello models verify [<id>] [--json]      # every installed file's size and SHA-256
vocello models active [--json]             # the package each mode uses, as the app resolves it
vocello models install <id> [--verbose]    # headless download into the shared models dir
vocello models install-recommended [--plan] # the package each mode uses (`models active`); --plan downloads nothing
vocello models remove <id>                  # an installed model, its staging and the shared files only it used
vocello models use <mode> speed|quality|automatic   # the app's per-mode package choice
vocello models prefer-lower-memory on|off           # the app's "Prefer lower-memory models"
```

`install-recommended` installs, for each mode, the package `models active` names (the app's explicit
choice, the lower-memory preference, then this Mac's recommendation); its result lists each with
`planned`, `update_planned` or `already_installed` with `--plan`, else `installed`, `updated` or
`already_installed`; a failure keeps the rows already installed. `remove` deletes as the app's model
manager does and is refused (`engine_busy`) while the Vocello app or another vocello engine runs, since
either may have the model loaded; a package choice that named the removed model moves to another
installed package of its mode, or back to the recommendation. Its `freedBytes` is the model folder's
size; shared components another model still links stay. Installs and removals tell a running app
(`com.qwenvoice.shared.modelsDidChange`).

`use` and `prefer-lower-memory` set the same preferences as `settings set variant.<mode>` and
`settings set prefer-lower-memory`; `models active` shows what each mode then resolves to.

`verify` reads every byte of each installed model and compares it with the authenticated catalog's
exact sizes and SHA-256 digests (`--ndjson` reports progress per file); any difference exits 1 with
`integrity_failed` and keeps every row.

Shows each model's install state, on-disk size, and (for `status`) any missing required files.
`install` uses the same `HuggingFaceDownloader` as the macOS app — a CLI-installed model is
immediately usable in the app, and vice versa. Variant-scoped ids (`pro_custom_speed`, `…_quality`)
are what `generate --variant` selects. Foreground sessions are invalidated on every terminal path;
durable staging precedes terminal continuation, bounded progress retains the exact final count,
transient retries preserve valid staging, explicit cancellation discards it, and compact local
metrics are bounded under `diagnostics/model-downloads/`. See
[`model-delivery.md`](model-delivery.md).

For test/bench lanes with `QWENVOICE_DEBUG=1`, weights live under `QwenVoice-Debug/`; the test
driver symlinks `QwenVoice-Debug/models` → the canonical store (see
[`testing-runbook.md`](testing-runbook.md) "Model readiness").

### `doctor` — check the setup

`vocello doctor [--json]` checks, with no engine boot, the shared data folder, the bundled model
contract and authenticated catalog, the installed models, the Mac's memory tier and free disk. A
missing contract or catalog exits 78 (`config_error`); everything else is a named `ok`/`warn` check.

### `bench` — drive the perf/quality matrix + aggregate

```sh
vocello bench [--modes custom,design,clone] [--variants speed,quality] \
              [--lengths short,medium,long] [--warm 3] [options]
```

Per cell: 1 cold (medium) for Custom/Design + N warm per length; Voice Cloning is warm-only.
Telemetry defaults to verbose; use `--telemetry off` for engine-only WAV diagnostics without
history publication. Results land in `<data>/diagnostics`, carry a collision-resistant run ID, and
are summarized from the exact run evidence by `scripts/summarize_generation_telemetry.py` when the
CLI is run from a Vocello checkout (skipped when `--telemetry off` or repository tools are absent).

| Option | Meaning |
|---|---|
| `--modes` / `--variants` / `--lengths` | strict comma-list matrix axes: `custom,design,clone` / `speed,quality` / `short,medium,long`; empty, unknown, or duplicate values fail before runtime bootstrap |
| `--warm` | warm reps per (cell × length); default 3 |
| `--voice` / `--voice-brief` | clone voice name / design brief |
| `--confirm-consent` | required when `clone` is in `--modes`: confirms you own or have permission to clone the saved voice |
| `--delivery [list]` | add **instruct-bearing delivery cells** (Custom/Design, warm, medium text, 1 take each): comma list of `<preset>[.<intensity>]` values (e.g. `happy.strong,calm.normal`); the bare flag runs `happy.strong,calm.strong,whisper.strong`. Rows are stamped `notes.delivery` and summarized in their own block; the plain warm takes double as the neutral reference for prosody/delivery A/Bs. Prosody analysis selects only WAVs named by the current run manifest and runs before the final summary. Delivery evidence remains inside the parent engine-generation record. |
| `--label <opaque-id>` | stamp a privacy-safe identifier using only letters, numbers, `.`, `_`, and `-` |
| `--run-id <id>` | supply a collision-resistant run ID for orchestration; normal invocations mint one automatically |
| `--force-class` | **dev/diagnostic only** — force a constrained memory tier on any Mac: `8gb` · `16gb` · `high` · `iphone` (sets the `QWENVOICE_FORCE_MEMORY_CLASS` knob, read in-process by the engine; stamps `notes.deviceClass`) |
| `--telemetry` | `off` · `lightweight` · `verbose` (default; raw per-sample sidecars). `off` builds no recorder, sampler or sink and writes no engine row even though the bench's runtime overrides set `QWENVOICE_DEBUG=1`; `verbose` sizes the sidecar budget to the planned generations and refuses a plan above 256 |
| `--seed` | deterministic sampling seed applied to every benchmark take |
| `--no-stream` | accumulate the full result before decoding (old bench behavior) |
| `--ttfc` | add an engine first-chunk-latency probe per cell → table + `bench-ttfc.json` in the diagnostics directory |
| `--keep` / `--force` | append to existing diagnostics / allow clearing even the real app data dir |
| `--data-dir` / `--manifest` | override the runtime data dir (default: the debug-isolated folder) / the `qwenvoice_contract.json` path |
| `--no-summary` | skip the aggregator and standalone registry publication because a parent diagnostic/profile lane owns evidence and publication; do not use for a normal standalone benchmark |

**Streaming by default.** `vocello bench` runs the streaming path by default, so its
memory numbers match the iOS/app streaming reality. Streaming takes drain `engine.events`
and disable inline preview PCM (`QWENVOICE_STREAMING_PREVIEW_DATA=off`) so long matrices
do not retain chunk events across takes. Pass `--no-stream` to run the old accumulate-then-decode
behavior for comparison.

**What it measures.** Engine truth — RTF, decode, memory, per-stage GPU, and the `audioQC` verdict.
It does **not** capture the app's submit-to-first-chunk or submit-to-playback-scheduled timing, nor
the merged 3-layer telemetry row; those exist only in the real app process topology. CLI rows also
have no delayed-heartbeat coverage because there is no UI process, so the summarizer's
`UI heartbeat` column shows `—` for bench runs. `--ttfc` adds an *engine-side* first-chunk probe (a
warm streaming take per cell, run after the matrix and excluded from its frozen summary selection)
— distinct from app playback scheduling, which is not proof of acoustic audibility.

**Preflight.** Before running, `bench` fails fast if any requested `(mode × variant)` model isn't
installed (listing the missing ids), and fails if `clone` is in `--modes` but the saved voice
(`--voice`, default `A_warm_elderly_woman`) is absent or `--confirm-consent` is missing.
Prerequisites: the requested models installed; a saved clone voice and `--confirm-consent` when
clone is in the matrix.

The deterministic `audioQC` gate runs for every benchmark take. `--delivery` additionally runs the
paired delivery-prosody analysis before aggregation. The standalone
`scripts/prosody_quality_gate.py` per-clip check runs only when invoked explicitly.
Engine promotion is autonomous: required cells must have clean audioQC plus the applicable
fixed-seed language/prosody evidence. Optional listening may be recorded later, but cannot clear a
machine failure or warning and never blocks ordinary development publishing.

**History publication.** A successful, telemetry-enabled benchmark in a repository checkout emits
an atomic `benchmark-evidence.json`, publishes one allowlisted record under
`benchmarks/runs/engine-generation/`, and regenerates `benchmarks/HISTORY.md`. It never stages,
commits, or pushes. Failed/incomplete runs and `--telemetry off` diagnostics do not modify tracked
history. Records are validated against benchmark schema v3 (`vocello bench` takes carry the quality-registry
identity; v1 stays read-only), must declare
`run.rtfDefinition` (`rtf` = wall ÷ audio, lower is faster) and take `toolchain.optimization` from
the build receipt: the macOS publisher accepts only a `scripts/build.sh cli-optimized` receipt whose
digest matches the executed binary, so a record from an -Onone `cli` build, an unreceipted binary
or a rebuilt one is refused; see [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md).
When the CLI runs outside a
checkout it retains local WAVs and the immutable per-run `bench-results.json` under
`diagnostics/benchmark-runs/`, skips unavailable repository summary/history
tools without turning a successful generation into a failure, and prints the retained manifest path.
If publication alone fails, rerun the printed idempotent
`python3 scripts/benchmark_history.py record --artifact-dir <dir>` repair command.

### Collected codec replay (internal diagnostics only)

`bench --codec-replay <startup-reliability-take.json> --take-sha256 <sha256>
--codec-trace <codec-trace-v1.bin> --output-dir <new-untracked-directory>` reuses the
startup-reliability replay API on the Mac without generating text or downloading models.
It requires an internal-diagnostics binary and `QWENVOICE_DEBUG=1`. The original v2
CustomVoice Speed receipt and trace digest/shape/chunk boundaries are validated. Every installed
model file must match the pinned catalog bytes, including the receipt's tokenizer digest.
Source and local manifest digests are recorded separately: installation timestamps and older
revision metadata can differ even when all model bytes match. The output directory must not exist;
source artifacts remain untouched, partial results survive failure, and no benchmark history
is published.

The original replay field named `full` is the **production non-streaming 25-frame decoder
schedule**, not an independent implementation or a whole-sequence decoder call. The Mac result
names it `productionNonStreaming` and records this distinction. `replay_complete` means the
diagnostic finished; the separately recorded audio QC may still fail. No replay result alone
establishes a sampled-model pathology or authorizes a product/model/QC change.

### Codec round trip (internal diagnostics only)

`bench --codec-roundtrip <job.json> --output-dir <new-untracked-directory>` resynthesizes the job's
digest-bound mono PCM16 24 kHz WAVs through the installed Voice Cloning Speed model's speech
tokenizer, on one model load. Like the replay, it needs an internal-diagnostics binary and
`QWENVOICE_DEBUG=1`, binds the model to the pinned catalog bytes and refuses an existing output
directory.

### Codec loop (internal diagnostics only)

`bench --codec-loop <job.json> --output-dir <new-untracked-directory>` builds codec-loop takes:
each job item names a recorded codec trace by digest and one loop recipe (a span of frames repeated
right after itself, or the untouched trace as the sham). It verifies every trace
and recipe before loading, binds the installed CustomVoice Speed model to the pinned catalog bytes,
writes each mutated trace, decodes it through the codec replay's full arm (the production
non-streaming 25-frame schedule) and writes the PCM16 through the production output limiter, then
applies the publication marking once the model is unloaded. Like the replay, it needs an
internal-diagnostics binary and `QWENVOICE_DEBUG=1` with telemetry on, and refuses an existing output
directory.

## Examples

```sh
# Built-in Voice, speed, save to a path
vocello generate --mode custom --variant speed --text "The train left at dawn." --out /tmp/clip.wav

# Pipe a script in, stream it, get the JSON envelope with first-chunk latency
echo "Hello there." | vocello generate --variant speed --text - --json

# Voice Design from a brief
vocello generate --mode design --voice-brief "A warm, calm narrator" --text "Once upon a time…"

# Bulk: one model load for many lines
vocello batch --file lines.txt --mode custom --variant speed --out-dir /tmp/batch

# Discover what's available (instant — no engine boot)
vocello speakers list
vocello models list
vocello models install pro_custom_speed   # headless; shared with the app

# One-command benchmark: forced 8 GB tier, labelled; PASS publishes an exploratory record
vocello bench --modes custom --variants speed --lengths short,medium,long --warm 3 \
              --label "my-change" --force-class 8gb
```

## See also

- [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md) — the telemetry schema, the bench
  matrix in depth, autonomous `audioQC`/language/prosody gates, and optional listening annotation.
