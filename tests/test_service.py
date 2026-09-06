import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from vpn.service import Service
from vpn.errors import VPNError
from vpn.storage import Store

URI = "vless://11111111-1111-4111-8111-111111111111@203.0.113.1:443?security=tls&sni=example.com#Node"


class Lifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.service = Service(root, root / "settings", root / "runtime", root / "logs", AsyncMock())
        self.service.core = AsyncMock()
        self.service.core.alive = False
        self.service.core.route_verified.return_value = True
        with patch("vpn.service.download", return_value=(URI, {})):
            await self.service.add_or_update("https://example.com/SECRET_TOKEN", "Test")
        self.node = self.service.store.data["selected"]

    async def asyncTearDown(self):
        await self.service.close()
        self.tmp.cleanup()

    async def test_backend_owns_state_and_persists_subscription(self):
        state = self.service.status()
        state["state"] = "CONNECTED"
        self.assertEqual(self.service.status()["state"], "DISCONNECTED")
        restored = Store(self.service.store.path)
        self.assertEqual(restored.data["selected"], self.node)
        self.assertNotIn("SECRET_TOKEN", str(self.service.subscriptions()))
        self.assertNotIn("SECRET_TOKEN", self.service.diagnostic())

    async def test_duplicate_connect_and_cancel(self):
        blocker = asyncio.Event()
        async def start(_):
            await blocker.wait()
        self.service.core.start.side_effect = start
        with patch("vpn.service.public_ip", AsyncMock(return_value="1.2.3.4")):
            state = await self.service.connect(self.node)
            self.assertEqual(state["state"], "CONNECTING")
            with self.assertRaises(VPNError):
                await self.service.connect(self.node)
            await asyncio.sleep(0)
            await self.service.disconnect()
        self.assertEqual(self.service.status()["state"], "DISCONNECTED")
        self.assertTrue(self.service.task.done())
        self.service.core.stop.assert_awaited()

    async def test_failed_probe_never_connected(self):
        with patch("vpn.service.public_ip", AsyncMock(return_value=None)):
            await self.service.connect(self.node)
            await self.service.task
        self.assertEqual(self.service.status()["state"], "ERROR")
        self.service.core.stop.assert_awaited()

    async def test_cleanup_error_not_disconnected(self):
        self.service.core.stop.side_effect = VPNError("VPN cleanup failed; retry Disconnect")
        result = await self.service.disconnect()
        self.assertEqual(result["state"], "ERROR")
        self.service.core.stop.side_effect = None

    async def test_invalid_api_args(self):
        for value in (None, 123, "../../etc/passwd", "x" * 32):
            with self.assertRaises(VPNError):
                self.service.find_node(value)
        with self.assertRaises(VPNError):
            await self.service.add_or_update("https://example.com", "https://token")

    async def test_connected_requires_route_and_live_process(self):
        async def start(_):
            self.service.core.alive = True
        self.service.core.start.side_effect = start
        with patch("vpn.service.public_ip", AsyncMock(return_value="1.2.3.4")):
            await self.service.connect(self.node)
            await self.service.task
        self.assertEqual(self.service.status()["state"], "CONNECTED")
        self.service.core.alive = False
