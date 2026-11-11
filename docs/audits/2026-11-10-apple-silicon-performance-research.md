---
status: active
owner: backend-mlx
reviewed: 2026-11-10
summary: Read-only research into the runtime's speed and memory on Apple silicon: what bounds a frame on each device, what the pinned MLX does on these chips, what other MLX and Core ML ports of Qwen3-TTS measured, and ranked levers with the measurement that decides each; nothing was built, run or changed.
sourceOfTruth:
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSTalker.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSCodePredictorCompiled.swift
  - Packages/VocelloQwen3Core/Package.swift
  - Sources/QwenVoiceCore/NativeMemoryPolicyResolver.swift
  - Sources/QwenVoiceCore/IOSMemorySnapshot.swift
  - benchmarks/OPTIMIZATION.md
  - docs/audits/2026-10-16-engine-runtime-audit.md
  - config/roadmap.json
---
# Runtime speed and memory on Apple silicon: research report

**Date:** November 10, 2026. **Baseline:** `b7b414d0`. **Requested by** the maintainer: an
exhaustive analysis of the core runtime, then research into every way to raise generation speed and
cut memory by using Apple silicon well, with findings and recommendations.

**Method.** Read-only. The project was paused and its Mac in use for other work, so nothing was
built, run or measured for this report; every figure comes from a retained record named beside it,
from arithmetic on those records and the code, or from an outside source. The lead read the
generation loop, the talker, the compiled code predictor and the pinned MLX Metal backend
(mlx-swift 0.32.3) and tabulated the retained benchmark records. Three read-only agents surveyed the
code and the repository's own evidence; three more researched MLX, the Apple platform and other
implementations of Qwen3-TTS from primary sources. Two further agents then tried to overturn the
claims without seeing the ranking (section 12). The report recommends; it changes no code, model
or dependency.

**The maintainer's decisions while it was being written shaped it.** The repository's rules are
open to change where that makes the project better, so every collision with a standing rule is
judged on the evidence (section 1.2). The core overhaul is performed before the iOS App Store
submission and the target dates are removed from the roadmap (`8cb98059`), so the work is ordered by
gates and section 6 designs the larger change. And the result must be absolutely App Store
compliant, so section 8 checks every recommendation against the App Review Guidelines.

## 1. Verdict and decisions requested

### 1.1 Verdict

**The runtime is already close to what this model allows on a fast Mac.** The M6 generates a frame
in 19 ms, about what Qwen's technical report implies for its own server engine's language-model
time per frame (21 ms, a derived figure) [R6]. The repository's earlier programme took the cheap wins
and recorded what failed. What is left is narrower, and four parts of it are new to the repository.

1. **A frame has two costs, and they need different levers.** One is fixed overhead: 2,500 to 2,900
   tiny kernels, the command buffers that carry them, and the host work between. The other is the
   GPU reading about 1.5 GB of quantized weights per frame. On the 8 GB M2 they are about equal. The
   split is not known on any other device, and it decides everything below (section 2).
2. **MLX's submission settings have never been tuned for this workload.** MLX commits a command
   buffer every 20 operations on a phone, 120 to 140 commits per frame, and twice as often per frame
   as on a Mac; the phone's records show exactly twice the context switches. MLX's own tracker
   reports 8 to 17% from larger buffers on launch-heavy models. It is one setting, and the output
   stays bit-identical (A1).
3. **The loop waits where MLX's own loops do not.** It reads each token back before building the
   next frame; mlx-lm and mlx-swift-lm build the next step first. The gain from changing that is
   capped by MLX itself at about 8% of a phone frame until the buffers are larger, and the change
   has traps the verification found (A3). It sets no wired limit, so MLX's residency sets stay
   empty; that lever may cost as much as it saves (A2).
4. **The neural accelerators in the A19 and M5 families do not touch the talker or the code
   predictor.** MLX uses them only for products of many rows. Those two are one row, bound by memory
   bandwidth, as Apple says of language models. The accelerators can serve the prompt and the
   float32 codec decode. The chips therefore differ here mostly by bandwidth and heat (F).

**On memory:** the iPhone's budget is 6,144 MB, not the 8,192 MB the documents assume, and the peak
is half of it. One identity-safe saving of about 330 MB exists: reading the prompt's rows of the text
embedding from the file (E2). Memory-mapped weights, which would take 1.4 GB off the footprint, are
not possible in MLX and its maintainers have declined them (E3).

**On the iPhone 15 Pro:** nothing recorded explains why it is three times slower than the iPhone 17
Pro when rested and five to six times when hot, no iPhone 15 Pro has run the shipped build, and its
steady state is set by heat. The identity-safe levers will help its first takes. They are not
expected to bring its settled speed to real time (section 6).

**One known finding gains weight here.** On the newest chips the shipped app runs float32 matrix
products at reduced precision while the owned parity tests switch that off (audit finding F-17,
section 9). That path includes the watermark, which the App Review notes promise, so it should be
checked before any submission (section 8.5).

**The larger change the cards add up to** is a frame pipeline: the frame's state kept on the GPU,
compiled samplers, the code predictor as one function per frame, a few command buffers per frame,
and a batch axis from the start (section 6). Its identity-preserving stages produce the same samples
as today by proof, which matters because nobody listens: they are the part that can go into the
first App Store version without any judgement about audio.

**On App Store compliance:** every recommendation uses public API and in-bundle code and passes
(section 8). The one guideline this work can actually break is 2.4.2, on heat: generation is never
paused for the thermal state today, and a long-form project can hold an iPhone 15 Pro hot for half
an hour. The report recommends a pause between long-form segments at the serious state.

**What not to do, on the evidence and not because a rule says so:** move to Core ML or the Neural
Engine (J); move the MLX pin for speed (I2); lower the code predictor's precision (C2); re-enable
Game Mode for memory (E1); adopt the sustained-execution entitlement (G4); re-test the compiled
talker step first (K1).

### 1.2 Rules: which to change and which to keep

| Rule today | What it protects | What the evidence says | Recommendation |
|---|---|---|---|
| Batched decode is set aside (decision of 2026-06-11) | Single-take reproducibility; a simple loop | The same model on MLX: 1.6 times the throughput at batch 2, 2.3 at batch 4, 3.8 on a batched long-form take, for 0.1 GB (D) | **Change.** Reopen it for Mac long-form and line batches, after phase 1 is measured |
| A pinned seed reproduces its take; a change needs a release-note line | Reproducibility of saved takes | Two ports measured about 30% from one compiled predictor frame with in-graph sampling, which changes the random stream (B5). The seeds already changed once, at the move to MLX 0.32.3 | **Change when measured.** Accept one seed change in a release for a measured double-digit gain, if keeping the stream proves impractical |
| MLX is pinned to exact upstream releases; no fork | Supply-chain identity; one tested substrate | Upstream declined patches that help small, launch-bound models: removing the per-operation completion handler measured 31% on one (I3). The run-time commit limits are merged and unreleased | **Change if phase 0 says so.** Allow an owned fork at an exact revision with a short reviewed patch list, as the Qwen3 package already is a fork. Not before A1 is measured |
| MLX is the only backend; no Core ML | One numerics path, one artifact chain | For the 1.7B model every Core ML port is slower, larger or Mac-only, and two hit half-precision overflow (J) | **Keep**, on the evidence |
| The iPhone is Speed (4-bit) only | Memory and speed | 8-bit costs 40% per frame where bandwidth binds (section 2.2). It would fit the 6,144 MB budget | **Keep** for speed. Whether 12 GB iPhones should offer Quality is a quality question outside this report |
| Game Mode is opted out (RF-37) | App Review; no banner | It probably costs 2 GB of limit the app does not use (E1); no measurable speed | **Keep** |
| No hard MLX memory limit; no talker KV window or quantization; no compile with quantized parameters as inputs; no pipelining of the predictor's passes | Stability and exact sampling | Nothing new contradicts the recorded results (section 4) | **Keep** |
| Nobody listens; machine screens only | The maintainer's time | Word-error rate alone can hide a loss of naturalness (I1) | **Keep**, and note its cost: any sample-changing lever needs a screen with speaker similarity and a naturalness measure, or it cannot be cleared |
| The iPhone 15 Pro is the floor | Reach | It is the one device slower than real time, and it has never run the shipped build | **Keep until measured** (G5, M8) |
| Nothing outside the release plan before the submission; dated items | The November 12 target | The candidate is qualified once, on the build that carries the overhaul | **Changed on 2026-11-10.** The maintainer removed the dates and decided that the core overhaul precedes the iOS submission (section 6.3) |
| No prebuffer or memory-policy change for 3.0 (BKL-53, 2026-11-02) | A frozen candidate | The overhaul now precedes the submission; the prebuffer is the largest delay a listener perceives (H1) and the per-chunk clears cost speed (A5) | **Change**, as part of the overhaul |
| Memory is request-local; every production-affecting environment key is a registered diagnostic | Isolation between takes; no hidden switches | A wired limit is process-wide (A2); MLX's buffer limits are environment keys (A1) | **Keep both**, with two named exceptions: a wired limit raised only while a take runs, and buffer limits set in code as constants |
| Generation is never paused for heat (a recorded choice awaiting a maintainer decision) | Speed under load | Guideline 2.4.2 and Apple's advice at the serious state (section 8.3) | **Change.** Pause between long-form segments, never inside a take |

### 1.3 Decisions requested

| # | Decision | Recommendation |
|---|---|---|
| 1 | Keep the Game Mode opt-out and take 6,144 MB as the iPhone budget | Yes: Apple's support staff say a non-game that enables Game Mode will be rejected, and the peak is half the budget |
| 2 | How to treat the reduced-precision finding | One parked backlog line whose first step is M1, a few minutes on the Mac. The retained takes argue against a gross defect |
| 3 | Whether to obtain an 8 GB iPhone for the floor measurements | Yes: nothing else can measure the overhaul's effect on the floor device with the entitlement |
| 4 | Whether to reopen batching for long-form and line batches | Yes, as a Mac feature after phase 1: the evidence on MLX is direct (D) |
| 5 | On phones slower than real time, pauses in the preview (today) or a later start with none | A product choice; the engine supports either |
| 6 | Whether a quantization experiment is wanted at all | Only if the phones prove bandwidth-bound, and then the talker MLP, never the code predictor |
| 7 | Whether Vocello may carry an owned, exactly pinned MLX fork | Only if phase 0 shows a large fixed share after A1; first re-propose the patch upstream with Vocello's numbers |
| 8 | Whether a measured double-digit gain may change every pinned seed | Yes, once per release, with the release-note line the rule already asks for |
| 9 | The overhaul precedes the submission (decided 2026-11-10). Which stages it includes | Stages 0, 1, 2a, 3 and 4 as its core; the sample-changing stages 2b, 5 and 6 after the first approval unless the maintainer wants them in (section 6.3) |
| 10 | Whether long-form pauses for heat between segments | Yes (section 8.3) |
| 11 | The roadmap's dates | Removed on 2026-11-10 at the maintainer's instruction (`8cb98059`). Section 6.2 maps the stages onto the roadmap's items |

## 2. Regime per device

### 2.1 Evidence grades

Every figure and claim in this report carries one of four grades.

| Grade | Meaning |
|---|---|
| **M** | Measured on that device and build, in a retained record named beside it |
| **A** | Analog: measured on another device, another build or another project |
| **C** | Computed: arithmetic from the code or from retained figures |
| **U** | Unverified: stated by a source I could not check, or a hypothesis |

Speed is `rtf`, synthesis time over audio length, lower is faster (the convention since
2026-09-12). `benchmarks/OPTIMIZATION.md` uses the inverse for everything before that date; where
this report quotes it, the figure is converted and marked.

### 2.2 What the retained records say

Warm takes, medium and long cells, medians. A take produces 12.5 codec frames per audio second.
Frames per second is the token loop's own rate; `rtf` covers the whole request (prompt, decode and
finalization), so the two differ by 8 to 10%.

| Device, OS, build | Frames/s (loop) | ms per frame (loop) | `rtf` (whole request) | Process CPU per wall second | Kernel share of CPU | Context switches per frame |
|---|---|---|---|---|---|---|
| iPhone 17 Pro (A19 Pro), iOS 27.2, build 29 | 25.7 to 27.2 | 37 to 39 | 0.505 to 0.534 | 0.54 to 0.57 | 42 to 43% | 690 to 740 |
| Mac mini M6 16 GB, CLI gate bench, MLX 0.32.3 | 51.8 | 19.3 | 0.266 | 0.55 | 33% | 356 |
| Mac mini M6 16 GB, app matrix, MLX 0.31.6 | 49.6 to 51.9 | 19.3 to 20.2 | 0.263 to 0.282 | 0.61 to 0.68 | 25 to 33% | 367 to 421 |
| Mac mini M2 8 GB, Speed (4-bit), `-O` | 23.9 to 25.1 | 40 to 42 | 0.548 to 0.582 | 0.50 to 0.52 | 37 to 39% | 333 to 401 |
| Mac mini M2 8 GB, Quality (8-bit), `-O` | 17.1 to 17.5 | 57 to 58 | 0.767 to 0.792 | 0.48 to 0.50 | 34 to 36% | 347 to 399 |
| iPhone 15 Pro (A17 Pro), farm, exploratory | about 8 rested, 6 settled, 4 hot (derived from `rtf`) | about 120, 176, 240 (derived) | 1.5 to 1.6, 2.2, 2.8 to 3.2 | about 0.58 | not recorded | not recorded |

Grade **M** for the first five rows. Records, all under `benchmarks/runs/`:
`ui-generation/ios-xcui-benchmark-20261103-181710-c657e53a.json`,
`engine-generation/mac-gate-bench-20261017-004417-cfef80fb.json`,
`ui-generation/macos-xcui-benchmark-20261007-015814-74f026be.json`,
`engine-generation/mac-custom-speed-20260919-044142-5f7862eb.json` and
`mac-design-speed-20260919-044402-da647d43.json`,
`engine-generation/mac-custom-quality-20260919-044236-41a53bcc.json` and
`mac-design-quality-20260919-044511-f9914b60.json`. The columns come from each cell's
`cpuUserSeconds`, `cpuSystemSeconds`, `requestWallSeconds`, `contextSwitches` and `generatedTokens`.

