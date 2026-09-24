# Origins and lineage

Vocello Qwen3 Core is repository-owned product source derived from
[`Blaizzy/mlx-audio-swift`](https://github.com/Blaizzy/mlx-audio-swift) release `v0.1.2`, commit
`fcbd04daa1bfebe881932f630af2ba6ce9af3274`. The immutable machine-readable import identity is in
[`LINEAGE.json`](LINEAGE.json). [`UPSTREAM_BASELINE.json`](UPSTREAM_BASELINE.json) contains only
non-null hashes from that immutable import. [`CURRENT_INVENTORY.json`](CURRENT_INVENTORY.json) is
the separately derived inventory of today's retained files and classifies each one as identical,
modified, or added relative to the import.

The source was specialized for Vocello's Qwen3-TTS product runtime. It retains the Qwen3 TTS
implementation and required Mimi codec primitives, while upstream model families and tools outside
that product boundary were removed. Subsequent repository work added owned loading, streaming,
memory, telemetry, cancellation, codec, and clone-artifact behavior.

Reviewing or selectively adopting a newer upstream commit does not change the historical import
identity. Upstream reviews are recorded separately in `LINEAGE.json`; owned capabilities are
recorded in [`RUNTIME_CAPABILITIES.json`](RUNTIME_CAPABILITIES.json). The active semantic delta
ledger in [`SEMANTIC_DELTAS.json`](SEMANTIC_DELTAS.json) owns every changed or added implementation file and names
its tests, documentation, evidence status, upstream disposition, and removal criteria.

The relocation from `third_party_patches/mlx-audio-swift` combined a path move with pre-existing
semantic deltas plus owned facade and governance additions; it was not pure byte parity. Against
repository commit `2f1391d846b2ed259db6959ca47f6129cddb58d2`, the migration retained 65
byte-identical files, modified 11, added 12, and removed none. The immutable classification and
destination-digest snapshot is [`RELOCATION_INVENTORY.json`](RELOCATION_INVENTORY.json). These
historical relocation facts are distinct from the live upstream-delta counts.

The `MLXAudioMark` target is not part of the `mlx-audio-swift` import. It is a repository-owned port
of Meta's AudioSeal watermark generator (`audioseal_wm_16bits`, MIT-licensed code and weights) from
[`facebookresearch/audioseal`](https://github.com/facebookresearch/audioseal), recorded as the
`MARK-001` entry in `SEMANTIC_DELTAS.json`. The validation that preceded the port recorded the
`audioseal` 0.2.0 Python package and weights fetched from Meta's Hugging Face repository
`facebook/audioseal`, and the parity fixtures come from the PyTorch reference implementation. The exact
upstream revisions were not recorded when the port was made; on 2026-09-24 they were reconstructed from
public metadata (no weights downloaded):

- **Weights.** The `audioseal_wm_16bits` card points at `generator_base.pth` in `facebook/audioseal`.
  Its content never changed: every revision from its upload (`20f3f5ae`, 2024-03-11, as
  `generator.pth`) through the current `main` (`3c19eba53390776cf2cc9ed5f6c9ac67ce72ecba`, 2025-12-09)
  carries the same LFS object, 58,805,980 bytes, SHA-256
  `7a845b5fbe9364a63a3909d8ab3fe064d13a76ae4c2e983573e08c69b7b51748`. The separate
  `generator_streaming.pth` (added 2025-12-09) is a different, Moshi-based architecture that this port
  does not implement. The hosted fp16 conversion
  (`marking/audioseal_wm16_generator_fp16.safetensors`, 73 tensors, 14,675,873 parameters, base SEANet
  `encoder`/`decoder`/`msg_processor` layout) matches the base generator's shape; the byte-level
  conversion itself is not reproduced (the conversion script is not in this repository).
- **Code.** `audioseal` 0.2.0 was published to PyPI on 2025-12-17; the GitHub commit that sets
  `__version__ = "0.2.0"` is `a0ce2564ff2ba706356cdd2ad4308c4bd499b43c` (2025-12-19, "Push streaming
  audioseal"). Upstream does not tag releases; the only later commit adds copyright headers.

The AudioSeal license notice is in [`NOTICES.md`](NOTICES.md).

Qwen3-TTS model and research attribution belongs to the Qwen team. Model weights are not included
in this repository and retain their own upstream terms.
