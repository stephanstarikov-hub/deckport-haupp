import unittest

from vpn.errors import VPNError
from vpn.ipc import (
    MAX_RESPONSE,
    PROTOCOL_VERSION,
    Server,
    authorized,
    encode,
)


class FakeService:
    def __init__(self):
        self.maintenance = False
        self.connected_to = None
        self.prepared = False
        self.resumed = False

    def status(self):
        return {"state": "DISCONNECTED"}

    def subscriptions(self):
        return []

    def preferences(self):
        return {"channel": "stable", "autostart": False}

    async def connect(self, identifier):
        self.connected_to = identifier
        return {"state": "CONNECTING"}

    async def prepare_update(self):
        self.prepared = True
        return True

    async def resume_operations(self):
        self.resumed = True
        return True


def request(method, args=None, version=PROTOCOL_VERSION):
    return {
        "version": version,
        "method": method,
        "args": [] if args is None else args,
    }


class IPCAuthorization(unittest.TestCase):
    def test_owner_and_root_authorized(self):
        self.assertTrue(authorized(1000, 1000))
        self.assertTrue(authorized(0, 1000))

    def test_foreign_uid_rejected(self):
        self.assertFalse(authorized(1001, 1000))
        self.assertFalse(authorized(-1, 1000))
        self.assertFalse(authorized("1000", 1000))

    def test_encode_enforces_limit(self):
        data = encode({"ok": True}, MAX_RESPONSE)
        self.assertTrue(data.endswith(b"\n"))

        with self.assertRaises(VPNError):
            encode(
                {"data": "x" * (MAX_RESPONSE + 1)},
                MAX_RESPONSE,
            )


class IPCDispatch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = FakeService()
        self.server = Server(
            self.service,
            owner_uid=1000,
        )

    async def test_owner_can_read_status(self):
        result = await self.server.dispatch(
            request("status"),
            1000,
        )

        self.assertEqual(
            result["state"],
            "DISCONNECTED",
        )

    async def test_root_can_read_status(self):
        result = await self.server.dispatch(
            request("status"),
            0,
        )

        self.assertEqual(
            result["state"],
            "DISCONNECTED",
        )

    async def test_foreign_user_cannot_control_service(self):
        with self.assertRaisesRegex(
            VPNError,
            "cannot control",
        ):
            await self.server.dispatch(
                request("status"),
                1001,
            )

    async def test_wrong_protocol_version_rejected(self):
        with self.assertRaisesRegex(
            VPNError,
            "Unsupported control protocol",
        ):
            await self.server.dispatch(
                request(
                    "status",
                    version=PROTOCOL_VERSION + 1,
                ),
                1000,
            )

        # bool must not be accepted as int protocol version.
        with self.assertRaisesRegex(
            VPNError,
            "Unsupported control protocol",
        ):
            await self.server.dispatch(
                request(
                    "status",
                    version=True,
                ),
                1000,
            )

    async def test_unknown_method_rejected(self):
        with self.assertRaisesRegex(
            VPNError,
            "Invalid control request",
        ):
            await self.server.dispatch(
                request("run_shell"),
                1000,
            )

    async def test_argument_types_are_strict(self):
        with self.assertRaisesRegex(
            VPNError,
            "Invalid control arguments",
        ):
            await self.server.dispatch(
                request(
                    "connect",
                    [123],
                ),
                1000,
            )

        with self.assertRaisesRegex(
            VPNError,
            "Invalid control arguments",
        ):
            await self.server.dispatch(
                request(
                    "connect",
                    ["a", "b"],
                ),
                1000,
            )

    async def test_valid_async_method_is_dispatched(self):
        result = await self.server.dispatch(
            request(
                "connect",
                ["abc"],
            ),
            1000,
        )

        self.assertEqual(
            self.service.connected_to,
            "abc",
        )
        self.assertEqual(
            result["state"],
            "CONNECTING",
        )

    async def test_root_only_methods_reject_owner(self):
        with self.assertRaisesRegex(
            VPNError,
            "System authorization is required",
        ):
            await self.server.dispatch(
                request("prepare_update"),
                1000,
            )

        self.assertFalse(
            self.service.prepared,
        )

    async def test_root_only_methods_allow_root(self):
        result = await self.server.dispatch(
            request("prepare_update"),
            0,
        )

        self.assertTrue(result)
        self.assertTrue(
            self.service.prepared,
        )

    async def test_maintenance_allows_reads(self):
        self.service.maintenance = True

        result = await self.server.dispatch(
            request("status"),
            1000,
        )

        self.assertEqual(
            result["state"],
            "DISCONNECTED",
        )

    async def test_maintenance_blocks_mutation(self):
        self.service.maintenance = True

        with self.assertRaisesRegex(
            VPNError,
            "installation operation",
        ):
            await self.server.dispatch(
                request(
                    "connect",
                    ["abc"],
                ),
                1000,
            )

        self.assertIsNone(
            self.service.connected_to,
        )

    async def test_maintenance_still_allows_root_recovery(self):
        self.service.maintenance = True

        result = await self.server.dispatch(
            request("resume_operations"),
            0,
        )

        self.assertTrue(result)
        self.assertTrue(
            self.service.resumed,
        )

    async def test_request_shape_must_be_exact(self):
        malformed = request("status")
        malformed["extra"] = "not allowed"

        with self.assertRaisesRegex(
            VPNError,
            "Unsupported control protocol",
        ):
            await self.server.dispatch(
                malformed,
                1000,
            )


if __name__ == "__main__":
    unittest.main()
