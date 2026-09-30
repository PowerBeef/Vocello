#!/usr/bin/env python3
"""Injector and fixture goldens of the audio-QC qualification engine (audit section 5.2).

Every digest is SHA-256 over canonical PCM16, so a last-place floating-point
difference between hosts cannot move it. A changed digest means a changed
injector or fixture: bump its version and replace the golden in the same change.
"""

from __future__ import annotations

from dataclasses import replace
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
# Catalog version 3 (every version 2 golden above is unchanged): the new families on source 1, and the
# seam families on the procedural long-form source 1, whose seams start its second and third segments.
LONG_FORM_DIGEST = "960d8403d34d4ff11636c940b9cb1d51df1a4b1f47283fc14408403d4a62af12"
GOLDENS_V3 = {
    ("SIG-BAND@1", "sham"): "bb5c0ad0c4f77bf9c76a4ebdbc14798fa97202228ab97c6107a20a6fed4fde41",
    ("SIG-BAND@1", "mild"): "a6b1cf81f2310f7cf7d1f036634e524d0b6fab69355c1abd8f73eca2dc97f20e",
    ("SIG-BAND@1", "moderate"): "aa94b4dbe909ab0b0153622130e8aca7403dc7196ff489b149ba472bec667d2b",
    ("SIG-BAND@1", "severe"): "23c0be79ef2a73a5b110438f6b4553677c3a6ab2136313afcb3c3ede7c680a1b",
    ("PRS-ERRATIC@1", "sham"): SOURCE_DIGEST,
    ("PRS-ERRATIC@1", "mild"): "e5f6966a4db849fc990894400b97d6ce2194fca38336dcc74aabbdc984a7c9fa",
    ("PRS-ERRATIC@1", "moderate"): "ea20a5acfdb1734c528c235ad711c4ae35af0d4fad06ca73acb65502e223d635",
    ("PRS-ERRATIC@1", "severe"): "cd7f7fd56d713be1a88a8ce2adc5cd2cbf6cf5266b21c5cf8e57994ced8d41ad",
    ("IDN-ONSET@1", "sham"): SOURCE_DIGEST,
    ("IDN-ONSET@1", "control-same-speaker"): "994cdef62699e682fd6724bb135aa15a23bcade68bcea58105d123a546c6ed43",
    ("IDN-ONSET@1", "mild"): "ee2b54196d70f25eb3495c71b83f7663c8e2304cb28077027c4445b1092232a1",
    ("IDN-ONSET@1", "moderate"): "bde279a558d98e889bd5863d24bda87d28f520e46a4bf5e7f93c496ec049d6f8",
    ("IDN-ONSET@1", "severe"): "2e6392d245422784a8b1bc06e24e3f4319d611832b47e615ccf8e87363db05b0",
    ("SEAM-DISC@1", "sham"): LONG_FORM_DIGEST,
    ("SEAM-DISC@1", "mild"): "a89e5368f942f3b5c62259728a3f04b48775d62e004aa27d7128dc138c91ad22",
    ("SEAM-DISC@1", "moderate"): "35fa493b3582b782397dde242b4717639ac27b0a3883af029c3265c6d15d2857",
    ("SEAM-DISC@1", "severe"): "57eafc0e51e51de99e6b0e26934c7095dbaa844505b298e64cc43fdf8ab60d11",
    ("SEAM-VOICE@1", "sham"): LONG_FORM_DIGEST,
    ("SEAM-VOICE@1", "control-same-speaker"): "673dbd5de4fe3572e02c4eb39686ed9bea0224e60f0d426546f0bbf11d512931",
    ("SEAM-VOICE@1", "mild"): "b9aaa8df94c36079894e6154c64723b02ea53d9efb329ddf94095b9059e6cd73",
    ("SEAM-VOICE@1", "moderate"): "056c0ddd1ee1a0f895f53eaaf9364cd59e6299ecb627047ef22efa4b059fa1b4",
    ("SEAM-VOICE@1", "severe"): "2d214993222fa19add3b1f883efc5482ed72eacf53d0120901d6a45dc7781679",
}
# The donor splices of speaker-labelled recordings, on the procedural sources above with procedural donors:
# modal source 2 as another speaker, and source 1's voice reading script 3 as the same speaker.
DONOR_GOLDENS = {
    ("IDN-SWAP@1", "take-sham"): "3982de07cc703ca1863576a03513c098d8edc1f51a924150e49f948f73ba3b6c",
    ("IDN-SWAP@1", "take-mild"): "793ff7ea93d2623bc98c9c0472d069d7ac84264b7aa17d4014237a6f2f2b75ab",
    ("IDN-SWAP@1", "take-moderate"): "cb1a82502b78e8647109ef7be3e2da5be579f29bf81f2a40c69e1bacd727dff8",
    ("IDN-SWAP@1", "take-severe"): "0b4be78e5d137969fa6037b3555bd2bd7b1b997642edd5ef75a5c01c53cc6cbd",
    ("IDN-ONSET@1", "take-sham"): "c3ce78db867cb3f2620e46abfaa4752d76949a7b7fd0ad4752febeffaa1d3368",
    ("IDN-ONSET@1", "take-mild"): "1ef7f041f146a2292c56623b14b783b718a679fc546ca73a414f1cfb192be3e5",
    ("IDN-ONSET@1", "take-moderate"): "cb1a82502b78e8647109ef7be3e2da5be579f29bf81f2a40c69e1bacd727dff8",
    ("IDN-ONSET@1", "take-severe"): "54760fb263efb21c37e20f8cbc095e5b671819472e60c88a2d941fc51675197a",
    ("SEAM-VOICE@1", "take-sham"): "8231da2514bf4303133cf86c973e0bdf2caff745977a0cc1d2d335d3075977d8",
    ("SEAM-VOICE@1", "take-mild"): "f8d6686f0fe1fba42ad7e46489376c0549756a5c46e9ee778aaa2f33c4457657",
    ("SEAM-VOICE@1", "take-moderate"): "cff2fb5f2f613311feadd7c011cac714e57fb29a222cab5cd8ea1cc966fea5e8",
    ("SEAM-VOICE@1", "take-severe"): "0ec26c2a83dc28e345dd9d921226d5355db98ec96fffbddc2c6dc6af78518b66",
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
    "SIG-BAND", "PRS-ERRATIC", "IDN-ONSET", "SEAM-DISC", "SEAM-VOICE",
}
SEAM_FAMILIES = ("SEAM-DISC", "SEAM-VOICE")


