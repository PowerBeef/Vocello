#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("quality_promotion", SCRIPTS / "quality_promotion.py")
assert SPEC and SPEC.loader
PROMOTION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROMOTION
SPEC.loader.exec_module(PROMOTION)


CANONICAL_RECORD = (
    REPO_ROOT
    / "benchmarks/runs/ui-generation/macos-xcui-benchmark-20260801-182943-b0b5a448.json"
)


class QualityPromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir()
        for name in ("quality-promotion-contract.json",):
            shutil.copy2(REPO_ROOT / "config" / name, self.root / "config" / name)
        model_path = self.root / PROMOTION.MODEL_CONTRACT_PATH
        model_path.parent.mkdir(parents=True)
        shutil.copy2(REPO_ROOT / PROMOTION.MODEL_CONTRACT_PATH, model_path)
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Fixture")
        (self.root / "README.md").write_text("base\n", encoding="utf-8")
        # The candidate's public facts name the previous public release, which is the base.
        self.write_json(self.root / "config/public-product-facts.json",
                        {"stableMacRelease": {"version": "2.3.0", "tag": "v2.3.0"}})
        self.git("add", "README.md", "config/public-product-facts.json")
        self.git("commit", "-qm", "base")
        self.git("tag", "v2.3.0")
        self.base = self.git("rev-parse", "HEAD")
        (self.root / "README.md").write_text("candidate\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-qm", "candidate")
        self.commit = self.git("rev-parse", "HEAD")
        self.git("tag", "v2.4.0")
        self.release_path = self.root / "release-evidence.json"
        self.release = {
            "schemaVersion": 2,
            "release": {
                "tag": "v2.4.0",
                "commitSHA": self.commit,
                "marketingVersion": "2.4.0",
                "buildNumber": "23",
                "platform": "macos",
            },
            "sourceIdentity": {
                "gitCommit": self.commit,
                "treeDirty": False,
                "identityDigest": "a" * 64,
            },
        }
        self.write_json(self.release_path, self.release)
        self.record_path = self.root / "record.json"
        self.record = json.loads(CANONICAL_RECORD.read_text(encoding="utf-8"))
        self.rebind_record()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments], cwd=self.root, text=True, capture_output=True, check=True
        )
        return completed.stdout.strip()

    @staticmethod
    def write_json(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def rebind_record(self, *, age: timedelta = timedelta(minutes=1)) -> None:
        finished = datetime.now(timezone.utc).replace(microsecond=0) - age
        duration = float(self.record["run"]["durationSeconds"])
        self.record["run"]["finishedAt"] = finished.isoformat().replace("+00:00", "Z")
        self.record["run"]["startedAt"] = (finished - timedelta(seconds=duration)).isoformat().replace("+00:00", "Z")
        # Rebinding dates the record after the 2026-09-12 RTF cutover, which
        # requires the standard-RTF declaration on every record.
        self.record["run"]["rtfDefinition"] = "wall/audio"
        self.record["source"].update({
            "commit": self.commit,
            "dirty": False,
            "changedPaths": [],
            "fingerprintsMatch": True,
        })
        self.record["toolchain"]["appVersion"] = "2.4.0"
        self.record["toolchain"]["appBuild"] = "23"
        self.record["comparison"]["key"] = PROMOTION.benchmark_history.comparison_key(self.record)
        self.record["digest"] = PROMOTION.benchmark_history.record_digest(self.record)
        self.write_json(self.record_path, self.record)

    def create_args(self, **overrides: object) -> argparse.Namespace:
        values: dict[str, object] = {
            "root": self.root,
            "platform": "macos",
            "tag": "v2.4.0",
            "base": self.base,
            "release_evidence": self.release_path,
            "record": [f"macos-ui-benchmark={self.record_path}"],
            "receipt": [],
            "accept_warning": ["memory.pressure.soft_trim"],
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def validation_args(self, manifest: Path) -> argparse.Namespace:
        return argparse.Namespace(
            root=self.root,
            platform="macos",
            tag="v2.4.0",
            release_evidence=self.release_path,
            manifest=manifest,
        )

    def test_exact_source_manifest_round_trip(self) -> None:
        manifest = PROMOTION.create(self.create_args())
        path = self.root / "quality-promotion.json"
        self.write_json(path, manifest)
        validated = PROMOTION.validate_manifest(self.validation_args(path))
        self.assertEqual(validated["sourceCommit"], self.commit)
        self.assertEqual(validated["requiredEvidence"], ["macos-ui-benchmark"])
        self.assertEqual(validated["capabilityCoverage"], {})
        self.assertEqual(validated["unsupportedDimensions"], [])
        self.assertEqual(
            validated["lanes"]["macos-ui-benchmark"]["hardwareProfileID"],
            "mac-mini-m2-8gb",
        )

    def test_the_base_is_the_previous_public_release_not_a_nearer_commit(self) -> None:
        # A nearer base shrinks the evidence a candidate must prove to the platform minimum.
        nearer = self.commit
        (self.root / "README.md").write_text("candidate, again\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-qm", "candidate, again")
        self.commit = self.git("rev-parse", "HEAD")
        with self.assertRaisesRegex(PROMOTION.PromotionError, "previous public macOS release v2.3.0"):
            PROMOTION.require_public_base(self.root, "macos", nearer, self.commit)
        PROMOTION.require_public_base(self.root, "macos", self.base, self.commit)
        # A manifest re-signed onto the nearer base is refused at validation too.
        self.git("tag", "-f", "v2.4.0")
        self.release["release"]["commitSHA"] = self.commit
        self.release["sourceIdentity"]["gitCommit"] = self.commit
        self.write_json(self.release_path, self.release)
        self.rebind_record()
        manifest = PROMOTION.create(self.create_args())
        manifest["baseCommit"] = nearer
        manifest["digest"] = PROMOTION.digest_value({key: value for key, value in manifest.items() if key != "digest"})
        path = self.root / "quality-promotion.json"
        self.write_json(path, manifest)
        with self.assertRaisesRegex(PROMOTION.PromotionError, "previous public macOS release v2.3.0"):
            PROMOTION.validate_manifest(self.validation_args(path))

    def test_every_product_file_routes_to_a_class_or_is_listed_unrouted(self) -> None:
        classes = [{"id": "platform-ui", "include": ["Sources/Views/**"]}]
        for name in ("Sources/Views/Studio.swift", "Sources/Info.plist"):
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text("x\n", encoding="utf-8")
        self.git("add", "Sources")
        listed = [path for path in self.git("ls-files", "--", *PROMOTION.ROUTED_ROOTS).splitlines()
                  if not path.startswith("Sources/Views/")]
        unrouted = [{"paths": listed, "reason": "build manifest and fixture contract"}]
        PROMOTION.validate_routing_coverage(classes, unrouted, self.root)
        (self.root / "Sources/Services").mkdir(parents=True)
        (self.root / "Sources/Services/NewService.swift").write_text("x\n", encoding="utf-8")
        self.git("add", "Sources/Services/NewService.swift")
        with self.assertRaisesRegex(PROMOTION.PromotionError, "Sources/Services/NewService.swift"):
            PROMOTION.validate_routing_coverage(classes, unrouted, self.root)
        stale = unrouted + [{"paths": ["Sources/Gone.swift"], "reason": "removed"}]
        classes.append({"id": "app", "include": ["Sources/Services/**"]})
        with self.assertRaisesRegex(PROMOTION.PromotionError, "match no tracked file: Sources/Gone.swift"):
            PROMOTION.validate_routing_coverage(classes, stale, self.root)
        PROMOTION.validate_routing_coverage(classes, unrouted, self.root)

    def test_facts_that_name_no_previous_release_fail_closed(self) -> None:
        self.write_json(self.root / "config/public-product-facts.json", {"stableMacRelease": {}})
        self.git("add", "config/public-product-facts.json")
        self.git("commit", "-qm", "facts without a release")
        with self.assertRaisesRegex(PROMOTION.PromotionError, "names no previous public macOS release"):
            PROMOTION.previous_public_release(self.root, self.git("rev-parse", "HEAD"))

    def flip_facts_to(self, tag: str) -> str:
        self.write_json(self.root / "config/public-product-facts.json",
                        {"stableMacRelease": {"version": tag.removeprefix("v"), "tag": tag}})
        self.git("add", "config/public-product-facts.json")
        self.git("commit", "-qm", f"facts name {tag}")
        return self.git("rev-parse", "HEAD")

    def test_facts_flipped_before_the_tag_still_name_the_release_before_it(self) -> None:
        # The flip lands before the tag, so the candidate's facts name the candidate itself.
        flipped = self.flip_facts_to("v2.4.0")
        (self.root / "README.md").write_text("candidate, after the flip\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-qm", "candidate, after the flip")
        candidate = self.git("rev-parse", "HEAD")
        self.git("tag", "-f", "v2.4.0")
        self.assertEqual(PROMOTION.previous_public_release(self.root, candidate, "v2.4.0"), ("v2.3.0", self.base))
        PROMOTION.require_public_base(self.root, "macos", self.base, candidate, "v2.4.0")
        # The flip commit is no base: it is nearer than the release the facts named before it.
        with self.assertRaisesRegex(PROMOTION.PromotionError, "previous public macOS release v2.3.0"):
            PROMOTION.require_public_base(self.root, "macos", flipped, candidate, "v2.4.0")
        # Without the candidate's tag the facts are read as written, as before.
        self.assertEqual(PROMOTION.previous_public_release(self.root, candidate)[0], "v2.4.0")

    def test_flipped_facts_whose_history_names_no_earlier_release_fail_closed(self) -> None:
        self.git("rm", "-q", "config/public-product-facts.json")
        self.git("commit", "-qm", "no facts")
        self.git("checkout", "-q", "--orphan", "fresh")
        candidate = self.flip_facts_to("v2.4.0")
        with self.assertRaisesRegex(PROMOTION.PromotionError, "history names no release before it"):
            PROMOTION.previous_public_release(self.root, candidate, "v2.4.0")

    def test_changed_paths_route_to_lanes_through_the_contract(self) -> None:
        contract = PROMOTION.load_contract(self.root)
        docs_only = PROMOTION.classify_paths(contract, ["docs/reference/cli.md", "./README.md"])
        self.assertEqual(docs_only["classes"], [])
        self.assertEqual(docs_only["changedPaths"], ["README.md", "docs/reference/cli.md"])
        self.assertEqual(PROMOTION.required_evidence(contract, docs_only, "macos"), ["macos-ui-benchmark"])
        engine = PROMOTION.classify_paths(contract, ["Sources/QwenVoiceCore/MLXTTSEngine.swift"])
        self.assertIn("engine-runtime", engine["classes"])
        self.assertIn("macos-engine-benchmark", PROMOTION.required_evidence(contract, engine, "macos"))
        self.assertIn("multilingual-output", engine["promotionCapabilities"])
        excluded = PROMOTION.classify_paths(contract, ["Packages/VocelloQwen3Core/README.md"])
        self.assertNotIn("engine-runtime", excluded["classes"])
        memory = PROMOTION.classify_paths(contract, ["Sources/QwenVoiceCore/NativeMemoryPolicyResolver.swift"])
        self.assertIn("macos-retained-memory", memory["promotionRequiredEvidence"])
        # The in-app text normalization and edit metrics the language verdict scores with.
        transcriber = PROMOTION.classify_paths(contract, ["Sources/SharedSupport/Services/VoiceClipTranscriber.swift"])
        self.assertIn("audio-quality-and-evaluation", transcriber["classes"])
        self.assertIn("multilingual-output", transcriber["promotionCapabilities"])
        # The Chinese fold table it scores with, as data and as its generated Swift copy.
        for path in ("Sources/SharedSupport/Services/HantHansFoldTable.swift",
                     "config/language-normalization/hant-hans-v1.txt"):
            fold = PROMOTION.classify_paths(contract, [path])
            self.assertIn("audio-quality-and-evaluation", fold["classes"], path)

    def test_routing_must_reference_defined_evidence_and_capabilities(self) -> None:
        contract = PROMOTION.load_contract(self.root)
        contract["promotionRouting"]["classes"][0]["requiredEvidence"].append("no-such-lane")
        with self.assertRaisesRegex(PROMOTION.PromotionError, "undefined evidence"):
            PROMOTION.validate_contract(contract, root=self.root)
        contract = PROMOTION.load_contract(self.root)
        contract["promotionRouting"]["classes"][0]["capabilities"].append("no-such-capability")
        with self.assertRaisesRegex(PROMOTION.PromotionError, "undefined capabilities"):
            PROMOTION.validate_contract(contract, root=self.root)
        contract = PROMOTION.load_contract(self.root)
        del contract["promotionRouting"]
        with self.assertRaisesRegex(PROMOTION.PromotionError, "requires promotionRouting"):
            PROMOTION.validate_contract(contract, root=self.root)

    def test_capability_matrix_derives_platform_specific_evidence_and_limitations(self) -> None:
        contract = PROMOTION.load_contract(self.root)
        impact = {
            "promotionRequiredEvidence": [],
            "promotionCapabilities": [
                "quality-generation", "multilingual-output", "delivery-evaluation"
            ],
        }
        required = PROMOTION.required_evidence(contract, impact, "macos")
        # RF-59: one model per mode, no Quality package, so Quality generation applies on neither
        # platform and asks for no evidence.
        self.assertEqual(required, [
            "macos-delivery-benchmark",
            "macos-language-benchmark",
            "macos-ui-benchmark",
        ])
        self.assertFalse(any(identity.startswith("ios-") for identity in required))
        coverage, unsupported = PROMOTION.capability_coverage(contract, impact, "macos")
        self.assertEqual(coverage["quality-generation"]["requiredEvidence"], [])
        self.assertEqual(coverage["quality-generation"]["platformApplicability"]["status"], "unsupported")
        self.assertIn("quality-generation:platform-macos", unsupported)
        self.assertIn("multilingual-output:independent-generation-cohorts", unsupported)
        self.assertIn("delivery-evaluation:independent-holdout-calibration", unsupported)

    def test_ios_quality_is_explicitly_unsupported_without_omitting_speed_or_other_lanes(self) -> None:
        contract = PROMOTION.load_contract(self.root)
        PROMOTION.validate_contract(contract, root=self.root)
        impact = {"promotionCapabilities": list(contract["capabilities"]),
                  "promotionRequiredEvidence": ["ios-retained-memory", "ios-ui-performance"]}
        required = PROMOTION.required_evidence(contract, impact, "ios")
        self.assertNotIn("ios-quality-engine-benchmark", required)
        self.assertEqual(set(required), {
            "ios-ui-benchmark", "ios-language-benchmark",
            "ios-model-download-lifecycle", "ios-retained-memory", "ios-ui-performance",
        })
        coverage, unsupported = PROMOTION.capability_coverage(contract, impact, "ios")
        self.assertEqual(coverage["quality-generation"]["platformApplicability"]["status"], "unsupported")
        self.assertIn("quality-generation:platform-ios", unsupported)
        self.assertEqual(coverage["speed-generation"]["platformApplicability"]["status"], "applicable")

    def test_declared_not_applicable_platform_is_reported_unsupported_never_passed(self) -> None:
        contract = PROMOTION.load_contract(self.root)
        PROMOTION.validate_contract(contract, root=self.root)
        impact = {"promotionCapabilities": ["delivery-evaluation"]}
        self.assertEqual(PROMOTION.required_evidence(contract, impact, "ios"),
                         contract["platformMinimumEvidence"]["ios"])
        self.assertIn("macos-delivery-benchmark", PROMOTION.required_evidence(contract, impact, "macos"))
        coverage, unsupported = PROMOTION.capability_coverage(contract, impact, "ios")
        declared = coverage["delivery-evaluation"]["platformApplicability"]
        self.assertEqual(declared["status"], "unsupported")
        self.assertEqual(declared["reason"], "declared-not-applicable")
        self.assertIn("RF-17", declared["decision"])
        self.assertIn("delivery-evaluation:platform-ios", unsupported)
        coverage, unsupported = PROMOTION.capability_coverage(contract, impact, "macos")
        self.assertNotIn("platformApplicability", coverage["delivery-evaluation"])
        self.assertNotIn("delivery-evaluation:platform-macos", unsupported)

    def test_not_applicable_needs_one_reasoned_platform_without_evidence(self) -> None:
        for mutation in ("evidence-kept", "empty-reason", "both-platforms", "no-platform",
                         "catalog-capability", "historical"):
            with self.subTest(mutation=mutation):
                contract = PROMOTION.load_contract(self.root)
                delivery = contract["capabilities"]["delivery-evaluation"]
                if mutation == "evidence-kept":
                    delivery["evidenceByPlatform"]["ios"] = ["ios-delivery-benchmark"]
                elif mutation == "empty-reason":
                    delivery["notApplicable"]["ios"] = " "
                elif mutation == "both-platforms":
                    delivery["notApplicable"]["macos"] = "both"
                    delivery["evidenceByPlatform"]["macos"] = []
                elif mutation == "no-platform":
                    delivery["notApplicable"] = {}
                elif mutation == "catalog-capability":
                    contract["capabilities"]["speed-generation"]["notApplicable"] = {"ios": "waived"}
                else:
                    contract["schemaVersion"] = 2
                    del contract["modelApplicabilitySource"]
                    for definition in contract["capabilities"].values():
                        definition.pop("platformApplicability", None)
                with self.assertRaises(PROMOTION.PromotionError):
                    PROMOTION.validate_contract(contract, root=self.root)

    def test_applicability_cannot_waive_supported_platforms_or_claim_unsupported(self) -> None:
        for capability, platform in (("speed-generation", "ios"), ("quality-generation", "macos"),
                                     ("quality-generation", "ios")):
            with self.subTest(capability=capability, platform=platform):
                contract = PROMOTION.load_contract(self.root)
                definition = contract["capabilities"][capability]
                definition["platformApplicability"][platform] = not definition["platformApplicability"][platform]
                with self.assertRaisesRegex(PROMOTION.PromotionError, "applicability disagrees"):
                    PROMOTION.validate_contract(contract, root=self.root)

    def test_applicable_lane_cannot_be_empty_or_applicability_removed(self) -> None:
        for mutation in ("empty", "removed", "unrelated-waiver", "invalid-bool"):
            with self.subTest(mutation=mutation):
                contract = PROMOTION.load_contract(self.root)
                speed = contract["capabilities"]["speed-generation"]
                if mutation == "empty":
                    speed["evidenceByPlatform"]["ios"] = []
                elif mutation == "removed":
                    del speed["platformApplicability"]
                elif mutation == "invalid-bool":
                    speed["platformApplicability"]["ios"] = 1
                else:
                    contract["capabilities"]["delivery-evaluation"]["platformApplicability"] = {"ios": False}
                with self.assertRaises(PROMOTION.PromotionError):
                    PROMOTION.validate_contract(contract, root=self.root)

    def test_applicability_source_drift_or_substitution_fails_closed(self) -> None:
        contract = PROMOTION.load_contract(self.root)
        path = self.root / PROMOTION.MODEL_CONTRACT_PATH
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(PROMOTION.PromotionError, "source digest"):
            PROMOTION.validate_contract(contract, root=self.root)
        contract["modelApplicabilitySource"]["path"] = "config/waiver.json"
        with self.assertRaisesRegex(PROMOTION.PromotionError, "production model contract"):
            PROMOTION.validate_contract(contract, root=self.root)

    def test_quality_lane_cannot_be_replaced_by_speed_or_capability_deleted(self) -> None:
        for mutation in ("speed", "deleted"):
            contract = PROMOTION.load_contract(self.root)
            if mutation == "speed":
                contract["capabilities"]["quality-generation"]["evidenceByPlatform"]["macos"] = ["macos-ui-benchmark"]
            else:
                del contract["capabilities"]["quality-generation"]
            with self.assertRaises(PROMOTION.PromotionError):
                PROMOTION.validate_contract(contract, root=self.root)
    def test_new_ios_quality_or_partial_support_requires_contract_migration(self) -> None:
        # RF-59 retired the Quality packages; bringing one back, for one mode or all three,
        # needs a contract migration before promotion accepts it.
        for count in (1, 3):
            with self.subTest(supported_modes=count):
                path = self.root / PROMOTION.MODEL_CONTRACT_PATH
                source = json.loads((REPO_ROOT / PROMOTION.MODEL_CONTRACT_PATH).read_text())
                for model in source["models"][:count]:
                    speed = next(v for v in model["variants"] if v["kind"] == "speed")
                    model["variants"].append({**speed, "id": "quality", "kind": "quality"})
                self.write_json(path, source)
                contract = PROMOTION.load_contract(self.root)
                contract["modelApplicabilitySource"]["sha256"] = PROMOTION.file_digest(path)
                with self.assertRaises(PROMOTION.PromotionError):
                    PROMOTION.validate_contract(contract, root=self.root)

    def test_historical_v2_contract_and_manifest_round_trip_preserves_old_requirements(self) -> None:
        contract = PROMOTION.load_contract(self.root)
        contract["schemaVersion"] = 2
        del contract["modelApplicabilitySource"]
        for definition in contract["capabilities"].values():
            definition.pop("platformApplicability", None)
            definition.pop("notApplicable", None)
        # The v2 contracts predate RF-59: both platforms carried Quality evidence.
        contract["capabilities"]["quality-generation"]["evidenceByPlatform"] = {
            "macos": ["macos-quality-engine-benchmark"], "ios": ["ios-quality-engine-benchmark"],
        }
        contract["capabilities"]["delivery-evaluation"]["evidenceByPlatform"]["ios"] = ["ios-delivery-benchmark"]
        self.write_json(self.root / PROMOTION.CONTRACT_PATH, contract)
        PROMOTION.validate_contract(contract, root=self.root)
        impact = {"promotionCapabilities": ["quality-generation"]}
        self.assertIn("ios-quality-engine-benchmark", PROMOTION.required_evidence(contract, impact, "ios"))
        coverage, _ = PROMOTION.capability_coverage(contract, impact, "ios")
        self.assertNotIn("platformApplicability", coverage["quality-generation"])
        manifest = PROMOTION.create(self.create_args())
        path = self.root / "historical.json"
        self.write_json(path, manifest)
        self.assertEqual(PROMOTION.validate_manifest(self.validation_args(path)), manifest)

    def test_speed_record_cannot_substitute_for_quality_evidence(self) -> None:
        contract = PROMOTION.load_contract(self.root)
        definition = contract["evidence"]["macos-quality-engine-benchmark"]
        with self.assertRaisesRegex(PROMOTION.PromotionError, "variants: quality"):
            PROMOTION.validate_take_coverage("macos-quality-engine-benchmark", self.record, definition)

    def test_partial_language_record_cannot_claim_complete_language_capability(self) -> None:
        contract = PROMOTION.load_contract(self.root)
        definition = contract["evidence"]["macos-language-benchmark"]
        partial = copy.deepcopy(self.record)
        partial["takes"] = [{
            **partial["takes"][0],
            "cell": "custom-en-pinned",
            "variant": "speed",
        }]
        with self.assertRaisesRegex(PROMOTION.PromotionError, "custom-zh"):
            PROMOTION.validate_take_coverage("macos-language-benchmark", partial, definition)

    def test_non_delivery_record_cannot_claim_delivery_evaluation(self) -> None:
        contract = PROMOTION.load_contract(self.root)
        definition = contract["evidence"]["macos-delivery-benchmark"]
        with self.assertRaisesRegex(PROMOTION.PromotionError, "delivery"):
            PROMOTION.validate_take_coverage("macos-delivery-benchmark", self.record, definition)

    def test_missing_required_lane_is_rejected(self) -> None:
        with self.assertRaisesRegex(PROMOTION.PromotionError, "missing=.*macos-ui-benchmark"):
            PROMOTION.create(self.create_args(record=[]))

    def test_invalid_tag_is_rejected_before_git_resolution(self) -> None:
        with self.assertRaisesRegex(PROMOTION.PromotionError, "tag is invalid"):
            PROMOTION.create(self.create_args(tag="latest"))

    def test_cross_source_record_is_rejected(self) -> None:
        self.record["source"]["commit"] = "b" * 40
        self.record["digest"] = PROMOTION.benchmark_history.record_digest(self.record)
        self.write_json(self.record_path, self.record)
        with self.assertRaisesRegex(PROMOTION.PromotionError, "cross-source"):
            PROMOTION.create(self.create_args())

    def test_dirty_record_is_rejected(self) -> None:
        self.record["source"]["dirty"] = True
        self.record["source"]["changedPaths"] = ["Sources/Example.swift"]
        self.record["run"]["classification"] = "exploratory"
        self.record["digest"] = PROMOTION.benchmark_history.record_digest(self.record)
        self.write_json(self.record_path, self.record)
        with self.assertRaises(PROMOTION.PromotionError):
            PROMOTION.create(self.create_args())

    def test_unaccepted_warning_is_rejected(self) -> None:
        with self.assertRaisesRegex(PROMOTION.PromotionError, "not explicitly accepted"):
            PROMOTION.create(self.create_args(accept_warning=[]))

    def test_stale_record_is_rejected(self) -> None:
        self.rebind_record(age=timedelta(days=8))
        with self.assertRaisesRegex(PROMOTION.PromotionError, "freshness window"):
            PROMOTION.create(self.create_args())

    def bind_metadata(self, *rows: str) -> Path:
        """release-metadata.txt beside the release evidence, bound by digest as release_evidence.py binds it."""
        path = self.root / "release-metadata.txt"
        path.write_text("".join(f"{row}\n" for row in ("commit_sha=" + self.commit, *rows)), encoding="utf-8")
        self.release["artifacts"] = [
            {"name": "Vocello-macos26.dmg", "kind": "artifact", "bytes": 1, "sha256": "b" * 64},
            {"name": path.name, "kind": "metadata", "bytes": path.stat().st_size,
             "sha256": PROMOTION.file_digest(path)},
        ]
        self.write_json(self.release_path, self.release)
        return path

    def declare_toolchain(self, **fields: str) -> Path:
        path = self.root / "release-toolchain.json"
        self.write_json(path, fields)
        return path

    def test_records_from_the_xcode_that_built_the_release_are_accepted(self) -> None:
        recorded = self.record["toolchain"]
        self.bind_metadata(f"xcode_version={recorded['xcodeVersion']}", "sdk_version=26.0",
                           f"xcode_build={recorded['xcodeBuild']}")
        manifest = PROMOTION.create(self.create_args())
        path = self.root / "quality-promotion.json"
        self.write_json(path, manifest)
        self.assertEqual(PROMOTION.validate_manifest(self.validation_args(path))["digest"], manifest["digest"])

    def test_a_record_from_another_xcode_than_the_release_is_rejected_with_both_versions(self) -> None:
        # B1: the release is built with the pinned Xcode, the evidence came from a newer local one.
        recorded = self.record["toolchain"]["xcodeVersion"]
        self.bind_metadata("xcode_version=1.0-release-pin", "sdk_version=26.0")
        with self.assertRaises(PROMOTION.PromotionError) as raised:
            PROMOTION.create(self.create_args())
        message = str(raised.exception)
        self.assertIn(f"macos-ui-benchmark benchmark record was built with Xcode {recorded!r}", message)
        self.assertIn("the release with Xcode '1.0-release-pin'", message)
        # The same Xcode version from another build (a beta, a release candidate) is another compiler.
        self.bind_metadata(f"xcode_version={recorded}", "xcode_build=0X000")
        with self.assertRaisesRegex(PROMOTION.PromotionError, r"Xcode build '[^']+', the release with Xcode build '0X000'"):
            PROMOTION.create(self.create_args())

    def test_an_accepted_toolchain_difference_is_written_down_and_validated_by_name(self) -> None:
        # Decision of 2026-11-15: the release keeps its pinned Xcode; the Mac that measures cannot run it.
        recorded = self.record["toolchain"]["xcodeVersion"]
        self.bind_metadata("xcode_version=1.0-release-pin", "sdk_version=26.0")
        reason = "The measuring Mac's macOS does not run the release's Xcode."
        manifest = PROMOTION.create(self.create_args(accept_toolchain_difference=reason))
        self.assertEqual(manifest["toolchainDifference"], {
            "release": {"xcodeVersion": "1.0-release-pin"},
            "evidence": {"macos-ui-benchmark": {"xcodeVersion": recorded}},
            "reason": reason,
        })
        path = self.root / "quality-promotion.json"
        self.write_json(path, manifest)
        self.assertEqual(PROMOTION.validate_manifest(self.validation_args(path))["digest"], manifest["digest"])

        def resigned(change) -> Path:
            altered = json.loads(json.dumps(manifest))
            change(altered)
            altered.pop("digest")
            altered["digest"] = PROMOTION.digest_value(altered)
            self.write_json(path, altered)
            return path

        # Without the written acceptance the same manifest is refused: validation never accepts silently.
        with self.assertRaisesRegex(PROMOTION.PromotionError, "was built with Xcode"):
            PROMOTION.validate_manifest(self.validation_args(resigned(lambda m: m.pop("toolchainDifference"))))
        # The acceptance names exactly what differs, for exactly this release.
        for label, change in (
            ("another value", lambda m: m["toolchainDifference"]["evidence"]["macos-ui-benchmark"].update(
                xcodeVersion="9.9")),
            ("another record", lambda m: m["toolchainDifference"]["evidence"].update(
                {"macos-ui-perf": {"xcodeVersion": recorded}})),
            ("another release", lambda m: m["toolchainDifference"]["release"].update(xcodeVersion="2.0")),
            ("no reason", lambda m: m["toolchainDifference"].update(reason=" ")),
            ("an extra field", lambda m: m["toolchainDifference"].update(note="x")),
        ):
            with self.subTest(label), self.assertRaisesRegex(PROMOTION.PromotionError, "toolchain difference"):
                PROMOTION.validate_manifest(self.validation_args(resigned(change)))

    def test_accepting_a_difference_needs_a_reason_and_a_difference(self) -> None:
        self.bind_metadata("xcode_version=1.0-release-pin", "sdk_version=26.0")
        for reason in ("", "   ", "two\nlines", "x" * 401):
            with self.subTest(reason=reason[:8]), self.assertRaisesRegex(PROMOTION.PromotionError, "needs a reason"):
                PROMOTION.create(self.create_args(accept_toolchain_difference=reason))
        # A stale option is refused, so the acceptance cannot linger once the toolchains agree.
        recorded = self.record["toolchain"]
        self.bind_metadata(f"xcode_version={recorded['xcodeVersion']}", "sdk_version=26.0")
        with self.assertRaisesRegex(PROMOTION.PromotionError, "drop the option"):
            PROMOTION.create(self.create_args(accept_toolchain_difference="No longer true."))
        # And without the option the refusal says how a difference is accepted.
        self.bind_metadata("xcode_version=1.0-release-pin", "sdk_version=26.0")
        with self.assertRaisesRegex(PROMOTION.PromotionError, "--accept-toolchain-difference"):
            PROMOTION.create(self.create_args())

    def test_release_metadata_the_evidence_names_must_be_present_intact_and_name_xcode(self) -> None:
        metadata = self.bind_metadata(f"xcode_version={self.record['toolchain']['xcodeVersion']}")
        metadata.write_text(metadata.read_text(encoding="utf-8") + "edited=after-the-evidence\n", encoding="utf-8")
        with self.assertRaisesRegex(PROMOTION.PromotionError, "differs from the digest in the release evidence"):
            PROMOTION.create(self.create_args())
        metadata.unlink()
        with self.assertRaisesRegex(PROMOTION.PromotionError, "is missing beside it"):
            PROMOTION.create(self.create_args())
        self.bind_metadata("sdk_version=26.0")
        with self.assertRaisesRegex(PROMOTION.PromotionError, "names no xcode_version"):
            PROMOTION.create(self.create_args())
        outside = self.root.parent / f"{self.root.name}-outside-metadata.txt"
        outside.write_text("xcode_version=1.0\n", encoding="utf-8")
        self.addCleanup(outside.unlink)
        self.release["artifacts"] = [{"name": f"../{outside.name}", "kind": "metadata", "bytes": 1,
                                      "sha256": PROMOTION.file_digest(outside)}]
        self.write_json(self.release_path, self.release)
        with self.assertRaisesRegex(PROMOTION.PromotionError, "is missing beside it"):
            PROMOTION.create(self.create_args())

    def test_a_declared_release_toolchain_is_compared_when_the_evidence_binds_no_metadata(self) -> None:
        # The iPhone release evidence binds no release-metadata.txt; nothing is compared unless declared.
        recorded = self.record["toolchain"]
        manifest = PROMOTION.create(self.create_args())
        path = self.root / "quality-promotion.json"
        self.write_json(path, manifest)
        matching = self.declare_toolchain(xcodeVersion=recorded["xcodeVersion"], xcodeBuild=recorded["xcodeBuild"],
                                          swiftVersion=recorded["swiftVersion"])
        PROMOTION.create(self.create_args(release_toolchain=matching))
        arguments = self.validation_args(path)
        arguments.release_toolchain = matching
        PROMOTION.validate_manifest(arguments)
        arguments.release_toolchain = self.declare_toolchain(xcodeVersion=recorded["xcodeVersion"],
                                                             swiftVersion="Apple Swift version 0.1")
        with self.assertRaisesRegex(PROMOTION.PromotionError,
                                    "built with Swift '.+', the release with Swift 'Apple Swift version 0.1'"):
            PROMOTION.validate_manifest(arguments)
        with self.assertRaisesRegex(PROMOTION.PromotionError, "the release with Xcode '0.9'"):
            PROMOTION.create(self.create_args(release_toolchain=self.declare_toolchain(xcodeVersion="0.9")))
        for malformed in ({"xcodeBuild": "1A1"}, {"xcodeVersion": ""}, {"xcodeVersion": "1.0", "sdkVersion": "1.0"}):
            with self.subTest(malformed=malformed), \
                    self.assertRaisesRegex(PROMOTION.PromotionError, "--release-toolchain must be a JSON object"):
                PROMOTION.create(self.create_args(release_toolchain=self.declare_toolchain(**malformed)))
        # A declaration cannot contradict what the bound metadata states.
        self.bind_metadata(f"xcode_version={recorded['xcodeVersion']}")
        with self.assertRaisesRegex(PROMOTION.PromotionError, "--release-toolchain states Xcode '0.9' but the release "
                                                              "metadata states"):
            PROMOTION.create(self.create_args(release_toolchain=self.declare_toolchain(xcodeVersion="0.9")))

    def test_the_command_line_accepts_the_declared_toolchain_for_create_and_validate(self) -> None:
        for operation, extra in (("create", ["--base", "v2.3.0", "--output", "out.json"]), ("validate", ["--manifest", "m.json"])):
            arguments = PROMOTION.parser().parse_args([
                operation, "--platform", "ios", "--tag", "v2.4.0", "--release-evidence", "e.json",
                "--release-toolchain", "toolchain.json", *extra])
            self.assertEqual(arguments.release_toolchain, Path("toolchain.json"))

    def test_manifest_is_bound_to_release_evidence_bytes(self) -> None:
        manifest = PROMOTION.create(self.create_args())
        path = self.root / "quality-promotion.json"
        self.write_json(path, manifest)
        changed = copy.deepcopy(self.release)
        changed["extra"] = "different bytes"
        self.write_json(self.release_path, changed)
        with self.assertRaisesRegex(PROMOTION.PromotionError, "differs from release evidence"):
            PROMOTION.validate_manifest(self.validation_args(path))

    def test_private_device_identity_is_rejected(self) -> None:
        manifest = PROMOTION.create(self.create_args())
        manifest["deviceName"] = "Personal iPhone"
        manifest["digest"] = PROMOTION.digest_value({key: value for key, value in manifest.items() if key != "digest"})
        path = self.root / "quality-promotion.json"
        self.write_json(path, manifest)
        with self.assertRaises(PROMOTION.PromotionError):
            PROMOTION.validate_manifest(self.validation_args(path))

    def test_managed_command_receipt_digest_is_fail_closed(self) -> None:
        contract = PROMOTION.load_contract(self.root)
        definition = contract["evidence"]["macos-model-download-lifecycle"]
        receipt = {
            "schemaVersion": 1,
            "evidenceID": "macos-model-download-lifecycle",
            "platform": "macos",
            "sourceCommit": self.commit,
            "sourceDirty": False,
            "command": definition["command"],
            "commandDigest": PROMOTION.digest_value(definition["command"]),
            "startedAt": "2026-08-19T12:00:00Z",
            "finishedAt": "2026-08-19T12:01:00Z",
            "exitCode": 0,
            "outputDigest": "c" * 64,
            "contractDigest": PROMOTION.digest_value(contract),
        }
        receipt["digest"] = PROMOTION.digest_value(receipt)
        validated = PROMOTION.validate_receipt(
            "macos-model-download-lifecycle", receipt, definition, self.commit,
            PROMOTION.digest_value(contract), contract["maxEvidenceAgeSeconds"],
            datetime(2026, 8, 19, 12, 2, tzinfo=timezone.utc),
        )
        self.assertEqual(validated["receiptDigest"], receipt["digest"])
        receipt["outputDigest"] = "d" * 64
        with self.assertRaisesRegex(PROMOTION.PromotionError, "digest is invalid"):
            PROMOTION.validate_receipt(
                "macos-model-download-lifecycle", receipt, definition, self.commit,
                PROMOTION.digest_value(contract), contract["maxEvidenceAgeSeconds"],
                datetime(2026, 8, 19, 12, 2, tzinfo=timezone.utc),
            )

    def test_stale_managed_command_receipt_is_rejected(self) -> None:
        contract = PROMOTION.load_contract(self.root)
        definition = contract["evidence"]["macos-model-download-lifecycle"]
        receipt = {
            "schemaVersion": 1,
            "evidenceID": "macos-model-download-lifecycle",
            "platform": "macos",
            "sourceCommit": self.commit,
            "sourceDirty": False,
            "command": definition["command"],
            "commandDigest": PROMOTION.digest_value(definition["command"]),
            "startedAt": "2026-08-01T12:00:00Z",
            "finishedAt": "2026-08-01T12:01:00Z",
            "exitCode": 0,
            "outputDigest": "c" * 64,
            "contractDigest": PROMOTION.digest_value(contract),
        }
        receipt["digest"] = PROMOTION.digest_value(receipt)
        with self.assertRaisesRegex(PROMOTION.PromotionError, "freshness window"):
            PROMOTION.validate_receipt(
                "macos-model-download-lifecycle", receipt, definition, self.commit,
                PROMOTION.digest_value(contract), contract["maxEvidenceAgeSeconds"],
                datetime(2026, 8, 19, 12, 2, tzinfo=timezone.utc),
            )


class LanguageBenchCoverageTests(unittest.TestCase):
    def test_the_full_language_matrix_covers_every_required_language_cell(self) -> None:
        # Each language lane names a Custom cell per product language; a matrix without one can
        # never produce a promotable record (four were missing until 2026-10-22).
        contract = json.loads((REPO_ROOT / "config/quality-promotion-contract.json").read_text(encoding="utf-8"))
        matrix = json.loads((REPO_ROOT / "config/language-bench-matrix.json").read_text(encoding="utf-8"))
        takes = [{"cell": cell["id"], "mode": cell["mode"], "variant": cell["variant"]} for cell in matrix["cells"]]
        for identity in ("macos-language-benchmark", "ios-language-benchmark"):
            with self.subTest(identity=identity):
                PROMOTION.validate_take_coverage(identity, {"takes": takes}, contract["evidence"][identity])


if __name__ == "__main__":
    unittest.main()
