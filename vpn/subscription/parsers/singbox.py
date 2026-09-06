from ...errors import VPNError, INVALID


def items(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        raise VPNError(INVALID)
    if "outbounds" in data or "endpoints" in data:
        return data.get("outbounds", []) + data.get("endpoints", [])
    if "type" in data:
        return [data]
    raise VPNError("Unsupported subscription format")


def convert(value):
    if not isinstance(value, dict):
        raise VPNError(INVALID)
    if value.get("type") == "wireguard" and "local_address" in value:
        value = dict(value)
        value["address"] = value["local_address"]
        if not value.get("peers"):
            value["peers"] = [{"address": value.get("server"), "port": value.get("server_port"), "public_key": value.get("peer_public_key"), "pre_shared_key": value.get("pre_shared_key"), "allowed_ips": ["0.0.0.0/0", "::/0"], **({"reserved": value["reserved"]} if "reserved" in value else {})}]
    return value, value.get("tag", "")