def same_speaker(base: fixtures.Fixture, index: int) -> fixtures.Fixture:
    """Another utterance of `base`'s speaker: another script read by its voice, with its word intervals."""
    script = fixtures.make_script(index, stratum="modal")
    return fixtures.make_fixture(f"same-speaker-{index:04d}", script.family, "modal",
                                 fixtures.render(script, base.voice), words=script.words, pauses=script.pauses,
                                 text=script.text, script=script, voice=base.voice)


class InjectorTests(unittest.TestCase):
    source: fixtures.Fixture
    long_form: fixtures.Fixture

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = fixtures.clean_fixture(SOURCE_INDEX, "modal")
        cls.long_form = fixtures.long_form_fixture(SOURCE_INDEX)
        cls.other_speaker = fixtures.clean_fixture(2, "modal")
        cls.same_speaker = same_speaker(cls.source, 3)

    def source_for(self, injector_id: str) -> fixtures.Fixture:
        """The pinned source of a family: the seam families need declared seams."""
        return self.long_form if injector_id in SEAM_FAMILIES else self.source

    def donor_for(self, variant: injectors.Variant) -> fixtures.Fixture:
        return self.same_speaker if variant.parameters["donor"] == "same-speaker" else self.other_speaker

    def test_the_catalog_covers_the_defect_families(self) -> None:
        self.assertTrue(REQUIRED_FAMILIES <= set(injectors.CATALOG))
        self.assertEqual(injectors.CATALOG_VERSION, 3)
        for injector in injectors.CATALOG.values():
            severities = {variant.severity for variant in injector.variants}
            self.assertEqual(injector.variants[0].name, "sham", injector.key)
            self.assertTrue({"sham", "mild", "moderate", "severe"} <= severities, injector.key)
            self.assertTrue(set(injector.classes) <= set("ABCDEFGHIJ"), injector.key)
            names = [variant.name for variant in injector.variants]
            self.assertEqual(len(names), len(set(names)), injector.key)
        self.assertFalse(set(GOLDENS) & set(GOLDENS_V3))
        self.assertEqual(set(GOLDENS) | set(GOLDENS_V3),
                         {(injector.key, variant.name) for injector in injectors.CATALOG.values()
                          for variant in injector.variants})
        self.assertEqual(set(DONOR_GOLDENS), {(injector.key, variant.name) for injector in injectors.CATALOG.values()
                                              for variant in injector.recording_variants
                                              if "donor" in variant.parameters})

    def test_every_variant_matches_its_golden_digest(self) -> None:
        self.assertEqual(self.source.digest, SOURCE_DIGEST)
        for (key, variant), expected in GOLDENS.items():
            injection = injectors.inject(key.split("@")[0], variant, self.source, SEED)
            self.assertEqual(injection.digest, expected, f"{key} {variant}")

    def test_every_catalog_3_variant_matches_its_golden_digest(self) -> None:
        self.assertEqual(self.long_form.digest, LONG_FORM_DIGEST)
        self.assertEqual(len(self.long_form.seams), 2)
        for (key, variant), expected in GOLDENS_V3.items():
            injector_id = key.split("@")[0]
            injection = injectors.inject(injector_id, variant, self.source_for(injector_id), SEED)
            self.assertEqual(injection.digest, expected, f"{key} {variant}")
        for (key, variant), expected in DONOR_GOLDENS.items():
            injector_id = key.split("@")[0]
            chosen = injectors.CATALOG[injector_id].variant(variant)
            injection = injectors.inject(injector_id, variant, self.source_for(injector_id), SEED,
                                         donor=self.donor_for(chosen))
            self.assertEqual(injection.digest, expected, f"{key} {variant}")
            self.assertEqual(injection.recipe()["donorPCMSHA256"], self.donor_for(chosen).digest)

    def test_same_input_seed_and_parameters_are_byte_identical(self) -> None:
        for injector in injectors.CATALOG.values():
            severe = [variant.name for variant in injector.variants if variant.severity == "severe"][0]
            source = self.source_for(injector.injector_id)
            first = injectors.inject(injector.injector_id, severe, source, SEED)
            second = injectors.inject(injector.injector_id, severe, source, SEED)
            self.assertEqual(first.samples.tobytes(), second.samples.tobytes(), injector.key)
            self.assertEqual(first.recipe(), second.recipe(), injector.key)
        other = injectors.inject("SIG-CLICK", "moderate", self.source, SEED + 1)
        self.assertNotEqual(other.digest, GOLDENS[("SIG-CLICK@1", "moderate")])

    def test_shams_label_nothing_and_positives_label_their_interval(self) -> None:
        for injector in injectors.CATALOG.values():
            for variant in injector.variants:
                injection = injectors.inject(injector.injector_id, variant.name,
                                             self.source_for(injector.injector_id), SEED)
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
            for variant in injector.recording_variants:
                if "donor" not in variant.parameters:
                    continue
                injection = injectors.inject(injector.injector_id, variant.name,
                                             self.source_for(injector.injector_id), SEED,
                                             donor=self.donor_for(variant))
                # The sham's donor is the source speaker, every positive's another speaker.
                self.assertEqual(variant.parameters["donor"] == "same-speaker", not injection.positive)
                self.assertEqual(bool(injection.labels), injection.positive, f"{injector.key} {variant.name}")

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

    def test_clipping_needs_a_sample_above_its_level(self) -> None:
        # A source already flat at its peak (its loudest 5% share one magnitude) has nothing to
        # clip: every clipping variant is not applicable, while the sham and the control still run.
        samples = self.source.samples.copy()
        loudest = np.argsort(np.abs(samples))[-int(0.06 * samples.size):]
        samples[loudest] = np.sign(samples[loudest]) * np.abs(samples).max()
        flat = replace(self.source, samples=samples)
        for variant in ("mild", "moderate", "severe", "soft-knee-moderate", "over-range-moderate"):
            with self.assertRaises(injectors.InjectorNotApplicable, msg=variant):
                injectors.inject("SIG-CLIP", variant, flat, SEED)
        self.assertEqual(injectors.inject("SIG-CLIP", "sham", flat, SEED).labels, ())
        self.assertEqual(injectors.inject("SIG-CLIP", "control-peak-normalized", flat, SEED).labels, ())

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
        self.assertEqual((recipe["injector"], recipe["catalogVersion"], recipe["seed"]), ("SIG-NOISE@1", 3, SEED))
        self.assertEqual(recipe["mechanism"], "T1-pcm-construction")
        self.assertNotIn("donorPCMSHA256", recipe)
        description = injectors.catalog_description()
        self.assertEqual(len(description["injectors"]), len(injectors.CATALOG))
        self.assertFalse({variant["name"] for injector in description["injectors"] for variant in injector["variants"]
                          if variant["name"].startswith("take-")})


