import os
from pathlib import Path
import stat
import tempfile
import unittest

from installer.bundle import extract
from scripts import package as packaging


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(
    (ROOT / "backend/bin/sing-box").is_file()
    and (ROOT / "dist/index.js").is_file(),
    "requires fetched dependencies and frontend build",
)
class PackageV2(unittest.TestCase):
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
                "0.2.0",
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
                "0.2.0",
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


if __name__ == "__main__":
    unittest.main()
