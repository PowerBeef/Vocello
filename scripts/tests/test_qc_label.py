"""QC v2 labels: the batch sampler, the listening page server, the export summary and kappa."""

from __future__ import annotations

import http.client
import json
import random
import sys
import tempfile
import threading
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from qc import label, store  # noqa: E402
from qc.store import Layout  # noqa: E402

VOICES = {"custom": ["aiden", "serena", "dylan"], "design": ["design-calm"], "clone": ["clone-ref1", "clone-ref2"]}
CELLS = {"custom": ["standard", "cross-lingual"], "design": ["standard"], "clone": ["clone"]}


def synthetic_manifest(source: str, languages=("french", "english", "german"), scripts=20) -> dict:
    takes = []
    for language in languages:
        for script in range(scripts):
            family = f"{language[:2]}-{script:04d}"
            for mode, voices in VOICES.items():
                for voice in voices:
                    cell = CELLS[mode][script % len(CELLS[mode])]
                    take_id = f"{family}--{voice}"
                    takes.append({
                        "takeID": take_id, "token": store.take_token(source, take_id), "audio": f"/nonexistent/{take_id}.wav",
                        "audioSHA256": store.sha256_text(source + take_id), "language": language, "text": f"script {family}",
                        "mode": mode, "voice": voice, "cell": cell, "reference": None, "referenceSHA256": None,
                        "referenceText": None, "finishReason": "eos", "seed": 1, "family": family,
                    })
    return {"schema": store.TAKES_SCHEMA, "source": source, "takes": takes}


