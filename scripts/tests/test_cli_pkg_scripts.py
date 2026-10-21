"""The CLI installer package's shell scripts, run against temporary volumes.

preinstall and postinstall run the way Installer runs them, with the target volume as $3
(here a temporary folder whose name has spaces) and a restrictive caller umask. They are
the shipped files from scripts/cli_pkg; `cli_package.py pkg` copies them into the package
and `pkg-verify` proves the package carries them byte for byte. uninstall.sh is run only
where it must refuse: outside /usr/local/lib/vocello, and without root.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" / "cli_pkg"
LIB = "usr/local/lib/vocello"
BIN_LINK = "usr/local/bin/vocello"
ZSH_LINK = "usr/local/share/zsh/site-functions/_vocello"


class PackageScriptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.volume = self.base / "volume with spaces"
        self.volume.mkdir()
        self.marker = self.base / "the CLI ran"

    def tearDown(self):
        self.temporary.cleanup()

    def run_script(self, name: str, *arguments: str) -> subprocess.CompletedProcess:
        # Installer's environment is minimal; a umask of 077 proves the scripts set their own.
        return subprocess.run(
            ["/bin/sh", "-c", 'umask 077 && exec /bin/sh "$@"', "sh", str(SCRIPTS / f"{name}.sh"), *arguments],
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}, cwd=self.base, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=30, check=False)

    def installer(self, name: str, volume: Path | None = None, *, suffix: str = "") -> subprocess.CompletedProcess:
        target = volume or self.volume
        return self.run_script(name, str(self.base / "Vocello-macos26-cli.pkg"), str(target / LIB),
                               str(target) + suffix, "/")

    def copy_payload(self, volume: Path | None = None) -> Path:
        """What Installer copies between the two scripts, reduced to what they look at."""
        lib = (volume or self.volume) / LIB
        lib.mkdir(parents=True)
        executable = lib / "vocello"
        executable.write_text(f'#!/bin/sh\necho ran > "{self.marker}"\n', encoding="utf-8")
        executable.chmod(0o755)
        (lib / "_vocello").write_text("#compdef vocello\n", encoding="utf-8")
        (lib / "package-manifest.json").write_text("{}\n", encoding="utf-8")
        (lib / "uninstall.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        return lib

    def assert_linked(self, volume: Path | None = None):
        volume = volume or self.volume
        for link, target, name in ((BIN_LINK, "../lib/vocello/vocello", "vocello"),
                                   (ZSH_LINK, "../../../lib/vocello/_vocello", "_vocello")):
            path = volume / link
            self.assertTrue(path.is_symlink(), link)
            self.assertEqual(os.readlink(path), target)
            self.assertEqual(path.resolve(), (volume / LIB / name).resolve())

    def mode(self, path: Path) -> int:
        return stat.S_IMODE(path.lstat().st_mode)

    def test_fresh_install_links_relatively_and_creates_missing_folders(self):
        result = self.installer("preinstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.volume / LIB).exists())
        self.copy_payload()
        result = self.installer("postinstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_linked()
        for folder in ("usr/local/bin", "usr/local/share", "usr/local/share/zsh",
                       "usr/local/share/zsh/site-functions"):
            self.assertEqual(self.mode(self.volume / folder), 0o755, folder)
        self.assertFalse(self.marker.exists(), "the scripts must never run the CLI")

    def test_upgrade_removes_the_previous_payload_and_relinks(self):
        lib = self.copy_payload()
        (lib / "stale-from-an-older-version.txt").write_text("stale\n", encoding="utf-8")
        nested = lib / "removed.bundle" / "Contents"
        nested.mkdir(parents=True)
        (nested / "Info.plist").write_text("old\n", encoding="utf-8")
        self.assertEqual(self.installer("postinstall").returncode, 0)

        # Installer passes "/" for the startup disk, so a trailing slash must work too.
        result = self.installer("preinstall", suffix="/")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(lib.exists() or lib.is_symlink())
        self.copy_payload()
        result = self.installer("postinstall", suffix="/")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_linked()
        self.assertEqual(sorted(path.name for path in lib.iterdir()),
                         ["_vocello", "package-manifest.json", "uninstall.sh", "vocello"])

    def test_preinstall_refuses_what_it_did_not_install(self):
        decoy = self.base / "decoy with a manifest"
        decoy.mkdir()
        (decoy / "package-manifest.json").write_text("{}\n", encoding="utf-8")

        def linked(lib: Path):
            lib.symlink_to(decoy, target_is_directory=True)

        def foreign(lib: Path):
            lib.mkdir()
            (lib / "notes.txt").write_text("someone else's\n", encoding="utf-8")

        def linked_manifest(lib: Path):
            lib.mkdir()
            (lib / "package-manifest.json").symlink_to(decoy / "package-manifest.json")

        def file(lib: Path):
            lib.write_text("not a folder\n", encoding="utf-8")

        cases = {"linked": (linked, "symbolic link"), "foreign": (foreign, "sudo rm -rf"),
                 "linked-manifest": (linked_manifest, "not a Vocello CLI installation"),
                 "file": (file, "not a folder")}
        for case, (prepare, message) in cases.items():
            with self.subTest(case=case):
                volume = self.base / f"volume {case}"
                lib = volume / LIB
                lib.parent.mkdir(parents=True)
                prepare(lib)
                before = sorted(str(path.relative_to(volume)) for path in volume.rglob("*"))
                result = self.installer("preinstall", volume)
                self.assertEqual(result.returncode, 1)
                self.assertIn(message, result.stderr)
                self.assertEqual(sorted(str(path.relative_to(volume)) for path in volume.rglob("*")), before)
        self.assertTrue((decoy / "package-manifest.json").is_file())

    def test_scripts_refuse_without_an_absolute_target_volume(self):
        for name in ("preinstall", "postinstall"):
            for arguments in ((), ("package.pkg", "usr/local/lib/vocello", "relative volume", "/")):
                with self.subTest(script=name, arguments=len(arguments)):
                    result = self.run_script(name, *arguments)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("target volume", result.stderr)
        self.assertEqual(list(self.base.iterdir()), [self.volume])

    def test_postinstall_replaces_links_and_files_but_keeps_folders_as_they_are(self):
        self.copy_payload()
        bin_folder = self.volume / "usr/local/bin"
        zsh_folder = self.volume / "usr/local/share/zsh/site-functions"
        bin_folder.mkdir(parents=True)
        zsh_folder.mkdir(parents=True)
        bin_folder.chmod(0o775)
        zsh_folder.chmod(0o700)
        (bin_folder / "vocello").symlink_to("/opt/elsewhere/vocello")
        (zsh_folder / "_vocello").write_text("#compdef vocello\n# a hand-written copy\n", encoding="utf-8")
        (bin_folder / "other-tool").write_text("kept\n", encoding="utf-8")
        result = self.installer("postinstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_linked()
        self.assertEqual(self.mode(bin_folder), 0o775)
        self.assertEqual(self.mode(zsh_folder), 0o700)
        self.assertEqual((bin_folder / "other-tool").read_text(), "kept\n")
        # Running it again leaves the same links.
        self.assertEqual(self.installer("postinstall").returncode, 0)
        self.assert_linked()

    def test_postinstall_refuses_a_folder_where_a_link_or_its_folder_goes(self):
        cases = {"folder-at-link": ("usr/local/bin/vocello", True), "file-at-folder": ("usr/local/bin", False)}
        for case, (path, folder) in cases.items():
            with self.subTest(case=case):
                volume = self.base / f"volume {case}"
                self.copy_payload(volume)
                blocker = volume / path
                blocker.parent.mkdir(parents=True, exist_ok=True)
                if folder:
                    blocker.mkdir()
                    (blocker / "kept.txt").write_text("kept\n", encoding="utf-8")
                else:
                    blocker.write_text("kept\n", encoding="utf-8")
                result = self.installer("postinstall", volume)
                self.assertEqual(result.returncode, 1)
                self.assertTrue((blocker / "kept.txt").is_file() if folder else blocker.is_file())
                self.assertFalse((volume / ZSH_LINK).is_symlink())

    def test_postinstall_requires_the_installed_executable(self):
        def missing(volume: Path):
            (volume / LIB).mkdir(parents=True)

        def not_executable(volume: Path):
            (self.copy_payload(volume) / "vocello").chmod(0o644)

        def linked(volume: Path):
            real = self.copy_payload(self.base / "real payload volume")
            (volume / LIB).parent.mkdir(parents=True)
            (volume / LIB).symlink_to(real, target_is_directory=True)

        for case, prepare in {"missing": missing, "not-executable": not_executable, "linked": linked}.items():
            with self.subTest(case=case):
                volume = self.base / f"volume {case}"
                prepare(volume)
                result = self.installer("postinstall", volume)
                self.assertEqual(result.returncode, 1)
                self.assertIn("installed command is missing", result.stderr)
                self.assertFalse((volume / "usr/local/bin").exists())

    def test_uninstall_refuses_outside_the_installed_folder_and_without_root(self):
        copy = self.base / LIB
        copy.mkdir(parents=True)
        (copy / "package-manifest.json").write_text("{}\n", encoding="utf-8")
        (copy / "uninstall.sh").write_bytes((SCRIPTS / "uninstall.sh").read_bytes())
        links = self.base / "usr/local/bin"
        links.mkdir(parents=True)
        (links / "vocello").symlink_to("../lib/vocello/vocello")
        before = sorted(str(path.relative_to(self.base)) for path in self.base.rglob("*"))
        for script in (copy / "uninstall.sh", SCRIPTS / "uninstall.sh"):
            with self.subTest(script=script.parent.name):
                result = subprocess.run(["/bin/sh", str(script)], env={"PATH": "/usr/bin:/bin"}, cwd=self.base,
                                        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
                                        check=False)
                self.assertEqual(result.returncode, 1)
                self.assertIn("not the installed copy in /usr/local/lib/vocello", result.stderr)
                if os.geteuid() != 0:
                    self.assertIn("sudo sh /usr/local/lib/vocello/uninstall.sh", result.stderr)
                self.assertEqual(result.stdout, "")
        self.assertEqual(sorted(str(path.relative_to(self.base)) for path in self.base.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
