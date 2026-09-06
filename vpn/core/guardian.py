"""Linux-only process guardian. Parent pipe EOF also covers abrupt Decky death.

Only this process owns core and routing cleanup. No provider data is executed.
Runs independently of Decky's asyncio loop and frontend lifetime.
"""
import fcntl
import ctypes
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

TUN, TABLE, RULE = "deckyvpn0", 20777, 17770
STOP = False


def command(*args, allow_failure=False):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False)
    if result.returncode and not allow_failure:
        raise RuntimeError("Network operation failed")
    return result


def rules(family):
    return json.loads(command("ip", family, "-j", "rule", "show").stdout)


def owned(rule):
    return RULE <= int(rule.get("priority", -1)) < RULE + 20


def clean():
    ok = True
    for family in ("-4", "-6"):
        try:
            for rule in rules(family):
                if owned(rule):
                    command("ip", family, "rule", "del", "pref", str(rule["priority"]))
            command("ip", family, "route", "flush", "table", str(TABLE), allow_failure=True)
            if any(owned(r) for r in rules(family)):
                ok = False
        except Exception:
            ok = False
    try:
        if Path("/sys/class/net/" + TUN).exists():
            command("ip", "link", "delete", "dev", TUN)
        ok = ok and not Path("/sys/class/net/" + TUN).exists()
    except Exception:
        ok = False
    return ok


def stop_signal(_signum, _frame):
    global STOP
    STOP = True


def parent_death_signal():
    # Guardian is single-threaded; this pre-exec call cannot deadlock on Python
    # locks. Kernel stops core even if guardian itself receives SIGKILL.
    parent = os.getppid()
    if ctypes.CDLL(None).prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        os._exit(127)
    if os.getppid() != parent:
        os._exit(127)


def main():
    # Paths come only from our backend, never a subscription.
    binary, config, runtime = map(Path, sys.argv[1:4])
    runtime = runtime.resolve(strict=True)
    if config.resolve().parent != runtime or binary.name != "sing-box":
        return 2
    lock = (runtime / "guardian.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 3
    marker = runtime / "network-owned.json"
    child = None
    claimed = False
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, stop_signal)
    try:
        # An earlier killed guardian can leave only its own reserved rules.
        if marker.exists():
            if not clean():
                return 4
            marker.unlink()
        for family in ("-4", "-6"):
            if any(owned(r) or str(r.get("table")) == str(TABLE) for r in rules(family)):
                return 5
            routes = command("ip", family, "-j", "route", "show", "table", str(TABLE), allow_failure=True)
            if routes.returncode == 0 and json.loads(routes.stdout or b"[]"):
                return 5
        if Path("/sys/class/net/" + TUN).exists():
            return 5
        if "--cleanup" in sys.argv:
            return 0
        with marker.open("x") as stream:
            json.dump({"table": TABLE, "rule": RULE, "tun": TUN}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        claimed = True
        # Core output can contain addresses or credentials. Deliberately discard it.
        child = subprocess.Popen([str(binary), "run", "-c", str(config)], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, preexec_fn=parent_death_signal)
        (runtime / "vpn.pid").write_text(str(child.pid), encoding="ascii")
        selector = selectors.DefaultSelector()
        selector.register(sys.stdin, selectors.EVENT_READ)
        while not STOP and child.poll() is None:
            if selector.select(timeout=0.25):
                if not os.read(sys.stdin.fileno(), 1024):
                    break
        return 0 if STOP else 6
    except Exception:
        return 7
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        if claimed:
            if clean():
                marker.unlink(missing_ok=True)
            (runtime / "vpn.pid").unlink(missing_ok=True)
            config.unlink(missing_ok=True)


if __name__ == "__main__":
    os.umask(0o077)
    sys.exit(main())
