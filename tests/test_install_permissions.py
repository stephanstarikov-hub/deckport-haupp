import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from installer.bundle import extract
from installer.transaction import checked_directory


@unittest.skipUnless(
    os.name == "posix",
    "requires POSIX permission semantics",
)
class InstallerPermissions(unittest.TestCase):
    def test_checked_directory_overrides_restrictive_umask(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "product"

            previous = os.umask(0o077)
            try:
                checked_directory(
                    path,
                    0o755,
                    uid=os.getuid(),
                )
            finally:
                os.umask(previous)

            self.assertEqual(
                stat.S_IMODE(path.stat().st_mode),
                0o755,
            )

    def test_bundle_directories_are_traversable_after_umask_077(self):
        required = {
            "daemon-entry.py": b"pass\n",
            "vpn/daemon.py": b"pass\n",
            "vpn/core/guardian.py": b"pass\n",
            "backend/bin/sing-box": b"\x7fELFtest",
            "package.json": json.dumps(
                {"version": "0.2.1"}
            ).encode(),
            "main.py": b"pass\n",
            "plugin.json": b"{}",
            "dist/index.js": b"// test\n",
            "desktop/deckport": b"#!/usr/bin/env python3\n",
            "assets/deckport-vpn.svg": b"<svg/>",
            "installer/entry.py": b"pass\n",
            "py_modules/yaml/__init__.py": b"",
        }

        manifest = {
            "format": 1,
            "version": "0.2.1",
            "files": {},
        }

        modes = {}

        for name, data in required.items():
            mode = (
                0o755
                if name in (
                    "desktop/deckport",
                    "backend/bin/sing-box",
                )
                else 0o644
            )

            modes[name] = mode
            manifest["files"][name] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "mode": mode,
            }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "payload.zip"

            with zipfile.ZipFile(
                archive,
                "w",
                zipfile.ZIP_DEFLATED,
            ) as output:
                for name, data in required.items():
                    info = zipfile.ZipInfo(name)
                    info.create_system = 3
                    info.external_attr = (
                        stat.S_IFREG | modes[name]
                    ) << 16
                    output.writestr(info, data)

                payload = json.dumps(
                    manifest,
                    separators=(",", ":"),
                ).encode()

                info = zipfile.ZipInfo("payload.json")
                info.create_system = 3
                info.external_attr = (
                    stat.S_IFREG | 0o644
                ) << 16
                output.writestr(info, payload)

            digest = hashlib.sha256(
                archive.read_bytes()
            ).hexdigest()

            destination = root / "product"

            previous = os.umask(0o077)
            try:
                extract(
                    archive,
                    destination,
                    digest,
                )
            finally:
                os.umask(previous)

            directories = [destination]
            directories.extend(
                path
                for path in destination.rglob("*")
                if path.is_dir()
            )

            for path in directories:
                self.assertEqual(
                    stat.S_IMODE(path.stat().st_mode),
                    0o755,
                    str(path),
                )


if __name__ == "__main__":
    unittest.main()
