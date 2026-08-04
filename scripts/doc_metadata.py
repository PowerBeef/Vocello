#!/usr/bin/env python3
"""Per-file documentation metadata: freshness, pinning, and a generated index.

PROTOTYPE. Applied to three documents that exercise every mode; the remaining
docs are unannotated and are reported as coverage gaps rather than failures, so
this can land without a 60-file sweep.

Why three layers instead of one
-------------------------------
On 2026-08-01 the commit that retired the `subtle` intensity tier edited both
`EmotionPreset.swift` and `qwen3-tts-guide.md`. The guide still shipped the
sentence "10 x 3 presets". Any freshness check built on "did the doc change when
its source changed" would have passed it, because the doc *did* change. That is
the whole reason this file has a fact scanner and not just a source binding:

* ``sourceOfTruth`` + git      catches "the source moved and nobody touched the doc"
* derived facts + deny scan    catches "somebody touched the doc and missed a spot"
* generated index              catches "the map of what exists drifted from reality"

Neither of the first two subsumes the other, and the second is the one that
would have caught the real defect.

Modes, driven entirely by ``status``
------------------------------------
``active``      tracks the tree. Freshness enforced against ``sourceOfTruth``;
                scanned for contradictions with derived facts.
``historical``  a pinned snapshot. Freshness is meaningless (its sources have of
                course moved on) and fact scanning is *wrong*, because recording
                what was true at capture is the document's entire purpose. The
                body digest is enforced instead, so the corpus cannot be
                modified by accident.
``superseded``  same protection as historical, plus a required ``supersededBy``
                pointer so a reader knows before the first paragraph that
                current truth lives elsewhere.

The digest covers the body only, never the frontmatter. Metadata can be added or
corrected on a pinned document without disturbing the seal on its content.

Usage:
    python3 scripts/doc_metadata.py derive-facts [--check]
    python3 scripts/doc_metadata.py rebuild-index [--check]
    python3 scripts/doc_metadata.py validate [--strict]
    python3 scripts/doc_metadata.py scan-text FILE   # fact scan arbitrary content
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FACTS_PATH = "config/derived-doc-facts.json"
INDEX_PATH = "docs/INDEX.json"
DOC_ROOTS = ("docs", ".claude/rules")
ROOT_SCAN_FILES = ("CLAUDE.md", "README.md")
STATUSES = ("active", "historical", "superseded")
PINNED = ("historical", "superseded")
OWNERS = ("backend-mlx", "release-qa", "ios", "macos", "backend-and-platform")


# --------------------------------------------------------------------------
# frontmatter
# --------------------------------------------------------------------------

def split_frontmatter(text: str) -> tuple[dict | None, str]:
    """Return (metadata, body). Metadata is None when the file has no block.

    A deliberately small YAML subset -- scalars and `- ` string lists -- so the
    gate stays dependency-free and cannot be broken by a PyYAML version bump.
    """
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("frontmatter opened with --- but never closed")
    block, body = text[4:end], text[end + 5:]

    meta: dict = {}
    key = None
    for raw in block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith("  - ") or raw.startswith("- "):
            if key is None:
                raise ValueError("list item before any key")
            meta.setdefault(key, [])
            if not isinstance(meta[key], list):
                raise ValueError(f"{key} has both a scalar and list items")
            meta[key].append(raw.split("- ", 1)[1].strip().strip('"\''))
            continue
        if ":" not in raw:
            raise ValueError(f"unparsable frontmatter line: {raw!r}")
        key, _, value = raw.partition(":")
        key, value = key.strip(), value.strip().strip('"\'')
        meta[key] = value if value else []
    return meta, body


def body_digest(body: str) -> str:
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


# Generated documents are output, not authored prose. They carry no frontmatter
# by design, and counting them as "not yet annotated" would leave the rollout
# coverage number permanently short of complete.
GENERATED_DOCS = frozenset({
    "docs/INDEX.md",
    "docs/ROADMAP.md",
    "docs/project-health.md",
})


def iter_docs(root: pathlib.Path):
    for doc_root in DOC_ROOTS:
        base = root / doc_root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.md")):
            if path.relative_to(root).as_posix() in GENERATED_DOCS:
                continue
            yield path


# --------------------------------------------------------------------------
# derived facts
# --------------------------------------------------------------------------

def derive_facts(root: pathlib.Path) -> dict:
    """Extract machine-known truths from code and contracts.

    Derived, never hand-maintained: a hand-typed facts file is just one more
    document that goes stale, which is the failure being fixed.
    """
    preset_src = root / "Sources/QwenVoiceCore/EmotionPreset.swift"
    swift = preset_src.read_text(encoding="utf-8")
    all_block = swift.split("public static let all: [EmotionPreset] = [", 1)
    if len(all_block) != 2:
        raise ValueError("EmotionPreset.all not found")
    presets = len(re.findall(r'id:\s*"[a-z]+"', all_block[1]))
    enum_block = re.search(
        r"public enum EmotionIntensity[^{]*\{(.*?)\n\}", swift, re.S
    )
    if not enum_block:
        raise ValueError("EmotionIntensity enum not found")
    tiers = len(re.findall(r"(?m)^\s*case\s+\w+\s*=", enum_block.group(1)))

    contract = json.loads(
        (root / "Sources/Resources/qwenvoice_contract.json").read_text(encoding="utf-8")
    )
    speakers = len(contract.get("speakerMetadata") or {})

    # project.yml is the version authority; public-product-facts.json is checked
    # against it elsewhere, so deriving from the manifest skips the intermediary.
    manifest = (root / "project.yml").read_text(encoding="utf-8")
    version_match = re.search(r'MARKETING_VERSION:\s*"([0-9]+\.[0-9]+\.[0-9]+)"', manifest)
    if not version_match:
        raise ValueError("MARKETING_VERSION not found in project.yml")
    version = version_match.group(1)

    # The canonical benchmark machine is flagged in the profile registry itself,
    # so the chip name is a derived fact rather than a policy restatement.
    profiles = json.loads(
        (root / "benchmarks/hardware-profiles.json").read_text(encoding="utf-8")
    )["profiles"]
    canonical_macs = [
        p for p in profiles if p.get("canonical") and p.get("platform") == "macos"
    ]
    if len(canonical_macs) != 1:
        raise ValueError(
            f"expected exactly one canonical macOS hardware profile, found {len(canonical_macs)}"
        )
    canonical_chip = canonical_macs[0]["chip"]

    if not (presets and tiers and speakers and version and canonical_chip):
        raise ValueError("a derived fact came out empty; refusing to write")

    return {
        "schemaVersion": 1,
        "generated": "python3 scripts/doc_metadata.py derive-facts",
        "boundary": (
            "Internal engineering facts, DERIVED from code and contracts and regenerated "
            "on demand. Never hand-edit. Distinct from config/public-product-facts.json, "
            "which is hand-curated public product policy (release version, minimum device, "
            "canonical benchmark hardware) validated against project.yml and README. "
            "Different provenance and different audience: if a value can be read out of "
            "the tree it belongs here; if it is a decision about what we publish it "
            "belongs there."
        ),
        "facts": {
            "deliveryPresetCount": {
                "value": presets,
                "source": "Sources/QwenVoiceCore/EmotionPreset.swift",
            },
            "deliveryIntensityTiers": {
                "value": tiers,
                "source": "Sources/QwenVoiceCore/EmotionPreset.swift",
            },
            "qwenSpeakerCount": {
                "value": speakers,
                "source": "Sources/Resources/qwenvoice_contract.json",
            },
            "stableMacReleaseVersion": {
                "value": version,
                "source": "project.yml",
            },
            "canonicalMacBenchmarkChip": {
                "value": canonical_chip,
                "source": "benchmarks/hardware-profiles.json",
            },
        },
    }


_WORD_FORMS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
    7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
}


def _number_forms(value: int) -> str:
    """Alternation matching a count written as a digit or as a word."""
    forms = [str(value)]
    if value in _WORD_FORMS:
        forms.append(_WORD_FORMS[value])
    return "(?:" + "|".join(forms) + ")"


def deny_patterns(facts: dict) -> list[tuple[str, str, re.Pattern]]:
    """Contradiction patterns, generated from the derived values.

    Parameterised by the fact so the patterns cannot themselves go stale: if the
    tier count ever becomes three, the "10 x N where N is not 3" pattern follows
    automatically.
    """
    presets = facts["deliveryPresetCount"]["value"]
    tiers = facts["deliveryIntensityTiers"]["value"]
    speakers = facts["qwenSpeakerCount"]["value"]
    version = facts["stableMacReleaseVersion"]["value"]
    chip = facts["canonicalMacBenchmarkChip"]["value"]
    out = [
        (
            "deliveryIntensityTiers",
            f"a preset x tier product whose tier count is not {tiers}",
            re.compile(rf"\b{presets}\s*[x×]\s*(?!{tiers}\b)\d+\b"),
        ),
        (
            "deliveryIntensityTiers",
            f"a spelled-out intensity-tier count other than {tiers}",
            re.compile(
                # Precision over recall, deliberately. Three constraints, each
                # added to kill a real false positive seen on the corpus:
                #  * both spellings of the correct count are excluded, so
                #    "2 intensities" and "two intensities" both pass;
                #  * the noun must be plural, because "one intensity tier and
                #    not the other" is selection prose, not a count claim;
                #  * whitespace excludes newlines, so a match cannot span a
                #    line break and join two unrelated clauses.
                rf"\b(?!{_number_forms(tiers)}\b)"
                r"(?:two|three|four|five|\d+)[^\S\n]+"
                r"intensit(?:y[^\S\n]+tiers|ies)\b",
                re.I,
            ),
        ),
        (
            "deliveryPresetCount",
            f"a delivery/emotion preset count other than {presets}",
            re.compile(
                # "styles" and spelled-out numbers included after README shipped
                # "ten delivery styles" for a day past the roster cut without
                # tripping the digits-plus-"presets" pattern (2026-08-04).
                rf"\b(?!{_number_forms(presets)}\b)"
                r"(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)"
                r"\s+(?:delivery|emotion)\s+(?:presets?|styles?)\b",
                re.I,
            ),
        ),
        (
            "qwenSpeakerCount",
            f"a built-in speaker count other than {speakers}",
            re.compile(
                rf"\b(?!{speakers}\b)\d+\s+(?:built-in|preset|premium)\s+"
                r"(?:speakers?|timbres?|voices?)\b",
                re.I,
            ),
        ),
        (
            "stableMacReleaseVersion",
            f"a current-release claim naming a version other than {version}",
            # Only the *claim* forms. Version numbers appear legitimately all over
            # release notes and history; what must not drift is the statement about
            # which release is current.
            re.compile(
                r"(?:macOS\s+\*{0,2}(?!" + re.escape(version) + r"\b)\d+\.\d+\.\d+\*{0,2}"
                r"\s+(?:is\s+)?(?:the\s+)?(?:current|latest|stable)"
                r"|\*{0,2}(?!" + re.escape(version) + r"\b)\d+\.\d+\.\d+\*{0,2}"
                r"\s+is\s+(?:the\s+)?current\s+(?:macOS\s+)?release)",
                re.I,
            ),
        ),
        (
            "canonicalMacBenchmarkChip",
            f"canonical benchmark hardware other than {chip}",
            # The standing risk is public copy citing the wrong Mac. The chip is
            # derived from the profile flagged canonical in the registry.
            re.compile(
                r"Mac\s+mini\s+\(?(?!"
                + re.escape(chip.replace("Apple ", "")) + r"\b)M\d\b"
                r"|canonical[^.\n]{0,40}\bMac\s+mini\s+\(?(?!"
                + re.escape(chip.replace("Apple ", "")) + r"\b)M\d\b",
                re.I,
            ),
        ),
    ]
    return out


def scan_text(text: str, facts: dict) -> list[dict]:
    """Every contradiction between the text and a derived fact."""
    findings = []
    for fact, description, pattern in deny_patterns(facts):
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            findings.append({
                "fact": fact,
                "line": line,
                "matched": match.group(0),
                "detail": description,
            })
    return findings


# --------------------------------------------------------------------------
# freshness
# --------------------------------------------------------------------------

def last_commit_epoch(root: pathlib.Path, relative: str) -> int | None:
    result = subprocess.run(
        ["git", "-C", str(root), "log", "-1", "--format=%ct", "--", relative],
        capture_output=True, text=True, check=False,
    )
    value = result.stdout.strip()
    return int(value) if value.isdigit() else None


def freshness_findings(
    root: pathlib.Path, relative: str, meta: dict
) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for one active document.

    Severity is calibrated to precision. A missing or wrong ``sourceOfTruth``
    path is unambiguous, so it fails. Drift is a *suspicion*: any edit to a
    declared source trips it, including ones that could not possibly affect the
    prose, so it warns. An error that fires spuriously teaches people to bypass
    the gate, which costs more than the drift it catches -- the precise check
    against derived facts is what blocks.
    """
    sources = meta.get("sourceOfTruth") or []
    if not sources:
        return ([f"{relative}: status active requires sourceOfTruth"], [])
    errors, warnings = [], []
    doc_time = last_commit_epoch(root, relative)
    for source in sources:
        if not (root / source).exists():
            errors.append(f"{relative}: sourceOfTruth path does not exist: {source}")
            continue
        if doc_time is None:
            continue  # never committed; nothing to compare against yet
        source_time = last_commit_epoch(root, source)
        if source_time and source_time > doc_time:
            warnings.append(
                f"{relative}: {source} changed after this doc was last updated; "
                "re-review, or correct sourceOfTruth if the binding is wrong"
            )
    return (errors, warnings)


