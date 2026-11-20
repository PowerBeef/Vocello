---
trigger: glob
globs: "**/scripts/**, **/.github/**, **/config/**, **/benchmarks/**, **/.agents/**, **/AGENTS.md"
---

# Tooling, CI & Evidence Rule

Before editing scripts, CI workflows, `config/` contracts, benchmark tooling, or `.agents/` harness
files, read `docs/reference/tooling-and-evidence.md` (the authoritative release/QA and evidence rule)
and `docs/reference/development-workflow.md` as relevant.

Non-negotiable invariants enforced here:
- **Contract & lint gates:** run `scripts/dev.sh check` locally; push CI on `main` is the gate.
  Update `scripts/lib/contract_gate.py` in the same commit if a validator starts reading a new path.
- **Owned build output:** `config/build-output-policy.json` owns `build/`; never delete whole caches
  (use `scripts/clean_build_caches.sh` selectively).
- **Evidence & privacy:** commit only compact privacy-safe records; never commit raw diagnostics,
  private paths, prompts, transcripts, credentials, WAVs, screenshots, or `.xcresult` bundles;
  preserve failed evidence and assign new run IDs to justified reruns.
- **Measured lanes & worker tracking:** join/stop all subagents (`manage_subagents list`,
  `swarm status`) and confirm no other host sessions are running before measured/model/device lanes,
  then run with `QVOICE_LEAD_ONLY=1`.
- **Supply chain & actions:** keep GitHub Actions SHA-pinned and synchronized with
  `config/toolchain.json`; never install or repin dependencies without explicit authorization.
