# iPhone 6 GB hardware-floor feasibility — staged evidence plan

- **Status:** pre-registered 2026-08-01 (maintainer-directed). The floor does **not**
  move on simulation evidence alone; this document stages the question so each step
  can kill it cheaply.
- **Motivation:** the f16 codec promotion (§R, −234 MB resident) plus adaptive
  residency staying **off** on small devices puts 6 GB iPhones (iPhone 14 Pro / 15 /
  15 Plus — among the most-owned devices in the wild) within plausible reach of the
  current engine. Current floor: iPhone 15 Pro (8 GB, A17 Pro), enforced by
  `IOSDeviceSupport.isSupportedHardware`.

## Step 1 — memory feasibility under clamp (next phone window; kill-cheap)

Run on the paired iPhone 17 Pro with the new `iphone14pro` memory profile
(`QVOICE_IOS_MEMORY_PROFILE=iphone14pro`, 3,600 MB entitled clamp — the conservative
bottom of the 6 GB class's community-measured ~3.6–4.0 GB band), f16 artifacts,
residency off:

```sh
scripts/ios_device.sh bench custom:speed:… --memory-profile iphone14pro --label i14p-floor-custom
scripts/ios_device.sh bench design:speed:… --memory-profile iphone14pro --label i14p-floor-design
scripts/ios_device.sh bench clone:speed:…  --memory-profile iphone14pro --label i14p-floor-clone --voice-id <fixture>
# plus one long-form project via the UI lane with the clamp exported, if the
# clamp knob is honored there; otherwise the three modes above are the verdict.
```

**Pre-registered verdicts (memory only):**
- **Feasible:** all clamped runs complete with no memory warning/exit, no
  `hardTrim`/`fullUnload`, and peak `phys_footprint` ≤ 3,300 MB (≥ 300 MB margin
  under the clamp) on every mode.
- **Infeasible:** any mode exceeds the clamp or trips hard relief → the floor
  question closes as a recorded do-NOT until the engine's peaks shrink again;
  record the failing mode and peak.

All clamped runs classify exploratory (forced-profile rule); they are evidence for
this decision, never canonical history.

### Step 1 result (2026-08-02) — FEASIBLE with ~1 GB margin

Clamped matrix on the paired iPhone 17 Pro (`iphone14pro` profile honored: headroom
started at 3,577 MB), fp32 artifacts (conservative — f16 subtracts another ~234 MB),
full 140-character spec text, runs `ios-engine-20260802-0104/0105/0106…`:

| mode | peak phys footprint | worst headroom | vs ≤3,300 MB bound |
| --- | --- | --- | --- |
| custom | 2,347 MB | 1,593 MB | pass, 953 MB under |
| design | 2,109 MB | 1,669 MB | pass, 1,191 MB under |
| clone | 2,372 MB | 1,374 MB | pass, 928 MB under |

QC pass on every take; warnings limited to the policy's ordinary
`memory.pressure.soft_trim` cadence; no memory warning, no hardTrim, no fullUnload.
**The memory dimension of the 6 GB floor is green.** The question advances to step 2
(real A16 compute/thermals) per plan. Operator note for reproduction: the
`ios_device.sh bench` positional argument is bare *text*, not a mode — always pass
the full `mode:variant:text` spec (a bare mode word generates that word as a
six-character prompt, which mandatory Fast QC rejects; three early runs failed this
way before diagnosis).

## Step 2 — real-silicon validation (requires hardware; only after step 1 passes)

The clamp cannot simulate A16 compute, thermals, or real-world ambient Jetsam
pressure. Options, cheapest first: a used iPhone 15; or a TestFlight build with the
hardware gate relaxed for a known 6 GB volunteer tester. Required evidence: the
standard bench matrix + a long-form project on the real device — RTF ≥ 1.0× realtime
warm on every Speed cell, thermal state ≤ serious throughout, QC clean, no memory
events. iOS floors also stay honest with the existing burn-in-safe rules.

## Step 3 — the floor decision (maintainer)

Only with steps 1–2 green: `IOSDeviceSupport.isSupportedHardware` widens, public
support copy updates (README, website, TestFlight description), and the release
notes carry the change. A floor expansion is one-way in practice; retracting later
is worse than never widening, which is why step 2 is not skippable.

## Related

- Adaptive speech-tokenizer residency shipped the same day and was qualified live
  on 2026-08-02: the flip build's default-state retained-memory run
  (`ios-memory-qualification-20260802-011251`) passed with engagement proven by
  load-event counts — one speech-tokenizer load across the Custom→Design→Clone
  switch sequence instead of three. (Methodology note: an earlier knob-based A/B
  on the prior build read a footprint delta as engagement; load events showed the
  knob never engaged there, and footprint deltas at this scale are run noise —
  count loads, not megabytes.) 6 GB devices stay non-resident under any outcome
  of this plan.
