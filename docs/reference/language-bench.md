---
status: active
owner: backend-mlx
summary: The Phase 2-3 language bench — hint-contract and on-device output verification matrices, subset semantics, Speech asset prerequisites, and how to read hint_gate/output_gate verdicts.
sourceOfTruth:
  - scripts/check_language_hints.py
  - scripts/check_language_output.py
  - config/language-bench-matrix.json
---
# Language bench (Phases 2–3)

Headless matrix for the Qwen3 language path:

1. **Phase 2 — hint contract:** UI hint → resolved `notes.languageHint` in engine telemetry.
2. **Phase 3 — output verification:** three-pass locale-locked on-device Speech consensus,
   language score, WER/CER, and exact fixed-seed WAV proof vs script.

## Config

| File | Role |
| --- | --- |
| `config/language-bench-corpus.json` | Versioned scripts plus Custom speaker and Design delivery fixtures per language |
| `config/language-bench-matrix.json` | Cells: mode, `uiHint`, `scriptLang`, `expectedHint` |
| `config/language-bench-diagnostic-cohort.json` | Fixed cells and five predeclared seeds for autonomous failure diagnosis |

Cells tagged `"quick": true` form the **quick** subset (English + French + negative control, 7 cells).
**full** runs all 19 cells (6 languages × Custom pinned/Auto + Design explicit-language + negative).

The version-2 corpus is deliberately longer than the original smoke snippets: each alphabetic
script contains at least 15 normalized words and each Chinese/Japanese script contains at least 24
normalized characters. Design always receives the known target language explicitly. Custom uses a
native-language speaker where the Qwen speaker contract provides one (Chinese `vivian`, Japanese
`ono_anna`); the remaining languages use the contract's stable `aiden` fixture.

The paired Custom pinned/Auto cells intentionally generate the same prompt with the same speaker,
seed, and sampling policy. They prove that Auto resolves equivalently to the pinned hint; they are
not independent audio samples. Likewise, the three sequential Speech recognitions prove that the
on-device recognizer reproduced one transcript for one WAV. They do not provide three statistically
independent accuracy observations. The 18 output cells remain strict per-cell multilingual smoke
acceptance, not a population estimate of language quality.

## iOS (on-device)

Requires Built-in Voice and Voice Design **Speed** installed on the paired iPhone.

**Speech Recognition (app):** Phase 3 transcribes each output WAV in the app process. Grant
**Settings → Privacy → Speech Recognition → Vocello** once before the first output-gated run.

### Phase 3 prerequisites (on-device Speech assets)

Output verification runs three sequential recognitions of the exact generated WAV using
**on-device Speech** in the deterministic locale of each cell. All three final transcripts must
agree before WER/CER is scored. EN/FR work out of the
box; **DE, ES, ZH, JA** need system dictation languages and downloaded voice assets on the
phone. Authorization denied, recognizer unavailable, missing on-device support, timeout, engine
error, inconsistent transcripts, or failed WER/CER are distinct machine failures; none is replaced
with a fabricated score or a listening judgment.

The versioned `normalized-edit-rate-v1` accuracy contract uses **WER ≤ 0.15** for languages with
word boundaries and **CER ≤ 0.15** for Chinese and Japanese; both scores and both word/character
edit-count decompositions remain evidence. The Python gate and history publisher independently
recompute the metrics from the tracked corpus and untracked consensus transcript before accepting
the Swift verdict.

**One-time setup (on the iPhone — Settings app, not Vocello):**

1. **Keyboards:** Settings → General → Keyboard → Keyboards → Add keyboard — e.g.
   Allemand, Espagnol, Japonais (Romaji), Chinois simplifié (Pinyin QWERTY).
2. **Dictation languages:** Settings → search *dictée* → **Langues de Dictée** — enable
   Allemand, Espagnol, Japonais, Mandarin (and any variants listed for your locale).
3. **Explicit asset bootstrap:** With the unlocked phone on Wi‑Fi, run
   `scripts/ios_device.sh speech-assets`. Vocello resolves the device-supported equivalents for
   `de_DE`, `es_419`, `ja_JP`, and `zh_CN`, creates DictationTranscriber modules, checks
   AssetInventory before and after one combined `downloadAndInstall()` request, and requires every
   resolved locale to report installed. The command also prints a separate
   `vocello_legacy_gate` verdict from fresh SFSpeechRecognizer instances and the same deterministic
   locale-selection policy used by the output verifier.
