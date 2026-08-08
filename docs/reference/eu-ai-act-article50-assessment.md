---
status: active
owner: release-qa
summary: Point-in-time research assessment (2026-08-06) of the EU AI Act's Article 50 synthetic-content marking obligations — what the law requires, whether and how it applies to Vocello, the current gap, and maintainer decision points. Not legal advice.
sourceOfTruth:
  - Sources/QwenVoiceCore/GenerationOutputAdapter.swift
---
# EU AI Act Article 50 and Vocello — research assessment (2026-08-06)

> **What this is.** A researched, point-in-time assessment of the EU's synthetic-content
> marking rules and their bearing on Vocello, written to inform maintainer decisions.
> **It is not legal advice**; the applicability questions below include genuine legal gray
> zones that only a qualified adviser (or, eventually, regulators and courts) can settle.
> Sources are linked at the end; all were retrieved 2026-08-06.

## 1. The law, precisely

The rule the news is about is **Article 50 of Regulation (EU) 2024/1689 (the "AI Act")** —
the transparency obligations — which **became applicable on 2 August 2026**. It was adopted
in 2024; what "just happened" is that this obligation tier entered into application.

**Article 50(2), the marking duty (providers):**

> "Providers of AI systems, including general-purpose AI systems, generating synthetic
> audio, image, video or text content, shall ensure that the outputs of the AI system are
> marked in a machine-readable format and detectable as artificially generated or
> manipulated."

Technical solutions must be "effective, interoperable, robust and reliable as far as this
is technically feasible", accounting for content-type specificities, implementation costs,
and the generally acknowledged state of the art. The Commission's 2026 draft Guidelines
make two points that matter for a small project: **no single marking technique currently
satisfies all four statutory properties** (multi-layered approaches are expected), and
**technical feasibility is an objective notion** — it does not scale down with an
individual provider's resources. There is no SME safe harbor on the obligation itself
(only on penalty proportionality).

**Article 50(4), the deepfake disclosure duty (deployers/users):** anyone *using* an AI
system to generate or manipulate audio/image/video that appreciably resembles real
persons, places or events and would falsely appear authentic — a definition that squarely
covers cloned voices of real people — must **disclose the artificial origin
human-perceptibly, at first exposure**. Intent to deceive is irrelevant. The duty is
attenuated (not removed) for evidently artistic, creative or satirical works, and does not
apply to purely personal, non-professional use (Article 2(10)).

**Key dates and status, verified against 2026 developments:**

| Fact | Status |
| --- | --- |
| Article 50 applicability | **2 August 2026** — confirmed unchanged by the 2026 "AI Act Omnibus" (which extended *high-risk* deadlines to Dec 2027/Aug 2028 but left Article 50 alone) |
| Grace period | Generative systems **placed on the EU market before 2026-08-02** may defer the 50(2) marking duty to **2 December 2026** |
| Retroactivity | Content generated before 2026-08-02 need not be labelled |
| Code of Practice on Transparency of AI-generated Content | Final version published **10 June 2026**, assessed adequate by the Commission and AI Board; ~190 signatories by end-July 2026. Voluntary; signatories get supervisory focus limited to code adherence; non-signatories must demonstrate compliance by "alternative adequate means" and can expect more information requests |
| Enforcement | National market-surveillance authorities; fines up to **€15M or 3% of worldwide turnover**, with SME proportionality at the penalty (not obligation) level |

**Open source is not exempt.** Article 2(12) exempts free and open-source AI systems
"*unless* they are placed on the market or put into service as high-risk AI systems or as
an AI system **that falls under Article 5 or 50**". A generative TTS system falls under
Article 50 by definition, so the FOSS exemption does not shelter Vocello. What remains is
the antecedent question in §3.

## 2. What Vocello emits today (the gap)

Verified against the tree at this assessment's date:

- Both WAV writers emit a **bare 44-byte RIFF header plus PCM** — no `LIST/INFO`, `bext`,
  `iXML`, ID3, or any custom chunk (`Sources/QwenVoiceCore/GenerationOutputAdapter.swift`,
  non-streaming header builder and the streaming `IncrementalPCM16WAVFileWriter`).
- Share sheets, the optional iOS export folder, the macOS output directory, and the CLI
  all move the file **byte-identically**; filenames carry no generator marker.
- The only provenance (mode, model tier, voice, seed, timestamps) lives in the **local
  History database**, never in the file.
- The repo contains **no watermarking, C2PA, or content-credential code or plans**; the
  one prior mention of this space is a 2026-07-16 threat-model row naming "optional source
  note/export labeling" as a possible next control for voice misuse.

