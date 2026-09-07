"""Validate every payload byte and mode before any privileged installation step."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import zipfile

MAX_ARCHIVE = 600 * 1024 * 1024
MAX_EXPANDED = 1500 * 1024 * 1024
REQUIRED = {"daemon-entry.py", "vpn/daemon.py", "vpn/core/guardian.py", "backend/bin/sing-box", "package.json", "main.py", "plugin.json", "dist/index.js", "desktop/deckport", "assets/deckport-vpn.svg", "installer/entry.py", "py_modules/yaml/__init__.py"}


def digest_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if not name or str(path) != name or path.is_absolute() or any(part in (".", "..") for part in path.parts) or any(c in name for c in ("\\", ":", "\x00")) or any(ord(c) < 32 for c in name):
        raise ValueError("Unsafe payload path")
    return path


def extract(archive, destination, expected):
    if not re.fullmatch(r"[a-f0-9]{64}", expected) or archive.stat().st_size > MAX_ARCHIVE or digest_file(archive) != expected:
        raise ValueError("Payload integrity check failed")
    destination.mkdir(mode=0o755)
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if len(entries) > 12000 or sum(x.file_size for x in entries) > MAX_EXPANDED:
            raise ValueError("Payload size limit exceeded")
        names = set()
        for entry in entries:
            safe_name(entry.filename)
            mode = entry.external_attr >> 16
            if stat.S_IFMT(mode) != stat.S_IFREG or stat.S_IMODE(mode) not in (0o644, 0o755) or entry.filename in names or entry.flag_bits & 1:
                raise ValueError("Payload links, special files or unsafe modes are forbidden")
            names.add(entry.filename)
        if "payload.json" not in names or source.getinfo("payload.json").file_size > 4 * 1024 * 1024:
            raise ValueError("Payload manifest is missing")
        manifest = json.loads(source.read("payload.json"))
        if manifest.get("format") != 1 or not REQUIRED <= names or set(manifest["files"]) != names - {"payload.json"}:
            raise ValueError("Incomplete payload")
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?", manifest["version"]):
            raise ValueError("Invalid product version")
        for entry in entries:
            target = destination.joinpath(*safe_name(entry.filename).parts)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            with source.open(entry) as incoming, target.open("xb") as output:
                shutil.copyfileobj(incoming, output, 1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            mode = stat.S_IMODE(entry.external_attr >> 16)
            target.chmod(mode)
            if entry.filename != "payload.json":
                record = manifest["files"][entry.filename]
                if record != {"sha256": digest_file(target), "mode": mode}:
                    raise ValueError("Payload file integrity check failed")
        package = json.loads((destination / "package.json").read_text())
        if package["version"] != manifest["version"] or (destination / "backend/bin/sing-box").read_bytes()[:4] != b"\x7fELF":
            raise ValueError("Invalid Linux product payload")
    return manifest
