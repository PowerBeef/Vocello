#!/usr/bin/env python3
"""Injector and fixture goldens of the audio-QC qualification engine (audit section 5.2).

Every digest is SHA-256 over canonical PCM16, so a last-place floating-point
difference between hosts cannot move it. A changed digest means a changed
injector or fixture: bump its version and replace the golden in the same change.
"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.qc_qualification import fixtures, injectors, pcm  # noqa: E402

SEED = 7
SOURCE_DIGEST = "bde6268d7471968ad162374db3e3eaf8598eb4394aaa4b88369005bdf30847c1"
GOLDENS = {
    ("SIG-CLICK@1", "sham"): SOURCE_DIGEST,
    ("SIG-CLICK@1", "mild"): "b3aba73e828f33f054733aa0b9af4b234c4dfe36bc8a916fae18a016ebed8124",
    ("SIG-CLICK@1", "moderate"): "b54ed8fa1cb82a334ad798678c63c5986390a279ad78a623e695f3c522214517",
    ("SIG-CLICK@1", "severe"): "7ffd02422f1da49d32fb23ff55737ddd466f0ac22c3ac1fc4f3557ece3794f37",
    ("SIG-CLICK@1", "quiet-clustered"): "be807902a1232889750827a428882878fbb9a772d8f0e4e613a0985cdac86efe",
    ("SIG-DROP@1", "sham"): SOURCE_DIGEST,
    ("SIG-DROP@1", "control-natural-pause"): "9dfc2321e8ba241a3b92459401d0f33d64e35e879d2a1a040ea5b8d0fa09167e",
    ("SIG-DROP@1", "mild"): "0005331909761b54553c56e5b862876d3a6d49f21f836462962247f9bbfc951e",
    ("SIG-DROP@1", "moderate"): "616a32afd5c078efbd7e31e9cfba344a6f0748e5914cdf34d71493fa37378dd8",
    ("SIG-DROP@1", "severe"): "52413029787581befdf199fa8106e0682782992f157192d1821d2feabc1c28eb",
    ("SIG-DROP@1", "attenuated-ramped"): "d9fb93e3a2ebcc4249292efa250ffc09d1093f3f06df7e2bf58cfd74049e9a72",
    ("SIG-CLIP@1", "sham"): "167ee54f190ab4cc5fa6a2e9899c029bf1515b26c3201bbce74a85b4d47c5d1c",
    ("SIG-CLIP@1", "mild"): "609c81f432d1970b082f52727571f86ac184064752d7668efed1f2afdd1996dd",
    ("SIG-CLIP@1", "moderate"): "863116d6afa18e9b9575ae029a82789a94caf0a047fd1b7785233a59f5789dc5",
    ("SIG-CLIP@1", "severe"): "b0f11a0b8a11ac18ddc33226904c3ed83205fd59c336044a325354579088e154",
    ("SIG-CLIP@1", "tanh-moderate"): "15147ea96f6203eb023e9abf52cf3e2c1e95c4291ce344f8f8026cedb3b9dd07",
    ("SIG-CLIP@1", "overdrive-moderate"): "1bab426718816f14f465ab5e94cdbd2d5726cb7caf18b281fa6393eb547d3394",
    ("SIG-DC@1", "sham"): SOURCE_DIGEST,
    ("SIG-DC@1", "mild"): "acbb2620b03134bf43e05f74c4f570b32516e017cce88a3e0483765bb20fc380",
    ("SIG-DC@1", "moderate"): "8954c1504f297f4c75c4901598c49be9fdefe24eae4460d915299689a3ba457e",
    ("SIG-DC@1", "severe"): "bae21695ea566601a8ba740ee0568d3f5aaadebd23c52f75b7606b46a6e117d8",
    ("SIG-LEVEL@1", "sham"): SOURCE_DIGEST,
    ("SIG-LEVEL@1", "mild"): "961e2346bd5a851631882df5514b6e0021b9bafd8fce9c339ce4eeae79653a34",
    ("SIG-LEVEL@1", "moderate"): "cfc2a769acc92f3001c1d5421a4bcfeef263914ad9f51f444f17b9c6fcc52f47",
    ("SIG-LEVEL@1", "severe"): "1f0a4539121f8cf0117f724e92ff0fe0ae3a4c29c5f797c4f61fbdbdb4417037",
    ("SIG-NOISE@1", "sham"): SOURCE_DIGEST,
    ("SIG-NOISE@1", "control-80db"): "f86ce0f2602d9a2da8233d9099ca1124db28c0d420637b9a1ee59d8fb0e90076",
    ("SIG-NOISE@1", "mild"): "a52086b1382bfc878e4284518a91ffa071b614db50c69ad12bbd08255d0da5a1",
    ("SIG-NOISE@1", "moderate"): "f2f294b3820e283c00f58023f7761da07e62c3775ce4faaa6213872724d13b23",
    ("SIG-NOISE@1", "severe"): "0af080bf11d961686a07a5022a1cd3091193e7690567f59f1a8fd33dd35a8c03",
    ("SIG-NOISE@1", "hum-moderate"): "373df0d5d984e86c1ff8cc7633ca8988023c6c63952a72c506323c26af673893",
    ("SIG-SIL@1", "sham"): SOURCE_DIGEST,
    ("SIG-SIL@1", "mild"): "deccca1ef863c034b90c372853736727d1b003b38efb81183516b4de9e4bc011",
    ("SIG-SIL@1", "moderate"): "9609ed4755fa62206dd75ed886b520eadb67d01913382271e2d13e9ac8d0edba",
    ("SIG-SIL@1", "severe"): "ad0e92049fcbf8d2e9bff79f327fa9b98efdc3fe69dfa5c90a7ca0da930fb311",
    ("SIG-SIL@1", "leading-moderate"): "efe355a5f2d14455b541ded46817aaf77de23972d4d83d0c927501cdfe6addfd",
    ("BND-TRUNC@1", "sham"): "1dfd31ea6b918c545f7fca9f22fb0e416e2ceeaa6c310d1c3354c8e6a61481c7",
    ("BND-TRUNC@1", "mild"): "8e5a6d40497958c9c788ba071f8ee6f92d586494327e58870387165c48f9258e",
    ("BND-TRUNC@1", "moderate"): "731159b2fef70e2dda386f960b9db9a267504da7e2bbf6b8aa97e53f80e7f81d",
    ("BND-TRUNC@1", "severe"): "43a454d0568aa4788480e2a53f5b08a8b4b67df861a31e43aa25543630a876fa",
    ("BND-RUNON@1", "sham"): "fefce421e35ac575b0b8a7bcb2281ba91ce433b9bb79a8d9ba03d5cc6f3512b6",
    ("BND-RUNON@1", "mild"): "e10e7693b2c2aafe3201af0b99b5594513d67220458af7eda45bcbe8ed31348d",
    ("BND-RUNON@1", "moderate"): "f08c9d426167f4497949aab1f26cbab5fd910b980a96cf101789f614917461f1",
    ("BND-RUNON@1", "severe"): "b4678f5d55faf758f6510f5c05d2242ebb1d540f45c2e9aebfa41d7d106777f8",
    ("BND-RUNON@1", "reversed-moderate"): "54f84a5c3325ba74a962c5d5e73f1710141f7934d144e2d0e5f68b13a965dc5d",
    ("CNT-REP@1", "sham"): "4fbb82dc2e0e588765baf9aabc7542b5677e0b5a6ba1877c463998d1db9099b3",
    ("CNT-REP@1", "mild"): "3778ecec77fe46b712254c6c7e5d1528465281134bf1c131c74f4c0819e6eaaf",
    ("CNT-REP@1", "moderate"): "79898352b6ae4ed4ad20d1b0a96d69f8723ae56ed36282b9c66d802be88053cf",
    ("CNT-REP@1", "severe"): "21d6107beef6cf47ab738e1d8ae954982eb720cb36db8ec599f9ea79320ddc3d",
    ("CNT-DEL@1", "sham"): "8dce5fba12118020f974ff520306f0747734418f1522ca542b67884f88d35b38",
    ("CNT-DEL@1", "mild"): "929666389fedc4d4cfa9ebe72c59400748cd3a38bc017585a8db35861dbe90be",
    ("CNT-DEL@1", "moderate"): "7278737a2a75b6c4a9b37acd547f0e2d8a7e2ffeac1b2d65222135f2a7cda799",
    ("CNT-DEL@1", "severe"): "6b4a4b56bbd7bd2addec82600fd5f7a4208db435e53262eb910ebd747b39ae7a",
    ("CNT-INS@1", "sham"): "15884bfa9644f480330bc9f359ec9e82ba20b089a2ac376faf62cf44943ca374",
    ("CNT-INS@1", "mild"): "f9ca1e8d1b1b200c2e03f9faba5679c34510a1c619b46a68e3d23ab7ae0923f9",
    ("CNT-INS@1", "moderate"): "fcfe050340f0bc5fe9132cfce1ff6ff4f7a90cc278f939a802e6703920b97b7c",
    ("CNT-INS@1", "severe"): "50a69122dd44fb18d67113a518e26b4870cad1751c02457c0ff721fc97880420",
    ("PRS-OCT@1", "sham"): SOURCE_DIGEST,
    ("PRS-OCT@1", "mild"): "4e91eb2970c943cfcebe8fff3d03209583b15041820eda029c1768d87539dca1",
    ("PRS-OCT@1", "moderate"): "2e1ff9405549ab6b4b4e90c9b5343112567d222a34c1e9b711c0317624722017",
    ("PRS-OCT@1", "severe"): "e0726e69394af157592705d3dbf7305186b45643073d530c66a7695897b4b56e",
    ("PRS-OCT@1", "down-moderate"): "37eebc5632ea8d8431dce8abd1087fcc3a305f1cd3f0ce966b08f84a21637a98",
    ("PRS-BRK@1", "sham"): SOURCE_DIGEST,
    ("PRS-BRK@1", "mild"): "07f3e09008bad2cab5d4658aeccf4b2954edd61d9f4b9cf5f66fcb55bc56ea82",
    ("PRS-BRK@1", "moderate"): "c0e163587fd95c136ad70198786b7fc8ee2aa25c14a78dc6f587ee7d8703da59",
    ("PRS-BRK@1", "severe"): "40ff5b5c277685d56d25c0f5158bab2e3a16e7dcfc67375c6056e56b896bb060",
    ("PRS-RATE@1", "sham"): SOURCE_DIGEST,
    ("PRS-RATE@1", "mild"): "bc130c8cb87e6e7b13157878e7f59c6329ab51654c9700ec444ce968d4da6877",
    ("PRS-RATE@1", "moderate"): "5bf90e6f12d8e02c9e1ce1461cc54f1ad6aa635d8907f9ba4db1266f30363a26",
    ("PRS-RATE@1", "severe"): "bda564253a7a6d9d1bbb761ce36bd50221a515568cc31dd06d56e3e6f38acb4f",
    ("PRS-RATE@1", "fast-severe"): "c4687e05aa3049736d222ceef3f65e3e7f6ccc7cb117625b3149351a69e225c7",
    ("IDN-SHIFT@1", "sham"): SOURCE_DIGEST,
    ("IDN-SHIFT@1", "mild"): "ff880e83263eef01f6f654d3e521136a2d09d78cb80624623bbeffd5cbee826d",
    ("IDN-SHIFT@1", "moderate"): "8caf54490a7acf39a48e2e947ec74dc28740af63f22693f0fac9ff36c0631c17",
    ("IDN-SHIFT@1", "severe"): "3a002158b5b38623fe21b1443284df4b27db4d3a577b4ef6f79fbb8da51c1e90",
    ("IDN-SWAP@1", "sham"): SOURCE_DIGEST,
    ("IDN-SWAP@1", "control-same-speaker"): "9b86826c3413e6597f8b52561d5bdf8659e83c895c676b1d4b3023cb862d8ecf",
    ("IDN-SWAP@1", "mild"): "0eda0143daf113f16419317618dba19657f85ed5ad0a31174586fd309e433bac",
    ("IDN-SWAP@1", "moderate"): "edead46a736634476ff0ccfdab3c0b3faeeae827f98f2bde0598162d86eb0641",
    ("IDN-SWAP@1", "severe"): "3f86dcf3fd8f1b03d21576378153ff559bd882ebf4a70965b9b1d9900e00f3e4",
}
FIXTURE_GOLDENS = {
    "modal": "08a40198714b6b152e1694c97a5f71d6873ad9265a966692e81a492ba7410111",
    "quiet": "5734b4c5d89e951027708fa79fd5f3f19a9356f3ad0bbcff238ac90e6ed983a2",
    "breathy": "53db81fa0a39f14ef871fad8016d0c2679cc9bf6e9433acbc344bf9cf394f28d",
    "long-pause": "e5fa0637af6bbe9a7f3b88e147b34cbe39ab1125afaa6cc7a79249e845bdd0c9",
    "high-f0": "0601268f10225643080aba5f169ac69cfe1a245958ec5c113b16c995d2837529",
}
# The families the task and the audit's section 5.2 require of the T1 catalog.
REQUIRED_FAMILIES = {
    "BND-TRUNC", "BND-RUNON", "CNT-REP", "CNT-DEL", "CNT-INS", "SIG-CLICK", "SIG-DROP", "SIG-CLIP",
    "SIG-NOISE", "PRS-OCT", "PRS-BRK", "IDN-SWAP", "PRS-RATE", "IDN-SHIFT",
}


class InjectorTests(unittest.TestCase):
    source: fixtures.Fixture

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = fixtures.clean_fixture(0, "modal")

    def test_the_catalog_covers_the_defect_families(self) -> None:
        self.assertTrue(REQUIRED_FAMILIES <= set(injectors.CATALOG))
        for injector in injectors.CATALOG.values():
            severities = {variant.severity for variant in injector.variants}
            self.assertEqual(injector.variants[0].name, "sham", injector.key)
            self.assertTrue({"sham", "mild", "moderate", "severe"} <= severities, injector.key)
            self.assertTrue(set(injector.classes) <= set("ABCDEFGHIJ"), injector.key)
            names = [variant.name for variant in injector.variants]
            self.assertEqual(len(names), len(set(names)), injector.key)
        self.assertEqual(set(GOLDENS), {(injector.key, variant.name) for injector in injectors.CATALOG.values()
                                        for variant in injector.variants})

    def test_every_variant_matches_its_golden_digest(self) -> None:
        self.assertEqual(self.source.digest, SOURCE_DIGEST)
        for (key, variant), expected in GOLDENS.items():
            injection = injectors.inject(key.split("@")[0], variant, self.source, SEED)
            self.assertEqual(injection.digest, expected, f"{key} {variant}")

    def test_same_input_seed_and_parameters_are_byte_identical(self) -> None:
        for injector in injectors.CATALOG.values():
            severe = [variant.name for variant in injector.variants if variant.severity == "severe"][0]
            first = injectors.inject(injector.injector_id, severe, self.source, SEED)
            second = injectors.inject(injector.injector_id, severe, self.source, SEED)
            self.assertEqual(first.samples.tobytes(), second.samples.tobytes(), injector.key)
            self.assertEqual(first.recipe(), second.recipe(), injector.key)
        other = injectors.inject("SIG-CLICK", "moderate", self.source, SEED + 1)
        self.assertNotEqual(other.digest, GOLDENS[("SIG-CLICK@1", "moderate")])

    def test_shams_label_nothing_and_positives_label_their_interval(self) -> None:
        for injector in injectors.CATALOG.values():
            for variant in injector.variants:
                injection = injectors.inject(injector.injector_id, variant.name, self.source, SEED)
                if variant.severity in injectors.NON_DEFECT_SEVERITIES:
                    self.assertFalse(injection.positive)
                    self.assertEqual(injection.labels, (), f"{injector.key} {variant.name}")
                    continue
                self.assertTrue(injection.positive)
                self.assertTrue(injection.labels, f"{injector.key} {variant.name}")
                for label in injection.labels:
                    self.assertLessEqual(0, label["startSample"])
                    self.assertLessEqual(label["startSample"], label["endSample"])
                    self.assertLessEqual(label["endSample"], injection.samples.size)

    def test_labels_are_exact(self) -> None:
        source = self.source
        clicks = injectors.inject("SIG-CLICK", "moderate", source, SEED)
        sham = injectors.inject("SIG-CLICK", "sham", source, SEED)
        difference = np.flatnonzero(clicks.samples != source.samples)
        self.assertEqual(sorted({int(index) for index in difference}),
                         [label["startSample"] for label in clicks.labels])
        self.assertTrue(np.array_equal(sham.samples, source.samples))
        dropout = injectors.inject("SIG-DROP", "moderate", source, SEED)
        (label,) = dropout.labels
        self.assertEqual(label["endSample"] - label["startSample"], 14_400)
        self.assertTrue(np.all(dropout.samples[label["startSample"]:label["endSample"]] == 0.0))
        self.assertTrue(np.array_equal(dropout.samples[:label["startSample"]], source.samples[:label["startSample"]]))
        truncation = injectors.inject("BND-TRUNC", "moderate", source, SEED)
        (cut,) = truncation.labels
        self.assertEqual(truncation.samples.size, cut["startSample"])
        self.assertEqual(cut["removedSamples"], source.samples.size - truncation.samples.size)
        silence = injectors.inject("SIG-SIL", "moderate", source, SEED)
        self.assertEqual(silence.samples.size - source.samples.size, 60_000)
        self.assertEqual(silence.labels[0]["startSample"], source.samples.size)
        swap = injectors.inject("IDN-SWAP", "moderate", source, SEED)
        (span,) = swap.labels
        self.assertEqual(span["startSample"], source.words[0][0])
        outside = np.r_[0:span["startSample"], span["endSample"]:source.samples.size]
        self.assertTrue(np.array_equal(swap.samples[outside], source.samples[outside]))

    def test_splices_change_length_by_the_edited_content(self) -> None:
        source = self.source
        cuts = injectors.boundaries(source)
        fade = 120
        deletion = injectors.inject("CNT-DEL", "mild", source, SEED)
        middle = (len(source.words) - 1) // 2
        removed = cuts[middle + 1] - cuts[middle]
        self.assertEqual(deletion.labels[0]["deletedSamples"], removed)
        self.assertEqual(source.samples.size - deletion.samples.size, removed + fade)
        repetition = injectors.inject("CNT-REP", "moderate", source, SEED)
        self.assertGreater(repetition.samples.size, source.samples.size)
        sham = injectors.inject("CNT-DEL", "sham", source, SEED)
        self.assertEqual(source.samples.size - sham.samples.size, 2 * fade)
        run_on = injectors.inject("BND-RUNON", "severe", source, SEED)
        (label,) = run_on.labels
        self.assertGreaterEqual(label["endSample"] - label["startSample"], 4 * 24_000 - 10 * fade)

    def test_pitch_and_rate_changes_keep_or_scale_length(self) -> None:
        source = self.source
        for key in ("PRS-OCT", "PRS-BRK", "IDN-SHIFT"):
            self.assertEqual(injectors.inject(key, "severe", source, SEED).samples.size, source.samples.size, key)
        slower = injectors.inject("PRS-RATE", "severe", source, SEED)
        self.assertEqual(slower.samples.size, round(source.samples.size / 0.7))
        tone = np.sin(2 * np.pi * 200.0 * np.arange(24_000) / 24_000)
        shifted = injectors.pitch_shift(tone, 12.0)
        spectrum = np.abs(np.fft.rfft(shifted[4_000:20_000] * np.hanning(16_000)))
        self.assertAlmostEqual(np.argmax(spectrum) * 24_000 / 16_000, 400.0, delta=3.0)
        self.assertTrue(np.allclose(injectors.resample(tone, 1.0), tone, atol=1e-12))

    def test_recipes_bind_source_injector_and_output(self) -> None:
        injection = injectors.inject("SIG-NOISE", "moderate", self.source, SEED)
        recipe = injection.recipe()
        self.assertEqual(recipe["sourcePCMSHA256"], SOURCE_DIGEST)
        self.assertEqual(recipe["outputPCMSHA256"], GOLDENS[("SIG-NOISE@1", "moderate")])
        self.assertEqual((recipe["injector"], recipe["catalogVersion"], recipe["seed"]), ("SIG-NOISE@1", 1, SEED))
        self.assertEqual(recipe["mechanism"], "T1-pcm-construction")
        description = injectors.catalog_description()
        self.assertEqual(len(description["injectors"]), len(injectors.CATALOG))


class FixtureTests(unittest.TestCase):
    def test_clean_fixtures_are_pinned(self) -> None:
        for stratum, digest in FIXTURE_GOLDENS.items():
            fixture = fixtures.clean_fixture(3, stratum)
            self.assertEqual(fixture.digest, digest, stratum)
            self.assertEqual(fixture.digest, pcm.pcm_digest(fixture.samples))
            self.assertFalse(fixture.samples.flags.writeable)
            self.assertEqual(fixture.family, f"proc-script-{stratum}-0003")
        long_pause = fixtures.clean_fixture(3, "long-pause")
        self.assertTrue(any(end - start >= 0.9 * 24_000 for start, end in long_pause.pauses))

    def test_donor_renders_are_time_aligned(self) -> None:
        source = fixtures.clean_fixture(1, "modal")
        donor = fixtures.rerender(source, fixtures.donor_voice(source.voice, "cross-gender"))
        self.assertEqual(donor.size, source.samples.size)
        self.assertTrue(np.array_equal(fixtures.rerender(source, source.voice), source.samples))

    def test_abstention_fixtures(self) -> None:
        built = {kind: fixtures.abstention_fixture(kind) for kind in fixtures.ABSTENTION_KINDS}
        self.assertTrue(np.all(built["digital-silence"].samples == 0.0))
        self.assertEqual(int(np.isnan(built["nan-bearing"].samples).sum()), 16)
        self.assertLess(built["short-clip"].duration_seconds, 1.0)
        self.assertGreaterEqual(built["long-take"].duration_seconds, 60.0)
        words = {word.strip(",.") for word in built["repeated-word"].text.split()}
        self.assertEqual(len(words), 1)
        self.assertTrue(any(end - start >= 2.4 * 24_000 for start, end in built["explicit-long-pause"].pauses))
        with self.assertRaises(ValueError):
            fixtures.abstention_fixture("jazz")

    def test_pcm_digest_and_seeded_streams(self) -> None:
        self.assertEqual(pcm.to_pcm16(np.array([0.5 / 32767, -0.5 / 32767, 2.0, np.nan])).tolist(),
                         [1, -1, 32767, 0])
        self.assertNotEqual(pcm.pcm_digest(np.array([0.0, np.nan])), pcm.pcm_digest(np.array([0.0, 0.0])))
        first = pcm.SeededStream(4, "a").uniform(5)
        self.assertTrue(np.array_equal(first, pcm.SeededStream(4, "a").uniform(5)))
        self.assertFalse(np.array_equal(first, pcm.SeededStream(4, "b").uniform(5)))
        # PCG64 raw words are the stable part of NumPy's random API: pin the first draws.
        self.assertEqual(pcm.SeededStream(0, "pin").integers(1_000_000, 3).tolist(), [330923, 768800, 957133])
        self.assertEqual(pcm.SeededStream(0, "pin").uniform(2).tolist(), [0.3309236229676439, 0.7688001029704082])
        with self.assertRaises(ValueError):
            pcm.SeededStream(-1)


if __name__ == "__main__":
    unittest.main()