class SamplerTests(unittest.TestCase):
    def setUp(self):
        self.manifests = [synthetic_manifest("run-a"), synthetic_manifest("run-b")]
        by_id = {take["takeID"]: take for take in self.manifests[0]["takes"]}
        self.enriched_ids = sorted(take_id for take_id in by_id if take_id.endswith("--dylan"))[:30]
        self.enrichment = {(None, take_id): {"reasons": ["register-outlier"], "certain": False}
                           for take_id in self.enriched_ids}
        self.enrichment[("run-a", "fr-0003--serena")] = {"reasons": ["named"], "certain": True}

    def sample(self, **overrides):
        options = dict(name="batch-1", size=96, languages=["french", "english"], enrichment=self.enrichment,
                       blind=0.1, seed=7)
        options.update(overrides)
        return label.sample_batch(self.manifests, **options)

    def primaries(self, batch):
        return [item for item in batch["items"] if item["repeatOf"] is None]

    def test_size_languages_and_enrichment_share(self):
        batch = self.sample()
        primaries = self.primaries(batch)
        self.assertLessEqual(len(primaries), 96)
        self.assertGreaterEqual(len(primaries), 90)  # overlaps of the two parts only
        languages = Counter(batch["takes"][item["takeToken"]]["language"] for item in primaries)
        self.assertEqual(set(languages), {"french", "english"})
        self.assertLessEqual(abs(languages["french"] - languages["english"]), 4)
        enriched = [item for item in primaries if item["enriched"]]
        self.assertTrue(30 <= len(enriched) <= 40, len(enriched))
        self.assertTrue(all(item["reasons"] for item in enriched))
        # The certain take is in, with probability 1.
        certain = [item for item in primaries if batch["takes"][item["takeToken"]]["takeID"] == "fr-0003--serena"
                   and item["inclusionProbability"] == 1.0]
        self.assertEqual(len(certain), 1)

    def test_uniform_part_is_stratified(self):
        batch = self.sample(enrichment={})
        primaries = self.primaries(batch)
        modes = Counter((batch["takes"][item["takeToken"]]["language"], batch["takes"][item["takeToken"]]["mode"])
                        for item in primaries)
        for language in ("french", "english"):
            for mode, voices in VOICES.items():
                share = len(voices) / sum(len(v) for v in VOICES.values())
                self.assertAlmostEqual(modes[(language, mode)], 48 * share, delta=1.01)

    def test_inclusion_probabilities(self):
        batch = self.sample()
        population = {language: sum(1 for m in self.manifests for t in m["takes"] if t["language"] == language)
                      for language in ("french", "english")}
        for item in self.primaries(batch):
            take = batch["takes"][item["takeToken"]]
            if item["inclusionProbability"] == 1.0:
                continue
            expected_uniform = (48 - round(0.4 * 48)) / population[take["language"]]
            if item["reasons"]:
                self.assertGreater(item["inclusionProbability"], expected_uniform)
            else:
                self.assertAlmostEqual(item["inclusionProbability"], round(expected_uniform, 6))

    def test_systematic_sampling_is_equal_probability(self):
        population = synthetic_manifest("p", languages=("french",), scripts=10)["takes"][:50]
        counts = Counter()
        rng = random.Random(1)
        rounds = 2000
        for _ in range(rounds):
            for take in label._systematic(population, 10, rng):
                counts[take["token"]] += 1
        self.assertEqual(len(counts), 50)
        for value in counts.values():
            self.assertAlmostEqual(value / rounds, 0.2, delta=0.05)

    def test_family_split_keeps_scripts_together_and_is_stable(self):
        batch = self.sample()
        sides = {}
        for item in self.primaries(batch):
            family = batch["takes"][item["takeToken"]]["family"]
            sides.setdefault(family, set()).add(item["split"])
        self.assertTrue(all(len(value) == 1 for value in sides.values()))
        self.assertEqual({next(iter(value)) for value in sides.values()}, {"train", "heldout"})
        other = self.sample(name="batch-2", seed=99)
        for item in self.primaries(other):
            family = other["takes"][item["takeToken"]]["family"]
            if family in sides:
                self.assertEqual({item["split"]}, sides[family])
        everything = [label.split_for_family(f"fr-{index:04d}") for index in range(2000)]
        self.assertAlmostEqual(everything.count("train") / 2000, 0.6, delta=0.04)

    def test_blind_repeats_come_later_under_a_new_token(self):
        batch = self.sample()
        primaries = self.primaries(batch)
        repeats = [item for item in batch["items"] if item["repeatOf"] is not None]
        self.assertEqual(len(repeats), round(0.1 * len(primaries)))
        positions = {item["token"]: item["order"] for item in batch["items"]}
        tokens = [item["token"] for item in batch["items"]]
        self.assertEqual(len(tokens), len(set(tokens)))
        self.assertEqual([item["order"] for item in batch["items"]], list(range(len(batch["items"]))))
        for repeat in repeats:
            original = next(item for item in primaries if item["token"] == repeat["repeatOf"])
            self.assertEqual(repeat["takeToken"], original["takeToken"])
            self.assertGreater(positions[repeat["token"]], positions[original["token"]])

    def test_same_seed_same_batch(self):
        first, second = self.sample(), self.sample()
        self.assertEqual(first["items"], second["items"])
        self.assertNotEqual([item["token"] for item in self.sample(seed=8)["items"]],
                            [item["token"] for item in first["items"]])

    def test_enrichment_file_shapes(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "qc-takes-run-a"
            run_dir.mkdir()
            sources = {str(run_dir.resolve()): "run-a"}
            lead_shape = {f"a:fr-0001--dylan": {"run": str(run_dir), "takeID": "fr-0001--dylan",
                                                "reasons": ["asr-disagreement", "named"]},
                          "b:fr-0002--aiden": {"run": "/elsewhere/unknown-run", "takeID": "fr-0002--aiden",
                                               "reasons": ["x"]}}
            path = Path(directory) / "enrich.json"
            path.write_text(json.dumps(lead_shape))
            loaded = label.load_enrichment(path, sources)
            self.assertEqual(loaded, {("run-a", "fr-0001--dylan"): {"reasons": ["asr-disagreement", "named"],
                                                                    "certain": False}})
            path.write_text(json.dumps({"fr-0005--serena": "tonal"}))
            self.assertEqual(label.load_enrichment(path, sources),
                             {(None, "fr-0005--serena"): {"reasons": ["tonal"], "certain": False}})

    def test_sample_command_writes_a_private_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            layout = Layout(Path(directory))
            manifest_path = Path(directory) / "takes.json"
            manifest_path.write_text(json.dumps(self.manifests[0]))
            summary = label.sample_command(layout, [str(manifest_path)], name="b1", size=20,
                                           languages=["fr", "en"], enrich_file=None, blind=0.1, seed=1)
            self.assertEqual(summary["takes"], 20)
            self.assertEqual(summary["repeats"], 2)
            self.assertTrue((layout.private / "batches/b1.json").is_file())
            with self.assertRaises(FileExistsError):
                label.sample_command(layout, [str(manifest_path)], name="b1", size=20, languages=["fr"],
                                     enrich_file=None, blind=0.1, seed=1)


class ServeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.layout = Layout(self.root)
        (self.layout.config).mkdir(parents=True)
        (self.layout.config / "protocol.json").write_text((ROOT / "config/qc/protocol.json").read_text())
        audio = self.root / "private-audio"
        audio.mkdir()
        manifest = synthetic_manifest("run-a", languages=("french", "japanese"), scripts=2)
        for take in manifest["takes"]:
            path = audio / f"{take['takeID']}.wav"
            path.write_bytes(b"RIFF" + take["takeID"].encode() * 20)
            take["audio"] = str(path)
            if take["mode"] == "clone":
                reference = audio / f"ref-{take['voice']}.wav"
                reference.write_bytes(b"RIFFreference")
                take["reference"] = str(reference)
        (self.root / "secret.txt").write_text("do not serve")
        batch = label.sample_batch([manifest], name="serve-batch", size=12, languages=["french", "japanese"],
                                   enrichment={(None, "fr-0000--dylan"): {"reasons": ["named-take"], "certain": True}},
                                   blind=0.2, seed=3)
        label.write_batch(self.layout, batch)
        self.batch = batch
        self.server = label.LabelServer(self.layout, batch, port=0, acoustic_only_languages=["ja"])
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.directory.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def post_label(self, payload, content_type="application/json", *, played=1.0):
        if isinstance(payload, dict) and played is not None and "playedFraction" not in payload:
            payload = dict(payload, playedFraction=played)
        return self.request("POST", "/api/label", json.dumps(payload).encode(), {"Content-Type": content_type})

    def item(self, language, *, clone=None):
        for item in self.batch["items"]:
            take = self.batch["takes"][item["takeToken"]]
            if take["language"] == language and item["repeatOf"] is None and (
                    clone is None or (take["mode"] == "clone") == clone):
                return item, take
        raise AssertionError("no item")

    def test_page_and_state_never_reveal_paths_modes_voices_or_reasons(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Vocello QC labels", body)
        self.assertNotIn(b"http://", body.replace(b"http://www.w3.org", b""))  # no external assets
        status, _, body = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        text = body.decode()
        for secret in (str(self.root), "private-audio", "named-take", "clone-ref", "design-calm", "dylan",
                       "custom", "cross-lingual", "inclusionProbability", "takeToken"):
            self.assertNotIn(secret, text)
        state = json.loads(text)
        self.assertEqual(state["total"], len(self.batch["items"]))
        japanese = [item for item in state["items"] if item["language"] == "japanese"]
        self.assertTrue(japanese and all(item["acousticOnly"] and item["text"] is None for item in japanese))
        french = [item for item in state["items"] if item["language"] == "french"]
        self.assertTrue(all(item["text"] for item in french))

    def test_audio_streams_by_token_with_ranges(self):
        item, take = self.item("french", clone=False)
        content = Path(take["audio"]).read_bytes()
        status, headers, body = self.request("GET", f"/audio/{item['token']}")
        self.assertEqual((status, body), (200, content))
        self.assertEqual(headers["Content-Type"], "audio/wav")
        status, headers, body = self.request("GET", f"/audio/{item['token']}", headers={"Range": "bytes=4-9"})
        self.assertEqual((status, body), (206, content[4:10]))
        self.assertEqual(headers["Content-Range"], f"bytes 4-9/{len(content)}")
        clone_item, clone_take = self.item("french", clone=True)
        status, _, body = self.request("GET", f"/reference/{clone_item['token']}")
        self.assertEqual((status, body), (200, b"RIFFreference"))
        status, _, _ = self.request("GET", f"/reference/{item['token']}")
        self.assertEqual(status, 404)

    def test_path_traversal_and_unknown_tokens_are_refused(self):
        item, _ = self.item("french")
        for path in ("/audio/../secret.txt", "/audio/..%2F..%2Fsecret.txt", "/audio/%2e%2e/secret.txt",
                     f"/audio/{item['token']}/../../secret.txt", "/audio/0000000000000000", "/audio/",
                     "/audio/" + "a" * 64, "/secret.txt", f"/{self.root}/secret.txt"):
            with self.subTest(path):
                status, _, body = self.request("GET", path)
                self.assertEqual(status, 404)
                self.assertNotIn(b"do not serve", body)

    def test_labels_append_and_the_latest_wins(self):
        item, _ = self.item("french")
        status, _, body = self.post_label({"token": item["token"], "verdict": "objectionable",
                                           "classes": {"stutter": {"severity": "moderate", "start": 1.25, "end": 0.5}}})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["labelled"], 1)
        status, _, _ = self.post_label({"token": item["token"], "verdict": "acceptable", "classes": {}})
        self.assertEqual(status, 200)
        rows = store.read_jsonl(self.layout.labels / "serve-batch.jsonl")
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(set(first), {"token", "batch", "rater", "classes", "verdict", "acousticOnly", "playedFraction",
                                      "protocolSHA256", "labelledAt"})
        self.assertEqual(first["classes"]["stutter"], {"severity": "moderate", "start": 0.5, "end": 1.25})
        self.assertEqual((first["rater"], first["acousticOnly"], first["playedFraction"]), ("maintainer", False, 1.0))
        self.assertEqual(first["protocolSHA256"], label.protocol_digest(label.load_protocol(self.layout)))
        self.assertEqual(label.latest_labels(self.layout, "serve-batch")[item["token"]]["verdict"], "acceptable")
        state = json.loads(self.request("GET", "/api/state")[2])
        self.assertEqual(state["labels"][item["token"]]["verdict"], "acceptable")

    def test_invalid_labels_are_refused(self):
        french, _ = self.item("french")
        japanese, _ = self.item("japanese")
        cases = [
            ({"token": french["token"], "verdict": "fine", "classes": {}}, 400),
            ({"token": french["token"], "verdict": "acceptable", "classes": {"vibes": {"severity": "mild"}}}, 400),
            ({"token": french["token"], "verdict": "acceptable", "classes": {"cutoff": {"severity": "huge"}}}, 400),
            ({"token": french["token"], "verdict": "acceptable",
              "classes": {"cutoff": {"severity": "mild", "start": -1}}}, 400),
            ({"token": "0" * 16, "verdict": "acceptable", "classes": {}}, 400),
            ({"token": japanese["token"], "verdict": "objectionable",
              "classes": {"mispronunciation": {"severity": "mild"}}}, 400),
            ({"token": french["token"], "verdict": "objectionable", "classes": {"cutoff": {"severity": None}}}, 400),
            ({"token": french["token"], "verdict": "objectionable", "classes": {"cutoff": {}}}, 400),
            ({"token": french["token"], "verdict": "acceptable", "classes": {}, "playedFraction": 0.5}, 400),
            ({"token": french["token"], "verdict": "acceptable", "classes": {}, "playedFraction": True}, 400),
            ({"token": french["token"], "verdict": "acceptable", "classes": {}, "playedFraction": None}, 400),
        ]
        for payload, expected in cases:
            with self.subTest(payload):
                self.assertEqual(self.post_label(payload)[0], expected)
        self.assertEqual(self.post_label({"token": french["token"], "verdict": "acceptable"}, "text/plain")[0], 415)
        status, _, _ = self.request("GET", "/api/state", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        self.assertEqual(store.read_jsonl(self.layout.labels / "serve-batch.jsonl"), [])
        status, _, _ = self.post_label({"token": japanese["token"], "verdict": "objectionable",
                                        "classes": {"artifact": {"severity": "severe", "start": 2.0, "end": None}}})
        self.assertEqual(status, 200)
        self.assertTrue(store.read_jsonl(self.layout.labels / "serve-batch.jsonl")[0]["acousticOnly"])


    def test_a_second_rater_keeps_separate_labels(self):
        item, _ = self.item("french")
        self.assertEqual(self.post_label({"token": item["token"], "verdict": "objectionable",
                                          "classes": {"pause": {"severity": "severe"}}})[0], 200)
        second = label.LabelServer(self.layout, self.batch, port=0, rater="second")
        try:
            self.assertEqual(second.state()["labels"], {})
            second.save({"token": item["token"], "verdict": "acceptable", "classes": {}, "playedFraction": 1})
        finally:
            second.server_close()
        self.assertEqual(label.latest_labels(self.layout, "serve-batch")[item["token"]]["verdict"], "objectionable")
        self.assertEqual(label.latest_labels(self.layout, "serve-batch", "second")[item["token"]]["verdict"], "acceptable")
        with self.assertRaises(ValueError):
            label.LabelServer(self.layout, self.batch, port=0, rater="../x")

    def test_batch_names_skip_other_json(self):
        store.write_json_atomic(self.layout.batches / "batch-1.takes.json", {"schema": "vocello.qc.takes/1", "takes": []})
        self.assertEqual(label.batch_names(self.layout), ["serve-batch"])


class ExportTests(unittest.TestCase):
    def test_cohen_kappa(self):
        self.assertEqual(label.cohen_kappa([("a", "a"), ("a", "a"), ("b", "b"), ("a", "b")]), 0.5)
        self.assertEqual(label.cohen_kappa([("a", "a"), ("b", "b")]), 1.0)
        self.assertEqual(label.cohen_kappa([("a", "b"), ("b", "a")]), -1.0)
        self.assertIsNone(label.cohen_kappa([]))
        self.assertIsNone(label.cohen_kappa([("a", "a"), ("a", "a")]))

    def test_export_counts_and_intra_rater_agreement(self):
        with tempfile.TemporaryDirectory() as directory:
            layout = Layout(Path(directory))
            layout.config.mkdir(parents=True)
            (layout.config / "protocol.json").write_text((ROOT / "config/qc/protocol.json").read_text())
            batch = label.sample_batch([synthetic_manifest("run-a", scripts=4)], name="exp", size=30,
                                       languages=["french", "english"], blind=0.2, seed=5)
            label.write_batch(layout, batch)
            repeats = [item for item in batch["items"] if item["repeatOf"]]
            self.assertGreaterEqual(len(repeats), 4)
            labels_file = layout.labels / "exp.jsonl"
            for index, repeat in enumerate(repeats):
                defect = index % 2 == 0
                original = {"token": repeat["repeatOf"], "verdict": "objectionable" if defect else "acceptable",
                            "classes": {"stutter": {"severity": "moderate", "start": None, "end": None}} if defect else {}}
                # The repeat agrees except on the last pair.
                again = dict(original, token=repeat["token"])
                if index == len(repeats) - 1:
                    again = {"token": repeat["token"], "verdict": "uncertain", "classes": {}}
                for row in (original, again):
                    store.append_jsonl(labels_file, dict(row, batch="exp", rater="maintainer", acousticOnly=False,
                                                         labelledAt="2026-10-01T20:00:00Z"))
            summary = label.export_summary(layout, "exp")
            self.assertEqual(summary["labelled"], len(repeats))
            self.assertEqual(summary["intraRater"]["pairs"], len(repeats))
            self.assertLess(summary["intraRater"]["verdictKappa"], 1.0)
            self.assertGreater(summary["intraRater"]["verdictKappa"], 0.3)
            self.assertEqual(sum(summary["verdicts"].values()), len(repeats))
            self.assertEqual(summary["classes"]["stutter"].get("moderate"), (len(repeats) + 1) // 2)
            self.assertEqual(sum(value["labelled"] for value in summary["languages"].values()), len(repeats))
            rows = label.labelled_takes(layout, "exp")
            self.assertEqual(len(rows), len(repeats))
            self.assertTrue(all(row["item"]["repeatOf"] is None for row in rows))


if __name__ == "__main__":
    unittest.main()
