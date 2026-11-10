---
status: active
owner: release-qa
reviewed: 2026-11-10
summary: Read-only audit, on 2026-11-10 at 232a0bcb, of the README, CLAUDE.md, the agent skills and agents, CONTRIBUTING, SECURITY and every active document under docs/ for inaccurate, stale and duplicated statements, each checked against source. It changes no document; every fix waits for the maintainer.
sourceOfTruth:
  - CLAUDE.md
  - README.md
  - docs/reference/development-workflow.md
  - docs/reference/ios-appstore-submission.md
  - docs/ARCHITECTURE.md
  - config/roadmap.json
---
# Documentation audit (2026-11-10)

Source: `main` at `232a0bcb`. The maintainer asked for an audit of the README, the documentation,
the instructions and `CLAUDE.md` for inaccurate, stale or duplicated content. Nothing was changed.

## 1. Verdict

The documentation is in better shape than its size suggests. About 22,000 lines were checked and
most checkable claims hold: counts, sizes, dependency pins, memory bands, commands, flags, hooks,
skills and identifiers all match source. The defects cluster in three places:

1. **The release documents lag the candidate.** They describe build 29, and the public release
   notes still say the iPhone beta runs 2.4.
2. **`CLAUDE.md` is stricter than the decision it summarizes,** and it credits guards and
   permissions with protection that comes from somewhere else.
3. **The same procedure is written out in several places.** 61 duplicated groups were found, and
   14 of them already disagree.

## 2. Method and limits

- **Mechanical pass (lead):** every backticked path, every roadmap-style ID and every `reviewed:`
  date in 53 documents. All paths resolve; the 128 raw hits were generated-artifact names and
  shorthand paths. The IDs unknown to the roadmap (`IOS-06` to `IOS-23`, `BG-1`) are finding IDs
  from earlier audits.
- **Three read-only checkers** compared the instructions, the product and platform documents, and
  the engine and measurement documents against source, scripts' help text, the roadmap and git
  history. The lead re-checked each leading finding below against source.
- **Not checked:** timing figures, benchmark numbers, translation quality, the dated documents
  under `docs/audits/` and `docs/decisions/`, and the website's page copy.
- Nothing was built or run.

## 3. Inaccurate

### Instructions

| Where | It says | What is true |
|---|---|---|
| `CLAUDE.md:119-120` | Anything outside the release plan becomes a parked line "with no investigation", and work outside the plan needs the maintainer's word | `focusLock.decision` in `config/roadmap.json`, the authority, says backlog items that need no iPhone "stay authorized (2026-10-16): each is closed in the change that fixes it", and that Mac-only requests follow as items of the plan |
| `CLAUDE.md:115` | "the lock's dated decision records the current cap" | The decision text states no cap; the cap is only `focusLock.maxInFlight: 3` |
| `CLAUDE.md:136-140` | A read-only side session shares the main checkout, and `agent_guard.py` screens agents and side sessions | The guard screens only calls that carry an agent ID or come from a linked worktree (`scripts/hooks/agent_guard.py:5-7`). A session in the main checkout passes straight through; only its brief restrains it |
| `CLAUDE.md:187-188`, `development-workflow.md:588` | Permissions deny non-main pushes and hand-made branches | The deny rules cover specific push forms and `checkout -b`, `switch -c` and `worktree add`. `git push origin <other>` is only asked and `git branch <name>` has no rule; the `policy_guard.sh` hook refuses both |
| `CLAUDE.md:186`, `development-workflow.md:581-583` | External writes, GitHub included, ask first | The six ask rules name `mcp__claude_ai_Github__*`, which matches none of the connector's tools in the desktop app (already parked as BKL-62) |
| `.claude/skills/vocello-ui-autonomy/SKILL.md:11` | Read `development-workflow.md` (Computer use) | That document has no such section; the content is a bullet under "The Claude desktop app" (line 688) |

### Product and platform documents

