"""GitHub Releases discovery and bounded HTTPS downloads; never runs as root."""
from dataclasses import dataclass
from functools import total_ordering
import hashlib
import json
from pathlib import Path
import re
import urllib.request
from urllib.parse import urlsplit
from vpn.errors import VPNError

REPO = "stephanstarikov-hub/deckport-vpn"
SETUP = "DeckPort-VPN-Setup-x86_64.AppImage"


@total_ordering
class Version:
    def __init__(self, text):
        match = re.fullmatch(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?", text)
        if not match:
            raise ValueError("Invalid release version")
        self.core = tuple(int(match[i]) for i in (1, 2, 3))
        self.pre = match[4].split(".") if match[4] else []
        if any(x.isdigit() and len(x) > 1 and x[0] == "0" for x in self.pre):
            raise ValueError("Invalid prerelease version")

    def __eq__(self, other):
        return self.core == other.core and self.pre == other.pre

    def __lt__(self, other):
        if self.core != other.core:
            return self.core < other.core
        if not self.pre or not other.pre:
            return bool(self.pre) and not other.pre
        for left, right in zip(self.pre, other.pre):
            if left != right:
                if left.isdigit() and right.isdigit():
                    return int(left) < int(right)
                if left.isdigit() != right.isdigit():
                    return left.isdigit()
                return left < right
        return len(self.pre) < len(other.pre)


def allowed_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.hostname not in {"api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}:
        raise VPNError("Release download address was rejected")


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        allowed_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def fetch(url, limit, destination=None, progress=None):
    allowed_url(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), HTTPSRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "DeckPort-VPN-Updater", "Accept": "application/vnd.github+json" if urlsplit(url).hostname == "api.github.com" else "application/octet-stream"})
    data = bytearray()
    count = 0
    stream = destination.open("xb") if destination else None
    try:
        with opener.open(request, timeout=30) as response:
            allowed_url(response.url)
            length = int(response.headers.get("Content-Length", 0))
            if length > limit:
                raise VPNError("Release download is too large")
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > limit:
                    raise VPNError("Release download is too large")
                if stream:
                    stream.write(chunk)
                else:
                    data.extend(chunk)
                if progress:
                    progress(min(99, count * 100 // length) if length else 0)
        return bytes(data)
    except VPNError:
        raise
    except Exception:
        raise VPNError("Release download failed; check the network and try again") from None
    finally:
        if stream:
            stream.close()


def choose_release(releases, installed, channel):
    if channel not in ("stable", "preview"):
        raise VPNError("Invalid update channel")
    candidates = []
    for release in releases:
        try:
            version = Version(release["tag_name"])
            if release.get("draft") or (channel == "stable" and (release.get("prerelease") or version.pre)) or version <= Version(installed):
                continue
            assets = {asset["name"]: asset["browser_download_url"] for asset in release["assets"]}
            if SETUP not in assets or SETUP + ".sha256" not in assets:
                continue
            for name in (SETUP, SETUP + ".sha256"):
                allowed_url(assets[name])
                prefix = f"https://github.com/{REPO}/releases/download/{release['tag_name']}/"
                if assets[name] != prefix + name:
                    raise ValueError("Unexpected asset")
            candidates.append((version, {"version": release["tag_name"].removeprefix("v"), "notes": (release.get("body") or "No release notes provided.")[:20000], "url": assets[SETUP], "checksum": assets[SETUP + ".sha256"]}))
        except (KeyError, TypeError, ValueError, VPNError):
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def check(installed, channel):
    releases = []
    for page in range(1, 6):
        batch = json.loads(fetch(f"https://api.github.com/repos/{REPO}/releases?per_page=100&page={page}", 8 * 1024 * 1024))
        if not isinstance(batch, list):
            raise VPNError("Release information is unavailable")
        releases.extend(batch)
        if len(batch) < 100:
            break
    return choose_release(releases, installed, channel)


def download_release(release, directory, progress=None):
    checksum = fetch(release["checksum"], 1024).decode("ascii").strip().split()
    if len(checksum) != 2 or checksum[1] != SETUP or not re.fullmatch(r"[a-fA-F0-9]{64}", checksum[0]):
        raise VPNError("Release checksum is invalid")
    target = Path(directory) / SETUP
    try:
        fetch(release["url"], 600 * 1024 * 1024, target, progress)
        with target.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != checksum[0].lower():
            raise VPNError("Release integrity check failed; nothing changed")
        target.chmod(0o755)
        return target
    except BaseException:
        target.unlink(missing_ok=True)
        raise
