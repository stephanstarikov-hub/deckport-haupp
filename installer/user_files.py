"""Anchor all privileged writes in opened directory descriptors, never home paths."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import stat
import uuid


@contextmanager
def directory(path, create=False, owner=None):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Unsafe directory")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            try:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o755, dir_fd=fd)
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                if owner:
                    os.fchown(next_fd, *owner)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def read_at(fd, name, limit=1024 * 1024):
    try:
        child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return None
    with os.fdopen(child, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("Unsafe existing file")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("File size limit exceeded")
        return data


def write_at(fd, name, data, owner=None):
    # Existing symlinks are refused; atomic rename never follows the last path.
    read_at(fd, name)
    temporary = ".deckport-" + uuid.uuid4().hex
    child = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=fd)
    try:
        with os.fdopen(child, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            if owner:
                os.fchown(stream.fileno(), *owner)
        os.rename(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


def plugin_swap(release, plugins, backup, progress_saved):
    with directory(plugins) as parent:
        try:
            target = os.open("decky-vpn", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        except FileNotFoundError:
            target = None
        if target is not None:
            try:
                manifest = json.loads(read_at(target, "plugin.json", 16384))
                if manifest.get("name") not in ("Decky VPN", "DeckPort VPN"):
                    raise ValueError("Target contains a different plugin")
            finally:
                os.close(target)
        name = ".deckport-stage-" + uuid.uuid4().hex
        os.mkdir(name, 0o700, dir_fd=parent)
        staged = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            if os.fstat(staged).st_uid != os.geteuid():
                raise ValueError("Unsafe staging directory")
            staging_path = Path(f"/proc/self/fd/{staged}")
            for item in ("main.py", "plugin.json", "package.json"):
                write_at(staged, item, (release / item).read_bytes())
            for item in ("dist", "vpn"):
                shutil.copytree(release / item, staging_path / item)
            os.fchmod(staged, 0o755)
            if target is not None:
                os.rename("decky-vpn", backup, src_dir_fd=parent, dst_dir_fd=parent)
            progress_saved()
            # Ensure the stage name still refers to the directory we built.
            if os.stat(name, dir_fd=parent, follow_symlinks=False).st_ino != os.fstat(staged).st_ino:
                raise ValueError("Staging directory was replaced")
            os.rename(name, "decky-vpn", src_dir_fd=parent, dst_dir_fd=parent)
        finally:
            os.close(staged)


def plugin_restore(plugins, backup, new_moved):
    with directory(plugins) as parent:
        if new_moved:
            try:
                os.rename("decky-vpn", ".deckport-failed-" + uuid.uuid4().hex, src_dir_fd=parent, dst_dir_fd=parent)
            except FileNotFoundError:
                pass
        try:
            os.rename(backup, "decky-vpn", src_dir_fd=parent, dst_dir_fd=parent)
        except FileNotFoundError:
            pass


def remove_plugin(plugins):
    with directory(plugins) as parent:
        try:
            child = os.open("decky-vpn", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        except FileNotFoundError:
            return
        try:
            manifest = json.loads(read_at(child, "plugin.json", 16384))
            if manifest.get("name") not in ("DeckPort VPN", "Decky VPN"):
                raise ValueError("Target contains a different plugin")
        finally:
            os.close(child)
        tombstone = ".deckport-remove-" + uuid.uuid4().hex
        os.rename("decky-vpn", tombstone, src_dir_fd=parent, dst_dir_fd=parent)
        # Linux shutil uses its fd-based, symlink-resistant rmtree implementation.
        if not shutil.rmtree.avoids_symlink_attacks:
            raise ValueError("Safe directory removal is unavailable")
        shutil.rmtree(tombstone, dir_fd=parent)