| Where | It says | What is true |
|---|---|---|
| `ios-appstore-submission.md:221-222` | The disk check uses the full catalog total even when components can be reused | It uses only the bytes still to fetch (`Sources/iOS/IOSModelDownloadCoordinator.swift:160-189`, since `64ff7f86`). `model-delivery.md:205-208` has it right. The 4.5 GB advice stays safe |
| `macos-app-guide.md:203-209`, `macos-release-qa.md:278-281` | Mac Settings has four categories | There is a fifth, Updates, with a Check for Updates button (`Sources/Views/Settings/MacSettingsScreen.swift:24`, since 2026-10-20) |
| `ios-app-guide.md:640-641, 682-684` | Only the `model-download` lane changes model state | `smoke --scenario update-models` and the candidate `first-launch` row also install models |
| `quality-promotion.md:24-25`, `ios-appstore-submission.md:330` | Build 26 joined the Public Beta under a one-time waiver | Builds 26 and 27 did (RF-17's notes, and the same runbook's lines 29-30) |
| `ios-appstore-submission.md:68-69` | The version's train holds builds 24 to 26 | Builds 27, 28 and 29 were uploaded too |
| `README.md:79` | "Quality is a Mac option for 16 GB or more" | Quality installs on any Mac and shows a "Heavy" badge on smaller ones; line 75 and the release notes say "recommended" |
| `website/PRODUCT.md:28` | Models & Files is the Mac category; Voice Models is the iPhone's | The iPhone also has Models & Files, with Voice Models inside it |
| `macos-release-qa.md:373` | The What to Test heading's exact form | The release notes use a different heading; the checker matches only its start |

### Engine and measurement documents

| Where | It says | What is true |
|---|---|---|
| `telemetry-and-benchmarking.md:2149-2151` | Fast QC's dropout rule: pauses of 350 ms count against the punctuation budget and an excess fails as `dropout:excessN`; a single gap fails at 1,200 ms | `dropout:excess` counts suspicious-scale pauses (900, 1,200 or 1,500 ms by regime). Too many 350 ms pauses only warns, as `cadence:excessN`. A gap fails at 1,200 ms only without declared pauses under 45 s, otherwise at 2,000 ms (`Sources/QwenVoiceCore/GenerationOutputAdapter.swift:3069-3076`, `3165-3243`) |
| `ARCHITECTURE.md:204` | SPM dependencies are declared in `project.yml` | mlx-swift-lm and swift-transformers are declared only in `Packages/VocelloQwen3Core/Package.swift:34,43`. `mlx-guide.md:538-545` has it right |
| `ARCHITECTURE.md:340` | `ClonePreparationState` is an enum with payloads | It is a struct with a phase, an identity key and a message |
| `performance-guide.md:176` | A `Task {}` from a main-actor context hops off the main thread | It inherits the main actor, and since `50af9a6d` nonisolated async functions also stay on the caller's actor unless marked `@concurrent` |
| `qwen_tone.md:51` | "neutral" and "default" drop the instruction | The synonyms are empty, "normal tone", "neutral" and "neutral tone" (`Sources/QwenVoiceCore/EmotionPreset.swift:139-147`) |
| `performance-guide.md:14, 87, 95` | Three `project.yml` line citations | Each is four lines later since `0f203210` |

## 4. Stale

