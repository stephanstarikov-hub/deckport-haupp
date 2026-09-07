from .detect import detect
from .model import node
from .parsers import uri_list, singbox, clash, wireguard, xray
from ..errors import VPNError

MAX_BYTES = 4 * 1024 * 1024
MAX_NODES = 2000


def parse(text, subscription_id):
    if not isinstance(text, str) or len(text.encode()) > MAX_BYTES:
        raise VPNError("Subscription is too large")
    try:
        kind, data = detect(text)
        if kind == "uri":
            entries = [v.strip() for v in data.splitlines() if v.strip() and not v.lstrip().startswith("#")]
            converter = uri_list.parse_uri
        elif kind == "clash":
            entries, converter = clash.load(data), clash.convert
        elif kind == "json":
            if isinstance(data, dict) and "proxies" in data:
                entries, converter = data["proxies"], clash.convert
            elif xray.is_xray(data):
                if xray.inactive(data):
                    return [], 0
                entries, converter = xray.items(data), xray.convert
            else:
                entries, converter = singbox.items(data), singbox.convert
        else:
            entries, converter = [data], wireguard.convert
        if not isinstance(entries, list) or len(entries) > MAX_NODES:
            raise VPNError("Subscription has too many entries")
        nodes, skipped, seen = [], 0, set()
        for entry in entries:
            try:
                config, name = converter(entry)
                n = node(config, name, subscription_id)
                if n["id"] not in seen:
                    nodes.append(n)
                    seen.add(n["id"])
            except (VPNError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
                skipped += 1
        if not nodes:
            raise VPNError("No supported valid servers found in subscription")
        return nodes, skipped
    except VPNError:
        raise
    except Exception:
        raise VPNError("Unsupported subscription format") from None
