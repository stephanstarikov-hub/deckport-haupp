import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import zipfile
from installer.apply import extract, verify, install, REQUIRED


class Installer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.archive = self.root / "bundle.zip"
        self.checksum = self.root / "checksum"
        self.make_archive()

    def tearDown(self):
        self.temp.cleanup()

    def make_archive(self, extra=None):
        with zipfile.ZipFile(self.archive, "w") as z:
            for name in REQUIRED:
                content = b"synthetic"
                if name == "plugin.json":
                    content = json.dumps({"name": "DeckPort VPN", "flags": ["_root"]}).encode()
                elif name == "backend/bin/sing-box":
                    content = b"\x7fELFsynthetic"
                z.writestr("decky-vpn/" + name, content)
            if extra:
                z.writestr(*extra)
        self.checksum.write_text(hashlib.sha256(self.archive.read_bytes()).hexdigest())

    def test_verified_extract(self):
        verify(self.archive, self.checksum)
        result = extract(self.archive, self.root / "staging")
        self.assertTrue((result / "main.py").is_file())

    def test_corrupted_archive_rejected(self):
        self.checksum.write_text("0" * 64)
        with self.assertRaisesRegex(ValueError, "checksum"):
            verify(self.archive, self.checksum)

    def test_path_traversal_rejected(self):
        for name in ("decky-vpn/../../escaped", "/absolute", "other/main.py", "decky-vpn/..\\escaped"):
            self.make_archive((name, "unsafe"))
            with self.assertRaises(ValueError):
                extract(self.archive, self.root / "staging")
        self.assertFalse((self.root / "escaped").exists())

    def test_symlink_rejected(self):
        member = zipfile.ZipInfo("decky-vpn/link")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.make_archive((member, "/etc/passwd"))
        with self.assertRaisesRegex(ValueError, "Links"):
            extract(self.archive, self.root / "staging")

    def decky_home(self):
        home = self.root / "homebrew"
        (home / "plugins/decky-vpn").mkdir(parents=True)
        (home / "services").mkdir()
        (home / "services/PluginLoader").write_text("existing loader")
        (home / "plugins/decky-vpn/plugin.json").write_text('{"name":"Decky VPN"}')
        (home / "plugins/decky-vpn/old.txt").write_text("previous version")
        (home / "settings").mkdir()
        (home / "settings/subscriptions.json").write_text("keep me")
        return home

    def test_update_keeps_backup_and_settings(self):
        home = self.decky_home()
        with patch("installer.apply.subprocess.run", return_value=MagicMock(returncode=0)), patch("installer.apply.systemctl") as service:
            install(self.archive, self.checksum, home)
        self.assertEqual((home / "settings/subscriptions.json").read_text(), "keep me")
        self.assertTrue(list((home / "deckport-backups").glob("*/old.txt")))
        self.assertTrue((home / "plugins/decky-vpn/main.py").exists())
        self.assertEqual([c.args for c in service.call_args_list], [("stop",), ("start",)])

    def test_restart_failure_rolls_back(self):
        home = self.decky_home()
        with patch("installer.apply.subprocess.run", return_value=MagicMock(returncode=0)), patch("installer.apply.systemctl", side_effect=[None, RuntimeError("restart failed"), None]):
            with self.assertRaisesRegex(RuntimeError, "restart failed"):
                install(self.archive, self.checksum, home)
        self.assertEqual((home / "plugins/decky-vpn/old.txt").read_text(), "previous version")
        self.assertEqual((home / "settings/subscriptions.json").read_text(), "keep me")
