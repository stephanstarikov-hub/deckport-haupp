import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class RPC(unittest.IsolatedAsyncioTestCase):
    async def test_decky_entrypoint_roundtrip_and_safe_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            decky = types.ModuleType("decky")
            for kind in ("SETTINGS", "RUNTIME", "LOG"):
                setattr(decky, f"DECKY_PLUGIN_{kind}_DIR", str(root / kind))
            decky.emit, decky.logger = AsyncMock(), MagicMock()
            with patch.dict(sys.modules, {"decky": decky}):
                spec = importlib.util.spec_from_file_location("decky_vpn_test_main", Path(__file__).resolve().parents[1] / "main.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                plugin = module.Plugin()
                await plugin._main()
                try:
                    result = await plugin.get_status()
                    self.assertTrue(result["ok"])
                    self.assertEqual(result["data"]["state"], "DISCONNECTED")
                    invalid = await plugin.connect("../../secret")
                    self.assertFalse(invalid["ok"])
                    self.assertNotIn("secret", invalid["error"])
                    with patch.object(plugin.service, "status", side_effect=RuntimeError("https://provider/SECRET_TOKEN")):
                        failed = await plugin.get_status()
                    self.assertFalse(failed["ok"])
                    self.assertNotIn("SECRET_TOKEN", str(failed))
                finally:
                    await plugin._unload()
                    await plugin._uninstall()
