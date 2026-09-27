"""Stage 2 jobs for the AQ-06 judge panel (audit sections 3.4, 3.5 and 4).

The orchestrator runs each panel judge exactly as it runs whisper-small: one
persistent, supervised worker per judge per run (`scripts/audio_qc_worker.py`
inside the judge's pinned runtime, launched as
`acquire_audio_qc_judges.worker_launch` says), admitted by the budgeted
semaphore at the judge's registry ceiling and thread count, with its raw
output cached as L1 under its output identity and its metrics as L2. This
module holds what shapes a panel judge's rows, and therefore its L1:

- **Profiles.** Each judge's category (a recognizer, the aligner, language ID,
  a speaker embedding, pitch, Audiobox or DNSMOS), how its rows name the
  language (the ISO code the Whisper, Parakeet, Paraformer and SenseVoice
  engines read, or the English name the Qwen3 engines read), whether it reads
  the take's reference text (the aligner) and whether it embeds the take's
  reference clip as well (the speaker families, in the clone lane).
- **Scope.** A judge whose registry entry lists its languages
  (`panel.languages`) runs only on takes in them; the rest are out of scope.
- **Requests.** What keys an L1 entry beside the canonical audio and the output
  identity: the locked language where the row names one, and the script digest
  for the aligner. Language-free judges (LID, speaker, pitch, quality) share one
  L1 entry for identical audio, whatever the take's language.
- **Output identity.** Everything the registry lists as output identity:
  the entry's acquisition digest (pins and every file digest, decode options,
  configuration, preprocessing, engine and threads, never the qualification
  state), the runtime (lock or native binary, and the interpreter), the worker
  sources (this module included), the host (until cross-host determinism is
  measured) and the declared thread count.

Nothing here loads a model or reads the model root: the launch comes from the
judge's receipt, and the worker verifies its snapshot before it loads.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Mapping

from delivery_analysis_cache import NO_MODEL_DIGEST, CanonicalAudio, digest
from lib.language_metrics import LANGUAGE_LOCALE_CODES
from lib.qc_pipeline.layered_cache import JudgeIdentity, output_identity_digest

REPO = Path(__file__).resolve().parents[3]
PANEL_JOB_VERSION = "panel-job-v1"
PANEL_JOBS_SOURCE = Path(__file__).resolve()
WORKER_HOST = REPO / "scripts/audio_qc_worker.py"
PANEL_ENGINES_SOURCE = REPO / "scripts/lib/qc_pipeline/panel_engines.py"
WHISPER_WORKER_SOURCE = REPO / "scripts/independent_asr_worker.py"
# A reference clip's row for a speaker judge is planned under this suffix of its take's id.
REFERENCE_SUFFIX = "#reference"
CATEGORIES = ("asr", "alignment", "lid", "speaker", "pitch", "audiobox", "dnsmos")
CODE_TO_LANGUAGE = {code: name for name, code in LANGUAGE_LOCALE_CODES.items()}


class PanelJobError(ValueError):
    """A panel judge cannot be built into a Stage 2 job."""


@dataclass(frozen=True)
class PanelProfile:
    category: str
    # How a row names its language: "iso" (en), "name" (English), or None (no language).
    language_style: str | None
    needs_script: bool = False
    needs_reference: bool = False
    # The judge identifies the language from the audio, so its detected language is a language vote.
    language_channel: bool = False

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES or self.language_style not in ("iso", "name", None):
            raise PanelJobError("a panel profile names a known category and language style")


PROFILES: dict[str, PanelProfile] = {
    "asr.whisper-large-v3@1": PanelProfile("asr", "iso", language_channel=True),
    "asr.parakeet-tdt-0.6b-v3@1": PanelProfile("asr", "iso"),
    "asr.paraformer-zh@1": PanelProfile("asr", "iso"),
    "asr.sensevoice-small-f16@1": PanelProfile("asr", "iso", language_channel=True),
    "asr.qwen3-asr-1.7b@1": PanelProfile("asr", "name"),
    "align.qwen3-forcedaligner-0.6b@1": PanelProfile("alignment", "name", needs_script=True),
    "lid.voxlingua107-ecapa@1": PanelProfile("lid", None, language_channel=True),
    "speaker.campplus-voxceleb@1": PanelProfile("speaker", None, needs_reference=True),
    "speaker.resnet293-voxceleb@1": PanelProfile("speaker", None, needs_reference=True),
    "pitch.pyin@1": PanelProfile("pitch", None),
    "quality.audiobox-aesthetics@1": PanelProfile("audiobox", None),
    "quality.dnsmos-p835@1": PanelProfile("dnsmos", None),
}


def profile(judge_id: str) -> PanelProfile:
    found = PROFILES.get(judge_id)
    if found is None:
        raise PanelJobError(f"{judge_id} is not a panel judge the orchestrator knows how to run")
    return found


def panel_judge_ids(registry: Mapping[str, Any]) -> list[str]:
    """Every runnable panel judge: an acquisition entry, a known profile, not retired or quarantined."""
    return sorted(
        judge_id for judge_id, judge in (registry.get("judges") or {}).items()
        if isinstance(judge, Mapping) and "acquisition" in judge
        and judge.get("status") not in ("retired", "quarantined") and judge_id in PROFILES
    )


def judge_scope(judge: Mapping[str, Any]) -> frozenset[str] | None:
    """The language names a judge's entry lists (`panel.languages`), or None when it names none."""
    languages = ((judge.get("panel") or {}).get("languages")) if isinstance(judge.get("panel"), Mapping) else None
    if not isinstance(languages, Mapping):
        return None
    names = set()
    for codes in languages.values():
        for code in codes if isinstance(codes, list) else []:
            if code not in CODE_TO_LANGUAGE:
                raise PanelJobError(f"panel language {code!r} is not a product language")
            names.add(CODE_TO_LANGUAGE[code])
    return frozenset(names)


