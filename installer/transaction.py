"""Root-owned releases and journaled rollback. No network and no subscription code."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
from .bundle import extract, digest_file
from vpn.safe_fs import read_regular
from vpn.storage import atomic_json
from vpn.ipc import Client
from .user_files import directory, read_at, write_at, plugin_swap, plugin_restore, remove_plugin

BASE = Path("/var/lib/deckport-vpn")
UNIT = "deckportd.service"
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}


def checked_directory(path, mode=0o755, uid=0):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Unsafe installation directory")
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    if os.name == "posix" and (path.stat().st_uid != uid or path.stat().st_mode & 0o022):
        raise ValueError("Installation directory has unsafe ownership or permissions")
    return path


class System:
    def ctl(self, *args):
        return subprocess.run(["/usr/bin/systemctl", *args], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=True)

    def active(self, unit):
        return subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", unit], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10).returncode == 0

    def prepare(self):
        return asyncio.run(Client().call("prepare_update"))

    def resume(self):
        return asyncio.run(Client().call("resume_operations"))

    def health(self, version):
        import time
        for _ in range(30):
            try:
                status = asyncio.run(Client().call("status"))
                if status["version"] == version:
                    return
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError("Service health check failed")


def unit_text(base):
    return f"""[Unit]
Description=DeckPort VPN system connection service
After=network.target
StartLimitIntervalSec=120
StartLimitBurst=10

[Service]
Type=simple
ExecStart=/usr/bin/python3 -I {base}/current/daemon-entry.py
ExecStopPost=/usr/bin/python3 -I {base}/current/vpn/core/guardian.py {base}/current/backend/bin/sing-box /run/deckport-vpn/private/generated-config.json /run/deckport-vpn/private --cleanup
Restart=on-failure
RestartSec=3
TimeoutStopSec=45
KillMode=control-group
RuntimeDirectory=deckport-vpn
RuntimeDirectoryMode=0755
RuntimeDirectoryPreserve=restart
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths={base} /run/deckport-vpn
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW CAP_DAC_OVERRIDE CAP_CHOWN
Environment=PATH=/usr/sbin:/usr/bin:/sbin:/bin

[Install]
WantedBy=multi-user.target
"""


def launcher_text(base):
    return f"""[Desktop Entry]
Type=Application
Name=DeckPort VPN
Comment=Your connection. Your Deck.
Exec={base}/current/desktop/deckport
Icon={base}/current/assets/deckport-vpn.svg
Terminal=false
Categories=Network;Security;
StartupNotify=true
Actions=Connect;Disconnect;Setup;

[Desktop Action Connect]
Name=Connect
Exec={base}/current/desktop/deckport --connect

[Desktop Action Disconnect]
Name=Disconnect
Exec={base}/current/desktop/deckport --disconnect

