import configparser
from urllib.parse import urlsplit
from ...errors import VPNError, INVALID


def convert(text):
    p = configparser.ConfigParser(interpolation=None, strict=True)
    p.read_string(text)
    if set(p.sections()) != {"Interface", "Peer"}:
        raise VPNError(INVALID)
    i, peer = p["Interface"], p["Peer"]
    if any(k in i for k in ("preup", "postup", "predown", "postdown")):
        raise VPNError(INVALID)
    endpoint = urlsplit("wg://" + peer["endpoint"])
    return {"type": "wireguard", "address": [a.strip() for a in i["address"].split(",")], "private_key": i["privatekey"], "peers": [{"address": endpoint.hostname, "port": endpoint.port, "public_key": peer["publickey"], "pre_shared_key": peer.get("presharedkey"), "allowed_ips": [a.strip() for a in peer["allowedips"].split(",")]}]}, "WireGuard"
