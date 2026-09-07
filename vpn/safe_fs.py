"""No-follow file access, including every ancestor, on Linux."""
import os
from pathlib import Path
import stat


def read_regular(path, limit):
    path = Path(path).absolute()
    if os.name != "posix":
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("Unsafe file path")
        if not path.is_file() or path.stat().st_size > limit:
            raise ValueError("Invalid file size")
        return path.read_bytes()
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_fd
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError("Invalid file size")
            data = stream.read(limit + 1)
            if len(data) > limit:
                raise ValueError("Invalid file size")
            return data
    finally:
        os.close(directory)
