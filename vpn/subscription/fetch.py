import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urlsplit, urljoin
from ..errors import VPNError
from .parser import MAX_BYTES


def validate_url(url):
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 33 for c in url):
        raise VPNError("Enter a valid HTTPS subscription URL")
    try:
        u = urlsplit(url)
        if u.scheme != "https" or not u.hostname or u.username or u.password or u.fragment or u.port not in (None, 443):
            raise ValueError()
    except ValueError:
        raise VPNError("Enter a valid HTTPS subscription URL (port 443)") from None
    return u


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, name, address, timeout):
        super().__init__(name, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # Connect to the validated IP, retaining TLS hostname verification/SNI.
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def download(url):
    deadline = time.monotonic() + 25
    for _ in range(4):
        u = validate_url(url)
        connection = None
        try:
            ips = list(dict.fromkeys(r[4][0] for r in socket.getaddrinfo(u.hostname, 443, type=socket.SOCK_STREAM)))
            if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
                raise VPNError("Subscription must use a public HTTPS endpoint")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            connection = PinnedHTTPS(u.hostname, ips[0], min(10, remaining))
            connection.request("GET", (u.path or "/") + ("?" + u.query if u.query else ""), headers={"User-Agent": "DeckyVPN/0.1", "Accept": "text/plain, application/json, application/yaml", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                url = urljoin(url, response.getheader("Location", ""))
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
