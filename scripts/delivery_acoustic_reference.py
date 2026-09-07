"""Frozen descriptive reference data for the existing delivery cascade, not a gate.

No downloads, model execution, fitting, label inference or quality verdicts. Labels
are used only after blind extraction to select a same-language comparison cohort.
"""
from __future__ import annotations

import json
import math
import re
import statistics
import sys
import tempfile
from pathlib import Path
import numpy as np

from analyze_prosody import analyze
from delivery_analysis_cache import LayerIdentity, NO_MODEL_DIGEST, digest, file_sha256
from delivery_compact_model_adapter import _canonical_wav

REPO = Path(__file__).resolve().parents[1]
CONTRACT = REPO / "config/delivery-evaluator-v2-contract.json"
FEATURES = (
    "durationSec", "f0_median_hz", "f0_range_semitones", "f0_voiced_frac",
    "rate_syllable_rate_hz", "pauses_pause_speech_ratio", "energy_rms_mean_db",
    "energy_dynamic_range_db", "spectral_alpha_ratio_db", "spectral_centroid_hz",
    "spectral_hf_energy_ratio", "spectral_flux", "spectral_hammarberg_db",
    "voice_hnr_db_mean", "voice_cpp_db_mean",
)
SHA = re.compile(r"[0-9a-f]{64}")


def validate_base(base: dict) -> None:
    """Structural and pairing checks supplement the contract's exact file digest."""
    if (base.get("kind") != "licensed-acoustic-reference" or base.get("schemaVersion") != 1
            or base.get("promotionAuthority") is not False or base.get("qualityLabels") is not False
            or base.get("exposure") != "development-only"):
        raise ValueError("invalid-reference-authority")
    rows = base.get("rows", [])
    if len(rows) != 45 or len({r['id'] for r in rows}) != 45:
        raise ValueError("reference-accounting-mismatch")
    by_id = {r['id']: r for r in rows}
    for row in rows:
        if not re.fullmatch(r"ref-[0-9]{3}", row['id']):
            raise ValueError("invalid-reference-id")
        for key in ('audioSHA256', 'canonicalPCM16kSHA256', 'sourceGroup', 'scriptGroup', 'speakerGroup'):
            if not SHA.fullmatch(row[key]):
                raise ValueError("invalid-reference-digest")
        if set(row['features']) != set(FEATURES) or any(
                type(v) not in (int, float) or not math.isfinite(v) for v in row['features'].values()):
            raise ValueError("invalid-reference-features")
        if row['features']['durationSec'] <= 0:
            raise ValueError("invalid-reference-duration")
        if row['dataset'] not in base['sources'] or row['nativeQC']['verdict'] not in ('pass', 'warn', 'fail'):
            raise ValueError("invalid-reference-provenance")
        for field in ('sourceWarnings', 'advisoryWarnings'):
            if not isinstance(row[field], list) or not all(isinstance(v, str) for v in row[field]):
                raise ValueError("invalid-reference-warnings")
        neutral = row.get('neutralID')
        if neutral is not None:
            other = by_id.get(neutral)
            if (other is None or other['preset'] != 'neutral' or row['preset'] == 'neutral'
                    or any(row[k] != other[k] for k in ('dataset', 'language', 'speakerGroup', 'scriptGroup'))
                    or row['sourceGroup'] == other['sourceGroup']):
                raise ValueError("invalid-reference-pair")
    if sum(r.get('neutralID') is not None for r in rows) != 24:
        raise ValueError("reference-pair-accounting-mismatch")


def load_base() -> dict:
    registration = json.loads(CONTRACT.read_text())['acousticReferenceBase']
    path = REPO / registration['manifest']
    if path.resolve().parent != (REPO / 'config').resolve():
        raise ValueError("invalid-reference-registration")
    if file_sha256(path) != registration['sha256']:
        raise ValueError("reference-manifest-drift")
    base = json.loads(path.read_text())
    validate_base(base)
    base['_manifestSHA256'] = registration['sha256']
    return base


def availability(base: dict, resampler: str) -> str | None:
    if resampler != base['preprocessing']['resamplerVersion']:
        return 'reference-preprocessing-mismatch'
    for name, expected in base['featureSources'].items():
        if file_sha256(REPO / 'scripts' / name) != expected:
            return 'reference-feature-source-drift'
    return None


def verify_originals(base: dict, directory: Path) -> dict:
    """Optional operator audit; unavailable audio is never a normal CI prerequisite."""
    results = []
    for row in base['rows']:
        path = directory / (row['id'] + '.wav')
        status = ('missing' if not path.is_file() else
                  'matched' if not path.is_symlink() and file_sha256(path) == row['audioSHA256'] else 'mismatch')
        results.append({'id': row['id'], 'status': status})
    return {'rows': results, 'allMatched': all(r['status'] == 'matched' for r in results)}


