---
status: active
owner: release-qa
reviewed: 2026-11-15
summary: What the interrupted Mac and CLI 3.1 release run of 2026-11-14 showed, each issue's cause as far as it was traced, and the decisions and work left before RF-61's gate can pass.
sourceOfTruth:
  - config/roadmap.json
  - docs/development-progress.md
  - benchmarks/runs/ui-perf/macos-xcui-perf-20261114-193957-54115c9c.json
---
# The interrupted 3.1 release run: what it showed (RF-61)

The maintainer stopped the Mac and CLI 3.1 release work on 2026-11-14 and asked on 2026-11-15 what
went wrong. This is an investigation only: nothing in the product changed. Evidence comes from the
retained run folders, the tracked records and three new headless measurements on the M6 at
`28b4aa25` (a development build of `vocello`, so no timing is read from them).

## Summary

| # | Issue | Verdict | Blocks 3.1? |
|---|---|---|---|
| 1 | The UI benchmark failed on a refused Voice Design take | A rare model ending, refused as designed; the benchmark has no way to pass it | Yes, until decided |
| 2 | Filtering History stalls the window for up to 873 ms | A real regression since September, cause not yet traced | Maintainer's call (it fails "flawless") |
| 3 | The delivery menu drops more frames than in September | Inside its ceiling, 19% worse | No |
| 4 | Half the UI benchmark never ran | Voice Design medium and long and all of Voice Cloning are unmeasured in the app | Yes (evidence missing) |
| 5 | The run itself was rough | Three avoidable tool mistakes, one missing local tool, lanes that take over the screen | No, but fix the method |

Playback and the streaming preview were clean wherever they were measured: the twelve takes that
completed had no underrun, no continuity failure, at least 320 ms of audio queued at all times, and a
longest main-thread delay of 189 ms against the 600 ms stall limit.

## 1. The refused take

