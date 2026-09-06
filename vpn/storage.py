import json
import os
import tempfile
from pathlib import Path


def private_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise RuntimeError("Unsafe storage directory")
    path.chmod(0o700)


def atomic_json(path: Path, data):
    private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
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
            self.data = json.loads(path.read_text(encoding="utf-8"))
            path.chmod(0o600)

    def save(self):
        atomic_json(self.path, self.data)
