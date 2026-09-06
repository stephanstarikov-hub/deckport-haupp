import json
from .parsers.base64_list import decode
from ..errors import VPNError


def detect(text: str):
    text = text.lstrip("\ufeff").strip()
    if text.startswith(("{", "[")) and not text.startswith("[Interface]"):
        try:
            return "json", json.loads(text)
        except (ValueError, RecursionError):
            raise VPNError("Unsupported subscription format") from None
    if text.startswith("[Interface]"):
        return "wireguard", text
    if any(line.strip().startswith(("vless://", "vmess://", "trojan://", "ss://", "socks://", "socks5://")) for line in text.splitlines()):
        return "uri", text
    if "proxies:" in text:
        return "clash", text
    try:
        decoded = decode(text)
        if decoded == text:
            raise ValueError()
        if "://" in decoded:
            return "uri", decoded
    except (ValueError, UnicodeError):
        pass
    raise VPNError("Unsupported subscription format")
