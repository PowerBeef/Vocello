"""What each benchmark record kind measures: its lineage identity (audit #22, #23, #34).

A record's comparison key decides which earlier record its deltas are taken
from. Until 2026-09-25 every kind hashed one shared list of 45 harness files
(the engine under test, the publisher and every other lane's probes included)
and the whole of project.yml, so nearly any edit started a new lineage: 39 of
48 comparable UI records had no baseline. Replaying file hashes over even a
narrow per-kind list did no better (2 of 16 canonical macOS UI records): the
harness files changed at almost every transition, for a moved consent toggle,
a comment, an environment-gated diagnostic, a new telemetry field or new gate
thresholds, none of which changes what a take measures.

Records stamped with ``inputs.lineageContractVersion`` are therefore keyed on
automatic structural guards plus one reviewed number per kind:

- ``lineageProjectHash``: the build-settings subset of project.yml the lane
  builds (global options, configs and settings, the lane's scheme, and every
  built target's settings), so a scheme or compiler-setting change such as the
  2026-07-23 screen-recording switch always starts a new lineage. Version
  labels, file membership, target links and package pins stay out.
- The topology (the take layer set, read from the takes), so in-process
  records never share a lineage with the XPC era.
- ``lineageMeasurementVersion``: the reviewed measurement version of the kind
  and platform (``LINEAGE_MEASUREMENT_VERSIONS``). A change that alters what
  the kind measures (an in-window driver action, a probe, the metric mapping
  or aggregation) bumps it in the same change (.claude/rules/release.md). The
  kind's path list (``LINEAGE_PATHS``) is the scope of that review;
  ``scripts/dev.sh check`` names changed files on it while this module is
  untouched. The memory contract version joins the key beside the evidence
  contract, so a memory aggregation change never depends on this review.
- ``lineageHarnessHash`` hashes that path list. It is provenance, not identity:
  benchmarks/HISTORY.md marks a delta taken across a harness change.

Engine sources and dependency pins stay out of every key: deltas exist to
measure engine changes. The key composition of a published contract version is
frozen; changing what the key reads bumps ``LINEAGE_CONTRACT_VERSION``. Legacy
records carry no version and keep their stored keys byte for byte.

Contract versions:

- 1 (2026-09-25): the composition above.
- 2 (2026-09-25, audit #11 option b, #29 and #30): contract 1 plus the memory tier a
  forced or emulated run measured (``runtime_policy_identity``: the forced
  ``deviceClass`` and the emulated ``simulatedPhysicalMemoryMB``; a native tier
  adds nothing, so a native record with or without ``run.runtimePolicy`` keys
  alike), the run's seed policy (``run.seedPolicy``) and the cell aggregate
  version (``evidence.cellAggregateVersion``), so emulated-floor and
  forced-tier records get a lineage of their own, a seeded matrix never shares
  one with random seeds, and medians that leave the take after a cold take out
  never compare with medians that kept it. Contract-1 records keep their
  stored keys.

Every function takes a ``read(path) -> bytes | None`` callable, so the same
identity is computed from the working tree at publication and from Git objects
when committed records are replayed offline.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Callable, Iterable

LINEAGE_CONTRACT_VERSION = 2
SUPPORTED_LINEAGE_CONTRACT_VERSIONS = frozenset({1, 2})
NOT_APPLICABLE = "not-applicable"

Reader = Callable[[str], "bytes | None"]

# The telemetry every generation lane publishes through: the per-take stamp,
# the telemetry row, the memory sampler, the memory aggregation (one series per
# process, audit #1) and the RTF/TTFC definitions.
GENERATION_TELEMETRY = (
    "Sources/QwenVoiceCore/BenchRunContext.swift",
    "Sources/QwenVoiceCore/GenerationTelemetryRecord.swift",
    "Sources/QwenVoiceCore/NativeTelemetrySampler.swift",
    "scripts/benchmark_memory.py",
    "scripts/lib/rtf.py",
)
# The UI benchmark's seed policy (audit #29): the app side and the checkers'
# mirror; and its declared matrices (audit #30).
UI_BENCH_DESIGN = (
    "Sources/QwenVoiceCore/BenchSeedPolicy.swift",
    "scripts/lib/bench_seed.py",
    "config/ui-bench-matrix.json",
    "scripts/lib/ui_bench_matrix.py",
)
# The shared XCUITest driver code that runs inside every measured UI window.
UI_AUTOMATION = (
    "Tests/UIAutomationSupport/VocelloPlaybackCaptureSupport.swift",
    "Tests/UIAutomationSupport/VocelloUIAutomationSupport.swift",
    "Tests/UIAutomationSupport/VocelloUIInteractionPolicy.swift",
)
# The app-side frontend timeline and the main-thread stall probe.
APP_TIMELINE = (
    "Sources/SharedSupport/Telemetry/AppGenerationTimeline.swift",
    "Sources/SharedSupport/Telemetry/MainThreadStallWatchdog.swift",
)
# Headless CLI lanes (vocello bench, memory, lang-bench, profiles): the lane
# script, its quiet-host preflight, the publisher that maps rows to take
# metrics, and the bench command and matrix.
MACOS_ENGINE_LANE = (
    "scripts/macos_test.sh",
    "scripts/lib/host_preflight.sh",
    "scripts/publish_benchmark_history.py",
    "Sources/VocelloCLI/BenchCommand.swift",
    "Sources/QwenVoiceCore/BenchMatrixSpec.swift",
    *GENERATION_TELEMETRY,
)
# Headless iPhone lanes: the device lane script, the in-app runner and the publisher.
IOS_ENGINE_LANE = (
    "scripts/ios_device.sh",
    "scripts/publish_benchmark_history.py",
    "Sources/iOS/IOSDeviceDiagnosticsRunner.swift",
    "Sources/QwenVoiceCore/BenchMatrixSpec.swift",
    *GENERATION_TELEMETRY,
)
# Delivery and prosody analysis whose outputs engine records publish per take.
DELIVERY_ANALYSIS = (
    "scripts/analyze_prosody.py",
    "scripts/bench_delivery_prosody.py",
    "scripts/clone_prosody_fidelity.py",
    "scripts/delivery_quality_gate.py",
    "scripts/delivery_separability.py",
    "scripts/prosody_profile.py",
    "scripts/prosody_quality_gate.py",
)
LANGUAGE_VERIFICATION = (
    "scripts/check_language_hints.py",
    "scripts/check_language_output.py",
    "scripts/independent_asr.py",
    "scripts/independent_asr_worker.py",
    "scripts/lib/language_metrics.py",
)
PROFILE_SUMMARY = (
    "scripts/lib/profile_trace_retention.py",
    # The per-take decode-loop interval statistics and their completeness check.
    "scripts/lib/trace_intervals.py",
    # The per-take CPU cycles per rusage CPU-second (audit #97).
    "scripts/lib/trace_cpu.py",
)

LINEAGE_PATHS: dict[tuple[str, str], tuple[str, ...]] = {
    ("ui-generation", "macos"): (
        "scripts/ui_test.sh",
        "scripts/lib/host_preflight.sh",
        "scripts/check_macos_ui_bench.py",
        "scripts/lib/playback_capture.py",
        *UI_AUTOMATION,
        "Tests/VocelloMacUITests/VocelloMacUITestCase.swift",
        "Tests/VocelloMacUITests/VocelloMacBenchmarkUITests.swift",
        "Tests/VocelloMacUITests/VocelloPlaybackCaptureSession.swift",
        *UI_BENCH_DESIGN,
        *APP_TIMELINE,
        *GENERATION_TELEMETRY,
    ),
    ("ui-generation", "ios"): (
        "scripts/ui_test.sh",
        "scripts/check_ios_ui_benchmark.py",
        *UI_AUTOMATION,
        "Tests/VocelloiOSUITests/VocelloiOSUITestCase.swift",
        "Tests/VocelloiOSUITests/VocelloiOSBenchmarkUITests.swift",
        *UI_BENCH_DESIGN,
        *APP_TIMELINE,
        *GENERATION_TELEMETRY,
    ),
    # The ceilings in config/ui-perf-thresholds*.json judge a record; they do not
    # shape what it measures, so they stay out of the identity (audit #34).
    ("ui-perf", "macos"): (
        "scripts/ui_test.sh",
        "scripts/lib/host_preflight.sh",
        "scripts/check_macos_ui_perf.py",
        "Sources/Services/UIPerfFrameProbe.swift",
        "Sources/Services/UIPerfHistorySeeder.swift",
        "Sources/SharedSupport/Telemetry/MainThreadStallWatchdog.swift",
        *UI_AUTOMATION,
        "Tests/VocelloMacUITests/VocelloMacUITestCase.swift",
        "Tests/VocelloMacUITests/VocelloMacPerfUITests.swift",
    ),
    ("ui-perf", "ios"): (
        "scripts/ui_test.sh",
        "scripts/check_ios_ui_perf.py",
        "Sources/iOSSupport/Services/IOSUIPerfFrameProbe.swift",
        "Sources/iOSSupport/Services/IOSUIPerfHistorySeeder.swift",
        "Sources/SharedSupport/Telemetry/MainThreadStallWatchdog.swift",
        *UI_AUTOMATION,
        "Tests/VocelloiOSUITests/VocelloiOSUITestCase.swift",
        "Tests/VocelloiOSUITests/VocelloiOSPerfUITests.swift",
    ),
    ("engine-generation", "macos"): (*MACOS_ENGINE_LANE, *DELIVERY_ANALYSIS),
    ("engine-generation", "ios"): IOS_ENGINE_LANE,
    ("memory-qualification", "macos"): (
        *MACOS_ENGINE_LANE, "config/memory-qualification-policy.json",
    ),
    ("memory-qualification", "ios"): (
        *IOS_ENGINE_LANE,
        "config/memory-qualification-policy.json",
        "config/ios-memory-budget-policy.json",
    ),
    ("language", "macos"): (*MACOS_ENGINE_LANE, *LANGUAGE_VERIFICATION),
    ("language", "ios"): (*IOS_ENGINE_LANE, *LANGUAGE_VERIFICATION),
    ("instrument-profile", "macos"): (*MACOS_ENGINE_LANE, *PROFILE_SUMMARY),
    ("instrument-profile", "ios"): (*IOS_ENGINE_LANE, *PROFILE_SUMMARY),
    # Calibration analyzes a labeled corpus; it builds and launches nothing.
    ("prosody-calibration", "macos"): (
        "scripts/analyze_prosody.py",
        "scripts/prosody_calibration.py",
        "scripts/prosody_profile.py",
        "scripts/publish_benchmark_history.py",
    ),
}

# Kinds that generate no speech from a prompt corpus: ui-perf replays seeded
# history, and its stored corpusHash is the default hash of the CLI bench matrix
# and UI driver files, which says nothing about what a ui-perf record measures.
CORPUS_FREE_KINDS = frozenset({"ui-perf"})

# The reviewed measurement version of each kind and platform. Bump one when a
# change alters what that kind measures (release.md "Records measure what they
# claim"); a bump starts a new lineage and never rewrites a stored key.
LINEAGE_MEASUREMENT_VERSIONS: dict[tuple[str, str], int] = {
    **{key: 1 for key in LINEAGE_PATHS},
    # Sampler change (2026-09-25, audit #3 part 4, #65 part 2), every kind that
    # carries memory evidence: periodic memory ticks no longer enumerate
    # threads, the floor tiers (8 GB Mac, iPhone) sample every 250 ms instead of
    # 500 ms, and every sample times its own capture. The versions below that
    # name it moved for it; the others were already moved in the same batch.
    ("ui-generation", "macos"): 2,
    ("ui-generation", "ios"): 2,
    # Also 2 for audit #39: delivery takes publish the remaining
    # expectation-bound paired features and their per-take adherence flags as a
    # diagnostic count; the cell verdict, not each take's flags, warns.
    ("engine-generation", "macos"): 2,
    ("memory-qualification", "macos"): 2,
    # 2 (2026-09-25, audit #12/#99): the CPU profile records three warm takes
    # instead of one on a quiet host, and publishes per-take decode-loop
    # interval statistics that must keep 36 intervals per decode step.
    # 3 (2026-09-25, audit #50/#97, the sampler change): the kind gains the
    # os_signpost-only witness profile, a macOS profile's matrix hash names its
    # profile kind, so a witness, CPU or memory profile never shares a lineage,
    # and a CPU trace reports each take's cycles per rusage CPU-second. No
    # record of the kind carried the lineage stamp yet.
    ("instrument-profile", "macos"): 3,
    # 2 (2026-09-25, audit #45/#56): the iPhone gate's generation step and the
    # memory-qualification wait no longer copy the whole diagnostics tree from
    # the phone every 10 s while the take runs; they poll only their markers.
    # 3 (2026-09-25): the sampler change, and iPhone evidence judged on the
    # measured process budget instead of absolute bands (audit #68).
    ("engine-generation", "ios"): 3,
    ("memory-qualification", "ios"): 3,
    # 2 (2026-09-25, audit #89): the whisper recognition time excludes model
    # load and warm-up, and the processed duration is the decoded sample count.
    # 3 (2026-09-25): the sampler change; and (audit #42/#43) the word gate
    # reads WER v2 (segmentation-aware) and each verdict channel is voted per
    # family; the Auto seed (#86) and the macOS corpus fixtures (#88) ride this
    # version because no record carries it yet.
    ("language", "macos"): 3,
    # 3 (2026-09-25, audit #87, #42/#43 and the sampler change): the iPhone lang-bench
    # probes each take's sentinel first at its predicted end, then every 3 s,
    # instead of every 10 s from the launch, so fewer device copies overlap the
    # measured generation.
    ("language", "ios"): 3,
    # 2 (2026-09-25, audit #51/#52/#97 and the sampler change): the iPhone
    # memory profile records through the Allocations template (no automatic VM
    # snapshots, which suspended the target), every iPhone profile stops
    # recording once its take's sentinel appears instead of recording the idle
    # app to the time limit, and a CPU trace reports the take's cycles per
    # rusage CPU-second.
    ("instrument-profile", "ios"): 2,
}

# (scheme, extra root targets) whose project.yml subset each lane builds;
# None when the lane builds nothing.
LINEAGE_PROJECT_SCOPES: dict[tuple[str, str], tuple[str | None, tuple[str, ...]] | None] = {
    ("ui-generation", "macos"): ("VocelloMacUI", ()),
    ("ui-perf", "macos"): ("VocelloMacUI", ()),
    ("ui-generation", "ios"): ("VocelloiOSUI", ()),
    ("ui-perf", "ios"): ("VocelloiOSUI", ()),
    **{
        (kind, "macos"): (None, ("VocelloCLI",))
        for kind in ("engine-generation", "memory-qualification", "language", "instrument-profile")
    },
    **{
        (kind, "ios"): ("VocelloiOS", ())
        for kind in ("engine-generation", "memory-qualification", "language", "instrument-profile")
    },
    ("prosody-calibration", "macos"): None,
}

PROJECT_FILE = "project.yml"
# Global project.yml blocks that set how every target builds. `packages` (the
# dependency pins) is engine, like the Package.resolved lock: out of the key.
PROJECT_GLOBAL_BLOCKS = ("options", "configs", "settings")
# Target sub-blocks that describe file membership or the link graph rather
# than how the target builds; `dependencies` is still followed to find targets.
PROJECT_TARGET_EXCLUDED_BLOCKS = frozenset({"sources", "resources", "dependencies"})
# Version labels: bumping a release never changes what a lane measures.
PROJECT_VERSION_LABELS = frozenset({"MARKETING_VERSION", "CURRENT_PROJECT_VERSION"})

_YAML_KEY_RE = re.compile(r"^( *)([A-Za-z0-9_.$()-]+):(?:[ \t]|$)")
_YAML_TARGET_DEPENDENCY_RE = re.compile(r"^ *- *target: *([A-Za-z0-9_.-]+) *$")


def has_lineage(kind: str, platform: str) -> bool:
    return (kind, platform) in LINEAGE_PATHS


def content_hash(paths: Iterable[str], read: Reader) -> str:
    """SHA-256 over (path, file SHA-256) pairs in path order; missing files are skipped.

    The same construction as benchmark_history.hash_existing_files."""
    digest = hashlib.sha256()
    found = False
    for path in sorted(set(paths)):
        data = read(path)
        if data is None:
            continue
        found = True
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).hexdigest().encode("ascii"))
    return digest.hexdigest() if found else NOT_APPLICABLE


def yaml_lines(text: str) -> list[tuple[tuple[str, ...], str]]:
    """(key path, line) for every significant line of a block-style YAML document.

    A line belongs to the innermost mapping key that encloses it; a key line
    belongs to its own key. Blank and comment-only lines are dropped. This is
    the subset project.yml uses (block mappings and lists, no anchors), read
    without a YAML dependency."""
    stack: list[tuple[int, str]] = []
    entries: list[tuple[tuple[str, ...], str]] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        match = _YAML_KEY_RE.match(raw)
        if match:
            while stack and stack[-1][0] >= indent:
                stack.pop()
            stack.append((indent, match.group(2)))
        else:
            # A list item or continuation belongs to the key it is nested under,
            # including a list written at its parent key's own indent.
            while stack and stack[-1][0] > indent:
                stack.pop()
        entries.append((tuple(key for _, key in stack), raw.rstrip()))
    return entries


def _block(entries: list[tuple[tuple[str, ...], str]], prefix: tuple[str, ...]) -> list[str]:
    return [
        line for path, line in entries
        if path[:len(prefix)] == prefix and not (PROJECT_VERSION_LABELS & set(path))
    ]


def _child_keys(entries: list[tuple[tuple[str, ...], str]], prefix: tuple[str, ...]) -> list[str]:
    return sorted({
        path[len(prefix)] for path, _ in entries
        if len(path) > len(prefix) and path[:len(prefix)] == prefix
    })


def project_targets(
    entries: list[tuple[tuple[str, ...], str]], scheme: str | None, roots: Iterable[str],
) -> list[str]:
    """The scheme's build targets plus the roots, closed over `- target:` dependencies."""
    pending = list(roots)
    if scheme:
        pending.extend(_child_keys(entries, ("schemes", scheme, "build", "targets")))
    targets: set[str] = set()
    while pending:
        name = pending.pop()
        if name in targets:
            continue
        targets.add(name)
        for line in _block(entries, ("targets", name, "dependencies")):
            if match := _YAML_TARGET_DEPENDENCY_RE.match(line):
                pending.append(match.group(1))
    return sorted(targets)