So if Article 50(2) applies, Vocello at this assessment's date satisfied none of it: outputs
were indistinguishable, by bytes, from any other 24 kHz mono PCM WAV.

> **Status update (CP-2, 2026-08).** The gap above is being closed in the tree: every
> published WAV now passes a publication-marking seam in `GenerationOutputAdapter`
> (`Sources/QwenVoiceCore/AudioPublicationMarking.swift`) that embeds an imperceptible
> AudioSeal watermark with a fixed Vocello payload (owned MLX port,
> `Packages/VocelloQwen3Core/Sources/MLXAudioMark/`, parity-proven against the PyTorch
> reference) and appends a machine-readable `LIST`/`INFO` provenance chunk — the layered
> approach §4 recommends. Both marks flip together and fail closed; the only off-switch is
> a registered debug knob under the `QWENVOICE_DEBUG` master gate. Weights ship through the
> model catalog as a required per-model file. This section's point-in-time findings are
> retained unedited as the motivating record.

## 3. Does it apply to Vocello? An honest analysis

**The provider question hinges on "placing on the market."** The AI Act's obligations
attach to a "provider" who "places on the market or puts into service" an AI system in the
EU — and placing on the market means making available "**in the course of a commercial
activity**, whether in return for payment or free of charge." That qualifier is where
Vocello's situation genuinely sits on a line:

*Against applicability:* Vocello is MIT-licensed, fully open source, free, with **zero
monetization surface** — no purchases, no subscriptions, no donations, no ads, no data
collection. A personal open-source project supplied outside any commercial activity is,
on the most natural reading, not "placed on the market" at all, and EU product-law
practice (the Blue Guide tradition the AI Act borrows from) treats genuinely
non-commercial supply as out of scope.

*For applicability:* Vocello is distributed as a **branded, polished product** through
managed channels — notarized DMGs on GitHub Releases, a **public TestFlight link** under
an Apple Developer Program membership, and a marketing website with a pricing section.
Both channels are worldwide by construction, so EU availability is real even though never
stated. Regulators reading "commercial activity" broadly (as a *professional context*
rather than profit-seeking) could find the supply in scope; a future **App Store listing
would strengthen that character considerably** (the repo's own submission runbook already
flags the analogous EU DSA trader-status question).

**Judgment (not legal advice):** today, as a free hobby OSS project, Vocello has a
plausible, good-faith argument that it is not "placed on the market" and that Article
50(2) therefore does not bind it. That argument thins with every step toward productized
distribution and effectively dissolves at App Store submission. Prudent engineering
posture is to **treat marking as applicable-soon**: the 50(2) requirements are
architecture-shaping (output-file format, share paths), cheap at their base layer, and
entirely aligned with Vocello's stated privacy-and-honesty ethos.

**The grace period is real but not to be leaned on.** Vocello 2.4.0 was on the market
before 2026-08-02, so *if* in scope, the marking duty defers to 2026-12-02. But releases
after 2026-08-02 arguably restart the clock under the substantial-modification doctrine,
and the deferral is four months regardless — it changes urgency, not direction.

**Vocello's users have their own duty that the app should surface.** Article 50(4) binds
*users* who publish deepfakes — which includes cloned real voices — to disclose the
artificial origin, unless the use is purely personal and non-professional. Vocello's
consent gate ("I own or have permission to clone the voices I use") addresses *rights*,
not *disclosure*; an EU user with permission to clone a voice still owes the audience a
disclosure when publishing. This is a product-honesty gap the app can close with copy
alone, independent of the provider question.

## 4. Options, from cheapest to heaviest

| # | Option | What it buys | Effort / notes |
| --- | --- | --- | --- |
| A | **WAV metadata provenance chunk** — write `LIST/INFO` (+ `iXML`) declaring "AI-generated · Vocello \<version\> · Qwen3-TTS", mode, and date into every output | The machine-readable baseline; the Code of Practice's metadata layer; also the threat-model row's "export labeling" | **Small.** Backend-owned change to the two WAV writers + tests; survives byte-copy share paths automatically; trivially strippable (which the layered model accepts for the base layer) |
| B | **C2PA Content Credentials manifest** on export | Industry-standard, verifiable provenance (the interoperability property); WAV supported in the current C2PA spec; open-source SDKs (c2pa-rs + bindings) | **Medium.** New dependency and signing-identity decisions; fits at the share/export boundary |
| C | **Imperceptible audio watermark** (AudioSeal-class) | The robustness layer — survives re-encoding and stripping | **Large.** AudioSeal is fully MIT (code *and* weights) with streaming support, but it is PyTorch at 16 kHz vs the engine's 24 kHz output; a Vocello integration needs an MLX/Swift port or a post-process stage plus a sample-rate fit spike; measurable RTF/memory cost on the 8 GB floor must be benchmarked |
| D | **Cloning-disclosure UX copy** — one sentence beside the existing consent gate noting that EU users publishing cloned real voices must disclose the artificial origin | Closes the user-side 50(4) gap; pure copy | **Small.** Consent-gate copy + website/README line; delivery-instruction contract untouched |
| E | **Code of Practice signature** | Legal certainty; supervisory goodwill | **Maintainer-only decision** — signing is a legal commitment by the provider, and it presumes accepting provider status; not appropriate before the posture decision |

