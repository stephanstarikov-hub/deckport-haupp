import asyncio
import base64
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from vpn.subscription.parser import parse
from vpn.subscription.fetch import validate_url, download
from vpn.subscription.model import public_node
from vpn.core.config import generate
from vpn.errors import VPNError

SID = "a" * 32
UUID = "11111111-1111-4111-8111-111111111111"
KEY = base64.b64encode(bytes(range(32))).decode()
VLESS = f"vless://{UUID}@example.com:443?security=tls&type=ws&path=%2Fvpn&sni=example.com#Germany"


class Parsers(unittest.TestCase):
    def test_plain_and_base64_have_stable_ids(self):
        a, skipped = parse(VLESS, SID)
        b, _ = parse(base64.b64encode(VLESS.encode()).decode(), SID)
        self.assertEqual(a, b)
        self.assertEqual(skipped, 0)
        self.assertEqual(a[0]["raw_config"]["transport"]["path"], "/vpn")
        self.assertNotIn(UUID, json.dumps(public_node(a[0])))

    def test_vmess_trojan_ss_socks(self):
        vmess = "vmess://" + base64.b64encode(json.dumps({"add": "example.com", "port": 443, "id": UUID, "ps": "VMess", "tls": "tls"}).encode()).decode()
        ss = "ss://" + base64.b64encode(b"aes-128-gcm:password").decode() + "@example.com:8388#SS"
        nodes, skipped = parse("\n".join([vmess, "trojan://secret@example.com:443#Trojan", ss, "socks5://user:pass@example.com:1080#SOCKS"]), SID)
        self.assertEqual({n["protocol"] for n in nodes}, {"vmess", "trojan", "shadowsocks", "socks"})
        self.assertEqual(skipped, 0)

    def test_clash(self):
        text = f'proxies:\n  - name: Germany\n    type: vless\n    server: example.com\n    port: 443\n    uuid: {UUID}\n    tls: true\n    network: ws\n    ws-opts:\n      path: /vpn\n'
        nodes, _ = parse(text, SID)
        self.assertEqual(nodes[0]["raw_config"]["tls"]["server_name"], "example.com")

    def test_json_does_not_import_routes_or_files(self):
        payload = {"inbounds": [{"type": "mixed", "listen": "0.0.0.0"}], "route": {"final": "direct"}, "outbounds": [{"type": "vless", "tag": "Node", "server": "example.com", "server_port": 443, "uuid": UUID}, {"type": "direct"}]}
        nodes, skipped = parse(json.dumps(payload), SID)
        self.assertEqual(skipped, 1)
        self.assertNotIn("inbounds", nodes[0]["raw_config"])
        payload["outbounds"][0]["tls"] = {"enabled": True, "certificate_path": "/etc/shadow"}
        with self.assertRaises(VPNError):
            parse(json.dumps(payload), SID)

    def test_wireguard_conf(self):
        text = f"[Interface]\nPrivateKey={KEY}\nAddress=10.0.0.2/32, fd00::2/128\n[Peer]\nPublicKey={KEY}\nEndpoint=example.com:51820\nAllowedIPs=0.0.0.0/0, ::/0"
        nodes, _ = parse(text, SID)
        self.assertEqual(nodes[0]["protocol"], "wireguard")
        self.assertEqual(len(nodes[0]["raw_config"]["peers"]), 1)
        with self.assertRaises(VPNError):
            parse(text.replace("[Peer]", "PostUp=touch /tmp/pwn\n[Peer]"), SID)

    def test_reject_malicious_yaml_and_aliases(self):
        for value in ("proxies: !!python/object/apply:os.system [echo unsafe]", "proxies: &x [*x]"):
            with self.assertRaises(VPNError):
                parse(value, SID)

    def test_partial_subscription_warns(self):
        nodes, skipped = parse(VLESS + "\nvless://broken\nhy2://unsupported", SID)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(skipped, 2)

    def test_no_ssl_bypass_or_shell_transport(self):
        for text in (VLESS.replace("security=tls", "security=tls&allowInsecure=1"), VLESS.replace("type=ws", "type=xhttp")):
            with self.assertRaises(VPNError):
                parse(text, SID)

    def test_fetch_restricts_url(self):
        for url in ("file:///etc/shadow", "http://example.com", "https://user:password@example.com", "https://example.com:8080", "https://example.com/\r\nCookie:x"):
            with self.assertRaises(VPNError):
                validate_url(url)
        validate_url("https://example.com/sub/token")
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaisesRegex(VPNError, "public HTTPS"):
                download("https://example.com/token")

    def test_limits(self):
        with self.assertRaises(VPNError):
            parse("A" * (4 * 1024 * 1024 + 1), SID)

    def test_credentials_in_provider_label_are_removed(self):
        nodes, _ = parse(VLESS.replace("#Germany", "#" + UUID), SID)
        self.assertNotIn(UUID, json.dumps(public_node(nodes[0])))

    def test_yaml_nesting_limit(self):
        with self.assertRaises(VPNError):
            parse("proxies: " + "[" * 40 + "]" * 40, SID)


class Config(unittest.IsolatedAsyncioTestCase):
    async def test_full_tunnel_dns_and_ipv6(self):
        nodes, _ = parse(VLESS.replace("example.com:443", "203.0.113.1:443"), SID)
        config = await generate(nodes[0]["raw_config"])
        tun = config["inbounds"][0]
        self.assertTrue(tun["auto_route"])
        self.assertTrue(tun["strict_route"])
        self.assertEqual(tun["dns_mode"], "hijack")
        self.assertEqual(len(tun["address"]), 2)
        self.assertTrue(all(d["detour"] == "vpn" for d in config["dns"]["servers"]))
        self.assertEqual(config["route"]["final"], "vpn")
        self.assertEqual(config["outbounds"][0]["tls"]["server_name"], "example.com")


if __name__ == "__main__":
    unittest.main()
