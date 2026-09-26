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
# Source 1 declares one punctuation pause, which the natural-pause control needs.
SOURCE_INDEX = 1
SOURCE_DIGEST = "d0f9db35ba8a45aa0e8ff6d2802c71bb20ab4d41b5db0a4f5f34cf1b78b2964f"
GOLDENS = {
    ("SIG-CLICK@1", "sham"): SOURCE_DIGEST,
    ("SIG-CLICK@1", "mild"): "72c6e432ba6e42ed19b58bdf98f1ed497c5fe9cc856f00c2d876e2a369154534",
    ("SIG-CLICK@1", "moderate"): "fa108b3ac0c4d8dc8488eeb529567182ed8b85e3d9f919cd931424b5557691b5",
    ("SIG-CLICK@1", "severe"): "242f54bcbadb7a0a2220ea3b3982ed6f24fc7cb74062fae82a152cc6bf251d91",
    ("SIG-CLICK@1", "quiet-clustered"): "78dfb62facb5bfa7c70911d5b71263c62a8d9284b160c38cdd74a966eef4d921",
    ("SIG-DROP@2", "sham"): SOURCE_DIGEST,
    ("SIG-DROP@2", "control-natural-pause"): "fe53b9010dc31aa391f10160edc0a4a9d3cd733cdc4846f1f3ec5564aa706e4a",
    ("SIG-DROP@2", "mild"): "77675efb952caa13a8d22dfab290cdd2990fdc45c22ab3c0a130e0490ba19e56",
    ("SIG-DROP@2", "moderate"): "75e3e36bcc228d01b1bc3875a6afe107bd0d0e435f6fbb9953882dcfb458a925",
    ("SIG-DROP@2", "severe"): "19d3f0bdfa7b033464b98536508cb41571188bf74bce636cbb59454a507b87c5",
    ("SIG-DROP@2", "attenuated-ramped"): "391d32d460d3094ded4e7e943dcf5c70f22fffa496b031385c3bc75286efa826",
    ("SIG-CLIP@2", "sham"): SOURCE_DIGEST,
    ("SIG-CLIP@2", "control-peak-normalized"): "2002eb222544617610366fa604007dbc1473678bdd1208a3cd6081e20bdc3412",
    ("SIG-CLIP@2", "mild"): "2ce789192a9499184d6f9c1cd6427766dbac72943a17947802cff4498a7f706c",
    ("SIG-CLIP@2", "moderate"): "7fadcb94442be058cb27b89f4996828f878b3bb20db4884adc26a716c3ecaa07",
    ("SIG-CLIP@2", "severe"): "60c00262ac6df8821e3e7170d99085180c113fc39c6169522caf77a4595f637d",
    ("SIG-CLIP@2", "soft-knee-moderate"): "01b16918c59eabf1c22821c4701a19bf3e8a4d88a66841636034a73e7a04e7d7",
    ("SIG-CLIP@2", "over-range-moderate"): "4c157091a072ec7d5cb43da3b0567e88d520ec63d3c9b3943c1d9a613eeb9084",
    ("SIG-DC@1", "sham"): SOURCE_DIGEST,
    ("SIG-DC@1", "mild"): "f6751102acfc6bfb8cf0efb213780d80782445d7ad5c1604c43d67137a5b4330",
    ("SIG-DC@1", "moderate"): "777c9bc2c435a8ae25e765224d8efd7c2bb627ba867bac4dcbde2faa50ae8547",
    ("SIG-DC@1", "severe"): "ef06eda8d6b063842fe54a8ee857f8a6f41766390783fcf25293e44044553f2f",
    ("SIG-LEVEL@1", "sham"): SOURCE_DIGEST,
    ("SIG-LEVEL@1", "mild"): "00262ab4ccddd940ea58a4ce0bdad6e9d8d53f90e509028a90559efcfdada96a",
    ("SIG-LEVEL@1", "moderate"): "f3914d3aab15522bfb2645ab1608d8c536e8535bca0312f06e416a295c3425c0",
    ("SIG-LEVEL@1", "severe"): "9c0c7dfbf249b7b30f6674665f2b766ff10f3d399fa95ad6f858d191e8bff63d",
    ("SIG-NOISE@1", "sham"): SOURCE_DIGEST,
    ("SIG-NOISE@1", "control-80db"): "13d45f113918f5216d98f90258111a2104e68fd55992d364461edf0403d3a7b5",
    ("SIG-NOISE@1", "mild"): "f2d275a8faf01210a35d15664e7c10e0b4bba8410f95835abd2cdf11ff199fe2",
    ("SIG-NOISE@1", "moderate"): "744c29e5531ca01d88753ce51897180da681356a3b3f565aa0da90301e796a19",
    ("SIG-NOISE@1", "severe"): "135a35f44933d872e0c7f84bdb329030a316ba437a8819c303bdad50822775f5",
    ("SIG-NOISE@1", "hum-moderate"): "533d7260f68216e7d3341b864a86bf58a38b78ff1bce30b72f09cf7a45728fe1",
    ("SIG-SIL@1", "sham"): SOURCE_DIGEST,
    ("SIG-SIL@1", "mild"): "965bb1c9b9147824e7d2f39d8119c25678cda210b6f74cfe57230ad45205dbf6",
    ("SIG-SIL@1", "moderate"): "fd3db5899f705638f16de0453fa60e0b583c87b3f4229602e71aaf58f1d92cdf",
    ("SIG-SIL@1", "severe"): "d7cb4fb8838f9d0cbaedc6ed6f687c2d0b9b205284de343d8853d5bd21685360",
    ("SIG-SIL@1", "leading-moderate"): "7344a86741888f8509b0f193ad4e7eb486cf13ef7352ec83791bc9c99d12dd83",
    ("BND-TRUNC@1", "sham"): "8c25c70082e5a51e89db4cec38a9f12fda7350a268e8f06a963af7da78cb7eec",
    ("BND-TRUNC@1", "mild"): "72eaeecdfce67249fedd672d9161427c74574113fca504c33118015cb050e497",
    ("BND-TRUNC@1", "moderate"): "8a3fa23cf2742c680b3918147cb18d65377383706ed291496e1bade0f1ba8d34",
    ("BND-TRUNC@1", "severe"): "faff2ef72fd012b6bdcfbd1281a73681b58d3acf6dc912c3d5f57aa7bcce2428",
    ("BND-RUNON@1", "sham"): "64d879e08bce8f7759398bf51100a7bfcb6a5a224cc4539c18331953a5ea2dfa",
    ("BND-RUNON@1", "mild"): "ba0011182b3413c775c8332b1c2bdf7fe4ee929c86a898f0e1909b64644b7c98",
    ("BND-RUNON@1", "moderate"): "42225b62eedd2ca744420b4627174e1e523fe0a6a7caf7dd71a223d8ee6725f8",
    ("BND-RUNON@1", "severe"): "fd32c544019944d49541e550e04055d6801ad82032dc9fde5f14aef7519c89ca",
    ("BND-RUNON@1", "reversed-moderate"): "a7132e0365984c66b26e8714bd8570b0fc97bf574cf13a4424e5c8ca12356072",
    ("CNT-REP@1", "sham"): "115d10cf4f8ed761934f452c5c091871520489068adf3346df0710cefaa55427",
    ("CNT-REP@1", "mild"): "d5159277968cf136fa1aa81c5ed9edf3b96c20f252822d84899f0580a935ba9d",
    ("CNT-REP@1", "moderate"): "d50e480ef6925a949cbdcff04fd5d676681bd7b79dcfbfc63a054b4bbeaa91d1",
    ("CNT-REP@1", "severe"): "346e68b6d28c4c884b87190f49d5efd2e5f307909f20f1c52f55c26061cfd8e7",
    ("CNT-DEL@1", "sham"): "1e620171e0394c26a45cdde0623206bfc98f7d99d59dae3d774f4e4274457528",
    ("CNT-DEL@1", "mild"): "f0e5de2b947b7297bcc202b8a9e3754ef21cc1bbcc24fc89a2ec1199b0acad25",
    ("CNT-DEL@1", "moderate"): "4716dbe5e47b2add3f7c1d87f33480ddd83c9832d2f02d24a46b1fe27877224d",
    ("CNT-DEL@1", "severe"): "1fdd3d9b2752b6f3142b4a2d721389f1bd51c6f50b168493d2e642dd06d2fb85",
    ("CNT-INS@1", "sham"): "24038a7393ac18804265d68e8c8bb584ba4782c4b51be449160e8810941f873d",
    ("CNT-INS@1", "mild"): "b94bf6bdb29d72677dc1c3369974685b0923e8ca7792e0478c2d6f855fb82591",
    ("CNT-INS@1", "moderate"): "38991ceba8e51495e0aea6aef1018c38707f84e859064fa085c3b76c0defb156",
    ("CNT-INS@1", "severe"): "a85a75bb2e72316ca9ba41c539f79a9c4c0c3780d6a584b182c8758b1f76bbb6",
    ("PRS-OCT@1", "sham"): SOURCE_DIGEST,
    ("PRS-OCT@1", "mild"): "a22e2f675fbf86bf78c8e8d0125f9d789f2a70a601b96dd685f946579693c25c",
    ("PRS-OCT@1", "moderate"): "78bc9bf35273af92a1a4f28220f9136f42cbb5d590e1be5e6db663b61ba4c3ca",
    ("PRS-OCT@1", "severe"): "b0f7e8deece07848a5a53a7bf6feb499f314fcd71b934d089137af94d9bcf2ae",
    ("PRS-OCT@1", "down-moderate"): "871c3e89d5c5e265cdb38162348658ff509b3fcb4e8b845912bb33aab1e8781b",
    ("PRS-BRK@1", "sham"): SOURCE_DIGEST,
    ("PRS-BRK@1", "mild"): "2953b3e51d8d596de4be25853a113ef2bbaa6c8cd493abe0b8c383d0deecd520",
    ("PRS-BRK@1", "moderate"): "442f915e417c7ce022503610bee618399f8401890d417a27a9e3c238d8665894",
    ("PRS-BRK@1", "severe"): "7e278f2dfcc2ddcc428bbd0d0cb47051f62c3254bcd8f77553e8bfdc97d137a4",
    ("PRS-RATE@1", "sham"): SOURCE_DIGEST,
    ("PRS-RATE@1", "mild"): "d76661056e7d5b3f4cef1eefe13353653c56b25ed42648ec1f6ba013773b90b9",
    ("PRS-RATE@1", "moderate"): "b2875618a6335de60363f122ba1a5a2ecaa8d0a04fdd60f6bbc1d2dfe87bd838",
    ("PRS-RATE@1", "severe"): "984444c12049306d25f129c1bca9aaa736b1beaaae9a5dd1c5b185e7da5427d7",
    ("PRS-RATE@1", "fast-severe"): "f802899d67d6be5d0e18c64a53175e9bfa8827310f80f7fef266768878cbad72",
    ("IDN-SHIFT@1", "sham"): SOURCE_DIGEST,
    ("IDN-SHIFT@1", "mild"): "a953b1d33cc911ca7f02d6982aad7f7de87388e10d8348457fb8b4b4f0fe6b2c",
    ("IDN-SHIFT@1", "moderate"): "b4bdeda2056d87cd60b9208b27d2e74048ebceb0d55d014977579a20b228eb7b",
    ("IDN-SHIFT@1", "severe"): "f85290cf9092ea9f6887ab4234874434de1213839d383928df3f4716f1009800",
    ("IDN-SWAP@1", "sham"): SOURCE_DIGEST,
    ("IDN-SWAP@1", "control-same-speaker"): "865000434717bdd6137c627b03483a5b27bef1b79b54257c9a64fc3696e32bcd",
    ("IDN-SWAP@1", "mild"): "41700d37903aed530175e39e53350da8a0b419511556a8098ba96d692f752aa7",
    ("IDN-SWAP@1", "moderate"): "ab3f8c289044138ee43b03db4201b8b547828152d562570a89391ec7f4a1ff4b",
    ("IDN-SWAP@1", "severe"): "356ab34f0563912d608852091f5c3d04cb605e85f12c313c94b6d17554cc86c1",
}
FIXTURE_GOLDENS = {
    "modal": "b47b989b559c93adc985a3ec55a25fca0257d7b14185f2c596ed31d84272210e",
    "quiet": "7772ebeeeee00f477912ec27d57adf66fb4484d07022c8c070a0ea2b5ba51e5f",
    "breathy": "b4b71cf3c576dfd389c8229341e939806cb5e36eb28b290d3fe24264ec912ab6",
    "long-pause": "5bdd3ad3238ec45d4152413c06ba5a48757a6b2ce3f4de176ad4e0fadd0d09d2",
    "high-f0": "d7eb1a67bd5d38977919adf83279998373f72b39549d90067a05a4df86ee4b09",
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
        cls.source = fixtures.clean_fixture(SOURCE_INDEX, "modal")

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
        ramped = injectors.inject("SIG-DROP", "attenuated-ramped", source, SEED)
        (label,) = ramped.labels
        changed = np.flatnonzero(ramped.samples != source.samples)
        # The label covers the 5 ms ramps (120 samples each side) as well as the full-depth span.
        self.assertEqual((label["startSample"], label["endSample"]), (int(changed[0]), int(changed[-1]) + 1))
        self.assertEqual((label["fullDepthStartSample"] - label["startSample"],
                          label["endSample"] - label["fullDepthEndSample"]), (120, 120))
        for variant in ("mild", "moderate", "severe", "soft-knee-moderate"):
            clipped = injectors.inject("SIG-CLIP", variant, source, SEED)
            (label,) = clipped.labels
            changed = np.flatnonzero(clipped.samples != source.samples)
            self.assertEqual((label["startSample"], label["endSample"], label["clippedSamples"]),
                             (int(changed[0]), int(changed[-1]) + 1, changed.size), variant)
        soft = injectors.inject("SIG-CLIP", "soft-knee-moderate", source, SEED)
        level = 10.0 ** (soft.labels[0]["levelDBFS"] / 20.0)
        # A soft knee is bounded: nothing exceeds the asymptote, and it is continuous at the knee.
        self.assertLess(np.max(np.abs(soft.samples)), level * (1.0 + injectors.SOFT_KNEE_HEADROOM))
        self.assertTrue(np.array_equal(injectors.inject("SIG-CLIP", "sham", source, SEED).samples, source.samples))
        over = injectors.inject("SIG-CLIP", "over-range-moderate", source, SEED)
        self.assertEqual((over.labels[0]["startSample"], over.labels[0]["endSample"]), (0, source.samples.size))
        self.assertEqual(int(np.count_nonzero(np.abs(over.samples) > 1.0)), over.labels[0]["overRangeSamples"])
        normalized = injectors.inject("SIG-CLIP", "control-peak-normalized", source, SEED)
        self.assertEqual((normalized.severity, normalized.labels), ("control", ()))
        self.assertAlmostEqual(float(np.max(np.abs(normalized.samples))), 1.0, places=12)
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

    def test_the_natural_pause_control_needs_a_declared_pause(self) -> None:
        source = self.source
        (first, last), = source.pauses
        control = injectors.inject("SIG-DROP", "control-natural-pause", source, SEED)
        # The declared pause is re-timed to the dropout's 600 ms, not lengthened by it.
        self.assertEqual(control.samples.size - source.samples.size, 14_400 - (last - first))
        self.assertTrue(np.array_equal(control.samples[:first], source.samples[:first]))
        self.assertTrue(np.array_equal(control.samples[first + 14_400:], source.samples[last:]))
        bare = fixtures.clean_fixture(0, "modal")
        self.assertEqual(bare.pauses, ())
        with self.assertRaises(injectors.InjectorNotApplicable):
            injectors.inject("SIG-DROP", "control-natural-pause", bare, SEED)

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
        self.assertEqual((recipe["injector"], recipe["catalogVersion"], recipe["seed"]), ("SIG-NOISE@1", 2, SEED))
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
