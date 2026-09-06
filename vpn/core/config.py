import asyncio
import copy
import ipaddress
import socket
from ..subscription.model import sanitize
from ..errors import VPNError

TUN = "deckyvpn0"
TABLE = 20777
RULE = 17770
CORE_VERSION = "1.14.0"


async def generate(raw):
    out = copy.deepcopy(sanitize(raw))
    # Resolve the endpoint before installing TUN. No bootstrap DNS bypass remains
    # while connected. Preserve its original TLS server_name / transport headers.
    target = out["peers"][0] if out["type"] == "wireguard" else out
    field = "address" if out["type"] == "wireguard" else "server"
    try:
        ipaddress.ip_address(target[field])
    except ValueError:
        try:
            answers = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(target[field], None, type=socket.SOCK_STREAM), 10)
            answers.sort(key=lambda answer: answer[0] != socket.AF_INET)
            target[field] = answers[0][4][0]
        except Exception:
            raise VPNError("VPN server address could not be resolved") from None
    config = {
        "log": {"level": "error", "timestamp": False},
        "dns": {"servers": [
            {"type": "https", "tag": "dns-primary", "server": "1.1.1.1", "path": "/dns-query", "detour": "vpn"},
            {"type": "https", "tag": "dns-secondary", "server": "9.9.9.9", "path": "/dns-query", "detour": "vpn"}
        ], "final": "dns-primary", "strategy": "prefer_ipv4"},
        "inbounds": [{"type": "tun", "tag": "tun", "interface_name": TUN,
                      "address": ["172.29.253.1/30", "fd72:6465:636b::1/126"],
                      "mtu": 1280, "auto_route": True, "auto_redirect": True,
                      "strict_route": True, "dns_mode": "hijack",
                      "iproute2_table_index": TABLE, "iproute2_rule_index": RULE,
                      "stack": "mixed"}],
        "route": {"auto_detect_interface": True, "default_domain_resolver": "dns-primary",
                  "rules": [{"port": 53, "action": "hijack-dns"}], "final": "vpn"},
        "outbounds": []
    }
    if out["type"] == "wireguard":
        config["endpoints"] = [out]
    else:
        config["outbounds"] = [out]
    return config
