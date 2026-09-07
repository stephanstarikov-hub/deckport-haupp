from pathlib import Path
import importlib.util
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class RPC(unittest.IsolatedAsyncioTestCase):
    async def test_decky_entrypoint_roundtrip_and_safe_errors(self):
        decky = types.ModuleType("decky")
        decky.emit = AsyncMock()
        decky.logger = MagicMock()

        with patch.dict(sys.modules, {"decky": decky}):
            spec = importlib.util.spec_from_file_location(
                "decky_vpn_test_main",
                Path(__file__).resolve().parents[1] / "main.py",
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            plugin = module.Plugin()
            await plugin._main()

            # Decky must proxy status through the daemon IPC client.
            plugin.client.call = AsyncMock(
                return_value={
                    "state": "DISCONNECTED",
                    "server": None,
                }
            )

            result = await plugin.get_status()

            self.assertTrue(result["ok"])
            self.assertEqual(
                result["data"]["state"],
                "DISCONNECTED",
            )
            plugin.client.call.assert_awaited_once_with("status")

            # VPNError may be returned to the UI, but sensitive input
            # must not be reflected unnecessarily.
            plugin.client.call.reset_mock()
            plugin.client.call.side_effect = module.VPNError(
                "Invalid identifier"
            )

            invalid = await plugin.connect("../../secret")

            self.assertFalse(invalid["ok"])
            self.assertEqual(
                invalid["error"],
                "Invalid identifier",
            )
            self.assertNotIn(
                "secret",
                invalid["error"],
            )
            plugin.client.call.assert_awaited_once_with(
                "connect",
                "../../secret",
            )

            # Unexpected daemon/client exceptions must be sanitized.
            plugin.client.call.reset_mock()
            plugin.client.call.side_effect = RuntimeError(
                "https://provider/SECRET_TOKEN"
            )

            failed = await plugin.get_status()

            self.assertFalse(failed["ok"])
            self.assertNotIn(
                "SECRET_TOKEN",
                str(failed),
            )
            self.assertEqual(
                failed["error"],
                "Operation failed; view safe diagnostic information",
            )

            # Closing/removing the Decky UI must not disconnect
            # the system-owned VPN daemon.
            plugin.client.call.reset_mock()
            plugin.client.call.side_effect = None

            await plugin._unload()
            await plugin._uninstall()

            plugin.client.call.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
