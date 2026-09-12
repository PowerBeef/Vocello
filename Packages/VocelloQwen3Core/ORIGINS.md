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

Qwen3-TTS model and research attribution belongs to the Qwen team. Model weights are not included
in this repository and retain their own upstream terms.