def row_language(style: str | None, language: str) -> str | None:
    if style == "iso":
        return LANGUAGE_LOCALE_CODES[language]
    if style == "name":
        return language.capitalize()
    return None


def panel_request(spec: PanelProfile, scope: frozenset[str] | None, take: Mapping[str, Any]) -> dict[str, Any] | None:
    """What the judge is asked for this take (part of its L1 key); None when the take is out of its scope."""
    language = take["language"]
    if scope is not None and language not in scope:
        return None
    request: dict[str, Any] = {}
    locked = row_language(spec.language_style, language)
    if locked is not None:
        request["lockedLanguage"] = locked
    if spec.needs_script:
        script = take.get("referenceText")
        if not isinstance(script, str) or not script.strip():
            return None
        request["scriptSHA256"] = take["scriptSHA256"]
    return request


def panel_job_row(spec: PanelProfile, key: str, canonical: CanonicalAudio, request: Mapping[str, Any],
                  take: Mapping[str, Any] | None) -> dict[str, Any]:
    """One worker row. The job file is private; it may carry the reference text the aligner reads."""
    row: dict[str, Any] = {"id": key, "pcmPath": str(canonical.derivative_path)}
    if "lockedLanguage" in request:
        row["language"] = request["lockedLanguage"]
    if spec.needs_script and take is not None and "scriptSHA256" in request:
        row["referenceText"] = take["referenceText"]
    return row


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def worker_sources(engine: str, *, root: Path = REPO) -> dict[str, str]:
    """The sources a panel worker runs for this engine, by repository path: output identity."""
    paths = [WORKER_HOST, PANEL_ENGINES_SOURCE, PANEL_JOBS_SOURCE]
    if engine == "whisper-mlx":
        paths.append(WHISPER_WORKER_SOURCE)
    sources = {}
    for path in paths:
        relative = path.relative_to(REPO).as_posix()
        sources[relative] = _file_sha256(root / relative)
    return dict(sorted(sources.items()))


def runtime_identity(registry: Mapping[str, Any], judge_id: str) -> dict[str, Any]:
    """The pinned runtime a panel judge runs in: its venv lock or native binary, and the interpreter."""
    judge = (registry.get("judges") or {}).get(judge_id) or {}
    acquisition = registry.get("acquisition") or {}
    family = (judge.get("acquisition") or {}).get("runtime")
    spec = (acquisition.get("runtimes") or {}).get(family)
    if not isinstance(spec, Mapping):
        raise PanelJobError(f"{judge_id} names no registered runtime family")
    interpreter = (acquisition.get("interpreter") or {}).get("sha256")
    if spec.get("kind") == "venv":
        return {"family": family, "kind": "venv", "lockSHA256": spec.get("lockSHA256"),
                "interpreterSHA256": interpreter}
    artifact = (acquisition.get("artifacts") or {}).get(spec.get("artifact")) or {}
    return {"family": family, "kind": "native", "archiveSHA256": artifact.get("sha256"),
            "binarySHA256": (artifact.get("members") or {}).get(spec.get("binary")),
            "interpreterSHA256": interpreter}


def identity_components(judge_id: str, registry: Mapping[str, Any], *, engine: str, threads: int,
                        host: Mapping[str, Any], root: Path = REPO) -> dict[str, Any]:
    """Every output-identity component of one panel judge (registry `identity.output`)."""
    from audio_qc_judges import acquisition_entry_digest

    judge = (registry.get("judges") or {}).get(judge_id)
    if not isinstance(judge, Mapping):
        raise PanelJobError(f"{judge_id} is not registered")
    execution = judge.get("execution") or {}
    if execution.get("engine") != engine or execution.get("threads") != threads:
        raise PanelJobError(f"{judge_id}: the launch's engine and threads must be the registry's")
    return {
        "panelJobVersion": PANEL_JOB_VERSION,
        "registryEntrySHA256": acquisition_entry_digest(dict(judge)),
        "runtime": runtime_identity(registry, judge_id),
        "workerSourceSHA256": worker_sources(engine, root=root),
        "engine": engine,
        "hostProfile": dict(host),
        "threads": threads,
    }


def panel_identity(judge_id: str, registry: Mapping[str, Any], components: Mapping[str, Any]) -> JudgeIdentity:
    """The L1 identity of a panel judge: its output identity, repository, revision and pinned files."""
    judge = (registry.get("judges") or {}).get(judge_id) or {}
    pins = judge.get("pins") or {}
    files = pins.get("files") or {}
    return JudgeIdentity(
        judge_id, output_identity_digest(judge_id, components),
        str(pins.get("repository") or "none"), str(pins.get("revision") or "not-applicable"),
        digest({"files": files}) if files else NO_MODEL_DIGEST,
    )
