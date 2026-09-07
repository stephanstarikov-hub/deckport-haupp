import json
import os
import tempfile
from pathlib import Path
from .safe_fs import read_regular


def private_dir(path: Path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise RuntimeError("Unsafe storage directory")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise RuntimeError("Unsafe storage directory")
    path.chmod(0o700)


def atomic_json(path: Path, data):
    private_dir(path.parent)
    if path.is_symlink():
        raise RuntimeError("Unsafe storage file")
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Store:
    def __init__(self, path: Path):
        self.path = path
        private_dir(path.parent)
        self.data = {"subscriptions": [], "selected": None}
        if path.exists():
            if path.is_symlink():
                raise RuntimeError("Unsafe storage file")
            self.data = json.loads(read_regular(path, 64 * 1024 * 1024))
            path.chmod(0o600)
        self.data.setdefault("favorites", [])
        self.data.setdefault("desired_connection", False)
        self.data.setdefault("preferences", {"channel": "stable", "autostart": False})

    def save(self):
        atomic_json(self.path, self.data)
