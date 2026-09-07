import errno
import unittest

from installer.update import install_with_low_space_fallback


class FakeTransaction:
    def __init__(self, install_result=None, install_error=None):
        self.install_result = install_result
        self.install_error = install_error
        self.install_calls = []
        self.uninstall_calls = []
        self.stage = "preflight"

    def install(self, payload, expected, account, decky=False):
        self.install_calls.append(
            (payload, expected, account, decky)
        )
        if self.install_error is not None:
            raise self.install_error
        return self.install_result

    def uninstall(self, purge=False):
        self.uninstall_calls.append(purge)
        return {
            "daemon": "removed",
            "settings": "preserved" if not purge else "removed",
        }


class LowSpaceUpdateTests(unittest.TestCase):
    def test_normal_install_does_not_remove_existing_program(self):
        first = FakeTransaction(
            install_result={"version": "0.2.5"}
        )
        state = {
            "transaction": first,
            "replace_started": False,
        }
        progress = []

        result = install_with_low_space_fallback(
            state,
            lambda: self.fail("retry should not be created"),
            "/tmp/payload.zip",
            "a" * 64,
            {"uid": 1000},
            True,
            True,
            lambda percent, message: progress.append(
                (percent, message)
            ),
        )

        self.assertEqual(result, {"version": "0.2.5"})
        self.assertEqual(first.uninstall_calls, [])
        self.assertFalse(state["replace_started"])
        self.assertEqual(progress, [])

    def test_enospc_replaces_program_without_purging_settings(self):
        first = FakeTransaction(
            install_error=OSError(errno.ENOSPC, "disk full")
        )
        retry = FakeTransaction(
            install_result={"version": "0.2.5"}
        )
        state = {
            "transaction": first,
            "replace_started": False,
        }
        progress = []

        result = install_with_low_space_fallback(
            state,
            lambda: retry,
            "/tmp/payload.zip",
            "b" * 64,
            {"uid": 1000},
            True,
            True,
            lambda percent, message: progress.append(
                (percent, message)
            ),
        )

        self.assertTrue(state["replace_started"])
        self.assertIs(state["transaction"], retry)
        self.assertEqual(first.uninstall_calls, [False])
        self.assertEqual(result["version"], "0.2.5")
        self.assertEqual(
            result["update"],
            "low-space-replace",
        )
        self.assertGreaterEqual(len(progress), 2)
        self.assertIn("preserving settings", progress[0][1])
        self.assertIn("settings preserved", progress[1][1])

    def test_enospc_on_first_install_never_triggers_destructive_fallback(self):
        first = FakeTransaction(
            install_error=OSError(errno.ENOSPC, "disk full")
        )
        state = {
            "transaction": first,
            "replace_started": False,
        }

        with self.assertRaises(OSError) as raised:
            install_with_low_space_fallback(
                state,
                lambda: self.fail("retry should not be created"),
                "/tmp/payload.zip",
                "c" * 64,
                {"uid": 1000},
                True,
                False,
                lambda *_: None,
            )

        self.assertEqual(raised.exception.errno, errno.ENOSPC)
        self.assertEqual(first.uninstall_calls, [])
        self.assertFalse(state["replace_started"])

    def test_non_space_error_is_never_replaced(self):
        first = FakeTransaction(
            install_error=OSError(errno.EACCES, "denied")
        )
        state = {
            "transaction": first,
            "replace_started": False,
        }

        with self.assertRaises(OSError) as raised:
            install_with_low_space_fallback(
                state,
                lambda: self.fail("retry should not be created"),
                "/tmp/payload.zip",
                "d" * 64,
                {"uid": 1000},
                True,
                True,
                lambda *_: None,
            )

        self.assertEqual(raised.exception.errno, errno.EACCES)
        self.assertEqual(first.uninstall_calls, [])
        self.assertFalse(state["replace_started"])


if __name__ == "__main__":
    unittest.main()