| Where | It says | Since |
|---|---|---|
| `docs/releases/v3.0.0.md:6-7, 103-106` | The iPhone's 3.0 "follows in the coming days"; until then the beta runs 2.4 | The public beta has run 3.0 since 2026-10-26. The README links this file twice |
| `docs/releases/v3.0.0.md:174-178` | What to Test text for build 24 | The runbook makes this section the paste source for every build; the candidate is build 30 |
| `ios-appstore-submission.md:28-32` | Build 29 is the App Review candidate | RF-41 and RF-42 need a new candidate; the build number is 30 |
| `app-store-listing.md:123` (also live in App Store Connect) | Review notes step 2: tap Install | Build 30 shows a "Download <mode>?" alert first. Update the notes when build 30 is attached |
| `privacy-storage.md:278, 297, 333` | ASR-06's procedure names build 29 and "tap Install, lock the phone" | Same two changes |
| `model-delivery.md:443-445` | The model-download lane starts a transfer directly | Every start now passes the confirmation |
| `ios-device-testing.md:1052` | The newest canonical records are build 26's | Records exist for builds 28 and 29 |
| `performance-guide.md:91`, §3 | The targets rely on Swift 6 language mode alone | Strict memory safety, NonisolatedNonsendingByDefault and two more features are on since 2026-10-19 |
| `qwen3-tts-guide.md:538-545`, `mlx-guide.md:306-310`, `qwen3-tts-prompting-guide.md:54-57` | Which changes stop a seed reproducing a take | All three omit `9cd075bd` (RF-21); the prompting guide also omits `c62390d6` |
| `ios-built-in-startup-reliability.md:19-21, 156-172` | A closure plan built on six seeds and their outcomes | Four later sampling and text-layout changes mean those seeds no longer reproduce the takes; the document carries no warning |
| `ios-increased-memory-entitlement-request.md:128, 146` | Without the entitlement the app reports critically low headroom before model admission | RF-40 ran 41 takes at a 2.52 GB peak on an iPhone 15 Pro without it |
| `ARCHITECTURE.md:322-327` | The `GenerationRequest` field list | Missing `longFormSegment` |
| `ARCHITECTURE.md:1463`, `ios-appstore-submission.md:12, 211` | Link `ios-engine-optimization.md` and `eu-ai-act-article50-assessment.md` as current guidance | Both are marked `status: historical` |
| `development-workflow.md:175-189` | The toolset "as of 2026-11-02" | The session's tools include plugins and connectors the list lacks |
| `.claude/skills/vocello-ui-autonomy/SKILL.md:50-51` | Typing has not reached the phone "until the first-window probe settles a method" | Two Mirroring windows have run since; the outcome was never recorded |

**Review dates behind their content:** `ios-app-guide.md`, `ios-appstore-submission.md`,
`app-store-listing.md`, `content-rights-review.md`, `privacy-storage.md` and `quality-promotion.md`
say 2026-10-28 and `ios-device-testing.md` 2026-11-02, with substantive edits after each;
`qwen_tone.md` says 2026-09-21. `native-engineering.md`, `tooling-and-evidence.md` and `qc.md` have
a status and no review date. `macos-ios-ui-reset-2026-09.md` reads `active` for a finished plan.

## 5. Duplicated

61 groups: 30 in the instructions, 20 in the product documents and 11 in the engine documents.

### Copies that already disagree

| Content | Copies | Difference |
|---|---|---|
| iPhone model install flow | `ios-app-guide.md:448-535`, `model-delivery.md:308-316, 436-470`, `app-store-listing.md:123`, `privacy-storage.md:331-336`, `v3.0.0.md:184, 194` | Only the app guide has the download confirmation |
| Free-space admission | `ios-appstore-submission.md:220-225`, `model-delivery.md:205-208` | Full catalog total against bytes still to fetch |
| Builds under the RF-17 waiver | `ios-appstore-submission.md:29-30`, `:330`, `quality-promotion.md:24-25` | "26 and 27" against "26" |
| Required screenshot size | `ios-appstore-submission.md:235-241`, `app-store-listing.md:149-150` | One hedges on the 6.5-inch size, the other doesn't |
| What to Test paste source | `ios-appstore-submission.md:351-353`, `macos-release-qa.md:373-376`, `v3.0.0.md:174` | Heading form and build number |
| Distinct-delivery group order | `v3.0.0.md:84`, `ios-app-guide.md:190, 574`, `website/PRODUCT.md:14`, `app-store-listing.md:62` | Only `website/PRODUCT.md` has the picker's real order |
| Model download states | `ios-app-guide.md:450-458`, `model-delivery.md:310-311` | The second lacks Incomplete and Update available |
| Seed-reproducibility breaks | three engine guides (section 4) | All incomplete, and different from each other |
| Where dependencies are declared | `ARCHITECTURE.md:204`, `mlx-guide.md:538-560` | Section 3 |
| Fast QC thresholds | `telemetry-and-benchmarking.md:2140-2160` against source | The only copy with numbers is wrong |
| Run verdict classes | `testing-runbook.md:67`, `vocello-xcresult-triage.md:31-32`, `vocello-debug/SKILL.md:14` | Three different lists |
| Playwright install | `website/CLAUDE.md:15`, `development-workflow.md:106` | `--with-deps` against none; CI uses it |
| Diagnostics gating | `CLAUDE.md:161-162`, `native-engineering.md:62-63`, `vocello-swift-review.md:17-18` | The agent omits `QWENVOICE_DEBUG` |
| Dates of the computer-use decision | `CLAUDE.md:151-152`, `development-workflow.md:593`, `vocello-ui-autonomy/SKILL.md:12` | Three different dates |