# --------------------------------------------------------------------------
# validate / index
# --------------------------------------------------------------------------

def collect(root: pathlib.Path) -> tuple[list[dict], list[str]]:
    """Every annotated doc, plus paths still lacking frontmatter."""
    entries, unannotated = [], []
    for path in iter_docs(root):
        relative = path.relative_to(root).as_posix()
        try:
            meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
        except ValueError as error:
            entries.append({"path": relative, "error": str(error)})
            continue
        if meta is None:
            unannotated.append(relative)
            continue
        entries.append({"path": relative, "meta": meta, "body": body})
    return entries, unannotated


def validate(root: pathlib.Path, strict: bool = False) -> dict:
    facts_file = root / FACTS_PATH
    if not facts_file.exists():
        return {"errors": [f"missing {FACTS_PATH}; run derive-facts"], "ok": False}
    stored = json.loads(facts_file.read_text(encoding="utf-8"))
    if stored != derive_facts(root):
        return {
            "errors": [f"{FACTS_PATH} is stale; run: python3 scripts/doc_metadata.py derive-facts"],
            "ok": False,
        }
    facts = stored["facts"]

    errors: list[str] = []
    warnings: list[str] = []
    entries, unannotated = collect(root)

    for entry in entries:
        relative = entry["path"]
        if "error" in entry:
            errors.append(f"{relative}: {entry['error']}")
            continue
        meta, body = entry["meta"], entry["body"]

        status = meta.get("status")
        if status not in STATUSES:
            errors.append(f"{relative}: status must be one of {STATUSES}, got {status!r}")
            continue
        if meta.get("owner") not in OWNERS:
            errors.append(f"{relative}: owner must be one of {OWNERS}")
        if not meta.get("summary"):
            errors.append(f"{relative}: summary is required (it is the index entry)")

        if status in PINNED:
            digest = meta.get("contentDigest")
            actual = body_digest(body)
            if not digest:
                errors.append(f"{relative}: {status} documents require contentDigest")
            elif digest != actual:
                errors.append(
                    f"{relative}: body changed but contentDigest was not updated. "
                    "A pinned document is a historical record -- if the edit is "
                    "deliberate, re-pin it explicitly; if it was accidental, revert it. "
                    f"expected {digest}, got {actual}"
                )
            if status == "superseded":
                target = meta.get("supersededBy")
                if not target:
                    errors.append(f"{relative}: superseded requires supersededBy")
                elif not (root / target).exists():
                    errors.append(f"{relative}: supersededBy path missing: {target}")
        else:
            fresh_errors, fresh_warnings = freshness_findings(root, relative, meta)
            errors.extend(fresh_errors)
            warnings.extend(fresh_warnings)
            for finding in scan_text(body, facts):
                errors.append(
                    f"{relative}:{finding['line']}: contradicts derived fact "
                    f"{finding['fact']} -- {finding['detail']} (matched {finding['matched']!r})"
                )

    # The two root documents are fact-scanned but never annotated. CLAUDE.md is
    # the file that mandates fact-checking and was, until 2026-08-02, the one
    # document exempt from it: a wrong preset count there passed every gate. They
    # are scan-only rather than annotated because CLAUDE.md describes the whole
    # repository, so a sourceOfTruth binding would be either uselessly broad or
    # arbitrarily narrow. Contradictions here FAIL -- these are the two documents
    # most read and most copied from.
    for relative in ROOT_SCAN_FILES:
        target = root / relative
        if not target.exists():
            continue
        for finding in scan_text(target.read_text(encoding="utf-8"), facts):
            errors.append(
                f"{relative}:{finding['line']}: contradicts derived fact "
                f"{finding['fact']} -- {finding['detail']} (matched {finding['matched']!r})"
            )

    # Unannotated docs are scanned for contradictions too, but reported rather
    # than failed, so the prototype lands without a 60-file sweep.
    pinned_prefixes = ("docs/research/", "docs/audits/", "docs/releases/")
    for relative in unannotated:
        if relative.startswith(pinned_prefixes):
            continue
        text = (root / relative).read_text(encoding="utf-8")
        for finding in scan_text(text, facts):
            message = (
                f"{relative}:{finding['line']}: contradicts derived fact "
                f"{finding['fact']} (matched {finding['matched']!r})"
            )
            (errors if strict else warnings).append(message)

    return {
        "annotated": len([e for e in entries if "meta" in e]),
        "unannotated": len(unannotated),
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }


