import os
from pathlib import Path
import tempfile
import unittest

from vpn.safe_fs import read_regular


class SafeFS(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_symlink(self, target, link, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable in this environment")

    def test_read_regular_reads_normal_file(self):
        path = self.root / "normal.txt"
        path.write_bytes(b"deckport")

        self.assertEqual(
            read_regular(path, 1024),
            b"deckport",
        )

    def test_read_regular_rejects_oversized_file(self):
        path = self.root / "large.bin"
        path.write_bytes(b"x" * 32)

        with self.assertRaises(ValueError):
            read_regular(path, 16)

    def test_read_regular_rejects_final_symlink(self):
        target = self.root / "secret.txt"
        target.write_bytes(b"secret")

        link = self.root / "link.txt"
        self.make_symlink(target, link)

        with self.assertRaises((ValueError, OSError)):
            read_regular(link, 1024)

    def test_read_regular_rejects_symlink_parent(self):
        real = self.root / "real"
        real.mkdir()
        (real / "secret.txt").write_bytes(b"secret")

        alias = self.root / "alias"
        self.make_symlink(real, alias, directory=True)

        with self.assertRaises((ValueError, OSError)):
            read_regular(alias / "secret.txt", 1024)


@unittest.skipUnless(
    os.name == "posix",
    "requires POSIX dir_fd/O_NOFOLLOW",
)
class UserFilesPOSIX(unittest.TestCase):
    def setUp(self):
        from installer.user_files import (
            directory,
            read_at,
            write_at,
        )

        self.directory = directory
        self.read_at = read_at
        self.write_at = write_at

        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_directory_rejects_relative_path(self):
        with self.assertRaises(ValueError):
            with self.directory(Path("relative/path")):
                pass

    def test_directory_rejects_parent_escape(self):
        with self.assertRaises(ValueError):
            with self.directory(Path("/tmp/../etc")):
                pass

    def test_write_and_read_at_roundtrip(self):
        folder = self.root / "files"
        folder.mkdir()

        with self.directory(folder) as fd:
            self.write_at(
                fd,
                "deckport.txt",
                b"hello",
            )

            self.assertEqual(
                self.read_at(fd, "deckport.txt"),
                b"hello",
            )

    def test_read_at_rejects_symlink(self):
        folder = self.root / "files"
        folder.mkdir()

        outside = self.root / "outside.txt"
        outside.write_bytes(b"secret")

        (folder / "link.txt").symlink_to(outside)

        with self.directory(folder) as fd:
            with self.assertRaises(OSError):
                self.read_at(fd, "link.txt")

    def test_write_at_refuses_existing_symlink(self):
        folder = self.root / "files"
        folder.mkdir()

        outside = self.root / "outside.txt"
        outside.write_bytes(b"DO-NOT-CHANGE")

        (folder / "victim.txt").symlink_to(outside)

        with self.directory(folder) as fd:
            with self.assertRaises(OSError):
                self.write_at(
                    fd,
                    "victim.txt",
                    b"attacker-data",
                )

        self.assertEqual(
            outside.read_bytes(),
            b"DO-NOT-CHANGE",
        )

    def test_directory_rejects_symlink_ancestor(self):
        real = self.root / "real"
        real.mkdir()

        alias = self.root / "alias"
        alias.symlink_to(real, target_is_directory=True)

        with self.assertRaises(OSError):
            with self.directory(alias):
                pass


if __name__ == "__main__":
    unittest.main()
