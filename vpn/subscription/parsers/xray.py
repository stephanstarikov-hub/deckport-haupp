from ...errors import VPNError, INVALID


SUPPORTED = ("vless", "vmess")


def is_xray(data):
    if isinstance(data, list):
        return bool(data) and all(isinstance(v, dict) for v in data) and any(
            "outbounds" in v or "remarks" in v for v in data
        )
    return isinstance(data, dict) and "outbounds" in data and "type" not in data


def _blocked(config):
    remarks = str(config.get("remarks", "")).lower()
    if any(word in remarks for word in ("подписка неактивна", "пополните баланс", "inactive", "expired")):
        return True
    for outbound in config.get("outbounds", []):
        if not isinstance(outbound, dict):
            continue
        settings = outbound.get("settings", {})
        for vnext in settings.get("vnext", []) if isinstance(settings, dict) else []:
            if isinstance(vnext, dict) and str(vnext.get("address", "")).lower() == "subscription-blocked.invalid":
                return True
    return False


def items(data):
    configs = data if isinstance(data, list) else [data]
    if configs and all(_blocked(v) for v in configs if isinstance(v, dict)):
        raise VPNError("Subscription is inactive")
    return configs


def _tls_from_stream(stream):
    security = str(stream.get("security", "")).lower()
    if security not in ("tls", "reality"):
        return None

    if security == "reality":
        src = stream.get("realitySettings", {})
    else:
        src = stream.get("tlsSettings", {})

    tls = {
        "enabled": True,
        "server_name": src.get("serverName") or src.get("server_name"),
    }
    fingerprint = src.get("fingerprint")
    if fingerprint:
        tls["utls"] = {"enabled": True, "fingerprint": fingerprint}

    if security == "reality":
        tls["reality"] = {
            "enabled": True,
            "public_key": src.get("publicKey") or src.get("public_key"),
            "short_id": src.get("shortId") or src.get("short_id") or "",
        }

    return tls


def _transport_from_stream(stream):
    network = str(stream.get("network", "")).lower()
    if network in ("", "tcp"):
        return None
    if network == "ws":
        src = stream.get("wsSettings", {})
        return {
            "type": "ws",
            "path": src.get("path", "/"),
            "headers": src.get("headers", {}),
        }
    if network == "grpc":
        src = stream.get("grpcSettings", {})
        return {
            "type": "grpc",
            "service_name": src.get("serviceName", ""),
        }
    if network in ("http", "h2"):
        src = stream.get("httpSettings", {}) or stream.get("http2Settings", {})
        hosts = src.get("host", [])
        if isinstance(hosts, str):
            hosts = [hosts]
        return {
            "type": "http",
            "path": src.get("path", "/"),
            "host": hosts,
        }
    raise VPNError(INVALID)


def _convert_outbound(outbound):
    protocol = str(outbound.get("protocol", "")).lower()
    if protocol not in SUPPORTED:
        raise VPNError(INVALID)

    settings = outbound.get("settings")
    if not isinstance(settings, dict):
        raise VPNError(INVALID)

    vnext = settings.get("vnext")
    if not isinstance(vnext, list) or not vnext or not isinstance(vnext[0], dict):
        raise VPNError(INVALID)
    server = vnext[0]

    users = server.get("users")
    if not isinstance(users, list) or not users or not isinstance(users[0], dict):
        raise VPNError(INVALID)
    user = users[0]

    config = {
        "type": protocol,
        "server": server.get("address"),
        "server_port": server.get("port"),
        "uuid": user.get("id"),
    }

    if protocol == "vless" and user.get("flow"):
        config["flow"] = user["flow"]

    if protocol == "vmess":
        config["security"] = user.get("security", "auto")
        config["alter_id"] = user.get("alterId", user.get("alter_id", 0))

    stream = outbound.get("streamSettings", {})
    if not isinstance(stream, dict):
        raise VPNError(INVALID)

    tls = _tls_from_stream(stream)
    if tls:
        config["tls"] = tls

    transport = _transport_from_stream(stream)
    if transport:
        config["transport"] = transport

    return config


def convert(config):
    if not isinstance(config, dict) or _blocked(config):
        raise VPNError(INVALID)

    for outbound in config.get("outbounds", []):
        if isinstance(outbound, dict) and str(outbound.get("protocol", "")).lower() in SUPPORTED:
            return _convert_outbound(outbound), config.get("remarks", "")

    raise VPNError(INVALID)
