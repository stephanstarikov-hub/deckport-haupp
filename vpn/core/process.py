import asyncio
import os
from pathlib import Path
import platform
import shutil
from .config import CORE_VERSION, TUN
from ..errors import VPNError
from ..storage import atomic_json


class Core:
    def __init__(self, root: Path, runtime: Path):
        self.binary = root / "backend" / "bin" / "sing-box"
        self.guardian = root / "vpn" / "core" / "guardian.py"
        self.runtime = runtime
        self.config = runtime / "generated-config.json"
        self.proc = None

    @property
    def alive(self):
        return self.proc is not None and self.proc.returncode is None

    async def preflight(self):
        if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
            raise VPNError("VPN requires SteamOS / Linux x86_64")
        if os.geteuid() != 0:
            raise VPNError("Root permission is required; reinstall the plugin with its root flag")
        if not self.binary.is_file() or self.binary.is_symlink():
            raise VPNError("Bundled VPN core is missing; install the complete release ZIP")
        self.binary.chmod(0o700)
        if not Path("/dev/net/tun").exists():
            raise VPNError("Unable to create TUN interface: /dev/net/tun is unavailable")
        if not shutil.which("ip"):
            raise VPNError("SteamOS iproute2 is unavailable")
        p = await asyncio.create_subprocess_exec(str(self.binary), "version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            output, _ = await asyncio.wait_for(p.communicate(), 5)
        except BaseException:
            p.kill()
            await p.wait()
            raise
        if f"sing-box version {CORE_VERSION}" not in output.decode(errors="ignore"):
            raise VPNError("Bundled VPN core version does not match this plugin")

    async def recover(self):
        if not (self.runtime / "network-owned.json").exists():
            return
        await self._spawn(cleanup=True)
        try:
            code = await asyncio.wait_for(self.proc.wait(), 25)
        except asyncio.TimeoutError:
            raise VPNError("Previous VPN cleanup is still running") from None
        if code or (self.runtime / "network-owned.json").exists():
            raise VPNError("Previous VPN cleanup failed; retry Disconnect")

    async def _spawn(self, cleanup=False):
        # Decky may be PyInstaller-frozen: sys.executable can be PluginLoader,
        # not a Python interpreter. SteamOS ships /usr/bin/python3.
        if not Path("/usr/bin/python3").is_file():
            raise VPNError("SteamOS Python runtime is unavailable")
        args = ["/usr/bin/python3", str(self.guardian), str(self.binary), str(self.config), str(self.runtime)]
        if cleanup:
            args.append("--cleanup")
        # Do not propagate PyInstaller's LD_LIBRARY_PATH/PYTHONHOME to system Python.
        environment = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}
        creation = asyncio.create_task(asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=True, env=environment))
        try:
            self.proc = await asyncio.shield(creation)
        except asyncio.CancelledError:
            self.proc = await creation
            raise

    async def start(self, config):
        if self.alive:
            raise VPNError("VPN core is already running")
        await self.preflight()
        atomic_json(self.config, config)
        checker = await asyncio.create_subprocess_exec(str(self.binary), "check", "-c", str(self.config), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            code = await asyncio.wait_for(checker.wait(), 10)
        except BaseException:
            checker.kill()
            await checker.wait()
            raise
        if code:
            self.config.unlink(missing_ok=True)
            raise VPNError("Server configuration is invalid for the bundled VPN core")
        await self._spawn()
        for _ in range(100):
            if not self.alive:
                messages = {3: "Another VPN session is still stopping", 4: "Previous VPN cleanup failed", 5: "VPN routing conflicts with an existing network configuration"}
                raise VPNError(messages.get(self.proc.returncode, "VPN core failed to start; check TUN and server settings"))
            if Path("/sys/class/net/" + TUN).exists():
                return
            await asyncio.sleep(0.1)
        raise VPNError("Unable to create TUN interface")

    async def stop(self):
        if self.alive:
            self.proc.stdin.close()
            try:
                await asyncio.wait_for(self.proc.wait(), 22)
            except asyncio.TimeoutError:
                # Keep guardian alive: it owns cleanup. Never abandon it via SIGKILL.
                self.proc.terminate()
                raise VPNError("VPN cleanup is still running; retry Disconnect") from None
        if (self.runtime / "network-owned.json").exists():
            await self.recover()
        self.config.unlink(missing_ok=True)

    async def route_verified(self):
        # auto_redirect routes Linux traffic through nftables, so
        # `ip route get` does not have to report deckyvpn0 directly.
        return self.alive and Path("/sys/class/net/" + TUN).exists()
