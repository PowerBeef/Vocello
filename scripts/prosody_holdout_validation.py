#!/usr/bin/env python3
"""Validate an untouched, independently grouped prosody-threshold holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import prosody_calibration
from prosody_profile import load_profile
from prosody_corpus_inventory import audio_identity, inventory_audio


ROOT = Path(__file__).resolve().parent.parent
METADATA_FIELDS = (
    "speakerGroup", "scriptGroup", "translationGroup", "lengthClass", "language", "defectSeverity"
)


class HoldoutError(ValueError):
    pass


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HoldoutError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise HoldoutError(f"{path.name} must contain an object")
    return value


def validate_policy(root: Path = ROOT) -> dict[str, Any]:
    policy = _load_object(root / "config/prosody-holdout-policy.json")
    if policy.get("schemaVersion") != 1 or policy.get("confidenceLevel") != 0.95:
        raise HoldoutError("prosody holdout policy must be schema v1 at 95% confidence")
    for key in (
        "minimumCalibrationClips", "minimumHoldoutGoodClips", "minimumHoldoutBadClips",
        "minimumHoldoutSpeakerGroups", "minimumHoldoutScriptGroups", "minimumHoldoutLanguages",
    ):
        if type(policy.get(key)) is not int or policy[key] < 2:
            raise HoldoutError(f"{key} must be an integer of at least two")
    for key in ("maximumFalsePositiveRateUpperBound", "minimumTruePositiveRateLowerBound"):
        value = policy.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < 1:
            raise HoldoutError(f"{key} is invalid")
    for key in ("requiredLengthClasses", "requiredDefectSeverities", "groupIsolation"):
        value = policy.get(key)
        if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
            raise HoldoutError(f"{key} must be a non-empty string array")
    if set(policy["groupIsolation"]) != {"speakerGroup", "scriptGroup", "translationGroup"}:
        raise HoldoutError("holdout isolation must cover speaker, script, and translation groups")
    good, bad = policy["minimumHoldoutGoodClips"], policy["minimumHoldoutBadClips"]
    if _wilson(0, good)["upper"] > policy["maximumFalsePositiveRateUpperBound"]:
        raise HoldoutError("good-clip floor cannot satisfy the false-positive bound even with zero errors")
    if _wilson(bad, bad)["lower"] < policy["minimumTruePositiveRateLowerBound"]:
        raise HoldoutError("bad-clip floor cannot satisfy the true-positive bound even with perfect detection")
    if policy.get("samplingUnit") != "independent-source-recording":
        raise HoldoutError("sampling unit must identify independent source recordings")
    if policy.get('reviewAuthority') != {
        'humanListeningRequired': False, 'default': 'independent-reference-evidence',
        'acceptedSources': ['controlled-pcm', 'published-label', 'optional-human-annotation'],
        'detectorSelfLabelsAllowed': False, 'controlledFixturesQualifyPerceptualQuality': False,
    }:
        raise HoldoutError('automated independent-reference policy is invalid')
    catalogs = policy.get('approvedExternalCatalogSHA256')
    if (not isinstance(catalogs, list)
            or any(not isinstance(item, str) or not re.fullmatch(r'[0-9a-f]{64}', item) for item in catalogs)
            or len(set(catalogs)) != len(catalogs)):
        raise HoldoutError('approved external catalog pins are invalid')
    annotation = policy.get("annotationProtocol", {})
    if annotation.get("id") != "speech-defects-1" or annotation.get("minimumIndependentReviewers") != 3:
        raise HoldoutError("independent speech/defect annotation protocol is required")
    if annotation.get('minimumFluentReviewersPerClip') != 1 or annotation.get('decisions') != ['acceptable', 'objectionable', 'uncertain']:
        raise HoldoutError('annotation fluency and uncertainty contract is invalid')
    return policy


def _safe_token(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value):
        raise HoldoutError(f"{field} must be a privacy-safe stable token")
    return value


def _clip_digest(entry: dict[str, Any]) -> str:
    try:
        with Path(entry["path"]).open("rb") as audio:
            return hashlib.file_digest(audio, "sha256").hexdigest()
    except OSError as error:
        raise HoldoutError("a manifest clip cannot be read") from error


def validate_manifests(
    calibration: list[dict[str, Any]],
    holdout: list[dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    if len(calibration) < policy["minimumCalibrationClips"]:
        raise HoldoutError("calibration manifest is below the frozen minimum")
    good = sum(row.get("label") == "good" for row in holdout)
    bad = sum(row.get("label") == "bad" for row in holdout)
    if good < policy["minimumHoldoutGoodClips"] or bad < policy["minimumHoldoutBadClips"]:
        raise HoldoutError("holdout lacks the frozen good/bad sample floors")
    for split_name, entries in (("calibration", calibration), ("holdout", holdout)):
        for row in entries:
            if row.get('exposure') not in ('previously-examined', 'untouched'):
                raise HoldoutError('source exposure history is required')
            if split_name == 'holdout' and row['exposure'] != 'untouched':
                raise HoldoutError('previously examined audio cannot qualify an untouched holdout')
            _safe_token(row.get("sourceGroup"), f"{split_name}.sourceGroup")
            for field in METADATA_FIELDS:
                _safe_token(row.get(field), f"{split_name}.{field}")
    calibration_audio = {_clip_digest(row) for row in calibration}
    holdout_audio = {_clip_digest(row) for row in holdout}
    if calibration_audio & holdout_audio:
        raise HoldoutError("calibration and holdout reuse audio bytes")
    if len(calibration_audio) != len(calibration) or len(holdout_audio) != len(holdout):
        raise HoldoutError("duplicate audio cannot count as independent observations")
    # Container metadata is not a new observation. Variants/replays of one
    # recording must also share sourceGroup, even when their PCM differs.
    pcm = [[audio_identity(Path(row["path"]))["pcmSHA256"] for row in rows]
           for rows in (calibration, holdout)]
    if len(set(pcm[0] + pcm[1])) != len(calibration) + len(holdout):
        raise HoldoutError("duplicate PCM cannot count as independent observations")
    if len({row["sourceGroup"] for row in holdout}) != len(holdout):
        raise HoldoutError("holdout requires one primary observation per independent sourceGroup")
    origins = [
        [(row.get('referenceEvidence') or {}).get('referenceSHA256', _clip_digest(row))
         for row in entries] for entries in (calibration, holdout)
    ]
    if set(origins[0]) & set(origins[1]) or len(set(origins[1])) != len(holdout):
        raise HoldoutError('controlled derivatives cannot disguise source reuse across holdout observations')
    for field in (*policy["groupIsolation"], "sourceGroup"):
        if {row[field] for row in calibration} & {row[field] for row in holdout}:
            raise HoldoutError(f"calibration and holdout leak {field}")
    speaker_count = len({row["speakerGroup"] for row in holdout})
    script_count = len({row["scriptGroup"] for row in holdout})
    languages = sorted({row["language"] for row in holdout})
    if speaker_count < policy["minimumHoldoutSpeakerGroups"]:
        raise HoldoutError("holdout speaker coverage is incomplete")
    if script_count < policy["minimumHoldoutScriptGroups"]:
        raise HoldoutError("holdout script coverage is incomplete")
    if len(languages) < policy["minimumHoldoutLanguages"]:
        raise HoldoutError("holdout language coverage is incomplete")
    if not set(policy["requiredLengthClasses"]) <= {row["lengthClass"] for row in holdout}:
        raise HoldoutError("holdout length coverage is incomplete")
    if not set(policy["requiredDefectSeverities"]) <= {row["defectSeverity"] for row in holdout}:
        raise HoldoutError("holdout defect-severity coverage is incomplete")
    return {
        "calibrationClipCount": len(calibration),
        "holdoutGoodClipCount": good,
        "holdoutBadClipCount": bad,
        "holdoutSpeakerGroupCount": speaker_count,
        "holdoutScriptGroupCount": script_count,
        "holdoutLanguages": languages,
        "holdoutSourceGroupCount": len({row["sourceGroup"] for row in holdout}),
        "samplingUnit": policy["samplingUnit"],
    }


def validate_annotations(row: dict[str, Any], policy: dict[str, Any]) -> str:
    """Validate independent observations, not an analyzer's self-assigned labels.

    Pseudonyms and human/fluency declarations require operator attestation; this
    validates binding/structure, not that a program can authenticate a human.
    Disagreement needs a separate, blind adjudicator, preserving original votes.
    """
    protocol = policy['annotationProtocol']
    responses = row.get('annotations')
    if not isinstance(responses, list) or len(responses) < protocol['minimumIndependentReviewers']:
        raise HoldoutError('independent per-listener annotations are missing')
    identity = audio_identity(Path(row['path']))
    reviewers = set()

    def checked(response):
        if not isinstance(response, dict):
            raise HoldoutError('annotation must be an object')
        reviewer = response.get('reviewerID')
        if not isinstance(reviewer, str) or not re.fullmatch(r'[0-9a-f]{64}', reviewer) or reviewer in reviewers:
            raise HoldoutError('annotations require distinct anonymous reviewer digests')
        reviewers.add(reviewer)
        if response.get('audioSHA256') != identity['audioSHA256']:
            raise HoldoutError('annotation audio binding does not match')
        if response.get('protocolID') != protocol['id'] or response.get('source') != 'independent-human':
            raise HoldoutError('annotation must declare the independent human protocol')
        confidence = response.get('confidence')
        if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise HoldoutError('annotation confidence must be finite and bounded')
        decision = response.get('decision')
        if decision not in protocol['decisions']:
            raise HoldoutError('annotation decision is invalid')
        languages = response.get('fluentLanguages')
        if not isinstance(languages, list) or any(not isinstance(item, str) for item in languages):
            raise HoldoutError('annotation fluent languages are required')
        defects = response.get('defects')
        if not isinstance(defects, list) or (decision == 'objectionable' and not defects):
            raise HoldoutError('objectionable annotations require defect intervals')
        for defect in defects:
            if not isinstance(defect, dict) or defect.get('type') not in protocol['defectTypes']:
                raise HoldoutError('annotation defect type is invalid')
            if defect.get('severity') not in ('mild', 'moderate', 'severe'):
                raise HoldoutError('annotation defect severity is invalid')
            start, end = defect.get('startSeconds'), defect.get('endSeconds')
            if any(type(value) not in (int, float) or not math.isfinite(value) for value in (start, end)) or not 0 <= start < end <= identity['durationSeconds']:
                raise HoldoutError('annotation interval is outside the original WAV')
        return decision, row['language'] in languages

    votes = [checked(response) for response in responses]
    if not any(fluent for _, fluent in votes):
        raise HoldoutError('annotations lack fluent-language coverage')
    expected = {'good': 'acceptable', 'bad': 'objectionable'}.get(row['label'])
    if expected is None:
        raise HoldoutError('a binary label must be independently resolved')
    resolved_responses = responses
    if any(decision != expected for decision, _ in votes):
        adjudication = row.get('adjudication')
        response_digest = hashlib.sha256(json.dumps(responses, sort_keys=True).encode()).hexdigest()
        if not isinstance(adjudication, dict) or adjudication.get('responseSetSHA256') != response_digest:
            raise HoldoutError('disagreement or uncertainty needs retained independent adjudication')
        decision, fluent = checked(adjudication)
        if decision != expected or not fluent:
            raise HoldoutError('adjudication must independently resolve the label with language fluency')
        resolved_responses = [adjudication]
    severity_order = ['none', 'mild', 'moderate', 'severe']
    severity = max((severity_order.index(defect['severity'])
                    for response in resolved_responses for defect in response['defects']), default=0)
    if row.get('defectSeverity') != severity_order[severity]:
        raise HoldoutError('declared defect severity disagrees with independent annotations')
    return hashlib.sha256(json.dumps({'annotations': responses, 'adjudication': row.get('adjudication')}, sort_keys=True).encode()).hexdigest()


def validate_label_evidence(row: dict[str, Any], policy: dict[str, Any]) -> dict[str, str]:
    """Reference truth is independent of the detector being fitted.

    Existing listener records remain optional, strictly validated inputs. Machine
    fixtures establish an exact signal transformation, never general usability.
    Published labels require an immutable local annotation file; no network runs.
    """
    evidence = row.get('referenceEvidence')
    if evidence is None:
        return {'scope': 'listener-labelled-cohort', 'sha256': validate_annotations(row, policy)}
    if not isinstance(evidence, dict):
        raise HoldoutError('reference evidence must be an object')
    audio = audio_identity(Path(row['path']))
    if evidence.get('audioSHA256') != audio['audioSHA256']:
        raise HoldoutError('reference evidence audio binding mismatch')
    kind = evidence.get('kind')
    if kind == 'published-label':
        # The registry is private. Only its content digest and declared scope
        # leave this function; URLs, local paths and labels are not copied out.
        try:
            annotation_path = Path(evidence['annotationFile'])
            if annotation_path.stat().st_size > 16 * 1024**2:
                raise HoldoutError('published annotations exceed the bounded input size')
            raw = annotation_path.read_bytes()
        except (OSError, KeyError, TypeError) as error:
            raise HoldoutError('published reference annotations unavailable') from error
        if hashlib.sha256(raw).hexdigest() != evidence.get('annotationFileSHA256'):
            raise HoldoutError('published reference annotations changed')
        if evidence['annotationFileSHA256'] not in policy['approvedExternalCatalogSHA256']:
            raise HoldoutError('external reference catalog is not independently approved and pinned')
        corpus = json.loads(raw)
        if (not isinstance(corpus, dict) or corpus.get('kind') != 'external-reference-labels'
                or not isinstance(corpus.get('source'), str) or not corpus['source'].startswith('https://')
                or not all(isinstance(corpus.get(key), str) and corpus[key].strip()
                           for key in ('revision', 'license', 'labelDefinition'))
                or corpus.get('derivedFromVocelloEvaluator') is not False):
            raise HoldoutError('independent published label provenance is incomplete')
        matches = [entry for entry in corpus.get('rows', []) if isinstance(entry, dict)
                   and entry.get('audioSHA256') == audio['audioSHA256']]
        if (len(matches) != 1 or matches[0].get('label') != row['label']
                or matches[0].get('defectSeverity') != row['defectSeverity']):
            raise HoldoutError('published reference label does not match the frozen row')
        scope = 'external-dataset-label-definition-only'
    elif kind == 'controlled-pcm':
        try:
            reference = Path(evidence['referenceWAV'])
            original = audio_identity(reference)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise HoldoutError('controlled reference audio unavailable') from error
        if original['audioSHA256'] != evidence.get('referenceSHA256'):
            raise HoldoutError('controlled reference digest mismatch')
        operation = evidence.get('operation')
        start, end = evidence.get('startFrame'), evidence.get('endFrame')
        if operation not in ('unchanged', 'mute-interval'):
            raise HoldoutError('unregistered controlled transformation')
        with wave.open(str(reference), 'rb') as source, wave.open(row['path'], 'rb') as target:
            if source.getparams() != target.getparams() or source.getsampwidth() != 2:
                raise HoldoutError('controlled PCM requires identical PCM16 formats and frame counts')
            frames, channels = source.getnframes(), source.getnchannels()
            if operation == 'mute-interval':
                if (type(start) is not int or type(end) is not int or not 0 < start < end < frames
                        or row['label'] != 'bad' or row['defectSeverity'] == 'none'):
                    raise HoldoutError('controlled interval or label invalid')
            elif row['label'] != 'good' or row['defectSeverity'] != 'none':
                raise HoldoutError('unchanged control must have no injected defect')
            changed = False
            for offset in range(0, frames, 8192):
                expected = bytearray(source.readframes(min(8192, frames - offset)))
                observed = target.readframes(min(8192, frames - offset))
                if len(expected) != min(8192, frames - offset) * channels * 2 or len(observed) != len(expected):
                    raise HoldoutError('controlled PCM is truncated')
                if operation == 'mute-interval':
                    left, right = max(start, offset), min(end, offset + len(expected) // (channels * 2))
                    if left < right:
                        a, b = (left - offset) * channels * 2, (right - offset) * channels * 2
                        changed |= any(expected[a:b])
                        expected[a:b] = bytes(b - a)
                if observed != expected:
                    raise HoldoutError('controlled PCM differs outside the declared transformation')
            if operation == 'mute-interval' and not changed:
                raise HoldoutError('controlled defect did not change any samples')
        if (audio_identity(reference)['audioSHA256'] != original['audioSHA256']
                or audio_identity(Path(row['path']))['audioSHA256'] != audio['audioSHA256']):
            raise HoldoutError('controlled audio changed during verification')
        scope = 'controlled-signal-defect-detection-only'
    else:
        raise HoldoutError('independent reference evidence kind is unsupported')
    return {'scope': scope, 'sha256': hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()}


def _wilson(successes: int, total: int) -> dict[str, float]:
    if type(total) is not int or type(successes) is not int or total <= 0 or not 0 <= successes <= total:
        raise HoldoutError("confidence interval requires valid integer observation counts")
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / denominator
    return {"estimate": proportion, "lower": max(0.0, centre - radius), "upper": min(1.0, centre + radius)}


def _metrics(
    entries: list[dict[str, Any]],
    analyzer: Callable[[str], dict[str, Any]],
) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    good: list[dict[str, float]] = []
    bad: list[dict[str, float]] = []
    for row in entries:
        result = analyzer(row["path"])
        if "error" in result:
            raise HoldoutError("holdout analysis failed")
        record = prosody_calibration.validated_metrics(result)
        (good if row["label"] == "good" else bad).append(record)
    return good, bad


def validate_profile_binding(
    profile: dict[str, Any],
    calibration: list[dict[str, Any]],
) -> str:
    calibration_digest = prosody_calibration.corpus_digest(calibration)
    if profile.get("calibration_corpus_digest") != calibration_digest:
        raise HoldoutError("profile is not bound to the calibration manifest")
    if profile.get("analyzer_algorithm_version") != prosody_calibration.analyzer_algorithm_version():
        raise HoldoutError("profile analyzer version does not match the current analyzer")
    return calibration_digest


def evaluate(
    calibration_path: Path,
    holdout_path: Path,
    profile_path: Path,
    *,
    root: Path = ROOT,
    analyzer: Callable[[str], dict[str, Any]] = prosody_calibration.analyze,
) -> dict[str, Any]:
    policy = validate_policy(root)
    calibration = prosody_calibration.load_labels(calibration_path)
    holdout = prosody_calibration.load_labels(holdout_path)
    coverage = validate_manifests(calibration, holdout, policy)
    # Check independent labels before launching any acoustic analyzer.
    label_evidence = [validate_label_evidence(row, policy) for row in calibration + holdout]
    profile = load_profile(profile_path)
    calibration_digest = validate_profile_binding(profile, calibration)
    good, bad = _metrics(holdout, analyzer)
    rates = prosody_calibration.evaluate_profile(profile, good, bad)
    false_positive_count = round(rates["false_positive_rate"] * len(good))
    true_positive_count = round(rates["true_positive_rate"] * len(bad))
    fpr = _wilson(false_positive_count, len(good))
    tpr = _wilson(true_positive_count, len(bad))
    failures: list[str] = []
    if fpr["upper"] > policy["maximumFalsePositiveRateUpperBound"]:
        failures.append("false-positive-upper-bound")
    if tpr["lower"] < policy["minimumTruePositiveRateLowerBound"]:
        failures.append("true-positive-lower-bound")
    return {
        "schemaVersion": 1,
        "status": "PASS" if not failures else "FAIL",
        "checkedAtUTC": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "analyzerAlgorithmVersion": profile["analyzer_algorithm_version"],
        "calibrationCorpusDigest": calibration_digest,
        "holdoutCorpusDigest": prosody_calibration.corpus_digest(holdout),
        "profileDigest": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        "policySHA256": hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest(),
        "annotationEvidenceSHA256": hashlib.sha256(json.dumps(label_evidence, sort_keys=True).encode()).hexdigest(),
        "reviewAuthority": policy['reviewAuthority'],
        "qualificationScopes": sorted({entry['scope'] for entry in label_evidence}),
        "validationSourceSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "inventorySourceSHA256": hashlib.sha256(Path(__file__).with_name('prosody_corpus_inventory.py').read_bytes()).hexdigest(),
        "coverage": coverage,
        "falsePositiveRate95CI": fpr,
        "truePositiveRate95CI": tpr,
        "qualificationFailures": failures,
        "promotionAuthority": not failures and all(entry['scope'] != 'controlled-signal-defect-detection-only' for entry in label_evidence),
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _new_private_output(path: Path) -> Path:
    path = path.resolve()
    if path.exists():
        raise HoldoutError("preparation output already exists; preserve the earlier artifact")
    if path.is_relative_to(ROOT):
        ignored = subprocess.run(["git", "check-ignore", "-q", "--", str(path)], cwd=ROOT, check=False)
        if ignored.returncode != 0:
            raise HoldoutError("calibration artifacts inside the repository must be git-ignored")
    return path


def prepare_calibration(inventory: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    """Prepare blind, byte-bound labelling inventory; never open or infer labels.

