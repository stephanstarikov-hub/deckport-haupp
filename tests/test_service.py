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


    async def test_local_subscription_import(self):
        path = self.service.import_dir / "local.txt"
        path.write_text(URI, encoding="utf-8")

        result = await self.service.import_subscription(
            "local.txt",
            "Local VPN",
        )

        self.assertEqual(result["count"], 1)

        subscription = next(
            s
            for s in self.service.store.data["subscriptions"]
            if s["id"] == result["id"]
        )

        self.assertEqual(subscription["source_type"], "file")
        self.assertEqual(subscription["source"], "local.txt")
        self.assertEqual(subscription["name"], "Local VPN")

        public = next(
            s
            for s in self.service.subscriptions()
            if s["id"] == result["id"]
        )

        self.assertEqual(public["source_type"], "file")
        self.assertEqual(public["source_label"], "local.txt")
        self.assertNotIn("url", public)

    async def test_local_import_rejects_unsafe_paths_and_extensions(self):
        for filename in (
            "../evil.txt",
            "..\\evil.txt",
            "/etc/passwd",
            "evil.exe",
            "nested/file.txt",
        ):
            with self.assertRaises(VPNError):
                await self.service.import_subscription(
                    filename,
                    "Unsafe",
                )

    async def test_local_import_file_listing(self):
        good = self.service.import_dir / "provider.yaml"
        good.write_text(URI, encoding="utf-8")

        ignored = self.service.import_dir / "ignore.exe"
        ignored.write_text(URI, encoding="utf-8")

        files = self.service.import_files()
        names = [item["name"] for item in files]

        self.assertIn("provider.yaml", names)
        self.assertNotIn("ignore.exe", names)

    async def test_local_subscription_refresh_reloads_same_file(self):
        path = self.service.import_dir / "reload.txt"
        path.write_text(URI, encoding="utf-8")

        result = await self.service.import_subscription(
            "reload.txt",
            "Reload VPN",
        )

        identifier = result["id"]

        original = self.service.find_subscription(identifier)
        original_node = original["nodes"][0]["id"]

        replacement = (
            "vless://22222222-2222-4222-8222-222222222222"
            "@203.0.113.2:443?security=tls&sni=example.org#Reloaded"
        )

        path.write_text(replacement, encoding="utf-8")

        refreshed = await self.service.refresh(identifier)

        self.assertEqual(refreshed["id"], identifier)
        self.assertEqual(refreshed["count"], 1)

        updated = self.service.find_subscription(identifier)

        self.assertEqual(updated["source_type"], "file")
        self.assertEqual(updated["source"], "reload.txt")
        self.assertNotEqual(
            updated["nodes"][0]["id"],
            original_node,
        )


    async def test_local_file_can_contain_subscription_url(self):
        path = self.service.import_dir / "provider.txt"
        path.write_text(
            "http://example.com/subscription",
            encoding="utf-8",
        )

        with patch(
            "vpn.service.download",
            return_value=(URI, {"total": 12345}),
        ) as mocked:
            result = await self.service.import_subscription(
                "provider.txt",
                "Provider file",
            )

        self.assertEqual(result["count"], 1)
        mocked.assert_called_once_with(
            "http://example.com/subscription"
        )

        subscription = self.service.find_subscription(
            result["id"]
        )

        self.assertEqual(
            subscription["source_type"],
            "url",
        )
        self.assertEqual(
            subscription["source"],
            "http://example.com/subscription",
        )
        self.assertEqual(
            subscription["url"],
            "http://example.com/subscription",
        )
        self.assertEqual(
            subscription["metadata"]["total"],
            12345,
        )

    async def test_connect_retries_public_ip_until_changed(self):
        self.service.core.alive = False

        async def start(_):
            self.service.core.alive = True

        self.service.core.start.side_effect = start

        with (
            patch(
                "vpn.service.public_ip",
                AsyncMock(
                    side_effect=[
                        "1.1.1.1",
                        "1.1.1.1",
                        "2.2.2.2",
                    ]
                ),
            ),
            patch(
                "vpn.service.asyncio.sleep",
                AsyncMock(),
            ),
        ):
            await self.service.connect(self.node)
            await self.service.task

        state = self.service.status()

        self.assertEqual(state["state"], "CONNECTED")
        self.assertEqual(state["before_ip"], "1.1.1.1")
        self.assertEqual(state["public_ip"], "2.2.2.2")
        self.assertEqual(state["verification"], "verified")

    async def test_connected_requires_route_and_live_process(self):
        async def start(_):
            self.service.core.alive = True
        self.service.core.start.side_effect = start
        with patch("vpn.service.public_ip", AsyncMock(return_value="1.2.3.4")):
            await self.service.connect(self.node)
            await self.service.task
        self.assertEqual(self.service.status()["state"], "CONNECTED")
        self.service.core.alive = False
