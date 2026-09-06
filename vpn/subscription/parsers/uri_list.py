import json
from urllib.parse import urlsplit, parse_qs, unquote
from .base64_list import decode
from ...errors import VPNError, INVALID


def transport(kind, path="/", host="", service=""):
    if kind in ("", "tcp", None):
        return None
    if kind == "ws":
        return {"type": "ws", "path": path or "/", "headers": {"Host": host} if host else {}}
    if kind == "grpc":
        return {"type": "grpc", "service_name": service}
    if kind in ("http", "h2"):
        return {"type": "http", "path": path or "/", "host": host.split(",") if host else []}
    raise VPNError(INVALID)


def parse_uri(uri):
    if len(uri) > 16384:
        raise VPNError(INVALID)
    u = urlsplit(uri)
    q = {k: v[-1] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
    name = unquote(u.fragment)
    if u.scheme == "vmess":
        v = json.loads(decode(uri[8:].split("#")[0]))
        out = {"type": "vmess", "server": v.get("add"), "server_port": v.get("port"), "uuid": v.get("id"), "alter_id": v.get("aid", 0), "security": v.get("scy", "auto")}
        if v.get("tls") in ("tls", True, "1"):
            out["tls"] = {"enabled": True, "server_name": v.get("sni") or v.get("host") or v.get("add"), "insecure": str(v.get("allowInsecure", "0")).lower() in ("1", "true")}
        t = transport(v.get("net", "tcp"), v.get("path"), v.get("host", ""), v.get("path", ""))
        if v.get("type") not in (None, "", "none") and not t:
            raise VPNError(INVALID)
        if t:
            out["transport"] = t
        return out, v.get("ps", name)
    if u.scheme == "ss":
        if q.get("plugin"):
            raise VPNError(INVALID)
        authority = uri[5:].split("#")[0].split("?")[0].rstrip("/")
        if "@" not in authority:
            authority = decode(authority)
        auth, address = authority.rsplit("@", 1)
        credentials = unquote(auth) if ":" in auth else decode(auth)
        method, password = credentials.split(":", 1)
        endpoint = urlsplit("ss://" + address)
        return {"type": "shadowsocks", "server": endpoint.hostname, "server_port": endpoint.port, "method": method, "password": password}, name
    protocol = "socks" if u.scheme in ("socks", "socks5") else u.scheme
    if protocol not in ("vless", "trojan", "socks"):
        raise VPNError(INVALID)
    out = {"type": protocol, "server": u.hostname, "server_port": u.port}
    user = unquote(u.username or "")
    if protocol == "vless":
        out.update(uuid=user, flow=q.get("flow", ""))
        if q.get("encryption", "none") != "none":
            raise VPNError(INVALID)
    elif protocol == "trojan":
        out["password"] = user
    else:
        out.update(username=user, password=unquote(u.password or ""))
    security = q.get("security", "tls" if protocol == "trojan" else "none")
    if security in ("tls", "reality"):
        tls = {"enabled": True, "server_name": q.get("sni") or q.get("peer") or u.hostname, "insecure": q.get("allowInsecure", q.get("insecure", "0")) in ("1", "true")}
        if q.get("alpn"):
            tls["alpn"] = q["alpn"].split(",")
        if q.get("fp") or security == "reality":
            tls["utls"] = {"enabled": True, "fingerprint": q.get("fp", "chrome")}
        if security == "reality":
            tls["reality"] = {"enabled": True, "public_key": q.get("pbk"), "short_id": q.get("sid", "")}
        out["tls"] = tls
    elif security != "none":
        raise VPNError(INVALID)
    t = transport(q.get("type", "tcp"), q.get("path", "/"), q.get("host", ""), q.get("serviceName", ""))
    if q.get("headerType", "none") != "none" or q.get("packetEncoding"):
        raise VPNError(INVALID)
    if t:
        out["transport"] = t
    return out, name
