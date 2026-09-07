import asyncio
import copy
import json
import logging
import ipaddress
import socket
import os
import hashlib
from logging.handlers import RotatingFileHandler
from pathlib import Path
import time
import uuid
from .core.config import generate, CORE_VERSION
from .core.process import Core
from .errors import VPNError
from .network import public_ip
from .storage import Store, private_dir, atomic_json
from .subscription.fetch import download, validate_url
from .subscription.model import public_node
from .subscription.parser import parse
from .safe_fs import read_regular
from .version import VERSION, PROTOCOL_VERSION


class Service:
    def __init__(self, root, settings, runtime, logs, emit):
        for p in (settings, runtime, logs):
            private_dir(p)
        self.store = Store(settings / "subscriptions.json")
        self.import_dir = settings / "import"
        private_dir(self.import_dir)
        self.runtime, self.logs, self.emit = runtime, logs, emit
        self.core = Core(root, runtime)
        self.state = {"state": "DISCONNECTED", "server": None, "selected": self.store.data["selected"], "error": None, "before_ip": None, "public_ip": None, "verification": None, "since": None}
        self.lock = asyncio.Lock()
        self.download_lock = asyncio.Lock()
        self.task = None
        self.monitor = None
        self.closing = False
        self.maintenance = False
        self.legacy_import_dir = None
        self.retry_at = 0
        self.retry_delay = 2
        self.network_signature = None
        self.last_tick = self.boottime()
        self.logger = logging.getLogger("decky-vpn-safe")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        handler = RotatingFileHandler(logs / "plugin.log", maxBytes=128 * 1024, backupCount=2, encoding="utf-8")
        self.logger.addHandler(handler)
        self.log_handler = handler

    async def initialize(self):
        try:
            await self.core.recover()
        except VPNError as e:
            await self.set_state("ERROR", error=str(e))
        self.monitor = asyncio.create_task(self.watch())
        if self.store.data["desired_connection"] and self.store.data["selected"]:
            await self.set_state("RECONNECTING", error=None)

    async def set_state(self, state, **kwargs):
        self.state.update(state=state, **kwargs)
        self.logger.info("State: %s", state)
        atomic_json(self.runtime / "state.json", self.state)
        try:
            await asyncio.wait_for(self.emit("vpn_status", self.status()), 2)
        except Exception:
            pass

    def status(self):
        result = copy.deepcopy(self.state)
        result.update(selected_server=None, selected_subscription=None, version=VERSION, maintenance=self.maintenance)
        for subscription in self.store.data["subscriptions"]:
            for n in subscription["nodes"]:
                if n["id"] == self.state["selected"]:
                    result.update(selected_server=public_node(n), selected_subscription=subscription["id"])
        return result

    def subscriptions(self):
        return [{
            "id": s["id"],
            "name": s["name"],
            "count": len(s["nodes"]),
            "updated": s["updated"],
            "metadata": s["metadata"],
            "skipped": s["skipped"],
            "source_type": s.get("source_type", "url"),
            "source_label": s.get("source") if s.get("source_type") == "file" else "URL",
        } for s in self.store.data["subscriptions"]]

    @staticmethod
    def validate_import_filename(filename):
        if (
            not isinstance(filename, str)
            or not 1 <= len(filename) <= 160
            or filename != Path(filename).name
            or "/" in filename
            or "\\" in filename
            or any(ord(c) < 32 for c in filename)
        ):
            raise VPNError("Invalid import filename")

        if Path(filename).suffix.lower() not in (
            ".txt", ".conf", ".json", ".yaml", ".yml"
        ):
            raise VPNError("Unsupported subscription file type")

        return filename

    def import_files(self):
        files = []

        paths = list(self.import_dir.iterdir())
        if self.legacy_import_dir and self.legacy_import_dir.is_dir() and not self.legacy_import_dir.is_symlink():
            paths += list(self.legacy_import_dir.iterdir())[:100]
        seen = set()
        for path in paths:
            try:
                if path.is_symlink() or not path.is_file():
                    continue

                self.validate_import_filename(path.name)
                if path.name in seen:
                    continue
                seen.add(path.name)

                stat = path.stat()
                if stat.st_size > 8 * 1024 * 1024:
                    continue

                files.append({
                    "name": path.name,
                    "size": stat.st_size,
                    "modified": int(stat.st_mtime),
                })
            except (OSError, VPNError):
                continue

        files.sort(key=lambda item: item["name"].lower())
        return files

    def read_import_file(self, filename):
        filename = self.validate_import_filename(filename)
        path = self.import_dir / filename
        if not path.exists() and self.legacy_import_dir:
            path = self.legacy_import_dir / filename

        if not path.exists() or path.is_symlink() or not path.is_file():
            raise VPNError("Import file not found")

        if path.stat().st_size > 8 * 1024 * 1024:
            raise VPNError("Subscription file is too large")

        try:
            return read_regular(path, 4 * 1024 * 1024).decode("utf-8-sig")
        except UnicodeDecodeError:
            raise VPNError("Subscription file must be UTF-8 text") from None
        except (OSError, ValueError):
            raise VPNError("Subscription file could not be read safely") from None

    async def import_content(self, content, name):
        if len(content.encode("utf-8")) > 4 * 1024 * 1024:
            raise VPNError("Subscription file is too large")
        filename = uuid.uuid4().hex + ".txt"
        target = self.import_dir / filename
        # Unique daemon-owned path. No client-provided filesystem path is used.
        with target.open("x", encoding="utf-8") as stream:
            stream.write(content)
        target.chmod(0o600)
        try:
            return await self.import_subscription(filename, name)
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    async def import_subscription(self, filename, name=None, identifier=None):
        filename = self.validate_import_filename(filename)

        if name is None or not str(name).strip():
            name = Path(filename).stem

        if (
            not isinstance(name, str)
            or not 1 <= len(name.strip()) <= 80
            or any(ord(c) < 32 for c in name)
        ):
            raise VPNError("Subscription name must contain 180 characters")

        editing = identifier is not None

        if identifier:
            self.find_subscription(identifier)
        elif len(self.store.data["subscriptions"]) >= 30:
            raise VPNError("Subscription limit reached (30)")

        identifier = identifier or uuid.uuid4().hex

        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(self.read_import_file, filename),
                5,
            )

            candidate = raw.strip()
            metadata = {}

            # A local import file may contain either the subscription itself
            # or a single HTTP/HTTPS subscription URL.
            if (
                candidate.startswith(("http://", "https://"))
                and "\n" not in candidate
                and "\r" not in candidate
            ):
                validate_url(candidate)

                if self.download_lock.locked():
                    raise VPNError("A subscription download is already running")

                async with self.download_lock:
                    raw, metadata = await asyncio.wait_for(
                        asyncio.to_thread(download, candidate),
                        30,
                    )

            nodes, skipped = await asyncio.wait_for(
                asyncio.to_thread(parse, raw, identifier),
                10,
            )
        except asyncio.TimeoutError:
            raise VPNError(
                "Subscription file download or parsing timed out"
            ) from None

        async with self.lock:
            old = next(
                (
                    s for s in self.store.data["subscriptions"]
                    if s["id"] == identifier
                ),
                None,
            )

            if editing and old is None:
                raise VPNError("Subscription was deleted while importing")

            if old:
                self.store.data["subscriptions"].remove(old)

            record = {
                "id": identifier,
                "name": name.strip(),
                "source_type": "file",
                "source": filename,
                "nodes": nodes,
                "skipped": skipped,
                "metadata": metadata,
                "updated": int(time.time()),
            }

            self.store.data["subscriptions"].append(record)

            if self.store.data["selected"] is None:
                self.store.data["selected"] = nodes[0]["id"]
            elif (
                old
                and any(
                    n["id"] == self.store.data["selected"]
                    for n in old["nodes"]
                )
                and not any(
                    n["id"] == self.store.data["selected"]
                    for n in nodes
                )
            ):
                self.store.data["selected"] = nodes[0]["id"]

            self.store.save()
            self.state["selected"] = self.store.data["selected"]

        return {
            "id": identifier,
            "count": len(nodes),
            "skipped": skipped,
        }

    def find_subscription(self, identifier):
        self.validate_id(identifier)
        result = next((s for s in self.store.data["subscriptions"] if s["id"] == identifier), None)
        if result is None:
            raise VPNError("Subscription not found")
        return result

    @staticmethod
    def validate_id(value):
        if not isinstance(value, str) or len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
            raise VPNError("Invalid identifier")

    def find_node(self, identifier):
        self.validate_id(identifier)
        for s in self.store.data["subscriptions"]:
            for n in s["nodes"]:
                if n["id"] == identifier:
                    return n
        raise VPNError("Server not found; refresh the server list")

    def servers(self, subscription_id):
        return [dict(public_node(n), favorite=n["id"] in self.store.data["favorites"]) for n in self.find_subscription(subscription_id)["nodes"]]

    async def favorite(self, identifier, enabled):
        self.find_node(identifier)
        favorites = set(self.store.data["favorites"])
        if enabled:
            favorites.add(identifier)
        else:
            favorites.discard(identifier)
        self.store.data["favorites"] = sorted(favorites)
        self.store.save()
        return enabled

    def preferences(self):
        return copy.deepcopy(self.store.data["preferences"])

    async def set_preferences(self, values):
        if set(values) - {"channel", "autostart"} or ("channel" in values and values["channel"] not in ("stable", "preview")) or ("autostart" in values and type(values["autostart"]) is not bool):
            raise VPNError("Invalid preferences")
        self.store.data["preferences"].update(values)
        self.store.save()
        return self.preferences()

    def prepare_update(self):
        if self.state["state"] in ("CONNECTING", "RECONNECTING", "DISCONNECTING") or (self.task and not self.task.done()) or self.download_lock.locked() or self.lock.locked():
            raise VPNError("Wait for the active VPN operation to finish")
        self.maintenance = True
        return True

    def resume_operations(self):
        self.maintenance = False
        return True

    async def ping_servers(self, subscription_id):
        subscription = self.find_subscription(subscription_id)
        semaphore = asyncio.Semaphore(16)

        async def probe(node):
            # WireGuard endpoints are UDP; TCP latency would be misleading.
            if node["protocol"] == "wireguard":
                return {
                    "id": node["id"],
                    "status": "unsupported",
                    "latency_ms": None,
                }

            raw = node["raw_config"]
            host = raw.get("server")
            port = raw.get("server_port")

            async with semaphore:
                try:
                    loop = asyncio.get_running_loop()

                    answers = await asyncio.wait_for(
                        loop.getaddrinfo(
                            host,
                            port,
                            type=socket.SOCK_STREAM,
                        ),
                        2.0,
                    )

                    addresses = list(
                        dict.fromkeys(answer[4][0] for answer in answers)
                    )

                    if not addresses:
                        raise OSError()

                    # Subscription data must never be usable to scan localhost/LAN.
                    if any(
                        not ipaddress.ip_address(address).is_global
                        for address in addresses
                    ):
                        return {
                            "id": node["id"],
                            "status": "blocked",
                            "latency_ms": None,
                        }

                    started = time.perf_counter()

                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(addresses[0], port),
                        2.5,
                    )

                    latency = max(
                        1,
                        round((time.perf_counter() - started) * 1000),
                    )

                    writer.close()

                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass

                    return {
                        "id": node["id"],
                        "status": "ok",
                        "latency_ms": latency,
                    }

                except Exception:
                    return {
                        "id": node["id"],
                        "status": "timeout",
                        "latency_ms": None,
                    }

        return await asyncio.gather(
            *(probe(node) for node in subscription["nodes"])
        )

    async def add_or_update(self, url, name, identifier=None):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name) or "://" in name:
            raise VPNError("Subscription name must contain 1–80 characters")
        editing = identifier is not None
        if identifier:
            self.find_subscription(identifier)
        elif len(self.store.data["subscriptions"]) >= 30:
            raise VPNError("Subscription limit reached (30)")
        validate_url(url)
        if self.download_lock.locked():
            raise VPNError("A subscription download is already running")
        identifier = identifier or uuid.uuid4().hex
        async with self.download_lock:
            try:
                # Bounded sockets and body size; no shell, proxy env, or recursive config fetching.
                text, metadata = await asyncio.wait_for(asyncio.to_thread(download, url), 30)
                nodes, skipped = await asyncio.wait_for(asyncio.to_thread(parse, text, identifier), 10)
            except asyncio.TimeoutError:
                raise VPNError("Subscription download or parsing timed out") from None
        async with self.lock:
            old = next((s for s in self.store.data["subscriptions"] if s["id"] == identifier), None)
            if editing and old is None:
                raise VPNError("Subscription was deleted while downloading")
            if old:
                self.store.data["subscriptions"].remove(old)
            record = {
                "id": identifier,
                "name": name.strip(),
                "source_type": "url",
                "source": url,
                "url": url,
                "nodes": nodes,
                "skipped": skipped,
                "metadata": metadata,
                "updated": int(time.time()),
            }
            self.store.data["subscriptions"].append(record)
            if self.store.data["selected"] is None:
                self.store.data["selected"] = nodes[0]["id"]
            elif old and any(n["id"] == self.store.data["selected"] for n in old["nodes"]) and not any(n["id"] == self.store.data["selected"] for n in nodes):
                self.store.data["selected"] = nodes[0]["id"]
            self.store.save()
            self.state["selected"] = self.store.data["selected"]
        return {"id": identifier, "count": len(nodes), "skipped": skipped}

    async def refresh(self, identifier):
        s = self.find_subscription(identifier)

        if s.get("source_type") == "file":
            return await self.import_subscription(
                s["source"],
                s["name"],
                identifier,
            )

        return await self.add_or_update(
            s["url"],
            s["name"],
            identifier,
        )

    async def edit(self, identifier, name, url):
        s = self.find_subscription(identifier)
        if url == "":
            url = s["url"]
        return await self.add_or_update(url, name, identifier)

    async def delete(self, identifier):
        async with self.lock:
            s = self.find_subscription(identifier)
            active = self.state["server"]
            if active and any(n["id"] == active["id"] for n in s["nodes"]) and (self.core.alive or self.state["state"] in ("CONNECTING", "CONNECTED", "DISCONNECTING")):
                raise VPNError("Disconnect before deleting the active subscription")
            self.store.data["subscriptions"].remove(s)
            if any(n["id"] == self.store.data["selected"] for n in s["nodes"]):
                self.store.data["selected"] = None
                self.state["selected"] = None
            self.store.save()
        return True

    async def select(self, identifier):
        self.find_node(identifier)
        self.store.data["selected"] = identifier
        self.state["selected"] = identifier
        self.store.save()
        return self.status()

    async def connect(self, identifier):
        async with self.lock:
            if self.closing or self.maintenance or self.core.alive or (self.task and not self.task.done()) or self.state["state"] == "DISCONNECTING":
                raise VPNError("A VPN operation is already running")
            n = copy.deepcopy(self.find_node(identifier))
            await self.select(identifier)
            self.store.data["desired_connection"] = True
            self.store.save()
            await self.set_state("CONNECTING", server=public_node(n), error=None, public_ip=None, verification=None, since=None)
            self.task = asyncio.create_task(self.run_connection(n))
        return self.status()

    async def run_connection(self, n):
        try:
            await self.core.preflight()
            config = await generate(n["raw_config"])
            before = await public_ip()
            self.state["before_ip"] = before
            await self.core.start(config)
            if not await self.core.route_verified():
                raise VPNError("System traffic is not routed through the VPN interface")
            after = None

            # Routing may be ready slightly before existing sockets/DNS paths
            # fully settle. Retry public-IP verification briefly so we do not
            # report "same IP" just because the first probe was too early.
            for delay in (0, 0.75, 1.25):
                if delay:
                    await asyncio.sleep(delay)

                if not self.core.alive:
                    break

                after = await public_ip()

                if after and (not before or after != before):
                    break

            # The VPN core/TUN must remain alive. Public-IP verification is
            # informational and must never tear down an otherwise working VPN.
            if not self.core.alive or not await self.core.route_verified():
                raise VPNError("VPN tunnel stopped before connection completed")

            if after:
                verification = (
                    "same_ip"
                    if before and before == after
                    else "verified"
                )
            else:
                verification = "unavailable"

            await self.set_state(
                "CONNECTED",
                public_ip=after,
                verification=verification,
                since=int(time.time()),
                error=None,
            )
            self.retry_delay = 2
        except asyncio.CancelledError:
            raise
        except Exception as e:
            error = str(e) if isinstance(e, VPNError) else "VPN core failed to start"
            try:
                await self.core.stop()
            except VPNError:
                error = "VPN cleanup failed; retry Disconnect"
            await self.set_state("ERROR", error=error, public_ip=None)
            self.retry_at = self.boottime() + self.retry_delay
            self.retry_delay = min(self.retry_delay * 2, 60)

    async def disconnect(self, preserve_intent=False):
        async with self.lock:
            if not preserve_intent:
                self.store.data["desired_connection"] = False
                self.store.save()
            await self.set_state("DISCONNECTING", error=None)
            if self.task and not self.task.done():
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
            try:
                await self.core.stop()
            except VPNError as e:
                await self.set_state("ERROR", error=str(e))
                return self.status()
            await self.set_state("DISCONNECTED", server=None, error=None, public_ip=None, verification=None, since=None)
            return self.status()

    @staticmethod
    def boottime():
        return time.clock_gettime(time.CLOCK_BOOTTIME) if hasattr(time, "CLOCK_BOOTTIME") else time.monotonic()

    async def network_fingerprint(self):
        if os.name != "posix":
            return None
        try:
            process = await asyncio.create_subprocess_exec("ip", "-j", "route", "show", "table", "main", "default", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            try:
                data, _ = await asyncio.wait_for(process.communicate(), 3)
            except BaseException:
                process.kill()
                await process.wait()
                raise
            routes = json.loads(data)
            return hashlib.sha256(json.dumps(routes, sort_keys=True).encode()).hexdigest()
        except Exception:
            return None

    async def watch_tick(self, fingerprint, now):
        resumed = now - self.last_tick > 15
        changed = self.network_signature is not None and fingerprint is not None and fingerprint != self.network_signature
        self.last_tick, self.network_signature = now, fingerprint
        if self.maintenance or self.closing or not self.store.data["desired_connection"]:
            return
        if self.task and not self.task.done():
            return
        if self.state["state"] == "CONNECTED" and (not self.core.alive or changed or resumed or not await self.core.route_verified()):
            await self.disconnect(preserve_intent=True)
            if self.state["state"] == "ERROR":
                return
            await self.set_state("RECONNECTING", error=None)
        if self.state["state"] in ("RECONNECTING", "ERROR", "DISCONNECTED") and now >= self.retry_at:
            try:
                await self.connect(self.store.data["selected"])
            except VPNError:
                self.retry_at = now + 10

    async def watch(self):
        try:
            while True:
                await asyncio.sleep(2)
                try:
                    await self.watch_tick(await self.network_fingerprint(), self.boottime())
                except Exception:
                    self.logger.info("Network recovery will retry")
        except asyncio.CancelledError:
            return

    async def check_connection(self):
        if self.state["state"] != "CONNECTED":
            raise VPNError("Connect before verifying the tunnel")
        ip = await public_ip()
        tunnel_ok = self.core.alive and await self.core.route_verified()
        verified = tunnel_ok and bool(ip)
        changed = bool(
            ip
            and self.state.get("before_ip")
            and ip != self.state["before_ip"]
        )

        if self.state["state"] == "CONNECTED":
            self.state["public_ip"] = ip
            self.state["verification"] = (
                "verified"
                if changed
                else "same_ip"
                if ip
                else "unavailable"
            )

        return {
            "verified": verified,
            "tunnel_ok": tunnel_ok,
            "public_ip": ip,
            "changed": changed,
        }

    def diagnostic(self):
        # Deliberately omit server/provider labels, host, URL, keys and raw core output.
        return json.dumps({"plugin": VERSION, "daemon": VERSION, "protocol": PROTOCOL_VERSION, "core": CORE_VERSION, "state": self.state["state"], "core_alive": self.core.alive, "cleanup_pending": (self.runtime / "network-owned.json").exists(), "subscription_count": len(self.store.data["subscriptions"]), "platform": "SteamOS/Linux required"}, indent=2)

    def get_logs(self):
        return (self.logs / "plugin.log").read_text(encoding="utf-8")[-12000:]

    async def close(self, preserve_intent=False):
        self.closing = True
        if self.monitor:
            self.monitor.cancel()
            await asyncio.gather(self.monitor, return_exceptions=True)
        await self.disconnect(preserve_intent=preserve_intent)
        self.log_handler.close()
        self.logger.removeHandler(self.log_handler)