The iPhone 15 Pro row is grade **A**: BrowserStack farm runs of a re-signed diagnostics build
without the increased-memory entitlement, on a phone in a rack on a charger, summarized in the notes
of RF-40 and BKL-53 (`config/roadmap-archive.json`). No iPhone 15 Pro has run
the shipped build, and no iPhone 16 Pro has run Vocello at all.

### 2.3 Five readings

**1. The generation thread sleeps about half the time on every measured device (C, from M).** The
loop is single-threaded and the whole process, with its interface, audio and completion threads,
uses 0.5 to 0.6 of one core. The sleeping half is the wait for the GPU. It happens in two places: the
token read after each frame (`Qwen3TTS.swift:4092`), and inside MLX whenever more than ten command
buffers are in flight, where `eval` stops and waits for one to finish (`transforms.cpp:25`,
`transforms.cpp:271-282` in the pinned MLX).

**2. The context switches follow MLX's command-buffer commits, not the cache clears (C, from M).**
The phone shows twice the context switches per frame of either Mac: 690 to 740 against 333 to 421.
MLX commits a command buffer once it holds more than 20 operations on a phone and more than 40 on a
base or Pro Mac chip (`backend/metal/device.cpp:511-514`, `:603-611`). The ratio of two is the
evidence: it matches the commit limits, and nothing else that differs between the phone and the
Macs was found to explain it. If a frame is the 2,500 to 2,900 operations that reading the code
gives (section 3.1), that is about five context switches per commit on both; the two figures are
not independent, so this is a consistency check and not a measurement of either. BKL-53's note
calls the phone's kernel time, context switches and page faults "consistent with the unmeasured MLX
cache clears". The records point elsewhere. Both Macs here also clear the cache on every chunk
(`NativeMemoryPolicyResolver.swift:46-65`), the M6 every 4 frames against the phone's 7 or 14, and
they show half the switches; warm takes take only 9 to 30 page faults per frame.

**3. A third or more of the CPU time is spent in the kernel (M).** Per frame of request time that
is 10.3 ms of 42 on the iPhone 17 Pro, 8.8 ms of 45 on the M2 and 3.9 ms of 21 on the M6. A frame
makes 120 to 140 commits on the phone and 60 to 70 on a Mac (C, from the limits and the operation
count). If all the kernel time were commits, which it is not, a commit would cost 67 to 88, 115 to
155 and 49 to 78 microseconds of it.

**4. On the M2, a frame is about half fixed overhead and half weight bandwidth (C, from M).** The
M2 is the only device with both tiers recorded. A frame reads every quantized weight of the talker
once and of the code predictor fifteen times:

| | Parameters | At 4-bit (4.5 bits with scales and biases) | At 8-bit (8.5 bits) |
|---|---|---|---|
| Talker, 28 layers and the head | 50.3 M per layer | about 0.80 GB per frame | about 1.50 GB |
| Code predictor, 5 layers plus projection and head, 15 passes | 82.8 M per pass | about 0.70 GB per frame | about 1.32 GB |
| **Per frame** | | **about 1.5 GB** | **about 2.8 GB** |

A talker layer is q and o at 2,048 by 2,048, k and v at 2,048 by 1,024, and gate, up and down at
2,048 by 6,144; a code-predictor layer is the same shape at a hidden size of 1,024 with a 3,072
intermediate size (`docs/reference/qwen3-tts-guide.md` sections 3.1 and 3.4;
`Qwen3TTSTalker.swift:143-151`). The code predictor's head size of 128 is the code's default
(`Qwen3TTSConfig.swift:96`), not read from the shipped `config.json`, so its figure is grade **C**.

Fitting `frame time = fixed + bytes / bandwidth` to the two tiers (41 ms at 1.5 GB, 58 ms at 2.8 GB)
gives about 22 ms fixed and about 78 GB/s effective bandwidth. So on the M2 about 47% of a Speed
frame is the GPU reading weights and at most 53% is everything that does not scale with bytes:
launches, commits, host work and decode. The ledger's 49% GPU-busy figure
(`benchmarks/OPTIMIZATION.md` section M) is of the same order, but it came from an unoptimized
build on an older MLX and measures a different quantity, so it is not a confirmation. Where the fit
breaks: two points fit any line, the 8-bit kernel may also cost more per weight than the 4-bit one,
and the split is known on no other device.

At the measured speeds the weight reads alone are about 36 GB/s on the M2, 39 GB/s on the iPhone
17 Pro and 77 GB/s on the M6. Real time needs about 19 GB/s.

**5. Nothing recorded explains why the iPhone 15 Pro is so much slower than the iPhone 17 Pro (U).**
By `rtf` it is about three times slower when rested, more than four when settled and five to six
when hot. Section 5, F, gives the hardware ratios; they are far smaller than
that. The candidates, none measured: weight bandwidth through the A17 Pro's GPU (at real time the
loop needs about 19 GB/s of weight reads alone); the GPU's power governor holding a low performance
state under a load that is idle half the time; the diagnostics build's telemetry; and the farm
phone's charging heat. Section 7 lists the measurement that separates them.

### 2.4 The regime, per device

| Device | Bound by | Grade | What it means for the levers |
|---|---|---|---|
| M2 8 GB | Half fixed overhead, half weight bandwidth | C from M | Launch and commit levers should pay. The ledger's one data point, +26% from 600 fewer launches, was measured on an unoptimized build; the optimized build ran the same cell about 60% faster (ledger J), so the elasticity there is unknown |
| M6 16 GB | Probably mostly weight bandwidth | U | One data point: the move to MLX 0.32.3 added about 80 launches per frame and `rtf` stayed at 0.265 to 0.266 (`docs/reference/mlx-guide.md`, section 9), but that move changed more than the launch count |
| iPhone 17 Pro | Unknown split; the highest kernel share measured (43%) | M for the share | Commit and residency levers first; the split needs one measurement |
| iPhone 15 Pro | Unknown; heat adds a second regime (1.5 rested, 2.2 settled, about 3 hot) | A | Rank by energy per frame, not by overlap; needs a device |
| iPhone 16 Pro | Never run | none | No neural-accelerator kernels (section 5, F); expect it between the two |

## 3. How the runtime spends time and memory

Paths in this section are short forms. `Qwen3TTS.swift`, `Qwen3TTSTalker.swift`,
`Qwen3TTSCodePredictorCompiled.swift` and `Qwen3TTSSpeechTokenizer.swift` are under
`Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/`. MLX files are under
`build/cache/xcode/source-packages/checkouts/mlx-swift/Source/Cmlx/mlx/mlx/` (mlx-swift 0.32.3, which
vendors MLX core 0.32.2), the pinned checkout on this Mac.

### 3.1 One frame

The streaming loop starts at `Qwen3TTS.swift:3883`. Each iteration builds one lazy graph:

1. **Talker step** (`:3893`): 28 layers at batch 1 over a growing key-value cache.
2. **First-codebook sampling** (`:3905-3917`): cast to float32, suppress 1,023 special ids, apply the
   repetition penalty, temperature, top-k, optional top-p, then a categorical draw.
3. **Code predictor** (`:3980-4022`): 15 passes, each one compiled function per pass index
   (`Qwen3TTSCodePredictorCompiled.swift:67-105`) followed by an uncompiled sampler.
4. **Next input** (`:4036-4041`): the sum of 16 codebook embeddings plus the text embedding.
5. **Submit** (`:4052`): one `asyncEval` for the whole frame.
6. **Read back** (`:4092`, `:4110`, `:4122-4128`): the token (this is the wait for the GPU), the
   end-of-speech flag and two introspection scalars.
7. **Record the token for the repetition penalty** (`:4155`).