def render_index(root: pathlib.Path) -> dict:
    entries, unannotated = collect(root)
    documents = []
    for entry in sorted(entries, key=lambda e: e["path"]):
        if "meta" not in entry:
            continue
        meta = entry["meta"]
        record = {
            "path": entry["path"],
            "status": meta.get("status"),
            "owner": meta.get("owner"),
            "summary": meta.get("summary"),
        }
        for optional in ("sourceOfTruth", "supersededBy", "contentDigest", "appliesTo"):
            if meta.get(optional):
                record[optional] = meta[optional]
        documents.append(record)
    return {
        "schemaVersion": 1,
        "generated": "python3 scripts/doc_metadata.py rebuild-index",
        "note": "Machine-readable documentation map. Query this instead of globbing docs/.",
        "annotatedDocuments": len(documents),
        "unannotatedDocuments": len(unannotated),
        "documents": documents,
    }


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command",
                        choices=["derive-facts", "rebuild-index", "validate", "scan-text"])
    parser.add_argument("file", nargs="?", help="file to scan (scan-text only)")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--check", action="store_true", help="verify freshness, do not write")
    parser.add_argument("--strict", action="store_true",
                        help="fail on contradictions in unannotated docs too")
    args = parser.parse_args(argv)
    root = pathlib.Path(args.root).resolve()

    if args.command == "derive-facts":
        payload = derive_facts(root)
        target = root / FACTS_PATH
        if args.check:
            current = json.loads(target.read_text(encoding="utf-8")) if target.exists() else None
            if current != payload:
                print(f"error: {FACTS_PATH} is stale", file=sys.stderr)
                return 1
            print(f"Derived doc facts: fresh ({len(payload['facts'])} facts)")
            return 0
        write_json(target, payload)
        print(f"Wrote {FACTS_PATH} ({len(payload['facts'])} facts)")
        return 0

    if args.command == "rebuild-index":
        payload = render_index(root)
        target = root / INDEX_PATH
        if args.check:
            current = json.loads(target.read_text(encoding="utf-8")) if target.exists() else None
            if current != payload:
                print(f"error: {INDEX_PATH} is stale", file=sys.stderr)
                return 1
            print(f"Documentation index: fresh ({payload['annotatedDocuments']} annotated)")
            return 0
        write_json(target, payload)
        print(f"Wrote {INDEX_PATH} ({payload['annotatedDocuments']} annotated, "
              f"{payload['unannotatedDocuments']} not yet)")
        return 0

    if args.command == "scan-text":
        if not args.file:
            parser.error("scan-text requires a file")
        facts = json.loads((root / FACTS_PATH).read_text(encoding="utf-8"))["facts"]
        findings = scan_text(pathlib.Path(args.file).read_text(encoding="utf-8"), facts)
        for finding in findings:
            print(f"line {finding['line']}: {finding['fact']} -- "
                  f"{finding['detail']} (matched {finding['matched']!r})")
        print(f"{len(findings)} contradiction(s)")
        return 1 if findings else 0

    report = validate(root, strict=args.strict)
    for warning in report.get("warnings", []):
        print(f"doc-metadata warning: {warning}", file=sys.stderr)
    for error in report["errors"]:
        print(f"doc-metadata error: {error}", file=sys.stderr)
    if not report["ok"]:
        return 1
    print(f"Documentation metadata: PASS ({report['annotated']} annotated, "
          f"{report['unannotated']} unannotated, {len(report.get('warnings', []))} warning(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