Input is private/local. Output has anonymous group tokens and audio digests only.
Splits must be declared by the operator before fitting; this is not a selector.
An empty inventory emits the existing protocol and honest data dependencies.
"""
    rows = []
    seen = set()
    source_groups = set()
    groups = {split: {field: set() for field in (*policy['groupIsolation'], 'sourceGroup')}
              for split in ('calibration', 'holdout')}
    for item in inventory:
        if item.get('split') not in groups:
            raise HoldoutError('preparation requires an explicit calibration/holdout split')
        allowed = {'path', 'split', 'sourceGroup', 'exposure', *METADATA_FIELDS} - {'defectSeverity'}
        if set(item) - allowed:
            raise HoldoutError('blind preparation must not receive requested or scored labels')
        if item.get('exposure') not in ('previously-examined', 'untouched'):
            raise HoldoutError('preparation requires explicitly attested exposure history')
        if item['split'] == 'holdout' and item['exposure'] != 'untouched':
            raise HoldoutError('previously examined recordings cannot enter an untouched holdout')
        source_group = _safe_token(item.get('sourceGroup'), 'sourceGroup')
        if item['split'] == 'holdout' and source_group in source_groups:
            raise HoldoutError('holdout requires one primary observation per sourceGroup')
        if item['split'] == 'holdout':
            source_groups.add(source_group)
        audio_digest = _clip_digest(item)
        identity = audio_identity(Path(item['path']))
        if identity['audioSHA256'] != audio_digest:
            raise HoldoutError('audio changed during preparation')
        if identity['pcmSHA256'] in seen:
            raise HoldoutError('preparation reuses audio bytes or PCM')
        seen.add(identity['pcmSHA256'])
        row = {**identity, 'split': item['split'], 'label': None,
               'sourceGroup': source_group, 'exposure': item['exposure']}
        for field in METADATA_FIELDS:
            if field == 'defectSeverity':
                continue  # Independent annotation, never a requested-label feature.
            row[field] = _safe_token(item.get(field), field)
        for field in groups[item['split']]:
            groups[item['split']][field].add(row[field])
        rows.append(row)
    for field in groups['calibration']:
        if groups['calibration'][field] & groups['holdout'][field]:
            raise HoldoutError(f'preparation leaks {field}')
    counts = {split: sum(row['split'] == split for row in rows) for split in groups}
    minimum = {'calibration': policy['minimumCalibrationClips'],
               'holdout': policy['minimumHoldoutGoodClips']+policy['minimumHoldoutBadClips']}
    return {
        'schemaVersion': 1, 'kind': 'prosody-calibration-preparation',
        'status': 'NEEDS_REFERENCE_EVIDENCE', 'promotionAuthority': False,
        'humanListeningRequired': False,
        'policy': policy, 'policySHA256': hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest(),
        'sourceSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'inventorySourceSHA256': hashlib.sha256(Path(__file__).with_name('prosody_corpus_inventory.py').read_bytes()).hexdigest(),
        'counts': counts, 'additionalAudioMinimum': {s: max(0, minimum[s]-counts[s]) for s in groups},
        'items': rows,
        'referenceEvidenceOptions': policy['reviewAuthority']['acceptedSources'],
        'requiredAnnotations': [],
        'annotationTemplate': {
            'protocolID': policy['annotationProtocol']['id'], 'source': 'independent-human',
            'audioSHA256': None, 'reviewerID': None, 'fluentLanguages': [],
            'decision': None, 'confidence': None,
            'defects': [{'type': None, 'startSeconds': None, 'endSeconds': None, 'severity': None}],
            'status': 'UNANSWERED',
        },
        'samplingFeasibility': {
            'zeroErrorsAtGoodFloor95Upper': _wilson(0, policy['minimumHoldoutGoodClips'])['upper'],
            'perfectDetectionAtBadFloor95Lower': _wilson(policy['minimumHoldoutBadClips'], policy['minimumHoldoutBadClips'])['lower'],
            'countsAreStartingFloorsNotPowerGuarantees': True,
        },
        'nextActions': ['complete-group-and-language-coverage', 'bind-independent-reference-evidence',
                        'fit-only-calibration', 'freeze-profile-before-opening-holdout',
                        'evaluate-once-with-existing-prosody-holdout-validator'],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate-contract", "inventory", "prepare", "evaluate"))
    parser.add_argument("--audio-root", type=Path, action="append", help="explicit retained-audio directory; never a holdout selector")
    parser.add_argument("--private-map", type=Path, help="new untracked local path map, separate from the sanitized inventory")
    parser.add_argument("--max-files", type=int, default=5000)
    parser.add_argument("--inventory", type=Path, help="private JSON object with predeclared unlabelled items")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--calibration-labels", type=Path)
    parser.add_argument("--holdout-labels", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.command == "inventory":
            if not arguments.audio_root or arguments.output is None or arguments.private_map is None:
                raise HoldoutError('inventory requires audio roots, output and private map')
            output, private_map = map(_new_private_output, (arguments.output, arguments.private_map))
            if output == private_map:
                raise HoldoutError('public and private outputs must be separate')
            result, paths = inventory_audio(arguments.audio_root, max_files=arguments.max_files)
            _atomic_json(private_map, paths)
            _atomic_json(output, result)
            print(json.dumps({'status': result['status'], 'counts': result['counts']}))
            return 0 if result['status'] == 'INVENTORIED' else 2
        if arguments.command == "validate-contract":
            policy = validate_policy(arguments.root.resolve())
            print(f"Prosody holdout contract: PASS ({policy['minimumHoldoutGoodClips']} good + {policy['minimumHoldoutBadClips']} bad)")
            return 0
        if arguments.command == "prepare":
            if arguments.output is None:
                raise HoldoutError('prepare requires --output')
            items = _load_object(arguments.inventory).get('items') if arguments.inventory else []
            if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
                raise HoldoutError('inventory items must be an array of objects')
            result = prepare_calibration(items, validate_policy(arguments.root.resolve()))
            _atomic_json(_new_private_output(arguments.output), result)
            print(json.dumps({'status': result['status'], 'counts': result['counts']}))
            return 0
        if not all((arguments.calibration_labels, arguments.holdout_labels, arguments.profile, arguments.output)):
            raise HoldoutError("evaluate requires calibration, holdout, profile, and output paths")
        result = evaluate(
            arguments.calibration_labels.resolve(),
            arguments.holdout_labels.resolve(),
            arguments.profile.resolve(),
            root=arguments.root.resolve(),
        )
        _atomic_json(arguments.output.resolve(), result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    except (OSError, ValueError) as error:
        print(f"Prosody holdout validation: FAIL\n{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
