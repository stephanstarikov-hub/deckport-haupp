import asyncio
import ipaddress
from urllib.parse import urlsplit
from .subscription.fetch import PinnedHTTPS

# Each request is optional; failure of one service does not prevent connection.
ENDPOINTS = ["https://api.ipify.org/", "https://icanhazip.com/", "https://checkip.amazonaws.com/"]


def _request(host, address):
    connection = PinnedHTTPS(host, address, 4)
    try:
        connection.request("GET", "/", headers={"User-Agent": "DeckyVPN/0.1"})
        r = connection.getresponse()
        value = r.read(128).decode("ascii").strip()
        return str(ipaddress.ip_address(value)) if r.status == 200 else None
    except Exception:
        return None
    finally:
        connection.close()


async def public_ip():
    async def one(url):
        import socket
        name = urlsplit(url).hostname
        try:
            answers = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(name, 443, type=socket.SOCK_STREAM), 4)
            answers.sort(key=lambda answer: answer[0] != socket.AF_INET)
            return await asyncio.wait_for(asyncio.to_thread(_request, name, answers[0][4][0]), 5)
        except Exception:
            return None
    results = await asyncio.gather(*(one(u) for u in ENDPOINTS))
    return next((ip for ip in results if ip), None)
