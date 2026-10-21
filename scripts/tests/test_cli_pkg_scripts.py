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
import shutil
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
        # The scripts trust only folders no other user can change; the folders these tests make
        # stand for root's 0755 ones whatever umask the test run inherited.
        previous = os.umask(0o022)
        self.addCleanup(os.umask, previous)
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

    def test_preinstall_refuses_shared_folders_that_others_can_change(self):
        # Installer writes the payload through these after preinstall returns; a user who could
        # change either could swap the install folder for a link in between.
        elsewhere = self.base / "elsewhere"
        (elsewhere / "vocello").mkdir(parents=True)
        (elsewhere / "vocello" / "package-manifest.json").write_text("{}\n", encoding="utf-8")

        def writable(mode: int, level: str):
            def prepare(volume: Path):
                (volume / level).chmod(mode)
            return prepare

        def linked(level: str):
            def prepare(volume: Path):
                real = volume / f"{level} (real)"
                (volume / level).rename(real)
                (volume / level).symlink_to(real, target_is_directory=True)
            return prepare

        def file(volume: Path):
            lib = volume / "usr/local/lib"
            shutil.rmtree(lib)
            lib.write_text("not a folder\n", encoding="utf-8")

        cases = {
            "group-writable-local": (writable(0o775, "usr/local"), "usr/local"),
            "other-writable-lib": (writable(0o757, "usr/local/lib"), "usr/local/lib"),
            "linked-local": (linked("usr/local"), None),
            "linked-lib": (linked("usr/local/lib"), None),
            "file-lib": (file, None),
        }
        for case, (prepare, untrusted) in cases.items():
            with self.subTest(case=case):
                volume = self.base / f"volume {case}"
                self.copy_payload(volume)  # a previous installation preinstall would otherwise remove
                prepare(volume)
                before = sorted(str(path.relative_to(volume)) for path in volume.rglob("*"))
                result = self.installer("preinstall", volume)
                self.assertEqual(result.returncode, 1, result.stderr)
                if untrusted:
                    folder = volume / untrusted
                    self.assertIn(f'(sudo chown root:wheel "{folder}" && sudo chmod go-w "{folder}")',
                                  result.stderr)
                else:
                    self.assertIn("is a symbolic link or a file, not a folder", result.stderr)
                self.assertEqual(sorted(str(path.relative_to(volume)) for path in volume.rglob("*")), before)
        self.assertTrue((elsewhere / "vocello" / "package-manifest.json").is_file())

        # Present and only the owner's, or absent, both pass.
        volume = self.base / "volume with only usr/local"
        (volume / "usr/local").mkdir(parents=True)
        result = self.installer("preinstall", volume)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_postinstall_replaces_only_links_into_the_installed_folder(self):
        self.copy_payload()
        bin_folder = self.volume / "usr/local/bin"
        zsh_folder = self.volume / "usr/local/share/zsh/site-functions"
        bin_folder.mkdir(parents=True)
        zsh_folder.mkdir(parents=True)
        zsh_folder.chmod(0o700)
        (bin_folder / "other-tool").write_text("kept\n", encoding="utf-8")
        for case, (bin_target, zsh_target) in {
                "absolute": ("/usr/local/lib/vocello/vocello", "/usr/local/lib/vocello/_vocello"),
                "renamed": ("../lib/vocello/vocello-2.9", "../../../lib/vocello/old/_vocello"),
                "current": ("../lib/vocello/vocello", "../../../lib/vocello/_vocello")}.items():
            with self.subTest(case=case):
                for folder, target, name in ((bin_folder, bin_target, "vocello"), (zsh_folder, zsh_target, "_vocello")):
                    (folder / name).unlink(missing_ok=True)
                    (folder / name).symlink_to(target)
                result = self.installer("postinstall")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assert_linked()
        self.assertEqual(self.mode(bin_folder), 0o755)
        self.assertEqual(self.mode(zsh_folder), 0o700)
        self.assertEqual((bin_folder / "other-tool").read_text(), "kept\n")

    def test_postinstall_leaves_files_folders_and_other_links_and_warns(self):
        command = None

        def foreign_link(path: Path):
            path.symlink_to("/opt/elsewhere/vocello")

        def near_miss_link(path: Path):
            path.symlink_to("../lib/vocello-other/vocello")

        def hand_written(path: Path):
            path.write_text("#compdef vocello\n# a hand-written copy\n", encoding="utf-8")

        def folder(path: Path):
            path.mkdir()
            (path / "kept.txt").write_text("kept\n", encoding="utf-8")

        cases = {"foreign-link": (BIN_LINK, foreign_link), "near-miss-link": (BIN_LINK, near_miss_link),
                 "file": (ZSH_LINK, hand_written), "folder": (BIN_LINK, folder)}
        for case, (link, prepare) in cases.items():
            with self.subTest(case=case):
                volume = self.base / f"volume {case}"
                command = self.copy_payload(volume) / "vocello"
                blocker = volume / link
                blocker.parent.mkdir(parents=True)
                prepare(blocker)
                before = (blocker.is_symlink(), os.readlink(blocker) if blocker.is_symlink() else None,
                          sorted(path.name for path in blocker.iterdir()) if blocker.is_dir() and not blocker.is_symlink()
                          else blocker.read_bytes() if blocker.is_file() and not blocker.is_symlink() else None)
                result = self.installer("postinstall", volume)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"{blocker} is not a link into the installed CLI", result.stderr)
                self.assertIn(f"The command is installed at {command}.", result.stderr)
                after = (blocker.is_symlink(), os.readlink(blocker) if blocker.is_symlink() else None,
                         sorted(path.name for path in blocker.iterdir()) if blocker.is_dir() and not blocker.is_symlink()
                         else blocker.read_bytes() if blocker.is_file() and not blocker.is_symlink() else None)
                self.assertEqual(after, before)
                # The other link is still made.
                other = ZSH_LINK if link == BIN_LINK else BIN_LINK
                self.assertTrue((volume / other).is_symlink(), other)
        self.assertIsNotNone(command)

    def test_postinstall_skips_a_folder_it_cannot_trust_and_warns(self):
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()

        def writable(mode: int):
            def prepare(volume: Path):
                (volume / "usr/local/bin").mkdir()
                (volume / "usr/local/bin").chmod(mode)
            return prepare

        def linked_folder(volume: Path):
            (volume / "usr/local/bin").symlink_to(elsewhere, target_is_directory=True)

        def linked_parent(volume: Path):
            # Only the link's folder is missing; the nearest level that exists is a link.
            (volume / "usr/local/share").symlink_to(elsewhere, target_is_directory=True)

        def file_folder(volume: Path):
            (volume / "usr/local/bin").write_text("kept\n", encoding="utf-8")

        def untrusted_ancestor(volume: Path):
            # The missing link folders would be made inside a folder others can change.
            (volume / "usr/local").chmod(0o775)

        cases = {"group-writable": (writable(0o775), ["usr/local/bin"]),
                 "other-writable": (writable(0o757), ["usr/local/bin"]),
                 "linked-folder": (linked_folder, ["usr/local/bin"]),
                 "linked-parent": (linked_parent, ["usr/local/share/zsh/site-functions"]),
                 "file-folder": (file_folder, ["usr/local/bin"]),
                 "untrusted-ancestor": (untrusted_ancestor, ["usr/local/bin", "usr/local/share/zsh/site-functions"])}
        for case, (prepare, skipped) in cases.items():
            with self.subTest(case=case):
                volume = self.base / f"volume {case}"
                command = self.copy_payload(volume) / "vocello"
                prepare(volume)
                result = self.installer("postinstall", volume)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"The command is installed at {command}.", result.stderr)
                for folder in skipped:
                    self.assertIn(f"{volume / folder} is not a real folder that only root can change", result.stderr)
                for link in (BIN_LINK, ZSH_LINK):
                    if str(Path(link).parent) in skipped:
                        self.assertFalse((volume / link).is_symlink(), link)
                    else:
                        self.assertTrue((volume / link).is_symlink(), link)
                self.assertEqual(list(elsewhere.iterdir()), [])
                if case == "file-folder":
                    self.assertEqual((volume / "usr/local/bin").read_text(), "kept\n")
                if case == "untrusted-ancestor":
                    self.assertEqual(sorted(path.name for path in (volume / "usr/local").iterdir()), ["lib"])
                if case.endswith("writable"):
                    self.assertEqual(list((volume / "usr/local/bin").iterdir()), [])

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