def extract_canonical(canonical, cache, base: dict) -> tuple[dict, bool]:
    """Label-blind, bounded PCM extraction; neutral hits do no work/model launch."""
    identity = LayerIdentity(
        original_wav_sha256=canonical.original_wav_sha256,
        canonical_derivative_sha256=canonical.canonical_derivative_sha256,
        layer_id='reference-global-16k', layer_version='1',
        binary_sha256=file_sha256(Path(__file__)), model_id='none',
        model_revision='not-applicable', weights_sha256=NO_MODEL_DIGEST,
        preprocessing_config_digest=digest({'preprocessing': base['preprocessing'],
                                            'featureSources': base['featureSources'],
                                            'pythonVersion': sys.version, 'numpyVersion': np.__version__}))

    def compute():
        with tempfile.TemporaryDirectory(prefix='reference-', dir=canonical.derivative_path.parent) as folder:
            wav = Path(folder) / 'audio.wav'
            _canonical_wav(canonical, wav)
            result = analyze(str(wav))
            if 'error' in result:
                raise ValueError('reference-feature-extraction-failed')
            return {key: result[key] for key in FEATURES}
    return cache.get_or_compute(identity, compute)


def contrast(instructed: dict, neutral: dict) -> dict:
    result = {k: instructed[k] - neutral[k] for k in FEATURES if k not in ('durationSec', 'f0_median_hz')}
    result['pitchShiftSemitones'] = (12 * math.log2(instructed['f0_median_hz'] / neutral['f0_median_hz'])
                                   if min(instructed['f0_median_hz'], neutral['f0_median_hz']) > 0 else None)
    result['durationRatio'] = instructed['durationSec'] / neutral['durationSec'] if neutral['durationSec'] > 0 else None
    return result


def flagged(row: dict) -> bool:
    return bool(row['sourceWarnings'] or row['advisoryWarnings'] or row['nativeQC']['flags']
                or any(row['nativeQC'][k] != 'pass' for k in
                       ('verdict', 'instabilityVerdict', 'writtenOutputVerdict')))


def distribution(values: list[float], observed: float | None) -> dict:
    if not values:
        return {'n': 0, 'comparison': 'unavailable'}
    low, high = min(values), max(values)
    valid = type(observed) in (float, int) and math.isfinite(observed)
    return {'n': len(values), 'minimum': low, 'median': statistics.median(values), 'maximum': high,
            'observed': observed if valid else None,
            'comparison': ('unmeasured' if not valid else 'below-observed-range' if observed < low
                           else 'above-observed-range' if observed > high else 'within-observed-range')}


def compare(base: dict, *, preset: str, language: str, instructed: dict, neutral: dict) -> dict:
    """Descriptive empirical ranges, never a population interval or emotion score."""
    matches = [r for r in base['rows'] if r['preset'] == preset and r['language'] == language.lower()]
    by_id = {r['id']: r for r in base['rows']}
    pairs = [r for r in matches if r['neutralID'] is not None]
    paired = bool(pairs)
    cohort = pairs if paired else matches
    sample = contrast(instructed, neutral) if paired else instructed
    values = {r['id']: contrast(r['features'], by_id[r['neutralID']]['features']) if paired
              else r['features'] for r in cohort}
    excluded = [r['id'] for r in cohort if flagged(r) or (paired and flagged(by_id[r['neutralID']]))]
    metrics = {}
    for key, observed in sample.items():
        all_values = [values[r['id']][key] for r in cohort if values[r['id']][key] is not None]
        clean = [values[r['id']][key] for r in cohort if r['id'] not in excluded and values[r['id']][key] is not None]
        metrics[key] = {'allReferences': distribution(all_values, observed),
                        'excludingFlaggedSensitivity': distribution(clean, observed)}
    ids = {r['id'] for r in cohort} | {r['neutralID'] for r in pairs}
    return {'schemaVersion': 1, 'baseID': base['id'], 'manifestSHA256': base['_manifestSHA256'],
            'status': 'descriptive' if cohort else 'missing-coverage',
            'comparisonKind': 'same-speaker-text-neutral-delta' if paired else 'unpaired-style-context',
            'referenceCount': len(cohort), 'speakerCount': len({r['speakerGroup'] for r in cohort}),
            'scriptCount': len({r['scriptGroup'] for r in cohort}),
            'reason': None if paired else 'no-matched-neutral-controls' if cohort else 'no-same-language-preset-references',
            'references': [{'id': r['id'], 'neutralID': r['neutralID'], 'sourceWarnings': r['sourceWarnings'],
                            'nativeQC': r['nativeQC'], 'advisoryWarnings': r['advisoryWarnings']}
                           for r in base['rows'] if r['id'] in ids],
            'sensitivityExcludedIDs': excluded, 'metrics': metrics,
            'limitations': base['limitations'], 'promotionAuthority': False, 'qualityVerdict': 'not-assessed'}