### Copies that agree today

`CLAUDE.md` says the reference documents own the detail, yet it restates eight blocks of
`development-workflow.md` nearly in full: the agent and side-session rules (130-142), computer use
(150-157), worker tracking (192-194), the desktop-app rules (195-199, 215-217), tool routing
(207-214), the command list (84-102), the hook list (182-191) and the permission summary (185-189).
The computer-use rules appear in six files and the Fast QC against QC v2 distinction in five.
`cli.md` states five times that the CLI writes no History. Sampling values and parity arms are in
five engine documents, and the per-tier memory policy in four. All of these agree with source
today; each is a place the next change must be made several times.

## 6. Recommendations

Nothing below has been started.

### Before build 30 is submitted

1. Update `ios-appstore-submission.md`'s current-state paragraph and build list for build 30.
2. Add the download confirmation to review notes step 2, in `app-store-listing.md` and App Store
   Connect, when build 30 is attached (an App Store Connect write, on the maintainer's go).
3. Update ASR-06's procedure in `privacy-storage.md` for build 30 and the confirmation.
4. Refresh `docs/releases/v3.0.0.md`: the iPhone paragraphs and the What to Test section. Decide
   first whether published notes are frozen, since `macos-release-qa.md:377` says they are.
5. Correct the free-space sentence and the waiver builds in the runbook.

### Instructions, small and safe

6. Align `CLAUDE.md`'s release-focus bullets with `focusLock.decision`, or change the decision if
   the stricter rule is the intended one. This is the maintainer's call: the two disagree about
   what an agent may do without asking.
7. Say in `CLAUDE.md` and `development-workflow.md` that the hooks, not the permission rules,
   refuse non-main pushes and hand-made branches, and that a main-checkout side session is not
   screened.
8. Give the three verdict-class lists one owner and make the other two point to it.
9. Fix the skill's "Computer use" pointer and record the typing probe's outcome.

### Engine documents, after the submission

10. Rewrite the Fast QC dropout paragraph from `makeAudioQCReport`, or replace its numbers with a
    pointer to the code.
11. Correct `ARCHITECTURE.md:204` and `:340`, `performance-guide.md`'s concurrency section and the
    three seed lists; keep one seed list and link to it.
12. Add a warning to `ios-built-in-startup-reliability.md` that its seeds predate four sampling
    changes, and mark the two historical documents as historical where they are linked.

### Structure

13. Cut `CLAUDE.md`'s eight restated blocks to a rule and a pointer each. It would shrink by about
    a third, and the reference document would become the only place to edit.
14. Give each duplicated procedure one owner: the install flow in `ios-app-guide.md`, the storage
    rule in `model-delivery.md`, the candidate's state in the checkpoint.
15. Add `reviewed:` to the three documents without it, and refresh the dates that trail their
    content when each document is next corrected.