[Desktop Action Setup]
Name=Repair, Update or Uninstall
Exec={base}/current/desktop/deckport --setup
"""


class Transaction:
    def __init__(self, base=BASE, etc=Path("/etc"), system=None, progress=None):
        self.base, self.etc = Path(base), Path(etc)
        self.system = system or System()
        self.progress = progress or (lambda *_: None)
        self.journal = self.base / "transaction.json"

    def write_file(self, path, data, mode=0o644):
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("Unsafe target file")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".deckport-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def swap(self, release):
        link = self.base / (".current-" + uuid.uuid4().hex)
        link.symlink_to(release, target_is_directory=True)
        os.replace(link, self.base / "current")

    def current(self):
        path = self.base / "current"
        if not path.is_symlink():
            if path.exists():
                raise ValueError("Unsafe current release path")
            return None
        value = path.resolve(strict=True)
        if value.parent != (self.base / "releases").resolve():
            raise ValueError("Current release escapes installation")
        return value

    def save_file(self, record, path):
        if path.is_symlink():
            raise ValueError("Unsafe managed file")
        record["files"].append({"path": str(path), "data": read_regular(path, 4 * 1024 * 1024).hex() if path.exists() else None})
        self.write_file(self.journal, json.dumps(record).encode(), 0o600)

    def rollback(self, record):
        self.system.ctl("stop", UNIT)
        if record["previous"]:
            self.swap(Path(record["previous"]))
        else:
            (self.base / "current").unlink(missing_ok=True)
        for item in reversed(record["files"]):
            path = Path(item["path"])
            if item["data"] is None:
                path.unlink(missing_ok=True)
            else:
                self.write_file(path, bytes.fromhex(item["data"]))
        for item in reversed(record.get("user_files", [])):
            with directory(Path(item["path"]).parent) as fd:
                if item["data"] is None:
                    try:
                        os.unlink(Path(item["path"]).name, dir_fd=fd)
                    except FileNotFoundError:
                        pass
                else:
                    write_at(fd, Path(item["path"]).name, bytes.fromhex(item["data"]), tuple(record["owner"]))
        plugin = record.get("plugin")
        if plugin:
            plugin_restore(Path(plugin["target"]).parent, Path(plugin["backup"]).name, plugin.get("new_moved", False))
        self.system.ctl("daemon-reload")
        if record["was_active"]:
            self.system.ctl("start", UNIT)
        if record.get("decky_active") and plugin:
            self.system.ctl("restart", "plugin_loader.service")
        self.journal.unlink(missing_ok=True)

    def recover(self):
        if self.journal.exists():
            self.progress(5, "Restoring the previous installation")
            self.rollback(json.loads(read_regular(self.journal, 16 * 1024 * 1024)))

    def install(self, archive, expected, account, decky=False):
        checked_directory(self.base)
        # atomic_json deliberately makes its parent private. Keep the product root
        # traversable for the native app; private settings/logs live below it.
        self.recover()
        self.base.chmod(0o755)
        checked_directory(self.base / "releases")
        if self.system.active(UNIT):
            self.system.prepare()
        previous = self.current()
        record = {"previous": str(previous) if previous else None, "was_active": self.system.active(UNIT), "files": [], "plugin": None, "decky_active": self.system.active("plugin_loader.service")}
        try:
            with tempfile.TemporaryDirectory(prefix=".stage-", dir=self.base) as work:
                work = Path(work)
                # Read once without following symlinks, then verify and use the
                # root-owned snapshot. A caller cannot swap the checked payload.
                incoming = work / "payload.zip"
                incoming.write_bytes(read_regular(archive, 600 * 1024 * 1024))
                self.progress(15, "Checking bundled files and permissions")
                manifest = extract(incoming, work / "product", expected)
                release = self.base / "releases" / (manifest["version"] + "-" + uuid.uuid4().hex[:12])
                (work / "product").rename(release)
                shutil.copyfile(incoming, release / "payload.zip")
                (release / "payload.zip").chmod(0o644)
                (release / "payload.sha256").write_text(expected, encoding="ascii")
                self.write_file(self.journal, json.dumps(record).encode(), 0o600)
                self.base.chmod(0o755)
                self.progress(40, "Saving the previous version")
                # Migration copies data once. The old settings are kept intact.
                settings = self.base / "settings"
                checked_directory(settings, 0o700)
                legacy = Path(account["home"]) / "homebrew/settings/decky-vpn/subscriptions.json"
                if not (settings / "subscriptions.json").exists() and legacy.exists():
                    data = json.loads(read_regular(legacy, 64 * 1024 * 1024))
                    if not isinstance(data, dict) or not isinstance(data.get("subscriptions"), list):
                        raise ValueError("Invalid existing settings")
                    atomic_json(settings / "subscriptions.json", data)
                for path, data in ((self.base / "installation.json", json.dumps(account).encode()), (self.etc / "systemd/system" / UNIT, unit_text(self.base).encode())):
                    self.save_file(record, path)
                    self.write_file(path, data, 0o600 if path.name == "installation.json" else 0o644)
                if decky:
                    self.install_plugin(release, account, record)
                self.progress(65, "Activating the new release")
                self.system.ctl("stop", UNIT)
                self.swap(release)
                self.system.ctl("daemon-reload")
                self.system.ctl("enable", "--now", UNIT)
                self.system.health(manifest["version"])
                self.progress(85, "Installing menu shortcut and icon")
                self.integrate(account, record)
                # The desktop integration is installed in /etc/xdg, never through
                # user-controlled home paths as root. KDE reads XDG_DATA_DIRS via
                # the per-user integration performed by the unprivileged GUI.
                if decky and record["decky_active"]:
                    self.system.ctl("restart", "plugin_loader.service")
                self.journal.unlink(missing_ok=True)
                self.system.resume()
                self.base.chmod(0o755)
                self.progress(100, "Installation complete")
                return {"version": manifest["version"], "daemon": "installed", "sing-box": "verified", "desktop": "installed", "decky": "installed" if decky else "not selected", "rollback": "available" if previous else "first installation"}
        except BaseException:
            if self.journal.exists():
                self.progress(10, "Restoring the previous version")
                self.rollback(record)
            try:
                if self.system.active(UNIT):
                    self.system.resume()
            except Exception:
                pass
            raise
        finally:
            self.base.chmod(0o755)

    def install_plugin(self, release, account, record):
        homebrew = Path(account["home"]) / "homebrew"
        if not (homebrew / "services/PluginLoader").is_file():
            raise ValueError("Decky Loader was not found")
        target = homebrew / "plugins/decky-vpn"
        backup = target.parent / (".deckport-backup-" + uuid.uuid4().hex)
        record["plugin"] = {"target": str(target), "backup": str(backup), "new_moved": False}
        self.write_file(self.journal, json.dumps(record).encode(), 0o600)
        if record["decky_active"]:
            self.system.ctl("stop", "plugin_loader.service")
        def saved():
            record["plugin"]["new_moved"] = True
            self.write_file(self.journal, json.dumps(record).encode(), 0o600)
        plugin_swap(release, target.parent, backup.name, saved)

    def integrate(self, account, record):
        owner = (account["uid"], account["gid"])
        home = Path(account["home"])
        files = {
            home / ".local/share/applications/deckport-vpn.desktop": launcher_text(self.base).encode(),
            home / ".local/share/icons/hicolor/scalable/apps/deckport-vpn.svg": (self.current() / "assets/deckport-vpn.svg").read_bytes(),
        }
        record["owner"] = list(owner)
        record["user_files"] = []
        for path, data in files.items():
            with directory(path.parent, create=True, owner=owner) as fd:
                old = read_at(fd, path.name)
                record["user_files"].append({"path": str(path), "data": old.hex() if old is not None else None})
                self.write_file(self.journal, json.dumps(record).encode(), 0o600)
                write_at(fd, path.name, data, owner)

    def uninstall(self, purge=False):
        self.recover()
        current = self.current()
        if current is None:
            return {"product": "not installed"}
        if self.system.active(UNIT):
            self.system.prepare()
        account = json.loads(read_regular(self.base / "installation.json", 16384))
        self.system.ctl("disable", "--now", UNIT)
        if Path("/sys/class/net/deckyvpn0").exists():
            raise RuntimeError("VPN cleanup is still pending; retry Uninstall")
        if account.get("decky"):
            active = self.system.active("plugin_loader.service")
            if active:
                self.system.ctl("stop", "plugin_loader.service")
            try:
                remove_plugin(Path(account["home"]) / "homebrew/plugins")
            finally:
                if active:
                    self.system.ctl("start", "plugin_loader.service")
        for relative in (".local/share/applications/deckport-vpn.desktop", ".local/share/icons/hicolor/scalable/apps/deckport-vpn.svg", ".config/autostart/deckport-vpn.desktop"):
            path = Path(account["home"]) / relative
            try:
                with directory(path.parent) as fd:
                    os.unlink(path.name, dir_fd=fd)
            except FileNotFoundError:
                pass
        # Rename first so interrupted removal cannot follow a replaced tree.
        (self.etc / "systemd/system" / UNIT).unlink(missing_ok=True)
        (self.base / "current").unlink()
        self.system.ctl("daemon-reload")
        # Releases, import data and credentials are removed only after cleanup.
        shutil.rmtree(self.base / "releases")
        if purge:
            for name in ("settings", "logs"):
                path = self.base / name
                if path.exists():
                    if path.is_symlink():
                        raise ValueError("Unsafe data directory")
                    shutil.rmtree(path)
        (self.base / "installation.json").unlink(missing_ok=True)
        return {"daemon": "removed", "desktop": "removed", "settings": "removed" if purge else "preserved"}
