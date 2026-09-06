"""Validated release installation with backup and rollback. No network requests."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile

PREFIX = "decky-vpn/"
MAX_SIZE = 256 * 1024 * 1024
REQUIRED = {"main.py", "plugin.json", "package.json", "dist/index.js", "backend/bin/sing-box", "vpn/core/guardian.py", "py_modules/yaml/__init__.py", "LICENSE"}


def verify(archive, checksum):
    if archive.stat().st_size > 128 * 1024 * 1024 or checksum.stat().st_size > 1024:
        raise ValueError("Release exceeds size limit")
    expected = checksum.read_text(encoding="ascii").split()[0]
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected) or hashlib.sha256(archive.read_bytes()).hexdigest() != expected.lower():
        raise ValueError("Release checksum mismatch")


def extract(archive, staging):
    with zipfile.ZipFile(archive) as zipped:
        files = zipped.infolist()
        if len(files) > 10000 or sum(f.file_size for f in files) > MAX_SIZE:
            raise ValueError("Release exceeds extraction limits")
        seen = set()
        for member in files:
            path = PurePosixPath(member.filename)
            if not member.filename.startswith(PREFIX) or ".." in path.parts or "\\" in member.filename or path.is_absolute() or ":" in member.filename:
                raise ValueError("Unsafe archive path")
            kind = stat.S_IFMT(member.external_attr >> 16)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or member.filename in seen:
                raise ValueError("Links, special files and duplicate entries are not allowed")
            seen.add(member.filename)
        if not {PREFIX + n for n in REQUIRED}.issubset(seen):
            raise ValueError("Incomplete plugin release")
        manifest = json.loads(zipped.read(PREFIX + "plugin.json"))
        if manifest.get("name") != "DeckPort VPN" or manifest.get("flags") != ["_root"]:
            raise ValueError("Unexpected plugin manifest")
        if zipped.read(PREFIX + "backend/bin/sing-box")[:4] != b"\x7fELF":
            raise ValueError("Linux core missing")
        for member in files:
            target = staging / member.filename
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755 if member.filename == PREFIX + "backend/bin/sing-box" else 0o644)
        for path in staging.rglob("*"):
            if path.is_dir():
                path.chmod(0o755)
    return staging / "decky-vpn"


def checked_home(home):
    if not home.is_absolute() or home.is_symlink() or home.resolve(strict=True) != home or home.name != "homebrew":
        raise ValueError("Unsafe Decky home directory")
    plugins = home / "plugins"
    if not plugins.is_dir() or plugins.is_symlink() or not (home / "services/PluginLoader").is_file():
        raise ValueError("Existing Decky Loader installation required")
    target = plugins / "decky-vpn"
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise ValueError("Unsafe existing plugin path")
    return target


def systemctl(*args):
    subprocess.run(["systemctl", *args, "plugin_loader.service"], check=True, timeout=45)


def install(archive, checksum, home):
    target = checked_home(home)
    verify(archive, checksum)
    backup_root = home / "deckport-backups"
    if backup_root.is_symlink():
        raise ValueError("Unsafe backup directory")
    backup_root.mkdir(mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".deckport-stage-", dir=home) as directory:
        staged = extract(archive, Path(directory))
        # Validate all files before touching the existing plugin or Decky service.
        was_active = subprocess.run(["systemctl", "is-active", "--quiet", "plugin_loader.service"], check=False).returncode == 0
        backup = backup_root / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        moved_old, moved_new = False, False
        try:
            systemctl("stop")
            for _ in range(20):
                if not Path("/sys/class/net/deckyvpn0").exists():
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("VPN is still stopping; retry after Disconnect")
            if target.exists():
                # Do not silently replace a different plugin using the same directory.
                existing = json.loads((target / "plugin.json").read_text())
                if existing.get("name") not in ("DeckPort VPN", "Decky VPN"):
                    raise ValueError("Target directory contains a different plugin")
                target.rename(backup)
                moved_old = True
            staged.rename(target)
            moved_new = True
            if was_active:
                systemctl("start")
        except BaseException:
            if moved_new:
                target.rename(backup_root / ("failed-" + uuid.uuid4().hex))
            if moved_old:
                backup.rename(target)
            if was_active:
                systemctl("start")
            raise
    print("DeckPort VPN installed. Open Decky > DeckPort VPN.")
    if not was_active:
        print("Decky was inactive and was left inactive. Start Decky to use the plugin.")
    if moved_old:
        print(f"Previous plugin preserved at: {backup}")
    print("Saved subscriptions and settings were not modified.")


if __name__ == "__main__":
    try:
        if os.geteuid() != 0 or len(sys.argv) != 4:
            raise ValueError("Use install.sh from your normal user account")
        os.umask(0o022)
        install(*(Path(a) for a in sys.argv[1:]))
    except Exception as error:
        print(f"Installation failed: {error}", file=sys.stderr)
        sys.exit(1)
