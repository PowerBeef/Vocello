"""Audio-QC qualification engine (AQ-03, audit 2026-09-25 sections 3.3 and 5).

The engine measures what a detector can claim, from construction rather than
listening. Nothing here runs a model, reads a private file or writes tracked
evidence.

- `stats`: exact one-sided Clopper-Pearson bounds, the legacy Wilson bound,
  sample sizes, and false-alarm / miss rates at a declared operating point,
  counted per source family (the unit of independence).
- `resampling`: cluster bootstrap by source family and digest-based family
  merging.
- `correlation`: the correlated-failure audit between two judges (phi,
  conditional failure rates, and the joint failure bound per family).
- `thresholds`: pre-registered threshold derivation from clean clips only:
  plans committed as files and read back (A5), a split disjoint by family,
  speaker and script, the split-conformal quantile or fixed-sequence
  Learn-then-Test, and one confirmation per plan against every requirement of
  a policy operating point, recorded in an exclusive ledger file.
- `pcm`: canonical PCM16 digests and seeded randomness that is stable across
  NumPy releases.
- `fixtures`: procedural speech-like sources and abstention fixtures.
- `injectors`: the T1 PCM injector catalog, every family with a zero-magnitude
  sham and a severity sweep, every output bound to a golden digest.
- `composer`: the pure Stage 3 verdict composer.
- `policy`: the loader and validator of
  `config/audio-qc-qualification-policy.json`.

Operating points and sample sizes are the policy file's; this package only
computes them.
"""
