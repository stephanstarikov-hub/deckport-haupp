"""Bounded, versioned, local-only RPC. One JSON line per connection."""
import asyncio
import inspect
import json
import os
from pathlib import Path
import socket
import struct
from .errors import VPNError
from .version import PROTOCOL_VERSION

SOCKET = Path("/run/deckport-vpn/control.sock")
MAX_REQUEST = 6 * 1024 * 1024
MAX_RESPONSE = 2 * 1024 * 1024
METHODS = {
    "status": (), "subscriptions": (), "servers": (str,), "ping_servers": (str,),
    "import_files": (), "import_subscription": (str, str), "import_content": (str, str),
    "add_or_update": (str, str), "refresh": (str,), "edit": (str, str, str),
    "delete": (str,), "select": (str,), "connect": (str,), "disconnect": (),
    "check_connection": (), "get_logs": (), "diagnostic": (),
    "favorite": (str, bool), "preferences": (), "set_preferences": (dict,),
    "prepare_update": (), "resume_operations": (),
}
READ_ONLY = {"status", "subscriptions", "servers", "import_files", "get_logs", "diagnostic", "preferences"}
ROOT_ONLY = {"prepare_update", "resume_operations"}


def peer_uid(sock):
    if not hasattr(socket, "SO_PEERCRED"):
        raise VPNError("Local peer credentials are unavailable")
    return struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]


def authorized(uid, owner_uid):
    return type(uid) is int and uid in (0, owner_uid)


def encode(value, limit):
    data = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
    if len(data) > limit:
        raise VPNError("Message exceeds the protocol size limit")
    return data


class Server:
    def __init__(self, service, owner_uid, path=SOCKET, owner_gid=None):
        self.service, self.owner_uid, self.path = service, owner_uid, Path(path)
        self.owner_gid = owner_gid
        self.server = None
        self.active = 0
        self.handlers = set()

    async def start(self):
        if self.path.exists() or self.path.is_symlink():
            # Only the root-owned runtime directory may contain this socket.
            if self.path.is_symlink() or not self.path.is_socket():
                raise VPNError("Unsafe control socket path")
            self.path.unlink()
        self.server = await asyncio.start_unix_server(self.handle, path=str(self.path), limit=MAX_REQUEST)
        if self.owner_gid is not None:
            os.chown(self.path, 0, self.owner_gid)
        self.path.chmod(0o660)

    async def dispatch(self, request, uid):
        if not authorized(uid, self.owner_uid):
            raise VPNError("This account cannot control DeckPort VPN")
        if not isinstance(request, dict) or set(request) != {"version", "method", "args"} or type(request["version"]) is not int or request["version"] != PROTOCOL_VERSION:
            raise VPNError("Unsupported control protocol")
        method, args = request["method"], request["args"]
        if not isinstance(method, str) or method not in METHODS or not isinstance(args, list):
            raise VPNError("Invalid control request")
        schema = METHODS[method]
        if len(args) != len(schema) or any(type(arg) is not kind for arg, kind in zip(args, schema)):
            raise VPNError("Invalid control arguments")
        if method in ROOT_ONLY and uid != 0:
            raise VPNError("System authorization is required")
        if getattr(self.service, "maintenance", False) and method not in READ_ONLY | ROOT_ONLY:
            raise VPNError("An installation operation is running")
        value = getattr(self.service, method)(*args)
        return await value if inspect.isawaitable(value) else value

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.handlers.add(task)
        self.active += 1
        try:
            uid = peer_uid(writer.get_extra_info("socket"))
            if not authorized(uid, self.owner_uid):
                raise VPNError("This account cannot control DeckPort VPN")
            if self.active > 8:
                raise VPNError("Too many local requests; try again")
            line = await asyncio.wait_for(reader.readline(), 5)
            if not line.endswith(b"\n") or len(line) > MAX_REQUEST:
                raise VPNError("Invalid control message size")
            request = json.loads(line)
            value = await asyncio.wait_for(self.dispatch(request, uid), 90)
            response = {"version": PROTOCOL_VERSION, "ok": True, "data": value}
        except VPNError as error:
            response = {"version": PROTOCOL_VERSION, "ok": False, "error": str(error)}
        except Exception:
            response = {"version": PROTOCOL_VERSION, "ok": False, "error": "Operation failed; view safe diagnostics"}
        try:
            writer.write(encode(response, MAX_RESPONSE))
            await asyncio.wait_for(writer.drain(), 5)
        except (Exception, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            self.active -= 1
            self.handlers.discard(task)

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for task in list(self.handlers):
            task.cancel()
        await asyncio.gather(*list(self.handlers), return_exceptions=True)
        self.path.unlink(missing_ok=True)


class Client:
    def __init__(self, path=SOCKET, server_uid=0):
        self.path, self.server_uid = str(path), server_uid

    async def call(self, method, *args):
        writer = None
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(self.path, limit=MAX_RESPONSE), 5)
            if peer_uid(writer.get_extra_info("socket")) != self.server_uid:
                raise VPNError("Control service identity check failed")
            writer.write(encode({"version": PROTOCOL_VERSION, "method": method, "args": args}, MAX_REQUEST))
            await asyncio.wait_for(writer.drain(), 5)
            line = await asyncio.wait_for(reader.readline(), 95)
            if not line.endswith(b"\n") or len(line) > MAX_RESPONSE:
                raise VPNError("Invalid service response")
            result = json.loads(line)
            if result.get("version") != PROTOCOL_VERSION or type(result.get("ok")) is not bool:
                raise VPNError("Incompatible service; run Repair")
            if not result["ok"]:
                raise VPNError(result.get("error", "Operation failed"))
            return result["data"]
        except VPNError:
            raise
        except Exception:
            raise VPNError("DeckPort service is unavailable; open Setup and choose Repair") from None
        finally:
            if writer:
                writer.close()
