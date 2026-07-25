# QwenVoice / Vocello Performance Architecture

> **Imported research snapshot (2026-07-17).** Converted 2026-07-22 from the external HTML
> report bundle into the repository so corrections and review history stay tracked. Every
> measured figure below is a point-in-time capture from on or before 2026-07-17; the
> 2026-07-22 backend refactor review counter-verified this corpus and found its measured
> claims correct at capture with several since superseded. Superseded figures carry inline
> **Editor's note** blocks; see [`docs/research/README.md`](README.md) for the verification
> summary and [`config/runtime-refactor-contract.json`](../../config/runtime-refactor-contract.json)
> for current phase status.


## Memory Reduction, Streaming Preview, Latency Decomposition and Future Optimization Roadmap

**Repository:** `PowerBeef/Vocello`
 **Reviewed branch:** `main`
 **Exact source:** [`079757abc3524ad5c0308bb1d914a9ff151c0de6`](https://github.com/PowerBeef/Vocello/commit/079757abc3524ad5c0308bb1d914a9ff151c0de6)
 **Review date:** July 17, 2026
 **Primary benchmark machine:** Mac mini M2, 8 GB unified memory
 **Secondary hardware:** physical iPhone acceptance platform
 **Scope:** model loading, MLX execution, codec generation, streaming decode, incremental output, live preview, playback buffering, memory policy, XPC lifecycle, evidence and future performance research   61% measured same-path physical-memory reduction from ~7.6 GB to ~3.0 GB   **Executive verdict.** Vocello's major performance gains did not come from one clever kernel. They came from correcting the execution architecture. The old non-streaming path retained the entire autoregressive codec sequence, its lazy MLX graph and a full final decode. The streaming path bounds the live codec window, decodes causally, appends PCM to the final WAV incrementally, emits preview chunks, clears caches under a device policy and can retire the entire macOS engine process. That changed the actual iPhone/Mac memory curve from length-growing ~7–8 GB behavior to an approximately flat ~3 GB streaming footprint. The subsequent fused Code Predictor RoPE and allocator/graph-build work raised Custom Speed from roughly 0.80× to 1.07× realtime on long content. The next largest user-visible win is now outside the neural model: Vocello's conservative smooth-first playback buffer often waits seconds after the first chunk is already available. An adaptive RTF- and jitter-aware admission policy can likely make first audible feedback 1–2.5 seconds earlier on the now-faster Custom and Design paths without changing generated audio.    7.6→3.0GB same-path physFoot +34%Custom warm long/medium RTF program gain +26%fused Code Predictor RoPE step 12.5 Hzsemantic codec frame rate 3.25 scurrent minimum smooth-first buffer 0 RSSmacOS engine after retirement

> **Editor's note (2026-07-22).** These RTF figures originate in the §H program (2026-06-09) and were still current on 2026-07-16 (canonical record `macos-xcui-benchmark-20260716-181853-b4c2e299`: custom warm 1.036/1.120/1.147) — except Clone long, which the owned core had already lifted to **1.087** by 2026-07-16, so 0.63 was superseded when this report was written. After the Phase-4 cutover the canonical macOS matrix (`macos-xcui-benchmark-20260720-172920-591696d1`) measures custom warm **0.880/0.915/0.934** — sub-realtime in every cell, under diagnosis as of 2026-07-22.


>

**Central finding:** the remaining optimization problem is no longer “make a 1.7B model fit.” It fits. The work is now to reduce latency between already-produced audio and the speaker, eliminate duplicated immutable components, trim the remaining launch/graph-build overhead and avoid trading quality for marginal memory savings.

## 1. Executive conclusions

### What produced the drastic RAM reduction

The largest reduction came from changing the lifetime of generated state:

```
legacy non-streaming
  retain every generated codec frame
  retain the lazy graph/intermediates needed by full decode
  build one complete audio tensor
  materialize/convert/write at the end

streaming
  retain only the next bounded codec chunk
  run the causal decoder incrementally
  materialize one chunk
  append it to an incremental WAV
  publish preview metadata/PCM
  release chunk state and clear caches

```

Measured on the same long Custom Speed workload:

| Path | Peak GPU allocation | Physical footprint | Length behavior |
| --- | --- | --- | --- |
| Legacy non-streaming | about 8.0 GB | about 7.6 GB | grew strongly with output length |
| Streaming product path | about 3.0 GB | about 3.0 GB | approximately flat from short through ~76 s |
| Relative reduction | about 62.5% | about 60.5% | growth largely removed |

> **Editor's note (2026-07-22).** The streaming-vs-non-streaming conclusion (≈2.5× smaller, approximately length-flat) stands. The exact ~3.0 GB figure is from the 2026-06-01 experiment; current canonical peaks are 2.56–3.52 GB (iOS) and 2.75–3.90 GB (macOS UI). Do not generalize the older number (see `docs/reference/ios-engine-optimization.md` §3).


The final PCM itself was never the multi-gigabyte problem. Seventy-six seconds of 24 kHz mono Int16 PCM is only about 3.5 MiB. The memory cliff came from retained MLX arrays, codec histories, graph/intermediate state and full-result decoding in unified memory.

### What produced the speed gains

The sequence was:

1. measure the fused lazy graph correctly rather than attributing Swift graph-build timers as GPU compute;
2. keep one evaluation boundary per semantic frame;
3. overlap causal decoder work with the next token loop using `asyncEval`;
4. reuse sampler scratch and per-step constants;
5. fuse Code Predictor RoPE into `MLXFast.RoPE`;
6. use fused scaled dot-product attention;
7. keep the useful compiled SwiGLU micro-kernel;
8. reject whole-graph compile, KV quantization and KV windowing after matched evidence showed regressions or no gain.

The fused Code Predictor RoPE change alone moved Custom Speed long warm RTF from approximately 0.81 to 1.02. The complete P2–P6 program moved Custom medium from about 0.83 to 1.11 and long from 0.80 to 1.07, with Clone long improving from about 0.55 to 0.63 in that historical program.

> **Editor's note (2026-07-22).** These RTF figures originate in the §H program (2026-06-09) and were still current on 2026-07-16 (canonical record `macos-xcui-benchmark-20260716-181853-b4c2e299`: custom warm 1.036/1.120/1.147) — except Clone long, which the owned core had already lifted to **1.087** by 2026-07-16, so 0.63 was superseded when this report was written. After the Phase-4 cutover the canonical macOS matrix (`macos-xcui-benchmark-20260720-172920-591696d1`) measures custom warm **0.880/0.915/0.934** — sub-realtime in every cell, under diagnosis as of 2026-07-22.


### How streaming preview reduces perceived latency

Preview changes the user-visible completion condition:

```
without preview:
submit → load/prefill → generate entire utterance → decode/finalize → play

with preview:
submit → load/prefill → generate first codec chunk → decode first chunk
      → buffer safely → play
      while generation, decode and final WAV append continue

```

In one current canonical cold Custom/medium take:

| Milestone | Time from submit |
| --- | --- |
| First audio chunk reaches the product path | about 2.70 s |
| Live playback is scheduled | about 5.06 s |
| Generation completes | about 7.61 s |

The existing preview therefore made feedback about 2.55 seconds earlier than waiting for final completion. It still waited about 2.36 seconds after the first chunk, primarily because the smooth-first policy requires at least 3.25 seconds of buffered audio or 35% of the estimated utterance. The model is now frequently faster than realtime for Custom and Design, so this static rule is increasingly conservative.

### Highest-value next moves

1. **Adaptive live-preview admission** keyed by predicted and observed RTF, output duration and chunk jitter.
2. **Separate first and later chunk sizes**, preserving a small first packet and using larger later packets to reduce decoder/transport overhead.
3. **Content-addressed shared tokenizer/decoder components** across all six model packages and across model-family switches.
4. **Explicit audio-engine preparation** before the first scheduled buffer.
5. **Dynamic cache and service-retention policy** based on current headroom and recent intent rather than physical-RAM class alone.
6. **A current Instruments experiment on the causal decoder and inter-frame gap**, including a separate MLX stream only if the trace proves useful overlap.
7. **A quarantined MLX 0.31.x substrate branch**, not an in-place dependency bump.
8. **A custom Code Predictor operation/kernel proof of concept** only after the low-risk work.
9. **Multi-token/speculative speech decoding** as a model-research program, not a port optimization.

## 2. Scope, source identity and methodology

This review reconstructs the optimization history from current source, historical decision ledgers, canonical benchmark records and exact implementation files. It distinguishes:

- measured production gains;
- historical experiments that were rejected;
- current bottlenecks visible in traces/source;
- low-risk product/runtime improvements;
- framework experiments;
- model-training research.

The current main head is `079757abc3524ad5c0308bb1d914a9ff151c0de6`. Project health at this source inventories 232 Swift tests, 524 Python tests, all 55 required workflow steps covered by forced-failure fixtures and a complete 50-entry unsafe-concurrency registry. Current canonical hardware evidence is fresh for generation terminal behavior, clone conditioning, event delivery, memory policy, model delivery, XPC transport and benchmark validation. Release-supply-chain evidence is separately marked stale after later dependency/security work.

### Evidence hierarchy

1. exact current source and contracts;
2. current clean canonical Mac/iPhone evidence;
3. matched same-session A/B experiments;
4. historical benchmark records bound to their source identity;
5. official framework/model documentation;
6. research papers used only for future hypotheses.

The report does not infer a performance benefit from code shape alone when a matched experiment exists. In particular, whole-graph compilation, talker source-weight release, sliding-window KV and 8-bit KV were not promoted because evidence contradicted the intuitive story.

## 3. Architecture of the current performance path

```
SwiftUI / CLI request
  │
  ├─ proactive model/conditioning warmup when admitted
  │
  ▼
QwenVoiceCore / MLXTTSEngine
  │  one active generation, typed terminal, device policy
  ▼
NativeEngineRuntime
  │  prepared checkpoint, model family, clone/design/custom conditioning
  ▼
VocelloQwen3Core / Qwen3-TTS
  │
  ├─ dual-track text + codec preparation
  ├─ 1 semantic codec token per 12.5 Hz frame
  ├─ 15 residual codebook predictions
  ├─ causal Mimi decoder, streaming state
  └─ first/later codec chunk schedule
        │
        ▼
NativeStreamingSynthesisSession
  ├─ bounded codec/audio chunk lifetime
  ├─ Float → limited Int16 scratch conversion
  ├─ incremental final WAV append
  ├─ preview PCM + exact frame offset/sequence
  ├─ persisted-WAV QC
  └─ post-generation cache policy
        │
        ▼
ordered GenerationEvent stream
  ├─ macOS: engine service → XPC client
  └─ iOS: in-process stream
        │
        ▼
AudioPlayerViewModel
  ├─ continuity validation
  ├─ AVAudioEngine / AVAudioPlayerNode
  ├─ smooth-first buffer admission
  ├─ underrun feedback
  └─ seamless handoff to final file

```

### Why XPC remains part of the performance architecture

On macOS, XPC is not primarily an IPC optimization. It provides:

- UI crash isolation from MLX/Metal failures;
- UI responsiveness under high unified-memory pressure;
- a process-retirement lever that can return engine RSS to zero;
- bounded app-side state while the ML process owns large allocations.

The per-chunk UI path was already moved off the main actor where appropriate, high-frequency counters were removed from `@Published`, and event handling avoids a redundant main-queue hop. Current performance evidence treats the app and engine as separate process owners rather than combining unrelated maxima.

## 4. Quantified optimization timeline

| Stage | Main change | Result | Disposition |
| --- | --- | --- | --- |
| Pre-optimization baseline | Full-result accumulation and final decode | RTF about 0.20–0.89; Clone roughly 7.4–8.7 GB | Replaced |
| Streaming default | Bounded codec chunks, causal decode, incremental output | Custom/Design Speed about 0.95–1.04; 2.4–3.8 GB instead of ~7–8 GB | Shipped |
| Output/QC recalibration | Punctuation-aware silence budget | Removed false dropout failures without changing engine | Shipped |
| Instruments attribution | Separated graph build, GPU flush and overlapped decoder | Found launch/CPU graph-build bottleneck; GPU only 31–37% busy overall | Foundation |
| Full quantized compile spike | Compiled quantized forward with module state as inputs | Warm RTF regressed ~5% | Rejected |
| Sliding-window KV | Rotating talker cache | <5 MB change; inert at token cap | Off by default |
| Sampler scratch/constants | Reused suppress arrays, CP masks and constants | About +1%, lower allocator churn | Shipped |
| Fused CP RoPE | `MLXFast.RoPE` in residual predictor | Custom long 0.81→1.02, about +26% | Shipped |
| KV 8-bit | Quantized KV cache | Saved ~271 MB on Clone long, cost ~8.6% RTF | Rejected |
| P6 accepted runtime | P2 + P3, official sampling retained | Custom medium/long about +34%; Clone long +15% | Shipped |
| Preview activation | Ordered preview PCM, live engine activation | Audio during generation; no measurable RTF/memory cost | Shipped |
| Smooth-first buffering | Prebuffer and underrun recovery | Stable no-underrun experience, but conservative first-play timing | Shipped; now tunable |
| Service retirement | Idle/hard-trim process exit | Engine RSS reaches zero after dwell | Shipped |
| Current canonical record | Owned core, current UI/evidence | All Custom/Design aggregate cells ≥ realtime; Clone medium/long near or above realtime | Current |

> **Editor's note (2026-07-22).** "All Custom/Design aggregate cells ≥ realtime" described the 2026-07-16 canonical record. The post-Phase-4-cutover canonical matrix (2026-07-20) is sub-realtime in every macOS cell; iOS is unchanged (1.70–1.91).


> **Editor's note (2026-07-22).** The 31–37% GPU-busy figure was captured 2026-06-09 **before** the +26% fused Code Predictor RoPE change removed ~600 kernel launches per frame; no post-P3 re-capture exists yet, so treat it as historical, not current.


### The most important negative results

Negative experiments prevented the project from accumulating complexity:

- **whole-graph `compile()`** moved more module state per call and slowed the quantized path;
- **talker source-weight early release** did not reduce load peak;
- **lossless KV windowing** saved essentially no memory;
- **small lossy KV windows** violate the no-degradation requirement;
- **8-bit KV** traded too much speed for a modest memory reduction;
- **lower sampling temperatures** did not beat official defaults in listening/quality work;
- **hard MLX memory limits** caused false allocation failures;
- **output-side silence smoothing** would mask rather than solve generation behavior.

## 5. Deep dive: why memory fell from ~7.6 GB to ~3.0 GB

### 5.1 Unified memory makes retained graphs a system-wide problem

MLX arrays live in Apple unified memory. CPU and GPU can operate on the same allocations without explicit device copies. That is a major advantage, but it means a retained lazy graph or audio tensor contributes directly to the same memory pressure seen by the entire system.

The old benchmark conflated “long output” with “large unavoidable KV cache.” Measurement disproved that. The talker KV cache was tens of MiB, not multiple GiB. The actual length-dependent growth was retained generation and decode state.

### 5.2 Non-streaming retained the whole utterance

The non-streaming Qwen path:

```
var generatedCodes = MLXArray
generatedCodes.reserveCapacity(effectiveMaxTokens)
// append one 16-codebook frame per semantic step
...
let codes = stacked(generatedCodes, axis: 1)
let audio = decodeChunk(codes)
eval(audio)

```

This retains:

- every generated codec frame as an MLX object;
- the dependency graph needed to stack and decode all frames;
- full decoder intermediates;
- the final full audio MLX tensor;
- conversion/write state after decode.

The raw codec IDs are small. Their MLX object graph, lazy dependencies and full decoder activation lifetime are not.

### 5.3 Streaming bounds the working set

The streaming path keeps:

```
pendingStreamCodes ≤ current chunk size
decoder streaming state
one decoded MLX chunk
one reusable Int16 scratch buffer
one incremental WAV writer
bounded event/preview buffers

```

After each chunk:

1. codec frames are stacked only for the chunk;
2. the causal decoder advances its state;
3. `asyncEval` schedules the audio tensor;
4. the consumer materializes samples;
5. PCM is appended to the final WAV;
6. preview data is emitted;
7. pending codec arrays are released;
8. MLX cache is cleared according to policy.

The current floor-tier first chunk is seven codec frames because `Int(0.6 × 12.5) = 7`, about 0.56 seconds of audio. Design and Clone use a 2× later chunk multiplier, while Custom's baseline currently keeps the same later size.

### 5.4 Incremental final output prevents a second full-audio peak

`IncrementalPCM16WAVFileWriter` writes a placeholder WAV header, appends each Int16 chunk and repairs the header only at finish. It reuses an `AVAudioPCMBuffer` and atomically publishes the final file.

This avoids:

- a full `[Int16]` result for the complete utterance;
- a second full-size `Data`;
- a second full file-write copy;
- a final “gather every chunk” phase.

The session also reuses a pooled PCM scratch buffer between generations, avoiding recurring allocation churn.

### 5.5 Device-specific cache discipline

Current floor-8-GB policy:

| Setting | Floor 8 GB Mac |
| --- | --- |
| MLX cache limit | 256 MiB |
| Clear cache on chunk emit | Yes |
| Token-loop memory-clear cadence | 50 frames |
| Clear cache after single generation | Yes |
| Idle unload | 120 s |
| Clone prompt cache | 1 reference |
| Post-batch trim | Hard trim |

The policy is intentionally different on higher-memory Macs. High-memory systems retain more cache and avoid needless clears; constrained systems trade some warm throughput for bounded pressure.

### 5.6 Selective component loading

The runtime profile knows the model family and requested capability. Prepared-load options can skip:

- the speaker encoder outside Base clone;
- the speech-tokenizer encoder when only decoding is needed;
- redundant tokenizer preparation/evaluation.

This matters because the Base, Custom and VoiceDesign packages are separate models. Vocello loads the family required by the current workflow rather than one synthetic all-capability model.

### 5.7 Clone cache and artifact design

On the floor tier, only one primed clone reference is retained. The repository records that retaining two can add roughly 200–400 MiB during the second prime. Disk-backed normalized references and persisted prompt artifacts recover much of the usability without holding two live prompt states.

### 5.8 Idle unload and process retirement

Model unload alone does not always return every framework/allocator page to the operating system. The macOS engine service therefore has a stronger lever: after the eligible idle/pressure lifecycle, it exits and the OS reclaims the process completely.

The trade-off is explicit:

- warm service: first chunk around the lower warm baseline;
- retired service: zero engine RSS, then a cold-start penalty;
- fresh user intent can warm again;
- idle unload must not trigger an immediate automatic rewarm.

### 5.9 Bounded UI and transport state

RAM reductions outside MLX also matter:

- generation-scoped event streams prevent old backlog contaminating the next generation;
- frontend latest-state snapshots strip preview PCM;
- high-frequency audio counters are not `@Published`;
- preview queue and retained buffers are bounded;
- raw telemetry and traces are not held by the product path.

## 6. New high-value finding: the six packages duplicate one 682 MB speech tokenizer

The production catalog shows that Base, CustomVoice and VoiceDesign—both 4-bit and 8-bit—carry the same:

```
speech_tokenizer/model.safetensors
SHA-256: 836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258
size:    682,293,092 bytes

```

The text tokenizer files are also identical.

### Avoidable storage and transfer

| Installed set | Redundant speech-tokenizer copies | Avoidable bytes |
| --- | --- | --- |
| Three Speed packages | 2 | 1,364,586,184 bytes (~1.27 GiB) |
| Three Quality packages | 2 | 1,364,586,184 bytes (~1.27 GiB) |
| All six packages | 5 | 3,411,465,460 bytes (~3.18 GiB) |

The three recommended Speed packages are currently about 7 GB combined. Sharing one immutable tokenizer component could reduce that set by roughly one fifth before counting smaller shared tokenizer/config files.

### Proposed component architecture

```
Application Support/QwenVoice/models/
  shared/
    qwen3-tokenizer-12hz/
      <integrity-digest>/
        speech_tokenizer/...
        text_tokenizer/...
        manifest.json
  models/
    custom-speed/
      talker-model...
      component-references.json
    design-speed/
      talker-model...
      component-references.json
    clone-speed/
      talker-model...
      component-references.json

```

The loader receives explicit directories for:

- text tokenizer;
- speech tokenizer decoder;
- optional speech tokenizer encoder;
- family-specific talker/speaker encoder.

Do not use unverified symlinks to bypass the existing path/integrity model. The shared component is a first-class catalog artifact with its own exact digest and reference count.

### Runtime reuse

A content-addressed `SharedQwenTokenizerPool` can hold at most one instance of the identical decoder. Model switching becomes:

```
retain verified shared decoder
unload old talker/speaker encoder
load new talker
reuse decoder buckets/state after reset

```

On the 8 GB tier, this should not mean “keep more models.” It means one decoder plus one active talker, instead of destroying and recreating an identical decoder during a family switch. Under pressure or service retirement, the shared pool still clears completely.

### Expected benefits

- 1.27 GiB less network/storage for the three Speed packages;
- lower model-switch I/O and decode-bucket warm cost;
- lower transient risk of duplicate tokenizer instances;
- one integrity identity for the shared codec;
- easier updates when only the talker artifact changes.

This is the strongest newly identified storage/load optimization in the current tree.

## 7. Deep dive: how live preview reaches the speaker

### 7.1 First packet generation

Qwen3-TTS 12Hz uses a 12.5 Hz semantic codec stream and 15 residual codebooks. Vocello's hot loop:

1. runs the main talker for one semantic frame;
2. samples codebook 0;
3. runs 15 Code Predictor steps for residual codebooks;
4. constructs the next codec/text embedding;
5. evaluates the frame and reads EOS;
6. appends the 16-codebook frame to the pending streaming chunk.

At seven frames, the first chunk represents about 0.56 seconds of audio.

### 7.2 Decoder overlap

When a chunk is ready:

- its codec frames are passed to the causal speech decoder;
- `asyncEval(audioChunk)` schedules materialization;
- the token loop can continue building/scheduling later work;
- the consumer materializes and converts the earlier chunk.

This does not make decoder compute free. It hides part of it behind subsequent autoregressive work.

### 7.3 Product-side chunk processing

For every decoded chunk, Vocello:

1. optionally computes chunk QC;
2. records the first-chunk boundary;
3. converts float samples through a limiter into a reusable Int16 buffer;
4. optionally creates preview PCM `Data`;
5. appends PCM to the final WAV;
6. updates exact frame count;
7. emits mode/title/path/duration/frame offset/sequence;
8. continues generation.

At 24 kHz mono Int16, a 0.6-second preview packet is only about 28.8 kB. A matched preview ON/OFF device experiment found no meaningful RTF or memory cost, so zero-copy preview transport is not currently a priority.

### 7.4 Ordered transport

The full preview event travels through the ordered generation stream:

- macOS: service drains the engine stream and sends events over XPC;
- iOS: the app drains the in-process stream;
- the coalesced `latestEvent` path strips preview PCM and is not used as the audio transport.

Each chunk has a generation ID, request ID, frame offset, frame count and monotonically increasing sequence.

### 7.5 Audio graph and scheduling

`AudioPlayerViewModel`:

- configures a 24 kHz mono Int16 `AVAudioEngine` graph;
- validates sample rate, frame offset and byte count;
- converts the chunk into `AVAudioPCMBuffer`;
- schedules buffers back-to-back on `AVAudioPlayerNode`;
- tracks true queued audio via completion callbacks;
- starts playback only when smooth-first admission is satisfied;
- pauses on underrun and increases fallback prebuffer;
- morphs seamlessly into final-file playback after live buffers drain.

The graph is configured before chunks arrive, which removes most first-chunk setup. It does not currently exploit every explicit AVFAudio preparation primitive.

## 8. Current smooth-first policy and its latency cost

### Current rule

The current defaults include:

```
minimum chunks:       3
minimum audio buffer: 3.25 s
estimated fraction:   35% of predicted utterance
maximum target:       8 s
underrun fallback:    +75% multiplier, bounded

```

The effective requirement is approximately:

```
Bcurrent = min(Aestimated, max(3.25 s, 0.35 × Aestimated))

```

plus the chunk-count requirement.

This rule was designed when many cells generated slower than realtime. It prioritizes uninterrupted playback over earliest feedback.

### Why it is now over-conservative for Custom and Design

Let:

```
r = generated audio seconds / wall second
A = final audio duration
B = audio buffered before playback
J = jitter and audio-engine safety margin

```

For constant generation rate below realtime, a sufficient no-underrun condition is:

```
B ≥ A × (1 − r) + J

```

For `r ≥ 1`, generation can replenish the buffer at least as fast as playback consumes it. Only jitter margin `J` is needed.

Current canonical evidence says every Custom and Design aggregate cell is at or faster than playback. A fixed 35% buffer is therefore solving a historical slower-than-realtime problem for modes that frequently no longer have it.

### Current example

One cold Custom/medium take:

```
submit                    0.00 s
first preview chunk       2.70 s
playback scheduled        5.06 s
generation complete       7.61 s

```

Current preview saves:

```
7.61 − 5.06 = 2.55 s

```

relative to waiting for the final file.

The remaining buffer delay is:

```
5.06 − 2.70 = 2.36 s

```

A safe adaptive buffer near 0.8–1.2 seconds for a faster-than-realtime cell could plausibly move audible feedback another 1.2–2.0 seconds earlier. This is an estimate to test, not a promised gain.

## 9. Recommendation P0: model-informed preview admission

### Policy

Use a conservative lower-bound generation rate rather than one universal fraction.

Inputs:

- mode;
- variant;
- device class;
- cold/warm state;
- text/language length bucket;
- historical clean RTF distribution;
- current first/second chunk production time;
- p95 chunk-gap jitter;
- audio route/engine startup time;
- estimated total duration;
- fallback history.

Algorithm:

```
rprior = lower confidence bound from canonical history
robs   = generatedAudioSeconds / generationWallSeconds after each chunk
r      = conservative blend(rprior, robs)
J      = p95 chunk jitter + measured audio start margin
Bsafe  = J + max(0, Aestimated × (1 − r))
start when:
  queuedAudio ≥ Bsafe
  AND minimum continuity-valid chunks are present

```

### Suggested initial classes

| Class | Starting policy |
| --- | --- |
| Custom/Design, lower-bound RTF ≥1.05 | 2 chunks and 0.8–1.0 s |
| Custom/Design, RTF 0.9–1.05 | formula with 1.0–1.2 s jitter |
| Clone or unknown | current smooth-first rule |
| Batch/no live playback | no preview admission requirement |
| Prior underrun in session | increase jitter target |
| Pressure/thermal warning | use more conservative lower bound |

### Safety

- Never infer continuity from progress events; use exact queued frames.
- Do not start when sequence/frame validation has failed.
- Update policy only between generations, not mid-buffer in a way that can discard queued audio.
- Preserve existing underrun pause/recovery.
- Record the exact policy and estimated/observed rates in telemetry.

### Promotion gate

- zero underruns in all promoted faster-than-realtime cells;
- no difference in final WAV or generation RTF;
- p50/p95 submit-to-first-render improvement;
- route-change and interruption tests;
- no increase in dropped audio chunks.

## 10. Recommendation P0: decouple first and later chunk sizes

Current floor-tier base chunk:

```
Int(0.6 × 12.5) = 7 frames ≈ 0.56 s

```

Current later chunks:

| Mode | First | Later |
| --- | --- | --- |
| Custom baseline | 7 frames | 7 frames |
| Design | 7 frames | 14 frames |
| Clone | 7 frames | 14 frames |

The code already has a first/later schedule. The remaining work is policy.

### Proposed experiment

| First frames | Audio | Later frames | Audio |
| --- | --- | --- | --- |
| 4 | 0.32 s | 10 | 0.80 s |
| 5 | 0.40 s | 10 | 0.80 s |
| 6 | 0.48 s | 14 | 1.12 s |
| 7 | 0.56 s | 14 or 18 | 1.12 or 1.44 s |

Expected effects:

- smaller first chunk: earlier first decode/transport;
- larger later chunks: fewer decoder calls, `Data` conversions, WAV appends, events and playback buffers;
- too-small first chunk: decoder onset artifact or poor amortization;
- too-large later chunks: burstier arrival and more underrun risk.

### Important implementation rule

Do not couple chunk schedule to experimental token-budget policies. The current Custom profiles mix max-token multipliers, minimum generated codes and later-chunk multipliers. Create a separate `Qwen3StreamChunkPolicy` so chunk tuning cannot silently alter generation length.

## 11. Recommendation P0: shared immutable tokenizer/decoder components

This recommendation affects:

- model download time;
- disk footprint;
- model-switch load;
- prepared-component cache behavior;
- peak risk during family transitions.

### Work plan

1. Generate a component inventory from the existing catalog.
2. Prove identical file sets by digest for all six artifacts.
3. Add a `sharedComponents` section to the production catalog.
4. Install shared components transactionally before dependent talkers.
5. Store per-model reference manifests.
6. Update prepared-directory validation.
7. Refactor the loader to accept component roots explicitly.
8. Key prepared tokenizer caches by component digest, not model directory.
9. Retain at most one decoder instance.
10. Clear the shared pool on pressure, full unload or service retirement.

### Compatibility

Existing installations can migrate by:

- verifying one installed copy;
- moving/copying it into the shared store;
- validating the new manifest;
- leaving existing model folders intact until the new load succeeds;
- deleting duplicate files only after an atomic state transition.

No model redownload should be required when valid matching files already exist.

## 12. Recommendation P1: prepare the audio engine explicitly

The app currently builds the AVAudioEngine graph before chunks arrive. Apple documents that `AVAudioEngine.prepare()` preallocates resources required to start and is intended to improve responsive audio start. `AVAudioPlayerNode` also exposes `prepare(withFrameCount:)`.

### Experiment

At generation acceptance or model-ready state:

```
configureLiveEngineIfNeeded()
liveEngine.prepare()
livePlayerNode.prepare(withFrameCount: expectedFirstBufferFrames)

```

Variants:

- prepare only;
- prepare + start engine when the first continuity-valid chunk arrives;
- start the engine earlier with the player stopped/paused;
- different player preparation frame counts.

Instrument:

```
buffer_ready
engine_start_begin/end
player_play_call
first_render_host_time
first_audible_estimate

```

This is a small optimization compared with model compute, but it is low risk and directly targets the last hundred milliseconds of perceived start.

On iOS, test audio-session activation and preferred I/O buffer duration separately. A smaller hardware I/O buffer may reduce output latency but can increase power/underrun sensitivity; it is not a model-generation optimization.

## 13. Recommendation P1: dynamic cache and service retention

Current device classes are effective, but physical RAM is a static proxy. The project already measures process headroom and pressure.

### Dynamic policy inputs

- `os_proc_available_memory` / current process headroom;
- kernel pressure;
- model family/variant;
- warm cache hit history;
- app active/background state;
- recent mode-switch probability;
- time since last generation;
- prior allocation retry;
- thermal state.

### Example policy

```
normal + likely reuse:
  cache 256–384 MiB
  retain shared decoder
  90–120 s retirement

normal + low reuse:
  cache 192–256 MiB
  30–45 s retirement

warning:
  stop proactive warm
  cache 128–192 MiB
  clear after generation
  15–30 s retirement

critical:
  cancel/terminal barrier
  full unload
  immediate retirement

```

### Required experiment

Sweep 128/192/256/320/384 MiB on the floor Mac and record:

- cold/warm TTFC;
- token-loop RTF;
- recompilation/cache misses if observable;
- active/cache/peak memory;
- pressure/trims;
- system compressed memory;
- model-switch time.

Do not assume the smallest cache is best. A cache that is too small can increase kernel and allocation churn.

## 14. Recommendation P1: profile the remaining causal decoder gap

Historical Instruments work estimated roughly 13% of generation wall time as inter-frame decoder/chunk plumbing, with decoder work already partially overlapped.

Reprofile current main because fused RoPE changed the relative bottleneck.

### Questions

- Is causal decoder GPU work still serialized behind token compute?
- Does `asyncEval` only overlap CPU graph construction or actual GPU work?
- How much time is sample materialization versus ConvNet execution?
- Are decoder invocations too small for efficient GPU utilization?
- Does larger post-first chunking reduce total decoder wall time?
- Is PCM conversion/WAV writing ever on the token critical path?

### Separate-stream experiment

MLX supports multiple streams and automatically inserts dependencies when arrays cross streams. A dedicated decoder stream might allow useful overlap between:

```
GPU: decode completed codec chunk
CPU: build next talker/CP graph
GPU: execute next token frame

```

It may also increase memory and contention. Promote only when a Metal trace proves overlap and the M2 floor machine improves.

## 15. Recommendation P2: isolated MLX 0.31.x evaluation

Current source pins:

```
mlx-swift    0.30.6
mlx-swift-lm 2.30.6

```

Current MLX Swift releases are newer. The newer line includes framework and race fixes, but there is no evidence that it automatically speeds this M2 Qwen path. MLX's quantization API also changed.

### Branch-only protocol

1. bump every pin in lockstep;
2. regenerate the project;
3. repair API changes without refactoring behavior;
4. run deterministic Qwen runtime tests;
5. run fixed-seed output/QC/ASR/prosody;
6. rerun the M2 canonical matrix;
7. rerun Instruments;
8. keep only with a clear performance/stability gain and no unexplained drift.

### Compile retest

MLX documentation notes that compilation can fuse common work and reduce graph size, runtime and memory. The current 0.30.6 whole-quantized-forward experiment regressed because model state was passed as function input and marshalled every call. A future retest is justified only if:

- the newer API can capture stable module state without per-call transfer;
- the compiled region is shape-stable;
- first-call compilation is prewarmed;
- numerical and output evidence remain valid.

## 16. Recommendation P2: custom Code Predictor operation/kernel

### Why this is the plausible remaining engine target

Current trace evidence shows:

- main GPU flush remains the largest block;
- Code Predictor graph construction is a substantial CPU/launch-bound component;
- GPU utilization is well below saturation;
- 15 residual steps are executed for every semantic frame;
- fused RoPE already proved that reducing tiny graph operations can create a large end-to-end gain.

### Candidate scopes

1. **small:** fuse codec embedding assembly and residual head sampling helpers;
2. **medium:** custom operation for one Code Predictor decoder layer;
3. **large:** one stateful Code Predictor step that captures quantized weights and cache state.

MLX supports custom CPU/GPU extensions and custom Metal kernels. Every custom kernel creates/JIT-compiles a Metal library, so it must be prewarmed and system-cached. A custom primitive also creates a long-term maintenance burden across MLX releases.

### Gate

Do not start with the full 15-step loop. Prove one layer:

- exact numerical tolerance versus current path;
- graph-build reduction;
- kernel launch reduction;
- M2 end-to-end RTF;
- 4-bit and 8-bit correctness;
- memory and cold compile cost.

A 5–15% end-to-end gain is plausible if the remaining build/launch overhead can be removed, but that estimate is uncertain.

## 17. Long-term research: multi-token and speculative speech decoding

The semantic codec loop remains autoregressive across time. No Swift micro-optimization can remove that dependency.

Research systems demonstrate larger gains by changing the model:

- multi-token prediction plus speculative decoding for codec speech synthesis reports roughly 4–5× lower token prediction time with small quality trade-offs;
- VITA-Audio reports 3–5× acceleration with multiple cross-modal token prediction;
- SoundStorm parallelizes residual acoustic token generation and reports orders-of-magnitude acoustic-stage speedups;
- VALL-E R reduces inference time through alignment and codec-merging changes.

These are not drop-in patches. They require new heads, training/distillation, verification logic or a different acoustic generator.

### Vocello-relevant directions

#### Multi-token semantic heads

Train `k` future semantic codec heads from the current talker hidden state. Verify accepted prefixes against the main head.

#### Draft-and-verify

Use a smaller draft model/head to propose semantic tokens and the 1.7B model to verify. Holding a separate 0.6B model next to 1.7B may be inappropriate on 8 GB; an attached draft head is more realistic.

#### Parallel residual codebooks

Replace the 15 sequential residual predictions with a trained parallel or masked acoustic predictor. This changes checkpoint architecture and quality behavior.

### Entry condition

Do not begin until the low-risk preview/chunk/component work is complete and the remaining model compute is still strategically important. This is a new model program with its own provenance and release identity.

## 18. Optional product-level lever: 0.6B modes

Official Qwen releases include 0.6B CustomVoice and Base models, but not VoiceDesign. An optional “Compact” tier could offer:

- lower memory;
- faster cold load;
- potentially lower TTFC/RTF;
- smaller downloads.

It is not a transparent optimization:

- mode availability becomes asymmetric;
- quality and speaker/prosody behavior differ;
- a second artifact matrix increases testing and support;
- the project previously chose a 1.7B-only product.

Evaluate only as a distinct product tier, never as a silent fallback from 1.7B.

## 19. Low-priority or explicitly rejected work

| Idea | Why it should not lead the roadmap |
| --- | --- |
| Zero-copy preview PCM | Current 0.6 s packet is ~28.8 kB and preview ON/OFF had no measurable cost |
| Smaller lossless KV window | KV is tens of MiB; a lossless window saves essentially nothing |
| Lossy KV window | Drops context and violates output transparency |
| 8-bit KV | ~271 MB saving cost ~8.6% RTF in Clone long |
| Hard `Memory.memoryLimit` | Produced spurious OOM behavior |
| Whole quantized graph `compile()` on 0.30.6 | Regressed warm RTF by ~5% |
| More frequent `eval()` | MLX has fixed evaluation overhead; current one-per-frame boundary is intentional |
| Fewer Code Predictor passes without retraining | Changes the model's 16-codebook output contract |
| Parallel candidates/processes on M2 | Compete for unified memory/Metal and violate single-owner policy |
| Output-side silence suppression | Risks deleting natural prosody and hides root causes |
| Increase all first chunks | Improves throughput at the expense of first feedback |
| Keep every model warm | Defeats the 8 GB memory architecture |
| Upgrade MLX directly on main | Substrate changes require a full evidence branch |

## 20. Detailed experiment plan

### Experiment A — adaptive preview admission

**Corpus:** current 29-take Mac matrix plus long Clone stress.
 **Compare:** current, RTF prior, observed EWMA.
 **Metrics:**

```
submit_to_first_chunk
first_chunk_to_frontend
frontend_to_buffer_ready
buffer_ready_to_engine_start
engine_start_to_first_render
submit_to_first_render
underruns
minimum_queued_audio
final_completion

```

**Promotion:** at least 25% p50 first-render reduction on Custom/Design, zero canonical underruns, no generation/output change.

### Experiment B — chunk schedule

**Grid:**

```
first: 4,5,6,7 frames
later: 7,10,14,18 frames
modes: Custom, Design, Clone
lengths: short, medium, long

```

**Promotion:** lower TTFC and/or ≥2% RTF without QC/ASR/prosody or underrun regression.

### Experiment C — shared component pool

**Measure:**

- installed bytes;
- download wire bytes;
- cold model load;
- model-family switch time;
- peak physical/GPU memory;
- decoder bucket warm time;
- full unload/retirement behavior.

**Promotion:** exact integrity, no peak increase, material switch/storage improvement.

### Experiment D — cache and retention

Run repeated interactive sequences:

```
custom → custom
custom → design → custom
custom → clone → custom
idle 15/30/45/90/120 s → generate
warning pressure → generate

```

Record user-visible first audio, memory headroom and process retirement.

### Experiment E — decoder stream

Use `xctrace`/Metal capture with exact signposts:

```
Talker Forward
Code Predictor Loop
Step Eval Flush
Audio Decoder
Audio Chunk Eval
PCM conversion/write

```

A separate stream is accepted only if trace-level overlap explains the measured gain.

### Experiment F — MLX substrate

Same binary/product source except package substrate. No simultaneous refactor. Compare exact fixed-seed outputs and current hardware evidence.

### Experiment G — custom CP primitive

Start with one layer and synthetic deterministic tensors before live speech. Keep the current implementation as a selectable control until complete parity.

## 21. Recommended roadmap

### 0–2 weeks — perceived latency and measurement

1. Add first-render timestamp and full preview latency decomposition.
2. Implement adaptive buffer policy behind a runtime experiment gate.
3. Add `AVAudioEngine.prepare()` / player preparation A/B.
4. Decouple chunk schedule from token-budget profiles.
5. Run first/later chunk matrix.
6. Fix any known XPC event-admission correctness issue before increasing preview aggressiveness.

### 2–6 weeks — shared components and dynamic policy

1. Build catalog component-digest report.
2. Design shared tokenizer/decoder installation manifest.
3. Implement model-loader component roots.
4. Benchmark family switches.
5. Add dynamic cache/retirement experiment.
6. Re-run floor-Mac memory and first-audio acceptance.

### 4–10 weeks — decoder and framework experiments

1. Reprofile current decoder/inter-frame gap.
2. Test larger later chunks.
3. Test dedicated decoder stream.
4. Run isolated MLX 0.31.x branch.
5. Decide whether a custom CP primitive is justified.

### 2–6 months — research

1. prototype one Code Predictor custom operation;
2. evaluate optional 0.6B product tier;
3. investigate multi-token semantic heads/speculative verification;
4. investigate trained parallel residual prediction;
5. create separate checkpoint and artifact governance for any model change.

## 22. Recommended metrics and dashboards

### User-visible latency

```
submit_to_engine_accept
accept_to_model_ready
model_ready_to_first_semantic_token
first_token_to_first_codec_chunk
first_chunk_to_frontend
frontend_to_buffer_ready
buffer_ready_to_engine_start
engine_start_to_first_render
submit_to_first_render
submit_to_final_completion

```

### Throughput

```
audio_seconds_per_generation_second
semantic_frames_per_second
mean/p95 semantic_frame_ms
code_predictor_ms_per_frame
decoder_ms_per_audio_second
decoder_calls
codec_frames_per_decoder_call

```

### Memory

```
app_phys_footprint
engine_phys_footprint
combined_phys_footprint
MLX active/cache/peak
available process memory
compressed memory
shared component resident bytes
post_generation_reclaimed_bytes
post_retirement_RSS

```

### Preview health

```
queued_audio_seconds_min/p50/p95
chunk_gap_ms_p50/p95/max
underrun_count
pause_resume_count
dropped_audio_chunks
first_render_success
preview_final_handoff_gap

```

### Model load and switching

```
talker_load_ms
text_tokenizer_load_ms
speech_decoder_load_ms
speaker_encoder_load_ms
decoder_bucket_prewarm_ms
shared_component_hit
family_switch_ms

```

All metrics must be keyed by exact source, model/artifact digest, mode, variant, language, warm state, device, chunk policy, buffer policy and MLX substrate.

## 23. Promotion gates

A performance change is accepted only when:

1. exact source and artifact identities are recorded;
2. fixed-seed output evidence passes;
3. audio QC passes;
4. language/ASR gates pass where applicable;
5. clone identity/prosody gates pass where applicable;
6. no terminal/cancellation regression occurs;
7. no new memory pressure or allocation retry appears;
8. preview chunk continuity is complete;
9. p50 and p95—not one best run—meet the declared improvement;
10. the M2 8 GB canonical machine improves or remains within a predeclared neutral range;
11. iPhone-specific code is requalified when touched;
12. negative results are documented and the experiment gate defaults off.

### Suggested thresholds

| Change class | Required performance result |
| --- | --- |
| Preview/UI-only | ≥15% first-render improvement, zero underruns |
| Chunk schedule | ≥2% RTF or ≥100 ms TTFC improvement |
| Runtime micro-optimization | ≥3% RTF with no quality/memory loss |
| Framework upgrade | ≥3% broad gain or material stability fix |
| Custom kernel | ≥5% end-to-end gain after cold/warm cost |
| Model architecture | Material gain across quality, speed and memory; separate release identity |

## 24. External research synthesis

### Qwen3-TTS

The official Qwen3-TTS report describes a dual-track streaming LM and a 12.5 Hz, 16-codebook tokenizer with a lightweight causal decoder. It reports first-packet latency as low as 97 ms in its reference system. That demonstrates architectural headroom, not an expected M2 Swift result: hardware, precision, serving stack and workload differ.

### MLX

MLX's lazy evaluation is central to both the gains and the historical memory failure. Larger graphs improve fusion but increase graph-build and retained-state cost; too-frequent evaluation adds fixed overhead. Unified memory removes device copies but makes every retained allocation system-visible.

MLX compilation can fuse graphs and reduce runtime/memory, but the first call compiles and complex module state has edge cases. Vocello's matched 0.30.6 experiment is more authoritative for the current stack than generic compile guidance.

MLX streams can overlap independent operations and automatically track dependencies. A decoder-stream experiment is therefore technically legitimate, but only a current Metal trace can establish whether M2 executes useful overlap.

Custom extensions/Metal kernels offer a route around repeated graph construction. They are a maintenance and cold-JIT trade, not a free optimization.

### Speech-generation research

Multi-token/speculative speech work validates the idea that the sequential semantic-token loop can be accelerated by model changes. SoundStorm validates parallel residual/acoustic prediction. Neither can be grafted onto the existing checkpoint without training and a new quality/provenance program.

## 25. Quantitative memory model

### 25.1 Why raw audio was not the problem

For 24 kHz mono Int16 output:

```
bytes per audio second = 24,000 samples × 2 bytes = 48,000 bytes
76 seconds             = 3,648,000 bytes ≈ 3.48 MiB

```

Even if the product held two PCM copies and one WAV file buffer, raw final audio would remain in the low tens of MiB. The measured difference between non-streaming and streaming was roughly 4.6 GB of physical footprint. Therefore, more than 99% of that difference cannot be explained by the final waveform.

The retained state included:

- hundreds of per-frame `MLXArray` objects;
- 16-codebook tensors and their graph ancestry;
- token and codec embedding operations;
- talker and Code Predictor lazy graphs;
- full-sequence stacking;
- full causal-decoder activations;
- allocator/cache state held until final evaluation;
- the final waveform tensor before conversion.

This is why optimizing the final `Data` or WAV copy could never have delivered the observed result.

### 25.2 Bounded streaming state

At the current floor-tier schedule:

```
semantic frame rate: 12.5 Hz
first chunk:         7 frames
audio represented:  7 / 12.5 = 0.56 s
codebooks:           16

```

The raw integer identity of one chunk is tiny. The important bound is that graph and decoder state are permitted to terminate at the chunk boundary instead of growing with utterance duration.

For Design and Clone, later chunks currently use 14 frames, approximately 1.12 seconds. Custom baseline remains at seven. The streaming working set therefore scales mainly with:

```
model weights
+ active KV/cache
+ one decoder chunk
+ bounded decoder state
+ bounded MLX cache
+ bounded preview/event queue

```

rather than with total audio length.

### 25.3 Component duplication

One speech-tokenizer file is 682,293,092 bytes. The exact same digest appears in all six production artifacts.

```
three packages:
  current copies = 3
  required copies = 1
  redundant = 2 × 682,293,092
            = 1,364,586,184 bytes
            ≈ 1.27 GiB

six packages:
  current copies = 6
  required copies = 1
  redundant = 5 × 682,293,092
            = 3,411,465,460 bytes
            ≈ 3.18 GiB

```

Text tokenizer files add a smaller but still unnecessary duplicate set. A shared component design reduces:

- download payload;
- installation time;
- disk footprint;
- integrity verification work;
- family-switch component loading;
- duplicate prepared-cache entries.

The disk figure is certain because it comes from exact catalog identities. The load-time benefit must be measured because operating-system file caching and current component-cache behavior can hide part of the I/O.

### 25.4 Cache policy is a Pareto frontier

MLX cache memory is not simply waste. It may contain reusable allocations or compiled kernel state that improves subsequent execution. The correct objective is not minimum cache bytes; it is:

```
minimize:
  first-audio latency
  generation wall time
  memory pressure probability
  model-switch latency
  service energy

subject to:
  no allocation failure
  no quality drift
  no unload/rewarm churn
  floor-device headroom

```

A 128 MiB cache may reclaim more memory but increase allocation and kernel churn. A 384 MiB cache may improve warm latency but leave insufficient system headroom. The optimum depends on current model, app state and pressure.

### 25.5 Process retirement is qualitatively different from cache clearing

There are three increasingly strong relief levels:

1. **MLX cache clear** — releases reusable framework cache, not live model state.
2. **Model unload** — drops product references and model arrays, but allocators/frameworks may retain pages.
3. **Process retirement** — the operating system destroys the engine process and guarantees complete reclamation.

This hierarchy explains why XPC remains valuable even after excellent in-process memory discipline.

## 26. Quantitative latency model

### 26.1 Definitions

```
Tload    model load and prepared-component readiness
Tprefill prompt/conditioning preparation
Tframe   time per semantic codec frame
Nfirst   codec frames in first chunk
Tdecode  first causal decoder chunk
Twire    engine → frontend transport
Tbuffer  additional wait for playback admission
Taudio   audio-engine start to first rendered sample
Tfinal   complete utterance generation/finalization

```

Approximate first audible time:

```
time-to-first-audible = Tload + Tprefill + Nfirst × Tframe + Tdecode + Twire + Tbuffer + Taudio

```

Most engine micro-optimizations reduce `Tframe`. The current largest immediately avoidable term for faster-than-realtime modes is often `Tbuffer`.

### 26.2 Throughput-safe buffer derivation

Let:

```
A = estimated final audio duration
r = conservative generation rate in audio seconds per wall second
B = queued audio at playback start
J = jitter and audio-engine safety margin

```

During playback, queued audio changes at rate `r − 1`. If `r < 1`, generation finishes after producing the remaining `A − B` seconds. Requiring the queue not to reach zero yields:

```
B ≥ A × (1 − r)

```

Adding uncertainty:

```
Bsafe = J + max(0, A × (1 − rlower))

```

where `rlower` is a conservative lower confidence bound rather than a median.

Examples for a 12-second utterance with one second of jitter margin:

| Conservative speed `r` | Required buffer |
| --- | --- |
| 1.20 | 1.0 s |
| 1.05 | 1.0 s |
| 1.00 | 1.0 s |
| 0.90 | 2.2 s |
| 0.75 | 4.0 s |
| 0.60 | 5.8 s |

The current 35% rule corresponds approximately to protecting a rate near `r = 0.65` before adding other safety. That was sensible when many cells were slower than realtime. It is unnecessarily expensive for a stable `r ≥ 1` cell.

### 26.3 Confidence model

Before the first chunk:

```
rlower = historical p10 or lower confidence bound

```

After chunk one:

```
observed rate = generated audio / elapsed generation time

```

After chunk two and later:

```
EWMA rate
p95 inter-arrival jitter
estimated remaining duration

```

Blend conservatively:

```
rlower = min(
  historical lower bound adjusted for cold/warm state,
  observed EWMA − uncertainty margin
)

```

Do not let one unusually fast first chunk eliminate the jitter margin.

### 26.4 First-chunk trade

Reducing seven frames to four removes three semantic iterations before first decode:

```
time saved ≈ 3 × current semantic-frame wall time

```

If a frame costs 45–60 ms after current optimization, the theoretical engine saving is roughly 135–180 ms, plus a smaller decoder/transport effect. Cold load and prefill are unchanged.

> **Editor's note (2026-07-22).** The 45–60 ms/frame band is not reproducible from any repository record. Re-derived from canonical RTF (frame = 80 ms audio ÷ RTF): **≈42–47 ms/frame on iPhone 17 Pro** (RTF 1.70–1.91) and **≈82–92 ms/frame on the 8 GB Mac mini post-cutover** (RTF 0.87–0.98). Use the per-platform values.


A smaller packet also contains less playable audio. That is acceptable when the next packet arrives quickly and the playback policy uses a rate model. It is dangerous when generation is slower than playback.

### 26.5 Later-chunk trade

Larger later chunks reduce:

- decoder calls;
- decoder state transitions;
- `asyncEval` scheduling;
- PCM conversion calls;
- WAV append calls;
- event/XPC messages;
- AVAudioPCMBuffer schedules.

They increase:

- burst size;
- queued memory per chunk;
- interval between opportunities to recover from a slow chunk;
- latency of the final partial chunk if flushing is poorly implemented.

The first and later sizes should therefore be independent.

## 27. Detailed inventory of existing optimizations

### 27.1 Prepared-load specialization

The prepared loader can independently decide whether to:

- trust an already verified prepared checkpoint;
- load the speaker encoder;
- load the speech-tokenizer encoder;
- evaluate the speech tokenizer at load time;
- reuse cached tokenizer components.

This avoids loading clone-only components for Custom or VoiceDesign.

### 27.2 Component caches

The package has small LRU caches for text and speech tokenizers. On macOS the limit is three; on iOS it is one. Cached speech tokenizers reset streaming decoder state before reuse.

The weakness is keying by prepared-model directory rather than immutable component digest. Identical components from three model families are treated as distinct identities.

### 27.3 Qwen hot-loop structure

The production loop already includes:

- fused Q/K normalization and scaled dot-product attention;
- fused RoPE in the Code Predictor;
- compiled shapeless SwiGLU;
- cached causal masks;
- sampler scratch arrays;
- one semantic sample followed by 15 residual samples;
- one controlled evaluation boundary per semantic frame;
- explicit EOS suppression until minimum generated frames;
- reusable Code Predictor cache;
- mode-specific token, chunk and timing diagnostics.

This is a highly optimized model port, not a straightforward line-by-line translation.

### 27.4 Decoder pipeline

The decoder:

- maintains causal streaming state;
- accepts transposed codec frames for one chunk;
- schedules materialization asynchronously;
- returns one audio tensor;
- resets state at generation boundaries;
- exposes substage timings when telemetry is active.

Current profiling should confirm whether the decoder remains sufficiently overlapped after the CP speedups.

### 27.5 Product output pipeline

The session:

- runs outside the main actor;
- converts one audio chunk at a time;
- limits/sanitizes samples;
- reuses a scratch buffer;
- appends to an incremental final file;
- emits exact sequence and frame metadata;
- performs final persisted-WAV QC;
- publishes atomically;
- cleans partial output on failure/cancellation.

### 27.6 Preview/UI pipeline

The frontend:

- avoids reading preview audio through the coalesced snapshot path;
- drains the complete ordered stream;
- validates continuity before scheduling;
- configures a reusable audio graph;
- tracks queued duration from playback callbacks;
- does not publish high-frequency counters into SwiftUI;
- pauses and increases buffer after underrun;
- hands off to the final file without jumping playback position.

### 27.7 Memory lifecycle

The system combines:

- per-tier cache limit;
- per-chunk cache clear on constrained devices;
- periodic token-loop clear;
- post-generation clear;
- post-batch trim;
- pressure-aware proactive-warm admission;
- one active generation;
- terminal-before-unload;
- idle unload;
- process retirement.

The gain is the composition. Removing one layer because another exists would weaken the system.

## 28. Research opportunity ranking

### Tier A — high confidence, no model change

| Opportunity | Expected value | Main risk |
| --- | --- | --- |
| Adaptive preview admission | Largest immediate perceived-latency gain | Underruns if lower-bound rate is wrong |
| Shared tokenizer/decoder components | Large storage/network and switch-load gain | Installer/loader migration complexity |
| First/later chunk policy | TTFC plus modest RTF | Onset quality and burstiness |
| AVAudioEngine preparation | Small first-audible-latency gain | Route/session side effects |
| Dynamic cache/retirement | Better warm latency/headroom trade | Policy complexity |
| Exact first-render telemetry | Makes all later decisions reliable | Schema work only |

### Tier B — framework/runtime experiments

| Opportunity | Expected value | Main risk |
| --- | --- | --- |
| Larger Custom later chunks | Fewer decoder/event calls | Preview jitter |
| Dedicated decoder MLX stream | Possible overlap | Memory/serialization |
| MLX 0.31.x branch | Unknown performance, stability fixes | API/output drift |
| Component-level decoder retention | Faster family switches | Retained memory under pressure |
| Custom CP primitive | Material RTF potential | Large maintenance burden |

### Tier C — product/model research

| Opportunity | Expected value | Main risk |
| --- | --- | --- |
| Optional 0.6B tier | Large load/RTF reduction | Quality and mode asymmetry |
| Multi-token semantic heads | Potential multi-fold speed | Requires training |
| Draft-and-verify | Potential large speed | Extra model/head and memory |
| Parallel residual predictor | Removes 15-pass chain | New checkpoint architecture |
| Codec merging/downsampling | Fewer AR steps | Quality and compatibility |
| Distillation | Smaller/faster runtime | Training/data/evaluation program |

### Recommended capital allocation

Approximately:

```
60% low-risk product/runtime work
25% profiling and custom-runtime prototypes
15% model research

```

until the preview and shared-component gains are exhausted.

## 29. Performance risk register and definition of done

### Risk register

| Risk | Trigger | Mitigation |
| --- | --- | --- |
| Preview underrun | Buffer starts too early | Conservative lower bound, jitter margin, fallback |
| Quality regression | Smaller chunks or new runtime | Fixed-seed QC/ASR/prosody |
| Memory regression | Decoder overlap or retention | Combined app+engine peak gate |
| Cold-start regression | New kernel/compile | Separate cold and warm metrics |
| Artifact ambiguity | Shared components | Exact digest references and atomic migration |
| Stale decoder state | Shared instance | Reset and generation-ownership tests |
| MLX drift | Framework upgrade | Quarantined branch and full evidence |
| Kernel maintenance | Custom Metal op | Small proof, parity tests, fallback |
| Policy oscillation | Dynamic cache/retirement | Hysteresis and state-machine tests |
| Hidden battery cost | Early audio engine start | Energy/idle instrumentation |
| Evidence overfitting | One prompt/device | Full matrix and p50/p95 |
| Concurrency regression | More streams/overlap | Single-owner and cancellation stress |

### Definition of done for the next performance program

1. First-render latency is a first-class canonical metric.
2. Every latency stage has one clock domain or a validated correlation.
3. Custom/Design faster-than-realtime cells use adaptive rather than universal 35% buffering.
4. Canonical preview has zero underruns and zero audio drops.
5. First/later chunk sizes are independent policies.
6. Three Speed packages share one verified speech tokenizer on disk.
7. The runtime never holds two identical speech decoder instances.
8. Model family switching has explicit cold/warm evidence.
9. Cache and retirement decisions use pressure/headroom plus device class.
10. Current decoder overlap is proven by Metal trace.
11. Any MLX upgrade is source/model/evidence bound.
12. Any custom kernel has a maintained fallback.
13. All accepted gains pass quality and accuracy gates.
14. Negative experiments remain documented.
15. The M2 8 GB machine remains the performance floor.

## 30. Source evidence index

### Current repository

- [Current README and performance statement](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/README.md)
- [Historical optimization ledger](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/benchmarks/OPTIMIZATION.md)
- [Current benchmark history](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/benchmarks/HISTORY.md)
- [Current canonical Mac record](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/benchmarks/runs/ui-generation/macos-xcui-benchmark-20260716-181853-b4c2e299.json)
- [Current project health](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/docs/project-health.md)
- [Current development checkpoint](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/docs/development-progress.md)
- [Native memory policy](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/NativeMemoryPolicyResolver.swift)
- [Native streaming session](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/NativeStreamingSynthesisSession.swift)
- [Audio player/live preview](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/SharedSupport/ViewModels/AudioPlayerViewModel.swift)
- [Mac warmup coordinator](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/Services/MacGenerationWarmupCoordinator.swift)
- [Native engine runtime](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/QwenVoiceCore/NativeEngineRuntime.swift)
- [Qwen generation implementation](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift)
- [Code Predictor implementation](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSCodePredictor.swift)
- [Production model catalog](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Sources/Resources/qwenvoice_production_model_catalog.json)
- [Owned package pins](https://github.com/PowerBeef/Vocello/blob/079757abc3524ad5c0308bb1d914a9ff151c0de6/Packages/VocelloQwen3Core/Package.swift)

### Primary external sources

- [Qwen3-TTS official repository](https://github.com/QwenLM/Qwen3-TTS)
- [Qwen3-TTS technical report](https://arxiv.org/abs/2601.15621)
- [MLX lazy evaluation](https://ml-explore.github.io/mlx/build/html/usage/lazy_evaluation.html)
- [MLX unified memory](https://ml-explore.github.io/mlx/build/html/usage/unified_memory.html)
- [MLX compilation](https://ml-explore.github.io/mlx/build/html/usage/compile.html)
- [MLX streams](https://ml-explore.github.io/mlx/build/html/usage/using_streams.html)
- [MLX custom Metal kernels](https://ml-explore.github.io/mlx/build/html/dev/custom_metal_kernels.html)
- [MLX custom extensions](https://ml-explore.github.io/mlx/build/html/dev/extensions.html)
- [MLX Swift releases](https://github.com/ml-explore/mlx-swift/releases)
- [Apple AVAudioEngine.prepare](https://developer.apple.com/documentation/avfaudio/avaudioengine/prepare%28%29)
- [Apple AVAudioPlayerNode](https://developer.apple.com/documentation/avfaudio/avaudioplayernode)
- [Accelerating Codec-based Speech Synthesis with Multi-Token Prediction and Speculative Decoding](https://arxiv.org/abs/2410.13839)
- [VITA-Audio](https://arxiv.org/abs/2505.03739)
- [SoundStorm](https://www.research.google/blog/soundstorm-efficient-parallel-audio-generation/)
- [VALL-E R](https://arxiv.org/abs/2406.07855)

## 31. Final recommendation

Vocello should preserve the current streaming/XPC architecture. It has already crossed the hard threshold: 1.7B 4-bit generation fits, memory is approximately flat with utterance length and Custom/Design reach realtime on the 8 GB M2 floor machine.

The next program should be:

```
first:
  adaptive preview buffer
  first/later chunk schedule
  exact first-render instrumentation
  shared tokenizer/decoder components

then:
  dynamic cache/retirement
  decoder overlap profiling
  isolated MLX upgrade

only afterward:
  custom Code Predictor primitive
  0.6B product tier
  multi-token/speculative model research

```

The largest immediate user benefit is likely not another 5% model-speed gain. It is allowing the user to hear audio that Vocello has already produced, safely and earlier. The largest structural storage/load benefit is eliminating 1.27 GiB of duplicated codec files from the three Speed packages and reusing one verified decoder across model families. The largest remaining engine opportunity is the repeated 15-pass Code Predictor path—but meaningful gains there require either a custom low-level operation or a new model architecture.

No further optimization should sacrifice the principles that made the current system successful: exact evidence, bounded memory, one MLX mutator, official-quality sampling, typed terminal behavior and fail-closed output publication.   Prepared from exact-ref QwenVoice source, tracked benchmark evidence and primary external documentation/research. Hypothetical gains are labeled and require the report's promotion gates.