4. **Interpret both results:** `asset_inventory=PASS` proves the modern assets installed.
   `vocello_legacy_gate=PASS` is additionally required by the current Phase 3 verifier. If the
   modern gate passes but the legacy gate remains blocked, do not claim language readiness or run
   the full matrix as promotion evidence; preserve the local diagnostic result and investigate the
   OS-level legacy recognizer state.
5. **Re-run** once both are ready:
   `scripts/ios_device.sh lang-bench --subset full --label "lang-full-output-v3"`.

Settings remains useful for confirming enabled Dictation languages, but the explicit command owns
asset installation and machine verification. This is an operational prerequisite, not a subjective
audio review.
Vocello UI expectations remain documented in [`ios-ui-reference.md`](ios-ui-reference.md).
Language-benchmark labels are opaque privacy-safe identifiers matching
`[A-Za-z0-9][A-Za-z0-9._-]{0,95}`; they are not free-form notes.

```sh
scripts/ios_device.sh lang-bench --subset quick --label "lang-smoke"
scripts/ios_device.sh lang-bench --subset full --label "lang-full"
scripts/ios_device.sh lang-bench --diagnostic-cohort
```

Skip output verification (hint gate only):

```sh
QVOICE_LANG_BENCH_SKIP_OUTPUT=1 scripts/ios_device.sh lang-bench --subset quick
```

Per cell the driver sets:

- `QVOICE_IOS_DEVICE_RUN_ID` — shared run id (`ios-lang-bench-…`)
- `QVOICE_MAC_BENCH_CELL` — matrix cell id
- `QVOICE_IOS_DEVICE_DIAGNOSTICS_LANGUAGE` — language hint (`english`, `french`, …; omitted for Auto)
- `QVOICE_IOS_DEVICE_DIAGNOSTICS_SPEC` — `mode:speed:<script>`
- `QVOICE_IOS_DEVICE_DIAGNOSTICS_VERIFY_OUTPUT=1` — Speech round-trip (default unless skipped)
- `QVOICE_IOS_DEVICE_DIAGNOSTICS_SEED` — immutable UInt64 from the pre-generation plan
- `QVOICE_IOS_DEVICE_DIAGNOSTICS_VARIATION=expressive` — explicit sampling policy

Before the first launch, the driver atomically writes `language-run-plan.json` with one-based take
indexes, child run IDs, cells, prompt-equivalence groups, seeds, and sampling variation. Normal
quick/full matrices use one stable seed per mode/script language; pinned and Auto Custom cells for
the same script intentionally share both prompt assembly and seed so the hint is the controlled
variable. The plan also freezes the corpus-owned Custom speaker and one shared Design delivery
instruction; the shared Design fixture keeps language as the controlled variable and preserves one
typed fixture identity for the model across the matrix.
The diagnostic cohort is seed-major and evaluates exactly three cells across five fixed
seeds (15 takes). It performs no retry and never publishes benchmark history.

Gates:

- `scripts/check_language_hints.py` — exact plan-selected `engine/generations.jsonl`, including
  run/cell/generation/seed/variation and resolved prompt-assembly correlation
- `scripts/check_language_output.py` — exact plan-selected `device-diagnostics-done.json` →
  `outputVerification`, exact WAV SHA/metadata, and structured three-pass recognition evidence

The device sentinel is schema v2 and is written last as a completion barrier. The collector copies
only the plan-selected engine/app rows, their verbose sidecars, the exact `output.wav`, and bounded
manifests into the untracked run artifact. It verifies the WAV digest, byte/frame/channel/sample-rate
metadata, generation identity, and unique ordering; it never summarizes the phone's historical
diagnostics tree. Raw transcripts and audio remain untracked.

After both requested gates pass, the runner automatically publishes one privacy-safe `language`
record under `benchmarks/runs/language/` and regenerates `benchmarks/HISTORY.md`. A run made with
`QVOICE_LANG_BENCH_SKIP_OUTPUT=1` is recorded as `partial` and excluded from normal timing trends.
Failed cells, missing typed telemetry/model identity, or a publication error leave the tracked
registry unchanged; the untracked artifact directory retains the idempotent repair command.
Passing the diagnostic cohort prints its verdict locally and intentionally creates no record.

### Validation and diagnostic snapshot (through 2026-07-16)

