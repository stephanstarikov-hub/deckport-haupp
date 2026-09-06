import base64


def decode(value: str) -> str:
    compact = "".join(value.split())
    return base64.b64decode(compact + "=" * (-len(compact) % 4), altchars=b"-_", validate=True).decode("utf-8-sig")
