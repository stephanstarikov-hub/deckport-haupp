import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from installer.transaction import (
    Transaction,
    checked_directory,
)


class FakeSystem:
    def __init__(self):
        self.calls = []

    def ctl(self, *args):
        self.calls.append(args)

    def active(self, unit):
        return False

    def prepare(self):
        return True

    def resume(self):
        return True

    def health(self, version):
        return True


class InstallerV2(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root / "base"
        self.etc = self.root / "etc"

        self.base.mkdir()
        self.etc.mkdir()

        self.system = FakeSystem()
        self.tx = Transaction(
            base=self.base,
            etc=self.etc,
            system=self.system,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_checked_directory_rejects_relative_path(self):
        with self.assertRaises(ValueError):
            checked_directory(Path("relative/path"))

    def test_current_rejects_non_symlink(self):
        current = self.base / "current"
        current.write_text("unsafe", encoding="utf-8")

        with self.assertRaisesRegex(
            ValueError,
            "Unsafe current release path",
        ):
            self.tx.current()

    def test_save_file_records_contents_and_mode(self):
        target = self.root / "installation.json"
        target.write_bytes(b"old-secret")

        record = {"files": []}

        self.tx.save_file(record, target)

        self.assertEqual(len(record["files"]), 1)

        item = record["files"][0]

        self.assertEqual(
            bytes.fromhex(item["data"]),
            b"old-secret",
        )
        self.assertEqual(
            item["mode"],
            stat.S_IMODE(target.stat().st_mode),
        )

        saved = json.loads(
            self.tx.journal.read_text(encoding="utf-8")
        )
        self.assertEqual(
            saved["files"][0]["data"],
            item["data"],
        )
        self.assertEqual(
            saved["files"][0]["mode"],
            item["mode"],
        )

    def test_rollback_restores_recorded_file_mode(self):
        target = self.root / "installation.json"
        target.write_bytes(b"new")

        record = {
            "previous": None,
            "was_active": False,
            "files": [
                {
                    "path": str(target),
                    "data": b"old".hex(),
                    "mode": 0o600,
                }
            ],
            "user_files": [],
            "plugin": None,
            "decky_active": False,
        }

        with patch.object(
            self.tx,
            "write_file",
            wraps=self.tx.write_file,
        ) as write:
            self.tx.rollback(record)

        self.assertEqual(
            target.read_bytes(),
            b"old",
        )

        write.assert_any_call(
            target,
            b"old",
            0o600,
        )

    def test_rollback_removes_file_that_did_not_exist_before(self):
        target = self.root / "new-file"
        target.write_bytes(b"created-by-update")

        record = {
            "previous": None,
            "was_active": False,
            "files": [
                {
                    "path": str(target),
                    "data": None,
                    "mode": None,
                }
            ],
            "user_files": [],
            "plugin": None,
            "decky_active": False,
        }

        self.tx.rollback(record)

        self.assertFalse(target.exists())

    def test_rollback_restarts_previous_active_service(self):
        record = {
            "previous": None,
            "was_active": True,
            "files": [],
            "user_files": [],
            "plugin": None,
            "decky_active": False,
        }

        self.tx.rollback(record)

        self.assertIn(
            ("stop", "deckportd.service"),
            self.system.calls,
        )
        self.assertIn(
            ("daemon-reload",),
            self.system.calls,
        )
        self.assertIn(
            ("start", "deckportd.service"),
            self.system.calls,
        )

    def test_recover_reads_existing_journal(self):
        record = {
            "previous": None,
            "was_active": False,
            "files": [],
            "user_files": [],
            "plugin": None,
            "decky_active": False,
        }

        self.tx.journal.write_text(
            json.dumps(record),
            encoding="utf-8",
        )

        with patch.object(
            self.tx,
            "rollback",
        ) as rollback:
            self.tx.recover()

        rollback.assert_called_once_with(record)


    def test_prejournal_staging_failure_removes_inactive_release(self):
        archive = self.root / "payload.zip"
        archive.write_bytes(b"verified-payload")

        account = {
            "uid": 1000,
            "gid": 1000,
            "home": str(self.root / "home"),
            "decky": False,
        }

        def fake_extract(
            incoming,
            destination,
            expected,
        ):
            destination.mkdir(parents=True)
            (destination / "marker").write_text(
                "ok",
                encoding="utf-8",
            )
            return {"version": "0.2.2"}

        with patch(
            "installer.transaction.extract",
            side_effect=fake_extract,
        ), patch.object(
            self.tx,
            "write_file",
            side_effect=RuntimeError("forced staging failure"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "forced staging failure",
            ):
                self.tx.install(
                    archive,
                    "0" * 64,
                    account,
                    decky=False,
                )

        releases = self.base / "releases"

        self.assertTrue(releases.is_dir())
        self.assertEqual(
            list(releases.iterdir()),
            [],
        )
        self.assertIsNone(self.tx.current())
        self.assertEqual(
            self.tx.stage,
            "release-staging",
        )


if __name__ == "__main__":
    unittest.main()
