"""Validate generated synthetic protocol configs with the actual pinned core."""
import argparse
import asyncio
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "py_modules")]
from vpn.core.config import generate
from vpn.subscription.model import sanitize


def fixtures():
    base = {"server": "203.0.113.1", "server_port": 443}
    uid = "11111111-1111-4111-8111-111111111111"
    tls = {"enabled": True, "server_name": "example.com"}
    key = base64.b64encode(bytes(range(32))).decode()
    yield "vless-tls", {**base, "type": "vless", "uuid": uid, "tls": tls}
    yield "vless-reality", {**base, "type": "vless", "uuid": uid, "flow": "xtls-rprx-vision", "tls": {**tls, "utls": {"enabled": True, "fingerprint": "chrome"}, "reality": {"enabled": True, "public_key": key.rstrip("="), "short_id": "abcdef"}}}
    yield "vmess-ws", {**base, "type": "vmess", "uuid": uid, "tls": tls, "transport": {"type": "ws", "path": "/vpn", "headers": {"Host": "example.com"}}}
    yield "trojan-grpc", {**base, "type": "trojan", "password": "synthetic-test-only", "tls": tls, "transport": {"type": "grpc", "service_name": "vpn"}}
    yield "shadowsocks", {**base, "type": "shadowsocks", "method": "aes-128-gcm", "password": "synthetic-test-only"}
    yield "socks", {**base, "type": "socks", "username": "test", "password": "synthetic-test-only"}
    yield "wireguard", {"type": "wireguard", "address": ["10.0.0.2/32", "fd00::2/128"], "private_key": key, "peers": [{"address": "203.0.113.1", "port": 51820, "public_key": key, "allowed_ips": ["0.0.0.0/0", "::/0"]}]}


async def main(binary):
    with tempfile.TemporaryDirectory(prefix="deckyvpn-check-") as directory:
        for name, raw in fixtures():
            config = await generate(sanitize(raw))
            path = Path(directory) / (name + ".json")
            path.write_text(json.dumps(config), encoding="utf-8")
            result = subprocess.run([str(binary), "check", "-c", str(path)], capture_output=True, text=True, timeout=10)
            if result.returncode:
                raise SystemExit(f"FAIL {name}: {result.stderr}")
            print(f"PASS {name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=ROOT / (".cache/sing-box.exe" if sys.platform == "win32" else "backend/bin/sing-box"))
    asyncio.run(main(parser.parse_args().binary))
