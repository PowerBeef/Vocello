import base64
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("auto_language_check", ROOT / "scripts" / "auto_language_check.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

TRACKED_SPEC = ROOT / "config" / "auto-language-check.json"
CORPUS = json.loads((ROOT / "config" / "ios-control-audit-corpus.json").read_text(encoding="utf-8"))["scripts"]
TEN = ("english", "chinese", "french", "japanese", "german", "korean", "spanish", "russian", "italian", "portuguese")
EXPLICIT = {
    # takeID: (selection, menu title, witnessLanguage, witness level, requireAudioPass)
    "custom-explicit-french-over-english": ("french", "French", "english", "required", False),
    "custom-explicit-japanese": ("japanese", "Japanese", "japanese", "advisory", True),
    "custom-explicit-english-over-dutch": ("english", "English", None, "absent", False),
    "design-explicit-spanish-over-french": ("spanish", "Spanish", "french", "required", False),
    "clone-explicit-english-over-japanese": ("english", "English", "japanese", "advisory", False),
}
# Explicit takes whose script the recognizer names as another language than the selection.
OVERRIDES = {take_id for take_id, (selection, _, witness, _, _) in EXPLICIT.items()
             if witness is not None and witness != selection}
TAKE_IDS = [
    *(f"custom-{language}" for language in TEN),
    "custom-mixed", "custom-undetected",
    "custom-explicit-french-over-english", "custom-explicit-japanese", "custom-explicit-english-over-dutch",
    "design-french", "design-japanese", "design-undetected", "design-explicit-spanish-over-french",
    "clone-japanese", "clone-french", "clone-explicit-english-over-japanese",
]
RUN_ID = "auto-language-20261020-000000"
MODELS = {"custom": "pro_custom_speed", "design": "pro_design_speed", "clone": "pro_clone_speed"}
CONDITIONING = {"custom": "custom_voice", "design": "voice_design", "clone": "clone_transcript_backed"}


def generation_id(index):
    return f"{index:08x}-abcd-4ef0-8000-{index:012x}"


class AutoLanguagePlanTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.spec = json.loads(TRACKED_SPEC.read_text(encoding="utf-8"))

    def tearDown(self):
        self.temp.cleanup()

    def build(self, spec):
        path = self.root / "spec.json"
        path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        return MODULE.build_plan(path)

    def test_plan_builds_from_tracked_config(self):
        plan = MODULE.build_plan(TRACKED_SPEC)
        self.assertEqual(plan["source"], "config/auto-language-check.json")
        self.assertEqual([take["takeID"] for take in plan["takes"]], TAKE_IDS)
        self.assertEqual(len(plan["takes"]), 22)
        custom_corpus = {take["expectedChip"] for take in plan["takes"]
                         if take["mode"] == "custom" and take["scriptKey"].startswith("corpus:")
                         and take["selection"] == "auto"}
        self.assertEqual(custom_corpus, set(TEN))
        takes = {take["takeID"]: take for take in plan["takes"]}
        for take in plan["takes"]:
            with self.subTest(take=take["takeID"]):
                self.assertEqual(set(take), MODULE.PLAN_TAKE_KEYS)
                self.assertEqual(take["scriptDigest"], hashlib.sha256(take["script"].encode("utf-8")).hexdigest())
                explicit = take["takeID"] in EXPLICIT
                if take["scriptKey"].startswith("corpus:"):
                    language, length = take["scriptKey"][len("corpus:"):].split("/")
                    if explicit:
                        self.assertEqual((language, length), (take["witnessLanguage"], "long"))
                    else:
                        self.assertEqual((language, length), (take["expectedChip"], "short"))
                    self.assertEqual(take["script"], CORPUS[language][length])
                else:
                    self.assertEqual(take["scriptKey"], "edge:" + take["takeID"])
                self.assertIsInstance(take["requireAudioPass"], bool)
                if not explicit:
                    self.assertEqual(take["selection"], "auto")
                    self.assertIsNone(take["selectionTitle"])
                    self.assertEqual(take["witnessLanguage"],
                                     None if take["witness"] == "absent" else take["expectedChip"])
        self.assertEqual(takes["custom-french"]["expectedChipValue"], "French, Auto")
        self.assertEqual(takes["custom-french"]["expectedRecommendedTitle"], "French — Detected")
        self.assertEqual(takes["clone-japanese"]["expectedRecommendedTitle"], "Japanese — Detected")
        for take_id in ("custom-undetected", "design-undetected"):
            self.assertEqual(takes[take_id]["expectedChipValue"], "Auto")
            self.assertIsNone(takes[take_id]["expectedRecommendedTitle"])
            self.assertEqual(takes[take_id]["witness"], "absent")
            self.assertFalse(takes[take_id]["requireAudioPass"])
        self.assertEqual(takes["custom-undetected"]["expectedEngine"], "english")
        self.assertEqual(takes["custom-undetected"]["knownMismatch"], "D6")
        self.assertEqual(takes["design-undetected"]["expectedEngine"], "auto")
        self.assertIsNone(takes["design-undetected"]["knownMismatch"])
        witnesses = {take_id: take["witness"] for take_id, take in takes.items()}
        for language in ("english", "french", "german", "spanish", "italian", "portuguese"):
            self.assertEqual(witnesses[f"custom-{language}"], "required")
        for language in ("chinese", "japanese", "korean", "russian"):
            self.assertEqual(witnesses[f"custom-{language}"], "advisory")
        self.assertEqual(witnesses["custom-mixed"], "advisory")
        self.assertEqual(witnesses["design-french"], "required")
        self.assertEqual(witnesses["clone-japanese"], "advisory")
        # Explicit takes: the chip shows the plain name, the menu recommends nothing, and the
        # witness is the language the script is written in, not the selection.
        for take_id, (selection, title, witness_language, level, require_audio) in EXPLICIT.items():
            with self.subTest(explicit=take_id):
                take = takes[take_id]
                self.assertEqual(take["selection"], selection)
                self.assertEqual(take["selectionTitle"], title)
                self.assertEqual((take["expectedChip"], take["expectedEngine"]), (selection, selection))
                self.assertEqual(take["expectedChipValue"], title)
                self.assertNotIn("Auto", take["expectedChipValue"])
                self.assertIsNone(take["expectedRecommendedTitle"])
                self.assertEqual(take["witnessLanguage"], witness_language)
                self.assertEqual(take["witness"], level)
                self.assertEqual(take["requireAudioPass"], require_audio)
                self.assertIsNone(take["knownMismatch"])
        self.assertEqual(takes["custom-explicit-english-over-dutch"]["script"],
                         "Wij fietsen elke zondag samen naar het strand.")
        # The digest covers everything but itself and is stable across builds.
        self.assertEqual(plan["planDigest"], MODULE.plan_digest(plan))
        self.assertEqual(MODULE.build_plan(TRACKED_SPEC), plan)
        output, encoded = self.root / "plan.json", self.root / "plan.b64"
        self.assertEqual(MODULE.main(["prepare", "--spec", str(TRACKED_SPEC), "--output", str(output),
                                      "--encoded-output", str(encoded)]), 0)
        raw = encoded.read_bytes()
        self.assertTrue(raw.endswith(b"\n"))
        self.assertEqual(raw.count(b"\n"), 1)
        decoded = json.loads(base64.b64decode(raw.strip(), validate=True))
        self.assertEqual(decoded, plan)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), plan)
        self.assertEqual(MODULE.load_plan(output), plan)

    def test_plan_drift_is_rejected(self):
        def take(spec, take_id):
            return next(row for row in spec["takes"] if row["takeID"] == take_id)

        cases = [
            ("unknown corpus language", lambda s: take(s, "design-french")["script"].update(corpus="dutch"),
             "unknown corpus language"),
            ("unknown corpus length", lambda s: take(s, "design-french")["script"].update(length="medium"),
             "unknown corpus length"),
            ("duplicate takeID", lambda s: take(s, "design-japanese").update(takeID="design-french"),
             "duplicate takeID"),
            ("duplicate mode and script", lambda s: take(s, "design-japanese").update(
                script={"corpus": "french", "length": "short"}, expectedChip="french", expectedEngine="french"),
             "repeats another design take"),
            ("unsupported chip language", lambda s: take(s, "custom-mixed").update(expectedChip="dutch"),
             "unsupported language"),
            ("unsupported engine language", lambda s: take(s, "design-undetected").update(expectedEngine="dutch"),
             "unsupported language"),
            ("knownMismatch outside custom", lambda s: take(s, "design-undetected").update(knownMismatch="D6"),
             "only valid for custom"),
            ("unknown knownMismatch", lambda s: take(s, "custom-undetected").update(knownMismatch="D7"),
             "unknown knownMismatch"),
            ("divergence without knownMismatch", lambda s: take(s, "custom-undetected").pop("knownMismatch"),
             "without a knownMismatch"),
            ("corpus chip drift", lambda s: take(s, "custom-german").update(expectedChip="english", expectedEngine="english"),
             "expects chip english for a german corpus"),
            ("missing custom language", lambda s: s["takes"].remove(take(s, "custom-korean")),
             "miss corpus languages: korean"),
            ("unknown take field", lambda s: take(s, "custom-english").update(seed=7), "unknown fields"),
            ("non-boolean audio requirement", lambda s: take(s, "design-undetected").update(requireAudioPass="no"),
             "requireAudioPass"),
            ("unsupported selection", lambda s: take(s, "custom-explicit-japanese").update(selection="dutch"),
             "unsupported selection"),
            ("null selection", lambda s: take(s, "custom-english").update(selection=None), "unsupported selection"),
            ("explicit chip is not the selection", lambda s: take(s, "design-explicit-spanish-over-french").update(
                expectedChip="french"), "selects spanish but expects chip french"),
            ("explicit engine is not the selection", lambda s: take(s, "clone-explicit-english-over-japanese").update(
                expectedEngine="japanese"), "selects english but expects chip english and engine japanese"),
            ("explicit selection with the auto chip", lambda s: take(s, "custom-explicit-japanese").update(
                expectedChip="auto", expectedEngine="auto"), "selects japanese but expects chip auto"),
            ("knownMismatch on an explicit take", lambda s: take(s, "custom-explicit-english-over-dutch").update(
                knownMismatch="D6"), "only valid on auto takes"),
            ("textLanguage on a corpus sentence", lambda s: take(s, "custom-explicit-japanese").update(
                textLanguage="japanese"), "textLanguage on a corpus sentence"),
            ("unsupported textLanguage", lambda s: take(s, "custom-explicit-english-over-dutch").update(
                textLanguage="dutch"), "unsupported textLanguage"),
            ("auto edge textLanguage disagrees with the chip", lambda s: take(s, "custom-mixed").update(
                textLanguage="japanese"), "declares textLanguage japanese but expects chip english"),
            ("auto edge textLanguage on an undetected take", lambda s: take(s, "design-undetected").update(
                textLanguage="english"), "declares textLanguage english but expects chip auto"),
            # An explicit Japanese corpus take never stands in for the Auto Japanese take.
            ("explicit takes do not count toward the ten", lambda s: s["takes"].remove(take(s, "custom-japanese")),
             "miss corpus languages: japanese"),
            ("duplicate mode, script and selection", lambda s: s["takes"].append(
                {**take(s, "custom-explicit-japanese"), "takeID": "custom-explicit-japanese-again"}),
             "repeats another custom take's script and selection"),
        ]
        for name, mutate, message in cases:
            with self.subTest(case=name):
                spec = copy.deepcopy(self.spec)
                mutate(spec)
                with self.assertRaisesRegex(MODULE.ContractError, message):
                    self.build(spec)
        spec = copy.deepcopy(self.spec)
        take(spec, "custom-mixed")["expectedChip"] = "dutch"
        path = self.root / "bad-spec.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            code = MODULE.main(["prepare", "--spec", str(path), "--output", str(self.root / "p.json"),
                                "--encoded-output", str(self.root / "p.b64")])
        self.assertEqual(code, 2)
        self.assertIn("unsupported language", errors.getvalue())
        self.assertFalse((self.root / "p.json").exists())

    def test_uniqueness_includes_the_selection(self):
        # The same mode and script under another selection is a distinct take.
        spec = copy.deepcopy(self.spec)
        spec["takes"].append({"takeID": "custom-explicit-german-over-english", "mode": "custom",
                              "selection": "german", "script": {"corpus": "english", "length": "short"},
                              "expectedChip": "german", "expectedEngine": "german"})
        spec["takes"].append({"takeID": "custom-explicit-english-over-english", "mode": "custom",
                              "selection": "english", "script": {"corpus": "english", "length": "short"},
                              "expectedChip": "english", "expectedEngine": "english"})
        # An explicit edge take that declares its text's language takes that language as its witness.
        spec["takes"].append({"takeID": "design-explicit-italian-over-german", "mode": "design",
                              "selection": "italian", "script": {"text": "Der Zug fährt pünktlich ab."},
                              "textLanguage": "german", "expectedChip": "italian", "expectedEngine": "italian"})
        # textLanguage on an Auto edge take must agree with the chip it expects.
        spec["takes"].append({"takeID": "clone-mixed-declared", "mode": "clone",
                              "script": {"text": "The capital of Japan is 東京, a city of many trains."},
                              "textLanguage": "english", "expectedChip": "english", "expectedEngine": "english"})
        takes = {take["takeID"]: take for take in self.build(spec)["takes"]}
        english = takes["custom-english"]
        for take_id in ("custom-explicit-german-over-english", "custom-explicit-english-over-english"):
            self.assertEqual(takes[take_id]["scriptDigest"], english["scriptDigest"])
        self.assertEqual(takes["custom-explicit-german-over-english"]["witnessLanguage"], "english")
        self.assertEqual(takes["custom-explicit-german-over-english"]["witness"], "required")
        self.assertEqual(takes["custom-explicit-english-over-english"]["expectedChipValue"], "English")
        self.assertEqual(takes["design-explicit-italian-over-german"]["witnessLanguage"], "german")
        self.assertEqual(takes["design-explicit-italian-over-german"]["witness"], "required")
        self.assertEqual(takes["clone-mixed-declared"]["witness"], "advisory")
        self.assertEqual(takes["clone-mixed-declared"]["witnessLanguage"], "english")
        # Spelling out the default selection is the same take as leaving it out.
        spec = copy.deepcopy(self.spec)
        spec["takes"].append({"takeID": "custom-english-again", "mode": "custom", "selection": "auto",
                              "script": {"corpus": "english", "length": "short"},
                              "expectedChip": "english", "expectedEngine": "english"})
        with self.assertRaisesRegex(MODULE.ContractError, "repeats another custom take's script and selection"):
            self.build(spec)

    def test_tampered_plan_fails_its_digest(self):
        plan = MODULE.build_plan(TRACKED_SPEC)
        plan["takes"][0]["expectedEngine"] = "french"
        path = self.root / "plan.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ContractError, "plan digest"):
            MODULE.load_plan(path)


class AutoLanguageValidationTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.plan = MODULE.build_plan(TRACKED_SPEC)
        self.plan_path = self.root / "plan.json"
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        self.takes = {take["takeID"]: take for take in self.plan["takes"]}
        self.rows, self.records = self.passing_fixture()
        self.extra_rows = []
        self.extra_lines = []

    def tearDown(self):
        self.temp.cleanup()

    def receipt(self, take, index, *, retry=0):
        engine = take["expectedEngine"]
        receipt = {
            "schemaVersion": 3, "generationID": generation_id(index).upper(),
            "generationIdentityDigest": "a" * 64, "requestIdentityDigest": "b" * 64,
            "sessionIdentityDigest": "c" * 64, "prewarmIdentityDigest": "d" * 64,
            "modelID": MODELS[take["mode"]], "instructionCharacters": 0,
            "language": engine, "seed": 1000 + index, "seedSource": "generated",
            "variation": "balanced", "streaming": True, "warmState": "warm",
            "retryAttempt": retry, "operationGeneration": index,
            "storedLanguageSelection": take["selection"], "finalModelLanguage": engine,
            "languageTokenMode": "nothink" if engine == "auto" else "think",
            "conditioningMode": CONDITIONING[take["mode"]],
            "normalizedTargetTextDigest": take["scriptDigest"],
            "normalizedTargetTextCharacters": len(take["script"]),
            "referenceTranscriptCharacters": 24 if take["mode"] == "clone" else 0,
            # The engine's real signature format: "|"-joined fields, ","-joined lists.
            "modelRuntimeIdentity": {
                "resolvedModelID": MODELS[take["mode"]], "modelRepository": "fixture/model",
                "runtimeProfileSignature": f"qwen3_tts|{CONDITIONING[take['mode']]}|8bit|24000|auto,english,french",
            },
        }
        # The recognizer names the script's own language, which an explicit selection may override.
        if take["witnessLanguage"] is not None:
            receipt["detectedTargetLanguage"] = take["witnessLanguage"]
        if take["mode"] == "custom":
            receipt["speakerID"] = "aiden"
        if take["mode"] == "clone":
            receipt["referenceTranscriptLanguage"] = "english"
        MODULE.validate_engine_receipt(receipt)
        return receipt

    def row(self, take, index, *, retry=0, run_id=RUN_ID):
        engine = take["expectedEngine"]
        return {
            "schemaVersion": 8, "layer": "engine", "generationID": generation_id(index).upper(),
            "mode": take["mode"], "modelID": MODELS[take["mode"]], "finishReason": "eos", "warmState": "warm",
            "requestReceipt": self.receipt(take, index, retry=retry),
            "audioQC": {"verdict": "pass"},
            "notes": {"benchRunID": run_id, "promptDigest": take["scriptDigest"], "languageHint": engine,
                      "quality_registry_outcome": "pass"},
            "summary": {"runEnvironment": {"runtimeDebugProvenance": {
                "internalDiagnosticsAvailable": True, "masterGateRequested": False,
                "activeOverrideKeys": [], "activeOverrideDigest": None}}},
        }

    def record(self, take, index):
        title = take["expectedRecommendedTitle"]
        return {
            "schemaVersion": 1, "runID": RUN_ID, "planDigest": self.plan["planDigest"],
            "takeID": take["takeID"], "mode": take["mode"],
            "chip": {"expectedValue": take["expectedChipValue"], "observedValue": take["expectedChipValue"],
                     "stable": True},
            "menu": {"opened": True, "recommendedSeen": True if title else None, "autoItemSeen": True,
                     "valueUnchanged": True},
            "generationID": generation_id(index), "visibleErrorShown": False,
        }

    def passing_fixture(self):
        rows, records = {}, {}
        for index, take in enumerate(self.plan["takes"], 1):
            rows[take["takeID"]] = [self.row(take, index)]
            records[take["takeID"]] = self.record(take, index)
        # custom-english needed one allocation retry: the higher attempt is terminal.
        failed_attempt = self.row(self.takes["custom-english"], 1, retry=0)
        failed_attempt.update(finishReason="memory.insufficient")
        rows["custom-english"] = [failed_attempt, self.row(self.takes["custom-english"], 1, retry=1)]
        return rows, records

    @staticmethod
    def manifest_line(record):
        encoded = base64.b64encode(json.dumps(record, sort_keys=True).encode("utf-8")).decode("ascii")
        return f"    t =    12.50s VOCELLO_AUTO_LANGUAGE_TAKE={encoded}"

    def write_run(self, diagnostics=None):
        diagnostics = diagnostics or self.root / "diagnostics"
        engine = diagnostics / "engine"
        engine.mkdir(parents=True, exist_ok=True)
        other_run = self.row(self.takes["custom-french"], 99, run_id="another-run")
        torn = json.dumps(other_run)[:200]  # an earlier run's interrupted append
        lines = [torn + json.dumps(other_run), json.dumps({"layer": "engine", "notes": {"benchRunID": RUN_ID}})]
        for rows in self.rows.values():
            lines.extend(json.dumps(row) for row in rows)
        lines.extend(json.dumps(row) for row in self.extra_rows)
        # A trailing append still in progress is not a row yet.
        (engine / "generations.jsonl").write_text("\n".join(lines) + "\n{\"layer\": \"eng", encoding="utf-8")
        log = ["Test Suite 'VocelloMacAutoLanguageUITests' started"]
        for record in self.records.values():
            log.extend([self.manifest_line(record)] * 2)  # xcodebuild echoes lines
        log.extend(self.extra_lines)
        log_path = self.root / "xcodebuild.log"
        log_path.write_text("\n".join(log) + "\n", encoding="utf-8")
        return log_path, diagnostics

    def run_main(self, *extra, diagnostics=None, output=None):
        log_path, diagnostics = self.write_run(diagnostics)
        output = output or self.root / "summary.json"
        command = ["validate", "--plan", str(self.plan_path), "--xcodebuild-log", str(log_path),
                   "--diagnostics", str(diagnostics), "--run-id", RUN_ID, "--output", str(output), *extra]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = MODULE.main(command)
        # A contract failure writes no summary; an empty dict stands for it.
        summary: dict = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
        return code, summary

    def validate_direct(self):
        log_path, diagnostics = self.write_run()
        return MODULE.validate(self.plan_path, log_path, diagnostics, RUN_ID, self.root / "summary.json")

    @staticmethod
    def take_summary(summary, take_id):
        return next(take for take in summary["takes"] if take["takeID"] == take_id)

    def test_all_pass_with_the_known_d6_observation_and_no_script_text(self):
        code, summary = self.run_main()
        self.assertEqual(code, 0, [t["issues"] for t in summary.get("takes", [])])
        self.assertEqual(summary["result"], "pass")
        self.assertEqual(summary["runID"], RUN_ID)
        self.assertEqual(summary["planDigest"], self.plan["planDigest"])
        self.assertEqual(summary["counts"]["plannedTakes"], 22)
        self.assertEqual(summary["counts"]["manifestRecords"], 22)
        self.assertEqual(summary["counts"]["failedTakes"], 0)
        self.assertEqual([take["takeID"] for take in summary["takes"]], TAKE_IDS)
        for take in summary["takes"]:
            with self.subTest(take=take["takeID"]):
                self.assertEqual(take["issues"], [])
                self.assertEqual(take["correlation"], "generationID")
                self.assertEqual(set(take), {"takeID", "mode", "scriptKey", "scriptDigest", "expected", "observed",
                                             "correlation", "issues", "observations"})
        d6 = self.take_summary(summary, "custom-undetected")
        self.assertIn("known_d6_chip_auto_engine_english", d6["observations"])
        self.assertEqual(d6["observed"]["finalModelLanguage"], "english")
        self.assertEqual(d6["observed"]["chip"], {"value": "Auto", "stable": True})
        english = self.take_summary(summary, "custom-english")
        self.assertEqual(english["observed"]["finishReason"], "eos")
        self.assertEqual(english["observed"]["fastQC"], {"outcome": "pass", "audioQCVerdict": "pass"})
        self.assertEqual(english["observed"]["speakerID"], "aiden")
        self.assertEqual(self.take_summary(summary, "clone-french")["observed"]["referenceTranscriptLanguage"], "english")
        # Manual selection wins: the recognizer named the script's language and the engine spoke the choice.
        for take_id, (selection, title, witness_language, _, _) in EXPLICIT.items():
            with self.subTest(explicit=take_id):
                take = self.take_summary(summary, take_id)
                self.assertEqual(take["expected"]["selection"], selection)
                self.assertEqual(take["expected"]["chipValue"], title)
                self.assertEqual(take["expected"]["witnessLanguage"], witness_language)
                self.assertEqual(take["observed"]["storedLanguageSelection"], selection)
                self.assertEqual(take["observed"]["finalModelLanguage"], selection)
                self.assertEqual(take["observed"]["languageTokenMode"], "think")
                self.assertEqual(take["observed"]["detectedTargetLanguage"], witness_language)
                self.assertEqual(take["observed"]["chip"], {"value": title, "stable": True})
                if take_id in OVERRIDES:
                    self.assertIn("explicit_selection_overrode_detection", take["observations"])
                else:
                    self.assertNotIn("explicit_selection_overrode_detection", take["observations"])
        self.assertEqual(OVERRIDES, {"custom-explicit-french-over-english", "design-explicit-spanish-over-french",
                                     "clone-explicit-english-over-japanese"})
        for take in summary["takes"]:
            if take["takeID"] not in EXPLICIT:
                self.assertEqual(take["expected"]["selection"], "auto")
                self.assertNotIn("explicit_selection_overrode_detection", take["observations"])
        data = (self.root / "summary.json").read_bytes()
        for take in self.plan["takes"]:
            self.assertNotIn(take["script"].encode("utf-8"), data)
            self.assertNotIn(json.dumps(take["script"])[1:-1].encode("ascii"), data)
        MODULE.startup.recursively_reject_private_fields(summary)

    def test_each_failure_has_its_own_issue(self):
        def receipt(take_id):
            return self.rows[take_id][-1]["requestReceipt"]

        def notes(take_id):
            return self.rows[take_id][-1]["notes"]

        def speak(take_id, language):
            receipt(take_id).update(language=language, finalModelLanguage=language,
                                    languageTokenMode="nothink" if language == "auto" else "think")
            notes(take_id)["languageHint"] = language

        cases = [
            ("stored selection pinned", "custom-french",
             lambda: receipt("custom-french").update(storedLanguageSelection="french"), "stored_selection_not_auto"),
            ("chip and engine disagree", "custom-french", lambda: speak("custom-french", "english"),
             "chip_engine_mismatch"),
            ("engine language wrong", "custom-french", lambda: speak("custom-french", "english"),
             "engine_language_mismatch"),
            ("language and final drift", "custom-italian",
             lambda: receipt("custom-italian").update(language="english"), "language_final_drift"),
            ("wrong token mode", "design-undetected",
             lambda: receipt("design-undetected").update(languageTokenMode="think"), "token_mode_mismatch"),
            ("Latin witness wrong", "custom-german",
             lambda: receipt("custom-german").update(detectedTargetLanguage="english"), "detected_target_mismatch"),
            ("Latin witness missing", "custom-portuguese",
             lambda: receipt("custom-portuguese").pop("detectedTargetLanguage"), "detected_target_mismatch"),
            ("undetected take names a target", "design-undetected",
             lambda: receipt("design-undetected").update(detectedTargetLanguage="german"),
             "detected_target_unexpected"),
            ("prompt digest wrong", "custom-korean",
             lambda: notes("custom-korean").update(promptDigest="0" * 64), "prompt_digest_mismatch"),
            ("language hint mismatch", "custom-spanish",
             lambda: notes("custom-spanish").update(languageHint="english"), "language_hint_mismatch"),
            ("finish not eos", "custom-russian",
             lambda: self.rows["custom-russian"][-1].update(finishReason="max_tokens"), "finish_not_eos"),
            ("Fast QC fail", "custom-chinese",
             lambda: notes("custom-chinese").update(quality_registry_outcome="fail"), "fast_qc_failed"),
            ("audio QC fail", "custom-chinese",
             lambda: self.rows["custom-chinese"][-1].update(audioQC={"verdict": "fail"}), "audio_qc_failed"),
            ("missing row", "design-japanese", lambda: self.rows.pop("design-japanese"), "no_engine_row"),
            ("missing manifest record", "design-japanese", lambda: self.records.pop("design-japanese"),
             "missing_take"),
            ("no generation identity", "design-japanese",
             lambda: self.records["design-japanese"].update(generationID=None), "missing_generation_id"),
            ("wrong mode", "clone-japanese",
             lambda: self.rows["clone-japanese"][-1].update(mode="design"), "mode_mismatch"),
            ("chip value wrong", "custom-french",
             lambda: self.records["custom-french"]["chip"].update(observedValue="English, Auto"),
             "chip_value_mismatch"),
            ("chip unstable", "custom-japanese",
             lambda: self.records["custom-japanese"]["chip"].update(stable=False), "chip_unstable"),
            ("menu changed the value", "custom-german",
             lambda: self.records["custom-german"]["menu"].update(valueUnchanged=False), "menu_changed_value"),
            ("menu not opened", "custom-german",
             lambda: self.records["custom-german"]["menu"].update(opened=False), "menu_not_opened"),
            ("menu lacks Auto", "custom-german",
             lambda: self.records["custom-german"]["menu"].update(autoItemSeen=False), "menu_auto_item_missing"),
            ("menu lacks the detected recommendation", "custom-german",
             lambda: self.records["custom-german"]["menu"].update(recommendedSeen=False), "menu_recommended_missing"),
            ("D6 flipped to auto", "custom-undetected", lambda: speak("custom-undetected", "auto"),
             "d6_expectation_changed"),
            ("D6 override active", "custom-undetected",
             lambda: self.rows["custom-undetected"][-1]["summary"]["runEnvironment"]["runtimeDebugProvenance"].update(
                 activeOverrideKeys=["QWENVOICE_CUSTOM_AUTO_LANGUAGE"]), "d6_override_active"),
            ("receipt too old", "custom-english",
             lambda: receipt("custom-english").update(schemaVersion=1), "receipt_schema_too_old"),
            ("receipt invalid", "custom-english",
             lambda: receipt("custom-english").update(seedSource="guessed"), "receipt_invalid"),
            ("profile signature carries a path", "custom-english",
             lambda: receipt("custom-english")["modelRuntimeIdentity"].update(runtimeProfileSignature="qwen3_tts|/Users/x"),
             "receipt_invalid"),
            ("required take shows an error", "custom-english",
             lambda: self.records["custom-english"].update(visibleErrorShown=True), "visible_error"),
            ("explicit selection stored as auto", "custom-explicit-french-over-english",
             lambda: receipt("custom-explicit-french-over-english").update(storedLanguageSelection="auto"),
             "stored_selection_mismatch"),
            ("explicit selection stored as the detected language", "design-explicit-spanish-over-french",
             lambda: receipt("design-explicit-spanish-over-french").update(storedLanguageSelection="french"),
             "stored_selection_mismatch"),
            ("detection beat the explicit selection", "custom-explicit-french-over-english",
             lambda: speak("custom-explicit-french-over-english", "english"), "engine_language_mismatch"),
            ("explicit chip disagrees with the engine", "clone-explicit-english-over-japanese",
             lambda: speak("clone-explicit-english-over-japanese", "japanese"), "chip_engine_mismatch"),
            ("explicit chip still shows Auto", "custom-explicit-japanese",
             lambda: self.records["custom-explicit-japanese"]["chip"].update(observedValue="Japanese, Auto"),
             "chip_value_mismatch"),
            ("explicit chip still shows Auto is no plain-name chip", "custom-explicit-japanese",
             lambda: self.records["custom-explicit-japanese"]["chip"].update(observedValue="Japanese, Auto"),
             "chip_engine_mismatch"),
            ("explicit witness compared to the script, not the selection", "design-explicit-spanish-over-french",
             lambda: receipt("design-explicit-spanish-over-french").update(detectedTargetLanguage="spanish"),
             "detected_target_mismatch"),
            ("explicit required witness missing", "custom-explicit-french-over-english",
             lambda: receipt("custom-explicit-french-over-english").pop("detectedTargetLanguage"),
             "detected_target_mismatch"),
            ("explicit advisory witness names the selection", "clone-explicit-english-over-japanese",
             lambda: receipt("clone-explicit-english-over-japanese").update(detectedTargetLanguage="english"),
             "detected_target_mismatch"),
            ("explicit unsupported text names a target", "custom-explicit-english-over-dutch",
             lambda: receipt("custom-explicit-english-over-dutch").update(detectedTargetLanguage="german"),
             "detected_target_unexpected"),
            ("explicit take without its language token", "custom-explicit-japanese",
             lambda: receipt("custom-explicit-japanese").update(languageTokenMode="nothink"), "token_mode_mismatch"),
            ("explicit take fell back to auto", "custom-explicit-english-over-dutch",
             lambda: speak("custom-explicit-english-over-dutch", "auto"), "token_mode_mismatch"),
        ]
        for name, take_id, mutate, issue in cases:
            with self.subTest(case=name):
                self.rows, self.records = self.passing_fixture()
                mutate()
                code, summary = self.run_main()
                self.assertEqual(code, 1)
                self.assertEqual(summary["result"], "fail")
                take = self.take_summary(summary, take_id)
                self.assertIn(issue, take["issues"])
                others = [t["takeID"] for t in summary["takes"] if t["issues"] and t["takeID"] != take_id]
                self.assertEqual(others, [])

    def test_observations_do_not_fail_the_run(self):
        def mutate_clone():
            self.rows["clone-french"][-1]["notes"]["languageHint"] = "english"

        def mutate_edge():
            self.rows["custom-undetected"][-1].update(finishReason="max_tokens", audioQC={"verdict": "fail"})
            self.rows["custom-undetected"][-1]["notes"]["quality_registry_outcome"] = "fail"

        def mutate_advisory():
            self.rows["custom-korean"][-1]["requestReceipt"].pop("detectedTargetLanguage")

        def mutate_explicit_advisory():
            self.rows["clone-explicit-english-over-japanese"][-1]["requestReceipt"].pop("detectedTargetLanguage")

        def mutate_explicit_edge():
            self.rows["custom-explicit-english-over-dutch"][-1].update(finishReason="max_tokens")

        cases = [
            (mutate_clone, "clone-french", {"clone_language_hint_differs"}),
            (mutate_edge, "custom-undetected", {"finish_not_eos", "fast_qc_failed", "audio_qc_failed"}),
            (mutate_advisory, "custom-korean", {"detected_target_absent"}),
            # Without the recognizer's witness there is no override to prove, and nothing fails.
            (mutate_explicit_advisory, "clone-explicit-english-over-japanese", {"detected_target_absent"}),
            (mutate_explicit_edge, "custom-explicit-english-over-dutch", {"finish_not_eos"}),
        ]
        for mutate, take_id, expected in cases:
            with self.subTest(take=take_id):
                self.rows, self.records = self.passing_fixture()
                mutate()
                code, summary = self.run_main()
                self.assertEqual(code, 0)
                take = self.take_summary(summary, take_id)
                self.assertEqual(take["issues"], [])
                self.assertTrue(expected.issubset(take["observations"]), take["observations"])
                if take_id == "clone-explicit-english-over-japanese":
                    self.assertNotIn("explicit_selection_overrode_detection", take["observations"])

    def test_explicit_failures_withhold_the_override_observation(self):
        def receipt(take_id):
            return self.rows[take_id][-1]["requestReceipt"]

        take_id = "custom-explicit-french-over-english"
        # The engine followed the script's language: the override is not proven.
        receipt(take_id).update(language="english", finalModelLanguage="english")
        self.rows[take_id][-1]["notes"]["languageHint"] = "english"
        code, summary = self.run_main()
        self.assertEqual(code, 1)
        take = self.take_summary(summary, take_id)
        self.assertIn("engine_language_mismatch", take["issues"])
        self.assertNotIn("explicit_selection_overrode_detection", take["observations"])
        # An explicit take names its own stored-selection issue, never the Auto one.
        self.rows, self.records = self.passing_fixture()
        receipt(take_id).update(storedLanguageSelection="auto")
        code, summary = self.run_main()
        self.assertEqual(code, 1)
        take = self.take_summary(summary, take_id)
        self.assertEqual(take["issues"], ["stored_selection_mismatch"])
        # An Auto take keeps its original name for the same drift.
        self.rows, self.records = self.passing_fixture()
        receipt("custom-french").update(storedLanguageSelection="french")
        code, summary = self.run_main()
        self.assertEqual(self.take_summary(summary, "custom-french")["issues"], ["stored_selection_not_auto"])

    def test_manifest_identity_errors_fail_closed(self):
        def conflicting():
            changed = copy.deepcopy(self.records["custom-english"])
            changed["chip"]["stable"] = False
            self.extra_lines.append(self.manifest_line(changed))

        def unknown():
            record = copy.deepcopy(self.records["custom-english"])
            record.update(takeID="custom-dutch", generationID=generation_id(500))
            self.extra_lines.append(self.manifest_line(record))

        def reused():
            self.records["custom-french"]["generationID"] = self.records["custom-english"]["generationID"]

        def oversized():
            self.extra_lines.append(self.manifest_line(self.records["custom-english"]) + " " + "x" * 9000)

        cases = [
            ("duplicate conflicting", conflicting, "conflicting manifest records"),
            ("unknown take", unknown, "unknown take"),
            ("run drift", lambda: self.records["custom-english"].update(runID="another-run"), "run identity"),
            ("plan drift", lambda: self.records["custom-english"].update(planDigest="0" * 64), "plan identity"),
            ("reused generation", reused, "reused"),
            ("private text", lambda: self.records["custom-english"].update(text="private"), "private field"),
            ("private transcript", lambda: self.records["custom-english"]["chip"].update(transcript="private"),
             "private field"),
            ("private error", lambda: self.records["custom-english"].update(error="raw"), "private field"),
            ("oversized line", oversized, "exceeds 8192 bytes"),
            ("uppercase generation", lambda: self.records["custom-english"].update(
                generationID=generation_id(1).upper()), "lowercase UUID"),
            ("unknown field", lambda: self.records["custom-english"].update(attempt=2), "schema v1"),
            ("expected chip drift", lambda: self.records["custom-english"]["chip"].update(expectedValue="Auto"),
             "expected a different chip"),
            ("mode drift", lambda: self.records["custom-english"].update(mode="design"), "planned mode"),
            ("not base64 JSON", lambda: self.extra_lines.append("VOCELLO_AUTO_LANGUAGE_TAKE=bm90IGpzb24="),
             "not base64 JSON"),
        ]
        for name, mutate, message in cases:
            with self.subTest(case=name):
                self.rows, self.records = self.passing_fixture()
                self.extra_lines = []
                mutate()
                with self.assertRaisesRegex(MODULE.ContractError, message):
                    self.validate_direct()
        self.rows, self.records = self.passing_fixture()
        self.extra_lines = []
        reused()
        output = self.root / "contract-summary.json"
        code, summary = self.run_main(output=output)
        self.assertEqual(code, 2)
        self.assertEqual(summary, {})

    def test_identical_echoes_collapse(self):
        self.extra_lines = [self.manifest_line(self.records["custom-english"])] * 3
        code, summary = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(summary["counts"]["manifestRecords"], 22)

    def test_visible_error_takes_fall_back_to_the_prompt_digest(self):
        # A required take with a visible error: matched by digest, still a failure.
        self.records["custom-french"].update(generationID=None, visibleErrorShown=True)
        # An edge take without the audio requirement: matched by digest, observed only.
        self.records["design-undetected"].update(generationID=None, visibleErrorShown=True)
        code, summary = self.run_main()
        self.assertEqual(code, 1)
        french = self.take_summary(summary, "custom-french")
        self.assertEqual(french["correlation"], "digest")
        self.assertEqual(french["issues"], ["visible_error"])
        self.assertEqual(french["observed"]["finalModelLanguage"], "french")
        edge = self.take_summary(summary, "design-undetected")
        self.assertEqual(edge["correlation"], "digest")
        self.assertEqual(edge["issues"], [])
        self.assertIn("visible_error", edge["observations"])
        self.assertEqual(summary["counts"]["digestCorrelatedTakes"], 2)
        # A digest match never takes a row another take's generation already owns.
        self.rows.pop("design-undetected")
        code, summary = self.run_main()
        edge = self.take_summary(summary, "design-undetected")
        self.assertEqual(edge["correlation"], "none")
        self.assertIn("no_engine_row", edge["issues"])

    def test_rows_not_yet_present_exit_75(self):
        output = self.root / "pending-summary.json"
        log_path, diagnostics = self.write_run(self.root / "pending")
        (diagnostics / "engine" / "generations.jsonl").unlink()
        command = ["validate", "--plan", str(self.plan_path), "--xcodebuild-log", str(log_path),
                   "--diagnostics", str(diagnostics), "--run-id", RUN_ID, "--output", str(output)]
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(MODULE.main(command), 75)
        other = self.row(self.takes["custom-french"], 3, run_id="another-run")
        (diagnostics / "engine" / "generations.jsonl").write_text(
            json.dumps(other) + "\n" + json.dumps(self.rows["custom-english"][-1]), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(MODULE.main(command), 75)
        self.assertIn("run ID", errors.getvalue())
        self.assertFalse(output.exists())
        # A malformed row that belongs to this run is a contract error, not a wait.
        (diagnostics / "engine" / "generations.jsonl").write_text(
            '{"notes": {"benchRunID": "' + RUN_ID + '"}, "requestReceipt": {"schema\n', encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(MODULE.main(command), 2)
        self.assertIn("of this run is not JSON", errors.getvalue())

    def test_retained_rows_reproduce_the_verdict(self):
        retained = self.root / "retained"
        for mutate, expected in ((lambda: None, 0),
                                 (lambda: self.rows["custom-korean"][-1]["notes"].update(promptDigest="0" * 64), 1)):
            with self.subTest(expected=expected):
                self.rows, self.records = self.passing_fixture()
                mutate()
                first, second = self.root / "first.json", self.root / "second.json"
                code, summary = self.run_main("--retain-rows", str(retained), output=first)
                self.assertEqual(code, expected)
                rows = [json.loads(line) for line in
                        (retained / "engine" / "generations.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(len(rows), 23)  # 22 takes plus custom-english's earlier attempt
                self.assertTrue(all(row["notes"]["benchRunID"] == RUN_ID for row in rows))
                log_path = self.root / "xcodebuild.log"
                with contextlib.redirect_stdout(io.StringIO()):
                    again = MODULE.main(["validate", "--plan", str(self.plan_path), "--xcodebuild-log", str(log_path),
                                         "--diagnostics", str(retained), "--run-id", RUN_ID,
                                         "--output", str(second)])
                self.assertEqual(again, expected)
                self.assertEqual(first.read_bytes(), second.read_bytes())
                self.assertEqual(summary["result"], "pass" if expected == 0 else "fail")


if __name__ == "__main__":
    unittest.main()
