from .uri_list import transport
from ...errors import VPNError, INVALID


def load(text):
    import yaml
    # Reject aliases to avoid recursive objects and expansion attacks.
    depth = 0
    for event in yaml.parse(text):
        if isinstance(event, yaml.AliasEvent):
            raise VPNError("YAML aliases are not supported")
        if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
            depth += 1
        elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
            depth -= 1
        if depth > 30 or (isinstance(event, yaml.ScalarEvent) and len(event.value) > 16384):
            raise VPNError("YAML subscription exceeds safe nesting or field limits")
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or not isinstance(data.get("proxies"), list):
        raise VPNError("Unsupported subscription format")
    return data["proxies"]


def convert(v):
    if not isinstance(v, dict) or v.get("dialer-proxy") or v.get("plugin") or v.get("skip-cert-verify"):
        raise VPNError(INVALID)
    kind = {"ss": "shadowsocks", "socks5": "socks"}.get(v.get("type"), v.get("type"))
    out = {"type": kind, "server": v.get("server"), "server_port": v.get("port")}
    for k in ("uuid", "password", "username", "flow"):
        if k in v:
            out[k] = v[k]
    if kind == "shadowsocks":
        out["method"] = v.get("cipher")
    if kind == "vmess":
        out.update(security=v.get("cipher", "auto"), alter_id=v.get("alterId", 0))
    if kind == "wireguard":
        out = {"type": kind, "private_key": v.get("private-key"), "address": [], "peers": [{"address": v.get("server"), "port": v.get("port"), "public_key": v.get("public-key"), "pre_shared_key": v.get("pre-shared-key"), "allowed_ips": v.get("allowed-ips", ["0.0.0.0/0", "::/0"])}]}
        for key, prefix in (("ip", "/32"), ("ipv6", "/128")):
            if v.get(key):
                out["address"].append(v[key] if "/" in v[key] else v[key] + prefix)
        if "reserved" in v:
            out["peers"][0]["reserved"] = v["reserved"]
        return out, v.get("name")
    if v.get("tls") or kind == "trojan" or v.get("reality-opts"):
        tls = {"enabled": True, "server_name": v.get("servername") or v.get("sni") or v.get("server")}
        if v.get("alpn"):
            tls["alpn"] = v["alpn"]
        if v.get("client-fingerprint") or v.get("reality-opts"):
            tls["utls"] = {"enabled": True, "fingerprint": v.get("client-fingerprint", "chrome")}
        if v.get("reality-opts"):
            tls["reality"] = {"enabled": True, "public_key": v["reality-opts"].get("public-key"), "short_id": v["reality-opts"].get("short-id", "")}
        out["tls"] = tls
    net = v.get("network", "tcp")
    ws = v.get("ws-opts", {})
    t = transport(net, ws.get("path", "/"), ws.get("headers", {}).get("Host", ""), v.get("grpc-opts", {}).get("grpc-service-name", ""))
    if t:
        out["transport"] = t
    return out, v.get("name")
