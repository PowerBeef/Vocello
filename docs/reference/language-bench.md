---
status: active
owner: backend-mlx
reviewed: 2026-09-12
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

The paired Custom pinned/Auto cells intentionally generate the same prompt with the same speaker
and sampling policy; the shared resolved prompt digest proves that Auto resolves equivalently to the
pinned hint. Since seed identity v2 (2026-09-25) the Auto cell draws its own seed, so its audio is an
independent sample rather than a byte copy of the pinned take. Likewise, the three sequential Speech recognitions prove that the
on-device recognizer reproduced one transcript for one WAV. They do not provide three statistically
independent accuracy observations. The 18 positive output cells (plus the expected-fail negative
control) remain strict per-cell multilingual smoke acceptance, not a population estimate of
language quality.

## iOS (on-device)

Requires Built-in Voice and Voice Design **Speed** installed on the paired iPhone.

**Speech Recognition (app):** Phase 3 transcribes each output WAV in the app process; after the run
the Mac adds the whisper family over the collected `output.wav` files (`scripts/independent_asr.py`),
and the publisher requires the two families to agree (`languageVerification.families:
["apple-speech", "whisper"]`). Grant
**Settings → Privacy → Speech Recognition → Vocello** once before the first output-gated run.

### Phase 3 prerequisites (on-device Speech assets)

Output verification runs three sequential recognitions of the exact generated WAV using
**on-device Speech** in the deterministic locale of each cell. All three final transcripts must
agree before WER/CER is scored. EN/FR work out of the
box; **DE, ES, ZH, JA** need system dictation languages and downloaded voice assets on the
phone. Authorization denied, recognizer unavailable, missing on-device support, timeout, engine
error, inconsistent transcripts, or failed WER/CER are distinct machine failures; none is replaced
with a fabricated score or a listening judgment.

The versioned accuracy contract uses **WER ≤ 0.15** for languages with word boundaries and
**CER ≤ 0.15** for Chinese and Japanese; both scores and both word/character edit-count
decompositions remain evidence. The Python gate and history publisher independently recompute the
metrics from the tracked corpus and untracked consensus transcript before accepting the Swift
verdict.

