import os
from pathlib import Path
import socket
import stat
import tempfile
import unittest

from vpn.errors import VPNError
from vpn.ipc import Client, Server


class FakeService:
    maintenance = False

    def status(self):
        return {
            "state": "DISCONNECTED",
            "version": "0.2.0",
        }


@unittest.skipUnless(
    os.name == "posix" and hasattr(socket, "SO_PEERCRED"),
    "requires Linux Unix sockets and SO_PEERCRED",
)
class IPCSocketIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.socket = self.root / "control.sock"

        self.service = FakeService()
        self.server = Server(
            self.service,
            owner_uid=os.getuid(),
            path=self.socket,
        )

        await self.server.start()

    async def asyncTearDown(self):
        await self.server.close()
        self.temp.cleanup()

    async def test_real_client_server_roundtrip(self):
        client = Client(
            self.socket,
            server_uid=os.getuid(),
        )

        result = await client.call("status")

        self.assertEqual(
            result["state"],
            "DISCONNECTED",
        )

    async def test_socket_permissions_are_private(self):
        mode = stat.S_IMODE(
            self.socket.stat().st_mode
        )

        self.assertEqual(mode, 0o660)

    async def test_client_rejects_wrong_server_identity(self):
        wrong_uid = os.getuid() + 10000

        client = Client(
            self.socket,
            server_uid=wrong_uid,
        )

        with self.assertRaisesRegex(
            VPNError,
            "identity check failed",
        ):
            await client.call("status")

    async def test_server_close_removes_socket(self):
        self.assertTrue(self.socket.exists())

        await self.server.close()

        self.assertFalse(self.socket.exists())

        # Prevent asyncTearDown from doing meaningful work twice.
        self.server.server = None

    async def test_internal_service_error_is_sanitized(self):
        def explode():
            raise RuntimeError(
                "SECRET_TOKEN=https://provider/private"
            )

        self.service.status = explode

        client = Client(
            self.socket,
            server_uid=os.getuid(),
        )

        with self.assertRaises(VPNError) as error:
            await client.call("status")

        self.assertNotIn(
            "SECRET_TOKEN",
            str(error.exception),
        )
        self.assertIn(
            "Operation failed",
            str(error.exception),
        )


@unittest.skipUnless(
    os.name == "posix",
    "requires POSIX symlinks",
)
class IPCSocketPathSecurity(unittest.IsolatedAsyncioTestCase):
    async def test_server_rejects_symlink_socket_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            target = root / "target"
            target.write_text(
                "do not touch",
                encoding="utf-8",
            )

            socket_path = root / "control.sock"
            socket_path.symlink_to(target)

            server = Server(
                FakeService(),
                owner_uid=os.getuid(),
                path=socket_path,
            )

            with self.assertRaisesRegex(
                VPNError,
                "Unsafe control socket path",
            ):
                await server.start()

            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "do not touch",
            )


if __name__ == "__main__":
    unittest.main()
