"""Real TUN/traffic/cleanup tests, only in a disposable network namespace.

Run: sudo unshare --net --mount --mount-proc python3 scripts/linux_smoke.py
No rules, interfaces or routes are installed in the host network namespace.
"""
import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vpn.core.config import generate, TUN, TABLE, RULE
from vpn.core.process import Core


def ip(*args):
    return subprocess.run(["ip", *args], check=True, capture_output=True, text=True).stdout


async def socks(reader, writer):
    """Synthetic SOCKS5 server; measures real TUN TCP flow end to end."""
    try:
        version, count = await reader.readexactly(2)
        await reader.readexactly(count)
        writer.write(b"\x05\x00")
        await writer.drain()
        header = await reader.readexactly(4)
        sizes = {1: 4, 4: 16}
        if header[3] == 3:
            count = (await reader.readexactly(1))[0]
        else:
            count = sizes[header[3]]
        await reader.readexactly(count + 2)
        writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        await writer.drain()
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\nTUN-TRAFFIC")
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def traffic():
    reader, writer = await asyncio.wait_for(asyncio.open_connection("198.51.100.10", 80), 5)
    writer.write(b"GET / HTTP/1.1\r\nHost: synthetic.example\r\n\r\n")
    await writer.drain()
    response = await asyncio.wait_for(reader.read(), 5)
    writer.close()
    await writer.wait_closed()
    assert response.endswith(b"TUN-TRAFFIC"), response


def clean_assert():
    assert not Path("/sys/class/net/" + TUN).exists(), "TUN was left behind"
    for family in ("-4", "-6"):
        rules = json.loads(ip(family, "-j", "rule", "show"))
        assert not any(RULE <= int(r.get("priority", -1)) < RULE + 20 for r in rules), rules


async def main():
    if os.geteuid() != 0 or os.readlink("/proc/self/ns/net") == os.readlink("/proc/1/ns/net"):
        raise SystemExit("Refusing host network namespace; run with sudo unshare --net --mount --mount-proc")
    if os.readlink("/proc/self/ns/mnt") == os.readlink("/proc/1/ns/mnt"):
        raise SystemExit("Refusing host mount namespace")
    # sysfs must reflect this network namespace rather than the inherited host view.
    subprocess.run(["mount", "-t", "sysfs", "sysfs", "/sys"], check=True)
    ip("link", "set", "lo", "up")
    ip("link", "add", "testwan", "type", "dummy")
    ip("addr", "add", "192.0.2.1/24", "dev", "testwan")
    ip("link", "set", "testwan", "up")
    ip("route", "add", "default", "dev", "testwan")
    server = await asyncio.start_server(socks, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="deckyvpn-linux-") as directory:
        runtime = Path(directory)
        config = await generate({"type": "socks", "server": "127.0.0.1", "server_port": port})
        # Dummy network is only an isolated test uplink. Loopback server must bind lo.
        config["outbounds"][0]["bind_interface"] = "lo"
        core = Core(ROOT, runtime)
        try:
            await core.start(config)
            assert await core.route_verified(), ip("-j", "route", "get", "1.1.1.1")
            await traffic()
            print("PASS: real system TCP traffic through TUN -> bundled sing-box -> SOCKS")
            await core.stop()
            clean_assert()
            print("PASS: Disconnect removes TUN and owned rules")
            await core.start(config)
            pid = int((runtime / "vpn.pid").read_text())
            os.kill(pid, signal.SIGKILL)
            await asyncio.wait_for(core.proc.wait(), 15)
            await core.stop()
            clean_assert()
            print("PASS: unexpected core crash cleans network")
            await core.start(config)
            core.proc.stdin.close()
            await asyncio.wait_for(core.proc.wait(), 15)
            clean_assert()
            print("PASS: parent pipe EOF cleans core and network")
            await core.start(config)
            os.kill(core.proc.pid, signal.SIGKILL)
            await core.proc.wait()
            await asyncio.sleep(2)
            await core.recover()
            clean_assert()
            print("PASS: guardian SIGKILL recovery cleans reserved network state")
        finally:
            await core.stop()
            server.close()
            await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