Since 2026-09-25 the contract is `segmentation-aware-edit-rate-v2` (audit #43; the maintainer
delegated the decision to the audit's recommendation). The word gate no longer charges a
recognizer's word-boundary choice as errors: the alignment may pair a block of one to four reference
words with a block of one to four hypothesis words at no cost when both spell the same characters
and one side holds two or more words (a merge such as "vor Mittag" heard as "Vormittag", a split, or
a moved boundary). Every other edit keeps its v1 cost, and a merge of five or more words is charged
as before. Takes publish `segmentationAwareWordErrorRate` and `wordBoundaryOnlyEdits` (the plain
edits the v2 alignment credited) per family (`independent…` for whisper) beside the unchanged v1
`wordErrorRate`, and `primaryAccuracyScore` is the v2 rate for word languages; the character rate is
the same under both versions. Swift (`VoiceClipTranscriber.segmentationAwareWordMetrics`) and
`scripts/lib/language_metrics.py` share the operation set and parity fixtures; the minimum is unique,
so they agree exactly. Records published before carry `normalized-edit-rate-v1` and keep validating
under it. Replayed offline over the 38 committed scored takes: the three German cells (WER 0.138,
CER 0.0, 2 substitutions and 2 deletions, so two character-identical merges of at most four words)
score 0.0 under v2; no passing take can change verdict because the v2 distance never exceeds the v1
distance; the two macOS accuracy controls (WER 0.5625) need their transcripts, which are not
committed, so the next lang-bench measures them under v2. The app's `languageASR` quality gate
reports the rate its outcome reads since gate composition 5 (the v2 word rate as `word_error_rate`,
or the character rate as `character_error_rate`; through version 4 it reported the v1 word rate),
and the delivery cascade records the `accuracyMetricVersion` it scored each recognition under.

Each family's alignment also yields `longestDeletionRun`, the longest run of consecutive reference
units the recognizer deleted on the primary metric's units (a match, substitution or insertion ends
a run; the Swift verifier and `scripts/lib/language_metrics.py` share the tie-broken path and parity
fixtures). It is warn-only: a skipped phrase of two to four words stays under the 15 % gate on the
corpus's 17-32-unit scripts, so a run of two or more on a take that must pass publishes the take with
`language.deletion_run:<family>` and never changes a verdict or the accuracy contract.
Published as `longestDeletionRun` (Apple Speech, recomputed and checked against the app's value) and
`independentLongestDeletionRun` (whisper). Replayed over the committed records, no passing take can
carry a run of two: the only takes with two deletions are the German cells, whose zero CER makes
every word error a two-word compound merge.

The host checker also enforces the app's existing **outer-edge** timing rule whenever the
verification declares `sourceAudioDurationSeconds` or the record includes WAV `outputEvidence`:
all three recognitions must start within `min(2.5, max(1.0, duration × 0.15))` seconds of the
beginning and end within that allowance of the end, without exceeding the duration by more
than 0.25 seconds. Supplied durations must be positive, finite and mutually consistent. Missing
timings, invalid durations or incomplete edges cannot authorize a claimed PASS. The VLR composer
classifies this as a harness/evidence gap, preserving already typed incomplete-coverage results.
Legacy reports lacking both duration fields retain historical validation; they are not fresh
full-WAV proof. Edge coverage does **not** establish interior completeness or waive WER/CER.
Independent recognizers disagreeing on the same WAV remain diagnostic evidence; never choose
the better score, substitute their transcripts, or relabel a retained failure automatically.

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
quick/full matrices use seed identity v2 (`seedPolicy: sha256-v2-mode-script-language-auto-63bit`;
audit #86 part 2, the maintainer delegated the decision to the audit's recommendation on
2026-09-25): a pinned cell keeps its v1 seed per mode/script language, and an Auto cell draws its own
seed, so Auto is an independent sample. The pinned and Auto Custom cells of one script still share
the resolved prompt assembly, and every gate (`check_language_hints.py`, `check_language_output.py`,
the publisher) requires the members of a prompt-equivalence group to share that digest whatever
their seeds: the prompt, not the audio, proves Auto resolution. Every take publishes
`output.fileDigest` (macOS from the engine's WAV digest since 2026-09-25, iOS from the sentinel), and
group members that share a seed (a diagnostic cohort's pinned and Auto takes at one explicit seed)
must publish one digest (audit #86 part 1; the committed iOS records' eight groups replay
identical). The iOS rerun that shows the Auto takes' own verdicts is the part-3 device run. The plan also freezes the corpus-owned Custom speaker and one shared Design delivery
instruction; the shared Design fixture keeps language as the controlled variable and preserves one
typed fixture identity for the model across the matrix.
The diagnostic cohort is seed-major and evaluates exactly three cells across five fixed
seeds (15 takes). It performs no retry and never publishes benchmark history. Whisper runs for the
cohort too (recognition rows are keyed by the take's child run ID, so a cell repeated across seeds
is five distinct rows), and `independent_asr.py verdict` combines each take's whisper verdict with
its in-app Apple Speech verdict through the shared family rule: the cohort passes only when the two
families agree on every take's expected outcome (`witnesses=apple-speech,whisper consensus=pass`),
disagreement is `inconclusive` and fails the lane, and a cohort run without the in-app pass is
labelled `one-witness` rather than reported as consensus (audit #44). A whisper recognition the
publisher would refuse (a truncated decode, an empty transcript, uncovered edges) is no witness:
its take is `unqualified`, which fails the lane whatever the take's expected outcome, so a broken
decode never confirms a negative control.

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

Each family's language check observes something different, and records say so (audit #42):
`evidence.languageVerification.languageCheckKinds` declares `transcript-language-consistency` for
Apple Speech (text language detection over a transcript produced with the recognizer locked to the
expected locale, close to unfalsifiable for an anglicized take) and `audio-language-identification`
for whisper (detection from the first 30 s of audio). Each language take publishes the language each
family detected in `detectedLanguages`. On the negative control an English-locked whisper hears
English and passes its language check; the control fails on accuracy alone.

Consensus is per channel (audit #42; the maintainer delegated the decision to the audit's
recommendation on 2026-09-25). A verdict has a `language` channel and an `accuracy` channel, and
`scripts/lib/language_metrics.py` `channel_consensus` votes each one separately through the family
rule, so two families that fail a take for different reasons no longer read as agreement and a
channel the families split on is `inconclusive`. A take that must pass needs both channels to pass
by consensus; the negative control is re-declared an **accuracy control**: it must fail the accuracy
channel by consensus, and its language channel is reported only. A two-family record publishes each
scored take's `channelConsensus` (`pass`, `fail` or `inconclusive` per channel) and the run's
`languageVerification.channelVerdicts` (a channel is `pass` when every take that constrains it
reached its expected status) with `channelConsensusAlgorithm: per-channel-family-consensus-v1`, and
a run with a control declares `negativeControlKind: accuracy-control`. The history validator
recomputes both from the per-family verdicts the takes publish. The cohort verdict
(`independent_asr.py verdict`) applies the same rule and prints each take's channels. A second
acoustic language detector would be research, not part of this rule.

### Validation and diagnostic snapshot (through 2026-07-16)

The table below is preserved as dated operational evidence; it is not the current acceptance
state. Current PASS evidence must exist in `benchmarks/runs/language/` and appear in generated
`benchmarks/HISTORY.md`, while the active resume status lives in
[`../development-progress.md`](../development-progress.md). The current tracked registry contains
a clean physical-iPhone quick PASS record covering the seven EN/FR cells, historical macOS
hint-only records, the exploratory full PASS described below, and a later dirty-worktree macOS
full run (`mac-lang-bench-20260902-024501-bd2df074`, partial, exploratory). Generated
`benchmarks/HISTORY.md` is the authoritative list. Run
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

Negative control `custom-fr-text-en-pinned` carries `expectedOutcome: "fail"`: the pinned English hint
is sent over a French script, synthesis still speaks French today, and the cell passes only when the
English-locked output verification ran and failed on accuracy (an accuracy control since
2026-09-25; before, a failed language check alone also confirmed it). A verification that passes
means the model started honoring the pinned hint; a skipped verification is not a confirmed
control. Before 2026-09-12 this cell was hint-only and never measured its output. In a published
record the control's take carries `expectedOutcome: "fail"` (a schema-v3 take key) and
`scripts/benchmark_history.py` inverts its accuracy gate: the take is evidence only if its
verification failed, and the stamped takes must match `negativeControlsConfirmed`.

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

The lane writes the same immutable `language-run-plan.json` the iPhone lane follows
(`scripts/language_bench_evidence.py plan`) and generates its takes in order (audit #88, the
maintainer delegated the decision to the audit's recommendation on 2026-09-25): each Custom take
speaks with its script language's corpus speaker (`vocello generate --speaker`, for example `vivian`
for Chinese and `ono_anna` for Japanese) and each Design take with the corpus's one Voice Design
brief (`--voice-brief`), at the plan's seed-identity-v2 seed (`--seed`, `--variation expressive`,
`--language` for a pinned hint). Until then the lane spoke every language with the default speaker
and a lane-owned brief, so macOS and iPhone takes were not comparable. The engine row names its
Custom speaker (`notes.customSpeakerID`) and its Design brief's digest (the typed fixture digest),
and the publisher (`--plan`) refuses a macOS verification whose rows do not match the plan's seed,
variation and fixture, or that has no plan. Each Custom and Design row also carries
`notes.resolvedPromptAssemblyDigest`, the request-resolved prompt digest the iPhone sentinel records
(one definition, `GenerationSemantics.promptAssemblyDigest`): the Auto take draws its own seed, so
the publisher proves Auto resolution on the Mac by requiring every member of a prompt-equivalence
group to carry that digest and share it; the plan's fixtures and seed policy enter the analysis
profile. The hint gate reads `~/Library/Application Support/QwenVoice-Debug/diagnostics/` with
`QWENVOICE_DEBUG=1`. Apple Speech is **not**
available to the CLI (TCC). Spoken content is instead verified after every CLI process has exited by
`scripts/independent_asr.py`: the pinned `whisper-small` MLX model
(`config/delivery-evaluator-v2-candidates.json`, `whisper-small-mlx`) is loaded and warmed once in a
supervised subprocess (`scripts/independent_asr_worker.py`, whose digest alone is the recognizer's
cache and provenance identity; the cache holds the worker's raw result and the producer derives each
recognition from it on every read, and takes with byte-identical audio and one language share one
decode), decodes each take with the language locked to the expected language,
detects the language from the first 30 s, and reports what it measured: the decoded sample count (the
processed duration the publisher checks against the WAV), the per-take recognition time without model
load or warm-up (`modelLoadSeconds` and `warmupSeconds` are reported once per launch; the language
lineage's measurement version is 3 since WER v2, the per-channel vote, the Auto seed, the corpus
fixtures and the macOS prompt digest, none of which a published record carries yet) and whisper's worst no-speech probability and
mean log probability, published as `independentMaximumNoSpeechProbability` and
`independentMeanAverageLogProbability`. The publisher re-scores every transcript against the corpus with the same
15 % edit-rate gate (whisper-small's character error rate on Chinese and Japanese sits close to that
gate, so treat those verdicts as real evidence, not noise; recognizer or metric changes go into
`scripts/lib/language_metrics.py`, never its consumers). The recognizer never runs while the engine
is resident. The record is `focused` with `languageVerification.families: ["whisper"]`: one
independent witness, explicitly not a two-family consensus. The recognizer is prepared from the local
Hugging Face cache by `scripts/prepare_delivery_compact_model_config.py whisper-small-mlx`; nothing
downloads automatically. `scripts/lib/language_metrics.py` also accepts `sensevoice` as a family
identifier (the compact-model cascade's SenseVoice adapter, limited to English, Chinese, Japanese,
Korean and Cantonese); publication today cites only `apple-speech` and `whisper`.

## Offline gate tests

```sh
python3 -m pytest scripts/tests/test_check_ios_speech_assets.py scripts/tests/test_check_language_hints.py scripts/tests/test_check_language_output.py
# or, after editing a gate: scripts/dev.sh py
```

## Related

- Phase 1 unit tests: `scripts/macos_test.sh core-test`
- Language semantics: `docs/reference/qwen3-tts-guide.md` §7
- iOS device lanes: `docs/reference/ios-device-testing.md`