The layered reading of 50(2) suggests A (+ eventually B) as the credible baseline for a
local-first app, with C as the robustness layer if/when the provider posture is accepted
or App Store distribution makes it unavoidable. D is worth doing regardless of the legal
posture — it is honest product design.

## 5. Recommendation and decision points

1. **Decide the posture** (maintainer): treat Vocello as an Article 50 provider now, at
   App Store submission, or only if circumstances change. The engineering recommendation
   is "applicable-soon": implement A and D on ordinary roadmap cadence, well before any
   App Store submission, and fold B/C into that submission's requirements.
2. **Option D is recommended unconditionally** — it aligns the app's cloning ethics with
   its users' actual legal duties in the EU.
3. **Revisit at App Store submission**: the submission runbook should gain an Article 50
   checklist row next to the existing EU DSA trader-status row.
4. **If professional/commercial distribution ever becomes the goal**, obtain actual legal
   advice and consider the Code of Practice signature question then.

This assessment and its options are registered on the roadmap as a maintainer-gated
compliance item; no technical work proceeds without that call.

> **Status update (CP-1 close, 2026-08-08).** The maintainer's posture call (a one-time
> purchase is planned, so Article 50(2) binds the paid offering with certainty; roadmap
> CP-1 records the adopted sequence) has been executed as far as it reaches today:
> **Option C** landed first via the CP-2 marking seam (§2 status update). **Option A** is
> now verified complete against this section's field set — the `LIST/INFO` chunk carries
> the AI-generated declaration, generator (`Vocello` + a `version=` field added in this
> close), engine, exact model ID, mode, ISO 8601 date, and the watermark payload
> reference. **Option D** landed as one disclosure sentence beside the consent gate on
> both platforms plus a README bullet and a website "AI disclosure" limitations entry
> (the site line states only the user duty: the shipping 2.4.0 release predates the
> marking seam). Recommendation 3 is done — the submission runbook carries the Article 50
> checklist row beside the DSA row. **Options B (C2PA) and E (Code of Practice) plus the
> real legal review remain gated on the paid launch**, recorded in roadmap CP-1's gate.

## Sources

- [Commission FAQ: Transparency obligations under Article 50 of the AI Act](https://digital-strategy.ec.europa.eu/en/faqs/transparency-obligations-under-article-50-ai-act)
- [Commission policy page: Code of Practice on Transparency of AI-generated Content](https://digital-strategy.ec.europa.eu/en/policies/code-practice-ai-generated-content)
- [Commission quick facts: Transparency rules for AI systems](https://digital-strategy.ec.europa.eu/en/factpages/quick-facts-transparency-rules-ai-systems)
- [AI Act text, Article 50](https://artificialintelligenceact.eu/article/50/) and [Article 2 (scope, FOSS exemption)](https://artificialintelligenceact.eu/article/2/)
- [Practical guide to Article 50 (artificialintelligenceact.eu)](https://artificialintelligenceact.eu/transparency-rules-article-50/)
- [Covington, "10 Takeaways: European Commission Draft Guidelines on AI Transparency" (May 2026)](https://www.globalpolicywatch.com/2026/05/10-takeaways-european-commission-draft-guidelines-on-ai-transparency-under-the-eu-ai-act/)
- [Latham & Watkins, "AI Act Update: EU Resolves to Change Rules and Extend Deadlines" (Omnibus)](https://www.lw.com/en/insights/ai-act-update-eu-resolves-to-change-rules-and-extend-deadlines)
- [TechTimes, "EU Finalizes AI Disclosure Rules as Watermarking Mandate Outpaces Technology" (July 2026)](https://www.techtimes.com/articles/321174/20260721/eu-finalizes-ai-disclosure-rules-watermarking-mandate-outpaces-technology.htm)
- [AudioSeal (Meta) — MIT-licensed audio watermarking, code and weights](https://github.com/facebookresearch/audioseal)
