import asyncio
import os
from pathlib import Path
import sys
import decky

# Decky does not guarantee the plugin root is on sys.path.
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "py_modules"))
sys.path.insert(0, str(ROOT))
from vpn.service import Service
from vpn.errors import VPNError


class Plugin:
    async def _main(self):
        os.umask(0o077)
        self.ready = asyncio.Event()
        self.service = None
        try:
            self.service = Service(ROOT, Path(decky.DECKY_PLUGIN_SETTINGS_DIR), Path(decky.DECKY_PLUGIN_RUNTIME_DIR), Path(decky.DECKY_PLUGIN_LOG_DIR), decky.emit)
            await self.service.initialize()
        except Exception:
            decky.logger.error("Decky VPN initialization failed; check storage permissions")
        finally:
            self.ready.set()

    async def _rpc(self, method, *args):
        try:
            if not hasattr(self, "ready"):
                raise VPNError("VPN backend is starting; try again")
            await asyncio.wait_for(self.ready.wait(), 30)
            if self.service is None:
                raise VPNError("VPN backend could not initialize its private storage")
            result = getattr(self.service, method)(*args)
            if asyncio.iscoroutine(result):
                result = await result
            return {"ok": True, "data": result}
        except VPNError as e:
            return {"ok": False, "error": str(e)}
        except Exception:
            # Never return repr(exception): urllib/core errors may contain secrets.
            return {"ok": False, "error": "Operation failed; view safe diagnostic information"}

    async def get_status(self):
        return await self._rpc("status")

    async def get_subscriptions(self):
        return await self._rpc("subscriptions")

    async def get_servers(self, subscription_id):
        return await self._rpc("servers", subscription_id)

    async def ping_servers(self, subscription_id):
        return await self._rpc("ping_servers", subscription_id)

    async def get_import_files(self):
        return await self._rpc("import_files")

    async def import_subscription_file(self, filename, name):
        return await self._rpc("import_subscription", filename, name)

    async def add_subscription(self, url, name):
        return await self._rpc("add_or_update", url, name)

    async def update_subscription(self, identifier):
        return await self._rpc("refresh", identifier)

    async def edit_subscription(self, identifier, name, url):
        return await self._rpc("edit", identifier, name, url)

    async def delete_subscription(self, identifier):
        return await self._rpc("delete", identifier)

    async def select_server(self, server_id):
        return await self._rpc("select", server_id)

    async def connect(self, server_id):
        return await self._rpc("connect", server_id)

    async def disconnect(self):
        return await self._rpc("disconnect")

    async def check_connection(self):
        return await self._rpc("check_connection")

    async def get_logs(self):
        return await self._rpc("get_logs")

    async def get_diagnostic_info(self):
        return await self._rpc("diagnostic")

    async def _unload(self):
        if getattr(self, "service", None):
            await self.service.close()

    async def _uninstall(self):
        if getattr(self, "service", None):
            await self.service.disconnect()