In the production streaming path, step 7 is the only data that frame N+1's graph needs from the
read-back (the diagnostic and non-streaming modes read more). The penalty is built from a
host-side list of the unique tokens generated so far (`:5127-5143`, used at `:5263-5285`). Everything
else the next frame needs (the embedding, the cache, the code predictor's buffers) is already a lazy
array. The loop therefore reads frame N before it starts building frame N+1 for one reason only, and
that reason is removable (lever A3).

**By count (C).** Reading the layer code gives about 28 to 30 kernels per talker layer
(`Qwen3TTSTalker.swift:8-23`, `:143-184`, `:197-205`):

| Talker layer, one step | Kernels |
|---|---|
| Two layer norms, q and k norms | 4 |
| q, k, v, o, gate, up, down (quantized matrix-vector products) | 7 |
| Rotary embedding by hand: multiply, slice, negate, concatenate, multiply, add, for q and for k | 10 to 12 |
| Cache writes for k and v, attention, one reshape copy | 4 |
| SwiGLU (compiled, one fused kernel), two residual adds | 3 |

A code-predictor layer is about 20, because its rotary step is already the fused `MLXFast.RoPE`
(`Qwen3TTSCodePredictorCompiled.swift:156-163`). So a frame is about 790 talker kernels, about 1,550
code-predictor kernels across the 15 passes, and about 160 sampler kernels: 2,500 to 2,900 in all.
The October 13 review's 2,900 and section 2's context-switch count agree with that. The code
predictor is about 60% of the launches for about 47% of the bytes.

### 3.2 What MLX does with that graph

- **It encodes every operation inline on the calling thread** (`transforms.cpp:266`,
  `backend/metal/eval.cpp:29-70`). Each operation allocates a set of its input buffers and adds its
  own completion handler to the command buffer (`eval.cpp:66`).
- **It commits a command buffer when either limit is passed** (`backend/metal/device.cpp:511-514`):
  more than 20 operations on a phone, 40 on a base or Pro Mac chip, 50 on a Max or Ultra
  (`:603-623`); or more than 40 (50 on Max and Ultra) "megabytes" of distinct input buffers. That
  second counter adds each array's element count, not its bytes (`:345-358`; `array.h:346`), and
  model weights count toward it. A 4-bit talker layer counts as about 7.5, so the limit does not
  bind today; it starts to bind near 120 to 150 operations per buffer at 4-bit and 70 to 85 at
  8-bit. Both limits are read once from `MLX_MAX_OPS_PER_BUFFER` and `MLX_MAX_MB_PER_BUFFER`
  (`:625-626`, `utils.h:182-190`).
- **It lets the host run at most ten command buffers ahead** (`transforms.cpp:25`, `:271-282`). On a
  phone that is about 230 operations, 8% of a frame; on a Mac about 15%. While more buffers than
  that are in flight, MLX commits the buffer it is filling before it waits, so a loop that waits on
  the GPU commits more often than the limits alone imply.
- **It registers no buffer in a Metal residency set unless a wired limit is set**
  (`backend/metal/resident.cpp:136-152`: `insert` returns when the total would pass the capacity, and
  the capacity is the wired limit, zero by default, `resident.h:15-16`). Neither the app nor the
  package ever sets one. So each of the roughly 130 commits per phone frame leaves the system to make
  that buffer's resources resident.
- **It never uses the neural-accelerator kernels for a one-row quantized product.** They need macOS
  or iOS 26.2 and GPU generation 18 on a phone or 17 elsewhere (`device.cpp:947-966`), which admits
  the A19 and M5 families and excludes the A17 Pro and A18 Pro. Even there, a quantized matmul below
  13 to 33 rows goes to the plain matrix-vector kernel (`backend/metal/quantized.cpp:85-100`,
  `:1804-1832`). The decode step is one row. Only the prefill, with one row per prompt token, can
  take the accelerated path (`:1039-1043`). The float32 codec decode, which runs inside the loop, can
  take accelerator kernels too: its convolutions and linears go through MLX's matmul
  (`backend/metal/conv.cpp:191`, `backend/metal/matmul.cpp:916-919`).
- **On those chips it runs float32 matrix products in a reduced-precision mode by default**
  (`utils.h:214-216`: `MLX_ENABLE_TF32` defaults to 1; `backend/metal/matmul.cpp:916-919`). Section 9
  returns to this: the owned runtime tests switch it off (`scripts/macos_test.sh:1496-1512`), which
  the October 16 audit recorded as finding F-17.

### 3.3 Decode, and after the last frame

- **Streamed decode.** Every 7 frames on the iPhone and the 8 GB Mac (14 for Voice Design and Voice
  Cloning after the first chunk), the pending codes go through the stateful decoder and are
  submitted with `asyncEval` (`Qwen3TTS.swift:4166-4209`); the samples are read at the next step.
  On the iPhone 17 Pro decode is 15 to 16% of the loop and its per-frame cost grows 8 to 21% over a
  take (audit D-10, D-11), because the decoder's own cache is never windowed (PA-16).
- **Cache clears.** The iPhone, the 8 GB Mac and the 16 GB Mac clear MLX's buffer cache on every
  chunk (`:4295`, policy at `NativeMemoryPolicyResolver.swift:46-100`); the iPhone's cache limit is
  128 MB.
- **After the last frame** the take is read, marked, checked and hashed in three or four full passes
  (`Sources/QwenVoiceCore/GenerationOutputAdapter.swift:2115-2270`). The watermark model reloads its
  weights and casts them to float32 on every take
  (`Packages/VocelloQwen3Core/Sources/MLXAudioMark/AudioSealGenerator.swift:158-161`) and runs its
  LSTMs as a Swift loop over time steps (`:96`). Marking runs on the GPU by a recorded measurement:
  MLX's CPU convolution path ran near real time with about 300 MB of transients per window
  (`Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/AudioMarking.swift:21-28`). Measured
  finalization (M, the section 2 records): about 36 ms per audio second on the iPhone 17 Pro, 20 on
  the M6 and 47 on the M2.
- **Audible start** is dominated by the live preview's prebuffer, not the engine: 0.7 to 3.8 s of
  waiting the engine does not need (audit D-01). It is the largest delay a user perceives on the
  iPhone 17 Pro and it is already parked in ER-08.

### 3.4 Memory

| | iPhone 17 Pro (M) | Source |
|---|---|---|
| Resident model | 1.36 to 1.40 GB | Audit section D |
| Peak footprint, Built-in, Design, Clone | 2.07 to 2.45, 2.13 to 2.83, 2.39 to 3.17 GB | The October 20 to November 3 records, memory qualification included |
| MLX peak, Built-in, Design, Clone | 2.23, 2.67, 2.93 GB | Same |
| Process limit | 8,192 MB on builds 24 and 26; 6,144 MB on builds 28 and 29 | Section 5, E1 |

- **Weights are read into Metal buffers, not mapped.** `MLX.loadArrays` (`Qwen3TTS.swift:6350-6356`)
  creates lazy load steps that read the file into allocator memory at evaluation
  (`io/safetensors.cpp:209-217` in the pinned MLX). All of it is dirty memory that counts against
  the process limit.
- **The text embedding is the largest single tensor that a take barely touches.** It is 151,936 rows
  of 2,048, about 330 MB at 8-bit, and a take uses the few hundred rows of its prompt. During decode
  the text input is one cached padding row (`Qwen3TTS.swift:4025-4032`).
- **The iPhone bands are constants:** guarded at 4,500 MiB and critical at 5,200 MiB of footprint,
  or 768 and 384 MiB of headroom, and a third band at 0.80 of Metal's recommended working set
  (`Sources/QwenVoiceCore/IOSMemorySnapshot.swift:425-430`). Against a 6,144 MB limit the critical
  footprint band is at 85%.

### 3.5 What changed outside since August

| Area | Fact | Bearing |
|---|---|---|
| MLX releases | The pin, mlx-swift 0.32.3, vendors MLX core 0.32.2 (the `0.32.0` string in its `Package.swift` is stale). Newer: core 0.32.3 and 0.32.4, mlx-swift 0.33.0 (2026-10-27). mlx-swift-lm has no release after 3.32.3 [X1, X2, X3] | I2 |
| MLX and one-row decode | No release and no merged change on main speeds up a one-row 4-bit product; three new kernel families state "M = 1: unchanged" [X22] | C1, I2 |
| MLX launch overhead | Reports on large Macs: about 20 microseconds of GPU time per command-buffer boundary, 8 to 17% from larger buffers on launch-heavy models; the defaults will not change; a run-time setting is merged and unreleased [X4, X5, X7] | A1 |
| MLX reference loops | mlx-lm and mlx-swift-lm submit step n+1 before reading token n, keep the repetition penalty in the graph, and (mlx-lm) wire memory for the whole generation [X8, X11] | A2, A3 |
| MLX and memory mapping | Refused by the maintainers in August 2026 [X17] | E3 |
| Neural accelerators | In the A19 and M5 families and later; MLX uses them from macOS and iOS 26.2 for products of many rows and long attention; Apple measures up to 4 times on the prompt and 19 to 27% on generation, the latter from bandwidth [X19, P11] | F1 |
| Reduced-precision float32 | Default on those chips; MLX documents it and the switch `MLX_ENABLE_TF32` [X20] | Section 9 |
| Apple hardware | M6 (August 2026, 170 GB/s) and A20 Pro (September 2026, 12 GB, 50% more bandwidth than A19 Pro) are shipping [P1] | F |
| iPhone memory limits | 6,144 MB with the entitlement on 8 GB and 12 GB phones; reports of 8,192 MB on 12 GB phones under iOS 27 for apps with Game Mode [P5] | E1 |
| Metal 4 | A new command model (reusable command buffers, argument tables, explicit residency) that Apple says lowers CPU encode cost, with no figure; MLX has not adopted it [P10, X1] | A1, A2 |
| Background GPU | Still iPad-only, per Apple support staff [P13] | F5 |
| Upstream ports | mlx-audio landed the decoder's 72-frame window (2026-11-03), batching, and removed its per-chunk cache clears; a Swift port compiled the whole predictor frame [R1, R2, R3] | PA-16, D, A5, B5 |
| Qwen | No new open weights or code since March 2026 [R6]. Its technical report implies about 21 ms of language-model time per frame for the 1.7B model on its own server engine (derived; the report gives no formula) [R6]; the M6 runs a whole frame in 19 ms | I4 |

## 4. One ledger: done, tried, rejected and parked

Nothing in section 5 repeats a row of this table unless the row's reopen condition is met and the
card says so. Sources: `benchmarks/OPTIMIZATION.md` (sections F to R), `docs/reference/mlx-guide.md`
(sections 7, 9 and 10), the audits of October 13 and 16, and `config/roadmap.json`. Speed figures
from the ledger are converted to `rtf` where the ledger used the inverse.

### 4.1 Landed

| Change | Measured effect | Record |
|---|---|---|
| Streaming by default | Peak memory 7.6 to 8.0 GB down to about 3.0 GB, flat with length | Ledger F.1 |
| Fused rotary embedding in the code predictor | About 600 fewer launches per frame; +26% on the 8 GB M2 | Ledger H, P3 |
| Sampler scratch reuse | About 17,000 fewer allocations per take; about +1% | Ledger H, P2 |
| Pipelined step (`asyncEval`, chunk flush in the gap) | +0.5 to +3.3% | Ledger M, P2a-i |
| Compiled code predictor, one function per pass | +8.3 to +10.6%, byte-identical | Ledger M, P3 |
| 8-bit text embedding | 278 MB less MLX memory, 292 MB less on disk, at most 1% slower | Ledger N, 2.2 |
| Speech-tokenizer residency across model switches (Mac) | Switch reload 503 ms to 0 | Ledger N, 2.1 |
| Liquid Glass off while generating (Mac; iPhone on 60 Hz panels) | Removed a 25% loss on the 8 GB Mac | Ledger K |
| MLX 0.30.6 to 0.31.6, then to 0.32.3 | Speed within noise both times | Ledger Q; CONV-21 |

### 4.2 Tried and rejected

| Idea | Result | Reopen condition on record | Met today? |
|---|---|---|---|
| Compile the talker MLP with quantized weights as `inputs:` | 5% slower | None; "do not pursue" (ledger F) | No |
| Static-shape compiled talker step (P1b) | Flat on 0.30.6; 0.74% slower on 0.31.6 in a paired soak | The branch was kept "for a future pin generation"; the do-NOT is maintainer-ratified (ledger Q) | By the letter only (0.32.3). The branch is no longer in the repository, so a re-test is a re-implementation. See K1 |
| Submit the talker before the code predictor is built | 3.9% slower | None; a comment marks the site (`Qwen3TTS.swift:3959-3964`) | No |
| Decode the codec on a second MLX stream | 0.4 to 4.3% slower | None | No |
| Read the token later with nothing in between (`.eosOnly`, `.deferred`) | No effect | None (`Qwen3TTS.swift:437-444`) | No. Lever A3 is a different change and says why |
| Talker KV window | About 0 MB saved; never rotates below the 2,048-token cap | The token cap rises above the window; never with the streaming text layout | No |
| 8-bit talker KV | 271 MB saved, 8.6% slower | A memory emergency on some tier | No |
| Hard MLX memory limit | Spurious out-of-memory downgrades; reverted | None; an engine invariant | No |
| Half-precision codec | 234 MB saved, about 5% slower; shipped August 1, withdrawn September 14 for a burst in the first 50 ms of 4 of 28 streamed clone takes | A decoder precision fix, or an iPhone 17 Pro measurement for a per-platform split | No |
| Metal 4 TensorOps `matmul2d` in place of MLX's kernels | No faster on the M2; one-row shapes not expressible in parallel; silent wrong output at one shape | "Until Apple's portable fallback improves or the canonical floor changes" | No: the benchmark host moved to an M6, the support floor did not. See K2 |
| The 0.6B model | Ruled out: Voice Design needs 1.7B | None | No |
| Repetition penalty 1.10, community sampling recipes | No gain over the defaults | None | No |
| vDSP in long-form assembly | Declined: 28 ms per 10 minutes, and it changes samples | None | No |
| iPhone cache-clear A/B on the farm | Could not run: the memory guard stopped the first take without the entitlement | None recorded | It can run on a phone with the entitlement (A5) |

### 4.3 Parked items the overhaul draws on

These were parked until after the submission. The decision of 2026-11-10 brings the overhaul forward
(section 6.3); the items stay as they are until its stages are recorded against them.

| Item | What it holds |
|---|---|
| ER-01 | Measurement tooling: a Metal dispatch-count profile, an iPhone per-chunk-clear knob, an iPhone benchmark build that matches the shipped build, fresh baselines |
| ER-07 | iPhone memory bands from the measured process limit; idle unload and per-chunk clear from measured headroom; the 8 GB Mac's unexplained Metal allocation |
| ER-08 | Identity-safe performance: the speed-aware prebuffer (D-01), decoder warm-up (D-02), weight-hash reuse, marking cost, the dispatch levers PERF-2 to PERF-6, a held compiled plan (PERF-10) |
| ER-09 | Performance that shifts numerics: the fused talker rotary step (PERF-1), decoder mask and chunked encoder, decode-cost levers, the per-chunk clear |
| PA-16 | The codec decoder's 72-frame attention window, before any decoder lever |

## 5. Lever cards

Each card gives the mechanism, why it suits Apple silicon, the estimate with its grade, whether the
output stays bit-identical, the cost and risk, what it needs from the maintainer, the result that
would kill it, and how it interacts with the others. Estimates use four small models:

| Lever class | Model | Where it breaks |
|---|---|---|
| Fewer commits or launches | Fixed overhead removed, times the share of commits or launches removed | Overhead is not uniform; the fixed share is known only on the M2 |
| Overlap | At most the host's graph-build time per frame, and only where the GPU is the slower side | The build share is in no published record |
| Bytes | At most the bandwidth share of the frame | The share is known only on the M2 |
| Batch of B | Throughput ratio B × (fixed + bytes) / (fixed + B × bytes), or better where MLX's small-batch kernel applies | The small-batch kernel is below its roofline at 2 to 8 rows |

A frame is modelled as `host build + max(host encode, GPU pipeline)`, where the GPU pipeline is the
weight reads plus a cost per command buffer and per dispatch. The records support the shape: the
generation thread sleeps about half the time, so the GPU side is the slower one (section 2.3).

### A. Submission and scheduling: no change to any sample

#### A1. Size MLX's command buffers for this workload

- **Mechanism.** MLX commits a command buffer after 20 operations on a phone and 40 on a base or
  Pro Mac chip (section 3.2). That is 120 to 140 commits per frame on a phone and 60 to 70 on a Mac
  (C). The limits are environment variables read once, before the Metal device is created:
  `MLX_MAX_OPS_PER_BUFFER` and `MLX_MAX_MB_PER_BUFFER`. The second one counts array elements, weights
  included, and starts to bind near 120 to 150 operations per buffer at 4-bit, so the two must rise
  together. On iOS MLX is first touched in `App.init` (`Sources/iOS/QVoiceiOSApp.swift:44`), which
  ER-08 plans to move (B-08); the setting must precede that call, and the two changes are sequenced
  together.
- **Why it suits Apple silicon.** On a unified-memory GPU a commit moves no data; its cost is the
  round trip: the kernel hand-off, the completion handler and a core that went idle and must wake.
  Apple's own guidance is that work items of 4 to 20 microseconds are "barely shorter than the time
  it takes to wake up a CPU core" [P7]. MLX's defaults are tuned for large language models with few,
  large kernels; this loop is thousands of tiny dependent ones.
- **Evidence from MLX's own tracker (A; large Macs only).** On an M3 Ultra, each command-buffer
  boundary costs "about 20 us of GPU time plus a completion handler on the CPU", and a launch-heavy
  model with about 1,600 kernels per token gained 7.7% from 1,000 operations and 400 MB per buffer,
  while a dense model did not move; a second reporter measured 11.9 to 13.7% on an M5 Max [X4].
  A maintainer-reviewed patch that raised the limits only around decode measured 2.6 to 17.5% [X5].
  A Metal probe on the same class of machine measured 15.8 microseconds per dispatch inside one
  encoder against about 145 when each dispatch closes its encoder and waits [X6]. No source measures
  a phone or a base Mac chip, and the phone default of 20 carries no stated reason beyond the source
  comment `// phone` [X5].
- **Estimate.** 5 to 15%, grade **A**. With the tracker's 20 microseconds of GPU time per boundary,
  130 boundaries are about 7% of a phone frame and 65 about 7% of an M6 frame, before the
  completion-handler and wake-up costs. There is no basis to expect more on the phone than
  elsewhere: per millisecond it commits no more often than the M6 (about 3.8 against 3.7), and the
  kernel time in its records is not shown to be on the critical path.
- **Output.** Bit-identical: only the grouping of the same kernels changes.
- **Cost and risk.** One `setenv` per chip class before MLX is first touched. The repository
  requires every production-affecting environment key to be a registered diagnostic
  (`docs/reference/native-engineering.md:63-64`): the sweep's keys go through that registry, and the
  shipped values are constants the app sets in code, not values read from its environment. MLX reads
  these variables itself, outside the app's knob registry, which knows only `QWENVOICE_` and
  `QVOICE_` names, so a swept record would not identify its own settings until the registry and the
  record's runtime signature learn them. Three risks to measure. Memory: buffers in flight keep
  their temporaries alive, and the upstream reports saw prefill peaks rise from 0.57 to 2.1 GB on
  one model and far more on a 30,000-token prompt [X4, X5]; Vocello's prompts are hundreds of
  tokens, but the peak must be watched on the iPhone. Latency: with very few commits the GPU starts
  each frame later, so there is an optimum, not a monotone gain. Interface: long compute buffers may
  delay the app's own frames on the shared GPU.
- **Devices.** All; most on the phones.
- **Needs from the maintainer.** Nothing beyond the overhaul's go-ahead: no pin, artifact or rule
  change. (A later MLX will let the limits change at run time, around decode only [X7]; that is
  unreleased.)
- **Kill criterion.** A fixed-seed sweep (20, 40, 80, 160, 320 operations with 40, 160, 400, 1,000 MB)
  shows less than 3% at its best point, or a changed PCM digest, a higher memory peak than the bands
  allow, or more interface hitches.
- **Interactions.** It sets how far A3 can reach: MLX lets the host run ten buffers ahead, 200
  operations today and a whole frame at about 300 per buffer. It reduces what A2 can add.
- **Lands in.** ER-08.

#### A2. Let MLX use Metal residency sets while a take runs

- **Mechanism.** MLX attaches Metal residency sets to its command queue, but adds a buffer to one
  only while the total is under the wired limit, which is zero unless the app sets it
  (`backend/metal/resident.cpp:136-152`, `resident.h:15-16`). Vocello never sets it. A wired limit
  held only while a take runs puts the weights in the sets, so a commit no longer leaves the system
  to make them resident.
- **Why it suits Apple silicon.** Residency sets exist for many command buffers that reference the
  same large resources; Metal 4 makes them the only residency mechanism [P10]. mlx-lm wires to the
  recommended working set for the whole of every generation [X8], and another Swift port of this
  model pins the wired limit by default [R3].
- **Estimate.** Unknown, and possibly negative: grade **U**. Buffers touched every 20 to 40 ms may
  never lose residency, so there may be nothing to save. And with a non-zero limit MLX commits the
  residency set on every buffer it allocates or releases outside its small-buffer heap
  (`resident.cpp:153-154`, `:167-171`); the iPhone releases constantly, with a 128 MB cache cleared
  on every chunk. A2 therefore comes after A5 or not at all. MLX documents the wired limit as useful
  on macOS 15 and later and says nothing about iOS; its source enables the sets on iOS 18 and later
  [X9].
- **Output.** Bit-identical.
- **Cost and risk.** mlx-swift's ticket API (`WiredMemoryManager`) raises and lowers the limit
  around a take. The limit is process-wide allocator state, and the rules ask for request-local
  memory (`CLAUDE.md`, Runtime); like the cache limit it would be an allowed, named exception. Wired
  memory cannot be compressed, so the limit must fall when the take ends, and the 8 GB Mac needs its
  own check. MLX refuses a limit above the recommended working set
  (`backend/metal/allocator.cpp:254-262`), which is 8,192 MB on the phone, above the 6,144 MB process
  limit, so the app must choose the number; and when the limit rises MLX fills it in hash order, not
  weights first (`resident.cpp:189-200`). On macOS 27 the system drops residency about two seconds
  after the last GPU work, and the refresh option that counters it is not in the pinned MLX [X10].
  How wired buffers count on an iPhone is not documented anywhere [P4]: measure before trusting.
- **Kill criterion.** No change in kernel CPU seconds per frame at fixed seed, or any loss of
  headroom on the iPhone.
- **Lands in.** ER-08, after A1.

#### A3. Build frame N+1 while frame N runs

- **Mechanism.** Today the loop reads frame N's token before it builds frame N+1, because the
  repetition penalty is built from a host-side list (`Qwen3TTS.swift:4155`, `:5127-5143`). Keep that
  list in the graph instead, as a lazy array of the tokens so far or a fixed-shape seen-mask. Then
  build and submit frame N+1 from frame N's lazy outputs, and read frame N's token, end-of-speech
  flag and introspection scalars afterwards. When the flag is true, discard the one speculative
  frame.
- **This is how MLX's own loops are written.** mlx-lm builds the next step from the still-lazy token,
  calls `async_eval`, and only then reads the previous token; its repetition penalty is array
  operations on a lazy token history [X8]. mlx-swift-lm does the same, with a comment that its
  penalty uses mask operations "preserving asyncEval() pipelining" [X11]. A core maintainer called a
  GPU-to-CPU round trip per sampled token something that "sounds like a bug if it really is the
  case" [X12].
- **Why it is not one of the rejected ideas.** The `.eosOnly` and `.deferred` policies moved the same
  read later "with nothing in between" (`Qwen3TTS.swift:437-444`). The early talker submit split one
  frame into two command buffers. The engine invariant forbids pipelining the code predictor's 15
  passes because that would change what each pass samples from. This changes none of those: every
  frame keeps its one submission and every pass its inputs and order. Only the host's read moves
  behind the next frame's build.
- **Estimate.** At most the smaller of two things: the host's graph-build time per frame, and the
  GPU work still queued when the submission returns. MLX's ten-buffer window caps the second at
  about 8% of a phone frame and 15% of a Mac frame at today's buffer sizes. The first is known only
  from the ledger's traces of an unoptimized build (19 to 23% of wall, sections H and M); the
  optimized product builds far faster. A maintainer's own judgment is that "the effect of not
  pipelining is relatively small" [X13], and the repository's own overlap experiments gave +0.5 to
  +3.3% at best (section 4). Expect 0 to 8% alone, grade **C**; more only with A1, where the bound
  becomes `max(build + encode, GPU pipeline)`.
- **Output.** Bit-identical if the penalty applies the same multiply or divide to the same logits; a
  repeated index writes the same value twice. The fixed-seed PCM digest decides.
- **Cost and risk.** Moderate, all in the loop, with three traps the verification found.
  - **The read must create no new work.** Today's read slices the token first
    (`Qwen3TTS.swift:4092`); a new slice is committed behind everything already queued, the
    speculative frame included, and would wait for it. The lagged read has to be of an array the
    frame's own submission already scheduled.
  - **The cache write may stop being in place.** MLX reuses a buffer only when nothing else holds
    it (`array.h:294-296`), and every command buffer in flight holds its operations' inputs until it
    completes (`backend/metal/eval.cpp:47-67`). Today frame N has completed before frame N+1 is
    encoded. Under lookahead it has not, so the talker's per-layer cache update could turn into a
    copy of the whole cache every frame. This is an inference from the source and must be measured
    before anything else.
  - **The discarded frame is not free.** It delays the tail decode by one frame, 120 to 240 ms on an
    iPhone 15 Pro, and an MLX failure inside it would poison the stream of a take that had already
    finished.
  The speculative frame must also stay out of the decoder's state, the chunk schedule, telemetry and
  introspection; cancellation must drop it; and the sampler's random state must advance exactly as
  before for every kept frame (it does: each request owns its random state). `asyncEval` can block
  under MLX's back-pressure, which is why mlx-swift-lm moved its loop off the cooperative pool
  [X14]; Vocello's loop runs on the engine actor and should be checked for the same.
- **Kill criterion.** A changed PCM digest that cannot be explained, or less than 3% with A1 in place.
- **Interactions.** Makes PERF-3 (a compiled sampler) natural, since the seen-mask gives the sampler
  fixed shapes. Shrinks the case for K1.
- **Lands in.** ER-08.

#### A4. Confirm the generation thread's core placement

- **Mechanism.** No code sets a priority for generation; the tasks inherit their caller's
  (`Sources/QwenVoiceCore/MLXTTSEngine.swift:1304`,
  `Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Engine.swift:1140`). On the Mac, forcing the
  process to background priority halved speed (ledger section J), and background-class threads run
  on efficiency cores only [P8].
- **Estimate.** Zero if the thread already runs on performance cores. The engine writes the process
  role and the main thread's quality-of-service class into each take's telemetry notes (ledger
  section J), but the published records do not carry them, so this is a check to make, not a known
  gain. Grade **U**.
- **Lands in.** ER-01.

#### A5. Stop clearing the buffer cache on every chunk

- **Mechanism.** The iPhone, the 8 GB Mac and the 16 GB Mac clear MLX's cache on every chunk, and
  every 50 frames besides (`NativeMemoryPolicyResolver.swift:46-100`). After a clear, the next frame
  allocates its temporaries again. The iPhone's peak is 2.1 to 3.0 GB of a 6,144 MB limit, so there
  is room to clear once per take.
- **Estimate.** Unknown, at most a few percent. In the records, Voice Design and Voice Cloning clear
  half as often as Built-in Voice and spend about 1 ms less kernel time per frame (9.3 against
  10.3 ms, **M**), but they also make half the decode calls and hand-offs, so the comparison is
  confounded. Upstream, removing the same per-chunk and every-50-step clears from mlx-audio's
  streaming path took an M1 Pro from 0.682 to 0.596 at a far shorter chunk interval [R1]. MLX's iOS
  guidance is a small cache limit, not frequent clears: 20 MB in its example, and "a cache limit of
  0 will result in decreased performance" [X15]. The clean test is available on the Mac today: the
  registered `QWENVOICE_FORCE_MEMORY_CLASS` knob switches a 16 GB Mac between a policy that clears
  per chunk and one that does not.
- **Output.** Expected bit-identical. The roadmap files the per-chunk clear under numerics-shifting
  work (ER-09's gate), so the digest decides. **Kill criterion.** A fixed-seed A/B on the phone, with
  the entitlement, shows no gain or a higher peak than the bands allow (the farm could not run it,
  section 4.2).
- **A decision it reopens.** BKL-53 was closed on 2026-11-02 with no prebuffer or memory-policy
  change for 3.0. With the overhaul now before the submission, A5, E4 and H1 reopen that.
- **Lands in.** ER-07, as recorded there (PERF-7).

### B. Fewer kernels per frame

The parked levers stand as the October 13 review wrote them. This report adds B2 and B5, and an
order.

| Card | Lever | Launches per frame | Output | Status |
|---|---|---|---|---|
| B1 | Fuse q, k and v, and gate and up, into one quantized product each (PERF-2). Costs fused weight tensors: about 19 MB more per talker layer if the originals stay, or a changed module tree and key check | −309 | Expected identical | Parked, ER-08 |
| B2 | Talker rotary step with the same arithmetic in fewer kernels | −112, or up to −220 if the compiled form keeps the digest | The exact part is identical; the compiled part needs the digest | **New** |
| B3 | Compile each sampler (PERF-3); stop copying the code predictor's K/V buffers (PERF-4); merge embedding gathers (PERF-5); drop the introspection reads when telemetry is off (PERF-6) | −360 | Identical, except that a compiled float32 sampler needs the digest | Parked, ER-08 |
| B4 | Fused `MLXFast.RoPE` in the talker (PERF-1) | −241 | Shifts numerics | Parked, ER-09; superseded by B2 if B2 holds |
| B5 | The whole code-predictor frame as one compiled function, sampling included | Host calls 30 to 1 | Identical only if the same sampler and random stream are kept | **New**, from another port |

**B2 in detail.** The talker rotates q and k by hand: `q * cos + rotateHalf(q) * sin`, where
`rotateHalf` slices, negates and concatenates (`Qwen3TTSTalker.swift:8-23`). That is six dispatches
each for q and k, 12 of a layer's 30. The same values come from `q * cos + take(q, perm) * sin'`,
where `perm` swaps the halves and `sin'` carries the sign: `(-x) * s` and `x * (-s)` are the same
IEEE product, and the gather is exact. Uncompiled that is four dispatches each, 112 fewer per frame,
with identical output. Compiling the multiply-add chain into one kernel, as the SwiGLU already is
(`:33-37`), would halve it again, but that part is not identical by construction: a fused kernel in
Metal's native bfloat type has nothing that forces a round between the multiply and the add, and
this package's own compiled predictor moved float32 values by about 1e-7 (ledger M). The digest
decides the compiled form. PERF-1 reaches a similar count through `MLXFast.RoPE`, which rotates in
float32 and shifts the samples, which is why it sits in ER-09. The cos and sin tables can also be
computed once per take instead of once per frame (`:82-99`, `:310`). Upstream mlx-audio compiles
this same rotary helper [R1].

**B5 in detail.** Another Swift port unrolled all 15 passes into one fixed-shape compiled graph,
kept the predictor's cache inside the graph and sampled in-graph, and measured 31.8% less generation
time; a Core ML port measured 29% more steps per second from the same change on an M4 [R3, R4]. The
Swift port's baseline was the structure Vocello has today, one compiled function per pass and one
evaluation per frame, but its device and model size are not stated, so this is a weak analogy for a
large effect. What the change removes is host work: 15 compiled calls and 15 sampler graphs per
frame, and the K/V buffers that cross each call (PERF-4). Both ports sample by Gumbel-max with
host-drawn noise; adopting that here would change every seed and move the card to ER-09. Keeping
MLX's categorical draw inside the trace, with its key or random state declared, keeps the stream
(PERF-3's condition), though a float32 sampler inside a trace cannot be proven identical by a few
seeds: a moved edge of the distribution flips a draw only when the random number lands in that
sliver. If keeping the stream proves impractical, the seed change is a price worth paying for a
measured double-digit gain (section 1.2). The engine invariant that the per-pass plan matches the
eager path, and its test, would be re-based on the new function. A CUDA engine that wrote the
predictor's cache inside one compiled function found the compiler silently copying the buffer on
every step [R7]; the same must be ruled out here.

- **Estimate for B as a whole.** B1 to B3 remove about 800 of 2,900 launches. On the M2 the ledger's
  one data point gives an elasticity near one (600 fewer launches of about 3,500, +26%); on the M6
  near zero (section 2.4). That +26% was measured on an unoptimized build. B5 is host time, not
  launches: Vocello's own trace puts the predictor's host window at 9.7% of wall after the per-pass
  plan, again unoptimized, so the other port's 30% is not a forecast here. Grade **A**. After A1,
  expect less everywhere: once commits are few, a launch costs its encode time and one dispatch,
  about 16 microseconds on the one machine measured [X6].
- **Kill criterion.** As ER-08 already requires: a byte-identical PCM digest and a measured dispatch
  count and gate-bench effect per lever.

### C. Bytes per frame: the floor under everything else

Once the fixed overhead is reduced, what remains is the GPU reading about 1.5 GB of quantized
weights per frame (section 2.3). Apple describes token generation the same way: it "is bounded by
memory bandwidth, rather than by compute ability", and the M5 gained 19 to 27% over the M4 there
against up to four times for the prompt [X19, P11]. No lever in sections A or B touches this term.

- **C1. No identity-safe way to read fewer bytes was found.** The per-group scales and biases (half
  a bit per weight) are part of MLX's format. The key-value cache is about 112 KiB per position and
  the activations are kilobytes; neither matters next to the weights. The one-row kernel is already
  the fast one: its conditions (input width a multiple of 512 at 4-bit, output a multiple of 8) hold
  for every projection in this model [X18], and a report on MLX's tracker measured one row "at
  roofline", which the maintainer's reply did not dispute [X22].
- **C2. The code predictor is 5.5% of the quantized parameters and 47% of the bytes read (C),** because
  every frame runs it fifteen times. It is also the worst place to cut precision. Qwen calls the
  predictor precision-sensitive, three independent ports moved it to float32 for correctness, and
  two bf16 implementations agree on its top token only 87 to 90% of the time [R6, R7, R5, R3].
- **C3. Within the talker, the three MLP matrices are 75% of the bytes** (37.7 M of 50.3 M parameters
  per layer). A mixed recipe that lowers only those is where a quantization experiment would start
  (decision item I1).
- **C4. Precision buys memory, not speed, where the GPU is not bandwidth-bound.** On an M3 Max the
  same 1.7B model ran at 19.9 to 20.9 frames per second at 4-bit, 6-bit, 8-bit and bf16 alike [R1].
  On the M2, 8-bit costs 40% more time per frame (section 2.2), though the 8-bit kernel also has a
  different alignment rule, so not all of that is bytes. The bytes term matters most on the
  devices with the least bandwidth: the phones and the base Mac chips.
- **Estimate.** The bandwidth share of a frame times the share of bytes removed. On the M2 a recipe
  that removed 20% of the bytes would give about 9%. Grade **C**; unknown on the phones until their
  split is measured (section 7).

### D. A batch of segments for long-form and line batches (recommended; needs a rule change)

- **Mechanism.** Long-form projects and Mac line batches run one independent take per segment
  (`Sources/iOS/Studio/IOSLongFormProject.swift:917`, `Sources/Services/MacLineBatchRunner.swift:177`).
  Segments in one batch share every commit and every launch, and on most chips part of the weight
  read: MLX has a small-batch quantized kernel for 2 rows up to the 13 to 33 where it switches to a
  matrix-matrix kernel, enabled for this quantization mode on GPU generation 15 and later, which
  includes every supported iPhone and the M6 but not the M2 [X22]. The same report measured it below
  its roofline at 2 to 8 rows.
- **Evidence on MLX (A).** Upstream mlx-audio batches this same 1.7B model. On an M3 Max, total
  frames per second were 19.8 alone, 31.8 at batch 2 and 46.3 at batch 4, for 0.1 GB more peak
  memory; a batched eight-segment long-form take ran 3.8 times faster than sequential; on an M2 Pro
  at 8-bit, eight slots gave 53 to 57 frames per second against about 25 alone [R1, R2].
- **Estimate.** 1.3 to 1.6 times at batch 2 and about 2 times at batch 4 on Macs, grade **A**. On the
  M2, without the small-batch kernel, the model `B × (fixed + bytes) / (fixed + B × bytes)` gives
  1.37 at batch 2 (C). On the phones unknown, and bounded by heat (card G). After A1 the fixed
  share falls and so does this gain: the two levers spend the same budget.
- **Output.** Not bit-identical to single takes: different kernels, different rounding, and a
  different sampler path, since MLX draws batched rows by the Gumbel method and single rows by
  inverse CDF (`random.cpp:422-431` in the pinned MLX). No batched row can reproduce a single-take
  seed. The engine also refuses batch requests today
  (`Sources/QwenVoiceCore/MLXTTSEngine.swift:819-822`). Every pinned
  long-form seed would change, with a release-note line and a pre-registered machine screen. One
  upstream measurement found each batched request's codes identical to the same request run alone
  at a fixed seed [R1], so per-row reproducibility is achievable; identity with today's single takes
  is not.
- **Voice consistency.** No implementation publishes a cross-segment speaker-similarity figure.
  Built-in Voice and Voice Cloning share a speaker token or reference across rows. Voice Design
  samples a new voice per take, so batched Voice Design segments need the same design-then-clone
  route that long-form already depends on (`docs/audits/2026-10-17-qwen3-tts-model-research.md`).
- **Cost.** Large: per-row cache lengths and end-of-speech, per-row seeds (segments already carry
  their own, `Sources/QwenVoiceCore/LongFormPlanning.swift:330`), a batched compiled code predictor,
  a decoder per row, and no live preview of rows beyond the first. The cache is about 110 MB per row
  for a one-minute segment.
- **The rule.** The maintainer set batched decode aside on 2026-06-11 as a future idea (ledger I).
  The measurements above are newer than that decision and are on this model and this framework. This
  report recommends reopening it for the Mac, where long-form and line batches wait longest and heat
  does not bind, and deciding the iPhone after M8.
- **Kill criterion.** A two-row probe of the talker step alone, at fixed inputs, shows less than
  1.15 times the one-row throughput on the target device.
- **Lands in.** A new item after ER-08's phase 1 is measured.

### E. Memory

#### E1. The process limit: accept 6,144 MB and correct ER-07

- **What the records show (M).** On the same iPhone 17 Pro and the same iOS build (27.0.1, 24A446),
  the implied process limit was 8,192 MB with builds 24 and 26 (October 20 and 27) and 6,144 MB with
  build 28 (October 30); it is 6,144 MB on iOS 27.2 with build 29. The Game Mode opt-out (RF-37,
  `26b303ed`,
  October 27) lies between builds 26 and 28. ER-07's note and audit finding D-06 still say iOS 27
  grants 8,192 MB.
- **What outside sources say.** A third-party report on an iPhone 17 Pro Max says iOS 27 allows 8 GB
  on 12 GB iPhones "if Game Mode is enabled in addition to" the entitlement, and that the 27.0
  release made `LSSupportsGameMode` necessary [P5]. A developer measured 6,144 MB on both an 8 GB and
  a 12 GB iPhone with the entitlement alone; no Apple engineer has answered that thread [P5]. Apple
  documents none of it: the public kernel (the 26.x line) treats Game Mode as a scheduler flag, and
  the limit can be set by closed user-space policy [P3]. Grade: probable, undocumented, never a
  controlled A/B.
- **Recommendation.** Keep the opt-out. Apple's developer support states that "an app that enables
  Game Mode but isn't a game will be rejected by App Review" [P6]. The peak is about 3.2 GB at most,
  about half of 6,144 MB, and the fixed bands (4,500 and 5,200 MiB) sit at 73% and 85% of it, which
  is about where ER-07 would put them. The two builds also give a clean answer on speed: `rtf` was
  the same with Game Mode available (0.522 to 0.527, October 27) and without it (0.526 to 0.534,
  November 3).
- **What changes.** ER-07's premise: the budget is 6,144 MB on every supported iPhone measured or
  reported so far, 8 GB and 12 GB alike, not 8,192 MB. Derive the bands at launch from
  `os_proc_available_memory()` plus the footprint, as Apple advises [P3], and never from Metal's
  recommended working set, which reads 8,192 MB on the same phone and is not the limit [P5]. One
  existing band, the GPU working-set ratio (`Sources/QwenVoiceCore/IOSMemorySnapshot.swift:430`),
  is keyed on that figure and should be reviewed with the others.
- **Not measured:** the limit on any 8 GB iPhone with the entitlement under the shipped build.

#### E2. Load only the text-embedding rows a prompt uses

- **Mechanism.** The text embedding is 151,936 rows of 2,048, about 330 MB at 8-bit, resident for
  the life of the model. A take uses it only while assembling its prompt (every call site is in
  prompt assembly, `Qwen3TTS.swift:1630-1761` and `:4676-5011`); the decode loop uses one cached
  padding row. MLX's quantized embedding already gathers the looked-up rows of the packed weights,
  scales and biases and dequantizes only those
  (`build/cache/xcode/source-packages/checkouts/mlx-swift/Source/MLXNN/Quantized.swift:231-238`). The
  rows can instead be read from the weights file by offset, a few hundred rows of about 2.2 KB each,
  and handed to the same dequantize call.
- **Why it suits Apple silicon.** On an iPhone every resident byte of weights is dirty memory charged
  to the app [P4]. This is the one large tensor that can stay on disk at no cost in speed.
- **Estimate.** About 330 MB less resident memory on every platform, 24% of the resident model on
  the iPhone. Grade **C**. A few milliseconds of file reads per take, in the prompt path only.
- **Output.** Identical by construction: the same packed rows through the same MLX dequantize.
- **Cost and risk.** A loader path in the owned package that leaves that tensor out of the module
  tree and keeps the file handle. The key check at load, the batched load evaluation
  (`Qwen3TTS.swift:5941`) and 13 call sites all name the tensor today; the install-time hash already
  covers the file. The package caches conditioning prefixes, so most takes would not touch the file
  at all.
- **Kill criterion.** A changed PCM digest, or a resident saving under 250 MB.
- **Lands in.** ER-07 (it changes the budget), or ER-08 as an identity-safe item.

#### E3. File-backed weights: not available, and not on MLX's road map

- Weights read into Metal buffers count in full against the limit; a read-only file mapping would
  not [P4]. That is 1.4 GB of the iPhone's footprint.
- MLX does not offer it. A pull request for mapped, zero-copy weight arrays was closed in August
  2026 with "at the moment we are not considering using mmap" [X17]. Metal's no-copy buffers need a
  page-aligned pointer and length, which safetensors offsets do not give [P4, X17].
- Third-party measurements on Macs report that the GPU driver wires a whole no-copy buffer on first
  use, and how iOS charges such pages is not documented [P4]. So even a private fork of the loader
  would be a research project with an uncertain result. No action; watch upstream.

#### E4. Smaller items

- **The iPhone unloads the model 30 seconds after the last take** and on leaving the foreground
  (`NativeMemoryPolicyResolver.swift:99`), so an app switch costs a 0.85 s load (audit EN-6, parked).
  With a 6,144 MB limit and a 1.4 GB model the 30 seconds can be minutes while the app is in front.
- **A full unload leaves 309 MiB in MLX's buffer cache** (audit D-04, parked in ER-06), and on the
  Mac an idle unload leaves the package caches, including the resident speech tokenizer, in place
  (section 9).
- **A cheaper idle state than unloading exists in Metal:** buffers marked volatile leave the
  footprint and may be discarded by the system [P4]. MLX has no hook for it. Not actionable today.

### F. What differs per chip

| Chip (devices) | GPU cores, memory | Bandwidth | Neural accelerators in MLX | What it means here |
|---|---|---|---|---|
| A17 Pro (15 Pro) | 6, 8 GB | LPDDR5 (S); no figure published | No | The floor. Needs about 19 GB/s of weight reads for real time; the least thermal headroom |
| A18 (16, 16 Plus; 16e with 4 cores) | 5 or 4, 8 GB | LPDDR5X (S) | No | Admitted by the hardware gate and never measured; the 16e may be the slowest GPU supported |
| A18 Pro (16 Pro) | 6, 8 GB | about 60 GB/s (S) | No: MLX's phone gate starts at generation 18 | Never measured |
| A19 (17) | 5, 8 GB | about 68 GB/s (S) | Yes, on iOS 26.2 and later | An 8 GB phone with the accelerators; never measured |
| A19 Pro (17 Pro, Air) | 6 or 5, 12 GB | about 77 GB/s (S) | Yes | The measured phone: 0.50 to 0.60 |
| A20 Pro (18 Pro) | 7, 12 GB | 50% more than A19 Pro (P) | Yes | Shipping since September 2026; never measured |
| M2 | up to 10, 8 GB floor | 100 GB/s (P) | No | Half fixed, half bandwidth |
| M5 | 10 | 153 GB/s (P) | Yes, on macOS 26.2 and later | Not measured here |
| M6 | 12 | 170 GB/s (P) | Yes | The benchmark host: 0.27 |

Sources [P1, P2]; (P) is Apple's figure, (S) a third-party derivation from the memory's speed grade.

- **F1. The accelerators do not touch the talker or the code predictor.** At one row, MLX routes
  the quantized product to the plain matrix-vector kernel, attention to its vector kernel and float
  products to `gemv`; none of the three accelerator families is reachable (section 3.2) [X22]. That
  is most of every frame, and it matches Apple's numbers for language models [X19, P11]. They do
  serve the prefill, and they can serve the float32 codec decode inside the loop, which is 15 to 16%
  of it on the iPhone 17 Pro, at reduced precision (section 9).
- **F2. So the iPhone 17 Pro's lead over the iPhone 15 Pro is mostly not the accelerators.** What is
  left: more memory bandwidth (the A17 Pro's is not published), GPU and CPU generation, a vapor
  chamber that Apple credits with up to 40% better sustained performance [P1], the codec's share,
  and the unmeasured candidates of section 2.3.
- **F3. On accelerator chips, float32 matrix products run at reduced precision by default.** See
  section 9: it affects the float32 codec on the iPhone 17 Pro and the M6, and the owned tests turn
  it off.
- **F4. The supported set is wider than the measured set.** The hardware gate admits eleven iPhones
  on five chips [P2]; one has run the shipped build. Four of the five chips are 8 GB phones.
- **F5. What the 27 releases add.** Metal's tensor operations gained 4-bit and 8-bit integer tensors
  in 26.4 and scale planes in 27 [P12], which is what would let a future MLX use the accelerators for
  quantized products of many rows; decode stays one row. Core AI is new and needs iOS 27 [P14].
  Background GPU work is still not available on any iPhone [P13], so a take cannot continue when
  the app leaves the foreground.

### G. Heat and energy on the iPhone 15 Pro

- **G1. The slowdown is by design.** Apple describes the default performance profile as three
  phases: a burst, a period of consistent performance, then a steady state "which honors device
  constraints for longer workloads" [P9]. The farm runs show exactly that: 1.5 to 1.6 rested, 2.2
  for forty takes at nominal or fair heat, and about 3 once the phone reports serious, a state in
  which the system "reduces performance" [P15]. Part of the hot behaviour is the app's own: at
  serious or critical it blocks proactive warming and trims memory on each transition
  (`Sources/iOS/TTSEngineStore.swift:96-99`, `Sources/iOS/QVoiceiOSApp.swift:93-98`).
- **G2. Rank phone levers by energy per frame.** In the steady state, speed is the power budget
  divided by the energy a frame costs. Overlap (A3) and batching (D) finish the same work sooner at
  the same energy; they help the burst and not the plateau. Removing work helps both: fewer commits
  and wake-ups (A1), fewer kernels (B), no cache churn (A5). That is the order for the iPhone 15 Pro.
- **G3. Low Power Mode is recorded and not acted on** (audit EN-7, parked). Apple says it may reduce
  CPU and GPU performance [P15]. A take started in Low Power Mode on a 15 Pro will be slower than
  the listing's figure; the app can say so before it starts.
- **G4. The sustained-execution entitlement is not a fix.** It pins an app to the steady state from
  launch, trading the fast first takes for consistency [P9]. Short takes are the common case here.
- **G5. No measurement exists for the device that needs it most.** No iPhone 15 Pro has run the
  shipped build with the entitlement; the farm build was a diagnostics build on a charger.

### H. After the last frame, and what the listener waits for

- **H1. The prebuffer is the largest delay a listener perceives (parked, D-01).** It ignores
  generation speed and adds 0.7 to 3.8 s to every warm take on hardware that generates at twice real
  time. This report adds one point for the iPhone 15 Pro: where generation is slower than real time,
  a speed-aware buffer can also choose to start later and never pause. At an `rtf` of 2.2, playback
  runs without a pause once 55% of the take exists. BKL-53 accepted the pauses and made no prebuffer
  change for 3.0; this is the alternative, and it is a product choice, not an engine change.
  Registered knobs for the prebuffer already exist (`QWENVOICE_LIVE_PREVIEW_PREBUFFER_SECONDS` and
  `_CHUNKS`), so it can be explored without new code.
- **H2. Marking is 96 to 98% of finalization (audit section D).** About 36 ms per audio second on
  the iPhone 17 Pro and 47 on the M2 (M). Three causes are in the code: the model's weights are
  reloaded and cast on every take (`AudioSealGenerator.swift:158-161`); the LSTMs run as a Swift loop
  of single time steps, 75 per audio second for each of four LSTM layers (`:96`), which on the GPU
  is the same launch-bound pattern as the token loop; and marking starts only when the take is
  complete. ER-08 already holds the first; holding the weights changes retained memory, which the
  memory-qualification lane meters. The second is review finding PERF-9. Moving the LSTM to MLX's
  CPU device is rule-compliant but probably not worth it: marking is on the GPU by a recorded
  measurement (MLX's CPU convolution path ran near real time with about 300 MB of transients per
  window, `AudioMarking.swift:21-28`), and a CPU LSTM between GPU stages pays a device crossing each
  way, about 180 microseconds each in the pinned MLX [X6]. For the third, the convolutional stages
  are already windowed (`AudioSealGenerator.swift:299-375`), so marking could follow generation
  chunk by chunk; that is a redesign and competes with the token loop for the GPU.
- **H3. Three or four full passes over the finished audio** (`GenerationOutputAdapter.swift:2115-2270`):
  mark, re-read for Fast QC, hash, rename. The QC observer and the hash can consume the audio as it
  is written. Small in time next to H2; its value is on long takes and on the iPhone, where long-form
  segments get a second QC pass.

### I. The model, the pin and MLX itself

Each of these changes samples, needs a new artifact with its receipts, and falls under the rule that
nobody listens for 3.0: it can land only behind a pre-registered machine screen.

- **I1. A mixed-precision Speed recipe.** The bytes term (section C) is the only one a recipe can
  move. The evidence argues for caution. One port withdrew its 4-bit 1.7B bundle for "silent or
  garbled output on some inputs" although its word-error rate did not separate 4-bit from 8-bit, and
  a published study of quantized speech models found a baseline that kept its word-error rate while
  its naturalness score collapsed [R3, R8]. So a word-error screen alone cannot clear a recipe. No
  one has published 4-bit against 6-bit, 8-bit or mixed precision for this model with both
  word-error rate and speaker similarity [R8]. MLX's learned-quantization tools (DWQ and the others)
  need calibration text and next-token logits and are written for text models [X24]; adapting them
  to a speech-token model is research, not configuration.
  **Recommendation:** none before the regime split is measured on a phone. If the phones turn out
  bandwidth-bound, the experiment worth pre-registering is a lower-bit talker MLP with the code
  predictor left alone, screened with QC v2 plus speaker similarity.
- **I2. A pin move to mlx-swift 0.33.0.** It brings nothing for a one-row decode step: the commit
  policy and per-operation path are unchanged, and every newer kernel reports one row "unchanged"
  [X1, X22]. It does shift samples: MLX 0.32.4 changes how the 4-bit affine kernel accumulates its
  bias term for half-precision inputs [X18]. It breaks `compile` call sites at build time [X2], the
  tagged mlx-swift-lm cannot resolve against it [X3], and any move rebuilds every saved voice's clone
  prompt (`docs/reference/mlx-guide.md`, section 9). What it would add: the residency refresh
  option (A2), the reliable form of the fast CPU and GPU synchronization, and `eval` no longer
  holding the lock while it waits [X2, X6, X10]. **Recommendation:** no move for speed. Re-examine
  when the run-time configuration module ships in a release [X7], since it makes A1 a per-phase
  setting.
- **I3. Upstream patches MLX has declined.** Removing the per-operation completion handler measured
  280 to 367 tokens per second on a 0.8B 4-bit model and was closed for lack of response; a faster
  graph walk measured 2 to 3% [X16]. Vocello's code predictor is exactly the small, launch-bound
  kind of model those patches help. Carrying them means owning a fork of MLX, which the exact-pin
  rule exists to avoid. The rule is worth changing if the measurement supports it: the Qwen3 package
  is already an owned fork, and a fork pinned to an exact revision with a short reviewed patch list
  keeps the supply-chain identity the rule protects. Its cost is a rebase at every pin move and
  owning MLX's fixes in between. **Recommendation:** measure A1 first; if the fixed share is still
  large, re-propose the patch upstream with Vocello's numbers, and fork only if that fails.
- **I4. Nothing new upstream to switch to.** Qwen has released no new open speech weights or code
  since March 2026; the 25 Hz and voice-editing models are still not planned [R6].

### J. Core ML and the Neural Engine: judged on the evidence

The rules say MLX is the only backend. With the rules open to change, the question is whether the
evidence supports a second backend for any part of the model. It does not.

- **What exists.** Three projects export Qwen3-TTS to Core ML with the same six-part split. All three
  ship the 0.6B model. The most mature restricts the 1.7B model to macOS because compiling it needs
  more memory than an iPhone reliably has; another runs its 1.7B export on the CPU only, at 14.5
  times slower than real time on an M5 Pro; a third evaluated the model and dropped it as too slow
  [R4, R3, R5].
- **The one measured Neural Engine code predictor** (0.6B, fused into one program, M4) takes 35.7 ms
  per frame [R4]. Vocello's whole frame is 38 ms on the iPhone 17 Pro and 19 ms on the M6.
- **The known costs.** Half-precision overflow in the predictor forced float32 compute in two
  independent ports; fixed cache capacities and a fixed 10-second decoder; chunking to pass the
  Neural Engine's operation limits; a first call about seven times slower without warm-up; minutes
  of on-device compilation in one port [R3, R4, R5]. Apple's own guidance places bandwidth-bound
  decode on the GPU and the Neural Engine on power-efficient, re-authored, static-shape models
  [P14]. Core AI, the 27-era successor, needs iOS 27 [P14], above the app's 26.0 floor.
- **Assessment.** For the 1.7B model there is no evidence that a Core ML or Neural Engine path would
  be faster than the current one on any device, and direct evidence that it would be slower, larger
  and less exact. Keep MLX-only. Re-examine if someone publishes a 1.7B export that runs on an
  iPhone's Neural Engine or GPU faster than 38 ms per frame.

### K. Rejected ideas whose reopen condition is met

- **K1. The static-shape compiled talker step.** The ledger kept its branch "for a future pin
  generation", and the pins have moved to 0.32.3; it also records the do-NOT as ratified by the
  maintainer on 2026-08-01. Do not re-test it first. Its gain was host build time, which A3
  hides behind the GPU; its cost was padded attention, which nothing here reduces; and the branch is
  gone, so a re-test is a re-implementation. MLX's maintainers say the same of compiling a whole
  decode step, that it launches the same kernels either way, and mlx-swift-lm's shipped compiled
  segments gained 1.7 to 3.5% on a dense model [X21]. Re-open it only if, after A1 and A3, a trace still
  shows the talker's graph build above 5% of a frame.
- **K2. Metal 4 TensorOps matmul.** The condition was a better portable fallback or a change of the
  canonical floor. Neither has happened: the benchmark host is now an M6, but the support floor is
  still the 8 GB class without accelerators. It stays closed for the decode step in any case: the
  one-row product cannot be expressed at parallel scope (ledger O, finding 1), and for the many-row
  products of the prefill MLX already routes to its own accelerator kernels on the newer chips.
- **K3. The cache-clear A/B** could not run on the farm without the entitlement. It can run on the
  Mac today with a registered knob, and on the maintainer's phone in a device window (A5).

## 6. The refactor, in stages

The maintainer has decided that an ambitious overhaul of the core precedes the iOS submission and
has removed the target dates. This section therefore orders the work by gates, not dates, and
designs the larger change the cards point to, not only the small ones.

### 6.1 The design: a frame pipeline

Today's streaming loop is one 420-line body inside a 6,693-line file (`Qwen3TTS.swift:3883-4307`)
that builds a frame, submits it, waits, reads four scalars, then does its bookkeeping. The cards of
section 5 are all pieces of one redesign:

| Part | Today | After | Cards |
|---|---|---|---|
| Frame state | Token history, end-of-speech and counters on the host | Lazy arrays: a seen-mask, an end flag, sampling keys. The host reads one frame late | A3 |
| Sampling | 16 uncompiled sampler graphs per frame | One compiled function per sampler shape, `(logits, mask, key) -> token` | B3 (PERF-3) |
| Code predictor | 15 compiled calls, 15 samplers, buffers crossing each call | One compiled function per frame with its cache inside | B5, PERF-4 |
| Talker layer | Seven quantized products, a twelve-kernel rotary step | Four products, an eight-kernel rotary step (four if the compiled form keeps the digest), tables built once per take | B1, B2 |
| Submission | 120 to 140 commits per phone frame; nothing resident | A few commits per frame; weights in residency sets during a take | A1, A2 |
| Shape | Batch of one assumed throughout | Every array carries a batch axis, with one row shipped first | D |
| Decoder | Unbounded cache; warm-up shapes that production never uses | The model's 72-frame window; production shapes warmed; a primed state per saved voice | PA-16, D-02 |
| After the last frame | Mark, re-read, check, hash, rename | Mark, check and hash as chunks arrive; weights held | H2, H3 |
| Memory | Fixed bands; every table resident | Bands from the measured limit; the text embedding read by row | E1, E2 |

Splitting the loop, the samplers, prompt assembly, loading and diagnostics into separate files is
part of the same work: it is what makes the frame pipeline reviewable.

### 6.2 Stages and gates

| Stage | What | Output | Gate to pass |
|---|---|---|---|
| 0. Instruments | Fixed-seed PCM digests per mode as a regression net; the loop's build, enqueue and wait totals and kernel time in the records; the two-tier split; the command-buffer sweep with the phone's limits replayed on the Mac; the reduced-precision screen with a watermark check | No product change | M1 to M5 of section 7 produce numbers |
| 1. Submission layer | Command-buffer sizes per chip class; one cache clear per take; core placement confirmed; residency during a take only if it measures faster | Bit-identical, with the digest deciding for the cache clear | Digest equal; a measured gain; no higher peak; no new interface hitches |
| 2a. Frame pipeline, identity-preserving | Lagged reads with the seen-mask; compiled samplers with the same random stream; fused projections; the cheaper rotary step; the predictor frame as one function if the stream can be kept | Bit-identical | Digest equal per step; each step measured alone |
| 3. Memory | The 6,144 MB budget and bands from the measured limit; text-embedding rows from the file; a longer foreground idle window; the peak counter reset | Bit-identical | Digest equal; the resident saving measured |
| 4. Finalization and preview | Weights held for marking; marking, QC and hash during generation; the speed-aware prebuffer | Bit-identical if marking's arithmetic is unchanged | Digest equal; every take still marked and checked before it is saved |
| 2b. Frame pipeline, seed-changing | In-graph sampling that changes the random stream, if 2a could not keep it; static talker cache | Samples change | A pre-registered machine screen; one release-note line |
| 5. Decoder | The 72-frame window with upstream's landed version as reference; primed decoder state per voice | Samples change | The ER-09 screen; first-chunk and long-take figures |
| 6. Batch engine | Rows for long-form and line batches on the Mac at two to four rows; the iPhone only after M8 and under section 8's heat rule | Samples change for batched takes | The two-row probe of card D; per-row reproducibility at fixed seed |
| 7. An owned MLX fork, if stage 0 says so | The per-operation completion handler; commit limits scoped to decode until upstream ships them; a pipeline cache for the first launch | Bit-identical | Stage 1 measured first; each patch offered upstream |

Against the parked roadmap items: stage 0 is ER-01; stages 1, 2a and 4 are ER-08; stage 3 is ER-07;
stages 2b and 5 are ER-09 and PA-16; stages 6 and 7 would be new items.

### 6.3 The overhaul comes before the iOS submission

Decided by the maintainer on 2026-11-10: the core overhaul is performed before the iOS App Store
submission, and the roadmap carries no dates. Build 30 stays in TestFlight; the submission candidate
is the build that carries the overhaul, and the candidate's records and rows run once, on that
build. What remains is the scope of "the overhaul", and one constraint the maintainer has kept
shapes it: nobody listens.

- **The core of the overhaul: stages 0, 1, 2a, 3 and 4, with the heat pause of section 8.3.** Their
  output is bit-identical to today's by proof, so they need no judgement about audio at all. The
  first public version then carries the faster loop, the corrected memory budget, a settled answer
  on reduced precision and a documented response to heat, and the listing's speed sentences are
  rewritten from measurement.
- **Stages 2b, 5 and 6 change samples.** They can be part of the overhaul, since no date forbids
  it, but each needs a machine screen strong enough to clear it (section 1.2), and that screen has
  to be built first. This report's advice is to cut the submission candidate after the core stages
  and to let these follow the first approval: a new sample path in front of a first review adds
  risk and no compliance. The decision is the maintainer's.
- **Stage 7 only on evidence** from stage 0.
- **A check on the premise.** If stage 0 shows the core stages are worth less than about 10% on the
  phone, say so before building them: the overhaul is still worth doing for memory, for the heat
  pause and for the reduced-precision answer, but not for speed.

### 6.4 What to expect, honestly

Stages 1 and 2a are estimated at 5 to 20% on the M2 and the iPhone 17 Pro, less on the M6, unknown
on the iPhone 15 Pro. Not one of those figures is measured on Vocello, and the verification pass
weakened several: the lookahead is capped by MLX, the wired limit may cost time, and the one
elasticity figure the ledger has comes from an unoptimized build. The ledger's own history says
estimates in this code base miss in both directions: the fused rotary step was forecast at 2 to 3%
and delivered 26%, and the compiled talker step was expected to help and did nothing. Stage 0 exists
so that the next choice rests on a number.

The iPhone 15 Pro needs to be about twice as fast when settled (2.2 to 1.0) to reach real time. The
identity-safe stages are estimated at a fraction of that, and its steady state is set by heat.
Reaching real time there needs a measured answer to section 2.3's fifth reading first; it may need
the bytes term reduced (card I1), and it may not be reachable at all. The listing already says so.

## 7. The measurement plan for when the project resumes

Cheapest first. Identity-safe changes are compared by PCM digest at a fixed seed. None of it was run
for this report, and each row names what it needs that does not exist yet. One gap is common to M1,
M3 and M5: they set `MLX_` variables that no registry or record signature knows today, so a record
made with them would look like any other. Registering them comes first.

| # | Measurement | Where | Decides |
|---|---|---|---|
| M1 | The shipped configuration against `MLX_ENABLE_TF32=0`, on Voice Cloning short takes (they exercise the speaker encoder and the first chunk) and one Built-in take: PCM difference, Fast QC's onset-burst warning, a watermark detection check, speed. The runtime tests already have a `--shipped-config` mode for the parity side (`scripts/macos_test.sh:1496-1512`) | M6 | Section 9, item 1; section 8.5 |
| M2 | Speed and Quality tiers on the same host: solve `fixed + bytes / bandwidth`. Needs a Quality model installed on the M6 and a Quality cell, neither of which the gate bench has today | M6 | The regime split (section 2.3), and whether sections A and B or section C matter there |
| M3 | Command-buffer sweep: 20, 40, 80, 160, 320 operations with 40, 160, 400, 1,000 for the second limit. The first point replays the phone's commit rate on the Mac. The keys must first be registered diagnostics | M6 | A1, and a first estimate for the phone |
| M4 | Publish per take the loop's graph-build, enqueue and wait totals (the counters exist, `Qwen3TTS.swift:3594-3615`), with kernel and user CPU and context switches per frame | Any | A3's bound; ER-01 |
| M5 | Wired limit held during a take against none. The 8 GB emulation on the M6 proves policy and footprint only, not speed (`docs/reference/mlx-guide.md`, section 9), so the floor's answer needs real 8 GB hardware | M6 | A2 |
| M5b | Per-chunk cache clears on and off on a 16 GB Mac, with the registered `QWENVOICE_FORCE_MEMORY_CLASS` knob | M6 | A5, before any phone time |
| M6 | PCM digest for B2, then B1, then B5 with the sampler unchanged | M6 | Whether each is identity-safe |
| M7 | In a device window: the limit at launch from `os_proc_available_memory()` plus footprint; the M3 sweep at three points; one clear per take against per chunk; one Metal System Trace for GPU busy time and performance state. Needs a diagnostics build and ER-01's per-chunk-clear knob | iPhone 17 Pro | A1, A5, E1 on the phone |
| M8 | The shipped build with the entitlement on an 8 GB phone: rested, settled and hot speed with M4's counters | An iPhone 15 Pro, 16 or 17 | G5 and section 2.3's fifth reading. No such device is available today; the farm drops the entitlement |

Two cautions carried from the ledger. Take medians of warm takes against a same-day control, because
heat moves the M-series floor too (ledger H, P2). And a tracer changes this workload: record speed
without it and use traces only for shares (ledger H, P0).

A check that costs nothing: assert at run time that the talker's cache is bf16. Upstream found a
float32 speaker embedding leaking into the prefix and running every step in float32, at 2.2 to 2.4
times the cost [R1, R2]. The records show no such slowdown here, and a canary would keep it so.

## 8. App Store compliance of every recommendation

The maintainer's condition is that the result be absolutely App Store compliant. Guideline text was
re-read on 2026-11-10 from Apple's App Review Guidelines page; 2.4.2, 2.5.1, 2.5.2 and 2.5.4 are
quoted from the page itself, and 2.5.19 and 4.2.3(ii) as the repository's own audit verified them on
November 4 (`docs/audits/2026-11-04-app-review-readiness.md`).

### 8.1 The guidelines this work can touch

| Guideline | Text | What it means here |
|---|---|---|
| 2.4.2 | "Design your app to use power efficiently and be used in a way that does not risk damage to the device. Apps should not rapidly drain battery, generate excessive heat, or put unnecessary strain on device resources." | Speed work must not turn into heat. See 8.3 |
| 2.5.1 | "Apps may only use public APIs and must run on the currently shipping OS." and "Apps should use APIs and frameworks for their intended purposes" | Every lever must use public API, for its purpose |
| 2.5.2 | "Apps should be self-contained in their bundles, and may not read or write data outside the designated container area, nor may they download, install, or execute code which introduces or changes features or functionality of the app" | All code, kernels and settings ship in the bundle |
| 2.5.4 | "Multitasking apps may only use background services for their intended purposes: VoIP, audio playback, location, task completion, local notifications, etc." | No background trick to keep generating |
| 2.5.19 | No "hidden, dormant, or undocumented features" | Tuning knobs stay out of the shipped app |
| 2.3.1(a) | New features and changes "must be described with specificity in the Notes for Review" | The notes and the listing quote speeds; they change with the speed |
| 4.2.3(ii) | Disclose the size and prompt before a download needed at first launch | Any new model artifact is a new download |

### 8.2 Each lever, checked

| Lever or stage | Verdict | Condition |
|---|---|---|
| A1, command-buffer sizes | Compliant | The values are constants set by the app at launch for its own library; never fetched or user-visible switches |
| A2, residency sets and a wired limit | Compliant | `MTLResidencySet` is public API on iOS 18 and later, used for its purpose |
| A3, A4, A5, B1 to B5 | Compliant | Internal changes; no API, permission, download or metadata is touched |
| D, batching | Compliant on the Mac. On the iPhone only under 8.3 | Two rows draw more power for the same time; that is the heat rule's subject |
| E1, the limit read at launch | Compliant | `os_proc_available_memory` and the increased-memory entitlement are public and already in use. Game Mode must stay off: Apple's support staff state that an app that enables it and is not a game "will be rejected by App Review" [P6] |
| E2, embedding rows from the weights file | Compliant | The file is inside the app's container and already hash-verified |
| H2 and H3, marking and checks during generation | Compliant if every saved or exported take is still marked and checked | The review notes promise that "every generated take, including exported files, carries an inaudible watermark". No redesign may leave a path that saves an unmarked take |
| I1, a new quantization recipe | Compliant | A new artifact is a new download with its size disclosed and its checksum pinned (4.2.3(ii)), as today |
| I3 and stage 7, an owned MLX fork | Compliant | It is compiled into the bundle. Its Metal kernels are built at run time from source that ships in the binary, exactly as upstream MLX does in the build already in TestFlight. Nothing may be fetched |
| J, Core ML | Compliant, and not recommended | No compliance reason for or against |
| Stage 0, new counters | Compliant | They stay on the device or in development builds; "Data Not Collected" stays true |
| A pinned seed that no longer reproduces an old take (stage 2b) | Compliant | The description says "Pin a seed to reproduce a take". It stays true for takes made after the update; say so in What's New |

### 8.3 Heat (2.4.2) is the guideline this work can actually break

Generation is never slowed or stopped for heat today, by a recorded choice: the thermal state only
blocks proactive warming between takes (`Sources/iOS/TTSEngineStore.swift:96-100`), and the
long-form runner does not read it. The farm's 33-minute soak held an
iPhone 15 Pro at the serious state from its second take to its last. A single take is ordinary heavy
use. A long-form project that drives a phone hot for half an hour is the case the guideline
describes, and Apple's advice at that state is to "reduce CPU and GPU usage by stopping or deferring
work" [P15].

- **Recommendation, part of stage 2a or 4:** between long-form segments, and never inside a take,
  pause while the state is serious or critical, and tell the user why. It costs nothing on a cool
  phone and it is the documented response.
- **Rank iPhone levers by energy** (section 5, G2). Removing work is compliant by construction;
  overlap and batching are compliant only with the pause above.
- **Low Power Mode:** say before a long take that it will be slower; do not fight the setting.

### 8.4 What must never be used

- Game Mode, or any game-only treatment, for an app that is not a game.
- Private API or debugging entitlements: the kernel's memory-limit controls, GPU wiring controls,
  `increased-debugging-memory-limit`.
- A background audio, VoIP or location mode to keep a take running. Background GPU work is not
  available on any iPhone [P13]; the app's cancel-and-unload on backgrounding is the compliant
  behaviour.
- Kernels, limits or feature switches delivered from the network. The review notes already state
  that "no feature is enabled remotely".
- A release build that still reads tuning knobs from its environment. The sweep of stage 0 uses the
  registered-diagnostics path; the shipped values are constants.

### 8.5 Two things to settle before any submission

1. **The watermark under reduced precision.** On the iPhone 17 Pro the watermark model's float32
   products run at reduced precision by default (audit finding F-17; section 9, item 1), and the
   parity contracts run with that switched off. The review notes and the listing promise the
   watermark. M1 must include a detection check on a take made with the default setting.
2. **The notes and the description quote speeds.** If any stage changes them, the same release
   updates both (`docs/reference/app-store-listing.md`), or the metadata no longer matches the app.

## 9. Observations outside the request, and where each is already recorded

The reading turned up six things that are not speed or memory levers. The verification pass checked
each against the repository's records: five are already assigned and one is a documented design
choice. So this report adds no backlog line. It adds one thing to an existing item: the watermark
check of section 8.5 belongs in the first stage of the overhaul.

| # | Observation | Where it already lives |
|---|---|---|
| 1 | **Reduced-precision float32 on the newest chips reaches the watermark and the codec.** MLX defaults `MLX_ENABLE_TF32` to 1 (`utils.h:214-216`), which on A19 and M5 or later chips routes float32 matmul and attention to accelerator kernels at reduced precision (`backend/metal/matmul.cpp:916-919`) [X20]; one report measured a relative error of 7e-4 to 1e-3 on an iPhone 17 Pro Max against 1e-7 with the switch off [X20]. `scripts/macos_test.sh:1496-1512` turns it off for the parity contracts and has a shipped-configuration mode, run nightly, that skips them | Audit finding F-17 ("runtime tests disable TF32; production path untested"), in ER-01's gate. What this report adds: the affected production parts are the float32 codec, the speaker encoder and the watermark, on the iPhone 17 Pro and the M6 but not on the iPhone 15 Pro or an M2; the half-precision codec was withdrawn for a first-chunk burst measured on an M2, which has no accelerators; and the reference guides do not mention the switch. The retained takes argue against a gross defect: 27 Voice Cloning takes on the iPhone 17 Pro and the M6 passed Fast QC with no onset-burst warning, where the withdrawn codec failed 4 of 28. M1 in section 7 settles it |
| 2 | The iPhone's mode switch clears the package caches, which drops the resident speech tokenizer the package keeps for phones with 7 GiB or more (`Sources/QwenVoiceCore/NativeEngineRuntime.swift:1631-1646`, `Qwen3TTS.swift:498-504`, `:1274-1282`), so the residency never helps there | The October 13 review (`docs/audits/2026-10-13-core-engine-review.md:615`) |
| 3 | On the Mac an idle unload leaves the package caches in place, the resident tokenizer included | A documented design choice, not a defect: "macOS intentionally preserves" them so a take after idle stays fast (`NativeEngineRuntime.swift:2362-2370`) |
| 4 | The `isBatch` branches of the memory policy cannot run: the engine refuses any request with a batch index (`Sources/QwenVoiceCore/MLXTTSEngine.swift:819-822`) | Audit finding B-13, in ER-06 |
| 5 | On the iPhone and the 8 GB Mac, prewarm warms decoder shapes of 4, 1, 2 and 3 frames while production chunks are 7 and 14 (`Qwen3TTS.swift:2087-2112`) | With D-02 in ER-08 |
| 6 | Each Voice Cloning take reads its prompt artifact from disk, with an integrity hash, before it checks the in-memory cache (`Sources/QwenVoiceCore/NativeCloneSupport.swift:357-395`) | Audit finding B-16, in ER-06 |

## 10. Corrections owed to existing documents

Listed, not made. The first four rest on this report's own reading. Items 5, 7, 8 and 9 were
reported by the evidence survey and confirmed by the numbers check (section 12); item 6 was not
re-verified.

1. **The iPhone process limit.** `docs/reference/mlx-guide.md:386`, audit finding D-06 and ER-07's
   note give 8,192 MB for the 12 GB iPhone under iOS 27. The shipped builds read 6,144 MB (section 5,
   E1).
2. **What the phone's kernel time is.** BKL-53's note calls the iPhone 17 Pro's kernel time, context
   switches and page faults "consistent with the unmeasured MLX cache clears". The records point to
   command-buffer commits (section 2.3).
3. **What the 49% GPU-busy figure is.** It was measured on the 8 GB M2 with an unoptimized build
   under a tracer on MLX 0.30.6 (`benchmarks/OPTIMIZATION.md` section M). The October 13 review's
   "about 2,900 kernel launches" is a count from code, not a measurement. The review quotes both
   without that context (`docs/audits/2026-10-13-core-engine-review.md:443-445`).
4. **Reduced-precision float32 is missing from the reference guides.** The audit records it (F-17)
   and the test script explains it, but `docs/reference/mlx-guide.md` and
   `docs/reference/performance-guide.md` do not mention `MLX_ENABLE_TF32` (section 9, item 1).
5. `docs/reference/mlx-guide.md:466` cites the ledger's "0.74% slower" as re-confirming the rejected
   quantized-inputs compile; the ledger attributes that figure to the static-shape talker compile.
6. The ledger gives two causes for the half-precision codec's 5% cost: convolution throughput in
   section N, and "elsewhere in the decode graph" in sections Q and R.
7. Speech-tokenizer residency on the iPhone is described three ways: gated on in the package's
   `PERFORMANCE.md`, left disabled in the ledger's section R, and "never engages" in the October 13
   review.
8. Audit finding D-09's 4.5 to 5.1 GB on the 8 GB Mac comes from records that the September 25
   benchmark audit found double-counted.
9. `docs/reference/ios-engine-optimization.md` still carries the projection that the iPhone 15 Pro
   would run at about real time; the farm measured 1.5 to 3.2.

## 11. Sources

All accessed 2026-11-10. Three read-only research agents gathered them and kept fuller notes with
the quoted passages; the lead read those notes and verified in the pinned source every MLX claim
that carries a file and line. Figures from other projects are analogies (grade **A**), never
predictions. Items marked (S) are secondary: a third-party measurement, a press report or a forum
post with no reply from Apple.

**MLX**

- [X1] MLX releases, including v0.32.2 (the core the pin vendors) and v0.32.4:
  https://github.com/ml-explore/mlx/releases
- [X2] mlx-swift 0.33.0 release notes: https://github.com/ml-explore/mlx-swift/releases/tag/0.33.0
- [X3] mlx-swift-lm 3.32.3 package manifest:
  https://github.com/ml-explore/mlx-swift-lm/blob/3.32.3/Package.swift
- [X4] MLX issue 4521, command-buffer boundaries (S, reporters on M3 Ultra and M5 Max):
  https://github.com/ml-explore/mlx/issues/4521
- [X5] MLX pull request 4562, run-time command-buffer limits, with the maintainer's reply:
  https://github.com/ml-explore/mlx/pull/4562
- [X6] MLX issue 4438, dispatch and synchronization cost (S, M3 Ultra):
  https://github.com/ml-explore/mlx/issues/4438
- [X7] MLX pull request 4647, the configuration module (merged, unreleased):
  https://github.com/ml-explore/mlx/pull/4647
- [X8] mlx-lm v0.32.2, `generate_step` and `make_repetition_penalty`:
  https://github.com/ml-explore/mlx-lm/blob/v0.32.2/mlx_lm/generate.py and
  https://github.com/ml-explore/mlx-lm/blob/v0.32.2/mlx_lm/sample_utils.py
- [X9] MLX memory management documentation:
  https://ml-explore.github.io/mlx/build/html/python/memory_management.html
- [X10] MLX issue 4609 and pull requests 4633 and 4211, residency sets:
  https://github.com/ml-explore/mlx/issues/4609 , https://github.com/ml-explore/mlx/pull/4633 ,
  https://github.com/ml-explore/mlx/pull/4211
- [X11] mlx-swift-lm 3.32.3, `TokenIterator`:
  https://github.com/ml-explore/mlx-swift-lm/blob/3.32.3/Libraries/MLXLMCommon/Evaluate.swift
- [X12] MLX issue 3789, maintainer replies: https://github.com/ml-explore/mlx/issues/3789
- [X13] mlx-swift-lm issue 124, maintainer replies:
  https://github.com/ml-explore/mlx-swift-lm/issues/124
- [X14] mlx-swift-lm pull request 611: https://github.com/ml-explore/mlx-swift-lm/pull/611
- [X15] mlx-swift, "Running on iOS":
  https://github.com/ml-explore/mlx-swift/blob/0.32.3/Source/MLX/Documentation.docc/Articles/running-on-ios.md
- [X16] MLX pull requests 4048 and 3920 (closed unmerged; S for their figures):
  https://github.com/ml-explore/mlx/pull/4048 , https://github.com/ml-explore/mlx/pull/3920
- [X17] MLX pull request 4249 and discussion 615, memory-mapped weights:
  https://github.com/ml-explore/mlx/pull/4249 , https://github.com/ml-explore/mlx/discussions/615
- [X18] MLX pull request 4516, the fast one-row kernel and the bias-term change:
  https://github.com/ml-explore/mlx/pull/4516
- [X19] Apple, "Exploring LLMs with MLX and the Neural Accelerators in the M5 GPU" (2025-11-19):
  https://machinelearning.apple.com/research/exploring-llms-mlx-m5
- [X20] MLX precision documentation and issue 3702 (S for the error figures):
  https://ml-explore.github.io/mlx/build/html/usage/precision.html ,
  https://github.com/ml-explore/mlx/issues/3702
- [X21] MLX pull request 4296 and mlx-swift-lm pull request 467, compiling a decode step:
  https://github.com/ml-explore/mlx/pull/4296 , https://github.com/ml-explore/mlx-swift-lm/pull/467
- [X22] MLX pull request 3764 and issue 4265, small-batch quantized kernels; pull requests 4712, 4781
  and 4787 for "M = 1: unchanged": https://github.com/ml-explore/mlx/pull/3764 ,
  https://github.com/ml-explore/mlx/issues/4265
- [X24] mlx-lm, learned quantization:
  https://github.com/ml-explore/mlx-lm/blob/v0.32.2/mlx_lm/LEARNED_QUANTS.md

**Apple platform**

- [P1] Apple Newsroom chip announcements: A17 Pro (2023-09-12), A19 Pro (2025-09-09), A20 Pro
  (2026-09-09), M2 (2022-06-06), M5 (2025-10-15), M6 (2026-08-25), under
  https://www.apple.com/newsroom/ . Phone memory types and bandwidths are third-party (S).
- [P2] Required device capabilities, device matrix:
  https://developer.apple.com/support/required-device-capabilities/
- [P3] xnu `kern_memorystatus.c` (the 26.x kernel line; no 27 source is public), the
  increased-memory-limit entitlement and `os_proc_available_memory`:
  https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_memorystatus.c ,
  https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.kernel.increased-memory-limit ,
  https://developer.apple.com/documentation/os/os_proc_available_memory
- [P4] Memory accounting: WWDC18 session 416 and WWDC22 session 10106; `makeBuffer(bytesNoCopy:)`;
  "Reducing the memory footprint of Metal apps". Third-party measurements of no-copy buffers (S):
  https://developer.apple.com/videos/play/wwdc2018/416/ ,
  https://developer.apple.com/videos/play/wwdc2022/10106/ ,
  https://developer.apple.com/documentation/metal/reducing-the-memory-footprint-of-metal-apps
- [P5] The limit in practice (all S): Apple Developer Forums threads 834805 and 805161, no Apple
  replies; a third-party report on Game Mode and the 8 GB tier; press reports of iOS 27 beta 3:
  https://developer.apple.com/forums/thread/834805 , https://developer.apple.com/forums/thread/805161 ,
  https://github.com/LiveContainer/LiveContainer/issues/1587 ,
  https://www.igen.fr/ios/2026/07/ios-27-beta-3-repousse-la-limite-de-ram-pour-les-applications-plus-de-8-go-157133
- [P6] Apple Developer Technical Support on Game Mode and App Review:
  https://developer.apple.com/forums/thread/782343
- [P7] Apple Tech Talk 110147, tuning CPU job scheduling:
  https://developer.apple.com/videos/play/tech-talks/110147/
- [P8] "Tuning your code's performance for Apple silicon"; a third-party measurement of
  background-class placement (S):
  https://developer.apple.com/documentation/apple-silicon/tuning-your-code-s-performance-for-apple-silicon
- [P9] Apple Tech Talk 111372 and the sustained-execution entitlement:
  https://developer.apple.com/videos/play/tech-talks/111372/ ,
  https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.sustained-execution
- [P10] "Understanding the Metal 4 core API" and WWDC25 session 205:
  https://developer.apple.com/documentation/metal/understanding-the-metal-4-core-api
- [P11] Apple Tech Talk 111432, machine learning on the M5 and A19 GPUs:
  https://developer.apple.com/videos/play/tech-talks/111432/
- [P12] WWDC26 session 330, tensor operations: https://developer.apple.com/videos/play/wwdc2026/330/
- [P13] Apple Developer Technical Support on background GPU access:
  https://developer.apple.com/forums/thread/797538
- [P14] Core AI documentation; Apple, "On Device Llama 3.1 with Core ML" (2024-11-01):
  https://developer.apple.com/documentation/coreai ,
  https://machinelearning.apple.com/research/core-ml-on-device-llama
- [P15] `ProcessInfo.ThermalState`; Low Power Mode in the Energy Efficiency Guide:
  https://developer.apple.com/documentation/foundation/processinfo/thermalstate-swift.enum ,
  https://developer.apple.com/library/archive/documentation/Performance/Conceptual/EnergyGuide-iOS/LowPowerMode.html

**Other implementations of Qwen3-TTS**

- [R1] mlx-audio (pull requests 534, 644, 1117, 1118; issues 851 and 874):
  https://github.com/Neywa-Labs/mlx-audio
- [R2] mlx-audio-swift (pull requests 82, 315, 369): https://github.com/Neywa-Labs/mlx-audio-swift
- [R3] soniqo speech-swift (pull requests 450 and 333, the inference and Core ML benchmark
  documents): https://github.com/soniqo/speech-swift
- [R4] Argmax TTSKit (pull requests 513 and 494): https://github.com/argmaxinc/argmax-oss-swift
- [R5] FluidInference conversion log and FluidAudio's model list:
  https://github.com/FluidInference/mobius , https://github.com/FluidInference/FluidAudio
- [R6] Qwen: repository history, issue 294, and the technical report (arXiv 2601.15621):
  https://github.com/QwenLM/Qwen3-TTS , https://arxiv.org/abs/2601.15621 . The precision guidance is
  recorded in `docs/audits/2026-10-17-qwen3-tts-model-research.md`.
- [R7] CUDA engines and the vLLM-Omni engineering post (2026-06-23):
  https://vllm.ai/blog/2026-06-23-vllm-omni-tts ,
  https://github.com/saichranreddy/Qwen3-TTS-Engine , https://github.com/andimarafioti/faster-qwen3-tts
- [R8] Quantization quality: soniqo's round-trip benchmark and TTS-Q (arXiv 2610.12474):
  https://soniqo.audio/benchmarks , https://arxiv.org/abs/2610.12474

**Not verified, and it matters**

- Every overhead figure from MLX's tracker is one reporter on a large Mac. None exists for an
  iPhone or a base chip.
- The A17 Pro's GPU generation is inferred (16), not read from a primary source.
- Phone memory bandwidths are derivations from the memory's speed grade.
- How residency sets and wired buffers count against an iPhone's limit.
- Whether Game Mode is what raises the limit: no Apple statement, no controlled A/B.
- The device and model behind the other Swift port's 31.8%.
- Digits taken from the vLLM-Omni post, the technical report's latency table and one benchmark page
  were read through a summarizing tool and should be re-read before they are quoted elsewhere.

## 12. How this report was checked

Two read-only agents checked a draft of sections 2 to 5 and 7 to 11. Neither was given the verdict,
the ranking or the stages. Both read the repository and the pinned MLX; neither built or ran
anything. Everything below was corrected before this version.

### 12.1 Numbers and rules

**Reproduced from the records:** every cell of the five measured rows in section 2.2; the layer
sizes and the bytes-per-frame table (the predictor's head size of 128 is confirmed by the 8-bit
artifact's size); the two-tier fit (21.9 ms and 78 GB/s); the weight traffic at measured speeds; the
finalization figures; the process limit by build and the position of the Game Mode commit between
builds 26 and 28; every landed and rejected figure in section 4; every cited MLX and loop line.

**Overturned, and how the report changed:**

| The draft said | The check found | Change |
|---|---|---|
| MLX's second commit limit counts megabytes, forcing a commit every layer and a half | It counts array elements (`array.h:346`); it does not bind today | Sections 3.2 and A1 rewritten; the sweep still raises both limits |
| MLX's peak figure is cumulative since launch | It is reset at every request (`NativeEngineRuntime.swift:855`) | The claim and its "finding" removed |
| Nothing in the repository mentions the reduced-precision switch | It is audit finding F-17, with a nightly shipped-configuration job | Section 9 item 1 now credits it and keeps only what is new |
| Frames per second divided by 12.5 is the inverse of `rtf` | Frames per second is loop-only; `rtf` is the whole request | Section 2.2 relabelled; per-frame figures restated against request time |
| A commit costs "at most" 71, 122 and 54 microseconds of kernel time | Not a bound; the operation count is itself an estimate | Restated as ranges, with the circularity named |
| The 49% GPU-busy figure confirms the two-term fit | It is from an unoptimized build on an older MLX and measures something else | Called "of the same order", not a confirmation |
| Build windows are 19 to 27% of wall | The ledger says 19 to 23% | Corrected |
| The iPhone's peak is 3.06 GB at most | 3.17 GB in the October 27 memory-qualification record | Corrected to about 3.2 GB |
| The A17 Pro's bandwidth is about 51 GB/s | Not published; that was a derivation | Removed |

It also found rule collisions the draft had not named. They are now in section 1.2: the November 2
decision against prebuffer or memory-policy changes, the request-local memory rule against a wired
limit, the registered-diagnostics rule for MLX's environment keys, and the roadmap's classification
of the per-chunk clear as numerics-shifting.

### 12.2 Mechanisms

**Held:** every loop line reference; every MLX reference for commits, limits, back-pressure,
residency, the accelerator gate and quantized routing; that weights count toward the second limit
and that the settings can be applied in time on every host; that mlx-swift's wired-memory manager
reaches the allocator on iOS; that the lookahead changes no random draw for a kept frame; that the
code predictor's random state can live inside a compiled function; that the text embedding is unused
in the loop and 8-bit in both tiers; and the process-limit records.

**Weakened or refuted, and how the report changed:**

| Card | What the refuter showed | Change |
|---|---|---|
| A1 | "The phone may gain more" does not follow: per millisecond it commits no more often than the M6, and kernel time is not shown to be on the critical path | Claim removed; estimate kept at 5 to 15% for every device |
| A2 | A wired limit adds a residency-set commit on every allocation and release, on the tier that releases most; the fill order is arbitrary; MLX's ceiling exceeds the phone's limit | Estimate now "unknown, possibly negative"; A2 comes after A5 or not at all |
| A3 | MLX's ten-buffer window caps the overlap at about 8% of a phone frame; today's read would wait behind the speculative frame; under lookahead the cache write may become a full copy; the discarded frame has costs | Estimate cut to 0 to 8% alone; three traps written into the card |
| A5 | The 1 ms kernel difference is confounded; the roadmap classes the change as numerics-shifting; a Mac A/B exists today | Estimate reduced to "unknown"; the Mac A/B added as M5b |
| B2 | The gather and sign fold are exact; the compiled multiply-add is not provably identical; the step is 12 dispatches, not 10 | "Identical by construction" limited to the exact part |
| B5 | The other port's 30% exceeds the host window Vocello has measured for that loop (9.7% of wall); a compiled float32 sampler cannot be proven identical by a few seeds | Estimate capped; identity caveat added |
| F1, F2 | The float32 codec decode inside the loop can use the accelerators | Both cards and the verdict corrected |
| H2 | Marking on the GPU is a recorded, measured choice | The CPU-LSTM idea downgraded |
| Section 9 | Five of the six observations were already assigned and one is a design choice | Section rewritten; no new backlog lines |

Three line references were wrong and are corrected: the code predictor's rotary lines, the iPhone
band constants, and BKL-53's location and wording.

### 12.3 What neither check could do

Neither measured anything, and neither checked the outside sources themselves, only that the report
uses them consistently with the research notes. Every estimate in section 5 is still an estimate.
