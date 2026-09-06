import base64
import hashlib
import ipaddress
import json
import re
import uuid
from ..errors import VPNError, INVALID


def string(value, maximum=1024, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not value and not empty) or any(ord(c) < 32 for c in value):
        raise VPNError(INVALID)
    return value


def port(value):
    if isinstance(value, bool):
        raise VPNError(INVALID)
    try:
        result = int(value)
        if str(result) != str(value) or not 1 <= result <= 65535:
            raise ValueError()
        return result
    except (TypeError, ValueError):
        raise VPNError(INVALID) from None


def host(value):
    value = string(value, 253)
    try:
        ipaddress.ip_address(value)
    except ValueError:
        if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", value) or ".." in value:
            raise VPNError(INVALID)
    return value


def key(value):
    try:
        if len(base64.b64decode(string(value), validate=True)) != 32:
            raise ValueError()
    except ValueError:
        raise VPNError(INVALID) from None
    return value


def sanitize(config):
    """Rebuild a single outbound from a closed schema. Never pass a provider config to core."""
    if not isinstance(config, dict):
        raise VPNError(INVALID)
    protocol = config.get("type")
    if protocol not in ("vless", "vmess", "trojan", "shadowsocks", "socks", "wireguard"):
        raise VPNError(INVALID)
    if any(k in config for k in ("detour", "plugin", "plugin_opts", "bind_interface", "routing_mark", "domain_resolver")):
        raise VPNError(INVALID)
    if protocol == "wireguard":
        peers = config.get("peers", [])
        if not isinstance(peers, list) or len(peers) != 1:
            raise VPNError(INVALID)
        p = peers[0]
        addresses = config.get("address", [])
        if not isinstance(addresses, list) or not 1 <= len(addresses) <= 8:
            raise VPNError(INVALID)
        try:
            addresses = [str(ipaddress.ip_interface(a)) for a in addresses]
            allowed = [str(ipaddress.ip_network(a, strict=False)) for a in p["allowed_ips"]]
        except (KeyError, ValueError, TypeError):
            raise VPNError(INVALID) from None
        if "0.0.0.0/0" not in allowed:
            raise VPNError("WireGuard requires IPv4 default allowed IPs for full tunnel")
        peer = {"address": host(p.get("address")), "port": port(p.get("port")), "public_key": key(p.get("public_key")), "allowed_ips": allowed}
        if p.get("pre_shared_key"):
            peer["pre_shared_key"] = key(p["pre_shared_key"])
        if "reserved" in p:
            r = p["reserved"]
            if not isinstance(r, list) or len(r) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in r):
                raise VPNError(INVALID)
            peer["reserved"] = r
        peer["persistent_keepalive_interval"] = 25
        return {"type": protocol, "tag": "vpn", "system": False, "address": addresses, "private_key": key(config.get("private_key")), "peers": [peer], "mtu": 1280}
    out = {"type": protocol, "tag": "vpn", "server": host(config.get("server")), "server_port": port(config.get("server_port"))}
    if protocol in ("vless", "vmess"):
        try:
            out["uuid"] = str(uuid.UUID(config.get("uuid", "")))
        except (ValueError, TypeError, AttributeError):
            raise VPNError(INVALID) from None
    if protocol == "vless" and config.get("flow"):
        if config["flow"] != "xtls-rprx-vision":
            raise VPNError(INVALID)
        out["flow"] = config["flow"]
    if protocol == "vmess":
        security = config.get("security", "auto")
        if security not in ("auto", "none", "zero", "aes-128-gcm", "chacha20-poly1305"):
            raise VPNError(INVALID)
        out.update(security=security, alter_id=int(config.get("alter_id", 0)))
    if protocol in ("trojan", "shadowsocks"):
        out["password"] = string(config.get("password"), 4096)
    if protocol == "shadowsocks":
        out["method"] = string(config.get("method"), 100)
    if protocol == "socks":
        out["version"] = "5"
        if config.get("username"):
            out["username"] = string(config["username"])
            out["password"] = string(config.get("password", ""), empty=True)
    tls = config.get("tls")
    if tls:
        if not isinstance(tls, dict) or tls.get("insecure") or any(k in tls for k in ("certificate_path", "key_path", "ech", "client_certificate_path", "client_key_path")):
            raise VPNError(INVALID)
        out["tls"] = {"enabled": True, "server_name": host(tls.get("server_name") or out["server"])}
        if tls.get("alpn"):
            if not isinstance(tls["alpn"], list) or len(tls["alpn"]) > 8:
                raise VPNError(INVALID)
            out["tls"]["alpn"] = [string(v, 100) for v in tls["alpn"]]
        if tls.get("utls", {}).get("enabled"):
            out["tls"]["utls"] = {"enabled": True, "fingerprint": string(tls["utls"].get("fingerprint", "chrome"), 50)}
        if tls.get("reality", {}).get("enabled"):
            reality = tls["reality"]
            public = string(reality.get("public_key"), 64)
            short = string(reality.get("short_id", ""), 16, empty=True)
            if not re.fullmatch(r"[0-9a-fA-F]{0,16}", short) or len(short) % 2:
                raise VPNError(INVALID)
            out["tls"]["reality"] = {"enabled": True, "public_key": public, "short_id": short}
    elif protocol == "trojan":
        raise VPNError(INVALID)
    transport = config.get("transport")
    if transport:
        kind = transport.get("type")
        if kind == "ws":
            headers = transport.get("headers", {})
            if not isinstance(headers, dict) or len(headers) > 16:
                raise VPNError(INVALID)
            out["transport"] = {"type": "ws", "path": string(transport.get("path", "/"), 2048), "headers": {string(k, 100): string(v, 2048) for k, v in headers.items()}}
        elif kind == "grpc":
            out["transport"] = {"type": "grpc", "service_name": string(transport.get("service_name", ""), 1024, empty=True)}
        elif kind == "http":
            out["transport"] = {"type": "http", "path": string(transport.get("path", "/"), 2048)}
            hosts = transport.get("host", [])
            if not isinstance(hosts, list) or len(hosts) > 16:
                raise VPNError(INVALID)
            out["transport"]["host"] = [host(h) for h in hosts]
        else:
            raise VPNError(INVALID)
    return out


def node(config, name, subscription_id):
    raw = sanitize(config)
    digest = hashlib.sha256((subscription_id + json.dumps(raw, sort_keys=True)).encode()).hexdigest()[:32]
    endpoint = raw["peers"][0] if raw["type"] == "wireguard" else {"address": raw["server"], "port": raw["server_port"]}
    # Provider labels are untrusted; never derive a label from a URI or credentials.
    label = str(name or raw["type"].upper())[:100]
    if "://" in label or any(k in label.lower() for k in ("password=", "token=", "uuid=")):
        label = raw["type"].upper()
    label = "".join(c for c in label if ord(c) >= 32)
    def secrets(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if k in ("uuid", "password", "private_key", "pre_shared_key", "username") and isinstance(v, str) and v:
                    yield v
                else:
                    yield from secrets(v)
        elif isinstance(value, list):
            for v in value:
                yield from secrets(v)
    if any(secret in label for secret in secrets(raw)):
        label = raw["type"].upper()
    return {"id": digest, "name": label, "protocol": raw["type"], "host": endpoint["address"], "port": endpoint["port"], "country": "", "metadata": {}, "raw_config": raw}


def public_node(n):
    return {k: n[k] for k in ("id", "name", "protocol", "country")}