def project_subset(
    project_text: str, scheme: str | None, roots: Iterable[str],
) -> list[list[object]]:
    """[block name, normalized lines] for the build-settings subset a lane builds."""
    entries = yaml_lines(project_text)
    blocks: list[list[object]] = [[name, _block(entries, (name,))] for name in PROJECT_GLOBAL_BLOCKS]
    if scheme:
        blocks.append([f"schemes.{scheme}", _block(entries, ("schemes", scheme))])
    for target in project_targets(entries, scheme, roots):
        lines = [
            line for path, line in entries
            if path[:2] == ("targets", target)
            and not (len(path) > 2 and path[2] in PROJECT_TARGET_EXCLUDED_BLOCKS)
            and not (PROJECT_VERSION_LABELS & set(path))
        ]
        blocks.append([f"targets.{target}", lines])
    return blocks


def project_subset_hash(project_text: str | None, scheme: str | None, roots: Iterable[str]) -> str:
    if project_text is None:
        return NOT_APPLICABLE
    encoded = json.dumps(
        project_subset(project_text, scheme, roots), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def lineage_inputs(kind: str, platform: str, read: Reader) -> dict[str, object] | None:
    """The stored lineage fields for a new record, or None for a kind without a lineage."""
    paths = LINEAGE_PATHS.get((kind, platform))
    if paths is None:
        return None
    scope = LINEAGE_PROJECT_SCOPES.get((kind, platform))
    if scope is None:
        project_hash = NOT_APPLICABLE
    else:
        project = read(PROJECT_FILE)
        project_hash = project_subset_hash(
            project.decode("utf-8") if project is not None else None, scope[0], scope[1],
        )
    return {
        "lineageContractVersion": LINEAGE_CONTRACT_VERSION,
        "lineageMeasurementVersion": LINEAGE_MEASUREMENT_VERSIONS[(kind, platform)],
        "lineageHarnessHash": content_hash(paths, read),
        "lineageProjectHash": project_hash,
    }


def runtime_policy_identity(run: dict[str, object]) -> list[object] | None:
    """The memory-tier part of a contract-2 key (audit #11 option b).

    None for a native tier or a record without ``run.runtimePolicy``: the
    hardware profile already names the native tier. A forced class or an
    emulated smaller Mac (``QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB``) names the
    tier it ran under and the emulated RAM, so such records never share a
    lineage with the host's own."""
    policy = run.get("runtimePolicy")
    if not isinstance(policy, dict) or policy.get("deviceClassForced") is not True:
        return None
    return [policy.get("deviceClass"), policy.get("simulatedPhysicalMemoryMB")]


def topology(takes: Iterable[object]) -> list[str]:
    """The sorted layer set the takes were measured across (XPC era: engine-service too)."""
    layers: set[str] = set()
    for take in takes:
        if isinstance(take, dict) and isinstance(take.get("layers"), list):
            layers.update(str(layer) for layer in take["layers"])
    return sorted(layers)
