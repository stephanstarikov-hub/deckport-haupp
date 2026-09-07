import json
from .parsers.base64_list import decode
from ..errors import VPNError


SUPPORTED_URI_SCHEMES = (
    "vless://",
    "vmess://",
    "trojan://",
    "ss://",
    "socks://",
    "socks5://",
)


def _contains_supported_uri(text):
    for line in text.splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if value.lower().startswith(SUPPORTED_URI_SCHEMES):
            return True
    return False


def detect(text: str):
    text = text.lstrip("\ufeff").strip()

    if text.startswith(("{", "[")) and not text.startswith("[Interface]"):
        try:
            return "json", json.loads(text)
        except (ValueError, RecursionError):
            raise VPNError("Unsupported subscription format") from None

    if text.startswith("[Interface]"):
        return "wireguard", text

    if _contains_supported_uri(text):
        return "uri", text

    if "proxies:" in text:
        return "clash", text

    try:
        decoded = decode(text)
        if decoded == text:
            raise ValueError()
        if _contains_supported_uri(decoded):
            return "uri", decoded
    except (ValueError, UnicodeError):
        pass

    raise VPNError("Unsupported subscription format")