The table below is preserved as dated operational evidence; it is not the current acceptance
state. Current PASS evidence must exist in `benchmarks/runs/language/` and appear in generated
`benchmarks/HISTORY.md`, while the active resume status lives in
[`../development-progress.md`](../development-progress.md). The current tracked registry contains
a clean physical-iPhone quick PASS record covering the seven EN/FR cells, historical macOS
hint-only records, and the exploratory full PASS described below. Run
`ios-speech-assets-20260716-164115-e8b16d82` resolved `de_DE`, `es_ES` (for requested `es_419`),
`ja_JP`, and `zh_CN`; every DictationTranscriber asset and Vocello's legacy on-device recognition
gate passed. That result establishes prerequisites only.

| Run | Subset | Hint gate | Output gate | Notes |
| --- | --- | --- | --- | --- |
| `ios-lang-bench-20260706-110143` | quick | **7/7 PASS** | — | Hint only (pre–Phase 3 output) |
| `ios-lang-bench-20260706-112319` | quick | **7/7 PASS** | **6/6 PASS** | Locale-locked ASR + stored `pass`; negative control hint-only |
| `ios-lang-bench-20260706-135146` | full | **19/19 PASS** | **7/18 FAIL** | DE/ES/ZH/JA `transcription_failed` — Speech Wi‑Fi assets pending on device |
| `ios-lang-bench-20260714-134925-3e73b43d` | full | **19/19 PASS** | **10/18 FAIL** | Assets ready; exposed an out-of-range language-score producer bug and genuine failures in the original short corpus. No history record was published. |
| `ios-lang-cohort-20260714-143612-f5e99664` | bounded DE/ZH/JA diagnostic | **6/6 PASS** | **6/6 PASS** | Retry-free validator/corpus-v2 confirmation after adding CJK punctuation to the deterministic pause budget. Diagnostic only; no history record was published. |
| `ios-lang-bench-20260714-145013-304721d6` | full | **19/19 PASS** | **13/18 FAIL** | Corpus-v2 evidence localized remaining fixed-seed failures to French Custom and all three German paths. No history record was published. |
| `ios-lang-bench-20260714-153252-d2a3eea5` | full | **not evaluated** | **not evaluated** | Intentionally interrupted while take 7 was launching after six completed takes. No final gates or history record exist; this local partial run is not acceptance evidence. |
| `ios-lang-bench-20260716-164248-1ecf8361` | full | **19/19 PASS** | **18/18 PASS** | Fresh physical-iPhone corpus-v2 acceptance with zero diagnostic failures and three-pass locale-locked ASR. `passedWithWarnings` for accepted Spanish Custom written-output/dropout evidence and soft memory trims; tracked as exploratory because the runtime worktree was dirty. |

Negative control `custom-fr-text-en-pinned` is **hint-only** (`skipOutputVerification`) — pinned
English hint is sent, but synthesis still speaks French for a French script today.

The version-2 corpus, explicit Design language, native-language Custom fixtures where available,
stricter validator correlation, and CJK-aware punctuation pause accounting address the defects
exposed by the July 14 attempts. The bounded DE/ZH/JA cohort confirms those paths. Four subsequent
retry-free cohorts exercised the revised French and German scripts at the exact normal-matrix seeds:
French Custom pinned/Auto and Design all passed strict QC with zero WER, while German Custom
pinned/Auto and Design passed strict QC at approximately 0.138 WER. The later partial full run was
intentionally stopped and cannot be resumed or promoted. The July 16 fresh full run reproduced
those results inside the complete 19-cell matrix and passed every automated gate; because it was
recorded from a dirty worktree, a future clean comparable baseline must start from a committed
revision. A failed, incomplete, or diagnostic run correctly creates no tracked history and cannot
be replaced by this dated table or a listening judgment.

## macOS (in-process CLI)

Requires test models (`scripts/macos_test.sh models ensure`).

```sh
scripts/macos_test.sh lang-bench --subset quick
```

Uses `QWENVOICE_DEBUG=1`, `vocello generate --language …`, and the hint gate against
`~/Library/Application Support/QwenVoice-Debug/diagnostics/`. CLI Speech is **not** used
(TCC); output verification is available through the iOS device-diagnostics lane only. Successful
macOS hint-only evidence is therefore explicitly `partial` in benchmark history.

## Offline gate tests

```sh
python3 -m unittest scripts.test_check_ios_speech_assets
python3 scripts/test_check_language_hints.py
python3 scripts/test_check_language_output.py
```

## Related

- Phase 1 unit tests: `scripts/macos_test.sh core-test`
- Language semantics: `docs/reference/qwen3-tts-guide.md` §7
- iOS device lanes: `docs/reference/ios-device-testing.md`
