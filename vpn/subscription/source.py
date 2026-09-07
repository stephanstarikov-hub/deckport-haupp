from .fetch import validate_url


def remote_subscription_url(text):
    if not isinstance(text, str):
        return None

    candidate = text.strip()

    if not candidate or "\n" in candidate or "\r" in candidate:
        return None

    if not candidate.lower().startswith(("https://", "http://")):
        return None

    validate_url(candidate)
    return candidate