class CatalogVersion3Tests(unittest.TestCase):
    """The families catalog version 3 adds: exact labels, seams and every refusal."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = fixtures.clean_fixture(SOURCE_INDEX, "modal")
        cls.long_form = fixtures.long_form_fixture(SOURCE_INDEX)
        cls.other_speaker = fixtures.clean_fixture(2, "modal")
        cls.same_speaker = same_speaker(cls.source, 3)

    def assert_outside_unchanged(self, output: np.ndarray, source: np.ndarray, label: dict, what: str) -> None:
        """Before the label the output is the source; after it, the source moved by the length change."""
        start, end = label["startSample"], label["endSample"]
        delta = output.size - source.size
        self.assertTrue(np.array_equal(output[:start], source[:start]), what)
        self.assertTrue(np.array_equal(output[end:], source[end - delta:]), what)

    def test_band_limit_cuts_relative_to_the_measured_bandwidth(self) -> None:
        source = self.source
        bandwidth = injectors.effective_bandwidth(source.samples, source.sample_rate)
        self.assertEqual(bandwidth, 11_531.25)
        for variant, fraction in (("mild", 0.7), ("moderate", 0.5), ("severe", 0.3)):
            injection = injectors.inject("SIG-BAND", variant, source, SEED)
            (label,) = injection.labels
            self.assertEqual((label["startSample"], label["endSample"]), (0, source.samples.size))
            self.assertEqual(injection.samples.size, source.samples.size)
            self.assertEqual((label["sourceBandwidthHz"], label["cutoffHz"]),
                             (bandwidth, round(fraction * bandwidth, 3)))
            after = injectors.effective_bandwidth(injection.samples, source.sample_rate)
            self.assertEqual(label["outputBandwidthHz"], after)
            self.assertLess(after, bandwidth)
            self.assertLess(after, label["cutoffHz"] + 250.0)
        # The sham runs the same low-pass above the measured band: it keeps the band and labels nothing.
        sham = injectors.inject("SIG-BAND", "sham", source, SEED)
        self.assertEqual(sham.labels, ())
        self.assertEqual(injectors.effective_bandwidth(sham.samples, source.sample_rate), bandwidth)
        # A FLEURS-like source band-limited near 8 kHz still has a band to cut, at its own fractions.
        narrow = fixtures.make_fixture("narrow", "narrow", "modal",
                                       injectors.lowpass(source.samples, 8_000.0, source.sample_rate))
        narrow_bandwidth = injectors.effective_bandwidth(narrow.samples, narrow.sample_rate)
        self.assertLess(narrow_bandwidth, 8_300.0)
        (label,) = injectors.inject("SIG-BAND", "mild", narrow, SEED).labels
        self.assertEqual(label["cutoffHz"], round(0.7 * narrow_bandwidth, 3))

    def test_band_limit_refuses_a_source_with_no_band_to_cut(self) -> None:
        silence = fixtures.abstention_fixture("digital-silence")
        for variant in ("sham", "mild", "severe"):
            with self.assertRaisesRegex(injectors.InjectorNotApplicable, "no active frame"):
                injectors.inject("SIG-BAND", variant, silence, SEED)
        # Already telephone-narrow: 0.3 of a 2.6 kHz band would cut below 1 kHz, while milder cuts still apply.
        muffled = fixtures.make_fixture("muffled", "muffled", "modal",
                                        injectors.lowpass(self.source.samples, 2_500.0, self.source.sample_rate))
        with self.assertRaisesRegex(injectors.InjectorNotApplicable, "below 1000 Hz"):
            injectors.inject("SIG-BAND", "severe", muffled, SEED)
        self.assertTrue(injectors.inject("SIG-BAND", "mild", muffled, SEED).labels)

    def test_erratic_pitch_shifts_seeded_spans_that_tile_the_take(self) -> None:
        source = self.source
        severe = injectors.inject("PRS-ERRATIC", "severe", source, SEED)
        (label,) = severe.labels
        self.assertEqual((label["startSample"], label["endSample"]), (0, source.samples.size))
        self.assertEqual(severe.samples.size, source.samples.size)
        spans = label["spans"]
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1][1], source.samples.size)
        for (start, end, semitones), following in zip(spans, spans[1:] + [None]):
            self.assertIn(semitones, (-7.0, 7.0))
            self.assertGreaterEqual(end - start, 3_600)
            if following is not None:
                self.assertEqual(end, following[0])
                self.assertLessEqual(end - start, 7_200)
        # Every severity and the sham draw the same spans and signs; the sham changes nothing.
        mild = injectors.inject("PRS-ERRATIC", "mild", source, SEED).labels[0]["spans"]
        self.assertEqual([[start, end, 2.0 * semitones / 7.0] for start, end, semitones in spans], mild)
        sham = injectors.inject("PRS-ERRATIC", "sham", source, SEED)
        self.assertEqual((sham.labels, sham.digest), ((), SOURCE_DIGEST))
        short = fixtures.make_fixture("short", "short", "modal", source.samples[:5_000])
        with self.assertRaisesRegex(injectors.InjectorNotApplicable, "two spans"):
            injectors.inject("PRS-ERRATIC", "severe", short, SEED)

    def test_onset_swap_replaces_the_first_seconds_of_speech(self) -> None:
        source = self.source
        onset = source.words[0][0]
        for variant, seconds in (("mild", 0.3), ("moderate", 1.0), ("severe", 1.5)):
            injection = injectors.inject("IDN-ONSET", variant, source, SEED)
            (label,) = injection.labels
            self.assertEqual((label["startSample"], label["endSample"]), (onset, onset + int(seconds * 24_000)))
            self.assert_outside_unchanged(injection.samples, source.samples, label, variant)
        self.assertEqual(injectors.inject("IDN-ONSET", "control-same-speaker", source, SEED).labels, ())

    def test_seam_discontinuity_removes_samples_at_a_seam_and_moves_later_seams(self) -> None:
        source = self.long_form
        sham = injectors.inject("SEAM-DISC", "sham", source, SEED)
        self.assertEqual((sham.digest, sham.labels, sham.seams), (LONG_FORM_DIGEST, (), source.seams))
        for variant, removed in (("mild", 24), ("moderate", 120), ("severe", 480)):
            injection = injectors.inject("SEAM-DISC", variant, source, SEED)
            (label,) = injection.labels
            seam = label["seamSample"]
            self.assertIn(seam, source.seams)
            self.assertEqual((label["startSample"], label["endSample"], label["removedSamples"]), (seam, seam, removed))
            self.assertEqual(injection.samples.size, source.samples.size - removed)
            self.assertTrue(np.array_equal(injection.samples[:seam], source.samples[:seam]))
            self.assertTrue(np.array_equal(injection.samples[seam:], source.samples[seam + removed:]))
            self.assertEqual(injection.seams, tuple(value if value <= seam else value - removed
                                                    for value in source.seams))
        # Every variant draws the same seam from the same stream.
        seams = {injectors.inject("SEAM-DISC", variant, source, SEED).labels[0]["seamSample"]
                 for variant in ("mild", "moderate", "severe")}
        self.assertEqual(len(seams), 1)

    def test_seam_voice_changes_the_voice_after_a_seam(self) -> None:
        source = self.long_form
        for variant in ("mild", "moderate", "severe"):
            injection = injectors.inject("SEAM-VOICE", variant, source, SEED)
            (label,) = injection.labels
            self.assertEqual(label["startSample"], label["seamSample"])
            self.assertIn(label["seamSample"], source.seams)
            self.assert_outside_unchanged(injection.samples, source.samples, label, variant)
            self.assertEqual(injection.seams, source.seams)
        severe = injectors.inject("SEAM-VOICE", "severe", source, SEED).labels[0]
        # The whole segment: up to the next seam, or to the take's end after the last one.
        following = [seam for seam in source.seams if seam > severe["seamSample"]]
        self.assertEqual(severe["endSample"], following[0] if following else source.samples.size)

    def test_donor_splices_label_exactly_what_the_donor_reaches(self) -> None:
        cases = (("IDN-SWAP", self.source), ("IDN-ONSET", self.source), ("SEAM-VOICE", self.long_form))
        for injector_id, source in cases:
            injector = injectors.CATALOG[injector_id]
            for variant in injector.recording_variants:
                donor = self.same_speaker if variant.parameters["donor"] == "same-speaker" else self.other_speaker
                injection = injectors.inject(injector_id, variant.name, source, SEED, donor=donor)
                what = f"{injector.key} {variant.name}"
                if variant.severity == "sham":
                    self.assertEqual(injection.labels, (), what)
                    continue
                (label,) = injection.labels
                self.assertEqual(label["donorRelation"], "other-speaker", what)
                self.assert_outside_unchanged(injection.samples, source.samples, label, what)
                # Two 5 ms crossfades, or one when the donor runs to the take's end.
                fades = 120 if label["endSample"] == injection.samples.size else 240
                self.assertEqual(injection.samples.size - source.samples.size,
                                 label["donorSamples"] - label["replacedSamples"] - fades, what)
                if injector_id == "IDN-ONSET" or variant.parameters["position"] == "onset":
                    self.assertEqual(label["startSample"], injectors.boundaries(source)[0] - 120, what)
                if injector_id == "SEAM-VOICE":
                    self.assertIn(label["seamSample"], source.seams, what)
                    # Seams at or before the splice stay; none lies inside a segment.
                    self.assertEqual(injection.seams, source.seams, what)

    def test_refusals_name_what_the_source_or_donor_lacks(self) -> None:
        source = self.source
        # No seams: every seam variant is not applicable.
        for injector_id in SEAM_FAMILIES:
            for variant in injectors.CATALOG[injector_id].variants:
                with self.assertRaisesRegex(injectors.InjectorNotApplicable, "seam offsets"):
                    injectors.inject(injector_id, variant.name, source, SEED)
        # Seams too close to the end for the largest removal (or a whole segment) are never drawn.
        crowded = replace(source, seams=(source.samples.size - 100,))
        with self.assertRaisesRegex(injectors.InjectorNotApplicable, "no seam followed"):
            injectors.inject("SEAM-DISC", "sham", crowded, SEED)
        with self.assertRaisesRegex(injectors.InjectorNotApplicable, "no seam followed"):
            injectors.inject("SEAM-VOICE", "severe", crowded, SEED)
        # A donor variant without its donor, a donor without word intervals, and a donor on a variant taking none.
        for injector_id in ("IDN-SWAP", "IDN-ONSET"):
            with self.assertRaisesRegex(injectors.InjectorNotApplicable, "speaker-labelled donor"):
                injectors.inject(injector_id, "take-severe", source, SEED)
        wordless = replace(self.other_speaker, words=())
        with self.assertRaisesRegex(injectors.InjectorNotApplicable, "donor has no word intervals"):
            injectors.inject("IDN-SWAP", "take-severe", source, SEED, donor=wordless)
        with self.assertRaises(ValueError):
            injectors.inject("IDN-SWAP", "severe", source, SEED, donor=self.other_speaker)
        # A recording without word intervals refuses a splice even with a donor.
        recording = replace(source, words=(), pauses=(), script=None, voice=None)
        with self.assertRaisesRegex(injectors.InjectorNotApplicable, "word intervals"):
            injectors.inject("IDN-ONSET", "take-mild", recording, SEED, donor=self.other_speaker)

    def test_version_2_outputs_keep_the_source_seams_only_on_an_unchanged_timeline(self) -> None:
        seamed = self.long_form
        # A length-keeping edit keeps the seams; a tempo change or a word splice cannot place them.
        self.assertEqual(injectors.inject("SIG-CLICK", "severe", seamed, SEED).seams, seamed.seams)
        self.assertEqual(injectors.inject("PRS-RATE", "severe", seamed, SEED).seams, ())
        self.assertEqual(injectors.inject("CNT-DEL", "mild", seamed, SEED).seams, ())
        self.assertEqual(injectors.inject("SIG-CLICK", "severe", self.source, SEED).seams, ())


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
