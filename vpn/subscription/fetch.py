import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit

from ..errors import VPNError
from .parser import MAX_BYTES


HAPP_USER_AGENT = "Happ/5.5.0/linux"
MAX_REDIRECTS = 8


def validate_url(url):
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 33 for c in url):
        raise VPNError("Enter a valid HTTP/HTTPS subscription URL")
    try:
        u = urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.fragment:
            raise ValueError()
        port = u.port
        if port is not None and not (1 <= port <= 65535):
            raise ValueError()
    except ValueError:
        raise VPNError("Enter a valid HTTP/HTTPS subscription URL") from None
    return u


class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, name, address, port, timeout):
        super().__init__(name, port=port, timeout=timeout)
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, name, address, port, timeout):
        super().__init__(name, port=port, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def _store_response_cookies(response, hostname, cookie_jar):
    jar = cookie_jar.setdefault(hostname.lower(), {})
    for header, value in response.getheaders():
        if header.lower() != "set-cookie":
            continue
        first = value.split(";", 1)[0].strip()
        name, sep, cookie_value = first.partition("=")
        if not sep or not name or any(c in name for c in " \t\r\n;"):
            continue
        if any(ord(c) < 32 for c in cookie_value):
            continue
        jar[name] = cookie_value


def _cookie_header(hostname, cookie_jar):
    jar = cookie_jar.get(hostname.lower(), {})
    return "; ".join(f"{name}={value}" for name, value in jar.items())


def download(url):
    deadline = time.monotonic() + 25
    seen = {}
    cookie_jar = {}

    for _ in range(MAX_REDIRECTS + 1):
        u = validate_url(url)
        state = (url, _cookie_header(u.hostname, cookie_jar))
        seen[state] = seen.get(state, 0) + 1
        if seen[state] > 1:
            raise VPNError("Subscription redirect loop detected")

        connection = None
        try:
            port = u.port or (443 if u.scheme == "https" else 80)
            ips = list(
                dict.fromkeys(
                    r[4][0]
                    for r in socket.getaddrinfo(
                        u.hostname,
                        port,
                        type=socket.SOCK_STREAM,
                    )
                )
            )
            if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
                raise VPNError("Subscription must use a public HTTP/HTTPS endpoint")

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()

            if u.scheme == "https":
                connection = PinnedHTTPS(u.hostname, ips[0], port, min(10, remaining))
            else:
                connection = PinnedHTTP(u.hostname, ips[0], port, min(10, remaining))

            headers = {
                "User-Agent": HAPP_USER_AGENT,
                "Accept": "text/plain, application/json, application/yaml, application/x-yaml, application/octet-stream, */*;q=0.1",
                "Accept-Encoding": "identity",
            }
            cookie = _cookie_header(u.hostname, cookie_jar)
            if cookie:
                headers["Cookie"] = cookie

            connection.request(
                "GET",
                (u.path or "/") + ("?" + u.query if u.query else ""),
                headers=headers,
            )
            response = connection.getresponse()
            _store_response_cookies(response, u.hostname, cookie_jar)

            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location", "").strip()
                if not location:
                    raise VPNError("Subscription redirect did not include a target")
                url = urljoin(url, location)
                continue

            if response.status != 200:
                raise VPNError("Subscription could not be downloaded")

            if response.getheader("Content-Encoding", "identity") != "identity":
                raise VPNError("Compressed subscription response is not supported")

            chunks, total = [], 0
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError()
                part = response.read1(min(65536, MAX_BYTES + 1 - total))
                if not part:
                    break
                total += len(part)
                if total > MAX_BYTES:
                    raise VPNError("Subscription is too large")
                chunks.append(part)

            metadata = {}
            for pair in response.getheader("Subscription-Userinfo", "").split(";"):
                key, _, value = pair.strip().partition("=")
                if key in ("upload", "download", "total", "expire") and value.isdigit() and len(value) <= 20:
                    metadata[key] = int(value)

            return b"".join(chunks).decode("utf-8-sig"), metadata
        except VPNError:
            raise
        except Exception:
            raise VPNError("Subscription could not be downloaded") from None
        finally:
            if connection:
                connection.close()

    raise VPNError("Subscription redirected too many times")