**What happened.** Take 13 of the UI benchmark (`design/short/warm#1`: "The train left the station at
dawn.", the benchmark's narrator brief, Neutral delivery, seed 13240896822931298179) spoke its
sentence and then kept producing silence instead of ending. After 3 s the engine stopped it and
Fast QC v10 refused it (`terminal_silence:3425ms`). The app showed "Generation failed", as designed
(ICA-15: never trim, regenerate or substitute a seed).

**It is the model, at this seed.** The same request on the command line is refused every time on
the hybrid. It is refused with streaming off too, so the preview path is not involved. It is refused
with `QWENVOICE_TALKER_FILTER_EOS=off` as well (whether the key took effect was not confirmed from
the take's provenance). The 3.0 Speed model at the same seed gives a clean 1.92 s take, and 3.0
Quality a clean 2.4 s take.

**It is rare.** Sixty other seeds of the same request, run on both models:

| | Takes | Refused | Longest trailing silence |
|---|---|---|---|
| Hybrid | 60 | 0 | 466 ms |
| 3.0 Speed | 60 | 0 | 918 ms |

With RF-55's single-take screen (144 hybrid takes, none refused) that is 0 refusals in 204 hybrid
takes outside the benchmark's seed, so the rate is probably under 1.5%. The 3.0 Speed model had its
own refusals in that screen (2 of 144). The hybrid is not worse than what shipped; the benchmark's
fixed seed for this cell happens to be one of the bad ones.

**Why it blocks.** The benchmark's seeds are derived from each cell (`cell-hash-v1`), so this cell
fails on every run with the hybrid. The lane publishes nothing when a take fails, so it yields no
record for the README charts, the website numbers or the promotion evidence.

**A second defect, in the harness.** In measured lanes the benchmark waits only for the player, so
a refused take costs a 120 s timeout and reads as "timed out", not as "refused by the audio check".

**Options (the maintainer's decision).**

- **A. New seeds for the new model's lineage.** Move the benchmark to a `cell-hash-v2` policy, declared
  before the rerun, and keep this run's refusal on record. The hybrid starts a new benchmark lineage
  anyway. One rule should go with it: if a v2 cell is refused too, the result stands and the seeds
  do not move again.
- **B. Let the benchmark record a refusal.** A refused take becomes a counted outcome (not timed, the
  run continues), and the lane fails only above a stated number of refusals. This is the more honest
  design, since a refusal is a product outcome the app handled correctly; it is also a harness change
  that needs its own tests.
- **C. Change what the app does with such a take.** ICA-15 says to keep refusing. Changing it would
  mean one of: trimming trailing silence when the speech before it is complete, or a visible
  automatic retry with a new seed. Either alters accepted output and needs a screen with its rule
  recorded first.

Recommended: A now, with the fast failure fix (the benchmark should say "refused" at once), and B
or C as later work if refusals matter to you beyond the benchmark.

## 2. History filter stalls

The UI-performance lane's `history-filter` scenario (400 seeded rows, type a query, clear it, three
times) is exploratory, so no ceiling judged it, and the lane passed. Against the three calibration
runs of 2026-09-27 on the same Mac:

| | Sept 27 (three runs) | Nov 14 |
|---|---|---|
| Hitch time | 124 to 126 ms/s | 201 ms/s |
| Longest frame gap | 464 to 474 ms | 873 ms |
| Main-thread delays over 250 ms | 6 | 18 |
| Longest main-thread delay | 413 to 439 ms | 830 ms |

A user filtering a long History sees the window freeze for most of a second. The scenario's 400-row
tree also carries accessibility cost that the harness adds, which is why it is exploratory, but that
cost was the same in September: the doubling is real.

**Cause: not traced.** Paging is not it (it landed on 2026-09-24, before the calibration, and 400
rows fit one page, so the filter runs in memory as before). The History screen changed in these
candidates since: the move of view models to `@Observable` (`1406ebaf`, October 18),
`NonisolatedNonsendingByDefault` (`50af9a6d`, October 19, which moves unmarked async work onto the
caller's actor), the recovery work of October 6 to 14, and macOS 26B131 with Xcode 27B52. One
Instruments time profile of the scenario would name it.

## 3. Delivery menu

Ten open-and-close cycles of the delivery menu: 80.9 ms/s of hitch time against 67 to 70 in
September, under the 89 ceiling, with the 95th-percentile frame gap at 23 ms where it was 16.7. The
cost is even across the ten cycles, so it is the menu's own animation, not a load. The footprint
warning on this scenario is a model warm at the window's last half second and is harmless. Worth
profiling together with issue 2; not a blocker.

Everything else in the lane held or improved: idle, Settings scrolling, typing in the composer and
window resizing are at or under September's numbers, and frame health while a take generates is
better (61 ms/s against 75 to 104).

## 4. What was never measured

The benchmark stopped at take 13 of 29. Voice Design medium and long, and every Voice Cloning take,
have no app-level playback, stall or capture evidence on 3.1. Also not run: the full smoke lane
(fifteen journeys, playback among them), `release-readiness`, `scripts/dev.sh ci`, the engine bench
against the new baseline, the static audits of the release diff, the README charts and the
website's performance numbers.

## 5. Why the run was rough

- **Tool mistakes (mine, each cost a restart).** A shell loop passed two options as one argument; the
  speed lane was given `--variants both`, which the bench does not accept (the help text said it did;
  fixed); the UI benchmark was started detached, so its end had to be watched by hand.
- **Playwright's browsers are not installed on this Mac,** so the website's browser tests cannot run
  locally. The built-in browser pass covered them once; installing the browsers is a download that
  needs the maintainer's word. CI runs them on every push.
- **UI lanes take over the Mac.** The perf and benchmark lanes launch the app, move focus and capture
  the screen for many minutes (the benchmark's desktop screenshot captured other windows too; it is
  local and untracked). They are best run while the Mac is not in use.
- **The run was long and serial:** about five hours of lanes before the first failure, with the most
  failure-prone lane (the UI benchmark) near the end.

## Recommended order from here

1. Decide issue 1 (A, B or C). Nothing else in the gate can finish before it.
2. Profile the History filter and the delivery menu once (Instruments, the perf lane's own
   scenarios), fix what the profile names, and rerun `ui_test.sh macos perf`.
3. Make the benchmark report a refused take at once instead of timing out.
4. Then, in one unattended sitting with the Mac free: the UI benchmark first (it fails most often),
   the full smoke lane, `release-readiness`, `scripts/dev.sh ci`, the engine bench, the charts.
5. The static audits and the release notes' final numbers, then the maintainer's push and tag.

## Evidence

- UI benchmark: `build/artifacts/ui-tests/macos/macos-xcui-benchmark-20261114-195242-cfbe3925`
  (failed; retained locally) and the app's engine and frontend rows for its thirteen takes.
- UI performance: `benchmarks/runs/ui-perf/macos-xcui-perf-20261114-193957-54115c9c.json` against
  the three records of 2026-09-27.
- Seed reproduction and the 60-seed comparison: headless `vocello design` runs of 2026-11-15, local
  diagnostics, not benchmark evidence.
