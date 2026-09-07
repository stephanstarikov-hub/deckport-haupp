import os
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
import zipfile

from installer.bundle import extract
from scripts import package as packaging


ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads(
    (ROOT / "package.json").read_text(encoding="utf-8")
)["version"]


@unittest.skipUnless(
    (ROOT / "backend/bin/sing-box").is_file()
    and (ROOT / "dist/index.js").is_file(),
    "requires fetched dependencies and frontend build",
)
class PackageV2(unittest.TestCase):
    @unittest.skipUnless(
        os.name == "posix",
        "native Desktop binary requires Linux",
    )
    def test_desktop_binary_reports_release_version(self):
        output = subprocess.check_output(
            [ROOT / "desktop/deckport", "--version"],
            text=True,
        ).strip()

        self.assertEqual(output, f"DeckPort VPN {VERSION}")

    def test_generated_payload_is_accepted_by_installer(self):
        files = packaging.collect_product_files()

        names = {
            p.relative_to(ROOT).as_posix()
            for p in files
        }

        for required in (
            "daemon-entry.py",
            "desktop/deckport",
            "desktop/setup.py",
            "assets/deckport-vpn.svg",
            "installer/entry.py",
            "installer/bundle.py",
            "vpn/daemon.py",
            "backend/bin/sing-box",
            "dist/index.js",
        ):
            self.assertIn(required, names)

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            output = directory / "release"
            output.mkdir()

            archive, digest = packaging.write_v2_payload(
                output,
                VERSION,
                files,
            )

            destination = directory / "extracted"

            manifest = extract(
                archive,
                destination,
                digest,
            )

            self.assertEqual(
                manifest["version"],
                VERSION,
            )

            self.assertTrue(
                (destination / "daemon-entry.py").is_file()
            )
            self.assertTrue(
                (destination / "desktop/deckport").is_file()
            )
            self.assertTrue(
                (destination / "desktop/setup.py").is_file()
            )

            # These are the permissions recorded inside payload.json.
            # They are portable and must be correct on every OS.
            self.assertEqual(
                manifest["files"]["desktop/deckport"]["mode"],
                0o755,
            )

            self.assertEqual(
                manifest["files"]["backend/bin/sing-box"]["mode"],
                0o755,
            )

            self.assertEqual(
                manifest["files"]["daemon-entry.py"]["mode"],
                0o644,
            )

            # Only POSIX systems can faithfully report chmod 0755
            # after extraction. Windows maps these bits differently.
            if os.name == "posix":
                self.assertEqual(
                    stat.S_IMODE(
                        (
                            destination
                            / "desktop/deckport"
                        ).stat().st_mode
                    ),
                    0o755,
                )

                self.assertEqual(
                    stat.S_IMODE(
                        (
                            destination
                            / "backend/bin/sing-box"
                        ).stat().st_mode
                    ),
                    0o755,
                )

    @unittest.skipUnless(
        os.name == "posix",
        "hardlink reuse requires POSIX filesystem semantics",
    )
    def test_update_reuses_unchanged_files_with_hardlinks(self):
        files = packaging.collect_product_files()

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            output = directory / "release"
            output.mkdir()

            archive, digest = packaging.write_v2_payload(
                output,
                VERSION,
                files,
            )

            previous = directory / "previous"
            extract(
                archive,
                previous,
                digest,
            )

            old_sing = previous / "backend/bin/sing-box"
            old_daemon = previous / "daemon-entry.py"

            old_sing_inode = old_sing.stat().st_ino
            old_daemon_inode = old_daemon.stat().st_ino

            # A mode mismatch must prevent reuse.
            old_daemon.chmod(0o755)

            updated = directory / "updated"
            extract(
                archive,
                updated,
                digest,
                reuse_from=previous,
            )

            new_sing = updated / "backend/bin/sing-box"
            new_daemon = updated / "daemon-entry.py"

            self.assertEqual(
                old_sing_inode,
                new_sing.stat().st_ino,
            )
            self.assertGreaterEqual(
                new_sing.stat().st_nlink,
                2,
            )

            self.assertNotEqual(
                old_daemon_inode,
                new_daemon.stat().st_ino,
            )
            self.assertEqual(
                stat.S_IMODE(new_daemon.stat().st_mode),
                0o644,
            )

    def test_source_archive_excludes_cargo_build_output(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = packaging.write_source(
                Path(directory),
                VERSION,
            )

            with zipfile.ZipFile(archive) as source:
                names = source.namelist()
                timestamps = {
                    item.date_time
                    for item in source.infolist()
                }

            self.assertIn(
                "deckport-vpn/desktop-native/src/app.rs",
                names,
            )
            self.assertIn(
                "deckport-vpn/desktop-native/build.rs",
                names,
            )
            self.assertFalse(
                any("/desktop-native/target/" in name for name in names)
            )
            self.assertEqual(
                timestamps,
                {(2026, 9, 6, 0, 0, 0)},
            )

if __name__ == "__main__":
    unittest.main()
